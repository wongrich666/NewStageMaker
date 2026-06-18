from __future__ import annotations

from pathlib import Path


SERVER_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "server.py"
).read_text(encoding="utf-8")


def test_framework_to_script_stage_lock_is_scoped_by_asset_and_stage() -> None:
    assert "def _try_begin_framework_stage(user_id: int, asset_id: str, stage: str)" in SERVER_SOURCE
    assert 'key = (int(user_id), str(asset_id or "").strip(), str(stage or "").strip())' in SERVER_SOURCE
    assert "if key in framework_stage_runs" in SERVER_SOURCE
    assert "framework_stage_runs.add(key)" in SERVER_SOURCE
