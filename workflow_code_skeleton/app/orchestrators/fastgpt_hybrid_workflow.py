from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Protocol

from ..config import ModelOption, settings
from ..models.inputs import WorkflowInput
from ..models.state import WorkflowState
from ..services.fastgpt_client import fastgpt_client
from ..services.fastgpt_contracts import (
    ALL_DIALOGUES,
    ALL_HOOKS,
    ALL_SCRIPT,
    BATCH_DIALOGUES,
    BATCH_HOOKS,
    BATCH_SCRIPT,
    CHARACTERS,
    EPISODE_WORD_COUNT,
    EPISODE_PLAN,
    FINAL_SCRIPT,
    IS_CONSISTENT,
    LAST_SUMMARY,
    MAX_RETRIES,
    SCENES,
    SCRIPT_TITLE,
    STAGE_CHARACTERS,
    STAGE_CONSISTENCY,
    STAGE_DIALOGUES,
    STAGE_FINAL,
    STAGE_HOOKS,
    STAGE_MEMORY,
    STAGE_SCENES,
    STAGE_SCRIPT,
    STAGE_WORLDVIEW,
    STORY_OUTLINE,
    TOTAL_EPISODES,
    USER_CHARACTERS,
    USER_CONTENT_BASELINE,
    USER_SCENES,
    WORLDVIEW,
    contract_for,
)
from ..utils.episode import BatchWindow, iter_episode_batches
from ..utils.logger import get_logger
from ..workflow_ids import (
    CHARACTER_VAR,
    CORE_SCENE_FINAL_VAR,
    DIALOGUE_CURRENT_VAR,
    DIALOGUE_FINAL_VAR,
    HOOK_CURRENT_VAR,
    HOOK_FINAL_VAR,
    MEMORY_VAR,
    SCENE_VAR,
    SCRIPT_CURRENT_VAR,
    SCRIPT_FINAL_VAR,
    WORLDVIEW_VAR,
)
from .runtime_tools import set_runtime_stage, sync_runtime_state

logger = get_logger("fastgpt_hybrid_workflow")


class FastGPTRunner(Protocol):
    def run_stage(self, stage_name: str, variables: dict[str, Any]) -> dict[str, Any]:
        ...


def run_fastgpt_hybrid_workflow(
    payload: WorkflowInput,
    *,
    workflow_spec_path: str | Path | None = None,
    runtime=None,
    model_option: ModelOption | None = None,
    client: FastGPTRunner | None = None,
) -> WorkflowState:
    """Run the script workflow with local orchestration and FastGPT stage calls."""

    del workflow_spec_path
    payload.validate()
    state = WorkflowState.from_defaults(user_input=payload, default_variables={})
    state.runtime = runtime
    state.preferred_provider = model_option.provider if model_option else None
    state.preferred_model = model_option.model if model_option else None
    runner = client or fastgpt_client

    variables = _initial_fastgpt_variables(payload)
    _sync_state_variables(state, variables)
    sync_runtime_state(state)

    set_runtime_stage(state, "validation", "正在核对分集计划和总集数。", progress_percent=1)
    consistency = _run_fastgpt_stage(
        state,
        runner,
        STAGE_CONSISTENCY,
        variables,
        stage_key="validation",
        message="正在核对分集计划和总集数。",
        progress_percent=2,
        max_retries=0,
    )
    if not consistency[IS_CONSISTENT]:
        state.halted_message = "分集计划与总集数不一致，请调整后重新生成。"
        state.final_output_text = state.halted_message
        set_runtime_stage(state, "validation", state.halted_message, progress_percent=0)
        sync_runtime_state(state)
        return state
    set_runtime_stage(state, "validation", "集数一致性检查通过。", progress_percent=3)

    variables.update(
        _run_fastgpt_stage(
            state,
            runner,
            STAGE_WORLDVIEW,
            variables,
            stage_key="worldview",
            message="正在生成并校正故事规则。",
            progress_percent=12,
        )
    )
    _sync_state_variables(state, variables)

    variables.update(
        _run_fastgpt_stage(
            state,
            runner,
            STAGE_CHARACTERS,
            variables,
            stage_key="character",
            message="正在生成并校正人物设定。",
            progress_percent=24,
        )
    )
    _sync_state_variables(state, variables)

    variables.update(
        _run_fastgpt_stage(
            state,
            runner,
            STAGE_SCENES,
            variables,
            stage_key="scene",
            message="正在生成并校正核心场景。",
            progress_percent=34,
        )
    )
    _sync_state_variables(state, variables)

    _run_batched_generation(state, runner, payload, variables)

    final_output = _run_fastgpt_stage(
        state,
        runner,
        STAGE_FINAL,
        variables,
        stage_key="finalize",
        message="正在整理最终完整剧本。",
        progress_percent=99,
        max_retries=0,
    )
    variables.update(final_output)
    state.final_output_text = final_output[FINAL_SCRIPT]
    state.set_var(SCRIPT_FINAL_VAR, final_output[FINAL_SCRIPT])
    _sync_state_variables(state, variables)
    set_runtime_stage(
        state,
        "finalize",
        "最终完整剧本已生成。",
        progress_percent=100,
        generated_episodes=payload.total_episodes,
    )
    sync_runtime_state(state)
    return state


