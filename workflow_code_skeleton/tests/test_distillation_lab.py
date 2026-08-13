from __future__ import annotations

import json
import time
import zipfile

from workflow_code_skeleton.app.services.distillation_lab import (
    EVIDENCE_SCHEMA_VERSION,
    SKILL_MODULE_KEYS,
    SKILL_SCHEMA_VERSION,
    DistillationLabStore,
    _complete_json_with_repair,
    _distillation_sample,
    _narrative_quality_checks,
)


def _quality_modules() -> dict[str, str]:
    return {
        "genre_profile": "题材类型与目标受众决定情绪承诺，并形成差异化表达。",
        "story_architecture": "主线围绕长期目标展开；持续阻力与对手反应逐级升级，人物选择付出代价并造成局势变化，最终在结局兑现。",
        "hook_craft": "开场钩子提出追剧问题，并用最短因果锚帮助观众理解。",
        "character_emotion": "人物角色以目标和欲望行动；压力下的选择暴露恐惧与伤口，并改变关系债、行动和代价。",
        "continuity": "上一集结尾状态与下一集承接事实保持因果连续；下集开场动作兑现未完成动作，换场地点需有交接理由。",
        "dialogue_voice": "对白通过人物目的、关系与潜台词形成不同声音。",
        "adversity_payoff": "冲突阻力通过对手反制递进升级，迫使主角抉择并承担代价，最终兑现处境变化。",
        "anti_patterns": "说明题材受众边界、不适用条件、失效方式与应避免的反模式。",
        "quality_gate": "检查主线、冲突、人物、连续性和差异化。",
    }


from workflow_code_skeleton.app.services.deepseek_agent import DeepSeekJSONError


def test_long_script_sampling_keeps_complete_adjacent_episode_boundaries() -> None:
    source = "\n\n".join(
        f"第{episode}集：《测试》\n开场{episode}\n" + (f"剧情{episode}。" * 500)
        for episode in range(1, 31)
    )

    sample = _distillation_sample(source, max_chars=9000)

    assert sample.startswith("[按完整集与相邻集交接抽样]")
    assert "第1集" in sample and "第2集" in sample
    assert "第29集" in sample and "第30集" in sample
    assert "[中段分布样本]" not in sample


def test_narrative_quality_gate_checks_all_four_story_foundations() -> None:
    checks = _narrative_quality_checks(_quality_modules())

    assert checks == {
        "mainline_clarity": 100,
        "conflict_escalation": 100,
        "character_choice": 100,
        "episode_handoff": 100,
        "differentiation": 100,
    }


