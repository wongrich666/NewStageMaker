from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..config import ModelOption, settings
from ..models.inputs import WorkflowInput
from ..models.state import WorkflowState
from ..orchestrators.runner import run_configured_workflow
from .fastgpt_contracts import (
    ALL_DIALOGUES,
    ALL_HOOKS,
    ALL_SCRIPT,
    APPEARANCE_CONTINUITY_MEMORY,
    APPEARANCE_MAPPING,
    BATCH_DIALOGUES,
    BATCH_HOOKS,
    BATCH_SCRIPT,
    BATCH_START_EPISODE,
    CHARACTERS,
    CHARACTER_ALIAS_NAMING_RULES,
    CHARACTER_ALIAS_REGISTRY,
    CHARACTER_APPEARANCE_REQUIREMENTS,
    CHARACTER_REGISTRY,
    EPISODE_ALIAS_PLAN,
    EPISODE_PLAN,
    FINAL_SCRIPT,
    FRAMEWORK_NATURAL_LANGUAGE,
    IS_CONSISTENT,
    LAST_SUMMARY,
    NORMALIZED_EPISODE_PLAN,
    OUTFIT_SWITCH_RULES,
    SCENES,
    SCENE_APPEARANCE_REQUIREMENTS,
    script_title_content,
    STORY_OUTLINE,
    TOTAL_EPISODES,
    USER_CHARACTERS,
    USER_CONTENT_BASELINE,
    UNSTRUCTURED_CONTENT_KIND,
    UNSTRUCTURED_SOURCE,
    USER_SCENES,
    WORLDVIEW,
    WORLDVIEW_NATURAL_LANGUAGE,
)
from .runtime_paths import (
    get_runtime_data_dir,
    load_runtime_manifest,
    resolve_project_snapshot_path,
    update_runtime_manifest,
)
from .workflow_spec import WorkflowSpec
from ..utils.logger import get_logger
from ..utils.episode import (
    BatchWindow,
    build_episode_batches,
    iter_episode_batches,
    rewrite_start_validation_message,
    validate_rewrite_start_episode,
)
from ..utils.user_visible_text import (
    build_user_visible_section,
    clean_user_visible_text,
    export_safe_text,
    has_meaningful_content,
    is_machine_structured_content,
    is_meaningful_text,
    is_placeholder_text,
    normalize_user_visible_text,
    parse_structured_value,
    pick_best_user_visible_value,
)
from ..workflow_ids import (
    APPEARANCE_ALIAS_NAMING_RULES_VAR,
    APPEARANCE_ALIAS_MAPPING_VAR,
    APPEARANCE_MAPPING_VAR,
    APPEARANCE_NATURAL_LANGUAGE_VAR,
    APPEARANCE_PRE_STRATEGY_REQUIREMENTS_VAR,
    APPEARANCE_REQUIREMENTS_VAR,
    CHARACTER_BIOS_VAR,
    CHARACTER_NATURAL_LANGUAGE_VAR,
    CHARACTER_VAR,
    CORE_SCENE_INPUT_VAR,
    CORE_SCENE_FINAL_VAR,
    DIALOGUE_FINAL_VAR,
    DIALOGUE_CURRENT_VAR,
    DIALOGUE_START_VAR,
    EPISODE_PLAN_CURSOR_VAR,
    EPISODE_PLAN_NORMALIZED_VAR,
    FINAL_CHARACTER_VAR,
    FINAL_SCENE_VAR,
    FRAMEWORK_ALIAS_NAMING_RULES_VAR,
    FRAMEWORK_APPEARANCE_REQUIREMENTS_VAR,
    HOOK_FINAL_VAR,
    HOOK_CURRENT_VAR,
    HOOK_START_VAR,
    MEMORY_VAR,
    OUTFIT_SWITCH_RULES_VAR,
    EPISODE_PLAN_VAR,
    SCENE_VAR,
    SCENE_NATURAL_LANGUAGE_VAR,
    SCRIPT_CURRENT_VAR,
    SCRIPT_FINAL_VAR,
    SCRIPT_START_VAR,
    STORY_OUTLINE_VAR,
    TITLE_VAR,
    UNSTRUCTURED_KIND_VAR,
    UNSTRUCTURED_SOURCE_VAR,
    WORLDVIEW_VAR,
)

logger = get_logger("task_manager")
_ONE_SHOT_WARNING_KEYS: set[str] = set()

