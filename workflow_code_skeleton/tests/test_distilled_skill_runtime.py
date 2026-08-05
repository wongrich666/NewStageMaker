from __future__ import annotations

from dataclasses import replace

from workflow_code_skeleton.app.services.codebuddy_npc import CodeBuddyNpcConfig, CodeBuddyNpcJobStore, public_job
from workflow_code_skeleton.app.services.codebuddy_npc_stage_runner import _distilled_skill_text


def _snapshot() -> dict:
    return {
        "schema_version": "script-team-skill/v1",
        "skill_id": "dst-test",
        "name": "现实情感",
        "version_id": "ver-test",
        "version": "v1.0",
        "manifest": {
            "modules": [
                {"key": "genre_profile", "stages": ["showrunner"]},
                {"key": "dialogue_voice", "stages": ["script_writer"]},
            ]
        },
        "modules": {
            "genre_profile": "题材规则",
            "dialogue_voice": "对白规则",
        },
    }


def test_job_freezes_skill_snapshot_but_public_payload_hides_prompt_body(tmp_path) -> None:
    config = replace(CodeBuddyNpcConfig.from_env(), job_dir=tmp_path)
    store = CodeBuddyNpcJobStore(config)
    job = store.create(
        user_id=9,
        request_payload={
            "project_title": "关联测试",
            "source_text": "写一个现实情感故事。",
            "distilled_skill_snapshot": _snapshot(),
        },
    )

    assert job["skill_snapshot"]["modules"]["dialogue_voice"] == "对白规则"
    assert job["request"]["distilled_skill"]["version_id"] == "ver-test"
    assert "skill_snapshot" not in public_job(job)


def test_local_fallback_routes_the_same_distilled_modules() -> None:
    job = {"skill_snapshot": _snapshot()}

    writer = _distilled_skill_text("script_writer", job)
    showrunner = _distilled_skill_text("showrunner", job)

    assert "对白规则" in writer
    assert "题材规则" not in writer
    assert "题材规则" in showrunner
    assert "对白规则" not in showrunner
