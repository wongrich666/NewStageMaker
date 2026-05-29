from __future__ import annotations

from .base_loop import should_retry
from .runtime_tools import set_runtime_stage, sync_runtime_state
from ..prompts.scene_prompts import (
    EXTRACT_CORE_SCENE_NODE_ID,
    GENERATE_NODE_ID,
    REVIEW_NODE_ID,
    REVISE_NODE_ID,
    SUMMARY_NODE_ID,
)
from ..services.json_utils import ensure_dict, normalize_pass_review
from ..services.node_executor import execute_chat_node
from ..services.workflow_spec import WorkflowSpec
from ..utils.logger import get_logger
from ..workflow_ids import (
    CORE_SCENE_FINAL_VAR,
    CORE_SCENE_INPUT_VAR,
    SCENE_MAX_RETRY_VAR,
    SCENE_RETRY_VAR,
    SCENE_VAR,
)

logger = get_logger("scene_stage")


def run_scene_stage(state, spec: WorkflowSpec):
    logger.info("开始执行场景阶段")
    set_runtime_stage(state, "scene", "正在准备核心场景输入。", progress_percent=24)

    user_core_scene = str(state.get_var(CORE_SCENE_INPUT_VAR, "") or "").strip()
    if user_core_scene:
        state.set_var(CORE_SCENE_FINAL_VAR, user_core_scene)
        state.set_var(SCENE_RETRY_VAR, 0)
        sync_runtime_state(state)
    else:
        generated_core_scene = execute_chat_node(
            state,
            spec,
            EXTRACT_CORE_SCENE_NODE_ID,
            expect_json=False,
        ).strip()
        state.set_var(CORE_SCENE_FINAL_VAR, generated_core_scene)
        state.set_var(SCENE_RETRY_VAR, 0)
        sync_runtime_state(state)

    set_runtime_stage(state, "scene", "正在生成场景设定。", progress_percent=26)
    scene_bundle = execute_chat_node(state, spec, GENERATE_NODE_ID, expect_json=True)
    ensure_dict(scene_bundle)
    state.set_var(SCENE_VAR, scene_bundle)
    sync_runtime_state(state)

    review = normalize_pass_review(
        ensure_dict(execute_chat_node(state, spec, REVIEW_NODE_ID, expect_json=True))
    )
    while not review.approved and should_retry(
        state.get_int_var(SCENE_RETRY_VAR),
        state.get_int_var(SCENE_MAX_RETRY_VAR),
    ):
        set_runtime_stage(
            state,
            "scene",
            f"场景审核未通过，正在执行第 {state.get_int_var(SCENE_RETRY_VAR) + 1} 次修订。",
            progress_percent=29,
        )
        scene_bundle = execute_chat_node(state, spec, REVISE_NODE_ID, expect_json=True)
        ensure_dict(scene_bundle)
        state.set_var(SCENE_VAR, scene_bundle)
        state.set_var(SCENE_RETRY_VAR, state.get_int_var(SCENE_RETRY_VAR) + 1)
        sync_runtime_state(state)
        review = normalize_pass_review(
            ensure_dict(execute_chat_node(state, spec, REVIEW_NODE_ID, expect_json=True))
        )

    set_runtime_stage(state, "scene", "正在整理核心场景摘要。", progress_percent=31)
    core_scene_summary = execute_chat_node(
        state,
        spec,
        SUMMARY_NODE_ID,
        expect_json=False,
    ).strip()
    state.set_var(CORE_SCENE_FINAL_VAR, core_scene_summary)
    sync_runtime_state(state)

    set_runtime_stage(state, "scene", "核心场景阶段完成。", progress_percent=32)
    logger.info("场景阶段结束，修订次数=%s", state.get_int_var(SCENE_RETRY_VAR))
    return state
