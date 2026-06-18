from __future__ import annotations

from pathlib import Path


APP_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "web"
    / "static"
    / "app.js"
).read_text(encoding="utf-8")


def test_character_reskin_running_status_uses_chinese_stage_messages() -> None:
    assert "CHARACTER_RESKIN_RUNNING_MESSAGES" in APP_SOURCE
    assert "正在运行：统计原剧本实际集数" in APP_SOURCE
    assert "正在运行：整理人设" in APP_SOURCE
    assert "正在运行：按批次编写剧本正文" in APP_SOURCE
    assert "startToolProgressTicker(activeToolKey)" in APP_SOURCE
    assert "stopToolProgressTicker()" in APP_SOURCE


def test_tool_payload_collection_is_scoped_to_active_tool_fields() -> None:
    assert "function collectToolPayload(toolKey = state.activeTool)" in APP_SOURCE
    assert "const allowedFields = new Set((tool?.fields || []).map" in APP_SOURCE
    assert "(els.toolForms || document)" in APP_SOURCE
    assert "if (!allowedFields.has(key)) return;" in APP_SOURCE
    assert 'if (toolKey === "hot_review")' in APP_SOURCE


def test_tool_run_freezes_active_tool_before_collecting_payload() -> None:
    assert "const activeToolKey = state.activeTool;\n    const payload = collectToolPayload(activeToolKey);" in APP_SOURCE
    assert "state.toolResults[activeToolKey] = null;" in APP_SOURCE
    assert 'friendlyErrorText(error, fallback, { toolKey: activeToolKey })' in APP_SOURCE
