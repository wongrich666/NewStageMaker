from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..workflow_ids import CHARACTER_VAR, WORLDVIEW_VAR
from .json_utils import parse_json, strip_code_fence

STAGE_WORLDVIEW = "worldview"
STAGE_CHARACTERS = "characters"
WORLDVIEW_FIELD = "worldview"
CHARACTERS_FIELD = "characters"
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
    return stage_name in {STAGE_WORLDVIEW, STAGE_CHARACTERS}


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
    return None


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


def _search_stage_body(
    candidate: Any,
    *,
    wrapper_keys: tuple[str, ...],
    detector,
    audit_detector,
    relaxed: bool,
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
            found = _search_stage_body(
                current.get(key),
                wrapper_keys=wrapper_keys,
                detector=detector,
                audit_detector=audit_detector,
                relaxed=relaxed,
                depth=depth + 1,
            )
            if found is not None:
                return found
        if len(current) == 1:
            only_value = next(iter(current.values()))
            found = _search_stage_body(
                only_value,
                wrapper_keys=wrapper_keys,
                detector=detector,
                audit_detector=audit_detector,
                relaxed=relaxed,
                depth=depth + 1,
            )
            if found is not None:
                return found
        if relaxed:
            for nested in current.values():
                found = _search_stage_body(
                    nested,
                    wrapper_keys=wrapper_keys,
                    detector=detector,
                    audit_detector=audit_detector,
                    relaxed=False,
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
    try:
        return parse_json(cleaned)
    except Exception:
        pass
    try:
        return json.loads(cleaned)
    except Exception:
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
