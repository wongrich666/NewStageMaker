from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..workflow_ids import (
    APPEARANCE_ALIAS_NAMING_RULES_VAR,
    APPEARANCE_MAPPING_VAR,
    APPEARANCE_NATURAL_LANGUAGE_VAR,
    APPEARANCE_PRE_STRATEGY_REQUIREMENTS_VAR,
    APPEARANCE_REQUIREMENTS_VAR,
    APPEARANCE_REVIEW_VAR,
    CHARACTER_BIOS_VAR,
    CHARACTER_NATURAL_LANGUAGE_VAR,
    CHARACTER_SEARCH_INTENT_VAR,
    CHARACTER_MAX_RETRY_VAR,
    CHARACTER_VAR,
    CORE_SCENE_FINAL_VAR,
    CORE_SCENE_INPUT_VAR,
    DIALOGUE_CURRENT_VAR,
    DIALOGUE_CURRENT_WORKFLOW_VAR,
    DIALOGUE_CURRENT_WRITE_VAR,
    DIALOGUE_FINAL_VAR,
    DIALOGUE_HOOK_BATCH_VAR,
    DIALOGUE_HOOK_REWRITE_VAR,
    DIALOGUE_HOOK_REVIEW_VAR,
    DIALOGUE_MEMORY_INPUT_VAR,
    DIALOGUE_MEMORY_LEGACY_OUTPUT_VAR,
    DIALOGUE_MEMORY_OUTPUT_VAR,
    DIALOGUE_MEMORY_SEARCH_VAR,
    DIALOGUE_REVIEW_LEGACY_VAR,
    DIALOGUE_REVIEW_WORKFLOW_VAR,
    DIALOGUE_START_VAR,
    DIALOGUE_MAX_RETRY_VAR,
    EPISODE_PLAN_VAR,
    EPISODE_PLAN_NORMALIZED_VAR,
    EPISODE_WORD_COUNT_VAR,
    FINAL_CHARACTER_VAR,
    FINAL_SCENE_VAR,
    FRAMEWORK_CHARACTER_BIOS_VAR,
    FRAMEWORK_CHARACTER_COUNT_VAR,
    FRAMEWORK_CORE_SCENE_VAR,
    FRAMEWORK_EPISODE_PLAN_VAR,
    FRAMEWORK_TITLE_VAR,
    FRAMEWORK_TOTAL_EPISODES_VAR,
    FRAMEWORK_STORY_OUTLINE_VAR,
    FRAMEWORK_USER_EXPECTATION_VAR,
    HOOK_CURRENT_VAR,
    HOOK_CURRENT_WRITE_VAR,
    HOOK_FINAL_VAR,
    HOOK_MEMORY_INPUT_VAR,
    HOOK_MEMORY_OUTPUT_VAR,
    HOOK_MEMORY_REVIEW_VAR,
    HOOK_MEMORY_REVISE_VAR,
    HOOK_START_VAR,
    HOOK_MAX_RETRY_VAR,
    MEMORY_VAR,
    OUTFIT_SWITCH_RULES_VAR,
    SCENE_MAX_RETRY_VAR,
    SCENE_APPEARANCE_REQUIREMENTS_VAR,
    SCENE_ALIAS_NAMING_RULES_VAR,
    SCENE_VAR,
    DIALOGUE_CHARACTER_INPUT_VAR,
    SCRIPT_CURRENT_VAR,
    SCRIPT_CURRENT_WRITE_VAR,
    SCRIPT_DIALOGUE_BATCH_VAR,
    SCRIPT_FINAL_VAR,
    SCRIPT_HOOK_BATCH_VAR,
    SCRIPT_MEMORY_OUTPUT_VAR,
    SCRIPT_MEMORY_WRITE_INPUT_VAR,
    DIALOGUE_EPISODE_PLAN_INPUT_VAR,
    DIALOGUE_HOOK_INPUT_VAR,
    DIALOGUE_MAX_RETRY_INPUT_VAR,
    DIALOGUE_REVIEW_OUTPUT_VAR,
    DIALOGUE_SCENE_INPUT_VAR,
    DIALOGUE_START_INPUT_VAR,
    DIALOGUE_TOTAL_EPISODES_INPUT_VAR,
    DIALOGUE_WORLDVIEW_INPUT_VAR,
    HOOK_REVIEW_OUTPUT_VAR,
    SCRIPT_START_VAR,
    SCRIPT_MAX_RETRY_VAR,
    SCRIPT_REVIEW_WRITE_VAR,
    SCRIPT_REVIEW_OUTPUT_VAR,
    STORY_OUTLINE_VAR,
    TITLE_VAR,
    TOTAL_EPISODES_VAR,
    UNSTRUCTURED_KIND_VAR,
    UNSTRUCTURED_OUTPUT_VAR,
    UNSTRUCTURED_SOURCE_VAR,
    WORLDVIEW_MAX_RETRY_VAR,
    WORLDVIEW_VAR,
)
from .json_utils import parse_json
from .stage_output_repair import describe_repairable_stage_output_issue

script_title_content = "script_title_content"
SCRIPT_TITLE = script_title_content
TOTAL_EPISODES = "total_episodes"
EPISODE_WORD_COUNT = "episode_word_count"
USER_EXPECTATION = "user_expectation"
CHARACTER_COUNT = "character_count"
CHARACTER_APPEARANCE_REQUIREMENTS = "character_appearance_requirements"
CHARACTER_ALIAS_NAMING_RULES = "character_alias_naming_rules"
OUTFIT_SWITCH_RULES = "outfit_switch_rules"
EPISODE_PLAN = "episode_plan"
STORY_OUTLINE = "story_outline"
USER_SCENES = "user_scenes"
USER_CHARACTERS = "user_characters"
CHARACTER_SEARCH_INTENT = "character_search_intent"
USER_CONTENT_BASELINE = "user_content_baseline"
FRAMEWORK_NATURAL_LANGUAGE = "framework_natural_language"
WORLDVIEW_NATURAL_LANGUAGE = "worldview_natural_language"
UNSTRUCTURED_SOURCE = "unstructured_source"
UNSTRUCTURED_CONTENT_KIND = "unstructured_content_kind"
MAX_RETRIES = "max_retries"
WORLDVIEW = "worldview"
CHARACTERS = "characters"
SCENES = "scenes"
BATCH_START_EPISODE = "batch_start_episode"
BATCH_HOOKS = "batch_hooks"
HOOK_BATCH_START_EPISODE = BATCH_START_EPISODE
HOOK_BATCH_CONTENT = BATCH_HOOKS
HOOK_REVIEW_RESULT = "hook_review_result"
HOOK_MEMORY = "hook_memory"
ALL_HOOKS = "all_hooks"
BATCH_DIALOGUES = "batch_dialogues"
DIALOGUE_BATCH_START_EPISODE = BATCH_START_EPISODE
DIALOGUE_BATCH_CONTENT = BATCH_DIALOGUES
DIALOGUE_REVIEW_RESULT = "dialogue_review_result"
DIALOGUE_MEMORY = "dialogue_memory"
ALL_DIALOGUES = "all_dialogues"
BATCH_SCRIPT = "batch_script"
SCRIPT_BATCH_START_EPISODE = BATCH_START_EPISODE
SCRIPT_BATCH_CONTENT = BATCH_SCRIPT
SCRIPT_REVIEW_RESULT = "script_review_result"
SCRIPT_MEMORY = "last_summary"
ALL_SCRIPT = "all_script"
LAST_SUMMARY = "last_summary"
FINAL_SCRIPT = "final_script"
IS_CONSISTENT = "is_consistent"
NORMALIZED_EPISODE_PLAN = "normalized_episode_plan"
APPEARANCE_MAPPING = "appearance_mapping"
CHARACTER_REGISTRY = "character_registry"
CHARACTER_ALIAS_REGISTRY = "character_alias_registry"
EPISODE_ALIAS_PLAN = "episode_alias_plan"
APPEARANCE_CONTINUITY_MEMORY = "appearance_continuity_memory"
SCENE_APPEARANCE_REQUIREMENTS = "scene_appearance_requirements"
PASS_REVIEW_JSON = "pass_review_json"
REVIEW_PASSED = "passed"
REWRITE_REQUIRED = "rewrite_required"
REVIEW_SUMMARY = "summary"
BLOCKING_ISSUES = "blocking_issues"
NON_BLOCKING_ISSUES = "non_blocking_issues"
REWRITE_START_EPISODE = "rewrite_start_episode"
REVIEW_STAGE_NAME = "stage"

STAGE_FRAMEWORK = "framework"
STAGE_FRAMEWORK_NATURALIZE = "framework_naturalize"
STAGE_APPEARANCE_PRE_STRATEGY = "appearance_pre_strategy"
STAGE_CONSISTENCY = "consistency"
STAGE_EPISODE_PLAN_NORMALIZE = "episode_plan_normalize"
STAGE_WORLDVIEW = "worldview"
STAGE_WORLDVIEW_NATURALIZE = "worldview_naturalize"
STAGE_CHARACTERS_NATURALIZE = "characters_naturalize"
STAGE_CHARACTERS = "characters"
STAGE_SCENES = "scenes"
STAGE_APPEARANCE_ALIAS_GENERATION = "appearance_alias_generation"
STAGE_APPEARANCE_ALIAS_WRITING = "appearance_alias_writing"
STAGE_APPEARANCE_ALIAS_REVIEW = "appearance_alias_review"
STAGE_APPEARANCE_ALIAS_REWRITE = "appearance_alias_rewrite"
STAGE_APPEARANCE_ALIAS_UNSTRUCTURED = "appearance_alias_unstructured"
STAGE_HOOKS = "hooks"
STAGE_HOOKS_WRITING = "hooks_writing"
STAGE_HOOK_WRITE = "hook_write"
STAGE_HOOKS_REVIEW = "hooks_review"
STAGE_HOOK_REVIEW = "hook_review"
STAGE_HOOKS_REWRITE = "hooks_rewrite"
STAGE_HOOK_REVISE = "hook_revise"
STAGE_HOOK_MEMORY = "hook_memory"
STAGE_DIALOGUES = "dialogues"
STAGE_DIALOGUES_WRITING = "dialogues_writing"
STAGE_DIALOGUE_WRITE = "dialogue_write"
STAGE_DIALOGUES_REVIEW = "dialogues_review"
STAGE_DIALOGUE_REVIEW = "dialogue_review"
STAGE_DIALOGUES_REWRITE = "dialogues_rewrite"
STAGE_DIALOGUE_REVISE = "dialogue_revise"
STAGE_DIALOGUE_MEMORY = "dialogue_memory"
STAGE_SCRIPT = "script"
STAGE_SCRIPT_WRITING = "script_writing"
STAGE_SCRIPT_WRITE = "script_write"
STAGE_SCRIPT_REVIEW = "script_review"
STAGE_SCRIPT_REWRITE = "script_rewrite"
STAGE_SCRIPT_REVISE = "script_revise"
STAGE_MEMORY = "memory"
STAGE_SCRIPT_MEMORY = "script_memory"
STAGE_FINAL = "final"

