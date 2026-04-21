from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path
from typing import Any, Protocol

from ..config import ModelOption, settings
from ..models.inputs import WorkflowInput
from ..models.state import WorkflowState
from ..services.fastgpt_client import FastGPTTransientError, fastgpt_client
from ..services.fastgpt_contracts import (
    ALL_DIALOGUES,
    ALL_HOOKS,
    ALL_SCRIPT,
    BATCH_START_EPISODE,
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
    NORMALIZED_EPISODE_PLAN,
    CHARACTER_COUNT,
    SCENES,
    SCRIPT_TITLE,
    STAGE_FRAMEWORK,
    STAGE_CHARACTERS,
    STAGE_CONSISTENCY,
    STAGE_DIALOGUES,
    STAGE_EPISODE_PLAN_NORMALIZE,
    STAGE_FINAL,
    STAGE_HOOKS,
    STAGE_MEMORY,
    STAGE_SCENES,
    STAGE_SCRIPT,
    STAGE_WORLDVIEW,
    STORY_OUTLINE,
    TOTAL_EPISODES,
    USER_EXPECTATION,
    USER_CHARACTERS,
    USER_CONTENT_BASELINE,
    USER_SCENES,
    WORLDVIEW,
    contract_for,
)
from ..utils.episode import BatchWindow, iter_episode_batches
from ..utils.logger import get_logger
from ..workflow_ids import (
    CHARACTER_BIOS_VAR,
    CHARACTER_VAR,
    CORE_SCENE_INPUT_VAR,
    CORE_SCENE_FINAL_VAR,
    DIALOGUE_CURRENT_VAR,
    DIALOGUE_START_VAR,
    DIALOGUE_FINAL_VAR,
    EPISODE_PLAN_VAR,
    EPISODE_PLAN_CURSOR_VAR,
    EPISODE_PLAN_NORMALIZED_VAR,
    FINAL_CHARACTER_VAR,
    FINAL_SCENE_VAR,
    HOOK_CURRENT_VAR,
    HOOK_START_VAR,
    HOOK_FINAL_VAR,
    MEMORY_VAR,
    SCENE_VAR,
    SCRIPT_CURRENT_VAR,
    SCRIPT_START_VAR,
    SCRIPT_FINAL_VAR,
    STORY_OUTLINE_VAR,
    TITLE_VAR,
    WORLDVIEW_VAR,
)
from .runtime_tools import set_runtime_stage, sync_runtime_state

logger = get_logger("fastgpt_hybrid_workflow")
LOCAL_COMPLETED_BATCHES = "_completed_batches"
LOCAL_COMMITTED_SCRIPT = "_committed_all_script"


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
    resume_snapshot: dict[str, Any] | None = None,
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
    _restore_resume_state(state, variables, resume_snapshot)
    _apply_framework_outputs_to_variables(payload, variables)
    _apply_normalized_episode_plan_to_variables(payload, variables)
    _sync_state_variables(state, variables)
    sync_runtime_state(state)

    if _has_framework_outputs(variables):
        set_runtime_stage(
            state,
            "framework",
            "已从缓存恢复剧本框架。",
            progress_percent=4,
        )
    else:
        variables.update(
            _run_fastgpt_stage(
                state,
                runner,
                STAGE_FRAMEWORK,
                variables,
                stage_key="framework",
                message="正在撰写剧本框架。",
                progress_percent=4,
                max_retries=0,
            )
        )
        _apply_framework_outputs_to_variables(payload, variables)
    _sync_state_variables(state, variables)

    if _truthy(variables.get(IS_CONSISTENT)):
        consistency = {IS_CONSISTENT: True}
        set_runtime_stage(
            state,
            "validation",
            "已从缓存恢复集数一致性检查结果。",
            progress_percent=3,
        )
    else:
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
        variables.update(consistency)
    if not consistency[IS_CONSISTENT]:
        state.halted_message = "分集计划与总集数不一致，请调整后重新生成。"
        state.final_output_text = state.halted_message
        set_runtime_stage(state, "validation", state.halted_message, progress_percent=0)
        sync_runtime_state(state)
        return state
    set_runtime_stage(state, "validation", "集数一致性检查通过。", progress_percent=3)

    normalized_plan = _normalize_episode_plan_object(variables.get(NORMALIZED_EPISODE_PLAN))
    if _has_normalized_episode_plan(normalized_plan):
        variables[NORMALIZED_EPISODE_PLAN] = normalized_plan
        set_runtime_stage(
            state,
            "validation",
            "已从缓存恢复规范化分集计划。",
            progress_percent=7,
        )
    else:
        variables.update(
            _run_fastgpt_stage(
                state,
                runner,
                STAGE_EPISODE_PLAN_NORMALIZE,
                variables,
                stage_key="validation",
                message="正在规范化分集计划结构。",
                progress_percent=7,
                max_retries=0,
            )
        )
        normalized_plan = _normalize_episode_plan_object(variables.get(NORMALIZED_EPISODE_PLAN))
        if _has_normalized_episode_plan(normalized_plan):
            variables[NORMALIZED_EPISODE_PLAN] = normalized_plan
            _apply_normalized_episode_plan_to_variables(payload, variables)
    _sync_state_variables(state, variables)

    if _has_value(variables.get(WORLDVIEW)):
        set_runtime_stage(
            state,
            "worldview",
            "已从缓存恢复故事规则。",
            progress_percent=12,
        )
    else:
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

    if _has_value(variables.get(CHARACTERS)):
        set_runtime_stage(
            state,
            "character",
            "已从缓存恢复人物设定。",
            progress_percent=24,
        )
    else:
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

    if _has_value(variables.get(SCENES)):
        set_runtime_stage(
            state,
            "scene",
            "已从缓存恢复核心场景。",
            progress_percent=34,
        )
    else:
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
        USER_EXPECTATION: payload.user_expectation,
        CHARACTER_COUNT: payload.character_count,
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


