from __future__ import annotations

import copy
import hashlib
import json
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
    IS_CONSISTENT,
    LAST_SUMMARY,
    NORMALIZED_EPISODE_PLAN,
    OUTFIT_SWITCH_RULES,
    SCENES,
    SCENE_APPEARANCE_REQUIREMENTS,
    script_title_content,
    STORY_OUTLINE,
    USER_CHARACTERS,
    USER_CONTENT_BASELINE,
    USER_SCENES,
    WORLDVIEW,
)
from .llm_client import llm_client
from .workflow_spec import WorkflowSpec
from ..utils.logger import get_logger
from ..utils.episode import BatchWindow, iter_episode_batches
from ..workflow_ids import (
    APPEARANCE_ALIAS_NAMING_RULES_VAR,
    APPEARANCE_MAPPING_VAR,
    APPEARANCE_PRE_STRATEGY_REQUIREMENTS_VAR,
    APPEARANCE_REQUIREMENTS_VAR,
    CHARACTER_BIOS_VAR,
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
    SCRIPT_CURRENT_VAR,
    SCRIPT_FINAL_VAR,
    SCRIPT_START_VAR,
    STORY_OUTLINE_VAR,
    TITLE_VAR,
    WORLDVIEW_VAR,
)

logger = get_logger("task_manager")

PROJECT_RUNNING_STATUSES = {"pending", "running", "pausing", "paused"}
WAITING_STATUSES = {"pending", "running", "pausing"}
STAGE_LABELS = {
    "framework": "正在撰写剧本框架",
    "appearance_strategy": "正在生成服装前置策略",
    "validation": "正在检查集数",
    "worldview": "正在整理世界观",
    "character": "正在梳理角色",
    "scene": "正在整理核心场景",
    "appearance": "正在给不同服饰的人物进行处理",
    "hook": "正在设计开场，冲突，钩子",
    "dialogue": "正在创作角色对话",
    "script": "正在写作剧本正文",
    "finalize": "正在整理完整稿件",
    "finished": "已完成",
}
FAILED_PUBLIC_MESSAGE = "当前步骤执行失败，任务已停在上一个成功步骤，等待手动继续生成。"
TERMINATED_PUBLIC_MESSAGE = "任务已终止，已保留当前阶段和中间产物。"
STORY_TEASER_ARTIFACT = "story_teaser"
STORY_TEASER_SOURCE_ARTIFACT = "story_teaser_source"
STAGE_PREVIEW_TEXT_ARTIFACT = "stage_preview_text"
STAGE_PREVIEW_STAGE_ARTIFACT = "stage_preview_stage"
STAGE_PREVIEW_SOURCE_HASH_ARTIFACT = "stage_preview_source_hash"
EPISODE_PLAN_DISPLAY_ARTIFACT = "episode_plan_display"
EPISODE_PLAN_DISPLAY_SOURCE_HASH_ARTIFACT = "episode_plan_display_source_hash"
PUBLIC_INPUT_PAYLOAD_KEYS = (
    "title",
    "story_outline",
    "user_expectation",
    "character_count",
    "total_episodes",
)
PUBLIC_ARTIFACT_KEYS = (
    "script_title_content",
    "story_outline",
    "character_bios",
    "core_scene_input",
    "episode_plan",
    "worldview",
    "character_summary",
    "core_scene_summary",
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
    "story_outline",
    "normalized_episode_plan",
    "character_summary",
    "core_scene_summary",
    "appearance_mapping",
    "character_registry",
    "character_alias_registry",
    "episode_alias_plan",
    STORY_TEASER_ARTIFACT,
    STORY_TEASER_SOURCE_ARTIFACT,
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
    ("dialogues", "角色对白"),
    ("script", "剧本正文"),
    ("final", "最终剧本拼接"),
)
ROLLBACK_STAGE_LABELS = {key: label for key, label in ROLLBACK_STAGE_OPTIONS}