HOOK_CURRENT_ALIASES = (HOOK_CURRENT_VAR, HOOK_CURRENT_WRITE_VAR)
HOOK_MEMORY_ALIASES = (
    HOOK_MEMORY_INPUT_VAR,
    HOOK_MEMORY_REVIEW_VAR,
    HOOK_MEMORY_REVISE_VAR,
    HOOK_MEMORY_OUTPUT_VAR,
)
DIALOGUE_CURRENT_ALIASES = (
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
DIALOGUE_HOOK_ALIASES = (
    DIALOGUE_HOOK_BATCH_VAR,
    DIALOGUE_HOOK_REVIEW_VAR,
    DIALOGUE_HOOK_REWRITE_VAR,
    DIALOGUE_HOOK_INPUT_VAR,
)
SCRIPT_CURRENT_ALIASES = (SCRIPT_CURRENT_VAR, SCRIPT_CURRENT_WRITE_VAR)
SCRIPT_REVIEW_ALIASES = (
    SCRIPT_REVIEW_OUTPUT_VAR,
    SCRIPT_REVIEW_WRITE_VAR,
)
SCRIPT_MEMORY_ALIASES = (
    MEMORY_VAR,
    SCRIPT_MEMORY_WRITE_INPUT_VAR,
    SCRIPT_MEMORY_OUTPUT_VAR,
)
SCRIPT_HOOK_ALIASES = (SCRIPT_HOOK_BATCH_VAR, HOOK_FINAL_VAR)
SCRIPT_DIALOGUE_ALIASES = (SCRIPT_DIALOGUE_BATCH_VAR, DIALOGUE_FINAL_VAR)
OPTIONAL_EMPTY_INPUTS = {CHARACTER_SEARCH_INTENT}

APPEARANCE_MAPPING_STAGE_NAMES = {
    STAGE_APPEARANCE_ALIAS_GENERATION,
    STAGE_APPEARANCE_ALIAS_WRITING,
    STAGE_APPEARANCE_ALIAS_REWRITE,
}

FRAMEWORK_WEB_INPUT_NAMES = (
    TOTAL_EPISODES,
    USER_EXPECTATION,
    CHARACTER_COUNT,
)

FRAMEWORK_STORY_OUTLINE_KEYS = (
    "opening",
    "inciting_incident",
    "early_goal",
    "middle_escalation",
    "relationship_changes",
    "larger_crisis_or_truth",
    "late_direction",
    "final_climax",
    "ending_resolution",
    "theme",
)
FRAMEWORK_CHARACTER_KEYS = (
    "name",
    "role_type",
    "identity",
    "personality",
    "core_desire",
    "deep_motivation",
    "strengths",
    "weaknesses",
    "appearance_anchor",
    "relationship_to_protagonist",
    "relationships_with_others",
    "growth_arc",
    "plot_function",
)
FRAMEWORK_SCENE_KEYS = (
    "era_background",
    "world_state",
    "core_locations",
    "rules",
    "danger_sources",
    "resource_or_stakes",
    "power_distribution",
    "special_rules",
    "overall_atmosphere",
)
FRAMEWORK_CORE_LOCATION_KEYS = (
    "name",
    "function",
    "conflict_soil",
    "key_characters",
)
FRAMEWORK_EPISODE_PLAN_KEYS = (
    "episode",
    "title",
    "main_plot",
    "conflicts",
    "ending_hook",
)


@dataclass(frozen=True, slots=True)
class FastGPTVariable:
    name: str
    type_name: str
    description: str
    source: str


@dataclass(frozen=True, slots=True)
class FastGPTStageContract:
    stage_name: str
    label: str
    input_names: tuple[str, ...]
    output_types: dict[str, str]
    fastgpt_responsibility: str
    local_responsibility: str
    output_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    expected_output_kind: str | None = None
    workflow_json_name: str | None = None

    @property
    def output_names(self) -> tuple[str, ...]:
        return tuple(self.output_types.keys())

    def aliases_for_output(self, field_name: str) -> tuple[str, ...]:
        return tuple(self.output_aliases.get(field_name, ()))

    def build_input_payload(self, variables: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        missing: list[str] = []
        for name in self.input_names:
            if name in variables:
                payload[name] = variables[name]
            elif name in OPTIONAL_EMPTY_INPUTS:
                payload[name] = ""
            elif name in {LAST_SUMMARY, HOOK_MEMORY, DIALOGUE_MEMORY, SCRIPT_MEMORY}:
                # 记忆类字段允许缺省为“空记忆”，这样首批正文不需要为了凑输入
                # 额外制造一个伪 summary。
                payload[name] = ""
            elif name in {ALL_HOOKS, ALL_DIALOGUES}:
                # 批处理阶段允许前序累计对象以空 object 开局；真正的跨阶段完整性
                # 由编排层在进入当前阶段前负责校验。
                payload[name] = {}
            else:
                missing.append(name)
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"FastGPT 阶段 {self.stage_name} 缺少输入变量：{joined}")
        return payload

    def validate_output_payload(self, output: Any) -> dict[str, Any]:
        if not isinstance(output, dict):
            actual_type = type(output).__name__
            raise ValueError(
                f"FastGPT 阶段 {self.stage_name} 输出必须是 object，实际得到 {actual_type}"
            )
        normalized: dict[str, Any] = {}
        missing: list[str] = []
        for name, type_name in self.output_types.items():
            if name not in output:
                missing.append(name)
                continue
            try:
                if self.stage_name == STAGE_CONSISTENCY and name == IS_CONSISTENT:
                    # 这个工作流的 system prompt 已经明确要求“只能回复 true / false”。
                    # 因此这里故意不用宽松布尔推断，避免把“通过/一致/解释文本”
                    # 误判成合法结果，导致编排层错把脏输出当成正式布尔值继续流转。
                    normalized[name] = coerce_strict_fastgpt_boolean(output[name])
                elif (
                    self.stage_name
                    in {
                        STAGE_HOOKS_REVIEW,
                        STAGE_HOOK_REVIEW,
                        STAGE_DIALOGUES_REVIEW,
                        STAGE_DIALOGUE_REVIEW,
                        STAGE_SCRIPT_REVIEW,
                    }
                    and name in {REVIEW_PASSED, REWRITE_REQUIRED}
                ):
                    normalized[name] = coerce_strict_fastgpt_boolean(output[name])
                else:
                    normalized[name] = coerce_fastgpt_value(output[name], type_name)
            except ValueError as exc:
                value = output.get(name)
                if type_name == "string" and _is_empty_string_output(value):
                    raise ValueError(
                        f"FastGPT 阶段 {self.stage_name} 输出字段 {name} 不能为空"
                    ) from exc
                raise ValueError(
                    f"FastGPT 阶段 {self.stage_name} 输出字段 {name} 校验失败：{exc}"
                ) from exc
            # 这里只做“字段类型已对”还不够。
            # hooks/dialogues/normalized_episode_plan 等阶段如果 shape 漂了，
            # 后面的批次切片与缓存恢复会直接失真，所以要在契约层提前拦住。
            issue = describe_stage_output_shape_issue(
                self.stage_name,
                name,
                normalized[name],
            )
            if issue:
                raise ValueError(
                    f"FastGPT 阶段 {self.stage_name} 输出字段 {name} 结构不符合契约：{issue}"
                )
        if missing:
            joined = ", ".join(missing)
            if self.stage_name == STAGE_APPEARANCE_PRE_STRATEGY:
                raise ValueError(f"{self.stage_name} 缺少字段：{joined}")
            raise ValueError(f"FastGPT 阶段 {self.stage_name} 缺少输出变量：{joined}")
        return normalized


def describe_stage_output_shape_issue(
    stage_name: str,
    field_name: str,
    value: Any,
) -> str | None:
    repairable_issue = describe_repairable_stage_output_issue(stage_name, field_name, value)
    if repairable_issue:
        return repairable_issue

    # 这里故意做得比一般 JSON 校验更严格：
    # 本地后续逻辑会直接依赖这些固定键做切片、拼接、恢复和回退，
    # 所以宁可在阶段出口报错，也不让“近似正确”的结构混入缓存。
    if stage_name == STAGE_FRAMEWORK:
        if field_name == STORY_OUTLINE:
            return _describe_framework_story_outline_issue(value)
        if field_name == USER_CHARACTERS:
            return _describe_framework_user_characters_issue(value)
        if field_name == USER_SCENES:
            return _describe_framework_user_scenes_issue(value)
        if field_name == EPISODE_PLAN:
            return _describe_framework_episode_plan_issue(value)
        return None

    if stage_name == STAGE_EPISODE_PLAN_NORMALIZE and field_name == NORMALIZED_EPISODE_PLAN:
        if not isinstance(value, dict):
            return "必须是 object"
        required = {"parsed_episode_count", "episodes"}
        allowed = required | {"appearance_alias_planning"}
        missing = sorted(required - set(value.keys()))
        extra = sorted(set(value.keys()) - allowed)
        if missing:
            return f"缺少键 {', '.join(missing)}"
        if extra:
            return f"存在非契约键 {', '.join(extra)}"
        if not isinstance(value.get("episodes"), list):
            return "episodes 必须是数组"
        return None

    if _is_hook_payload_stage(stage_name) and field_name == BATCH_HOOKS:
        if not isinstance(value, dict):
            return "必须是 object"
        required = {"batch_meta", "global_hook_engine", "episodes"}
        extra = sorted(set(value.keys()) - required)
        missing = sorted(required - set(value.keys()))
        if missing:
            return f"缺少键 {', '.join(missing)}"
        if extra:
            return f"存在非契约键 {', '.join(extra)}"
        if not isinstance(value.get("batch_meta"), dict):
            return "batch_meta 必须是 object"
        if not isinstance(value.get("global_hook_engine"), dict):
            return "global_hook_engine 必须是 object"
        if not isinstance(value.get("episodes"), list):
            return "episodes 必须是数组"
        return None

    if _is_dialogue_payload_stage(stage_name) and field_name == BATCH_DIALOGUES:
        if not isinstance(value, dict):
            return "必须是 object"
        nested_value = value.get(BATCH_DIALOGUES)
        if isinstance(nested_value, str):
            try:
                nested_value = parse_json(nested_value)
            except Exception:
                nested_value = nested_value
        if isinstance(nested_value, dict):
            value = nested_value
        required = {"batch_meta", "character_voice_bibles", "episode_dialogue_blocks"}
        extra = sorted(set(value.keys()) - required)
        missing = sorted(required - set(value.keys()))
        if missing:
            return f"缺少键 {', '.join(missing)}"
        if extra:
            return f"存在非契约键 {', '.join(extra)}"
        if not isinstance(value.get("batch_meta"), dict):
            return "batch_meta 必须是 object"
        if not isinstance(value.get("character_voice_bibles"), list):
            return "character_voice_bibles 必须是数组"
        if not isinstance(value.get("episode_dialogue_blocks"), list):
            return "episode_dialogue_blocks 必须是数组"
        return None

    if stage_name in APPEARANCE_MAPPING_STAGE_NAMES and field_name == APPEARANCE_MAPPING:
        if not isinstance(value, dict):
            return "必须是 object"
        mapping = value.get("appearance_mapping") if isinstance(value.get("appearance_mapping"), dict) else value
        characters = mapping.get("characters")
        if not isinstance(characters, list):
            return "appearance_mapping.characters 必须是数组"
        if not any(isinstance(item, dict) for item in characters):
            return "appearance_mapping.characters 不能为空"
        return None

    return None


def _is_hook_payload_stage(stage_name: str) -> bool:
    return stage_name in {
        STAGE_HOOKS,
        STAGE_HOOKS_WRITING,
        STAGE_HOOK_WRITE,
        STAGE_HOOKS_REWRITE,
        STAGE_HOOK_REVISE,
    }


def _is_dialogue_payload_stage(stage_name: str) -> bool:
    return stage_name in {
        STAGE_DIALOGUES,
        STAGE_DIALOGUES_WRITING,
        STAGE_DIALOGUE_WRITE,
        STAGE_DIALOGUES_REWRITE,
        STAGE_DIALOGUE_REVISE,
    }


def _is_script_family_stage(stage_name: str) -> bool:
    return stage_name in {
        STAGE_SCRIPT,
        STAGE_SCRIPT_WRITING,
        STAGE_SCRIPT_WRITE,
        STAGE_SCRIPT_REVIEW,
        STAGE_SCRIPT_REWRITE,
        STAGE_SCRIPT_REVISE,
    }


def _describe_framework_story_outline_issue(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "必须是 object"
    issue = _describe_exact_keys_issue(value, FRAMEWORK_STORY_OUTLINE_KEYS)
    if issue:
        return issue
    for key in FRAMEWORK_STORY_OUTLINE_KEYS:
        if not str(value.get(key) or "").strip():
            return f"{key} 不能为空"
    return None


def _describe_framework_user_characters_issue(value: Any) -> str | None:
    if not isinstance(value, list):
        return "必须是数组"
    if not value:
        return "数组不能为空"
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            return f"第 {index} 个角色必须是 object"
        issue = _describe_exact_keys_issue(item, FRAMEWORK_CHARACTER_KEYS)
        if issue:
            return f"第 {index} 个角色 {issue}"
        for key in FRAMEWORK_CHARACTER_KEYS:
            if not str(item.get(key) or "").strip():
                return f"第 {index} 个角色的 {key} 不能为空"
    return None


def _describe_framework_user_scenes_issue(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "必须是 object"
    issue = _describe_exact_keys_issue(value, FRAMEWORK_SCENE_KEYS)
    if issue:
        return issue
    for key in FRAMEWORK_SCENE_KEYS:
        if key == "special_rules":
            if not isinstance(value.get(key), str):
                return "special_rules 必须是字符串"
            continue
        if key == "core_locations":
            locations = value.get(key)
            if not isinstance(locations, list):
                return "core_locations 必须是数组"
            if not locations:
                return "core_locations 不能为空"
            for index, location in enumerate(locations, start=1):
                if not isinstance(location, dict):
                    return f"第 {index} 个 core_locations 条目必须是 object"
                location_issue = _describe_exact_keys_issue(location, FRAMEWORK_CORE_LOCATION_KEYS)
                if location_issue:
                    return f"第 {index} 个 core_locations 条目 {location_issue}"
                for location_key in ("name", "function", "conflict_soil"):
                    if not str(location.get(location_key) or "").strip():
                        return f"第 {index} 个 core_locations 条目的 {location_key} 不能为空"
                key_characters = location.get("key_characters")
                if not isinstance(key_characters, list):
                    return f"第 {index} 个 core_locations 条目的 key_characters 必须是数组"
                if any(not str(character or "").strip() for character in key_characters):
                    return f"第 {index} 个 core_locations 条目的 key_characters 不能包含空值"
            continue
        if not str(value.get(key) or "").strip():
            return f"{key} 不能为空"
    return None


def _describe_framework_episode_plan_issue(value: Any) -> str | None:
    if not isinstance(value, list):
        return "必须是数组"
    if not value:
        return "数组不能为空"
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            return f"第 {index} 集必须是 object"
        issue = _describe_exact_keys_issue(item, FRAMEWORK_EPISODE_PLAN_KEYS)
        if issue:
            return f"第 {index} 集 {issue}"
        episode = item.get("episode")
        if isinstance(episode, bool):
            return f"第 {index} 集的 episode 必须是正整数"
        try:
            episode_number = int(episode)
        except (TypeError, ValueError):
            return f"第 {index} 集的 episode 必须是正整数"
        if episode_number <= 0:
            return f"第 {index} 集的 episode 必须是正整数"
        for key in ("title", "main_plot", "ending_hook"):
            if not str(item.get(key) or "").strip():
                return f"第 {episode_number} 集的 {key} 不能为空"
        conflicts = item.get("conflicts")
        if not isinstance(conflicts, list):
            return f"第 {episode_number} 集的 conflicts 必须是数组"
        if not conflicts:
            return f"第 {episode_number} 集的 conflicts 不能为空"
        if any(not str(conflict or "").strip() for conflict in conflicts):
            return f"第 {episode_number} 集的 conflicts 不能包含空值"
    return None


def _describe_exact_keys_issue(value: dict[str, Any], required_keys: tuple[str, ...]) -> str | None:
    required = set(required_keys)
    actual = set(value.keys())
    missing = sorted(required - actual)
    extra = sorted(actual - required)
    if missing:
        return f"缺少键 {', '.join(missing)}"
    if extra:
        return f"存在非契约键 {', '.join(extra)}"
    return None


GLOBAL_VARIABLES: dict[str, FastGPTVariable] = {
    TOTAL_EPISODES: FastGPTVariable(
        TOTAL_EPISODES,
        "number",
        "总集数",
        "用户输入",
    ),
    EPISODE_PLAN: FastGPTVariable(
        EPISODE_PLAN,
        "string",
        "用户分集计划。framework 阶段可能先返回结构化 JSON；本地会把它序列化后缓存。consistency/worldview 阶段传全量计划；hooks/dialogues/script 阶段传当前批次规范化 JSON 字符串。",
        "用户输入/本地批次裁剪",
    ),
    USER_EXPECTATION: FastGPTVariable(
        USER_EXPECTATION,
        "string",
        "用户对剧本的期待/想要的故事。",
        "用户输入",
    ),
    CHARACTER_COUNT: FastGPTVariable(
        CHARACTER_COUNT,
        "number",
        "角色数量。",
        "用户输入",
    ),
    CHARACTER_APPEARANCE_REQUIREMENTS: FastGPTVariable(
        CHARACTER_APPEARANCE_REQUIREMENTS,
        "string",
        "供后续阶段复用的服装版本需求。默认由“服装前置策略生成器”自动生成，也兼容外部直接传入。",
        "FastGPT 输出/兼容外部输入",
    ),
    CHARACTER_ALIAS_NAMING_RULES: FastGPTVariable(
        CHARACTER_ALIAS_NAMING_RULES,
        "string",
        "供后续阶段复用的人物别名/服装版本命名偏好，例如“顾沉（上班）/顾沉（居家）”。默认由“服装前置策略生成器”自动生成。",
        "FastGPT 输出/兼容外部输入",
    ),
    OUTFIT_SWITCH_RULES: FastGPTVariable(
        OUTFIT_SWITCH_RULES,
        "string",
        "供后续阶段复用的服装切换规则。默认由“服装前置策略生成器”自动生成。",
        "FastGPT 输出/兼容外部输入",
    ),
    NORMALIZED_EPISODE_PLAN: FastGPTVariable(
        NORMALIZED_EPISODE_PLAN,
        "object",
        "代码侧保存的规范化分集计划对象。",
        "FastGPT 输出/本地缓存",
    ),
    STORY_OUTLINE: FastGPTVariable(
        STORY_OUTLINE,
        "string",
        "故事大纲。framework 阶段可先返回结构化 JSON，本地缓存时仍统一保存为字符串。",
        "框架阶段输出/用户输入兼容",
    ),
    USER_SCENES: FastGPTVariable(
        USER_SCENES,
        "string",
        "核心场景。framework 阶段可先返回结构化 JSON，本地缓存时仍统一保存为字符串。",
        "框架阶段输出/用户输入兼容",
    ),
    USER_CHARACTERS: FastGPTVariable(
        USER_CHARACTERS,
        "string",
        "人物小传。framework 阶段可先返回结构化 JSON，本地缓存时仍统一保存为字符串。",
        "框架阶段输出/用户输入兼容",
    ),
    CHARACTER_SEARCH_INTENT: FastGPTVariable(
        CHARACTER_SEARCH_INTENT,
        "string",
        "人设检索意图。当前人设工作流的新公开输入变量；未提供时代码侧兼容为空字符串，避免旧项目和旧前端缺字段时直接失败。",
        "用户输入/兼容缺省",
    ),
    script_title_content: FastGPTVariable(
        script_title_content,
        "string",
        "剧本标题。优先使用框架阶段生成标题；若缺失，再回退到本地基于用户想要的剧本生成的标题。",
        "框架阶段输出/本地回退",
    ),
    WORLDVIEW: FastGPTVariable(
        WORLDVIEW,
        "string",
        "生成的世界观内容",
        "FastGPT 输出",
    ),
    CHARACTERS: FastGPTVariable(
        CHARACTERS,
        "string",
        "生成的人设内容",
        "FastGPT 输出",
    ),
    SCENES: FastGPTVariable(
        SCENES,
        "string",
        "生成的核心场景内容",
        "FastGPT 输出",
    ),
    SCENE_APPEARANCE_REQUIREMENTS: FastGPTVariable(
        SCENE_APPEARANCE_REQUIREMENTS,
        "object",
        "从场景 JSON 中提炼出的视觉条件、造型条件、命名条件与 alias 使用规则摘要。",
        "本地从场景阶段结果提炼",
    ),
    APPEARANCE_MAPPING: FastGPTVariable(
        APPEARANCE_MAPPING,
        "object",
        "人物服装版本映射 JSON。内部保存 canonical 角色与 outfit variant / alias 的对应关系。",
        "FastGPT 输出/本地缓存",
    ),
    CHARACTER_REGISTRY: FastGPTVariable(
        CHARACTER_REGISTRY,
        "object",
        "角色基础身份注册表。保存 canonical 角色本体与稳定识别锚点。",
        "本地从 appearance_mapping 提炼",
    ),
    CHARACTER_ALIAS_REGISTRY: FastGPTVariable(
        CHARACTER_ALIAS_REGISTRY,
        "object",
        "角色别名注册表。保存 alias_name 与 canonical 角色的映射关系。",
        "本地从 appearance_mapping 提炼",
    ),
    EPISODE_ALIAS_PLAN: FastGPTVariable(
        EPISODE_ALIAS_PLAN,
        "object",
        "逐集 alias 使用计划。为当前批次切片后供 hooks / dialogues / script 使用。",
        "本地从 normalized_episode_plan + appearance_mapping 提炼",
    ),
    APPEARANCE_CONTINUITY_MEMORY: FastGPTVariable(
        APPEARANCE_CONTINUITY_MEMORY,
        "object",
        "跨批次保存的角色当前服装/别名状态记忆。",
        "本地维护",
    ),
    BATCH_HOOKS: FastGPTVariable(
        BATCH_HOOKS,
        "object",
        "当前批次 5 集的开头冲突钩子 JSON",
        "FastGPT 输出",
    ),
    ALL_HOOKS: FastGPTVariable(
        ALL_HOOKS,
        "object",
        "完整开头冲突钩子 JSON",
        "本地拼接",
    ),
    BATCH_DIALOGUES: FastGPTVariable(
        BATCH_DIALOGUES,
        "object",
        "当前批次 5 集的角色对话 JSON",
        "FastGPT 输出",
    ),
    ALL_DIALOGUES: FastGPTVariable(
        ALL_DIALOGUES,
        "object",
        "完整角色对话 JSON",
        "本地拼接",
    ),
    BATCH_SCRIPT: FastGPTVariable(
        BATCH_SCRIPT,
        "string",
        "当前批次 5 集的剧本正文",
        "FastGPT 输出",
    ),
    ALL_SCRIPT: FastGPTVariable(
        ALL_SCRIPT,
        "string",
        "完整剧本正文",
        "本地拼接",
    ),
    LAST_SUMMARY: FastGPTVariable(
        LAST_SUMMARY,
        "string",
        "最近一次剧本摘要，覆盖式保存",
        "FastGPT 输出/本地覆盖",
    ),
    FINAL_SCRIPT: FastGPTVariable(
        FINAL_SCRIPT,
        "string",
        "最终完整剧本",
        "FastGPT 输出",
    ),
    IS_CONSISTENT: FastGPTVariable(
        IS_CONSISTENT,
        "boolean",
        "集数一致性检查结果",
        "FastGPT 输出",
    ),
    EPISODE_WORD_COUNT: FastGPTVariable(
        EPISODE_WORD_COUNT,
        "number",
        "每集正文字数。仅当前 legacy FastGPT 剧本正文工作流需要。",
        "用户输入",
    ),
    USER_CONTENT_BASELINE: FastGPTVariable(
        USER_CONTENT_BASELINE,
        "string",
        "用户内容提取基准 JSON。仅当前 legacy FastGPT 工作流需要。",
        "本地整理",
    ),
    MAX_RETRIES: FastGPTVariable(
        MAX_RETRIES,
        "number",
        "FastGPT 内部审核修订最大轮次。仅当前 legacy 工作流需要。",
        "本地配置",
    ),
    BATCH_START_EPISODE: FastGPTVariable(
        BATCH_START_EPISODE,
        "number",
        "当前批次起始集数。仅传给当前 legacy 批处理智能体，用于约束从第几集开始。",
        "本地批次控制",
    ),
}


LegacyInputAlias = str | tuple[str, ...]


LEGACY_INPUT_ALIASES: dict[str, dict[str, LegacyInputAlias]] = {
    STAGE_FRAMEWORK: {
        TOTAL_EPISODES: FRAMEWORK_TOTAL_EPISODES_VAR,
        USER_EXPECTATION: FRAMEWORK_USER_EXPECTATION_VAR,
        CHARACTER_COUNT: FRAMEWORK_CHARACTER_COUNT_VAR,
    },
    STAGE_FRAMEWORK_NATURALIZE: {
        UNSTRUCTURED_SOURCE: UNSTRUCTURED_SOURCE_VAR,
        UNSTRUCTURED_CONTENT_KIND: UNSTRUCTURED_KIND_VAR,
    },
    STAGE_APPEARANCE_PRE_STRATEGY: {
        USER_EXPECTATION: FRAMEWORK_USER_EXPECTATION_VAR,
        TOTAL_EPISODES: FRAMEWORK_TOTAL_EPISODES_VAR,
        CHARACTER_COUNT: FRAMEWORK_CHARACTER_COUNT_VAR,
        STORY_OUTLINE: FRAMEWORK_STORY_OUTLINE_VAR,
        USER_CHARACTERS: FRAMEWORK_CHARACTER_BIOS_VAR,
        USER_SCENES: FRAMEWORK_CORE_SCENE_VAR,
        EPISODE_PLAN: FRAMEWORK_EPISODE_PLAN_VAR,
    },
    STAGE_CONSISTENCY: {
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
    },
    STAGE_EPISODE_PLAN_NORMALIZE: {
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        USER_CHARACTERS: CHARACTER_BIOS_VAR,
        CHARACTER_ALIAS_NAMING_RULES: APPEARANCE_ALIAS_NAMING_RULES_VAR,
    },
    STAGE_WORLDVIEW: {
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        USER_SCENES: CORE_SCENE_INPUT_VAR,
        USER_CHARACTERS: CHARACTER_BIOS_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
    },
    STAGE_WORLDVIEW_NATURALIZE: {
        UNSTRUCTURED_SOURCE: UNSTRUCTURED_SOURCE_VAR,
        UNSTRUCTURED_CONTENT_KIND: UNSTRUCTURED_KIND_VAR,
    },
    STAGE_CHARACTERS_NATURALIZE: {
        UNSTRUCTURED_SOURCE: UNSTRUCTURED_SOURCE_VAR,
        UNSTRUCTURED_CONTENT_KIND: UNSTRUCTURED_KIND_VAR,
    },
    STAGE_CHARACTERS: {
        WORLDVIEW: WORLDVIEW_VAR,
        USER_CHARACTERS: CHARACTER_BIOS_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        CHARACTER_SEARCH_INTENT: CHARACTER_SEARCH_INTENT_VAR,
    },
    STAGE_SCENES: {
        WORLDVIEW: WORLDVIEW_VAR,
        USER_SCENES: CORE_SCENE_INPUT_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        USER_CHARACTERS: CHARACTER_BIOS_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        CHARACTER_APPEARANCE_REQUIREMENTS: SCENE_APPEARANCE_REQUIREMENTS_VAR,
        CHARACTER_ALIAS_NAMING_RULES: SCENE_ALIAS_NAMING_RULES_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
    },
    STAGE_APPEARANCE_ALIAS_GENERATION: {
        WORLDVIEW: WORLDVIEW_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        USER_CHARACTERS: CHARACTER_BIOS_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        CHARACTER_ALIAS_NAMING_RULES: APPEARANCE_ALIAS_NAMING_RULES_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
    },
    STAGE_APPEARANCE_ALIAS_WRITING: {
        WORLDVIEW: WORLDVIEW_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        USER_CHARACTERS: CHARACTER_BIOS_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        CHARACTER_ALIAS_NAMING_RULES: APPEARANCE_ALIAS_NAMING_RULES_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
    },
    STAGE_APPEARANCE_ALIAS_REVIEW: {
        WORLDVIEW: WORLDVIEW_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        USER_CHARACTERS: CHARACTER_BIOS_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        CHARACTER_ALIAS_NAMING_RULES: APPEARANCE_ALIAS_NAMING_RULES_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
    },
    STAGE_APPEARANCE_ALIAS_REWRITE: {
        WORLDVIEW: WORLDVIEW_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        USER_CHARACTERS: CHARACTER_BIOS_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        CHARACTER_ALIAS_NAMING_RULES: APPEARANCE_ALIAS_NAMING_RULES_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        PASS_REVIEW_JSON: APPEARANCE_REVIEW_VAR,
    },
    STAGE_APPEARANCE_ALIAS_UNSTRUCTURED: {
        WORLDVIEW: WORLDVIEW_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        USER_CHARACTERS: CHARACTER_BIOS_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        CHARACTER_ALIAS_NAMING_RULES: APPEARANCE_ALIAS_NAMING_RULES_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
    },
    STAGE_HOOKS: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        BATCH_START_EPISODE: HOOK_START_VAR,
        HOOK_MEMORY: HOOK_MEMORY_ALIASES,
    },
    STAGE_HOOKS_WRITING: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        BATCH_START_EPISODE: HOOK_START_VAR,
        HOOK_MEMORY: HOOK_MEMORY_ALIASES,
    },
    STAGE_HOOKS_REVIEW: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        BATCH_HOOKS: HOOK_CURRENT_ALIASES,
        HOOK_MEMORY: HOOK_MEMORY_ALIASES,
        BATCH_START_EPISODE: HOOK_START_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
    },
    STAGE_HOOKS_REWRITE: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        BATCH_HOOKS: HOOK_CURRENT_ALIASES,
        PASS_REVIEW_JSON: HOOK_REVIEW_OUTPUT_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        BATCH_START_EPISODE: HOOK_START_VAR,
        HOOK_MEMORY: HOOK_MEMORY_ALIASES,
    },
    STAGE_HOOK_WRITE: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        BATCH_START_EPISODE: HOOK_START_VAR,
        HOOK_MEMORY: HOOK_MEMORY_ALIASES,
    },
    STAGE_HOOK_REVIEW: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        BATCH_HOOKS: HOOK_CURRENT_ALIASES,
        HOOK_MEMORY: HOOK_MEMORY_ALIASES,
        BATCH_START_EPISODE: HOOK_START_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
    },
    STAGE_HOOK_REVISE: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        BATCH_HOOKS: HOOK_CURRENT_ALIASES,
        PASS_REVIEW_JSON: HOOK_REVIEW_OUTPUT_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        BATCH_START_EPISODE: HOOK_START_VAR,
        HOOK_MEMORY: HOOK_MEMORY_ALIASES,
    },
    STAGE_HOOK_MEMORY: {
        BATCH_HOOKS: HOOK_CURRENT_ALIASES,
        HOOK_MEMORY: HOOK_MEMORY_ALIASES,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        BATCH_START_EPISODE: HOOK_START_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
    },
    STAGE_DIALOGUES: {
        WORLDVIEW: DIALOGUE_WORLDVIEW_INPUT_VAR,
        CHARACTERS: DIALOGUE_CHARACTER_INPUT_VAR,
        SCENES: DIALOGUE_SCENE_INPUT_VAR,
        ALL_HOOKS: DIALOGUE_HOOK_ALIASES,
        EPISODE_PLAN: DIALOGUE_EPISODE_PLAN_INPUT_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: DIALOGUE_TOTAL_EPISODES_INPUT_VAR,
        BATCH_START_EPISODE: DIALOGUE_START_INPUT_VAR,
        MAX_RETRIES: DIALOGUE_MAX_RETRY_INPUT_VAR,
        DIALOGUE_MEMORY: DIALOGUE_MEMORY_ALIASES,
    },
    STAGE_DIALOGUES_WRITING: {
        WORLDVIEW: DIALOGUE_WORLDVIEW_INPUT_VAR,
        CHARACTERS: DIALOGUE_CHARACTER_INPUT_VAR,
        SCENES: DIALOGUE_SCENE_INPUT_VAR,
        ALL_HOOKS: DIALOGUE_HOOK_ALIASES,
        EPISODE_PLAN: DIALOGUE_EPISODE_PLAN_INPUT_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: DIALOGUE_TOTAL_EPISODES_INPUT_VAR,
        BATCH_START_EPISODE: DIALOGUE_START_INPUT_VAR,
        MAX_RETRIES: DIALOGUE_MAX_RETRY_INPUT_VAR,
        DIALOGUE_MEMORY: DIALOGUE_MEMORY_ALIASES,
    },
    STAGE_DIALOGUES_REVIEW: {
        WORLDVIEW: DIALOGUE_WORLDVIEW_INPUT_VAR,
        CHARACTERS: DIALOGUE_CHARACTER_INPUT_VAR,
        SCENES: DIALOGUE_SCENE_INPUT_VAR,
        ALL_HOOKS: DIALOGUE_HOOK_ALIASES,
        EPISODE_PLAN: DIALOGUE_EPISODE_PLAN_INPUT_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: DIALOGUE_TOTAL_EPISODES_INPUT_VAR,
        BATCH_START_EPISODE: DIALOGUE_START_INPUT_VAR,
        BATCH_DIALOGUES: DIALOGUE_CURRENT_ALIASES,
    },
    STAGE_DIALOGUES_REWRITE: {
        WORLDVIEW: DIALOGUE_WORLDVIEW_INPUT_VAR,
        CHARACTERS: DIALOGUE_CHARACTER_INPUT_VAR,
        SCENES: DIALOGUE_SCENE_INPUT_VAR,
        ALL_HOOKS: DIALOGUE_HOOK_ALIASES,
        EPISODE_PLAN: DIALOGUE_EPISODE_PLAN_INPUT_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: DIALOGUE_TOTAL_EPISODES_INPUT_VAR,
        BATCH_START_EPISODE: DIALOGUE_START_INPUT_VAR,
        BATCH_DIALOGUES: DIALOGUE_CURRENT_ALIASES,
        PASS_REVIEW_JSON: DIALOGUE_REVIEW_ALIASES,
        DIALOGUE_MEMORY: DIALOGUE_MEMORY_ALIASES,
    },
    STAGE_DIALOGUE_WRITE: {
        WORLDVIEW: DIALOGUE_WORLDVIEW_INPUT_VAR,
        CHARACTERS: DIALOGUE_CHARACTER_INPUT_VAR,
        SCENES: DIALOGUE_SCENE_INPUT_VAR,
        ALL_HOOKS: DIALOGUE_HOOK_ALIASES,
        EPISODE_PLAN: DIALOGUE_EPISODE_PLAN_INPUT_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: DIALOGUE_TOTAL_EPISODES_INPUT_VAR,
        BATCH_START_EPISODE: DIALOGUE_START_INPUT_VAR,
        MAX_RETRIES: DIALOGUE_MAX_RETRY_INPUT_VAR,
        DIALOGUE_MEMORY: DIALOGUE_MEMORY_ALIASES,
    },
    STAGE_DIALOGUE_REVIEW: {
        WORLDVIEW: DIALOGUE_WORLDVIEW_INPUT_VAR,
        CHARACTERS: DIALOGUE_CHARACTER_INPUT_VAR,
        SCENES: DIALOGUE_SCENE_INPUT_VAR,
        ALL_HOOKS: DIALOGUE_HOOK_ALIASES,
        EPISODE_PLAN: DIALOGUE_EPISODE_PLAN_INPUT_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: DIALOGUE_TOTAL_EPISODES_INPUT_VAR,
        BATCH_START_EPISODE: DIALOGUE_START_INPUT_VAR,
        BATCH_DIALOGUES: DIALOGUE_CURRENT_ALIASES,
    },
    STAGE_DIALOGUE_REVISE: {
        WORLDVIEW: DIALOGUE_WORLDVIEW_INPUT_VAR,
        CHARACTERS: DIALOGUE_CHARACTER_INPUT_VAR,
        SCENES: DIALOGUE_SCENE_INPUT_VAR,
        ALL_HOOKS: DIALOGUE_HOOK_ALIASES,
        EPISODE_PLAN: DIALOGUE_EPISODE_PLAN_INPUT_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: DIALOGUE_TOTAL_EPISODES_INPUT_VAR,
        BATCH_START_EPISODE: DIALOGUE_START_INPUT_VAR,
        BATCH_DIALOGUES: DIALOGUE_CURRENT_ALIASES,
        PASS_REVIEW_JSON: DIALOGUE_REVIEW_ALIASES,
        DIALOGUE_MEMORY: DIALOGUE_MEMORY_ALIASES,
    },
    STAGE_DIALOGUE_MEMORY: {
        BATCH_DIALOGUES: DIALOGUE_CURRENT_ALIASES,
        DIALOGUE_MEMORY: DIALOGUE_MEMORY_ALIASES,
        ALL_HOOKS: DIALOGUE_HOOK_ALIASES,
        EPISODE_PLAN: DIALOGUE_EPISODE_PLAN_INPUT_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: DIALOGUE_TOTAL_EPISODES_INPUT_VAR,
        BATCH_START_EPISODE: DIALOGUE_START_INPUT_VAR,
        CHARACTER_ALIAS_NAMING_RULES: APPEARANCE_ALIAS_NAMING_RULES_VAR,
    },
    STAGE_SCRIPT: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: CHARACTER_VAR,
        ALL_HOOKS: SCRIPT_HOOK_ALIASES,
        ALL_DIALOGUES: SCRIPT_DIALOGUE_ALIASES,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        EPISODE_WORD_COUNT: EPISODE_WORD_COUNT_VAR,
        LAST_SUMMARY: SCRIPT_MEMORY_ALIASES,
        SCRIPT_MEMORY: SCRIPT_MEMORY_ALIASES,
        BATCH_START_EPISODE: SCRIPT_START_VAR,
        ALL_SCRIPT: SCRIPT_FINAL_VAR,
    },
    STAGE_SCRIPT_WRITING: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: CHARACTER_VAR,
        ALL_HOOKS: SCRIPT_HOOK_ALIASES,
        ALL_DIALOGUES: SCRIPT_DIALOGUE_ALIASES,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        EPISODE_WORD_COUNT: EPISODE_WORD_COUNT_VAR,
        LAST_SUMMARY: SCRIPT_MEMORY_ALIASES,
        SCRIPT_MEMORY: SCRIPT_MEMORY_ALIASES,
        BATCH_START_EPISODE: SCRIPT_START_VAR,
        ALL_SCRIPT: SCRIPT_FINAL_VAR,
    },
    STAGE_SCRIPT_REVIEW: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: CHARACTER_VAR,
        ALL_HOOKS: SCRIPT_HOOK_ALIASES,
        ALL_DIALOGUES: SCRIPT_DIALOGUE_ALIASES,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        EPISODE_WORD_COUNT: EPISODE_WORD_COUNT_VAR,
        LAST_SUMMARY: SCRIPT_MEMORY_ALIASES,
        SCRIPT_MEMORY: SCRIPT_MEMORY_ALIASES,
        BATCH_START_EPISODE: SCRIPT_START_VAR,
        BATCH_SCRIPT: SCRIPT_CURRENT_ALIASES,
    },
    STAGE_SCRIPT_REWRITE: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: CHARACTER_VAR,
        ALL_HOOKS: SCRIPT_HOOK_ALIASES,
        ALL_DIALOGUES: SCRIPT_DIALOGUE_ALIASES,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        EPISODE_WORD_COUNT: EPISODE_WORD_COUNT_VAR,
        LAST_SUMMARY: SCRIPT_MEMORY_ALIASES,
        SCRIPT_MEMORY: SCRIPT_MEMORY_ALIASES,
        BATCH_START_EPISODE: SCRIPT_START_VAR,
        BATCH_SCRIPT: SCRIPT_CURRENT_ALIASES,
        PASS_REVIEW_JSON: SCRIPT_REVIEW_ALIASES,
    },
    STAGE_SCRIPT_WRITE: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: CHARACTER_VAR,
        ALL_HOOKS: SCRIPT_HOOK_ALIASES,
        ALL_DIALOGUES: SCRIPT_DIALOGUE_ALIASES,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        EPISODE_WORD_COUNT: EPISODE_WORD_COUNT_VAR,
        LAST_SUMMARY: SCRIPT_MEMORY_ALIASES,
        SCRIPT_MEMORY: SCRIPT_MEMORY_ALIASES,
        BATCH_START_EPISODE: SCRIPT_START_VAR,
        ALL_SCRIPT: SCRIPT_FINAL_VAR,
    },
    STAGE_SCRIPT_REVISE: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: CHARACTER_VAR,
        ALL_HOOKS: SCRIPT_HOOK_ALIASES,
        ALL_DIALOGUES: SCRIPT_DIALOGUE_ALIASES,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        EPISODE_WORD_COUNT: EPISODE_WORD_COUNT_VAR,
        LAST_SUMMARY: SCRIPT_MEMORY_ALIASES,
        SCRIPT_MEMORY: SCRIPT_MEMORY_ALIASES,
        BATCH_START_EPISODE: SCRIPT_START_VAR,
        BATCH_SCRIPT: SCRIPT_CURRENT_ALIASES,
        PASS_REVIEW_JSON: SCRIPT_REVIEW_ALIASES,
    },
    STAGE_MEMORY: {
        BATCH_SCRIPT: SCRIPT_CURRENT_ALIASES,
        LAST_SUMMARY: SCRIPT_MEMORY_ALIASES,
        SCRIPT_MEMORY: SCRIPT_MEMORY_ALIASES,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        CHARACTER_ALIAS_NAMING_RULES: APPEARANCE_ALIAS_NAMING_RULES_VAR,
    },
    STAGE_SCRIPT_MEMORY: {
        BATCH_SCRIPT: SCRIPT_CURRENT_ALIASES,
        LAST_SUMMARY: SCRIPT_MEMORY_ALIASES,
        SCRIPT_MEMORY: SCRIPT_MEMORY_ALIASES,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        CHARACTER_ALIAS_NAMING_RULES: APPEARANCE_ALIAS_NAMING_RULES_VAR,
    },
    STAGE_FINAL: {
        script_title_content: TITLE_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        CHARACTERS: FINAL_CHARACTER_VAR,
        SCENES: FINAL_SCENE_VAR,
        ALL_SCRIPT: SCRIPT_FINAL_VAR,
    },
}


