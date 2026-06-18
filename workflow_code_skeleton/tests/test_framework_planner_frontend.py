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
    assert "const done = stageProgressDone(item.stageKey) ? \"done\" : \"\";" in FRONTEND_SOURCE
    assert "const done = state.stage_state[item.stageKey] && state.stage_state[item.stageKey].confirmed ? \"done\" : \"\";" not in FRONTEND_SOURCE


def test_framework_planner_asset_import_uses_single_busy_state() -> None:
    assert "assetImporting: false" in FRONTEND_SOURCE
    assert "导入资产中，请稍后" in FRONTEND_SOURCE
    assert "if (ui.assetImporting) return;" in FRONTEND_SOURCE
    assert "showToast(\"资产导入成功\")" in FRONTEND_SOURCE
    assert "已恢复框架策划资产，可继续生成或进入下游剧本" not in FRONTEND_SOURCE


def test_framework_planner_package_view_defines_locked_and_template_busts_cache() -> None:
    assert "function renderPackageView() {" in FRONTEND_SOURCE
    assert "const locked = Boolean(stage.locked);" in FRONTEND_SOURCE
    assert "framework_planner.js') }}?v=20260617-framework-assets-v3" in FRONTEND_TEMPLATE


def test_framework_planner_knowledge_apply_replaces_old_tag_sections() -> None:
    assert "function stripKnowledgeStagePromptSections(value)" in FRONTEND_SOURCE
    assert "section.startsWith(\"【智慧库标签偏好：\")" in FRONTEND_SOURCE
    assert "function replaceKnowledgeStagePrompts(existingPrompts, knowledgePrompts)" in FRONTEND_SOURCE
    assert "stage_prompts: replaceKnowledgeStagePrompts((state.prompt_preferences || {}).stage_prompts || {}, stagePrompts)" in FRONTEND_SOURCE
    assert "await applyKnowledgeTags();" in FRONTEND_SOURCE


def test_framework_planner_has_one_click_framework_auto_run() -> None:
    assert "一键出框架" in FRONTEND_SOURCE
    assert "function renderAutoFrameworkButton" in FRONTEND_SOURCE
    assert "async function autoRunFramework()" in FRONTEND_SOURCE
    assert "for (const stageKey of STAGE_SEQUENCE)" in FRONTEND_SOURCE
    assert "await runStage(stageKey, { revise: false, autoRunFramework: true });" in FRONTEND_SOURCE
    assert "await commitAutoFrameworkStage(stageKey);" in FRONTEND_SOURCE
    assert "ui.stageErrors[stageKey] = error && error.message" in FRONTEND_SOURCE


def test_framework_planner_auto_run_commits_and_saves_each_stage() -> None:
    assert "async function commitAutoFrameworkStage(stageKey)" in FRONTEND_SOURCE
    assert "markStageCommitted(stageKey);" in FRONTEND_SOURCE
    assert "syncFrameworkAssetState(state, `auto_confirm:${stageKey}`);" in FRONTEND_SOURCE
    assert "await saveFrameworkAsset({ silent: true, skipDirtyCheck: true });" in FRONTEND_SOURCE
    assert "function validateAutoFrameworkStart()" in FRONTEND_SOURCE