def _initial_fastgpt_variables(payload: WorkflowInput) -> dict[str, Any]:
    return {
        SCRIPT_TITLE: payload.title,
        TOTAL_EPISODES: payload.total_episodes,
        EPISODE_WORD_COUNT: payload.episode_word_count,
        EPISODE_PLAN: payload.episode_plan,
        STORY_OUTLINE: payload.story_outline,
        USER_SCENES: payload.core_scene_input,
        USER_CHARACTERS: payload.character_bios,
        USER_CONTENT_BASELINE: _build_user_content_baseline(payload),
        MAX_RETRIES: settings.max_retries_default,
        LAST_SUMMARY: "",
        ALL_HOOKS: {},
        ALL_DIALOGUES: {},
        ALL_SCRIPT: "",
    }


def _build_user_content_baseline(payload: WorkflowInput) -> str:
    baseline = {
        SCRIPT_TITLE: payload.title,
        TOTAL_EPISODES: payload.total_episodes,
        EPISODE_WORD_COUNT: payload.episode_word_count,
        STORY_OUTLINE: payload.story_outline,
        USER_SCENES: payload.core_scene_input,
        USER_CHARACTERS: payload.character_bios,
        EPISODE_PLAN: payload.episode_plan,
    }
    return json.dumps(baseline, ensure_ascii=False, indent=2)


