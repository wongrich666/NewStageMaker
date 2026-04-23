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
    APPEARANCE_CONTINUITY_MEMORY,
    APPEARANCE_MAPPING,
    BATCH_START_EPISODE,
    BATCH_DIALOGUES,
    BATCH_HOOKS,
    BATCH_SCRIPT,
    CHARACTERS,
    CHARACTER_ALIAS_NAMING_RULES,
    CHARACTER_ALIAS_REGISTRY,
    CHARACTER_APPEARANCE_REQUIREMENTS,
    CHARACTER_REGISTRY,
    EPISODE_WORD_COUNT,
    EPISODE_PLAN,
    EPISODE_ALIAS_PLAN,
    FINAL_SCRIPT,
    IS_CONSISTENT,
    LAST_SUMMARY,
    LEGACY_INPUT_ALIASES,
    MAX_RETRIES,
    NORMALIZED_EPISODE_PLAN,
    CHARACTER_COUNT,
    OUTFIT_SWITCH_RULES,
    SCENES,
    SCENE_APPEARANCE_REQUIREMENTS,
    SCRIPT_TITLE,
    STAGE_APPEARANCE_ALIAS_GENERATION,
    STAGE_APPEARANCE_PRE_STRATEGY,
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
    to_jsonable_value,
)
from ..utils.episode import BatchWindow, iter_episode_batches
from ..utils.logger import get_logger
from ..workflow_ids import (
    APPEARANCE_ALIAS_NAMING_RULES_VAR,
    APPEARANCE_MAPPING_VAR,
    APPEARANCE_PRE_STRATEGY_REQUIREMENTS_VAR,
    APPEARANCE_REQUIREMENTS_VAR,
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
    FRAMEWORK_ALIAS_NAMING_RULES_VAR,
    FRAMEWORK_APPEARANCE_REQUIREMENTS_VAR,
    HOOK_CURRENT_VAR,
    HOOK_START_VAR,
    HOOK_FINAL_VAR,
    MEMORY_VAR,
    OUTFIT_SWITCH_RULES_VAR,
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
LOCAL_CURRENT_BATCH_INDEX = "_current_batch_index"
LOCAL_CURRENT_BATCH_STAGE = "_current_batch_stage"
LOCAL_REWRITE_FROM_STAGE = "_rewrite_from_stage"
LOCAL_SCRIPT_BATCHES = "_script_batches"
LOCAL_SUMMARY_BY_BATCH = "_summary_by_batch"
LOCAL_APPEARANCE_MEMORY_BY_BATCH = "_appearance_memory_by_batch"
SCRIPT_STAGE_PAYLOAD_SOFT_LIMIT = 32000
SCRIPT_STAGE_PREVIOUS_SCRIPT_BATCHES = 2


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
    _apply_appearance_outputs_to_variables(variables)
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

    if _has_pre_strategy_outputs(variables):
        _refresh_user_content_baseline(payload, variables)
        set_runtime_stage(
            state,
            "appearance_strategy",
            "已从缓存恢复服装前置策略。",
            progress_percent=6,
        )
    else:
        variables.update(
            _run_fastgpt_stage(
                state,
                runner,
                STAGE_APPEARANCE_PRE_STRATEGY,
                variables,
                stage_key="appearance_strategy",
                message="正在生成服装前置策略。",
                progress_percent=6,
                max_retries=0,
            )
        )
        _refresh_user_content_baseline(payload, variables)
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

    if _normalize_appearance_mapping_object(variables.get(APPEARANCE_MAPPING)):
        _apply_appearance_outputs_to_variables(variables)
        set_runtime_stage(
            state,
            "appearance",
            "已从缓存恢复人物服装版本映射。",
            progress_percent=42,
        )
    else:
        variables.update(
            _run_fastgpt_stage(
                state,
                runner,
                STAGE_APPEARANCE_ALIAS_GENERATION,
                variables,
                stage_key="appearance",
                message="正在生成人物服装版本映射。",
                progress_percent=42,
            )
        )
        if not _apply_appearance_outputs_to_variables(variables):
            raise ValueError("人物服装版本映射阶段返回内容不可解析，未得到合法 appearance_mapping。")
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
        CHARACTER_APPEARANCE_REQUIREMENTS: str(payload.character_appearance_requirements or "").strip(),
        CHARACTER_ALIAS_NAMING_RULES: str(payload.character_alias_naming_rules or "").strip(),
        OUTFIT_SWITCH_RULES: str(payload.outfit_switch_rules or "").strip(),
        EPISODE_PLAN: payload.episode_plan,
        STORY_OUTLINE: payload.story_outline,
        USER_SCENES: payload.core_scene_input,
        USER_CHARACTERS: payload.character_bios,
        APPEARANCE_MAPPING: {},
        CHARACTER_REGISTRY: {},
        CHARACTER_ALIAS_REGISTRY: {},
        EPISODE_ALIAS_PLAN: {},
        APPEARANCE_CONTINUITY_MEMORY: {},
        SCENE_APPEARANCE_REQUIREMENTS: {},
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
    appearance_requirements_value: str | None = None,
    alias_naming_rules_value: str | None = None,
    outfit_switch_rules_value: str | None = None,
) -> str:
    baseline = {
        SCRIPT_TITLE: script_title if script_title is not None else payload.title,
        TOTAL_EPISODES: payload.total_episodes,
        EPISODE_WORD_COUNT: payload.episode_word_count,
        CHARACTER_APPEARANCE_REQUIREMENTS: (
            appearance_requirements_value
            if appearance_requirements_value is not None
            else _merge_optional_text(
                payload.character_appearance_requirements,
                payload.outfit_switch_rules,
            )
        ),
        CHARACTER_ALIAS_NAMING_RULES: (
            alias_naming_rules_value
            if alias_naming_rules_value is not None
            else payload.character_alias_naming_rules
        ),
        OUTFIT_SWITCH_RULES: (
            outfit_switch_rules_value
            if outfit_switch_rules_value is not None
            else payload.outfit_switch_rules
        ),
        STORY_OUTLINE: story_outline_value if story_outline_value is not None else payload.story_outline,
        USER_SCENES: user_scenes_value if user_scenes_value is not None else payload.core_scene_input,
        USER_CHARACTERS: user_characters_value if user_characters_value is not None else payload.character_bios,
        EPISODE_PLAN: episode_plan_value if episode_plan_value is not None else payload.episode_plan,
    }
    return json.dumps(baseline, ensure_ascii=False, indent=2)


def _current_appearance_requirements_text(
    variables: dict[str, Any],
    payload: WorkflowInput,
) -> str:
    return _merge_optional_text(
        variables.get(CHARACTER_APPEARANCE_REQUIREMENTS),
        variables.get(OUTFIT_SWITCH_RULES),
        payload.character_appearance_requirements,
        payload.outfit_switch_rules,
    )


def _current_alias_naming_rules_text(
    variables: dict[str, Any],
    payload: WorkflowInput,
) -> str:
    return str(
        variables.get(CHARACTER_ALIAS_NAMING_RULES)
        or payload.character_alias_naming_rules
        or ""
    ).strip()


