from __future__ import annotations

import json
import re
from typing import Any

from .json_utils import parse_json

DEFAULT_FORBIDDEN_GENERIC_NAMES = ("男主", "女主", "反派", "配角", "路人")


def build_compact_character_context_for_scenes(characters: Any) -> str:
    items = _extract_character_items(characters)
    payload = {
        "characters": [
            {
                "character_name": _text(item.get("character_name")),
                "story_role": _text(item.get("story_role")),
                "appearance": {
                    "overall_look": _nested_text(item, "appearance", "overall_look"),
                    "recognizable_features": _nested_list(item, "appearance", "recognizable_features", limit=3),
                },
                "behavior": {
                    "habitual_actions": _nested_list(item, "behavior", "habitual_actions", limit=2),
                },
                "dramatic_value_summary": _short_text(item.get("dramatic_value"), limit=120),
            }
            for item in items
            if _text(item.get("character_name"))
        ]
    }
    return _dump_json(payload)


def build_compact_character_context_for_appearance(characters: Any) -> str:
    items = _extract_character_items(characters)
    payload = {
        "characters": [
            {
                "character_name": _text(item.get("character_name")),
                "story_role": _text(item.get("story_role")),
                "appearance": {
                    "overall_look": _nested_text(item, "appearance", "overall_look"),
                    "recognizable_features": _nested_list(item, "appearance", "recognizable_features", limit=3),
                },
                "same_person_traits": _dedupe(
                    [
                        _nested_text(item, "appearance", "overall_look"),
                        *_nested_list(item, "appearance", "recognizable_features", limit=3),
                        *_nested_list(item, "behavior", "habitual_actions", limit=2),
                    ]
                )[:4],
                "default_name_candidate": _text(item.get("character_name")),
                "forbidden_generic_names": _dedupe(
                    [
                        *_string_list(item.get("forbidden_generic_names"), limit=4),
                        *DEFAULT_FORBIDDEN_GENERIC_NAMES,
                    ]
                )[:6],
            }
            for item in items
            if _text(item.get("character_name"))
        ]
    }
    return _dump_json(payload)


def build_compact_character_context_for_hooks(characters: Any) -> str:
    items = _extract_character_items(characters)
    payload = {
        "characters": [
            {
                "character_name": _text(item.get("character_name")),
                "story_role": _text(item.get("story_role")),
                "core_motivation": _short_text(item.get("core_motivation"), limit=120),
                "key_relations": _compact_relation_modes(item.get("relation_modes"), limit=2),
            }
            for item in items
            if _text(item.get("character_name"))
        ]
    }
    return _dump_json(payload)


def build_compact_character_context_for_dialogues(characters: Any) -> str:
    items = _extract_character_items(characters)
    payload = {
        "characters": [
            {
                "character_name": _text(item.get("character_name")),
                "story_role": _text(item.get("story_role")),
                "speech_profile": _compact_speech_profile(item.get("speech_profile")),
                "relation_modes": _compact_relation_modes(item.get("relation_modes"), limit=2),
            }
            for item in items
            if _text(item.get("character_name"))
        ]
    }
    return _dump_json(payload)


def build_compact_character_context_for_script(characters: Any) -> str:
    items = _extract_character_items(characters)
    payload = {
        "characters": [
            {
                "character_name": _text(item.get("character_name")),
                "story_role": _text(item.get("story_role")),
                "core_motivation": _short_text(item.get("core_motivation"), limit=100),
                "appearance_hint": _join_nonempty(
                    [
                        _nested_text(item, "appearance", "overall_look"),
                        "、".join(_nested_list(item, "appearance", "recognizable_features", limit=2)),
                    ],
                    sep="；",
                ),
                "speech_profile": _compact_speech_profile(item.get("speech_profile")),
                "key_relations": _compact_relation_modes(item.get("relation_modes"), limit=2),
            }
            for item in items
            if _text(item.get("character_name"))
        ]
    }
    return _dump_json(payload)


