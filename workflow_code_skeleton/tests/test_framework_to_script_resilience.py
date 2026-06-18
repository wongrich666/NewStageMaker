from __future__ import annotations

from pathlib import Path


SERVER_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "server.py"
).read_text(encoding="utf-8")

FRONTEND_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "web"
    / "static"
    / "framework_to_script.js"
).read_text(encoding="utf-8")


def test_framework_to_script_login_guard_accepts_token_current_user() -> None:
    assert "session[\"user_id\"] = int(user.id)" in SERVER_SOURCE
    assert "if not _current_user():\n                return _json_error(\"请先登录。\", 401)" in SERVER_SOURCE


def test_framework_to_script_stage_drafts_are_saved_without_marking_completed() -> None:
    assert "stageDrafts" in SERVER_SOURCE
    assert "_save_framework_to_script_stage_draft" in SERVER_SOURCE
    assert 'status: str = "running"' in SERVER_SOURCE
    assert "draft_only" in SERVER_SOURCE
    assert "completed_set.discard(stage_number)" in SERVER_SOURCE
    assert "causal_conflict_write" in SERVER_SOURCE
    assert "script_write" in SERVER_SOURCE
    assert "script_memory" in SERVER_SOURCE


def test_framework_to_script_batches_are_requested_explicitly() -> None:
    assert "batchStartEpisode: batchStart" in FRONTEND_SOURCE
    assert "batch_start_episode: batchStart" in FRONTEND_SOURCE
    assert "batch_already_completed" in SERVER_SOURCE
    assert "requested_batch_start" in SERVER_SOURCE


def test_framework_asset_import_readiness_is_explained_to_frontend() -> None:
    assert "import_readiness" in SERVER_SOURCE
    assert "framework_package_source" in SERVER_SOURCE
    assert "available_stage_output_keys" in SERVER_SOURCE
    assert "return asset" in SERVER_SOURCE
    assert "框架资产不存在或当前账号无权访问。" in SERVER_SOURCE
    assert "import_readiness" in FRONTEND_SOURCE
    assert "07 最终策划包" in FRONTEND_SOURCE


def test_stage10_output_uses_safe_renderer() -> None:
    assert "function renderStage10Output(stage10)" in FRONTEND_SOURCE
    assert "safeRenderTree(text, \"enrichedEpisodePlanText\")" in FRONTEND_SOURCE
    assert "normalizeEpisodePlanItems(stage10Plan(stage10))" in FRONTEND_SOURCE
    assert "${renderStage10Output(stage10)}" in FRONTEND_SOURCE
