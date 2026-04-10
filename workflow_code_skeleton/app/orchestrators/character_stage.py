from __future__ import annotations

from .base_loop import should_retry
from .runtime_tools import set_runtime_stage, sync_runtime_state
from ..prompts.character_prompts import (
    GENERATE_NODE_ID,
    REVIEW_NODE_ID,
    REVISE_NODE_ID,
    SUMMARY_NODE_ID,
)
from ..services.json_utils import ensure_dict, normalize_pass_review
from ..services.node_executor import execute_chat_node
from ..services.workflow_spec import WorkflowSpec
from ..utils.logger import get_logger
from ..workflow_ids import CHARACTER_MAX_RETRY_VAR, CHARACTER_RETRY_VAR, CHARACTER_VAR

logger = get_logger("character_stage")


def run_character_stage(state, spec: WorkflowSpec):
    logger.info("开始执行人设阶段")
    set_runtime_stage(state, "character", "正在生成人物设定。", progress_percent=15)

    character_bundle = execute_chat_node(state, spec, GENERATE_NODE_ID, expect_json=True)
    ensure_dict(character_bundle)
    state.set_var(CHARACTER_VAR, character_bundle)
    state.set_var(CHARACTER_RETRY_VAR, 0)
    sync_runtime_state(state)

    review = normalize_pass_review(
        ensure_dict(execute_chat_node(state, spec, REVIEW_NODE_ID, expect_json=True))
    )
    while not review.approved and should_retry(
        state.get_int_var(CHARACTER_RETRY_VAR),
        state.get_int_var(CHARACTER_MAX_RETRY_VAR),
    ):
        set_runtime_stage(
            state,
            "character",
            f"人物设定审核未通过，正在执行第 {state.get_int_var(CHARACTER_RETRY_VAR) + 1} 次修订。",
            progress_percent=18,
        )
        character_bundle = execute_chat_node(state, spec, REVISE_NODE_ID, expect_json=True)
        ensure_dict(character_bundle)
        state.set_var(CHARACTER_VAR, character_bundle)
        state.set_var(CHARACTER_RETRY_VAR, state.get_int_var(CHARACTER_RETRY_VAR) + 1)
        sync_runtime_state(state)
        review = normalize_pass_review(
            ensure_dict(execute_chat_node(state, spec, REVIEW_NODE_ID, expect_json=True))
        )

    set_runtime_stage(state, "character", "正在整理人物小传摘要。", progress_percent=21)
    character_summary = execute_chat_node(
        state,
        spec,
        SUMMARY_NODE_ID,
        expect_json=False,
    ).strip()
    state.set_var(CHARACTER_VAR, character_summary)
    sync_runtime_state(state)

    set_runtime_stage(state, "character", "人物设定阶段完成。", progress_percent=22)
    logger.info("人设阶段结束，修订次数=%s", state.get_int_var(CHARACTER_RETRY_VAR))
    return state
