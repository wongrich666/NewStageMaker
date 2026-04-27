from __future__ import annotations

from pathlib import Path

from ..config import ModelOption
from ..models.inputs import WorkflowInput
from ..models.state import WorkflowState
from .character_stage import run_character_stage
from .dialogue_stage import run_dialogue_stage
from .hook_stage import run_hook_stage
from .runtime_tools import set_runtime_stage, sync_runtime_state
from .scene_stage import run_scene_stage
from .script_stage import run_script_stage
from .worldview_stage import run_worldview_stage
from ..services.node_executor import execute_answer_node, execute_chat_node, execute_text_editor_node
from ..services.workflow_spec import WorkflowSpec
from ..utils.logger import get_logger
from ..workflow_ids import (
    EPISODE_CONSISTENCY_FAILURE_NODE_ID,
    EPISODE_CONSISTENCY_NODE_ID,
    FINAL_ANSWER_NODE_ID,
    FINAL_TEXT_EDITOR_NODE_ID,
)

logger = get_logger("workflow")


def run_full_workflow(
    payload: WorkflowInput,
    *,
    workflow_spec_path: str | Path,
    runtime=None,
    model_option: ModelOption | None = None,
) -> WorkflowState:
    payload.validate()
    spec = WorkflowSpec(workflow_spec_path)
    state = WorkflowState.from_defaults(
        user_input=payload,
        default_variables=spec.get_default_variables(),
    )
    state.runtime = runtime
    state.preferred_provider = model_option.provider if model_option else None
    state.preferred_model = model_option.model if model_option else None
    state.prompt_fixes = spec.get_prompt_fixes()
    sync_runtime_state(state)

    if not validate_inputs_and_episode_plan(state, spec):
        return state

    run_worldview_stage(state, spec)
    run_character_stage(state, spec)
    run_scene_stage(state, spec)
    run_hook_stage(state, spec)
    run_dialogue_stage(state, spec)
    run_script_stage(state, spec)

    set_runtime_stage(state, "finalize", "正在拼接最终输出。", progress_percent=99)
    state.final_output_text = execute_text_editor_node(state, spec, FINAL_TEXT_EDITOR_NODE_ID)
    execute_answer_node(state, spec, FINAL_ANSWER_NODE_ID)
    state.prompt_fixes = spec.get_prompt_fixes()
    sync_runtime_state(state)
    return state


def validate_inputs_and_episode_plan(
    state: WorkflowState,
    spec: WorkflowSpec,
) -> bool:
    logger.info("执行集数一致性检查")
    set_runtime_stage(state, "validation", "正在核对分集计划和总集数。", progress_percent=1)
    result = execute_chat_node(
        state,
        spec,
        EPISODE_CONSISTENCY_NODE_ID,
        expect_json=False,
    ).strip()

    if result.lower() == "true":
        set_runtime_stage(state, "validation", "集数一致性检查通过。", progress_percent=3)
        sync_runtime_state(state)
        return True

    state.halted_message = execute_answer_node(
        state,
        spec,
        EPISODE_CONSISTENCY_FAILURE_NODE_ID,
    )
    state.final_output_text = state.halted_message
    set_runtime_stage(state, "validation", state.halted_message, progress_percent=0)
    sync_runtime_state(state)
    return False