PROJECT_RUNNING_STATUSES = {"pending", "running", "pausing", "paused"}
WAITING_STATUSES = {"pending", "running", "pausing"}
STAGE_LABELS = {
    "framework": "剧本框架",
    "framework_naturalize": "剧本框架自然语言化",
    "appearance_strategy": "服装前置策略",
    "appearance_pre_strategy": "服装前置策略",
    "validation": "集数检查",
    "consistency": "集数一致性检查",
    "episode_plan_normalize": "分集计划规范化",
    "worldview": "世界观",
    "worldview_naturalize": "世界观自然语言化",
    "character": "角色设定",
    "characters": "角色设定",
    "scene": "核心场景",
    "scenes": "核心场景",
    "appearance": "服装映射",
    "appearance_alias_generation": "服装版本映射",
    "appearance_alias_writing": "服装版本映射编写",
    "appearance_alias_review": "服装版本映射审核",
    "appearance_alias_rewrite": "服装版本映射修订",
    "appearance_alias_unstructured": "服装版本映射自然语言说明",
    "framework_scene_dictionary": "框架转剧本：场景字典提炼",
    "framework_appearanceMapping": "框架转剧本：人设服装 alias 映射",
    "framework_enriched_episode_plan": "框架转剧本：丰富分集计划",
    "framework_causal_conflict": "框架转剧本：因果冲突推进计划",
    "framework_causal_conflict_write": "框架转剧本：因果冲突推进计划",
    "framework_causal_conflict_review": "框架转剧本：因果冲突推进计划",
    "framework_causal_conflict_rewrite": "框架转剧本：因果冲突推进计划",
    "framework_causal_conflict_memory": "框架转剧本：因果冲突推进计划",
    "framework_script": "框架转剧本：正文对白融合",
    "framework_script_write": "框架转剧本：正文对白融合",
    "framework_script_review": "框架转剧本：正文对白融合",
    "framework_script_rewrite": "框架转剧本：正文对白融合",
    "framework_script_memory": "框架转剧本：正文对白融合",
    "hook": "开头冲突钩子",
    "hooks": "开头冲突钩子",
    "hooks_writing": "开头冲突钩子编写",
    "hook_write": "开头冲突钩子编写",
    "hooks_review": "开头冲突钩子审核",
    "hook_review": "开头冲突钩子审核",
    "hooks_rewrite": "开头冲突钩子修订",
    "hook_revise": "开头冲突钩子修订",
    "hook_memory": "开头冲突钩子记忆",
    "dialogue": "角色对话",
    "dialogues": "角色对白",
    "dialogues_writing": "角色对白编写",
    "dialogue_write": "角色对白编写",
    "dialogues_review": "角色对白审核",
    "dialogue_review": "角色对白审核",
    "dialogues_rewrite": "角色对白修订",
    "dialogue_revise": "角色对白修订",
    "dialogue_memory": "角色对白记忆",
    "script": "剧本正文",
    "script_writing": "剧本正文编写",
    "script_write": "剧本正文编写",
    "script_review": "剧本正文审核",
    "script_rewrite": "剧本正文修订",
    "script_revise": "剧本正文修订",
    "script_memory": "剧本正文记忆",
    "memory": "记忆",
    "final": "最终剧本",
    "finalize": "最终剧本",
    "finished": "已完成",
}
FAILED_PUBLIC_MESSAGE = "当前步骤执行失败，任务已停在上一个成功步骤，等待手动继续生成。"
TERMINATED_PUBLIC_MESSAGE = "任务已终止，已保留当前阶段和中间产物。"
RUNNING_STAGE_MESSAGE_FALLBACKS = {
    "framework": "正在生成剧本框架",
    "framework_naturalize": "正在整理剧本框架自然语言说明",
    "appearance_strategy": "正在生成服装前置策略",
    "appearance_pre_strategy": "正在生成服装前置策略",
    "validation": "正在执行集数检查",
    "consistency": "正在执行集数一致性检查",
    "episode_plan_normalize": "正在规范化分集计划",
    "worldview": "正在生成世界观",
    "worldview_naturalize": "正在整理世界观自然语言说明",
    "character": "正在生成人物设定",
    "characters": "正在生成人物设定",
    "scene": "正在生成核心场景",
    "scenes": "正在生成核心场景",
    "appearance": "正在生成服装版本映射",
    "appearance_alias_generation": "正在生成服装版本映射",
    "appearance_alias_writing": "正在编写服装版本映射",
    "appearance_alias_review": "正在审核服装版本映射",
    "appearance_alias_rewrite": "正在修订服装版本映射",
    "appearance_alias_unstructured": "正在整理服装版本映射自然语言说明",
    "framework_scene_dictionary": "正在生成框架转剧本：场景字典提炼",
    "framework_appearanceMapping": "正在生成框架转剧本：人设服装 alias 映射",
    "framework_enriched_episode_plan": "正在生成框架转剧本：丰富分集计划",
    "framework_causal_conflict": "正在生成框架转剧本因果冲突推进计划",
    "framework_causal_conflict_write": "正在编写框架转剧本：因果冲突推进计划",
    "framework_causal_conflict_review": "正在审核框架转剧本：因果冲突推进计划",
    "framework_causal_conflict_rewrite": "正在修订框架转剧本：因果冲突推进计划",
    "framework_causal_conflict_memory": "正在写入框架转剧本：因果冲突记忆",
    "framework_script": "正在生成框架转剧本正文对白融合稿",
    "framework_script_write": "正在编写框架转剧本：正文对白融合",
    "framework_script_review": "正在审核框架转剧本：正文对白融合",
    "framework_script_rewrite": "正在修订框架转剧本：正文对白融合",
    "framework_script_memory": "正在写入框架转剧本：正文记忆",
    "hooks": "正在生成开头冲突钩子",
    "hooks_writing": "正在生成开头冲突钩子",
    "hook": "正在生成开头冲突钩子",
    "hook_write": "正在生成开头冲突钩子",
    "hooks_review": "正在审核开头冲突钩子",
    "hook_review": "正在审核开头冲突钩子",
    "hooks_rewrite": "正在修订开头冲突钩子",
    "hook_revise": "正在修订开头冲突钩子",
    "hook_memory": "正在写入开头冲突钩子记忆",
    "dialogues": "正在生成角色对白",
    "dialogues_writing": "正在生成角色对白",
    "dialogue": "正在生成角色对白",
    "dialogue_write": "正在生成角色对白",
    "dialogues_review": "正在审核角色对白",
    "dialogue_review": "正在审核角色对白",
    "dialogues_rewrite": "正在修订角色对白",
    "dialogue_revise": "正在修订角色对白",
    "dialogue_memory": "正在写入角色对白记忆",
    "script": "正在生成剧本正文",
    "script_writing": "正在生成剧本正文",
    "script_write": "正在生成剧本正文",
    "script_review": "正在审核剧本正文",
    "script_rewrite": "正在修订剧本正文",
    "script_revise": "正在修订剧本正文",
    "script_memory": "正在写入剧本正文记忆",
    "final": "正在整理最终剧本",
    "finalize": "正在整理最终剧本",
    "finished": "已完成",
}
STORY_TEASER_ARTIFACT = "story_teaser"
STORY_TEASER_SOURCE_ARTIFACT = "story_teaser_source"
STAGE_PREVIEW_TEXT_ARTIFACT = "stage_preview_text"
STAGE_PREVIEW_STAGE_ARTIFACT = "stage_preview_stage"
STAGE_PREVIEW_SOURCE_HASH_ARTIFACT = "stage_preview_source_hash"
EPISODE_PLAN_DISPLAY_ARTIFACT = "episode_plan_display"
EPISODE_PLAN_DISPLAY_SOURCE_HASH_ARTIFACT = "episode_plan_display_source_hash"
APPEARANCE_NATURAL_LANGUAGE_ARTIFACT = "appearance_natural_language"
SCRIPT_BATCH_PREVIEW_ARTIFACT = "script_batch_preview"
SCRIPT_BATCH_RANGE_ARTIFACT = "script_batch_range"
PARTIAL_SCRIPT_ARTIFACT = "partial_script"
PARTIAL_SCRIPT_EPISODES_ARTIFACT = "partial_script_episodes"
SCRIPT_BATCHES_DISPLAY_ARTIFACT = "script_batches_display"
PUBLIC_INPUT_PAYLOAD_KEYS = (
    "title",
    "story_outline",
    "user_expectation",
    "character_count",
    "total_episodes",
    "script_format_mode",
    "workflow_mode",
    "generation_chain",
    "framework_to_script",
    "framework_planner_source",
    "source_framework_project_id",
)
AUXILIARY_TOOL_ASSET_KIND = "tool_result"
AUXILIARY_TOOL_CACHE_NOTICE = "辅助工具结果已保存到用户资产，可随时回来查看、修改或删除。"
PUBLIC_ARTIFACT_KEYS = (
    "script_title_content",
    "framework_natural_language",
    "worldview_natural_language",
    PARTIAL_SCRIPT_ARTIFACT,
    SCRIPT_BATCHES_DISPLAY_ARTIFACT,
    SCRIPT_BATCH_PREVIEW_ARTIFACT,
    SCRIPT_BATCH_RANGE_ARTIFACT,
    PARTIAL_SCRIPT_EPISODES_ARTIFACT,
)
PUBLIC_COMPLETED_ARTIFACT_KEYS = (
    "final_script",
    "final_output_text",
)
COMPLETED_INPUT_PAYLOAD_KEYS = (
    "title",
    "story_outline",
    "total_episodes",
    "script_format_mode",
)
COMPLETED_ARTIFACT_KEYS = (
    "script_title_content",
    "framework_natural_language",
    "story_outline",
    "normalized_episode_plan",
    "character_natural_language",
    "character_summary",
    "scene_natural_language",
    "core_scene_summary",
    "worldview_natural_language",
    APPEARANCE_NATURAL_LANGUAGE_ARTIFACT,
    "appearanceMapping",
    "character_registry",
    "character_alias_registry",
    "episode_alias_plan",
    "final_script",
    "final_output_text",
)
COMPLETION_PENDING_MESSAGE = "剧本已生成完成。请确认是否满意；确认后将清理缓存并锁定成品。"
COMPLETION_CONFIRMED_MESSAGE = "已确认剧本满意完成，缓存已清理，成品已锁定。"
COMPLETION_PENDING_NOTICE = (
    "当前剧本已经生成完成，系统暂时保留执行缓存，方便你回退到任意工作流重写。"
    "如果确认满意完成，系统会清理缓存并锁定当前成品；如需继续调整，请先选择回退重写。"
)
COMPLETION_CONFIRMED_NOTICE = (
    "你已确认当前剧本满意完成。执行缓存已经清理，当前成品正文不可再直接修改；公开/私有仍可随时切换。"
)
RUNTIME_CACHE_NOTICE = "系统会保留必要缓存，方便暂停、继续、失败恢复和阶段回退。请谨慎选择。"
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
SCRIPT_EPISODE_HEADING_PATTERN = re.compile(
    r"(?=^[ \t>#*\-]*第\s*([0-9０-９一二三四五六七八九十百千万两零〇]+)\s*集(?:\s*[:：]|$))",
    re.MULTILINE,
)
ROLLBACK_STAGE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("framework", "剧本框架撰写"),
    ("appearance_strategy", "服装前置策略生成"),
    ("consistency", "集数一致性检查"),
    ("episode_plan_normalize", "分集计划规范化"),
    ("worldview", "世界观生成"),
    ("characters", "人物设定生成"),
    ("scenes", "核心场景生成"),
    ("appearance", "服装版本映射"),
    ("hooks", "开头冲突钩子"),
    ("dialogues", "角色对话"),
    ("script", "剧本正文"),
    ("final", "最终剧本拼接"),
)
ROLLBACK_STAGE_LABELS = {key: label for key, label in ROLLBACK_STAGE_OPTIONS}
ROLLBACK_STAGE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "hooks": ("hooks", "dialogues", "script"),
    "dialogues": ("dialogues", "script"),
    "script": ("script",),
}
ROLLBACK_RANGE_STAGE_KEYS = frozenset(ROLLBACK_STAGE_DEPENDENCIES)


