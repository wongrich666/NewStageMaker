from __future__ import annotations

from pathlib import Path


FRONTEND_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "web"
    / "static"
    / "framework_planner.js"
).read_text(encoding="utf-8")

FRONTEND_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "web"
    / "templates"
    / "framework_planner.html"
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


def test_framework_planner_progress_tick_uses_downstream_progress() -> None:
    assert "function stageProgressDone(stageKey)" in FRONTEND_SOURCE
    assert "STAGE_SEQUENCE.slice(index + 1).some" in FRONTEND_SOURCE
    assert "downstream.status === \"running\"" in FRONTEND_SOURCE
    assert "const done = stageProgressDone(item.stageKey) ? \"done\" : \"\";" in FRONTEND_SOURCE
    assert "const done = state.stage_state[item.stageKey] && state.stage_state[item.stageKey].confirmed ? \"done\" : \"\";" not in FRONTEND_SOURCE


def test_framework_planner_asset_import_uses_single_busy_state() -> None:
    assert "assetImporting: false" in FRONTEND_SOURCE
    assert "导入资产中，请稍后" in FRONTEND_SOURCE
    assert "if (ui.assetImporting) return;" in FRONTEND_SOURCE
    assert "showToast(\"资产导入成功\")" in FRONTEND_SOURCE
    assert "已恢复框架策划资产，可继续生成或进入下游剧本" not in FRONTEND_SOURCE


def test_framework_planner_refresh_keeps_local_state_unless_forced_fresh() -> None:
    assert 'params.get("resume") !== "1"' not in FRONTEND_SOURCE
    assert 'params.get("fresh") || params.get("reset")' in FRONTEND_SOURCE
    assert "persistLoadedState(normalized)" in FRONTEND_SOURCE


def test_framework_planner_clears_stale_running_state_on_restore() -> None:
    assert "function clearStaleRunningStages(targetState)" in FRONTEND_SOURCE
    assert 'stage.status !== "running" || isStageLoading(stageKey)' in FRONTEND_SOURCE
    assert 'targetState.asset_state.status = "in_progress"' in FRONTEND_SOURCE


def test_framework_planner_asset_import_uses_framework_asset_endpoints_and_silent_history() -> None:
    assert 'requestJson("/api/framework-assets")' in FRONTEND_SOURCE
    assert "requestJson(`/api/framework-assets/${projectId}`)" in FRONTEND_SOURCE
    assert 'loadStageHistory(stageKeyForView(state.current_view || "basic"), { silent: true })' in FRONTEND_SOURCE


def test_framework_planner_new_project_clears_knowledge_residue() -> None:
    assert "loadKnowledgePreferences().catch" not in FRONTEND_SOURCE
    assert "state.prompt_preferences = normalizePromptPreferences({});" in FRONTEND_SOURCE
    assert "ui.knowledge.selectedIds = [];" in FRONTEND_SOURCE
    assert "storageRemove(PREFERENCE_STORAGE_KEY);" in FRONTEND_SOURCE


def test_framework_planner_package_view_defines_locked_and_template_busts_cache() -> None:
    assert "function renderPackageView() {" in FRONTEND_SOURCE
    assert "const locked = Boolean(stage.locked);" in FRONTEND_SOURCE
    assert "framework_planner.js') }}?v=20260604-framework-planner-flow-fixes" in FRONTEND_TEMPLATE
