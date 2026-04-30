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
from .workflow_spec import WorkflowSpec
from ..utils.logger import get_logger
from ..utils.episode import (
    BatchWindow,
    build_episode_batches,
    iter_episode_batches,
    rewrite_start_validation_message,
    validate_rewrite_start_episode,
)
from ..workflow_ids import (
    APPEARANCE_ALIAS_NAMING_RULES_VAR,
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
)
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
    "appearance_mapping",
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
    APPEARANCE_MAPPING: (APPEARANCE_MAPPING_VAR,),
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
        "appearance_mapping",
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
        "appearance_mapping",
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
        "appearance_mapping",
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
        "appearance_mapping",
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
        "appearance_mapping",
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
        "appearance_mapping",
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
        "appearance_mapping",
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
        "appearance_mapping",
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
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2).strip()
        except Exception:
            return str(value).strip()
    return str(value).strip()


PLACEHOLDER_STAGE_OUTPUTS = {
    "剧本框架自然语言说明暂未生成。",
    "世界观自然语言说明暂未生成。",
    "人物设定自然语言说明暂未生成。",
    "核心场景自然语言说明暂未生成。",
}


def _meaningful_stage_output_text(value: Any) -> str:
    text = _display_text(value)
    if not text:
        return ""
    if text in PLACEHOLDER_STAGE_OUTPUTS:
        return ""
    if text in {"{}", "[]", "[object Object]"}:
        return ""
    return text


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


def _truncate_log_text(text: Any, *, max_chars: int = 500) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "..."


def clean_export_readable_text(value: Any) -> str:
    """把可能来自 JSON、markdown 或字段化文本的内容清洗成适合导出的自然语言。"""
    if value in (None, "", {}, []):
        return ""
    if isinstance(value, (dict, list)):
        parts: list[str] = []
        items = value.items() if isinstance(value, dict) else enumerate(value, start=1)
        for key, item in items:
            cleaned = clean_export_readable_text(item)
            if not cleaned:
                continue
            if isinstance(value, dict) and isinstance(key, str) and re.search(r"[\u4e00-\u9fff]", key):
                parts.append(f"{key}：{cleaned}")
            else:
                parts.append(cleaned)
        return "\n".join(part for part in parts if part).strip()

    text = _strip_export_code_fences(str(value or ""))
    parsed = _jsonish_value(text)
    if parsed is not None:
        return clean_export_readable_text(parsed)

    cleaned_lines: list[str] = []
    for raw_line in text.replace("\r", "").split("\n"):
        line = _clean_export_key_line(raw_line)
        if not line:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
        cleaned_lines.append(line)

    while cleaned_lines and cleaned_lines[0] == "":
        cleaned_lines.pop(0)
    while cleaned_lines and cleaned_lines[-1] == "":
        cleaned_lines.pop()

    paragraphs: list[str] = []
    current: list[str] = []
    for line in cleaned_lines:
        if line == "":
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(" ".join(current).strip())
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph).strip()


def _placeholder_cleaned_text(value: Any) -> str:
    return clean_export_readable_text(value).strip()


def _is_placeholder_like_character_text(value: Any) -> bool:
    text = _placeholder_cleaned_text(value)
    if not text:
        return True
    compact = re.sub(r"[\s，。；：:、,【】（）()“”\"'`·\-_/]", "", text)
    if not compact:
        return True
    if CHARACTER_HEADING_ONLY_PATTERN.fullmatch(text):
        return True
    if compact.lower() in {
        "待补全",
        "待完善",
        "未提供",
        "未补充",
        "暂无",
        "待填写",
        "待定",
        "省略",
        "tbd",
        "todo",
        "na",
        "none",
        "null",
    }:
        return True
    if CHARACTER_PLACEHOLDER_PATTERN.search(text) and len(compact) <= 18:
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
        nested = candidate.get("appearance_mapping")
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


class TaskTerminated(RuntimeError):
    pass


@dataclass(slots=True)
class TaskControl:
    pause_requested: bool = False
    terminate_requested: bool = False
    condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock())
    )

    def request_pause(self) -> None:
        with self.condition:
            self.pause_requested = True
            self.condition.notify_all()

    def request_resume(self) -> None:
        with self.condition:
            self.pause_requested = False
            self.condition.notify_all()

    def request_terminate(self) -> None:
        with self.condition:
            self.terminate_requested = True
            self.pause_requested = False
            self.condition.notify_all()

    def is_pause_requested(self) -> bool:
        with self.condition:
            return self.pause_requested

    def checkpoint(self, *, on_paused: Callable[[], None] | None = None) -> None:
        with self.condition:
            while self.pause_requested and not self.terminate_requested:
                if on_paused is not None:
                    on_paused()
                self.condition.wait(timeout=0.5)
            if self.terminate_requested:
                raise TaskTerminated("任务已终止")


@dataclass(slots=True)
class TaskRecord:
    user_id: int
    project_id: int
    task_id: str
    workflow_spec_path: str
    input_payload: dict[str, Any]
    model_option: ModelOption | None
    snapshot: dict[str, Any]
    control: TaskControl = field(default_factory=TaskControl)
    thread: threading.Thread | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)
    resume_snapshot: dict[str, Any] | None = None

    def clone_snapshot(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self.snapshot)


class WorkflowRuntime:
    def __init__(
        self,
        *,
        manager: "TaskManager",
        record: TaskRecord,
        spec: WorkflowSpec | None,
    ) -> None:
        self.manager = manager
        self.record = record
        self.spec = spec

    def checkpoint(self) -> None:
        def _mark_paused() -> None:
            snapshot = self.record.clone_snapshot()
            if snapshot.get("status") != "paused":
                self.manager._update_snapshot(
                    self.record,
                    status="paused",
                    message="已暂停，等待继续。",
                )

        if self.record.control.is_pause_requested():
            _mark_paused()
        self.record.control.checkpoint(on_paused=_mark_paused)
        if self.record.clone_snapshot().get("status") in {"paused", "pausing"}:
            self.manager._update_snapshot(
                self.record,
                status="running",
                message="已继续执行。",
            )

    def set_stage(
        self,
        stage_key: str,
        message: str,
        *,
        batch_label: str | None = None,
        progress_percent: int | None = None,
        generated_episodes: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "current_stage": stage_key,
            "current_stage_label": STAGE_LABELS.get(stage_key, stage_key),
            "message": message,
            "current_batch": str(batch_label).strip() if batch_label else None,
        }
        if progress_percent is not None:
            payload["progress_percent"] = max(0, min(100, int(progress_percent)))
        if generated_episodes is not None:
            payload["generated_episodes"] = max(0, int(generated_episodes))
        self.manager._update_snapshot(self.record, **payload)

    def before_node(self, node_id: str, state: WorkflowState) -> None:
        self.checkpoint()
        node_name = self.spec.get_node_name(node_id) if self.spec else node_id
        self.manager._append_log(
            self.record,
            title=f"开始节点：{node_name}",
            message=f"{node_id} 正在执行。",
            node_id=node_id,
        )
        self.manager._update_snapshot(
            self.record,
            status="running",
            current_node_id=node_id,
            current_node_name=node_name,
            message=f"正在执行：{node_name}",
        )
        self.sync_from_state(state)

    def after_node(self, node_id: str, state: WorkflowState, output_text: str) -> None:
        node_name = self.spec.get_node_name(node_id) if self.spec else node_id
        preview = str(output_text or "").strip().replace("\n", " ")[:180]
        self.manager._append_log(
            self.record,
            title=f"完成节点：{node_name}",
            message=preview or "节点已完成。",
            node_id=node_id,
        )
        self.sync_from_state(state)
        self.checkpoint()

    def fastgpt_stage_started(
        self,
        stage_label: str,
        *,
        batch_label: str | None = None,
        attempt: int = 1,
    ) -> None:
        self.checkpoint()
        batch_text = f" {batch_label} 集" if batch_label else ""
        self.manager._append_log(
            self.record,
            title=f"{stage_label}{batch_text}",
            message=f"第 {attempt} 次尝试",
            node_id=f"fastgpt:{stage_label}",
        )

    def fastgpt_stage_finished(
        self,
        stage_label: str,
        *,
        batch_label: str | None = None,
        output: dict[str, Any],
    ) -> None:
        batch_text = f" {batch_label} 集" if batch_label else ""
        self.manager._append_log(
            self.record,
            title=f"{stage_label}{batch_text} 已完成",
            message=_summarize_fastgpt_output(output),
            node_id=f"fastgpt:{stage_label}",
        )

    def sync_from_state(self, state: WorkflowState) -> None:
        script_title_content = str(state.get_var(TITLE_VAR, "") or "").strip()
        final_script_text = _resolve_best_script_text(
            total_episodes=_safe_int(getattr(state.user_input, "total_episodes", 0), 0),
            artifacts={},
            variables=state.variables,
            final_output_text=state.final_output_text,
        )
        if not final_script_text:
            final_script_text = str(
                state.final_output_text
                or state.get_var(FINAL_SCRIPT, "")
                or state.get_var(SCRIPT_FINAL_VAR, "")
                or ""
            ).strip()
        raw_character_natural_language = str(
            state.get_var(CHARACTER_NATURAL_LANGUAGE_VAR, "") or ""
        ).strip()
        character_natural_language, character_natural_language_issues = _select_character_display_text(
            raw_character_natural_language,
            state.get_var(CHARACTER_VAR, ""),
        )
        if raw_character_natural_language and character_natural_language_issues:
            logger.warning(
                "character_natural_language_rejected issues=%s preview=%s",
                ",".join(character_natural_language_issues),
                _truncate_log_text(raw_character_natural_language, max_chars=240),
            )
        appearance_natural_language = str(
            state.get_var(APPEARANCE_NATURAL_LANGUAGE_VAR, "") or ""
        ).strip()
        scene_natural_language = str(
            state.get_var(SCENE_NATURAL_LANGUAGE_VAR, "") or ""
        ).strip()
        structured_characters = state.get_var(CHARACTER_VAR, "")
        structured_scenes = state.get_var(SCENE_VAR, "")
        partial_script_artifacts = _partial_script_artifacts_from_variables(
            total_episodes=_safe_int(getattr(state.user_input, "total_episodes", 0), 0),
            variables=state.variables,
        )
        artifacts = {
            "script_title_content": script_title_content,
            "framework_natural_language": state.get_var(FRAMEWORK_NATURAL_LANGUAGE, ""),
            "story_outline": state.get_var(STORY_OUTLINE_VAR, ""),
            "character_bios": state.get_var(CHARACTER_BIOS_VAR, ""),
            "episode_plan": state.get_var(EPISODE_PLAN_VAR, ""),
            "normalized_episode_plan": state.get_var(NORMALIZED_EPISODE_PLAN, ""),
            "worldview": state.get_var(WORLDVIEW_VAR, ""),
            "worldview_natural_language": state.get_var(WORLDVIEW_NATURAL_LANGUAGE, ""),
            "characters": structured_characters,
            "character_natural_language": character_natural_language,
            "character_summary": character_natural_language,
            "scene_json": structured_scenes,
            "scene_natural_language": scene_natural_language,
            "core_scene_input": state.get_var(
                SCENE_NATURAL_LANGUAGE_VAR,
                state.get_var(CORE_SCENE_INPUT_VAR, ""),
            ),
            "core_scene_summary": scene_natural_language,
            "character_appearance_requirements": state.get_var(CHARACTER_APPEARANCE_REQUIREMENTS, ""),
            "character_alias_naming_rules": state.get_var(CHARACTER_ALIAS_NAMING_RULES, ""),
            "outfit_switch_rules": state.get_var(OUTFIT_SWITCH_RULES, ""),
            "appearance_mapping": state.get_var(APPEARANCE_MAPPING, ""),
            APPEARANCE_NATURAL_LANGUAGE_ARTIFACT: appearance_natural_language,
            "character_registry": state.get_var(CHARACTER_REGISTRY, ""),
            "character_alias_registry": state.get_var(CHARACTER_ALIAS_REGISTRY, ""),
            "episode_alias_plan": state.get_var(EPISODE_ALIAS_PLAN, ""),
            "appearance_continuity_memory": state.get_var(APPEARANCE_CONTINUITY_MEMORY, ""),
            "hook_plan": state.get_var(HOOK_FINAL_VAR, ""),
            "dialogue_plan": state.get_var(DIALOGUE_FINAL_VAR, ""),
            "script_batch": state.get_var(SCRIPT_CURRENT_VAR, ""),
            "final_script": final_script_text,
            "continuity_memory": state.get_var(MEMORY_VAR, ""),
            "halted_message": state.halted_message or "",
            "final_output_text": final_script_text,
        }
        artifacts.update(partial_script_artifacts)
        # artifacts 面向前端展示与导出，debug_state 面向恢复/回退。
        # 两份都要同步：前者保证用户能立刻看到正式成品，后者保证失败后能从真实执行状态继续。
        self.manager._update_snapshot(
            self.record,
            title=script_title_content or self.record.snapshot.get("title") or "未命名剧本",
            artifacts=artifacts,
            debug_state=state.as_debug_dict(),
            prompt_fixes=state.prompt_fixes,
        )
        self.manager._save_resume_checkpoint(self.record)


