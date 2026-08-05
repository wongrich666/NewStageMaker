from __future__ import annotations

import time
import zipfile

from workflow_code_skeleton.app.services.distillation_lab import (
    SKILL_MODULE_KEYS,
    SKILL_SCHEMA_VERSION,
    DistillationLabStore,
)


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
                    "modules": {key: f"{key}模块规则" for key in SKILL_MODULE_KEYS},
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