def build_compact_scene_context_for_appearance(scenes: Any) -> str:
    items = _extract_scene_items(scenes)
    payload = {
        "scenes": [
            {
                "scene_name": _text(item.get("scene_name")),
                "scene_type": _text(item.get("scene_type")),
                "scene_time_or_period": _text(item.get("scene_time_or_period")),
                "weather_or_environment_state": _text(item.get("weather_or_environment_state")),
                "visual_condition_summary": _short_text(item.get("visual_condition_summary"), limit=120),
                "identity_or_status_requirements": _string_list(item.get("identity_or_status_requirements"), limit=2),
                "styling_condition_summary": _short_text(item.get("styling_condition_summary"), limit=120),
                "naming_condition_summary": _short_text(item.get("naming_condition_summary"), limit=120),
                "conflict_potential_summary": "；".join(_string_list(item.get("conflict_potential"), limit=2)),
            }
            for item in items
            if _text(item.get("scene_name"))
        ]
    }
    return _dump_json(payload)


def build_compact_scene_context_for_script(scenes: Any) -> str:
    items = _extract_scene_items(scenes)
    payload = {
        "scenes": [
            {
                "scene_name": _text(item.get("scene_name")),
                "scene_type": _text(item.get("scene_type")),
                "story_function": _short_text(item.get("story_function"), limit=100),
                "visual_condition_summary": _short_text(item.get("visual_condition_summary"), limit=100),
                "identity_or_status_requirements": _string_list(item.get("identity_or_status_requirements"), limit=2),
                "styling_condition_summary": _short_text(item.get("styling_condition_summary"), limit=100),
                "naming_condition_summary": _short_text(item.get("naming_condition_summary"), limit=100),
                "conflict_potential_summary": "；".join(_string_list(item.get("conflict_potential"), limit=2)),
            }
            for item in items
            if _text(item.get("scene_name"))
        ]
    }
    return _dump_json(payload)


def build_compact_appearance_context_for_batch(appearance_plan: Any) -> str:
    plan = _extract_alias_plan(appearance_plan)
    payload = {
        "planning_scope": _text(plan.get("planning_scope")),
        "global_naming_style": _text(plan.get("global_naming_style")),
        "global_rules": _string_list(plan.get("global_rules"), limit=4),
        "episodes": [
            {
                "episode": _safe_int(item.get("episode")),
                "title": _text(item.get("title")),
                "main_character_aliases": [
                    {
                        "character_id": _text(alias.get("character_id")),
                        "character_name": _text(alias.get("character_name")),
                        "recommended_alias_name": _text(alias.get("recommended_alias_name")),
                        "reason": _short_text(alias.get("reason"), limit=80),
                    }
                    for alias in item.get("main_character_aliases") or []
                    if isinstance(alias, dict) and _text(alias.get("recommended_alias_name"))
                ],
                "appearance_events": _string_list(item.get("appearance_events"), limit=3),
                "scene_based_alias_hints": [
                    {
                        "character_id": _text(alias.get("character_id")),
                        "character_name": _text(alias.get("character_name")),
                        "recommended_alias_name": _text(alias.get("recommended_alias_name")),
                        "reason": _short_text(alias.get("reason"), limit=80),
                    }
                    for alias in item.get("scene_based_alias_hints") or []
                    if isinstance(alias, dict) and _text(alias.get("recommended_alias_name"))
                ],
            }
            for item in plan.get("episodes") or []
            if isinstance(item, dict) and _safe_int(item.get("episode")) > 0
        ],
        "scene_level_usage_plan": [
            {
                "scene_name": _text(item.get("scene_name")),
                "expected_alias_usage": [
                    {
                        "character_id": _text(alias.get("character_id")),
                        "character_name": _text(alias.get("character_name")),
                        "alias_name": _text(alias.get("alias_name") or alias.get("recommended_alias_name")),
                        "reason": _short_text(alias.get("reason"), limit=80),
                    }
                    for alias in item.get("expected_alias_usage") or []
                    if isinstance(alias, dict)
                    and _text(alias.get("alias_name") or alias.get("recommended_alias_name"))
                ],
            }
            for item in plan.get("scene_level_usage_plan") or []
            if isinstance(item, dict) and _text(item.get("scene_name"))
        ],
        "uncertain_or_missing_items": _string_list(plan.get("uncertain_or_missing_items"), limit=4),
    }
    return _dump_json(payload)


