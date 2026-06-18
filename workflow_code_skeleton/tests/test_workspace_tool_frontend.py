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