# Keep broad legacy alias coverage for compatibility with workflow public input
# declarations, but allow individual stages to further trim what is actually sent
# on the wire when their active system prompt only references a smaller subset.
LEGACY_WIRE_INPUT_ALIASES_OVERRIDES: dict[str, dict[str, LegacyInputAlias]] = {
    STAGE_SCRIPT_REVIEW: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        APPEARANCE_MAPPING: APPEARANCE_MAPPING_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        SCRIPT_MEMORY: MEMORY_VAR,
        BATCH_SCRIPT: SCRIPT_CURRENT_VAR,
        EPISODE_WORD_COUNT: EPISODE_WORD_COUNT_VAR,
        BATCH_START_EPISODE: SCRIPT_START_VAR,
    },
}


STAGE_CONTRACTS: dict[str, FastGPTStageContract] = {
    STAGE_FRAMEWORK: FastGPTStageContract(
        stage_name=STAGE_FRAMEWORK,
        label="剧本框架撰写",
        # framework 必须和网页端保持一致，只吃 3 个用户输入：
        # 想要的剧本 / 角色数量 / 总集数。
        # 服装需求、命名偏好等字段已经前移为后置内部阶段生成，
        # 不能再回流成 framework 的直接输入。
        input_names=FRAMEWORK_WEB_INPUT_NAMES,
        output_types={
            script_title_content: "string",
            STORY_OUTLINE: "object",
            USER_CHARACTERS: "array",
            USER_SCENES: "object",
            EPISODE_PLAN: "array",
        },
        output_aliases={
            script_title_content: (FRAMEWORK_TITLE_VAR, "script_title", "title"),
            STORY_OUTLINE: (FRAMEWORK_STORY_OUTLINE_VAR, "story_outline_content"),
            USER_CHARACTERS: (FRAMEWORK_CHARACTER_BIOS_VAR, "character_bios_content"),
            USER_SCENES: (FRAMEWORK_CORE_SCENE_VAR, "core_scene_content"),
            EPISODE_PLAN: (FRAMEWORK_EPISODE_PLAN_VAR, "episode_plan_content"),
        },
        fastgpt_responsibility="根据用户想要的剧本、角色数量和总集数，生成剧本标题、故事大纲、人物小传、核心场景、分集计划。",
        local_responsibility="缓存并复用五项框架产物，后续阶段统一读取这些结果。",
        workflow_json_name="剧本框架撰写.json",
    ),
    STAGE_FRAMEWORK_NATURALIZE: FastGPTStageContract(
        stage_name=STAGE_FRAMEWORK_NATURALIZE,
        label="剧本框架自然语言化",
        input_names=(UNSTRUCTURED_SOURCE, UNSTRUCTURED_CONTENT_KIND),
        output_types={FRAMEWORK_NATURAL_LANGUAGE: "string"},
        output_aliases={FRAMEWORK_NATURAL_LANGUAGE: (UNSTRUCTURED_OUTPUT_VAR,)},
        fastgpt_responsibility="把完整结构化剧本框架改写成普通人可读的自然语言说明。",
        local_responsibility="保留结构化 framework 正式产物，并额外缓存自然语言框架说明供前端展示和辅助输入。",
        expected_output_kind="unstructured_natural_language_text",
        workflow_json_name="自然语言化.json",
    ),
    STAGE_APPEARANCE_PRE_STRATEGY: FastGPTStageContract(
        stage_name=STAGE_APPEARANCE_PRE_STRATEGY,
        label="服装前置策略生成器",
        input_names=(
            USER_EXPECTATION,
            TOTAL_EPISODES,
            CHARACTER_COUNT,
            STORY_OUTLINE,
            USER_CHARACTERS,
            USER_SCENES,
            EPISODE_PLAN,
        ),
        output_types={
            CHARACTER_APPEARANCE_REQUIREMENTS: "string",
            CHARACTER_ALIAS_NAMING_RULES: "string",
            OUTFIT_SWITCH_RULES: "string",
        },
        output_aliases={
            CHARACTER_APPEARANCE_REQUIREMENTS: (APPEARANCE_PRE_STRATEGY_REQUIREMENTS_VAR,),
            CHARACTER_ALIAS_NAMING_RULES: (APPEARANCE_ALIAS_NAMING_RULES_VAR,),
            OUTFIT_SWITCH_RULES: (OUTFIT_SWITCH_RULES_VAR,),
        },
        fastgpt_responsibility="基于故事、人物、场景和分集计划，先生成后续阶段要统一复用的服装版本需求、命名偏好和服装切换规则。",
        local_responsibility="缓存三项服装前置策略结果，并继续沿用现有逻辑字段供后续阶段读取。",
        workflow_json_name="服装前置策略生成器.json",
    ),
    STAGE_CONSISTENCY: FastGPTStageContract(
        stage_name=STAGE_CONSISTENCY,
        label="集数一致性检查",
        input_names=(TOTAL_EPISODES, EPISODE_PLAN),
        output_types={IS_CONSISTENT: "boolean"},
        output_aliases={IS_CONSISTENT: ("passed", "approved", "consistent")},
        fastgpt_responsibility="判断分集计划与总集数是否一致。",
        local_responsibility="不做内容判断，只根据布尔结果继续或停止。",
        workflow_json_name="集数一致性检查.json",
    ),
    STAGE_EPISODE_PLAN_NORMALIZE: FastGPTStageContract(
        stage_name=STAGE_EPISODE_PLAN_NORMALIZE,
        label="分集计划规范化",
        input_names=(
            EPISODE_PLAN,
            STORY_OUTLINE,
            USER_CHARACTERS,
            CHARACTER_ALIAS_NAMING_RULES,
        ),
        output_types={NORMALIZED_EPISODE_PLAN: "object"},
        output_aliases={
            NORMALIZED_EPISODE_PLAN: (
                EPISODE_PLAN_NORMALIZED_VAR,
                "episode_plan_normalized",
                "normalizedEpisodePlan",
                "episodePlanNormalized",
                "normalized_plan",
            )
        },
        fastgpt_responsibility="只把原始分集计划整理成结构化 JSON，不做改写、润色、摘要或扩写。",
        local_responsibility="缓存规范化结果，并从中提炼逐集 alias 使用计划供后续批处理阶段读取当前批次需要的集数。",
        workflow_json_name="分集计划规范化.json",
    ),
    STAGE_WORLDVIEW: FastGPTStageContract(
        stage_name=STAGE_WORLDVIEW,
        label="世界观生成与审核",
        input_names=(STORY_OUTLINE, USER_SCENES, USER_CHARACTERS, EPISODE_PLAN),
        output_types={WORLDVIEW: "string"},
        output_aliases={WORLDVIEW: (WORLDVIEW_VAR,)},
        fastgpt_responsibility="完成世界观提取、生成、审核、修订，返回最终可用世界观。",
        local_responsibility="不做业务审核循环，只校验 worldview 是否按契约返回并缓存。",
        workflow_json_name="世界观生成.json",
    ),
    STAGE_WORLDVIEW_NATURALIZE: FastGPTStageContract(
        stage_name=STAGE_WORLDVIEW_NATURALIZE,
        label="世界观自然语言化",
        input_names=(UNSTRUCTURED_SOURCE, UNSTRUCTURED_CONTENT_KIND),
        output_types={WORLDVIEW_NATURAL_LANGUAGE: "string"},
        output_aliases={WORLDVIEW_NATURAL_LANGUAGE: (UNSTRUCTURED_OUTPUT_VAR,)},
        fastgpt_responsibility="把结构化世界观改写成普通人可读的自然语言说明。",
        local_responsibility="保留结构化 worldview 正式产物，并额外缓存自然语言世界观说明供前端展示和辅助输入。",
        expected_output_kind="unstructured_natural_language_text",
        workflow_json_name="自然语言化.json",
    ),
    STAGE_CHARACTERS_NATURALIZE: FastGPTStageContract(
        stage_name=STAGE_CHARACTERS_NATURALIZE,
        label="人物小传自然语言化",
        input_names=(UNSTRUCTURED_SOURCE, UNSTRUCTURED_CONTENT_KIND),
        output_types={CHARACTER_NATURAL_LANGUAGE_VAR: "string"},
        output_aliases={CHARACTER_NATURAL_LANGUAGE_VAR: (UNSTRUCTURED_OUTPUT_VAR,)},
        fastgpt_responsibility="把结构化人物设定或原始人物小传整理成普通人可读的人物小传自然语言说明。",
        local_responsibility="保留结构化人物设定正式产物，并额外缓存统一自然语言人物小传供前端展示和导出使用。",
        expected_output_kind="unstructured_natural_language_text",
        workflow_json_name="自然语言化.json",
    ),
    STAGE_CHARACTERS: FastGPTStageContract(
        stage_name=STAGE_CHARACTERS,
        label="人物设定生成与审核",
        input_names=(USER_CHARACTERS, WORLDVIEW, STORY_OUTLINE, CHARACTER_SEARCH_INTENT),
        output_types={CHARACTERS: "string"},
        output_aliases={CHARACTERS: (CHARACTER_VAR,)},
        fastgpt_responsibility="完成人设生成、审核、修订、整理。",
        local_responsibility="不做业务审核循环，只校验 characters 是否按契约返回并缓存。",
        workflow_json_name="人设生成.json",
    ),
    STAGE_SCENES: FastGPTStageContract(
        stage_name=STAGE_SCENES,
        label="核心场景生成与审核",
        input_names=(
            USER_SCENES,
            WORLDVIEW,
            STORY_OUTLINE,
            USER_CHARACTERS,
            EPISODE_PLAN,
            CHARACTER_APPEARANCE_REQUIREMENTS,
            CHARACTER_ALIAS_NAMING_RULES,
        ),
        output_types={SCENES: "string"},
        output_aliases={SCENES: (SCENE_VAR,)},
        fastgpt_responsibility="完成核心场景提炼/复用、生成、审核、修订、整理。",
        local_responsibility="不做业务审核循环，只校验 scenes 是否按契约返回并缓存。",
        workflow_json_name="场景生成.json",
    ),
    STAGE_APPEARANCE_ALIAS_GENERATION: FastGPTStageContract(
        stage_name=STAGE_APPEARANCE_ALIAS_GENERATION,
        label="人物服装版本映射",
        input_names=(
            WORLDVIEW,
            STORY_OUTLINE,
            EPISODE_PLAN,
            USER_CHARACTERS,
            CHARACTERS,
            SCENES,
            CHARACTER_ALIAS_NAMING_RULES,
        ),
        output_types={APPEARANCE_MAPPING: "object"},
        output_aliases={APPEARANCE_MAPPING: (APPEARANCE_MAPPING_VAR,)},
        fastgpt_responsibility="逻辑阶段名；实际由 Python 依次调用服装映射编写、审核、修订与自然语言说明四个独立 workflow。",
        local_responsibility="编排四阶段循环，审核通过后才提交正式 appearance_mapping，并在本地提炼 registry / alias plan。",
    ),
    STAGE_APPEARANCE_ALIAS_WRITING: FastGPTStageContract(
        stage_name=STAGE_APPEARANCE_ALIAS_WRITING,
        label="服装版本映射编写",
        input_names=(
            WORLDVIEW,
            STORY_OUTLINE,
            EPISODE_PLAN,
            USER_CHARACTERS,
            CHARACTERS,
            SCENES,
            CHARACTER_ALIAS_NAMING_RULES,
        ),
        output_types={APPEARANCE_MAPPING: "object"},
        output_aliases={APPEARANCE_MAPPING: (APPEARANCE_MAPPING_VAR,)},
        fastgpt_responsibility="编写完整结构化服装版本映射 JSON。",
        local_responsibility="只做输出 repair/结构校验；正式缓存提交由 Python 审核结果决定。",
        expected_output_kind="appearance_mapping_json",
        workflow_json_name="服装版本映射编写.json",
    ),
    STAGE_APPEARANCE_ALIAS_REVIEW: FastGPTStageContract(
        stage_name=STAGE_APPEARANCE_ALIAS_REVIEW,
        label="服装版本映射审核",
        input_names=(
            WORLDVIEW,
            STORY_OUTLINE,
            EPISODE_PLAN,
            USER_CHARACTERS,
            CHARACTERS,
            SCENES,
            CHARACTER_ALIAS_NAMING_RULES,
            APPEARANCE_MAPPING,
        ),
        output_types={
            REVIEW_PASSED: "boolean",
            REWRITE_REQUIRED: "boolean",
            BLOCKING_ISSUES: "array",
        },
        output_aliases={
            REVIEW_PASSED: (APPEARANCE_REVIEW_VAR, "approved"),
            REWRITE_REQUIRED: (APPEARANCE_REVIEW_VAR,),
            BLOCKING_ISSUES: (APPEARANCE_REVIEW_VAR,),
        },
        fastgpt_responsibility="审核当前结构化服装版本映射是否可提交到正式缓存。",
        local_responsibility="严格解析 review JSON，并决定进入通过、修订或失败退出。",
        expected_output_kind="review_json",
        workflow_json_name="服装版本映射审核.json",
    ),
    STAGE_APPEARANCE_ALIAS_REWRITE: FastGPTStageContract(
        stage_name=STAGE_APPEARANCE_ALIAS_REWRITE,
        label="服装版本映射修订",
        input_names=(
            WORLDVIEW,
            STORY_OUTLINE,
            EPISODE_PLAN,
            USER_CHARACTERS,
            CHARACTERS,
            SCENES,
            CHARACTER_ALIAS_NAMING_RULES,
            APPEARANCE_MAPPING,
            PASS_REVIEW_JSON,
        ),
        output_types={APPEARANCE_MAPPING: "object"},
        output_aliases={APPEARANCE_MAPPING: (APPEARANCE_MAPPING_VAR,)},
        fastgpt_responsibility="基于当前服装映射与审核结果，输出新的完整 appearance_mapping。",
        local_responsibility="只做输出 repair/结构校验；是否继续循环由 Python 决定。",
        expected_output_kind="appearance_mapping_json",
        workflow_json_name="服装版本映射修订.json",
    ),
    STAGE_APPEARANCE_ALIAS_UNSTRUCTURED: FastGPTStageContract(
        stage_name=STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
        label="自然语言服装版本映射说明",
        input_names=(
            WORLDVIEW,
            STORY_OUTLINE,
            EPISODE_PLAN,
            USER_CHARACTERS,
            CHARACTERS,
            SCENES,
            CHARACTER_ALIAS_NAMING_RULES,
            APPEARANCE_MAPPING,
        ),
        output_types={APPEARANCE_NATURAL_LANGUAGE_VAR: "string"},
        output_aliases={APPEARANCE_NATURAL_LANGUAGE_VAR: (APPEARANCE_NATURAL_LANGUAGE_VAR,)},
        fastgpt_responsibility="把正式结构化服装映射整理成便于人工阅读的自然语言说明。",
        local_responsibility="只缓存 c7VnQ4eX 展示文本；不能覆盖 h2KpLm91。",
        expected_output_kind="unstructured_natural_language_text",
        workflow_json_name="自然语言服装版本映射.json",
    ),
    STAGE_HOOKS: FastGPTStageContract(
        stage_name=STAGE_HOOKS,
        label="开头冲突钩子批处理",
        input_names=(
            WORLDVIEW,
            CHARACTERS,
            SCENES,
            STORY_OUTLINE,
            EPISODE_PLAN,
            APPEARANCE_MAPPING,
            TOTAL_EPISODES,
            BATCH_START_EPISODE,
        ),
        output_types={BATCH_HOOKS: "object"},
        fastgpt_responsibility="生成当前批次 5 集的开头冲突钩子 JSON。",
        local_responsibility="划分批次、裁剪 episode_plan、拼接 all_hooks、推进批次。",
    ),
    STAGE_HOOKS_WRITING: FastGPTStageContract(
        stage_name=STAGE_HOOKS_WRITING,
        label="开头冲突钩子编写",
        input_names=(
            WORLDVIEW,
            CHARACTERS,
            SCENES,
            STORY_OUTLINE,
            EPISODE_PLAN,
            APPEARANCE_MAPPING,
            HOOK_MEMORY,
            TOTAL_EPISODES,
            BATCH_START_EPISODE,
        ),
        output_types={BATCH_HOOKS: "object"},
        output_aliases={BATCH_HOOKS: (*HOOK_CURRENT_ALIASES, "batch_hooks")},
        fastgpt_responsibility="编写当前批次 5 集的开头冲突钩子 JSON。",
        local_responsibility="只消费当前批输入，不直接提交 all_hooks；是否落正式缓存由本地审核结果决定。",
        expected_output_kind="hooks_batch_json",
        workflow_json_name="开头冲突钩子编写.json",
    ),
    STAGE_HOOKS_REVIEW: FastGPTStageContract(
        stage_name=STAGE_HOOKS_REVIEW,
        label="开头冲突钩子审核",
        input_names=(
            WORLDVIEW,
            CHARACTERS,
            SCENES,
            STORY_OUTLINE,
            EPISODE_PLAN,
            APPEARANCE_MAPPING,
            BATCH_HOOKS,
            HOOK_MEMORY,
            BATCH_START_EPISODE,
            TOTAL_EPISODES,
        ),
        output_types={
            REVIEW_PASSED: "boolean",
            REWRITE_REQUIRED: "boolean",
            BLOCKING_ISSUES: "array",
        },
        output_aliases={
            REVIEW_PASSED: (HOOK_REVIEW_OUTPUT_VAR, HOOK_REVIEW_RESULT, "approved"),
            REWRITE_REQUIRED: (HOOK_REVIEW_OUTPUT_VAR, HOOK_REVIEW_RESULT),
            BLOCKING_ISSUES: (HOOK_REVIEW_OUTPUT_VAR, HOOK_REVIEW_RESULT),
        },
        fastgpt_responsibility="审核当前批次开头冲突钩子是否可提交。",
        local_responsibility="把审核结果转成 passed/rewrite_required/blocking_issues，并决定是否进入修订。",
        expected_output_kind="review_json",
        workflow_json_name="开头冲突钩子审核.json",
    ),
    STAGE_HOOKS_REWRITE: FastGPTStageContract(
        stage_name=STAGE_HOOKS_REWRITE,
        label="开头冲突钩子修订",
        input_names=(
            WORLDVIEW,
            CHARACTERS,
            SCENES,
            STORY_OUTLINE,
            EPISODE_PLAN,
            APPEARANCE_MAPPING,
            BATCH_HOOKS,
            PASS_REVIEW_JSON,
            HOOK_MEMORY,
            TOTAL_EPISODES,
            BATCH_START_EPISODE,
        ),
        output_types={BATCH_HOOKS: "object"},
        output_aliases={BATCH_HOOKS: (*HOOK_CURRENT_ALIASES, "batch_hooks")},
        fastgpt_responsibility="根据审核意见重写当前批次开头冲突钩子 JSON。",
        local_responsibility="保留当前批次边界，只在 passed=true 后才允许提交到 all_hooks。",
        expected_output_kind="hooks_batch_json",
        workflow_json_name="开头冲突钩子修订.json",
    ),
    STAGE_DIALOGUES: FastGPTStageContract(
        stage_name=STAGE_DIALOGUES,
        label="角色对话批处理",
        input_names=(
            WORLDVIEW,
            CHARACTERS,
            SCENES,
            ALL_HOOKS,
            EPISODE_PLAN,
            APPEARANCE_MAPPING,
            DIALOGUE_MEMORY,
            TOTAL_EPISODES,
            BATCH_START_EPISODE,
            MAX_RETRIES,
        ),
        output_types={BATCH_DIALOGUES: "object"},
        output_aliases={
            BATCH_DIALOGUES: (
                *DIALOGUE_CURRENT_ALIASES,
                "batchDialogues",
                "dialogue_content",
                "batch_dialogues_raw",
            )
        },
        fastgpt_responsibility="生成当前批次 5 集的角色对话 JSON。",
        local_responsibility="划分批次、裁剪 episode_plan、拼接 all_dialogues、推进批次。",
    ),
    STAGE_DIALOGUES_WRITING: FastGPTStageContract(
        stage_name=STAGE_DIALOGUES_WRITING,
        label="角色对白编写",
        input_names=(
            WORLDVIEW,
            CHARACTERS,
            SCENES,
            ALL_HOOKS,
            EPISODE_PLAN,
            APPEARANCE_MAPPING,
            DIALOGUE_MEMORY,
            TOTAL_EPISODES,
            BATCH_START_EPISODE,
            MAX_RETRIES,
        ),
        output_types={BATCH_DIALOGUES: "object"},
        output_aliases={
            BATCH_DIALOGUES: (
                *DIALOGUE_CURRENT_ALIASES,
                "batchDialogues",
                "dialogue_content",
                "batch_dialogues_raw",
                "batch_dialogues",
            )
        },
        fastgpt_responsibility="编写当前批次 5 集的角色对白 JSON。",
        local_responsibility="只缓存当前批次临时对白，正式合并到 all_dialogues 前仍需本地审核通过。",
        expected_output_kind="dialogues_batch_json",
        workflow_json_name="角色对话编写.json",
    ),
    STAGE_DIALOGUES_REVIEW: FastGPTStageContract(
        stage_name=STAGE_DIALOGUES_REVIEW,
        label="角色对白审核",
        input_names=(
            WORLDVIEW,
            CHARACTERS,
            SCENES,
            ALL_HOOKS,
            EPISODE_PLAN,
            APPEARANCE_MAPPING,
            TOTAL_EPISODES,
            BATCH_START_EPISODE,
            BATCH_DIALOGUES,
        ),
        output_types={
            REVIEW_PASSED: "boolean",
            REWRITE_REQUIRED: "boolean",
            BLOCKING_ISSUES: "array",
        },
        output_aliases={
            REVIEW_PASSED: (*DIALOGUE_REVIEW_ALIASES, "approved"),
            REWRITE_REQUIRED: (*DIALOGUE_REVIEW_ALIASES,),
            BLOCKING_ISSUES: (*DIALOGUE_REVIEW_ALIASES,),
        },
        fastgpt_responsibility="审核当前批次角色对白是否可提交。",
        local_responsibility="把审核结果转成 passed/rewrite_required/blocking_issues，并决定是否进入修订。",
        expected_output_kind="review_json",
        workflow_json_name="角色对话审核.json",
    ),
    STAGE_DIALOGUES_REWRITE: FastGPTStageContract(
        stage_name=STAGE_DIALOGUES_REWRITE,
        label="角色对白修订",
        input_names=(
            WORLDVIEW,
            CHARACTERS,
            SCENES,
            ALL_HOOKS,
            EPISODE_PLAN,
            APPEARANCE_MAPPING,
            TOTAL_EPISODES,
            BATCH_START_EPISODE,
            BATCH_DIALOGUES,
            PASS_REVIEW_JSON,
            DIALOGUE_MEMORY,
        ),
        output_types={BATCH_DIALOGUES: "object"},
        output_aliases={
            BATCH_DIALOGUES: (
                *DIALOGUE_CURRENT_ALIASES,
                "batchDialogues",
                "dialogue_content",
                "batch_dialogues_raw",
                "batch_dialogues",
            )
        },
        fastgpt_responsibility="根据审核意见修订当前批次角色对白 JSON。",
        local_responsibility="保留当前批次边界，只在 passed=true 后才允许提交到 all_dialogues。",
        expected_output_kind="dialogues_batch_json",
        workflow_json_name="角色对话修订.json",
    ),
    STAGE_SCRIPT: FastGPTStageContract(
        stage_name=STAGE_SCRIPT,
        label="剧本正文批处理",
        input_names=(
            WORLDVIEW,
            CHARACTERS,
            SCENES,
            ALL_HOOKS,
            ALL_DIALOGUES,
            EPISODE_PLAN,
            APPEARANCE_MAPPING,
            TOTAL_EPISODES,
            EPISODE_WORD_COUNT,
            LAST_SUMMARY,
            BATCH_START_EPISODE,
            ALL_SCRIPT,
        ),
        output_types={BATCH_SCRIPT: "string"},
        fastgpt_responsibility="生成当前批次 5 集剧本正文。",
        local_responsibility="划分批次、裁剪 episode_plan、拼接 all_script、推进批次。",
    ),
    STAGE_SCRIPT_WRITING: FastGPTStageContract(
        stage_name=STAGE_SCRIPT_WRITING,
        label="剧本正文编写",
        input_names=(
            WORLDVIEW,
            CHARACTERS,
            SCENES,
            ALL_HOOKS,
            ALL_DIALOGUES,
            EPISODE_PLAN,
            APPEARANCE_MAPPING,
            TOTAL_EPISODES,
            EPISODE_WORD_COUNT,
            LAST_SUMMARY,
            BATCH_START_EPISODE,
            ALL_SCRIPT,
        ),
        output_types={BATCH_SCRIPT: "string"},
        output_aliases={BATCH_SCRIPT: SCRIPT_CURRENT_ALIASES},
        fastgpt_responsibility="编写当前批次 5 集剧本正文。",
        local_responsibility="只缓存当前批次临时正文，正式合并到 all_script 前仍需本地审核通过。",
        expected_output_kind="script_text",
        workflow_json_name="剧本正文编写.json",
    ),
    STAGE_SCRIPT_REVIEW: FastGPTStageContract(
        stage_name=STAGE_SCRIPT_REVIEW,
        label="剧本正文审核",
        input_names=(
            WORLDVIEW,
            CHARACTERS,
            SCENES,
            ALL_HOOKS,
            ALL_DIALOGUES,
            EPISODE_PLAN,
            APPEARANCE_MAPPING,
            TOTAL_EPISODES,
            EPISODE_WORD_COUNT,
            LAST_SUMMARY,
            BATCH_START_EPISODE,
            BATCH_SCRIPT,
        ),
        output_types={
            REVIEW_PASSED: "boolean",
            REWRITE_REQUIRED: "boolean",
            BLOCKING_ISSUES: "array",
        },
        output_aliases={
            REVIEW_PASSED: (*SCRIPT_REVIEW_ALIASES, "approved"),
            REWRITE_REQUIRED: SCRIPT_REVIEW_ALIASES,
            BLOCKING_ISSUES: SCRIPT_REVIEW_ALIASES,
        },
        fastgpt_responsibility="审核当前批次剧本正文是否可提交。",
        local_responsibility="把审核结果转成 passed/rewrite_required/blocking_issues，并决定是否进入修订。",
        expected_output_kind="review_json",
        workflow_json_name="剧本正文审核.json",
    ),
    STAGE_SCRIPT_REWRITE: FastGPTStageContract(
        stage_name=STAGE_SCRIPT_REWRITE,
        label="剧本正文修订",
        input_names=(
            WORLDVIEW,
            CHARACTERS,
            SCENES,
            ALL_HOOKS,
            ALL_DIALOGUES,
            EPISODE_PLAN,
            APPEARANCE_MAPPING,
            TOTAL_EPISODES,
            EPISODE_WORD_COUNT,
            LAST_SUMMARY,
            BATCH_START_EPISODE,
            BATCH_SCRIPT,
            PASS_REVIEW_JSON,
        ),
        output_types={BATCH_SCRIPT: "string"},
        output_aliases={BATCH_SCRIPT: SCRIPT_CURRENT_ALIASES},
        fastgpt_responsibility="根据审核意见修订当前批次剧本正文。",
        local_responsibility="保留当前批次边界，只在 passed=true 后才允许提交到 all_script。",
        expected_output_kind="script_text",
        workflow_json_name="剧本正文修订.json",
    ),
    STAGE_MEMORY: FastGPTStageContract(
        stage_name=STAGE_MEMORY,
        label="正文记忆整理",
        input_names=(
            BATCH_SCRIPT,
            LAST_SUMMARY,
            APPEARANCE_MAPPING,
            CHARACTER_ALIAS_NAMING_RULES,
        ),
        output_types={LAST_SUMMARY: "string"},
        fastgpt_responsibility="把当前批次正文整理成下一批可用的摘要。",
        local_responsibility="用新 last_summary 覆盖旧 last_summary，不保存历史。",
        workflow_json_name="当前五集剧本正文摘要.json",
    ),
    STAGE_SCRIPT_MEMORY: FastGPTStageContract(
        stage_name=STAGE_SCRIPT_MEMORY,
        label="正文批次记忆整理",
        input_names=(
            BATCH_SCRIPT,
            LAST_SUMMARY,
            APPEARANCE_MAPPING,
            CHARACTER_ALIAS_NAMING_RULES,
        ),
        output_types={LAST_SUMMARY: "string"},
        output_aliases={LAST_SUMMARY: SCRIPT_MEMORY_ALIASES},
        fastgpt_responsibility="把当前批次正文整理成下一批可用的摘要。",
        local_responsibility="用新 last_summary 覆盖旧 last_summary，不保存历史。",
        expected_output_kind="script_memory_json",
        workflow_json_name="当前五集剧本正文摘要.json",
    ),
    STAGE_FINAL: FastGPTStageContract(
        stage_name=STAGE_FINAL,
        label="最终剧本拼接",
        input_names=(
            script_title_content,
            TOTAL_EPISODES,
            STORY_OUTLINE,
            CHARACTERS,
            SCENES,
            ALL_SCRIPT,
        ),
        output_types={FINAL_SCRIPT: "string"},
        fastgpt_responsibility="输出最终完整剧本。",
        local_responsibility="调用最终拼接工作流，并以最终回复文本作为 final_script。",
        workflow_json_name="完整剧本拼接.json",
    ),
}