def _current_outfit_switch_rules_text(
    variables: dict[str, Any],
    payload: WorkflowInput,
) -> str:
    return str(variables.get(OUTFIT_SWITCH_RULES) or payload.outfit_switch_rules or "").strip()


def _refresh_user_content_baseline(
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> None:
    variables[USER_CONTENT_BASELINE] = _build_user_content_baseline(
        payload,
        script_title=str(variables.get(SCRIPT_TITLE) or payload.title or "").strip() or "AI原创剧本",
        story_outline_value=str(variables.get(STORY_OUTLINE) or payload.story_outline or "").strip(),
        user_scenes_value=str(variables.get(USER_SCENES) or payload.core_scene_input or "").strip(),
        user_characters_value=str(variables.get(USER_CHARACTERS) or payload.character_bios or "").strip(),
        episode_plan_value=str(variables.get(EPISODE_PLAN) or payload.episode_plan or "").strip(),
        appearance_requirements_value=_current_appearance_requirements_text(variables, payload),
        alias_naming_rules_value=_current_alias_naming_rules_text(variables, payload),
        outfit_switch_rules_value=_current_outfit_switch_rules_text(variables, payload),
    )


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
    all_hooks = _dict_or_empty(variables.get(ALL_HOOKS))
    all_dialogues = _dict_or_empty(variables.get(ALL_DIALOGUES))
    committed_script = str(
        variables.get(LOCAL_COMMITTED_SCRIPT) or variables.get(ALL_SCRIPT) or ""
    ).strip()
    script_batches = _normalize_batch_text_map(variables.get(LOCAL_SCRIPT_BATCHES))
    summary_by_batch = _normalize_batch_text_map(variables.get(LOCAL_SUMMARY_BY_BATCH))
    appearance_memory_by_batch = _normalize_batch_object_map(
        variables.get(LOCAL_APPEARANCE_MEMORY_BY_BATCH)
    )
    completed_batches = min(
        total_batches,
        max(0, _safe_int(variables.get(LOCAL_COMPLETED_BATCHES), 0)),
    )
    current_batch_index = max(
        completed_batches,
        _safe_int(variables.get(LOCAL_CURRENT_BATCH_INDEX), completed_batches),
    )
    current_batch_stage = str(variables.get(LOCAL_CURRENT_BATCH_STAGE) or "").strip().lower()
    rewrite_from_stage = str(variables.get(LOCAL_REWRITE_FROM_STAGE) or "").strip().lower()
    normalized_plan = _normalize_episode_plan_object(variables.get(NORMALIZED_EPISODE_PLAN))
    episode_alias_plan = _normalize_episode_alias_plan_object(variables.get(EPISODE_ALIAS_PLAN))

    if rewrite_from_stage == "final" and _has_value(variables.get(ALL_SCRIPT)):
        set_runtime_stage(
            state,
            "script",
            "已保留剧本正文，将直接重新执行最终剧本拼接。",
            progress_percent=98,
            generated_episodes=total_episodes,
        )
        variables[LOCAL_REWRITE_FROM_STAGE] = ""
        _sync_state_variables(state, variables)
        return

    for index, batch in enumerate(batches):
        if index < completed_batches:
            continue
        resume_stage = current_batch_stage if index == current_batch_index else ""
        plan_for_batch = get_episode_batch_payload(
            normalized_plan,
            batch.start_episode,
            batch_size=batch.size,
            raw_episode_plan=str(variables.get(EPISODE_PLAN) or payload.episode_plan or ""),
        )
        alias_plan_for_batch = slice_episode_alias_plan_for_batch(episode_alias_plan, batch)
        variables[BATCH_START_EPISODE] = batch.start_episode
        variables[LOCAL_CURRENT_BATCH_INDEX] = index
        batch_base = dict(variables)
        batch_base[EPISODE_PLAN] = plan_for_batch
        batch_base[EPISODE_ALIAS_PLAN] = alias_plan_for_batch or {}
        batch_base[APPEARANCE_CONTINUITY_MEMORY] = _appearance_memory_for_batch(
            variables.get(APPEARANCE_CONTINUITY_MEMORY),
            alias_plan_for_batch,
        )

        hook_progress = 36 + int((index / total_batches) * 12)
        force_skip_hook = rewrite_from_stage in {"dialogue", "script"} and bool(all_hooks)
        cached_batch_hooks = (
            slice_object_episodes_for_batch(all_hooks, batch) if force_skip_hook else {}
        )
        if force_skip_hook and cached_batch_hooks:
            variables[BATCH_HOOKS] = cached_batch_hooks
            variables[LOCAL_CURRENT_BATCH_STAGE] = "hook"
            set_runtime_stage(
                state,
                "hook",
                f"已保留第 {batch.label} 集开头冲突钩子，将从后续步骤开始重写。",
                batch_label=batch.label,
                progress_percent=hook_progress,
            )
        elif resume_stage in {"hook", "dialogue", "script"} and _has_value(variables.get(BATCH_HOOKS)):
            set_runtime_stage(
                state,
                "hook",
                f"已停在第 {batch.label} 集开头冲突钩子的成功检查点。",
                batch_label=batch.label,
                progress_percent=hook_progress,
            )
        else:
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
            variables[LOCAL_CURRENT_BATCH_STAGE] = "hook"
        _sync_state_variables(state, variables)

        dialogue_base = dict(variables)
        dialogue_base[EPISODE_PLAN] = plan_for_batch
        dialogue_base[BATCH_START_EPISODE] = batch.start_episode
        dialogue_base[EPISODE_ALIAS_PLAN] = alias_plan_for_batch or {}
        dialogue_base[APPEARANCE_CONTINUITY_MEMORY] = _appearance_memory_for_batch(
            variables.get(APPEARANCE_CONTINUITY_MEMORY),
            alias_plan_for_batch,
        )
        dialogue_progress = 50 + int((index / total_batches) * 12)
        force_skip_dialogue = rewrite_from_stage == "script" and bool(all_dialogues)
        cached_batch_dialogues = (
            slice_object_episodes_for_batch(all_dialogues, batch) if force_skip_dialogue else {}
        )
        if force_skip_dialogue and cached_batch_dialogues:
            variables[BATCH_DIALOGUES] = cached_batch_dialogues
            variables[LOCAL_CURRENT_BATCH_STAGE] = "dialogue"
            set_runtime_stage(
                state,
                "dialogue",
                f"已保留第 {batch.label} 集角色对白，将从剧本正文开始重写。",
                batch_label=batch.label,
                progress_percent=dialogue_progress,
            )
        elif resume_stage in {"dialogue", "script"} and _has_value(variables.get(BATCH_DIALOGUES)):
            set_runtime_stage(
                state,
                "dialogue",
                f"已停在第 {batch.label} 集角色对话的成功检查点。",
                batch_label=batch.label,
                progress_percent=dialogue_progress,
            )
        else:
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
            variables[LOCAL_CURRENT_BATCH_STAGE] = "dialogue"
        _sync_state_variables(state, variables)

        script_base = _build_script_stage_context(
            variables,
            batch=batch,
            plan_for_batch=plan_for_batch,
            alias_plan_for_batch=alias_plan_for_batch,
            committed_script=committed_script,
            script_batches=script_batches,
        )
        script_progress = 68 + int((index / total_batches) * 26)
        if resume_stage == "script" and _has_value(variables.get(BATCH_SCRIPT)):
            batch_script = str(variables.get(BATCH_SCRIPT) or "").strip()
            variables[ALL_SCRIPT] = str(
                variables.get(ALL_SCRIPT) or _join_script_parts(committed_script, batch_script)
            )
            script_batches[batch.start_episode] = batch_script
            variables[LOCAL_SCRIPT_BATCHES] = _string_keyed_batch_map(script_batches)
            set_runtime_stage(
                state,
                "script",
                f"已停在第 {batch.label} 集剧本正文的成功检查点。",
                batch_label=batch.label,
                progress_percent=script_progress,
                generated_episodes=min(total_episodes, index * batch_size),
            )
        else:
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
            variables[BATCH_SCRIPT] = batch_script
            variables[ALL_SCRIPT] = _join_script_parts(committed_script, batch_script)
            script_batches[batch.start_episode] = batch_script
            variables[LOCAL_SCRIPT_BATCHES] = _string_keyed_batch_map(script_batches)
            variables[LOCAL_CURRENT_BATCH_STAGE] = "script"
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
        variables[APPEARANCE_CONTINUITY_MEMORY] = _update_appearance_continuity_memory(
            variables.get(APPEARANCE_CONTINUITY_MEMORY),
            alias_plan_for_batch,
            batch=batch,
        )
        summary_by_batch[batch.start_episode] = str(variables[LAST_SUMMARY] or "").strip()
        appearance_memory_by_batch[batch.start_episode] = copy.deepcopy(
            _normalize_appearance_memory(variables.get(APPEARANCE_CONTINUITY_MEMORY)) or {}
        )
        variables[LOCAL_SUMMARY_BY_BATCH] = _string_keyed_batch_map(summary_by_batch)
        variables[LOCAL_APPEARANCE_MEMORY_BY_BATCH] = _string_keyed_batch_map(
            appearance_memory_by_batch
        )
        variables[LOCAL_COMPLETED_BATCHES] = index + 1
        variables[LOCAL_COMMITTED_SCRIPT] = variables[ALL_SCRIPT]
        committed_script = str(variables.get(LOCAL_COMMITTED_SCRIPT) or "").strip()
        variables[LOCAL_CURRENT_BATCH_INDEX] = index + 1
        variables[LOCAL_CURRENT_BATCH_STAGE] = ""
        variables[LOCAL_REWRITE_FROM_STAGE] = ""
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


def _join_script_parts(*parts: Any) -> str:
    normalized: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if text:
            normalized.append(text)
    return "\n\n".join(normalized)


def _normalize_batch_text_map(value: Any) -> dict[int, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[int, str] = {}
    for key, item in value.items():
        episode = _safe_int(key, 0)
        if episode <= 0:
            continue
        text = str(item or "").strip()
        if text:
            normalized[episode] = text
    return normalized


def _normalize_batch_object_map(value: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[int, dict[str, Any]] = {}
    for key, item in value.items():
        episode = _safe_int(key, 0)
        if episode <= 0 or not isinstance(item, dict):
            continue
        normalized[episode] = copy.deepcopy(item)
    return normalized


def _string_keyed_batch_map(value: dict[int, Any]) -> dict[str, Any]:
    return {str(int(key)): copy.deepcopy(item) for key, item in sorted(value.items()) if int(key) > 0}


def _run_full_fastgpt_generation(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> None:
    alias_plan = _normalize_episode_alias_plan_object(variables.get(EPISODE_ALIAS_PLAN))
    variables[EPISODE_PLAN] = get_episode_batch_payload(
        _normalize_episode_plan_object(variables.get(NORMALIZED_EPISODE_PLAN)),
        1,
        batch_size=payload.total_episodes,
        raw_episode_plan=str(variables.get(EPISODE_PLAN) or payload.episode_plan or ""),
    )
    variables[BATCH_START_EPISODE] = 1
    variables[EPISODE_ALIAS_PLAN] = slice_episode_alias_plan_for_batch(
        alias_plan,
        BatchWindow(start_episode=1, end_episode=max(1, payload.total_episodes)),
    ) or {}

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

    script_variables = _build_script_stage_context(
        variables,
        batch=BatchWindow(start_episode=1, end_episode=max(1, payload.total_episodes)),
        plan_for_batch=variables[EPISODE_PLAN],
        alias_plan_for_batch=variables.get(EPISODE_ALIAS_PLAN) or {},
        committed_script=str(variables.get(ALL_SCRIPT) or "").strip(),
        script_batches=_normalize_batch_text_map(variables.get(LOCAL_SCRIPT_BATCHES)),
    )
    script_output = _run_fastgpt_stage(
        state,
        runner,
        STAGE_SCRIPT,
        script_variables,
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
    variables[APPEARANCE_CONTINUITY_MEMORY] = _update_appearance_continuity_memory(
        variables.get(APPEARANCE_CONTINUITY_MEMORY),
        variables.get(EPISODE_ALIAS_PLAN),
        batch=BatchWindow(start_episode=1, end_episode=max(1, payload.total_episodes)),
    )
    _sync_state_variables(state, variables)

    set_runtime_stage(
        state,
        "script",
        "剧本正文阶段完成。",
        progress_percent=98,
        generated_episodes=payload.total_episodes,
    )
    sync_runtime_state(state)


def _build_script_stage_context(
    variables: dict[str, Any],
    *,
    batch: BatchWindow,
    plan_for_batch: str,
    alias_plan_for_batch: dict[str, Any] | None,
    committed_script: str,
    script_batches: dict[int, str] | None = None,
) -> dict[str, Any]:
    context = dict(variables)
    context[EPISODE_PLAN] = plan_for_batch
    context[BATCH_START_EPISODE] = batch.start_episode
    context[EPISODE_ALIAS_PLAN] = alias_plan_for_batch or {}
    context[APPEARANCE_CONTINUITY_MEMORY] = _appearance_memory_for_batch(
        variables.get(APPEARANCE_CONTINUITY_MEMORY),
        alias_plan_for_batch,
    )
    context[ALL_HOOKS] = slice_object_episodes_for_batch(variables.get(ALL_HOOKS), batch)
    context[ALL_DIALOGUES] = slice_object_episodes_for_batch(variables.get(ALL_DIALOGUES), batch)
    context[ALL_SCRIPT] = _build_previous_script_context(
        script_batches or {},
        committed_script,
        current_batch_start=batch.start_episode,
    )

    estimated_before = _estimate_stage_payload_length(STAGE_SCRIPT, context)
    estimated_after, compressed_fields = _apply_script_stage_length_guard(context, estimated_before)
    if compressed_fields:
        logger.warning(
            "剧本正文 %s 集上下文过长，已压缩：%s；payload 估算长度 %s -> %s",
            batch.label,
            "、".join(compressed_fields),
            estimated_before,
            estimated_after,
        )
    else:
        logger.info("剧本正文 %s 集 payload 估算长度：%s", batch.label, estimated_after)
    return context


def _build_previous_script_context(
    script_batches: dict[int, str],
    committed_script: str,
    *,
    current_batch_start: int,
) -> str:
    if current_batch_start <= 1:
        return ""

    previous_parts: list[str] = []
    previous_starts = sorted(start for start in script_batches if start < current_batch_start)
    for start in previous_starts[-SCRIPT_STAGE_PREVIOUS_SCRIPT_BATCHES:]:
        text = str(script_batches.get(start) or "").strip()
        if text:
            previous_parts.append(text)
    if previous_parts:
        return _join_script_parts(*previous_parts)
    return _trim_text_tail(committed_script, max_chars=12000)


def _apply_script_stage_length_guard(
    context: dict[str, Any],
    initial_estimate: int | None = None,
) -> tuple[int, list[str]]:
    estimate = initial_estimate or _estimate_stage_payload_length(STAGE_SCRIPT, context)
    if estimate <= SCRIPT_STAGE_PAYLOAD_SOFT_LIMIT:
        return estimate, []

    compressed_fields: list[str] = []
    strategies: tuple[tuple[str, str, tuple[int, ...], Any], ...] = (
        (ALL_SCRIPT, "previous_batch_summary", (12000, 8000, 5000), _trim_text_tail),
        (ALL_DIALOGUES, "dialogues", (520, 320, 200), _compact_nested_strings),
        (LAST_SUMMARY, "script_memory", (3600, 2200, 1200), _trim_text_tail),
        (ALL_HOOKS, "hooks", (520, 320, 200), _compact_nested_strings),
    )

    for field_name, label, limits, compressor in strategies:
        if estimate <= SCRIPT_STAGE_PAYLOAD_SOFT_LIMIT:
            break
        for limit in limits:
            current_value = context.get(field_name)
            if not _has_value(current_value):
                break
            candidate = compressor(current_value, max_chars=limit)
            if candidate == current_value:
                continue
            context[field_name] = candidate
            if label not in compressed_fields:
                compressed_fields.append(label)
            estimate = _estimate_stage_payload_length(STAGE_SCRIPT, context)
            if estimate <= SCRIPT_STAGE_PAYLOAD_SOFT_LIMIT:
                break

    return estimate, compressed_fields


def _estimate_stage_payload_length(stage_name: str, variables: dict[str, Any]) -> int:
    return len(
        json.dumps(
            _build_stage_wire_payload_preview(stage_name, variables),
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    )


def _build_stage_wire_payload_preview(stage_name: str, variables: dict[str, Any]) -> dict[str, Any]:
    aliases = LEGACY_INPUT_ALIASES.get(stage_name)
    if not aliases:
        return contract_for(stage_name).build_input_payload(variables)

    payload: dict[str, Any] = {}
    for canonical_name, wire_name in aliases.items():
        if canonical_name in variables:
            value = variables[canonical_name]
            if canonical_name == CHARACTER_APPEARANCE_REQUIREMENTS:
                value = _merge_optional_text(
                    variables.get(CHARACTER_APPEARANCE_REQUIREMENTS),
                    variables.get(OUTFIT_SWITCH_RULES),
                )
            payload[wire_name] = _format_wire_value_for_estimate(value)
            continue
        if canonical_name == LAST_SUMMARY:
            payload[wire_name] = ""
        elif canonical_name in {ALL_HOOKS, ALL_DIALOGUES, ALL_SCRIPT}:
            payload[wire_name] = ""
        elif canonical_name == USER_CONTENT_BASELINE:
            payload[wire_name] = "{}"
        elif canonical_name == MAX_RETRIES:
            payload[wire_name] = settings.max_retries_default
    return payload


def _format_wire_value_for_estimate(value: Any) -> Any:
    jsonable = to_jsonable_value(value)
    if (
        isinstance(jsonable, dict)
        and set(jsonable.keys()) == {"raw"}
        and isinstance(jsonable.get("raw"), str)
    ):
        return jsonable["raw"]
    if isinstance(jsonable, (dict, list)):
        return json.dumps(jsonable, ensure_ascii=False, separators=(",", ":"))
    return jsonable


def _trim_text_tail(value: Any, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    parts = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    if not parts:
        return text[-max_chars:]

    selected: list[str] = []
    remaining = max_chars
    for part in reversed(parts):
        if not part:
            continue
        extra = len(part) + (2 if selected else 0)
        if extra > remaining and selected:
            break
        if extra > remaining:
            selected.append(part[-remaining:])
            remaining = 0
            break
        selected.append(part)
        remaining -= extra
        if remaining <= 0:
            break
    return "\n\n".join(reversed(selected)).strip() or text[-max_chars:]


def _compact_nested_strings(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _compact_nested_strings(item, max_chars=max_chars)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_compact_nested_strings(item, max_chars=max_chars) for item in value]
    if not isinstance(value, str):
        return value

    text = value.strip()
    if len(text) <= max_chars:
        return text
    if max_chars <= 16:
        return text[:max_chars]
    head = max_chars * 3 // 5
    tail = max_chars - head - 5
    if tail <= 0:
        return text[:max_chars]
    return f"{text[:head].rstrip()}\n...\n{text[-tail:].lstrip()}"


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
            if _is_model_connection_error(exc):
                delay_seconds = _transient_retry_delay(attempt)
                retry_message = "模型连接波动，已保留当前进度，正在自动重试。"
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
                    "%s%s第 %s 次尝试遇到模型连接异常，将在 %.0f 秒后自动重试：%s",
                    contract.label,
                    _format_batch_suffix(batch_label),
                    attempt,
                    delay_seconds,
                    exc,
                )
                _sleep_with_checkpoints(state, delay_seconds)
                continue
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


def _is_model_connection_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    if not text:
        return False
    markers = (
        "model connection",
        "model service",
        "upstream model",
        "upstream service",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "connection refused",
        "connection timed out",
        "read timed out",
        "connect timeout",
        "socket hang up",
        "broken pipe",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "eof",
        "模型连接",
        "模型服务",
        "上游模型",
        "连接异常",
        "连接失败",
        "连接超时",
        "读取超时",
        "网关错误",
        "服务不可用",
    )
    return any(marker in text for marker in markers)


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
    if CHARACTER_APPEARANCE_REQUIREMENTS in variables:
        merged_appearance_requirements = _merge_optional_text(
            variables[CHARACTER_APPEARANCE_REQUIREMENTS],
            variables.get(OUTFIT_SWITCH_RULES),
        )
        state.set_var(APPEARANCE_PRE_STRATEGY_REQUIREMENTS_VAR, variables[CHARACTER_APPEARANCE_REQUIREMENTS])
        state.set_var(APPEARANCE_REQUIREMENTS_VAR, merged_appearance_requirements)
        state.set_var(FRAMEWORK_APPEARANCE_REQUIREMENTS_VAR, merged_appearance_requirements)
    if CHARACTER_ALIAS_NAMING_RULES in variables:
        state.set_var(APPEARANCE_ALIAS_NAMING_RULES_VAR, variables[CHARACTER_ALIAS_NAMING_RULES])
        state.set_var(FRAMEWORK_ALIAS_NAMING_RULES_VAR, variables[CHARACTER_ALIAS_NAMING_RULES])
    if OUTFIT_SWITCH_RULES in variables:
        state.set_var(OUTFIT_SWITCH_RULES_VAR, variables[OUTFIT_SWITCH_RULES])
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
    if SCENE_APPEARANCE_REQUIREMENTS in variables:
        state.set_var(SCENE_APPEARANCE_REQUIREMENTS, variables[SCENE_APPEARANCE_REQUIREMENTS])
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
        state.set_var(ALL_SCRIPT, variables[ALL_SCRIPT])
    if LAST_SUMMARY in variables:
        state.set_var(MEMORY_VAR, variables[LAST_SUMMARY])
    if APPEARANCE_MAPPING in variables:
        normalized_mapping = _normalize_appearance_mapping_object(variables[APPEARANCE_MAPPING])
        if normalized_mapping is not None:
            state.set_var(APPEARANCE_MAPPING, normalized_mapping)
            state.set_var(APPEARANCE_MAPPING_VAR, json.dumps(normalized_mapping, ensure_ascii=False))
    if CHARACTER_REGISTRY in variables:
        state.set_var(CHARACTER_REGISTRY, variables[CHARACTER_REGISTRY])
    if CHARACTER_ALIAS_REGISTRY in variables:
        state.set_var(CHARACTER_ALIAS_REGISTRY, variables[CHARACTER_ALIAS_REGISTRY])
    if EPISODE_ALIAS_PLAN in variables:
        normalized_alias_plan = _normalize_episode_alias_plan_object(variables[EPISODE_ALIAS_PLAN])
        if normalized_alias_plan is not None:
            state.set_var(EPISODE_ALIAS_PLAN, normalized_alias_plan)
    if APPEARANCE_CONTINUITY_MEMORY in variables:
        normalized_memory = _normalize_appearance_memory(variables[APPEARANCE_CONTINUITY_MEMORY])
        if normalized_memory is not None:
            state.set_var(APPEARANCE_CONTINUITY_MEMORY, normalized_memory)
    if FINAL_SCRIPT in variables:
        state.set_var(FINAL_SCRIPT, variables[FINAL_SCRIPT])
        state.final_output_text = str(variables[FINAL_SCRIPT] or "").strip()

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
        if ALL_SCRIPT not in variables:
            restored_all_script = restored_variables.get(ALL_SCRIPT)
            if not _has_value(restored_all_script):
                restored_all_script = restored_variables.get(SCRIPT_FINAL_VAR)
            if _has_value(restored_all_script):
                variables[ALL_SCRIPT] = restored_all_script
        if FINAL_SCRIPT not in variables:
            restored_final_script = restored_variables.get(FINAL_SCRIPT)
            if not _has_value(restored_final_script):
                restored_final_script = debug_state.get("final_output_text")
            if _has_value(restored_final_script):
                variables[FINAL_SCRIPT] = restored_final_script
        if NORMALIZED_EPISODE_PLAN not in variables:
            normalized_alias = restored_variables.get(EPISODE_PLAN_NORMALIZED_VAR)
            normalized_plan = _normalize_episode_plan_object(normalized_alias)
            if normalized_plan is not None:
                variables[NORMALIZED_EPISODE_PLAN] = normalized_plan
        state.variables.update(restored_variables)
        if ALL_SCRIPT in variables:
            state.set_var(ALL_SCRIPT, variables[ALL_SCRIPT])
        if FINAL_SCRIPT in variables:
            state.set_var(FINAL_SCRIPT, variables[FINAL_SCRIPT])
        restored_final_text = str(debug_state.get("final_output_text") or variables.get(FINAL_SCRIPT) or "").strip()
        if restored_final_text:
            state.final_output_text = restored_final_text

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
    _refresh_user_content_baseline(payload, variables)
    return normalized_plan


def _has_framework_outputs(variables: dict[str, Any]) -> bool:
    return all(
        _has_value(variables.get(name))
        for name in (STORY_OUTLINE, USER_CHARACTERS, USER_SCENES, EPISODE_PLAN)
    )


def _has_pre_strategy_outputs(variables: dict[str, Any]) -> bool:
    return all(
        _has_value(variables.get(name))
        for name in (
            CHARACTER_APPEARANCE_REQUIREMENTS,
            CHARACTER_ALIAS_NAMING_RULES,
            OUTFIT_SWITCH_RULES,
        )
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
    _refresh_user_content_baseline(payload, variables)
    return True


def _merge_optional_text(*parts: Any) -> str:
    merged: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = str(part or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return "\n".join(merged).strip()


def _apply_appearance_outputs_to_variables(variables: dict[str, Any]) -> bool:
    normalized_mapping = _normalize_appearance_mapping_object(variables.get(APPEARANCE_MAPPING))
    if normalized_mapping is None:
        return False

    normalized_plan = _normalize_episode_plan_object(variables.get(NORMALIZED_EPISODE_PLAN))
    character_registry = _build_character_registry(normalized_mapping)
    character_alias_registry = _build_character_alias_registry(normalized_mapping)
    episode_alias_plan = _build_episode_alias_plan(normalized_plan, normalized_mapping)
    scene_requirements = _extract_scene_appearance_requirements(variables.get(SCENES))

    variables[APPEARANCE_MAPPING] = normalized_mapping
    variables[CHARACTER_REGISTRY] = character_registry
    variables[CHARACTER_ALIAS_REGISTRY] = character_alias_registry
    variables[EPISODE_ALIAS_PLAN] = episode_alias_plan
    variables[SCENE_APPEARANCE_REQUIREMENTS] = scene_requirements
    if not _normalize_appearance_memory(variables.get(APPEARANCE_CONTINUITY_MEMORY)):
        variables[APPEARANCE_CONTINUITY_MEMORY] = _initialize_appearance_continuity_memory(
            character_registry,
            character_alias_registry,
        )
    return True


def _normalize_appearance_mapping_object(value: Any) -> dict[str, Any] | None:
    candidate = value
    if candidate in (None, ""):
        return None
    if isinstance(candidate, str):
        text = candidate.strip()
        if not text:
            return None
        try:
            candidate = json.loads(text)
        except Exception:
            return None
    if not isinstance(candidate, dict):
        return None
    mapping = candidate.get("appearance_mapping") if isinstance(candidate.get("appearance_mapping"), dict) else candidate
    characters = mapping.get("characters")
    if not isinstance(characters, list):
        return None

    normalized_characters: list[dict[str, Any]] = []
    for item in characters:
        if not isinstance(item, dict):
            continue
        character_id = str(item.get("character_id") or "").strip()
        canonical_name = str(item.get("canonical_name") or "").strip()
        if not character_id and not canonical_name:
            continue
        variants: list[dict[str, Any]] = []
        for variant in item.get("outfit_variants") or []:
            if not isinstance(variant, dict):
                continue
            alias_name = _normalize_alias_display_name(variant.get("alias_name") or "")
            if not alias_name:
                continue
            variants.append(
                {
                    "variant_id": str(variant.get("variant_id") or alias_name).strip(),
                    "alias_name": alias_name,
                    "applicable_identity_state": str(variant.get("applicable_identity_state") or "").strip(),
                    "outfit_type": str(variant.get("outfit_type") or "").strip(),
                    "outfit_description": str(variant.get("outfit_description") or "").strip(),
                    "visual_keypoints": _string_list(variant.get("visual_keypoints")),
                    "episode_range_hint": str(variant.get("episode_range_hint") or "").strip(),
                    "scene_trigger_rules": _normalize_scene_trigger_rules(variant.get("scene_trigger_rules")),
                    "usage_rule": str(variant.get("usage_rule") or "").strip(),
                    "must_use_when_triggered": bool(variant.get("must_use_when_triggered", True)),
                    "fallback_allowed": bool(variant.get("fallback_allowed", False)),
                    "same_person_confirmation": str(variant.get("same_person_confirmation") or "").strip(),
                }
            )

        normalized_characters.append(
            {
                "character_id": character_id or canonical_name,
                "canonical_name": canonical_name or character_id,
                "story_role": str(item.get("story_role") or "").strip(),
                "same_person_anchor": _normalize_same_person_anchor(item.get("same_person_anchor")),
                "default_name": str(item.get("default_name") or canonical_name or character_id).strip(),
                "forbidden_generic_names": _string_list(item.get("forbidden_generic_names")),
                "outfit_variants": variants,
            }
        )

    if not normalized_characters:
        return None

    normalized = {
        "appearance_mapping": {
            "mapping_principle": str(mapping.get("mapping_principle") or "").strip(),
            "global_naming_style": str(mapping.get("global_naming_style") or "").strip(),
            "characters": normalized_characters,
            "episode_level_usage_plan": _normalize_usage_plan_items(mapping.get("episode_level_usage_plan")),
            "scene_level_usage_plan": _normalize_scene_usage_plan(mapping.get("scene_level_usage_plan")),
            "special_naming_rules": _string_list(mapping.get("special_naming_rules")),
        }
    }
    return normalized


def _normalize_same_person_anchor(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    return {
        "stable_appearance_traits": _string_list(value.get("stable_appearance_traits")),
        "stable_recognition_points": _string_list(value.get("stable_recognition_points")),
        "unchanged_core_impression": str(value.get("unchanged_core_impression") or "").strip(),
    }


def _normalize_scene_trigger_rules(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    return {
        "scene_names": _string_list(value.get("scene_names")),
        "scene_types": _string_list(value.get("scene_types")),
        "environment_or_time": _string_list(value.get("environment_or_time")),
        "status_conditions": _string_list(value.get("status_conditions")),
    }


def _normalize_usage_plan_items(items: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return normalized
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "episode_range": str(item.get("episode_range") or "").strip(),
                "main_character_aliases": _normalize_alias_usage_list(item.get("main_character_aliases")),
            }
        )
    return normalized


def _normalize_scene_usage_plan(items: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return normalized
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "scene_name": str(item.get("scene_name") or "").strip(),
                "expected_alias_usage": _normalize_alias_usage_list(item.get("expected_alias_usage")),
            }
        )
    return normalized


def _normalize_alias_usage_list(items: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return normalized
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "character_id": str(item.get("character_id") or item.get("character_name") or "").strip(),
                "character_name": str(item.get("character_name") or item.get("canonical_name") or "").strip(),
                "recommended_alias_name": _normalize_alias_display_name(
                    item.get("recommended_alias_name") or item.get("alias_name") or ""
                ),
                "switch_type": str(item.get("switch_type") or "").strip(),
                "reason": str(item.get("reason") or "").strip(),
            }
        )
    return [item for item in normalized if item["recommended_alias_name"]]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _normalize_alias_display_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "【" in text and "】" in text:
        return text
    if "_" not in text:
        return text

    base, note = text.split("_", 1)
    base = base.strip()
    note = note.strip()
    if not base or not note:
        return text
    if not re.search(r"[\u4e00-\u9fff]", base):
        return text
    if any(bracket in note for bracket in "【】[]()（）"):
        return text
    return f"{base}【{note}】"


def _build_character_registry(appearance_mapping: dict[str, Any]) -> dict[str, Any]:
    mapping = appearance_mapping.get("appearance_mapping") or {}
    characters = mapping.get("characters") or []
    return {
        "global_naming_style": str(mapping.get("global_naming_style") or "").strip(),
        "characters": [
            {
                "character_id": item.get("character_id"),
                "canonical_name": item.get("canonical_name"),
                "story_role": item.get("story_role"),
                "default_name": item.get("default_name"),
                "same_person_anchor": copy.deepcopy(item.get("same_person_anchor") or {}),
                "forbidden_generic_names": copy.deepcopy(item.get("forbidden_generic_names") or []),
            }
            for item in characters
            if isinstance(item, dict)
        ],
    }


def _build_character_alias_registry(appearance_mapping: dict[str, Any]) -> dict[str, Any]:
    mapping = appearance_mapping.get("appearance_mapping") or {}
    characters = mapping.get("characters") or []
    aliases_by_name: dict[str, dict[str, Any]] = {}
    character_entries: list[dict[str, Any]] = []
    for item in characters:
        if not isinstance(item, dict):
            continue
        aliases: list[dict[str, Any]] = []
        for variant in item.get("outfit_variants") or []:
            if not isinstance(variant, dict):
                continue
            alias_name = _normalize_alias_display_name(variant.get("alias_name") or "")
            if not alias_name:
                continue
            alias_entry = {
                "character_id": item.get("character_id"),
                "canonical_name": item.get("canonical_name"),
                "alias_name": alias_name,
                "variant_id": str(variant.get("variant_id") or alias_name).strip(),
                "usage_rule": str(variant.get("usage_rule") or "").strip(),
                "scene_trigger_rules": copy.deepcopy(variant.get("scene_trigger_rules") or {}),
                "fallback_allowed": bool(variant.get("fallback_allowed", False)),
                "must_use_when_triggered": bool(variant.get("must_use_when_triggered", True)),
            }
            aliases.append(alias_entry)
            aliases_by_name[alias_name] = alias_entry
        character_entries.append(
            {
                "character_id": item.get("character_id"),
                "canonical_name": item.get("canonical_name"),
                "default_name": item.get("default_name"),
                "forbidden_generic_names": copy.deepcopy(item.get("forbidden_generic_names") or []),
                "aliases": aliases,
            }
        )
    return {
        "global_naming_style": str(mapping.get("global_naming_style") or "").strip(),
        "mapping_principle": str(mapping.get("mapping_principle") or "").strip(),
        "characters": character_entries,
        "aliases_by_name": aliases_by_name,
    }


def _build_episode_alias_plan(
    normalized_plan: dict[str, Any] | None,
    appearance_mapping: dict[str, Any],
) -> dict[str, Any]:
    mapping = appearance_mapping.get("appearance_mapping") or {}
    normalized = _normalize_episode_plan_object(normalized_plan) or {"parsed_episode_count": 0, "episodes": []}
    planning = normalized.get("appearance_alias_planning") or {}
    episode_usage = mapping.get("episode_level_usage_plan") or []

    episodes: list[dict[str, Any]] = []
    for episode_item in normalized.get("episodes") or []:
        if not isinstance(episode_item, dict):
            continue
        episode_no = _coerce_episode_number(episode_item.get("episode"))
        if episode_no is None:
            continue
        merged_aliases = list(episode_item.get("main_character_aliases") or [])
        for usage in episode_usage:
            if not isinstance(usage, dict):
                continue
            if _episode_in_range(episode_no, str(usage.get("episode_range") or "")):
                merged_aliases.extend(usage.get("main_character_aliases") or [])
        episodes.append(
            {
                "episode": episode_no,
                "title": str(episode_item.get("title") or "").strip(),
                "content": str(episode_item.get("content") or "").strip(),
                "main_character_aliases": _dedupe_alias_usage_items(merged_aliases),
                "appearance_events": _string_list(episode_item.get("appearance_events")),
                "long_term_stage_flags": _string_list(episode_item.get("long_term_stage_flags")),
                "scene_based_alias_hints": _normalize_alias_usage_list(episode_item.get("scene_based_alias_hints")),
            }
        )

    return {
        "planning_scope": str(planning.get("planning_scope") or mapping.get("mapping_principle") or "").strip(),
        "global_naming_style": str(
            planning.get("global_naming_style") or mapping.get("global_naming_style") or ""
        ).strip(),
        "global_rules": _string_list(planning.get("global_rules")) + _string_list(mapping.get("special_naming_rules")),
        "episodes": episodes,
        "scene_level_usage_plan": copy.deepcopy(mapping.get("scene_level_usage_plan") or []),
        "uncertain_or_missing_items": _string_list(planning.get("uncertain_or_missing_items")),
    }


def _dedupe_alias_usage_items(items: list[Any]) -> list[dict[str, Any]]:
    normalized = _normalize_alias_usage_list(items)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in normalized:
        key = (str(item.get("character_id") or item.get("character_name") or ""), item["recommended_alias_name"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _episode_in_range(episode_no: int, raw_range: str) -> bool:
    text = str(raw_range or "").strip()
    if not text:
        return False
    numbers = [int(match) for match in re.findall(r"\d+", text)]
    if not numbers:
        return False
    if len(numbers) == 1:
        return numbers[0] == episode_no
    start, end = numbers[0], numbers[1]
    if start > end:
        start, end = end, start
    return start <= episode_no <= end


def _extract_scene_appearance_requirements(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    candidate = value
    if isinstance(candidate, str):
        text = candidate.strip()
        if not text:
            return {}
        try:
            candidate = json.loads(text)
        except Exception:
            return {}
    if not isinstance(candidate, dict):
        return {}
    setting = candidate.get("scene_setting") if isinstance(candidate.get("scene_setting"), dict) else candidate
    scenes = setting.get("scenes")
    if not isinstance(scenes, list):
        return {}
    return {
        "scene_design_principle": str(setting.get("scene_design_principle") or "").strip(),
        "scene_visual_styling_naming_strategy": str(
            setting.get("scene_visual_styling_naming_strategy") or ""
        ).strip(),
        "scenes": [
            {
                "scene_name": str(scene.get("scene_name") or "").strip(),
                "scene_type": str(scene.get("scene_type") or "").strip(),
                "visual_condition_summary": str(scene.get("visual_condition_summary") or "").strip(),
                "styling_condition_summary": str(scene.get("styling_condition_summary") or "").strip(),
                "naming_condition_summary": str(scene.get("naming_condition_summary") or "").strip(),
                "outfit_requirements": _normalize_alias_usage_list(scene.get("outfit_requirements")),
                "alias_usage_rules": _normalize_alias_usage_list(scene.get("alias_usage_rules")),
            }
            for scene in scenes
            if isinstance(scene, dict)
        ],
    }


def _normalize_episode_alias_plan_object(value: Any) -> dict[str, Any] | None:
    if value in (None, "", {}):
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
    if not isinstance(candidate, dict):
        return None
    episodes = candidate.get("episodes")
    if not isinstance(episodes, list):
        return None
    normalized_episodes: list[dict[str, Any]] = []
    for item in episodes:
        if not isinstance(item, dict):
            continue
        episode_no = _coerce_episode_number(item.get("episode"))
        if episode_no is None:
            continue
        normalized_episodes.append(
            {
                "episode": episode_no,
                "title": str(item.get("title") or "").strip(),
                "content": str(item.get("content") or "").strip(),
                "main_character_aliases": _normalize_alias_usage_list(item.get("main_character_aliases")),
                "appearance_events": _string_list(item.get("appearance_events")),
                "long_term_stage_flags": _string_list(item.get("long_term_stage_flags")),
                "scene_based_alias_hints": _normalize_alias_usage_list(item.get("scene_based_alias_hints")),
            }
        )
    return {
        "planning_scope": str(candidate.get("planning_scope") or "").strip(),
        "global_naming_style": str(candidate.get("global_naming_style") or "").strip(),
        "global_rules": _string_list(candidate.get("global_rules")),
        "episodes": normalized_episodes,
        "scene_level_usage_plan": _normalize_scene_usage_plan(candidate.get("scene_level_usage_plan")),
        "uncertain_or_missing_items": _string_list(candidate.get("uncertain_or_missing_items")),
    }


def slice_episode_alias_plan_for_batch(
    episode_alias_plan: Any,
    batch: BatchWindow,
) -> dict[str, Any] | None:
    normalized = _normalize_episode_alias_plan_object(episode_alias_plan)
    if not normalized:
        return None
    selected = [
        copy.deepcopy(item)
        for item in normalized["episodes"]
        if batch.start_episode <= item["episode"] <= batch.end_episode
    ]
    if not selected:
        return None
    return {
        "planning_scope": normalized.get("planning_scope") or "",
        "global_naming_style": normalized.get("global_naming_style") or "",
        "global_rules": copy.deepcopy(normalized.get("global_rules") or []),
        "episodes": selected,
        "scene_level_usage_plan": copy.deepcopy(normalized.get("scene_level_usage_plan") or []),
        "uncertain_or_missing_items": copy.deepcopy(normalized.get("uncertain_or_missing_items") or []),
    }


def _normalize_appearance_memory(value: Any) -> dict[str, Any] | None:
    if value in (None, "", {}):
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
    if not isinstance(candidate, dict):
        return None
    aliases = candidate.get("current_aliases")
    if not isinstance(aliases, dict):
        aliases = {}
    return {
        "last_processed_episode": _safe_int(candidate.get("last_processed_episode"), 0),
        "current_aliases": {
            str(key): _normalize_alias_display_name(val)
            for key, val in aliases.items()
            if str(key).strip() and _normalize_alias_display_name(val)
        },
        "recent_stage_flags": _string_list(candidate.get("recent_stage_flags")),
        "recent_appearance_events": _string_list(candidate.get("recent_appearance_events")),
    }


def _initialize_appearance_continuity_memory(
    character_registry: dict[str, Any],
    character_alias_registry: dict[str, Any],
) -> dict[str, Any]:
    current_aliases: dict[str, str] = {}
    alias_by_name = character_alias_registry.get("aliases_by_name") or {}
    for character in character_registry.get("characters") or []:
        if not isinstance(character, dict):
            continue
        character_id = str(character.get("character_id") or "").strip()
        default_name = str(character.get("default_name") or "").strip()
        if character_id and default_name:
            current_aliases[character_id] = default_name
            continue
        canonical_name = str(character.get("canonical_name") or "").strip()
        if character_id and canonical_name:
            current_aliases[character_id] = canonical_name
    for alias_name, alias_info in alias_by_name.items():
        if not isinstance(alias_info, dict):
            continue
        character_id = str(alias_info.get("character_id") or "").strip()
        if character_id and character_id not in current_aliases:
            current_aliases[character_id] = alias_name
    return {
        "last_processed_episode": 0,
        "current_aliases": current_aliases,
        "recent_stage_flags": [],
        "recent_appearance_events": [],
    }


def _appearance_memory_for_batch(
    current_memory: Any,
    alias_plan_for_batch: dict[str, Any] | None,
) -> dict[str, Any]:
    memory = _normalize_appearance_memory(current_memory) or {
        "last_processed_episode": 0,
        "current_aliases": {},
        "recent_stage_flags": [],
        "recent_appearance_events": [],
    }
    if not alias_plan_for_batch:
        return memory
    batch_aliases = dict(memory.get("current_aliases") or {})
    for episode in alias_plan_for_batch.get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        for alias in episode.get("main_character_aliases") or []:
            if not isinstance(alias, dict):
                continue
            character_id = str(alias.get("character_id") or alias.get("character_name") or "").strip()
            alias_name = _normalize_alias_display_name(alias.get("recommended_alias_name") or "")
            if character_id and alias_name:
                batch_aliases[character_id] = alias_name
    preview = dict(memory)
    preview["current_aliases"] = batch_aliases
    preview["recent_stage_flags"] = _collect_batch_stage_flags(alias_plan_for_batch)
    preview["recent_appearance_events"] = _collect_batch_appearance_events(alias_plan_for_batch)
    return preview


def _update_appearance_continuity_memory(
    current_memory: Any,
    alias_plan_for_batch: dict[str, Any] | None,
    *,
    batch: BatchWindow,
) -> dict[str, Any]:
    updated = _appearance_memory_for_batch(current_memory, alias_plan_for_batch)
    updated["last_processed_episode"] = batch.end_episode
    return updated


def _collect_batch_stage_flags(alias_plan_for_batch: dict[str, Any] | None) -> list[str]:
    flags: list[str] = []
    for episode in (alias_plan_for_batch or {}).get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        for flag in episode.get("long_term_stage_flags") or []:
            text = str(flag or "").strip()
            if text and text not in flags:
                flags.append(text)
    return flags


def _collect_batch_appearance_events(alias_plan_for_batch: dict[str, Any] | None) -> list[str]:
    events: list[str] = []
    for episode in (alias_plan_for_batch or {}).get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        for event in episode.get("appearance_events") or []:
            text = str(event or "").strip()
            if text and text not in events:
                events.append(text)
    return events


def merge_batch_object(current: dict[str, Any], batch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(current or {})
    incoming = copy.deepcopy(batch or {})
    return _merge_dicts(merged, incoming)


def slice_object_episodes_for_batch(value: Any, batch: BatchWindow) -> dict[str, Any]:
    payload = _dict_or_empty(value)
    if not payload:
        return {}
    episodes = payload.get("episodes")
    if not isinstance(episodes, list):
        return copy.deepcopy(payload)
    selected = []
    for item in episodes:
        if not isinstance(item, dict):
            continue
        episode_no = _safe_int(item.get("episode"), 0)
        if batch.start_episode <= episode_no <= batch.end_episode:
            selected.append(copy.deepcopy(item))
    if not selected:
        return {}
    sliced = copy.deepcopy(payload)
    sliced["episodes"] = selected
    batch_meta = sliced.get("batch_meta")
    if isinstance(batch_meta, dict):
        updated_meta = copy.deepcopy(batch_meta)
        updated_meta["start_episode"] = batch.start_episode
        updated_meta["end_episode"] = batch.end_episode
        sliced["batch_meta"] = updated_meta
    return sliced


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
        "appearance_alias_planning": copy.deepcopy(normalized.get("appearance_alias_planning") or {}),
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
                "main_character_aliases": _normalize_alias_usage_list(item.get("main_character_aliases")),
                "appearance_events": _string_list(item.get("appearance_events")),
                "long_term_stage_flags": _string_list(item.get("long_term_stage_flags")),
                "scene_based_alias_hints": _normalize_alias_usage_list(item.get("scene_based_alias_hints")),
            }
        )

    return {
        "parsed_episode_count": len(normalized_episodes),
        "appearance_alias_planning": _normalize_appearance_alias_planning(
            candidate.get("appearance_alias_planning")
        ),
        "episodes": normalized_episodes,
    }


def _normalize_appearance_alias_planning(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    characters = value.get("characters_with_multiple_variants")
    normalized_characters: list[dict[str, Any]] = []
    if isinstance(characters, list):
        for item in characters:
            if not isinstance(item, dict):
                continue
            normalized_characters.append(
                {
                    "character_name": str(item.get("character_name") or "").strip(),
                    "switch_dimensions": _string_list(item.get("switch_dimensions")),
                    "long_term_stage_switches": [
                        {
                            "episode_range": str(entry.get("episode_range") or "").strip(),
                            "recommended_alias_name": _normalize_alias_display_name(
                                entry.get("recommended_alias_name") or ""
                            ),
                            "reason": str(entry.get("reason") or "").strip(),
                        }
                        for entry in (item.get("long_term_stage_switches") or [])
                        if isinstance(entry, dict)
                    ],
                    "scene_based_switches": [
                        {
                            "scene_or_condition": str(entry.get("scene_or_condition") or "").strip(),
                            "recommended_alias_name": _normalize_alias_display_name(
                                entry.get("recommended_alias_name") or ""
                            ),
                            "reason": str(entry.get("reason") or "").strip(),
                        }
                        for entry in (item.get("scene_based_switches") or [])
                        if isinstance(entry, dict)
                    ],
                }
            )
    return {
        "planning_scope": str(value.get("planning_scope") or "").strip(),
        "global_naming_style": str(value.get("global_naming_style") or "").strip(),
        "characters_with_multiple_variants": normalized_characters,
        "global_rules": _string_list(value.get("global_rules")),
        "uncertain_or_missing_items": _string_list(value.get("uncertain_or_missing_items")),
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
