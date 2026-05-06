from __future__ import annotations

import copy
import json
import re
import time
import traceback
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from ..config import ModelOption, settings
from ..models.inputs import WorkflowInput
from ..models.state import WorkflowState
from ..services.compact_context import (
    build_compact_appearance_context_for_batch,
    build_compact_character_context_for_appearance,
    build_compact_character_context_for_dialogues,
    build_compact_character_context_for_dialogues,
    build_compact_character_context_for_hooks,
    build_compact_character_context_for_scenes,
    build_compact_character_context_for_script,
    build_compact_scene_context_for_appearance,
    build_compact_scene_context_for_script,
    build_compact_story_outline_context,
    build_compact_worldview_context,
)
from ..services.fastgpt_client import (
    FastGPTPayloadTooLargeError,
    FastGPTStageFormatError,
    FastGPTTransientError,
    fastgpt_client,
)
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
    FRAMEWORK_NATURAL_LANGUAGE,
    HOOK_MEMORY,
    HOOK_REVIEW_RESULT,
    IS_CONSISTENT,
    LAST_SUMMARY,
    LEGACY_INPUT_ALIASES,
    BLOCKING_ISSUES,
    MAX_RETRIES,
    NORMALIZED_EPISODE_PLAN,
    PASS_REVIEW_JSON,
    REVIEW_PASSED,
    REWRITE_REQUIRED,
    CHARACTER_COUNT,
    OUTFIT_SWITCH_RULES,
    SCENES,
    SCENE_APPEARANCE_REQUIREMENTS,
    DIALOGUE_MEMORY,
    DIALOGUE_REVIEW_RESULT,
    SCRIPT_TITLE,
    SCRIPT_MEMORY,
    SCRIPT_REVIEW_RESULT,
    STAGE_APPEARANCE_ALIAS_GENERATION,
    STAGE_APPEARANCE_ALIAS_REVIEW,
    STAGE_APPEARANCE_ALIAS_REWRITE,
    STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
    STAGE_APPEARANCE_ALIAS_WRITING,
    STAGE_APPEARANCE_PRE_STRATEGY,
    STAGE_FRAMEWORK,
    STAGE_FRAMEWORK_NATURALIZE,
    STAGE_CHARACTERS_NATURALIZE,
    STAGE_CHARACTERS,
    STAGE_CONSISTENCY,
    STAGE_DIALOGUES,
    STAGE_DIALOGUE_MEMORY,
    STAGE_DIALOGUE_REVIEW,
    STAGE_DIALOGUE_REVISE,
    STAGE_DIALOGUE_WRITE,
    STAGE_DIALOGUES_REVIEW,
    STAGE_DIALOGUES_REWRITE,
    STAGE_DIALOGUES_WRITING,
    STAGE_EPISODE_PLAN_NORMALIZE,
    STAGE_FINAL,
    STAGE_HOOKS,
    STAGE_HOOK_MEMORY,
    STAGE_HOOK_REVIEW,
    STAGE_HOOK_REVISE,
    STAGE_HOOK_WRITE,
    STAGE_HOOKS_REVIEW,
    STAGE_HOOKS_REWRITE,
    STAGE_HOOKS_WRITING,
    STAGE_MEMORY,
    STAGE_SCENES,
    STAGE_SCRIPT,
    STAGE_SCRIPT_MEMORY,
    STAGE_SCRIPT_REVIEW,
    STAGE_SCRIPT_REVISE,
    STAGE_SCRIPT_REWRITE,
    STAGE_SCRIPT_WRITE,
    STAGE_SCRIPT_WRITING,
    STAGE_WORLDVIEW,
    STAGE_WORLDVIEW_NATURALIZE,
    STORY_OUTLINE,
    TOTAL_EPISODES,
    UNSTRUCTURED_CONTENT_KIND,
    UNSTRUCTURED_SOURCE,
    USER_EXPECTATION,
    USER_CHARACTERS,
    USER_CONTENT_BASELINE,
    USER_SCENES,
    WORLDVIEW,
    WORLDVIEW_NATURAL_LANGUAGE,
    coerce_strict_fastgpt_boolean,
    contract_for,
    _is_script_family_stage,
    to_jsonable_value,
)
from ..services.json_utils import normalize_pass_review, parse_json
from ..services.stage_output_repair import (
    normalize_appearance_mapping_candidate,
    validate_appearance_mapping_output,
    validate_scenes_output,
)
from ..services.unstructured_naturalize import (
    build_character_unstructured_source,
    build_unstructured_stage_variables,
    character_natural_text_is_usable,
    clean_multiline_character_text,
    extract_unstructured_stage_output_text,
    resolve_unstructured_content_kind,
)
from ..services.workflow_output_validation import (
    WorkflowOutputValidationError,
    build_debug_artifact,
    load_workflow_output_contract,
    resolve_workflow_json_path,
    validate_stage_output_with_workflow_contract,
)
from ..utils.episode import BatchWindow, iter_episode_batches, iter_episode_batches_from
from ..utils.logger import get_logger
from ..utils.user_visible_text import has_meaningful_content, is_meaningful_text
from ..workflow_ids import (
    APPEARANCE_NATURAL_LANGUAGE_VAR,
    APPEARANCE_ALIAS_NAMING_RULES_VAR,
    APPEARANCE_MAPPING_VAR,
    APPEARANCE_PRE_STRATEGY_REQUIREMENTS_VAR,
    APPEARANCE_REQUIREMENTS_VAR,
    APPEARANCE_REVIEW_VAR,
    CHARACTER_BIOS_VAR,
    CHARACTER_NATURAL_LANGUAGE_VAR,
    CHARACTER_VAR,
    CORE_SCENE_INPUT_VAR,
    CORE_SCENE_FINAL_VAR,
    DIALOGUE_CURRENT_VAR,
    DIALOGUE_CURRENT_WORKFLOW_VAR,
    DIALOGUE_CURRENT_WRITE_VAR,
    DIALOGUE_HOOK_BATCH_VAR,
    DIALOGUE_HOOK_MEMORY_VAR,
    DIALOGUE_HOOK_REWRITE_VAR,
    DIALOGUE_HOOK_REVIEW_VAR,
    DIALOGUE_MAX_RETRY_VAR,
    DIALOGUE_MEMORY_INPUT_VAR,
    DIALOGUE_MEMORY_LEGACY_OUTPUT_VAR,
    DIALOGUE_MEMORY_OUTPUT_VAR,
    DIALOGUE_MEMORY_SEARCH_VAR,
    DIALOGUE_RETRY_VAR,
    DIALOGUE_REVIEW_LEGACY_VAR,
    DIALOGUE_REVIEW_OUTPUT_VAR,
    DIALOGUE_REVIEW_WORKFLOW_VAR,
    DIALOGUE_START_VAR,
    DIALOGUE_START_INPUT_VAR,
    DIALOGUE_FINAL_VAR,
    EPISODE_PLAN_VAR,
    EPISODE_PLAN_CURSOR_VAR,
    EPISODE_PLAN_NORMALIZED_VAR,
    FINAL_CHARACTER_VAR,
    FINAL_SCENE_VAR,
    FRAMEWORK_ALIAS_NAMING_RULES_VAR,
    FRAMEWORK_APPEARANCE_REQUIREMENTS_VAR,
    HOOK_CURRENT_VAR,
    HOOK_CURRENT_WRITE_VAR,
    HOOK_MAX_RETRY_VAR,
    HOOK_MEMORY_INPUT_VAR,
    HOOK_MEMORY_OUTPUT_VAR,
    HOOK_MEMORY_REVIEW_VAR,
    HOOK_MEMORY_REVISE_VAR,
    HOOK_RETRY_VAR,
    HOOK_REVIEW_OUTPUT_VAR,
    HOOK_START_VAR,
    HOOK_FINAL_VAR,
    MEMORY_VAR,
    OUTFIT_SWITCH_RULES_VAR,
    SCENE_MAX_RETRY_VAR,
    SCENE_NATURAL_LANGUAGE_VAR,
    SCENE_RETRY_VAR,
    SCENE_VAR,
    SCRIPT_CURRENT_VAR,
    SCRIPT_CURRENT_WRITE_VAR,
    SCRIPT_DIALOGUE_BATCH_VAR,
    SCRIPT_MAX_RETRY_VAR,
    SCRIPT_MEMORY_OUTPUT_VAR,
    SCRIPT_MEMORY_WRITE_INPUT_VAR,
    SCRIPT_RETRY_VAR,
    SCRIPT_REVIEW_OUTPUT_VAR,
    SCRIPT_REVIEW_WRITE_VAR,
    SCRIPT_HOOK_BATCH_VAR,
    SCRIPT_START_VAR,
    SCRIPT_FINAL_VAR,
    STORY_OUTLINE_VAR,
    TITLE_VAR,
    UNSTRUCTURED_KIND_VAR,
    UNSTRUCTURED_OUTPUT_VAR,
    UNSTRUCTURED_SOURCE_VAR,
    WORLDVIEW_VAR,
)
from .runtime_tools import set_runtime_stage, sync_runtime_state

logger = get_logger("fastgpt_hybrid_workflow")
LOCAL_COMPLETED_BATCHES = "_completed_batches"
LOCAL_COMMITTED_SCRIPT = "_committed_all_script"
LOCAL_CURRENT_BATCH_INDEX = "_current_batch_index"
LOCAL_CURRENT_BATCH_STAGE = "_current_batch_stage"
LOCAL_HOOK_CHECKPOINT_START = "_batch_hooks_start_episode"
LOCAL_DIALOGUE_CHECKPOINT_START = "_batch_dialogues_start_episode"
LOCAL_SCRIPT_CHECKPOINT_START = "_batch_script_start_episode"
LOCAL_REWRITE_FROM_STAGE = "_rewrite_from_stage"
LOCAL_SCRIPT_BATCHES = "_script_batches"
LOCAL_SCRIPT_EPISODES = "_script_episode_cache"
LOCAL_SUMMARY_BY_BATCH = "_summary_by_batch"
LOCAL_APPEARANCE_MEMORY_BY_BATCH = "_appearance_memory_by_batch"
LOCAL_RAW_EPISODE_PLAN = "_raw_episode_plan"
SCRIPT_STAGE_PAYLOAD_HARD_LIMIT = max(
    240000,
    int(getattr(settings, "fastgpt_script_payload_hard_limit", 240000)),
)
SCRIPT_STAGE_PAYLOAD_SOFT_LIMIT = min(
    SCRIPT_STAGE_PAYLOAD_HARD_LIMIT - 20000,
    max(
        200000,
        int(getattr(settings, "fastgpt_script_payload_soft_limit", 200000)),
    ),
)
SCRIPT_STAGE_PREVIOUS_SCRIPT_BATCHES = 2
SCRIPT_STAGE_PREVIOUS_BATCH_SUMMARY_MAX_CHARS = max(
    1200,
    int(getattr(settings, "fastgpt_script_previous_batch_summary_max_chars", 4500)),
)
SCRIPT_STAGE_MEMORY_MAX_CHARS = max(
    2000,
    int(getattr(settings, "fastgpt_script_memory_max_chars", 8000)),
)
FRAMEWORK_TITLE_MIN_LENGTH = 2
FRAMEWORK_TEXT_MIN_LENGTH = 10
CONSISTENCY_SELF_CHECK_ATTEMPTS = 2
BATCH_REVIEW_MAX_LOOPS = 10
SCRIPT_AUTO_REPAIR_MAX_RETRIES = 3
SCRIPT_AUTO_REPAIR_BATCH_FALLBACKS = {5: 3, 3: 2}
PRE_STRATEGY_RUNTIME_FIELDS = (
    CHARACTER_APPEARANCE_REQUIREMENTS,
    CHARACTER_ALIAS_NAMING_RULES,
    OUTFIT_SWITCH_RULES,
)

HOOK_BATCH_ALIASES = (HOOK_CURRENT_WRITE_VAR, HOOK_CURRENT_VAR)
HOOK_REVIEW_ALIASES = (HOOK_REVIEW_OUTPUT_VAR,)
HOOK_MEMORY_ALIASES = (
    HOOK_MEMORY_INPUT_VAR,
    HOOK_MEMORY_REVIEW_VAR,
    HOOK_MEMORY_REVISE_VAR,
    HOOK_MEMORY_OUTPUT_VAR,
)
HOOK_FINAL_ALIASES = (HOOK_FINAL_VAR,)

DIALOGUE_BATCH_ALIASES = (
    DIALOGUE_CURRENT_WORKFLOW_VAR,
    DIALOGUE_CURRENT_WRITE_VAR,
    DIALOGUE_CURRENT_VAR,
)
DIALOGUE_REVIEW_ALIASES = (
    DIALOGUE_REVIEW_OUTPUT_VAR,
    DIALOGUE_REVIEW_WORKFLOW_VAR,
    DIALOGUE_REVIEW_LEGACY_VAR,
)
DIALOGUE_MEMORY_ALIASES = (
    DIALOGUE_MEMORY_INPUT_VAR,
    DIALOGUE_MEMORY_OUTPUT_VAR,
    DIALOGUE_MEMORY_SEARCH_VAR,
    DIALOGUE_MEMORY_LEGACY_OUTPUT_VAR,
)
DIALOGUE_HOOK_INPUT_ALIASES = (
    DIALOGUE_HOOK_BATCH_VAR,
    DIALOGUE_HOOK_REVIEW_VAR,
    DIALOGUE_HOOK_REWRITE_VAR,
    DIALOGUE_HOOK_MEMORY_VAR,
)
DIALOGUE_FINAL_ALIASES = (DIALOGUE_FINAL_VAR,)

SCRIPT_BATCH_ALIASES = (SCRIPT_CURRENT_WRITE_VAR, SCRIPT_CURRENT_VAR)
SCRIPT_REVIEW_ALIASES = (SCRIPT_REVIEW_WRITE_VAR, SCRIPT_REVIEW_OUTPUT_VAR)
SCRIPT_MEMORY_ALIASES = (SCRIPT_MEMORY_WRITE_INPUT_VAR, MEMORY_VAR, SCRIPT_MEMORY_OUTPUT_VAR)
SCRIPT_HOOK_INPUT_ALIASES = (SCRIPT_HOOK_BATCH_VAR, HOOK_FINAL_VAR)
SCRIPT_DIALOGUE_INPUT_ALIASES = (SCRIPT_DIALOGUE_BATCH_VAR, DIALOGUE_FINAL_VAR)
SCRIPT_FINAL_ALIASES = (SCRIPT_FINAL_VAR,)
SCENE_CORE_INPUT_FIELDS = (
    WORLDVIEW,
    STORY_OUTLINE,
    USER_CHARACTERS,
    EPISODE_PLAN,
)
SCENE_OPTIONAL_INPUT_FIELDS = (
    USER_SCENES,
    CHARACTER_APPEARANCE_REQUIREMENTS,
    CHARACTER_ALIAS_NAMING_RULES,
)
SCENE_STAGE_TRANSIENT_KEYS = (
    SCENES,
    SCENE_VAR,
    CORE_SCENE_FINAL_VAR,
    FINAL_SCENE_VAR,
    SCENE_NATURAL_LANGUAGE_VAR,
    SCENE_RETRY_VAR,
    SCENE_MAX_RETRY_VAR,
    SCENE_APPEARANCE_REQUIREMENTS,
)
SCENE_MIN_COUNT = 3
APPEARANCE_STAGE_TRANSIENT_KEYS = (
    APPEARANCE_MAPPING,
    APPEARANCE_MAPPING_VAR,
    PASS_REVIEW_JSON,
    APPEARANCE_REVIEW_VAR,
    APPEARANCE_NATURAL_LANGUAGE_VAR,
    CHARACTER_REGISTRY,
    CHARACTER_ALIAS_REGISTRY,
    EPISODE_ALIAS_PLAN,
    APPEARANCE_CONTINUITY_MEMORY,
)
SCRIPT_EPISODE_HEADING_PATTERN = re.compile(
    r"(?=^[ \t>#*\-]*第\s*([0-9０-９一二三四五六七八九十百千万两零〇]+)\s*集(?:\s*[:：]|$))",
    re.MULTILINE,
)
CHARACTER_NATURALIZE_READY_FLAG = "__character_naturalize_ready__"
REVIEW_ROUND_MESSAGE_PATTERN = re.compile(r"(第\s*\d+\s*/\s*\d+\s*轮)")


class FastGPTRunner(Protocol):
    def run_stage(self, stage_name: str, variables: dict[str, Any]) -> dict[str, Any]:
        ...


class FrameworkOutputValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__(_format_framework_validation_errors(self.errors))


class ConsistencySelfCheckError(ValueError):
    """一致性阶段没有产出严格 true/false 时，阻止误打回 framework。"""


class _RetryWithSmallerScriptBatch(ValueError):
    def __init__(
        self,
        *,
        batch: BatchWindow,
        next_batch_size: int,
        failure_reasons: list[str],
    ) -> None:
        self.batch = batch
        self.next_batch_size = int(next_batch_size)
        self.failure_reasons = [str(item).strip() for item in failure_reasons if str(item).strip()]
        super().__init__(
            f"script batch {batch.label} auto repair exhausted; retry with smaller batch size {next_batch_size}"
        )


@dataclass(frozen=True)
class ReviewDecision:
    passed: bool
    rewrite_required: bool
    blocking_issues: list[Any]
    non_blocking_issues: list[Any]
    rewrite_start_episode: int | None = None
    stage: str | None = None
    summary: str = ""
    raw: dict[str, Any] | None = None

    @property
    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            REVIEW_PASSED: self.passed,
            REWRITE_REQUIRED: self.rewrite_required,
            BLOCKING_ISSUES: list(self.blocking_issues),
            "non_blocking_issues": list(self.non_blocking_issues),
        }
        if self.summary:
            payload["summary"] = self.summary
        if self.rewrite_start_episode is not None:
            payload["rewrite_start_episode"] = self.rewrite_start_episode
        if self.stage:
            payload["stage"] = self.stage
        return payload


def run_fastgpt_hybrid_workflow(
    payload: WorkflowInput,
    *,
    workflow_spec_path: str | Path | None = None,
    runtime=None,
    model_option: ModelOption | None = None,
    client: FastGPTRunner | None = None,
    resume_snapshot: dict[str, Any] | None = None,
) -> WorkflowState:
    """主控整个 FastGPT 编排流程，并在关键节点兜底恢复/回退/重试。"""

    del workflow_spec_path
    payload.validate()
    state = WorkflowState.from_defaults(user_input=payload, default_variables={})
    state.runtime = runtime
    state.preferred_provider = model_option.provider if model_option else None
    state.preferred_model = model_option.model if model_option else None
    runner = client or fastgpt_client

    variables = _initial_fastgpt_variables(payload)
    _restore_resume_state(state, variables, resume_snapshot)
    # 先把“前置静态设定”跑稳，再进入批处理阶段。
    # 这样后面的 worldview/characters/scenes/hooks/dialogues/script 才能统一读取
    # 同一份框架、服装策略和一致性校验结果。
    _ensure_framework_and_consistency(
        state,
        runner,
        payload,
        variables,
        resume_snapshot_present=resume_snapshot is not None,
    )
    _apply_normalized_episode_plan_to_variables(payload, variables)
    _apply_appearance_outputs_to_variables(variables)
    _sync_state_variables(state, variables)
    sync_runtime_state(state)
    _sync_state_variables(state, variables)

    normalized_plan = _normalize_episode_plan_object(variables.get(NORMALIZED_EPISODE_PLAN))
    if _normalized_episode_plan_is_trusted(normalized_plan, payload.total_episodes):
        variables[NORMALIZED_EPISODE_PLAN] = normalized_plan
        _apply_normalized_episode_plan_to_variables(payload, variables)
        set_runtime_stage(
            state,
            "validation",
            "已从缓存恢复规范化分集计划。",
            progress_percent=7,
        )
        sync_runtime_state(state)
    else:
        if _has_normalized_episode_plan(normalized_plan):
            logger.warning(
                "恢复到的规范化分集计划疑似被旧快照污染：%s，当前总集数=%s。将重新执行规范化阶段。",
                _describe_normalized_episode_plan(normalized_plan),
                payload.total_episodes,
            )
        raw_episode_plan = _raw_episode_plan_source(payload, variables)
        if not raw_episode_plan:
            raise ValueError(
                "恢复的规范化分集计划疑似只剩局部批次，且当前项目未保留原始分集计划，"
                "请从剧本框架或分集计划规范化阶段重新生成。"
            )
        variables.pop(NORMALIZED_EPISODE_PLAN, None)
        variables[EPISODE_PLAN] = raw_episode_plan
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
        if _normalized_episode_plan_is_trusted(normalized_plan, payload.total_episodes):
            variables[NORMALIZED_EPISODE_PLAN] = normalized_plan
            _apply_normalized_episode_plan_to_variables(payload, variables)
        else:
            raise ValueError(
                "分集计划规范化结果未覆盖完整剧集范围，已拒绝继续使用疑似局部批次结果。"
            )
    _sync_state_variables(state, variables)

    if has_meaningful_content(variables.get(WORLDVIEW)):
        set_runtime_stage(
            state,
            "worldview",
            "已从缓存恢复世界观。",
            progress_percent=12,
        )
        sync_runtime_state(state)
    else:
        variables.update(
            _run_fastgpt_stage(
                state,
                runner,
                STAGE_WORLDVIEW,
                variables,
                stage_key="worldview",
                message="正在生成并校正世界观。",
                progress_percent=12,
            )
        )
    _ensure_worldview_natural_language(state, runner, variables)
    _sync_state_variables(state, variables)

    if has_meaningful_content(variables.get(CHARACTERS)):
        set_runtime_stage(
            state,
            "character",
            "已从缓存恢复人物设定。",
            progress_percent=24,
        )
        sync_runtime_state(state)
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
    _ensure_character_natural_language(state, runner, variables)
    _sync_state_variables(state, variables)

    _ensure_scene_outputs(state, runner, variables)
    _sync_state_variables(state, variables)

    _ensure_appearance_outputs(state, runner, variables)
    _sync_state_variables(state, variables)

    _run_batched_generation(state, runner, payload, variables)
    # final 只接受 hooks / dialogues / script 三套正式产物都完整落盘。
    # 这里先在本地把跨批缓存重新拼接并补做完整性校验，避免 FastGPT final
    # 阶段把缺批正文或缺批前置材料“正常拼接”成一个看似成功的结果。
    _ensure_complete_batched_outputs_before_final(payload, variables)
    _sync_state_variables(state, variables)
    sync_runtime_state(state)

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
        # 这 3 个字段只是运行态占位，供 appearance_pre_strategy 及其后续阶段复用。
        # framework 真正发给 FastGPT 的输入仍严格受 contract.input_names 约束，
        # 只会携带网页端现有的 3 个用户输入，不会把这里的旧兼容字段一并送进去。
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
        LOCAL_RAW_EPISODE_PLAN: str(payload.episode_plan or "").strip(),
        MAX_RETRIES: settings.max_retries_default,
        LAST_SUMMARY: "",
        HOOK_MEMORY: "",
        DIALOGUE_MEMORY: "",
        SCRIPT_MEMORY: "",
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

# 这个是用来获取当前衣服规则的，本来接到网页现在缩到后天里面完成
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

# 当前服饰明明规则
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

def _find_batch_index_by_start(
    batches: list[BatchWindow],
    start_episode: int,
) -> int:
    if not batches:
        return 0
    if start_episode > batches[-1].end_episode:
        return len(batches)

    for index, batch in enumerate(batches):
        if batch.start_episode <= start_episode <= batch.end_episode:
            return index
        if start_episode < batch.start_episode:
            return index
    return len(batches)


def _resolve_batch_resume_position(
    batches: list[BatchWindow],
    *,
    saved_batch_start: int,
    current_batch_stage: str,
    saved_completed_batches: int,
    saved_current_batch_index: int,
) -> tuple[int, int]:
    total_batches = len(batches)
    if total_batches <= 0:
        return 0, 0

    absolute_index = _find_batch_index_by_start(batches, saved_batch_start)

    if current_batch_stage:
        completed_batches = min(total_batches, absolute_index)
        current_batch_index = min(total_batches - 1, absolute_index)
        return completed_batches, current_batch_index

    completed_batches = min(
        total_batches,
        max(absolute_index, saved_completed_batches),
    )
    current_batch_index = min(
        total_batches,
        max(completed_batches, saved_current_batch_index),
    )
    return completed_batches, current_batch_index