def build_compact_worldview_context(worldview: Any) -> str:
    body = _extract_worldview_body(worldview)
    payload = {
        "worldview_summary": _short_text(body.get("worldview_summary"), limit=180),
        "era_background": _short_text(body.get("era_background"), limit=100),
        "social_rules": _short_text(body.get("social_rules"), limit=120),
        "space_logic": _short_text(body.get("space_logic"), limit=120),
        "key_settings": _string_list(body.get("key_settings"), limit=3),
        "conflict_mechanisms": _string_list(body.get("conflict_mechanisms"), limit=3),
        "visual_keywords": _string_list(body.get("visual_keywords"), limit=4),
    }
    return _dump_json(payload)


def build_compact_story_outline_context(story_outline: Any) -> str:
    body = _extract_story_outline_body(story_outline)
    if not body:
        return _short_text(story_outline, limit=240)
    payload = {
        "opening": _short_text(body.get("opening"), limit=100),
        "inciting_incident": _short_text(body.get("inciting_incident"), limit=100),
        "middle_escalation": _short_text(body.get("middle_escalation"), limit=100),
        "final_climax": _short_text(body.get("final_climax"), limit=100),
        "ending_resolution": _short_text(body.get("ending_resolution"), limit=100),
        "theme": _short_text(body.get("theme"), limit=80),
    }
    return _dump_json(payload)


def _extract_character_items(value: Any) -> list[dict[str, Any]]:
    candidate = _jsonish(value)
    if isinstance(candidate, list):
        return [item for item in candidate if isinstance(item, dict)]
    if not isinstance(candidate, dict):
        return _extract_character_items_from_text(value)
    if isinstance(candidate.get("character_plan"), dict):
        candidate = candidate["character_plan"]
    if isinstance(candidate.get("character_setting"), dict):
        candidate = candidate["character_setting"]
    items = candidate.get("characters")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    items = candidate.get("main_characters")
    if isinstance(items, list):
        result = [_normalize_character_plan_item(item) for item in items if isinstance(item, dict)]
        return [item for item in result if item]
    protagonist = candidate.get("protagonist")
    if isinstance(protagonist, dict):
        item = _normalize_character_plan_item(protagonist, default_role="主角")
        return [item] if item else []
    return _extract_character_items_from_text(value)


def _normalize_character_plan_item(
    item: dict[str, Any],
    *,
    default_role: str = "",
) -> dict[str, Any]:
    name = _text(item.get("character_name") or item.get("name"))
    if not name:
        return {}
    story_role = _text(item.get("story_role") or item.get("role_type") or default_role)
    core_motivation = _text(
        item.get("core_motivation")
        or item.get("goal")
        or item.get("core_desire")
        or item.get("deep_motivation")
    )
    flaw = _text(item.get("flaw") or item.get("weaknesses"))
    arc = _text(item.get("arc") or item.get("growth_arc"))
    normalized: dict[str, Any] = {
        "character_name": name,
        "story_role": story_role or "角色设定",
        "core_motivation": core_motivation,
        "dramatic_value": _join_nonempty([core_motivation, flaw, arc], sep="；"),
    }
    speech_profile = item.get("speech_profile")
    if isinstance(speech_profile, dict):
        normalized["speech_profile"] = speech_profile
    elif _text(item.get("personality")):
        normalized["speech_profile"] = {
            "baseline_register": _short_text(item.get("personality"), limit=80),
            "sentence_rhythm": "",
            "keyword_habits": [],
            "conflict_style": "",
            "intimacy_style": "",
            "when_angry": "",
            "when_hiding_truth": "",
        }
    relation_modes = item.get("relation_modes")
    if isinstance(relation_modes, list):
        normalized["relation_modes"] = relation_modes
    elif _text(item.get("relationship_to_protagonist")):
        relation = _text(item.get("relationship_to_protagonist"))
        normalized["relation_modes"] = [
            {
                "target": "主角",
                "relation_type": _short_text(relation, limit=60),
                "default_posture": _short_text(relation, limit=80),
                "speech_difference": "",
                "conflict_trigger": "",
            }
        ]
    return normalized