class TaskManager:
    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parents[2] / "runtime_data"
        self.projects_dir = self.base_dir / "projects"
        self.exports_dir = self.base_dir / "exports"
        self.index_path = self.base_dir / "index.json"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._tasks: dict[str, TaskRecord] = {}
        self._projects: dict[int, TaskRecord] = {}
        self._index = self._load_index()
        self._repair_persisted_snapshots()

    def _load_index(self) -> dict[str, Any]:
        if self.index_path.exists():
            try:
                return json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        data = {"next_project_id": 1, "latest_project_id": None}
        self._save_index(data)
        return data

    def _save_index(self, data: dict[str, Any] | None = None) -> None:
        payload = data or self._index
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _repair_persisted_snapshots(self) -> None:
        for path in self.projects_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            changed = False
            if data.get("status") in PROJECT_RUNNING_STATUSES:
                data["status"] = "terminated"
                data["message"] = TERMINATED_PUBLIC_MESSAGE
                data["updated_at"] = now_iso()
                changed = True
            elif str(data.get("status") or "") == "failed":
                if str(data.get("message") or "").strip() != FAILED_PUBLIC_MESSAGE:
                    data["message"] = FAILED_PUBLIC_MESSAGE
                    data["updated_at"] = now_iso()
                    changed = True
            elif str(data.get("status") or "") == "terminated":
                if str(data.get("message") or "").strip() != TERMINATED_PUBLIC_MESSAGE:
                    data["message"] = TERMINATED_PUBLIC_MESSAGE
                    data["updated_at"] = now_iso()
                    changed = True
            elif str(data.get("status") or "") == "completed":
                if "completion_confirmed" not in data:
                    data["completion_confirmed"] = True
                    data["awaiting_user_confirmation"] = False
                    data["cache_retained"] = False
                    changed = True
                if _completion_confirmed(data):
                    compacted = self._compact_completed_snapshot(data)
                    if compacted != data:
                        data = compacted
                        changed = True
                else:
                    if not _awaiting_completion_confirmation(data):
                        data["awaiting_user_confirmation"] = True
                        changed = True
                    if not data.get("cache_retained"):
                        data["cache_retained"] = True
                        changed = True
                    if str(data.get("message") or "").strip() != COMPLETION_PENDING_MESSAGE:
                        data["message"] = COMPLETION_PENDING_MESSAGE
                        changed = True
            if changed:
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    def _project_path(self, project_id: int) -> Path:
        return self.projects_dir / f"{project_id}.json"

    def _persist_snapshot(self, record: TaskRecord) -> None:
        path = self._project_path(record.project_id)
        with record.lock:
            if bool(record.snapshot.get("_deleted")):
                return
            path.write_text(
                json.dumps(record.snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _build_resume_checkpoint(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        checkpoint = copy.deepcopy(snapshot)
        # 恢复快照只保留“可继续执行所需的稳定状态”；
        # 错误文案、结束时间和滚动日志属于一次性运行痕迹，不应污染下一次继续生成。
        checkpoint.pop("_resume_checkpoint", None)
        checkpoint.pop("logs", None)
        checkpoint.pop("error", None)
        checkpoint.pop("finished_at", None)
        return checkpoint

    def _save_resume_checkpoint(self, record: TaskRecord) -> None:
        with record.lock:
            record.snapshot["_resume_checkpoint"] = self._build_resume_checkpoint(record.snapshot)
        self._persist_snapshot(record)

    def _restore_from_resume_checkpoint(self, record: TaskRecord) -> None:
        checkpoint = record.clone_snapshot().get("_resume_checkpoint")
        if not isinstance(checkpoint, dict):
            return
        fields_to_restore = (
            "title",
            "artifacts",
            "debug_state",
            "prompt_fixes",
            "input_payload",
            "workflow_spec_path",
            "model_option",
            "total_episodes",
            "progress_percent",
            "generated_episodes",
            "current_stage",
            "current_stage_label",
            "current_node_id",
            "current_node_name",
            "current_batch",
        )
        restored = self._build_resume_checkpoint(checkpoint)
        with record.lock:
            for key in fields_to_restore:
                if key in restored:
                    record.snapshot[key] = copy.deepcopy(restored[key])
            record.snapshot["_resume_checkpoint"] = restored
            record.snapshot["updated_at"] = now_iso()
        self._persist_snapshot(record)

    def _append_log(
        self,
        record: TaskRecord,
        *,
        title: str,
        message: str,
        node_id: str | None = None,
    ) -> None:
        with record.lock:
            logs = list(record.snapshot.get("logs", []))
            logs.append(
                {
                    "time": now_iso(),
                    "title": title,
                    "message": message,
                    "node_id": node_id,
                }
            )
            record.snapshot["logs"] = logs[-200:]
            record.snapshot["updated_at"] = now_iso()
        self._persist_snapshot(record)

    def _update_snapshot(self, record: TaskRecord, **changes: Any) -> None:
        with record.lock:
            previous_status = record.snapshot.get("status")
            if "artifacts" in changes and isinstance(changes["artifacts"], dict):
                merged_artifacts = dict(record.snapshot.get("artifacts", {}))
                merged_artifacts.update(changes.pop("artifacts"))
                record.snapshot["artifacts"] = merged_artifacts

            record.snapshot.update(changes)
            current_time = now_iso()
            current_status = record.snapshot.get("status", previous_status)
            _sync_wait_tracking(
                record.snapshot,
                previous_status=previous_status,
                current_status=current_status,
                current_time_iso=current_time,
            )
            record.snapshot["updated_at"] = current_time
        self._persist_snapshot(record)

    def _next_project_id(self) -> int:
        with self._lock:
            project_id = int(self._index.get("next_project_id", 1))
            self._index["next_project_id"] = project_id + 1
            self._index["latest_project_id"] = project_id
            self._save_index()
            return project_id

    def _remember_latest_project(self, user_id: int, project_id: int) -> None:
        with self._lock:
            latest_by_user = dict(self._index.get("latest_project_by_user", {}))
            latest_by_user[str(int(user_id))] = int(project_id)
            self._index["latest_project_by_user"] = latest_by_user
            self._index["latest_project_id"] = int(project_id)
            self._save_index()

    def _snapshot_belongs_to_user(
        self,
        snapshot: dict[str, Any] | None,
        user_id: int | None,
    ) -> bool:
        if snapshot is None:
            return False
        if user_id is None:
            return True
        return int(snapshot.get("user_id") or 0) == int(user_id)

    def _public_input_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return _select_non_empty_fields(
            snapshot.get("input_payload") or {},
            PUBLIC_INPUT_PAYLOAD_KEYS,
        )

    def _public_artifacts(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """只把前端允许展示的正式产物挑出来，避免中间变量泄露。"""
        allowed_keys = list(PUBLIC_ARTIFACT_KEYS)
        if str(snapshot.get("status") or "") == "completed":
            allowed_keys.extend(PUBLIC_COMPLETED_ARTIFACT_KEYS)
        raw_artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        artifacts = _select_non_empty_fields(
            raw_artifacts,
            tuple(allowed_keys),
        )
        debug_variables = (
            (snapshot.get("debug_state") or {}).get("variables")
            if isinstance(snapshot.get("debug_state"), dict)
            else {}
        )
        if not isinstance(debug_variables, dict):
            debug_variables = {}
        structured_characters = (
            debug_variables.get(CHARACTERS)
            or raw_artifacts.get("characters")
            or raw_artifacts.get(CHARACTER_VAR)
            or ""
        )
        for key in (
            "framework_natural_language",
            "worldview_natural_language",
        ):
            text = _meaningful_stage_output_text(artifacts.get(key))
            if text:
                artifacts[key] = text
            else:
                artifacts.pop(key, None)
        episode_plan_display = self._episode_plan_display_text(snapshot, snapshot.get("artifacts") or {})
        if episode_plan_display:
            artifacts[EPISODE_PLAN_DISPLAY_ARTIFACT] = episode_plan_display
        if str(snapshot.get("status") or "") != "completed":
            artifacts.update(
                _partial_script_artifacts_from_variables(
                    total_episodes=_safe_int(snapshot.get("total_episodes"), 0),
                    variables=debug_variables,
                )
            )
        return artifacts

    def _episode_plan_display_text(
        self,
        snapshot: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> str:
        raw_episode_plan = artifacts.get("episode_plan")
        if raw_episode_plan in (None, "", {}, []):
            return ""
        parsed = self._parse_episode_plan_display_json(raw_episode_plan)
        if parsed is None:
            return _display_text(raw_episode_plan)

        display_text = self._fallback_episode_plan_display(parsed)
        return display_text or self._episode_plan_display_json_text(parsed) or _display_text(raw_episode_plan)

    def _parse_episode_plan_display_json(self, raw_episode_plan: Any) -> Any | None:
        if isinstance(raw_episode_plan, (dict, list)):
            return copy.deepcopy(raw_episode_plan)
        text = str(raw_episode_plan or "").strip()
        if not text or text[0] not in "[{":
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        if isinstance(parsed, (dict, list)):
            return parsed
        return None

    def _episode_plan_display_json_text(self, parsed: Any) -> str:
        if isinstance(parsed, dict):
            nested_episode_plan = parsed.get("episode_plan")
            if isinstance(nested_episode_plan, str):
                nested_parsed = self._parse_episode_plan_display_json(nested_episode_plan)
                if nested_parsed is not None:
                    return self._episode_plan_display_json_text(nested_parsed)
        try:
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            return ""

    def _episode_plan_display_source_text(self, parsed: Any) -> str:
        if isinstance(parsed, dict):
            nested_episode_plan = parsed.get("episode_plan")
            if isinstance(nested_episode_plan, str):
                nested_parsed = self._parse_episode_plan_display_json(nested_episode_plan)
                if nested_parsed is not None:
                    return self._episode_plan_display_source_text(nested_parsed)
            if isinstance(parsed.get("episodes"), list):
                parts: list[str] = []
                for item in parsed.get("episodes") or []:
                    if not isinstance(item, dict):
                        continue
                    episode_no = _safe_int(item.get("episode"), 0)
                    if episode_no <= 0:
                        continue
                    title = str(item.get("title") or "").strip()
                    content = str(item.get("content") or "").strip()
                    section = f"第{episode_no}集"
                    if title:
                        section += f"《{title}》"
                    if content:
                        section += f"\n{content}"
                    parts.append(section)
                if parts:
                    return "\n\n".join(parts)
        if isinstance(parsed, list):
            parts = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                episode_no = _safe_int(
                    item.get("episode")
                    or item.get("episode_no")
                    or item.get("episodeNumber"),
                    0,
                )
                title = str(item.get("title") or "").strip()
                content = str(item.get("content") or item.get("summary") or "").strip()
                if episode_no <= 0 and not content:
                    continue
                section = f"第{episode_no}集" if episode_no > 0 else "分集内容"
                if title:
                    section += f"《{title}》"
                if content:
                    section += f"\n{content}"
                parts.append(section)
            if parts:
                return "\n\n".join(parts)
        return ""

    def _generate_episode_plan_display(self, source_text: str) -> str:
        """不再额外调用模型润色分集计划展示，统一走本地回退整理。"""
        return ""

    def _fallback_episode_plan_display(self, parsed: Any) -> str:
        text = self._episode_plan_display_source_text(parsed)
        if not text:
            return ""
        return text

    def _cache_episode_plan_display(
        self,
        snapshot: dict[str, Any],
        display_text: str,
        text_hash: str,
    ) -> None:
        project_id = int(snapshot.get("project_id") or 0)
        if project_id <= 0 or not display_text:
            return
        artifacts_update = {
            EPISODE_PLAN_DISPLAY_ARTIFACT: display_text,
            EPISODE_PLAN_DISPLAY_SOURCE_HASH_ARTIFACT: text_hash,
        }
        record = self._projects.get(project_id)
        if record is not None:
            self._update_snapshot(record, artifacts=artifacts_update)
            snapshot.setdefault("artifacts", {}).update(artifacts_update)
            return

        persisted = copy.deepcopy(snapshot)
        persisted.setdefault("artifacts", {}).update(artifacts_update)
        self._project_path(project_id).write_text(
            json.dumps(persisted, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        snapshot.setdefault("artifacts", {}).update(artifacts_update)

    def _available_rollback_stage_options(self, snapshot: dict[str, Any]) -> list[tuple[str, str]]:
        """只返回当前项目已经走到的阶段，避免前端展示未来还没执行的回退选项。"""
        max_index = self._max_reached_rollback_stage_index(snapshot)
        if max_index < 0:
            return []
        return list(ROLLBACK_STAGE_OPTIONS[: max_index + 1])

    def _max_reached_rollback_stage_index(self, snapshot: dict[str, Any]) -> int:
        """根据正式产物、缓存变量和当前阶段，推断用户真正已经到达的最深阶段。"""
        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        debug_state = snapshot.get("debug_state") if isinstance(snapshot.get("debug_state"), dict) else {}
        variables = debug_state.get("variables") if isinstance(debug_state.get("variables"), dict) else {}

        reached: set[str] = set()
        if any(str(artifacts.get(key) or "").strip() for key in ("script_title_content", "story_outline", "character_bios", "core_scene_input", "episode_plan")):
            reached.add("framework")
        if any(str(variables.get(key) or "").strip() for key in (
            USER_CONTENT_BASELINE,
            CHARACTER_APPEARANCE_REQUIREMENTS,
            CHARACTER_ALIAS_NAMING_RULES,
            OUTFIT_SWITCH_RULES,
        )):
            reached.add("appearance_strategy")
        if variables.get(IS_CONSISTENT) is not None:
            reached.add("consistency")
        if variables.get(NORMALIZED_EPISODE_PLAN):
            reached.add("episode_plan_normalize")
        if str(artifacts.get("worldview") or "").strip():
            reached.add("worldview")
        if any(
            str(artifacts.get(key) or "").strip()
            for key in ("character_natural_language", "character_summary")
        ) or any(
            str(variables.get(key) or "").strip()
            for key in (CHARACTERS, CHARACTER_NATURAL_LANGUAGE_VAR)
        ):
            reached.add("characters")
        if any(
            str(artifacts.get(key) or "").strip()
            for key in ("scene_natural_language", "core_scene_summary", "scene_json")
        ) or any(
            str(variables.get(key) or "").strip()
            for key in (SCENES, SCENE_NATURAL_LANGUAGE_VAR)
        ):
            reached.add("scenes")
        if variables.get(APPEARANCE_MAPPING):
            reached.add("appearance")
        if variables.get(ALL_HOOKS) or variables.get(BATCH_HOOKS):
            reached.add("hooks")
        if variables.get(ALL_DIALOGUES) or variables.get(BATCH_DIALOGUES):
            reached.add("dialogues")
        if variables.get(ALL_SCRIPT) or variables.get(BATCH_SCRIPT):
            reached.add("script")
        if any(str(artifacts.get(key) or "").strip() for key in ("final_output_text", "final_script")):
            reached.add("final")

        current_stage = self._snapshot_stage_to_rollback_stage(snapshot, variables)
        if current_stage:
            reached.add(current_stage)

        indexes = [index for index, (key, _) in enumerate(ROLLBACK_STAGE_OPTIONS) if key in reached]
        current_stage_index = _rollback_stage_index(current_stage)
        if current_stage_index >= 0:
            indexes = [index for index in indexes if index <= current_stage_index]
        return max(indexes) if indexes else -1

    def _snapshot_stage_to_rollback_stage(
        self,
        snapshot: dict[str, Any],
        variables: dict[str, Any],
    ) -> str:
        """把运行时阶段名映射成回退阶段名，保证前后端对阶段理解一致。"""
        batch_stage = _normalize_rollback_stage_key(variables.get(LOCAL_CURRENT_BATCH_STAGE))
        rewrite_stage = _normalize_rollback_stage_key(variables.get(LOCAL_REWRITE_FROM_STAGE))
        for candidate in (batch_stage, rewrite_stage):
            if candidate in {"hooks", "dialogues", "script"}:
                return candidate

        current_stage = str(snapshot.get("current_stage") or "").strip().lower()
        if current_stage == "validation":
            return "episode_plan_normalize" if variables.get(NORMALIZED_EPISODE_PLAN) else "consistency"
        mapping = {
            "framework": "framework",
            "framework_naturalize": "framework",
            "appearance_strategy": "appearance_strategy",
            "appearance_pre_strategy": "appearance_strategy",
            "consistency": "consistency",
            "episode_plan_normalize": "episode_plan_normalize",
            "worldview": "worldview",
            "worldview_naturalize": "worldview",
            "character": "characters",
            "characters": "characters",
            "scene": "scenes",
            "scenes": "scenes",
            "appearance": "appearance",
            "appearance_alias_generation": "appearance",
            "appearance_alias_writing": "appearance",
            "appearance_alias_review": "appearance",
            "appearance_alias_rewrite": "appearance",
            "appearance_alias_unstructured": "appearance",
            "hook": "hooks",
            "hooks": "hooks",
            "hooks_writing": "hooks",
            "hook_write": "hooks",
            "hooks_review": "hooks",
            "hook_review": "hooks",
            "hooks_rewrite": "hooks",
            "hook_revise": "hooks",
            "hook_memory": "hooks",
            "dialogue": "dialogues",
            "dialogues": "dialogues",
            "dialogues_writing": "dialogues",
            "dialogue_write": "dialogues",
            "dialogues_review": "dialogues",
            "dialogue_review": "dialogues",
            "dialogues_rewrite": "dialogues",
            "dialogue_revise": "dialogues",
            "dialogue_memory": "dialogues",
            "script": "script",
            "script_writing": "script",
            "script_write": "script",
            "script_review": "script",
            "script_rewrite": "script",
            "script_revise": "script",
            "script_memory": "script",
            "memory": "script",
            "finalize": "final",
            "final": "final",
            "finished": "final",
        }
        mapped_stage = mapping.get(current_stage, "")
        if rewrite_stage in ROLLBACK_STAGE_LABELS:
            rewrite_index = _rollback_stage_index(rewrite_stage)
            mapped_index = _rollback_stage_index(mapped_stage)
            if rewrite_index >= 0 and (mapped_index < 0 or rewrite_index < mapped_index):
                return rewrite_stage
        return mapped_stage or rewrite_stage or batch_stage or ""

    def _current_stage_display_payload(
        self,
        snapshot: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> dict[str, str]:
        """只挑用户需要看的正式阶段内容，并补一段自然语言版摘要减轻等待焦虑。"""
        raw_artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        partial_script_output = _display_text(
            artifacts.get(PARTIAL_SCRIPT_ARTIFACT)
            or raw_artifacts.get(PARTIAL_SCRIPT_ARTIFACT)
        )
        final_stage_output = _display_text(
            artifacts.get("final_output_text")
            or artifacts.get("final_script")
            or raw_artifacts.get("final_output_text")
            or raw_artifacts.get("final_script")
            or partial_script_output
        )
        stage_order = ("framework", "worldview", "final")
        stage_title_map = {
            "framework": "剧本框架",
            "worldview": "世界观",
            "final": (
                "已生成正文"
                if str(snapshot.get("status") or "") != "completed" and partial_script_output
                else "最终剧本"
            ),
        }
        stage_outputs = {
            "framework": self._framework_stage_output_text(raw_artifacts),
            "worldview": self._worldview_stage_output_text(raw_artifacts),
            "final": final_stage_output,
        }

        current_stage = self._snapshot_stage_to_rollback_stage(
            snapshot,
            (snapshot.get("debug_state") or {}).get("variables") if isinstance(snapshot.get("debug_state"), dict) else {},
        )
        stage_ceiling_map = {
            "framework": "framework",
            "appearance_strategy": "framework",
            "consistency": "framework",
            "episode_plan_normalize": "framework",
            "worldview": "worldview",
            "characters": "worldview",
            "scenes": "worldview",
            "appearance": "worldview",
            "hooks": "worldview",
            "dialogues": "worldview",
            "script": "final",
            "final": "final",
        }
        ceiling_stage = stage_ceiling_map.get(current_stage, "framework")
        ceiling_index = stage_order.index(ceiling_stage)

        chosen_stage = ""
        for stage_key in reversed(stage_order[: ceiling_index + 1]):
            if stage_outputs.get(stage_key):
                chosen_stage = stage_key
                break
        if not chosen_stage and not current_stage:
            for stage_key in stage_order:
                if stage_outputs.get(stage_key):
                    chosen_stage = stage_key
                    break
        if not chosen_stage:
            return {
                "stage_key": "",
                "stage_title": "当前阶段输出",
                "output": "",
                "natural_output": "",
            }

        raw_output = stage_outputs[chosen_stage]
        natural_output = self._stage_preview_text(
            snapshot,
            stage_key=chosen_stage,
            stage_title=stage_title_map[chosen_stage],
            raw_output=raw_output,
        )
        return {
            "stage_key": chosen_stage,
            "stage_title": stage_title_map[chosen_stage],
            "output": raw_output,
            "natural_output": natural_output,
        }

    def _framework_stage_output_text(self, artifacts: dict[str, Any]) -> str:
        return _meaningful_stage_output_text(artifacts.get("framework_natural_language"))

    def _worldview_stage_output_text(self, artifacts: dict[str, Any]) -> str:
        return _meaningful_stage_output_text(artifacts.get("worldview_natural_language"))

    def _character_stage_output_text(
        self,
        snapshot: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> str:
        raw_artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        natural = _display_text(
            artifacts.get("character_natural_language")
            or artifacts.get("character_summary")
            or raw_artifacts.get("character_natural_language")
            or raw_artifacts.get("character_summary")
        )
        return _meaningful_stage_output_text(natural)

    def _scene_stage_output_text(
        self,
        snapshot: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> str:
        raw_artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        natural = _display_text(
            artifacts.get("scene_natural_language")
            or artifacts.get("core_scene_summary")
            or raw_artifacts.get("scene_natural_language")
            or raw_artifacts.get("core_scene_summary")
        )
        return _meaningful_stage_output_text(natural)

    def _stage_preview_text(
        self,
        snapshot: dict[str, Any],
        *,
        stage_key: str,
        stage_title: str,
        raw_output: str,
    ) -> str:
        """阶段展示只走本地格式化，不再额外触发展示摘要调用。"""
        text = str(raw_output or "").strip()
        if not text:
            return ""
        return self._fallback_stage_preview(stage_title, text)

    def _hash_text(self, value: str) -> str:
        """用内容哈希判断阶段产物是否变化，避免重复生成摘要。"""
        return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()

    def _generate_stage_preview(self, stage_title: str, raw_output: str) -> str:
        """保留接口位置，但不再额外调用模型生成阶段摘要。"""
        return ""

    def _preview_source_text(self, raw_output: str) -> str:
        """把阶段原文裁成适合摘要模型理解的长度，避免长正文拖慢详情接口。"""
        text = str(raw_output or "").strip()
        if len(text) <= 6000:
            return text
        head = text[:3600].strip()
        tail = text[-1800:].strip()
        if not tail:
            return head
        return f"{head}\n\n【后段摘要参考】\n{tail}"

    def _fallback_stage_preview(self, stage_title: str, raw_output: str) -> str:
        """模型不可用时，给用户一段稳定的本地说明，避免输出区域空白。"""
        condensed = " ".join(str(raw_output or "").replace("\r", "\n").split())
        if not condensed:
            return ""
        return f"当前展示的是{stage_title}阶段"

    def _cache_stage_preview(
        self,
        snapshot: dict[str, Any],
        *,
        stage_key: str,
        text_hash: str,
        preview: str,
    ) -> None:
        """把阶段摘要写回项目快照，减少轮询时的重复计算。"""
        project_id = int(snapshot.get("project_id") or 0)
        if project_id <= 0 or not preview:
            return
        artifacts_update = {
            STAGE_PREVIEW_TEXT_ARTIFACT: preview,
            STAGE_PREVIEW_STAGE_ARTIFACT: stage_key,
            STAGE_PREVIEW_SOURCE_HASH_ARTIFACT: text_hash,
        }
        record = self._projects.get(project_id)
        if record is not None:
            self._update_snapshot(record, artifacts=artifacts_update)
            snapshot.setdefault("artifacts", {}).update(artifacts_update)
            return
        persisted = copy.deepcopy(snapshot)
        persisted.setdefault("artifacts", {}).update(artifacts_update)
        self._project_path(project_id).write_text(
            json.dumps(persisted, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        snapshot.setdefault("artifacts", {}).update(artifacts_update)

    def _public_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """把内部任务快照裁成安全、简洁、适合前端直接消费的公开视图。"""
        artifacts = self._public_artifacts(snapshot)
        completion_confirmed = _completion_confirmed(snapshot)
        awaiting_confirmation = _awaiting_completion_confirmation(snapshot)
        can_stage_rollback = _can_stage_rollback(snapshot)
        display_payload = self._current_stage_display_payload(snapshot, artifacts)
        progress_metrics = self._snapshot_progress_metrics(snapshot)
        rollback_stage_default, rollback_start_episode_default = self._rollback_defaults(snapshot)
        rollback_stage_start_options = (
            self._rollback_stage_start_options(snapshot) if can_stage_rollback else {}
        )
        rollback_script_start_options = rollback_stage_start_options.get("script", [])
        rollback_stage_options = self._available_rollback_stage_options(snapshot) if can_stage_rollback else []
        payload: dict[str, Any] = {
            "project_id": snapshot.get("project_id"),
            "task_id": snapshot.get("task_id"),
            "status": snapshot.get("status"),
            "title": snapshot.get("title") or artifacts.get("script_title_content") or "未命名剧本",
            "message": _public_status_message(snapshot),
            "created_at": snapshot.get("created_at"),
            "updated_at": snapshot.get("updated_at"),
            "finished_at": snapshot.get("finished_at"),
            "wait_elapsed_ms": _safe_int(snapshot.get("wait_elapsed_ms"), 0),
            "wait_started_at": snapshot.get("wait_started_at"),
            "visibility": snapshot.get("visibility") or "private",
            "input_payload": self._public_input_payload(snapshot),
            "artifacts": artifacts,
            "progress_percent": progress_metrics["progress_percent"],
            "generated_episodes": progress_metrics["generated_episodes"],
            "total_episodes": int(snapshot.get("total_episodes") or 0),
            "current_stage": snapshot.get("current_stage"),
            "current_stage_label": snapshot.get("current_stage_label") or "待开始",
            "current_batch": snapshot.get("current_batch"),
            "completion_confirmed": completion_confirmed,
            "awaiting_user_confirmation": awaiting_confirmation,
            "cache_retained": bool(snapshot.get("cache_retained", False) or awaiting_confirmation),
            "cache_notice": _cache_notice(snapshot),
            "can_confirm_completion": awaiting_confirmation,
            "can_stage_rollback": can_stage_rollback,
            "rollback_stage_options": [
                {"key": key, "label": label} for key, label in rollback_stage_options
            ] if can_stage_rollback else [],
            "rollback_stage_default": rollback_stage_default if can_stage_rollback else "",
            "rollback_stage_start_options": rollback_stage_start_options if can_stage_rollback else {},
            "rollback_script_start_options": rollback_script_start_options,
            "rollback_start_episode_default": rollback_start_episode_default if can_stage_rollback else None,
            "rollback_stage_dependencies": {
                stage_key: list(dependencies)
                for stage_key, dependencies in ROLLBACK_STAGE_DEPENDENCIES.items()
            } if can_stage_rollback else {},
            "display_stage_key": display_payload["stage_key"],
            "display_stage_title": display_payload["stage_title"],
            "display_stage_output": display_payload["output"],
            "display_stage_output_natural": display_payload["natural_output"],
            "has_final": bool(
                str(artifacts.get("final_output_text") or artifacts.get("final_script") or "").strip()
            ),
        }
        # 有意不把 debug_state / logs / 内部控制位直接暴露给前端。
        # 前端只看正式字段，避免中间变量、节点回显和恢复指针泄漏到公开接口。
        return payload

    def _rollback_stage_start_options(
        self,
        snapshot: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            stage_key: self._batched_stage_rollback_start_options(snapshot, stage_key)
            for stage_key in ("hooks", "dialogues", "script")
        }

    def _batched_stage_rollback_start_options(
        self,
        snapshot: dict[str, Any],
        stage_key: str,
    ) -> list[dict[str, Any]]:
        normalized_stage = _normalize_rollback_stage_key(stage_key)
        if normalized_stage == "script":
            return self._script_rollback_start_options(snapshot)
        if normalized_stage not in {"hooks", "dialogues"}:
            return []

        debug_state = snapshot.get("debug_state") or {}
        variables = debug_state.get("variables") if isinstance(debug_state, dict) else {}
        if not isinstance(variables, dict):
            variables = {}

        total_episodes = int(snapshot.get("total_episodes") or 0)
        batch_size = max(1, int(settings.batch_size or 5))
        if total_episodes <= 0:
            return []

        batches = list(iter_episode_batches(total_episodes, batch_size=batch_size))
        valid_batch_starts = {batch.start_episode for batch in batches}
        interrupted_start = self._interrupted_batch_start_episode(snapshot)
        next_unfinished = (
            self._next_unfinished_object_batch_start(variables.get(ALL_HOOKS), batches)
            if normalized_stage == "hooks"
            else self._next_unfinished_object_batch_start(variables.get(ALL_DIALOGUES), batches)
        )

        candidate_starts = [batch.start_episode for batch in batches if batch.start_episode < next_unfinished]
        if next_unfinished in valid_batch_starts:
            candidate_starts.append(next_unfinished)
        if interrupted_start in valid_batch_starts:
            candidate_starts.append(interrupted_start)
        if not candidate_starts and batches:
            candidate_starts = [batches[0].start_episode]

        return [
            self._build_rollback_start_option(
                normalized_stage,
                total_episodes=total_episodes,
                start_episode=start_episode,
            )
            for start_episode in sorted(set(candidate_starts))
        ]

    def _build_rollback_start_option(
        self,
        stage_key: str,
        *,
        total_episodes: int,
        start_episode: int,
        allow_script_episode_labels: bool = False,
    ) -> dict[str, Any]:
        batch_size = max(1, int(settings.batch_size or 5))
        end_episode = min(total_episodes, start_episode + batch_size - 1)
        dependencies = list(_rollback_stage_dependency_keys(stage_key))
        del allow_script_episode_labels

        stage_label = {
            "hooks": "开头冲突钩子",
            "dialogues": "角色对话",
            "script": "剧本正文",
        }.get(stage_key, ROLLBACK_STAGE_LABELS.get(stage_key, stage_key))
        if end_episode < total_episodes:
            label = (
                f"从第 {start_episode} 集开始重写{stage_label}"
                f"（将按批次重写第 {start_episode}-{end_episode} 集，并继续重写后续批次）"
            )
        else:
            label = f"从第 {start_episode} 集开始重写{stage_label}（将重写第 {start_episode}-{end_episode} 集）"

        return {
            "value": start_episode,
            "label": label,
            "start_episode": start_episode,
            "end_episode": end_episode,
            "stage_key": stage_key,
            "affected_stages": dependencies,
        }

    def _script_rollback_start_options(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        debug_state = snapshot.get("debug_state") or {}
        variables = debug_state.get("variables") if isinstance(debug_state, dict) else {}
        if not isinstance(variables, dict):
            variables = {}

        batch_size = max(1, int(settings.batch_size or 5))
        total_episodes = int(snapshot.get("total_episodes") or 0)
        if total_episodes <= 0:
            return []

        batch_starts = [
            int(batch["start"])
            for batch in build_episode_batches(total_episodes, batch_size=batch_size)
        ]
        script_batches = _normalize_batch_text_map(variables.get(LOCAL_SCRIPT_BATCHES))
        script_episodes = _normalize_episode_script_map(variables.get(LOCAL_SCRIPT_EPISODES))
        interrupted_start = self._interrupted_batch_start_episode(snapshot)
        if script_episodes:
            candidate_starts = batch_starts
        elif script_batches:
            candidate_starts = batch_starts
        else:
            candidate_starts = [interrupted_start] if interrupted_start in batch_starts else batch_starts[:1]

        if interrupted_start in batch_starts and interrupted_start not in candidate_starts:
            candidate_starts = sorted({*candidate_starts, interrupted_start})

        options: list[dict[str, Any]] = []
        for start_episode in candidate_starts:
            options.append(
                self._build_rollback_start_option(
                    "script",
                    total_episodes=total_episodes,
                    start_episode=start_episode,
                    allow_script_episode_labels=bool(script_episodes),
                )
            )
        return options

    def _rollback_defaults(self, snapshot: dict[str, Any]) -> tuple[str, int | None]:
        debug_state = snapshot.get("debug_state") or {}
        variables = debug_state.get("variables") if isinstance(debug_state, dict) else {}
        if not isinstance(variables, dict):
            variables = {}

        current_stage = _normalize_rollback_stage_key(snapshot.get("current_stage"))
        rewrite_stage = _normalize_rollback_stage_key(variables.get(LOCAL_REWRITE_FROM_STAGE))
        batch_stage = _normalize_rollback_stage_key(variables.get(LOCAL_CURRENT_BATCH_STAGE))
        interrupted_start = self._interrupted_batch_start_episode(snapshot)

        for candidate in (batch_stage, rewrite_stage, current_stage):
            if candidate in {"hooks", "dialogues", "script"}:
                valid_options = self._batched_stage_rollback_start_options(snapshot, candidate)
                valid_starts = [int(option["value"]) for option in valid_options if _safe_int(option.get("value"), 0) > 0]
                if interrupted_start in valid_starts:
                    return candidate, interrupted_start
                return candidate, valid_starts[-1] if valid_starts else None

        for candidate in (batch_stage, rewrite_stage, current_stage):
            if candidate in ROLLBACK_STAGE_LABELS:
                return candidate, None
        return "", None

    def _interrupted_batch_start_episode(self, snapshot: dict[str, Any]) -> int | None:
        """优先按真实缓存覆盖度推断中断批次，避免旧的 start_episode 把回退点带偏。"""
        debug_state = snapshot.get("debug_state") or {}
        variables = debug_state.get("variables") if isinstance(debug_state, dict) else {}
        if not isinstance(variables, dict):
            variables = {}

        total_episodes = int(snapshot.get("total_episodes") or 0)
        batch_size = max(1, int(settings.batch_size or 5))
        batches = list(iter_episode_batches(total_episodes, batch_size=batch_size)) if total_episodes > 0 else []
        if batches:
            batch_stage = _normalize_rollback_stage_key(variables.get(LOCAL_CURRENT_BATCH_STAGE))
            rewrite_stage = _normalize_rollback_stage_key(variables.get(LOCAL_REWRITE_FROM_STAGE))
            current_stage = self._snapshot_stage_to_rollback_stage(snapshot, variables)
            saved_start = _safe_int(
                variables.get(BATCH_START_EPISODE)
                or variables.get(HOOK_START_VAR)
                or variables.get(DIALOGUE_START_VAR)
                or variables.get(SCRIPT_START_VAR),
                0,
            )
            derived_start = self._derived_batch_start_from_cache(
                variables,
                batches=batches,
                batch_stage=batch_stage,
                rewrite_stage=rewrite_stage,
                current_stage=current_stage,
            )
            if derived_start is not None:
                return derived_start
            if saved_start > 0:
                return saved_start

        current_batch = str(snapshot.get("current_batch") or "").strip()
        if current_batch:
            prefix = current_batch.split("-", 1)[0].strip()
            parsed = _safe_int(prefix, 0)
            if parsed > 0:
                return parsed
        return None

    def _derived_batch_start_from_cache(
        self,
        variables: dict[str, Any],
        *,
        batches: list[BatchWindow],
        batch_stage: str,
        rewrite_stage: str,
        current_stage: str,
    ) -> int | None:
        """根据 hooks/dialogues/script 的真实缓存，反推出当前应该从哪一批继续。"""
        if not batches:
            return None

        hooks_start = self._next_unfinished_object_batch_start(variables.get(ALL_HOOKS), batches)
        dialogues_start = self._next_unfinished_object_batch_start(variables.get(ALL_DIALOGUES), batches)
        script_start = self._next_unfinished_script_batch_start(variables, batches)

        anchor_stage = ""
        for candidate in (batch_stage, rewrite_stage, current_stage):
            if candidate in {"hooks", "dialogues", "script", "final"}:
                anchor_stage = candidate
                break

        if anchor_stage == "hooks":
            return hooks_start
        if anchor_stage == "dialogues":
            return dialogues_start
        if anchor_stage in {"script", "final"}:
            return script_start
        return min(hooks_start, dialogues_start, script_start)

    def _next_unfinished_object_batch_start(
        self,
        value: Any,
        batches: list[BatchWindow],
    ) -> int:
        payload = copy.deepcopy(value) if isinstance(value, dict) else {}
        for batch in batches:
            if not self._episode_object_covers_batch(payload, batch):
                return batch.start_episode
        return batches[-1].end_episode + 1

    def _episode_object_covers_batch(self, value: Any, batch: BatchWindow) -> bool:
        payload = copy.deepcopy(value) if isinstance(value, dict) else {}
        episodes = payload.get("episodes")
        if not isinstance(episodes, list):
            return False
        episode_numbers = sorted(
            {
                _safe_int(item.get("episode"), 0)
                for item in episodes
                if isinstance(item, dict)
                and batch.start_episode <= _safe_int(item.get("episode"), 0) <= batch.end_episode
            }
        )
        expected = list(range(batch.start_episode, batch.end_episode + 1))
        return episode_numbers == expected

    def _next_unfinished_script_batch_start(
        self,
        variables: dict[str, Any],
        batches: list[BatchWindow],
    ) -> int:
        script_batches = _normalize_batch_text_map(variables.get(LOCAL_SCRIPT_BATCHES))
        script_episodes = _normalize_episode_script_map(variables.get(LOCAL_SCRIPT_EPISODES))
        summary_by_batch = _normalize_batch_text_map(variables.get(LOCAL_SUMMARY_BY_BATCH))
        for batch in batches:
            batch_text = str(script_batches.get(batch.start_episode) or "").strip()
            if not batch_text:
                expected = range(batch.start_episode, batch.end_episode + 1)
                if all(str(script_episodes.get(episode) or "").strip() for episode in expected):
                    batch_text = "\n".join(
                        str(script_episodes.get(episode) or "").strip()
                        for episode in expected
                    ).strip()
            batch_summary = str(summary_by_batch.get(batch.start_episode) or "").strip()
            if not batch_text or not batch_summary:
                return batch.start_episode
        return batches[-1].end_episode + 1

    def _episode_stage_completed_count(self, total_episodes: int, *values: Any) -> int:
        if total_episodes <= 0:
            return 0

        covered: set[int] = set()
        for value in values:
            payloads: list[dict[str, Any]] = []
            if isinstance(value, dict) and isinstance(value.get("episodes"), list):
                payloads.append(value)
            elif isinstance(value, dict):
                payloads.extend(_normalize_batch_object_map(value).values())

            for payload in payloads:
                episodes = payload.get("episodes")
                if not isinstance(episodes, list):
                    continue
                for item in episodes:
                    if not isinstance(item, dict):
                        continue
                    episode_no = _safe_int(item.get("episode"), 0)
                    if 1 <= episode_no <= total_episodes:
                        covered.add(episode_no)
        return len(covered)

    def _script_completed_episode_count(
        self,
        snapshot: dict[str, Any],
        variables: dict[str, Any],
        total_episodes: int,
    ) -> int:
        if total_episodes <= 0:
            return 0

        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        if (
            str(snapshot.get("status") or "").strip().lower() == "completed"
            or any(str(artifacts.get(key) or "").strip() for key in ("final_output_text", "final_script"))
        ):
            return total_episodes

        completed: set[int] = set()
        script_episodes = _normalize_episode_script_map(variables.get(LOCAL_SCRIPT_EPISODES))
        for episode_no in script_episodes:
            if 1 <= episode_no <= total_episodes:
                completed.add(episode_no)

        script_batches = _normalize_batch_text_map(variables.get(LOCAL_SCRIPT_BATCHES))
        if script_batches:
            batch_size = max(1, int(settings.batch_size or 5))
            for batch in iter_episode_batches(total_episodes, batch_size=batch_size):
                if str(script_batches.get(batch.start_episode) or "").strip():
                    completed.update(range(batch.start_episode, batch.end_episode + 1))

        return len(completed)

    def _progress_value_present(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (dict, list, tuple, set)):
            return bool(value)
        return True

    def _progress_stage_key(self, snapshot: dict[str, Any], variables: dict[str, Any]) -> str:
        batch_stage = str(variables.get(LOCAL_CURRENT_BATCH_STAGE) or "").strip().lower()
        if batch_stage in {"hook", "dialogue", "script"}:
            return batch_stage
        return str(snapshot.get("current_stage") or "").strip().lower()

    def _progress_batch_start_episode(
        self,
        snapshot: dict[str, Any],
        variables: dict[str, Any],
        total_episodes: int,
    ) -> int:
        upper_bound = max(1, int(total_episodes or 0) + 1)
        start_episode = _safe_int(variables.get(BATCH_START_EPISODE), 0)
        if 1 <= start_episode <= upper_bound:
            return start_episode

        current_batch = str(snapshot.get("current_batch") or "").strip()
        match = re.match(r"^\s*(\d+)", current_batch)
        if match:
            parsed = _safe_int(match.group(1), 0)
            if 1 <= parsed <= upper_bound:
                return parsed
        return 0

    def _max_fixed_stage_index(self, snapshot: dict[str, Any], progress_stage: str) -> int:
        status = str(snapshot.get("status") or "").strip().lower()
        if status == "completed" or progress_stage in {"finished", "hook", "dialogue", "script", "finalize"}:
            return 8
        stage_limits = {
            "framework": 0,
            "appearance_strategy": 1,
            "validation": 4,
            "worldview": 4,
            "character": 5,
            "scene": 6,
            "appearance": 7,
        }
        return int(stage_limits.get(progress_stage, 0))

    def _fixed_stage_completion_flags(
        self,
        snapshot: dict[str, Any],
        variables: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> list[bool]:
        del snapshot
        framework_done = all(
            self._progress_value_present(artifacts.get(key))
            for key in (
                "script_title_content",
                "story_outline",
                "character_bios",
                "core_scene_input",
                "episode_plan",
            )
        )
        pre_strategy_done = all(
            self._progress_value_present(variables.get(key) or artifacts.get(artifact_key))
            for key, artifact_key in (
                (CHARACTER_APPEARANCE_REQUIREMENTS, "character_appearance_requirements"),
                (CHARACTER_ALIAS_NAMING_RULES, "character_alias_naming_rules"),
                (OUTFIT_SWITCH_RULES, "outfit_switch_rules"),
            )
        )
        consistency_done = variables.get(IS_CONSISTENT) is not None
        normalize_done = self._progress_value_present(
            variables.get(NORMALIZED_EPISODE_PLAN) or artifacts.get("normalized_episode_plan")
        )
        worldview_done = self._progress_value_present(artifacts.get("worldview"))
        character_done = self._progress_value_present(
            artifacts.get("character_natural_language")
            or artifacts.get("character_summary")
            or variables.get(CHARACTERS)
            or variables.get(CHARACTER_NATURAL_LANGUAGE_VAR)
        )
        scene_done = self._progress_value_present(
            artifacts.get("scene_natural_language")
            or artifacts.get("core_scene_summary")
            or artifacts.get("scene_json")
            or variables.get(SCENES)
            or variables.get(SCENE_NATURAL_LANGUAGE_VAR)
        )
        appearance_done = self._progress_value_present(
            variables.get(APPEARANCE_MAPPING) or artifacts.get("appearance_mapping")
        )
        return [
            framework_done,
            pre_strategy_done,
            consistency_done,
            normalize_done,
            worldview_done,
            character_done,
            scene_done,
            appearance_done,
        ]

    def _count_contiguous_completed_stages(
        self,
        flags: list[bool],
        *,
        allowed_count: int,
    ) -> int:
        completed = 0
        for index, done in enumerate(flags, start=1):
            if index > allowed_count or not done:
                break
            completed += 1
        return completed

    def _snapshot_progress_metrics(self, snapshot: dict[str, Any]) -> dict[str, int]:
        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        debug_state = snapshot.get("debug_state") if isinstance(snapshot.get("debug_state"), dict) else {}
        variables = debug_state.get("variables") if isinstance(debug_state.get("variables"), dict) else {}
        total_episodes = max(0, _safe_int(snapshot.get("total_episodes"), 0))
        fixed_stage_total = 8
        progress_stage = self._progress_stage_key(snapshot, variables)
        batch_stage = str(variables.get(LOCAL_CURRENT_BATCH_STAGE) or "").strip().lower()
        batch_start_episode = self._progress_batch_start_episode(snapshot, variables, total_episodes)
        completed_before_current_batch = (
            min(total_episodes, max(0, batch_start_episode - 1))
            if batch_start_episode > 0
            else 0
        )

        fixed_flags = self._fixed_stage_completion_flags(snapshot, variables, artifacts)
        fixed_completed = self._count_contiguous_completed_stages(
            fixed_flags,
            allowed_count=self._max_fixed_stage_index(snapshot, progress_stage),
        )

        final_completed = (
            str(snapshot.get("status") or "").strip().lower() == "completed"
            or progress_stage == "finished"
        )

        hooks_actual = self._episode_stage_completed_count(total_episodes, variables.get(ALL_HOOKS))
        dialogues_actual = self._episode_stage_completed_count(total_episodes, variables.get(ALL_DIALOGUES))
        script_actual = self._script_completed_episode_count(snapshot, variables, total_episodes)

        hooks_completed = 0
        dialogues_completed = 0
        script_completed = 0

        if final_completed:
            fixed_completed = fixed_stage_total
            hooks_completed = total_episodes
            dialogues_completed = total_episodes
            script_completed = total_episodes
        elif progress_stage == "hook":
            hooks_completed = (
                completed_before_current_batch
                if batch_stage == "hook" and batch_start_episode > 0
                else hooks_actual
            )
        elif progress_stage == "dialogue":
            hooks_completed = hooks_actual
            dialogues_completed = (
                completed_before_current_batch
                if batch_stage == "dialogue" and batch_start_episode > 0
                else dialogues_actual
            )
        elif progress_stage == "script":
            hooks_completed = hooks_actual
            dialogues_completed = dialogues_actual
            script_completed = (
                max(script_actual, completed_before_current_batch)
                if batch_stage == "script" and batch_start_episode > 0
                else script_actual
            )
        elif progress_stage == "finalize":
            hooks_completed = hooks_actual
            dialogues_completed = max(dialogues_actual, script_actual)
            if self._progress_value_present(artifacts.get("final_output_text") or artifacts.get("final_script")):
                script_completed = total_episodes
            else:
                script_completed = script_actual

        hooks_completed = min(total_episodes, max(0, hooks_completed))
        dialogues_completed = min(total_episodes, max(dialogues_completed, script_completed))
        hooks_completed = min(total_episodes, max(hooks_completed, dialogues_completed))
        dialogues_completed = min(dialogues_completed, hooks_completed)
        script_completed = min(script_completed, dialogues_completed)

        total_units = fixed_stage_total + (total_episodes * 3) + 1
        completed_units = fixed_completed + hooks_completed + dialogues_completed + script_completed + (1 if final_completed else 0)
        completed_units = max(0, min(total_units, completed_units))
        generated_episodes = total_episodes if final_completed else script_completed

        if final_completed:
            progress_percent = 100
        else:
            progress_percent = int(round((completed_units / total_units) * 100)) if total_units > 0 else 0

        return {
            "progress_percent": max(0, min(100, progress_percent)),
            "generated_episodes": max(0, generated_episodes),
        }

    def _completed_input_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        input_payload = _select_non_empty_fields(
            snapshot.get("input_payload") or {},
            COMPLETED_INPUT_PAYLOAD_KEYS,
        )
        artifacts = snapshot.get("artifacts") or {}
        title = str(
            artifacts.get("script_title_content")
            or snapshot.get("title")
            or input_payload.get("title")
            or ""
        ).strip()
        story_outline = str(
            artifacts.get("story_outline")
            or input_payload.get("story_outline")
            or ""
        ).strip()
        total_episodes = snapshot.get("total_episodes") or input_payload.get("total_episodes")
        if title:
            input_payload["title"] = title
        if story_outline:
            input_payload["story_outline"] = story_outline
        if total_episodes:
            input_payload["total_episodes"] = int(total_episodes)
        return input_payload

    def _compact_completed_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        compacted = copy.deepcopy(snapshot)
        compacted["artifacts"] = _select_non_empty_fields(
            compacted.get("artifacts") or {},
            COMPLETED_ARTIFACT_KEYS,
        )
        compacted["input_payload"] = self._completed_input_payload(compacted)
        compacted["current_node_id"] = None
        compacted["current_node_name"] = None
        compacted["current_batch"] = None
        # 用户确认“满意完成”后，不再保留可回退执行缓存。
        # 这样既减小快照体积，也避免前端误以为还能继续从中间阶段接着改。
        compacted.pop("debug_state", None)
        compacted.pop("logs", None)
        compacted.pop("error", None)
        compacted.pop("prompt_fixes", None)
        compacted["completion_confirmed"] = True
        compacted["awaiting_user_confirmation"] = False
        compacted["cache_retained"] = False
        compacted["message"] = COMPLETION_CONFIRMED_MESSAGE
        return compacted

    def _compact_record_after_completion(self, record: TaskRecord) -> None:
        compacted = self._compact_completed_snapshot(record.clone_snapshot())
        with record.lock:
            record.snapshot = compacted
        self._persist_snapshot(record)

    def _load_project_snapshot_raw(self, project_id: int) -> dict[str, Any] | None:
        record = self._projects.get(project_id)
        if record:
            return record.clone_snapshot()
        path = self._project_path(project_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_task_snapshot_raw(self, task_id: str) -> dict[str, Any] | None:
        record = self._tasks.get(task_id)
        if record:
            return record.clone_snapshot()
        for path in self.projects_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("task_id") == task_id:
                return data
        return None

    def _model_alias(self, provider: str, index: int = 1) -> str:
        provider_name = str(provider or "").strip().lower()
        initials = {
            "deepseek": "D",
            "gemini": "G",
            "claude": "C",
            "ollama": "O",
            "doubao": "D",
            "fastgpt": "F",
        }
        letter = initials.get(provider_name, (provider_name[:1] or "M").upper())
        base = f"XK{letter.upper()}"
        return base if index <= 1 else f"{base}{index}"

    def list_model_options(self, workflow_spec_path: str) -> list[dict[str, Any]]:
        extra_models: list[str] = []
        if not use_fastgpt_backend():
            spec = WorkflowSpec(workflow_spec_path)
            extra_models = spec.list_chat_models()
        options = settings.list_model_options(extra_models=extra_models)
        provider_counts: dict[str, int] = {}
        result = []
        for item in options:
            provider_counts[item.provider] = provider_counts.get(item.provider, 0) + 1
            alias = self._model_alias(item.provider, provider_counts[item.provider])
            if not item.configured:
                alias = f"{alias} [未配置]"
            result.append(
                {
                "id": item.id,
                "label": alias,
                "provider": item.provider,
                "model": item.model,
                "is_default": item.is_default,
                "configured": item.configured,
            }
            )
        return result

    def latest_project_snapshot(self, user_id: int | None = None) -> dict[str, Any] | None:
        if user_id is not None:
            latest_by_user = self._index.get("latest_project_by_user", {})
            latest_project_id = latest_by_user.get(str(int(user_id)))
            if latest_project_id:
                snapshot = self.get_project_snapshot(int(latest_project_id), user_id=user_id)
                if snapshot:
                    return snapshot

            candidates: list[dict[str, Any]] = []
            for path in self.projects_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if self._snapshot_belongs_to_user(data, user_id):
                    candidates.append(data)
            if not candidates:
                return None
            candidates.sort(
                key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
                reverse=True,
            )
            return self._public_snapshot(candidates[0])

        latest_project_id = self._index.get("latest_project_id")
        if not latest_project_id:
            return None
        return self.get_project_snapshot(int(latest_project_id))

    def get_project_snapshot(
        self,
        project_id: int,
        *,
        user_id: int | None = None,
        public_view: bool = True,
    ) -> dict[str, Any] | None:
        snapshot = self._load_project_snapshot_raw(project_id)
        if snapshot is None:
            return None
        if not self._snapshot_belongs_to_user(snapshot, user_id):
            return None
        return self._public_snapshot(snapshot) if public_view else snapshot

    def get_task_snapshot(
        self,
        task_id: str,
        *,
        user_id: int | None = None,
        public_view: bool = True,
    ) -> dict[str, Any] | None:
        snapshot = self._load_task_snapshot_raw(task_id)
        if snapshot is None:
            return None
        if not self._snapshot_belongs_to_user(snapshot, user_id):
            return None
        return self._public_snapshot(snapshot) if public_view else snapshot

    def start_task(
        self,
        *,
        user_id: int,
        input_payload: dict[str, Any],
        workflow_spec_path: str,
        model_selection_id: str | None,
    ) -> dict[str, Any]:
        project_id = self._next_project_id()
        self._remember_latest_project(user_id, project_id)
        task_id = uuid.uuid4().hex[:12]
        model_option = settings.resolve_model_selection(model_selection_id)
        spec = None if use_fastgpt_backend() else WorkflowSpec(workflow_spec_path)

        snapshot = {
            "user_id": int(user_id),
            "project_id": project_id,
            "task_id": task_id,
            "status": "pending",
            "title": str(input_payload.get("title", "")).strip(),
            "message": "任务已创建，准备开始生成。",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "workflow_spec_path": workflow_spec_path,
            "visibility": "private",
            "model_option": {
                "id": model_option.id,
                "label": self._model_alias(model_option.provider),
                "provider": model_option.provider,
                "model": model_option.model,
            }
            if model_option
            else None,
            "input_payload": input_payload,
            "artifacts": {},
            "logs": [],
            "prompt_fixes": spec.get_prompt_fixes() if spec else [],
            "progress_percent": 0,
            "generated_episodes": 0,
            "total_episodes": int(input_payload.get("total_episodes", 0) or 0),
            "current_stage": "validation",
            "current_stage_label": STAGE_LABELS["validation"],
            "current_node_id": None,
            "current_node_name": None,
            "current_batch": None,
            "completion_confirmed": False,
            "awaiting_user_confirmation": False,
            "cache_retained": True,
            "debug_state": {},
            "wait_elapsed_ms": 0,
            "wait_started_at": now_iso(),
        }

        record = TaskRecord(
            user_id=int(user_id),
            project_id=project_id,
            task_id=task_id,
            workflow_spec_path=workflow_spec_path,
            input_payload=input_payload,
            model_option=model_option,
            snapshot=snapshot,
        )
        self._tasks[task_id] = record
        self._projects[project_id] = record
        self._save_resume_checkpoint(record)
        self._persist_snapshot(record)

        thread = threading.Thread(
            target=self._run_task,
            args=(record,),
            daemon=True,
            name=f"workflow-task-{task_id}",
        )
        record.thread = thread
        thread.start()
        return self._public_snapshot(record.clone_snapshot())

    def list_user_assets(self, user_id: int) -> list[dict[str, Any]]:
        assets = [
            self._asset_summary(snapshot, include_private=True, use_teaser=True)
            for snapshot in self._all_project_snapshots()
            if self._snapshot_belongs_to_user(snapshot, user_id)
        ]
        assets.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return assets

    def list_user_projects(self, user_id: int) -> list[dict[str, Any]]:
        projects = [
            self._asset_summary(snapshot, include_private=True, use_teaser=False)
            for snapshot in self._all_project_snapshots()
            if self._snapshot_belongs_to_user(snapshot, user_id)
        ]
        projects.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return projects

    def _best_final_script_text(self, snapshot: dict[str, Any]) -> str:
        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        debug_state = snapshot.get("debug_state") if isinstance(snapshot.get("debug_state"), dict) else {}
        variables = debug_state.get("variables") if isinstance(debug_state.get("variables"), dict) else {}
        input_payload = snapshot.get("input_payload") if isinstance(snapshot.get("input_payload"), dict) else {}
        total_episodes = _safe_int(
            snapshot.get("total_episodes")
            or input_payload.get("total_episodes")
            or variables.get(TOTAL_EPISODES),
            0,
        )
        return _resolve_best_script_text(
            total_episodes=total_episodes,
            artifacts=artifacts,
            variables=variables,
            final_output_text=debug_state.get("final_output_text"),
        )

    def list_public_assets(self) -> list[dict[str, Any]]:
        assets = [
            self._asset_summary(snapshot, include_private=False, use_teaser=True)
            for snapshot in self._all_project_snapshots()
            if str(snapshot.get("visibility") or "private") == "public"
            and str(snapshot.get("status") or "") == "completed"
            and _completion_confirmed(snapshot)
            and bool(self._best_final_script_text(snapshot))
        ]
        assets.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return assets[:24]

    def get_public_asset(self, project_id: int) -> dict[str, Any] | None:
        snapshot = self.get_project_snapshot(project_id, public_view=False)
        if not snapshot:
            return None
        if str(snapshot.get("visibility") or "private") != "public":
            return None
        if str(snapshot.get("status") or "") != "completed":
            return None
        if not _completion_confirmed(snapshot):
            return None
        artifacts = snapshot.get("artifacts") or {}
        final_script = self._best_final_script_text(snapshot)
        if not final_script:
            return None

        payload = self._asset_summary(snapshot, include_private=False, use_teaser=True)
        payload["final_script"] = final_script
        payload["story_outline"] = str(
            artifacts.get("story_outline")
            or (snapshot.get("input_payload") or {}).get("story_outline")
            or ""
        ).strip()
        return payload

    def update_project_asset(
        self,
        project_id: int,
        *,
        user_id: int,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        record = self._projects.get(project_id)
        if record:
            snapshot = record.clone_snapshot()
        else:
            snapshot = self.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot or not self._snapshot_belongs_to_user(snapshot, user_id):
            raise ValueError("项目不存在或无权操作")
        if _completion_confirmed(snapshot) and any(
            key in changes for key in ("title", "story_outline", "final_script")
        ):
            raise ValueError("该剧本已确认满意完成，正文内容已锁定；如需调整请重新生成。公开/私有仍可随时切换。")

        title = str(changes.get("title") or "").strip()
        story_outline = str(changes.get("story_outline") or "").strip()
        final_script = changes.get("final_script")
        visibility = str(changes.get("visibility") or snapshot.get("visibility") or "private").strip()
        if visibility not in {"public", "private"}:
            raise ValueError("隐私设置只能是 public 或 private")

        if title:
            snapshot["title"] = title
            snapshot.setdefault("input_payload", {})["title"] = title
        if story_outline:
            snapshot.setdefault("input_payload", {})["story_outline"] = story_outline
            artifacts = dict(snapshot.get("artifacts") or {})
            artifacts.pop(STORY_TEASER_ARTIFACT, None)
            artifacts.pop(STORY_TEASER_SOURCE_ARTIFACT, None)
            snapshot["artifacts"] = artifacts
        if final_script is not None:
            text = str(final_script).strip()
            artifacts = dict(snapshot.get("artifacts") or {})
            artifacts["final_script"] = text
            artifacts["final_output_text"] = text
            snapshot["artifacts"] = artifacts
        snapshot["visibility"] = visibility
        snapshot["updated_at"] = now_iso()

        if record:
            with record.lock:
                record.snapshot = snapshot
            self._persist_snapshot(record)
        else:
            self._project_path(project_id).write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return self._public_snapshot(snapshot)

    def confirm_project_completion(
        self,
        project_id: int,
        *,
        user_id: int,
    ) -> dict[str, Any]:
        snapshot = self.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot or not self._snapshot_belongs_to_user(snapshot, user_id):
            raise ValueError("项目不存在或无权操作")
        if str(snapshot.get("status") or "") != "completed":
            raise ValueError("只有已完成的剧本才能确认满意完成")
        if _completion_confirmed(snapshot):
            return self._public_snapshot(snapshot)

        record = self._projects.get(project_id)
        if record:
            self._update_snapshot(
                record,
                completion_confirmed=True,
                awaiting_user_confirmation=False,
                cache_retained=False,
                message=COMPLETION_CONFIRMED_MESSAGE,
                finished_at=snapshot.get("finished_at") or now_iso(),
            )
            self._compact_record_after_completion(record)
            return self._public_snapshot(record.clone_snapshot())

        snapshot.update(
            {
                "completion_confirmed": True,
                "awaiting_user_confirmation": False,
                "cache_retained": False,
                "message": COMPLETION_CONFIRMED_MESSAGE,
                "finished_at": snapshot.get("finished_at") or now_iso(),
            }
        )
        compacted = self._compact_completed_snapshot(snapshot)
        self._project_path(project_id).write_text(
            json.dumps(compacted, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self._public_snapshot(compacted)

    def rollback_project_to_stage(
        self,
        project_id: int,
        *,
        user_id: int,
        stage_key: str,
        start_episode: int | None = None,
    ) -> dict[str, Any]:
        rollback_stage = _normalize_rollback_stage_key(stage_key)
        if rollback_stage not in ROLLBACK_STAGE_LABELS:
            raise ValueError("请选择有效的回退阶段")

        snapshot = self.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot or not self._snapshot_belongs_to_user(snapshot, user_id):
            raise ValueError("项目不存在或无权操作")
        status = str(snapshot.get("status") or "")
        if status in {"pending", "running"}:
            raise ValueError("任务仍在执行中，不能回退重写")
        if status not in {"completed", "paused", "pausing", "terminated", "failed"}:
            raise ValueError("当前状态不支持阶段回退重写")
        if _completion_confirmed(snapshot):
            raise ValueError("该剧本已确认满意完成并清理缓存，如需调整请重新生成。")

        debug_state = snapshot.get("debug_state")
        if not isinstance(debug_state, dict) or not isinstance(debug_state.get("variables"), dict):
            raise ValueError("当前项目缺少可回退的执行缓存，无法按阶段重写。")

        _, default_start_episode = self._rollback_defaults(snapshot)
        rollback_start_episode: int | None = None
        if _rollback_stage_requires_episode_range(rollback_stage):
            rollback_start_episode = _safe_int(start_episode, 0) or None
            if rollback_start_episode is None and default_start_episode:
                rollback_start_episode = int(default_start_episode)
            rollback_options = self._batched_stage_rollback_start_options(snapshot, rollback_stage)
            valid_start_episodes = {int(option["value"]) for option in rollback_options if _safe_int(option.get("value"), 0) > 0}
            if rollback_start_episode is None:
                raise ValueError(f"请选择{ROLLBACK_STAGE_LABELS[rollback_stage]}开始重写的集数范围")
            batch_size = max(1, int(settings.batch_size or 5))
            try:
                rollback_start_episode = validate_rewrite_start_episode(
                    rollback_start_episode,
                    int(snapshot.get("total_episodes") or 0),
                    batch_size=batch_size,
                )
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
            if rollback_start_episode not in valid_start_episodes:
                raise ValueError(rewrite_start_validation_message(batch_size))

        old_task_id = str(snapshot.get("task_id") or "").strip()
        old_record = self._projects.get(project_id)
        if old_record and status in {"paused", "pausing", "terminated"}:
            self._prepare_record_for_replacement(old_record)

        task_id = old_task_id or uuid.uuid4().hex[:12]
        rollback_snapshot = self._build_stage_rollback_snapshot(
            snapshot,
            rollback_stage,
            start_episode=rollback_start_episode,
        )
        model_option = settings.resolve_model_selection(
            (snapshot.get("model_option") or {}).get("id")
        )
        stage_label = ROLLBACK_STAGE_LABELS[rollback_stage]
        if _rollback_stage_requires_episode_range(rollback_stage) and rollback_start_episode:
            batch_size = max(1, int(settings.batch_size or 5))
            end_episode = min(int(snapshot.get("total_episodes") or 0), rollback_start_episode + batch_size - 1)
            if end_episode < int(snapshot.get("total_episodes") or 0):
                stage_label = (
                    f"{stage_label}（从第 {rollback_start_episode} 集开始，"
                    f"将按批次重写第 {rollback_start_episode}-{end_episode} 集，并继续重写后续批次）"
                )
            else:
                stage_label = f"{stage_label}（从第 {rollback_start_episode} 集开始，将重写第 {rollback_start_episode}-{end_episode} 集）"
        new_snapshot = copy.deepcopy(rollback_snapshot)
        new_snapshot.update(
            {
                "task_id": task_id,
                "status": "pending",
                "message": f"已回退到“{stage_label}”，准备在当前资产上继续生成。",
                "error": None,
                "rollback_of_task_id": None,
                "rollback_stage": rollback_stage,
                "rollback_start_episode": rollback_start_episode,
                "updated_at": now_iso(),
                "finished_at": None,
                "completion_confirmed": False,
                "awaiting_user_confirmation": False,
                "cache_retained": True,
                "wait_elapsed_ms": 0,
                "wait_started_at": now_iso(),
            }
        )

        if old_record is not None:
            record = old_record
            record.user_id = int(snapshot.get("user_id") or user_id or 0)
            record.project_id = int(project_id)
            record.task_id = task_id
            record.workflow_spec_path = str(snapshot.get("workflow_spec_path", ""))
            record.input_payload = copy.deepcopy(snapshot.get("input_payload") or {})
            record.model_option = model_option
            record.snapshot = new_snapshot
            record.control = TaskControl()
            record.thread = None
            record.resume_snapshot = rollback_snapshot
        else:
            record = TaskRecord(
                user_id=int(snapshot.get("user_id") or user_id or 0),
                project_id=int(project_id),
                task_id=task_id,
                workflow_spec_path=str(snapshot.get("workflow_spec_path", "")),
                input_payload=copy.deepcopy(snapshot.get("input_payload") or {}),
                model_option=model_option,
                snapshot=new_snapshot,
                resume_snapshot=rollback_snapshot,
            )
        with self._lock:
            if old_task_id and old_task_id != task_id:
                self._tasks.pop(old_task_id, None)
            self._tasks[task_id] = record
            self._projects[int(project_id)] = record
            self._remember_latest_project(int(user_id), int(project_id))
        self._append_log(
            record,
            title="控制动作：阶段回退重写",
            message=f"已保留前序阶段结果，并在当前资产上从“{stage_label}”开始重新生成。",
        )
        self._save_resume_checkpoint(record)
        self._persist_snapshot(record)

        thread = threading.Thread(
            target=self._run_task,
            args=(record,),
            daemon=True,
            name=f"workflow-task-{task_id}",
        )
        record.thread = thread
        thread.start()
        return self._public_snapshot(record.clone_snapshot())

    def _prepare_record_for_replacement(self, record: TaskRecord) -> None:
        thread = record.thread
        if thread is None or not thread.is_alive():
            return
        record.control.request_terminate()
        thread.join(timeout=3.0)
        if thread.is_alive():
            raise ValueError("当前任务仍在收尾，暂时无法回退重写，请稍后再试。")

    def _all_project_snapshots(self) -> list[dict[str, Any]]:
        snapshots: dict[int, dict[str, Any]] = {}
        for project_id, record in self._projects.items():
            snapshots[int(project_id)] = record.clone_snapshot()
        for path in self.projects_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            project_id = int(data.get("project_id") or path.stem or 0)
            snapshots.setdefault(project_id, data)
        return list(snapshots.values())

    def _build_stage_rollback_snapshot(
        self,
        snapshot: dict[str, Any],
        stage_key: str,
        *,
        start_episode: int | None = None,
    ) -> dict[str, Any]:
        """构造阶段回退后的新快照，只保留当前阶段之前仍然可信的缓存。"""
        effective_start_episode = (
            int(start_episode)
            if _safe_int(start_episode, 0) > 0
            else self._interrupted_batch_start_episode(snapshot)
            if stage_key in {"hooks", "dialogues", "script"}
            else None
        )
        rollback = copy.deepcopy(snapshot)
        rollback["artifacts"] = self._rolled_back_artifacts(snapshot, stage_key)
        rollback["debug_state"] = self._rolled_back_debug_state(
            snapshot,
            stage_key,
            start_episode=effective_start_episode,
        )
        rollback["artifacts"].update(
            _partial_script_artifacts_from_variables(
                total_episodes=_safe_int(rollback.get("total_episodes"), 0),
                variables=(rollback.get("debug_state") or {}).get("variables"),
            )
        )
        rollback["prompt_fixes"] = []
        rollback["current_node_id"] = None
        rollback["current_node_name"] = None
        rollback["current_batch"] = (
            f"{effective_start_episode}-{_batch_end_episode(int(snapshot.get('total_episodes') or 0), effective_start_episode)}"
            if stage_key in {"hooks", "dialogues", "script"} and effective_start_episode
            else None
        )
        rollback["generated_episodes"] = (
            max(0, int(effective_start_episode or 0) - 1)
            if stage_key in {"hooks", "dialogues", "script"} and effective_start_episode
            else 0
        )
        rollback["current_stage"] = stage_key
        rollback["current_stage_label"] = ROLLBACK_STAGE_LABELS.get(stage_key, stage_key)
        rollback["progress_percent"] = self._rollback_progress_percent(rollback)
        rollback["message"] = f"已回退到“{ROLLBACK_STAGE_LABELS.get(stage_key, stage_key)}”，等待重新生成。"
        rollback["error"] = None
        rollback["finished_at"] = None
        rollback["cache_retained"] = True
        rollback["awaiting_user_confirmation"] = False
        rollback["completion_confirmed"] = False
        rollback["rollback_start_episode"] = effective_start_episode
        return rollback

    def _rolled_back_artifacts(
        self,
        snapshot: dict[str, Any],
        stage_key: str,
    ) -> dict[str, Any]:
        artifacts = copy.deepcopy(snapshot.get("artifacts") or {})
        for key in ROLLBACK_ARTIFACT_CLEAR_RULES.get(stage_key, ()):
            artifacts.pop(key, None)
        artifacts.pop(STORY_TEASER_ARTIFACT, None)
        artifacts.pop(STORY_TEASER_SOURCE_ARTIFACT, None)
        artifacts.pop(EPISODE_PLAN_DISPLAY_ARTIFACT, None)
        artifacts.pop(EPISODE_PLAN_DISPLAY_SOURCE_HASH_ARTIFACT, None)
        return artifacts

    def _rolled_back_debug_state(
        self,
        snapshot: dict[str, Any],
        stage_key: str,
        *,
        start_episode: int | None = None,
    ) -> dict[str, Any]:
        debug_state = copy.deepcopy(snapshot.get("debug_state") or {})
        variables = debug_state.get("variables")
        if not isinstance(variables, dict):
            variables = {}

        # 回退不是简单清空全部缓存，而是“只删除当前阶段之后不再可信的部分”。
        # 这样前序稳定产物还能继续复用，减少重跑成本。
        clear_keys = set(ROLLBACK_DEBUG_CLEAR_RULES.get(stage_key, ()))
        for key in list(clear_keys):
            clear_keys.update(DEBUG_VARIABLE_MIRRORS.get(key, ()))
        for key in clear_keys:
            variables.pop(key, None)

        if stage_key in {"dialogues", "script", "final"}:
            variables[LOCAL_REWRITE_FROM_STAGE] = (
                "dialogue" if stage_key == "dialogues"
                else "script" if stage_key == "script"
                else "final"
            )

        if stage_key in {"hooks", "dialogues"} and start_episode:
            self._apply_batched_stage_rollback(
                snapshot,
                variables,
                stage_key=stage_key,
                start_episode=start_episode,
            )
        if stage_key == "script" and start_episode:
            self._apply_script_partial_rollback(
                snapshot,
                variables,
                start_episode=start_episode,
            )

        debug_state["variables"] = variables
        debug_state["node_outputs"] = {}
        debug_state["halted_message"] = None
        debug_state["final_output_text"] = ""
        return debug_state

    def _apply_batched_stage_rollback(
        self,
        snapshot: dict[str, Any],
        variables: dict[str, Any],
        *,
        stage_key: str,
        start_episode: int,
    ) -> None:
        """按批次回退 hooks/dialogues，保留前序结果，只清掉需要重做的窗口。"""
        debug_state = snapshot.get("debug_state") or {}
        original_variables = debug_state.get("variables") if isinstance(debug_state, dict) else {}
        if not isinstance(original_variables, dict):
            original_variables = {}

        total_episodes = int(snapshot.get("total_episodes") or 0)
        batch_size = max(1, int(settings.batch_size or 5))
        batch_end_episode = _batch_end_episode(total_episodes, start_episode)
        completed_batches = len(
            [batch for batch in iter_episode_batches(total_episodes, batch_size=batch_size) if batch.start_episode < start_episode]
        )

        original_hooks = copy.deepcopy(original_variables.get(ALL_HOOKS) or {})
        original_dialogues = copy.deepcopy(original_variables.get(ALL_DIALOGUES) or {})
        summary_by_batch = _normalize_batch_text_map(original_variables.get(LOCAL_SUMMARY_BY_BATCH))
        appearance_memory_by_batch = _normalize_batch_object_map(
            original_variables.get(LOCAL_APPEARANCE_MEMORY_BY_BATCH)
        )

        if stage_key == "hooks":
            preserved_hooks = _slice_episode_object_before(original_hooks, start_episode)
            if preserved_hooks:
                variables[ALL_HOOKS] = preserved_hooks
            else:
                variables.pop(ALL_HOOKS, None)
        elif stage_key == "dialogues":
            preserved_hooks = copy.deepcopy(original_hooks)
            if preserved_hooks:
                variables[ALL_HOOKS] = preserved_hooks
            else:
                variables.pop(ALL_HOOKS, None)
            preserved_dialogues = _slice_episode_object_before(original_dialogues, start_episode)
            if preserved_dialogues:
                variables[ALL_DIALOGUES] = preserved_dialogues
            else:
                variables.pop(ALL_DIALOGUES, None)

        previous_batch_candidates = [
            episode
            for episode in sorted(summary_by_batch)
            if episode + batch_size - 1 < start_episode
        ]
        previous_batch_start = previous_batch_candidates[-1] if previous_batch_candidates else None
        preserved_summary_batches = {
            episode: text for episode, text in summary_by_batch.items() if episode < start_episode
        }
        preserved_appearance_batches = {
            episode: value for episode, value in appearance_memory_by_batch.items() if episode < start_episode
        }

        if previous_batch_start and preserved_summary_batches.get(previous_batch_start):
            variables[LAST_SUMMARY] = preserved_summary_batches[previous_batch_start]
        else:
            variables.pop(LAST_SUMMARY, None)

        preserved_appearance_memory = (
            copy.deepcopy(preserved_appearance_batches.get(previous_batch_start))
            if previous_batch_start in preserved_appearance_batches
            else {}
        )
        if preserved_appearance_memory:
            variables[APPEARANCE_CONTINUITY_MEMORY] = preserved_appearance_memory
        else:
            variables.pop(APPEARANCE_CONTINUITY_MEMORY, None)

        variables[LOCAL_SUMMARY_BY_BATCH] = _string_keyed_batch_map(preserved_summary_batches)
        variables[LOCAL_APPEARANCE_MEMORY_BY_BATCH] = _string_keyed_batch_map(preserved_appearance_batches)
        variables[LOCAL_COMPLETED_BATCHES] = completed_batches
        variables[LOCAL_CURRENT_BATCH_INDEX] = completed_batches
        variables[LOCAL_CURRENT_BATCH_STAGE] = "hook" if stage_key == "hooks" else "dialogue"
        variables[BATCH_START_EPISODE] = int(start_episode)
        variables.pop(BATCH_HOOKS, None)
        variables.pop(BATCH_DIALOGUES, None)
        variables.pop(BATCH_SCRIPT, None)
        variables.pop(LOCAL_HOOK_CHECKPOINT_START, None)
        variables.pop(LOCAL_DIALOGUE_CHECKPOINT_START, None)
        variables.pop(LOCAL_SCRIPT_CHECKPOINT_START, None)

    def _apply_script_partial_rollback(
        self,
        snapshot: dict[str, Any],
        variables: dict[str, Any],
        *,
        start_episode: int,
    ) -> None:
        """按正文缓存切掉 start_episode 之后的内容，确保 script 从真实断点续写。"""
        debug_state = snapshot.get("debug_state") or {}
        original_variables = debug_state.get("variables") if isinstance(debug_state, dict) else {}
        if not isinstance(original_variables, dict):
            original_variables = {}

        script_batches = _normalize_batch_text_map(original_variables.get(LOCAL_SCRIPT_BATCHES))
        script_episodes = _normalize_episode_script_map(original_variables.get(LOCAL_SCRIPT_EPISODES))
        summary_by_batch = _normalize_batch_text_map(original_variables.get(LOCAL_SUMMARY_BY_BATCH))
        appearance_memory_by_batch = _normalize_batch_object_map(
            original_variables.get(LOCAL_APPEARANCE_MEMORY_BY_BATCH)
        )

        preserved_script_episodes = {
            episode: text for episode, text in script_episodes.items() if episode < start_episode
        }
        batch_size = max(1, int(settings.batch_size or 5))
        preserved_script_batches = {
            episode: text
            for episode, text in script_batches.items()
            if (
                episode < start_episode
                and (
                    not preserved_script_episodes
                    or episode + batch_size - 1 < start_episode
                )
            )
        }
        preserved_summary_batches = {
            episode: text for episode, text in summary_by_batch.items() if episode < start_episode
        }
        preserved_appearance_batches = {
            episode: value for episode, value in appearance_memory_by_batch.items() if episode < start_episode
        }

        preserved_starts = sorted(preserved_script_batches)
        preserved_script = (
            _join_script_episode_map(preserved_script_episodes)
            if preserved_script_episodes
            else _join_script_parts(*(preserved_script_batches[episode] for episode in preserved_starts))
        )
        previous_batch_candidates = [
            episode
            for episode in sorted(summary_by_batch)
            if episode + batch_size - 1 < start_episode
        ]
        previous_batch_start = previous_batch_candidates[-1] if previous_batch_candidates else None

        if preserved_script:
            variables[ALL_SCRIPT] = preserved_script
            variables[LOCAL_COMMITTED_SCRIPT] = preserved_script
        else:
            variables.pop(ALL_SCRIPT, None)
            variables.pop(LOCAL_COMMITTED_SCRIPT, None)

        if previous_batch_start and preserved_summary_batches.get(previous_batch_start):
            variables[LAST_SUMMARY] = preserved_summary_batches[previous_batch_start]
        else:
            variables.pop(LAST_SUMMARY, None)

        preserved_appearance_memory = (
            copy.deepcopy(preserved_appearance_batches.get(previous_batch_start))
            if previous_batch_start in preserved_appearance_batches
            else {}
        )
        if preserved_appearance_memory:
            variables[APPEARANCE_CONTINUITY_MEMORY] = preserved_appearance_memory
        else:
            variables.pop(APPEARANCE_CONTINUITY_MEMORY, None)

        variables[LOCAL_SCRIPT_BATCHES] = _string_keyed_batch_map(preserved_script_batches)
        variables[LOCAL_SCRIPT_EPISODES] = _string_keyed_batch_map(preserved_script_episodes)
        variables[LOCAL_SUMMARY_BY_BATCH] = _string_keyed_batch_map(preserved_summary_batches)
        variables[LOCAL_APPEARANCE_MEMORY_BY_BATCH] = _string_keyed_batch_map(preserved_appearance_batches)
        total_episodes = int(snapshot.get("total_episodes") or 0)
        completed_batches = len(
            [
                batch
                for batch in iter_episode_batches(total_episodes, batch_size=batch_size)
                if batch.start_episode < start_episode
            ]
        )
        variables[LOCAL_COMPLETED_BATCHES] = completed_batches
        variables[LOCAL_CURRENT_BATCH_INDEX] = completed_batches
        variables[LOCAL_CURRENT_BATCH_STAGE] = "script"
        variables[BATCH_START_EPISODE] = int(start_episode)
        variables.pop(BATCH_SCRIPT, None)
        variables.pop(LOCAL_HOOK_CHECKPOINT_START, None)
        variables.pop(LOCAL_DIALOGUE_CHECKPOINT_START, None)
        variables.pop(LOCAL_SCRIPT_CHECKPOINT_START, None)

    def _rollback_progress_percent(self, snapshot: dict[str, Any]) -> int:
        return self._snapshot_progress_metrics(snapshot)["progress_percent"]

    def _asset_summary(
        self,
        snapshot: dict[str, Any],
        *,
        include_private: bool,
        use_teaser: bool,
    ) -> dict[str, Any]:
        input_payload = snapshot.get("input_payload") or {}
        artifacts = snapshot.get("artifacts") or {}
        progress_metrics = self._snapshot_progress_metrics(snapshot)
        story_outline = str(
            input_payload.get("story_outline")
            or artifacts.get("story_outline")
            or ""
        ).strip()
        final_script = self._best_final_script_text(snapshot)
        summary = self._fallback_story_teaser(story_outline) if use_teaser else ""
        if not summary:
            summary = story_outline or "这个作品还没有填写故事梗概。"
        payload = {
            "project_id": snapshot.get("project_id"),
            "task_id": snapshot.get("task_id"),
            "title": artifacts.get("script_title_content") or snapshot.get("title") or input_payload.get("title") or "未命名剧本",
            "summary": summary[:360],
            "status": snapshot.get("status"),
            "visibility": snapshot.get("visibility") or "private",
            "updated_at": snapshot.get("updated_at"),
            "created_at": snapshot.get("created_at"),
            "has_final": bool(final_script),
            "message": _public_status_message(snapshot),
            "current_stage": snapshot.get("current_stage"),
            "current_stage_label": snapshot.get("current_stage_label") or "待开始",
            "current_batch": snapshot.get("current_batch"),
            "progress_percent": progress_metrics["progress_percent"],
            "generated_episodes": progress_metrics["generated_episodes"],
            "total_episodes": int(snapshot.get("total_episodes") or 0),
            "model_label": ((snapshot.get("model_option") or {}).get("label") or ""),
            "completion_confirmed": _completion_confirmed(snapshot),
            "awaiting_user_confirmation": _awaiting_completion_confirmation(snapshot),
            "cache_notice": _cache_notice(snapshot),
        }
        if include_private:
            payload["final_preview"] = final_script[:500]
        return payload

    def _story_teaser_for_snapshot(self, snapshot: dict[str, Any]) -> str:
        input_payload = snapshot.get("input_payload") or {}
        artifacts = snapshot.get("artifacts") or {}
        story_outline = str(
            artifacts.get("story_outline")
            or input_payload.get("story_outline")
            or ""
        ).strip()
        if not story_outline:
            return ""

        has_final = bool(self._best_final_script_text(snapshot))
        if str(snapshot.get("status") or "") != "completed" or not has_final:
            return self._fallback_story_teaser(story_outline)

        cached_teaser = str(artifacts.get(STORY_TEASER_ARTIFACT) or "").strip()
        cached_source = str(artifacts.get(STORY_TEASER_SOURCE_ARTIFACT) or "").strip()
        if cached_teaser and cached_source == story_outline:
            return cached_teaser

        teaser = self._generate_story_teaser(story_outline) or self._fallback_story_teaser(story_outline)
        self._cache_story_teaser(snapshot, teaser, story_outline)
        return teaser

    def _fallback_story_teaser(self, story_outline: str) -> str:
        condensed = " ".join(str(story_outline or "").replace("\r", "\n").split())
        return condensed[:88] if condensed else "这个作品还没有填写故事梗概。"

    def _generate_story_teaser(self, story_outline: str) -> str:
        """社区/资产摘要不再额外调用模型生成，统一走本地梗概截断。"""
        return ""

    def _cache_story_teaser(
        self,
        snapshot: dict[str, Any],
        teaser: str,
        story_outline: str,
    ) -> None:
        project_id = int(snapshot.get("project_id") or 0)
        if project_id <= 0 or not teaser:
            return
        artifacts_update = {
            STORY_TEASER_ARTIFACT: teaser,
            STORY_TEASER_SOURCE_ARTIFACT: story_outline,
        }
        record = self._projects.get(project_id)
        if record is not None:
            self._update_snapshot(record, artifacts=artifacts_update)
            snapshot.setdefault("artifacts", {}).update(artifacts_update)
            return

        persisted = copy.deepcopy(snapshot)
        persisted.setdefault("artifacts", {}).update(artifacts_update)
        self._project_path(project_id).write_text(
            json.dumps(persisted, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        snapshot.setdefault("artifacts", {}).update(artifacts_update)

    def _run_task(self, record: TaskRecord) -> None:
        self._update_snapshot(record, status="running", message="开始执行工作流。")
        runtime: WorkflowRuntime | None = None
        try:
            workflow_input = WorkflowInput.from_dict(record.input_payload)
            spec = None if use_fastgpt_backend() else WorkflowSpec(record.workflow_spec_path)
            runtime = WorkflowRuntime(manager=self, record=record, spec=spec)

            state = run_configured_workflow(
                workflow_input,
                workflow_spec_path=record.workflow_spec_path,
                runtime=runtime,
                model_option=record.model_option,
                resume_snapshot=record.resume_snapshot,
            )

            if state.halted_message:
                runtime.sync_from_state(state)
                self._update_snapshot(
                    record,
                    status="failed",
                    current_stage="validation",
                    current_stage_label=STAGE_LABELS["validation"],
                    message=state.halted_message,
                    error=state.halted_message,
                    progress_percent=0,
                )
                return

            runtime.set_stage("finalize", "正在整理最终输出。", progress_percent=100)
            runtime.sync_from_state(state)
            self._update_snapshot(
                record,
                status="completed",
                current_stage="finished",
                current_stage_label=STAGE_LABELS["finished"],
                message=COMPLETION_PENDING_MESSAGE,
                finished_at=now_iso(),
                progress_percent=100,
                generated_episodes=record.snapshot.get("total_episodes", 0),
                prompt_fixes=state.prompt_fixes,
                completion_confirmed=False,
                awaiting_user_confirmation=True,
                cache_retained=True,
            )
        except TaskTerminated as exc:
            if runtime is not None:
                self._append_log(
                    record,
                    title="任务已终止",
                    message="已保留终止前的阶段、进度和中间产物。",
                )
            self._update_snapshot(
                record,
                status="terminated",
                message=TERMINATED_PUBLIC_MESSAGE,
                error=str(exc),
                finished_at=now_iso(),
            )
        except Exception as exc:
            logger.exception("任务执行失败: %s", record.task_id)
            if runtime is not None:
                self._append_log(
                    record,
                    title="任务失败",
                    message=f"已保留失败前的阶段、进度和中间产物。错误：{exc}",
                )
            # 失败时先退回最近一次稳定 checkpoint，再对外标记 failed。
            # 这样 retry/继续生成看到的是“上一个成功步骤”的缓存，而不是半写入状态。
            self._restore_from_resume_checkpoint(record)
            self._update_snapshot(
                record,
                status="failed",
                message=FAILED_PUBLIC_MESSAGE,
                error=str(exc),
                finished_at=now_iso(),
            )

    def _get_task_record_for_user(self, task_id: str, user_id: int | None) -> TaskRecord:
        record = self._tasks.get(task_id)
        if not record:
            raise ValueError("任务不存在")
        if user_id is not None and int(record.user_id) != int(user_id):
            raise ValueError("您没有权限操作该任务")
        return record

    def pause_task(self, task_id: str, user_id: int | None = None) -> dict[str, Any]:
        record = self._get_task_record_for_user(task_id, user_id)
        snapshot = record.clone_snapshot()
        status = snapshot.get("status")
        if status in {"paused", "pausing"}:
            return self._public_snapshot(snapshot)
        if status not in {"pending", "running"}:
            raise ValueError("只有进行中的任务才能暂停")
        record.control.request_pause()
        self._append_log(
            record,
            title="控制动作：暂停请求",
            message="暂停指令已发出，当前节点完成后会暂停。",
        )
        self._update_snapshot(
            record,
            status="pausing",
            message="暂停指令已发出，当前节点完成后会暂停。",
        )
        return self._public_snapshot(record.clone_snapshot())

    def resume_task(self, task_id: str, user_id: int | None = None) -> dict[str, Any]:
        record = self._get_task_record_for_user(task_id, user_id)
        snapshot = record.clone_snapshot()
        status = snapshot.get("status")
        if status == "running" and not record.control.is_pause_requested():
            return self._public_snapshot(snapshot)
        if status not in {"paused", "pausing", "running"}:
            raise ValueError("只有已暂停或正在暂停的任务才能继续")
        record.control.request_resume()
        self._append_log(
            record,
            title="控制动作：继续请求",
            message="继续指令已发出，任务恢复执行。",
        )
        self._update_snapshot(
            record,
            status="running",
            message="继续指令已发出，任务恢复执行。",
        )
        return self._public_snapshot(record.clone_snapshot())

    def retry_task(self, task_id: str, user_id: int | None = None) -> dict[str, Any]:
        snapshot = self.get_task_snapshot(task_id, user_id=user_id, public_view=False)
        if not snapshot:
            raise ValueError("任务不存在")
        status = snapshot.get("status")
        if status in PROJECT_RUNNING_STATUSES:
            raise ValueError("任务仍在执行中，不能重复重试")
        if status == "completed":
            raise ValueError("任务已完成，无需继续生成")

        project_id = int(snapshot.get("project_id") or 0)
        if project_id <= 0:
            raise ValueError("项目记录缺少 project_id，无法继续")

        old_task_id = str(snapshot.get("task_id") or task_id)
        new_task_id = uuid.uuid4().hex[:12]
        resume_base = snapshot.get("_resume_checkpoint")
        if not isinstance(resume_base, dict):
            resume_base = snapshot
        resume_snapshot = copy.deepcopy(resume_base)
        model_option = settings.resolve_model_selection(
            (snapshot.get("model_option") or {}).get("id")
        )
        new_snapshot = copy.deepcopy(resume_base)
        new_snapshot.update(
            {
                "task_id": new_task_id,
                "status": "pending",
                "message": "已回退到上一个成功步骤，等待继续生成。",
                "error": None,
                "retry_of_task_id": old_task_id,
                "updated_at": now_iso(),
                "finished_at": None,
                "completion_confirmed": False,
                "awaiting_user_confirmation": False,
                "cache_retained": True,
                "wait_elapsed_ms": 0,
                "wait_started_at": now_iso(),
            }
        )

        record = TaskRecord(
            user_id=int(snapshot.get("user_id") or user_id or 0),
            project_id=project_id,
            task_id=new_task_id,
            workflow_spec_path=str(snapshot.get("workflow_spec_path", "")),
            input_payload=snapshot.get("input_payload", {}),
            model_option=model_option,
            snapshot=new_snapshot,
            resume_snapshot=resume_snapshot,
        )
        with self._lock:
            self._tasks.pop(old_task_id, None)
            self._tasks[new_task_id] = record
            self._projects[project_id] = record
            self._remember_latest_project(record.user_id, project_id)
        self._append_log(
            record,
            title="控制动作：继续失败任务",
            message="将从上一个成功步骤继续执行；已完成步骤会跳过，失败步骤会重新尝试。",
        )
        self._save_resume_checkpoint(record)
        self._persist_snapshot(record)

        thread = threading.Thread(
            target=self._run_task,
            args=(record,),
            daemon=True,
            name=f"workflow-task-{new_task_id}",
        )
        record.thread = thread
        thread.start()
        return self._public_snapshot(record.clone_snapshot())

    def restart_project(
        self,
        project_id: int,
        *,
        user_id: int,
        input_payload: dict[str, Any],
        workflow_spec_path: str,
        model_selection_id: str | None,
    ) -> dict[str, Any]:
        snapshot = self.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot:
            raise ValueError("项目不存在或无权操作")

        status = str(snapshot.get("status") or "")
        if status in PROJECT_RUNNING_STATUSES:
            raise ValueError("任务仍在执行中，不能重新开始")

        old_task_id = str(snapshot.get("task_id") or "").strip()
        new_task_id = uuid.uuid4().hex[:12]
        model_option = settings.resolve_model_selection(model_selection_id)

        new_snapshot = {
            "user_id": int(user_id),
            "project_id": int(project_id),
            "task_id": new_task_id,
            "status": "pending",
            "title": str(input_payload.get("title", "")).strip() or str(snapshot.get("title") or "").strip(),
            "message": "正在同一资产下重新开始生成。",
            "created_at": snapshot.get("created_at") or now_iso(),
            "updated_at": now_iso(),
            "workflow_spec_path": workflow_spec_path,
            "visibility": str(snapshot.get("visibility") or "private"),
            "model_option": {
                "id": model_option.id,
                "label": self._model_alias(model_option.provider),
                "provider": model_option.provider,
                "model": model_option.model,
            }
            if model_option
            else None,
            "input_payload": copy.deepcopy(input_payload),
            "artifacts": {},
            "logs": [],
            "prompt_fixes": [],
            "progress_percent": 0,
            "generated_episodes": 0,
            "total_episodes": int(input_payload.get("total_episodes", 0) or 0),
            "current_stage": "validation",
            "current_stage_label": STAGE_LABELS["validation"],
            "current_node_id": None,
            "current_node_name": None,
            "current_batch": None,
            "completion_confirmed": False,
            "awaiting_user_confirmation": False,
            "cache_retained": True,
            "debug_state": {},
            "restart_of_task_id": old_task_id or None,
            "finished_at": None,
            "error": None,
            "wait_elapsed_ms": 0,
            "wait_started_at": now_iso(),
        }

        record = TaskRecord(
            user_id=int(user_id),
            project_id=int(project_id),
            task_id=new_task_id,
            workflow_spec_path=workflow_spec_path,
            input_payload=copy.deepcopy(input_payload),
            model_option=model_option,
            snapshot=new_snapshot,
            resume_snapshot=None,
        )

        with self._lock:
            if old_task_id:
                self._tasks.pop(old_task_id, None)
            self._tasks[new_task_id] = record
            self._projects[int(project_id)] = record
            self._remember_latest_project(int(user_id), int(project_id))

        self._save_resume_checkpoint(record)
        self._persist_snapshot(record)

        thread = threading.Thread(
            target=self._run_task,
            args=(record,),
            daemon=True,
            name=f"workflow-task-{new_task_id}",
        )
        record.thread = thread
        thread.start()
        return self._public_snapshot(record.clone_snapshot())

    def terminate_task(self, task_id: str, user_id: int | None = None) -> dict[str, Any]:
        record = self._get_task_record_for_user(task_id, user_id)
        snapshot = record.clone_snapshot()
        if snapshot.get("status") in {"completed", "terminated"}:
            return self._public_snapshot(snapshot)
        if snapshot.get("status") == "failed":
            self._append_log(
                record,
                title="控制动作：终止失败任务",
                message="失败任务已标记为终止，失败前的阶段和中间产物已保留。",
            )
            self._update_snapshot(
                record,
                status="terminated",
                message="任务已终止，失败前的阶段和中间产物已保留，可直接重新开始。",
                finished_at=now_iso(),
            )
            return self._public_snapshot(record.clone_snapshot())
        record.control.request_terminate()
        self._append_log(
            record,
            title="控制动作：终止请求",
            message="终止指令已发出，当前节点结束后会停止。",
        )
        self._update_snapshot(
            record,
            status="terminated",
            message=TERMINATED_PUBLIC_MESSAGE,
            finished_at=now_iso(),
        )
        return self._public_snapshot(record.clone_snapshot())

    def clear_project(self, project_id: int, user_id: int | None = None) -> None:
        record = self._projects.get(project_id)
        owner_user_id: int | None = None
        if record:
            if user_id is not None and int(record.user_id) != int(user_id):
                raise ValueError("您没有权限清空该项目")
            snapshot = record.clone_snapshot()
            owner_user_id = int(snapshot.get("user_id") or record.user_id or 0)
            record.control.request_terminate()
            with record.lock:
                record.snapshot["_deleted"] = True
            self._tasks.pop(record.task_id, None)
            self._projects.pop(project_id, None)

        path = self._project_path(project_id)
        if path.exists():
            if user_id is not None:
                try:
                    snapshot = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    snapshot = {}
                if not self._snapshot_belongs_to_user(snapshot, user_id):
                    raise ValueError("您没有权限清空该项目")
                owner_user_id = int(snapshot.get("user_id") or owner_user_id or 0)
            path.unlink()

        latest_by_user = dict(self._index.get("latest_project_by_user", {}))
        if owner_user_id is not None and latest_by_user.get(str(owner_user_id)) == project_id:
            latest_by_user.pop(str(owner_user_id), None)
            self._index["latest_project_by_user"] = latest_by_user
        if self._index.get("latest_project_id") == project_id:
            self._index["latest_project_id"] = None
        self._save_index()

    def _snapshot_artifacts_dict(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        artifacts = snapshot.get("artifacts")
        return artifacts if isinstance(artifacts, dict) else {}

    def _snapshot_debug_variables(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        debug_state = snapshot.get("debug_state")
        if not isinstance(debug_state, dict):
            return {}
        variables = debug_state.get("variables")
        return variables if isinstance(variables, dict) else {}

    def _snapshot_input_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        input_payload = snapshot.get("input_payload")
        return input_payload if isinstance(input_payload, dict) else {}

    def _snapshot_export_value(
        self,
        snapshot: dict[str, Any],
        *,
        artifact_keys: tuple[str, ...] = (),
        variable_keys: tuple[str, ...] = (),
        input_keys: tuple[str, ...] = (),
    ) -> Any:
        artifacts = self._snapshot_artifacts_dict(snapshot)
        for key in artifact_keys:
            value = artifacts.get(key)
            if value not in (None, "", {}, []):
                return value
        variables = self._snapshot_debug_variables(snapshot)
        for key in variable_keys:
            value = variables.get(key)
            if value not in (None, "", {}, []):
                return value
        input_payload = self._snapshot_input_payload(snapshot)
        for key in input_keys:
            value = input_payload.get(key)
            if value not in (None, "", {}, []):
                return value
        return None

    def _sanitize_export_section_text(
        self,
        value: Any,
        *,
        banned_prefixes: tuple[str, ...] = (),
    ) -> str:
        cleaned = clean_export_readable_text(value)
        if not cleaned:
            return ""
        if not banned_prefixes:
            return cleaned
        lines = [
            line
            for line in cleaned.splitlines()
            if str(line).strip()
            and not any(str(line).strip().startswith(prefix) for prefix in banned_prefixes)
        ]
        return "\n".join(lines).strip()

    def _sentence_fragment(self, value: Any) -> str:
        return clean_export_readable_text(value).strip().strip("，。；： ")

    def _snapshot_record_for_update(
        self,
        project_id: int,
        snapshot: dict[str, Any],
    ) -> TaskRecord:
        existing = self._projects.get(project_id)
        if existing is not None:
            return existing
        return TaskRecord(
            user_id=int(snapshot.get("user_id") or 0),
            project_id=project_id,
            task_id=str(snapshot.get("task_id", "")),
            workflow_spec_path=str(snapshot.get("workflow_spec_path", "")),
            input_payload=snapshot.get("input_payload", {}),
            model_option=settings.resolve_model_selection(
                (snapshot.get("model_option") or {}).get("id")
            ),
            snapshot=copy.deepcopy(snapshot),
        )

    def _apply_snapshot_variable_artifact_updates(
        self,
        project_id: int,
        snapshot: dict[str, Any],
        *,
        artifact_updates: dict[str, Any],
        variable_updates: dict[str, Any],
    ) -> None:
        if artifact_updates:
            artifacts = snapshot.setdefault("artifacts", {})
            if isinstance(artifacts, dict):
                artifacts.update(artifact_updates)
        debug_state = snapshot.setdefault("debug_state", {})
        if not isinstance(debug_state, dict):
            debug_state = {}
            snapshot["debug_state"] = debug_state
        debug_variables = debug_state.setdefault("variables", {})
        if not isinstance(debug_variables, dict):
            debug_variables = {}
            debug_state["variables"] = debug_variables
        debug_variables.update(variable_updates)

        record = self._snapshot_record_for_update(project_id, snapshot)
        record_debug_state = copy.deepcopy(
            record.snapshot.get("debug_state") if isinstance(record.snapshot.get("debug_state"), dict) else {}
        )
        if not isinstance(record_debug_state, dict):
            record_debug_state = {}
        record_debug_variables = record_debug_state.setdefault("variables", {})
        if not isinstance(record_debug_variables, dict):
            record_debug_variables = {}
            record_debug_state["variables"] = record_debug_variables
        record_debug_variables.update(variable_updates)
        self._update_snapshot(
            record,
            artifacts=artifact_updates,
            debug_state=record_debug_state,
        )

    def _build_export_character_naturalize_stage_variables(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        structured = self._snapshot_export_value(
            snapshot,
            artifact_keys=("characters", "character_bios"),
            variable_keys=(CHARACTERS, CHARACTER_VAR),
            input_keys=("character_bios",),
        )
        source_value = _jsonish_value(structured)
        if source_value is None:
            source_text = str(structured or "").strip()
        else:
            try:
                source_text = json.dumps(source_value, ensure_ascii=False, indent=2)
            except Exception:
                source_text = str(structured or "").strip()
        return {
            UNSTRUCTURED_SOURCE: source_text,
            UNSTRUCTURED_CONTENT_KIND: "generic",
            UNSTRUCTURED_SOURCE_VAR: source_text,
            UNSTRUCTURED_KIND_VAR: "generic",
        }

    def _ensure_export_character_natural_language(
        self,
        snapshot: dict[str, Any],
        *,
        project_id: int,
    ) -> str:
        structured = self._snapshot_export_value(
            snapshot,
            artifact_keys=("characters", "character_bios"),
            variable_keys=(CHARACTERS, CHARACTER_VAR),
            input_keys=("character_bios",),
        )
        existing = self._snapshot_export_value(
            snapshot,
            artifact_keys=("character_natural_language",),
            variable_keys=(CHARACTER_NATURAL_LANGUAGE_VAR,),
        ) or self._snapshot_export_value(snapshot, artifact_keys=("character_summary",))
        preferred, issues = _select_character_display_text(existing, structured)
        existing_text = _meaningful_stage_output_text(self._sanitize_export_section_text(existing))
        if existing_text and not issues:
            logger.info("character_natural_language_export status=reuse_existing project_id=%s", project_id)
            return preferred
        if existing_text and issues:
            logger.warning(
                "character_natural_language_export status=reject_existing project_id=%s issues=%s preview=%s",
                project_id,
                ",".join(issues),
                _truncate_log_text(existing_text, max_chars=240),
            )

        if structured in (None, "", {}, []):
            logger.info("character_natural_language_export status=skip_missing_characters project_id=%s", project_id)
            return ""
        if not use_fastgpt_backend():
            logger.info("character_natural_language_export status=skip_non_fastgpt_backend project_id=%s", project_id)
            return ""

        try:
            workflow_input = WorkflowInput.from_dict(self._snapshot_input_payload(snapshot))
            stage_variables = self._build_export_character_naturalize_stage_variables(snapshot)
            from ..orchestrators.fastgpt_hybrid_workflow import run_stage_with_contract_guard
            from .fastgpt_client import FastGPTClient
            from .fastgpt_contracts import STAGE_CHARACTERS_NATURALIZE

            state = WorkflowState(user_input=workflow_input, variables=dict(stage_variables))
            runner = FastGPTClient()
            output = run_stage_with_contract_guard(
                state,
                runner,
                STAGE_CHARACTERS_NATURALIZE,
                stage_variables,
                stage_key="character",
                message="正在整理人物小传自然语言说明。",
                output_field=CHARACTER_NATURAL_LANGUAGE_VAR,
                sync_output_to_state=False,
            )
            natural = str(output.get(CHARACTER_NATURAL_LANGUAGE_VAR) or "").strip()
            natural = _meaningful_stage_output_text(self._sanitize_export_section_text(natural))
            issues = _character_natural_text_quality_issues(natural, structured) if natural else []
            if not natural or issues:
                logger.warning(
                    "character_natural_language_export status=empty_or_rejected_after_stage project_id=%s issues=%s preview=%s",
                    project_id,
                    ",".join(issues),
                    _truncate_log_text(natural, max_chars=240),
                )
                return ""
            self._apply_snapshot_variable_artifact_updates(
                project_id,
                snapshot,
                artifact_updates={
                    "character_natural_language": natural,
                    "character_summary": natural,
                },
                variable_updates={CHARACTER_NATURAL_LANGUAGE_VAR: natural},
            )
            logger.info(
                "character_natural_language_export status=generated_and_persisted project_id=%s",
                project_id,
            )
            return natural
        except Exception as exc:
            logger.warning(
                "character_natural_language_export status=fallback_after_failure project_id=%s preview=%s",
                project_id,
                _truncate_log_text(str(exc), max_chars=320),
            )
            return ""

    def _build_export_appearance_stage_variables(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        artifacts = self._snapshot_artifacts_dict(snapshot)
        input_payload = self._snapshot_input_payload(snapshot)
        variables = copy.deepcopy(self._snapshot_debug_variables(snapshot))
        if not isinstance(variables, dict):
            variables = {}

        def fill(key: str, *candidates: Any) -> None:
            if variables.get(key) not in (None, "", {}, []):
                return
            for candidate in candidates:
                if candidate not in (None, "", {}, []):
                    variables[key] = candidate
                    return

        fill(WORLDVIEW, artifacts.get("worldview"), input_payload.get("worldview"))
        fill(STORY_OUTLINE, artifacts.get("story_outline"), input_payload.get("story_outline"))
        fill(
            EPISODE_PLAN,
            artifacts.get("normalized_episode_plan"),
            artifacts.get("episode_plan"),
            input_payload.get("episode_plan"),
        )
        fill(USER_CHARACTERS, artifacts.get("character_bios"), input_payload.get("character_bios"))
        fill(CHARACTERS, artifacts.get("characters"), artifacts.get("character_bios"))
        fill(SCENES, artifacts.get("scene_json"), artifacts.get("core_scene_input"))
        fill(
            CHARACTER_ALIAS_NAMING_RULES,
            artifacts.get("character_alias_naming_rules"),
            input_payload.get("character_alias_naming_rules"),
            input_payload.get("alias_naming_rules"),
        )
        fill(APPEARANCE_MAPPING, artifacts.get("appearance_mapping"))
        return variables

    def _ensure_export_appearance_natural_language(
        self,
        snapshot: dict[str, Any],
        *,
        project_id: int,
    ) -> str:
        existing = _meaningful_stage_output_text(
            self._sanitize_export_section_text(
                self._snapshot_export_value(
                    snapshot,
                    artifact_keys=(APPEARANCE_NATURAL_LANGUAGE_ARTIFACT,),
                    variable_keys=(APPEARANCE_NATURAL_LANGUAGE_VAR, "c7VnQ4eX"),
                )
            )
        )
        if existing:
            logger.info("appearance_natural_language_export status=reuse_existing project_id=%s", project_id)
            return existing

        structured = self._snapshot_export_value(
            snapshot,
            artifact_keys=("appearance_mapping",),
            variable_keys=(APPEARANCE_MAPPING, APPEARANCE_MAPPING_VAR),
        )
        if structured in (None, "", {}, []):
            logger.info("appearance_natural_language_export status=skip_missing_mapping project_id=%s", project_id)
            return ""
        if not use_fastgpt_backend():
            logger.info("appearance_natural_language_export status=skip_non_fastgpt_backend project_id=%s", project_id)
            return ""

        try:
            workflow_input = WorkflowInput.from_dict(self._snapshot_input_payload(snapshot))
            stage_variables = self._build_export_appearance_stage_variables(snapshot)
            from ..orchestrators.fastgpt_hybrid_workflow import run_stage_with_contract_guard
            from .fastgpt_client import FastGPTClient
            from .fastgpt_contracts import STAGE_APPEARANCE_ALIAS_UNSTRUCTURED

            state = WorkflowState(user_input=workflow_input, variables=dict(stage_variables))
            runner = FastGPTClient()
            output = run_stage_with_contract_guard(
                state,
                runner,
                STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
                stage_variables,
                stage_key="appearance",
                message="正在整理服装版本自然语言说明。",
                output_field=APPEARANCE_NATURAL_LANGUAGE_VAR,
                sync_output_to_state=False,
            )
            natural = str(output.get(APPEARANCE_NATURAL_LANGUAGE_VAR) or "").strip()
            natural = _meaningful_stage_output_text(self._sanitize_export_section_text(natural))
            if not natural:
                logger.warning(
                    "appearance_natural_language_export status=empty_after_stage project_id=%s",
                    project_id,
                )
                return ""
            self._apply_snapshot_variable_artifact_updates(
                project_id,
                snapshot,
                artifact_updates={APPEARANCE_NATURAL_LANGUAGE_ARTIFACT: natural},
                variable_updates={APPEARANCE_NATURAL_LANGUAGE_VAR: natural},
            )
            logger.info(
                "appearance_natural_language_export status=generated_and_persisted project_id=%s",
                project_id,
            )
            return natural
        except Exception as exc:
            logger.warning(
                "appearance_natural_language_export status=fallback_after_failure project_id=%s preview=%s",
                project_id,
                _truncate_log_text(str(exc), max_chars=320),
            )
            return ""

    def _extract_labeled_export_segment(
        self,
        value: Any,
        *,
        start_labels: tuple[str, ...],
        stop_labels: tuple[str, ...] = (),
    ) -> str:
        raw_text = _strip_export_code_fences(str(value or "")).replace("\r", "")
        parsed = _jsonish_value(raw_text)
        text = clean_export_readable_text(parsed) if parsed is not None else raw_text.strip()
        if not text:
            return ""
        lines = [str(line or "").strip() for line in text.replace("\r", "").split("\n")]
        capturing = False
        captured: list[str] = []
        for line in lines:
            if not line:
                if capturing and captured and captured[-1] != "":
                    captured.append("")
                continue
            matched_start = next((label for label in start_labels if line.startswith(label)), "")
            if matched_start:
                capturing = True
                remainder = line[len(matched_start):].lstrip("：: ")
                if remainder:
                    captured.append(remainder)
                continue
            if capturing and any(line.startswith(label) for label in stop_labels):
                break
            if capturing:
                captured.append(line)
        if not captured:
            return text
        while captured and captured[0] == "":
            captured.pop(0)
        while captured and captured[-1] == "":
            captured.pop()
        return "\n".join(captured).strip()

    def _story_outline_fallback_text(self, value: Any) -> str:
        parsed = _jsonish_value(value)
        if isinstance(parsed, dict):
            segments: list[str] = []
            opening = self._sentence_fragment(parsed.get("opening"))
            inciting = self._sentence_fragment(parsed.get("inciting_incident"))
            early_goal = self._sentence_fragment(parsed.get("early_goal"))
            middle = self._sentence_fragment(parsed.get("middle_escalation"))
            relationship = self._sentence_fragment(parsed.get("relationship_changes"))
            crisis = self._sentence_fragment(parsed.get("larger_crisis_or_truth"))
            climax = self._sentence_fragment(parsed.get("final_climax"))
            ending = self._sentence_fragment(parsed.get("ending_resolution"))
            theme = self._sentence_fragment(parsed.get("theme"))
            if opening:
                segments.append(f"故事从{opening}展开。")
            if inciting:
                segments.append(f"主角因为{inciting}卷入冲突。")
            if early_goal:
                segments.append(f"前期的明确目标是{early_goal}。")
            if middle:
                segments.append(f"随着剧情推进，{middle}。")
            if relationship:
                segments.append(f"人物关系也在这个过程中逐渐变化，{relationship}。")
            if crisis:
                segments.append(f"更大的危机与真相随后浮出水面：{crisis}。")
            if climax:
                segments.append(f"最终故事在{climax}中迎来高潮。")
            if ending:
                segments.append(f"结局落在{ending}。")
            if theme:
                segments.append(f"整部作品最终指向的主题是{theme}。")
            if segments:
                return "\n".join(segments).strip()
        return self._sanitize_export_section_text(value)

    def _story_outline_export_text(self, snapshot: dict[str, Any]) -> str:
        natural = self._snapshot_export_value(
            snapshot,
            artifact_keys=("framework_natural_language",),
            variable_keys=(FRAMEWORK_NATURAL_LANGUAGE,),
        )
        natural_excerpt = self._extract_labeled_export_segment(
            natural,
            start_labels=("故事梗概", "故事简介"),
            stop_labels=("主要人物小传", "人物小传", "核心场景说明", "核心场景", "分集计划说明", "分集计划"),
        )
        text = _meaningful_stage_output_text(self._sanitize_export_section_text(natural_excerpt))
        if text:
            return text
        source = self._snapshot_export_value(
            snapshot,
            artifact_keys=("story_outline",),
            variable_keys=(STORY_OUTLINE,),
            input_keys=("story_outline",),
        )
        return self._story_outline_fallback_text(source)

    def _worldview_fallback_text(self, value: Any) -> str:
        parsed = _jsonish_value(value)
        if isinstance(parsed, dict):
            parts: list[str] = []
            summary = self._sentence_fragment(
                parsed.get("worldview_summary")
                or parsed.get("world_building_core")
                or parsed.get("worldview")
            )
            rules = clean_export_readable_text(parsed.get("social_rules") or parsed.get("rules"))
            atmosphere = self._sentence_fragment(parsed.get("atmosphere") or parsed.get("tone"))
            if summary:
                parts.append(summary if summary.endswith("。") else f"{summary}。")
            if rules:
                parts.append(f"这个世界的运行规则主要体现在：{rules}。")
            if atmosphere:
                parts.append(f"整体气质则偏向{atmosphere}。")
            if parts:
                return "\n".join(parts).strip()
        return self._sanitize_export_section_text(value)

    def _worldview_export_text(self, snapshot: dict[str, Any]) -> str:
        natural = self._snapshot_export_value(
            snapshot,
            artifact_keys=("worldview_natural_language",),
            variable_keys=(WORLDVIEW_NATURAL_LANGUAGE,),
        )
        text = _meaningful_stage_output_text(self._sanitize_export_section_text(natural))
        if text:
            return text
        source = self._snapshot_export_value(
            snapshot,
            artifact_keys=("worldview",),
            variable_keys=(WORLDVIEW,),
        )
        return self._worldview_fallback_text(source)

    def _character_export_text(self, snapshot: dict[str, Any]) -> str:
        banned = (
            "角色设计原则",
            "角色视觉风格命名策略",
            "角色角色设计原则",
            "character_design_principle",
            "character_visual_styling_naming_strategy",
            "character_role_design_principle",
            "character_registry",
            "character_alias_registry",
        )
        structured = self._snapshot_export_value(
            snapshot,
            artifact_keys=("characters", "character_bios"),
            variable_keys=(CHARACTERS, CHARACTER_VAR),
            input_keys=("character_bios",),
        )
        for candidate in (
            self._snapshot_export_value(snapshot, artifact_keys=("character_natural_language",)),
            self._snapshot_export_value(snapshot, variable_keys=(CHARACTER_NATURAL_LANGUAGE_VAR,)),
            self._snapshot_export_value(snapshot, artifact_keys=("character_summary",)),
        ):
            sanitized = self._sanitize_export_section_text(candidate, banned_prefixes=banned)
            text = _meaningful_stage_output_text(sanitized)
            issues = _character_natural_text_quality_issues(text, structured) if text else []
            if text and not issues:
                return text
            if sanitized and issues:
                logger.warning(
                    "character_export_text_rejected issues=%s preview=%s",
                    ",".join(issues),
                    _truncate_log_text(sanitized, max_chars=240),
                )
        characters = _character_items_from_value(structured)
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
            )
            growth = _meaningful_character_fragment(item.get("growth_arc") or item.get("plot_function"))
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
            if not fragments:
                fragments.append("人物设定暂未补充完整。")
            sections.append(f"{name}：" + "，".join(fragments).strip("，") + "。")
        return "\n".join(section for section in sections if section).strip()

    def _appearance_export_text(self, snapshot: dict[str, Any]) -> str:
        for candidate in (
            self._snapshot_export_value(snapshot, artifact_keys=(APPEARANCE_NATURAL_LANGUAGE_ARTIFACT,)),
            self._snapshot_export_value(snapshot, variable_keys=(APPEARANCE_NATURAL_LANGUAGE_VAR, "c7VnQ4eX")),
            self._snapshot_export_value(snapshot, artifact_keys=(APPEARANCE_NATURAL_LANGUAGE_ARTIFACT,)),
        ):
            text = _meaningful_stage_output_text(self._sanitize_export_section_text(candidate))
            if text:
                return text

        structured = self._snapshot_export_value(
            snapshot,
            artifact_keys=("appearance_mapping",),
            variable_keys=(APPEARANCE_MAPPING, APPEARANCE_MAPPING_VAR),
        )
        characters = _appearance_character_items_from_value(structured)
        if not characters:
            return ""
        blocks: list[str] = []
        for item in characters:
            role_name = self._sentence_fragment(
                item.get("default_name")
                or item.get("canonical_name")
                or item.get("character_name")
                or item.get("character_id")
            ) or "未命名角色"
            default_name = self._sentence_fragment(item.get("default_name") or item.get("canonical_name"))
            same_person_anchor = self._sentence_fragment(item.get("same_person_anchor"))
            forbidden = clean_export_readable_text(item.get("forbidden_generic_names"))
            variants = item.get("outfit_variants") if isinstance(item.get("outfit_variants"), list) else []
            variant_lines: list[str] = []
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                alias_name = self._sentence_fragment(variant.get("alias_name") or variant.get("default_name"))
                usage_rule = self._sentence_fragment(variant.get("usage_rule"))
                episode_hint = self._sentence_fragment(variant.get("episode_range_hint"))
                trigger_rule = self._sentence_fragment(
                    variant.get("scene_trigger_rules")
                    or variant.get("scene_names")
                    or variant.get("scene_types")
                    or variant.get("status_conditions")
                )
                detail_bits = [bit for bit in (usage_rule, episode_hint, trigger_rule) if bit]
                if alias_name:
                    if detail_bits:
                        variant_lines.append(f"{alias_name}：{'；'.join(detail_bits)}")
                    else:
                        variant_lines.append(alias_name)
            block_parts = [f"【角色】{role_name}"]
            if default_name:
                block_parts.append(f"默认称呼：{default_name}")
            if same_person_anchor:
                block_parts.append(f"固定识别锚点：{same_person_anchor}")
            if variant_lines:
                block_parts.append("服装版本与使用条件：" + "；".join(variant_lines))
            if forbidden:
                block_parts.append(f"禁止退回泛称：{forbidden}")
            blocks.append("\n".join(block_parts).strip())
        return "\n\n".join(block for block in blocks if block).strip()

    def _scene_export_text(self, snapshot: dict[str, Any]) -> str:
        for candidate in (
            self._snapshot_export_value(snapshot, artifact_keys=("scene_natural_language", "core_scene_summary")),
            self._snapshot_export_value(snapshot, variable_keys=(SCENE_NATURAL_LANGUAGE_VAR,)),
        ):
            text = _meaningful_stage_output_text(self._sanitize_export_section_text(candidate))
            if text:
                return text

        structured = self._snapshot_export_value(
            snapshot,
            artifact_keys=("scene_json", "core_scene_input"),
            variable_keys=(SCENES, SCENE_VAR),
            input_keys=("core_scene_input",),
        )
        scenes = _scene_items_from_value(structured)
        if not scenes:
            return ""
        blocks: list[str] = []
        for item in scenes:
            if not isinstance(item, dict):
                continue
            name = self._sentence_fragment(item.get("scene_name") or item.get("name")) or "核心场景"
            scene_type = self._sentence_fragment(item.get("scene_type"))
            story_function = self._sentence_fragment(item.get("story_function"))
            environment = self._sentence_fragment(item.get("environment_description"))
            atmosphere = self._sentence_fragment(item.get("atmosphere_description"))
            interaction = self._sentence_fragment(item.get("character_interaction_effect"))
            fragments = [bit for bit in (scene_type, story_function, environment, atmosphere, interaction) if bit]
            if not fragments:
                fragments.append("承载关键剧情推进。")
            blocks.append(f"{name}：{'，'.join(fragments).strip('，')}。")
        return "\n".join(block for block in blocks if block).strip()

    def _episode_plan_export_text(self, snapshot: dict[str, Any]) -> str:
        artifacts = self._snapshot_artifacts_dict(snapshot)
        display_text = self._snapshot_export_value(
            snapshot,
            artifact_keys=(EPISODE_PLAN_DISPLAY_ARTIFACT,),
        )
        if display_text:
            text = self._sanitize_export_section_text(display_text)
            if text:
                return text
        text = self._episode_plan_display_text(snapshot, artifacts)
        return self._sanitize_export_section_text(text)

    def _build_docx_export_source_text(self, snapshot: dict[str, Any]) -> str:
        """把正式产物组装成自然语言前置信息 + 正文，供 DOCX 导出使用。"""
        artifacts = self._snapshot_artifacts_dict(snapshot)
        input_payload = self._snapshot_input_payload(snapshot)
        title = str(
            artifacts.get("script_title_content")
            or snapshot.get("title")
            or input_payload.get("title")
            or f"project_{snapshot.get('project_id')}"
        ).strip()
        final_script = self._best_final_script_text(snapshot)
        if not final_script:
            return ""

        parts: list[str] = [title or f"project_{snapshot.get('project_id')}"]
        for heading, section_text in (
            ("故事梗概", self._story_outline_export_text(snapshot)),
            ("人物小传", self._character_export_text(snapshot)),
            ("人物服饰说明", self._appearance_export_text(snapshot)),
            ("核心场景", self._scene_export_text(snapshot)),
        ):
            cleaned = self._sanitize_export_section_text(section_text)
            if cleaned:
                parts.append(f"{heading}\n{cleaned}")

        script_section = (
            final_script
            if final_script.lstrip().startswith("剧本正文")
            else f"剧本正文\n{final_script}"
        )
        parts.append(script_section)
        return "\n\n".join(part.strip() for part in parts if str(part).strip()).strip() + "\n"

    def _build_character_setting_export_block(self, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        source_candidates = (
            artifacts.get("character_summary"),
            artifacts.get("character_bios"),
            artifacts.get("characters"),
            artifacts.get("user_characters"),
        )
        for candidate in source_candidates:
            normalized = self._coerce_existing_export_block(candidate, block_key="character_setting")
            if normalized:
                return normalized

        source_text = next((str(item).strip() for item in source_candidates if str(item or "").strip()), "")
        if not source_text:
            return None
        characters = self._parse_character_entries(source_text)
        if not characters:
            return None
        return {
            "character_setting": {
                "character_design_principle": self._summarize_export_text(source_text, limit=140),
                "characters": characters,
            }
        }

    def _build_scene_setting_export_block(self, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        source_candidates = (
            artifacts.get("core_scene_summary"),
            artifacts.get("scene_json"),
            artifacts.get("core_scene_input"),
            artifacts.get("user_scenes"),
        )
        for candidate in source_candidates:
            normalized = self._coerce_existing_export_block(candidate, block_key="scene_setting")
            if normalized:
                return normalized

        source_text = next((str(item).strip() for item in source_candidates if str(item or "").strip()), "")
        if not source_text:
            return None
        scenes = self._parse_scene_entries(source_text)
        if not scenes:
            return None
        return {
            "scene_setting": {
                "scene_design_principle": self._summarize_export_text(source_text, limit=180),
                "scenes": scenes,
            }
        }

    def _coerce_existing_export_block(
        self,
        candidate: Any,
        *,
        block_key: str,
    ) -> dict[str, Any] | None:
        value = self._coerce_jsonish_value(candidate)
        if value is None:
            return None
        if isinstance(value, dict) and isinstance(value.get(block_key), dict):
            return {block_key: value[block_key]}
        if block_key == "character_setting":
            if isinstance(value, dict) and isinstance(value.get("characters"), list):
                return {
                    "character_setting": {
                        "character_design_principle": self._summarize_export_text(candidate, limit=140),
                        "characters": [item for item in value.get("characters") or [] if isinstance(item, dict)],
                    }
                }
            if isinstance(value, list):
                items = [item for item in value if isinstance(item, dict)]
                if items:
                    return {
                        "character_setting": {
                            "character_design_principle": self._summarize_export_text(candidate, limit=140),
                            "characters": items,
                        }
                    }
        if block_key == "scene_setting":
            if isinstance(value, dict) and isinstance(value.get("scenes"), dict) and isinstance(
                value["scenes"].get("scene_setting"),
                dict,
            ):
                return {"scene_setting": value["scenes"]["scene_setting"]}
            if isinstance(value, dict) and isinstance(value.get("scenes"), list):
                return {
                    "scene_setting": {
                        "scene_design_principle": self._summarize_export_text(candidate, limit=180),
                        "scenes": [item for item in value.get("scenes") or [] if isinstance(item, dict)],
                    }
                }
            if isinstance(value, list):
                items = [item for item in value if isinstance(item, dict)]
                if items:
                    return {
                        "scene_setting": {
                            "scene_design_principle": self._summarize_export_text(candidate, limit=180),
                            "scenes": items,
                        }
                    }
        return None

    def _coerce_jsonish_value(self, value: Any) -> Any | None:
        if isinstance(value, (dict, list)):
            return value
        text = str(value or "").strip()
        if not text or text[0] not in "[{":
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        if isinstance(parsed, (dict, list)):
            return parsed
        return None

    def _parse_character_entries(self, text: str) -> list[dict[str, Any]]:
        blocks = self._split_character_blocks(text)
        if not blocks:
            return []
        entries: list[dict[str, Any]] = []
        for block in blocks:
            heading = str(block.get("heading") or "").strip()
            lines = block.get("lines") if isinstance(block.get("lines"), list) else []
            name, role_hint = self._parse_character_heading(heading)
            fields = self._parse_inline_fields(lines)
            story_role = self._pick_first_non_empty(
                fields,
                "人物定位",
                "身份定位",
                "故事角色",
            ) or role_hint
            core_motivation = self._pick_first_non_empty(
                fields,
                "核心欲望",
                "核心动机",
                "深层动机",
                "行为习惯与核心动机",
            )
            dramatic_value = self._pick_first_non_empty(
                fields,
                "主线作用",
                "戏剧价值",
                "人物小传",
                "关系特点",
            )
            personality_text = self._pick_first_non_empty(fields, "性格特点", "性格特质")
            appearance_anchor = self._pick_first_non_empty(fields, "稳定外貌识别锚点", "稳定识别锚点")
            entry = {
                "character_name": name or "未命名角色",
                "story_role": story_role or "角色设定",
                "core_motivation": core_motivation or "待补充",
                "dramatic_value": dramatic_value or story_role or "待补充",
            }
            personality = self._compact_dict(
                {
                    "traits": self._split_brief_items(personality_text),
                    "surface_impression": self._pick_first_non_empty(fields, "外貌特征", "外貌描述"),
                    "inner_contradiction": self._pick_first_non_empty(fields, "角色弱点", "深层动机"),
                }
            )
            family = self._compact_dict(
                {
                    "family_background": self._pick_first_non_empty(fields, "家庭背景", "家世"),
                    "upbringing": self._pick_first_non_empty(fields, "成长线", "成长经历"),
                    "key_family_influence": self._pick_first_non_empty(fields, "与主角关系", "与其他主要角色关系", "关系特点"),
                }
            )
            appearance = self._compact_dict(
                {
                    "overall_look": self._pick_first_non_empty(fields, "外貌特征", "外貌描述"),
                    "recognizable_features": self._split_brief_items(appearance_anchor, max_items=6),
                    "external_impression_effect": self._pick_first_non_empty(fields, "出场记忆点", "人物小传"),
                }
            )
            behavior = self._compact_dict(
                {
                    "emotional_response_pattern": self._pick_first_non_empty(fields, "行为习惯与核心动机", "角色弱点"),
                    "social_interaction_style": self._pick_first_non_empty(fields, "常见活动状态", "关系特点"),
                }
            )
            if personality:
                entry["personality"] = personality
            if family:
                entry["family"] = family
            if appearance:
                entry["appearance"] = appearance
            if behavior:
                entry["behavior"] = behavior
            entries.append(entry)
        return entries

    def _split_character_blocks(self, text: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        current_heading = ""
        current_lines: list[str] = []
        for raw_line in str(text or "").replace("\r", "").split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if self._looks_like_character_heading(line):
                if current_heading:
                    blocks.append({"heading": current_heading, "lines": current_lines[:]})
                current_heading = line
                current_lines = []
                continue
            if current_heading:
                current_lines.append(line)
        if current_heading:
            blocks.append({"heading": current_heading, "lines": current_lines[:]})
        return blocks

    def _looks_like_character_heading(self, line: str) -> bool:
        text = str(line or "").strip()
        if not text:
            return False
        if re.match(r"^\d+\.\s*[^\s]", text):
            return True
        if text.startswith("【") and "】" in text and "人物小传" not in text and "主要角色设定" not in text:
            suffix = text.split("】", 1)[1].strip()
            return bool(suffix)
        return False

    def _parse_character_heading(self, heading: str) -> tuple[str, str]:
        text = str(heading or "").strip()
        if not text:
            return "", ""
        if re.match(r"^\d+\.", text):
            body = re.sub(r"^\d+\.\s*", "", text)
            name = re.split(r"[（(]", body, maxsplit=1)[0].strip()
            role_hint = body[len(name):].strip("（）() ")
            return name, role_hint
        match = re.match(r"^【(?P<label>[^】]+)】\s*(?P<name>.+)$", text)
        if match:
            name = re.split(r"[（(]", match.group("name"), maxsplit=1)[0].strip()
            return name, match.group("label").strip()
        return text, ""

    def _parse_inline_fields(self, lines: list[str]) -> dict[str, str]:
        fields: dict[str, str] = {}
        current_key = ""
        for line in lines:
            text = str(line or "").strip()
            if not text:
                continue
            match = re.match(r"^(?P<key>[^：:]{1,24})[:：]\s*(?P<value>.*)$", text)
            if match:
                current_key = match.group("key").strip()
                value = match.group("value").strip()
                if current_key:
                    fields[current_key] = value
                continue
            if current_key and text:
                fields[current_key] = f"{fields.get(current_key, '')}\n{text}".strip()
        return fields

    def _parse_scene_entries(self, text: str) -> list[dict[str, Any]]:
        sections = self._parse_multiline_sections(text)
        area_items = self._parse_numbered_items(
            sections.get("核心场景区域")
            or sections.get("核心场景")
            or ""
        )
        conflict_items = self._parse_numbered_items(
            sections.get("冲突土壤")
            or sections.get("危险来源")
            or ""
        )
        visual_items = self._parse_numbered_items(
            sections.get("高频触发服装切换的场景类型")
            or ""
        )
        worldview_support = "\n".join(
            part for part in (
                sections.get("时代背景与世界观"),
                sections.get("时代背景"),
                sections.get("世界状态"),
            ) if part
        ).strip()
        interaction_effect = "\n".join(
            part for part in (
                sections.get("社会环境"),
                sections.get("生存规则与行动规则"),
                sections.get("社会身份要求"),
            ) if part
        ).strip()
        atmosphere = sections.get("整体氛围") or ""
        environment_suffix = "\n".join(
            part for part in (
                sections.get("环境条件与时间条件"),
                sections.get("环境条件触发"),
                sections.get("时间条件触发"),
            ) if part
        ).strip()

        if not area_items:
            merged_environment = self._summarize_export_text(
                "\n".join(part for part in (sections.get("核心场景区域"), environment_suffix) if part),
                limit=280,
            )
            return [self._compact_dict(
                {
                    "scene_name": "核心场景设定",
                    "scene_type": "故事舞台",
                    "story_function": self._summarize_export_text(text, limit=160),
                    "environment_description": merged_environment or self._summarize_export_text(text, limit=240),
                    "atmosphere_description": atmosphere or self._summarize_export_text(text, limit=120),
                    "character_interaction_effect": interaction_effect or None,
                    "worldview_support": worldview_support or None,
                    "visual_elements": visual_items[:6] if visual_items else None,
                    "conflict_potential": conflict_items[:6] if conflict_items else None,
                }
            )]

        scenes: list[dict[str, Any]] = []
        for item in area_items:
            name, description = self._split_list_item_name_value(item)
            environment_description = description
            if environment_suffix:
                environment_description = "\n".join(part for part in (description, environment_suffix) if part).strip()
            scene = self._compact_dict(
                {
                    "scene_name": name or "核心场景",
                    "scene_type": "故事关键区域",
                    "story_function": description or atmosphere or "承载关键剧情推进。",
                    "environment_description": environment_description or worldview_support or "见核心场景说明。",
                    "atmosphere_description": atmosphere or None,
                    "character_interaction_effect": interaction_effect or None,
                    "worldview_support": worldview_support or None,
                    "visual_elements": visual_items[:6] if visual_items else None,
                    "conflict_potential": conflict_items[:6] if conflict_items else None,
                }
            )
            scenes.append(scene)
        return scenes

    def _parse_multiline_sections(self, text: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        current_key = ""
        buffer: list[str] = []
        for raw_line in str(text or "").replace("\r", "").split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            match = re.match(r"^(?P<key>[^：:\n]{2,28})[:：]\s*(?P<value>.*)$", line)
            if match and not re.match(r"^\d+\.\s*", line):
                if current_key:
                    sections[current_key] = "\n".join(buffer).strip()
                current_key = match.group("key").strip()
                buffer = [match.group("value").strip()] if match.group("value").strip() else []
                continue
            if current_key:
                buffer.append(line)
        if current_key:
            sections[current_key] = "\n".join(buffer).strip()
        return sections

    def _parse_numbered_items(self, text: str) -> list[str]:
        items: list[str] = []
        for raw_line in str(text or "").replace("\r", "").split("\n"):
            line = raw_line.strip(" -\t")
            if not line:
                continue
            match = re.match(r"^\d+\.\s*(.+)$", line)
            if match:
                items.append(match.group(1).strip())
                continue
            if not items:
                items.append(line)
            else:
                items[-1] = f"{items[-1]} {line}".strip()
        return items

    def _split_list_item_name_value(self, item: str) -> tuple[str, str]:
        text = str(item or "").strip()
        if not text:
            return "", ""
        if "：" in text:
            name, value = text.split("：", 1)
            return name.strip(), value.strip()
        if ":" in text:
            name, value = text.split(":", 1)
            return name.strip(), value.strip()
        return text, ""

    def _pick_first_non_empty(self, fields: dict[str, str], *keys: str) -> str:
        for key in keys:
            value = str(fields.get(key) or "").strip()
            if value:
                return value
        return ""

    def _split_brief_items(self, value: str, *, max_items: int = 5) -> list[str]:
        text = str(value or "").replace("\n", " ").strip()
        if not text:
            return []
        parts = [
            part.strip("；;，,。 ")
            for part in re.split(r"[；;、]", text)
            if part.strip("；;，,。 ")
        ]
        if len(parts) <= 1:
            parts = [
                part.strip("；;，,。 ")
                for part in re.split(r"[，,]", text)
                if part.strip("；;，,。 ")
            ]
        return parts[:max_items] if parts else [text[:80]]

    def _summarize_export_text(self, value: Any, *, limit: int) -> str:
        condensed = " ".join(str(value or "").replace("\r", "\n").split())
        return condensed[:limit] if condensed else ""

    def _compact_dict(self, payload: dict[str, Any]) -> dict[str, Any]:
        compacted: dict[str, Any] = {}
        for key, value in payload.items():
            if value in (None, "", [], {}):
                continue
            compacted[key] = value
        return compacted

    def save_final_script(self, project_id: int, user_id: int | None = None) -> Path:
        snapshot = self.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot:
            raise ValueError("项目不存在")
        artifacts = snapshot.get("artifacts", {})
        final_script = self._best_final_script_text(snapshot)
        total_episodes = _safe_int(
            snapshot.get("total_episodes")
            or (snapshot.get("input_payload") or {}).get("total_episodes"),
            0,
        )
        if final_script and total_episodes > 0:
            available_episodes = _script_episode_numbers(
                final_script,
                total_episodes=total_episodes,
            )
            expected = list(range(1, total_episodes + 1))
            if available_episodes != expected:
                available_set = set(available_episodes)
                missing = [episode for episode in expected if episode not in available_set]
                raise ValueError(
                    f"当前剧本正文只覆盖 {len(available_episodes)}/{total_episodes} 集，"
                    f"缺少：{_format_episode_ranges(missing)}。"
                    "请先继续生成缺失批次，再下载成品。"
                )
        self._ensure_export_character_natural_language(snapshot, project_id=project_id)
        self._ensure_export_appearance_natural_language(snapshot, project_id=project_id)
        content = self._build_docx_export_source_text(snapshot)
        if not content:
            raise ValueError("当前项目还没有可保存的最终剧本")
        title = str(snapshot.get("title") or f"project_{project_id}").strip() or f"project_{project_id}"
        safe_title = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in title)[:80]
        base_name = f"{safe_title}_{project_id}"
        txt_path = self.exports_dir / f"{base_name}.txt"
        docx_path = self.exports_dir / f"{base_name}.docx"
        # TODO: README 历史上提到 zip/json 一起导出，但当前实现只稳定产出 txt/docx。
        # 如果后续要恢复压缩包导出，需要在这里补齐真实打包和快照写回逻辑。
        zip_path = self.exports_dir / f"{base_name}.zip"
        notice_path = self.exports_dir / f"{base_name}_导出说明.txt"
        legacy_json_paths = [
            self.exports_dir / f"{base_name}_character_registry.json",
            self.exports_dir / f"{base_name}_character_alias_registry.json",
            self.exports_dir / f"{base_name}_episode_alias_plan.json",
            self.exports_dir / f"{base_name}_appearance_mapping.json",
            self.exports_dir / f"{base_name}_appearance_continuity_memory.json",
            self.exports_dir / f"{base_name}_normalized_episode_plan.json",
        ]

        txt_path.write_text(content, encoding="utf-8")
        try:
            from ..utils.txt_to_docx import convert as convert_txt_to_docx
            convert_txt_to_docx(str(txt_path), str(docx_path))
        except ModuleNotFoundError as exc:
            if exc.name == "docx":
                raise ValueError("当前环境缺少 python-docx，暂时无法导出剧本正文 DOCX。") from exc
            else:
                raise ValueError(f"导出剧本正文 DOCX 失败：{exc}") from exc
        except Exception as exc:
            logger.exception("导出 Word 失败: %s", project_id)
            raise ValueError(f"导出剧本正文 DOCX 失败：{exc}") from exc

        for stale_path in (zip_path, notice_path, *legacy_json_paths):
            if stale_path.exists():
                stale_path.unlink()

        self._update_snapshot(
            self._projects.get(project_id) or TaskRecord(
                user_id=int(snapshot.get("user_id") or 0),
                project_id=project_id,
                task_id=str(snapshot.get("task_id", "")),
                workflow_spec_path=str(snapshot.get("workflow_spec_path", "")),
                input_payload=snapshot.get("input_payload", {}),
                model_option=settings.resolve_model_selection(
                    (snapshot.get("model_option") or {}).get("id")
                ),
                snapshot=snapshot,
            ),
            saved_file=str(docx_path),
            saved_txt_file="",
            saved_docx_file=str(docx_path),
            saved_zip_file="",
            export_notice="",
            saved_json_files={},
        )
        return docx_path


task_manager = TaskManager()
