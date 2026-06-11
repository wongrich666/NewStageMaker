from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..workflow_ids import (
    APPEARANCE_ALIAS_MAPPING_VAR,
    APPEARANCE_MAPPING_VAR,
    CHARACTER_VAR,
    SCENE_VAR,
    WORLDVIEW_VAR,
)
from .json_utils import parse_json, strip_code_fence

STAGE_WORLDVIEW = "worldview"
STAGE_CHARACTERS = "characters"
STAGE_SCENES = "scenes"
STAGE_APPEARANCE_ALIAS_GENERATION = "appearance_alias_generation"
STAGE_APPEARANCE_ALIAS_WRITING = "appearance_alias_writing"
STAGE_APPEARANCE_ALIAS_REWRITE = "appearance_alias_rewrite"
WORLDVIEW_FIELD = "worldview"
CHARACTERS_FIELD = "characters"
SCENES_FIELD = "scenes"
APPEARANCE_MAPPING_FIELD = "appearanceMapping"
APPEARANCE_MAPPING_FIELD_NAMES = {APPEARANCE_MAPPING_FIELD, "appearanceMapping"}
WORLDVIEW_REQUIRED_STRING_FIELDS = (
    "worldview_summary",
    "era_background",
    "social_rules",
    "space_logic",
)
WORLDVIEW_REQUIRED_LIST_FIELDS = (
    "key_settings",
    "conflict_mechanisms",
    "visual_keywords",
)
CHARACTER_MIN_REQUIRED_FIELDS = (
    "character_name",
    "story_role",
    "core_motivation",
    "decision_logic",
    "speech_profile",
    "relation_modes",
    "actable_evidence",
    "dramatic_value",
)
SCENE_MIN_REQUIRED_FIELDS = (
    "scene_name",
    "scene_type",
    "story_function",
    "visual_condition_summary",
    "styling_condition_summary",
    "outfit_requirements",
    "naming_condition_summary",
    "alias_usage_rules",
    "conflict_potential",
    "worldview_support",
)
SCENE_REQUIRED_SCALAR_FIELDS = (
    "scene_name",
    "scene_type",
    "story_function",
    "scene_time_or_period",
    "weather_or_environment_state",
    "environment_description",
    "atmosphere_description",
    "visual_condition_summary",
    "styling_condition_summary",
    "naming_condition_summary",
    "character_interaction_effect",
    "worldview_support",
)
SCENE_REQUIRED_LIST_FIELDS = (
    "visual_elements",
    "identity_or_status_requirements",
    "conflict_potential",
)
SCENE_FORBIDDEN_SCENE_KEYS = {
    "message",
    "role",
    "content",
    "finish_reason",
    "index",
    "name",
    "function",
    "conflict_soil",
    "key_characters",
}
SCENE_FORBIDDEN_TEXT_MARKERS = (
    "我开始执行",
    "审核通过",
    "自然语言场景说明",
)
SCENE_PLACEHOLDER_REJECTION_THRESHOLD = 6
WORLDVIEW_WRAPPER_KEYS = (
    WORLDVIEW_FIELD,
    WORLDVIEW_VAR,
    "worldView",
    "worldviewContent",
    "worldview_content",
    "worldviewJson",
    "current_worldview",
    "世界观",
    "世界观内容",
    "最终世界观",
)
CHARACTER_WRAPPER_KEYS = (
    CHARACTERS_FIELD,
    CHARACTER_VAR,
    "character_setting",
    "characterSetting",
    "character_profile",
    "characterProfile",
    "人物设定",
    "人设",
    "人设内容",
    "结构化人设",
    "最终结构化人设",
)
SCENE_WRAPPER_KEYS = (
    SCENES_FIELD,
    SCENE_VAR,
    "scene_setting",
    "sceneSetting",
    "scene_content",
    "sceneContent",
    "场景内容",
    "场景设定",
    "场景JSON",
    "结构化场景",
    "最终结构化场景",
)
APPEARANCE_WRAPPER_KEYS = (
    APPEARANCE_MAPPING_FIELD,
    APPEARANCE_MAPPING_VAR,
    APPEARANCE_ALIAS_MAPPING_VAR,
    "appearanceMapping",
    "appearanceMapping_json",
    "appearanceMappingJson",
    "服装版本映射",
    "服装映射",
    "结构化服装映射",
    "最终结构化服装映射",
)
APPEARANCE_MAPPING_STAGE_NAMES = {
    STAGE_APPEARANCE_ALIAS_GENERATION,
    STAGE_APPEARANCE_ALIAS_WRITING,
    STAGE_APPEARANCE_ALIAS_REWRITE,
}
APPEARANCE_DEFAULT_FORBIDDEN_GENERIC_NAMES = ["男主", "女主", "反派", "配角"]

_NEW_ALIAS_NAME_RE = re.compile(
    r"^(?P<name>[^()（）【】\[\]\s]{1,40})\((?P<tag>[^()（）【】\[\]\s]{1,40})\)$"
)
_OLD_ALIAS_NAME_RE = re.compile(r"^(?P<name>[^【】()（）\[\]\s]{1,40})【(?P<tag>[^【】()（）\[\]\s]{1,40})】$")
_CN_PAREN_ALIAS_NAME_RE = re.compile(r"^(?P<name>[^【】()（）\[\]\s]{1,40})（(?P<tag>[^【】()（）\[\]\s]{1,40})）$")
_CANONICAL_ALIAS_NAME_RE = re.compile(r"^(?P<name>[^【】()（）\[\]\s]{1,40})【(?P<tag>[^【】()（）\[\]\s]{1,40})】$")

_GENERIC_ALIAS_NAMES = {"男主", "女主", "反派", "配角", "主角", "男二", "女二", "路人"}


def normalize_appearance_alias_name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    old_match = _OLD_ALIAS_NAME_RE.match(text)
    if old_match:
        return f"{old_match.group('name')}【{old_match.group('tag')}】"

    cn_paren_match = _CN_PAREN_ALIAS_NAME_RE.match(text)
    if cn_paren_match:
        return f"{cn_paren_match.group('name')}【{cn_paren_match.group('tag')}】"

    new_match = _NEW_ALIAS_NAME_RE.match(text)
    if new_match:
        return f"{new_match.group('name')}【{new_match.group('tag')}】"

    return text


def _is_valid_new_alias_name(value: object) -> bool:
    text = normalize_appearance_alias_name(value)
    match = _CANONICAL_ALIAS_NAME_RE.match(text)
    if not match:
        return False

    character_name = match.group("name").strip()
    if character_name in _GENERIC_ALIAS_NAMES:
        return False

    return True

APPEARANCE_TOP_LEVEL_ALIASES: dict[str, tuple[str, ...]] = {
    "mapping_principle": ("mapping_principle", "mappingPrinciple", "principle"),
    "global_naming_style": ("global_naming_style", "globalNamingStyle", "naming_style"),
    "characters": ("characters", "character_list", "characterList"),
    "episode_level_usage_plan": (
        "episode_level_usage_plan",
        "episodeLevelUsagePlan",
        "episode_usage_plan",
    ),
    "scene_level_usage_plan": (
        "scene_level_usage_plan",
        "sceneLevelUsagePlan",
        "scene_usage_plan",
    ),
    "special_naming_rules": (
        "special_naming_rules",
        "specialNamingRules",
        "naming_rules",
    ),
}
APPEARANCE_CHARACTER_ALIASES: dict[str, tuple[str, ...]] = {
    "character_id": ("character_id", "characterId"),
    "canonical_name": ("canonical_name", "canonicalName", "character_name", "characterName"),
    "story_role": ("story_role", "storyRole", "role", "role_type"),
    "same_person_anchor": ("same_person_anchor", "samePersonAnchor"),
    "default_name": ("default_name", "defaultName"),
    "forbidden_generic_names": (
        "forbidden_generic_names",
        "forbiddenGenericNames",
    ),
    "outfit_variants": ("outfit_variants", "outfitVariants", "variants"),
}
APPEARANCE_SAME_PERSON_ANCHOR_ALIASES: dict[str, tuple[str, ...]] = {
    "stable_appearance_traits": (
        "stable_appearance_traits",
        "stableAppearanceTraits",
    ),
    "stable_recognition_points": (
        "stable_recognition_points",
        "stableRecognitionPoints",
    ),
    "unchanged_core_impression": (
        "unchanged_core_impression",
        "unchangedCoreImpression",
    ),
}
APPEARANCE_VARIANT_ALIASES: dict[str, tuple[str, ...]] = {
    "variant_id": ("variant_id", "variantId"),
    "alias_name": ("alias_name", "aliasName"),
    "applicable_identity_state": (
        "applicable_identity_state",
        "applicableIdentityState",
    ),
    "outfit_type": ("outfit_type", "outfitType"),
    "outfit_description": ("outfit_description", "outfitDescription"),
    "visual_keypoints": ("visual_keypoints", "visualKeypoints"),
    "episode_range_hint": ("episode_range_hint", "episodeRangeHint"),
    "scene_trigger_rules": ("scene_trigger_rules", "sceneTriggerRules"),
    "usage_rule": ("usage_rule", "usageRule"),
    "must_use_when_triggered": (
        "must_use_when_triggered",
        "mustUseWhenTriggered",
    ),
    "fallback_allowed": ("fallback_allowed", "fallbackAllowed"),
    "same_person_confirmation": (
        "same_person_confirmation",
        "samePersonConfirmation",
    ),
}
APPEARANCE_SCENE_TRIGGER_RULE_ALIASES: dict[str, tuple[str, ...]] = {
    "scene_names": ("scene_names", "sceneNames"),
    "scene_types": ("scene_types", "sceneTypes"),
    "environment_or_time": ("environment_or_time", "environmentOrTime"),
    "status_conditions": ("status_conditions", "statusConditions"),
}
WORLDVIEW_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "worldview_summary": (
        "worldview_summary",
        "worldviewSummary",
        "world_summary",
        "summary",
        "世界观总述",
        "世界观概述",
        "世界观总结",
        "总体概述",
        "世界观总览",
    ),
    "era_background": (
        "era_background",
        "eraBackground",
        "era",
        "时代背景",
        "背景时代",
        "宏观背景",
    ),
    "social_rules": (
        "social_rules",
        "socialRules",
        "social_environment",
        "社会规则",
        "社会环境",
        "社会运行规则",
        "秩序规则",
    ),
    "space_logic": (
        "space_logic",
        "spaceLogic",
        "spatial_logic",
        "空间逻辑",
        "空间规则",
        "故事空间逻辑",
        "发生空间底层逻辑",
    ),
    "key_settings": (
        "key_settings",
        "keySettings",
        "key_setting",
        "关键设定",
        "关键设置",
        "关键世界设定",
        "人物命运相关设定",
    ),
    "conflict_mechanisms": (
        "conflict_mechanisms",
        "conflictMechanisms",
        "conflict_rules",
        "冲突机制",
        "冲突规则",
        "禁忌机制",
        "核心冲突机制",
    ),
    "visual_keywords": (
        "visual_keywords",
        "visualKeywords",
        "visual_tags",
        "visual_words",
        "视觉关键词",
        "氛围关键词",
        "视觉与氛围关键词",
        "视觉氛围",
    ),
}
CHARACTER_SETTING_ALIASES: dict[str, tuple[str, ...]] = {
    "character_design_principle": (
        "character_design_principle",
        "characterDesignPrinciple",
        "design_principle",
        "角色设计原则",
        "人设设计原则",
    ),
    "core_relation_logic": (
        "core_relation_logic",
        "coreRelationLogic",
        "relation_logic",
        "核心关系逻辑",
    ),
    "search_strategy_summary": (
        "search_strategy_summary",
        "searchStrategySummary",
        "search_summary",
        "search_strategy",
        "联网参考策略",
        "检索策略摘要",
    ),
    "characters": (
        "characters",
        "角色列表",
        "人物列表",
    ),
}
CHARACTER_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "character_name": ("character_name", "characterName", "name", "角色名", "姓名", "名字"),
    "story_role": ("story_role", "storyRole", "role", "role_type", "角色定位", "人物定位", "剧情定位"),
    "core_motivation": (
        "core_motivation",
        "coreMotivation",
        "motivation",
        "deep_motivation",
        "core_desire",
        "核心动机",
        "深层动机",
        "核心欲望",
    ),
    "external_goal": ("external_goal", "externalGoal", "goal", "外在目标"),
    "inner_need": ("inner_need", "innerNeed", "need", "内在需求"),
    "deep_fear": ("deep_fear", "deepFear", "fear", "深层恐惧"),
    "self_deception": ("self_deception", "selfDeception", "自我欺骗"),
    "personality": ("personality", "性格"),
    "family": ("family", "家庭", "家庭背景"),
    "appearance": ("appearance", "外貌"),
    "behavior": ("behavior", "行为"),
    "dimension_relations": ("dimension_relations", "dimensionRelations", "维度关系"),
    "decision_logic": ("decision_logic", "decisionLogic", "决策逻辑", "行为逻辑"),
    "speech_profile": ("speech_profile", "speechProfile", "说话方式", "语言风格", "对白风格"),
    "relation_modes": ("relation_modes", "relationModes", "relationships", "关系模式", "关系反应"),
    "actable_evidence": ("actable_evidence", "actableEvidence", "performance_evidence", "可演证据", "表演证据"),
    "dramatic_function": ("dramatic_function", "dramaticFunction", "戏剧功能"),
    "search_reference_usage": ("search_reference_usage", "searchReferenceUsage", "检索参考使用"),
    "dramatic_value": ("dramatic_value", "dramaticValue", "戏剧价值", "剧情价值", "主线作用"),
}
SCENE_SETTING_ALIASES: dict[str, tuple[str, ...]] = {
    "scene_design_principle": (
        "scene_design_principle",
        "sceneDesignPrinciple",
        "design_principle",
        "场景设计原则",
    ),
    "scene_visual_styling_naming_strategy": (
        "scene_visual_styling_naming_strategy",
        "sceneVisualStylingNamingStrategy",
        "visual_styling_naming_strategy",
        "场景视觉造型命名策略",
        "视觉造型命名策略",
    ),
    "scenes": (
        "scenes",
        "scene_list",
        "sceneList",
        "场景列表",
        "核心场景列表",
    ),
}
SCENE_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "scene_name": ("scene_name", "sceneName", "场景名", "场景名称"),
    "scene_type": ("scene_type", "sceneType", "type", "场景类型"),
    "story_function": ("story_function", "storyFunction", "剧情功能", "场景功能"),
    "scene_time_or_period": ("scene_time_or_period", "sceneTimeOrPeriod", "time", "时间", "时间段"),
    "weather_or_environment_state": (
        "weather_or_environment_state",
        "weatherOrEnvironmentState",
        "environment_state",
        "天气或环境状态",
        "天气环境状态",
    ),
    "environment_description": (
        "environment_description",
        "environmentDescription",
        "environment",
        "环境描述",
    ),
    "atmosphere_description": (
        "atmosphere_description",
        "atmosphereDescription",
        "atmosphere",
        "氛围描述",
    ),
    "visual_elements": ("visual_elements", "visualElements", "视觉元素"),
    "visual_condition_summary": (
        "visual_condition_summary",
        "visualConditionSummary",
        "visual_summary",
        "视觉条件总结",
    ),
    "identity_or_status_requirements": (
        "identity_or_status_requirements",
        "identityOrStatusRequirements",
        "identity_requirements",
        "身份状态要求",
    ),
    "styling_condition_summary": (
        "styling_condition_summary",
        "stylingConditionSummary",
        "styling_summary",
        "造型条件总结",
    ),
    "outfit_requirements": (
        "outfit_requirements",
        "outfitRequirements",
        "服装要求",
        "造型要求",
    ),
    "naming_condition_summary": (
        "naming_condition_summary",
        "namingConditionSummary",
        "naming_summary",
        "命名条件总结",
    ),
    "alias_usage_rules": (
        "alias_usage_rules",
        "aliasUsageRules",
        "alias_rules",
        "别名使用规则",
    ),
    "conflict_potential": (
        "conflict_potential",
        "conflictPotential",
        "conflicts",
        "冲突潜力",
    ),
    "character_interaction_effect": (
        "character_interaction_effect",
        "characterInteractionEffect",
        "interaction_effect",
        "人物互动影响",
    ),
    "worldview_support": (
        "worldview_support",
        "worldviewSupport",
        "世界观支撑",
    ),
}