def _clone_stage_contract(
    source_stage_name: str,
    target_stage_name: str,
    label: str,
) -> FastGPTStageContract:
    source = STAGE_CONTRACTS[source_stage_name]
    return FastGPTStageContract(
        stage_name=target_stage_name,
        label=label,
        input_names=source.input_names,
        output_types=source.output_types,
        output_aliases=source.output_aliases,
        fastgpt_responsibility=source.fastgpt_responsibility,
        local_responsibility=source.local_responsibility,
        expected_output_kind=source.expected_output_kind,
        workflow_json_name=source.workflow_json_name,
    )


STAGE_CONTRACTS[STAGE_HOOK_WRITE] = _clone_stage_contract(
    STAGE_HOOKS_WRITING,
    STAGE_HOOK_WRITE,
    "开头冲突钩子编写",
)
STAGE_CONTRACTS[STAGE_HOOK_REVIEW] = _clone_stage_contract(
    STAGE_HOOKS_REVIEW,
    STAGE_HOOK_REVIEW,
    "开头冲突钩子审核",
)
STAGE_CONTRACTS[STAGE_HOOK_REVISE] = _clone_stage_contract(
    STAGE_HOOKS_REWRITE,
    STAGE_HOOK_REVISE,
    "开头冲突钩子修订",
)
STAGE_CONTRACTS[STAGE_HOOK_MEMORY] = FastGPTStageContract(
    stage_name=STAGE_HOOK_MEMORY,
    label="开头冲突钩子记忆",
    input_names=(
        BATCH_HOOKS,
        HOOK_MEMORY,
        APPEARANCE_MAPPING,
        TOTAL_EPISODES,
        BATCH_START_EPISODE,
        EPISODE_PLAN,
    ),
    output_types={HOOK_MEMORY: "string"},
    output_aliases={HOOK_MEMORY: HOOK_MEMORY_ALIASES},
    fastgpt_responsibility="基于当前批次钩子和已有钩子记忆生成下一批可承接的钩子记忆。",
    local_responsibility="用新的 hook_memory 覆盖旧钩子记忆，不合并到 all_hooks。",
    expected_output_kind="hook_memory_json",
    workflow_json_name="开头冲突钩子记忆存储.json",
)

