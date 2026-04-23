from __future__ import annotations

import re

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

APPEND_MEMORY_NODE_ID = "r2KI2sJgoEqfXBen"
LOCAL_SCRIPT_EPISODE_CACHE_VAR = "_local_script_episode_cache"

logger = get_logger("script_stage")


def run_script_stage(state, spec: WorkflowSpec):
    logger.info("开始执行剧本正文批处理阶段")

    state.set_var(SCRIPT_START_VAR, 1)
    state.set_var(SCRIPT_RETRY_VAR, 0)
    state.set_var(SCRIPT_FINAL_VAR, "")
    state.set_var(LOCAL_SCRIPT_EPISODE_CACHE_VAR, {})
    sync_runtime_state(state)

    total_episodes = state.get_int_var(TOTAL_EPISODES_VAR)
    total_batches = max(1, (total_episodes + 4) // 5)

    while state.get_int_var(SCRIPT_START_VAR) <= total_episodes:
        current_start = state.get_int_var(SCRIPT_START_VAR)
        batch = BatchWindow.from_start(current_start, total_episodes)
        generated_episodes = max(0, current_start - 1)
        progress_percent = 70 + int((generated_episodes / max(1, total_episodes)) * 28)

        set_runtime_stage(
            state,
            "script",
            f"正在生成第 {batch.label} 集的剧本正文。",
            batch_label=batch.label,
            progress_percent=progress_percent,
            generated_episodes=generated_episodes,
        )
        logger.info("生成正文批次 %s", batch.label)

        script_text = execute_chat_node(state, spec, GENERATE_NODE_ID, expect_json=False).strip()
        state.set_var(SCRIPT_CURRENT_VAR, script_text)
        sync_runtime_state(state)

        review = normalize_pass_review(
            ensure_dict(execute_chat_node(state, spec, REVIEW_NODE_ID, expect_json=True))
        )

        if not review.approved:
            if not should_retry(
                state.get_int_var(SCRIPT_RETRY_VAR),
                state.get_int_var(SCRIPT_MAX_RETRY_VAR),
            ):
                raise RuntimeError("剧本正文审核未通过，且已达到最大修订次数。")

            rewrite_start_episode = _resolve_rewrite_start_episode(
                review.rewrite_start_episode,
                current_start=current_start,
                total_episodes=total_episodes,
            )
            state.set_var(SCRIPT_RETRY_VAR, state.get_int_var(SCRIPT_RETRY_VAR) + 1)
            _rollback_script_episode_cache(state, rewrite_start_episode)
            state.set_var(SCRIPT_START_VAR, rewrite_start_episode)
            set_runtime_stage(
                state,
                "script",
                f"第 {batch.label} 集正文审核未通过，将从第 {rewrite_start_episode} 集开始重写。",
                batch_label=batch.label,
                progress_percent=progress_percent,
                generated_episodes=max(0, rewrite_start_episode - 1),
            )
            sync_runtime_state(state)
            continue

        _commit_script_batch(state, batch, script_text)
        state.set_var(SCRIPT_RETRY_VAR, 0)
        state.set_var(SCRIPT_START_VAR, batch.end_episode + 1)
        sync_runtime_state(state)

        set_runtime_stage(
            state,
            "script",
            f"正在整理第 {batch.label} 集的上下文记忆。",
            batch_label=batch.label,
            progress_percent=70 + int((batch.end_episode / max(1, total_episodes)) * 28),
            generated_episodes=batch.end_episode,
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


def _resolve_rewrite_start_episode(
    requested_start: int | None,
    *,
    current_start: int,
    total_episodes: int,
) -> int:
    start = requested_start if isinstance(requested_start, int) else current_start
    if start < 1:
        start = 1
    if start > total_episodes:
        start = total_episodes
    return start


def _commit_script_batch(state, batch: BatchWindow, script_text: str) -> None:
    episode_cache = _normalize_episode_cache(state.get_var(LOCAL_SCRIPT_EPISODE_CACHE_VAR, {}))
    episode_cache.update(_extract_script_episode_map(script_text, batch))
    state.set_var(LOCAL_SCRIPT_EPISODE_CACHE_VAR, episode_cache)

    if episode_cache:
        state.set_var(SCRIPT_FINAL_VAR, _join_episode_cache(episode_cache))
    else:
        current_final = str(state.get_var(SCRIPT_FINAL_VAR, "") or "").strip()
        state.set_var(
            SCRIPT_FINAL_VAR,
            "\n\n".join(part for part in (current_final, script_text.strip()) if part).strip(),
        )


def _rollback_script_episode_cache(state, rewrite_start_episode: int) -> None:
    episode_cache = _normalize_episode_cache(state.get_var(LOCAL_SCRIPT_EPISODE_CACHE_VAR, {}))
    preserved = {
        episode: text
        for episode, text in episode_cache.items()
        if episode < rewrite_start_episode
    }
    state.set_var(LOCAL_SCRIPT_EPISODE_CACHE_VAR, preserved)
    state.set_var(SCRIPT_FINAL_VAR, _join_episode_cache(preserved))
    state.set_var(SCRIPT_CURRENT_VAR, "")


def _normalize_episode_cache(value) -> dict[int, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[int, str] = {}
    for key, item in value.items():
        try:
            episode = int(key)
        except (TypeError, ValueError):
            continue
        text = str(item or "").strip()
        if episode > 0 and text:
            normalized[episode] = text
    return normalized


def _join_episode_cache(cache: dict[int, str]) -> str:
    return "\n\n".join(
        cache[episode].strip()
        for episode in sorted(cache)
        if cache[episode].strip()
    ).strip()


def _extract_script_episode_map(script_text: str, batch: BatchWindow) -> dict[int, str]:
    text = str(script_text or "").strip()
    if not text:
        return {}

    pattern = re.compile(
        r"(?=^第\s*([0-9０-９一二三四五六七八九十百千万两零〇]+)\s*集)",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return {}

    extracted: dict[int, str] = {}
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        episode = _parse_episode_token(match.group(1))
        if episode is None:
            continue
        if batch.start_episode <= episode <= batch.end_episode:
            chunk = text[start:end].strip()
            if chunk:
                extracted[episode] = chunk
    return extracted


def _parse_episode_token(value: str) -> int | None:
    token = str(value or "").strip()
    if not token:
        return None

    fullwidth_digits = str.maketrans("０１２３４５６７８９", "0123456789")
    normalized = token.translate(fullwidth_digits)
    if normalized.isdigit():
        return int(normalized)

    numerals = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = 0
    current = 0
    for char in normalized:
        if char in numerals:
            current = numerals[char]
            continue
        unit = units.get(char)
        if unit is None:
            return None
        if current == 0:
            current = 1
        total += current * unit
        current = 0
    total += current
    return total or None
