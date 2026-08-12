from __future__ import annotations

import copy
import json
import re
from typing import Any

from .workflow_output_parser import parse_workflow_output


SCHEMA_VERSION = "character_image_prompt_v1"
MAX_USER_REQUIREMENTS_CHARS = 2000
MAX_CONTEXT_CHARS = 18000


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_dict(container: dict[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        value = container.get(name)
        if isinstance(value, dict) and value:
            return value
    return {}


def _first_list(container: dict[str, Any], *names: str) -> list[Any]:
    for name in names:
        value = container.get(name)
        if isinstance(value, list) and value:
            return value
    return []


def _character_key(value: Any) -> str:
    text = _text(value).lower()
    text = re.sub(r"[（(][a-z0-9_-]+[）)]$", "", text, flags=re.IGNORECASE)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _dedupe_strings(values: list[Any], *, limit: int = 100) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value)
        key = text.lower()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _asset_sources(asset: dict[str, Any]) -> dict[str, Any]:
    package = _first_dict(asset, "framework_plan_package", "frameworkPlanPackage")
    stage_outputs = _dict(asset.get("stage_outputs"))
    state = _dict(asset.get("framework_to_script_state"))
    script_stages = (
        _first_dict(asset, "scriptStages", "script_stages")
        or _first_dict(state, "scriptStages", "script_stages")
    )
    character_plan = (
        _first_dict(package, "character_plan", "characterPlan")
        or _first_dict(stage_outputs, "character_plan", "characterPlan")
        or _first_dict(_dict(stage_outputs.get("stage03")), "character_plan", "characterPlan")
    )
    worldview = (
        _first_dict(package, "worldview_plan", "worldviewPlan")
        or _first_dict(stage_outputs, "worldview_plan", "worldviewPlan")
    )
    stage08 = _first_dict(script_stages, "stage08", "08")
    stage09 = _first_dict(script_stages, "stage09", "09")
    stage10 = _first_dict(script_stages, "stage10", "10")
    stage12 = _first_dict(script_stages, "stage12", "12")
    scene_dictionary = (
        _first_dict(stage08, "sceneDictionary", "scene_dictionary")
        or _first_dict(stage_outputs, "sceneDictionary", "scene_dictionary")
    )
    appearance_mapping = (
        _first_dict(stage09, "appearanceMapping", "appearance_mapping")
        or _first_dict(stage_outputs, "appearanceMapping", "appearance_mapping")
    )
    episode_plan = (
        _first_list(stage10, "allEnrichedEpisodePlan", "all_enriched_episode_plan", "enrichedEpisodePlan")
        or _first_list(stage_outputs, "allEnrichedEpisodePlan", "all_enriched_episode_plan")
    )
    return {
        "package": package,
        "character_plan": character_plan,
        "worldview": worldview,
        "scene_dictionary": scene_dictionary,
        "appearance_mapping": appearance_mapping,
        "episode_plan": episode_plan,
        "stage12": stage12,
    }


def _outfits(appearance: dict[str, Any]) -> list[dict[str, Any]]:
    raw = _first_list(appearance, "outfit_variants", "outfit_versions", "outfits")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        outfit_id = _text(
            item.get("outfit_version_id")
            or item.get("variant_id")
            or item.get("version_id")
            or item.get("id"),
            f"outfit_{index}",
        )
        key = outfit_id.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "outfit_id": outfit_id,
                "outfit_name": _text(item.get("version_name") or item.get("name"), outfit_id),
                "episode_range": _text(item.get("episode_range")),
                "trigger_condition": _text(item.get("trigger_condition")),
                "clothing": _text(item.get("clothing") or item.get("outfit_description")),
                "visual_anchor": _text(item.get("visual_anchor")),
                "scene_refs": _dedupe_strings(
                    _list(item.get("scene_refs")) + _list(item.get("scene_trigger_rules")),
                    limit=20,
                ),
                "usage_rule": _text(item.get("usage_rule")),
                "forbidden_confusion": _text(item.get("forbidden_confusion")),
            }
        )
    return result