def _rollback_stage_index(stage_key: Any) -> int:
    stage = str(stage_key or "").strip().lower()
    for index, (key, _) in enumerate(ROLLBACK_STAGE_OPTIONS):
        if key == stage:
            return index
    return -1


def _rollback_stage_requires_episode_range(stage_key: Any) -> bool:
    return _normalize_rollback_stage_key(stage_key) in ROLLBACK_RANGE_STAGE_KEYS


def _rollback_stage_dependency_keys(stage_key: Any) -> tuple[str, ...]:
    normalized = _normalize_rollback_stage_key(stage_key)
    return ROLLBACK_STAGE_DEPENDENCIES.get(normalized, (normalized,))
DEBUG_VARIABLE_MIRRORS: dict[str, tuple[str, ...]] = {
    script_title_content: (TITLE_VAR,),
    STORY_OUTLINE: (STORY_OUTLINE_VAR,),
    USER_CHARACTERS: (CHARACTER_BIOS_VAR,),
    USER_SCENES: (CORE_SCENE_INPUT_VAR,),
    EPISODE_PLAN: (EPISODE_PLAN_VAR,),
    NORMALIZED_EPISODE_PLAN: (EPISODE_PLAN_NORMALIZED_VAR,),
    CHARACTER_APPEARANCE_REQUIREMENTS: (
        APPEARANCE_PRE_STRATEGY_REQUIREMENTS_VAR,
        APPEARANCE_REQUIREMENTS_VAR,
        FRAMEWORK_APPEARANCE_REQUIREMENTS_VAR,
    ),
    CHARACTER_ALIAS_NAMING_RULES: (
        APPEARANCE_ALIAS_NAMING_RULES_VAR,
        FRAMEWORK_ALIAS_NAMING_RULES_VAR,
    ),
    OUTFIT_SWITCH_RULES: (OUTFIT_SWITCH_RULES_VAR,),
    WORLDVIEW: (WORLDVIEW_VAR,),
    CHARACTERS: (CHARACTER_VAR, FINAL_CHARACTER_VAR),
    CHARACTER_NATURAL_LANGUAGE_VAR: (CHARACTER_NATURAL_LANGUAGE_VAR,),
    SCENES: (SCENE_VAR, CORE_SCENE_FINAL_VAR, FINAL_SCENE_VAR),
    SCENE_NATURAL_LANGUAGE_VAR: (SCENE_NATURAL_LANGUAGE_VAR,),
    BATCH_START_EPISODE: (
        HOOK_START_VAR,
        DIALOGUE_START_VAR,
        SCRIPT_START_VAR,
        EPISODE_PLAN_CURSOR_VAR,
    ),
    BATCH_HOOKS: (HOOK_CURRENT_VAR,),
    ALL_HOOKS: (HOOK_FINAL_VAR,),
    BATCH_DIALOGUES: (DIALOGUE_CURRENT_VAR,),
    ALL_DIALOGUES: (DIALOGUE_FINAL_VAR,),
    BATCH_SCRIPT: (SCRIPT_CURRENT_VAR,),
    ALL_SCRIPT: (ALL_SCRIPT, SCRIPT_FINAL_VAR),
    LAST_SUMMARY: (MEMORY_VAR,),
    APPEARANCE_MAPPING: (APPEARANCE_MAPPING_VAR, APPEARANCE_ALIAS_MAPPING_VAR),
    FINAL_SCRIPT: (FINAL_SCRIPT,),
}
ROLLBACK_DEBUG_CLEAR_RULES: dict[str, tuple[str, ...]] = {
    "framework": (
        script_title_content,
        STORY_OUTLINE,
        USER_CHARACTERS,
        USER_SCENES,
        EPISODE_PLAN,
        USER_CONTENT_BASELINE,
        CHARACTER_APPEARANCE_REQUIREMENTS,
        CHARACTER_ALIAS_NAMING_RULES,
        OUTFIT_SWITCH_RULES,
        IS_CONSISTENT,
        NORMALIZED_EPISODE_PLAN,
        WORLDVIEW,
        CHARACTERS,
        SCENES,
        SCENE_APPEARANCE_REQUIREMENTS,
        APPEARANCE_MAPPING,
        CHARACTER_REGISTRY,
        CHARACTER_ALIAS_REGISTRY,
        EPISODE_ALIAS_PLAN,
        APPEARANCE_CONTINUITY_MEMORY,
        ALL_HOOKS,
        BATCH_HOOKS,
        ALL_DIALOGUES,
        BATCH_DIALOGUES,
        ALL_SCRIPT,
        BATCH_SCRIPT,
        LAST_SUMMARY,
        FINAL_SCRIPT,
        BATCH_START_EPISODE,
        "_completed_batches",
        "_committed_all_script",
        "_current_batch_index",
        "_current_batch_stage",
        LOCAL_HOOK_CHECKPOINT_START,
        LOCAL_DIALOGUE_CHECKPOINT_START,
        LOCAL_SCRIPT_CHECKPOINT_START,
        LOCAL_REWRITE_FROM_STAGE,
        LOCAL_RAW_EPISODE_PLAN,
    ),
    "appearance_strategy": (
        USER_CONTENT_BASELINE,
        CHARACTER_APPEARANCE_REQUIREMENTS,
        CHARACTER_ALIAS_NAMING_RULES,
        OUTFIT_SWITCH_RULES,
        IS_CONSISTENT,
        NORMALIZED_EPISODE_PLAN,
        WORLDVIEW,
        CHARACTERS,
        SCENES,
        SCENE_APPEARANCE_REQUIREMENTS,
        APPEARANCE_MAPPING,
        CHARACTER_REGISTRY,
        CHARACTER_ALIAS_REGISTRY,
        EPISODE_ALIAS_PLAN,
        APPEARANCE_CONTINUITY_MEMORY,
        ALL_HOOKS,
        BATCH_HOOKS,
        ALL_DIALOGUES,
        BATCH_DIALOGUES,
        ALL_SCRIPT,
        BATCH_SCRIPT,
        LAST_SUMMARY,
        FINAL_SCRIPT,
        BATCH_START_EPISODE,
        "_completed_batches",
        "_committed_all_script",
        "_current_batch_index",
        "_current_batch_stage",
        LOCAL_HOOK_CHECKPOINT_START,
        LOCAL_DIALOGUE_CHECKPOINT_START,
        LOCAL_SCRIPT_CHECKPOINT_START,
        LOCAL_REWRITE_FROM_STAGE,
    ),
    "consistency": (
        IS_CONSISTENT,
        NORMALIZED_EPISODE_PLAN,
        USER_CONTENT_BASELINE,
        WORLDVIEW,
        CHARACTERS,
        SCENES,
        SCENE_APPEARANCE_REQUIREMENTS,
        APPEARANCE_MAPPING,
        CHARACTER_REGISTRY,
        CHARACTER_ALIAS_REGISTRY,
        EPISODE_ALIAS_PLAN,
        APPEARANCE_CONTINUITY_MEMORY,
        ALL_HOOKS,
        BATCH_HOOKS,
        ALL_DIALOGUES,
        BATCH_DIALOGUES,
        ALL_SCRIPT,
        BATCH_SCRIPT,
        LAST_SUMMARY,
        FINAL_SCRIPT,
        BATCH_START_EPISODE,
        "_completed_batches",
        "_committed_all_script",
        "_current_batch_index",
        "_current_batch_stage",
        LOCAL_HOOK_CHECKPOINT_START,
        LOCAL_DIALOGUE_CHECKPOINT_START,
        LOCAL_SCRIPT_CHECKPOINT_START,
        LOCAL_REWRITE_FROM_STAGE,
    ),
    "episode_plan_normalize": (
        NORMALIZED_EPISODE_PLAN,
        USER_CONTENT_BASELINE,
        WORLDVIEW,
        CHARACTERS,
        SCENES,
        SCENE_APPEARANCE_REQUIREMENTS,
        APPEARANCE_MAPPING,
        CHARACTER_REGISTRY,
        CHARACTER_ALIAS_REGISTRY,
        EPISODE_ALIAS_PLAN,
        APPEARANCE_CONTINUITY_MEMORY,
        ALL_HOOKS,
        BATCH_HOOKS,
        ALL_DIALOGUES,
        BATCH_DIALOGUES,
        ALL_SCRIPT,
        BATCH_SCRIPT,
        LAST_SUMMARY,
        FINAL_SCRIPT,
        BATCH_START_EPISODE,
        "_completed_batches",
        "_committed_all_script",
        "_current_batch_index",
        "_current_batch_stage",
        LOCAL_HOOK_CHECKPOINT_START,
        LOCAL_DIALOGUE_CHECKPOINT_START,
        LOCAL_SCRIPT_CHECKPOINT_START,
        LOCAL_REWRITE_FROM_STAGE,
    ),
    "worldview": (
        WORLDVIEW,
        CHARACTERS,
        SCENES,
        SCENE_APPEARANCE_REQUIREMENTS,
        APPEARANCE_MAPPING,
        CHARACTER_REGISTRY,
        CHARACTER_ALIAS_REGISTRY,
        EPISODE_ALIAS_PLAN,
        APPEARANCE_CONTINUITY_MEMORY,
        ALL_HOOKS,
        BATCH_HOOKS,
        ALL_DIALOGUES,
        BATCH_DIALOGUES,
        ALL_SCRIPT,
        BATCH_SCRIPT,
        LAST_SUMMARY,
        FINAL_SCRIPT,
        BATCH_START_EPISODE,
        "_completed_batches",
        "_committed_all_script",
        "_current_batch_index",
        "_current_batch_stage",
        LOCAL_HOOK_CHECKPOINT_START,
        LOCAL_DIALOGUE_CHECKPOINT_START,
        LOCAL_SCRIPT_CHECKPOINT_START,
        LOCAL_REWRITE_FROM_STAGE,
    ),
    "characters": (
        CHARACTERS,
        SCENES,
        SCENE_APPEARANCE_REQUIREMENTS,
        APPEARANCE_MAPPING,
        CHARACTER_REGISTRY,
        CHARACTER_ALIAS_REGISTRY,
        EPISODE_ALIAS_PLAN,
        APPEARANCE_CONTINUITY_MEMORY,
        ALL_HOOKS,
        BATCH_HOOKS,
        ALL_DIALOGUES,
        BATCH_DIALOGUES,
        ALL_SCRIPT,
        BATCH_SCRIPT,
        LAST_SUMMARY,
        FINAL_SCRIPT,
        BATCH_START_EPISODE,
        "_completed_batches",
        "_committed_all_script",
        "_current_batch_index",
        "_current_batch_stage",
        LOCAL_HOOK_CHECKPOINT_START,
        LOCAL_DIALOGUE_CHECKPOINT_START,
        LOCAL_SCRIPT_CHECKPOINT_START,
        LOCAL_REWRITE_FROM_STAGE,
    ),
    "scenes": (
        SCENES,
        SCENE_APPEARANCE_REQUIREMENTS,
        APPEARANCE_MAPPING,
        CHARACTER_REGISTRY,
        CHARACTER_ALIAS_REGISTRY,
        EPISODE_ALIAS_PLAN,
        APPEARANCE_CONTINUITY_MEMORY,
        ALL_HOOKS,
        BATCH_HOOKS,
        ALL_DIALOGUES,
        BATCH_DIALOGUES,
        ALL_SCRIPT,
        BATCH_SCRIPT,
        LAST_SUMMARY,
        FINAL_SCRIPT,
        BATCH_START_EPISODE,
        "_completed_batches",
        "_committed_all_script",
        "_current_batch_index",
        "_current_batch_stage",
        LOCAL_HOOK_CHECKPOINT_START,
        LOCAL_DIALOGUE_CHECKPOINT_START,
        LOCAL_SCRIPT_CHECKPOINT_START,
        LOCAL_REWRITE_FROM_STAGE,
    ),
    "appearance": (
        SCENE_APPEARANCE_REQUIREMENTS,
        APPEARANCE_MAPPING,
        CHARACTER_REGISTRY,
        CHARACTER_ALIAS_REGISTRY,
        EPISODE_ALIAS_PLAN,
        APPEARANCE_CONTINUITY_MEMORY,
        ALL_HOOKS,
        BATCH_HOOKS,
        ALL_DIALOGUES,
        BATCH_DIALOGUES,
        ALL_SCRIPT,
        BATCH_SCRIPT,
        LAST_SUMMARY,
        FINAL_SCRIPT,
        BATCH_START_EPISODE,
        "_completed_batches",
        "_committed_all_script",
        "_current_batch_index",
        "_current_batch_stage",
        LOCAL_HOOK_CHECKPOINT_START,
        LOCAL_DIALOGUE_CHECKPOINT_START,
        LOCAL_SCRIPT_CHECKPOINT_START,
        LOCAL_REWRITE_FROM_STAGE,
    ),
    "hooks": (
        APPEARANCE_CONTINUITY_MEMORY,
        ALL_HOOKS,
        BATCH_HOOKS,
        ALL_DIALOGUES,
        BATCH_DIALOGUES,
        ALL_SCRIPT,
        BATCH_SCRIPT,
        LAST_SUMMARY,
        FINAL_SCRIPT,
        BATCH_START_EPISODE,
        "_completed_batches",
        "_committed_all_script",
        "_current_batch_index",
        "_current_batch_stage",
        LOCAL_HOOK_CHECKPOINT_START,
        LOCAL_DIALOGUE_CHECKPOINT_START,
        LOCAL_SCRIPT_CHECKPOINT_START,
        LOCAL_REWRITE_FROM_STAGE,
    ),
    "dialogues": (
        APPEARANCE_CONTINUITY_MEMORY,
        ALL_DIALOGUES,
        BATCH_DIALOGUES,
        ALL_SCRIPT,
        BATCH_SCRIPT,
        LAST_SUMMARY,
        FINAL_SCRIPT,
        BATCH_START_EPISODE,
        "_completed_batches",
        "_committed_all_script",
        "_current_batch_index",
        "_current_batch_stage",
        LOCAL_REWRITE_FROM_STAGE,
    ),
    "script": (
        APPEARANCE_CONTINUITY_MEMORY,
        ALL_SCRIPT,
        BATCH_SCRIPT,
        LAST_SUMMARY,
        FINAL_SCRIPT,
        BATCH_START_EPISODE,
        "_completed_batches",
        "_committed_all_script",
        "_current_batch_index",
        "_current_batch_stage",
        LOCAL_REWRITE_FROM_STAGE,
    ),
    "final": (
        FINAL_SCRIPT,
        LOCAL_REWRITE_FROM_STAGE,
    ),
}
for _stage_key in (
    "framework",
    "appearance_strategy",
    "consistency",
    "episode_plan_normalize",
    "worldview",
    "characters",
    "scenes",
    "appearance",
    "hooks",
    "dialogues",
):
    ROLLBACK_DEBUG_CLEAR_RULES[_stage_key] = ROLLBACK_DEBUG_CLEAR_RULES[_stage_key] + (
        LOCAL_SCRIPT_BATCHES,
        LOCAL_SCRIPT_EPISODES,
        LOCAL_SUMMARY_BY_BATCH,
        LOCAL_APPEARANCE_MEMORY_BY_BATCH,
    )