@dataclass(slots=True)
class StageRepairOutcome:
    payload: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    alias_hits: dict[str, str] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    used_fallback: bool = False
    requires_local_restart: bool = False
    mode: str = "local_repair"


def is_repairable_stage_output(stage_name: str) -> bool:
    return stage_name in {
        STAGE_WORLDVIEW,
        STAGE_CHARACTERS,
        STAGE_SCENES,
        *APPEARANCE_MAPPING_STAGE_NAMES,
    }


def repair_stage_output_candidate(
    stage_name: str,
    candidate: Any,
    *,
    source: str,
    input_variables: dict[str, Any],
    attempt_index: int = 0,
    allow_textual_relaxation: bool = True,
) -> StageRepairOutcome | None:
    relaxed = attempt_index > 0
    if stage_name == STAGE_WORLDVIEW:
        return _repair_worldview_candidate(
            candidate,
            source=source,
            input_variables=input_variables,
            relaxed=relaxed,
            allow_textual_relaxation=allow_textual_relaxation,
        )
    if stage_name == STAGE_CHARACTERS:
        return _repair_characters_candidate(
            candidate,
            source=source,
            input_variables=input_variables,
            relaxed=relaxed,
            allow_textual_relaxation=allow_textual_relaxation,
        )
    if stage_name == STAGE_SCENES:
        return _repair_scenes_candidate(
            candidate,
            source=source,
            input_variables=input_variables,
            relaxed=relaxed,
            allow_textual_relaxation=allow_textual_relaxation,
        )
    if stage_name in APPEARANCE_MAPPING_STAGE_NAMES:
        return _repair_appearanceMapping_candidate(
            candidate,
            source=source,
            input_variables=input_variables,
            relaxed=relaxed,
        )
    return None


def build_stage_output_fallback(
    stage_name: str,
    *,
    source: str,
    input_variables: dict[str, Any],
    failure_reason: str,
) -> StageRepairOutcome | None:
    warnings = [f"原始输出不可用，已启用 schema-valid fallback：{failure_reason[:180]}"]
    if stage_name == STAGE_WORLDVIEW:
        body = _build_worldview_fallback_body(input_variables, warnings)
        return StageRepairOutcome(
            payload={WORLDVIEW_FIELD: json.dumps(body, ensure_ascii=False, indent=2)},
            warnings=warnings,
            used_fallback=True,
            requires_local_restart=False,
            mode=f"{source}_fallback",
        )
    if stage_name == STAGE_CHARACTERS:
        body = _build_characters_fallback_body(input_variables, warnings)
        return StageRepairOutcome(
            payload={CHARACTERS_FIELD: json.dumps(body, ensure_ascii=False, indent=2)},
            warnings=warnings,
            used_fallback=True,
            requires_local_restart=False,
            mode=f"{source}_fallback",
        )
    return None


def describe_repairable_stage_output_issue(
    stage_name: str,
    field_name: str,
    value: Any,
) -> str | None:
    if stage_name == STAGE_WORLDVIEW and field_name == WORLDVIEW_FIELD:
        return _describe_worldview_output_issue(value)
    if stage_name == STAGE_CHARACTERS and field_name == CHARACTERS_FIELD:
        return _describe_characters_output_issue(value)
    if stage_name == STAGE_SCENES and field_name == SCENES_FIELD:
        return _describe_scenes_output_issue(value)
    if stage_name in APPEARANCE_MAPPING_STAGE_NAMES and field_name in APPEARANCE_MAPPING_FIELD_NAMES:
        return describe_appearanceMapping_output_issue(value)
    return None


def normalize_appearanceMapping_candidate(value: Any) -> dict[str, Any] | None:

    # framework_manual_unwrap_appearanceMapping
    # 兼容 09 框架转剧本工作流：answerText 返回 { "appearanceMapping": {...} } 的情况。
    if isinstance(value, dict):
        _wrapped_appearanceMapping = (
            value.get("appearanceMapping")
            or value.get("appearanceMapping")
            or value.get("appearanceMappingResult")
            or value.get("appearanceMapping_result")
        )
        if isinstance(_wrapped_appearanceMapping, dict):
            value = _wrapped_appearanceMapping
    body = _normalize_appearanceMapping_body(value)
    if not isinstance(body, dict):
        return None
    return {APPEARANCE_MAPPING_FIELD: body}


def describe_appearanceMapping_output_issue(value: Any) -> str | None:
    issues = _validate_appearanceMapping_contract_shape(value)
    return issues[0] if issues else None


def validate_appearanceMapping_output(value: Any) -> list[str]:
    repaired_value = _appearanceMapping_object(value)
    issues = _validate_appearanceMapping_contract_shape(
        repaired_value if repaired_value is not None else value
    )
    if issues:
        return issues
    return _validate_appearanceMapping_local_review(
        repaired_value if repaired_value is not None else value
    )


def _repair_appearanceMapping_candidate(
    candidate: Any,
    *,
    source: str,
    input_variables: dict[str, Any],
    relaxed: bool,
) -> StageRepairOutcome | None:
    del input_variables
    warnings: list[str] = []
    alias_hits: dict[str, str] = {}
    body = _search_stage_body(
        candidate,
        wrapper_keys=APPEARANCE_WRAPPER_KEYS,
        detector=_looks_like_appearanceMapping_body,
        audit_detector=_looks_like_appearanceMapping_review_json,
        relaxed=relaxed,
    )
    if body is None:
        return None

    normalized_body = _normalize_appearanceMapping_body(
        body,
        warnings=warnings,
        alias_hits=alias_hits,
    )
    if normalized_body is None:
        return None

    return StageRepairOutcome(
        payload={APPEARANCE_MAPPING_FIELD: normalized_body},
        warnings=warnings,
        alias_hits=alias_hits,
        used_fallback=False,
        requires_local_restart=False,
        mode="local_repair",
    )


def _repair_worldview_candidate(
    candidate: Any,
    *,
    source: str,
    input_variables: dict[str, Any],
    relaxed: bool,
    allow_textual_relaxation: bool,
) -> StageRepairOutcome | None:
    warnings: list[str] = []
    alias_hits: dict[str, str] = {}
    missing_fields: list[str] = []
    requires_local_restart = False
    body = _search_stage_body(
        candidate,
        wrapper_keys=WORLDVIEW_WRAPPER_KEYS,
        detector=_looks_like_worldview_body,
        audit_detector=_looks_like_worldview_review_json,
        relaxed=relaxed,
    )
    if body is None and relaxed and allow_textual_relaxation:
        text = _extract_text_candidate(candidate)
        if text and not _looks_like_worldview_review_json(_try_parse_json_value(text)):
            warnings.append(f"来源 {source} 不是合法 JSON，已退化为自然语言世界观摘要修复。")
            body = {"worldview_summary": text}
            requires_local_restart = True
    if body is None:
        return None

    canonical = _canonicalize_worldview_body(
        body,
        input_variables=input_variables,
        warnings=warnings,
        alias_hits=alias_hits,
        missing_fields=missing_fields,
        relaxed=relaxed,
    )
    if canonical is None:
        return None
    return StageRepairOutcome(
        payload={WORLDVIEW_FIELD: json.dumps(canonical, ensure_ascii=False, indent=2)},
        warnings=warnings,
        alias_hits=alias_hits,
        missing_fields=missing_fields,
        requires_local_restart=requires_local_restart,
    )


def _repair_characters_candidate(
    candidate: Any,
    *,
    source: str,
    input_variables: dict[str, Any],
    relaxed: bool,
    allow_textual_relaxation: bool,
) -> StageRepairOutcome | None:
    warnings: list[str] = []
    alias_hits: dict[str, str] = {}
    missing_fields: list[str] = []
    requires_local_restart = False
    body = _search_stage_body(
        candidate,
        wrapper_keys=CHARACTER_WRAPPER_KEYS,
        detector=_looks_like_character_body,
        audit_detector=_looks_like_characters_review_json,
        relaxed=relaxed,
    )
    if body is None and relaxed and allow_textual_relaxation:
        text = _extract_text_candidate(candidate)
        if text and not _looks_like_characters_review_json(_try_parse_json_value(text)):
            warnings.append(f"来源 {source} 是自然语言人物内容，已转为最小结构化人设。")
            body = text
            requires_local_restart = True
    if body is None:
        return None

    canonical = _canonicalize_characters_body(
        body,
        input_variables=input_variables,
        warnings=warnings,
        alias_hits=alias_hits,
        missing_fields=missing_fields,
        relaxed=relaxed,
    )
    if canonical is None:
        return None
    return StageRepairOutcome(
        payload={CHARACTERS_FIELD: json.dumps(canonical, ensure_ascii=False, indent=2)},
        warnings=warnings,
        alias_hits=alias_hits,
        missing_fields=missing_fields,
        requires_local_restart=requires_local_restart,
    )


def _repair_scenes_candidate(
    candidate: Any,
    *,
    source: str,
    input_variables: dict[str, Any],
    relaxed: bool,
    allow_textual_relaxation: bool,
) -> StageRepairOutcome | None:
    del allow_textual_relaxation
    warnings: list[str] = []
    alias_hits: dict[str, str] = {}
    missing_fields: list[str] = []
    body = _search_stage_body(
        candidate,
        wrapper_keys=SCENE_WRAPPER_KEYS,
        detector=_looks_like_scenes_body,
        audit_detector=_looks_like_scenes_review_json,
        relaxed=relaxed,
        blocked_nested_keys={"message", "content"},
    )
    if body is None:
        return None

    canonical = _canonicalize_scenes_body(
        body,
        input_variables=input_variables,
        warnings=warnings,
        alias_hits=alias_hits,
        missing_fields=missing_fields,
        relaxed=relaxed,
    )
    if canonical is None:
        return None
    return StageRepairOutcome(
        payload={SCENES_FIELD: json.dumps(canonical, ensure_ascii=False, indent=2)},
        warnings=warnings,
        alias_hits=alias_hits,
        missing_fields=missing_fields,
        requires_local_restart=False,
    )


def _search_stage_body(
    candidate: Any,
    *,
    wrapper_keys: tuple[str, ...],
    detector,
    audit_detector,
    relaxed: bool,
    blocked_nested_keys: set[str] | None = None,
    depth: int = 0,
) -> Any | None:
    if depth > 6:
        return None
    current = _deep_normalize_candidate(candidate)
    if current is None:
        return None
    if audit_detector(current):
        return None
    if detector(current):
        return current

    if isinstance(current, dict):
        for key in wrapper_keys:
            if key not in current:
                continue
            if blocked_nested_keys and str(key).lower() in blocked_nested_keys:
                continue
            found = _search_stage_body(
                current.get(key),
                wrapper_keys=wrapper_keys,
                detector=detector,
                audit_detector=audit_detector,
                relaxed=relaxed,
                blocked_nested_keys=blocked_nested_keys,
                depth=depth + 1,
            )
            if found is not None:
                return found
        if len(current) == 1:
            only_key, only_value = next(iter(current.items()))
            if blocked_nested_keys and str(only_key).lower() in blocked_nested_keys:
                return None
            found = _search_stage_body(
                only_value,
                wrapper_keys=wrapper_keys,
                detector=detector,
                audit_detector=audit_detector,
                relaxed=relaxed,
                blocked_nested_keys=blocked_nested_keys,
                depth=depth + 1,
            )
            if found is not None:
                return found
        if relaxed:
            for nested_key, nested in current.items():
                if blocked_nested_keys and str(nested_key).lower() in blocked_nested_keys:
                    continue
                found = _search_stage_body(
                    nested,
                    wrapper_keys=wrapper_keys,
                    detector=detector,
                    audit_detector=audit_detector,
                    relaxed=False,
                    blocked_nested_keys=blocked_nested_keys,
                    depth=depth + 1,
                )
                if found is not None:
                    return found

    if isinstance(current, list):
        for item in current:
            found = _search_stage_body(
                item,
                wrapper_keys=wrapper_keys,
                detector=detector,
                audit_detector=audit_detector,
                relaxed=relaxed,
                blocked_nested_keys=blocked_nested_keys,
                depth=depth + 1,
            )
            if found is not None:
                return found
    return None


def _canonicalize_worldview_body(
    body: Any,
    *,
    input_variables: dict[str, Any],
    warnings: list[str],
    alias_hits: dict[str, str],
    missing_fields: list[str],
    relaxed: bool,
) -> dict[str, Any] | None:
    if not isinstance(body, dict):
        return None
    lowered = _lowered_key_map(body)
    payload: dict[str, Any] = {}
    missing: list[str] = []
    for field_name in (*WORLDVIEW_REQUIRED_STRING_FIELDS, *WORLDVIEW_REQUIRED_LIST_FIELDS):
        actual_key = _match_alias_key(body, lowered, WORLDVIEW_FIELD_ALIASES[field_name])
        if actual_key is None:
            missing.append(field_name)
            continue
        if actual_key != field_name:
            alias_hits[field_name] = actual_key
        raw_value = body.get(actual_key)
        if field_name in WORLDVIEW_REQUIRED_STRING_FIELDS:
            payload[field_name] = _normalize_text_value(raw_value)
        else:
            payload[field_name] = _normalize_string_list(raw_value)

    if missing and not relaxed:
        return None
    missing_fields.extend(missing)

    for field_name in WORLDVIEW_REQUIRED_STRING_FIELDS:
        if not str(payload.get(field_name) or "").strip():
            if not relaxed:
                return None
            payload[field_name] = _worldview_placeholder(field_name, input_variables)
            missing_fields.append(field_name)
            warnings.append(f"worldview 缺少字段 {field_name}，已补降级占位。")

    for field_name in WORLDVIEW_REQUIRED_LIST_FIELDS:
        values = payload.get(field_name)
        if not isinstance(values, list) or not values:
            if not relaxed:
                return None
            payload[field_name] = _worldview_list_placeholder(field_name, input_variables)
            missing_fields.append(field_name)
            warnings.append(f"worldview 缺少数组字段 {field_name}，已补降级数组。")
            continue
        if len(values) < 3 and relaxed:
            values.extend(_worldview_list_placeholder(field_name, input_variables))
            payload[field_name] = _dedupe_strings(values)[:3]
            missing_fields.append(field_name)
            warnings.append(f"worldview 数组字段 {field_name} 条目不足，已补足到 3 条。")

    return payload if _describe_worldview_body_issue(payload) is None else None