def extract_character_catalog(asset: dict[str, Any]) -> dict[str, Any]:
    sources = _asset_sources(asset)
    character_plan = sources["character_plan"]
    appearance_mapping = sources["appearance_mapping"]
    base_characters = _first_list(character_plan, "characters", "main_characters")
    appearance_characters = _first_list(appearance_mapping, "characters", "character_mappings")

    base_by_key: dict[str, dict[str, Any]] = {}
    for item in base_characters:
        if not isinstance(item, dict):
            continue
        for identity in (item.get("id"), item.get("character_id"), item.get("name")):
            if key := _character_key(identity):
                base_by_key.setdefault(key, item)

    appearance_by_key: dict[str, dict[str, Any]] = {}
    for item in appearance_characters:
        if not isinstance(item, dict):
            continue
        for identity in (
            item.get("character_id"), item.get("canonical_name"), item.get("name"), item.get("default_name")
        ):
            if key := _character_key(identity):
                appearance_by_key.setdefault(key, item)

    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    consumed_appearance: set[int] = set()
    seen_base: set[int] = set()
    for base in base_characters:
        if not isinstance(base, dict) or id(base) in seen_base:
            continue
        seen_base.add(id(base))
        keys = [_character_key(base.get(name)) for name in ("id", "character_id", "name")]
        appearance = next((appearance_by_key[key] for key in keys if key in appearance_by_key), {})
        if appearance:
            consumed_appearance.add(id(appearance))
        candidates.append((base, appearance))
    for appearance in appearance_characters:
        if isinstance(appearance, dict) and id(appearance) not in consumed_appearance:
            keys = [_character_key(appearance.get(name)) for name in ("character_id", "canonical_name", "name")]
            base = next((base_by_key[key] for key in keys if key in base_by_key), {})
            candidates.append((base, appearance))

    characters: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, (base, appearance) in enumerate(candidates, start=1):
        character_id = _text(
            appearance.get("character_id")
            or base.get("id")
            or base.get("character_id")
            or appearance.get("canonical_name"),
            f"character_{index}",
        )
        character_name = _text(
            appearance.get("name") or appearance.get("default_name") or base.get("name"),
            character_id,
        )
        unique_id = character_id
        suffix = 2
        while unique_id.lower() in seen_ids:
            unique_id = f"{character_id}_{suffix}"
            suffix += 1
        seen_ids.add(unique_id.lower())
        characters.append(
            {
                "character_id": unique_id,
                "character_name": character_name,
                "role_type": _text(appearance.get("role_type") or base.get("role")),
                "identity": _text(appearance.get("identity") or base.get("identity")),
                "appearance_anchor": _text(appearance.get("appearance_anchor")),
                "outfits": _outfits(appearance),
                "source_status": {
                    "has_original_profile": bool(base),
                    "has_appearance_mapping": bool(appearance),
                },
            }
        )

    return {
        "asset_id": _text(asset.get("asset_id") or asset.get("project_id")),
        "project_title": _text(asset.get("title") or asset.get("source_title"), "未命名项目"),
        "characters": characters,
        "source_status": {
            "has_character_plan": bool(character_plan),
            "has_scene_dictionary": bool(sources["scene_dictionary"]),
            "has_appearance_mapping": bool(appearance_mapping),
            "has_episode_plan": bool(sources["episode_plan"]),
            "has_script_text": bool(sources["stage12"]),
        },
    }