def _run_batched_generation(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> None:
    """按 hooks 全量 -> dialogues 全量 -> script 全量 的顺序推进批处理阶段。"""
    batch_mode = _effective_batch_mode()
    if batch_mode in {"fastgpt_full", "full", "legacy_full"}:
        logger.warning(
            "检测到 FASTGPT_BATCH_MODE=%s，但当前项目已强制使用本地三段式批处理模式：all_hooks -> all_dialogues -> all_script。",
            batch_mode,
        )
        batch_mode = "local"
    if batch_mode != "local":
        raise ValueError(
            "FASTGPT_BATCH_MODE 只能是 auto、local 或 fastgpt_full，"
            f"当前为：{settings.fastgpt_batch_mode}"
        )

    total_episodes = int(variables[TOTAL_EPISODES])
    batch_size = max(1, int(settings.batch_size or 5))
    batches = list(iter_episode_batches(total_episodes, batch_size=batch_size))
    normalized_plan = _normalize_episode_plan_object(variables.get(NORMALIZED_EPISODE_PLAN))
    episode_alias_plan = _normalize_episode_alias_plan_object(variables.get(EPISODE_ALIAS_PLAN))
    rewrite_from_stage = str(variables.get(LOCAL_REWRITE_FROM_STAGE) or "").strip().lower()
    repaired_script_text, repaired_script_episodes = _repair_script_outputs(
        variables,
        total_episodes=total_episodes,
        batch_size=batch_size,
    )

    final_script_candidate = (
        repaired_script_text
        or get_with_aliases(variables, ALL_SCRIPT, SCRIPT_FINAL_ALIASES, "")
    )
    if (
        rewrite_from_stage == "final"
        and _has_value(final_script_candidate)
        and repaired_script_episodes == list(range(1, total_episodes + 1))
        and _script_text_is_reusable_for_final(
            final_script_candidate,
            total_episodes=total_episodes,
            batches=batches,
        )
    ):
        set_runtime_stage(
            state,
            "script",
            "已保留剧本正文，将直接重新执行最终剧本拼接。",
            progress_percent=98,
            generated_episodes=total_episodes,
        )
        variables[LOCAL_REWRITE_FROM_STAGE] = ""
        _sync_state_variables(state, variables)
        sync_runtime_state(state)
        return

    logger.info(
        "batch_sync 已切换为三段式流程：总批次=%s，rewrite_from_stage=%s。",
        len(batches),
        rewrite_from_stage or "none",
    )
    _run_all_hook_batches(
        state,
        runner,
        payload,
        variables,
        batches=batches,
        normalized_plan=normalized_plan,
        episode_alias_plan=episode_alias_plan,
        rewrite_from_stage=rewrite_from_stage,
    )
    _run_all_dialogue_batches(
        state,
        runner,
        payload,
        variables,
        batches=batches,
        normalized_plan=normalized_plan,
        episode_alias_plan=episode_alias_plan,
        rewrite_from_stage=rewrite_from_stage,
    )
    _run_all_script_batches(
        state,
        runner,
        payload,
        variables,
        batches=batches,
        normalized_plan=normalized_plan,
        episode_alias_plan=episode_alias_plan,
        rewrite_from_stage=rewrite_from_stage,
    )

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


def _run_all_hook_batches(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
    *,
    batches: list[BatchWindow],
    normalized_plan: dict[str, Any] | None,
    episode_alias_plan: dict[str, Any] | None,
    rewrite_from_stage: str,
) -> None:
    """先补齐全部 hooks，再允许后续阶段启动。"""
    cached_all_hooks = get_with_aliases(variables, ALL_HOOKS, HOOK_FINAL_ALIASES, {})
    if _phase_object_complete(cached_all_hooks, batches) and _pending_hook_memory_batch_start(
        variables,
        batches=batches,
    ) is None:
        set_with_aliases(
            variables,
            ALL_HOOKS,
            cached_all_hooks,
            HOOK_FINAL_ALIASES,
        )
        set_runtime_stage(
            state,
            "hook",
            "已从缓存恢复完整开头冲突钩子。",
            progress_percent=56,
        )
        sync_runtime_state(state)
        return

    _run_hook_batches(
        state,
        runner,
        payload,
        variables,
        batches=batches,
        normalized_plan=normalized_plan,
        episode_alias_plan=episode_alias_plan,
        rewrite_from_stage=rewrite_from_stage,
        batch_index_offset=0,
        total_batches=len(batches),
    )


def _run_all_dialogue_batches(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
    *,
    batches: list[BatchWindow],
    normalized_plan: dict[str, Any] | None,
    episode_alias_plan: dict[str, Any] | None,
    rewrite_from_stage: str,
) -> None:
    """只有在 hooks 全部完成后，才允许逐批生成全部对白。"""
    cached_all_hooks = get_with_aliases(variables, ALL_HOOKS, HOOK_FINAL_ALIASES, {})
    if not _phase_object_complete(cached_all_hooks, batches):
        raise ValueError("角色对白阶段启动失败：ALL_HOOKS 尚未完整覆盖全部集数。")

    cached_all_dialogues = get_with_aliases(variables, ALL_DIALOGUES, DIALOGUE_FINAL_ALIASES, {})
    if _phase_object_complete(
        cached_all_dialogues,
        batches,
    ) and _pending_dialogue_memory_batch_start(
        variables,
        batches=batches,
    ) is None:
        set_with_aliases(
            variables,
            ALL_DIALOGUES,
            cached_all_dialogues,
            DIALOGUE_FINAL_ALIASES,
        )
        set_runtime_stage(
            state,
            "dialogue",
            "已从缓存恢复完整角色对白。",
            progress_percent=70,
        )
        sync_runtime_state(state)
        return

    _run_dialogue_batches(
        state,
        runner,
        payload,
        variables,
        batches=batches,
        normalized_plan=normalized_plan,
        episode_alias_plan=episode_alias_plan,
        rewrite_from_stage=rewrite_from_stage,
        batch_index_offset=0,
        total_batches=len(batches),
    )


def _run_all_script_batches(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
    *,
    batches: list[BatchWindow],
    normalized_plan: dict[str, Any] | None,
    episode_alias_plan: dict[str, Any] | None,
    rewrite_from_stage: str,
) -> None:
    """只有在 hooks 与 dialogues 全部完成后，才允许逐批生成正文。"""
    cached_all_hooks = get_with_aliases(variables, ALL_HOOKS, HOOK_FINAL_ALIASES, {})
    cached_all_dialogues = get_with_aliases(variables, ALL_DIALOGUES, DIALOGUE_FINAL_ALIASES, {})
    if not _phase_object_complete(cached_all_hooks, batches):
        raise ValueError("剧本正文阶段启动失败：ALL_HOOKS 尚未完整覆盖全部集数。")
    if not _phase_object_complete(cached_all_dialogues, batches):
        raise ValueError("剧本正文阶段启动失败：ALL_DIALOGUES 尚未完整覆盖全部集数。")

    if _next_unfinished_script_batch_start(variables, batches) > batches[-1].end_episode:
        set_with_aliases(
            variables,
            ALL_SCRIPT,
            get_with_aliases(variables, ALL_SCRIPT, SCRIPT_FINAL_ALIASES, ""),
            SCRIPT_FINAL_ALIASES,
        )
        set_runtime_stage(
            state,
            "script",
            "已从缓存恢复完整剧本正文。",
            progress_percent=98,
            generated_episodes=payload.total_episodes,
        )
        sync_runtime_state(state)
        return

    _run_script_batches(
        state,
        runner,
        payload,
        variables,
        batches=batches,
        normalized_plan=normalized_plan,
        episode_alias_plan=episode_alias_plan,
        rewrite_from_stage=rewrite_from_stage,
        batch_index_offset=0,
        total_batches=len(batches),
    )


def _stage_input_context(stage_name: str, variables: dict[str, Any]) -> dict[str, Any]:
    """只保留当前阶段契约真正会读取的字段，避免旧缓存把无关上下文一并带入。"""
    contract = contract_for(stage_name)
    context: dict[str, Any] = {}
    for field_name in contract.input_names:
        if field_name in variables:
            context[field_name] = copy.deepcopy(variables[field_name])
    return context


def set_with_aliases(
    variables: dict[str, Any],
    canonical_name: str,
    value: Any,
    aliases: tuple[str, ...] | list[str] = (),
) -> None:
    variables[canonical_name] = copy.deepcopy(value)
    for alias in aliases:
        if alias and alias != canonical_name:
            variables[alias] = copy.deepcopy(value)


def get_with_aliases(
    variables: dict[str, Any],
    canonical_name: str,
    aliases: tuple[str, ...] | list[str] = (),
    default: Any = None,
) -> Any:
    if _has_value(variables.get(canonical_name)):
        return variables.get(canonical_name)
    for alias in aliases:
        if _has_value(variables.get(alias)):
            return variables.get(alias)
    return default


def sync_canonical_to_aliases(
    variables: dict[str, Any],
    mapping: dict[str, tuple[str, ...] | list[str]],
) -> None:
    for canonical_name, aliases in mapping.items():
        value = get_with_aliases(variables, canonical_name, aliases)
        if _has_value(value):
            set_with_aliases(variables, canonical_name, value, aliases)
        elif canonical_name in {LAST_SUMMARY, HOOK_MEMORY, DIALOGUE_MEMORY, SCRIPT_MEMORY}:
            set_with_aliases(variables, canonical_name, "", aliases)


def extract_stage_output_with_aliases(
    output: dict[str, Any],
    canonical_name: str,
    aliases: tuple[str, ...] | list[str],
    default: Any = None,
) -> Any:
    return get_with_aliases(output, canonical_name, aliases, default)


def mirror_current_batch_aliases(variables: dict[str, Any], group_name: str) -> None:
    mappings: dict[str, tuple[str, tuple[str, ...]]] = {
        "hook_batch": (BATCH_HOOKS, HOOK_BATCH_ALIASES),
        "hook_review": (HOOK_REVIEW_RESULT, HOOK_REVIEW_ALIASES),
        "hook_memory": (HOOK_MEMORY, HOOK_MEMORY_ALIASES),
        "dialogue_batch": (BATCH_DIALOGUES, DIALOGUE_BATCH_ALIASES),
        "dialogue_review": (DIALOGUE_REVIEW_RESULT, DIALOGUE_REVIEW_ALIASES),
        "dialogue_memory": (DIALOGUE_MEMORY, DIALOGUE_MEMORY_ALIASES),
        "script_batch": (BATCH_SCRIPT, SCRIPT_BATCH_ALIASES),
        "script_review": (SCRIPT_REVIEW_RESULT, SCRIPT_REVIEW_ALIASES),
        "script_memory": (LAST_SUMMARY, SCRIPT_MEMORY_ALIASES),
    }
    canonical_name, aliases = mappings[group_name]
    sync_canonical_to_aliases(variables, {canonical_name: aliases})


def _sync_stage_input_aliases(stage_name: str, variables: dict[str, Any]) -> None:
    aliases = LEGACY_INPUT_ALIASES.get(stage_name, {})
    for canonical_name, wire_names in aliases.items():
        names = _as_wire_names_for_estimate(wire_names)
        if canonical_name == ALL_HOOKS and _has_value(variables.get(BATCH_HOOKS)):
            set_with_aliases(variables, BATCH_HOOKS, variables[BATCH_HOOKS], names)
            continue
        if canonical_name == ALL_DIALOGUES and _has_value(variables.get(BATCH_DIALOGUES)):
            set_with_aliases(variables, BATCH_DIALOGUES, variables[BATCH_DIALOGUES], names)
            continue
        sync_canonical_to_aliases(variables, {canonical_name: names})


def _normalize_stage_output_aliases(stage_name: str, output: dict[str, Any]) -> dict[str, Any]:
    contract = contract_for(stage_name)
    normalized = dict(output)
    if {REVIEW_PASSED, REWRITE_REQUIRED, BLOCKING_ISSUES}.issubset(contract.output_names):
        try:
            review_payload = _strict_review_payload_from_output(normalized)
            normalized.update(review_payload)
            return normalized
        except Exception:
            pass
    for field_name in contract.output_names:
        value = extract_stage_output_with_aliases(
            normalized,
            field_name,
            contract.aliases_for_output(field_name),
        )
        if not _has_value(value) and field_name in {HOOK_MEMORY, DIALOGUE_MEMORY, SCRIPT_MEMORY, LAST_SUMMARY}:
            value = normalized.get("answerText")
        if _has_value(value):
            normalized[field_name] = value
    return normalized


def _review_aliases_for_stage_key(stage_key: str) -> tuple[str, tuple[str, ...]]:
    if stage_key == "hook":
        return HOOK_REVIEW_RESULT, HOOK_REVIEW_ALIASES
    if stage_key == "dialogue":
        return DIALOGUE_REVIEW_RESULT, DIALOGUE_REVIEW_ALIASES
    if stage_key == "script":
        return SCRIPT_REVIEW_RESULT, SCRIPT_REVIEW_ALIASES
    return PASS_REVIEW_JSON, ()


def _ensure_dialogue_revise_workflow_available() -> None:
    workflow_path = _workflow_json_path("角色对话修订.json")
    try:
        text = workflow_path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ValueError(
            "角色对白审核未通过，但缺少真正的角色对话修订 workflow："
            "未找到 workflow_jsons/角色对话修订.json。"
        ) from exc
    except OSError as exc:
        raise ValueError(f"无法读取角色对话修订 workflow：{exc}") from exc

    try:
        workflow_json = json.loads(text)
    except Exception:
        workflow_json = {}
    chat_variables = workflow_json.get("chatConfig", {}).get("variables")
    variable_keys = {
        str(item.get("key") or "").strip()
        for item in chat_variables or []
        if isinstance(item, dict)
    }

    required_current = any(token in text for token in DIALOGUE_BATCH_ALIASES)
    required_review = any(token in text for token in DIALOGUE_REVIEW_ALIASES)
    writes_current = any(
        marker in text
        for marker in (
            DIALOGUE_CURRENT_WRITE_VAR,
            DIALOGUE_CURRENT_WORKFLOW_VAR,
        )
    )
    if not (required_current and required_review and writes_current):
        raise ValueError(
            "角色对白审核未通过，但当前 角色对话修订.json 不是可用的修订器："
            "它必须读取 dialogueContent/exiXcZp1，读取 tClN5WMn/rMBlm0Oo，"
            "并写回 dialogueContent/exiXcZp1。请补充真正的角色对话修订 workflow。"
        )

    if "{{$VARIABLE_NODE_ID.hookContent$}}" in text and "hookContent" not in variable_keys:
        logger.warning(
            "角色对话修订 workflow prompt 引用了 hookContent，"
            "但 chatConfig.variables 未声明该变量。代码侧会继续镜像注入该 alias，"
            "不过建议补齐 workflow JSON，避免后续节点或平台校验漂移。"
        )


def _workflow_json_path(filename: str) -> Path:
    return resolve_workflow_json_path(filename)


def _stage_name_for_runner(runner: FastGPTRunner, preferred: str, legacy: str) -> str:
    stage_outputs = getattr(runner, "stage_outputs", None)
    if isinstance(stage_outputs, dict) and preferred not in stage_outputs:
        runner_name = runner.__class__.__name__
        if runner_name.startswith("_") or "RecordingRunner" in runner_name:
            return legacy
    return preferred


def _current_output_aliases_for_field(output_field: str) -> tuple[str, ...]:
    if output_field == BATCH_HOOKS:
        return HOOK_BATCH_ALIASES
    if output_field == BATCH_DIALOGUES:
        return DIALOGUE_BATCH_ALIASES
    if output_field == BATCH_SCRIPT:
        return SCRIPT_BATCH_ALIASES
    return ()


def _stage_review_revise_loop_limit() -> int:
    configured = int(
        getattr(settings, "fastgpt_stage_review_revise_max_loops", BATCH_REVIEW_MAX_LOOPS)
    )
    return max(1, min(BATCH_REVIEW_MAX_LOOPS, configured))


def parse_review_result(value: Any) -> ReviewDecision:
    issue_prefix = "review output invalid"
    candidate: Any = value
    required = {REVIEW_PASSED, REWRITE_REQUIRED, BLOCKING_ISSUES}
    allowed = required | {
        "summary",
        "non_blocking_issues",
        "rewrite_start_episode",
        "stage",
    }

    if isinstance(candidate, dict):
        direct = {key: value for key, value in candidate.items() if key in allowed}
        if required.issubset(direct):
            candidate = direct
        else:
            parsed_candidate = None
            for value in candidate.values():
                if isinstance(value, dict) and required.issubset(value):
                    parsed_candidate = value
                    break
                if isinstance(value, str) and value.strip():
                    try:
                        parsed = parse_json(value)
                    except Exception:
                        continue
                    if isinstance(parsed, dict) and required.issubset(parsed):
                        parsed_candidate = parsed
                        break
            candidate = parsed_candidate if parsed_candidate is not None else direct
    elif isinstance(candidate, str):
        try:
            candidate = parse_json(candidate)
        except Exception as exc:
            return ReviewDecision(
                passed=False,
                rewrite_required=True,
                blocking_issues=[f"{issue_prefix}: {str(exc).strip() or type(exc).__name__}"],
                non_blocking_issues=[],
                summary="review output is not valid JSON",
                raw=None,
            )

    if not isinstance(candidate, dict):
        return ReviewDecision(
            passed=False,
            rewrite_required=True,
            blocking_issues=["review output must be a JSON object"],
            non_blocking_issues=[],
            summary="review output must be a JSON object",
            raw=None,
        )

    missing = [key for key in required if key not in candidate]
    if missing:
        return ReviewDecision(
            passed=False,
            rewrite_required=True,
            blocking_issues=[f"review output missing required keys: {', '.join(sorted(missing))}"],
            non_blocking_issues=[],
            summary="review output missing required keys",
            raw=dict(candidate),
        )
    if not isinstance(candidate.get(REVIEW_PASSED), bool):
        return ReviewDecision(
            passed=False,
            rewrite_required=True,
            blocking_issues=["review output key passed must be boolean"],
            non_blocking_issues=[],
            summary="review output schema invalid",
            raw=dict(candidate),
        )
    if not isinstance(candidate.get(REWRITE_REQUIRED), bool):
        return ReviewDecision(
            passed=False,
            rewrite_required=True,
            blocking_issues=["review output key rewrite_required must be boolean"],
            non_blocking_issues=[],
            summary="review output schema invalid",
            raw=dict(candidate),
        )
    if not isinstance(candidate.get(BLOCKING_ISSUES), list):
        return ReviewDecision(
            passed=False,
            rewrite_required=True,
            blocking_issues=["review output key blocking_issues must be array"],
            non_blocking_issues=[],
            summary="review output schema invalid",
            raw=dict(candidate),
        )
    if candidate.get("non_blocking_issues") is None:
        candidate["non_blocking_issues"] = []
    if not isinstance(candidate.get("non_blocking_issues", []), list):
        return ReviewDecision(
            passed=False,
            rewrite_required=True,
            blocking_issues=["review output key non_blocking_issues must be array"],
            non_blocking_issues=[],
            summary="review output schema invalid",
            raw=dict(candidate),
        )
    rewrite_start = candidate.get("rewrite_start_episode")
    if rewrite_start in ("", None):
        rewrite_start = None
    elif isinstance(rewrite_start, bool) or not isinstance(rewrite_start, int):
        return ReviewDecision(
            passed=False,
            rewrite_required=True,
            blocking_issues=["review output key rewrite_start_episode must be int when present"],
            non_blocking_issues=list(candidate.get("non_blocking_issues") or []),
            summary="review output schema invalid",
            raw=dict(candidate),
        )

    normalized = dict(candidate)
    passed = bool(normalized[REVIEW_PASSED])
    rewrite_required = bool(normalized[REWRITE_REQUIRED])
    blocking_issues = list(normalized.get(BLOCKING_ISSUES) or [])
    non_blocking_issues = list(normalized.get("non_blocking_issues") or [])
    summary = str(normalized.get("summary") or "").strip()
    if passed and blocking_issues:
        passed = False
        rewrite_required = True
        summary = summary or "passed=true but blocking_issues is not empty"
    if not passed and not rewrite_required:
        issues = list(blocking_issues)
        issues.append("passed=false but rewrite_required=false; code side forced revision")
        blocking_issues = issues
        rewrite_required = True
        summary = summary or "passed=false but rewrite_required=false; forced revision"
        logger.warning("review returned passed=false with rewrite_required=false; forcing revision")
    return ReviewDecision(
        passed=passed,
        rewrite_required=rewrite_required,
        blocking_issues=blocking_issues,
        non_blocking_issues=non_blocking_issues,
        rewrite_start_episode=rewrite_start,
        stage=str(normalized.get("stage") or "").strip() or None,
        summary=summary,
        raw=dict(normalized),
    )


def _strict_review_payload_from_output(output: Any) -> dict[str, Any]:
    return parse_review_result(output).payload


def _run_pass_review_stage(
    state: WorkflowState,
    runner: FastGPTRunner,
    *,
    stage_name: str,
    stage_key: str,
    stage_label: str,
    batch: BatchWindow,
    review_context: dict[str, Any],
    progress_percent: int,
    generated_episodes: int,
    review_round: int,
    review_loop_limit: int,
) -> tuple[dict[str, Any], Any]:
    review_output = run_stage_with_contract_guard(
        state,
        runner,
        stage_name,
        review_context,
        stage_key=stage_key,
        message=f"正在审核{stage_label}：第 {batch.label} 集，第 {review_round}/{review_loop_limit} 轮",
        batch_label=batch.label,
        progress_percent=progress_percent,
        generated_episodes=generated_episodes,
        output_field=REVIEW_PASSED,
        batch=batch,
        review_round=review_round,
        review_parser=parse_review_result,
        sync_output_to_state=False,
    )
    review_payload = _strict_review_payload_from_output(review_output)
    review_result = normalize_pass_review(review_payload)

    if not review_result.approved and not review_result.rewrite_required:
        issues = list(review_payload.get(BLOCKING_ISSUES) or [])
        issues.append("审核返回 passed=false 但 rewrite_required=false，代码侧已转为需要重写。")
        review_payload[BLOCKING_ISSUES] = issues
        review_payload[REWRITE_REQUIRED] = True
        review_result = normalize_pass_review(review_payload)

    return review_payload, review_result


def _run_batch_write_review_revise_loop(
    state: WorkflowState,
    runner: FastGPTRunner,
    *,
    variables: dict[str, Any],
    batch: BatchWindow,
    stage_key: str,
    stage_label: str,
    output_field: str,
    current_output_var: str,
    review_output_var: str,
    retry_var: str,
    max_retry_var: str,
    writing_stage_name: str,
    review_stage_name: str,
    rewrite_stage_name: str,
    writing_context: dict[str, Any],
    review_context_builder,
    rewrite_context_builder,
    progress_percent: int,
    generated_episodes: int = 0,
    approved_output_validator=None,
    before_rewrite=None,
) -> tuple[Any, dict[str, Any]]:
    review_loop_limit = _stage_review_revise_loop_limit()
    variables[max_retry_var] = review_loop_limit
    variables[retry_var] = 0
    variables.pop(PASS_REVIEW_JSON, None)

    try:
        writing_output = run_stage_with_contract_guard(
            state,
            runner,
            writing_stage_name,
            writing_context,
            stage_key=stage_key,
            message=f"正在生成{stage_label}：第 {batch.label} 集",
            batch_label=batch.label,
            progress_percent=progress_percent,
            generated_episodes=generated_episodes,
            output_field=output_field,
            batch=batch,
            validator=(lambda candidate: list(approved_output_validator(candidate) or []))
            if callable(approved_output_validator)
            else None,
            sync_output_to_state=False,
        )
        current_output = writing_output[output_field]
    except Exception as exc:
        if stage_key != "script" or output_field != BATCH_SCRIPT or not callable(approved_output_validator):
            raise
        failure_reasons, invalid_output, _ = _script_stage_validation_details(
            exc,
            state=state,
            stage_name=writing_stage_name,
            output_field=output_field,
        )
        current_output = _auto_repair_script_output(
            state,
            runner,
            variables=variables,
            batch=batch,
            stage_label=stage_label,
            output_field=output_field,
            current_output_var=current_output_var,
            writing_stage_name=writing_stage_name,
            rewrite_stage_name=rewrite_stage_name,
            writing_context=writing_context,
            rewrite_context_builder=rewrite_context_builder,
            progress_percent=progress_percent,
            generated_episodes=generated_episodes,
            approved_output_validator=approved_output_validator,
            failure_reasons=failure_reasons,
            current_output=invalid_output,
        )
    set_with_aliases(
        variables,
        output_field,
        current_output,
        _current_output_aliases_for_field(output_field),
    )
    variables[current_output_var] = current_output
    _sync_state_variables(state, variables)
    sync_runtime_state(state)

    last_review_payload: dict[str, Any] = {}
    for review_round in range(1, review_loop_limit + 1):
        review_context = review_context_builder(current_output)
        review_payload, review_result = _run_pass_review_stage(
            state,
            runner,
            stage_name=review_stage_name,
            stage_key=stage_key,
            stage_label=stage_label,
            batch=batch,
            review_context=review_context,
            progress_percent=progress_percent,
            generated_episodes=generated_episodes,
            review_round=review_round,
            review_loop_limit=review_loop_limit,
        )
        last_review_payload = dict(review_payload)
        variables[PASS_REVIEW_JSON] = copy.deepcopy(review_payload)
        review_text = json.dumps(review_payload, ensure_ascii=False, indent=2)
        variables[review_output_var] = review_text
        review_canonical, review_aliases = _review_aliases_for_stage_key(stage_key)
        set_with_aliases(variables, review_canonical, review_text, review_aliases)
        variables[retry_var] = review_round - 1
        state.set_output(review_stage_name, "last_review", copy.deepcopy(review_payload))
        _sync_state_variables(state, variables)
        sync_runtime_state(state)

        if review_result.approved and callable(approved_output_validator):
            local_issues = [
                str(item).strip()
                for item in list(approved_output_validator(current_output) or [])
                if str(item).strip()
            ]
            if local_issues:
                review_payload = {
                    REVIEW_PASSED: False,
                    REWRITE_REQUIRED: True,
                    BLOCKING_ISSUES: local_issues,
                    "summary": "代码侧批次校验未通过",
                    "non_blocking_issues": [],
                }
                last_review_payload = dict(review_payload)
                variables[PASS_REVIEW_JSON] = copy.deepcopy(review_payload)
                review_text = json.dumps(review_payload, ensure_ascii=False, indent=2)
                variables[review_output_var] = review_text
                review_canonical, review_aliases = _review_aliases_for_stage_key(stage_key)
                set_with_aliases(variables, review_canonical, review_text, review_aliases)
                state.set_output(
                    review_stage_name,
                    "last_local_validation",
                    copy.deepcopy(review_payload),
                )
                review_result = normalize_pass_review(review_payload)
                logger.warning(
                    "%s %s 集代码侧批次校验未通过，将按需要修订处理：%s",
                    stage_label,
                    batch.label,
                    "；".join(local_issues[:10]),
                )

        if review_result.approved:
            variables[retry_var] = 0
            return current_output, last_review_payload

        issues = list(review_result.blocking_issues or [])
        if review_round >= review_loop_limit:
            raise ValueError(
                f"{stage_label} {batch.label} 集审核未通过，已达到最多 {review_loop_limit} 轮："
                + "；".join(issues[:10] or ["缺少 blocking_issues"])
            )

        if callable(before_rewrite):
            before_rewrite(current_output, review_payload)
        rewrite_context = rewrite_context_builder(current_output, review_payload)
        rewrite_output = run_stage_with_contract_guard(
            state,
            runner,
            rewrite_stage_name,
            rewrite_context,
            stage_key=stage_key,
            message=f"正在修订{stage_label}：第 {batch.label} 集，第 {review_round}/{review_loop_limit} 轮",
            batch_label=batch.label,
            progress_percent=progress_percent,
            generated_episodes=generated_episodes,
            output_field=output_field,
            batch=batch,
            review_round=review_round,
            validator=(lambda candidate: list(approved_output_validator(candidate) or []))
            if callable(approved_output_validator)
            else None,
            sync_output_to_state=False,
        )
        current_output = rewrite_output[output_field]
        set_with_aliases(
            variables,
            output_field,
            current_output,
            _current_output_aliases_for_field(output_field),
        )
        variables[current_output_var] = current_output
        variables[retry_var] = review_round
        _sync_state_variables(state, variables)
        sync_runtime_state(state)

    raise ValueError(f"{stage_label} {batch.label} 集审核循环异常结束。")


def _log_batched_stage_input(
    stage_name: str,
    *,
    stage_label: str,
    batch_label: str,
    fields: dict[str, Any],
    wire_context: dict[str, Any],
    memory_fields: tuple[str, ...] = (),
) -> None:
    """记录每个批处理阶段实际读取了哪些字段、长度多少、记忆字段占比如何。"""
    lengths = {
        field_name: _estimate_payload_value_length(value)
        for field_name, value in fields.items()
        if _has_value(value)
    }
    memory_desc = (
        "、".join(
            f"{field_name}={lengths[field_name]}"
            for field_name in memory_fields
            if field_name in lengths
        )
        or "无"
    )
    logger.info(
        "%s %s 集读取字段：%s；总长度=%s；记忆字段=%s；wire长度=%s。",
        stage_label,
        batch_label,
        _format_script_payload_breakdown(lengths),
        sum(lengths.values()),
        memory_desc,
        _estimate_stage_payload_length(stage_name, wire_context),
    )


def _compact_stage_text(
    value: Any,
    *,
    builder,
    fallback: Any = "",
) -> str:
    try:
        compact = str(builder(value) or "").strip()
    except Exception:
        logger.warning(
            "compact context builder 失败，builder=%s，fallback_to_original=%s",
            getattr(builder, "__name__", "unknown"),
            bool(fallback),
            exc_info=True,
        )
        compact = ""
    if compact:
        return compact
    return str(fallback or "").strip()


def _build_hook_stage_context(
    variables: dict[str, Any],
    *,
    stage_name: str,
    plan_for_batch: str,
    normalized_plan_for_batch: dict[str, Any] | None,
    alias_plan_for_batch: dict[str, Any] | None,
    batch_start_episode: int,
    hook_memory: Any = "",
    batch_hooks: Any = None,
    review_payload: Any = None,
) -> dict[str, Any]:
    context = _stage_input_context(stage_name, variables)
    _apply_batch_episode_plan_context(
        context,
        plan_for_batch=plan_for_batch,
        normalized_plan_for_batch=normalized_plan_for_batch,
    )
    context[WORLDVIEW] = _compact_stage_text(
        variables.get(WORLDVIEW),
        builder=build_compact_worldview_context,
        fallback=context.get(WORLDVIEW),
    )
    context[STORY_OUTLINE] = _compact_stage_text(
        variables.get(STORY_OUTLINE),
        builder=build_compact_story_outline_context,
        fallback=context.get(STORY_OUTLINE),
    )
    context[CHARACTERS] = _compact_stage_text(
        variables.get(CHARACTERS),
        builder=build_compact_character_context_for_hooks,
        fallback="",
    )
    context[SCENES] = _compact_stage_text(
        variables.get(SCENES),
        builder=build_compact_scene_context_for_script,
        fallback="",
    )
    context[APPEARANCE_MAPPING] = _compact_stage_text(
        alias_plan_for_batch,
        builder=build_compact_appearance_context_for_batch,
        fallback="",
    )
    context[BATCH_START_EPISODE] = batch_start_episode
    if _has_value(hook_memory):
        context[HOOK_MEMORY] = hook_memory
    if batch_hooks is not None:
        context[BATCH_HOOKS] = copy.deepcopy(batch_hooks)
    if review_payload is not None:
        context[PASS_REVIEW_JSON] = copy.deepcopy(review_payload)
    return context


def _build_dialogue_stage_context(
    variables: dict[str, Any],
    *,
    stage_name: str,
    plan_for_batch: str,
    normalized_plan_for_batch: dict[str, Any] | None,
    alias_plan_for_batch: dict[str, Any] | None,
    hook_payload: dict[str, Any],
    batch_start_episode: int,
    dialogue_memory: Any = "",
    batch_dialogues: Any = None,
    review_payload: Any = None,
) -> dict[str, Any]:
    context = _stage_input_context(stage_name, variables)
    _apply_batch_episode_plan_context(
        context,
        plan_for_batch=plan_for_batch,
        normalized_plan_for_batch=normalized_plan_for_batch,
    )
    context[WORLDVIEW] = _compact_stage_text(
        variables.get(WORLDVIEW),
        builder=build_compact_worldview_context,
        fallback=context.get(WORLDVIEW),
    )
    context[CHARACTERS] = _compact_stage_text(
        variables.get(CHARACTERS),
        builder=build_compact_character_context_for_dialogues,
        fallback="",
    )
    context[SCENES] = _compact_stage_text(
        variables.get(SCENES),
        builder=build_compact_scene_context_for_script,
        fallback="",
    )
    context[APPEARANCE_MAPPING] = _compact_stage_text(
        alias_plan_for_batch,
        builder=build_compact_appearance_context_for_batch,
        fallback="",
    )
    context[ALL_HOOKS] = copy.deepcopy(hook_payload)
    set_with_aliases(context, BATCH_HOOKS, hook_payload, DIALOGUE_HOOK_INPUT_ALIASES)
    context[BATCH_START_EPISODE] = batch_start_episode
    if _has_value(dialogue_memory):
        context[DIALOGUE_MEMORY] = dialogue_memory
    if batch_dialogues is not None:
        context[BATCH_DIALOGUES] = copy.deepcopy(batch_dialogues)
    if review_payload is not None:
        context[PASS_REVIEW_JSON] = copy.deepcopy(review_payload)
    context[MAX_RETRIES] = _stage_review_revise_loop_limit()
    return context


def _run_hook_batches(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
    *,
    batches: list[BatchWindow],
    normalized_plan: dict[str, Any] | None,
    episode_alias_plan: dict[str, Any] | None,
    rewrite_from_stage: str,
    batch_index_offset: int = 0,
    total_batches: int | None = None,
) -> None:
    """承接前置设定阶段，为所有批次补齐开头冲突钩子。"""
    total_batches = max(1, total_batches or len(batches))
    all_hooks = _dict_or_empty(get_with_aliases(variables, ALL_HOOKS, HOOK_FINAL_ALIASES, {}))
    if (
        rewrite_from_stage in {"dialogue", "script", "final"}
        and _phase_object_complete(all_hooks, batches)
        and _pending_hook_memory_batch_start(variables, batches=batches) is None
    ):
        set_runtime_stage(
            state,
            "hook",
            "已保留完整开头冲突钩子，直接进入后续阶段。",
            progress_percent=56,
        )
        return

    for index, batch in enumerate(batches):
        actual_index = batch_index_offset + index
        existing_batch_hooks = _current_batch_object_payload(
            variables.get(BATCH_HOOKS),
            all_hooks,
            batch=batch,
        )
        pending_hook_memory_only = _is_pending_hook_memory_recovery(
            variables,
            batch=batch,
            batch_payload=existing_batch_hooks,
        )
        if _batch_object_is_reusable(existing_batch_hooks, batch) and not pending_hook_memory_only:
            set_with_aliases(variables, BATCH_HOOKS, existing_batch_hooks, HOOK_BATCH_ALIASES)
            variables[LOCAL_HOOK_CHECKPOINT_START] = batch.start_episode
            variables[BATCH_START_EPISODE] = batch.end_episode + 1
            variables[LOCAL_COMPLETED_BATCHES] = actual_index + 1
            variables[LOCAL_CURRENT_BATCH_INDEX] = actual_index + 1
            variables[LOCAL_CURRENT_BATCH_STAGE] = ""
            continue

        plan_for_batch, normalized_plan_for_batch = _get_episode_batch_plan_context(
            normalized_plan,
            batch.start_episode,
            batch_size=batch.size,
            raw_episode_plan=_raw_episode_plan_source(payload, variables),
        )
        _ensure_plan_matches_batch(plan_for_batch, batch=batch, stage_label="开头冲突钩子")
        alias_plan_for_batch = slice_episode_alias_plan_for_batch(episode_alias_plan, batch)

        variables[BATCH_START_EPISODE] = batch.start_episode
        variables[LOCAL_COMPLETED_BATCHES] = actual_index
        variables[LOCAL_CURRENT_BATCH_INDEX] = actual_index
        variables[LOCAL_CURRENT_BATCH_STAGE] = "hook"
        set_with_aliases(
            variables,
            HOOK_MEMORY,
            get_with_aliases(variables, HOOK_MEMORY, HOOK_MEMORY_ALIASES, ""),
            HOOK_MEMORY_ALIASES,
        )
        set_with_aliases(variables, BATCH_HOOKS, "", HOOK_BATCH_ALIASES)
        _sync_state_variables(state, variables)
        sync_runtime_state(state)

        progress = 42 + int(((actual_index + 1) / total_batches) * 14)
        hook_write_stage = _stage_name_for_runner(runner, STAGE_HOOK_WRITE, STAGE_HOOKS_WRITING)
        hook_review_stage = _stage_name_for_runner(runner, STAGE_HOOK_REVIEW, STAGE_HOOKS_REVIEW)
        hook_revise_stage = _stage_name_for_runner(runner, STAGE_HOOK_REVISE, STAGE_HOOKS_REWRITE)
        if pending_hook_memory_only:
            batch_hooks = copy.deepcopy(existing_batch_hooks)
            set_with_aliases(variables, BATCH_HOOKS, batch_hooks, HOOK_BATCH_ALIASES)
            _sync_state_variables(state, variables)
            sync_runtime_state(state)
        else:
            hook_base = _build_hook_stage_context(
                variables,
                stage_name=hook_write_stage,
                plan_for_batch=plan_for_batch,
                normalized_plan_for_batch=normalized_plan_for_batch,
                alias_plan_for_batch=alias_plan_for_batch,
                batch_start_episode=batch.start_episode,
                hook_memory=get_with_aliases(
                    variables,
                    HOOK_MEMORY,
                    HOOK_MEMORY_ALIASES,
                    "",
                ),
            )
            _log_batched_stage_input(
                hook_write_stage,
                stage_label="开头冲突钩子",
                batch_label=batch.label,
                fields={
                    "batch_plan": hook_base.get(EPISODE_PLAN),
                    "worldview": hook_base.get(WORLDVIEW),
                    "characters": hook_base.get(CHARACTERS),
                    "scenes": hook_base.get(SCENES),
                    "story_outline": hook_base.get(STORY_OUTLINE),
                    "appearance_mapping": hook_base.get(APPEARANCE_MAPPING),
                    "hook_memory": hook_base.get(HOOK_MEMORY),
                },
                wire_context=hook_base,
                memory_fields=("hook_memory",),
            )
            batch_hooks, review_payload = _run_batch_write_review_revise_loop(
                state,
                runner,
                variables=variables,
                batch=batch,
                stage_key="hook",
                stage_label="开头冲突钩子",
                output_field=BATCH_HOOKS,
                current_output_var=HOOK_CURRENT_VAR,
                review_output_var=HOOK_REVIEW_OUTPUT_VAR,
                retry_var=HOOK_RETRY_VAR,
                max_retry_var=HOOK_MAX_RETRY_VAR,
                writing_stage_name=hook_write_stage,
                review_stage_name=hook_review_stage,
                rewrite_stage_name=hook_revise_stage,
                writing_context=hook_base,
                review_context_builder=lambda current_output: _build_hook_stage_context(
                    variables,
                    stage_name=hook_review_stage,
                    plan_for_batch=plan_for_batch,
                    normalized_plan_for_batch=normalized_plan_for_batch,
                    alias_plan_for_batch=alias_plan_for_batch,
                    batch_start_episode=batch.start_episode,
                    hook_memory=get_with_aliases(
                        variables,
                        HOOK_MEMORY,
                        HOOK_MEMORY_ALIASES,
                        "",
                    ),
                    batch_hooks=current_output,
                ),
                rewrite_context_builder=lambda current_output, current_review: _build_hook_stage_context(
                    variables,
                    stage_name=hook_revise_stage,
                    plan_for_batch=plan_for_batch,
                    normalized_plan_for_batch=normalized_plan_for_batch,
                    alias_plan_for_batch=alias_plan_for_batch,
                    batch_start_episode=batch.start_episode,
                    hook_memory=get_with_aliases(
                        variables,
                        HOOK_MEMORY,
                        HOOK_MEMORY_ALIASES,
                        "",
                    ),
                    batch_hooks=current_output,
                    review_payload=current_review,
                ),
                progress_percent=progress,
                approved_output_validator=lambda current_output: validate_batch_hooks(
                    current_output,
                    batch,
                ),
            )
            state.set_output(hook_review_stage, "last_committed_review", copy.deepcopy(review_payload))
            all_hooks = merge_batch_hooks(all_hooks, batch_hooks, batch)
            set_with_aliases(variables, BATCH_HOOKS, batch_hooks, HOOK_BATCH_ALIASES)
            set_with_aliases(variables, ALL_HOOKS, all_hooks, HOOK_FINAL_ALIASES)
            _sync_state_variables(state, variables)
            sync_runtime_state(state)
        state.set_output(STAGE_HOOK_MEMORY, "contract_guard", {})
        try:
            hook_memory_output = _run_optional_memory_stage(
                state,
                runner,
                STAGE_HOOK_MEMORY,
                {
                    BATCH_HOOKS: batch_hooks,
                    HOOK_MEMORY: get_with_aliases(variables, HOOK_MEMORY, HOOK_MEMORY_ALIASES, ""),
                    APPEARANCE_MAPPING: _compact_stage_text(
                        alias_plan_for_batch,
                        builder=build_compact_appearance_context_for_batch,
                        fallback="",
                    ),
                    TOTAL_EPISODES: variables.get(TOTAL_EPISODES),
                    BATCH_START_EPISODE: batch.start_episode,
                    EPISODE_PLAN: plan_for_batch,
                },
                stage_key="hook",
                message=f"正在写入开头冲突钩子记忆：第 {batch.label} 集",
                batch_label=batch.label,
                progress_percent=progress,
                generated_episodes=batch.end_episode,
                fallback_output={HOOK_MEMORY: get_with_aliases(variables, HOOK_MEMORY, HOOK_MEMORY_ALIASES, "")},
                output_field=HOOK_MEMORY,
                batch=batch,
                memory_normalizer=_normalize_hook_memory_output,
                memory_kwargs={
                    "batch": batch,
                    "batch_hooks": batch_hooks,
                    "previous_memory": get_with_aliases(variables, HOOK_MEMORY, HOOK_MEMORY_ALIASES, ""),
                },
            )
        except Exception:
            set_runtime_stage(
                state,
                "hook",
                f"开头冲突钩子 {batch.label} 集正文已保留，记忆补跑失败，请继续生成重试。",
                progress_percent=progress,
                generated_episodes=batch.end_episode,
            )
            _sync_state_variables(state, variables)
            sync_runtime_state(state)
            raise ValueError(
                f"开头冲突钩子 {batch.label} 集记忆生成失败，已保留当前批内容，请继续生成以补跑记忆。"
            )
        set_with_aliases(
            variables,
            HOOK_MEMORY,
            get_with_aliases(hook_memory_output, HOOK_MEMORY, HOOK_MEMORY_ALIASES, ""),
            HOOK_MEMORY_ALIASES,
        )
        variables[LOCAL_HOOK_CHECKPOINT_START] = batch.start_episode
        variables[BATCH_START_EPISODE] = batch.end_episode + 1
        variables[LOCAL_COMPLETED_BATCHES] = actual_index + 1
        variables[LOCAL_CURRENT_BATCH_INDEX] = actual_index + 1
        variables[HOOK_RETRY_VAR] = 0
        _sync_state_variables(state, variables)
        sync_runtime_state(state)


def _run_dialogue_batches(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
    *,
    batches: list[BatchWindow],
    normalized_plan: dict[str, Any] | None,
    episode_alias_plan: dict[str, Any] | None,
    rewrite_from_stage: str,
    batch_index_offset: int = 0,
    total_batches: int | None = None,
) -> None:
    """承接开头冲突钩子阶段，为所有批次补齐角色对白。"""
    total_batches = max(1, total_batches or len(batches))
    all_hooks = _dict_or_empty(get_with_aliases(variables, ALL_HOOKS, HOOK_FINAL_ALIASES, {}))
    all_dialogues = _dict_or_empty(
        get_with_aliases(variables, ALL_DIALOGUES, DIALOGUE_FINAL_ALIASES, {})
    )
    if not _phase_object_complete(all_hooks, batches):
        raise ValueError("角色对白阶段启动失败：ALL_HOOKS 尚未完整覆盖全部集数。")
    if (
        rewrite_from_stage in {"script", "final"}
        and _phase_object_complete(all_dialogues, batches)
        and _pending_dialogue_memory_batch_start(variables, batches=batches) is None
    ):
        set_runtime_stage(
            state,
            "dialogue",
            "已保留完整角色对白，直接进入正文阶段。",
            progress_percent=70,
        )
        return

    for index, batch in enumerate(batches):
        actual_index = batch_index_offset + index
        existing_batch_dialogues = _current_batch_object_payload(
            variables.get(BATCH_DIALOGUES),
            all_dialogues,
            batch=batch,
        )
        pending_dialogue_memory_only = _is_pending_dialogue_memory_recovery(
            variables,
            batch=batch,
            batch_payload=existing_batch_dialogues,
        )
        if _batch_object_is_reusable(existing_batch_dialogues, batch) and not pending_dialogue_memory_only:
            set_with_aliases(
                variables,
                BATCH_DIALOGUES,
                existing_batch_dialogues,
                DIALOGUE_BATCH_ALIASES,
            )
            variables[LOCAL_DIALOGUE_CHECKPOINT_START] = batch.start_episode
            variables[BATCH_START_EPISODE] = batch.end_episode + 1
            variables[LOCAL_COMPLETED_BATCHES] = actual_index + 1
            variables[LOCAL_CURRENT_BATCH_INDEX] = actual_index + 1
            variables[LOCAL_CURRENT_BATCH_STAGE] = ""
            continue

        plan_for_batch, normalized_plan_for_batch = _get_episode_batch_plan_context(
            normalized_plan,
            batch.start_episode,
            batch_size=batch.size,
            raw_episode_plan=_raw_episode_plan_source(payload, variables),
        )
        _ensure_plan_matches_batch(plan_for_batch, batch=batch, stage_label="角色对话")
        alias_plan_for_batch = slice_episode_alias_plan_for_batch(episode_alias_plan, batch)
        hook_payload = slice_object_episodes_for_batch(all_hooks, batch)
        _ensure_batch_object_matches(
            hook_payload,
            batch=batch,
            stage_label="角色对话",
            field_label="开头冲突钩子",
        )

        variables[BATCH_START_EPISODE] = batch.start_episode
        variables[LOCAL_COMPLETED_BATCHES] = actual_index
        variables[LOCAL_CURRENT_BATCH_INDEX] = actual_index
        variables[LOCAL_CURRENT_BATCH_STAGE] = "dialogue"
        set_with_aliases(
            variables,
            DIALOGUE_MEMORY,
            get_with_aliases(variables, DIALOGUE_MEMORY, DIALOGUE_MEMORY_ALIASES, ""),
            DIALOGUE_MEMORY_ALIASES,
        )
        set_with_aliases(variables, BATCH_HOOKS, hook_payload, DIALOGUE_HOOK_INPUT_ALIASES)
        set_with_aliases(variables, BATCH_DIALOGUES, "", DIALOGUE_BATCH_ALIASES)
        _sync_state_variables(state, variables)
        sync_runtime_state(state)

        progress = 58 + int(((actual_index + 1) / total_batches) * 14)
        dialogue_write_stage = _stage_name_for_runner(
            runner,
            STAGE_DIALOGUE_WRITE,
            STAGE_DIALOGUES_WRITING,
        )
        dialogue_review_stage = _stage_name_for_runner(
            runner,
            STAGE_DIALOGUE_REVIEW,
            STAGE_DIALOGUES_REVIEW,
        )
        dialogue_revise_stage = _stage_name_for_runner(
            runner,
            STAGE_DIALOGUE_REVISE,
            STAGE_DIALOGUES_REWRITE,
        )
        if pending_dialogue_memory_only:
            batch_dialogues = copy.deepcopy(existing_batch_dialogues)
            set_with_aliases(variables, BATCH_DIALOGUES, batch_dialogues, DIALOGUE_BATCH_ALIASES)
            _sync_state_variables(state, variables)
            sync_runtime_state(state)
        else:
            dialogue_base = _build_dialogue_stage_context(
                variables,
                stage_name=dialogue_write_stage,
                plan_for_batch=plan_for_batch,
                normalized_plan_for_batch=normalized_plan_for_batch,
                alias_plan_for_batch=alias_plan_for_batch,
                hook_payload=hook_payload,
                batch_start_episode=batch.start_episode,
                dialogue_memory=get_with_aliases(
                    variables,
                    DIALOGUE_MEMORY,
                    DIALOGUE_MEMORY_ALIASES,
                    "",
                ),
            )
            _log_batched_stage_input(
                dialogue_write_stage,
                stage_label="角色对话",
                batch_label=batch.label,
                fields={
                    "batch_plan": dialogue_base.get(EPISODE_PLAN),
                    "batch_hooks": dialogue_base.get(BATCH_HOOKS),
                    "worldview": dialogue_base.get(WORLDVIEW),
                    "characters": dialogue_base.get(CHARACTERS),
                    "scenes": dialogue_base.get(SCENES),
                    "appearance_mapping": dialogue_base.get(APPEARANCE_MAPPING),
                    "dialogue_memory": dialogue_base.get(DIALOGUE_MEMORY),
                },
                wire_context=dialogue_base,
                memory_fields=("dialogue_memory",),
            )
            batch_dialogues, review_payload = _run_batch_write_review_revise_loop(
                state,
                runner,
                variables=variables,
                batch=batch,
                stage_key="dialogue",
                stage_label="角色对白",
                output_field=BATCH_DIALOGUES,
                current_output_var=DIALOGUE_CURRENT_WORKFLOW_VAR,
                review_output_var=DIALOGUE_REVIEW_OUTPUT_VAR,
                retry_var=DIALOGUE_RETRY_VAR,
                max_retry_var=DIALOGUE_MAX_RETRY_VAR,
                writing_stage_name=dialogue_write_stage,
                review_stage_name=dialogue_review_stage,
                rewrite_stage_name=dialogue_revise_stage,
                writing_context=dialogue_base,
                review_context_builder=lambda current_output: _build_dialogue_stage_context(
                    variables,
                    stage_name=dialogue_review_stage,
                    plan_for_batch=plan_for_batch,
                    normalized_plan_for_batch=normalized_plan_for_batch,
                    alias_plan_for_batch=alias_plan_for_batch,
                    hook_payload=hook_payload,
                    batch_start_episode=batch.start_episode,
                    batch_dialogues=current_output,
                ),
                rewrite_context_builder=lambda current_output, current_review: _build_dialogue_stage_context(
                    variables,
                    stage_name=dialogue_revise_stage,
                    plan_for_batch=plan_for_batch,
                    normalized_plan_for_batch=normalized_plan_for_batch,
                    alias_plan_for_batch=alias_plan_for_batch,
                    hook_payload=hook_payload,
                    batch_start_episode=batch.start_episode,
                    dialogue_memory=get_with_aliases(
                        variables,
                        DIALOGUE_MEMORY,
                        DIALOGUE_MEMORY_ALIASES,
                        "",
                    ),
                    batch_dialogues=current_output,
                    review_payload=current_review,
                ),
                progress_percent=progress,
                before_rewrite=lambda _current_output, _current_review: _ensure_dialogue_revise_workflow_available(),
                approved_output_validator=lambda current_output: validate_batch_dialogues(
                    current_output,
                    batch,
                ),
            )
            state.set_output(dialogue_review_stage, "last_committed_review", copy.deepcopy(review_payload))
            all_dialogues = merge_batch_dialogues(all_dialogues, batch_dialogues, batch)
            set_with_aliases(variables, BATCH_DIALOGUES, batch_dialogues, DIALOGUE_BATCH_ALIASES)
            set_with_aliases(variables, ALL_DIALOGUES, all_dialogues, DIALOGUE_FINAL_ALIASES)
            _sync_state_variables(state, variables)
            sync_runtime_state(state)
        state.set_output(STAGE_DIALOGUE_MEMORY, "contract_guard", {})
        try:
            dialogue_memory_output = _run_optional_memory_stage(
                state,
                runner,
                STAGE_DIALOGUE_MEMORY,
                {
                    BATCH_DIALOGUES: batch_dialogues,
                    DIALOGUE_MEMORY: get_with_aliases(
                        variables,
                        DIALOGUE_MEMORY,
                        DIALOGUE_MEMORY_ALIASES,
                        "",
                    ),
                    ALL_HOOKS: copy.deepcopy(hook_payload),
                    EPISODE_PLAN: plan_for_batch,
                    APPEARANCE_MAPPING: _compact_stage_text(
                        alias_plan_for_batch,
                        builder=build_compact_appearance_context_for_batch,
                        fallback="",
                    ),
                    TOTAL_EPISODES: variables.get(TOTAL_EPISODES),
                    BATCH_START_EPISODE: batch.start_episode,
                    CHARACTER_ALIAS_NAMING_RULES: variables.get(CHARACTER_ALIAS_NAMING_RULES) or "",
                },
                stage_key="dialogue",
                message=f"正在写入角色对白记忆：第 {batch.label} 集",
                batch_label=batch.label,
                progress_percent=progress,
                generated_episodes=batch.end_episode,
                fallback_output={
                    DIALOGUE_MEMORY: get_with_aliases(
                        variables,
                        DIALOGUE_MEMORY,
                        DIALOGUE_MEMORY_ALIASES,
                        "",
                    )
                },
                output_field=DIALOGUE_MEMORY,
                batch=batch,
                memory_normalizer=_normalize_dialogue_memory_output,
                memory_kwargs={
                    "batch": batch,
                    "batch_dialogues": batch_dialogues,
                    "previous_memory": get_with_aliases(
                        variables,
                        DIALOGUE_MEMORY,
                        DIALOGUE_MEMORY_ALIASES,
                        "",
                    ),
                },
            )
        except Exception:
            set_runtime_stage(
                state,
                "dialogue",
                f"角色对白 {batch.label} 集正文已保留，记忆补跑失败，请继续生成重试。",
                progress_percent=progress,
                generated_episodes=batch.end_episode,
            )
            _sync_state_variables(state, variables)
            sync_runtime_state(state)
            raise ValueError(
                f"角色对白 {batch.label} 集记忆生成失败，已保留当前批内容，请继续生成以补跑记忆。"
            )
        set_with_aliases(
            variables,
            DIALOGUE_MEMORY,
            get_with_aliases(dialogue_memory_output, DIALOGUE_MEMORY, DIALOGUE_MEMORY_ALIASES, ""),
            DIALOGUE_MEMORY_ALIASES,
        )
        variables[LOCAL_DIALOGUE_CHECKPOINT_START] = batch.start_episode
        variables[BATCH_START_EPISODE] = batch.end_episode + 1
        variables[LOCAL_COMPLETED_BATCHES] = actual_index + 1
        variables[LOCAL_CURRENT_BATCH_INDEX] = actual_index + 1
        variables[DIALOGUE_RETRY_VAR] = 0
        _sync_state_variables(state, variables)
        sync_runtime_state(state)


def _run_script_batches(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
    *,
    batches: list[BatchWindow],
    normalized_plan: dict[str, Any] | None,
    episode_alias_plan: dict[str, Any] | None,
    rewrite_from_stage: str,
    batch_index_offset: int = 0,
    total_batches: int | None = None,
) -> None:
    """承接对白阶段，逐批生成正文并把记忆覆盖到下一批上下文里。"""
    total_batches = max(1, total_batches or len(batches))
    all_hooks = _dict_or_empty(get_with_aliases(variables, ALL_HOOKS, HOOK_FINAL_ALIASES, {}))
    all_dialogues = _dict_or_empty(
        get_with_aliases(variables, ALL_DIALOGUES, DIALOGUE_FINAL_ALIASES, {})
    )
    if not _phase_object_complete(all_hooks, batches):
        raise ValueError("剧本正文阶段启动失败：ALL_HOOKS 尚未完整覆盖全部集数。")
    if not _phase_object_complete(all_dialogues, batches):
        raise ValueError("剧本正文阶段启动失败：ALL_DIALOGUES 尚未完整覆盖全部集数。")
    _repair_script_outputs(
        variables,
        total_episodes=payload.total_episodes,
        batch_size=max(1, int(settings.batch_size or 5)),
    )
    committed_script = str(
        variables.get(LOCAL_COMMITTED_SCRIPT)
        or get_with_aliases(variables, ALL_SCRIPT, SCRIPT_FINAL_ALIASES, "")
        or ""
    ).strip()
    script_batches = _normalize_batch_text_map(variables.get(LOCAL_SCRIPT_BATCHES))
    script_episode_cache = _normalize_episode_script_map(variables.get(LOCAL_SCRIPT_EPISODES))
    summary_by_batch = _normalize_batch_text_map(variables.get(LOCAL_SUMMARY_BY_BATCH))
    appearance_memory_by_batch = _normalize_batch_object_map(
        variables.get(LOCAL_APPEARANCE_MEMORY_BY_BATCH)
    )

    for index, batch in enumerate(batches):
        actual_index = batch_index_offset + index
        plan_for_batch, normalized_plan_for_batch = _get_episode_batch_plan_context(
            normalized_plan,
            batch.start_episode,
            batch_size=batch.size,
            raw_episode_plan=_raw_episode_plan_source(payload, variables),
        )
        _ensure_plan_matches_batch(plan_for_batch, batch=batch, stage_label="剧本正文")
        alias_plan_for_batch = slice_episode_alias_plan_for_batch(episode_alias_plan, batch)
        hook_payload = slice_object_episodes_for_batch(all_hooks, batch)
        dialogue_payload = slice_object_episodes_for_batch(all_dialogues, batch)
        _ensure_batch_object_matches(
            hook_payload,
            batch=batch,
            stage_label="剧本正文",
            field_label="开头冲突钩子",
        )
        _ensure_batch_object_matches(
            dialogue_payload,
            batch=batch,
            stage_label="剧本正文",
            field_label="角色对白",
        )

        existing_batch_script = _existing_batch_script_text(
            batch,
            script_batches=script_batches,
            script_episode_cache=script_episode_cache,
        )
        existing_summary = str(summary_by_batch.get(batch.start_episode) or "").strip()
        existing_memory = copy.deepcopy(appearance_memory_by_batch.get(batch.start_episode) or {})
        batch_script = existing_batch_script

        if (
            existing_batch_script
            and existing_summary
            and _script_batch_memory_entry_exists(appearance_memory_by_batch, batch)
            and not _validate_script_batch_output(
            existing_batch_script,
            batch=batch,
            )
        ):
            # 只有“正文 + 对应记忆”同时存在，才把这一批视为可直接复用。
            # 只缓存正文而没有 memory，会让下一批上下文断层，所以宁可重跑也不盲跳过。
            set_with_aliases(variables, BATCH_SCRIPT, existing_batch_script, SCRIPT_BATCH_ALIASES)
            set_with_aliases(
                variables,
                SCRIPT_MEMORY,
                _bounded_script_memory(existing_summary),
                SCRIPT_MEMORY_ALIASES,
            )
            variables[LAST_SUMMARY] = variables[SCRIPT_MEMORY]
            if existing_memory:
                variables[APPEARANCE_CONTINUITY_MEMORY] = existing_memory
            else:
                variables.pop(APPEARANCE_CONTINUITY_MEMORY, None)
            variables[LOCAL_SCRIPT_CHECKPOINT_START] = batch.start_episode
            variables[BATCH_START_EPISODE] = batch.end_episode + 1
            variables[LOCAL_COMPLETED_BATCHES] = actual_index + 1
            variables[LOCAL_CURRENT_BATCH_INDEX] = actual_index + 1
            variables[LOCAL_CURRENT_BATCH_STAGE] = ""
            continue

        generated_before_batch = max(0, batch.start_episode - 1)
        variables[BATCH_START_EPISODE] = batch.start_episode
        variables[LOCAL_COMPLETED_BATCHES] = actual_index
        variables[LOCAL_CURRENT_BATCH_INDEX] = actual_index
        variables[LOCAL_CURRENT_BATCH_STAGE] = "script"
        set_with_aliases(variables, BATCH_HOOKS, hook_payload, SCRIPT_HOOK_INPUT_ALIASES)
        set_with_aliases(variables, BATCH_DIALOGUES, dialogue_payload, SCRIPT_DIALOGUE_INPUT_ALIASES)
        set_with_aliases(
            variables,
            SCRIPT_MEMORY,
            get_with_aliases(variables, SCRIPT_MEMORY, SCRIPT_MEMORY_ALIASES, variables.get(LAST_SUMMARY) or ""),
            SCRIPT_MEMORY_ALIASES,
        )
        variables[LAST_SUMMARY] = variables.get(SCRIPT_MEMORY, "")
        if not batch_script:
            set_with_aliases(variables, BATCH_SCRIPT, "", SCRIPT_BATCH_ALIASES)
        _sync_state_variables(state, variables)
        sync_runtime_state(state)

        if not batch_script:
            script_write_stage = _stage_name_for_runner(
                runner,
                STAGE_SCRIPT_WRITE,
                STAGE_SCRIPT_WRITING,
            )
            script_revise_stage = _stage_name_for_runner(
                runner,
                STAGE_SCRIPT_REVISE,
                STAGE_SCRIPT_REWRITE,
            )
            previous_batch_summary = _build_previous_script_context(
                script_batches,
                script_episode_cache,
                committed_script,
                current_batch_start=batch.start_episode,
            )
            script_memory = _bounded_script_memory(variables.get(LAST_SUMMARY))
            script_base = _build_script_stage_context(
                variables,
                batch=batch,
                script_stage_name=script_write_stage,
                plan_for_batch=plan_for_batch,
                normalized_plan_for_batch=normalized_plan_for_batch,
                alias_plan_for_batch=alias_plan_for_batch,
                hook_payload=hook_payload,
                dialogue_payload=dialogue_payload,
                previous_batch_summary=previous_batch_summary,
                script_memory=script_memory,
            )
            _log_batched_stage_input(
                STAGE_SCRIPT,
                stage_label="剧本正文",
                batch_label=batch.label,
                fields={
                    "batch_plan": script_base.get(EPISODE_PLAN),
                    "batch_hooks": script_base.get(BATCH_HOOKS),
                    "batch_dialogues": script_base.get(BATCH_DIALOGUES),
                    "previous_batch_summary": script_base.get(ALL_SCRIPT),
                    "script_memory": script_base.get(LAST_SUMMARY),
                    "appearance_mapping": script_base.get(APPEARANCE_MAPPING),
                    "character_scene_bundle": _build_script_character_scene_bundle_for_estimate(
                        script_base.get(CHARACTERS),
                        script_base.get(SCENES),
                    ),
                    "worldview": script_base.get(WORLDVIEW),
                },
                wire_context=script_base,
                memory_fields=("previous_batch_summary", "script_memory"),
            )
            progress = 72 + int((actual_index / total_batches) * 20)
            try:
                batch_script, review_payload = _run_batch_write_review_revise_loop(
                    state,
                    runner,
                    variables=variables,
                    batch=batch,
                    stage_key="script",
                    stage_label="剧本正文",
                    output_field=BATCH_SCRIPT,
                    current_output_var=SCRIPT_CURRENT_VAR,
                    review_output_var=SCRIPT_REVIEW_OUTPUT_VAR,
                    retry_var=SCRIPT_RETRY_VAR,
                    max_retry_var=SCRIPT_MAX_RETRY_VAR,
                    writing_stage_name=script_write_stage,
                    review_stage_name=STAGE_SCRIPT_REVIEW,
                    rewrite_stage_name=script_revise_stage,
                    writing_context=script_base,
                    review_context_builder=lambda current_output: {
                        **_build_script_stage_context(
                            variables,
                            batch=batch,
                            plan_for_batch=plan_for_batch,
                            normalized_plan_for_batch=normalized_plan_for_batch,
                            alias_plan_for_batch=alias_plan_for_batch,
                            hook_payload=hook_payload,
                            dialogue_payload=dialogue_payload,
                            script_memory=_bounded_script_memory(variables.get(LAST_SUMMARY)),
                            script_stage_name=STAGE_SCRIPT_REVIEW,
                        ),
                        BATCH_SCRIPT: current_output,
                    },
                    rewrite_context_builder=lambda current_output, current_review: {
                        **_build_script_stage_context(
                            variables,
                            batch=batch,
                            plan_for_batch=plan_for_batch,
                            normalized_plan_for_batch=normalized_plan_for_batch,
                            alias_plan_for_batch=alias_plan_for_batch,
                            hook_payload=hook_payload,
                            dialogue_payload=dialogue_payload,
                            script_memory=_bounded_script_memory(variables.get(LAST_SUMMARY)),
                            script_stage_name=script_revise_stage,
                        ),
                        BATCH_SCRIPT: current_output,
                        PASS_REVIEW_JSON: current_review,
                    },
                    progress_percent=progress,
                    generated_episodes=generated_before_batch,
                    approved_output_validator=lambda current_output: validate_batch_script_text(
                        current_output,
                        batch,
                    ),
                )
            except _RetryWithSmallerScriptBatch as exc:
                smaller_batches = _split_batch_window(
                    batch,
                    batch_size=exc.next_batch_size,
                )
                logger.warning(
                    {
                        "type": "script_auto_repair",
                        "strategy": "缩小批次",
                        "missing_episodes": _detect_missing_episodes(exc.failure_reasons),
                        "retry_count": SCRIPT_AUTO_REPAIR_MAX_RETRIES,
                        "batch_label": batch.label,
                        "next_batch_size": exc.next_batch_size,
                        "failure_reasons": list(exc.failure_reasons[:10]),
                    }
                )
                set_runtime_stage(
                    state,
                    "script",
                    f"剧本正文 {batch.label} 集自动修复未完成，正在降级为 {exc.next_batch_size} 集批次继续生成。",
                    batch_label=batch.label,
                    progress_percent=progress,
                    generated_episodes=generated_before_batch,
                )
                sync_runtime_state(state)
                set_with_aliases(variables, BATCH_SCRIPT, "", SCRIPT_BATCH_ALIASES)
                variables[SCRIPT_CURRENT_VAR] = ""
                variables[SCRIPT_RETRY_VAR] = 0
                _sync_state_variables(state, variables)
                sync_runtime_state(state)
                remaining_batches = list(batches[index + 1 :])
                _run_script_batches(
                    state,
                    runner,
                    payload,
                    variables,
                    batches=[*smaller_batches, *remaining_batches],
                    normalized_plan=normalized_plan,
                    episode_alias_plan=episode_alias_plan,
                    rewrite_from_stage=rewrite_from_stage,
                    batch_index_offset=actual_index,
                    total_batches=actual_index + len(smaller_batches) + len(remaining_batches),
                )
                return
            state.set_output(STAGE_SCRIPT_REVIEW, "last_committed_review", copy.deepcopy(review_payload))
            set_with_aliases(variables, BATCH_SCRIPT, batch_script, SCRIPT_BATCH_ALIASES)
            script_episode_cache.update(_extract_script_episode_map(batch_script, batch))
            script_batches[batch.start_episode] = batch_script
            variables[LOCAL_SCRIPT_BATCHES] = _string_keyed_batch_map(script_batches)
            variables[LOCAL_SCRIPT_EPISODES] = _string_keyed_batch_map(script_episode_cache)
            variables[LOCAL_SCRIPT_CHECKPOINT_START] = batch.start_episode
            if script_episode_cache:
                set_with_aliases(
                    variables,
                    ALL_SCRIPT,
                    _join_script_episode_map(script_episode_cache),
                    SCRIPT_FINAL_ALIASES,
                )
            else:
                set_with_aliases(
                    variables,
                    ALL_SCRIPT,
                    _join_script_parts(committed_script, batch_script),
                    SCRIPT_FINAL_ALIASES,
                )
            committed_script = str(
                get_with_aliases(variables, ALL_SCRIPT, SCRIPT_FINAL_ALIASES, "") or ""
            ).strip()
            variables[LOCAL_COMMITTED_SCRIPT] = (
                get_with_aliases(variables, ALL_SCRIPT, SCRIPT_FINAL_ALIASES, "") or committed_script
            )
            _sync_state_variables(state, variables)
            sync_runtime_state(state)
        else:
            set_with_aliases(variables, BATCH_SCRIPT, batch_script, SCRIPT_BATCH_ALIASES)

        _sync_state_variables(state, variables)
        sync_runtime_state(state)

        memory_progress = 78 + int(((actual_index + 1) / total_batches) * 20)
        previous_script_memory = _bounded_script_memory(variables.get(LAST_SUMMARY))
        state.set_output(STAGE_SCRIPT_MEMORY, "contract_guard", {})
        try:
            memory_output = run_stage_with_contract_guard(
                state,
                runner,
                STAGE_SCRIPT_MEMORY,
                {
                    BATCH_SCRIPT: batch_script,
                    LAST_SUMMARY: previous_script_memory,
                    APPEARANCE_MAPPING: _compact_stage_text(
                        alias_plan_for_batch,
                        builder=build_compact_appearance_context_for_batch,
                        fallback="",
                    ),
                    CHARACTER_ALIAS_NAMING_RULES: variables.get(CHARACTER_ALIAS_NAMING_RULES) or "",
                },
                stage_key="script",
                message=f"正在写入剧本正文记忆：第 {batch.label} 集",
                batch_label=batch.label,
                progress_percent=memory_progress,
                generated_episodes=batch.end_episode,
                output_field=LAST_SUMMARY,
                batch=batch,
                memory_normalizer=_normalize_script_memory_output,
                memory_kwargs={
                    "batch": batch,
                    "batch_script": batch_script,
                    "previous_memory": variables.get(LAST_SUMMARY),
                },
                sync_output_to_state=False,
            )
        except Exception:
            set_runtime_stage(
                state,
                "script",
                f"剧本正文 {batch.label} 集正文已保留，记忆补跑失败，请继续生成重试。",
                progress_percent=memory_progress,
                generated_episodes=batch.end_episode,
            )
            _sync_state_variables(state, variables)
            sync_runtime_state(state)
            raise ValueError(
                f"剧本正文 {batch.label} 集记忆生成失败，已保留当前批内容，请继续生成以补跑记忆。"
            )
        new_script_memory = _bounded_script_memory(
            get_with_aliases(
                memory_output,
                LAST_SUMMARY,
                SCRIPT_MEMORY_ALIASES,
                memory_output.get(LAST_SUMMARY) or memory_output.get("answerText"),
            )
        )
        set_with_aliases(variables, SCRIPT_MEMORY, new_script_memory, SCRIPT_MEMORY_ALIASES)
        variables[LAST_SUMMARY] = new_script_memory
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
        variables[BATCH_START_EPISODE] = batch.end_episode + 1
        variables[LOCAL_COMPLETED_BATCHES] = actual_index + 1
        variables[LOCAL_COMMITTED_SCRIPT] = (
            get_with_aliases(variables, ALL_SCRIPT, SCRIPT_FINAL_ALIASES, "") or committed_script
        )
        committed_script = str(variables.get(LOCAL_COMMITTED_SCRIPT) or committed_script).strip()
        variables[LOCAL_CURRENT_BATCH_INDEX] = actual_index + 1
        variables[LOCAL_CURRENT_BATCH_STAGE] = ""
        variables[SCRIPT_RETRY_VAR] = 0
        _sync_state_variables(state, variables)
        sync_runtime_state(state)


def _normalize_script_memory_output(
    value: Any,
    *,
    batch: BatchWindow,
    batch_script: Any,
    previous_memory: Any,
) -> str:
    text = str(value or "").strip()
    required_keys = {
        "final_hook_of_this_turn",
        "must_carry_into_next_turn",
        "appearance_continuity_summary",
    }
    try:
        parsed = parse_json(text)
        if not isinstance(parsed, dict):
            raise ValueError("memory output is not a JSON object")
        missing = sorted(key for key in required_keys if key not in parsed)
        if missing:
            raise ValueError(f"memory output missing keys: {', '.join(missing)}")
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(
            "script memory %s output invalid; generated local debug preview only: %s",
            batch.label,
            _truncate_log_text(str(exc), max_chars=240),
        )

    fallback = {
        "this_turn_episodes": list(range(batch.start_episode, batch.end_episode + 1)),
        "abstract_of_this_turn": _truncate_log_text(str(batch_script or ""), max_chars=1200),
        "final_hook_of_this_turn": "",
        "must_carry_into_next_turn": [],
        "appearance_continuity_summary": "",
        "previous_memory_parse_failed_or_missing": bool(str(previous_memory or "").strip()),
    }
    return json.dumps(fallback, ensure_ascii=False, indent=2)


def _normalize_json_memory_output(
    value: Any,
    *,
    batch: BatchWindow,
    required_keys: set[str],
    fallback: dict[str, Any],
    label: str,
) -> str:
    try:
        parsed = value if isinstance(value, dict) else parse_json(str(value or "").strip())
        if not isinstance(parsed, dict):
            raise ValueError("memory output is not a JSON object")
        missing = sorted(key for key in required_keys if key not in parsed)
        if missing:
            raise ValueError(f"memory output missing keys: {', '.join(missing)}")
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(
            "%s memory %s output invalid; generated local debug preview only: %s",
            label,
            batch.label,
            _truncate_log_text(str(exc), max_chars=240),
        )
    return json.dumps(fallback, ensure_ascii=False, indent=2)


def _normalize_hook_memory_output(
    value: Any,
    *,
    batch: BatchWindow,
    batch_hooks: Any,
    previous_memory: Any,
) -> str:
    fallback = {
        "this_turn_episodes": list(range(batch.start_episode, batch.end_episode + 1)),
        "abstract_of_this_turn": _truncate_log_text(
            json.dumps(batch_hooks, ensure_ascii=False, default=str),
            max_chars=1200,
        ),
        "final_hook_of_this_turn": "",
        "must_carry_into_next_turn": [],
        "appearance_alias_continuity_summary": "",
        "previous_memory_parse_failed_or_missing": bool(str(previous_memory or "").strip()),
        "local_fallback": True,
    }
    return _normalize_json_memory_output(
        value,
        batch=batch,
        required_keys={
            "final_hook_of_this_turn",
            "must_carry_into_next_turn",
            "appearance_alias_continuity_summary",
        },
        fallback=fallback,
        label="hook",
    )


def _normalize_dialogue_memory_output(
    value: Any,
    *,
    batch: BatchWindow,
    batch_dialogues: Any,
    previous_memory: Any,
) -> str:
    fallback = {
        "this_turn_episodes": list(range(batch.start_episode, batch.end_episode + 1)),
        "dialogue_voice_summary": _truncate_log_text(
            json.dumps(batch_dialogues, ensure_ascii=False, default=str),
            max_chars=1200,
        ),
        "must_carry_into_next_turn": [],
        "alias_usage_continuity": "",
        "previous_memory_parse_failed_or_missing": bool(str(previous_memory or "").strip()),
        "local_fallback": True,
    }
    return _normalize_json_memory_output(
        value,
        batch=batch,
        required_keys={
            "dialogue_voice_summary",
            "must_carry_into_next_turn",
            "alias_usage_continuity",
        },
        fallback=fallback,
        label="dialogue",
    )


def _validate_batch_dialogues_for_reuse(value: Any, batch: BatchWindow) -> list[str]:
    issues = list(validate_batch_dialogues(value, batch) or [])
    if issues:
        return issues
    payload = _normalize_batch_dialogues_payload(value) or {}
    blocks = payload.get("episode_dialogue_blocks")
    if not isinstance(blocks, list):
        return [f"dialogue batch {batch.label} missing episode_dialogue_blocks"]
    for item in blocks:
        if not isinstance(item, dict):
            continue
        episode = _safe_int(item.get("episode"), 0)
        if not isinstance(item.get("dialogue_blocks"), list):
            issues.append(
                f"dialogue episode {episode or '?'} cache must use nested dialogue_blocks structure"
            )
    return issues


def _batch_object_reuse_issues(value: Any, batch: BatchWindow) -> list[str]:
    payload = _dict_or_empty(value)
    if not payload:
        return [f"batch {batch.label} payload is empty"]
    if not _batch_object_covers_window(payload, batch):
        return [f"batch {batch.label} does not cover expected episode window"]

    list_key = _batch_object_episode_list_key(payload)
    if list_key == "episodes":
        return list(validate_batch_hooks(payload, batch) or [])
    if list_key == "episode_dialogue_blocks":
        return _validate_batch_dialogues_for_reuse(payload, batch)
    return [f"batch {batch.label} is not a recognized hooks/dialogues payload"]


def _batch_object_is_reusable(value: Any, batch: BatchWindow) -> bool:
    return not _batch_object_reuse_issues(value, batch)


def _find_batch_by_start(
    batches: list[BatchWindow],
    start_episode: Any,
) -> BatchWindow | None:
    start = _safe_int(start_episode, 0)
    if start <= 0:
        return None
    for batch in batches:
        if batch.start_episode == start:
            return batch
    return None


def _current_batch_object_recovery_start(
    variables: dict[str, Any],
    *,
    batches: list[BatchWindow],
    stage_name: str,
    checkpoint_key: str,
    current_value_key: str,
    aggregate_value_key: str,
) -> int | None:
    if str(variables.get(LOCAL_CURRENT_BATCH_STAGE) or "").strip().lower() != stage_name:
        return None
    batch = _find_batch_by_start(batches, variables.get(BATCH_START_EPISODE))
    if batch is None:
        return None
    batch_payload = slice_object_episodes_for_batch(variables.get(aggregate_value_key), batch)
    if not _batch_object_is_reusable(batch_payload, batch):
        return None
    if _safe_int(variables.get(checkpoint_key), 0) == batch.start_episode:
        return None
    return batch.start_episode


def _pending_hook_memory_batch_start(
    variables: dict[str, Any],
    *,
    batches: list[BatchWindow],
) -> int | None:
    return _current_batch_object_recovery_start(
        variables,
        batches=batches,
        stage_name="hook",
        checkpoint_key=LOCAL_HOOK_CHECKPOINT_START,
        current_value_key=BATCH_HOOKS,
        aggregate_value_key=ALL_HOOKS,
    )


def _pending_dialogue_memory_batch_start(
    variables: dict[str, Any],
    *,
    batches: list[BatchWindow],
) -> int | None:
    return _current_batch_object_recovery_start(
        variables,
        batches=batches,
        stage_name="dialogue",
        checkpoint_key=LOCAL_DIALOGUE_CHECKPOINT_START,
        current_value_key=BATCH_DIALOGUES,
        aggregate_value_key=ALL_DIALOGUES,
    )


def _is_pending_hook_memory_recovery(
    variables: dict[str, Any],
    *,
    batch: BatchWindow,
    batch_payload: Any,
) -> bool:
    return (
        str(variables.get(LOCAL_CURRENT_BATCH_STAGE) or "").strip().lower() == "hook"
        and _safe_int(variables.get(BATCH_START_EPISODE), 0) == batch.start_episode
        and _batch_object_is_reusable(
            slice_object_episodes_for_batch(variables.get(ALL_HOOKS), batch),
            batch,
        )
        and _safe_int(variables.get(LOCAL_HOOK_CHECKPOINT_START), 0) != batch.start_episode
    )


def _is_pending_dialogue_memory_recovery(
    variables: dict[str, Any],
    *,
    batch: BatchWindow,
    batch_payload: Any,
) -> bool:
    return (
        str(variables.get(LOCAL_CURRENT_BATCH_STAGE) or "").strip().lower() == "dialogue"
        and _safe_int(variables.get(BATCH_START_EPISODE), 0) == batch.start_episode
        and _batch_object_is_reusable(
            slice_object_episodes_for_batch(variables.get(ALL_DIALOGUES), batch),
            batch,
        )
        and _safe_int(variables.get(LOCAL_DIALOGUE_CHECKPOINT_START), 0) != batch.start_episode
    )


def _phase_object_complete(value: Any, batches: list[BatchWindow]) -> bool:
    """判断某个阶段的累计对象是否已经覆盖了全部批次。"""
    payload = _dict_or_empty(value)
    if not payload:
        return False
    return all(_batch_object_is_reusable(slice_object_episodes_for_batch(payload, batch), batch) for batch in batches)


def _script_batch_memory_entry_exists(
    appearance_memory_by_batch: dict[int, dict[str, Any]],
    batch: BatchWindow,
) -> bool:
    return batch.start_episode in appearance_memory_by_batch


def _script_text_reuse_issues_for_final(
    value: Any,
    *,
    total_episodes: int,
    batches: list[BatchWindow],
) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return ["ALL_SCRIPT is empty"]
    try:
        assert_complete_script(text, total_episodes)
    except ValueError as exc:
        return [str(exc)]

    episode_map = _extract_script_episode_map(
        text,
        BatchWindow(start_episode=1, end_episode=max(1, int(total_episodes))),
    )
    issues: list[str] = []
    for batch in batches:
        batch_text = _join_script_parts(
            *(episode_map.get(episode, "") for episode in range(batch.start_episode, batch.end_episode + 1))
        )
        issues.extend(_validate_script_batch_output(batch_text, batch=batch))
    return issues


def _script_text_is_reusable_for_final(
    value: Any,
    *,
    total_episodes: int,
    batches: list[BatchWindow],
) -> bool:
    return not _script_text_reuse_issues_for_final(
        value,
        total_episodes=total_episodes,
        batches=batches,
    )


def _existing_batch_script_text(
    batch: BatchWindow,
    *,
    script_batches: dict[int, str],
    script_episode_cache: dict[int, str],
) -> str:
    """优先从已缓存的正文里取出当前批次文本，避免重复请求同一批。"""
    cached_batch = str(script_batches.get(batch.start_episode) or "").strip()
    if cached_batch and _has_matching_batch_script_checkpoint(cached_batch, batch=batch, saved_start_episode=batch.start_episode):
        return cached_batch

    episode_parts = [
        text
        for episode, text in sorted(script_episode_cache.items())
        if batch.start_episode <= episode <= batch.end_episode and str(text or "").strip()
    ]
    if len(episode_parts) == batch.size:
        return _join_script_parts(*episode_parts)
    return ""

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


def _normalize_episode_script_map(value: Any) -> dict[int, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[int, str] = {}
    for key, item in value.items():
        episode = _safe_int(key, 0)
        text = str(item or "").strip()
        if episode > 0 and text:
            normalized[episode] = text
    return normalized


def _string_keyed_batch_map(value: dict[int, Any]) -> dict[str, Any]:
    return {str(int(key)): copy.deepcopy(item) for key, item in sorted(value.items()) if int(key) > 0}


def _join_script_episode_map(value: dict[int, str]) -> str:
    return "\n\n".join(
        str(value[episode]).strip()
        for episode in sorted(value)
        if str(value.get(episode) or "").strip()
    ).strip()


def _extract_script_episode_map(
    batch_script: str,
    batch: BatchWindow,
) -> dict[int, str]:
    text = str(batch_script or "").strip()
    if not text:
        return {}

    matches = _script_episode_heading_matches(text)
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


def _script_episode_heading_matches(text: str) -> list[re.Match[str]]:
    utf8_pattern = re.compile(
        r"(?=^[ \t>#*\-]*(?:#{1,6}[ \t]*)?\u7b2c[ \t]*([0-9\uff10-\uff19]+|[\u96f6\u3007\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343\u4e07]+)[ \t]*[\u96c6\u8bdd\u56de\u7ae0])",
        re.MULTILINE,
    )
    matches = list(utf8_pattern.finditer(text))
    if matches:
        return matches
    return list(SCRIPT_EPISODE_HEADING_PATTERN.finditer(text))


def __extract_script_episode_sequence(text: Any) -> list[int]:
    source = str(text or "").strip()
    if not source:
        return []
    sequence: list[int] = []
    for match in _script_episode_heading_matches(source):
        episode = _parse_episode_token(match.group(1))
        if episode is not None and episode > 0:
            sequence.append(episode)
    return sequence


def _duplicate_episode_numbers(sequence: list[int]) -> list[int]:
    return sorted(episode for episode, count in Counter(sequence).items() if episode > 0 and count > 1)


def _validate_script_batch_output_legacy(batch_script: Any, *, batch: BatchWindow) -> list[str]:
    sequence = __extract_script_episode_sequence(batch_script)
    if not sequence:
        return [f"剧本正文 {batch.label} 集缺少可识别的集标题，无法确认当前批次覆盖范围。"]

    issues: list[str] = []
    duplicates = _duplicate_episode_numbers(sequence)
    if duplicates:
        issues.append(
            f"剧本正文 {batch.label} 集存在重复集标题：{_format_episode_ranges(duplicates)}。"
        )

    expected = list(range(batch.start_episode, batch.end_episode + 1))
    expected_set = set(expected)
    out_of_range = sorted({episode for episode in sequence if episode not in expected_set})
    if out_of_range:
        issues.append(
            f"剧本正文 {batch.label} 集出现了批次窗口外的集标题：{_format_episode_ranges(out_of_range)}。"
        )

    filtered_sequence = [episode for episode in sequence if episode in expected_set]
    missing = [episode for episode in expected if episode not in set(filtered_sequence)]
    if missing:
        issues.append(
            f"剧本正文 {batch.label} 集缺少集标题：{_format_episode_ranges(missing)}。"
        )

    if not issues and filtered_sequence != expected:
        issues.append(
            f"剧本正文 {batch.label} 集标题顺序异常，当前顺序为：{_format_episode_ranges(filtered_sequence)}。"
        )
    return issues


def _looks_like_json_payload(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or stripped[0] not in "[{":
        return False
    try:
        parse_json(stripped)
    except Exception:
        return False
    return True


def _episode_chunk_has_scene_heading(chunk: str, episode: int) -> bool:
    text = str(chunk or "")
    if re.search(
        rf"(?m)^[ \t>#*\-]*(?:#{{1,6}}[ \t]*)?{episode}[ \t]*[-－—][ \t]*[0-9\uff10-\uff19]+(?:\b|[ \t:：])",
        text,
    ):
        return True
    if re.search(
        r"(?m)^[ \t>#*\-]*(?:\u573a\u666f|scene)[ \t]*[0-9\uff10-\uff19\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+",
        text,
        re.IGNORECASE,
    ):
        return True
    return "鍦烘櫙" in text


def _validate_script_batch_output(batch_script: Any, *, batch: BatchWindow) -> list[str]:
    text = str(batch_script or "").strip()
    if not text:
        return [f"script batch {batch.label} is empty"]
    if _looks_like_json_payload(text):
        return [f"script batch {batch.label} looks like JSON, not script正文"]

    lowered = text.lower()
    report_markers = (
        "blocking_issues",
        "rewrite_required",
        "non_blocking_issues",
        "\u5ba1\u6838",
        "\u5ba1\u6821",
        "\u4fee\u8ba2\u8bf4\u660e",
        "review report",
    )
    if any(marker in lowered or marker in text for marker in report_markers):
        return [f"script batch {batch.label} looks like a review/report, not script正文"]

    sequence = __extract_script_episode_sequence(text)
    if not sequence:
        return [f"script batch {batch.label} has no recognizable episode headings"]

    issues: list[str] = []
    if sequence[0] != batch.start_episode:
        issues.append(
            f"script batch {batch.label} must start from episode {batch.start_episode}, got {sequence[0]}"
        )

    duplicates = _duplicate_episode_numbers(sequence)
    if duplicates:
        issues.append(
            f"script batch {batch.label} has duplicate episode headings: {_format_episode_ranges(duplicates)}"
        )

    expected = list(range(batch.start_episode, batch.end_episode + 1))
    expected_set = set(expected)
    out_of_range = sorted({episode for episode in sequence if episode not in expected_set})
    if out_of_range:
        issues.append(
            f"script batch {batch.label} contains out-of-window episodes: {_format_episode_ranges(out_of_range)}"
        )

    filtered_sequence = [episode for episode in sequence if episode in expected_set]
    missing = [episode for episode in expected if episode not in set(filtered_sequence)]
    if missing:
        issues.append(
            f"script batch {batch.label} is missing episodes: {_format_episode_ranges(missing)}"
        )

    if not issues and filtered_sequence != expected:
        issues.append(
            f"script batch {batch.label} episode order is invalid: {_format_episode_ranges(filtered_sequence)}"
        )

    episode_map = _extract_script_episode_map(text, batch)
    for episode in expected:
        chunk = episode_map.get(episode, "")
        if not _episode_chunk_has_scene_heading(chunk, episode):
            issues.append(f"script episode {episode} is missing a scene heading such as {episode}-1")
    return issues


def validate_batch_script_text(text: Any, batch: BatchWindow) -> list[str]:
    if not isinstance(text, str):
        return [f"script batch {batch.label} must be string"]
    return _validate_script_batch_output(text, batch=batch)


def _script_stage_validation_details(
    exc: Exception,
    *,
    state: WorkflowState | None,
    stage_name: str,
    output_field: str,
) -> tuple[list[str], str, dict[str, Any]]:
    validation_error = getattr(exc, "contract_validation_error", None)
    if validation_error is None and isinstance(exc, WorkflowOutputValidationError):
        validation_error = exc
    if validation_error is None and isinstance(exc.__cause__, WorkflowOutputValidationError):
        validation_error = exc.__cause__

    artifact = getattr(exc, "contract_guard_artifact", None)
    if not isinstance(artifact, dict) and state is not None:
        artifact = state.get_output(stage_name, "contract_guard", {})
    if not isinstance(artifact, dict):
        artifact = {}

    reasons = [
        str(item).strip()
        for item in list(getattr(validation_error, "issues", []) or [])
        if str(item).strip()
    ]
    if not reasons:
        reasons = [
            str(item).strip()
            for item in list(getattr(exc, "validator_issues", []) or [])
            if str(item).strip()
        ]
    if not reasons:
        reasons = [
            str(item).strip()
            for item in list(artifact.get("validator_issues") or [])
            if str(item).strip()
        ]
    if not reasons and str(artifact.get("last_failure_reason") or "").strip():
        reasons = [str(artifact.get("last_failure_reason") or "").strip()]

    normalized_output = getattr(validation_error, "normalized_output", None)
    if not normalized_output:
        normalized_output = getattr(exc, "normalized_output", None)
    candidate_text = ""
    if isinstance(normalized_output, dict):
        candidate_text = str(normalized_output.get(output_field) or "").strip()
    elif isinstance(normalized_output, str):
        candidate_text = normalized_output.strip()

    return reasons, candidate_text, artifact


def _extract_episode_ranges_from_text(text: str) -> list[int]:
    episodes: set[int] = set()
    for match in re.finditer(
        r"第\s*([0-9０-９一二三四五六七八九十百千万两零〇]+)"
        r"(?:\s*[-－—~～到至]\s*([0-9０-９一二三四五六七八九十百千万两零〇]+))?\s*集",
        str(text or ""),
    ):
        start = _parse_episode_token(match.group(1) or "")
        end = _parse_episode_token(match.group(2) or "") if match.group(2) else start
        if start is None or end is None:
            continue
        left = min(start, end)
        right = max(start, end)
        episodes.update(range(left, right + 1))
    return sorted(episodes)


def _detect_missing_episodes(failure_reasons: list[str]) -> list[int]:
    missing: set[int] = set()
    for reason in failure_reasons:
        text = str(reason or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if "missing episodes" not in lowered and "缺少集" not in text:
            continue
        missing.update(_extract_episode_ranges_from_text(text))
    return sorted(missing)


def _script_error_has_missing_scene_heading(failure_reasons: list[str]) -> bool:
    for reason in failure_reasons:
        text = str(reason or "").strip()
        lowered = text.lower()
        if "missing a scene heading" in lowered or "缺少场景编号" in text or "缺少场景" in text:
            return True
    return False


def _script_error_has_duplicate_episodes(failure_reasons: list[str]) -> bool:
    for reason in failure_reasons:
        text = str(reason or "").strip()
        lowered = text.lower()
        if "duplicate episode" in lowered or "重复集" in text:
            return True
    return False


def _script_output_looks_truncated(
    batch_script: Any,
    *,
    batch: BatchWindow,
    failure_reasons: list[str],
) -> bool:
    text = str(batch_script or "").strip()
    if not text:
        return False
    sequence = __extract_script_episode_sequence(text)
    if sequence and max(sequence) < batch.end_episode:
        return True
    missing = _detect_missing_episodes(failure_reasons)
    if missing and batch.end_episode in missing:
        return True
    return False


def is_recoverable_script_error(failure_reasons: list[str]) -> bool:
    missing = _detect_missing_episodes(failure_reasons)
    if missing:
        return True
    if _script_error_has_missing_scene_heading(failure_reasons):
        return True
    if _script_error_has_duplicate_episodes(failure_reasons):
        return True
    for reason in failure_reasons:
        text = str(reason or "").strip()
        lowered = text.lower()
        if "truncated" in lowered or "截断" in text or "提前结束" in text:
            return True
    return False


def _script_auto_repair_review_payload(
    *,
    batch: BatchWindow,
    strategy: str,
    summary: str,
    instructions: list[str],
) -> dict[str, Any]:
    blocking_issues = [str(item).strip() for item in instructions if str(item).strip()]
    return {
        REVIEW_PASSED: False,
        REWRITE_REQUIRED: True,
        BLOCKING_ISSUES: blocking_issues,
        "non_blocking_issues": [],
        "summary": summary,
        "rewrite_start_episode": batch.start_episode,
        "stage": f"script_auto_repair_{strategy}",
    }


def _merge_script_repair_output(
    current_output: Any,
    repair_output: Any,
    *,
    batch: BatchWindow,
    repair_batch: BatchWindow,
) -> str:
    episode_map = _extract_script_episode_map(str(current_output or ""), batch)
    episode_map.update(_extract_script_episode_map(str(repair_output or ""), repair_batch))
    return _join_script_episode_map(episode_map)


def _is_contiguous_episode_window(episodes: list[int]) -> bool:
    return bool(episodes) and episodes == list(range(episodes[0], episodes[-1] + 1))


def _script_missing_episode_append_window(
    current_output: Any,
    *,
    batch: BatchWindow,
    missing_episodes: list[int],
) -> BatchWindow | None:
    if not _is_contiguous_episode_window(missing_episodes):
        return None
    sequence = __extract_script_episode_sequence(current_output)
    if not sequence:
        return None
    written = [episode for episode in sequence if batch.start_episode <= episode <= batch.end_episode]
    if not written:
        return None
    if max(written) >= missing_episodes[0] or missing_episodes[0] != max(written) + 1:
        return None
    return BatchWindow(start_episode=missing_episodes[0], end_episode=missing_episodes[-1])


def _script_batch_plan_from_context(
    context: dict[str, Any],
    *,
    batch: BatchWindow,
) -> tuple[str, dict[str, Any] | None]:
    plan_source = context.get(EPISODE_PLAN)
    raw_plan = ""
    if isinstance(plan_source, dict):
        raw_plan = json.dumps(plan_source, ensure_ascii=False)
    else:
        raw_plan = str(plan_source or "").strip()
    return _get_episode_batch_plan_context(
        context.get(NORMALIZED_EPISODE_PLAN),
        batch.start_episode,
        batch_size=batch.size,
        raw_episode_plan=raw_plan,
    )


def _script_repair_writing_context(
    writing_context: dict[str, Any],
    *,
    current_output: Any,
    batch: BatchWindow,
    repair_batch: BatchWindow,
    strategy: str,
    missing_episodes: list[int],
) -> dict[str, Any]:
    context = copy.deepcopy(writing_context)
    plan_for_batch, normalized_plan_for_batch = _script_batch_plan_from_context(
        writing_context,
        batch=repair_batch,
    )
    _apply_batch_episode_plan_context(
        context,
        plan_for_batch=plan_for_batch,
        normalized_plan_for_batch=normalized_plan_for_batch,
    )
    context[BATCH_START_EPISODE] = repair_batch.start_episode
    hook_payload = slice_object_episodes_for_batch(
        writing_context.get(BATCH_HOOKS) or writing_context.get(ALL_HOOKS),
        repair_batch,
    )
    dialogue_payload = slice_object_episodes_for_batch(
        writing_context.get(BATCH_DIALOGUES) or writing_context.get(ALL_DIALOGUES),
        repair_batch,
    )
    context[ALL_HOOKS] = copy.deepcopy(hook_payload)
    context[ALL_DIALOGUES] = copy.deepcopy(dialogue_payload)
    set_with_aliases(context, BATCH_HOOKS, hook_payload, SCRIPT_HOOK_INPUT_ALIASES)
    set_with_aliases(context, BATCH_DIALOGUES, dialogue_payload, SCRIPT_DIALOGUE_INPUT_ALIASES)
    current_text = str(current_output or "").strip()
    if current_text:
        if strategy == "append_missing":
            current_range = _format_episode_ranges(
                [episode for episode in __extract_script_episode_sequence(current_text) if episode > 0]
            )
            missing_range = _format_episode_ranges(missing_episodes)
            note = (
                "【自动补写上下文】已生成内容覆盖"
                f"{current_range or '部分集次'}，缺少 {missing_range or repair_batch.label}。"
                "请只补全缺失集次，不要重复已有内容，并从缺失起始集继续写。"
            )
            context[ALL_SCRIPT] = _join_script_parts(context.get(ALL_SCRIPT), note, current_text)
        else:
            context[ALL_SCRIPT] = _join_script_parts(context.get(ALL_SCRIPT), current_text)
    return context


def _should_retry_with_smaller_batch(
    *,
    batch: BatchWindow,
    retry_count: int,
    failure_reasons: list[str],
) -> int | None:
    if retry_count < SCRIPT_AUTO_REPAIR_MAX_RETRIES:
        return None
    if not is_recoverable_script_error(failure_reasons):
        return None
    return SCRIPT_AUTO_REPAIR_BATCH_FALLBACKS.get(batch.size)


def _split_batch_window(batch: BatchWindow, *, batch_size: int) -> list[BatchWindow]:
    normalized_size = max(1, int(batch_size or 1))
    sub_batches: list[BatchWindow] = []
    start_episode = batch.start_episode
    while start_episode <= batch.end_episode:
        end_episode = min(batch.end_episode, start_episode + normalized_size - 1)
        sub_batches.append(
            BatchWindow(start_episode=start_episode, end_episode=end_episode)
        )
        start_episode = end_episode + 1
    return sub_batches


def _auto_repair_script_output(
    state: WorkflowState,
    runner: FastGPTRunner,
    *,
    variables: dict[str, Any],
    batch: BatchWindow,
    stage_label: str,
    output_field: str,
    current_output_var: str,
    writing_stage_name: str,
    rewrite_stage_name: str,
    writing_context: dict[str, Any],
    rewrite_context_builder,
    progress_percent: int,
    generated_episodes: int,
    approved_output_validator,
    failure_reasons: list[str],
    current_output: Any,
) -> str:
    current_text = str(current_output or "").strip()
    issues = [str(item).strip() for item in failure_reasons if str(item).strip()]
    if not current_text and not issues:
        raise ValueError(f"{stage_label} {batch.label} 集自动修复失败：缺少可修复上下文。")

    recoverable = is_recoverable_script_error(issues) or _script_output_looks_truncated(
        current_text,
        batch=batch,
        failure_reasons=issues,
    )
    if not recoverable:
        raise ValueError(
            f"{stage_label} {batch.label} 集输出校验失败，且不属于可自动修复类型："
            + "；".join(issues[:10] or ["未知失败"])
        )

    for retry_count in range(1, SCRIPT_AUTO_REPAIR_MAX_RETRIES + 1):
        next_batch_size = _should_retry_with_smaller_batch(
            batch=batch,
            retry_count=retry_count,
            failure_reasons=issues,
        )
        if next_batch_size is not None:
            raise _RetryWithSmallerScriptBatch(
                batch=batch,
                next_batch_size=next_batch_size,
                failure_reasons=issues,
            )

        missing_episodes = _detect_missing_episodes(issues)
        truncated = _script_output_looks_truncated(
            current_text,
            batch=batch,
            failure_reasons=issues,
        )
        duplicate_episodes = _script_error_has_duplicate_episodes(issues)
        missing_scene_heading = _script_error_has_missing_scene_heading(issues)
        append_batch = _script_missing_episode_append_window(
            current_text,
            batch=batch,
            missing_episodes=missing_episodes,
        )

        strategy = "重写"
        repair_batch = batch
        repair_stage_name = rewrite_stage_name
        repair_context: dict[str, Any]
        repair_validator_batch = batch

        if retry_count == 1 and append_batch is not None:
            strategy = "补写"
            repair_batch = append_batch
            repair_stage_name = writing_stage_name
            repair_validator_batch = repair_batch
            repair_context = _script_repair_writing_context(
                writing_context,
                current_output=current_text,
                batch=batch,
                repair_batch=repair_batch,
                strategy="append_missing",
                missing_episodes=missing_episodes,
            )
        else:
            if retry_count == 1 and missing_scene_heading and not truncated and not duplicate_episodes:
                strategy = "结构修复"
            repair_payload = _script_auto_repair_review_payload(
                batch=batch,
                strategy=(
                    "repair_structure"
                    if strategy == "结构修复"
                    else "rewrite_batch"
                ),
                summary=(
                    f"{stage_label} {batch.label} 集需要补全缺失结构。"
                    if strategy == "结构修复"
                    else f"{stage_label} {batch.label} 集输出不完整，需要重新生成完整批次。"
                ),
                instructions=(
                    [
                        "请修复以下剧本格式：每一集必须包含 xx-1 场景编号；"
                        "不要改动既有剧情事实；只补结构，不要输出审核说明。"
                    ]
                    if strategy == "结构修复"
                    else [
                        f"你刚刚的输出被截断或缺集，没有完整生成第{batch.label}集。",
                        "请重新生成完整批次。",
                        "必须覆盖本批次全部集数，且不要提前结束。",
                        "每一集至少包含“第xx集”标题和一个“xx-1”场景编号。",
                        "不要输出审核报告、JSON 或补充说明。",
                    ]
                ),
            )
            repair_context = rewrite_context_builder(current_text, repair_payload)

        logger.warning(
            {
                "type": "script_auto_repair",
                "strategy": strategy,
                "missing_episodes": list(missing_episodes),
                "retry_count": retry_count,
                "batch_label": batch.label,
                "failure_reasons": list(issues[:10]),
            }
        )
        set_runtime_stage(
            state,
            "script",
            f"{stage_label} {batch.label} 集输出不完整，正在自动修复（{strategy}，第 {retry_count}/{SCRIPT_AUTO_REPAIR_MAX_RETRIES} 次）。",
            batch_label=batch.label,
            progress_percent=progress_percent,
            generated_episodes=generated_episodes,
        )
        sync_runtime_state(state)

        try:
            repair_output = run_stage_with_contract_guard(
                state,
                runner,
                repair_stage_name,
                repair_context,
                stage_key="script",
                message=f"正在自动修复{stage_label}：第 {batch.label} 集（{strategy}）",
                batch_label=batch.label,
                progress_percent=progress_percent,
                generated_episodes=generated_episodes,
                output_field=output_field,
                batch=repair_validator_batch,
                review_round=retry_count,
                validator=(
                    (lambda candidate: validate_batch_script_text(candidate, repair_validator_batch))
                    if strategy == "补写"
                    else (lambda candidate: list(approved_output_validator(candidate) or []))
                ),
                sync_output_to_state=False,
                max_format_retries=1,
            )
            candidate_text = str(repair_output.get(output_field) or "").strip()
            if strategy == "补写":
                candidate_text = _merge_script_repair_output(
                    current_text,
                    candidate_text,
                    batch=batch,
                    repair_batch=repair_batch,
                )
        except Exception as repair_exc:
            repair_issues, candidate_text, _ = _script_stage_validation_details(
                repair_exc,
                state=state,
                stage_name=repair_stage_name,
                output_field=output_field,
            )
            if strategy == "补写" and candidate_text:
                candidate_text = _merge_script_repair_output(
                    current_text,
                    candidate_text,
                    batch=batch,
                    repair_batch=repair_batch,
                )
            if not candidate_text:
                raise
            issues = repair_issues or list(approved_output_validator(candidate_text) or [])
            current_text = candidate_text
            variables[current_output_var] = current_text
            continue

        validation_issues = [
            str(item).strip()
            for item in list(approved_output_validator(candidate_text) or [])
            if str(item).strip()
        ]
        if not validation_issues:
            variables[current_output_var] = candidate_text
            return candidate_text
        current_text = candidate_text
        issues = validation_issues
        variables[current_output_var] = current_text

    raise ValueError(
        f"{stage_label} {batch.label} 集自动修复失败，已达到最多 {SCRIPT_AUTO_REPAIR_MAX_RETRIES} 次："
        + "；".join(issues[:10] or ["未知失败"])
    )


def _normalize_batch_hooks_payload(value: Any) -> dict[str, Any] | None:
    payload = _dict_or_empty(value)
    if not payload:
        return None
    candidate = payload.get(BATCH_HOOKS)
    if isinstance(candidate, dict):
        payload = copy.deepcopy(candidate)
    if isinstance(payload.get(BATCH_HOOKS), dict):
        payload = copy.deepcopy(payload[BATCH_HOOKS])
    if isinstance(payload.get("batch_meta"), dict) and isinstance(payload.get("episodes"), list):
        return payload
    return None


def _normalize_batch_dialogues_payload(value: Any) -> dict[str, Any] | None:
    payload = _dict_or_empty(value)
    if not payload:
        return None
    candidate = payload.get(BATCH_DIALOGUES)
    if isinstance(candidate, str) and candidate.strip():
        candidate = _dict_or_empty(candidate)
    if isinstance(candidate, dict):
        payload = copy.deepcopy(candidate)
    nested_candidate = payload.get(BATCH_DIALOGUES)
    if isinstance(nested_candidate, str) and nested_candidate.strip():
        nested_candidate = _dict_or_empty(nested_candidate)
    if isinstance(nested_candidate, dict):
        payload = copy.deepcopy(nested_candidate)
    if isinstance(payload.get("batch_meta"), dict) and isinstance(payload.get("episode_dialogue_blocks"), list):
        return payload
    return None


def _validate_batch_meta(payload: dict[str, Any], batch: BatchWindow, label: str) -> list[str]:
    issues: list[str] = []
    meta = payload.get("batch_meta")
    if not isinstance(meta, dict):
        return [f"{label} batch {batch.label} missing batch_meta"]
    if _safe_int(meta.get("start_episode"), 0) != batch.start_episode:
        issues.append(f"{label} batch_meta.start_episode must be {batch.start_episode}")
    if _safe_int(meta.get("end_episode"), 0) != batch.end_episode:
        issues.append(f"{label} batch_meta.end_episode must be {batch.end_episode}")
    return issues


def _validate_episode_window_items(
    items: Any,
    *,
    batch: BatchWindow,
    label: str,
) -> tuple[list[int], list[str]]:
    issues: list[str] = []
    if not isinstance(items, list) or not items:
        return [], [f"{label} batch {batch.label} episode list is empty"]
    episode_numbers: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            issues.append(f"{label} batch {batch.label} contains non-object episode item")
            continue
        episode = _safe_int(item.get("episode"), 0)
        episode_numbers.append(episode)
    expected = list(range(batch.start_episode, batch.end_episode + 1))
    duplicates = _duplicate_episode_numbers(episode_numbers)
    if duplicates:
        issues.append(f"{label} batch {batch.label} has duplicate episodes: {_format_episode_ranges(duplicates)}")
    out_of_range = sorted({episode for episode in episode_numbers if episode not in set(expected)})
    if out_of_range:
        issues.append(f"{label} batch {batch.label} contains out-of-window episodes: {_format_episode_ranges(out_of_range)}")
    missing = [episode for episode in expected if episode not in set(episode_numbers)]
    if missing:
        issues.append(f"{label} batch {batch.label} is missing episodes: {_format_episode_ranges(missing)}")
    if not issues and episode_numbers != expected:
        issues.append(f"{label} batch {batch.label} episode order is invalid: {_format_episode_ranges(episode_numbers)}")
    return episode_numbers, issues


def validate_batch_hooks(value: Any, batch: BatchWindow) -> list[str]:
    if isinstance(value, str) and not value.strip():
        return [f"hook batch {batch.label} is empty"]
    payload = _normalize_batch_hooks_payload(value)
    if payload is None:
        return [f"hook batch {batch.label} must be JSON object with batch_hooks"]
    issues = _validate_batch_meta(payload, batch, "hook")
    episodes = payload.get("episodes")
    _, episode_issues = _validate_episode_window_items(episodes, batch=batch, label="hook")
    issues.extend(episode_issues)
    required_fields = (
        "episode",
        "opening_alias_plan",
        "opening_action",
        "current_goal",
        "core_obstacle",
        "ending_hook",
        "next_episode_priority_response",
    )
    if isinstance(episodes, list):
        for item in episodes:
            if not isinstance(item, dict):
                continue
            episode = _safe_int(item.get("episode"), 0)
            missing = [field for field in required_fields if field not in item or not _has_value(item.get(field))]
            if missing:
                issues.append(f"hook episode {episode or '?'} missing fields: {', '.join(missing)}")
    return issues


def validate_batch_dialogues(value: Any, batch: BatchWindow) -> list[str]:
    if isinstance(value, str) and not value.strip():
        return [f"dialogue batch {batch.label} is empty"]
    raw_payload = _dict_or_empty(value)
    if raw_payload and {
        "dialogue_voice_summary",
        "must_carry_into_next_turn",
        "alias_usage_continuity",
    }.issubset(raw_payload):
        return ["角色对话修订 workflow 输出契约错误：输出是记忆 JSON，不是 batch_dialogues"]
    payload = _normalize_batch_dialogues_payload(value)
    if payload is None:
        return [f"dialogue batch {batch.label} must be JSON object with batch_dialogues"]
    issues = _validate_batch_meta(payload, batch, "dialogue")
    if not isinstance(payload.get("character_voice_bibles"), list):
        issues.append("dialogue character_voice_bibles must be array")
    blocks = payload.get("episode_dialogue_blocks")
    _, episode_issues = _validate_episode_window_items(blocks, batch=batch, label="dialogue")
    issues.extend(episode_issues)
    if isinstance(blocks, list):
        for item in blocks:
            if not isinstance(item, dict):
                continue
            episode = _safe_int(item.get("episode"), 0)
            nested_blocks = item.get("dialogue_blocks")
            if isinstance(nested_blocks, list):
                if not nested_blocks:
                    issues.append(f"dialogue episode {episode or '?'} dialogue_blocks is empty")
                    continue
                nested_valid = False
                for block_index, block in enumerate(nested_blocks, start=1):
                    if not isinstance(block, dict):
                        issues.append(
                            f"dialogue episode {episode or '?'} dialogue_block {block_index} must be object"
                        )
                        continue
                    dialogues = block.get("dialogues")
                    if not isinstance(dialogues, list) or not dialogues:
                        issues.append(
                            f"dialogue episode {episode or '?'} dialogue_block {block_index} dialogues is empty"
                        )
                        continue
                    block_has_valid_dialogue = False
                    for dialogue_index, dialogue in enumerate(dialogues, start=1):
                        if not isinstance(dialogue, dict):
                            issues.append(
                                f"dialogue episode {episode or '?'} dialogue_block {block_index} dialogue {dialogue_index} must be object"
                            )
                            continue
                        speaker = str(dialogue.get("speaker") or "").strip()
                        line = str(dialogue.get("line") or "").strip()
                        if not speaker or not line:
                            issues.append(
                                f"dialogue episode {episode or '?'} dialogue_block {block_index} dialogue {dialogue_index} speaker/line is empty"
                            )
                            continue
                        block_has_valid_dialogue = True
                    nested_valid = nested_valid or block_has_valid_dialogue
                if not nested_valid:
                    issues.append(
                        f"dialogue episode {episode or '?'} has no valid nested dialogues"
                    )
                continue

            block_text = str(item.get("dialogue_block") or item.get("content") or "").strip()
            participants = item.get("participants")
            speaker = item.get("speaker")
            if "participants" in item and not _has_value(participants):
                issues.append(f"dialogue episode {episode or '?'} participants is empty")
            if "speaker" in item and not _has_value(speaker):
                issues.append(f"dialogue episode {episode or '?'} speaker is empty")
            if not block_text and not _has_value(participants) and not _has_value(speaker):
                issues.append(
                    f"dialogue episode {episode or '?'} missing dialogue_blocks or flat dialogue content"
                )
    return issues


def _parse_episode_token(value: str) -> int | None:
    token = str(value or "").strip()
    if not token:
        return None

    fullwidth_digits = str.maketrans("０１２３４５６７８９", "0123456789")
    normalized = token.translate(fullwidth_digits)
    if normalized.isdigit():
        return int(normalized)
    parsed_chinese = _parse_chinese_number(normalized)
    if parsed_chinese is not None:
        return parsed_chinese

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


def _script_batch_window(
    start_episode: int,
    *,
    total_episodes: int,
    batch_size: int,
    next_start_episode: int | None = None,
) -> BatchWindow:
    end_episode = start_episode + max(1, batch_size) - 1
    if total_episodes > 0:
        end_episode = min(end_episode, total_episodes)
    if next_start_episode and next_start_episode > start_episode:
        end_episode = min(end_episode, next_start_episode - 1)
    return BatchWindow(start_episode=start_episode, end_episode=max(start_episode, end_episode))


def _rebuild_script_episode_cache(
    script_batches: dict[int, str],
    script_episode_cache: dict[int, str],
    *,
    total_episodes: int,
    batch_size: int,
) -> dict[int, str]:
    repaired = dict(script_episode_cache)
    sorted_starts = sorted(episode for episode in script_batches if episode > 0)
    for index, start_episode in enumerate(sorted_starts):
        batch_text = str(script_batches.get(start_episode) or "").strip()
        if not batch_text:
            continue
        next_start = sorted_starts[index + 1] if index + 1 < len(sorted_starts) else None
        batch_window = _script_batch_window(
            start_episode,
            total_episodes=total_episodes,
            batch_size=batch_size,
            next_start_episode=next_start,
        )
        repaired.update(_extract_script_episode_map(batch_text, batch_window))
    return repaired


def _script_episode_numbers(text: Any, *, total_episodes: int) -> list[int]:
    source = str(text or "").strip()
    if not source or total_episodes <= 0:
        return []
    return sorted(
        _extract_script_episode_map(
            source,
            BatchWindow(start_episode=1, end_episode=max(1, total_episodes)),
        )
    )


def _best_script_text_candidate(
    total_episodes: int,
    *candidates: Any,
) -> tuple[str, list[int]]:
    best_text = ""
    best_episodes: list[int] = []
    best_score = (-1, -1, -1)
    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        episodes = _script_episode_numbers(text, total_episodes=total_episodes)
        score = (
            len(episodes),
            episodes[-1] if episodes else 0,
            len(text),
        )
        if score > best_score:
            best_text = text
            best_episodes = episodes
            best_score = score
    return best_text, best_episodes


def _repair_script_outputs(
    variables: dict[str, Any],
    *,
    total_episodes: int,
    batch_size: int,
) -> tuple[str, list[int]]:
    script_batches = _normalize_batch_text_map(variables.get(LOCAL_SCRIPT_BATCHES))
    script_episode_cache = _normalize_episode_script_map(variables.get(LOCAL_SCRIPT_EPISODES))
    # 正文恢复时不能只信任单一缓存来源：
    # 有时保留下来的是整批文本，有时是逐集拆分结果，有时只有 ALL_SCRIPT。
    # 这里先尽量互相修复，再选出覆盖集数最多的那份正式正文。
    repaired_episode_cache = _rebuild_script_episode_cache(
        script_batches,
        script_episode_cache,
        total_episodes=total_episodes,
        batch_size=batch_size,
    )
    if repaired_episode_cache:
        variables[LOCAL_SCRIPT_EPISODES] = _string_keyed_batch_map(repaired_episode_cache)
    rebuilt_script = _join_script_episode_map(repaired_episode_cache) if repaired_episode_cache else ""
    joined_batches = _join_script_parts(
        *(script_batches[start_episode] for start_episode in sorted(script_batches))
    )
    best_text, best_episodes = _best_script_text_candidate(
        total_episodes,
        rebuilt_script,
        variables.get(ALL_SCRIPT),
        variables.get(LOCAL_COMMITTED_SCRIPT),
        joined_batches,
    )
    if best_text:
        variables[ALL_SCRIPT] = best_text
        variables[LOCAL_COMMITTED_SCRIPT] = best_text
    return best_text, best_episodes


def _format_episode_ranges(episodes: list[int]) -> str:
    if not episodes:
        return ""
    parts: list[str] = []
    start = episodes[0]
    previous = episodes[0]
    for episode in episodes[1:]:
        if episode == previous + 1:
            previous = episode
            continue
        parts.append(f"第{start}集" if start == previous else f"第{start}-{previous}集")
        start = previous = episode
    parts.append(f"第{start}集" if start == previous else f"第{start}-{previous}集")
    return "、".join(parts)


def _phase_missing_episodes(value: Any, batches: list[BatchWindow]) -> list[int]:
    missing: list[int] = []
    for batch in batches:
        batch_payload = slice_object_episodes_for_batch(value, batch)
        if _batch_object_is_reusable(batch_payload, batch):
            continue
        missing.extend(range(batch.start_episode, batch.end_episode + 1))
    return missing


def _extract_batch_episode_numbers_from_object(value: Any) -> list[int]:
    return _batch_object_episode_numbers(value)


def _ensure_object_phase_sequence_before_final(
    *,
    stage_label: str,
    value: Any,
    total_episodes: int,
) -> None:
    sequence = _extract_batch_episode_numbers_from_object(value)
    if not sequence or total_episodes <= 0:
        return

    expected = list(range(1, total_episodes + 1))
    expected_set = set(expected)
    duplicates = _duplicate_episode_numbers(sequence)
    if duplicates:
        raise ValueError(
            f"{stage_label}存在重复集，已阻止进入最终剧本拼接。重复：{_format_episode_ranges(duplicates)}。"
        )

    out_of_range = sorted({episode for episode in sequence if episode not in expected_set})
    if out_of_range:
        raise ValueError(
            f"{stage_label}存在越界集次，已阻止进入最终剧本拼接。异常：{_format_episode_ranges(out_of_range)}。"
        )

    missing = [episode for episode in expected if episode not in set(sequence)]
    if missing:
        return

    if sequence != expected:
        raise ValueError(
            f"{stage_label}集次顺序异常，已阻止进入最终剧本拼接。"
            f"当前顺序：{_format_episode_ranges(sequence)}。"
        )


def _ensure_script_sequence_before_final(
    script_text: Any,
    *,
    total_episodes: int,
) -> None:
    if total_episodes <= 0:
        return

    sequence = __extract_script_episode_sequence(script_text)
    if not sequence:
        return

    expected = list(range(1, total_episodes + 1))
    expected_set = set(expected)
    duplicates = _duplicate_episode_numbers(sequence)
    if duplicates:
        raise ValueError(
            "剧本正文存在重复集，已阻止进入最终剧本拼接。"
            f"重复：{_format_episode_ranges(duplicates)}。"
        )

    out_of_range = sorted({episode for episode in sequence if episode not in expected_set})
    if out_of_range:
        raise ValueError(
            "剧本正文存在越界集次，已阻止进入最终剧本拼接。"
            f"异常：{_format_episode_ranges(out_of_range)}。"
        )

    if sequence != expected:
        raise ValueError(
            "剧本正文集次顺序异常，已阻止进入最终剧本拼接。"
            f"当前顺序：{_format_episode_ranges(sequence)}。"
        )


def _ensure_complete_batched_outputs_before_final(
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> None:
    total_episodes = max(0, int(payload.total_episodes or 0))
    if total_episodes <= 0:
        return

    batch_size = max(1, int(settings.batch_size or 5))
    batches = list(iter_episode_batches(total_episodes, batch_size=batch_size))
    all_hooks = get_with_aliases(variables, ALL_HOOKS, HOOK_FINAL_ALIASES, {})
    all_dialogues = get_with_aliases(variables, ALL_DIALOGUES, DIALOGUE_FINAL_ALIASES, {})
    _ensure_object_phase_sequence_before_final(
        stage_label="开头冲突钩子",
        value=all_hooks,
        total_episodes=total_episodes,
    )
    hooks_missing = _phase_missing_episodes(all_hooks, batches)
    if hooks_missing:
        raise ValueError(
            "开头冲突钩子存在缺集，已阻止进入最终剧本拼接。"
            f"缺少：{_format_episode_ranges(hooks_missing)}。"
            "请先从 hooks 阶段继续生成缺失批次。"
        )

    _ensure_object_phase_sequence_before_final(
        stage_label="角色对白",
        value=all_dialogues,
        total_episodes=total_episodes,
    )
    dialogues_missing = _phase_missing_episodes(all_dialogues, batches)
    if dialogues_missing:
        raise ValueError(
            "角色对白存在缺集，已阻止进入最终剧本拼接。"
            f"缺少：{_format_episode_ranges(dialogues_missing)}。"
            "请先从 dialogues 阶段继续生成缺失批次。"
        )

    _ensure_complete_script_before_final(payload, variables)


def _ensure_complete_script_before_final(
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> None:
    total_episodes = max(0, int(payload.total_episodes or 0))
    if total_episodes <= 0:
        return
    repaired_script_text, available_episodes = _repair_script_outputs(
        variables,
        total_episodes=total_episodes,
        batch_size=max(1, int(settings.batch_size or 5)),
    )
    batches = list(iter_episode_batches(total_episodes, batch_size=max(1, int(settings.batch_size or 5))))
    expected = list(range(1, total_episodes + 1))
    if available_episodes == expected:
        script_text = (
            repaired_script_text
            or get_with_aliases(variables, ALL_SCRIPT, SCRIPT_FINAL_ALIASES, "")
        )
        _ensure_script_sequence_before_final(
            script_text,
            total_episodes=total_episodes,
        )
        issues = _script_text_reuse_issues_for_final(
            script_text,
            total_episodes=total_episodes,
            batches=batches,
        )
        if issues:
            raise ValueError(
                "剧本正文结构异常，已阻止进入最终剧本拼接。"
                f"问题：{'; '.join(issues[:3])}"
            )
        return
    available_set = set(available_episodes)
    missing = [episode for episode in expected if episode not in available_set]
    raise ValueError(
        "剧本正文存在缺集，已阻止进入最终剧本拼接。"
        f"当前识别到 {len(available_episodes)}/{total_episodes} 集，"
        f"缺少：{_format_episode_ranges(missing)}。"
        "请从剧本正文阶段继续生成缺失批次。"
    )


def _run_full_fastgpt_generation(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> None:
    alias_plan = _normalize_episode_alias_plan_object(variables.get(EPISODE_ALIAS_PLAN))
    full_plan_for_batch, full_normalized_plan_for_batch = _get_episode_batch_plan_context(
        _normalize_episode_plan_object(variables.get(NORMALIZED_EPISODE_PLAN)),
        1,
        batch_size=payload.total_episodes,
        raw_episode_plan=str(variables.get(EPISODE_PLAN) or payload.episode_plan or ""),
    )
    _apply_batch_episode_plan_context(
        variables,
        plan_for_batch=full_plan_for_batch,
        normalized_plan_for_batch=full_normalized_plan_for_batch,
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
        normalized_plan_for_batch=_normalize_episode_plan_object(
            variables.get(NORMALIZED_EPISODE_PLAN)
        ),
        alias_plan_for_batch=variables.get(EPISODE_ALIAS_PLAN) or {},
        committed_script=str(variables.get(ALL_SCRIPT) or "").strip(),
        hook_payload=variables.get(ALL_HOOKS) if isinstance(variables.get(ALL_HOOKS), dict) else None,
        dialogue_payload=variables.get(ALL_DIALOGUES) if isinstance(variables.get(ALL_DIALOGUES), dict) else None,
        script_batches=_normalize_batch_text_map(variables.get(LOCAL_SCRIPT_BATCHES)),
        script_episode_cache=_normalize_episode_script_map(variables.get(LOCAL_SCRIPT_EPISODES)),
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
    variables[LOCAL_SCRIPT_BATCHES] = {"1": all_script}
    variables[LOCAL_SCRIPT_EPISODES] = _string_keyed_batch_map(
        _extract_script_episode_map(
            all_script,
            BatchWindow(start_episode=1, end_episode=max(1, payload.total_episodes)),
        )
    )
    _sync_state_variables(state, variables)

    memory_output = _run_fastgpt_stage(
        state,
        runner,
        STAGE_SCRIPT_MEMORY,
        {
            BATCH_SCRIPT: all_script,
            LAST_SUMMARY: variables.get(LAST_SUMMARY) or "",
            APPEARANCE_MAPPING: variables.get(APPEARANCE_MAPPING) or {},
            CHARACTER_ALIAS_NAMING_RULES: variables.get(CHARACTER_ALIAS_NAMING_RULES)
            or "",
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
    normalized_plan_for_batch: dict[str, Any] | None,
    alias_plan_for_batch: dict[str, Any] | None,
    hook_payload: dict[str, Any] | None = None,
    dialogue_payload: dict[str, Any] | None = None,
    previous_batch_summary: str = "",
    script_memory: str = "",
    committed_script: str = "",
    script_batches: dict[int, str] | None = None,
    script_episode_cache: dict[int, str] | None = None,
    script_stage_name: str = STAGE_SCRIPT_WRITING,
) -> dict[str, Any]:
    """script 只带当前批 hooks/dialogues + 当前批 plan + 上一批摘要 + 滚动记忆。"""
    del committed_script, script_batches, script_episode_cache
    context = _stage_input_context(script_stage_name, variables)
    _apply_batch_episode_plan_context(
        context,
        plan_for_batch=plan_for_batch,
        normalized_plan_for_batch=normalized_plan_for_batch,
    )
    context[WORLDVIEW] = _compact_stage_text(
        variables.get(WORLDVIEW),
        builder=build_compact_worldview_context,
        fallback=context.get(WORLDVIEW),
    )
    context[CHARACTERS] = _compact_stage_text(
        variables.get(CHARACTERS),
        builder=build_compact_character_context_for_script,
        fallback="",
    )
    context[SCENES] = _compact_stage_text(
        variables.get(SCENES),
        builder=build_compact_scene_context_for_script,
        fallback="",
    )
    context[APPEARANCE_MAPPING] = _compact_stage_text(
        alias_plan_for_batch,
        builder=build_compact_appearance_context_for_batch,
        fallback="",
    )
    context[BATCH_START_EPISODE] = batch.start_episode
    batch_hooks = copy.deepcopy(hook_payload) if isinstance(hook_payload, dict) else _current_batch_object_payload(
        variables.get(BATCH_HOOKS),
        variables.get(ALL_HOOKS),
        batch=batch,
    )
    batch_dialogues = copy.deepcopy(dialogue_payload) if isinstance(dialogue_payload, dict) else _current_batch_object_payload(
        variables.get(BATCH_DIALOGUES),
        variables.get(ALL_DIALOGUES),
        batch=batch,
    )
    # script 子 workflows 读取的其实是当前五集 hooks/dialogues aliases。
    # 全量 all_hooks/all_dialogues 继续由 Python 聚合维护，这里只把当前批次切片放进 stage-local context。
    context[ALL_HOOKS] = copy.deepcopy(batch_hooks)
    context[ALL_DIALOGUES] = copy.deepcopy(batch_dialogues)
    set_with_aliases(context, BATCH_HOOKS, batch_hooks, SCRIPT_HOOK_INPUT_ALIASES)
    set_with_aliases(context, BATCH_DIALOGUES, batch_dialogues, SCRIPT_DIALOGUE_INPUT_ALIASES)
    # script 契约仍要求显式带上 all_script。首批正文没有前情时，也要传空字符串，
    # 否则契约层会把它判成“缺少输入”，恢复/重跑时第一批永远起不来。
    context[ALL_SCRIPT] = previous_batch_summary or ""
    if script_memory:
        context[LAST_SUMMARY] = _bounded_script_memory(script_memory)
    else:
        context.pop(LAST_SUMMARY, None)

    estimated_before = _estimate_stage_payload_length(STAGE_SCRIPT, context)
    breakdown_before = _script_stage_payload_breakdown(context)
    estimated_after, compressed_fields = _apply_script_stage_length_guard(context, estimated_before)
    breakdown_after = _script_stage_payload_breakdown(context)
    if compressed_fields:
        logger.warning(
            "剧本正文 %s 集 payload 保护生效：soft=%s hard=%s；压缩字段=%s；长度 %s -> %s；压缩前=%s；压缩后=%s",
            batch.label,
            SCRIPT_STAGE_PAYLOAD_SOFT_LIMIT,
            SCRIPT_STAGE_PAYLOAD_HARD_LIMIT,
            "、".join(compressed_fields),
            estimated_before,
            estimated_after,
            _format_script_payload_breakdown(breakdown_before),
            _format_script_payload_breakdown(breakdown_after),
        )
    else:
        logger.info(
            "剧本正文 %s 集 payload 阈值：soft=%s hard=%s；当前长度=%s；字段占比=%s",
            batch.label,
            SCRIPT_STAGE_PAYLOAD_SOFT_LIMIT,
            SCRIPT_STAGE_PAYLOAD_HARD_LIMIT,
            estimated_after,
            _format_script_payload_breakdown(breakdown_before),
        )
    return context


def _build_previous_script_context(
    script_batches: dict[int, str],
    script_episode_cache: dict[int, str],
    committed_script: str,
    *,
    current_batch_start: int,
) -> str:
    """只保留上一批正文的压缩摘要，避免把更早批次原文再次塞回 script 上下文。"""
    if current_batch_start <= 1:
        return ""

    previous_starts = sorted(start for start in script_batches if start < current_batch_start)
    if previous_starts:
        previous_text = str(script_batches.get(previous_starts[-1]) or "").strip()
        if previous_text:
            return _local_batch_script_summary(previous_text)

    batch_size = max(1, int(settings.batch_size or 5))
    previous_batch_start = max(1, current_batch_start - batch_size)
    previous_episode_parts = [
        text
        for episode, text in sorted(script_episode_cache.items())
        if previous_batch_start <= episode < current_batch_start and str(text or "").strip()
    ]
    if previous_episode_parts:
        return _local_batch_script_summary(_join_script_parts(*previous_episode_parts))
    return _local_batch_script_summary(committed_script)


def _local_batch_script_summary(value: Any) -> str:
    """本地把上一批正文压成简短摘要，避免为了展示/记忆额外请求模型。"""
    text = str(value or "").strip()
    if not text:
        return ""

    blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
    condensed = []
    for block in blocks:
        compact = " ".join(block.split())
        if compact:
            condensed.append(compact[:260])
    return _trim_text_tail(
        "\n".join(condensed) if condensed else text,
        max_chars=SCRIPT_STAGE_PREVIOUS_BATCH_SUMMARY_MAX_CHARS,
    )


def _bounded_script_memory(value: Any) -> str:
    """LAST_SUMMARY 只保留滚动压缩记忆，不允许随批次无限累加原文。"""
    return _trim_text_tail(value, max_chars=SCRIPT_STAGE_MEMORY_MAX_CHARS)


def _apply_script_stage_length_guard(
    context: dict[str, Any],
    initial_estimate: int | None = None,
) -> tuple[int, list[str]]:
    """在不破坏批次上下文的前提下，先压前情记忆，再在硬上限前做最后保护。"""
    estimate = initial_estimate or _estimate_stage_payload_length(STAGE_SCRIPT, context)
    if estimate <= SCRIPT_STAGE_PAYLOAD_SOFT_LIMIT:
        return estimate, []

    compressed_fields: list[str] = []
    soft_strategies: tuple[tuple[str, str, tuple[int, ...], Any], ...] = (
        (ALL_SCRIPT, "previous_batch_summary", (24000, 18000, 12000, 8000), _trim_text_tail),
        (LAST_SUMMARY, "script_memory", (9000, 6000, 3600, 2200), _trim_text_tail),
        (APPEARANCE_CONTINUITY_MEMORY, "appearance_memory", (6000, 4000, 2500), _compact_nested_strings),
    )
    hard_strategies: tuple[tuple[str, str, tuple[int, ...], Any], ...] = (
        (ALL_HOOKS, "hooks", (2200, 1600, 1000, 700), _compact_nested_strings),
        (ALL_DIALOGUES, "dialogues", (2200, 1600, 1000, 700), _compact_nested_strings),
        (ALL_SCRIPT, "previous_batch_summary", (6000, 4000), _trim_text_tail),
        (LAST_SUMMARY, "script_memory", (1600, 1000, 700), _trim_text_tail),
    )

    estimate = _apply_script_stage_compression_strategies(
        context,
        estimate,
        target_limit=SCRIPT_STAGE_PAYLOAD_SOFT_LIMIT,
        strategies=soft_strategies,
        compressed_fields=compressed_fields,
    )
    if estimate > SCRIPT_STAGE_PAYLOAD_HARD_LIMIT:
        estimate = _apply_script_stage_compression_strategies(
            context,
            estimate,
            target_limit=SCRIPT_STAGE_PAYLOAD_HARD_LIMIT,
            strategies=hard_strategies,
            compressed_fields=compressed_fields,
        )

    return estimate, compressed_fields


def _apply_script_stage_compression_strategies(
    context: dict[str, Any],
    estimate: int,
    *,
    target_limit: int,
    strategies: tuple[tuple[str, str, tuple[int, ...], Any], ...],
    compressed_fields: list[str],
) -> int:
    """按给定阈值分阶段压缩字段，优先保住当前批次最重要的 plan/hooks/dialogues。"""
    for field_name, label, limits, compressor in strategies:
        if estimate <= target_limit:
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
            if estimate <= target_limit:
                break
    return estimate


def _script_stage_payload_breakdown(context: dict[str, Any]) -> dict[str, int]:
    """统计正文阶段主要输入块的估算长度，便于观察是谁把 payload 撑大了。"""
    parts = {
        "batch_plan": context.get(EPISODE_PLAN),
        "batch_hooks": context.get(ALL_HOOKS),
        "batch_dialogues": context.get(ALL_DIALOGUES),
        "previous_batch_summary": context.get(ALL_SCRIPT),
        "script_memory": context.get(LAST_SUMMARY),
        "appearance_mapping": context.get(APPEARANCE_MAPPING),
        "appearance_memory": context.get(APPEARANCE_CONTINUITY_MEMORY),
        "character_scene_bundle": _build_script_character_scene_bundle_for_estimate(
            context.get(CHARACTERS),
            context.get(SCENES),
        ),
        "worldview": context.get(WORLDVIEW),
    }
    return {
        label: _estimate_payload_value_length(value)
        for label, value in parts.items()
        if _has_value(value)
    }


def _estimate_payload_value_length(value: Any) -> int:
    """用和 wire payload 一致的 JSON 估算方式统计单个字段大概会占多少长度。"""
    return len(
        json.dumps(
            _format_wire_value_for_estimate(value),
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    )


def _format_script_payload_breakdown(lengths: dict[str, int]) -> str:
    """把正文 payload 各大块长度格式化成日志里的占比摘要。"""
    if not lengths:
        return "无"
    total = sum(lengths.values()) or 1
    parts = []
    for label, size in sorted(lengths.items(), key=lambda item: item[1], reverse=True):
        ratio = int(round((size / total) * 100))
        parts.append(f"{label}={size}({ratio}%)")
    return "，".join(parts)


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
        wire_names = _as_wire_names_for_estimate(wire_name)
        if canonical_name == ALL_HOOKS and BATCH_HOOKS in variables:
            _set_wire_values_for_estimate(payload, wire_names, variables[BATCH_HOOKS])
            continue
        if canonical_name == ALL_DIALOGUES and BATCH_DIALOGUES in variables:
            _set_wire_values_for_estimate(payload, wire_names, variables[BATCH_DIALOGUES])
            continue
        if canonical_name in variables:
            if _is_script_family_stage(stage_name) and canonical_name == CHARACTERS:
                _set_wire_values_for_estimate(
                    payload,
                    wire_names,
                    _build_script_character_scene_bundle_for_estimate(
                        variables.get(CHARACTERS),
                        variables.get(SCENES),
                    ),
                )
                continue
            if _is_script_family_stage(stage_name) and canonical_name == SCENES:
                continue
            value = variables[canonical_name]
            if canonical_name == CHARACTER_APPEARANCE_REQUIREMENTS:
                value = _merge_optional_text(
                    variables.get(CHARACTER_APPEARANCE_REQUIREMENTS),
                    variables.get(OUTFIT_SWITCH_RULES),
                )
            _set_wire_values_for_estimate(payload, wire_names, value)
            continue
        if canonical_name in {LAST_SUMMARY, HOOK_MEMORY, DIALOGUE_MEMORY, SCRIPT_MEMORY}:
            _set_wire_values_for_estimate(payload, wire_names, "")
        elif canonical_name in {ALL_HOOKS, ALL_DIALOGUES, ALL_SCRIPT}:
            _set_wire_values_for_estimate(payload, wire_names, "")
        elif canonical_name == USER_CONTENT_BASELINE:
            _set_wire_values_for_estimate(payload, wire_names, "{}")
        elif canonical_name == MAX_RETRIES:
            _set_wire_values_for_estimate(payload, wire_names, settings.max_retries_default)
    return payload


def _as_wire_names_for_estimate(wire_name: Any) -> tuple[str, ...]:
    if isinstance(wire_name, (tuple, list, set)):
        return tuple(str(name) for name in wire_name if str(name).strip())
    return (str(wire_name),)


def _set_wire_values_for_estimate(payload: dict[str, Any], wire_names: tuple[str, ...], value: Any) -> None:
    formatted = _format_wire_value_for_estimate(value)
    for name in wire_names:
        payload[name] = formatted


def _build_script_character_scene_bundle_for_estimate(characters: Any, scenes: Any) -> str:
    character_text = str(characters or "").strip()
    scene_text = str(scenes or "").strip()
    if character_text and scene_text:
        return (
            "【人设结果JSON】\n"
            f"{character_text}\n\n"
            "【场景结果JSON】\n"
            f"{scene_text}"
        ).strip()
    return character_text or scene_text


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


def _stage_format_retry_limit() -> int:
    configured = int(getattr(settings, "fastgpt_stage_format_retry_limit", 3))
    return max(1, configured)


def _runner_stage_debug_info(runner: FastGPTRunner, stage_name: str) -> dict[str, Any]:
    getter = getattr(runner, "get_last_stage_debug_info", None)
    if callable(getter):
        try:
            info = getter(stage_name)
        except Exception:
            return {}
        return dict(info or {})
    return {}


def _debug_artifact_dir() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "runtime_data"
        / "debug"
        / "fastgpt_stage_failures"
    )


def _prune_stage_debug_artifacts(
    debug_dir: Path,
    *,
    max_files: int = 20,
    max_age_days: int = 7,
) -> None:
    try:
        files = sorted(
            (path for path in debug_dir.glob("*.json") if path.is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return

    cutoff_timestamp = datetime.now().timestamp() - max(1, int(max_age_days)) * 86400
    stale: list[Path] = []
    stale.extend(files[max(0, int(max_files)):])
    for path in files:
        try:
            if path.stat().st_mtime < cutoff_timestamp:
                stale.append(path)
        except OSError:
            continue

    seen: set[Path] = set()
    for path in stale:
        if path in seen:
            continue
        seen.add(path)
        try:
            path.unlink()
        except OSError:
            continue


def _safe_debug_filename_part(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    return text.strip("_") or "unknown"


def _write_stage_debug_artifact_file(
    *,
    artifact: dict[str, Any],
    stage_variables: dict[str, Any],
    runner_debug: dict[str, Any],
    raw_output: dict[str, Any] | None,
    batch: BatchWindow | None,
    exception: Exception | None,
) -> str:
    debug_dir = _debug_artifact_dir()
    debug_dir.mkdir(parents=True, exist_ok=True)
    batch_start = batch.start_episode if batch else ""
    batch_end = batch.end_episode if batch else ""
    filename = (
        f"{_safe_debug_filename_part(str(artifact.get('stage_name') or 'stage'))}"
        f"__{batch_start or 'na'}_{batch_end or 'na'}"
        f"__attempt{int(artifact.get('format_attempt') or 0)}"
        f"__{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
    )
    output_keys = sorted(raw_output.keys()) if isinstance(raw_output, dict) else []
    input_keys = sorted(str(key) for key in stage_variables.keys())
    payload = {
        **artifact,
        "batch": {
            "start_episode": batch.start_episode if batch else None,
            "end_episode": batch.end_episode if batch else None,
            "label": batch.label if batch else "",
        },
        "input_keys": input_keys,
        "input_preview": _compact_nested_strings(stage_variables, max_chars=600),
        "output_keys": output_keys,
        "raw_output_preview": _compact_nested_strings(raw_output or {}, max_chars=600),
        "raw_answer_text_preview": str(runner_debug.get("answer_text_preview") or ""),
        "fastgpt_client_answer_text_preview": str(
            runner_debug.get("answer_text_preview") or ""
        ),
        "fastgpt_client_response_preview": str(
            runner_debug.get("response_preview") or ""
        ),
        "fastgpt_client_output_keys": list(runner_debug.get("output_keys") or []),
        "fastgpt_client_raw_response": runner_debug.get("raw_response"),
        "fastgpt_client_last_stage_debug_info": _compact_nested_strings(
            runner_debug,
            max_chars=600,
        ),
        "conversation_log_available": False,
        "traceback": "".join(
            traceback.format_exception(type(exception), exception, exception.__traceback__)
        )
        if exception is not None
        else "",
    }
    target = debug_dir / filename
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    _prune_stage_debug_artifacts(debug_dir)
    return str(target.resolve())


def _stage_workflow_contract_spec(stage_name: str):
    contract = contract_for(stage_name)
    return load_workflow_output_contract(
        stage_name=stage_name,
        expected_output_kind=contract.expected_output_kind or "stage_contract",
        workflow_json_name=contract.workflow_json_name,
    )


def _artifact_debug_fields(
    *,
    runner_debug: dict[str, Any],
    exception: Exception | None,
    default_missing_fields: list[str],
) -> dict[str, Any]:
    matched_fields = list(
        getattr(exception, "matched_fields", None)
        or runner_debug.get("matched_fields", [])
        or []
    )
    missing_fields = list(
        getattr(exception, "missing_fields", None)
        or runner_debug.get("missing_fields", [])
        or default_missing_fields
    )
    candidate_sources = list(
        getattr(exception, "candidate_sources", None)
        or runner_debug.get("candidate_sources", [])
        or []
    )
    answer_text_preview = str(
        getattr(exception, "answer_text_preview", "")
        or runner_debug.get("answer_text_preview")
        or ""
    )
    response_preview = str(
        getattr(exception, "response_preview", "")
        or runner_debug.get("response_preview")
        or ""
    )
    return {
        "candidate_sources": candidate_sources,
        "matched_fields": matched_fields,
        "missing_fields": missing_fields,
        "probable_truncated_json": bool(
            getattr(exception, "probable_truncated_json", False)
            or runner_debug.get("probable_truncated_json")
        ),
        "answer_text_preview": answer_text_preview,
        "response_preview": response_preview,
        "raw_output_source": str(
            getattr(exception, "raw_output_source", "")
            or runner_debug.get("raw_output_source")
            or "stage_output"
        ),
        "last_failure_reason": str(
            getattr(exception, "failure_reason", "")
            or getattr(exception, "issues", None)
            or getattr(exception, "args", [""])[0]
            or ""
        ),
    }


def _log_stage_format_failure(
    *,
    contract,
    batch_label: str | None,
    format_attempt: int,
    retries: int,
    debug_fields: dict[str, Any],
    debug_file_path: str,
) -> None:
    logger.warning(
        "stage_name=%s attempt=%s/%s failure_reason=%s candidate_source=%s matched_fields=%s missing_fields=%s probable_truncated_json=%s answerText preview=%s debug_artifact=%s",
        contract.stage_name,
        format_attempt,
        retries,
        _truncate_log_text(str(debug_fields.get("last_failure_reason") or ""), max_chars=320),
        str(debug_fields.get("raw_output_source") or "stage_output"),
        list(debug_fields.get("matched_fields") or []),
        list(debug_fields.get("missing_fields") or []),
        bool(debug_fields.get("probable_truncated_json")),
        _truncate_log_text(str(debug_fields.get("answer_text_preview") or ""), max_chars=240),
        debug_file_path,
    )


def _format_retry_exhausted_error(
    *,
    contract,
    debug_file_path: str,
    failure_reason: str,
) -> ValueError:
    expected_fields = ", ".join(contract.output_names) or "无"
    return ValueError(
        f"{contract.stage_name} 输出格式重试已耗尽。"
        f"期望字段：{expected_fields}；"
        f"最后一次失败：{failure_reason or '未知'}；"
        f"调试文件：{debug_file_path}；"
        "建议检查 workflow 输出是否过长、是否缺 answerNode、是否 detail=false。"
    )


def _attach_contract_guard_error_meta(
    exc: ValueError,
    *,
    validation_error: WorkflowOutputValidationError | None,
    validator_issues: list[str],
    artifact: dict[str, Any],
) -> ValueError:
    setattr(exc, "validator_issues", list(validator_issues or []))
    setattr(exc, "contract_guard_artifact", copy.deepcopy(artifact))
    if validation_error is not None:
        setattr(exc, "contract_validation_error", validation_error)
        setattr(
            exc,
            "normalized_output",
            copy.deepcopy(getattr(validation_error, "normalized_output", {}) or {}),
        )
    return exc


def _run_fastgpt_stage_once(
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
    sync_output_to_state: bool = True,
) -> dict[str, Any]:
    contract = contract_for(stage_name)
    runtime_stage_key = stage_name or stage_key
    _checkpoint(state)
    set_runtime_stage(
        state,
        runtime_stage_key,
        message,
        batch_label=batch_label,
        progress_percent=progress_percent,
        generated_episodes=generated_episodes,
    )
    sync_runtime_state(state)
    _sync_stage_input_aliases(stage_name, variables)
    contract.build_input_payload(variables)
    log_label = _stage_label_with_review_round(contract.label, message)
    _log_fastgpt_stage_start(state, log_label, batch_label, 1)
    raw_output = _ensure_stage_output_mapping(
        stage_name,
        runner.run_stage(stage_name, variables),
    )
    raw_output = _normalize_stage_output_aliases(stage_name, raw_output)
    validated_output = contract.validate_output_payload(raw_output)
    output = dict(raw_output)
    output.update(validated_output)
    _log_fastgpt_stage_done(state, log_label, batch_label, output)
    if sync_output_to_state:
        _sync_state_variables(state, output)
    _checkpoint(state)
    return output


def run_stage_with_contract_guard(
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
    output_field: str | None = None,
    batch: BatchWindow | None = None,
    review_round: int | None = None,
    validator: Any = None,
    review_parser: Any = None,
    memory_normalizer: Any = None,
    memory_kwargs: dict[str, Any] | None = None,
    sync_output_to_state: bool = False,
    max_format_retries: int | None = None,
) -> dict[str, Any]:
    contract = contract_for(stage_name)
    expected_output_kind = contract.expected_output_kind
    runtime_stage_key = stage_name or stage_key
    if not expected_output_kind:
        return _run_fastgpt_stage(
            state,
            runner,
            stage_name,
            variables,
            stage_key=stage_key,
            message=message,
            batch_label=batch_label,
            progress_percent=progress_percent,
            generated_episodes=generated_episodes,
            max_retries=0,
            sync_output_to_state=sync_output_to_state,
        )

    retries = _stage_format_retry_limit() if max_format_retries is None else max(1, max_format_retries)
    workflow_contract = load_workflow_output_contract(
        stage_name=stage_name,
        expected_output_kind=expected_output_kind,
        workflow_json_name=contract.workflow_json_name,
    )
    canonical_name = output_field or (contract.output_names[0] if len(contract.output_names) == 1 else "")
    aliases = contract.aliases_for_output(canonical_name) if canonical_name else ()
    last_error: Exception | None = None
    format_attempt = 0

    while format_attempt < retries:
        raw_output: dict[str, Any] | None = None
        validation_meta: dict[str, Any] = {}
        try:
            raw_output = _run_fastgpt_stage_once(
                state,
                runner,
                stage_name,
                variables,
                stage_key=stage_key,
                message=message,
                batch_label=batch_label,
                progress_percent=progress_percent,
                generated_episodes=generated_episodes,
                sync_output_to_state=False,
            )
            validated_output, validation_meta = validate_stage_output_with_workflow_contract(
                raw_output,
                spec=workflow_contract,
                canonical_name=canonical_name,
                aliases=aliases,
                batch_validator=validator,
                review_parser=review_parser,
                memory_normalizer=memory_normalizer,
                memory_kwargs=memory_kwargs,
            )
            if stage_name == STAGE_SCRIPT_REVIEW:
                validated_output["summary"] = str(validated_output.get("summary") or "").strip()
                validated_output["non_blocking_issues"] = list(
                    validated_output.get("non_blocking_issues") or []
                )
                if not isinstance(validated_output.get("rewrite_start_episode"), int) and batch is not None:
                    validated_output["rewrite_start_episode"] = int(batch.start_episode)
                validated_output["stage"] = (
                    str(validated_output.get("stage") or "").strip()
                    or "five_episode_continuity_review"
                )
            if sync_output_to_state:
                _sync_state_variables(state, validated_output)
            runner_debug = _runner_stage_debug_info(runner, stage_name)
            debug_fields = _artifact_debug_fields(
                runner_debug=runner_debug,
                exception=None,
                default_missing_fields=[],
            )
            artifact = build_debug_artifact(
                spec=workflow_contract,
                batch_label=batch_label,
                review_round=review_round,
                format_attempt=max(1, format_attempt or 1),
                max_format_retries=retries,
                status="validated",
                raw_output_source=str(
                    validation_meta.get("raw_output_source")
                    or debug_fields.get("raw_output_source")
                    or "stage_output"
                ),
                matched_aliases=list(validation_meta.get("matched_aliases") or aliases),
                candidate_sources=debug_fields.get("candidate_sources"),
                matched_fields=debug_fields.get("matched_fields") or list(validated_output.keys()),
                missing_fields=[],
                probable_truncated_json=bool(debug_fields.get("probable_truncated_json")),
                answer_text_preview=debug_fields.get("answer_text_preview"),
                response_preview=debug_fields.get("response_preview"),
                raw_preview=debug_fields.get("response_preview") or raw_output,
                normalized_preview=validation_meta.get("normalized_preview") or validated_output,
                fallback_used=False,
                last_failure_reason="",
            )
            workflow_warnings = list(workflow_contract.workflow_warnings)
            workflow_warnings.extend(validation_meta.get("workflow_warnings", []) or [])
            if workflow_warnings:
                artifact["workflow_warnings"] = workflow_warnings
            state.set_output(stage_name, "contract_guard", artifact)
            if workflow_warnings:
                for warning in workflow_warnings:
                    logger.warning("%s", warning)
            return validated_output
        except FastGPTTransientError as exc:
            last_error = exc
            delay_seconds = _transient_retry_delay(max(1, format_attempt + 1))
            set_runtime_stage(
                state,
                runtime_stage_key,
                "网络波动，已保留当前进度，正在自动重试。",
                batch_label=batch_label,
                progress_percent=progress_percent,
                generated_episodes=generated_episodes,
            )
            sync_runtime_state(state)
            logger.warning(
                "%s%s遇到临时错误，将在 %.0f 秒后自动重试：%s",
                contract.label,
                _format_batch_suffix(batch_label),
                delay_seconds,
                exc,
            )
            _sleep_with_checkpoints(state, delay_seconds)
            continue
        except Exception as exc:
            if _is_model_connection_error(exc):
                last_error = exc
                delay_seconds = _transient_retry_delay(max(1, format_attempt + 1))
                set_runtime_stage(
                    state,
                    runtime_stage_key,
                    "模型连接波动，已保留当前进度，正在自动重试。",
                    batch_label=batch_label,
                    progress_percent=progress_percent,
                    generated_episodes=generated_episodes,
                )
                sync_runtime_state(state)
                logger.warning(
                    "%s%s遇到模型连接异常，将在 %.0f 秒后自动重试：%s",
                    contract.label,
                    _format_batch_suffix(batch_label),
                    delay_seconds,
                    exc,
                )
                _sleep_with_checkpoints(state, delay_seconds)
                continue
            last_error = exc
            format_attempt += 1
            runner_debug = _runner_stage_debug_info(runner, stage_name)
            issues = list(getattr(exc, "issues", []) or [])
            normalized_preview = getattr(exc, "normalized_output", None)
            debug_fields = _artifact_debug_fields(
                runner_debug=runner_debug,
                exception=exc,
                default_missing_fields=list(contract.output_names),
            )
            artifact = build_debug_artifact(
                spec=workflow_contract,
                batch_label=batch_label,
                review_round=review_round,
                format_attempt=format_attempt,
                max_format_retries=retries,
                status=(
                    "retry_exhausted"
                    if format_attempt >= retries or _is_non_retryable(exc)
                    else "failed_retryable"
                ),
                validator_issues=issues,
                exception=exc,
                raw_output_source=str(debug_fields.get("raw_output_source") or "stage_output"),
                matched_aliases=list(
                    getattr(exc, "matched_aliases", None)
                    or runner_debug.get("matched_aliases", [])
                    or aliases
                ),
                candidate_sources=debug_fields.get("candidate_sources"),
                matched_fields=debug_fields.get("matched_fields"),
                missing_fields=debug_fields.get("missing_fields"),
                probable_truncated_json=bool(debug_fields.get("probable_truncated_json")),
                answer_text_preview=debug_fields.get("answer_text_preview"),
                response_preview=debug_fields.get("response_preview"),
                raw_preview=debug_fields.get("response_preview") or raw_output,
                normalized_preview=normalized_preview or validation_meta.get("normalized_preview") or "",
                fallback_used=False,
                last_failure_reason=str(debug_fields.get("last_failure_reason") or str(exc)),
            )
            debug_file_path = _write_stage_debug_artifact_file(
                artifact=artifact,
                stage_variables=variables,
                runner_debug=runner_debug,
                raw_output=raw_output,
                batch=batch,
                exception=exc,
            )
            artifact["debug_file_path"] = debug_file_path
            state.set_output(stage_name, "contract_guard", artifact)
            _log_stage_format_failure(
                contract=contract,
                batch_label=batch_label,
                format_attempt=format_attempt,
                retries=retries,
                debug_fields=debug_fields,
                debug_file_path=debug_file_path,
            )
            if _is_non_retryable(exc) or format_attempt >= retries:
                set_runtime_stage(
                    state,
                    runtime_stage_key,
                    f"{contract.label} 输出格式校验失败，已保留当前进度：{exc}",
                    batch_label=batch_label,
                    progress_percent=progress_percent,
                    generated_episodes=generated_episodes,
                )
                sync_runtime_state(state)
                formatted_error = _format_retry_exhausted_error(
                    contract=contract,
                    debug_file_path=debug_file_path,
                    failure_reason=str(debug_fields.get("last_failure_reason") or str(exc)),
                )
                raise _attach_contract_guard_error_meta(
                    formatted_error,
                    validation_error=exc if isinstance(exc, WorkflowOutputValidationError) else None,
                    validator_issues=issues,
                    artifact=artifact,
                ) from exc
            set_runtime_stage(
                state,
                runtime_stage_key,
                "阶段输出格式异常，正在自动重试。",
                batch_label=batch_label,
                progress_percent=progress_percent,
                generated_episodes=generated_episodes,
            )
            sync_runtime_state(state)

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"{stage_name} contract guard failed without explicit error")


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
    sync_output_to_state: bool = True,
) -> dict[str, Any]:
    """统一封装单个 FastGPT 阶段调用，负责进度上报、契约校验和网络重试。"""
    contract = contract_for(stage_name)
    runtime_stage_key = stage_name or stage_key
    del max_retries
    retries = _stage_format_retry_limit()
    workflow_contract = _stage_workflow_contract_spec(stage_name)
    last_error: Exception | None = None

    attempt = 0
    format_failures = 0
    while True:
        attempt += 1
        _checkpoint(state)
        set_runtime_stage(
            state,
            runtime_stage_key,
            message,
            batch_label=batch_label,
            progress_percent=progress_percent,
            generated_episodes=generated_episodes,
        )
        sync_runtime_state(state)
        try:
            output = _run_fastgpt_stage_once(
                state,
                runner,
                stage_name,
                variables,
                stage_key=stage_key,
                message=message,
                batch_label=batch_label,
                progress_percent=progress_percent,
                generated_episodes=generated_episodes,
                sync_output_to_state=False,
            )
            if sync_output_to_state:
                _sync_state_variables(state, output)
            runner_debug = _runner_stage_debug_info(runner, stage_name)
            debug_fields = _artifact_debug_fields(
                runner_debug=runner_debug,
                exception=None,
                default_missing_fields=[],
            )
            artifact = build_debug_artifact(
                spec=workflow_contract,
                batch_label=batch_label,
                review_round=None,
                format_attempt=max(1, format_failures or 1),
                max_format_retries=retries,
                status="validated",
                raw_output_source=str(debug_fields.get("raw_output_source") or "stage_output"),
                matched_aliases=list(runner_debug.get("matched_aliases", [])),
                candidate_sources=debug_fields.get("candidate_sources"),
                matched_fields=debug_fields.get("matched_fields") or list(output.keys()),
                missing_fields=[],
                probable_truncated_json=bool(debug_fields.get("probable_truncated_json")),
                answer_text_preview=debug_fields.get("answer_text_preview"),
                response_preview=debug_fields.get("response_preview"),
                raw_preview=debug_fields.get("response_preview") or output,
                normalized_preview=output,
                fallback_used=False,
                last_failure_reason="",
            )
            state.set_output(stage_name, "contract_guard", artifact)
            return output
        except FastGPTTransientError as exc:
            last_error = exc
            delay_seconds = _transient_retry_delay(attempt)
            retry_message = "网络波动，已保留当前进度，正在自动重试。"
            set_runtime_stage(
                state,
                runtime_stage_key,
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
                    runtime_stage_key,
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
            format_failures += 1
            runner_debug = _runner_stage_debug_info(runner, stage_name)
            debug_fields = _artifact_debug_fields(
                runner_debug=runner_debug,
                exception=exc,
                default_missing_fields=list(contract.output_names),
            )
            artifact = build_debug_artifact(
                spec=workflow_contract,
                batch_label=batch_label,
                review_round=None,
                format_attempt=format_failures,
                max_format_retries=retries,
                status=(
                    "retry_exhausted"
                    if format_failures >= retries or _is_non_retryable(exc)
                    else "failed_retryable"
                ),
                validator_issues=list(getattr(exc, "issues", []) or []),
                exception=exc,
                raw_output_source=str(debug_fields.get("raw_output_source") or "stage_output"),
                matched_aliases=list(
                    getattr(exc, "matched_aliases", None)
                    or runner_debug.get("matched_aliases", [])
                    or []
                ),
                candidate_sources=debug_fields.get("candidate_sources"),
                matched_fields=debug_fields.get("matched_fields"),
                missing_fields=debug_fields.get("missing_fields"),
                probable_truncated_json=bool(debug_fields.get("probable_truncated_json")),
                answer_text_preview=debug_fields.get("answer_text_preview"),
                response_preview=debug_fields.get("response_preview"),
                raw_preview=debug_fields.get("response_preview"),
                normalized_preview=getattr(exc, "normalized_output", None),
                fallback_used=False,
                last_failure_reason=str(debug_fields.get("last_failure_reason") or str(exc)),
            )
            debug_file_path = _write_stage_debug_artifact_file(
                artifact=artifact,
                stage_variables=variables,
                runner_debug=runner_debug,
                raw_output=None,
                batch=None,
                exception=exc,
            )
            artifact["debug_file_path"] = debug_file_path
            state.set_output(stage_name, "contract_guard", artifact)
            sync_runtime_state(state)
            _log_stage_format_failure(
                contract=contract,
                batch_label=batch_label,
                format_attempt=format_failures,
                retries=retries,
                debug_fields=debug_fields,
                debug_file_path=debug_file_path,
            )
            if _is_non_retryable(exc) or format_failures >= retries:
                set_runtime_stage(
                    state,
                    stage_key,
                    f"{contract.label} 调用失败，已保留当前进度：{exc}",
                    batch_label=batch_label,
                    progress_percent=progress_percent,
                    generated_episodes=generated_episodes,
                )
                sync_runtime_state(state)
                raise _format_retry_exhausted_error(
                    contract=contract,
                    debug_file_path=debug_file_path,
                    failure_reason=str(debug_fields.get("last_failure_reason") or str(exc)),
                ) from exc
            set_runtime_stage(
                state,
                stage_key,
                "阶段返回格式异常，正在自动重试。",
                batch_label=batch_label,
                progress_percent=progress_percent,
                generated_episodes=generated_episodes,
            )


def _ensure_scene_outputs(
    state: WorkflowState,
    runner: FastGPTRunner,
    variables: dict[str, Any],
) -> None:
    cached_issue = _scene_output_integrity_issue(variables.get(SCENES))
    if cached_issue is None:
        set_runtime_stage(
            state,
            "scene",
            "已从缓存恢复核心场景。",
            progress_percent=34,
        )
        sync_runtime_state(state)
        return

    if _scene_stage_has_transient_state(state, variables):
        logger.warning(
            "stage_name=scenes failure_type=stale_scene_cache source=resume_or_runtime_cache "
            "missing_fields=%s attempted_json_repair=%s local_restart_attempt=%s "
            "cleared_stage_cache=%s preview=%s",
            [cached_issue] if cached_issue else [],
            False,
            0,
            True,
            _truncate_log_text(_serialize_framework_runtime_value(variables.get(SCENES)), max_chars=280),
        )
        _clear_scene_stage_state(state, variables)
        sync_runtime_state(state)

    scene_inputs, warnings, fatal_errors = _prepare_scene_stage_inputs(variables)
    for warning in warnings:
        logger.warning(
            "stage_name=scenes failure_type=scene_input_degraded source=local_input_guard "
            "missing_fields=[] attempted_json_repair=%s local_restart_attempt=%s "
            "cleared_stage_cache=%s preview=%s",
            True,
            0,
            False,
            _truncate_log_text(warning, max_chars=220),
        )
    if fatal_errors:
        message = (
            "scenes 阶段检测到上游正式输入已损坏，已阻止继续进入下一阶段："
            + "；".join(fatal_errors)
        )
        logger.warning(
            "stage_name=scenes failure_type=broken_upstream_inputs source=local_input_guard "
            "missing_fields=%s attempted_json_repair=%s local_restart_attempt=%s "
            "cleared_stage_cache=%s preview=%s",
            fatal_errors[:8],
            True,
            0,
            True,
            _truncate_log_text(message, max_chars=320),
        )
        _clear_scene_stage_state(state, variables)
        sync_runtime_state(state)
        raise ValueError(message)

    scene_context = {**variables, **scene_inputs}
    try:
        output = _run_fastgpt_stage(
            state,
            runner,
            STAGE_SCENES,
            scene_context,
            stage_key="scene",
            message="正在生成并校正核心场景。",
            progress_percent=34,
            max_retries=0,
        )
    except Exception as exc:
        logger.warning(
            "stage_name=scenes failure_type=scene_stage_restart_exhausted source=fastgpt_stage "
            "missing_fields=[] attempted_json_repair=%s local_restart_attempt=%s "
            "cleared_stage_cache=%s preview=%s",
            True,
            max(0, int(getattr(settings, "fastgpt_stage_local_restart_retries", 1))),
            True,
            _truncate_log_text(str(exc), max_chars=320),
        )
        _clear_scene_stage_state(state, variables)
        sync_runtime_state(state)
        raise

    scene_issue = _scene_output_integrity_issue(output.get(SCENES))
    if scene_issue:
        logger.warning(
            "stage_name=scenes failure_type=post_stage_scene_validation_failed source=contract_output "
            "missing_fields=%s attempted_json_repair=%s local_restart_attempt=%s "
            "cleared_stage_cache=%s preview=%s",
            [scene_issue],
            True,
            max(0, int(getattr(settings, "fastgpt_stage_local_restart_retries", 1))),
            True,
            _truncate_log_text(_serialize_framework_runtime_value(output.get(SCENES)), max_chars=320),
        )
        _clear_scene_stage_state(state, variables)
        sync_runtime_state(state)
        raise ValueError(f"scenes 阶段输出未通过本地结构校验：{scene_issue}")

    variables.update(output)


def _ensure_appearance_outputs(
    state: WorkflowState,
    runner: FastGPTRunner,
    variables: dict[str, Any],
) -> None:
    cached_issues = _appearance_output_integrity_issues(variables.get(APPEARANCE_MAPPING))
    if not cached_issues and _apply_appearance_outputs_to_variables(variables):
        _sync_state_variables(state, variables)
        _try_generate_appearance_unstructured_output(state, runner, variables)
        set_runtime_stage(
            state,
            "appearance",
            "已从缓存恢复人物服装版本映射。",
            progress_percent=42,
        )
        sync_runtime_state(state)
        return
    if not cached_issues:
        cached_issues = ["appearance_mapping 通过契约校验后仍无法生成本地 alias registry"]

    if _appearance_stage_has_transient_state(state, variables):
        logger.warning(
            "stage_name=appearance_alias_generation failure_type=stale_appearance_cache "
            "source=resume_or_runtime_cache blocking_issues=%s local_review_attempt=%s "
            "cleared_stage_cache=%s preview=%s",
            cached_issues[:8],
            0,
            True,
            _truncate_log_text(
                _serialize_framework_runtime_value(variables.get(APPEARANCE_MAPPING)),
                max_chars=320,
            ),
        )
        _clear_appearance_stage_state(state, variables)
        sync_runtime_state(state)

    appearance_inputs, warnings, fatal_errors = _prepare_appearance_stage_inputs(variables)
    for warning in warnings:
        logger.warning(
            "stage_name=appearance_alias_generation failure_type=appearance_input_degraded "
            "source=local_input_guard blocking_issues=[] local_review_attempt=%s "
            "cleared_stage_cache=%s preview=%s",
            0,
            False,
            _truncate_log_text(warning, max_chars=220),
        )
    if fatal_errors:
        message = (
            "appearance_alias_generation 阶段检测到上游正式产物损坏，已阻止继续进入下一阶段："
            + "；".join(fatal_errors)
        )
        logger.warning(
            "stage_name=appearance_alias_generation failure_type=broken_upstream_inputs "
            "source=local_input_guard blocking_issues=%s local_review_attempt=%s "
            "cleared_stage_cache=%s preview=%s",
            fatal_errors[:8],
            0,
            True,
            _truncate_log_text(message, max_chars=320),
        )
        state.set_output(
            STAGE_APPEARANCE_ALIAS_GENERATION,
            "last_invalid_output",
            {
                "failure_type": "broken_upstream_inputs",
                "blocking_issues": fatal_errors[:12],
                "preview": _truncate_log_text(message, max_chars=500),
            },
        )
        _clear_appearance_stage_state(state, variables)
        sync_runtime_state(state)
        raise ValueError(message)

    appearance_context = {**variables, **appearance_inputs}
    review_loop_limit = _stage_review_revise_loop_limit()
    current_mapping: dict[str, Any] | None = None
    current_review_payload: dict[str, Any] | None = None
    last_failure_type = "appearance_structured_stage_failed"
    last_issues: list[str] = []
    last_preview = ""

    try:
        writing_output = run_stage_with_contract_guard(
            state,
            runner,
            STAGE_APPEARANCE_ALIAS_WRITING,
            appearance_context,
            stage_key="appearance",
            message="正在编写人物服装版本映射。",
            progress_percent=42,
            output_field=APPEARANCE_MAPPING,
            validator=validate_appearance_mapping_output,
            sync_output_to_state=False,
        )
        current_mapping = _normalize_appearance_mapping_object(
            writing_output.get(APPEARANCE_MAPPING)
        )
        if current_mapping is None:
            raise ValueError("appearance_alias_writing 未返回可归一化的 h2KpLm91")

        for review_round in range(1, review_loop_limit + 1):
            review_context = {
                **appearance_context,
                APPEARANCE_MAPPING: copy.deepcopy(current_mapping),
            }
            review_output = run_stage_with_contract_guard(
                state,
                runner,
                STAGE_APPEARANCE_ALIAS_REVIEW,
                review_context,
                stage_key="appearance",
                message=f"正在审核人物服装版本映射：第 {review_round}/{review_loop_limit} 轮",
                progress_percent=42,
                review_round=review_round,
                review_parser=parse_review_result,
                sync_output_to_state=False,
            )
            review_decision = parse_review_result(review_output)
            current_review_payload = copy.deepcopy(review_decision.payload)
            last_issues = [
                str(item).strip()
                for item in list(review_decision.blocking_issues or [])
                if str(item).strip()
            ]
            last_preview = _truncate_log_text(
                _serialize_framework_runtime_value(current_review_payload),
                max_chars=500,
            )

            if review_decision.passed and not review_decision.blocking_issues:
                variables[APPEARANCE_MAPPING] = copy.deepcopy(current_mapping)
                variables[PASS_REVIEW_JSON] = copy.deepcopy(current_review_payload)
                variables[APPEARANCE_REVIEW_VAR] = copy.deepcopy(current_review_payload)
                if not _apply_appearance_outputs_to_variables(variables):
                    raise ValueError(
                        "appearance_mapping 通过审核后仍无法生成 registry / alias plan"
                    )
                _sync_state_variables(state, variables)
                state.set_var(APPEARANCE_REVIEW_VAR, copy.deepcopy(current_review_payload))
                _try_generate_appearance_unstructured_output(state, runner, variables)
                variables.pop(PASS_REVIEW_JSON, None)
                state.variables.pop(PASS_REVIEW_JSON, None)
                return

            if review_round >= review_loop_limit:
                last_failure_type = "appearance_review_rewrite_exhausted"
                raise ValueError(
                    "appearance_alias_generation 审核/修订循环已达到上限："
                    + "；".join(last_issues[:12] or ["review did not pass"])
                )

            rewrite_context = {
                **appearance_context,
                APPEARANCE_MAPPING: copy.deepcopy(current_mapping),
                PASS_REVIEW_JSON: copy.deepcopy(current_review_payload),
                APPEARANCE_REVIEW_VAR: copy.deepcopy(current_review_payload),
            }
            rewrite_output = run_stage_with_contract_guard(
                state,
                runner,
                STAGE_APPEARANCE_ALIAS_REWRITE,
                rewrite_context,
                stage_key="appearance",
                message=f"正在修订人物服装版本映射：第 {review_round}/{review_loop_limit} 轮",
                progress_percent=42,
                review_round=review_round,
                output_field=APPEARANCE_MAPPING,
                validator=validate_appearance_mapping_output,
                sync_output_to_state=False,
            )
            current_mapping = _normalize_appearance_mapping_object(
                rewrite_output.get(APPEARANCE_MAPPING)
            )
            if current_mapping is None:
                last_failure_type = "appearance_rewrite_invalid_output"
                raise ValueError("appearance_alias_rewrite 未返回可归一化的 h2KpLm91")
            last_preview = _truncate_log_text(
                _serialize_framework_runtime_value(current_mapping),
                max_chars=500,
            )
    except Exception as exc:
        if not last_preview:
            last_preview = _truncate_log_text(str(exc), max_chars=500)
        logger.warning(
            "stage_name=appearance_alias_generation failure_type=%s source=python_orchestration "
            "blocking_issues=%s review_loop_limit=%s cleared_stage_cache=%s preview=%s",
            last_failure_type,
            last_issues[:10],
            review_loop_limit,
            True,
            _truncate_log_text(str(exc), max_chars=320),
        )
        state.set_output(
            STAGE_APPEARANCE_ALIAS_GENERATION,
            "last_invalid_output",
            {
                "failure_type": last_failure_type,
                "blocking_issues": last_issues[:20],
                "preview": last_preview,
            },
        )
        _clear_appearance_stage_state(state, variables)
        sync_runtime_state(state)
        raise


def _try_generate_appearance_unstructured_output(
    state: WorkflowState,
    runner: FastGPTRunner,
    variables: dict[str, Any],
) -> None:
    if is_meaningful_text(variables.get(APPEARANCE_NATURAL_LANGUAGE_VAR)):
        return

    stage_variables = dict(variables)
    stage_variables.pop(APPEARANCE_NATURAL_LANGUAGE_VAR, None)
    try:
        output = run_stage_with_contract_guard(
            state,
            runner,
            STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
            stage_variables,
            stage_key="appearance",
            message="正在整理服装版本自然语言说明。",
            progress_percent=44,
            output_field=APPEARANCE_NATURAL_LANGUAGE_VAR,
            sync_output_to_state=False,
        )
    except Exception as exc:
        logger.warning(
            "stage_name=appearance_alias_unstructured failure_type=appearance_unstructured_optional_failed "
            "source=fastgpt_stage blocking_issues=[] cleared_stage_cache=%s preview=%s",
            False,
            _truncate_log_text(str(exc), max_chars=320),
        )
        state.set_output(
            STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
            "last_invalid_output",
            {
                "failure_type": "appearance_unstructured_optional_failed",
                "blocking_issues": [],
                "preview": _truncate_log_text(str(exc), max_chars=500),
            },
        )
        variables.pop(APPEARANCE_NATURAL_LANGUAGE_VAR, None)
        state.variables.pop(APPEARANCE_NATURAL_LANGUAGE_VAR, None)
        sync_runtime_state(state)
        return

    natural_language = str(output.get(APPEARANCE_NATURAL_LANGUAGE_VAR) or "").strip()
    if is_meaningful_text(natural_language):
        variables[APPEARANCE_NATURAL_LANGUAGE_VAR] = natural_language
        state.set_var(APPEARANCE_NATURAL_LANGUAGE_VAR, natural_language)
        sync_runtime_state(state)


def _prepare_appearance_stage_inputs(
    variables: dict[str, Any],
) -> tuple[dict[str, str], list[str], list[str]]:
    prepared: dict[str, str] = {}
    warnings: list[str] = []
    fatal_errors: list[str] = []

    worldview_text = _normalize_appearance_formal_stage_input(
        STAGE_WORLDVIEW,
        WORLDVIEW,
        variables.get(WORLDVIEW),
    )
    if worldview_text is None:
        fatal_errors.append("worldview 为空或不是合法世界观 JSON")
    else:
        prepared[WORLDVIEW] = worldview_text

    story_outline_text = _normalize_scene_json_object_input(
        variables.get(STORY_OUTLINE),
        field_name=STORY_OUTLINE,
    )
    if story_outline_text is None:
        fatal_errors.append("story_outline 为空或不是合法故事大纲 JSON")
    else:
        prepared[STORY_OUTLINE] = story_outline_text

    episode_plan_text = _normalize_scene_episode_plan_input(variables.get(EPISODE_PLAN))
    if episode_plan_text is None:
        fatal_errors.append("episode_plan 为空或不是合法分集计划 JSON")
    else:
        prepared[EPISODE_PLAN] = episode_plan_text

    user_characters_text = _normalize_appearance_story_context_input(
        variables.get(USER_CHARACTERS),
        field_name=USER_CHARACTERS,
        warnings=warnings,
    )
    if user_characters_text is None:
        fatal_errors.append("user_characters 为空或不是可消费的人物小传上下文")
    else:
        prepared[USER_CHARACTERS] = user_characters_text

    characters_text = _normalize_appearance_formal_stage_input(
        STAGE_CHARACTERS,
        CHARACTERS,
        variables.get(CHARACTERS),
    )
    if characters_text is None:
        fatal_errors.append("characters 为空或不是合法结构化人设 JSON")
    else:
        compact_characters_text = _compact_stage_text(
            variables.get(CHARACTERS),
            builder=build_compact_character_context_for_appearance,
            fallback=characters_text,
        )
        prepared[CHARACTERS] = compact_characters_text
        prepared[USER_CHARACTERS] = compact_characters_text

    scenes_text = _normalize_appearance_formal_stage_input(
        STAGE_SCENES,
        SCENES,
        variables.get(SCENES),
    )
    if scenes_text is None:
        fatal_errors.append("scenes 为空或不是合法结构化场景 JSON")
    else:
        prepared[SCENES] = _compact_stage_text(
            variables.get(SCENES),
            builder=build_compact_scene_context_for_appearance,
            fallback=scenes_text,
        )

    prepared[CHARACTER_ALIAS_NAMING_RULES] = _normalize_scene_optional_input(
        CHARACTER_ALIAS_NAMING_RULES,
        variables.get(CHARACTER_ALIAS_NAMING_RULES),
        warnings=warnings,
    )
    prepared[APPEARANCE_MAPPING] = _normalize_scene_optional_input(
        APPEARANCE_MAPPING,
        variables.get(APPEARANCE_MAPPING),
        warnings=warnings,
    )
    return prepared, warnings, fatal_errors


def _prepare_scene_stage_inputs(
    variables: dict[str, Any],
) -> tuple[dict[str, str], list[str], list[str]]:
    prepared: dict[str, str] = {}
    warnings: list[str] = []
    fatal_errors: list[str] = []

    worldview_text = _normalize_scene_worldview_input(variables.get(WORLDVIEW))
    if worldview_text is None:
        fatal_errors.append("worldview 为空或不是合法世界观 JSON")
    else:
        prepared[WORLDVIEW] = worldview_text

    story_outline_text = _normalize_scene_json_object_input(
        variables.get(STORY_OUTLINE),
        field_name=STORY_OUTLINE,
    )
    if story_outline_text is None:
        fatal_errors.append("story_outline 为空或不是可解析 JSON object")
    else:
        prepared[STORY_OUTLINE] = story_outline_text

    user_characters_text = _compact_stage_text(
        variables.get(CHARACTERS),
        builder=build_compact_character_context_for_scenes,
    )
    if not user_characters_text:
        user_characters_text = _normalize_scene_json_collection_input(
            variables.get(USER_CHARACTERS),
            field_name=USER_CHARACTERS,
        )
    if user_characters_text is None:
        fatal_errors.append("user_characters 为空或不是可解析 JSON")
    else:
        prepared[USER_CHARACTERS] = user_characters_text

    episode_plan_text = _normalize_scene_episode_plan_input(variables.get(EPISODE_PLAN))
    if episode_plan_text is None:
        fatal_errors.append("episode_plan 为空或不是可消费分集计划 JSON")
    else:
        prepared[EPISODE_PLAN] = episode_plan_text

    for field_name in SCENE_OPTIONAL_INPUT_FIELDS:
        prepared[field_name] = _normalize_scene_optional_input(
            field_name,
            variables.get(field_name),
            warnings=warnings,
        )

    return prepared, warnings, fatal_errors


def _normalize_appearance_formal_stage_input(
    stage_name: str,
    field_name: str,
    value: Any,
) -> str | None:
    if value in (None, ""):
        return None
    text = _serialize_framework_runtime_value(value)
    if not text:
        return None
    try:
        return contract_for(stage_name).validate_output_payload({field_name: text})[field_name]
    except Exception:
        return None


def _normalize_appearance_story_context_input(
    value: Any,
    *,
    field_name: str,
    warnings: list[str],
) -> str | None:
    del field_name
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    candidate = _scene_json_candidate(text)
    if isinstance(candidate, (dict, list)):
        return json.dumps(candidate, ensure_ascii=False, indent=2)
    warnings.append("user_characters 不是结构化 JSON，已按纯文本人物小传透传给 appearance 阶段。")
    return text


def _normalize_scene_worldview_input(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = _serialize_framework_runtime_value(value)
    if not text:
        return None
    try:
        return contract_for(STAGE_WORLDVIEW).validate_output_payload({WORLDVIEW: text})[WORLDVIEW]
    except Exception:
        return None


def _normalize_scene_json_object_input(value: Any, *, field_name: str) -> str | None:
    data = _scene_json_candidate(value)
    if not isinstance(data, dict) or not data:
        return None
    return json.dumps(data, ensure_ascii=False, indent=2)


def _normalize_scene_json_collection_input(value: Any, *, field_name: str) -> str | None:
    data = _scene_json_candidate(value)
    if isinstance(data, list):
        return json.dumps(data, ensure_ascii=False, indent=2) if data else None
    if isinstance(data, dict):
        characters = data.get("characters")
        if isinstance(characters, list) and characters:
            return json.dumps(data, ensure_ascii=False, indent=2)
        if data:
            return json.dumps(data, ensure_ascii=False, indent=2)
    return None


def _normalize_scene_episode_plan_input(value: Any) -> str | None:
    if _normalize_episode_plan_object(value) is None:
        return None
    return _serialize_framework_runtime_value(value)


def _normalize_scene_optional_input(
    field_name: str,
    value: Any,
    *,
    warnings: list[str],
) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    text = str(value).strip()
    if not text:
        return ""
    if field_name == USER_SCENES:
        candidate = _scene_json_candidate(text)
        if isinstance(candidate, (dict, list)):
            return json.dumps(candidate, ensure_ascii=False, indent=2)
        return text
    return text


def _scene_json_candidate(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return parse_json(text)
    except Exception:
        return None


def _scene_output_integrity_issue(value: Any) -> str | None:
    if not _has_value(value):
        return "scenes 为空"
    try:
        contract_for(STAGE_SCENES).validate_output_payload({SCENES: value})
    except Exception as exc:
        return str(exc)
    issues = validate_scenes_output(value)
    if issues:
        return issues[0]
    return None


def _appearance_output_integrity_issues(value: Any) -> list[str]:
    if not _has_value(value):
        return ["appearance_mapping 为空"]
    issues = validate_appearance_mapping_output(value)
    if issues:
        return issues
    if _normalize_appearance_mapping_object(value) is None:
        return ["appearance_mapping 未能规范化为内部可消费对象"]
    return []


def _scene_stage_has_transient_state(
    state: WorkflowState,
    variables: dict[str, Any],
) -> bool:
    for key in SCENE_STAGE_TRANSIENT_KEYS:
        if _has_value(variables.get(key)):
            return True
        if _has_value(state.variables.get(key)):
            return True
    return False


def _appearance_stage_has_transient_state(
    state: WorkflowState,
    variables: dict[str, Any],
) -> bool:
    for key in APPEARANCE_STAGE_TRANSIENT_KEYS:
        if _has_value(variables.get(key)):
            return True
        if _has_value(state.variables.get(key)):
            return True
    return False


def _clear_scene_stage_state(state: WorkflowState, variables: dict[str, Any]) -> None:
    for key in SCENE_STAGE_TRANSIENT_KEYS:
        variables.pop(key, None)
        state.variables.pop(key, None)


def _clear_appearance_stage_state(state: WorkflowState, variables: dict[str, Any]) -> None:
    for key in APPEARANCE_STAGE_TRANSIENT_KEYS:
        variables.pop(key, None)
        state.variables.pop(key, None)


def _ensure_stage_output_mapping(stage_name: str, output: Any) -> dict[str, Any]:
    if isinstance(output, dict):
        return output
    if output is None:
        raise ValueError(f"FastGPT 阶段 {stage_name} 返回了空结果（None）。")

    try:
        preview = json.dumps(to_jsonable_value(output), ensure_ascii=False, default=str)
    except Exception:
        preview = str(output)
    preview = " ".join(str(preview or "").split())
    if len(preview) > 240:
        preview = f"{preview[:240]}..."
    suffix = f"：{preview}" if preview else ""
    raise ValueError(
        f"FastGPT 阶段 {stage_name} 返回了非对象结果（{type(output).__name__}）{suffix}"
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


def _stage_label_with_review_round(stage_label: str, message: str) -> str:
    match = REVIEW_ROUND_MESSAGE_PATTERN.search(str(message or ""))
    if match is None:
        return stage_label
    round_text = re.sub(r"\s+", "", match.group(1))
    return f"{stage_label}（{round_text}）"


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
    if isinstance(exc, FastGPTPayloadTooLargeError):
        return True
    text = str(exc)
    return "缺少 FastGPT API Key" in text or "401" in text or "403" in text


def _run_optional_memory_stage(
    state: WorkflowState,
    runner: FastGPTRunner,
    stage_name: str,
    variables: dict[str, Any],
    *,
    stage_key: str,
    message: str,
    batch_label: str,
    progress_percent: int,
    generated_episodes: int,
    fallback_output: dict[str, Any],
    output_field: str | None = None,
    batch: BatchWindow | None = None,
    memory_normalizer: Any = None,
    memory_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stage_outputs = getattr(runner, "stage_outputs", None)
    if isinstance(stage_outputs, dict) and stage_name not in stage_outputs:
        runner_name = runner.__class__.__name__
        if runner_name.startswith("_") or "RecordingRunner" in runner_name:
            logger.warning("%s 未被当前测试 runner 声明，已保留上一轮记忆继续。", stage_name)
            return dict(fallback_output)
    try:
        return run_stage_with_contract_guard(
            state,
            runner,
            stage_name,
            variables,
            stage_key=stage_key,
            message=message,
            batch_label=batch_label,
            progress_percent=progress_percent,
            generated_episodes=generated_episodes,
            output_field=output_field,
            batch=batch,
            memory_normalizer=memory_normalizer,
            memory_kwargs=memory_kwargs,
            sync_output_to_state=False,
        )
    except AssertionError as exc:
        if "Unexpected stage call" not in str(exc):
            raise
        logger.warning("%s 未被当前 runner 支持，已保留上一轮记忆继续：%s", stage_name, exc)
        return dict(fallback_output)


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
    if CHARACTER_NATURAL_LANGUAGE_VAR in variables:
        state.set_var(
            CHARACTER_NATURAL_LANGUAGE_VAR,
            str(variables[CHARACTER_NATURAL_LANGUAGE_VAR] or "").strip(),
        )
    if CHARACTERS in variables:
        state.set_var(CHARACTER_VAR, variables[CHARACTERS])
        state.set_var(FINAL_CHARACTER_VAR, variables[CHARACTERS])
    if SCENE_NATURAL_LANGUAGE_VAR in variables:
        state.set_var(
            SCENE_NATURAL_LANGUAGE_VAR,
            str(variables[SCENE_NATURAL_LANGUAGE_VAR] or "").strip(),
        )
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
        state.set_var(DIALOGUE_START_INPUT_VAR, variables[BATCH_START_EPISODE])
        state.set_var(SCRIPT_START_VAR, variables[BATCH_START_EPISODE])
        state.set_var(EPISODE_PLAN_CURSOR_VAR, variables[BATCH_START_EPISODE])
    if BATCH_HOOKS in variables:
        for alias in HOOK_BATCH_ALIASES:
            state.set_var(alias, variables[BATCH_HOOKS])
    if ALL_HOOKS in variables:
        for alias in HOOK_FINAL_ALIASES:
            state.set_var(alias, variables[ALL_HOOKS])
    if BATCH_DIALOGUES in variables:
        for alias in DIALOGUE_BATCH_ALIASES:
            state.set_var(alias, variables[BATCH_DIALOGUES])
    if ALL_DIALOGUES in variables:
        for alias in DIALOGUE_FINAL_ALIASES:
            state.set_var(alias, variables[ALL_DIALOGUES])
    if BATCH_SCRIPT in variables:
        for alias in SCRIPT_BATCH_ALIASES:
            state.set_var(alias, variables[BATCH_SCRIPT])
    if ALL_SCRIPT in variables:
        state.set_var(ALL_SCRIPT, variables[ALL_SCRIPT])
        for alias in SCRIPT_FINAL_ALIASES:
            state.set_var(alias, variables[ALL_SCRIPT])
    if HOOK_MEMORY in variables:
        for alias in HOOK_MEMORY_ALIASES:
            state.set_var(alias, variables[HOOK_MEMORY])
    if DIALOGUE_MEMORY in variables:
        for alias in DIALOGUE_MEMORY_ALIASES:
            state.set_var(alias, variables[DIALOGUE_MEMORY])
    if SCRIPT_MEMORY in variables:
        for alias in SCRIPT_MEMORY_ALIASES:
            state.set_var(alias, variables[SCRIPT_MEMORY])
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
    """把快照里的变量和正式产物恢复回来，再对批次指针做一次去污染校正。"""
    if not resume_snapshot:
        return
    if not isinstance(resume_snapshot, dict):
        logger.warning(
            "恢复快照格式异常，已跳过恢复；实际类型=%s。",
            type(resume_snapshot).__name__,
        )
        return
    debug_state = resume_snapshot.get("debug_state")
    if not isinstance(debug_state, dict):
        return

    restored_variables = debug_state.get("variables")
    if isinstance(restored_variables, dict):
        # 恢复时优先保留“真实执行变量”，因为它们比 artifacts 更完整，
        # 包含了批次指针、局部缓存和回退控制位。
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

    # 快照里的 start_episode/index 可能是旧版本残留或失败中断时的脏值，
    # 恢复变量后必须再根据真实缓存覆盖度重新推导一次批次位置。
    _sanitize_restored_batch_progress(variables)


def _sanitize_restored_batch_progress(variables: dict[str, Any]) -> None:
    """清理恢复快照里明显失真的批次指针，避免旧尾批位置继续污染新批次切片。"""
    total_episodes = _safe_int(variables.get(TOTAL_EPISODES), 0)
    max_start_episode = max(1, total_episodes + 1) if total_episodes > 0 else 1
    batch_size = max(1, int(settings.batch_size or 5))
    batches = list(iter_episode_batches(total_episodes, batch_size=batch_size)) if total_episodes > 0 else []
    total_batches = len(batches)

    saved_start = _safe_int(variables.get(BATCH_START_EPISODE), 0)
    if saved_start and not (1 <= saved_start <= max_start_episode):
        variables.pop(BATCH_START_EPISODE, None)

    saved_index = _safe_int(variables.get(LOCAL_CURRENT_BATCH_INDEX), 0)
    if saved_index < 0 or (total_batches and saved_index > total_batches):
        variables[LOCAL_CURRENT_BATCH_INDEX] = 0

    current_stage = str(variables.get(LOCAL_CURRENT_BATCH_STAGE) or "").strip().lower()
    if current_stage not in {"", "hook", "dialogue", "script"}:
        variables[LOCAL_CURRENT_BATCH_STAGE] = ""

    rewrite_stage = str(variables.get(LOCAL_REWRITE_FROM_STAGE) or "").strip().lower()
    if rewrite_stage not in {"", "dialogue", "script", "final"}:
        variables[LOCAL_REWRITE_FROM_STAGE] = ""
        rewrite_stage = ""

    has_batched_outputs = any(
        _has_value(variables.get(key))
        for key in (ALL_HOOKS, BATCH_HOOKS, ALL_DIALOGUES, BATCH_DIALOGUES, ALL_SCRIPT, BATCH_SCRIPT)
    )
    derived_start, derived_completed_batches = _derive_restored_batch_progress(
        variables,
        batches=batches,
        current_stage=current_stage,
        rewrite_stage=rewrite_stage,
    )
    if derived_start is not None:
        variables[BATCH_START_EPISODE] = derived_start
        variables[LOCAL_COMPLETED_BATCHES] = derived_completed_batches
        variables[LOCAL_CURRENT_BATCH_INDEX] = derived_completed_batches
        if derived_start > total_episodes and current_stage in {"hook", "dialogue", "script"}:
            variables[LOCAL_CURRENT_BATCH_STAGE] = ""
        logger.info(
            "恢复快照批次已重新对齐：stage=%s rewrite=%s start_episode=%s completed_batches=%s/%s。",
            current_stage or "none",
            rewrite_stage or "none",
            derived_start,
            derived_completed_batches,
            total_batches,
        )
        return

    if not has_batched_outputs and not current_stage and saved_start > 1:
        variables[BATCH_START_EPISODE] = 1
        variables[LOCAL_COMPLETED_BATCHES] = 0
        variables[LOCAL_CURRENT_BATCH_INDEX] = 0
        logger.info("恢复快照未发现可信批次缓存，已回退到第 1 批重新开始。")


def _derive_restored_batch_progress(
    variables: dict[str, Any],
    *,
    batches: list[BatchWindow],
    current_stage: str,
    rewrite_stage: str,
) -> tuple[int | None, int]:
    """根据已落盘缓存倒推真实进度，优先相信实际产物，不盲信旧索引。"""
    if not batches:
        return None, 0

    pending_hook_memory_start = _pending_hook_memory_batch_start(variables, batches=batches)
    pending_dialogue_memory_start = _pending_dialogue_memory_batch_start(variables, batches=batches)
    hooks_start = _next_unfinished_object_batch_start(variables.get(ALL_HOOKS), batches)
    dialogues_start = _next_unfinished_object_batch_start(variables.get(ALL_DIALOGUES), batches)
    script_start = _next_unfinished_script_batch_start(variables, batches)
    if pending_hook_memory_start is not None:
        hooks_start = pending_hook_memory_start
    if pending_dialogue_memory_start is not None:
        dialogues_start = pending_dialogue_memory_start
    last_episode = batches[-1].end_episode
    hooks_complete = hooks_start > last_episode
    dialogues_complete = dialogues_start > last_episode

    if current_stage == "hook":
        target_start = hooks_start
    elif current_stage == "dialogue" or rewrite_stage == "dialogue":
        target_start = dialogues_start if hooks_complete else hooks_start
    elif current_stage == "script" or rewrite_stage in {"script", "final"}:
        if not hooks_complete:
            target_start = hooks_start
        elif not dialogues_complete:
            target_start = dialogues_start
        else:
            target_start = script_start
    else:
        # 新流程按大阶段顺序恢复：
        # 先补 hooks，再补 dialogues，最后补 script。
        if not hooks_complete:
            target_start = hooks_start
        elif not dialogues_complete:
            target_start = dialogues_start
        else:
            target_start = script_start

    completed_batches = len([batch for batch in batches if batch.end_episode < target_start])
    return target_start, completed_batches


def _next_unfinished_object_batch_start(value: Any, batches: list[BatchWindow]) -> int:
    for batch in batches:
        batch_payload = slice_object_episodes_for_batch(value, batch)
        if not _batch_object_is_reusable(batch_payload, batch):
            return batch.start_episode
    return batches[-1].end_episode + 1


def _next_unfinished_script_batch_start(
    variables: dict[str, Any],
    batches: list[BatchWindow],
) -> int:
    script_batches = _normalize_batch_text_map(variables.get(LOCAL_SCRIPT_BATCHES))
    script_episode_cache = _normalize_episode_script_map(variables.get(LOCAL_SCRIPT_EPISODES))
    summary_by_batch = _normalize_batch_text_map(variables.get(LOCAL_SUMMARY_BY_BATCH))
    appearance_memory_by_batch = _normalize_batch_object_map(
        variables.get(LOCAL_APPEARANCE_MEMORY_BY_BATCH)
    )

    for batch in batches:
        batch_text = _existing_batch_script_text(
            batch,
            script_batches=script_batches,
            script_episode_cache=script_episode_cache,
        )
        batch_summary = str(summary_by_batch.get(batch.start_episode) or "").strip()
        if (
            not batch_text
            or not batch_summary
            or not _script_batch_memory_entry_exists(appearance_memory_by_batch, batch)
            or _validate_script_batch_output(batch_text, batch=batch)
        ):
            return batch.start_episode
    return batches[-1].end_episode + 1


def _raw_episode_plan_source(
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> str:
    """优先读取框架阶段落下来的原始分集计划，避免后续规范化写回覆盖原文。"""
    explicit_raw = str(
        variables.get(LOCAL_RAW_EPISODE_PLAN)
        or payload.episode_plan
        or ""
    ).strip()
    if explicit_raw:
        return explicit_raw

    episode_plan_value = str(variables.get(EPISODE_PLAN) or "").strip()
    if episode_plan_value and _normalize_episode_plan_object(episode_plan_value) is None:
        return episode_plan_value
    return ""


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"true", "1", "yes", "y", "是", "通过", "一致"}


def _strict_consistency_flag(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    try:
        return coerce_strict_fastgpt_boolean(value)
    except ValueError:
        return None


def _is_consistency_self_check_retryable_error(exc: Exception) -> bool:
    if _is_non_retryable(exc):
        return False
    text = str(exc or "")
    markers = (
        "必须精确返回 true 或 false",
        "无法转换为 boolean",
        "输出字段 is_consistent 校验失败",
        "未返回契约字段",
        "缺少输出变量",
        "返回了非对象结果",
        "输出必须是 object",
    )
    return any(marker in text for marker in markers)


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


def _ensure_framework_and_consistency(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
    *,
    resume_snapshot_present: bool,
) -> None:
    """负责跑通 framework -> appearance_strategy -> consistency 这一整条前置链路。"""
    retry_limit = max(0, _safe_int(variables.get(MAX_RETRIES), settings.max_retries_default))
    total_attempts = 1 + retry_limit
    last_error: Exception | None = None

    for attempt in range(1, total_attempts + 1):
        _ensure_framework_outputs(
            state,
            runner,
            payload,
            variables,
            resume_snapshot_present=resume_snapshot_present and attempt == 1,
        )
        _ensure_framework_natural_language(state, runner, payload, variables)
        _ensure_pre_strategy_outputs(state, runner, payload, variables)

        cached_consistency = _strict_consistency_flag(variables.get(IS_CONSISTENT))
        if cached_consistency is True:
            set_runtime_stage(
                state,
                "validation",
                "已从缓存恢复集数一致性检查结果。",
                progress_percent=3,
            )
            sync_runtime_state(state)
            return

        if cached_consistency is False:
            consistency = {IS_CONSISTENT: False}
        else:
            set_runtime_stage(
                state,
                "validation",
                "正在核对分集计划和总集数。",
                progress_percent=1,
            )
            sync_runtime_state(state)
            consistency = _run_consistency_stage_with_self_check(
                state,
                runner,
                variables,
            )
            variables.update(consistency)

        consistency_flag = _strict_consistency_flag(consistency.get(IS_CONSISTENT))
        if consistency_flag is True:
            set_runtime_stage(state, "validation", "集数一致性检查通过。", progress_percent=3)
            sync_runtime_state(state)
            return
        if consistency_flag is None:
            raise ConsistencySelfCheckError(
                "集数一致性检查未明确返回 true/false，已停止继续回退 framework。"
            )

        last_error = ValueError(
            f"分集计划与总集数不一致，已回到剧本框架重新生成（第 {attempt}/{total_attempts} 次）。"
        )
        logger.warning("%s", last_error)
        if attempt >= total_attempts:
            break

        _reset_workflow_to_initial_input_state(state, payload, variables)
        set_runtime_stage(
            state,
            "framework",
            f"集数一致性未通过，正在回到剧本框架重新生成大纲（{attempt}/{retry_limit}）。",
            progress_percent=0,
        )
        sync_runtime_state(state)

    _reset_workflow_to_initial_input_state(state, payload, variables)
    final_message = _framework_consistency_terminal_error_message(last_error, total_attempts)
    set_runtime_stage(
        state,
        "framework",
        final_message,
        progress_percent=0,
    )
    sync_runtime_state(state)
    raise ValueError(final_message) from last_error


def _ensure_pre_strategy_outputs(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> None:
    """在 world-building 之前补齐服装/别名等前置策略，避免后续阶段吃到旧设定。"""
    cached_errors = _pre_strategy_output_integrity_errors(variables)
    if not cached_errors:
        _apply_pre_strategy_outputs_to_variables(variables)
        _refresh_user_content_baseline(payload, variables)
        set_runtime_stage(
            state,
            "appearance_strategy",
            "已从缓存恢复服装前置策略。",
            progress_percent=6,
        )
        _sync_state_variables(state, variables)
        return

    if any(_has_value(variables.get(name)) for name in PRE_STRATEGY_RUNTIME_FIELDS):
        logger.warning(
            "恢复到的服装前置策略缓存无效，将清空旧值后重新生成：%s",
            "；".join(cached_errors),
        )
    # 这里先清空旧缓存，再重跑 appearance_pre_strategy。
    # 否则一旦本轮只回了部分字段，旧残值可能和新结果拼出一个“假完整”的 payload。
    for field_name in PRE_STRATEGY_RUNTIME_FIELDS:
        variables.pop(field_name, None)

    pre_strategy_output = _run_fastgpt_stage(
        state,
        runner,
        STAGE_APPEARANCE_PRE_STRATEGY,
        variables,
        stage_key="appearance_strategy",
        message="正在生成服装前置策略。",
        progress_percent=6,
        max_retries=0,
    )
    variables.update(pre_strategy_output)
    if not _apply_pre_strategy_outputs_to_variables(variables):
        errors = _pre_strategy_output_integrity_errors(variables)
        raise ValueError(
            "服装前置策略阶段返回内容不可用："
            + ("；".join(errors) if errors else "未返回合法字段")
        )
    _refresh_user_content_baseline(payload, variables)
    _sync_state_variables(state, variables)


def _ensure_framework_outputs(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
    *,
    resume_snapshot_present: bool,
) -> None:
    cached_errors = _framework_output_integrity_errors(payload, variables)
    if cached_errors and resume_snapshot_present:
        logger.warning(
            "恢复到的剧本框架缓存无效，将丢弃旧缓存并回退到原始输入重跑 framework：%s",
            "；".join(cached_errors),
        )
        _reset_workflow_to_initial_input_state(state, payload, variables)

    if _has_framework_outputs(payload, variables):
        _apply_framework_outputs_to_variables(payload, variables)
        set_runtime_stage(
            state,
            "framework",
            "已从缓存恢复剧本框架。",
            progress_percent=4,
        )
        return

    retry_limit = max(0, _safe_int(variables.get(MAX_RETRIES), settings.max_retries_default))
    total_attempts = 1 + retry_limit
    last_error: Exception | None = None

    for attempt in range(1, total_attempts + 1):
        _reset_workflow_to_initial_input_state(state, payload, variables)
        try:
            framework_output = _run_fastgpt_stage(
                state,
                runner,
                STAGE_FRAMEWORK,
                variables,
                stage_key="framework",
                message="正在撰写剧本框架。",
                progress_percent=4,
                max_retries=0,
            )
            framework_errors = _framework_output_integrity_errors(payload, framework_output)
            if framework_errors:
                raise FrameworkOutputValidationError(framework_errors)
        except FrameworkOutputValidationError as exc:
            last_error = exc
            logger.warning(
                "剧本框架第 %s/%s 次完整性校验失败：%s",
                attempt,
                total_attempts,
                exc,
            )
            if attempt >= total_attempts:
                break
            set_runtime_stage(
                state,
                "framework",
                f"剧本框架输出不完整，正在自动重试（{attempt}/{retry_limit}）。",
                progress_percent=4,
            )
            sync_runtime_state(state)
            continue
        except Exception as exc:
            last_error = exc
            logger.warning(
                "剧本框架第 %s/%s 次执行失败：%s",
                attempt,
                total_attempts,
                exc,
            )
            if _is_non_retryable(exc) or attempt >= total_attempts:
                break
            set_runtime_stage(
                state,
                "framework",
                f"剧本框架生成失败，正在自动重试（{attempt}/{retry_limit}）。",
                progress_percent=4,
            )
            sync_runtime_state(state)
            continue

        variables.update(framework_output)
        if not _apply_framework_outputs_to_variables(payload, variables):
            last_error = FrameworkOutputValidationError(
                _framework_output_integrity_errors(payload, framework_output)
            )
            if attempt >= total_attempts:
                break
            set_runtime_stage(
                state,
                "framework",
                f"剧本框架输出不完整，正在自动重试（{attempt}/{retry_limit}）。",
                progress_percent=4,
            )
            sync_runtime_state(state)
            continue
        return

    _reset_workflow_to_initial_input_state(state, payload, variables)
    final_message = _framework_terminal_error_message(last_error)
    set_runtime_stage(
        state,
        "framework",
        final_message,
        progress_percent=0,
    )
    sync_runtime_state(state)
    raise ValueError(final_message) from last_error


def _run_consistency_stage_with_self_check(
    state: WorkflowState,
    runner: FastGPTRunner,
    variables: dict[str, Any],
) -> dict[str, Any]:
    """一致性工作流只允许 true/false。

    如果模型夹带解释文本或输出了其它同义词，这里先在 consistency 阶段内部自检重跑，
    而不是误判成 false 后直接打回 framework。
    """
    last_error: Exception | None = None
    for check_attempt in range(1, CONSISTENCY_SELF_CHECK_ATTEMPTS + 1):
        if check_attempt > 1:
            reminder = (
                "集数一致性检查未明确返回 true/false，"
                f"正在重新自检（{check_attempt}/{CONSISTENCY_SELF_CHECK_ATTEMPTS}）。"
            )
            set_runtime_stage(
                state,
                "validation",
                reminder,
                progress_percent=2,
            )
            sync_runtime_state(state)
            logger.warning("%s", reminder)

        variables.pop(IS_CONSISTENT, None)
        try:
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
        except Exception as exc:
            last_error = exc
            if not _is_consistency_self_check_retryable_error(exc):
                raise
            if check_attempt >= CONSISTENCY_SELF_CHECK_ATTEMPTS:
                break
            continue

        consistency_flag = _strict_consistency_flag(consistency.get(IS_CONSISTENT))
        if consistency_flag is not None:
            consistency[IS_CONSISTENT] = consistency_flag
            return consistency

        last_error = ValueError("集数一致性检查未明确返回 true/false。")
        if check_attempt >= CONSISTENCY_SELF_CHECK_ATTEMPTS:
            break

    details = str(last_error) if last_error is not None else "未返回任何可识别结果"
    raise ConsistencySelfCheckError(
        "集数一致性检查未明确返回 true/false，"
        f"已在当前阶段重新自检 {CONSISTENCY_SELF_CHECK_ATTEMPTS} 次仍失败：{details}"
    ) from last_error


def _reset_workflow_to_initial_input_state(
    state: WorkflowState,
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> None:
    """在 framework/consistency 重试前清空本轮临时状态，回到用户原始输入起点。"""
    variables.clear()
    variables.update(_initial_fastgpt_variables(payload))
    state.variables.clear()
    state.node_outputs.clear()
    state.final_output_text = ""
    state.halted_message = None
    _sync_state_variables(state, variables)


def _has_framework_outputs(
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> bool:
    return not _framework_output_integrity_errors(payload, variables)


def _framework_output_integrity_errors(
    payload: WorkflowInput,
    values: Any,
) -> list[str]:
    """对 framework 成品做代码级验收，拦住空字段、过短文本和分集计划缺集。"""
    if not isinstance(values, dict):
        return [f"framework 阶段返回值不是对象：{type(values).__name__}"]
    framework_values = _framework_output_snapshot(payload, values)
    errors: list[str] = []
    min_lengths = {
        SCRIPT_TITLE: FRAMEWORK_TITLE_MIN_LENGTH,
        STORY_OUTLINE: FRAMEWORK_TEXT_MIN_LENGTH,
        USER_CHARACTERS: FRAMEWORK_TEXT_MIN_LENGTH,
        USER_SCENES: FRAMEWORK_TEXT_MIN_LENGTH,
        EPISODE_PLAN: FRAMEWORK_TEXT_MIN_LENGTH,
    }

    for field_name, min_length in min_lengths.items():
        text = str(framework_values.get(field_name) or "").strip()
        if not text:
            errors.append(f"{field_name} 缺失")
            continue
        if len(text) < min_length:
            errors.append(
                f"{field_name} 过短（当前 {len(text)} 字，至少 {min_length} 字）"
            )

    episode_plan_issue = _framework_episode_plan_integrity_issue(
        framework_values.get(EPISODE_PLAN),
        payload.total_episodes,
    )
    if episode_plan_issue:
        errors.append(episode_plan_issue)
    return errors


def _serialize_framework_runtime_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            return str(value).strip()
    return str(value).strip()


def _truncate_log_text(text: Any, *, max_chars: int = 500) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars]}..."


def _framework_output_snapshot(
    payload: WorkflowInput,
    values: Any,
) -> dict[str, str]:
    """只抽出 framework 这一步真正要交给后续阶段的 5 个正式字段。"""
    if not isinstance(values, dict):
        return {
            SCRIPT_TITLE: "",
            STORY_OUTLINE: "",
            USER_CHARACTERS: "",
            USER_SCENES: "",
            EPISODE_PLAN: "",
        }
    return {
        SCRIPT_TITLE: _serialize_framework_runtime_value(
            values.get(SCRIPT_TITLE) or values.get("script_title")
        ),
        # framework 现在已经改成返回 object/array；这里仍统一序列化成字符串，
        # 是为了不惊动后面的 legacy 工作流、缓存快照和导出逻辑。
        STORY_OUTLINE: _serialize_framework_runtime_value(values.get(STORY_OUTLINE)),
        USER_CHARACTERS: _serialize_framework_runtime_value(values.get(USER_CHARACTERS)),
        USER_SCENES: _serialize_framework_runtime_value(values.get(USER_SCENES)),
        EPISODE_PLAN: _select_complete_framework_episode_plan_source(payload, values),
    }


def _build_framework_naturalize_source(
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> str:
    framework_snapshot = _framework_output_snapshot(payload, variables)
    structured_payload = {
        SCRIPT_TITLE: str(variables.get(SCRIPT_TITLE) or framework_snapshot.get(SCRIPT_TITLE) or "").strip(),
        STORY_OUTLINE: _framework_naturalize_structured_value(variables.get(STORY_OUTLINE)),
        USER_CHARACTERS: _framework_naturalize_structured_value(variables.get(USER_CHARACTERS)),
        USER_SCENES: _framework_naturalize_structured_value(variables.get(USER_SCENES)),
        EPISODE_PLAN: _framework_naturalize_structured_value(
            variables.get(EPISODE_PLAN) or framework_snapshot.get(EPISODE_PLAN)
        ),
    }
    return json.dumps(structured_payload, ensure_ascii=False, indent=2)


def _build_worldview_naturalize_source(variables: dict[str, Any]) -> str:
    worldview_value = variables.get(WORLDVIEW)
    if isinstance(worldview_value, str):
        text = worldview_value.strip()
        if text:
            try:
                worldview_value = parse_json(text)
            except Exception:
                return text
    if worldview_value in (None, ""):
        return ""
    try:
        return json.dumps(worldview_value, ensure_ascii=False, indent=2)
    except Exception:
        return str(worldview_value).strip()


def _build_character_naturalize_source(variables: dict[str, Any]) -> str:
    return build_character_unstructured_source(
        variables,
        extra_candidates=(variables.get(USER_CHARACTERS), variables.get(CHARACTER_BIOS_VAR)),
    )


def _character_items_from_value(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    from ..services.task_manager_common import _character_items_from_value as _impl

    return _impl(*args, **kwargs)


def _character_name_from_item(*args: Any, **kwargs: Any) -> str:
    from ..services.task_manager_common import _character_name_from_item as _impl

    return _impl(*args, **kwargs)


def _meaningful_character_fragment(*args: Any, **kwargs: Any) -> str:
    from ..services.task_manager_common import _meaningful_character_fragment as _impl

    return _impl(*args, **kwargs)


def _character_structured_fallback_text(value: Any) -> str:
    characters = _character_items_from_value(value)
    if not characters:
        return ""

    sections: list[str] = []
    for item in characters:
        name = _character_name_from_item(item)
        role = _meaningful_character_fragment(
            item.get("story_role") or item.get("role_type") or item.get("identity")
        )
        personality = _meaningful_character_fragment(
            item.get("personality") or item.get("speech_profile")
        )
        desire = _meaningful_character_fragment(
            item.get("core_desire") or item.get("core_motivation") or item.get("deep_motivation")
        )
        relationship = _meaningful_character_fragment(
            item.get("relationship_to_protagonist")
            or item.get("relationships_with_others")
            or item.get("relationships")
            or item.get("relation_modes")
        )
        growth = _meaningful_character_fragment(
            item.get("growth_arc") or item.get("plot_function") or item.get("dramatic_value")
        )
        appearance = _meaningful_character_fragment(
            item.get("appearance_anchor")
            or item.get("appearance")
            or item.get("appearance_description")
        )

        fragments: list[str] = []
        if role:
            fragments.append(f"是故事中的{role}")
        if personality:
            fragments.append(f"性格上{personality}")
        if desire:
            fragments.append(f"内在驱动力集中在{desire}")
        if relationship:
            fragments.append(f"与其他角色的关系重点在于{relationship}")
        if growth:
            fragments.append(f"人物成长会落在{growth}")
        if appearance:
            fragments.append(f"视觉辨识点则是{appearance}")

        if not name:
            continue
        if fragments:
            sections.append(f"{name}：" + "，".join(fragments).strip("，") + "。")
        else:
            sections.append(name)

    return "\n".join(section for section in sections if section).strip()


def _framework_naturalize_structured_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = parse_json(text)
    except Exception:
        return text
    return copy.deepcopy(parsed)


def _ensure_framework_natural_language(
    state: WorkflowState,
    runner: FastGPTRunner,
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> None:
    if is_meaningful_text(variables.get(FRAMEWORK_NATURAL_LANGUAGE)):
        set_runtime_stage(
            state,
            "framework",
            "已从缓存恢复剧本框架自然语言版。",
            progress_percent=5,
        )
        return

    stage_variables = build_unstructured_stage_variables(
        _build_framework_naturalize_source(payload, variables),
        stage_name=STAGE_FRAMEWORK_NATURALIZE,
        source_stage=STAGE_FRAMEWORK,
        variables=variables,
    )
    output = run_stage_with_contract_guard(
        state,
        runner,
        STAGE_FRAMEWORK_NATURALIZE,
        stage_variables,
        stage_key="framework",
        message="正在整理剧本框架自然语言说明。",
        progress_percent=5,
        output_field=FRAMEWORK_NATURAL_LANGUAGE,
        sync_output_to_state=False,
    )
    variables.update(output)
    naturalized = extract_unstructured_stage_output_text(
        output,
        output_field=FRAMEWORK_NATURAL_LANGUAGE,
    )
    if naturalized:
        variables[FRAMEWORK_NATURAL_LANGUAGE] = naturalized


def _ensure_worldview_natural_language(
    state: WorkflowState,
    runner: FastGPTRunner,
    variables: dict[str, Any],
) -> None:
    if is_meaningful_text(variables.get(WORLDVIEW_NATURAL_LANGUAGE)):
        set_runtime_stage(
            state,
            "worldview",
            "已从缓存恢复世界观自然语言版。",
            progress_percent=18,
        )
        sync_runtime_state(state)
        return

    source = _build_worldview_naturalize_source(variables)
    if not source:
        return

    stage_variables = build_unstructured_stage_variables(
        source,
        stage_name=STAGE_WORLDVIEW_NATURALIZE,
        source_stage=STAGE_WORLDVIEW,
        variables=variables,
    )
    output = run_stage_with_contract_guard(
        state,
        runner,
        STAGE_WORLDVIEW_NATURALIZE,
        stage_variables,
        stage_key="worldview",
        message="正在整理世界观自然语言说明。",
        progress_percent=18,
        output_field=WORLDVIEW_NATURAL_LANGUAGE,
        sync_output_to_state=False,
    )
    variables.update(output)
    naturalized = extract_unstructured_stage_output_text(
        output,
        output_field=WORLDVIEW_NATURAL_LANGUAGE,
    )
    if naturalized:
        variables[WORLDVIEW_NATURAL_LANGUAGE] = naturalized


def _ensure_character_natural_language(
    state: WorkflowState,
    runner: FastGPTRunner,
    variables: dict[str, Any],
) -> None:
    if not (
        has_meaningful_content(variables.get(CHARACTERS))
        or has_meaningful_content(variables.get(USER_CHARACTERS))
        or has_meaningful_content(variables.get(CHARACTER_BIOS_VAR))
    ):
        return
    fallback_text = _character_structured_fallback_text(
        variables.get(CHARACTERS) or variables.get(CHARACTER_VAR)
    )
    if not fallback_text:
        fallback_text = clean_multiline_character_text(
            variables.get(USER_CHARACTERS) or variables.get(CHARACTER_BIOS_VAR)
        ).strip()
    if (
        character_natural_text_is_usable(variables.get(CHARACTER_NATURAL_LANGUAGE_VAR))
        and bool(variables.get(CHARACTER_NATURALIZE_READY_FLAG))
    ):
        set_runtime_stage(
            state,
            "character",
            "已从缓存恢复人物小传自然语言版。",
            progress_percent=26,
        )
        sync_runtime_state(state)
        return

    source = _build_character_naturalize_source(variables)
    if not source:
        if character_natural_text_is_usable(fallback_text):
            variables[CHARACTER_NATURAL_LANGUAGE_VAR] = fallback_text
            state.set_var(CHARACTER_NATURAL_LANGUAGE_VAR, fallback_text)
        variables[CHARACTER_NATURALIZE_READY_FLAG] = True
        state.set_var(CHARACTER_NATURALIZE_READY_FLAG, True)
        return

    stage_variables = build_unstructured_stage_variables(
        source,
        stage_name=STAGE_CHARACTERS_NATURALIZE,
        source_stage=STAGE_CHARACTERS,
        variables=variables,
    )
    naturalized = ""
    try:
        output = run_stage_with_contract_guard(
            state,
            runner,
            STAGE_CHARACTERS_NATURALIZE,
            stage_variables,
            stage_key="character",
            message="正在整理人物小传自然语言说明。",
            progress_percent=26,
            output_field=CHARACTER_NATURAL_LANGUAGE_VAR,
            sync_output_to_state=False,
        )
        naturalized = extract_unstructured_stage_output_text(
            output,
            output_field=CHARACTER_NATURAL_LANGUAGE_VAR,
            text_cleaner=clean_multiline_character_text,
            text_is_usable=character_natural_text_is_usable,
        )
    except Exception as exc:
        logger.warning(
            "人物小传自然语言化失败，改用结构化人设本地兜底：%s",
            str(exc),
        )
    if not character_natural_text_is_usable(naturalized):
        naturalized = fallback_text
    naturalized = clean_multiline_character_text(naturalized)
    if character_natural_text_is_usable(naturalized):
        variables[CHARACTER_NATURAL_LANGUAGE_VAR] = naturalized
        state.set_var(CHARACTER_NATURAL_LANGUAGE_VAR, naturalized)
    variables[CHARACTER_NATURALIZE_READY_FLAG] = True
    state.set_var(CHARACTER_NATURALIZE_READY_FLAG, True)


def _select_complete_framework_episode_plan_source(
    payload: WorkflowInput,
    values: dict[str, Any],
) -> str:
    """从 framework 相关变量里挑出完整分集计划母本，避免误吃局部批次结果。"""
    canonical = _serialize_framework_runtime_value(values.get(EPISODE_PLAN))
    raw_source = _serialize_framework_runtime_value(values.get(LOCAL_RAW_EPISODE_PLAN))
    for candidate in (raw_source, canonical):
        if _episode_plan_covers_total_episodes(candidate, payload.total_episodes):
            return candidate
    return canonical or raw_source


def _framework_episode_plan_integrity_issue(
    value: Any,
    total_episodes: int,
) -> str | None:
    """检查 framework 产出的分集计划是否真的覆盖到第 1-total_episodes 集。"""
    text = _serialize_framework_runtime_value(value)
    if not text:
        return "episode_plan 缺失"

    episode_numbers = _extract_complete_episode_numbers_from_plan(text)
    if not episode_numbers:
        return f"episode_plan 未识别到第 1-{int(total_episodes or 0)} 集的有效覆盖"

    max_episode = int(total_episodes or 0)
    if max_episode <= 0:
        return None

    episode_set = set(episode_numbers)
    missing = [episode for episode in range(1, max_episode + 1) if episode not in episode_set]
    extras = [episode for episode in episode_numbers if episode > max_episode]
    if not missing and not extras and episode_numbers[0] == 1 and episode_numbers[-1] == max_episode:
        return None

    details: list[str] = [f"当前识别到 {_format_episode_ranges(episode_numbers)}"]
    if missing:
        details.append(f"缺少 {_format_episode_ranges(missing)}")
    if extras:
        details.append(f"超出总集数的有 {_format_episode_ranges(extras)}")
    return f"episode_plan 未完整覆盖 1-{max_episode} 集（{'；'.join(details)}）"


def _episode_plan_covers_total_episodes(value: Any, total_episodes: int) -> bool:
    return _framework_episode_plan_integrity_issue(value, total_episodes) is None


def _extract_complete_episode_numbers_from_plan(value: Any) -> list[int]:
    normalized = _normalize_episode_plan_object(value)
    if normalized is not None:
        episode_numbers = _extract_batch_episode_numbers_from_plan(normalized)
        return sorted({episode for episode in episode_numbers if episode > 0})

    text = str(value or "").strip()
    if not text:
        return []

    seen: set[int] = set()
    numbers: list[int] = []
    for match in re.finditer(
        r"第\s*([0-9零〇一二两三四五六七八九十百千]+)\s*[集话回章]",
        text,
        re.MULTILINE,
    ):
        raw = str(match.group(1) or "").strip()
        episode_number = int(raw) if raw.isdigit() else _parse_chinese_number(raw)
        if episode_number is None or episode_number in seen:
            continue
        seen.add(episode_number)
        numbers.append(episode_number)

    if numbers:
        return sorted(numbers)

    for line in text.splitlines():
        episode_number = _extract_episode_number(line)
        if episode_number is None or episode_number in seen:
            continue
        seen.add(episode_number)
        numbers.append(episode_number)
    return sorted(numbers)


def _format_episode_ranges(numbers: list[int]) -> str:
    normalized = sorted({int(number) for number in numbers if int(number) > 0})
    if not normalized:
        return "无有效集数"

    ranges: list[str] = []
    start = normalized[0]
    end = normalized[0]
    for episode in normalized[1:]:
        if episode == end + 1:
            end = episode
            continue
        ranges.append(_format_episode_range(start, end))
        start = episode
        end = episode
    ranges.append(_format_episode_range(start, end))
    return "第 " + "、".join(ranges) + " 集"


def _format_episode_range(start: int, end: int) -> str:
    if start == end:
        return str(start)
    return f"{start}-{end}"


def _format_framework_validation_errors(errors: list[str]) -> str:
    if not errors:
        return "剧本框架输出无效。"
    return "剧本框架输出无效：" + "；".join(errors)


def _framework_terminal_error_message(last_error: Exception | None) -> str:
    if isinstance(last_error, FrameworkOutputValidationError):
        return str(last_error)
    if last_error is None:
        return "剧本框架输出无效。"
    return f"剧本框架生成失败：{last_error}"


def _framework_consistency_terminal_error_message(
    last_error: Exception | None,
    total_attempts: int,
) -> str:
    if last_error is None:
        return "分集计划与总集数一致性校验失败，且未能回退到剧本框架完成重生。"
    if isinstance(last_error, FrameworkOutputValidationError):
        return str(last_error)
    return (
        f"分集计划与总集数一致性校验连续失败，已回到剧本框架重生 {total_attempts} 次仍未通过："
        f"{last_error}"
    )


def _has_pre_strategy_outputs(variables: dict[str, Any]) -> bool:
    return not _pre_strategy_output_integrity_errors(variables)


def _serialize_pre_strategy_runtime_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            return str(value).strip()
    return str(value).strip()


def _pre_strategy_output_snapshot(values: Any) -> dict[str, str]:
    """把服装前置策略统一收敛成三个稳定字符串，避免恢复时混入 dict/list 原样值。"""
    if not isinstance(values, dict):
        return {field_name: "" for field_name in PRE_STRATEGY_RUNTIME_FIELDS}
    return {
        field_name: _serialize_pre_strategy_runtime_value(values.get(field_name))
        for field_name in PRE_STRATEGY_RUNTIME_FIELDS
    }


def _pre_strategy_output_integrity_errors(values: Any) -> list[str]:
    if not isinstance(values, dict):
        return [f"appearance_pre_strategy 阶段返回值不是对象：{type(values).__name__}"]

    snapshot = _pre_strategy_output_snapshot(values)
    errors: list[str] = []
    for field_name, text in snapshot.items():
        if not text:
            errors.append(f"{field_name} 缺失")
            continue
        try:
            parsed = json.loads(text)
        except Exception:
            continue
        # 纯文本规则允许直接透传；但如果已经是结构化 JSON，就不能让空 dict/list/null
        # 混进缓存，否则后面的 baseline 和导出会把“空策略”当成有效策略复用。
        if parsed is None:
            errors.append(f"{field_name} 为空")
            continue
        if isinstance(parsed, str) and not parsed.strip():
            errors.append(f"{field_name} 为空字符串")
            continue
        if isinstance(parsed, (dict, list)) and not parsed:
            errors.append(f"{field_name} 为空结构")
    return errors


def _apply_pre_strategy_outputs_to_variables(variables: dict[str, Any]) -> bool:
    """在进入后续阶段前，把服装前置策略固定成字符串，保证缓存恢复和后续拼接口径一致。"""
    if not _has_pre_strategy_outputs(variables):
        return False

    for field_name, text in _pre_strategy_output_snapshot(variables).items():
        variables[field_name] = text
    return True


def _apply_framework_outputs_to_variables(
    payload: WorkflowInput,
    variables: dict[str, Any],
) -> bool:
    """把 framework 成品正式回写到运行态变量，供后面的策略、校验和批处理继续使用。"""
    if not _has_framework_outputs(payload, variables):
        return False

    framework_values = _framework_output_snapshot(payload, variables)
    script_title = framework_values[SCRIPT_TITLE]
    story_outline = framework_values[STORY_OUTLINE]
    user_characters = framework_values[USER_CHARACTERS]
    user_scenes = framework_values[USER_SCENES]
    episode_plan = framework_values[EPISODE_PLAN]

    variables[SCRIPT_TITLE] = script_title
    variables[STORY_OUTLINE] = story_outline
    variables[USER_CHARACTERS] = user_characters
    variables[USER_SCENES] = user_scenes
    variables[EPISODE_PLAN] = episode_plan
    if episode_plan:
        variables[LOCAL_RAW_EPISODE_PLAN] = episode_plan
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
    # appearance_mapping 是 FastGPT 给出的“原始服装/别名母本”；
    # 本地会继续拆成 registry / alias plan / continuity memory，目的是让后续批处理
    # 直接消费稳定结构，而不是每个阶段都重新自己理解一遍大 JSON。
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
    normalized_candidate = normalize_appearance_mapping_candidate(value)
    candidate = normalized_candidate if isinstance(normalized_candidate, dict) else value
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
                    "must_use_when_triggered": (
                        variant.get("must_use_when_triggered")
                        if isinstance(variant.get("must_use_when_triggered"), bool)
                        else True
                    ),
                    "fallback_allowed": (
                        variant.get("fallback_allowed")
                        if isinstance(variant.get("fallback_allowed"), bool)
                        else False
                    ),
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
    return f"{base}({note})"


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
    if isinstance(candidate.get("scenes"), dict) and isinstance(
        candidate["scenes"].get("scene_setting"),
        dict,
    ):
        setting = candidate["scenes"]["scene_setting"]
    else:
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
    """从逐集 alias 计划里切出当前批次，让命名规则跟着批次一起走。"""
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
    """承接上一批外观记忆，预演本批角色该沿用哪些 alias 和服装状态。"""
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


def _remove_batch_window_from_object(value: Any, batch: BatchWindow) -> dict[str, Any]:
    payload = _dict_or_empty(value)
    if not payload:
        return {}
    trimmed = copy.deepcopy(payload)
    list_key = _batch_object_episode_list_key(trimmed)
    if not list_key:
        return trimmed
    items = trimmed.get(list_key)
    if not isinstance(items, list):
        return trimmed
    trimmed[list_key] = [
        copy.deepcopy(item)
        for item in items
        if not (
            isinstance(item, dict)
            and batch.start_episode <= _safe_int(item.get("episode"), 0) <= batch.end_episode
        )
    ]
    return trimmed


def merge_batch_hooks(all_hooks: Any, batch_hooks: Any, batch: BatchWindow) -> dict[str, Any]:
    issues = validate_batch_hooks(batch_hooks, batch)
    if issues:
        raise ValueError("hook batch validation failed: " + "; ".join(issues))
    current = _remove_batch_window_from_object(all_hooks, batch)
    payload = _normalize_batch_hooks_payload(batch_hooks) or {}
    merged = merge_batch_object(current, payload)
    _assert_no_duplicate_object_episodes(merged, "ALL_HOOKS")
    return merged


def merge_batch_dialogues(all_dialogues: Any, batch_dialogues: Any, batch: BatchWindow) -> dict[str, Any]:
    issues = validate_batch_dialogues(batch_dialogues, batch)
    if issues:
        raise ValueError("dialogue batch validation failed: " + "; ".join(issues))
    current = _remove_batch_window_from_object(all_dialogues, batch)
    payload = _normalize_batch_dialogues_payload(batch_dialogues) or {}
    merged = merge_batch_object(current, payload)
    _assert_no_duplicate_object_episodes(merged, "ALL_DIALOGUES")
    return merged


def merge_batch_script(all_script: Any, batch_script: Any, batch: BatchWindow) -> str:
    issues = validate_batch_script_text(batch_script, batch)
    if issues:
        raise ValueError("script batch validation failed: " + "; ".join(issues))
    current_text = str(all_script or "").strip()
    full_window = BatchWindow(start_episode=1, end_episode=max(batch.end_episode, 1))
    existing_map = _extract_script_episode_map(current_text, full_window) if current_text else {}
    existing_map.update(_extract_script_episode_map(str(batch_script or ""), batch))
    return _join_script_episode_map(existing_map)


def assert_complete_hooks(all_hooks: Any, total_episodes: int) -> None:
    _assert_complete_object_phase(
        all_hooks,
        total_episodes,
        stage_label="ALL_HOOKS",
        list_key="episodes",
    )


def assert_complete_dialogues(all_dialogues: Any, total_episodes: int) -> None:
    _assert_complete_object_phase(
        all_dialogues,
        total_episodes,
        stage_label="ALL_DIALOGUES",
        list_key="episode_dialogue_blocks",
    )


def assert_complete_script(all_script: Any, total_episodes: int) -> None:
    text = str(all_script or "").strip()
    if not text:
        raise ValueError("ALL_SCRIPT is empty")
    episode_map = _extract_script_episode_map(
        text,
        BatchWindow(start_episode=1, end_episode=max(1, int(total_episodes))),
    )
    expected = list(range(1, int(total_episodes) + 1))
    found = sorted(episode_map)
    duplicates = _duplicate_episode_numbers(__extract_script_episode_sequence(text))
    if duplicates:
        raise ValueError(f"ALL_SCRIPT has duplicate episodes: {_format_episode_ranges(duplicates)}")
    missing = [episode for episode in expected if episode not in set(found)]
    if missing:
        raise ValueError(f"ALL_SCRIPT is missing episodes: {_format_episode_ranges(missing)}")
    out_of_range = [episode for episode in found if episode not in set(expected)]
    if out_of_range:
        raise ValueError(f"ALL_SCRIPT has out-of-range episodes: {_format_episode_ranges(out_of_range)}")


def _assert_no_duplicate_object_episodes(value: Any, stage_label: str) -> None:
    numbers = _batch_object_episode_numbers(value)
    duplicates = _duplicate_episode_numbers(numbers)
    if duplicates:
        raise ValueError(f"{stage_label} has duplicate episodes: {_format_episode_ranges(duplicates)}")


def _assert_complete_object_phase(
    value: Any,
    total_episodes: int,
    *,
    stage_label: str,
    list_key: str,
) -> None:
    payload = _dict_or_empty(value)
    items = payload.get(list_key)
    if not isinstance(items, list):
        raise ValueError(f"{stage_label} is not a complete batched object")
    numbers = [
        _safe_int(item.get("episode"), 0)
        for item in items
        if isinstance(item, dict)
    ]
    duplicates = _duplicate_episode_numbers(numbers)
    if duplicates:
        raise ValueError(f"{stage_label} has duplicate episodes: {_format_episode_ranges(duplicates)}")
    expected = list(range(1, int(total_episodes) + 1))
    out_of_range = sorted({episode for episode in numbers if episode not in set(expected)})
    if out_of_range:
        raise ValueError(f"{stage_label} has out-of-range episodes: {_format_episode_ranges(out_of_range)}")
    missing = [episode for episode in expected if episode not in set(numbers)]
    if missing:
        raise ValueError(f"{stage_label} is missing episodes: {_format_episode_ranges(missing)}")


def _has_matching_batch_object_checkpoint(
    value: Any,
    *,
    batch: BatchWindow,
    saved_start_episode: Any,
) -> bool:
    saved_start = _safe_int(saved_start_episode, 0)
    if saved_start > 0 and saved_start != batch.start_episode:
        return False
    payload = _dict_or_empty(value)
    if not payload:
        return False
    return _batch_object_is_reusable(payload, batch)


def _has_matching_batch_script_checkpoint(
    value: Any,
    *,
    batch: BatchWindow,
    saved_start_episode: Any,
) -> bool:
    saved_start = _safe_int(saved_start_episode, 0)
    text = str(value or "").strip()
    if not text:
        return False
    episode_map = _extract_script_episode_map(text, batch)
    expected = list(range(batch.start_episode, batch.end_episode + 1))
    if saved_start > 0 and saved_start != batch.start_episode:
        return False
    return (
        bool(episode_map)
        and sorted(episode_map) == expected
        and not _validate_script_batch_output(text, batch=batch)
    )


def _current_batch_object_payload(
    current_value: Any,
    aggregate_value: Any,
    *,
    batch: BatchWindow,
) -> dict[str, Any]:
    """恢复已完成批次时只信任正式全量缓存，不信任瞬时 current batch 临时值。"""
    del current_value
    return slice_object_episodes_for_batch(aggregate_value, batch)


def _batch_object_covers_window(value: Any, batch: BatchWindow) -> bool:
    payload = _dict_or_empty(value)
    if not payload:
        return False

    batch_meta = payload.get("batch_meta")
    if isinstance(batch_meta, dict):
        meta_start = _safe_int(batch_meta.get("start_episode"), 0)
        meta_end = _safe_int(batch_meta.get("end_episode"), 0)
        if meta_start == batch.start_episode and meta_end == batch.end_episode:
            return True

    list_key = _batch_object_episode_list_key(payload)
    if not list_key:
        return False

    episode_numbers: list[int] = []
    for item in payload.get(list_key) or []:
        if not isinstance(item, dict):
            continue
        episode_no = _safe_int(item.get("episode"), 0)
        if batch.start_episode <= episode_no <= batch.end_episode:
            episode_numbers.append(episode_no)

    if not episode_numbers:
        return False

    expected = list(range(batch.start_episode, batch.end_episode + 1))
    return sorted(dict.fromkeys(episode_numbers)) == expected


def _ensure_batch_object_matches(
    value: Any,
    *,
    batch: BatchWindow,
    stage_label: str,
    field_label: str,
) -> None:
    issues = _batch_object_reuse_issues(value, batch)
    if not issues:
        logger.info(
            "%s %s 集输入校验通过：%s覆盖当前批次。",
            stage_label,
            batch.label,
            field_label,
        )
        return
    raise ValueError(
        f"{stage_label} {batch.label} 集输入异常：{field_label}未正确覆盖当前批次。"
        f" {'; '.join(issues[:2])}"
    )


def _ensure_plan_matches_batch(
    plan_payload: Any,
    *,
    batch: BatchWindow,
    stage_label: str,
) -> None:
    """校验当前批分集计划是否真的只覆盖了本批，避免 1-5 和 6-10 串批。"""
    episode_numbers = _extract_batch_episode_numbers_from_plan(plan_payload)
    if not episode_numbers:
        logger.warning(
            "%s %s 集分集计划未能解析为结构化集数，将继续沿用原始文本。",
            stage_label,
            batch.label,
        )
        return
    expected = list(range(batch.start_episode, batch.end_episode + 1))
    if episode_numbers == expected:
        logger.info(
            "%s %s 集输入校验通过：分集计划范围=%s-%s。",
            stage_label,
            batch.label,
            episode_numbers[0],
            episode_numbers[-1],
        )
        return
    raise ValueError(
        f"{stage_label} {batch.label} 集输入异常：分集计划范围={episode_numbers}，期望={expected}。"
    )


def _extract_batch_episode_numbers_from_plan(plan_payload: Any) -> list[int]:
    normalized = _normalize_episode_plan_object(plan_payload)
    if not normalized:
        return []
    episode_numbers = [
        _safe_int(item.get("episode"), 0)
        for item in normalized.get("episodes", [])
        if isinstance(item, dict)
    ]
    return [episode for episode in episode_numbers if episode > 0]


def _batch_object_episode_list_key(payload: dict[str, Any]) -> str | None:
    for key in ("episodes", "episode_dialogue_blocks"):
        if isinstance(payload.get(key), list):
            return key
    return None


def _batch_object_episode_numbers(value: Any) -> list[int]:
    payload = _dict_or_empty(value)
    if not payload:
        return []
    list_key = _batch_object_episode_list_key(payload)
    if not list_key:
        return []
    items = payload.get(list_key)
    if not isinstance(items, list):
        return []
    episode_numbers = [
        _safe_int(item.get("episode"), 0)
        for item in items
        if isinstance(item, dict)
    ]
    return [episode for episode in episode_numbers if episode > 0]


def slice_object_episodes_for_batch(value: Any, batch: BatchWindow) -> dict[str, Any]:
    """把 hooks / dialogues 这类按集对象切成当前批窗口，供下游阶段直接消费。"""
    payload = _dict_or_empty(value)
    if not payload:
        return {}
    list_key = _batch_object_episode_list_key(payload)
    if not list_key:
        return copy.deepcopy(payload)
    selected = []
    for item in payload.get(list_key) or []:
        if not isinstance(item, dict):
            continue
        episode_no = _safe_int(item.get("episode"), 0)
        if batch.start_episode <= episode_no <= batch.end_episode:
            selected.append(copy.deepcopy(item))
    if not selected:
        return {}
    sliced = copy.deepcopy(payload)
    sliced[list_key] = selected
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


def _apply_batch_episode_plan_context(
    target: dict[str, Any],
    *,
    plan_for_batch: str,
    normalized_plan_for_batch: dict[str, Any] | None,
) -> None:
    target[EPISODE_PLAN] = plan_for_batch
    if normalized_plan_for_batch is None:
        target.pop(NORMALIZED_EPISODE_PLAN, None)
        target.pop(EPISODE_PLAN_NORMALIZED_VAR, None)
        return
    target[NORMALIZED_EPISODE_PLAN] = copy.deepcopy(normalized_plan_for_batch)
    target[EPISODE_PLAN_NORMALIZED_VAR] = _serialize_normalized_episode_plan(
        normalized_plan_for_batch
    )


def _get_episode_batch_plan_context(
    normalized_plan: Any,
    start_episode: int,
    *,
    batch_size: int,
    raw_episode_plan: str,
) -> tuple[str, dict[str, Any] | None]:
    """给 hooks/dialogues/script 取当前批次专属的分集计划，禁止混入母本全文。"""
    batch_window = BatchWindow(
        start_episode=start_episode,
        end_episode=max(start_episode, start_episode + max(1, batch_size) - 1),
    )
    batch_payload = slice_normalized_episode_plan_for_batch(normalized_plan, batch_window)
    if batch_payload is not None:
        return _serialize_normalized_episode_plan(batch_payload), batch_payload

    fallback_payload = _fallback_normalized_episode_plan_for_batch(raw_episode_plan, batch_window)
    if fallback_payload is not None:
        logger.warning(
            "当前批次 %s-%s 未能从规范化分集计划中切出内容，已改用原始分集计划重建结构化批次。",
            batch_window.start_episode,
            batch_window.end_episode,
        )
        return _serialize_normalized_episode_plan(fallback_payload), fallback_payload

    raw_batch_plan = slice_episode_plan_for_batch(raw_episode_plan, batch_window)
    return raw_batch_plan, _normalize_episode_plan_object(raw_batch_plan)


def get_episode_batch_payload(
    normalized_plan: Any,
    start_episode: int,
    *,
    batch_size: int,
    raw_episode_plan: str,
) -> str:
    """优先从可信的规范化分集计划切本批 JSON；异常时也要尽量回退成当前批的结构化计划。"""
    return _get_episode_batch_plan_context(
        normalized_plan,
        start_episode,
        batch_size=batch_size,
        raw_episode_plan=raw_episode_plan,
    )[0]


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


def _fallback_normalized_episode_plan_for_batch(
    raw_episode_plan: str,
    batch: BatchWindow,
) -> dict[str, Any] | None:
    """当规范化计划缓存失真时，用原始分集计划兜底重建当前批的结构化 JSON。"""
    text = str(raw_episode_plan or "").strip()
    if not text:
        return None

    structured = slice_normalized_episode_plan_for_batch(text, batch)
    if structured is not None:
        # framework 新版本直接把分集计划输出成 JSON 数组；恢复缓存时优先复用这份结构，
        # 避免再退回基于“第X集”标题的文本猜测。
        return structured

    lines = text.splitlines()
    found_marker = False
    current_episode: int | None = None
    current_lines: list[str] = []
    episodes: list[dict[str, Any]] = []

    def flush_current() -> None:
        if current_episode is None:
            return
        if not (batch.start_episode <= current_episode <= batch.end_episode):
            return
        content = "\n".join(current_lines).strip()
        if not content:
            return
        episodes.append(
            {
                "episode": current_episode,
                "title": "",
                "content": content,
                "main_character_aliases": [],
                "appearance_events": [],
                "long_term_stage_flags": [],
                "scene_based_alias_hints": [],
            }
        )

    for line in lines:
        marker = _extract_episode_number(line)
        if marker is not None:
            found_marker = True
            flush_current()
            current_episode = marker
            current_lines = [line]
            continue
        if current_episode is not None:
            current_lines.append(line)

    flush_current()
    if not found_marker or not episodes:
        return None

    return {
        "parsed_episode_count": len(episodes),
        "appearance_alias_planning": {},
        "episodes": episodes,
    }


def _has_normalized_episode_plan(value: Any) -> bool:
    normalized = _normalize_episode_plan_object(value)
    if not isinstance(normalized, dict):
        return False
    episodes = normalized.get("episodes")
    return isinstance(episodes, list) and bool(episodes)


def _normalized_episode_plan_is_trusted(
    value: Any,
    total_episodes: int,
) -> bool:
    """校验规范化分集计划是否仍是“全量计划”，避免旧快照只保留尾批 51-60。"""
    normalized = _normalize_episode_plan_object(value)
    if not _has_normalized_episode_plan(normalized):
        return False
    episode_numbers = _extract_batch_episode_numbers_from_plan(normalized)
    if not episode_numbers:
        return False
    if episode_numbers[0] != 1:
        return False
    if int(total_episodes or 0) > 0 and episode_numbers[-1] != int(total_episodes):
        return False
    return True


def _describe_normalized_episode_plan(value: Any) -> str:
    normalized = _normalize_episode_plan_object(value)
    if not normalized:
        return "empty"
    episode_numbers = _extract_batch_episode_numbers_from_plan(normalized)
    if not episode_numbers:
        return "no-episodes"
    return (
        f"first={episode_numbers[0]}, "
        f"last={episode_numbers[-1]}, "
        f"count={len(episode_numbers)}"
    )


def _serialize_normalized_episode_plan(normalized_plan: dict[str, Any]) -> str:
    return json.dumps(normalized_plan, ensure_ascii=False, separators=(",", ":"))


def _normalize_episode_plan_object(value: Any) -> dict[str, Any] | None:
    """把 FastGPT 返回的分集计划统一整理成代码里稳定可切片的结构。"""
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

    if isinstance(candidate, dict) and "episode_plan" in candidate:
        nested_plan = _normalize_episode_plan_object(candidate.get("episode_plan"))
        if nested_plan is not None:
            return nested_plan

    if isinstance(candidate, list):
        return _normalize_episode_plan_entries(candidate, appearance_alias_planning={})

    if not isinstance(candidate, dict):
        return None

    episodes = candidate.get("episodes")
    if not isinstance(episodes, list):
        return None

    return _normalize_episode_plan_entries(
        episodes,
        appearance_alias_planning=candidate.get("appearance_alias_planning"),
    )


def _normalize_episode_plan_entries(
    episodes: list[Any],
    *,
    appearance_alias_planning: Any,
) -> dict[str, Any] | None:
    normalized_episodes: list[dict[str, Any]] = []
    for item in episodes:
        if not isinstance(item, dict):
            continue
        episode_number = _coerce_episode_number(
            item.get("episode")
            or item.get("episode_no")
            or item.get("episodeNumber")
        )
        if episode_number is None:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            content = _framework_episode_plan_content(item)
        normalized_episodes.append(
            {
                "episode": episode_number,
                "title": str(item.get("title") or "").strip(),
                "content": content,
                "main_character_aliases": _normalize_alias_usage_list(item.get("main_character_aliases")),
                "appearance_events": _string_list(item.get("appearance_events")),
                "long_term_stage_flags": _string_list(item.get("long_term_stage_flags")),
                "scene_based_alias_hints": _normalize_alias_usage_list(item.get("scene_based_alias_hints")),
            }
        )

    if not normalized_episodes:
        return None

    return {
        "parsed_episode_count": len(normalized_episodes),
        "appearance_alias_planning": _normalize_appearance_alias_planning(
            appearance_alias_planning
        ),
        "episodes": normalized_episodes,
    }


def _framework_episode_plan_content(item: dict[str, Any]) -> str:
    parts: list[str] = []
    main_plot = str(item.get("main_plot") or item.get("summary") or "").strip()
    if main_plot:
        parts.append(f"主线剧情：{main_plot}")

    conflicts = [str(conflict or "").strip() for conflict in item.get("conflicts") or []]
    conflicts = [conflict for conflict in conflicts if conflict]
    if conflicts:
        parts.append("冲突：\n" + "\n".join(f"- {conflict}" for conflict in conflicts))

    ending_hook = str(item.get("ending_hook") or "").strip()
    if ending_hook:
        parts.append(f"结尾钩子：{ending_hook}")
    return "\n".join(parts).strip()


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
    structured_slice = _slice_structured_episode_plan_for_batch_text(episode_plan, batch)
    if structured_slice:
        return structured_slice

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


def _slice_structured_episode_plan_for_batch_text(
    episode_plan: Any,
    batch: BatchWindow,
) -> str:
    candidate = episode_plan
    if isinstance(candidate, str):
        text = candidate.strip()
        if not text or text[0] not in "[{":
            return ""
        try:
            candidate = json.loads(text)
        except Exception:
            return ""

    if isinstance(candidate, list):
        selected: list[dict[str, Any]] = []
        for item in candidate:
            if not isinstance(item, dict):
                continue
            episode_number = _coerce_episode_number(
                item.get("episode")
                or item.get("episode_no")
                or item.get("episodeNumber")
            )
            if episode_number is None:
                continue
            if batch.start_episode <= episode_number <= batch.end_episode:
                selected.append(copy.deepcopy(item))
        if selected:
            return json.dumps(selected, ensure_ascii=False, indent=2)
        return ""

    normalized_slice = slice_normalized_episode_plan_for_batch(candidate, batch)
    if normalized_slice is not None:
        return _serialize_normalized_episode_plan(normalized_slice)
    return ""


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

def _preferred_character_display_text(*args: Any, **kwargs: Any) -> str:
    """Lazy proxy to avoid importing task_manager_common during module initialization."""
    from ..services.task_manager_common import _preferred_character_display_text as _impl

    return _impl(*args, **kwargs)
