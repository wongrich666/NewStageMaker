from __future__ import annotations

import pytest

from workflow_code_skeleton.app.services.compliance_review import (
    ComplianceReviewStore,
    catalog,
    review_script,
)


def test_catalog_covers_all_provincial_regions_and_platforms() -> None:
    data = catalog()

    assert len(data["regions"]) == 33
    assert {item["id"] for item in data["platforms"]} >= {
        "douyin",
        "hongguo",
        "bilibili",
    }
    assert any(source["id"] == "nrta-2025-tiered-review" for source in data["sources"])
    assert data["source_coverage"]["automatic_sync"] is False
    assert data["source_coverage"]["province_fulltext_complete"] is False


def test_standard_review_reports_explicit_high_risk_context() -> None:
    result = review_script(
        {
            "text": "第1集\n反派：这是一套完美犯罪，下面教你销毁证据。",
            "mode": "standard",
            "region": "北京",
            "platforms": ["douyin"],
        }
    )

    assert result["status"] == "revision_required"
    assert any(item["category"] == "违法犯罪与危险模仿" for item in result["findings"])
    assert result["metrics"]["episodes"] == 1


def test_advanced_review_adds_checklist_and_soft_rules() -> None:
    result = review_script(
        {
            "text": "顾问：这个项目保证收益，稳赚不赔。",
            "mode": "advanced",
            "platforms": ["bilibili"],
        }
    )

    assert result["checklist"]
    assert any(item["category"] == "医疗金融等专业表达" for item in result["findings"])


def test_standard_review_keeps_national_baseline_but_skips_advanced_soft_rule() -> None:
    result = review_script(
        {
            "text": "顾问：这个项目保证收益，稳赚不赔。\n【外语无字幕】",
            "mode": "standard",
            "platforms": ["bilibili"],
        }
    )

    categories = {item["category"] for item in result["findings"]}
    assert "医疗金融等专业表达" in categories
    assert "语言文字与字幕" not in categories


def test_standard_review_recommends_advanced_for_special_subjects() -> None:
    result = review_script(
        {
            "text": "本剧根据真实案件改编，主角是一名未成年学生。",
            "mode": "standard",
        }
    )

    assert result["advanced_mode"]["recommended"] is True
    assert "司法公安或真实案件" in result["advanced_mode"]["reasons"]


def test_review_rejects_empty_or_invalid_input() -> None:
    with pytest.raises(ValueError, match="请粘贴剧本"):
        review_script({"text": ""})
    with pytest.raises(ValueError, match="检测模式"):
        review_script({"text": "正文", "mode": "strictest"})


def test_non_ai_review_detects_borderline_sexualized_camera_language() -> None:
    result = review_script(
        {
            "text": (
                "第1集\n镜头从她的大腿缓慢上移。她故意拉低领口，贴着老板耳边喘息，"
                "房门关上，画面反复特写她裸露的身体。"
            ),
            "mode": "standard",
            "use_ai": False,
        }
    )

    assert any(item["category"] == "淫秽色情与低俗" for item in result["findings"])
    assert result["risk_score"] > 0


@pytest.mark.parametrize(
    "text",
    [
        "制片人：陪我一晚，这个角色就是你的。",
        "镜头对准她走光的裙底反复特写，旁人举起手机偷拍。",
        "他拿私密照威胁她，不答应就群发。",
    ],
)
def test_non_ai_review_detects_common_borderline_euphemisms(text: str) -> None:
    result = review_script({"text": f"第1集\n{text}", "use_ai": False})

    assert any(item["category"] == "淫秽色情与低俗" for item in result["findings"])


def test_no_match_means_zero_known_risk_not_full_compliance_score() -> None:
    result = review_script({"text": "第1集\n小林走进办公室，放下文件。"})

    assert result["risk_score"] == 0
    assert result["status"] == "not_detected"


def test_review_history_persists_and_is_scoped_by_user(tmp_path) -> None:
    store = ComplianceReviewStore(tmp_path / "compliance.db")
    report = review_script({"text": "第1集\n反派教你销毁证据。"})

    saved = store.save(
        7,
        report=report,
        title="测试剧本",
        filename="测试剧本.docx",
        text="第1集\n反派教你销毁证据。",
    )

    assert store.list(7)[0]["id"] == saved["id"]
    assert store.get(7, saved["id"])["report"]["findings"]
    assert store.list(8) == []
    assert store.delete(7, saved["id"]) is True
    assert store.list(7) == []