def _selected_character(asset: dict[str, Any], character_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    sources = _asset_sources(asset)
    catalog = extract_character_catalog(asset)
    public = next(
        (
            item for item in catalog["characters"]
            if _text(item.get("character_id")).lower() == _text(character_id).lower()
        ),
        None,
    )
    if not public:
        raise ValueError("没有在该资产中找到所选角色。")
    target_keys = {
        _character_key(public.get("character_id")),
        _character_key(public.get("character_name")),
    }
    base = next(
        (
            item for item in _first_list(sources["character_plan"], "characters", "main_characters")
            if isinstance(item, dict)
            and target_keys.intersection(
                {_character_key(item.get("id")), _character_key(item.get("character_id")), _character_key(item.get("name"))}
            )
        ),
        {},
    )
    appearance = next(
        (
            item for item in _first_list(sources["appearance_mapping"], "characters", "character_mappings")
            if isinstance(item, dict)
            and target_keys.intersection(
                {
                    _character_key(item.get("character_id")), _character_key(item.get("canonical_name")),
                    _character_key(item.get("name")), _character_key(item.get("default_name")),
                }
            )
        ),
        {},
    )
    return {"public": public, "base": base, "appearance": appearance}, sources


def _script_texts(stage12: dict[str, Any]) -> list[str]:
    values: list[str] = []
    batches = _dict(stage12.get("batches"))
    for key in sorted(batches, key=lambda item: int(item) if str(item).isdigit() else 10**9):
        batch = _dict(batches.get(key))
        value = _text(batch.get("batchScriptText") or batch.get("batch_script_text"))
        if value:
            values.append(value)
    if not values:
        value = _text(stage12.get("batchScriptText") or stage12.get("batch_script_text"))
        if value:
            values.append(value)
    return _dedupe_strings(values, limit=200)


def _script_props_for_character(stage12: dict[str, Any], character_name: str) -> list[str]:
    props: list[str] = []
    section_pattern = re.compile(r"(?m)^\s*(?:#{1,6}\s*)?第\s*[0-9０-９一二三四五六七八九十百]+\s*集[^\r\n]*$")
    prop_pattern = re.compile(r"(?mi)^\s*(?:关键道具|核心道具|道具)\s*[：:]\s*(.+?)\s*$")
    name_key = _character_key(character_name)
    for text in _script_texts(stage12):
        matches = list(section_pattern.finditer(text))
        sections = []
        if matches:
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                sections.append(text[match.start():end])
        else:
            sections = [text]
        for section in sections:
            if name_key and name_key not in _character_key(section):
                continue
            props.extend(match.group(1) for match in prop_pattern.finditer(section))
    return _dedupe_strings(props, limit=80)


def _bounded_json(value: Any, *, limit: int = MAX_CONTEXT_CHARS) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text) <= limit:
        return text
    if isinstance(value, list):
        reduced = copy.deepcopy(value)
        while len(reduced) > 1 and len(json.dumps(reduced, ensure_ascii=False, separators=(",", ":"))) > limit:
            reduced.pop()
        text = json.dumps(reduced, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text) > limit:
        raise ValueError("角色出图上下文超过工作流安全长度，请减少资产中的重复字段。")
    return text