STAGE_CONTRACTS[STAGE_DIALOGUE_WRITE] = _clone_stage_contract(
    STAGE_DIALOGUES_WRITING,
    STAGE_DIALOGUE_WRITE,
    "角色对白编写",
)
STAGE_CONTRACTS[STAGE_DIALOGUE_REVIEW] = _clone_stage_contract(
    STAGE_DIALOGUES_REVIEW,
    STAGE_DIALOGUE_REVIEW,
    "角色对白审核",
)
STAGE_CONTRACTS[STAGE_DIALOGUE_REVISE] = _clone_stage_contract(
    STAGE_DIALOGUES_REWRITE,
    STAGE_DIALOGUE_REVISE,
    "角色对白修订",
)
STAGE_CONTRACTS[STAGE_DIALOGUE_MEMORY] = FastGPTStageContract(
    stage_name=STAGE_DIALOGUE_MEMORY,
    label="角色对白记忆",
    input_names=(
        BATCH_DIALOGUES,
        DIALOGUE_MEMORY,
        ALL_HOOKS,
        EPISODE_PLAN,
        APPEARANCE_MAPPING,
        TOTAL_EPISODES,
        BATCH_START_EPISODE,
        CHARACTER_ALIAS_NAMING_RULES,
    ),
    output_types={DIALOGUE_MEMORY: "string"},
    output_aliases={DIALOGUE_MEMORY: DIALOGUE_MEMORY_ALIASES},
    fastgpt_responsibility="基于当前批次对白、钩子和已有对白记忆生成下一批可承接的对白记忆。",
    local_responsibility="用新的 dialogue_memory 覆盖旧对白记忆，不合并到 all_dialogues。",
    expected_output_kind="dialogue_memory_json",
    workflow_json_name="角色对话记忆存储.json",
)

