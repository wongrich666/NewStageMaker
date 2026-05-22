from __future__ import annotations

from pathlib import Path


FRONTEND_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "web"
    / "static"
    / "framework_planner.js"
).read_text(encoding="utf-8")


def test_framework_planner_frontend_hides_raw_fastgpt_shell_fields() -> None:
    assert "isHiddenTechnicalKey" in FRONTEND_SOURCE
    assert "responseData" in FRONTEND_SOURCE
    assert "reasoningText" in FRONTEND_SOURCE
    assert "updateVarResult" in FRONTEND_SOURCE
    assert "newVariables" in FRONTEND_SOURCE
    assert "调试 / 完整结构" not in FRONTEND_SOURCE
    assert "<pre>${escapeHtml(prettyJson(data))}</pre>" not in FRONTEND_SOURCE


def test_framework_planner_frontend_uses_stage_preference_payload_fields() -> None:
    assert "stage_preference_prompt" in FRONTEND_SOURCE
    assert "user_stage_preference_prompt" in FRONTEND_SOURCE
    assert "应用到 01-07 阶段偏好" in FRONTEND_SOURCE
    assert "恢复到此版本" in FRONTEND_SOURCE
    assert "cache 和 logs" not in FRONTEND_SOURCE