ROLLBACK_ARTIFACT_CLEAR_RULES: dict[str, tuple[str, ...]] = {
    "framework": (
        "script_title_content",
        "story_outline",
        "character_bios",
        "episode_plan",
        "normalized_episode_plan",
        "character_natural_language",
        "worldview",
        "character_summary",
        "scene_natural_language",
        "scene_json",
        "core_scene_input",
        "core_scene_summary",
        "character_appearance_requirements",
        "character_alias_naming_rules",
        "outfit_switch_rules",
        "appearanceMapping",
        "character_registry",
        "character_alias_registry",
        "episode_alias_plan",
        "appearance_continuity_memory",
        "hook_plan",
        "dialogue_plan",
        "script_batch",
        "final_script",
        "continuity_memory",
        "final_output_text",
        "halted_message",
    ),
    "appearance_strategy": (
        "normalized_episode_plan",
        "character_natural_language",
        "worldview",
        "character_summary",
        "scene_natural_language",
        "scene_json",
        "core_scene_summary",
        "character_appearance_requirements",
        "character_alias_naming_rules",
        "outfit_switch_rules",
        "appearanceMapping",
        "character_registry",
        "character_alias_registry",
        "episode_alias_plan",
        "appearance_continuity_memory",
        "hook_plan",
        "dialogue_plan",
        "script_batch",
        "final_script",
        "continuity_memory",
        "final_output_text",
        "halted_message",
    ),
    "consistency": (
        "normalized_episode_plan",
        "character_natural_language",
        "worldview",
        "character_summary",
        "scene_natural_language",
        "scene_json",
        "core_scene_summary",
        "appearanceMapping",
        "character_registry",
        "character_alias_registry",
        "episode_alias_plan",
        "appearance_continuity_memory",
        "hook_plan",
        "dialogue_plan",
        "script_batch",
        "final_script",
        "continuity_memory",
        "final_output_text",
        "halted_message",
    ),
    "episode_plan_normalize": (
        "normalized_episode_plan",
        "character_natural_language",
        "worldview",
        "character_summary",
        "scene_natural_language",
        "scene_json",
        "core_scene_summary",
        "appearanceMapping",
        "character_registry",
        "character_alias_registry",
        "episode_alias_plan",
        "appearance_continuity_memory",
        "hook_plan",
        "dialogue_plan",
        "script_batch",
        "final_script",
        "continuity_memory",
        "final_output_text",
        "halted_message",
    ),
    "worldview": (
        "worldview",
        "character_natural_language",
        "character_summary",
        "scene_natural_language",
        "scene_json",
        "core_scene_summary",
        "appearanceMapping",
        "character_registry",
        "character_alias_registry",
        "episode_alias_plan",
        "appearance_continuity_memory",
        "hook_plan",
        "dialogue_plan",
        "script_batch",
        "final_script",
        "continuity_memory",
        "final_output_text",
        "halted_message",
    ),
    "characters": (
        "character_natural_language",
        "character_summary",
        "scene_natural_language",
        "scene_json",
        "core_scene_summary",
        "appearanceMapping",
        "character_registry",
        "character_alias_registry",
        "episode_alias_plan",
        "appearance_continuity_memory",
        "hook_plan",
        "dialogue_plan",
        "script_batch",
        "final_script",
        "continuity_memory",
        "final_output_text",
        "halted_message",
    ),
    "scenes": (
        "scene_natural_language",
        "scene_json",
        "core_scene_summary",
        "appearanceMapping",
        "character_registry",
        "character_alias_registry",
        "episode_alias_plan",
        "appearance_continuity_memory",
        "hook_plan",
        "dialogue_plan",
        "script_batch",
        "final_script",
        "continuity_memory",
        "final_output_text",
        "halted_message",
    ),
    "appearance": (
        "appearanceMapping",
        "character_registry",
        "character_alias_registry",
        "episode_alias_plan",
        "appearance_continuity_memory",
        "hook_plan",
        "dialogue_plan",
        "script_batch",
        "final_script",
        "continuity_memory",
        "final_output_text",
        "halted_message",
    ),
    "hooks": (
        "appearance_continuity_memory",
        "hook_plan",
        "dialogue_plan",
        "script_batch",
        "final_script",
        "continuity_memory",
        "final_output_text",
        "halted_message",
    ),
    "dialogues": (
        "appearance_continuity_memory",
        "dialogue_plan",
        "script_batch",
        "final_script",
        "continuity_memory",
        "final_output_text",
        "halted_message",
    ),
    "script": (
        "appearance_continuity_memory",
        "script_batch",
        "final_script",
        "continuity_memory",
        "final_output_text",
        "halted_message",
    ),
    "final": (
        "final_script",
        "final_output_text",
        "halted_message",
    ),
}