STAGE_CONTRACTS[STAGE_SCRIPT_WRITE] = _clone_stage_contract(
    STAGE_SCRIPT_WRITING,
    STAGE_SCRIPT_WRITE,
    "剧本正文编写",
)
STAGE_CONTRACTS[STAGE_SCRIPT_REVISE] = _clone_stage_contract(
    STAGE_SCRIPT_REWRITE,
    STAGE_SCRIPT_REVISE,
    "剧本正文修订",
)


def _validate_framework_web_input_alignment() -> None:
    """防止 framework 契约与网页端 3 输入再次漂移。"""
    framework_contract = STAGE_CONTRACTS[STAGE_FRAMEWORK]
    expected_inputs = set(FRAMEWORK_WEB_INPUT_NAMES)

    if tuple(framework_contract.input_names) != FRAMEWORK_WEB_INPUT_NAMES:
        raise RuntimeError(
            "framework 输入契约已偏离网页端："
            f"当前为 {framework_contract.input_names!r}，"
            f"预期为 {FRAMEWORK_WEB_INPUT_NAMES!r}"
        )

    legacy_inputs = LEGACY_INPUT_ALIASES.get(STAGE_FRAMEWORK, {})
    legacy_keys = set(legacy_inputs.keys())
    if legacy_keys != expected_inputs:
        raise RuntimeError(
            "framework legacy 输入映射已偏离网页端："
            f"当前为 {sorted(legacy_keys)!r}，"
            f"预期为 {sorted(expected_inputs)!r}"
        )