def _canonicalize_characters_body(
    body: Any,
    *,
    input_variables: dict[str, Any],
    warnings: list[str],
    alias_hits: dict[str, str],
    missing_fields: list[str],
    relaxed: bool,
) -> dict[str, Any] | None:
    normalized = _deep_normalize_candidate(body)
    setting: dict[str, Any]
    if isinstance(normalized, dict) and isinstance(normalized.get("character_setting"), dict):
        setting = dict(normalized["character_setting"])
    elif isinstance(normalized, dict) and _looks_like_character_setting_dict(normalized):
        setting = dict(normalized)
    elif isinstance(normalized, dict) and isinstance(normalized.get("characters"), list):
        setting = {"characters": normalized.get("characters")}
    elif isinstance(normalized, list):
        setting = {"characters": normalized}
    elif isinstance(normalized, str) and relaxed:
        # 这类自然语言小传常常没有显式写出“角色名：xxx”，
        # 优先借用 framework 的 user_characters，避免人设阶段退化成匿名“主角/配角”。
        seeds = _character_seeds_from_text(normalized) or _character_seeds_from_input(
            input_variables.get("user_characters")
        )
        missing_fields.append("character_setting.characters")
        if not seeds:
            seeds = _fallback_character_seeds(input_variables)
        setting = {"characters": seeds}
    else:
        return None

    lowered = _lowered_key_map(setting)
    canonical_setting: dict[str, Any] = {}
    for field_name, aliases in CHARACTER_SETTING_ALIASES.items():
        actual_key = _match_alias_key(setting, lowered, aliases)
        if actual_key is None:
            missing_fields.append(f"character_setting.{field_name}")
            continue
        if actual_key != field_name:
            alias_hits[f"character_setting.{field_name}"] = actual_key
        canonical_setting[field_name] = setting.get(actual_key)

    seeds = _normalize_character_seed_list(
        canonical_setting.get("characters"),
        input_variables=input_variables,
        relaxed=relaxed,
    )
    if not seeds and not relaxed:
        return None
    if not seeds:
        warnings.append("characters 未能从模型输出提取角色列表，已根据输入生成 fallback 角色。")
        missing_fields.append("character_setting.characters")
        seeds = _fallback_character_seeds(input_variables)

    canonical_setting["character_design_principle"] = _normalize_text_value(
        canonical_setting.get("character_design_principle")
    ) or "待补全：基于故事大纲和人物小传补充角色设计原则"
    canonical_setting["core_relation_logic"] = _normalize_text_value(
        canonical_setting.get("core_relation_logic")
    ) or "待补全：基于主线关系冲突补充核心关系逻辑"
    canonical_setting["search_strategy_summary"] = _normalize_text_value(
        canonical_setting.get("search_strategy_summary")
    ) or "未提供联网参考，本轮仅基于世界观、故事大纲和人物小传生成"
    canonical_setting["characters"] = [
        _normalize_character_item(
            seed,
            input_variables=input_variables,
            index=index,
            warnings=warnings,
            alias_hits=alias_hits,
            missing_fields=missing_fields,
            relaxed=relaxed,
        )
        for index, seed in enumerate(seeds, start=1)
    ]
    payload = {"character_setting": canonical_setting}
    return payload if _describe_characters_body_issue(payload) is None else None


def _canonicalize_scenes_body(
    body: Any,
    *,
    input_variables: dict[str, Any],
    warnings: list[str],
    alias_hits: dict[str, str],
    missing_fields: list[str],
    relaxed: bool,
) -> dict[str, Any] | None:
    normalized = _deep_normalize_candidate(body)
    setting: dict[str, Any]
    if isinstance(normalized, dict) and isinstance(normalized.get("scenes"), dict) and isinstance(
        normalized["scenes"].get("scene_setting"),
        dict,
    ):
        setting = dict(normalized["scenes"]["scene_setting"])
    elif isinstance(normalized, dict) and isinstance(normalized.get("scene_setting"), dict):
        setting = dict(normalized["scene_setting"])
    elif isinstance(normalized, dict) and _looks_like_scene_setting_dict(normalized):
        setting = dict(normalized)
    elif isinstance(normalized, dict) and isinstance(normalized.get("scenes"), list):
        setting = dict(normalized)
    elif isinstance(normalized, list):
        setting = {"scenes": normalized}
    else:
        return None
    initial_issue = _scene_payload_pollution_issue(setting)
    if initial_issue is not None:
        return None

    lowered = _lowered_key_map(setting)
    canonical_setting: dict[str, Any] = {}
    for field_name, aliases in SCENE_SETTING_ALIASES.items():
        actual_key = _match_alias_key(setting, lowered, aliases)
        if actual_key is None:
            missing_fields.append(f"scene_setting.{field_name}")
            continue
        if actual_key != field_name:
            alias_hits[f"scene_setting.{field_name}"] = actual_key
        canonical_setting[field_name] = setting.get(actual_key)

    scenes = _normalize_scene_seed_list(
        canonical_setting.get("scenes"),
    )
    if not scenes:
        return None
    for seed in scenes:
        issue = _scene_payload_pollution_issue(seed)
        if issue is not None:
            return None

    normalized_scenes = [
        _normalize_scene_item(
            seed,
            input_variables=input_variables,
            index=index,
            warnings=warnings,
            alias_hits=alias_hits,
            missing_fields=missing_fields,
            relaxed=relaxed,
        )
        for index, seed in enumerate(scenes, start=1)
        if isinstance(_deep_normalize_candidate(seed), dict)
    ]
    normalized_scenes = [item for item in normalized_scenes if item]
    if len(normalized_scenes) < 3 and not relaxed:
        return None
    if len(normalized_scenes) < 3:
        return None

    canonical_setting["scene_design_principle"] = _normalize_text_value(
        canonical_setting.get("scene_design_principle")
    ) or _scene_setting_placeholder("scene_design_principle", input_variables)
    canonical_setting["scene_visual_styling_naming_strategy"] = _normalize_text_value(
        canonical_setting.get("scene_visual_styling_naming_strategy")
    ) or _scene_setting_placeholder("scene_visual_styling_naming_strategy", input_variables)
    canonical_setting["scenes"] = normalized_scenes
    payload = {"scene_setting": canonical_setting}
    return payload if _describe_scenes_body_issue(payload) is None else None


def _normalize_scene_seed_list(
    value: Any,
) -> list[Any]:
    normalized = _deep_normalize_candidate(value)
    if isinstance(normalized, list):
        return normalized
    if isinstance(normalized, dict):
        if isinstance(normalized.get("scenes"), list):
            return list(normalized.get("scenes") or [])
        if _looks_like_single_scene_dict(normalized):
            return [normalized]
    return []


def _normalize_character_seed_list(
    value: Any,
    *,
    input_variables: dict[str, Any],
    relaxed: bool,
) -> list[Any]:
    normalized = _deep_normalize_candidate(value)
    if isinstance(normalized, list):
        return normalized
    if isinstance(normalized, dict):
        if isinstance(normalized.get("characters"), list):
            return list(normalized.get("characters") or [])
        if _looks_like_single_character_dict(normalized):
            return [normalized]
    if isinstance(normalized, str) and relaxed:
        return _character_seeds_from_text(normalized) or _fallback_character_seeds(input_variables)
    return []


def _normalize_character_item(
    seed: Any,
    *,
    input_variables: dict[str, Any],
    index: int,
    warnings: list[str],
    alias_hits: dict[str, str],
    missing_fields: list[str],
    relaxed: bool,
) -> dict[str, Any]:
    raw = _deep_normalize_candidate(seed)
    if isinstance(raw, str):
        names = _character_names_from_text(raw)
        raw = {"character_name": names[0]} if names else {}
    if not isinstance(raw, dict):
        raw = {}

    lowered = _lowered_key_map(raw)
    name = _extract_character_field(raw, lowered, "character_name", alias_hits)
    role = _extract_character_field(raw, lowered, "story_role", alias_hits)
    motivation = _extract_character_field(raw, lowered, "core_motivation", alias_hits)
    if not name:
        missing_fields.append(f"character_setting.characters[{index}].character_name")
    if not role:
        missing_fields.append(f"character_setting.characters[{index}].story_role")
    if not motivation:
        missing_fields.append(f"character_setting.characters[{index}].core_motivation")
    name = name or _fallback_character_name(input_variables, index)
    role = role or "待补全：补充人物定位"
    motivation = motivation or "待补全：补充核心动机"

    personality_text = _extract_character_field(raw, lowered, "personality", alias_hits)
    if isinstance(personality_text, dict):
        personality_text = json.dumps(personality_text, ensure_ascii=False)
    relationship_hint = _extract_any_text(
        raw,
        (
            "relationship_to_protagonist",
            "relationships_with_others",
            "relationship",
        ),
    )
    appearance_hint = _extract_any_text(raw, ("appearance_anchor", "appearance", "overall_look", "identity"))
    growth_hint = _extract_any_text(raw, ("growth_arc", "dramatic_value", "plot_function"))
    weakness_hint = _extract_any_text(raw, ("weaknesses", "deep_fear"))
    strengths_hint = _extract_any_text(raw, ("strengths", "core_desire", "external_goal"))
    if _extract_character_raw(raw, lowered, "decision_logic") in (None, "", [], {}):
        missing_fields.append(f"character_setting.characters[{index}].decision_logic")
    if _extract_character_raw(raw, lowered, "speech_profile") in (None, "", [], {}):
        missing_fields.append(f"character_setting.characters[{index}].speech_profile")
    if _extract_character_raw(raw, lowered, "relation_modes") in (None, "", [], {}):
        missing_fields.append(f"character_setting.characters[{index}].relation_modes")
    if _extract_character_raw(raw, lowered, "actable_evidence") in (None, "", [], {}):
        missing_fields.append(f"character_setting.characters[{index}].actable_evidence")
    if not _extract_character_field(raw, lowered, "dramatic_value", alias_hits):
        missing_fields.append(f"character_setting.characters[{index}].dramatic_value")

    return {
        "character_name": name,
        "story_role": role,
        "core_motivation": motivation,
        "external_goal": _extract_character_field(raw, lowered, "external_goal", alias_hits)
        or strengths_hint
        or f"待补全：明确{name}的外在目标",
        "inner_need": _extract_character_field(raw, lowered, "inner_need", alias_hits)
        or growth_hint
        or f"待补全：明确{name}的内在需求",
        "deep_fear": _extract_character_field(raw, lowered, "deep_fear", alias_hits)
        or weakness_hint
        or f"待补全：明确{name}的深层恐惧",
        "self_deception": _extract_character_field(raw, lowered, "self_deception", alias_hits)
        or f"待补全：补充{name}的自我欺骗",
        "personality": _normalize_character_personality(name, raw.get("personality"), personality_text),
        "family": _normalize_character_family(name, raw.get("family"), raw),
        "appearance": _normalize_character_appearance(name, raw.get("appearance"), appearance_hint),
        "behavior": _normalize_character_behavior(name, raw.get("behavior"), personality_text),
        "dimension_relations": _normalize_character_dimension_relations(name, raw.get("dimension_relations")),
        "decision_logic": _normalize_character_decision_logic(
            name,
            _extract_character_raw(raw, lowered, "decision_logic"),
            weaknesses=weakness_hint,
        ),
        "speech_profile": _normalize_character_speech_profile(
            name,
            _extract_character_raw(raw, lowered, "speech_profile"),
            personality_text=personality_text,
        ),
        "relation_modes": _normalize_character_relation_modes(
            name,
            _extract_character_raw(raw, lowered, "relation_modes"),
            relationship_hint=relationship_hint,
        ),
        "actable_evidence": _normalize_character_actable_evidence(
            name,
            _extract_character_raw(raw, lowered, "actable_evidence"),
            appearance_hint=appearance_hint,
            strengths_hint=strengths_hint,
        ),
        "dramatic_function": _normalize_character_dramatic_function(
            name,
            _extract_character_raw(raw, lowered, "dramatic_function"),
            role=role,
            growth_hint=growth_hint,
        ),
        "search_reference_usage": _normalize_search_reference_usage(
            _extract_character_raw(raw, lowered, "search_reference_usage")
        ),
        "dramatic_value": _extract_character_field(raw, lowered, "dramatic_value", alias_hits)
        or growth_hint
        or f"待补全：说明{name}对主线的戏剧价值",
    }


def _normalize_character_personality(
    name: str,
    value: Any,
    personality_text: str,
) -> dict[str, Any]:
    raw = _coerce_nested_dict(value)
    traits = _normalize_string_list(raw.get("traits") if raw else personality_text)[:2]
    if len(traits) < 2:
        traits.extend([f"{name}的外显特质", f"{name}的隐藏特质"])
        traits = _dedupe_strings(traits)[:2]
    return {
        "traits": traits,
        "surface_impression": _normalize_text_value(raw.get("surface_impression") if raw else personality_text)
        or f"待补全：补充{name}的表层印象",
        "inner_contradiction": _normalize_text_value(raw.get("inner_contradiction") if raw else "")
        or f"待补全：补充{name}的内在矛盾",
    }


def _normalize_character_family(name: str, value: Any, raw: dict[str, Any]) -> dict[str, Any]:
    family = _coerce_nested_dict(value)
    family_background = _normalize_text_value(family.get("family_background") if family else "")
    upbringing = _normalize_text_value(family.get("upbringing") if family else "")
    influence = _normalize_text_value(family.get("key_family_influence") if family else "")
    identity = _extract_any_text(raw, ("identity",))
    return {
        "family_background": family_background or identity or f"待补全：补充{name}的家庭背景",
        "upbringing": upbringing or f"待补全：补充{name}的成长经历",
        "key_family_influence": influence or f"待补全：补充{name}受到的关键家庭影响",
    }


def _normalize_character_appearance(name: str, value: Any, appearance_hint: str) -> dict[str, Any]:
    appearance = _coerce_nested_dict(value)
    recognizable = _normalize_string_list(appearance.get("recognizable_features") if appearance else appearance_hint)
    if not recognizable:
        recognizable = [f"{name}的稳定外貌锚点"]
    return {
        "overall_look": _normalize_text_value(appearance.get("overall_look") if appearance else appearance_hint)
        or f"待补全：补充{name}的整体外貌",
        "recognizable_features": recognizable[:2],
        "external_impression_effect": _normalize_text_value(
            appearance.get("external_impression_effect") if appearance else ""
        )
        or f"待补全：补充{name}给外界的第一印象",
    }


