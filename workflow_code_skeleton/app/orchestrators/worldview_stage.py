from __future__ import annotations

from .base_loop import should_retry
from .runtime_tools import set_runtime_stage, sync_runtime_state
from ..prompts.worldview_prompts import (
    CONSTRAINTS_NODE_ID,
    GENERATE_NODE_ID,
    REVIEW_NODE_ID,
    REVISE_NODE_ID,
)
from ..services.json_utils import ensure_dict, normalize_approval_review
from ..services.node_executor import execute_chat_node
from ..services.workflow_spec import WorkflowSpec
from ..utils.logger import get_logger
from ..workflow_ids import WORLDVIEW_MAX_RETRY_VAR, WORLDVIEW_RETRY_VAR, WORLDVIEW_VAR

logger = get_logger("worldview_stage")


def run_worldview_stage(state, spec: WorkflowSpec):
    logger.info("开始执行世界观阶段")
    set_runtime_stage(state, "worldview", "正在提炼世界观审核基准。", progress_percent=5)

    execute_chat_node(state, spec, CONSTRAINTS_NODE_ID, expect_json=True)
    sync_runtime_state(state)

    set_runtime_stage(state, "worldview", "正在生成世界观。", progress_percent=8)
    worldview = execute_chat_node(state, spec, GENERATE_NODE_ID, expect_json=True)
    ensure_dict(worldview)
    state.set_var(WORLDVIEW_VAR, worldview)
    state.set_var(WORLDVIEW_RETRY_VAR, 0)
    sync_runtime_state(state)

    review = normalize_approval_review(
        ensure_dict(execute_chat_node(state, spec, REVIEW_NODE_ID, expect_json=True))
    )
    while not review.approved and should_retry(
        state.get_int_var(WORLDVIEW_RETRY_VAR),
        state.get_int_var(WORLDVIEW_MAX_RETRY_VAR),
    ):
        set_runtime_stage(
            state,
            "worldview",
            f"世界观审核未通过，正在执行第 {state.get_int_var(WORLDVIEW_RETRY_VAR) + 1} 次修订。",
            progress_percent=10,
        )
        worldview = execute_chat_node(state, spec, REVISE_NODE_ID, expect_json=True)
        ensure_dict(worldview)
        state.set_var(WORLDVIEW_VAR, worldview)
        state.set_var(WORLDVIEW_RETRY_VAR, state.get_int_var(WORLDVIEW_RETRY_VAR) + 1)
        sync_runtime_state(state)
        review = normalize_approval_review(
            ensure_dict(execute_chat_node(state, spec, REVIEW_NODE_ID, expect_json=True))
        )

    set_runtime_stage(state, "worldview", "世界观阶段完成。", progress_percent=12)
    sync_runtime_state(state)
    logger.info("世界观阶段结束，修订次数=%s", state.get_int_var(WORLDVIEW_RETRY_VAR))
    return state
