from __future__ import annotations

from .base_loop import should_retry
from .runtime_tools import set_runtime_stage, sync_runtime_state
from ..prompts.dialogue_prompts import GENERATE_NODE_ID, REVIEW_NODE_ID, REVISE_NODE_ID
from ..services.json_utils import ensure_dict, normalize_pass_review
from ..services.node_executor import execute_chat_node, execute_text_editor_node
from ..services.workflow_spec import WorkflowSpec
from ..utils.episode import BatchWindow
from ..utils.logger import get_logger
from ..workflow_ids import (
    DIALOGUE_CURRENT_VAR,
    DIALOGUE_FINAL_VAR,
    DIALOGUE_MAX_RETRY_VAR,
    DIALOGUE_RETRY_VAR,
    DIALOGUE_START_VAR,
    TOTAL_EPISODES_VAR,
)

APPEND_DIALOGUES_NODE_ID = "uCjz4iWKDGDtrorY"

logger = get_logger("dialogue_stage")


def run_dialogue_stage(state, spec: WorkflowSpec):
    logger.info("开始执行角色对话批处理阶段")

    state.set_var(DIALOGUE_START_VAR, 1)
    state.set_var(DIALOGUE_RETRY_VAR, 0)
    sync_runtime_state(state)

    total_episodes = state.get_int_var(TOTAL_EPISODES_VAR)
    total_batches = max(1, (total_episodes + 4) // 5)
    completed_batches = 0
    while state.get_int_var(DIALOGUE_START_VAR) <= total_episodes:
        batch = BatchWindow.from_start(
            state.get_int_var(DIALOGUE_START_VAR),
            total_episodes,
        )
        set_runtime_stage(
            state,
            "dialogue",
            f"正在生成第 {batch.label} 集的角色对话。",
            batch_label=batch.label,
            progress_percent=50 + int((completed_batches / total_batches) * 18),
        )
        logger.info("生成对话批次 %s", batch.label)

        dialogue_bundle = execute_chat_node(
            state,
            spec,
            GENERATE_NODE_ID,
            expect_json=True,
        )
        ensure_dict(dialogue_bundle)
        state.set_var(DIALOGUE_CURRENT_VAR, dialogue_bundle)
        state.set_var(DIALOGUE_START_VAR, state.get_int_var(DIALOGUE_START_VAR) + 5)
        sync_runtime_state(state)

        review = normalize_pass_review(
            ensure_dict(execute_chat_node(state, spec, REVIEW_NODE_ID, expect_json=True))
        )
        while not review.approved and should_retry(
            state.get_int_var(DIALOGUE_RETRY_VAR),
            state.get_int_var(DIALOGUE_MAX_RETRY_VAR),
        ):
            state.set_var(DIALOGUE_START_VAR, state.get_int_var(DIALOGUE_START_VAR) - 5)
            set_runtime_stage(
                state,
                "dialogue",
                f"第 {batch.label} 集对话审核未通过，正在执行第 {state.get_int_var(DIALOGUE_RETRY_VAR) + 1} 次修订。",
                batch_label=batch.label,
                progress_percent=50 + int((completed_batches / total_batches) * 18),
            )
            dialogue_bundle = execute_chat_node(
                state,
                spec,
                REVISE_NODE_ID,
                expect_json=True,
            )
            ensure_dict(dialogue_bundle)
            state.set_var(DIALOGUE_CURRENT_VAR, dialogue_bundle)
            state.set_var(
                DIALOGUE_RETRY_VAR,
                state.get_int_var(DIALOGUE_RETRY_VAR) + 1,
            )
            state.set_var(DIALOGUE_START_VAR, state.get_int_var(DIALOGUE_START_VAR) + 5)
            sync_runtime_state(state)
            review = normalize_pass_review(
                ensure_dict(execute_chat_node(state, spec, REVIEW_NODE_ID, expect_json=True))
            )

        state.set_var(
            DIALOGUE_FINAL_VAR,
            execute_text_editor_node(state, spec, APPEND_DIALOGUES_NODE_ID),
        )
        state.set_var(DIALOGUE_RETRY_VAR, 0)
        completed_batches += 1
        sync_runtime_state(state)

    set_runtime_stage(state, "dialogue", "角色对话阶段完成。", progress_percent=68)
    return state