def _normalize_character_behavior(name: str, value: Any, personality_text: str) -> dict[str, Any]:
    behavior = _coerce_nested_dict(value)
    actions = _normalize_string_list(behavior.get("habitual_actions") if behavior else personality_text)
    if len(actions) < 2:
        actions.extend([f"{name}下意识会做的动作", f"{name}在压力下会暴露的行为"])
        actions = _dedupe_strings(actions)[:2]
    return {
        "habitual_actions": actions,
        "emotional_response_pattern": _normalize_text_value(
            behavior.get("emotional_response_pattern") if behavior else ""
        )
        or f"待补全：补充{name}的情绪反应模式",
        "social_interaction_style": _normalize_text_value(
            behavior.get("social_interaction_style") if behavior else personality_text
        )
        or f"待补全：补充{name}的社交互动方式",
    }


def _normalize_character_dimension_relations(name: str, value: Any) -> dict[str, Any]:
    relations = _coerce_nested_dict(value)
    return {
        "family_to_personality": _normalize_text_value(relations.get("family_to_personality") if relations else "")
        or f"待补全：家庭如何塑造{name}的性格",
        "personality_to_behavior": _normalize_text_value(relations.get("personality_to_behavior") if relations else "")
        or f"待补全：性格如何驱动{name}的行为",
        "appearance_to_social_effect": _normalize_text_value(
            relations.get("appearance_to_social_effect") if relations else ""
        )
        or f"待补全：外貌如何影响{name}的社会反馈",
        "behavior_to_character_reveal": _normalize_text_value(
            relations.get("behavior_to_character_reveal") if relations else ""
        )
        or f"待补全：行为如何揭示{name}的真实状态",
    }


def _normalize_character_decision_logic(
    name: str,
    value: Any,
    *,
    weaknesses: str,
) -> dict[str, Any]:
    raw = _coerce_nested_dict(value)
    base = _normalize_text_value(value) if isinstance(value, str) else ""
    return {
        "when_under_pressure": _normalize_text_value(raw.get("when_under_pressure") if raw else base)
        or f"待补全：{name}在压力下如何决策",
        "when_facing_authority": _normalize_text_value(raw.get("when_facing_authority") if raw else "")
        or f"待补全：{name}面对权威时的反应",
        "when_facing_desire": _normalize_text_value(raw.get("when_facing_desire") if raw else "")
        or f"待补全：{name}面对欲望时的取舍",
        "when_losing_control": _normalize_text_value(raw.get("when_losing_control") if raw else weaknesses)
        or f"待补全：{name}失控时的行为逻辑",
        "moral_bottom_line": _normalize_text_value(raw.get("moral_bottom_line") if raw else "")
        or f"待补全：{name}的道德底线",
        "self_justification": _normalize_text_value(raw.get("self_justification") if raw else "")
        or f"待补全：{name}如何为自己的选择辩解",
    }


def _normalize_character_speech_profile(
    name: str,
    value: Any,
    *,
    personality_text: str,
) -> dict[str, Any]:
    raw = _coerce_nested_dict(value)
    keywords = _normalize_string_list(raw.get("keyword_habits") if raw else personality_text)
    if not keywords:
        keywords = [f"{name}的口头习惯"]
    return {
        "baseline_register": _normalize_text_value(raw.get("baseline_register") if raw else personality_text)
        or f"待补全：{name}的基础语体",
        "sentence_rhythm": _normalize_text_value(raw.get("sentence_rhythm") if raw else "")
        or f"待补全：{name}的句式节奏",
        "keyword_habits": keywords[:2],
        "conflict_style": _normalize_text_value(raw.get("conflict_style") if raw else "")
        or f"待补全：{name}发生冲突时的表达方式",
        "intimacy_style": _normalize_text_value(raw.get("intimacy_style") if raw else "")
        or f"待补全：{name}亲密场景下的表达方式",
        "command_style": _normalize_text_value(raw.get("command_style") if raw else "")
        or f"待补全：{name}发号施令时的表达方式",
        "humor_style": _normalize_text_value(raw.get("humor_style") if raw else "")
        or f"待补全：{name}的幽默方式",
        "when_angry": _normalize_text_value(raw.get("when_angry") if raw else "")
        or f"待补全：{name}愤怒时的说话方式",
        "when_hiding_truth": _normalize_text_value(raw.get("when_hiding_truth") if raw else "")
        or f"待补全：{name}隐瞒真相时的说话方式",
    }


def _normalize_character_relation_modes(
    name: str,
    value: Any,
    *,
    relationship_hint: str,
) -> list[dict[str, Any]]:
    raw = _deep_normalize_candidate(value)
    items: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "target": _extract_any_text(item, ("target", "name", "对象")) or "关键关系对象",
                    "relation_type": _extract_any_text(item, ("relation_type", "type", "关系类型")) or "待补全",
                    "what_this_character_wants": _extract_any_text(item, ("what_this_character_wants", "wants"))
                    or f"待补全：{name}想从这段关系中得到什么",
                    "what_this_character_fears": _extract_any_text(item, ("what_this_character_fears", "fears"))
                    or f"待补全：{name}害怕在这段关系里失去什么",
                    "default_posture": _extract_any_text(item, ("default_posture", "posture"))
                    or f"待补全：{name}在这段关系中的默认姿态",
                    "speech_difference": _extract_any_text(item, ("speech_difference", "speech"))
                    or f"待补全：{name}面对该对象时的说话差异",
                    "conflict_trigger": _extract_any_text(item, ("conflict_trigger", "trigger"))
                    or f"待补全：{name}在这段关系中的冲突触发点",
                }
            )
    if items:
        return items
    target = "主角" if "主角" not in name else "关键对手"
    return [
        {
            "target": target,
            "relation_type": relationship_hint or "待补全：补充关系类型",
            "what_this_character_wants": f"待补全：{name}希望通过这段关系得到什么",
            "what_this_character_fears": f"待补全：{name}在这段关系中最怕失去什么",
            "default_posture": f"待补全：{name}面对{target}时的默认姿态",
            "speech_difference": f"待补全：{name}面对{target}时的说话差异",
            "conflict_trigger": f"待补全：{name}与{target}爆发冲突的触发点",
        }
    ]


def _normalize_character_actable_evidence(
    name: str,
    value: Any,
    *,
    appearance_hint: str,
    strengths_hint: str,
) -> dict[str, Any]:
    raw = _coerce_nested_dict(value)
    signature_actions = _normalize_string_list(raw.get("signature_actions") if raw else strengths_hint)
    if len(signature_actions) < 2:
        signature_actions.extend([f"{name}的代表性动作", f"{name}在关键场面会暴露的动作"])
        signature_actions = _dedupe_strings(signature_actions)[:2]
    micro_reactions = _normalize_string_list(raw.get("micro_reactions") if raw else "")
    if not micro_reactions:
        micro_reactions = [f"{name}下意识的细微反应"]
    props = _normalize_string_list(raw.get("props_or_style_clues") if raw else appearance_hint)
    if not props:
        props = [f"{name}的外在识别线索"]
    first_show = _normalize_string_list(raw.get("first_appearance_must_show") if raw else "")
    if not first_show:
        first_show = [f"待补全：{name}首次出场必须被镜头拍到的细节"]
    return {
        "signature_actions": signature_actions,
        "micro_reactions": micro_reactions[:2],
        "props_or_style_clues": props[:2],
        "first_appearance_must_show": first_show[:2],
    }


def _normalize_character_dramatic_function(
    name: str,
    value: Any,
    *,
    role: str,
    growth_hint: str,
) -> dict[str, Any]:
    raw = _coerce_nested_dict(value)
    return {
        "best_conflict_type": _normalize_text_value(raw.get("best_conflict_type") if raw else role)
        or f"待补全：{name}最适合承载哪类冲突",
        "easiest_wrong_choice": _normalize_text_value(raw.get("easiest_wrong_choice") if raw else "")
        or f"待补全：{name}最容易做出的错误选择",
        "turning_point": _normalize_text_value(raw.get("turning_point") if raw else growth_hint)
        or f"待补全：{name}的关键转折点",
        "scene_value": _normalize_text_value(raw.get("scene_value") if raw else "")
        or f"待补全：{name}在场景中的戏剧价值",
    }


def _normalize_search_reference_usage(value: Any) -> dict[str, Any]:
    raw = _coerce_nested_dict(value)
    borrowed = _normalize_string_list(raw.get("borrowed_domains") if raw else "")
    absorbed = _normalize_string_list(raw.get("absorbed_patterns") if raw else "")
    forbidden = _normalize_string_list(raw.get("forbidden_copying") if raw else "")
    return {
        "borrowed_domains": borrowed or ["未提供联网参考"],
        "absorbed_patterns": absorbed or ["未提供联网参考"],
        "forbidden_copying": forbidden or ["未照搬真实人物经历或原句"],
    }