def test_distillation_lab_builds_versions_and_keeps_workflow_detached(tmp_path, monkeypatch) -> None:
    store = DistillationLabStore(tmp_path / "distillation")
    project = store.create_project(
        7,
        {
            "name": "狼人逆袭实验",
            "genre": "狼人逆袭",
            "market": "中国大陆",
            "audience": "短剧用户",
        },
    )
    source_text = (
        "第1集：主角在众人误解中承受压力，但一个选择改变了局势。"
        "结尾留下身份疑问。下一集从上一集未完成的行动继续。"
    ) * 12
    source = store.add_source(7, project["id"], "sample.txt", source_text.encode("utf-8"))

    call_prompts: list[str] = []

    def fake_complete_json(prompt: str, **_kwargs):
        call_prompts.append(prompt)
        if "新剧本团队选择加载" in prompt:
            return {
                "structured_output": {
                    "skill_md": "---\nname: 狼人逆袭\ndescription: 生成狼人逆袭题材\n---\n# 规则\n明确适用边界与失效条件。",
                    "modules": _quality_modules(),
                    "verified_rules": [
                        {
                            "rule": "逆风必须改变主角下一步选择",
                            "source_ids": [source["id"]],
                        }
                    ],
                    "hypotheses": [],
                    "source_conflicts": [],
                    "confidence_notes": ["单样本仅作候选"],
                }
            }
        return {
            "structured_output": {
                "summary": "主角在逆风中推进目标",
                "structure_map": {
                    "mainline_engine": "主角的选择触发阻力升级",
                    "hook_mechanics": "先展示异常结果，再补最短原因",
                },
                "genre_signals": ["狼人"],
                "audience_emotions": ["压抑", "反转"],
                "story_architecture": [],
                "character_patterns": [],
                "hook_patterns": [],
                "emotion_curve": [],
                "continuity_patterns": [],
                "dialogue_style": [],
                "effective_patterns": [],
                "failure_patterns": [],
                "surface_elements": {
                    "character_names": [],
                    "relationship_gimmicks": [],
                    "identity_jobs": [],
                    "props_and_evidence": [],
                    "locations_and_world_rules": [],
                    "concrete_incidents": [],
                    "medical_or_biological_elements": [],
                },
            }
        }

    monkeypatch.setattr(
        "workflow_code_skeleton.app.services.distillation_lab.deepseek_agent_client.complete_json",
        fake_complete_json,
    )

    run = store.start_run(7, project["id"])
    deadline = time.time() + 5
    while time.time() < deadline:
        run = store.get_run(7, run["id"])
        if run["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)

    assert run["status"] == "completed", run.get("error")
    detail = store.get_project(7, project["id"])
    assert detail["status"] == "candidate"
    assert detail["active_version_id"] == ""
    assert len(detail["versions"]) == 1
    version = detail["versions"][0]
    assert set(version["modules"]) == set(SKILL_MODULE_KEYS)
    assert version["assets"]["manifest"]["schema_version"] == SKILL_SCHEMA_VERSION
    assert version["score"]["ready_to_publish"] is True
    assert len(call_prompts) == 2

    published = store.publish_version(7, project["id"], version["id"])
    assert published["status"] == "published"
    detail = store.get_project(7, project["id"])
    assert detail["active_version_id"] == version["id"]

    cards = store.list_published_skills(7)
    assert len(cards) == 1
    assert cards[0]["skill_id"] == project["id"]
    assert cards[0]["version_id"] == version["id"]
    assert cards[0]["module_count"] == len(SKILL_MODULE_KEYS)

    with store._connect() as db:
        db.execute(
            "UPDATE skill_versions SET evidence_json=? WHERE id=?",
            ('[{"schema_version":"script-team-evidence/v2","source_id":"legacy"}]', version["id"]),
        )
    assert store.list_published_skills(7) == []
    try:
        store.resolve_runtime_skill(7, project["id"], version["id"])
    except ValueError as exc:
        assert "旧版剧情复刻型蒸馏" in str(exc)
    else:
        raise AssertionError("legacy plot-copying Skill must not enter the new workflow")

    with store._connect() as db:
        db.execute(
            "UPDATE skill_versions SET evidence_json=? WHERE id=?",
            (
                json.dumps(version["evidence"], ensure_ascii=False),
                version["id"],
            ),
        )

    runtime = store.resolve_runtime_skill(7, project["id"], version["id"])
    assert runtime["schema_version"] == SKILL_SCHEMA_VERSION
    assert runtime["version_id"] == version["id"]
    assert set(runtime["modules"]) == set(SKILL_MODULE_KEYS)
    assert runtime["manifest"]["runtime"] == "codebuddy_npc_script_team"

    archive, filename = store.export_version(7, project["id"], version["id"])
    assert filename.endswith("_skill.zip")
    with zipfile.ZipFile(archive) as package:
        assert "SKILL.md" in package.namelist()
        assert "manifest.json" in package.namelist()
        assert "references/hook-craft.md" in package.namelist()
        assert "references/dialogue-voice.md" in package.namelist()

    rerun = store.start_run(7, project["id"])
    deadline = time.time() + 5
    while time.time() < deadline:
        rerun = store.get_run(7, rerun["id"])
        if rerun["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert rerun["status"] == "completed", rerun.get("error")
    assert len(call_prompts) == 3, "cached source evidence should not be charged twice"
    assert all(
        source["status"] == "analyzed"
        for source in store.get_project(7, project["id"])["sources"]
    )

    unpublished = store.unpublish_version(7, project["id"], version["id"])
    assert unpublished["status"] == "candidate"
    assert store.list_published_skills(7) == []
    detail = store.get_project(7, project["id"])
    assert detail["active_version_id"] == ""
    assert detail["status"] == "candidate"


def test_distillation_lab_rejects_unsupported_sources(tmp_path) -> None:
    store = DistillationLabStore(tmp_path / "distillation")
    project = store.create_project(9, {"name": "测试"})
    try:
        store.add_source(9, project["id"], "video.mp4", b"content")
    except ValueError as exc:
        assert "Word、PDF、TXT" in str(exc)
    else:
        raise AssertionError("unsupported source must be rejected")


def test_distillation_json_repair_uses_the_actual_malformed_response(monkeypatch) -> None:
    prompts: list[str] = []

    def fake_complete_json(prompt: str, **_kwargs):
        prompts.append(prompt)
        if len(prompts) == 1:
            raise DeepSeekJSONError(
                "剧本 Agent 没有返回合法JSON。",
                content='{"summary":"已有证据",}',
                finish_reason="stop",
            )
        return {"structured_output": {"summary": "已有证据"}}

    monkeypatch.setattr(
        "workflow_code_skeleton.app.services.distillation_lab.deepseek_agent_client.complete_json",
        fake_complete_json,
    )

    result = _complete_json_with_repair(
        "analyse source",
        system_prompt="json only",
        max_tokens=100,
        timeout_seconds=30,
    )

    assert result == {"summary": "已有证据"}
    assert '待修复内容：\n{"summary":"已有证据",}' in prompts[1]
    assert "analyse source" not in prompts[1]


def test_distillation_json_repair_compactly_regenerates_after_repair_failure(monkeypatch) -> None:
    prompts: list[str] = []

    def fake_complete_json(prompt: str, **_kwargs):
        prompts.append(prompt)
        if len(prompts) == 1:
            raise DeepSeekJSONError(
                "剧本 Agent 没有返回合法JSON。",
                content='{"summary":"未闭合"',
                finish_reason="stop",
            )
        if len(prompts) == 2:
            raise DeepSeekJSONError(
                "剧本 Agent 没有返回合法JSON。",
                content='{"summary":"仍未闭合"',
                finish_reason="stop",
            )
        return {"structured_output": {"summary": "紧凑证据"}}

    monkeypatch.setattr(
        "workflow_code_skeleton.app.services.distillation_lab.deepseek_agent_client.complete_json",
        fake_complete_json,
    )

    result = _complete_json_with_repair(
        "analyse source",
        system_prompt="json only",
        max_tokens=100,
        timeout_seconds=30,
    )

    assert result == {"summary": "紧凑证据"}
    assert "待修复内容" in prompts[1]
    assert "紧凑重生成" in prompts[2]
    assert "analyse source" in prompts[2]


def test_distillation_skips_one_failed_source_and_keeps_other_evidence(
    tmp_path, monkeypatch
) -> None:
    store = DistillationLabStore(tmp_path / "distillation")
    project = store.create_project(7, {"name": "容错蒸馏"})
    repeated = "主角作出选择，阻力随之升级，下一场承接未完成行动。" * 8
    bad = store.add_source(7, project["id"], "bad.txt", repeated.encode("utf-8"))
    good = store.add_source(7, project["id"], "good.txt", repeated.encode("utf-8"))
    corpus = store._parse_sources(7, project["id"])

    def fake_extract(prompt: str, **_kwargs):
        if "bad.txt" in prompt:
            raise DeepSeekJSONError("剧本 Agent 没有返回合法JSON。")
        return {
            "summary": "可迁移结构",
            "structure_map": {"mainline_engine": "选择推动阻力升级"},
            "surface_elements": {
                key: []
                for key in (
                    "character_names",
                    "relationship_gimmicks",
                    "identity_jobs",
                    "props_and_evidence",
                    "locations_and_world_rules",
                    "concrete_incidents",
                    "medical_or_biological_elements",
                )
            },
        }

    monkeypatch.setattr(
        "workflow_code_skeleton.app.services.distillation_lab._complete_json_with_repair",
        fake_extract,
    )

    evidence = store._extract_evidence(7, project["id"], corpus)

    assert len(evidence) == 1
    assert evidence[0]["source_id"] == good["id"]
    with store._connect() as db:
        bad_row = db.execute("SELECT status,error FROM sources WHERE id=?", (bad["id"],)).fetchone()
        good_row = db.execute("SELECT status,error FROM sources WHERE id=?", (good["id"],)).fetchone()
    assert bad_row["status"] == "failed"
    assert "合法JSON" in bad_row["error"]
    assert good_row["status"] == "analyzed"


def test_quality_gate_rejects_skill_that_copies_sample_surface_elements(tmp_path) -> None:
    store = DistillationLabStore(tmp_path / "distillation")
    modules = {key: f"{key}：按叙事功能组织冲突。" for key in SKILL_MODULE_KEYS}
    modules["hook_craft"] = "开篇必须让女主拿着验孕棒撞见自己的替身。"
    evidence = [
        {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "source_id": "source-a",
            "surface_elements": {
                "character_names": [],
                "relationship_gimmicks": ["替身"],
                "identity_jobs": [],
                "props_and_evidence": ["验孕棒"],
                "locations_and_world_rules": [],
                "concrete_incidents": [],
                "medical_or_biological_elements": [],
            },
        },
        {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "source_id": "source-b",
            "surface_elements": {
                "character_names": [],
                "relationship_gimmicks": ["替身"],
                "identity_jobs": [],
                "props_and_evidence": ["验孕棒"],
                "locations_and_world_rules": [],
                "concrete_incidents": [],
                "medical_or_biological_elements": [],
            },
        },
    ]
    version = {
        "skill_md": "---\nname: structure-only\n---\n# 边界与失效条件",
        "modules": modules,
        "assets": {
            "manifest": {"schema_version": SKILL_SCHEMA_VERSION},
            "verified_rules": [
                {
                    "rule": "强钩子先制造关系认知破位",
                    "source_ids": ["source-a", "source-b"],
                }
            ],
        },
    }

    score = store._evaluate(version, evidence)

    assert score["checks"]["structural_purity"] == 0
    assert score["surface_leaks"]["hook_craft"] == ["替身", "验孕棒"]
    assert score["ready_to_publish"] is False


def test_narrative_phrase_scores_are_quality_warnings_not_integrity_blockers(tmp_path) -> None:
    store = DistillationLabStore(tmp_path / "distillation")
    modules = {key: f"{key}：按样本提炼的叙事功能执行。" for key in SKILL_MODULE_KEYS}
    evidence = [
        {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "source_id": "source-a",
            "structure_map": {"engine": "选择推动后果"},
            "surface_elements": {
                "character_names": [],
                "relationship_gimmicks": [],
                "identity_jobs": [],
                "props_and_evidence": [],
                "locations_and_world_rules": [],
                "concrete_incidents": [],
                "medical_or_biological_elements": [],
            },
        }
    ]
    version = {
        "skill_md": "---\nname: structure-only\n---\n# 边界与失效条件",
        "modules": modules,
        "assets": {
            "manifest": {"schema_version": SKILL_SCHEMA_VERSION},
            "verified_rules": [{"rule": "结构规律", "source_ids": ["source-a"]}],
        },
    }

    score = store._evaluate(version, evidence)

    assert score["narrative_quality_ready"] is False
    assert score["quality_warnings"]
    assert score["blocking_reasons"] == []
    assert score["ready_to_publish"] is True


def test_project_detail_recomputes_stale_cached_integrity_score(tmp_path) -> None:
    store = DistillationLabStore(tmp_path / "distillation")
    project = store.create_project(7, {"name": "缓存评测测试"})
    now = "2026-08-12T10:00:00+08:00"
    with store._connect() as db:
        db.execute(
            """INSERT INTO skill_versions
            (id,project_id,user_id,version,status,skill_md,stage_prompts_json,
             assets_json,evidence_json,score_json,created_at,updated_at,published_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "version-stale",
                project["id"],
                7,
                "v1.0",
                "candidate",
                "",
                "{}",
                "{}",
                "[]",
                json.dumps({"total": 100, "ready_to_publish": True}),
                now,
                now,
                "",
            ),
        )

    version = store.get_project(7, project["id"])["versions"][0]

    assert version["score"]["ready_to_publish"] is False
    assert version["score"]["blocking_reasons"]


def test_ai_quality_optimization_creates_new_version_and_preserves_source(
    tmp_path, monkeypatch
) -> None:
    store = DistillationLabStore(tmp_path / "distillation")
    project = store.create_project(7, {"name": "AI优化测试", "genre": "情感"})
    modules = {key: f"原始-{key}" for key in SKILL_MODULE_KEYS}
    evidence = [
        {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "source_id": "source-a",
            "structure_map": {"engine": "选择推动后果"},
            "surface_elements": {key: [] for key in (
                "character_names", "relationship_gimmicks", "identity_jobs",
                "props_and_evidence", "locations_and_world_rules", "concrete_incidents",
                "medical_or_biological_elements",
            )},
        }
    ]
    assets = {
        "manifest": {
            "schema_version": SKILL_SCHEMA_VERSION,
            "version": "v1.0",
        },
        "verified_rules": [{"rule": "结构规律", "source_ids": ["source-a"]}],
    }
    now = "2026-08-12T10:00:00+08:00"
    with store._connect() as db:
        db.execute(
            """INSERT INTO skill_versions
            (id,project_id,user_id,version,status,skill_md,stage_prompts_json,
             assets_json,evidence_json,score_json,created_at,updated_at,published_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "version-source", project["id"], 7, "v1.0", "candidate",
                "---\nname: ai-test\n---\n# 边界与失效条件", json.dumps(modules),
                json.dumps(assets), json.dumps(evidence), "{}", now, now, "",
            ),
        )

    def fake_optimize(_prompt: str, **_kwargs):
        return {
            "modules": {
                "story_architecture": _quality_modules()["story_architecture"],
                "adversity_payoff": _quality_modules()["adversity_payoff"],
                "character_emotion": _quality_modules()["character_emotion"],
                "continuity": _quality_modules()["continuity"],
                "genre_profile": _quality_modules()["genre_profile"],
                "anti_patterns": _quality_modules()["anti_patterns"],
            }
        }

    monkeypatch.setattr(
        "workflow_code_skeleton.app.services.distillation_lab._complete_json_with_repair",
        fake_optimize,
    )

    optimized = store.optimize_version_with_ai(7, project["id"], "version-source")
    source = store.get_version(7, project["id"], "version-source")

    assert optimized["id"] != source["id"]
    assert optimized["version"] == "v1.1"
    assert source["modules"] == modules
    assert optimized["modules"]["hook_craft"] == modules["hook_craft"]
    assert optimized["modules"]["story_architecture"] != modules["story_architecture"]
    assert optimized["evidence"] == source["evidence"]
    assert optimized["assets"]["ai_optimization"]["source_version_id"] == source["id"]
    assert optimized["score"]["quality_warnings"] == []


def test_delete_single_version_preserves_other_versions_and_unlinks_published_skill(tmp_path) -> None:
    store = DistillationLabStore(tmp_path / "distillation")
    project = store.create_project(7, {"name": "版本删除测试"})
    now = "2026-08-12T10:00:00+08:00"
    rows = [
        ("version-live", "v1.0", "published"),
        ("version-candidate", "v1.1", "candidate"),
    ]
    with store._connect() as db:
        for version_id, number, status in rows:
            db.execute(
                """INSERT INTO skill_versions
                (id,project_id,user_id,version,status,skill_md,stage_prompts_json,
                 assets_json,evidence_json,score_json,created_at,updated_at,published_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    version_id, project["id"], 7, number, status, "", "{}", "{}", "[]",
                    "{}", now, now, now if status == "published" else "",
                ),
            )
        db.execute(
            "UPDATE projects SET status='published',active_version_id=? WHERE id=?",
            ("version-live", project["id"]),
        )

    store.delete_version(7, project["id"], "version-live")
    detail = store.get_project(7, project["id"])

    assert [item["id"] for item in detail["versions"]] == ["version-candidate"]
    assert detail["active_version_id"] == ""
    assert detail["status"] == "candidate"

    store.delete_version(7, project["id"], "version-candidate")
    assert store.get_project(7, project["id"])["versions"] == []