def _build_user_content_baseline(
    payload: WorkflowInput,
    *,
    script_title: str | None = None,
    story_outline_value: str | None = None,
    user_scenes_value: str | None = None,
    user_characters_value: str | None = None,
    episode_plan_value: str | None = None,
) -> str:
    baseline = {
        SCRIPT_TITLE: script_title if script_title is not None else payload.title,
        TOTAL_EPISODES: payload.total_episodes,
        EPISODE_WORD_COUNT: payload.episode_word_count,
        STORY_OUTLINE: story_outline_value if story_outline_value is not None else payload.story_outline,
        USER_SCENES: user_scenes_value if user_scenes_value is not None else payload.core_scene_input,
        USER_CHARACTERS: user_characters_value if user_characters_value is not None else payload.character_bios,
        EPISODE_PLAN: episode_plan_value if episode_plan_value is not None else payload.episode_plan,
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
    all_hooks = _dict_or_empty(variables.get(ALL_HOOKS))
    all_dialogues = _dict_or_empty(variables.get(ALL_DIALOGUES))
    committed_script = str(
        variables.get(LOCAL_COMMITTED_SCRIPT) or variables.get(ALL_SCRIPT) or ""
    ).strip()
    if committed_script:
        all_script_parts = [committed_script]
    completed_batches = min(
        total_batches,
        max(0, _safe_int(variables.get(LOCAL_COMPLETED_BATCHES), 0)),
    )
    normalized_plan = _normalize_episode_plan_object(variables.get(NORMALIZED_EPISODE_PLAN))

    for index, batch in enumerate(batches):
        if index < completed_batches:
            continue
        plan_for_batch = get_episode_batch_payload(
            normalized_plan,
            batch.start_episode,
            batch_size=batch.size,
            raw_episode_plan=str(variables.get(EPISODE_PLAN) or payload.episode_plan or ""),
        )
        variables[BATCH_START_EPISODE] = batch.start_episode
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
        dialogue_base[BATCH_START_EPISODE] = batch.start_episode
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
        script_base[BATCH_START_EPISODE] = batch.start_episode
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
        variables[LOCAL_COMPLETED_BATCHES] = index + 1
        variables[LOCAL_COMMITTED_SCRIPT] = variables[ALL_SCRIPT]
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
        return "local"
    return mode


def _run_full_fastgpt_generation(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> None:
    variables[EPISODE_PLAN] = get_episode_batch_payload(
        _normalize_episode_plan_object(variables.get(NORMALIZED_EPISODE_PLAN)),
        1,
        batch_size=payload.total_episodes,
        raw_episode_plan=str(variables.get(EPISODE_PLAN) or payload.episode_plan or ""),
    )
    variables[BATCH_START_EPISODE] = 1

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
    # Business audit/revise loops live inside FastGPT. Python only retries malformed
    # stage calls when explicitly configured, while HTTP/network retry is handled
    # by FastGPTClient.
    stage_retries = settings.fastgpt_stage_retries if max_retries is None else max_retries
    attempts = 1 + max(0, stage_retries)
    last_error: Exception | None = None

    attempt = 0
    contract_failures = 0
    while True:
        attempt += 1
        _checkpoint(state)
        set_runtime_stage(
            state,
            stage_key,
            message,
            batch_label=batch_label,
            progress_percent=progress_percent,
            generated_episodes=generated_episodes,
        )
        try:
            contract.build_input_payload(variables)
            _log_fastgpt_stage_start(state, contract.label, batch_label, attempt)
            output = runner.run_stage(stage_name, variables)
            output = contract.validate_output_payload(output)
            _log_fastgpt_stage_done(state, contract.label, batch_label, output)
            _sync_state_variables(state, output)
            _checkpoint(state)
            return output
        except FastGPTTransientError as exc:
            last_error = exc
            delay_seconds = _transient_retry_delay(attempt)
            retry_message = "网络波动，已保留当前进度，正在自动重试。"
            set_runtime_stage(
                state,
                stage_key,
                retry_message,
                batch_label=batch_label,
                progress_percent=progress_percent,
                generated_episodes=generated_episodes,
            )
            sync_runtime_state(state)
            logger.warning(
                "%s%s第 %s 次尝试遇到临时错误，将在 %.0f 秒后自动重试：%s",
                contract.label,
                _format_batch_suffix(batch_label),
                attempt,
                delay_seconds,
                exc,
            )
            _sleep_with_checkpoints(state, delay_seconds)
            continue
        except Exception as exc:
            last_error = exc
            contract_failures += 1
            sync_runtime_state(state)
            logger.warning(
                "%s%s第 %s 次尝试失败：%s",
                contract.label,
                _format_batch_suffix(batch_label),
                attempt,
                exc,
            )
            if _is_non_retryable(exc) or contract_failures >= attempts:
                set_runtime_stage(
                    state,
                    stage_key,
                    f"{contract.label} 调用失败，已保留当前进度：{exc}",
                    batch_label=batch_label,
                    progress_percent=progress_percent,
                    generated_episodes=generated_episodes,
                )
                sync_runtime_state(state)
                raise
            set_runtime_stage(
                state,
                stage_key,
                "阶段返回格式异常，正在自动重试。",
                batch_label=batch_label,
                progress_percent=progress_percent,
                generated_episodes=generated_episodes,
            )


def _log_fastgpt_stage_start(
    state: WorkflowState,
    stage_label: str,
    batch_label: str | None,
    attempt: int,
) -> None:
    logger.info("%s%s第 %s 次尝试", stage_label, _format_batch_suffix(batch_label), attempt)
    runtime = state.runtime
    if runtime and hasattr(runtime, "fastgpt_stage_started"):
        runtime.fastgpt_stage_started(stage_label, batch_label=batch_label, attempt=attempt)


def _log_fastgpt_stage_done(
    state: WorkflowState,
    stage_label: str,
    batch_label: str | None,
    output: dict[str, Any],
) -> None:
    logger.info(
        "%s%s成品已生成：%s",
        stage_label,
        _format_batch_suffix(batch_label),
        _summarize_stage_output(output),
    )
    runtime = state.runtime
    if runtime and hasattr(runtime, "fastgpt_stage_finished"):
        runtime.fastgpt_stage_finished(stage_label, batch_label=batch_label, output=output)


def _format_batch_suffix(batch_label: str | None) -> str:
    return f" {batch_label} 集，" if batch_label else "，"


def _summarize_stage_output(output: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in output.items():
        if isinstance(value, dict):
            episodes = value.get("episodes")
            if isinstance(episodes, list):
                parts.append(f"{key}=episodes[{len(episodes)}]")
                continue
            keys = list(value.keys())[:4]
            parts.append(f"{key}=dict({', '.join(str(item) for item in keys)})")
            continue
        if isinstance(value, list):
            parts.append(f"{key}=list[{len(value)}]")
            continue
        text = " ".join(str(value or "").split())
        parts.append(f"{key}={text[:80]}")
    return "；".join(parts)[:240] or "阶段已完成"


def _is_non_retryable(exc: Exception) -> bool:
    text = str(exc)
    return "缺少 FastGPT API Key" in text or "401" in text or "403" in text


def _checkpoint(state: WorkflowState) -> None:
    runtime = state.runtime
    if runtime and hasattr(runtime, "checkpoint"):
        runtime.checkpoint()


def _transient_retry_delay(attempt: int) -> float:
    base = max(1.0, float(getattr(settings, "fastgpt_http_retry_delay", 1.5)))
    return min(60.0, base * min(max(1, attempt), 20))


def _sleep_with_checkpoints(state: WorkflowState, seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        _checkpoint(state)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.5, remaining))


def _sync_state_variables(state: WorkflowState, variables: dict[str, Any]) -> None:
    for key, value in variables.items():
        state.set_var(key, value)

    if SCRIPT_TITLE in variables:
        state.set_var(TITLE_VAR, variables[SCRIPT_TITLE])
    if STORY_OUTLINE in variables:
        state.set_var(STORY_OUTLINE_VAR, variables[STORY_OUTLINE])
    if USER_CHARACTERS in variables:
        state.set_var(CHARACTER_BIOS_VAR, variables[USER_CHARACTERS])
    if USER_SCENES in variables:
        state.set_var(CORE_SCENE_INPUT_VAR, variables[USER_SCENES])
    if EPISODE_PLAN in variables:
        state.set_var(EPISODE_PLAN_VAR, variables[EPISODE_PLAN])
    if WORLDVIEW in variables:
        state.set_var(WORLDVIEW_VAR, variables[WORLDVIEW])
    if CHARACTERS in variables:
        state.set_var(CHARACTER_VAR, variables[CHARACTERS])
        state.set_var(FINAL_CHARACTER_VAR, variables[CHARACTERS])
    if SCENES in variables:
        state.set_var(SCENE_VAR, variables[SCENES])
        state.set_var(CORE_SCENE_FINAL_VAR, variables[SCENES])
        state.set_var(FINAL_SCENE_VAR, variables[SCENES])
    if NORMALIZED_EPISODE_PLAN in variables:
        normalized_plan = _normalize_episode_plan_object(variables[NORMALIZED_EPISODE_PLAN])
        if normalized_plan is not None:
            state.set_var(NORMALIZED_EPISODE_PLAN, normalized_plan)
            state.set_var(
                EPISODE_PLAN_NORMALIZED_VAR,
                json.dumps(normalized_plan, ensure_ascii=False),
            )
    if BATCH_START_EPISODE in variables:
        state.set_var(HOOK_START_VAR, variables[BATCH_START_EPISODE])
        state.set_var(DIALOGUE_START_VAR, variables[BATCH_START_EPISODE])
        state.set_var(SCRIPT_START_VAR, variables[BATCH_START_EPISODE])
        state.set_var(EPISODE_PLAN_CURSOR_VAR, variables[BATCH_START_EPISODE])
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


def _restore_resume_state(
    state: WorkflowState,
    variables: dict[str, Any],
    resume_snapshot: dict[str, Any] | None,
) -> None:
    if not resume_snapshot:
        return
    debug_state = resume_snapshot.get("debug_state")
    if not isinstance(debug_state, dict):
        return

    restored_variables = debug_state.get("variables")
    if isinstance(restored_variables, dict):
        variables.update(restored_variables)
        if NORMALIZED_EPISODE_PLAN not in variables:
            normalized_alias = restored_variables.get(EPISODE_PLAN_NORMALIZED_VAR)
            normalized_plan = _normalize_episode_plan_object(normalized_alias)
            if normalized_plan is not None:
                variables[NORMALIZED_EPISODE_PLAN] = normalized_plan
        state.variables.update(restored_variables)

    restored_outputs = debug_state.get("node_outputs")
    if isinstance(restored_outputs, dict):
        state.node_outputs.update(restored_outputs)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"true", "1", "yes", "y", "是", "通过", "一致"}


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return True


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except Exception:
        return default


def _dict_or_empty(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _apply_normalized_episode_plan_to_variables(
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> dict[str, Any] | None:
    normalized_plan = _normalize_episode_plan_object(variables.get(NORMALIZED_EPISODE_PLAN))
    if not _has_normalized_episode_plan(normalized_plan):
        return None

    normalized_text = _serialize_normalized_episode_plan(normalized_plan)
    variables[NORMALIZED_EPISODE_PLAN] = normalized_plan
    variables[EPISODE_PLAN] = normalized_text
    variables[USER_CONTENT_BASELINE] = _build_user_content_baseline(
        payload,
        script_title=str(variables.get(SCRIPT_TITLE) or payload.title or "").strip() or "AI原创剧本",
        story_outline_value=str(variables.get(STORY_OUTLINE) or payload.story_outline or "").strip(),
        user_scenes_value=str(variables.get(USER_SCENES) or payload.core_scene_input or "").strip(),
        user_characters_value=str(variables.get(USER_CHARACTERS) or payload.character_bios or "").strip(),
        episode_plan_value=normalized_text,
    )
    return normalized_plan


def _has_framework_outputs(variables: dict[str, Any]) -> bool:
    return all(
        _has_value(variables.get(name))
        for name in (STORY_OUTLINE, USER_CHARACTERS, USER_SCENES, EPISODE_PLAN)
    )


def _apply_framework_outputs_to_variables(
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> bool:
    if not _has_framework_outputs(variables):
        return False

    framework_title = str(variables.get(SCRIPT_TITLE) or "").strip()
    story_outline = str(variables.get(STORY_OUTLINE) or "").strip()
    user_characters = str(variables.get(USER_CHARACTERS) or "").strip()
    user_scenes = str(variables.get(USER_SCENES) or "").strip()
    episode_plan = str(variables.get(EPISODE_PLAN) or "").strip()
    script_title = framework_title or str(payload.title or "").strip() or "AI原创剧本"

    variables[SCRIPT_TITLE] = script_title
    variables[STORY_OUTLINE] = story_outline
    variables[USER_CHARACTERS] = user_characters
    variables[USER_SCENES] = user_scenes
    variables[EPISODE_PLAN] = episode_plan
    variables[USER_CONTENT_BASELINE] = _build_user_content_baseline(
        payload,
        script_title=script_title,
        story_outline_value=story_outline,
        user_scenes_value=user_scenes,
        user_characters_value=user_characters,
        episode_plan_value=episode_plan,
    )
    return True


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


def get_episode_batch_payload(
    normalized_plan: Any,
    start_episode: int,
    *,
    batch_size: int,
    raw_episode_plan: str,
) -> str:
    batch_window = BatchWindow(
        start_episode=start_episode,
        end_episode=max(start_episode, start_episode + max(1, batch_size) - 1),
    )
    batch_payload = slice_normalized_episode_plan_for_batch(normalized_plan, batch_window)
    if batch_payload is not None:
        return _serialize_normalized_episode_plan(batch_payload)
    return slice_episode_plan_for_batch(raw_episode_plan, batch_window)


def slice_normalized_episode_plan_for_batch(
    normalized_plan: Any,
    batch: BatchWindow,
) -> dict[str, Any] | None:
    normalized = _normalize_episode_plan_object(normalized_plan)
    if not _has_normalized_episode_plan(normalized):
        return None

    selected = [
        copy.deepcopy(item)
        for item in normalized["episodes"]
        if batch.start_episode <= item["episode"] <= batch.end_episode
    ]
    if not selected:
        return None

    return {
        "parsed_episode_count": len(selected),
        "episodes": selected,
    }


def _has_normalized_episode_plan(value: Any) -> bool:
    normalized = _normalize_episode_plan_object(value)
    if not isinstance(normalized, dict):
        return False
    episodes = normalized.get("episodes")
    return isinstance(episodes, list) and bool(episodes)


def _serialize_normalized_episode_plan(normalized_plan: dict[str, Any]) -> str:
    return json.dumps(normalized_plan, ensure_ascii=False, separators=(",", ":"))


def _normalize_episode_plan_object(value: Any) -> dict[str, Any] | None:
    if value in (None, ""):
        return None

    candidate = value
    if isinstance(candidate, str):
        text = candidate.strip()
        if not text:
            return None
        try:
            candidate = json.loads(text)
        except Exception:
            return None

    if isinstance(candidate, dict) and NORMALIZED_EPISODE_PLAN in candidate:
        candidate = candidate.get(NORMALIZED_EPISODE_PLAN)
        return _normalize_episode_plan_object(candidate)

    if not isinstance(candidate, dict):
        return None

    episodes = candidate.get("episodes")
    if not isinstance(episodes, list):
        return None

    normalized_episodes: list[dict[str, Any]] = []
    for item in episodes:
        if not isinstance(item, dict):
            continue
        episode_number = _coerce_episode_number(item.get("episode"))
        if episode_number is None:
            continue
        normalized_episodes.append(
            {
                "episode": episode_number,
                "title": str(item.get("title") or "").strip(),
                "content": str(item.get("content") or "").strip(),
            }
        )

    return {
        "parsed_episode_count": len(normalized_episodes),
        "episodes": normalized_episodes,
    }


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


def _coerce_episode_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)

    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return _parse_chinese_number(text)


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