def build_character_image_prompt_inputs(
    asset: dict[str, Any],
    *,
    character_id: str,
    selected_outfit_id: str = "",
    user_visual_requirements: str = "",
) -> tuple[dict[str, str], dict[str, Any]]:
    selected, sources = _selected_character(asset, character_id)
    public = selected["public"]
    base = selected["base"]
    appearance = selected["appearance"]
    requirements = _text(user_visual_requirements)
    if len(requirements) > MAX_USER_REQUIREMENTS_CHARS:
        raise ValueError(f"人物形象要求不能超过 {MAX_USER_REQUIREMENTS_CHARS} 个字符。")

    outfits = _outfits(appearance)
    outfit_id = _text(selected_outfit_id)
    selected_outfit = next((item for item in outfits if item["outfit_id"].lower() == outfit_id.lower()), None)
    if outfit_id and not selected_outfit:
        raise ValueError("所选服饰版本不存在，请重新选择。")
    if not selected_outfit and outfits:
        selected_outfit = outfits[0]
        outfit_id = selected_outfit["outfit_id"]

    source_profile_fields = (
        "id", "name", "role", "identity", "external_goal", "internal_need", "ability_or_resource",
        "weakness", "growth_arc", "story_function", "relationship_hooks", "forbidden_write",
    )
    appearance_fields = (
        "character_id", "name", "default_name", "role_type", "identity", "personality", "core_desire",
        "deep_motivation", "strengths", "weaknesses", "growth_arc", "plot_function", "appearance_anchor",
        "voice_hint", "continuity_notes", "forbidden_write",
    )
    source_profile = {key: copy.deepcopy(base.get(key)) for key in source_profile_fields if base.get(key) not in (None, "", [], {})}
    appearance_profile = {
        key: copy.deepcopy(appearance.get(key))
        for key in appearance_fields
        if appearance.get(key) not in (None, "", [], {})
    }
    appearance_profile["selected_outfit"] = selected_outfit or {}
    appearance_profile["available_outfits"] = outfits

    name_keys = {_character_key(public["character_name"]), _character_key(public["character_id"])}
    episode_candidates: list[dict[str, Any]] = []
    scene_refs: list[Any] = list((selected_outfit or {}).get("scene_refs") or [])
    for item in sources["episode_plan"]:
        if not isinstance(item, dict):
            continue
        characters = _list(item.get("characters"))
        if not any(_character_key(value) in name_keys for value in characters):
            continue
        scene_refs.extend(_list(item.get("scene_refs")))
        outfit_match = False
        if outfit_id:
            suffix_pattern = re.compile(rf"[（(]\s*{re.escape(outfit_id)}\s*[）)]\s*$", re.IGNORECASE)
            outfit_match = any(
                _character_key(value) in name_keys and bool(suffix_pattern.search(_text(value)))
                for value in characters
            )
        episode_candidates.append(
            {
                "episode": item.get("episode"),
                "title": _text(item.get("title")),
                "characters": characters,
                "scene_refs": _list(item.get("scene_refs")),
                "scenes": _list(item.get("scenes")),
                "alias_notes": _text(item.get("alias_notes"))[:500],
                "specific_plot": _text(item.get("specific_plot"))[:500],
                "_selected_outfit_match": outfit_match,
            }
        )
    preferred_episodes = [item for item in episode_candidates if item["_selected_outfit_match"]]
    episode_pool = preferred_episodes or episode_candidates
    if len(episode_pool) <= 12:
        related_episodes = episode_pool
    else:
        sampled_indices = sorted({round(index * (len(episode_pool) - 1) / 11) for index in range(12)})
        related_episodes = [episode_pool[index] for index in sampled_indices]
    for item in related_episodes:
        item.pop("_selected_outfit_match", None)
    scene_ref_set = {str(value).strip().lower() for value in scene_refs if str(value).strip()}
    related_scenes: list[dict[str, Any]] = []
    scene_props: list[Any] = []
    for scene in _first_list(sources["scene_dictionary"], "core_scenes", "scenes"):
        if not isinstance(scene, dict):
            continue
        scene_id = _text(scene.get("scene_id") or scene.get("id")).lower()
        scene_name = _text(scene.get("name")).lower()
        common_characters = {_character_key(value) for value in _list(scene.get("common_characters"))}
        is_related = (
            scene_id in scene_ref_set
            or scene_name in scene_ref_set
            or bool(name_keys.intersection(common_characters))
        )
        if not is_related:
            continue
        scene_props.extend(_list(scene.get("key_props")))
        related_scenes.append(
            {
                key: copy.deepcopy(scene.get(key))
                for key in (
                    "scene_id", "name", "scene_type", "visual_anchor", "dramatic_function", "common_characters",
                    "usable_episode_range", "key_props", "rules_or_limits", "continuity_notes",
                )
                if scene.get(key) not in (None, "", [], {})
            }
        )

    script_props = _script_props_for_character(sources["stage12"], public["character_name"])
    worldview = {
        key: copy.deepcopy(sources["worldview"].get(key))
        for key in ("world_type", "core_setting", "tone", "visual_style", "space_logic", "core_rules")
        if sources["worldview"].get(key) not in (None, "", [], {})
    }
    scene_prop_context = {
        "world_visual_context": worldview,
        "related_scenes": related_scenes[:12],
        "scene_key_props": _dedupe_strings(scene_props, limit=80),
        "script_props": script_props,
        "episode_visual_evidence": related_episodes,
    }
    variables = {
        "project_title": _text(asset.get("title") or asset.get("source_title"), "未命名项目"),
        "character_name": public["character_name"],
        "user_visual_requirements": requirements,
        "character_source_profile": _bounded_json(source_profile, limit=14000),
        "appearance_mapping": _bounded_json(appearance_profile, limit=16000),
        "scene_prop_context": _bounded_json(scene_prop_context, limit=MAX_CONTEXT_CHARS),
        "selected_outfit_id": outfit_id,
    }
    summary = {
        "character": public,
        "selected_outfit": selected_outfit or {},
        "related_scene_count": len(related_scenes),
        "related_episode_count": len(related_episodes),
        "prop_count": len(scene_prop_context["scene_key_props"]) + len(script_props),
        "input_char_lengths": {key: len(value) for key, value in variables.items()},
    }
    return variables, summary


