from __future__ import annotations

from .base_loop import should_retry
from .runtime_tools import set_runtime_stage, sync_runtime_state
from ..prompts.script_prompts import GENERATE_NODE_ID, MEMORY_NODE_ID, REVIEW_NODE_ID, REVISE_NODE_ID
from ..services.json_utils import ensure_dict, normalize_pass_review
from ..services.node_executor import execute_chat_node, execute_text_editor_node
from ..services.workflow_spec import WorkflowSpec
from ..utils.episode import BatchWindow
from ..utils.logger import get_logger
from ..workflow_ids import (
    MEMORY_VAR,
    SCRIPT_CURRENT_VAR,
    SCRIPT_FINAL_VAR,
    SCRIPT_MAX_RETRY_VAR,
    SCRIPT_RETRY_VAR,
    SCRIPT_START_VAR,
    TOTAL_EPISODES_VAR,
)

APPEND_SCRIPT_NODE_ID = "m20HcueENlYhZJy4"
APPEND_MEMORY_NODE_ID = "r2KI2sJgoEqfXBen"

logger = get_logger("script_stage")


def run_script_stage(state, spec: WorkflowSpec):
    logger.info("开始执行剧本正文批处理阶段")

    state.set_var(SCRIPT_START_VAR, 1)
    state.set_var(SCRIPT_RETRY_VAR, 0)
    sync_runtime_state(state)

    total_episodes = state.get_int_var(TOTAL_EPISODES_VAR)
    total_batches = max(1, (total_episodes + 4) // 5)
    completed_batches = 0
    while state.get_int_var(SCRIPT_START_VAR) <= total_episodes:
        batch = BatchWindow.from_start(
            state.get_int_var(SCRIPT_START_VAR),
            total_episodes,
        )
        set_runtime_stage(
            state,
            "script",
            f"正在生成第 {batch.label} 集的剧本正文。",
            batch_label=batch.label,
            progress_percent=70 + int((completed_batches / total_batches) * 28),
            generated_episodes=min(total_episodes, completed_batches * 5),
        )
        logger.info("生成正文批次 %s", batch.label)

        script_text = execute_chat_node(state, spec, GENERATE_NODE_ID, expect_json=False)
        state.set_var(SCRIPT_CURRENT_VAR, script_text.strip())
        state.set_var(SCRIPT_START_VAR, state.get_int_var(SCRIPT_START_VAR) + 5)
        sync_runtime_state(state)

        review = normalize_pass_review(
            ensure_dict(execute_chat_node(state, spec, REVIEW_NODE_ID, expect_json=True))
        )
        while not review.approved and should_retry(
            state.get_int_var(SCRIPT_RETRY_VAR),
            state.get_int_var(SCRIPT_MAX_RETRY_VAR),
        ):
            state.set_var(SCRIPT_START_VAR, state.get_int_var(SCRIPT_START_VAR) - 5)
            set_runtime_stage(
                state,
                "script",
                f"第 {batch.label} 集正文审核未通过，正在执行第 {state.get_int_var(SCRIPT_RETRY_VAR) + 1} 次修订。",
                batch_label=batch.label,
                progress_percent=70 + int((completed_batches / total_batches) * 28),
                generated_episodes=min(total_episodes, completed_batches * 5),
            )
            script_text = execute_chat_node(state, spec, REVISE_NODE_ID, expect_json=False)
            state.set_var(SCRIPT_CURRENT_VAR, script_text.strip())
            state.set_var(SCRIPT_RETRY_VAR, state.get_int_var(SCRIPT_RETRY_VAR) + 1)
            state.set_var(SCRIPT_START_VAR, state.get_int_var(SCRIPT_START_VAR) + 5)
            sync_runtime_state(state)
            review = normalize_pass_review(
                ensure_dict(execute_chat_node(state, spec, REVIEW_NODE_ID, expect_json=True))
            )

        state.set_var(
            SCRIPT_FINAL_VAR,
            execute_text_editor_node(state, spec, APPEND_SCRIPT_NODE_ID),
        )
        state.set_var(SCRIPT_RETRY_VAR, 0)
        completed_batches += 1
        sync_runtime_state(state)

        set_runtime_stage(
            state,
            "script",
            f"正在整理第 {batch.label} 集的上下文记忆。",
            batch_label=batch.label,
            progress_percent=70 + int((completed_batches / total_batches) * 28),
            generated_episodes=min(total_episodes, completed_batches * 5),
        )
        memory_packet = execute_chat_node(state, spec, MEMORY_NODE_ID, expect_json=True)
        state.set_output(MEMORY_NODE_ID, "answerText", memory_packet)
        state.set_var(MEMORY_VAR, execute_text_editor_node(state, spec, APPEND_MEMORY_NODE_ID))
        sync_runtime_state(state)

    set_runtime_stage(
        state,
        "script",
        "剧本正文阶段完成。",
        progress_percent=98,
        generated_episodes=total_episodes,
    )
    return state