def _run_batched_generation(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> None:
    batch_mode = _effective_batch_mode()
    if batch_mode in {"fastgpt_full", "full", "legacy_full"}:
        _run_full_fastgpt_generation(state, runner, payload, variables)
        return
    if batch_mode != "local":
        raise ValueError(
            "FASTGPT_BATCH_MODE 只能是 auto、local 或 fastgpt_full，"
            f"当前为：{settings.fastgpt_batch_mode}"
        )

    total_episodes = int(variables[TOTAL_EPISODES])
    batch_size = max(1, int(settings.batch_size or 5))
    batches = list(iter_episode_batches(total_episodes, batch_size=batch_size))
    total_batches = max(1, len(batches))
    all_hooks: dict[str, Any] = {}
    all_dialogues: dict[str, Any] = {}
    all_script_parts: list[str] = []

    for index, batch in enumerate(batches):
        plan_for_batch = slice_episode_plan_for_batch(payload.episode_plan, batch)
        batch_base = dict(variables)
        batch_base[EPISODE_PLAN] = plan_for_batch

        hook_progress = 36 + int((index / total_batches) * 12)
        hook_output = _run_fastgpt_stage(
            state,
            runner,
            STAGE_HOOKS,
            batch_base,
            stage_key="hook",
            message=f"正在生成第 {batch.label} 集的开头冲突钩子。",
            batch_label=batch.label,
            progress_percent=hook_progress,
        )
        all_hooks = merge_batch_object(all_hooks, hook_output[BATCH_HOOKS])
        variables[BATCH_HOOKS] = hook_output[BATCH_HOOKS]
        variables[ALL_HOOKS] = all_hooks
        _sync_state_variables(state, variables)

        dialogue_base = dict(variables)
        dialogue_base[EPISODE_PLAN] = plan_for_batch
        dialogue_progress = 50 + int((index / total_batches) * 12)
        dialogue_output = _run_fastgpt_stage(
            state,
            runner,
            STAGE_DIALOGUES,
            dialogue_base,
            stage_key="dialogue",
            message=f"正在生成第 {batch.label} 集的角色对话。",
            batch_label=batch.label,
            progress_percent=dialogue_progress,
        )
        all_dialogues = merge_batch_object(all_dialogues, dialogue_output[BATCH_DIALOGUES])
        variables[BATCH_DIALOGUES] = dialogue_output[BATCH_DIALOGUES]
        variables[ALL_DIALOGUES] = all_dialogues
        _sync_state_variables(state, variables)

        script_base = dict(variables)
        script_base[EPISODE_PLAN] = plan_for_batch
        script_progress = 68 + int((index / total_batches) * 26)
        script_output = _run_fastgpt_stage(
            state,
            runner,
            STAGE_SCRIPT,
            script_base,
            stage_key="script",
            message=f"正在生成第 {batch.label} 集的剧本正文。",
            batch_label=batch.label,
            progress_percent=script_progress,
            generated_episodes=min(total_episodes, index * batch_size),
        )
        batch_script = script_output[BATCH_SCRIPT].strip()
        all_script_parts.append(batch_script)
        variables[BATCH_SCRIPT] = batch_script
        variables[ALL_SCRIPT] = "\n\n".join(part for part in all_script_parts if part)
        _sync_state_variables(state, variables)

        memory_output = _run_fastgpt_stage(
            state,
            runner,
            STAGE_MEMORY,
            {BATCH_SCRIPT: batch_script},
            stage_key="script",
            message=f"正在整理第 {batch.label} 集的上下文记忆。",
            batch_label=batch.label,
            progress_percent=70 + int(((index + 1) / total_batches) * 26),
            generated_episodes=min(total_episodes, (index + 1) * batch_size),
            max_retries=0,
        )
        variables[LAST_SUMMARY] = memory_output[LAST_SUMMARY]
        _sync_state_variables(state, variables)

    set_runtime_stage(
        state,
        "script",
        "剧本正文阶段完成。",
        progress_percent=98,
        generated_episodes=total_episodes,
    )
    sync_runtime_state(state)


def _effective_batch_mode() -> str:
    mode = settings.fastgpt_batch_mode
    if mode == "auto":
        if settings.fastgpt_variable_mode in {"legacy", "legacy_ids"}:
            return "fastgpt_full"
        return "local"
    return mode


def _run_full_fastgpt_generation(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> None:
    variables[EPISODE_PLAN] = payload.episode_plan

    hook_output = _run_fastgpt_stage(
        state,
        runner,
        STAGE_HOOKS,
        variables,
        stage_key="hook",
        message="正在生成全量开头冲突钩子。",
        progress_percent=42,
    )
    variables[BATCH_HOOKS] = hook_output[BATCH_HOOKS]
    variables[ALL_HOOKS] = hook_output[BATCH_HOOKS]
    _sync_state_variables(state, variables)

    dialogue_output = _run_fastgpt_stage(
        state,
        runner,
        STAGE_DIALOGUES,
        variables,
        stage_key="dialogue",
        message="正在生成全量角色对话。",
        progress_percent=58,
    )
    variables[BATCH_DIALOGUES] = dialogue_output[BATCH_DIALOGUES]
    variables[ALL_DIALOGUES] = dialogue_output[BATCH_DIALOGUES]
    _sync_state_variables(state, variables)

    script_output = _run_fastgpt_stage(
        state,
        runner,
        STAGE_SCRIPT,
        variables,
        stage_key="script",
        message="正在生成全量剧本正文。",
        progress_percent=86,
        generated_episodes=0,
    )
    all_script = script_output[BATCH_SCRIPT].strip()
    variables[BATCH_SCRIPT] = all_script
    variables[ALL_SCRIPT] = all_script
    _sync_state_variables(state, variables)

    memory_output = _run_fastgpt_stage(
        state,
        runner,
        STAGE_MEMORY,
        {
            BATCH_SCRIPT: all_script,
            LAST_SUMMARY: "",
        },
        stage_key="script",
        message="正在整理全量剧本记忆。",
        progress_percent=94,
        generated_episodes=payload.total_episodes,
        max_retries=0,
    )
    variables[LAST_SUMMARY] = memory_output[LAST_SUMMARY]
    _sync_state_variables(state, variables)

    set_runtime_stage(
        state,
        "script",
        "剧本正文阶段完成。",
        progress_percent=98,
        generated_episodes=payload.total_episodes,
    )
    sync_runtime_state(state)


def _run_fastgpt_stage(
    state: WorkflowState,
    runner: FastGPTRunner,
    stage_name: str,
    variables: dict[str, Any],
    *,
    stage_key: str,
    message: str,
    batch_label: str | None = None,
    progress_percent: int | None = None,
    generated_episodes: int | None = None,
    max_retries: int | None = None,
) -> dict[str, Any]:
    contract = contract_for(stage_name)
    attempts = 1 + max(0, settings.max_retries_default if max_retries is None else max_retries)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        _checkpoint(state)
        visible_message = message
        if attempt > 1:
            visible_message = f"{message}（第 {attempt} 次尝试）"
        set_runtime_stage(
            state,
            stage_key,
            visible_message,
            batch_label=batch_label,
            progress_percent=progress_percent,
            generated_episodes=generated_episodes,
        )
        try:
            input_payload = contract.build_input_payload(variables)
            state.set_output(f"fastgpt:{stage_name}", f"attempt_{attempt}_input", input_payload)
            _log_fastgpt_stage_start(state, stage_name, input_payload.keys())
            output = runner.run_stage(stage_name, variables)
            output = contract.validate_output_payload(output)
            state.set_output(f"fastgpt:{stage_name}", f"attempt_{attempt}", output)
            _log_fastgpt_stage_done(state, stage_name, output)
            _sync_state_variables(state, output)
            _checkpoint(state)
            return output
        except Exception as exc:
            last_error = exc
            state.set_output(f"fastgpt:{stage_name}", f"attempt_{attempt}_error", str(exc))
            logger.warning(
                "FastGPT 阶段 %s 第 %s 次调用失败: %s",
                stage_name,
                attempt,
                exc,
            )
            if _is_non_retryable(exc) or attempt >= attempts:
                raise
            set_runtime_stage(
                state,
                stage_key,
                f"{contract.label} 返回不符合契约，正在重试。",
                batch_label=batch_label,
                progress_percent=progress_percent,
                generated_episodes=generated_episodes,
            )
    raise RuntimeError(f"FastGPT 阶段 {stage_name} 调用失败：{last_error}")


def _log_fastgpt_stage_start(
    state: WorkflowState,
    stage_name: str,
    input_names: Any,
) -> None:
    runtime = state.runtime
    if runtime and hasattr(runtime, "fastgpt_stage_started"):
        runtime.fastgpt_stage_started(stage_name, list(input_names))


def _log_fastgpt_stage_done(
    state: WorkflowState,
    stage_name: str,
    output: dict[str, Any],
) -> None:
    runtime = state.runtime
    if runtime and hasattr(runtime, "fastgpt_stage_finished"):
        runtime.fastgpt_stage_finished(stage_name, output)


def _is_non_retryable(exc: Exception) -> bool:
    text = str(exc)
    return "缺少 FastGPT API Key" in text or "401" in text or "403" in text


def _checkpoint(state: WorkflowState) -> None:
    runtime = state.runtime
    if runtime and hasattr(runtime, "checkpoint"):
        runtime.checkpoint()


def _sync_state_variables(state: WorkflowState, variables: dict[str, Any]) -> None:
    for key, value in variables.items():
        state.set_var(key, value)

    if WORLDVIEW in variables:
        state.set_var(WORLDVIEW_VAR, variables[WORLDVIEW])
    if CHARACTERS in variables:
        state.set_var(CHARACTER_VAR, variables[CHARACTERS])
    if SCENES in variables:
        state.set_var(SCENE_VAR, variables[SCENES])
        state.set_var(CORE_SCENE_FINAL_VAR, variables[SCENES])
    if BATCH_HOOKS in variables:
        state.set_var(HOOK_CURRENT_VAR, variables[BATCH_HOOKS])
    if ALL_HOOKS in variables:
        state.set_var(HOOK_FINAL_VAR, variables[ALL_HOOKS])
    if BATCH_DIALOGUES in variables:
        state.set_var(DIALOGUE_CURRENT_VAR, variables[BATCH_DIALOGUES])
    if ALL_DIALOGUES in variables:
        state.set_var(DIALOGUE_FINAL_VAR, variables[ALL_DIALOGUES])
    if BATCH_SCRIPT in variables:
        state.set_var(SCRIPT_CURRENT_VAR, variables[BATCH_SCRIPT])
    if ALL_SCRIPT in variables:
        state.set_var(SCRIPT_FINAL_VAR, variables[ALL_SCRIPT])
    if LAST_SUMMARY in variables:
        state.set_var(MEMORY_VAR, variables[LAST_SUMMARY])
    if FINAL_SCRIPT in variables:
        state.set_var(SCRIPT_FINAL_VAR, variables[FINAL_SCRIPT])

    sync_runtime_state(state)


def merge_batch_object(current: dict[str, Any], batch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(current or {})
    incoming = copy.deepcopy(batch or {})
    return _merge_dicts(merged, incoming)


def _merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    for key, value in right.items():
        if key not in left:
            left[key] = value
            continue

        existing = left[key]
        if isinstance(existing, dict) and isinstance(value, dict):
            left[key] = _merge_dicts(existing, value)
        elif isinstance(existing, list) and isinstance(value, list):
            left[key] = [*existing, *value]
        else:
            left[key] = value
    return left


def slice_episode_plan_for_batch(episode_plan: str, batch: BatchWindow) -> str:
    lines = str(episode_plan or "").splitlines()
    selected: list[str] = []
    current_episode: int | None = None
    found_marker = False

    for line in lines:
        marker = _extract_episode_number(line)
        if marker is not None:
            found_marker = True
            current_episode = marker
        if current_episode is not None and batch.start_episode <= current_episode <= batch.end_episode:
            selected.append(line)

    if found_marker and selected:
        return "\n".join(selected).strip()
    return str(episode_plan or "").strip()


def _extract_episode_number(line: str) -> int | None:
    text = str(line or "").strip()
    if not text:
        return None

    patterns = (
        r"第\s*([0-9零〇一二两三四五六七八九十百千]+)\s*[集话回章]",
        r"^\s*([0-9]{1,4})\s*[\.、)、:：-]",
        r"^\s*[Ee]pisode\s*([0-9]{1,4})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        raw = match.group(1)
        if raw.isdigit():
            return int(raw)
        parsed = _parse_chinese_number(raw)
        if parsed is not None:
            return parsed
    return None


def _parse_chinese_number(raw: str) -> int | None:
    text = str(raw or "").strip()
    if not text:
        return None
    digits = {
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
    if all(ch in digits for ch in text):
        return int("".join(str(digits[ch]) for ch in text))

    total = 0
    section = 0
    number = 0
    units = {"十": 10, "百": 100, "千": 1000}
    for ch in text:
        if ch in digits:
            number = digits[ch]
            continue
        if ch in units:
            unit = units[ch]
            section += (number or 1) * unit
            number = 0
            continue
        return None
    total += section + number
    return total or None