def _rollback_stage_index(stage_key: Any) -> int:
    stage = str(stage_key or "").strip().lower()
    for index, (key, _) in enumerate(ROLLBACK_STAGE_OPTIONS):
        if key == stage:
            return index
    return -1
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
    SCENES: (SCENE_VAR, CORE_SCENE_FINAL_VAR, FINAL_SCENE_VAR),
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
        "worldview",
        "character_summary",
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
        "worldview",
        "character_summary",
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
        "worldview",
        "character_summary",
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
        "worldview",
        "character_summary",
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
        "character_summary",
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
        "character_summary",
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
    if not message:
        return ""
    return message


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
    model_option: ModelOption
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
        }
        if batch_label is not None:
            payload["current_batch"] = batch_label
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
        final_script_text = str(
            state.final_output_text
            or state.get_var(FINAL_SCRIPT, "")
            or state.get_var(SCRIPT_FINAL_VAR, "")
            or ""
        ).strip()
        artifacts = {
            "script_title_content": script_title_content,
            "story_outline": state.get_var(STORY_OUTLINE_VAR, ""),
            "character_bios": state.get_var(CHARACTER_BIOS_VAR, ""),
            "episode_plan": state.get_var(EPISODE_PLAN_VAR, ""),
            "normalized_episode_plan": state.get_var(NORMALIZED_EPISODE_PLAN, ""),
            "worldview": state.get_var(WORLDVIEW_VAR, ""),
            "character_summary": state.get_var(FINAL_CHARACTER_VAR, state.get_var(CHARACTER_VAR, "")),
            "scene_json": state.get_var(SCENE_VAR, ""),
            "core_scene_input": state.get_var(CORE_SCENE_INPUT_VAR, ""),
            "core_scene_summary": state.get_var(FINAL_SCENE_VAR, state.get_var(CORE_SCENE_FINAL_VAR, "")),
            "character_appearance_requirements": state.get_var(CHARACTER_APPEARANCE_REQUIREMENTS, ""),
            "character_alias_naming_rules": state.get_var(CHARACTER_ALIAS_NAMING_RULES, ""),
            "outfit_switch_rules": state.get_var(OUTFIT_SWITCH_RULES, ""),
            "appearance_mapping": state.get_var(APPEARANCE_MAPPING, ""),
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
        artifacts = _select_non_empty_fields(
            snapshot.get("artifacts") or {},
            tuple(allowed_keys),
        )
        episode_plan_display = self._episode_plan_display_text(snapshot, snapshot.get("artifacts") or {})
        if episode_plan_display:
            artifacts[EPISODE_PLAN_DISPLAY_ARTIFACT] = episode_plan_display
        return artifacts

    def _episode_plan_display_text(
        self,
        snapshot: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> str:
        raw_episode_plan = str(artifacts.get("episode_plan") or "").strip()
        if not raw_episode_plan:
            return ""
        parsed = self._parse_episode_plan_display_json(raw_episode_plan)
        if parsed is None:
            return raw_episode_plan

        text_hash = self._hash_text(raw_episode_plan)
        cached_text = str(artifacts.get(EPISODE_PLAN_DISPLAY_ARTIFACT) or "").strip()
        cached_hash = str(artifacts.get(EPISODE_PLAN_DISPLAY_SOURCE_HASH_ARTIFACT) or "").strip()
        if cached_text and cached_hash == text_hash:
            return cached_text

        display_source_json = self._episode_plan_display_json_text(parsed) or raw_episode_plan
        display_text = self._generate_episode_plan_display(display_source_json)
        if not display_text:
            display_text = self._fallback_episode_plan_display(parsed)
        if not display_text:
            display_text = raw_episode_plan
        if display_text:
            self._cache_episode_plan_display(snapshot, display_text, text_hash)
        return display_text

    def _parse_episode_plan_display_json(self, raw_episode_plan: str) -> Any | None:
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
        text = str(source_text or "").strip()
        if not text:
            return ""
        try:
            display = llm_client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是短剧创作平台的展示转换助手。"
                            "请把输入的分集计划JSON信息改写成给前端展示的自然语言正文。"
                            "要求：只输出中文正文；不要JSON，不要Markdown，不要代码块，不要项目符号，不要解释过程；"
                            "按集数顺序写，可使用“第X集：”开头；只依据输入，不补编不存在的信息。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"请把下面这份分集计划 JSON 转成自然语言展示稿：\n\n{text}",
                    },
                ],
                provider="deepseek",
                temperature=0.4,
                max_tokens=2400,
            )
        except Exception as exc:
            logger.warning("分集计划展示转换失败，将使用本地回退文案: %s", exc)
            return ""
        return str(display or "").strip()

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
        if str(artifacts.get("character_summary") or "").strip():
            reached.add("characters")
        if str(artifacts.get("core_scene_summary") or "").strip():
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
            "appearance_strategy": "appearance_strategy",
            "worldview": "worldview",
            "character": "characters",
            "characters": "characters",
            "scene": "scenes",
            "scenes": "scenes",
            "appearance": "appearance",
            "hook": "hooks",
            "hooks": "hooks",
            "dialogue": "dialogues",
            "dialogues": "dialogues",
            "script": "script",
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
        stage_order = ("framework", "worldview", "characters", "scenes", "final")
        stage_title_map = {
            "framework": "剧本框架",
            "worldview": "世界观",
            "characters": "人物设定",
            "scenes": "核心场景",
            "final": "最终剧本",
        }
        stage_outputs = {
            "framework": self._framework_stage_output_text(artifacts),
            "worldview": str(artifacts.get("worldview") or "").strip(),
            "characters": str(artifacts.get("character_summary") or "").strip(),
            "scenes": str(artifacts.get("core_scene_summary") or "").strip(),
            "final": str(artifacts.get("final_output_text") or artifacts.get("final_script") or "").strip(),
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
            "characters": "characters",
            "scenes": "scenes",
            "appearance": "scenes",
            "hooks": "scenes",
            "dialogues": "scenes",
            "script": "scenes",
            "final": "final",
        }
        ceiling_stage = stage_ceiling_map.get(current_stage, "framework")
        ceiling_index = stage_order.index(ceiling_stage)

        chosen_stage = ""
        for stage_key in reversed(stage_order[: ceiling_index + 1]):
            if stage_outputs.get(stage_key):
                chosen_stage = stage_key
                break
        if not chosen_stage:
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
        """把框架阶段的几个正式字段拼成一份可直接阅读的阶段成品。"""
        title = str(artifacts.get("script_title_content") or "").strip()
        story_outline = str(artifacts.get("story_outline") or "").strip()
        character_bios = str(artifacts.get("character_bios") or "").strip()
        core_scene_input = str(artifacts.get("core_scene_input") or "").strip()
        episode_plan = str(
            artifacts.get(EPISODE_PLAN_DISPLAY_ARTIFACT)
            or artifacts.get("episode_plan")
            or ""
        ).strip()
        parts: list[str] = []
        if title:
            parts.append(f"剧本标题\n{title}")
        if story_outline:
            parts.append(f"故事大纲\n{story_outline}")
        if character_bios:
            parts.append(f"人物小传\n{character_bios}")
        if core_scene_input:
            parts.append(f"核心场景\n{core_scene_input}")
        if episode_plan:
            parts.append(f"分集计划\n{episode_plan}")
        return "\n\n".join(parts).strip()

    def _stage_preview_text(
        self,
        snapshot: dict[str, Any],
        *,
        stage_key: str,
        stage_title: str,
        raw_output: str,
    ) -> str:
        """优先复用缓存的自然语言摘要，避免轮询时反复请求模型。"""
        text = str(raw_output or "").strip()
        if not text:
            return ""
        text_hash = self._hash_text(text)
        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        cached_text = str(artifacts.get(STAGE_PREVIEW_TEXT_ARTIFACT) or "").strip()
        cached_stage = str(artifacts.get(STAGE_PREVIEW_STAGE_ARTIFACT) or "").strip()
        cached_hash = str(artifacts.get(STAGE_PREVIEW_SOURCE_HASH_ARTIFACT) or "").strip()
        if cached_text and cached_stage == stage_key and cached_hash == text_hash:
            return cached_text

        preview = self._generate_stage_preview(stage_title, text) or self._fallback_stage_preview(stage_title, text)
        self._cache_stage_preview(snapshot, stage_key=stage_key, text_hash=text_hash, preview=preview)
        return preview

    def _hash_text(self, value: str) -> str:
        """用内容哈希判断阶段产物是否变化，避免重复生成摘要。"""
        return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()

    def _generate_stage_preview(self, stage_title: str, raw_output: str) -> str:
        """调用摘要模型，把阶段原文转成用户更容易读懂的自然语言版本。"""
        preview_source = self._preview_source_text(raw_output)
        try:
            preview = llm_client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是短剧创作平台的阶段讲解助手。"
                            "请把给定阶段产物改写成更容易理解的自然语言说明。"
                            "要求：只输出 2-4 句中文；保留关键信息，不要编造，不要分点，不要说自己是 AI。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"阶段：{stage_title}\n\n阶段产物：\n{preview_source}",
                    },
                ],
                provider="deepseek",
                temperature=0.4,
                max_tokens=220,
            )
        except Exception as exc:
            logger.warning("生成阶段自然语言摘要失败，将使用本地回退文案: %s", exc)
            return ""
        return " ".join(str(preview or "").strip().split())[:260]

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
        return f"{stage_title}已经产出内容，当前展示的是该阶段的正式结果：{condensed[:180]}"

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
        rollback_stage_default, rollback_start_episode_default = self._rollback_defaults(snapshot)
        rollback_script_start_options = (
            self._script_rollback_start_options(snapshot) if can_stage_rollback else []
        )
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
            "progress_percent": int(snapshot.get("progress_percent") or 0),
            "total_episodes": int(snapshot.get("total_episodes") or 0),
            "current_stage": snapshot.get("current_stage"),
            "current_stage_label": snapshot.get("current_stage_label") or "待开始",
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
            "rollback_script_start_options": rollback_script_start_options,
            "rollback_start_episode_default": rollback_start_episode_default if can_stage_rollback else None,
            "display_stage_key": display_payload["stage_key"],
            "display_stage_title": display_payload["stage_title"],
            "display_stage_output": display_payload["output"],
            "display_stage_output_natural": display_payload["natural_output"],
            "has_final": bool(
                str(artifacts.get("final_output_text") or artifacts.get("final_script") or "").strip()
            ),
        }
        return payload

    def _script_rollback_start_options(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        debug_state = snapshot.get("debug_state") or {}
        variables = debug_state.get("variables") if isinstance(debug_state, dict) else {}
        if not isinstance(variables, dict):
            variables = {}

        batch_size = max(1, int(settings.batch_size or 5))
        total_episodes = int(snapshot.get("total_episodes") or 0)
        if total_episodes <= 0:
            return []

        batch_starts = [batch.start_episode for batch in iter_episode_batches(total_episodes, batch_size=batch_size)]
        script_batches = _normalize_batch_text_map(variables.get(LOCAL_SCRIPT_BATCHES))
        script_episodes = _normalize_episode_script_map(variables.get(LOCAL_SCRIPT_EPISODES))
        interrupted_start = self._interrupted_batch_start_episode(snapshot)
        if script_episodes:
            candidate_starts = list(range(1, total_episodes + 1))
        elif script_batches:
            candidate_starts = batch_starts
        else:
            candidate_starts = [interrupted_start] if interrupted_start else batch_starts[:1]

        if interrupted_start and interrupted_start not in candidate_starts:
            candidate_starts = sorted({*candidate_starts, interrupted_start})

        options: list[dict[str, Any]] = []
        for start_episode in candidate_starts:
            end_episode = min(total_episodes, start_episode + batch_size - 1)
            label = (
                f"从第 {start_episode} 集开始重写正文（本轮将覆盖第 {start_episode}-{end_episode} 集及后续）"
                if script_episodes
                else f"从第 {start_episode}-{end_episode} 集开始重写正文"
            )
            options.append(
                {
                    "value": start_episode,
                    "label": label,
                }
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
                return candidate, interrupted_start

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

    def list_public_assets(self) -> list[dict[str, Any]]:
        assets = [
            self._asset_summary(snapshot, include_private=False, use_teaser=True)
            for snapshot in self._all_project_snapshots()
            if str(snapshot.get("visibility") or "private") == "public"
            and str(snapshot.get("status") or "") == "completed"
            and _completion_confirmed(snapshot)
            and bool(
                (snapshot.get("artifacts") or {}).get("final_output_text")
                or (snapshot.get("artifacts") or {}).get("final_script")
            )
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
        final_script = str(
            artifacts.get("final_output_text") or artifacts.get("final_script") or ""
        ).strip()
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
        rollback_stage = str(stage_key or "").strip()
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
        if rollback_stage == "script":
            rollback_start_episode = _safe_int(start_episode, 0) or None
            if rollback_start_episode is None and default_start_episode:
                rollback_start_episode = int(default_start_episode)
            rollback_options = self._script_rollback_start_options(snapshot)
            valid_start_episodes = {int(option["value"]) for option in rollback_options if _safe_int(option.get("value"), 0) > 0}
            if rollback_start_episode is None:
                raise ValueError("请选择正文开始重写的集数")
            if rollback_start_episode not in valid_start_episodes:
                raise ValueError("请选择有效的正文重写起始集数")

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
        if rollback_stage == "script" and rollback_start_episode:
            batch_size = max(1, int(settings.batch_size or 5))
            end_episode = min(int(snapshot.get("total_episodes") or 0), rollback_start_episode + batch_size - 1)
            stage_label = f"{stage_label}（从第 {rollback_start_episode}-{end_episode} 集开始）"
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
        rollback["prompt_fixes"] = []
        rollback["current_node_id"] = None
        rollback["current_node_name"] = None
        rollback["current_batch"] = (
            f"{effective_start_episode}-{_batch_end_episode(int(snapshot.get('total_episodes') or 0), effective_start_episode)}"
            if stage_key in {"hooks", "dialogues", "script"} and effective_start_episode
            else None
        )
        rollback["progress_percent"] = self._rollback_progress_percent(stage_key)
        rollback["generated_episodes"] = (
            max(0, int(effective_start_episode or 0) - 1)
            if stage_key in {"hooks", "dialogues", "script"} and effective_start_episode
            else 0
        )
        rollback["current_stage"] = stage_key
        rollback["current_stage_label"] = ROLLBACK_STAGE_LABELS.get(stage_key, stage_key)
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
            preserved_hooks = _slice_episode_object_through(original_hooks, batch_end_episode)
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

    def _rollback_progress_percent(self, stage_key: str) -> int:
        defaults = {
            "framework": 0,
            "appearance_strategy": 4,
            "consistency": 1,
            "episode_plan_normalize": 3,
            "worldview": 7,
            "characters": 12,
            "scenes": 24,
            "appearance": 30,
            "hooks": 36,
            "dialogues": 50,
            "script": 68,
            "final": 98,
        }
        return int(defaults.get(stage_key, 0))

    def _asset_summary(
        self,
        snapshot: dict[str, Any],
        *,
        include_private: bool,
        use_teaser: bool,
    ) -> dict[str, Any]:
        input_payload = snapshot.get("input_payload") or {}
        artifacts = snapshot.get("artifacts") or {}
        story_outline = str(
            input_payload.get("story_outline")
            or artifacts.get("story_outline")
            or ""
        ).strip()
        final_script = str(
            artifacts.get("final_output_text") or artifacts.get("final_script") or ""
        ).strip()
        summary = self._story_teaser_for_snapshot(snapshot) if use_teaser else ""
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
            "progress_percent": int(snapshot.get("progress_percent") or 0),
            "generated_episodes": int(snapshot.get("generated_episodes") or 0),
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

        has_final = bool(
            str(artifacts.get("final_output_text") or artifacts.get("final_script") or "").strip()
        )
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
        try:
            teaser = llm_client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是短剧平台编辑。请把用户给出的剧本故事大纲压缩成一句中文展示摘要。"
                            "要求：只输出一句话；18-48字；点出主角、核心冲突和最大看点；"
                            "不要加前缀、不要解释、不要分点。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"故事大纲：\n{story_outline}",
                    },
                ],
                provider="deepseek",
                temperature=0.4,
                max_tokens=90,
            )
        except Exception as exc:
            logger.warning("生成剧本摘要失败，将回退到原始梗概截断: %s", exc)
            return ""
        cleaned = " ".join(str(teaser or "").strip().split())
        cleaned = cleaned.strip("“”\"' \n\r\t")
        if cleaned.startswith("一句话摘要"):
            cleaned = cleaned.split("：", 1)[-1].strip()
        return cleaned[:88]

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

    def save_final_script(self, project_id: int, user_id: int | None = None) -> Path:
        snapshot = self.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot:
            raise ValueError("项目不存在")
        artifacts = snapshot.get("artifacts", {})
        content = (
            artifacts.get("final_output_text")
            or artifacts.get("final_script")
            or ""
        ).strip()
        if not content:
            raise ValueError("当前项目还没有可保存的最终剧本")
        title = str(snapshot.get("title") or f"project_{project_id}").strip() or f"project_{project_id}"
        safe_title = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in title)[:80]
        base_name = f"{safe_title}_{project_id}"
        txt_path = self.exports_dir / f"{base_name}.txt"
        docx_path = self.exports_dir / f"{base_name}.docx"
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