def _extract_character_items_from_text(value: Any) -> list[dict[str, Any]]:
    text = _text(value)
    if not text:
        return []
    blocks = _split_character_text_blocks(text)
    items: list[dict[str, Any]] = []
    for block in blocks:
        item = _character_item_from_text_block(block)
        if item:
            items.append(item)
    return items


def _split_character_text_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current_heading = ""
    current_lines: list[str] = []
    for raw_line in text.replace("\r", "").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if _looks_like_character_text_heading(line):
            if current_heading:
                blocks.append({"heading": current_heading, "lines": current_lines[:]})
            current_heading = line
            current_lines = []
            continue
        if current_heading:
            current_lines.append(line)
            continue
        inline = _split_inline_character_line(line)
        if inline:
            blocks.append(inline)
    if current_heading:
        blocks.append({"heading": current_heading, "lines": current_lines[:]})
    return blocks


def _looks_like_character_text_heading(line: str) -> bool:
    text = _strip_list_marker(line)
    if not text:
        return False
    if text.startswith("【") and "】" in text:
        suffix = text.split("】", 1)[1].strip()
        return bool(suffix)
    if re.match(r"^[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9·]{1,12}[（(][^）)]{1,20}[）)]", text):
        return True
    return False


def _split_inline_character_line(line: str) -> dict[str, Any] | None:
    text = _strip_list_marker(line)
    match = re.match(
        r"^(?P<name>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9·]{1,12})(?:[（(](?P<role>[^）)]{1,20})[）)])?[：:]\s*(?P<body>.+)$",
        text,
    )
    if not match:
        return None
    role = _text(match.group("role"))
    body = _text(match.group("body"))
    lines = [body] if body else []
    heading = f"【{role or '角色'}】{match.group('name')}"
    return {"heading": heading, "lines": lines}


def _character_item_from_text_block(block: dict[str, Any]) -> dict[str, Any] | None:
    heading = _text(block.get("heading"))
    lines = [str(line).strip() for line in block.get("lines") or [] if str(line).strip()]
    name, role_hint = _parse_character_text_heading(heading)
    if not name:
        return None
    fields = _parse_character_text_fields(lines)
    body = "\n".join(lines).strip()
    story_role = _first_field(fields, "人物定位", "身份定位", "故事角色", "角色定位") or role_hint
    core_motivation = _first_field(fields, "核心欲望", "核心动机", "深层动机", "外部目标")
    dramatic_value = _first_field(fields, "主线作用", "戏剧价值", "人物小传", "关系特点")
    speech = _first_field(fields, "说话方式", "语言风格", "对白风格", "语气特点")
    relation = _first_field(fields, "关系特点", "与主角关系", "与其他主要角色关系")
    summary = _short_text(body, limit=220)
    item: dict[str, Any] = {
        "character_name": name,
        "story_role": _short_text(story_role or summary or "角色设定", limit=100),
        "core_motivation": _short_text(core_motivation or summary, limit=160),
        "dramatic_value": _short_text(dramatic_value or summary, limit=180),
    }
    if speech or summary:
        item["speech_profile"] = {
            "baseline_register": _short_text(speech or summary, limit=80),
            "sentence_rhythm": "",
            "keyword_habits": [],
            "conflict_style": "",
            "intimacy_style": "",
            "when_angry": "",
            "when_hiding_truth": "",
        }
    if relation:
        item["relation_modes"] = [
            {
                "target": "",
                "relation_type": _short_text(relation, limit=60),
                "default_posture": _short_text(relation, limit=80),
                "speech_difference": "",
                "conflict_trigger": "",
            }
        ]
    return item


def _parse_character_text_heading(heading: str) -> tuple[str, str]:
    text = _strip_list_marker(heading)
    match = re.match(r"^【(?P<label>[^】]+)】\s*(?P<name>.+)$", text)
    if match:
        name = re.split(r"[（(：:]", match.group("name"), maxsplit=1)[0].strip()
        return name, match.group("label").strip()
    match = re.match(r"^(?P<name>.+?)[（(](?P<role>[^）)]+)[）)]", text)
    if match:
        return match.group("name").strip(), match.group("role").strip()
    return re.split(r"[：:]", text, maxsplit=1)[0].strip(), ""