_validate_framework_web_input_alignment()


def contract_for(stage_name: str) -> FastGPTStageContract:
    try:
        return STAGE_CONTRACTS[stage_name]
    except KeyError as exc:
        raise ValueError(f"未知 FastGPT 阶段：{stage_name}") from exc


def coerce_strict_fastgpt_boolean(value: Any) -> bool:
    """只接受 true / false 语义本体，不接受“通过/一致/带解释句子”的宽松猜测。"""
    if isinstance(value, bool):
        return value

    if isinstance(value, dict):
        for key in ("is_consistent", "passed", "approved", "consistent"):
            if key in value:
                return coerce_strict_fastgpt_boolean(value[key])

    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)

    text = str(value or "").strip()
    try:
        parsed = parse_json(text)
        if parsed is not value:
            return coerce_strict_fastgpt_boolean(parsed)
    except Exception:
        pass

    compact = "".join(text.lower().split())
    if compact == "true":
        return True
    if compact == "false":
        return False
    raise ValueError(f"必须精确返回 true 或 false，实际得到：{value!r}")


def coerce_fastgpt_value(value: Any, type_name: str) -> Any:
    if type_name == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)

        if isinstance(value, dict):
            for key in ("is_consistent", "passed", "approved", "consistent"):
                if key in value:
                    return coerce_fastgpt_value(value[key], "boolean")

        text = str(value or "").strip()
        try:
            parsed = parse_json(text)
            if parsed is not value:
                return coerce_fastgpt_value(parsed, "boolean")
        except Exception:
            pass

        lowered = text.lower()
        compact = "".join(lowered.split())
        if compact in {"true", "truetrue", "yes", "y", "1", "是", "通过", "一致"}:
            return True
        if compact in {"false", "falsefalse", "no", "n", "0", "否", "不通过", "不一致"}:
            return False

        negative_tokens = (
            "false",
            "不一致",
            "不通过",
            "未通过",
            "否",
            "不符合",
            "不匹配",
            "inconsistent",
            "not consistent",
            "failed",
        )
        positive_tokens = (
            "true",
            "一致",
            "通过",
            "符合",
            "匹配",
            "consistent",
            "passed",
        )
        has_negative = any(token in lowered for token in negative_tokens)
        has_positive = any(token in lowered for token in positive_tokens)
        if has_negative and not has_positive:
            return False
        if has_positive and not has_negative:
            return True
        if has_negative and has_positive:
            first_negative = min(lowered.find(token) for token in negative_tokens if token in lowered)
            first_positive = min(lowered.find(token) for token in positive_tokens if token in lowered)
            return first_positive < first_negative
        raise ValueError(f"无法转换为 boolean：{value!r}")

    if type_name == "number":
        return int(value)

    if type_name == "string":
        if isinstance(value, (dict, list)):
            raise ValueError("string 类型不接受 object/array")
        text = "" if value is None else str(value).strip()
        if not text:
            raise ValueError("FastGPT 输出 string 不能为空")
        return text

    if type_name == "object":
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = parse_json(value)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        raise ValueError(f"无法转换为 object：{value!r}")

    if type_name == "array":
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = parse_json(value)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        raise ValueError(f"无法转换为 array：{value!r}")

    raise ValueError(f"不支持的 FastGPT 类型：{type_name}")


def _is_empty_string_output(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def to_jsonable_value(value: Any) -> Any:
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