def _extract_prompt_payload(raw: Any) -> dict[str, Any]:
    value = parse_workflow_output(raw)
    keys = (
        "character_image_prompt", "characterImagePrompt", "image_prompt", "imagePrompt", "Output", "output",
        "content", "Content", "result", "data", "text",
    )
    seen: set[int] = set()
    for _ in range(12):
        if isinstance(value, dict):
            if value.get("schema_version") == SCHEMA_VERSION or "positive_prompt" in value:
                return value
            if id(value) in seen:
                break
            seen.add(id(value))
            nested = next((value[key] for key in keys if key in value and value[key] not in (None, "", [], {})), None)
            if nested is None and len(value) == 1:
                nested = next(iter(value.values()))
            if nested is None:
                break
            value = nested
        elif isinstance(value, str):
            parsed = parse_workflow_output(value)
            if parsed == value:
                break
            value = parsed
        elif isinstance(value, list) and value:
            value = value[0]
        else:
            break
    raise ValueError("角色出图提示词工作流未返回可解析的 JSON。")


def normalize_character_image_prompt(raw: Any, *, expected_character: dict[str, Any]) -> dict[str, Any]:
    payload = _extract_prompt_payload(raw)
    positive_prompt = _text(payload.get("positive_prompt") or payload.get("prompt"))
    if not positive_prompt:
        raise ValueError("角色出图提示词工作流缺少 positive_prompt。")
    continuity = _dict(payload.get("continuity_lock"))
    views: list[dict[str, str]] = []
    for item in _list(payload.get("recommended_views")):
        if isinstance(item, dict) and _text(item.get("prompt_suffix")):
            views.append(
                {
                    "view_type": _text(item.get("view_type"), "补充视图"),
                    "prompt_suffix": _text(item.get("prompt_suffix")),
                }
            )
    returned_schema = _text(payload.get("schema_version"))
    if returned_schema != SCHEMA_VERSION:
        raise ValueError(f"角色出图提示词 schema_version 必须是 {SCHEMA_VERSION}。")
    expected_name = _text(expected_character.get("character_name"))
    returned_name = _text(payload.get("character_name"))
    if returned_name and expected_name and _character_key(returned_name) != _character_key(expected_name):
        raise ValueError(f"工作流返回了错误角色：期望 {expected_name}，实际 {returned_name}。")
    return {
        "schema_version": SCHEMA_VERSION,
        "character_id": _text(expected_character.get("character_id"), _text(payload.get("character_id"))),
        "character_name": expected_name or returned_name,
        "outfit_id": _text(expected_character.get("outfit_id"), _text(payload.get("outfit_id"))),
        "design_summary": _text(payload.get("design_summary")),
        "positive_prompt": positive_prompt,
        "negative_prompt": _text(payload.get("negative_prompt")),
        "continuity_lock": {
            "immutable_features": _dedupe_strings(_list(continuity.get("immutable_features")), limit=30),
            "outfit_features": _dedupe_strings(_list(continuity.get("outfit_features")), limit=30),
            "forbidden_drift": _dedupe_strings(_list(continuity.get("forbidden_drift")), limit=30),
        },
        "recommended_views": views[:8],
        "design_notes": _dedupe_strings(_list(payload.get("design_notes")), limit=30),
        "source_trace": _dict(payload.get("source_trace")),
    }


def generate_character_image_prompt(
    asset: dict[str, Any],
    *,
    character_id: str,
    selected_outfit_id: str = "",
    user_visual_requirements: str = "",
    client: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    variables, summary = build_character_image_prompt_inputs(
        asset,
        character_id=character_id,
        selected_outfit_id=selected_outfit_id,
        user_visual_requirements=user_visual_requirements,
    )
    if client is None:
        from .tencent_workflow_client import tencent_workflow_client

        client = tencent_workflow_client
    raw = client.run_raw("character_image_prompt", variables)
    expected = {
        "character_id": summary["character"]["character_id"],
        "character_name": summary["character"]["character_name"],
        "outfit_id": _text(summary.get("selected_outfit", {}).get("outfit_id")),
    }
    return normalize_character_image_prompt(raw, expected_character=expected), summary