PARTIAL_SCRIPT_ARTIFACT_KEYS: tuple[str, ...] = (
    PARTIAL_SCRIPT_ARTIFACT,
    SCRIPT_BATCHES_DISPLAY_ARTIFACT,
    SCRIPT_BATCH_PREVIEW_ARTIFACT,
    SCRIPT_BATCH_RANGE_ARTIFACT,
    PARTIAL_SCRIPT_EPISODES_ARTIFACT,
)

for _stage_key in (
    "framework",
    "appearance_strategy",
    "consistency",
    "episode_plan_normalize",
    "worldview",
    "characters",
    "scenes",
    "appearance",
    "hooks",
    "dialogues",
    "script",
):
    ROLLBACK_ARTIFACT_CLEAR_RULES[_stage_key] = (
        ROLLBACK_ARTIFACT_CLEAR_RULES[_stage_key] + PARTIAL_SCRIPT_ARTIFACT_KEYS
    )


def _select_non_empty_fields(
    source: dict[str, Any] | None,
    allowed_keys: tuple[str, ...],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if not isinstance(source, dict):
        return payload
    for key in allowed_keys:
        if key not in source:
            continue
        value = copy.deepcopy(source.get(key))
        if value in (None, "", {}, []):
            continue
        payload[key] = value
    return payload


def _display_text(value: Any) -> str:
    return normalize_user_visible_text(value).strip()


def _meaningful_stage_output_text(value: Any) -> str:
    return clean_user_visible_text(value).strip()


def clean_multiline_user_visible_text(value: Any) -> str:
    if not isinstance(value, str):
        return clean_user_visible_text(value).strip()
    raw = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [clean_user_visible_text(line).strip() for line in raw.split("\n")]
    non_empty_lines = [line for line in lines if line]
    if len(non_empty_lines) > 1:
        return "\n".join(non_empty_lines).strip()
    return clean_user_visible_text(value).strip()


EXPORT_TECHNICAL_KEY_PATTERN = re.compile(r'^\s*"?[A-Za-z_][A-Za-z0-9_]*"?\s*:\s*(.*)$')
EXPORT_JSON_FENCE_PATTERN = re.compile(r"```(?:json|text|markdown)?\s*([\s\S]*?)```", re.IGNORECASE)
CHARACTER_PLACEHOLDER_PATTERN = re.compile(
    r"(待补全|待完善|未提供|未补充|暂无|待填写|待定|省略|TBD|TODO|N/?A|None|null)",
    re.IGNORECASE,
)
CHARACTER_HEADING_ONLY_PATTERN = re.compile(r"^(人物定位|人物小传|关系特点|出场记忆点)\s*[：:]?\s*$")
CHARACTER_LABEL_LINE_PATTERN = re.compile(r"^【[^】]+】\s*[^：:\n]{1,20}$")


def _strip_export_code_fences(text: str) -> str:
    content = str(text or "").strip()
    match = EXPORT_JSON_FENCE_PATTERN.fullmatch(content)
    if match:
        return str(match.group(1) or "").strip()
    return EXPORT_JSON_FENCE_PATTERN.sub(lambda item: str(item.group(1) or "").strip(), content).strip()


def _clean_export_key_line(line: str) -> str:
    text = str(line or "").strip()
    if not text:
        return ""
    if text in {"{", "}", "[", "]", ",", "```", "```json", "```text", "```markdown"}:
        return ""
    match = EXPORT_TECHNICAL_KEY_PATTERN.match(text)
    if match:
        value = str(match.group(1) or "").strip().strip(",")
        if value in {"{", "[", "", "}", "]"}:
            return ""
        return value.strip(' "')
    return text.strip(' "')


INLINE_STRUCTURED_DUMP_MARKERS = (
    '{"appearanceMapping"',
    '{"character_setting"',
    '{"scene_setting"',
    '{"characters"',
    '{"scenes"',
    "{'appearanceMapping'",
    "{'character_setting'",
    "{'scene_setting'",
    "{'characters'",
    "{'scenes'",
)


def _strip_trailing_structured_dump_text(text: str) -> str:
    content = _strip_export_code_fences(text)
    if not content:
        return ""
    lines = content.splitlines()
    for index in range(1, len(lines)):
        tail = "\n".join(lines[index:]).strip()
        if not tail or tail[0] not in "[{":
            continue
        if parse_structured_value(tail) is None:
            continue
        head = "\n".join(lines[:index]).strip()
        if head:
            return head
    for marker in INLINE_STRUCTURED_DUMP_MARKERS:
        marker_index = content.find(marker)
        if marker_index <= 0:
            continue
        head = content[:marker_index].rstrip()
        if len(re.sub(r"\s+", "", head)) >= 12:
            return head
    return content.strip()


def _truncate_log_text(text: Any, *, max_chars: int = 500) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "..."


def clean_export_readable_text(value: Any) -> str:
    """把可能来自 JSON、markdown 或字段化文本的内容清洗成适合导出的自然语言。"""
    if isinstance(value, str):
        stripped = _strip_trailing_structured_dump_text(value)
        if stripped:
            return normalize_user_visible_text(stripped).strip()
    return normalize_user_visible_text(value).strip()


def _placeholder_cleaned_text(value: Any) -> str:
    return clean_user_visible_text(value).strip()


def _is_placeholder_like_character_text(value: Any) -> bool:
    text = _placeholder_cleaned_text(value)
    if not text:
        return True
    if CHARACTER_HEADING_ONLY_PATTERN.fullmatch(text):
        return True
    return is_placeholder_text(text)


def _export_text_has_placeholder_leaks(value: Any) -> bool:
    text = clean_export_readable_text(value).strip()
    if not text:
        return False
    lines = [line.strip() for line in text.replace("\r", "").split("\n") if line.strip()]
    if not lines:
        return False
    placeholder_lines = [line for line in lines if CHARACTER_PLACEHOLDER_PATTERN.search(line)]
    if not placeholder_lines:
        return False
    informative_lines = [line for line in lines if not CHARACTER_PLACEHOLDER_PATTERN.search(line)]
    placeholder_hits = CHARACTER_PLACEHOLDER_PATTERN.findall(text)
    if len(placeholder_hits) >= max(3, len(lines) // 3):
        return True
    if len(placeholder_lines) >= max(2, len(lines) // 3):
        return True
    if not informative_lines:
        return True
    return False


def _summarize_fastgpt_output(output: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in (output or {}).items():
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
    return "；".join(parts)[:240] or "成品已生成。"


def _public_status_message(snapshot: dict[str, Any]) -> str:
    status = str(snapshot.get("status") or "").strip()
    message = str(snapshot.get("message") or "").strip()
    if status == "failed":
        return FAILED_PUBLIC_MESSAGE
    if status == "terminated":
        return TERMINATED_PUBLIC_MESSAGE
    if status == "paused":
        return message or "已暂停。"
    if status == "pausing":
        return message or "正在暂停。"
    if status in {"pending", "running"} and not message:
        return _default_runtime_stage_message(snapshot)
    if not message:
        return ""
    return message


def _default_runtime_stage_message(snapshot: dict[str, Any]) -> str:
    stage_key = str(snapshot.get("current_stage") or "").strip().lower()
    current_batch = str(snapshot.get("current_batch") or "").strip()
    base = RUNNING_STAGE_MESSAGE_FALLBACKS.get(stage_key)
    if not base:
        label = str(snapshot.get("current_stage_label") or "").strip()
        base = f"正在处理{label}" if label else "正在处理中"
    if current_batch:
        return f"{base}：第 {current_batch} 集"
    return base


def _completion_confirmed(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    return bool(snapshot.get("completion_confirmed"))


def _awaiting_completion_confirmation(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if str(snapshot.get("status") or "") != "completed":
        return False
    if _completion_confirmed(snapshot):
        return False
    if snapshot.get("awaiting_user_confirmation") is not None:
        return bool(snapshot.get("awaiting_user_confirmation"))
    artifacts = snapshot.get("artifacts") or {}
    return bool(
        str(artifacts.get("final_output_text") or artifacts.get("final_script") or "").strip()
    )


def _can_stage_rollback(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if _completion_confirmed(snapshot):
        return False
    status = str(snapshot.get("status") or "").strip()
    if status in {"pending", "running"}:
        return False
    if status not in {"completed", "paused", "pausing", "terminated", "failed"}:
        return False
    debug_state = snapshot.get("debug_state")
    return isinstance(debug_state, dict) and isinstance(debug_state.get("variables"), dict)


def _cache_notice(snapshot: dict[str, Any]) -> str:
    if str(snapshot.get("asset_kind") or "").strip() == AUXILIARY_TOOL_ASSET_KIND:
        return AUXILIARY_TOOL_CACHE_NOTICE
    if _completion_confirmed(snapshot):
        return COMPLETION_CONFIRMED_NOTICE
    if _awaiting_completion_confirmation(snapshot):
        return COMPLETION_PENDING_NOTICE
    return RUNTIME_CACHE_NOTICE


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _is_waiting_status(status: Any) -> bool:
    return str(status or "").strip() in WAITING_STATUSES


def _iso_to_epoch_ms(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _sync_wait_tracking(
    snapshot: dict[str, Any],
    *,
    previous_status: Any,
    current_status: Any,
    current_time_iso: str,
) -> None:
    elapsed_ms = _safe_int(snapshot.get("wait_elapsed_ms"), 0)
    previous_waiting = _is_waiting_status(previous_status)
    current_waiting = _is_waiting_status(current_status)
    started_at = snapshot.get("wait_started_at")

    if previous_waiting and not current_waiting:
        started_ms = _iso_to_epoch_ms(started_at)
        current_ms = _iso_to_epoch_ms(current_time_iso)
        if started_ms is not None and current_ms is not None:
            elapsed_ms += max(0, current_ms - started_ms)
        snapshot["wait_elapsed_ms"] = elapsed_ms
        snapshot["wait_started_at"] = None
        return

    snapshot["wait_elapsed_ms"] = elapsed_ms
    if current_waiting:
        snapshot["wait_started_at"] = started_at or current_time_iso
    else:
        snapshot["wait_started_at"] = None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_rollback_stage_key(value: Any) -> str:
    stage = str(value or "").strip().lower()
    mapping = {
        "hook": "hooks",
        "hooks": "hooks",
        "dialogue": "dialogues",
        "dialogues": "dialogues",
        "script": "script",
        "final": "final",
    }
    return mapping.get(stage, stage)


def _batch_end_episode(total_episodes: int, start_episode: int) -> int:
    batch_size = max(1, int(settings.batch_size or 5))
    return min(max(0, total_episodes), start_episode + batch_size - 1)


def _slice_episode_object_before(value: Any, start_episode: int) -> dict[str, Any]:
    payload = copy.deepcopy(value) if isinstance(value, dict) else {}
    episodes = payload.get("episodes")
    if not isinstance(episodes, list):
        return payload if payload else {}

    selected = []
    for item in episodes:
        if not isinstance(item, dict):
            continue
        episode_no = _safe_int(item.get("episode"), 0)
        if 0 < episode_no < start_episode:
            selected.append(copy.deepcopy(item))

    if not selected:
        return {}

    payload["episodes"] = selected
    batch_meta = payload.get("batch_meta")
    if isinstance(batch_meta, dict):
        payload["batch_meta"] = {
            **copy.deepcopy(batch_meta),
            "start_episode": selected[0].get("episode") or 1,
            "end_episode": selected[-1].get("episode") or max(1, start_episode - 1),
        }
    return payload


def _slice_episode_object_through(value: Any, end_episode: int) -> dict[str, Any]:
    payload = copy.deepcopy(value) if isinstance(value, dict) else {}
    episodes = payload.get("episodes")
    if not isinstance(episodes, list):
        return payload if payload else {}

    selected = []
    for item in episodes:
        if not isinstance(item, dict):
            continue
        episode_no = _safe_int(item.get("episode"), 0)
        if 0 < episode_no <= end_episode:
            selected.append(copy.deepcopy(item))

    if not selected:
        return {}

    payload["episodes"] = selected
    batch_meta = payload.get("batch_meta")
    if isinstance(batch_meta, dict):
        payload["batch_meta"] = {
            **copy.deepcopy(batch_meta),
            "start_episode": selected[0].get("episode") or 1,
            "end_episode": selected[-1].get("episode") or end_episode,
        }
    return payload


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

    matches = list(SCRIPT_EPISODE_HEADING_PATTERN.finditer(text))
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


def _warning_signature(kind: str, issues: list[str], preview: str) -> str:
    return f"{kind}|{','.join(issues)}|{preview.strip()}"


def _log_warning_once(kind: str, issues: list[str], preview: str) -> None:
    signature = _warning_signature(kind, issues, preview)
    if signature in _ONE_SHOT_WARNING_KEYS:
        return
    _ONE_SHOT_WARNING_KEYS.add(signature)
    logger.warning("%s issues=%s preview=%s", kind, ",".join(issues), preview)


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
    if not source:
        return []
    end_episode = max(1, total_episodes) if total_episodes > 0 else 9999
    return sorted(
        _extract_script_episode_map(
            source,
            BatchWindow(start_episode=1, end_episode=end_episode),
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
        text = clean_user_visible_text(candidate).strip()
        if not text or text in seen:
            continue
        if not is_meaningful_text(text):
            continue
        seen.add(text)
        episodes = _script_episode_numbers(text, total_episodes=total_episodes)
        if is_machine_structured_content(candidate) and not episodes:
            continue
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


def _resolve_best_script_text(
    *,
    total_episodes: int,
    artifacts: dict[str, Any] | None,
    variables: dict[str, Any] | None,
    final_output_text: Any = None,
) -> str:
    normalized_artifacts = artifacts if isinstance(artifacts, dict) else {}
    normalized_variables = variables if isinstance(variables, dict) else {}
    batch_size = max(1, int(settings.batch_size or 5))
    script_batches = _normalize_batch_text_map(normalized_variables.get(LOCAL_SCRIPT_BATCHES))
    script_episode_cache = _normalize_episode_script_map(normalized_variables.get(LOCAL_SCRIPT_EPISODES))
    rebuilt_episode_cache = _rebuild_script_episode_cache(
        script_batches,
        script_episode_cache,
        total_episodes=total_episodes,
        batch_size=batch_size,
    )
    rebuilt_script = _join_script_episode_map(rebuilt_episode_cache) if rebuilt_episode_cache else ""
    joined_batches = _join_script_parts(
        *(script_batches[start_episode] for start_episode in sorted(script_batches))
    )
    best_text, _ = _best_script_text_candidate(
        total_episodes,
        rebuilt_script,
        final_output_text,
        normalized_variables.get(FINAL_SCRIPT),
        normalized_variables.get(SCRIPT_FINAL_VAR),
        normalized_variables.get(ALL_SCRIPT),
        normalized_variables.get(LOCAL_COMMITTED_SCRIPT),
        normalized_artifacts.get("final_output_text"),
        normalized_artifacts.get("final_script"),
        joined_batches,
    )
    return best_text


def _partial_script_entries_from_variables(
    *,
    total_episodes: int,
    variables: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    normalized_variables = variables if isinstance(variables, dict) else {}
    batch_size = max(1, int(settings.batch_size or 5))
    script_batches = _normalize_batch_text_map(normalized_variables.get(LOCAL_SCRIPT_BATCHES))
    script_episode_cache = _normalize_episode_script_map(normalized_variables.get(LOCAL_SCRIPT_EPISODES))
    entries: list[dict[str, Any]] = []
    seen_starts: set[int] = set()

    if total_episodes > 0:
        for batch in iter_episode_batches(total_episodes, batch_size=batch_size):
            batch_text = str(script_batches.get(batch.start_episode) or "").strip()
            if not batch_text and script_episode_cache:
                episode_slice = {
                    episode: script_episode_cache.get(episode)
                    for episode in range(batch.start_episode, batch.end_episode + 1)
                    if str(script_episode_cache.get(episode) or "").strip()
                }
                if len(episode_slice) == batch.size:
                    batch_text = _join_script_episode_map(episode_slice).strip()
            if not batch_text:
                continue
            entries.append(
                {
                    "start_episode": batch.start_episode,
                    "end_episode": batch.end_episode,
                    "range": f"{batch.start_episode}-{batch.end_episode}",
                    "content": batch_text,
                }
            )
            seen_starts.add(batch.start_episode)

    for start_episode in sorted(script_batches):
        if start_episode in seen_starts:
            continue
        batch_text = str(script_batches.get(start_episode) or "").strip()
        if not batch_text:
            continue
        end_episode = max(start_episode, start_episode + batch_size - 1)
        entries.append(
            {
                "start_episode": start_episode,
                "end_episode": end_episode,
                "range": f"{start_episode}-{end_episode}",
                "content": batch_text,
            }
        )
    return entries


def _partial_script_artifacts_from_variables(
    *,
    total_episodes: int,
    variables: dict[str, Any] | None,
) -> dict[str, Any]:
    entries = _partial_script_entries_from_variables(
        total_episodes=total_episodes,
        variables=variables,
    )
    if not entries:
        return {}
    partial_script = _join_script_parts(*(entry["content"] for entry in entries))
    completed_episodes: list[int] = []
    for entry in entries:
        completed_episodes.extend(
            list(range(int(entry["start_episode"]), int(entry["end_episode"]) + 1))
        )
    latest = entries[-1]
    return {
        PARTIAL_SCRIPT_ARTIFACT: partial_script,
        SCRIPT_BATCHES_DISPLAY_ARTIFACT: [
            {
                "start_episode": int(entry["start_episode"]),
                "end_episode": int(entry["end_episode"]),
                "content": entry["content"],
            }
            for entry in entries
        ],
        SCRIPT_BATCH_PREVIEW_ARTIFACT: latest["content"],
        SCRIPT_BATCH_RANGE_ARTIFACT: latest["range"],
        PARTIAL_SCRIPT_EPISODES_ARTIFACT: completed_episodes,
    }


def _jsonish_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    text = str(value or "").strip()
    if not text or text[0] not in "[{":
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _character_items_from_value(value: Any) -> list[dict[str, Any]]:
    candidate = _jsonish_value(value)
    if isinstance(candidate, dict):
        nested = candidate.get("character_setting")
        if isinstance(nested, dict) and isinstance(nested.get("characters"), list):
            return [item for item in nested.get("characters") or [] if isinstance(item, dict)]
        if isinstance(candidate.get("characters"), list):
            return [item for item in candidate.get("characters") or [] if isinstance(item, dict)]
    if isinstance(candidate, list):
        return [item for item in candidate if isinstance(item, dict)]
    return []


def _scene_items_from_value(value: Any) -> list[dict[str, Any]]:
    candidate = _jsonish_value(value)
    if isinstance(candidate, dict):
        nested_wrapper = candidate.get("scenes")
        if isinstance(nested_wrapper, dict):
            nested_scene_setting = nested_wrapper.get("scene_setting")
            if isinstance(nested_scene_setting, dict) and isinstance(nested_scene_setting.get("scenes"), list):
                return [item for item in nested_scene_setting.get("scenes") or [] if isinstance(item, dict)]
        nested = candidate.get("scene_setting")
        if isinstance(nested, dict) and isinstance(nested.get("scenes"), list):
            return [item for item in nested.get("scenes") or [] if isinstance(item, dict)]
        if isinstance(candidate.get("scenes"), list):
            return [item for item in candidate.get("scenes") or [] if isinstance(item, dict)]
    if isinstance(candidate, list):
        return [item for item in candidate if isinstance(item, dict)]
    return []


def _appearance_character_items_from_value(value: Any) -> list[dict[str, Any]]:
    candidate = _jsonish_value(value)
    if isinstance(candidate, dict):
        nested = candidate.get("appearanceMapping")
        if isinstance(nested, dict) and isinstance(nested.get("characters"), list):
            return [item for item in nested.get("characters") or [] if isinstance(item, dict)]
        if isinstance(candidate.get("characters"), list):
            return [item for item in candidate.get("characters") or [] if isinstance(item, dict)]
    if isinstance(candidate, list):
        return [item for item in candidate if isinstance(item, dict)]
    return []


def _character_name_from_item(item: dict[str, Any]) -> str:
    for key in ("character_name", "canonical_name", "name", "character_id"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return "未命名角色"


def _meaningful_character_fragment(value: Any) -> str:
    text = clean_export_readable_text(value).strip().strip("，。；： ")
    if not text or _is_placeholder_like_character_text(text):
        return ""
    return text


def _character_display_summary(item: dict[str, Any]) -> str:
    snippets: list[str] = []
    role = _meaningful_character_fragment(
        item.get("story_role") or item.get("role_type") or item.get("identity")
    )
    if role:
        snippets.append(f"人物定位：{role}")
    motivation = _meaningful_character_fragment(
        item.get("core_motivation") or item.get("core_desire")
    )
    plot_function = _meaningful_character_fragment(
        item.get("plot_function") or item.get("dramatic_value")
    )
    appearance = item.get("appearance") if isinstance(item.get("appearance"), dict) else {}
    behavior = item.get("behavior") if isinstance(item.get("behavior"), dict) else {}
    appearance_text = _meaningful_character_fragment(
        appearance.get("overall_look") or item.get("appearance_anchor")
    )
    behavior_text = _meaningful_character_fragment(
        behavior.get("social_interaction_style") or item.get("personality")
    )
    short_bits = [bit for bit in (appearance_text, behavior_text, motivation, plot_function) if bit]
    if short_bits:
        snippets.append("人物小传：" + "；".join(short_bits[:4]))
    memory_point = _meaningful_character_fragment(
        item.get("entry_memory_point")
        or item.get("appearance_anchor")
        or item.get("recognizable_scene_signal")
    )
    if memory_point:
        snippets.append(f"出场记忆点：{memory_point}")
    return "\n".join(snippets).strip()


def _structured_character_display_text(value: Any) -> str:
    characters = _character_items_from_value(value)
    if not characters:
        return ""
    parts: list[str] = []
    for item in characters:
        role = str(item.get("story_role") or item.get("role_type") or "角色").strip() or "角色"
        parts.append(f"【{role}】{_character_name_from_item(item)}")
        summary = _character_display_summary(item)
        if summary:
            parts.append(summary)
        parts.append("")
    return "\n".join(parts).strip()


def _natural_text_covers_all_characters(natural_text: str, structured_value: Any) -> bool:
    characters = _character_items_from_value(structured_value)
    if len(characters) <= 1:
        return True
    normalized_text = str(natural_text or "").strip()
    if not normalized_text:
        return False
    names = [_character_name_from_item(item) for item in characters]
    return all(name and name in normalized_text for name in names)


def _character_natural_text_quality_issues(natural_text: Any, structured_value: Any) -> list[str]:
    natural = clean_export_readable_text(natural_text).strip()
    if not natural:
        return []
    issues: list[str] = []
    if not _natural_text_covers_all_characters(natural, structured_value):
        issues.append("missing_character_coverage")
        return issues

    characters = _character_items_from_value(structured_value)
    lines = [line.strip() for line in natural.replace("\r", "").split("\n") if line.strip()]
    compact_natural = re.sub(r"[\s，。；：:、,【】（）()“”\"'`·\-_/]", "", natural)
    informative_lines = [
        line
        for line in lines
        if not CHARACTER_HEADING_ONLY_PATTERN.fullmatch(line)
        and not CHARACTER_LABEL_LINE_PATTERN.fullmatch(line)
        and not _is_placeholder_like_character_text(line)
        and len(re.sub(r"[\s，。；：:、,【】（）()“”\"'`·\-_/]", "", line)) >= 10
    ]
    placeholder_matches = CHARACTER_PLACEHOLDER_PATTERN.findall(natural)
    placeholder_lines = [
        line for line in lines if CHARACTER_PLACEHOLDER_PATTERN.search(line) or _is_placeholder_like_character_text(line)
    ]
    if placeholder_matches and (
        len(placeholder_matches) >= max(2, len(characters))
        or len(placeholder_lines) >= max(2, len(lines) // 2)
    ):
        issues.append("placeholder_heavy_natural_language")

    if len(characters) > 1:
        minimum_lines = min(3, max(2, len(characters) // 2))
        if len(informative_lines) < minimum_lines:
            average_compact_chars = (
                len(compact_natural) / max(1, len(characters))
                if compact_natural
                else 0
            )
            if average_compact_chars < 12:
                issues.append("low_information_character_bios")
        unique_lines = {
            re.sub(r"\s+", "", line)
            for line in informative_lines
            if re.sub(r"\s+", "", line)
        }
        if len(informative_lines) >= 2 and len(unique_lines) <= max(1, len(informative_lines) // 2):
            issues.append("low_information_character_bios")

    deduped: list[str] = []
    for issue in issues:
        if issue not in deduped:
            deduped.append(issue)
    return deduped


def _select_character_display_text(natural_text: Any, structured_value: Any) -> tuple[str, list[str]]:
    natural = clean_export_readable_text(natural_text).strip()
    issues = _character_natural_text_quality_issues(natural, structured_value) if natural else []
    if natural and not issues:
        return natural, []
    fallback = _structured_character_display_text(structured_value)
    return fallback or natural, issues


def _preferred_character_display_text(natural_text: Any, structured_value: Any) -> str:
    return _select_character_display_text(natural_text, structured_value)[0]


def use_fastgpt_backend() -> bool:
    return settings.workflow_backend in {"fastgpt", "hybrid", "fastgpt_hybrid"}


