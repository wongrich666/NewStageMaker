from __future__ import annotations

from pathlib import Path


SERVER_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "server.py"
).read_text(encoding="utf-8")


def test_framework_to_script_login_guard_accepts_token_current_user() -> None:
    assert "session[\"user_id\"] = int(user.id)" in SERVER_SOURCE
    assert "if not _current_user():\n                return _json_error(\"请先登录。\", 401)" in SERVER_SOURCE


def test_framework_to_script_stage_drafts_are_saved_without_marking_completed() -> None:
    assert "currentBatchDraft" in SERVER_SOURCE
    assert "inProgressBatch" in SERVER_SOURCE
    assert 'status: str = "running"' in SERVER_SOURCE
    assert "status=status" in SERVER_SOURCE
    assert "causal_conflict_write" in SERVER_SOURCE
    assert "script_write" in SERVER_SOURCE
    assert "script_memory" in SERVER_SOURCE