def _parse_character_text_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_key = ""
    for line in lines:
        match = re.match(r"^(?P<key>[^：:]{1,24})[:：]\s*(?P<value>.*)$", line)
        if match:
            current_key = match.group("key").strip()
            fields[current_key] = match.group("value").strip()
        elif current_key:
            fields[current_key] = f"{fields.get(current_key, '')}\n{line}".strip()
    return fields


def _first_field(fields: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = _text(fields.get(key))
        if value:
            return value
    return ""


def _strip_list_marker(line: str) -> str:
    return re.sub(r"^\s*(?:[-*•]\s*|\d+[.、]\s*)", "", _text(line)).strip()


def _extract_scene_items(value: Any) -> list[dict[str, Any]]:
    candidate = _jsonish(value)
    if not isinstance(candidate, dict):
        return []
    if isinstance(candidate.get("scenes"), dict) and isinstance(
        candidate["scenes"].get("scene_setting"),
        dict,
    ):
        candidate = candidate["scenes"]["scene_setting"]
    elif isinstance(candidate.get("scene_setting"), dict):
        candidate = candidate["scene_setting"]
    items = candidate.get("scenes")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def _extract_alias_plan(value: Any) -> dict[str, Any]:
    candidate = _jsonish(value)
    if not isinstance(candidate, dict):
        return {}
    episodes = candidate.get("episodes")
    if not isinstance(episodes, list):
        return {}
    return candidate


def _extract_worldview_body(value: Any) -> dict[str, Any]:
    candidate = _jsonish(value)
    if not isinstance(candidate, dict):
        return {}
    if isinstance(candidate.get("worldview"), dict):
        return candidate["worldview"]
    return candidate


def _extract_story_outline_body(value: Any) -> dict[str, Any]:
    candidate = _jsonish(value)
    if isinstance(candidate, dict):
        return candidate
    return {}


def _compact_speech_profile(value: Any) -> dict[str, Any]:
    profile = _jsonish(value)
    if not isinstance(profile, dict):
        return {}
    return {
        "baseline_register": _short_text(profile.get("baseline_register"), limit=60),
        "sentence_rhythm": _short_text(profile.get("sentence_rhythm"), limit=60),
        "keyword_habits": _string_list(profile.get("keyword_habits"), limit=3),
        "conflict_style": _short_text(profile.get("conflict_style"), limit=60),
        "intimacy_style": _short_text(profile.get("intimacy_style"), limit=60),
        "when_angry": _short_text(profile.get("when_angry"), limit=60),
        "when_hiding_truth": _short_text(profile.get("when_hiding_truth"), limit=60),
    }


def _compact_relation_modes(value: Any, *, limit: int) -> list[dict[str, Any]]:
    items = _jsonish(value)
    if not isinstance(items, list):
        return []
    compacted: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                "target": _text(item.get("target")),
                "relation_type": _short_text(item.get("relation_type"), limit=40),
                "default_posture": _short_text(item.get("default_posture"), limit=70),
                "speech_difference": _short_text(item.get("speech_difference"), limit=70),
                "conflict_trigger": _short_text(item.get("conflict_trigger"), limit=70),
            }
        )
        if len(compacted) >= max(1, limit):
            break
    return [item for item in compacted if item["target"] or item["relation_type"]]


def _nested_text(item: dict[str, Any], key: str, nested_key: str) -> str:
    nested = item.get(key)
    if not isinstance(nested, dict):
        return ""
    return _text(nested.get(nested_key))


def _nested_list(item: dict[str, Any], key: str, nested_key: str, *, limit: int) -> list[str]:
    nested = item.get(key)
    if not isinstance(nested, dict):
        return []
    return _string_list(nested.get(nested_key), limit=limit)


def _jsonish(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return parse_json(text)
    except Exception:
        return None


def _dump_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _short_text(value: Any, *, limit: int) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _safe_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _short_text(item, limit=60)
        if text:
            result.append(text)
        if len(result) >= max(1, limit):
            break
    return result


def _join_nonempty(parts: list[str], *, sep: str) -> str:
    return sep.join(part for part in parts if part)


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
