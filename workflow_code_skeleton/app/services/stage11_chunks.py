from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def episode_number(item: dict[str, Any], fallback: int = 0) -> int:
    raw = (
        item.get("episode")
        or item.get("episodeNumber")
        or item.get("episode_number")
        or item.get("episode_no")
        or fallback
    )
    match = re.search(r"\d+", str(raw or ""))
    return int(match.group(0)) if match else 0


def split_episode_plan(plan: list[dict[str, Any]], chunk_size: int = 1) -> list[list[dict[str, Any]]]:
    size = max(1, int(chunk_size or 1))
    return [plan[index:index + size] for index in range(0, len(plan), size)]


def stage11_input_fingerprint(plan: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_stage11_write_resume(
    path: Path,
    *,
    fingerprint: str,
    asset_id: str,
    start_episode: int,
    end_episode: int,
) -> dict[int, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict) or payload.get("status") not in {"partial", "complete"}:
        return {}
    if str(payload.get("fingerprint") or "") != str(fingerprint or ""):
        return {}
    if str(payload.get("asset_id") or "") != str(asset_id or ""):
        return {}
    if int(payload.get("start_episode") or 0) != int(start_episode or 0):
        return {}
    if int(payload.get("end_episode") or 0) != int(end_episode or 0):
        return {}

    plans: dict[int, dict[str, Any]] = {}
    for raw_key, plan in (payload.get("plans") or {}).items():
        if not isinstance(plan, dict):
            continue
        try:
            chunk_start = int(raw_key)
        except (TypeError, ValueError):
            continue
        if start_episode <= chunk_start <= end_episode:
            plans[chunk_start] = plan
    return plans


def save_stage11_write_resume(
    path: Path,
    *,
    status: str,
    fingerprint: str,
    asset_id: str,
    start_episode: int,
    end_episode: int,
    plans: dict[int, dict[str, Any]],
    updated_at: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": str(status or "partial"),
        "fingerprint": str(fingerprint or ""),
        "asset_id": str(asset_id or ""),
        "start_episode": int(start_episode or 0),
        "end_episode": int(end_episode or 0),
        "completed_chunk_starts": sorted(int(key) for key in plans),
        "plans": {str(key): plans[key] for key in sorted(plans)},
        "updated_at": str(updated_at or ""),
    }
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def compact_enriched_episode_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the semantic audit fields while removing duplicated display text."""
    allowed = {
        "episode",
        "title",
        "characters",
        "scene_refs",
        "scenes",
        "specific_plot",
        "pressure_sources",
        "ending_hook",
        "beat_refs",
        "character_storyline_refs",
        "alias_notes",
    }
    return [
        {key: copy.deepcopy(value) for key, value in item.items() if key in allowed}
        for item in plan
        if isinstance(item, dict)
    ]


def compact_appearance_mapping(
    mapping: dict[str, Any],
    relevant_names: list[str] | set[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        return {}
    relevant = {
        re.sub(r"[（(].*?[）)]", "", str(value or "")).strip().lower()
        for value in (relevant_names or [])
        if str(value or "").strip()
    }
    characters = []
    for item in mapping.get("characters") or []:
        if not isinstance(item, dict):
            continue
        item_names = {
            str(item.get(key) or "").strip().lower()
            for key in ("character_id", "name", "default_name", "canonical_name")
            if str(item.get(key) or "").strip()
        }
        if relevant and not (item_names & relevant):
            continue
        compact = {
            key: copy.deepcopy(item.get(key))
            for key in ("character_id", "name", "default_name", "canonical_name")
            if item.get(key) not in (None, "", [], {})
        }
        compact["outfit_version_ids"] = [
            str(version.get("version_id") or "").strip()
            for version in item.get("outfit_versions") or []
            if isinstance(version, dict) and str(version.get("version_id") or "").strip()
        ]
        compact["aliases"] = [
            str(rule.get("alias") or "").strip()
            for rule in item.get("alias_rules") or []
            if isinstance(rule, dict) and str(rule.get("alias") or "").strip()
        ]
        compact = {key: value for key, value in compact.items() if value not in (None, "", [], {})}
        characters.append(compact)
    result = {"characters": characters}
    for key in ("mapping_version", "naming_principle"):
        value = copy.deepcopy(mapping.get(key))
        if value not in (None, "", [], {}):
            result[key] = value
    return result


def compact_scene_dictionary(dictionary: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(dictionary, dict):
        return {}
    scene_keys = {
        "scene_id",
        "scene_ref",
        "scene_name",
        "name",
        "location",
        "common_characters",
        "key_props",
        "continuity_notes",
        "allowed_actions",
        "do_not_use_as",
    }
    compact_scenes = []
    for item in dictionary.get("core_scenes") or dictionary.get("coreScenes") or []:
        if isinstance(item, dict):
            compact_scenes.append(
                {key: copy.deepcopy(value) for key, value in item.items() if key in scene_keys}
            )
    return {
        key: value
        for key, value in {
            "dictionary_version": copy.deepcopy(dictionary.get("dictionary_version")),
            "core_scenes": compact_scenes,
            "global_continuity_rules": copy.deepcopy(dictionary.get("global_continuity_rules")),
        }.items()
        if value not in (None, "", [], {})
    }


def compact_conflict_plan_for_review(plan: dict[str, Any]) -> dict[str, Any]:
    """Create a bounded audit view without changing the saved full conflict plan."""
    if not isinstance(plan, dict):
        return {}
    episode_keys = {
        "episode",
        "episode_title",
        "active_characters",
        "scene_refs",
        "opening_alias_plan",
        "carry_in",
        "why_now",
        "character_motivation",
        "emotional_precondition",
        "scene_cause_chain",
        "non_conflict_moment",
        "natural_transition",
        "opening_image",
        "opening_action",
        "current_goal",
        "core_obstacle",
        "episode_state_change",
        "ending_hook",
        "dialogue_strategy",
    }
    result = {
        "batch_meta": copy.deepcopy(plan.get("batch_meta") or {}),
        "global_conflict_engine": copy.deepcopy(plan.get("global_conflict_engine") or {}),
        "episodes": [],
    }
    for episode in plan.get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        compact_episode = {
            key: copy.deepcopy(value)
            for key, value in episode.items()
            if key in episode_keys
        }
        compact_episode["opening_alias_plan"] = [
            {
                key: copy.deepcopy(value)
                for key, value in alias.items()
                if key in {"character_name", "opening_alias", "from_appearance_mapping"}
            }
            for alias in episode.get("opening_alias_plan") or []
            if isinstance(alias, dict)
        ]
        compact_episode["character_motivation"] = [
            {
                key: copy.deepcopy(value)
                for key, value in motivation.items()
                if key in {"character_name", "surface_goal", "deep_motivation", "immediate_pressure"}
            }
            for motivation in episode.get("character_motivation") or []
            if isinstance(motivation, dict)
        ]
        result["episodes"].append(compact_episode)
    return result


def merge_causal_conflict_plans(
    plans: list[dict[str, Any]],
    *,
    start_episode: int,
    end_episode: int,
) -> dict[str, Any]:
    if not plans:
        return {}
    episodes_by_number: dict[int, dict[str, Any]] = {}
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        for fallback, item in enumerate(plan.get("episodes") or [], start=start_episode):
            if not isinstance(item, dict):
                continue
            number = episode_number(item, fallback)
            if start_episode <= number <= end_episode:
                normalized = copy.deepcopy(item)
                normalized["episode"] = number
                episodes_by_number[number] = normalized
    expected = list(range(start_episode, end_episode + 1))
    if any(number not in episodes_by_number for number in expected):
        return {}

    first = plans[0]
    batch_meta = copy.deepcopy(first.get("batch_meta") or first.get("batchMeta") or {})
    batch_meta.update(
        {
            "start_episode": start_episode,
            "end_episode": end_episode,
            "episode_count": len(expected),
        }
    )
    global_engine = copy.deepcopy(
        first.get("global_conflict_engine")
        or first.get("globalConflictEngine")
        or {}
    )
    return {
        "batch_meta": batch_meta,
        "global_conflict_engine": global_engine,
        "episodes": [episodes_by_number[number] for number in expected],
    }
