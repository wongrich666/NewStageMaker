from __future__ import annotations

from workflow_code_skeleton.app.services import script_rating


def test_structural_diagnostics_count_episodes_scenes_and_duplicates() -> None:
    text = """第1集
场景1：办公室｜日｜内
林然：我不签。
林然走出办公室。
第2集
2-1 医院｜夜｜内
林然：我不签。
"""
    result = script_rating._structural_diagnostics(text)

    assert result["episodes"] == 2
    assert result["scenes"] == 2
    assert result["dialogue_lines"] == 2


def test_normalize_dimensions_preserves_fixed_schema_and_weights() -> None:
    result = script_rating._normalize_dimensions([
        {"id": "hooks", "score": 91, "evidence": ["开门。"], "actions": ["保留"]},
        {"id": "mainline", "score": 72},
    ])

    assert len(result) == 8
    assert sum(item["weight"] for item in result) == 100
    assert next(item for item in result if item["id"] == "hooks")["score"] == 91
    assert next(item for item in result if item["id"] == "premise")["score"] == 0


def test_grade_bands_are_stable() -> None:
    assert script_rating._grade(95)[0] == "S+"
    assert script_rating._grade(90)[0] == "S"
    assert script_rating._grade(85)[0] == "A+"
    assert script_rating._grade(80)[0] == "A"
    assert script_rating._grade(70)[0] == "B"
    assert script_rating._grade(69)[0] == "C"


def test_rating_store_is_scoped_by_user(tmp_path) -> None:
    store = script_rating.ScriptRatingStore(tmp_path / "rating.db")
    report = {"score": 82, "grade": "A", "level": "standard"}
    saved = store.save(1, report=report, title="测试", filename="", text="第1集")

    assert store.list(1)[0]["id"] == saved["id"]
    assert store.list(2) == []
    assert store.delete(1, saved["id"]) is True


def test_apply_exact_patches_only_changes_unique_source_text() -> None:
    source = "第1集\n林然走出办公室。\n第2集\n林然到了医院。"
    revised, applied, skipped = script_rating._apply_exact_patches(source, [
        {
            "location": "第1集结尾",
            "original_exact": "林然走出办公室。",
            "replacement": "林然接到医院电话，转身冲出办公室。",
            "reason": "补足去医院的动机",
        },
        {
            "location": "不存在",
            "original_exact": "没有这句话",
            "replacement": "不能应用",
        },
    ])

    assert "接到医院电话" in revised
    assert len(applied) == 1
    assert skipped[0]["skip_reason"] == "原文未命中"


def test_apply_exact_patches_rejects_ambiguous_source_text() -> None:
    source = "林然点头。\n林然点头。"
    revised, applied, skipped = script_rating._apply_exact_patches(source, [
        {"original_exact": "林然点头。", "replacement": "林然摇头。"},
    ])

    assert revised == source
    assert applied == []
    assert skipped[0]["skip_reason"] == "原文未唯一命中"


def test_rating_store_returns_source_text_only_for_detail(tmp_path) -> None:
    store = script_rating.ScriptRatingStore(tmp_path / "rating-text.db")
    saved = store.save(1, report={"level": "standard"}, title="测试", filename="a.txt", text="完整原文")

    assert "script_text" not in store.list(1)[0]
    assert store.get(1, saved["id"])["script_text"] == "完整原文"


def test_normalize_selected_fixes_supports_priority_and_dimension_actions() -> None:
    report = {
        "priority_fixes": [{"title": "补强开头", "action": "首句直接抛出危险"}],
        "dimensions": [{
            "id": "continuity",
            "name": "连续性与逻辑",
            "actions": ["补上前往医院的原因"],
            "evidence": ["上一集公司，下一集医院"],
        }],
    }

    selected = script_rating._normalize_selected_fixes(
        report,
        ["priority:0", "dimension:continuity:0"],
    )

    assert len(selected) == 2
    assert selected[0]["source"] == "优先修改"
    assert selected[1]["source"] == "八维评分"
    assert selected[1]["dimension_id"] == "continuity"
    assert selected[1]["evidence"] == ["上一集公司，下一集医院"]


def test_normalize_selected_fixes_keeps_numeric_indexes_compatible() -> None:
    report = {"priority_fixes": [{"title": "问题一"}, {"title": "问题二"}]}

    selected = script_rating._normalize_selected_fixes(report, [1])

    assert [item["title"] for item in selected] == ["问题二"]