def _build_worldview_fallback_body(
    input_variables: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    payload = {
        field_name: _worldview_placeholder(field_name, input_variables)
        for field_name in WORLDVIEW_REQUIRED_STRING_FIELDS
    }
    for field_name in WORLDVIEW_REQUIRED_LIST_FIELDS:
        payload[field_name] = _worldview_list_placeholder(field_name, input_variables)
    warnings.append("worldview 已生成最小可消费 JSON fallback。")
    return payload


def _build_characters_fallback_body(
    input_variables: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    warnings.append("characters 已生成最小可消费 JSON fallback。")
    return _canonicalize_characters_body(
        {"characters": _fallback_character_seeds(input_variables)},
        input_variables=input_variables,
        warnings=warnings,
        alias_hits={},
        missing_fields=[],
        relaxed=True,
    ) or {
        "character_setting": {
            "character_design_principle": "待补全：基于故事大纲和人物小传补充角色设计原则",
            "core_relation_logic": "待补全：基于世界观和主线补充核心关系逻辑",
            "search_strategy_summary": "未提供联网参考，本轮仅基于世界观、故事大纲和人物小传生成",
            "characters": [
                _normalize_character_item(
                    {"character_name": "主角", "story_role": "主角", "core_motivation": "待补全"},
                    input_variables=input_variables,
                    index=1,
                    warnings=warnings,
                    alias_hits={},
                    missing_fields=[],
                    relaxed=True,
                )
            ],
        }
    }


def _worldview_placeholder(field_name: str, input_variables: dict[str, Any]) -> str:
    scenes = _jsonish_dict(input_variables.get("user_scenes"))
    story_outline = _jsonish_dict(input_variables.get("story_outline"))
    if field_name == "worldview_summary":
        theme = _normalize_text_value(story_outline.get("theme"))
        opening = _normalize_text_value(story_outline.get("opening"))
        if theme or opening:
            return f"待补全：围绕{theme or '主线主题'}与{opening or '主角处境'}补充世界观总述"
        return "待补全：基于故事大纲和核心场景补充世界观总述"
    if field_name == "era_background":
        era = _normalize_text_value(scenes.get("era_background"))
        return era or "待补全：基于故事大纲和核心场景补充时代背景"
    if field_name == "social_rules":
        rules = _normalize_text_value(scenes.get("rules"))
        return rules or "待补全：基于故事大纲和核心场景补充社会规则"
    if field_name == "space_logic":
        world_state = _normalize_text_value(scenes.get("world_state"))
        return world_state or "待补全：基于核心场景补充空间逻辑"
    return f"待补全：补充 {field_name}"


def _worldview_list_placeholder(field_name: str, input_variables: dict[str, Any]) -> list[str]:
    def _complete(items: list[str], defaults: list[str]) -> list[str]:
        merged = _dedupe_strings(items)
        if len(merged) < 3:
            merged.extend(defaults)
        return _dedupe_strings(merged)[:3]

    scenes = _jsonish_dict(input_variables.get("user_scenes"))
    story_outline = _jsonish_dict(input_variables.get("story_outline"))
    core_locations = scenes.get("core_locations") if isinstance(scenes.get("core_locations"), list) else []
    location_names = [
        _normalize_text_value(item.get("name"))
        for item in core_locations
        if isinstance(item, dict) and _normalize_text_value(item.get("name"))
    ]
    if field_name == "key_settings":
        items = [
            f"待补全：支撑核心场景“{name}”成立的关键设定"
            for name in location_names[:3]
        ]
        return _complete(
            items,
            [
                "待补全：补充与主角命运相关的关键设定",
                "待补全：补充支撑核心场景成立的关键设定",
                "待补全：补充推动分集计划发展的关键设定",
            ],
        )
    if field_name == "conflict_mechanisms":
        hints = _normalize_string_list(
            [
                scenes.get("danger_sources"),
                scenes.get("resource_or_stakes"),
                scenes.get("power_distribution"),
                story_outline.get("middle_escalation"),
            ]
        )
        items = [f"待补全：围绕“{hint}”补充冲突机制" for hint in hints[:3]]
        return _complete(
            items,
            [
                "待补全：补充主线冲突的触发机制",
                "待补全：补充角色关系升级的约束机制",
                "待补充分集计划中的风险升级机制",
            ],
        )
    if field_name == "visual_keywords":
        hints = _normalize_string_list(
            [
                scenes.get("overall_atmosphere"),
                scenes.get("special_rules"),
                *location_names[:2],
            ]
        )
        items = [f"待补全：提炼“{hint}”对应的视觉关键词" for hint in hints[:3]]
        return _complete(
            items,
            [
                "待补全：补充整体氛围关键词",
                "待补全：补充空间视觉关键词",
                "待补全：补充冲突场景视觉关键词",
            ],
        )
    return [f"待补全：补充 {field_name} {index}" for index in range(1, 4)]


def _fallback_character_seeds(input_variables: dict[str, Any]) -> list[dict[str, Any]]:
    seeds = _character_seeds_from_input(input_variables.get("user_characters"))
    if seeds:
        return seeds
    return [
        {
            "character_name": "主角",
            "story_role": "主角",
            "core_motivation": "待补全：补充主角核心动机",
        }
    ]


def _character_seeds_from_input(value: Any) -> list[dict[str, Any]]:
    normalized = _deep_normalize_candidate(value)
    if isinstance(normalized, list):
        seeds = []
        for item in normalized:
            if isinstance(item, dict):
                seeds.append(item)
            elif isinstance(item, str) and item.strip():
                names = _character_names_from_text(item)
                if names:
                    seeds.append({"character_name": names[0], "story_role": "待补全", "core_motivation": "待补全"})
        return seeds
    if isinstance(normalized, dict):
        if isinstance(normalized.get("characters"), list):
            return [item for item in normalized.get("characters") or [] if isinstance(item, dict)]
        if _looks_like_single_character_dict(normalized):
            return [normalized]
    if isinstance(normalized, str):
        return [
            {"character_name": name, "story_role": "待补全", "core_motivation": "待补全"}
            for name in _character_names_from_text(normalized)
        ]
    return []


def _character_seeds_from_text(text: str) -> list[dict[str, Any]]:
    names = _character_names_from_text(text)
    return [
        {"character_name": name, "story_role": "待补全：补充人物定位", "core_motivation": "待补全：补充核心动机"}
        for name in names
    ]


def _character_names_from_text(text: str) -> list[str]:
    cleaned = strip_code_fence(text)
    names: list[str] = []
    patterns = (
        r"【[^】]{0,12}】\s*([\u4e00-\u9fa5A-Za-z0-9·]{2,16})",
        r"(?:角色名|姓名|名字|角色)\s*[：:]\s*([\u4e00-\u9fa5A-Za-z0-9·]{2,16})",
    )
    for pattern in patterns:
        for match in re.findall(pattern, cleaned):
            if match not in names:
                names.append(match)
    if names:
        return names[:8]
    for line in cleaned.splitlines():
        line = line.strip("-* \t")
        if not line:
            continue
        if len(line) <= 16 and re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9·]{2,16}", line):
            if line not in names:
                names.append(line)
    return names[:8]


def _fallback_character_name(input_variables: dict[str, Any], index: int) -> str:
    seeds = _character_seeds_from_input(input_variables.get("user_characters"))
    if 0 < index <= len(seeds):
        candidate = _extract_any_text(seeds[index - 1], ("character_name", "name"))
        if candidate:
            return candidate
    return "主角" if index == 1 else f"角色{index}"


def _normalize_scene_item(
    seed: Any,
    *,
    input_variables: dict[str, Any],
    index: int,
    warnings: list[str],
    alias_hits: dict[str, str],
    missing_fields: list[str],
    relaxed: bool,
) -> dict[str, Any]:
    raw = _deep_normalize_candidate(seed)
    if not isinstance(raw, dict):
        return {}

    lowered = _lowered_key_map(raw)
    scene_name = _extract_scene_field(raw, lowered, "scene_name", alias_hits)
    scene_type = _extract_scene_field(raw, lowered, "scene_type", alias_hits)
    story_function = _extract_scene_field(raw, lowered, "story_function", alias_hits)
    scene_missing = False

    for field_name in SCENE_MIN_REQUIRED_FIELDS:
        if _extract_scene_raw(raw, lowered, field_name) in (None, "", [], {}):
            missing_fields.append(f"scene_setting.scenes[{index}].{field_name}")
            scene_missing = True
    if scene_missing and not relaxed:
        return {}

    location_seed = _scene_location_seed(input_variables, index)
    scene_name = scene_name or (
        _normalize_text_value(location_seed.get("name")) if relaxed else ""
    ) or f"待补全场景{index}"
    scene_type = scene_type or "待补全：补充场景类型"
    story_function = (
        story_function
        or (_normalize_text_value(location_seed.get("function")) if relaxed else "")
        or "待补全：补充场景功能"
    )

    canonical: dict[str, Any] = {
        "scene_name": scene_name,
        "scene_type": scene_type,
        "story_function": story_function,
        "scene_time_or_period": _extract_scene_field(raw, lowered, "scene_time_or_period", alias_hits)
        or f"待补全：补充{scene_name}的时间或时段",
        "weather_or_environment_state": _extract_scene_field(
            raw,
            lowered,
            "weather_or_environment_state",
            alias_hits,
        )
        or f"待补全：补充{scene_name}的天气或环境状态",
        "environment_description": _extract_scene_field(raw, lowered, "environment_description", alias_hits)
        or f"待补全：补充{scene_name}的环境描述",
        "atmosphere_description": _extract_scene_field(raw, lowered, "atmosphere_description", alias_hits)
        or _normalize_text_value(_jsonish_dict(input_variables.get("user_scenes")).get("overall_atmosphere"))
        or f"待补全：补充{scene_name}的氛围描述",
        "visual_elements": _normalize_scene_string_list(
            _extract_scene_raw(raw, lowered, "visual_elements"),
            fallback_label=f"{scene_name}的视觉元素",
            minimum=2,
        ),
        "visual_condition_summary": _extract_scene_field(raw, lowered, "visual_condition_summary", alias_hits)
        or f"待补全：补充{scene_name}的视觉条件总结",
        "identity_or_status_requirements": _normalize_scene_string_list(
            _extract_scene_raw(raw, lowered, "identity_or_status_requirements"),
            fallback_label=f"{scene_name}的人物身份状态要求",
            minimum=1,
        ),
        "styling_condition_summary": _extract_scene_field(raw, lowered, "styling_condition_summary", alias_hits)
        or f"待补全：补充{scene_name}的造型条件总结",
        "outfit_requirements": _normalize_scene_outfit_requirements(
            _extract_scene_raw(raw, lowered, "outfit_requirements"),
            input_variables=input_variables,
            scene_name=scene_name,
        ),
        "naming_condition_summary": _extract_scene_field(raw, lowered, "naming_condition_summary", alias_hits)
        or f"待补全：补充{scene_name}的命名条件总结",
        "alias_usage_rules": _normalize_scene_alias_usage_rules(
            _extract_scene_raw(raw, lowered, "alias_usage_rules"),
            input_variables=input_variables,
            scene_name=scene_name,
        ),
        "conflict_potential": _normalize_scene_string_list(
            _extract_scene_raw(raw, lowered, "conflict_potential"),
            fallback_label=_normalize_text_value(location_seed.get("conflict_soil")) or f"{scene_name}的冲突潜力",
            minimum=1,
        ),
        "character_interaction_effect": _extract_scene_field(
            raw,
            lowered,
            "character_interaction_effect",
            alias_hits,
        ) or f"待补全：补充{scene_name}对人物互动方式的影响",
        "worldview_support": _extract_scene_field(raw, lowered, "worldview_support", alias_hits)
        or f"待补全：说明{scene_name}如何支撑世界观",
    }

    for key, value in raw.items():
        if key in canonical or value in (None, "", [], {}):
            continue
        canonical[str(key)] = value

    if scene_missing:
        warnings.append(f"scenes 第 {index} 个场景存在字段缺失，已按本地契约补齐。")
    return canonical


def _extract_scene_field(
    raw: dict[str, Any],
    lowered: dict[str, str],
    field_name: str,
    alias_hits: dict[str, str],
) -> str:
    actual_key = _match_alias_key(raw, lowered, SCENE_FIELD_ALIASES[field_name])
    if actual_key is None:
        return ""
    if actual_key != field_name:
        alias_hits[f"scenes.{field_name}"] = actual_key
    return _normalize_text_value(raw.get(actual_key))


def _extract_scene_raw(
    raw: dict[str, Any],
    lowered: dict[str, str],
    field_name: str,
) -> Any:
    actual_key = _match_alias_key(raw, lowered, SCENE_FIELD_ALIASES[field_name])
    return raw.get(actual_key) if actual_key is not None else None


def _normalize_scene_string_list(
    value: Any,
    *,
    fallback_label: str,
    minimum: int,
) -> list[str]:
    items = _normalize_string_list(value)
    while len(items) < minimum:
        items.append(f"待补全：补充{fallback_label}")
    return _dedupe_strings(items)[: max(minimum, len(items))]


def _normalize_scene_outfit_requirements(
    value: Any,
    *,
    input_variables: dict[str, Any],
    scene_name: str,
) -> list[dict[str, Any]]:
    normalized = _deep_normalize_candidate(value)
    items = normalized if isinstance(normalized, list) else []
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            canonical_name = _extract_any_text(item, ("canonical_name", "character_name", "name")) or "待补全角色"
            recommended_alias_name = _extract_any_text(
                item,
                ("recommended_alias_name", "alias_name"),
            ) or f"{canonical_name}（{scene_name}）"
            result.append(
                {
                    "character_id": _extract_any_text(item, ("character_id",)) or canonical_name,
                    "canonical_name": canonical_name,
                    "recommended_alias_name": recommended_alias_name,
                    "identity_or_status": _extract_any_text(item, ("identity_or_status", "identity"))
                    or "待补全：补充身份状态",
                    "outfit_requirement": _extract_any_text(item, ("outfit_requirement", "requirement"))
                    or "待补全：补充服装要求",
                    "visual_focus": _extract_any_text(item, ("visual_focus", "focus"))
                    or "待补全：补充视觉重点",
                    "must_use_alias_when_triggered": bool(item.get("must_use_alias_when_triggered", False)),
                    "trigger_reason": _extract_any_text(item, ("trigger_reason", "reason"))
                    or "待补全：补充触发原因",
                    "forbidden_fallback_names": _normalize_string_list(item.get("forbidden_fallback_names"))
                    or ["男主", "女主", "反派", "配角"],
                }
            )
            continue
        text = _normalize_text_value(item)
        if not text:
            continue
        seed = _scene_character_seed(input_variables, 1)
        canonical_name = seed.get("character_name") or "待补全角色"
        result.append(
            {
                "character_id": canonical_name,
                "canonical_name": canonical_name,
                "recommended_alias_name": f"{canonical_name}（{scene_name}）",
                "identity_or_status": "待补全：补充身份状态",
                "outfit_requirement": text,
                "visual_focus": f"待补全：补充{canonical_name}在{scene_name}的视觉重点",
                "must_use_alias_when_triggered": False,
                "trigger_reason": f"待补全：补充{canonical_name}在{scene_name}的服装触发原因",
                "forbidden_fallback_names": ["男主", "女主", "反派", "配角"],
            }
        )
    if result:
        return result

    seed = _scene_character_seed(input_variables, 1)
    canonical_name = seed.get("character_name") or "待补全角色"
    return [
        {
            "character_id": canonical_name,
            "canonical_name": canonical_name,
            "recommended_alias_name": f"{canonical_name}（{scene_name}）",
            "identity_or_status": "待补全：补充身份状态",
            "outfit_requirement": f"待补全：补充{canonical_name}在{scene_name}的服装要求",
            "visual_focus": f"待补全：补充{canonical_name}在{scene_name}的视觉重点",
            "must_use_alias_when_triggered": False,
            "trigger_reason": f"待补全：补充{canonical_name}在{scene_name}的触发原因",
            "forbidden_fallback_names": ["男主", "女主", "反派", "配角"],
        }
    ]


def _normalize_scene_alias_usage_rules(
    value: Any,
    *,
    input_variables: dict[str, Any],
    scene_name: str,
) -> list[dict[str, Any]]:
    normalized = _deep_normalize_candidate(value)
    items = normalized if isinstance(normalized, list) else []
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        canonical_name = _extract_any_text(item, ("canonical_name", "character_name", "name")) or "待补全角色"
        result.append(
            {
                "character_id": _extract_any_text(item, ("character_id",)) or canonical_name,
                "canonical_name": canonical_name,
                "recommended_alias_name": _extract_any_text(
                    item,
                    ("recommended_alias_name", "alias_name"),
                ) or f"{canonical_name}（{scene_name}）",
                "usage_condition": _extract_any_text(item, ("usage_condition", "condition"))
                or f"待补全：补充{canonical_name}在{scene_name}的别名使用条件",
                "fallback_allowed": bool(item.get("fallback_allowed", False)),
                "reason": _extract_any_text(item, ("reason",))
                or f"待补全：补充{canonical_name}在{scene_name}使用该 alias 的原因",
            }
        )
    if result:
        return result

    seed = _scene_character_seed(input_variables, 1)
    canonical_name = seed.get("character_name") or "待补全角色"
    return [
        {
            "character_id": canonical_name,
            "canonical_name": canonical_name,
            "recommended_alias_name": f"{canonical_name}（{scene_name}）",
            "usage_condition": f"待补全：补充{canonical_name}在{scene_name}的别名使用条件",
            "fallback_allowed": False,
            "reason": f"待补全：补充{canonical_name}在{scene_name}使用 alias 的原因",
        }
    ]


def _supplement_scene_items_from_input(
    existing: list[dict[str, Any]],
    *,
    input_variables: dict[str, Any],
    warnings: list[str],
) -> list[dict[str, Any]]:
    if len(existing) >= 3:
        return existing
    seeds = _scene_location_seeds(input_variables)
    used_names = {str(item.get("scene_name") or "").strip() for item in existing}
    next_index = len(existing) + 1
    for seed in seeds:
        name = _normalize_text_value(seed.get("name"))
        if not name or name in used_names:
            continue
        existing.append(
            _normalize_scene_item(
                seed,
                input_variables=input_variables,
                index=next_index,
                warnings=warnings,
                alias_hits={},
                missing_fields=[],
            )
        )
        used_names.add(name)
        next_index += 1
        if len(existing) >= 3:
            warnings.append("scenes 场景数量不足，已根据 user_scenes.core_locations 补足到至少 3 个。")
            break
    return existing


def _scene_character_seed(input_variables: dict[str, Any], index: int) -> dict[str, Any]:
    seeds = _character_seeds_from_input(input_variables.get("user_characters"))
    if 0 < index <= len(seeds) and isinstance(seeds[index - 1], dict):
        return seeds[index - 1]
    return {}


def _scene_location_seeds(input_variables: dict[str, Any]) -> list[dict[str, Any]]:
    user_scenes = _jsonish_dict(input_variables.get("user_scenes"))
    core_locations = user_scenes.get("core_locations")
    if not isinstance(core_locations, list):
        return []
    return [item for item in core_locations if isinstance(item, dict)]


def _scene_location_seed(input_variables: dict[str, Any], index: int) -> dict[str, Any]:
    seeds = _scene_location_seeds(input_variables)
    if 0 < index <= len(seeds):
        return seeds[index - 1]
    return {}


def _scene_setting_placeholder(field_name: str, input_variables: dict[str, Any]) -> str:
    user_scenes = _jsonish_dict(input_variables.get("user_scenes"))
    atmosphere = _normalize_text_value(user_scenes.get("overall_atmosphere"))
    rules = _normalize_text_value(user_scenes.get("rules"))
    if field_name == "scene_design_principle":
        return "待补全：围绕故事大纲、核心场景与分集计划统一场景功能分工"
    if field_name == "scene_visual_styling_naming_strategy":
        if atmosphere or rules:
            return f"待补全：围绕{atmosphere or '整体氛围'}与{rules or '场景规则'}统一视觉/造型/命名策略"
        return "待补全：统一视觉条件、造型条件和命名条件的场景策略"
    return f"待补全：补充 {field_name}"


def _extract_character_field(
    raw: dict[str, Any],
    lowered: dict[str, str],
    field_name: str,
    alias_hits: dict[str, str],
) -> str:
    actual_key = _match_alias_key(raw, lowered, CHARACTER_FIELD_ALIASES[field_name])
    if actual_key is None:
        return ""
    if actual_key != field_name:
        alias_hits[f"characters.{field_name}"] = actual_key
    return _normalize_text_value(raw.get(actual_key))


def _extract_character_raw(
    raw: dict[str, Any],
    lowered: dict[str, str],
    field_name: str,
) -> Any:
    actual_key = _match_alias_key(raw, lowered, CHARACTER_FIELD_ALIASES[field_name])
    return raw.get(actual_key) if actual_key is not None else None


def _normalize_appearanceMapping_body(
    value: Any,
    *,
    warnings: list[str] | None = None,
    alias_hits: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if warnings is None:
        warnings = []
    if alias_hits is None:
        alias_hits = {}
    candidate = _deep_normalize_candidate(value)
    if isinstance(candidate, dict):
        for wrapper_key in APPEARANCE_WRAPPER_KEYS:
            nested = candidate.get(wrapper_key)
            if nested is None:
                continue
            if isinstance(nested, str) and _looks_like_core_scene_narrative_text(nested):
                return None
            normalized_nested = _normalize_appearanceMapping_body(
                nested,
                warnings=warnings,
                alias_hits=alias_hits,
            )
            if isinstance(normalized_nested, dict):
                return normalized_nested

    if not isinstance(candidate, dict):
        return None
    if not _looks_like_appearanceMapping_body(candidate):
        return None

    return _canonicalize_appearanceMapping_body(
        candidate,
        warnings=warnings,
        alias_hits=alias_hits,
    )


def _canonicalize_appearanceMapping_body(
    value: dict[str, Any],
    *,
    warnings: list[str],
    alias_hits: dict[str, str],
) -> dict[str, Any]:
    lowered = _lowered_key_map(value)
    normalized: dict[str, Any] = {}
    for field_name, aliases in APPEARANCE_TOP_LEVEL_ALIASES.items():
        actual_key = _match_alias_key(value, lowered, aliases)
        if actual_key is None:
            continue
        if actual_key != field_name:
            alias_hits[f"appearanceMapping.{field_name}"] = actual_key
        raw = value.get(actual_key)
        if field_name == "characters":
            normalized[field_name] = _normalize_appearance_characters(raw, warnings, alias_hits)
        elif field_name == "episode_level_usage_plan":
            normalized[field_name] = _normalize_appearance_episode_usage_plan(
                raw,
                warnings,
                alias_hits,
            )
        elif field_name == "scene_level_usage_plan":
            normalized[field_name] = _normalize_appearance_scene_usage_plan(
                raw,
                warnings,
                alias_hits,
            )
        elif field_name == "special_naming_rules":
            normalized[field_name] = _normalize_string_list(raw)
        else:
            normalized[field_name] = _normalize_text_value(raw)
    if not str(normalized.get("mapping_principle") or "").strip():
        normalized["mapping_principle"] = (
            "以角色身份、场景触发与状态变化为核心，保持同人同锚点、同触发条件同别名。"
        )
        warnings.append("appearanceMapping.mapping_principle 缺失，已补默认映射原则")
    if not str(normalized.get("global_naming_style") or "").strip():
        normalized["global_naming_style"] = (
            "统一使用“角色中文全名【场景/状态/身份】”格式；常态默认使用 default_name。"
        )
        warnings.append("appearanceMapping.global_naming_style 缺失，已补默认命名风格")
    if not isinstance(normalized.get("characters"), list):
        normalized["characters"] = []
    if not isinstance(normalized.get("episode_level_usage_plan"), list):
        normalized["episode_level_usage_plan"] = []
        warnings.append("appearanceMapping.episode_level_usage_plan 缺失，已补空数组")
    if not isinstance(normalized.get("scene_level_usage_plan"), list):
        normalized["scene_level_usage_plan"] = []
        warnings.append("appearanceMapping.scene_level_usage_plan 缺失，已补空数组")
    if not isinstance(normalized.get("special_naming_rules"), list):
        normalized["special_naming_rules"] = []
        warnings.append("appearanceMapping.special_naming_rules 缺失，已补空数组")
    return normalized


def _normalize_appearance_characters(
    value: Any,
    warnings: list[str],
    alias_hits: dict[str, str],
) -> list[dict[str, Any]]:
    normalized = _deep_normalize_candidate(value)
    items = normalized if isinstance(normalized, list) else []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        lowered = _lowered_key_map(item)
        character: dict[str, Any] = {}
        raw_variant_seed = item.get(
            _match_alias_key(item, lowered, APPEARANCE_CHARACTER_ALIASES["outfit_variants"])
            or "outfit_variants"
        )
        for field_name, aliases in APPEARANCE_CHARACTER_ALIASES.items():
            actual_key = _match_alias_key(item, lowered, aliases)
            if actual_key is None:
                continue
            if actual_key != field_name:
                alias_hits[f"appearanceMapping.characters[{index}].{field_name}"] = actual_key
            raw = item.get(actual_key)
            if field_name == "same_person_anchor":
                character[field_name] = _normalize_same_person_anchor_for_appearance(
                    raw,
                    index=index,
                    alias_hits=alias_hits,
                )
            elif field_name == "forbidden_generic_names":
                character[field_name] = _normalize_string_list(raw)
            elif field_name == "outfit_variants":
                continue
            else:
                character[field_name] = _normalize_text_value(raw)
        raw_character_name = _normalize_text_value(item.get("character_name"))
        canonical_name = str(character.get("canonical_name") or "").strip() or raw_character_name
        if canonical_name and canonical_name != str(character.get("canonical_name") or "").strip():
            character["canonical_name"] = canonical_name
            warnings.append(
                f"appearanceMapping.characters[{index}].canonical_name 缺失，已回退为 {canonical_name}"
            )
        character_id = str(character.get("character_id") or "").strip()
        if not character_id:
            character_id = _stable_character_id(canonical_name or raw_character_name, index=index)
            if character_id:
                character["character_id"] = character_id
                warnings.append(
                    f"appearanceMapping.characters[{index}].character_id 缺失，已补为 {character_id}"
                )
        if not canonical_name and character_id:
            canonical_name = character_id
            character["canonical_name"] = character_id
            warnings.append(
                f"appearanceMapping.characters[{index}].canonical_name 为空，已回退为 {character_id}"
            )
        if not str(character.get("story_role") or "").strip():
            character["story_role"] = "关键角色"
            warnings.append(
                f"appearanceMapping.characters[{index}].story_role 缺失，已补默认值“关键角色”"
            )
        if not str(character.get("default_name") or "").strip():
            fallback_name = canonical_name or character_id
            if fallback_name:
                character["default_name"] = fallback_name
                warnings.append(
                    f"appearanceMapping.characters[{index}].default_name 为空，已回退为 {fallback_name}"
                )
        same_person_anchor = _complete_same_person_anchor_for_appearance(
            anchor=character.get("same_person_anchor"),
            variant_seed=raw_variant_seed,
            canonical_name=canonical_name or raw_character_name or character_id,
            default_name=str(character.get("default_name") or "").strip(),
        )
        character["same_person_anchor"] = same_person_anchor
        forbidden_names = _normalize_string_list(character.get("forbidden_generic_names"))
        if not forbidden_names:
            forbidden_names = list(APPEARANCE_DEFAULT_FORBIDDEN_GENERIC_NAMES)
            warnings.append(
                f"appearanceMapping.characters[{index}].forbidden_generic_names 缺失，已补默认泛称黑名单"
            )
        character["forbidden_generic_names"] = forbidden_names
        character["outfit_variants"] = _normalize_appearance_outfit_variants(
            raw_variant_seed,
            index=index,
            warnings=warnings,
            alias_hits=alias_hits,
            character_name=canonical_name or raw_character_name or character_id,
            default_name=str(character.get("default_name") or "").strip(),
            same_person_anchor=same_person_anchor,
        )
        result.append(character)
    return result


def _normalize_same_person_anchor_for_appearance(
    value: Any,
    *,
    index: int,
    alias_hits: dict[str, str],
) -> dict[str, Any]:
    normalized = _deep_normalize_candidate(value)
    raw = normalized if isinstance(normalized, dict) else {}
    lowered = _lowered_key_map(raw)
    result: dict[str, Any] = {}
    for field_name, aliases in APPEARANCE_SAME_PERSON_ANCHOR_ALIASES.items():
        actual_key = _match_alias_key(raw, lowered, aliases)
        if actual_key is None:
            continue
        if actual_key != field_name:
            alias_hits[
                f"appearanceMapping.characters[{index}].same_person_anchor.{field_name}"
            ] = actual_key
        value_at_key = raw.get(actual_key)
        if field_name == "unchanged_core_impression":
            result[field_name] = _normalize_text_value(value_at_key)
        else:
            result[field_name] = _normalize_string_list(value_at_key)
    return result


def _normalize_appearance_outfit_variants(
    value: Any,
    *,
    index: int,
    warnings: list[str],
    alias_hits: dict[str, str],
    character_name: str,
    default_name: str,
    same_person_anchor: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized = _deep_normalize_candidate(value)
    items = normalized if isinstance(normalized, list) else []
    result: list[dict[str, Any]] = []
    for variant_index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        lowered = _lowered_key_map(item)
        variant: dict[str, Any] = {}
        for field_name, aliases in APPEARANCE_VARIANT_ALIASES.items():
            actual_key = _match_alias_key(item, lowered, aliases)
            if actual_key is None:
                continue
            if actual_key != field_name:
                alias_hits[
                    f"appearanceMapping.characters[{index}].outfit_variants[{variant_index}].{field_name}"
                ] = actual_key
            raw = item.get(actual_key)
            if field_name == "visual_keypoints":
                variant[field_name] = _normalize_string_list(raw)
            elif field_name == "scene_trigger_rules":
                variant[field_name] = _normalize_appearance_scene_trigger_rules(
                    raw,
                    character_index=index,
                    variant_index=variant_index,
                    alias_hits=alias_hits,
                    raw_variant=item,
                )
            elif field_name in {"must_use_when_triggered", "fallback_allowed"}:
                variant[field_name] = raw
            else:
                variant[field_name] = _normalize_text_value(raw)
        alias_name = normalize_appearance_alias_name(variant.get("alias_name"))

        if not alias_name:
            alias_name = _default_variant_alias_name(character_name or default_name, variant_index)
            variant["alias_name"] = alias_name
            warnings.append(
                "appearanceMapping.characters"
                f"[{index}].outfit_variants[{variant_index}].alias_name 缺失，已补为 {alias_name}"
            )
        else:
            normalized_alias_name = normalize_appearance_alias_name(alias_name)
            if normalized_alias_name != str(variant.get("alias_name") or "").strip():
                warnings.append(
                    "appearanceMapping.characters"
                    f"[{index}].outfit_variants[{variant_index}].alias_name 已从旧格式归一化为 {normalized_alias_name}"
                )
            alias_name = normalized_alias_name
            variant["alias_name"] = alias_name

        if not _is_valid_new_alias_name(alias_name):
            fallback_alias_name = _default_variant_alias_name(character_name or default_name, variant_index)
            warnings.append(
                "appearanceMapping.characters"
                f"[{index}].outfit_variants[{variant_index}].alias_name={alias_name} 不符合新格式，已回退为 {fallback_alias_name}"
            )
            alias_name = fallback_alias_name
            variant["alias_name"] = alias_name
        identity_state = str(variant.get("applicable_identity_state") or "").strip()
        if not identity_state:
            identity_state = _extract_identity_state_from_alias(alias_name) or "常态"
            variant["applicable_identity_state"] = identity_state
        visual_keypoints = _normalize_string_list(variant.get("visual_keypoints"))
        outfit_description = str(variant.get("outfit_description") or "").strip()
        if not outfit_description:
            outfit_description = "，".join(visual_keypoints) or "待补全服装描述"
            variant["outfit_description"] = outfit_description
        if not visual_keypoints:
            visual_keypoints = _fallback_visual_keypoints(outfit_description, alias_name)
            variant["visual_keypoints"] = visual_keypoints
        if not str(variant.get("outfit_type") or "").strip():
            variant["outfit_type"] = _infer_outfit_type(alias_name, outfit_description)
        if not str(variant.get("variant_id") or "").strip():
            variant["variant_id"] = _stable_variant_id(alias_name, identity_state, variant_index)
        if not str(variant.get("episode_range_hint") or "").strip():
            variant["episode_range_hint"] = "按场景或状态触发"
        variant["scene_trigger_rules"] = _complete_appearance_scene_trigger_rules(
            variant.get("scene_trigger_rules"),
            raw_variant=item,
        )
        if not str(variant.get("usage_rule") or "").strip():
            rule_alias = alias_name or default_name or character_name
            variant["usage_rule"] = f"触发对应场景或状态时使用{rule_alias}"
        if not isinstance(variant.get("must_use_when_triggered"), bool):
            variant["must_use_when_triggered"] = True
        if not isinstance(variant.get("fallback_allowed"), bool):
            variant["fallback_allowed"] = False
        if not str(variant.get("same_person_confirmation") or "").strip():
            variant["same_person_confirmation"] = str(
                same_person_anchor.get("unchanged_core_impression") or ""
            ).strip()
        result.append(variant)
    return result


def _normalize_appearance_scene_trigger_rules(
    value: Any,
    *,
    character_index: int,
    variant_index: int,
    alias_hits: dict[str, str],
    raw_variant: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _deep_normalize_candidate(value)
    raw = normalized if isinstance(normalized, dict) else {}
    lowered = _lowered_key_map(raw)
    result: dict[str, Any] = {}
    for field_name, aliases in APPEARANCE_SCENE_TRIGGER_RULE_ALIASES.items():
        actual_key = _match_alias_key(raw, lowered, aliases)
        if actual_key is None:
            continue
        if actual_key != field_name:
            alias_hits[
                "appearanceMapping.characters"
                f"[{character_index}].outfit_variants[{variant_index}].scene_trigger_rules.{field_name}"
            ] = actual_key
        result[field_name] = _normalize_string_list(raw.get(actual_key))
    return _complete_appearance_scene_trigger_rules(result, raw_variant=raw_variant)


def _normalize_appearance_episode_usage_plan(
    value: Any,
    warnings: list[str],
    alias_hits: dict[str, str],
) -> list[dict[str, Any]]:
    del warnings
    normalized = _deep_normalize_candidate(value)
    items = normalized if isinstance(normalized, list) else []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        lowered = _lowered_key_map(item)
        episode_range_key = _match_alias_key(
            item,
            lowered,
            ("episode_range", "episodeRange"),
        )
        aliases_key = _match_alias_key(
            item,
            lowered,
            ("main_character_aliases", "mainCharacterAliases"),
        )
        entry = {
            "episode_range": _normalize_text_value(item.get(episode_range_key))
            if episode_range_key is not None
            else "",
            "main_character_aliases": _normalize_appearance_usage_alias_items(
                item.get(aliases_key),
                alias_name_field="recommended_alias_name",
            ),
        }
        if episode_range_key is not None and episode_range_key != "episode_range":
            alias_hits[f"appearanceMapping.episode_level_usage_plan[{index}].episode_range"] = episode_range_key
        if aliases_key is not None and aliases_key != "main_character_aliases":
            alias_hits[
                f"appearanceMapping.episode_level_usage_plan[{index}].main_character_aliases"
            ] = aliases_key
        result.append(entry)
    return result


def _normalize_appearance_scene_usage_plan(
    value: Any,
    warnings: list[str],
    alias_hits: dict[str, str],
) -> list[dict[str, Any]]:
    del warnings
    normalized = _deep_normalize_candidate(value)
    items = normalized if isinstance(normalized, list) else []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        lowered = _lowered_key_map(item)
        scene_name_key = _match_alias_key(item, lowered, ("scene_name", "sceneName"))
        usage_key = _match_alias_key(
            item,
            lowered,
            ("expected_alias_usage", "expectedAliasUsage"),
        )
        entry = {
            "scene_name": _normalize_text_value(item.get(scene_name_key))
            if scene_name_key is not None
            else "",
            "expected_alias_usage": _normalize_appearance_usage_alias_items(
                item.get(usage_key),
                alias_name_field="alias_name",
            ),
        }
        if scene_name_key is not None and scene_name_key != "scene_name":
            alias_hits[f"appearanceMapping.scene_level_usage_plan[{index}].scene_name"] = scene_name_key
        if usage_key is not None and usage_key != "expected_alias_usage":
            alias_hits[
                f"appearanceMapping.scene_level_usage_plan[{index}].expected_alias_usage"
            ] = usage_key
        result.append(entry)
    return result


def _normalize_appearance_usage_alias_items(
    value: Any,
    *,
    alias_name_field: str,
) -> list[dict[str, Any]]:
    normalized = _deep_normalize_candidate(value)
    items = normalized if isinstance(normalized, list) else []
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        lowered = _lowered_key_map(item)
        character_id_key = _match_alias_key(item, lowered, ("character_id", "characterId"))
        alias_key = _match_alias_key(
            item,
            lowered,
            (alias_name_field, "recommended_alias_name", "recommendedAliasName", "alias_name", "aliasName"),
        )
        reason_key = _match_alias_key(item, lowered, ("reason",))
        result.append(
            {
                "character_id": _normalize_text_value(item.get(character_id_key))
                if character_id_key is not None
                else "",
                alias_name_field: _normalize_text_value(item.get(alias_key))
                if alias_key is not None
                else "",
                "reason": _normalize_text_value(item.get(reason_key))
                if reason_key is not None
                else "",
            }
        )
    return result


def _complete_same_person_anchor_for_appearance(
    *,
    anchor: Any,
    variant_seed: Any,
    canonical_name: str,
    default_name: str,
) -> dict[str, Any]:
    existing = anchor if isinstance(anchor, dict) else {}
    stable_traits = _normalize_string_list(existing.get("stable_appearance_traits"))
    recognition_points = _normalize_string_list(existing.get("stable_recognition_points"))
    unchanged_core = str(existing.get("unchanged_core_impression") or "").strip()

    visual_seed_points: list[str] = []
    confirmation_texts: list[str] = []
    variant_items = _deep_normalize_candidate(variant_seed)
    if isinstance(variant_items, list):
        for item in variant_items:
            if not isinstance(item, dict):
                continue
            visual_seed_points.extend(_normalize_string_list(item.get("visual_keypoints")))
            confirmation = _normalize_text_value(item.get("same_person_confirmation"))
            if confirmation:
                confirmation_texts.append(confirmation)

    merged_points = _dedupe_strings([*stable_traits, *recognition_points, *visual_seed_points])
    if not stable_traits:
        stable_traits = merged_points[:3]
    if not recognition_points:
        recognition_points = merged_points[:3]
    if not unchanged_core:
        unchanged_core = (
            confirmation_texts[0]
            if confirmation_texts
            else "、".join(merged_points[:2])
            or default_name
            or canonical_name
            or "同一人物的核心外观印象保持一致"
        )

    if not stable_traits:
        stable_traits = [default_name or canonical_name or "核心人物造型稳定"]
    if not recognition_points:
        recognition_points = [default_name or canonical_name or "核心人物识别点稳定"]

    return {
        "stable_appearance_traits": stable_traits,
        "stable_recognition_points": recognition_points,
        "unchanged_core_impression": unchanged_core,
    }


def _complete_appearance_scene_trigger_rules(
    value: Any,
    *,
    raw_variant: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = value if isinstance(value, dict) else {}
    raw = raw_variant if isinstance(raw_variant, dict) else {}
    lowered = _lowered_key_map(raw)
    result: dict[str, Any] = {}
    for field_name, aliases in APPEARANCE_SCENE_TRIGGER_RULE_ALIASES.items():
        existing_values = _normalize_string_list(current.get(field_name))
        if existing_values:
            result[field_name] = existing_values
            continue
        actual_key = _match_alias_key(raw, lowered, aliases)
        if actual_key is not None:
            result[field_name] = _normalize_string_list(raw.get(actual_key))
            continue
        result[field_name] = []
    return result


def _stable_character_id(name: str, *, index: int) -> str:
    text = str(name or "").strip()
    if not text:
        return f"character_{index}"
    lowered = text.lower()
    ascii_candidate = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    if ascii_candidate:
        return ascii_candidate
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
    return normalized or f"character_{index}"


def _default_variant_alias_name(character_name: str, variant_index: int) -> str:
    base = str(character_name or "").strip() or f"角色{variant_index}"
    return f"{base}(常态)"


def _extract_identity_state_from_alias(alias_name: str) -> str:
    text = str(alias_name or "").strip()
    if not text:
        return ""
    for pattern in (r"\(([^)]+)\)", r"（([^）]+)）", r"【([^】]+)】", r"\[([^\]]+)\]"):
        match = re.search(pattern, text)
        if match:
            return str(match.group(1) or "").strip()
    return ""


def _fallback_visual_keypoints(outfit_description: str, alias_name: str) -> list[str]:
    description_points = _normalize_string_list(outfit_description)
    if description_points:
        return description_points[:3]
    alias_text = str(alias_name or "").strip()
    return [alias_text] if alias_text else ["待补全服装关键点"]


def _infer_outfit_type(alias_name: str, outfit_description: str) -> str:
    text = f"{alias_name} {outfit_description}".strip()
    for keyword, outfit_type in (
        ("日常", "日常装"),
        ("通勤", "通勤装"),
        ("会议", "职场装"),
        ("制服", "制服"),
        ("校服", "校服"),
        ("礼服", "礼服"),
        ("战斗", "战斗装"),
        ("婚礼", "礼服"),
        ("睡衣", "居家装"),
        ("居家", "居家装"),
    ):
        if keyword in text:
            return outfit_type
    return "剧情服装"


def _stable_variant_id(alias_name: str, identity_state: str, variant_index: int) -> str:
    seed = identity_state or alias_name or f"variant_{variant_index}"
    lowered = str(seed or "").strip().lower()
    ascii_candidate = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    if ascii_candidate:
        return ascii_candidate
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(seed or "").strip())
    return normalized or f"variant_{variant_index}"


def _looks_like_appearanceMapping_body(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    wrapped = value.get(APPEARANCE_MAPPING_FIELD)
    if wrapped is not None:
        if isinstance(wrapped, dict):
            return _looks_like_appearanceMapping_body(wrapped)
        return False
    if any(_looks_like_appearanceMapping_review_json(value.get(key)) for key in (APPEARANCE_MAPPING_FIELD,)):
        return False
    if any(
        isinstance(item, list) and item
        for item in (
            value.get("characters"),
            value.get("episode_level_usage_plan"),
            value.get("scene_level_usage_plan"),
            value.get("special_naming_rules"),
        )
    ):
        return True
    signal_count = 0
    for key in ("mapping_principle", "global_naming_style"):
        if str(value.get(key) or "").strip():
            signal_count += 1
    for key in ("characters", "episode_level_usage_plan", "scene_level_usage_plan", "special_naming_rules"):
        if key in value:
            signal_count += 1
    return signal_count >= 2


def _looks_like_core_scene_narrative_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = " ".join(strip_code_fence(value).split())
    if not text:
        return False
    if text.startswith("核心场景：") or text.startswith("核心场景:"):
        return True
    if "核心场景包括" in text:
        return True
    if "场景名：场景类型 / 建筑或空间属性" in text:
        return True
    if "核心场景" in text and "场景类型" in text and "建筑或空间属性" in text:
        return True
    return False


def _looks_like_appearanceMapping_review_json(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    keys = {str(key) for key in value.keys()}
    review_keys = {
        "passed",
        "approved",
        "blocking_issues",
        "non_blocking_issues",
        "rewrite_required",
        "summary",
        "suggestions",
        "issues",
        "patches",
    }
    return bool(keys & review_keys) and not _looks_like_appearanceMapping_body(value)


def _appearanceMapping_object(value: Any) -> dict[str, Any] | None:
    normalized_body = _normalize_appearanceMapping_body(value)
    if isinstance(normalized_body, dict):
        return normalized_body
    normalized = _parse_json_object_string(value)
    if not isinstance(normalized, dict):
        return None
    if isinstance(normalized.get(APPEARANCE_MAPPING_FIELD), dict):
        return normalized.get(APPEARANCE_MAPPING_FIELD)
    if _looks_like_appearanceMapping_body(normalized):
        return normalized
    return None


def _validate_appearanceMapping_contract_shape(value: Any) -> list[str]:
    mapping = _appearanceMapping_object(value)
    if not isinstance(mapping, dict):
        return ["必须是可归一化为 appearanceMapping 的 JSON object"]

    issues: list[str] = []
    for key in ("mapping_principle", "global_naming_style"):
        if not str(mapping.get(key) or "").strip():
            issues.append(f"appearanceMapping.{key} 不能为空")

    characters = mapping.get("characters")
    if not isinstance(characters, list) or not characters:
        issues.append("appearanceMapping.characters 必须是非空数组")
    episode_usage_plan = mapping.get("episode_level_usage_plan")
    if not isinstance(episode_usage_plan, list):
        issues.append("appearanceMapping.episode_level_usage_plan 必须是数组")
    scene_usage_plan = mapping.get("scene_level_usage_plan")
    if not isinstance(scene_usage_plan, list):
        issues.append("appearanceMapping.scene_level_usage_plan 必须是数组")
    if "special_naming_rules" not in mapping:
        issues.append("appearanceMapping.special_naming_rules 缺失")
    elif not isinstance(mapping.get("special_naming_rules"), list):
        issues.append("appearanceMapping.special_naming_rules 必须是数组")

    if not isinstance(characters, list):
        return issues

    for index, item in enumerate(characters, start=1):
        prefix = f"appearanceMapping.characters[{index}]"
        if not isinstance(item, dict):
            issues.append(f"{prefix} 必须是 object")
            continue
        if not str(item.get("character_id") or "").strip():
            issues.append(f"{prefix}.character_id 不能为空")
        if not str(item.get("canonical_name") or "").strip():
            issues.append(f"{prefix}.canonical_name 不能为空")
        if not str(item.get("story_role") or "").strip():
            issues.append(f"{prefix}.story_role 不能为空")
        if not str(item.get("default_name") or "").strip():
            issues.append(f"{prefix}.default_name 不能为空")

        same_person_anchor = item.get("same_person_anchor")
        if not isinstance(same_person_anchor, dict):
            issues.append(f"{prefix}.same_person_anchor 必须是 object")
        else:
            if not _normalize_string_list(same_person_anchor.get("stable_appearance_traits")):
                issues.append(f"{prefix}.same_person_anchor.stable_appearance_traits 必须是非空数组")
            if not _normalize_string_list(same_person_anchor.get("stable_recognition_points")):
                issues.append(f"{prefix}.same_person_anchor.stable_recognition_points 必须是非空数组")
            if not str(same_person_anchor.get("unchanged_core_impression") or "").strip():
                issues.append(f"{prefix}.same_person_anchor.unchanged_core_impression 不能为空")

        forbidden_names = item.get("forbidden_generic_names")
        if not isinstance(forbidden_names, list) or not _normalize_string_list(forbidden_names):
            issues.append(f"{prefix}.forbidden_generic_names 必须是非空数组")

        variants = item.get("outfit_variants")
        if not isinstance(variants, list) or not variants:
            issues.append(f"{prefix}.outfit_variants 必须是非空数组")
            continue

        for variant_index, variant in enumerate(variants, start=1):
            variant_prefix = f"{prefix}.outfit_variants[{variant_index}]"
            if not isinstance(variant, dict):
                issues.append(f"{variant_prefix} 必须是 object")
                continue
            for key in (
                "variant_id",
                "alias_name",
                "applicable_identity_state",
                "outfit_type",
                "outfit_description",
                "episode_range_hint",
                "usage_rule",
                "same_person_confirmation",
            ):
                if not str(variant.get(key) or "").strip():
                    issues.append(f"{variant_prefix}.{key} 不能为空")
            alias_name = normalize_appearance_alias_name(variant.get("alias_name"))
            if alias_name:
                variant["alias_name"] = alias_name

            if not _is_valid_new_alias_name(alias_name):
                issues.append(
                    f"{variant_prefix}.alias_name 必须使用“角色中文全名【场景/状态/身份】”格式"
                )
            if not _normalize_string_list(variant.get("visual_keypoints")):
                issues.append(f"{variant_prefix}.visual_keypoints 必须是非空数组")

            trigger_rules = variant.get("scene_trigger_rules")
            if not isinstance(trigger_rules, dict):
                issues.append(f"{variant_prefix}.scene_trigger_rules 必须是 object")
            else:
                for key in (
                    "scene_names",
                    "scene_types",
                    "environment_or_time",
                    "status_conditions",
                ):
                    if key not in trigger_rules:
                        issues.append(f"{variant_prefix}.scene_trigger_rules.{key} 缺失")
                    elif not isinstance(trigger_rules.get(key), list):
                        issues.append(f"{variant_prefix}.scene_trigger_rules.{key} 必须是数组")

            for bool_key in ("must_use_when_triggered", "fallback_allowed"):
                if not isinstance(variant.get(bool_key), bool):
                    issues.append(f"{variant_prefix}.{bool_key} 必须是 boolean")
    return issues


def _validate_appearanceMapping_local_review(value: Any) -> list[str]:
    mapping = _appearanceMapping_object(value)
    if not isinstance(mapping, dict):
        return ["必须是可归一化为 appearanceMapping 的 JSON object"]

    issues: list[str] = []
    episode_usage_plan = mapping.get("episode_level_usage_plan")
    if isinstance(episode_usage_plan, list):
        for index, item in enumerate(episode_usage_plan, start=1):
            prefix = f"appearanceMapping.episode_level_usage_plan[{index}]"
            if not isinstance(item, dict):
                issues.append(f"{prefix} 必须是 object")
                continue
            if not str(item.get("episode_range") or "").strip():
                issues.append(f"{prefix}.episode_range 不能为空")
            aliases = item.get("main_character_aliases")
            if not isinstance(aliases, list) or not aliases:
                issues.append(f"{prefix}.main_character_aliases 必须是非空数组")
                continue
            for alias_index, alias_item in enumerate(aliases, start=1):
                alias_prefix = f"{prefix}.main_character_aliases[{alias_index}]"
                if not isinstance(alias_item, dict):
                    issues.append(f"{alias_prefix} 必须是 object")
                    continue
                alias_name = normalize_appearance_alias_name(alias_item.get("recommended_alias_name"))
                if not alias_name:
                    issues.append(f"{alias_prefix}.recommended_alias_name 不能为空")
                else:
                    alias_item["recommended_alias_name"] = alias_name
                    if not _is_valid_new_alias_name(alias_name):
                        issues.append(
                            f"{alias_prefix}.recommended_alias_name 必须使用“角色中文全名【场景/状态/身份】”格式"
                        )
                if not str(alias_item.get("reason") or "").strip():
                    issues.append(f"{alias_prefix}.reason 不能为空")

    scene_usage_plan = mapping.get("scene_level_usage_plan")
    if isinstance(scene_usage_plan, list):
        for index, item in enumerate(scene_usage_plan, start=1):
            prefix = f"appearanceMapping.scene_level_usage_plan[{index}]"
            if not isinstance(item, dict):
                issues.append(f"{prefix} 必须是 object")
                continue
            if not str(item.get("scene_name") or "").strip():
                issues.append(f"{prefix}.scene_name 不能为空")
            aliases = item.get("expected_alias_usage")
            if not isinstance(aliases, list) or not aliases:
                issues.append(f"{prefix}.expected_alias_usage 必须是非空数组")
                continue
            for alias_index, alias_item in enumerate(aliases, start=1):
                alias_prefix = f"{prefix}.expected_alias_usage[{alias_index}]"
                if not isinstance(alias_item, dict):
                    issues.append(f"{alias_prefix} 必须是 object")
                    continue
                alias_name = normalize_appearance_alias_name(alias_item.get("alias_name"))
                if not alias_name:
                    issues.append(f"{alias_prefix}.alias_name 不能为空")
                else:
                    alias_item["alias_name"] = alias_name
                    if not _is_valid_new_alias_name(alias_name):
                        issues.append(
                            f"{alias_prefix}.alias_name 必须使用“角色中文全名【场景/状态/身份】”格式"
                        )
                if not str(alias_item.get("reason") or "").strip():
                    issues.append(f"{alias_prefix}.reason 不能为空")
    return issues


def _looks_like_worldview_body(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    lowered = {str(key).lower() for key in value.keys()}
    alias_set = {
        alias.lower()
        for aliases in WORLDVIEW_FIELD_ALIASES.values()
        for alias in aliases
    }
    return bool(lowered & alias_set)


def _looks_like_character_body(value: Any) -> bool:
    if isinstance(value, dict) and isinstance(value.get("character_setting"), dict):
        return True
    if isinstance(value, dict) and _looks_like_character_setting_dict(value):
        return True
    if isinstance(value, dict) and isinstance(value.get("characters"), list):
        return True
    if isinstance(value, list):
        return any(isinstance(item, dict) for item in value)
    return False


def _looks_like_scenes_body(value: Any) -> bool:
    if isinstance(value, dict) and isinstance(value.get("scenes"), dict) and isinstance(
        value["scenes"].get("scene_setting"),
        dict,
    ):
        return True
    if isinstance(value, dict) and isinstance(value.get("scene_setting"), dict):
        return True
    if isinstance(value, dict) and _looks_like_scene_setting_dict(value):
        return True
    if isinstance(value, dict) and isinstance(value.get("scenes"), list):
        return True
    if isinstance(value, list):
        return any(isinstance(item, dict) for item in value)
    return False


def _looks_like_character_setting_dict(value: dict[str, Any]) -> bool:
    lowered = {str(key).lower() for key in value.keys()}
    alias_set = {
        alias.lower()
        for aliases in CHARACTER_SETTING_ALIASES.values()
        for alias in aliases
    }
    return bool(lowered & alias_set)


def _looks_like_single_character_dict(value: dict[str, Any]) -> bool:
    lowered = {str(key).lower() for key in value.keys()}
    return any(alias.lower() in lowered for alias in CHARACTER_FIELD_ALIASES["character_name"])


def _looks_like_scene_setting_dict(value: dict[str, Any]) -> bool:
    lowered = {str(key).lower() for key in value.keys()}
    alias_set = {
        alias.lower()
        for aliases in SCENE_SETTING_ALIASES.values()
        for alias in aliases
    }
    return bool(lowered & alias_set)


def _looks_like_single_scene_dict(value: dict[str, Any]) -> bool:
    lowered = {str(key).lower() for key in value.keys()}
    return any(alias.lower() in lowered for alias in SCENE_FIELD_ALIASES["scene_name"])


def _looks_like_worldview_review_json(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    keys = {str(key) for key in value.keys()}
    return "approved" in keys and "suggestions" in keys and not _looks_like_worldview_body(value)


def _looks_like_characters_review_json(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    keys = {str(key) for key in value.keys()}
    review_keys = {"passed", "approved", "blocking_issues", "non_blocking_issues", "rewrite_required", "summary", "suggestions"}
    return bool(keys & review_keys) and not _looks_like_character_body(value)


def _looks_like_scenes_review_json(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    keys = {str(key) for key in value.keys()}
    review_keys = {
        "passed",
        "approved",
        "blocking_issues",
        "non_blocking_issues",
        "rewrite_required",
        "summary",
        "suggestions",
        "issues",
    }
    return bool(keys & review_keys) and not _looks_like_scenes_body(value)


def _describe_worldview_output_issue(value: Any) -> str | None:
    data = _parse_json_object_string(value)
    if data is None:
        return "必须是可 parse 的 JSON object"
    return _describe_worldview_body_issue(data)


def _describe_worldview_body_issue(data: dict[str, Any]) -> str | None:
    for key in WORLDVIEW_REQUIRED_STRING_FIELDS:
        if not str(data.get(key) or "").strip():
            return f"{key} 不能为空"
    for key in WORLDVIEW_REQUIRED_LIST_FIELDS:
        value = data.get(key)
        if not isinstance(value, list) or not [item for item in value if str(item).strip()]:
            return f"{key} 必须是非空数组"
    return None


def _describe_characters_output_issue(value: Any) -> str | None:
    data = _parse_json_object_string(value)
    if data is None:
        return "必须是可 parse 的 JSON object"
    return _describe_characters_body_issue(data)


def _describe_scenes_output_issue(value: Any) -> str | None:
    data = _parse_json_object_string(value)
    if data is None:
        return "必须是可 parse 的 JSON object"
    return _describe_scenes_body_issue(data)


def validate_scenes_output(value: Any) -> list[str]:
    issue = _describe_scenes_output_issue(value)
    return [issue] if issue else []


def _describe_characters_body_issue(data: dict[str, Any]) -> str | None:
    setting = data.get("character_setting")
    if not isinstance(setting, dict):
        return "character_setting 必须是 object"
    characters = setting.get("characters")
    if not isinstance(characters, list) or not characters:
        return "character_setting.characters 必须是非空数组"
    for index, item in enumerate(characters, start=1):
        if not isinstance(item, dict):
            return f"character_setting.characters[{index}] 必须是 object"
        missing = [key for key in CHARACTER_MIN_REQUIRED_FIELDS if item.get(key) in (None, "", [], {})]
        if missing:
            return f"character_setting.characters[{index}] 缺少字段 {', '.join(missing)}"
        if not isinstance(item.get("decision_logic"), dict):
            return f"character_setting.characters[{index}].decision_logic 必须是 object"
        if not isinstance(item.get("speech_profile"), dict):
            return f"character_setting.characters[{index}].speech_profile 必须是 object"
        if not isinstance(item.get("relation_modes"), list) or not item.get("relation_modes"):
            return f"character_setting.characters[{index}].relation_modes 必须是非空数组"
        if not isinstance(item.get("actable_evidence"), dict):
            return f"character_setting.characters[{index}].actable_evidence 必须是 object"
    return None


def _describe_scenes_body_issue(data: dict[str, Any]) -> str | None:
    if isinstance(data.get("scenes"), dict) and isinstance(data["scenes"].get("scene_setting"), dict):
        setting = data["scenes"]["scene_setting"]
    else:
        setting = data.get("scene_setting")
    if not isinstance(setting, dict):
        return "scene_setting 必须是 object"
    scenes = setting.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return "scene_setting.scenes 必须是非空数组"
    if len(scenes) < 3:
        return "scene_setting.scenes 至少需要 3 个场景"
    for index, item in enumerate(scenes, start=1):
        if not isinstance(item, dict):
            return f"scene_setting.scenes[{index}] 必须是 object"
        issue = _scene_payload_pollution_issue(item)
        if issue is not None:
            return f"scene_setting.scenes[{index}] {issue}"
        missing = [key for key in SCENE_MIN_REQUIRED_FIELDS if item.get(key) in (None, "", [], {})]
        if missing:
            return f"scene_setting.scenes[{index}] 缺少字段 {', '.join(missing)}"
        if not isinstance(item.get("outfit_requirements"), list) or not item.get("outfit_requirements"):
            return f"scene_setting.scenes[{index}].outfit_requirements 必须是非空数组"
        if not isinstance(item.get("alias_usage_rules"), list) or not item.get("alias_usage_rules"):
            return f"scene_setting.scenes[{index}].alias_usage_rules 必须是非空数组"
        if not isinstance(item.get("conflict_potential"), list) or not item.get("conflict_potential"):
            return f"scene_setting.scenes[{index}].conflict_potential 必须是非空数组"
    return None


def _scene_payload_pollution_issue(value: Any) -> str | None:
    normalized = _deep_normalize_candidate(value)
    if isinstance(normalized, dict):
        lowered_keys = {str(key).strip().lower() for key in normalized.keys()}
        forbidden_keys = sorted(
            key for key in lowered_keys if key in SCENE_FORBIDDEN_SCENE_KEYS
        )
        if forbidden_keys:
            return f"包含污染字段 {', '.join(forbidden_keys)}"
        placeholder_count = _scene_placeholder_count(normalized)
        if placeholder_count >= SCENE_PLACEHOLDER_REJECTION_THRESHOLD:
            return "含大量“待补全”占位，疑似未完成正式结构化输出"
        for nested_value in normalized.values():
            issue = _scene_payload_pollution_issue(nested_value)
            if issue is not None:
                return issue
        return None
    if isinstance(normalized, list):
        placeholder_count = _scene_placeholder_count(normalized)
        if placeholder_count >= SCENE_PLACEHOLDER_REJECTION_THRESHOLD:
            return "含大量“待补全”占位，疑似未完成正式结构化输出"
        for item in normalized:
            issue = _scene_payload_pollution_issue(item)
            if issue is not None:
                return issue
        return None
    if isinstance(normalized, str):
        raw_text = str(value or "")
        compact = " ".join(strip_code_fence(normalized).split())
        if "```" in raw_text:
            return "包含 markdown code fence"
        if any(marker in compact for marker in SCENE_FORBIDDEN_TEXT_MARKERS):
            return "包含审核说明或执行说明文本"
        if _looks_like_core_scene_narrative_text(compact):
            return "包含自然语言场景说明，不是正式 scene_setting JSON"
        return None
    return None


def _scene_placeholder_count(value: Any) -> int:
    if isinstance(value, str):
        return str(value).count("待补全")
    if isinstance(value, dict):
        return sum(_scene_placeholder_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(_scene_placeholder_count(item) for item in value)
    return 0


def _deep_normalize_candidate(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return value
    if isinstance(value, str):
        text = strip_code_fence(value)
        parsed = _try_parse_json_value(text)
        if parsed is None:
            return text
        return _deep_normalize_candidate(parsed, depth=depth + 1)
    if isinstance(value, list):
        mapped = _dict_from_variable_items(value)
        if mapped is not None:
            return _deep_normalize_candidate(mapped, depth=depth + 1)
        return [_deep_normalize_candidate(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _deep_normalize_candidate(item, depth=depth + 1)
            for key, item in value.items()
        }
    return value


def _parse_json_object_string(value: Any) -> dict[str, Any] | None:
    normalized = _deep_normalize_candidate(value)
    if isinstance(normalized, dict):
        return normalized
    return None


def _try_parse_json_value(value: Any) -> Any | None:
    if not isinstance(value, str):
        return None
    cleaned = strip_code_fence(value)
    if not cleaned:
        return None
    for parser in (parse_json, json.loads):
        try:
            parsed = parser(cleaned)
        except Exception:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed
        if isinstance(parsed, str):
            nested = strip_code_fence(parsed).strip()
            if nested.startswith("{") or nested.startswith("["):
                return parsed
    return None


def _dict_from_variable_items(values: list[Any]) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    matched_variable_shape = False
    for item in values:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        if isinstance(key, str) and key.strip():
            payload[key.strip()] = value
            matched_variable_shape = True
            continue
        variable = item.get("variable")
        if isinstance(variable, str) and variable.strip():
            payload[variable.strip()] = value
            matched_variable_shape = True
            continue
        if isinstance(variable, list) and variable:
            variable_key = str(variable[-1] or "").strip()
            if variable_key:
                payload[variable_key] = value
                matched_variable_shape = True
                continue
        name = item.get("name")
        if "value" in item and isinstance(name, str) and name.strip():
            payload[name.strip()] = value
            matched_variable_shape = True
    return payload if matched_variable_shape and payload else None


def _lowered_key_map(data: dict[str, Any]) -> dict[str, str]:
    return {str(key).lower(): str(key) for key in data.keys()}


def _match_alias_key(
    data: dict[str, Any],
    lowered: dict[str, str],
    aliases: tuple[str, ...],
) -> str | None:
    for alias in aliases:
        if alias in data:
            return alias
        actual = lowered.get(alias.lower())
        if actual is not None:
            return actual
    return None


def _coerce_nested_dict(value: Any) -> dict[str, Any]:
    normalized = _deep_normalize_candidate(value)
    return normalized if isinstance(normalized, dict) else {}


def _normalize_text_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "；".join(_normalize_string_list(value))
    if value is None:
        return ""
    return str(value).strip()


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = list(value.values())
    else:
        parsed = _try_parse_json_value(value) if isinstance(value, str) else None
        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, dict):
            items = list(parsed.values())
        else:
            text = _normalize_text_value(value)
            items = re.split(r"[；;\n,，、]+", text) if text else []
    return _dedupe_strings([str(item).strip() for item in items if str(item).strip()])


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _extract_text_candidate(value: Any) -> str:
    if isinstance(value, str):
        return strip_code_fence(value).strip()
    if isinstance(value, dict):
        for key in ("answerText", "answer", "response", "result", "content", "text", WORLDVIEW_FIELD, CHARACTERS_FIELD):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return strip_code_fence(nested).strip()
    return ""


def _extract_any_text(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    lowered = _lowered_key_map(data)
    for key in keys:
        actual = lowered.get(str(key).lower())
        if actual is None:
            continue
        text = _normalize_text_value(data.get(actual))
        if text:
            return text
    return ""


def _jsonish_dict(value: Any) -> dict[str, Any]:
    normalized = _deep_normalize_candidate(value)
    return normalized if isinstance(normalized, dict) else {}
