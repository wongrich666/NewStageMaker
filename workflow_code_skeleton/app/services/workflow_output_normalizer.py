from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .json_utils import strip_code_fence


DISPLAY_TEXT_KEYS = (
    "display_text",
    "displayText",
    "readable_text",
    "readableText",
    "summary",
    "overview",
    "explanation",
    "description",
    "text",
)
TEXT_CONTAINER_KEYS = (
    "answerText",
    "textOutput",
    "content",
    "message",
    "text",
    "output",
    "data",
    "result",
    "response",
)
NESTED_CONTAINER_KEYS = (
    "data",
    "output",
    "newVariables",
    "variables",
    "responseData",
    "updateVarResult",
    "outputs",
    "result",
    "parsed",
)
RAW_DEBUG_KEYS = {
    "raw_result",
    "raw_response",
    "_normalizer_debug",
    "workflow_output_normalization",
}
OUTPUT_FORMAT_INSTRUCTION = (
    "Return exactly one JSON object for this stage. Do not wrap it in markdown fences, "
    "do not output ```json, and do not add explanatory text before or after the JSON. "
    "Use the expected business field names for the current stage plus display_text."
)


@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    aliases: tuple[str, ...]
    kind: str = "object"
    mirror_to: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StageOutputSpec:
    canonical_stage: str
    stage_aliases: tuple[str, ...]
    fields: tuple[FieldSpec, ...]


STAGE_OUTPUT_SPECS: tuple[StageOutputSpec, ...] = (
    StageOutputSpec(
        canonical_stage="stage_01",
        stage_aliases=("stage_01", "01", "basic", "source_brief"),
        fields=(
            FieldSpec("source_brief", ("source_brief", "sourceBrief", "confirmed_info", "confirmedInfo"), "object"),
        ),
    ),
    StageOutputSpec(
        canonical_stage="stage_02",
        stage_aliases=("stage_02", "02", "worldview", "worldview_plan"),
        fields=(
            FieldSpec("worldview_plan", ("worldview_plan", "worldviewPlan", "worldview"), "object"),
        ),
    ),
    StageOutputSpec(
        canonical_stage="stage_03",
        stage_aliases=("stage_03", "03", "character", "character_plan"),
        fields=(
            FieldSpec("character_plan", ("character_plan", "characterPlan", "character"), "object"),
        ),
    ),
    StageOutputSpec(
        canonical_stage="stage_04",
        stage_aliases=("stage_04", "04", "beat", "beat_checkpoint"),
        fields=(
            FieldSpec("beat_checkpoint", ("beat_checkpoint", "beatCheckpoint", "beat", "checkpoint"), "object"),
            FieldSpec(
                "beat_checkpoint_timeline",
                ("beat_checkpoint_timeline", "beatCheckpointTimeline", "timeline", "beats"),
                "list",
            ),
            FieldSpec(
                "checkpoint_explanation",
                ("checkpoint_explanation", "checkpointExplanation", "explanation", "beat_explanation"),
                "object",
            ),
        ),
    ),
    StageOutputSpec(
        canonical_stage="stage_05",
        stage_aliases=("stage_05", "05", "storylines", "storyline"),
        fields=(
            FieldSpec("character_storylines", ("character_storylines", "characterStorylines", "storylines", "storyline"), "list"),
            FieldSpec("storyline_decisions", ("storyline_decisions", "storylineDecisions", "decisions"), "list"),
        ),
    ),
    StageOutputSpec(
        canonical_stage="stage_06",
        stage_aliases=("stage_06", "06", "guide", "adaptation_guide"),
        fields=(
            FieldSpec(
                "adaptation_guide",
                (
                    "adaptation_guide",
                    "adaptationGuide",
                    "overallAdaptationGuide",
                    "overall_adaptation_guide",
                    "adaptation",
                    "guide",
                ),
                "object",
            ),
        ),
    ),
    StageOutputSpec(
        canonical_stage="stage_07",
        stage_aliases=("stage_07", "07", "package", "framework_plan_package"),
        fields=(
            FieldSpec("framework_plan_package", ("framework_plan_package", "frameworkPlanPackage", "framework", "package"), "object"),
            FieldSpec("validation_report", ("validation_report", "validationReport", "validation"), "object"),
        ),
    ),
    StageOutputSpec(
        canonical_stage="stage_08",
        stage_aliases=("stage_08", "08", "scene", "framework_scene_dictionary", "scene_dictionary"),
        fields=(
            FieldSpec("sceneDictionary", ("sceneDictionary", "scene_dictionary", "scene", "scenes"), "object", ("scene_dictionary",)),
            FieldSpec(
                "scriptWorldRulesDigest",
                ("scriptWorldRulesDigest", "script_world_rules_digest", "world_rules_digest"),
                "object",
                ("script_world_rules_digest",),
            ),
        ),
    ),
    StageOutputSpec(
        canonical_stage="stage_09",
        stage_aliases=("stage_09", "09", "appearance", "framework_appearanceMapping", "framework_appearance_mapping"),
        fields=(
            FieldSpec(
                "appearanceMapping",
                ("appearanceMapping", "appearance_mapping", "appearance_alias_map", "alias", "appearance"),
                "object",
                ("appearance_mapping", "appearance_alias_map"),
            ),
        ),
    ),
    StageOutputSpec(
        canonical_stage="stage_10",
        stage_aliases=("stage_10", "10", "episode", "framework_enriched_episode_plan"),
        fields=(
            FieldSpec(
                "allEnrichedEpisodePlan",
                (
                    "allEnrichedEpisodePlan",
                    "all_enriched_episode_plan",
                    "enriched_episode_plan",
                    "episode_plan",
                    "episodeplan",
                ),
                "list",
                ("all_enriched_episode_plan", "enriched_episode_plan"),
            ),
            FieldSpec(
                "allEnrichedEpisodePlanText",
                ("allEnrichedEpisodePlanText", "all_enriched_episode_plan_text", "enriched_episode_plan_text"),
                "string",
                ("all_enriched_episode_plan_text",),
            ),
        ),
    ),
    StageOutputSpec(
        canonical_stage="stage_11",
        stage_aliases=(
            "stage_11",
            "stage_11_write",
            "stage_11_review",
            "stage_11_rewrite",
            "stage_11_memory",
            "11",
            "conflict",
            "framework_causal_conflict",
            "framework_causal_conflict_write",
            "framework_causal_conflict_review",
            "framework_causal_conflict_rewrite",
            "framework_causal_conflict_memory",
        ),
        fields=(
            FieldSpec(
                "batchCausalConflictPlan",
                ("batchCausalConflictPlan", "batch_causal_conflict_plan", "conflict_plan", "conflicts", "conflict"),
                "object",
                ("batch_causal_conflict_plan", "conflict_plan"),
            ),
            FieldSpec(
                "batchCausalConflictReview",
                ("batchCausalConflictReview", "batch_causal_conflict_review", "conflict_review", "conflictreview"),
                "object",
                ("batch_causal_conflict_review",),
            ),
            FieldSpec("conflictMemory", ("conflictMemory", "conflict_memory", "memory"), "string", ("conflict_memory",)),
        ),
    ),
    StageOutputSpec(
        canonical_stage="stage_12",
        stage_aliases=(
            "stage_12",
            "stage_12_write",
            "stage_12_review",
            "stage_12_rewrite",
            "stage_12_memory",
            "12",
            "script_text",
            "framework_script_write",
            "framework_script_review",
            "framework_script_rewrite",
            "framework_script_memory",
        ),
        fields=(
            FieldSpec("batchScriptText", ("batchScriptText", "batch_script_text", "script_text", "scripts", "script"), "string", ("batch_script_text",)),
            FieldSpec("batchScriptReview", ("batchScriptReview", "batch_script_review", "script_review", "scriptreview"), "object", ("batch_script_review",)),
            FieldSpec("scriptMemory", ("scriptMemory", "script_memory", "memory"), "string", ("script_memory",)),
        ),
    ),
)


def normalize_stage_output(
    stage_key: str,
    raw_result: Any,
    payload: dict[str, Any] | None = None,
    *,
    backend: str = "",
    backend_stage_key: str = "",
) -> dict[str, Any]:
    spec = stage_output_spec(stage_key or backend_stage_key)
    warnings: list[str] = []
    attempts: list[str] = []
    candidates = list(_iter_candidates(raw_result, attempts=attempts))
    normalized: dict[str, Any] = {}

    if isinstance(raw_result, dict):
        for key, value in raw_result.items():
            if key in RAW_DEBUG_KEYS:
                continue
            normalized[key] = value

    display_text = _find_display_text(candidates)
    matched_paths: list[str] = []
    for field in spec.fields:
        value, path = _find_field_value(field, candidates)
        if value is None:
            selected = _single_primary_object_candidate(spec, field, candidates) or _single_primary_list_candidate(
                spec,
                field,
                candidates,
            )
            if selected:
                value, path = selected
        coerced = _coerce_field_value(field, value, warnings)
        if coerced is None:
            continue
        normalized[field.name] = coerced
        for mirror in field.mirror_to:
            normalized.setdefault(mirror, coerced)
        if path:
            matched_paths.append(path)

    if spec.canonical_stage == "stage_04":
        _normalize_stage_04_beat_fields(normalized)
    elif spec.canonical_stage == "stage_10":
        _normalize_stage_10_episode_fields(normalized)
    elif spec.canonical_stage == "stage_11":
        _normalize_stage_11_conflict_fields(normalized)
    elif spec.canonical_stage == "stage_12":
        _normalize_stage_12_script_fields(normalized)

    plain_text = _first_plain_text_candidate(candidates)
    if not _has_any_stage_field(normalized, spec):
        if plain_text:
            warnings.append("model_returned_plain_text")
            _apply_plain_text_fallback(normalized, spec, plain_text)
            display_text = display_text or plain_text
        else:
            warnings.append("no_stage_business_field_found")
            _apply_empty_fallback(normalized, spec)

    display_text = display_text or _display_text_from_structure(normalized, spec)
    if not display_text:
        warnings.append("display_text_empty_after_normalization")
    normalized["display_text"] = display_text

    raw_content = _first_raw_content(raw_result)
    debug = {
        "stage_key": str(stage_key or ""),
        "backend": str(backend or ""),
        "backend_stage_key": str(backend_stage_key or ""),
        "canonical_stage": spec.canonical_stage,
        "normalized_from": "stage_output_normalizer",
        "candidate_paths": [path for path, _value in candidates],
        "matched_paths": matched_paths,
        "parse_attempts": attempts,
        "parse_warnings": _dedupe(warnings),
        "raw_result": raw_result,
        "raw_content": raw_content,
        "content_preview": _preview(raw_content if raw_content not in (None, "") else raw_result),
    }
    normalized["_normalizer_debug"] = debug
    normalized["workflow_output_normalization"] = debug
    normalized["parse_warnings"] = debug["parse_warnings"]
    return normalized


def stage_output_spec(stage_key: str) -> StageOutputSpec:
    normalized = _normalize_stage_key(stage_key)
    for spec in STAGE_OUTPUT_SPECS:
        if normalized in {_normalize_stage_key(alias) for alias in spec.stage_aliases}:
            return spec
    stage_match = re.search(r"stage[_-]?(0?[1-9]|1[0-2])", normalized)
    if stage_match:
        number = int(stage_match.group(1))
        if number == 11:
            return _spec_by_canonical("stage_11")
        if number == 12:
            return _spec_by_canonical("stage_12")
        return _spec_by_canonical(f"stage_{number:02d}")
    return StageOutputSpec(
        canonical_stage=normalized or "unknown",
        stage_aliases=(normalized or "unknown",),
        fields=(FieldSpec("output", ("output", "data", "result"), "object"),),
    )


def parse_jsonish(value: Any) -> Any | None:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    variants = _json_text_variants(text)
    for candidate in variants:
        parsed = _loads_json(candidate)
        if parsed is not None:
            return parsed
    for candidate in variants:
        for snippet in _balanced_json_snippets(candidate):
            parsed = _loads_json(snippet)
            if parsed is not None:
                return parsed
    return None


def _spec_by_canonical(canonical: str) -> StageOutputSpec:
    for spec in STAGE_OUTPUT_SPECS:
        if spec.canonical_stage == canonical:
            return spec
    raise KeyError(canonical)


def _normalize_stage_key(stage_key: str) -> str:
    text = str(stage_key or "").strip()
    if not text:
        return ""
    lowered = text.lower().replace("-", "_")
    if lowered.isdigit():
        number = int(lowered)
        return f"stage_{number:02d}" if 1 <= number <= 12 else lowered
    if re.fullmatch(r"stage_?\d+", lowered):
        number_text = re.sub(r"\D", "", lowered)
        return f"stage_{int(number_text):02d}"
    return lowered


def _iter_candidates(
    value: Any,
    *,
    path: str = "root",
    attempts: list[str],
    depth: int = 0,
    seen: set[int] | None = None,
):
    if seen is None:
        seen = set()
    if depth > 8:
        return
    if isinstance(value, (dict, list)):
        marker = id(value)
        if marker in seen:
            return
        seen.add(marker)

    yield path, value

    if isinstance(value, str):
        parsed = parse_jsonish(value)
        attempts.append(f"{path}:parse_jsonish:{type(parsed).__name__ if parsed is not None else 'failed'}")
        if parsed is not None and parsed is not value:
            yield from _iter_candidates(parsed, path=f"{path}<json>", attempts=attempts, depth=depth + 1, seen=seen)
        return

    if isinstance(value, list):
        variable_items = _dict_from_variable_items(value)
        if variable_items:
            yield from _iter_candidates(variable_items, path=f"{path}<variables>", attempts=attempts, depth=depth + 1, seen=seen)
        for index, item in enumerate(value):
            yield from _iter_candidates(item, path=f"{path}[{index}]", attempts=attempts, depth=depth + 1, seen=seen)
        return

    if not isinstance(value, dict):
        return

    variable_item = _dict_from_variable_item(value)
    if variable_item:
        yield from _iter_candidates(variable_item, path=f"{path}<variable>", attempts=attempts, depth=depth + 1, seen=seen)

    for key in (*TEXT_CONTAINER_KEYS, *NESTED_CONTAINER_KEYS):
        if key not in value:
            continue
        nested = value.get(key)
        if nested in (None, "", [], {}):
            continue
        yield from _iter_candidates(nested, path=f"{path}.{key}", attempts=attempts, depth=depth + 1, seen=seen)

    for key, nested in value.items():
        if key in TEXT_CONTAINER_KEYS or key in NESTED_CONTAINER_KEYS or key in RAW_DEBUG_KEYS:
            continue
        if isinstance(nested, (dict, list)):
            yield from _iter_candidates(nested, path=f"{path}.{key}", attempts=attempts, depth=depth + 1, seen=seen)
        elif isinstance(nested, str) and _looks_jsonish_text(nested):
            yield from _iter_candidates(nested, path=f"{path}.{key}", attempts=attempts, depth=depth + 1, seen=seen)


def _find_display_text(candidates: list[tuple[str, Any]]) -> str:
    for _path, candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in DISPLAY_TEXT_KEYS:
            value = candidate.get(key)
            if isinstance(value, str) and value.strip() and not _looks_jsonish_text(value):
                return value.strip()
    for _path, candidate in candidates:
        if isinstance(candidate, str) and candidate.strip() and not _looks_jsonish_text(candidate):
            return candidate.strip()
    return ""


def _find_field_value(field: FieldSpec, candidates: list[tuple[str, Any]]) -> tuple[Any, str]:
    alias_set = {_normalize_alias(alias) for alias in (field.name, *field.aliases)}
    for path, candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        found = _find_by_alias(candidate, alias_set)
        if found is not None:
            parsed = parse_jsonish(found) if isinstance(found, str) else found
            if parsed is None:
                parsed = found
            if isinstance(parsed, dict):
                nested = _find_by_alias(parsed, alias_set)
                if nested is not None:
                    return nested, f"{path}.{field.name}<nested>"
            return parsed, f"{path}.{field.name}"
    return None, ""


def _single_primary_object_candidate(
    spec: StageOutputSpec,
    field: FieldSpec,
    candidates: list[tuple[str, Any]],
) -> tuple[Any, str] | None:
    object_fields = [item for item in spec.fields if item.kind == "object"]
    list_fields = [item for item in spec.fields if item.kind == "list"]
    if list_fields or not object_fields or object_fields[0].name != field.name:
        return None
    for path, candidate in candidates:
        if path == "root" and isinstance(candidate, list) and candidate:
            return candidate, path
        if not isinstance(candidate, dict):
            continue
        business_keys = {
            _normalize_alias(alias)
            for item in spec.fields
            for alias in (item.name, *item.aliases)
        }
        candidate_keys = {_normalize_alias(key) for key in candidate.keys()}
        if candidate_keys & business_keys:
            continue
        if any(key in candidate for key in ("ok", "backend", "stage_key", "workflow_id")):
            continue
        if any(
            key in candidate
            for key in (
                "title",
                "summary",
                "overview",
                "core_logline",
                "world_type",
                "characters",
                "character_storylines",
                "locations",
                "scenes",
                "episodes",
                "rules",
                "conflict_chain",
            )
        ):
            return candidate, path
    return None


def _single_primary_list_candidate(
    spec: StageOutputSpec,
    field: FieldSpec,
    candidates: list[tuple[str, Any]],
) -> tuple[Any, str] | None:
    list_fields = [item for item in spec.fields if item.kind == "list"]
    if not list_fields or list_fields[0].name != field.name:
        return None
    for path, candidate in candidates:
        if isinstance(candidate, list) and candidate:
            return candidate, path
    return None


def _find_by_alias(candidate: dict[str, Any], alias_set: set[str]) -> Any:
    for key, value in candidate.items():
        if _normalize_alias(str(key)) in alias_set and value not in (None, "", [], {}):
            return value
    return None


def _normalize_alias(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _coerce_field_value(field: FieldSpec, value: Any, warnings: list[str]) -> Any:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, dict):
        content = value.get("content")
        if isinstance(content, str) and _looks_jsonish_text(content):
            parsed = parse_jsonish(content)
            if isinstance(parsed, dict):
                nested = _find_by_alias(parsed, {_normalize_alias(alias) for alias in (field.name, *field.aliases)})
                value = nested if nested is not None else parsed
        elif set(value.keys()) == {"content"} and isinstance(content, str) and field.kind != "string":
            warnings.append(f"{field.name}_content_plain_text_not_used_as_business_object")
            return None
    if field.kind == "object":
        if isinstance(value, dict):
            return _strip_raw_debug_keys(value)
        if isinstance(value, list):
            return {"items": value}
        if isinstance(value, str):
            parsed = parse_jsonish(value)
            if isinstance(parsed, dict):
                return _strip_raw_debug_keys(parsed)
            warnings.append(f"{field.name}_not_object")
            return None
    if field.kind == "list":
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for alias in field.aliases:
                nested = _find_by_alias(value, {_normalize_alias(alias)})
                if isinstance(nested, list):
                    return nested
            for key in ("items", "episodes", "plans", "beats", "storylines", "conflicts"):
                nested = value.get(key)
                if isinstance(nested, list):
                    return nested
            return [value]
        if isinstance(value, str):
            parsed = parse_jsonish(value)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                nested = _find_by_alias(parsed, {_normalize_alias(alias) for alias in field.aliases})
                if isinstance(nested, list):
                    return nested
            warnings.append(f"{field.name}_not_list")
            return None
    if field.kind == "string":
        if isinstance(value, str):
            return value.strip()
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def _normalize_stage_04_beat_fields(normalized: dict[str, Any]) -> None:
    beat = normalized.get("beat_checkpoint")
    if isinstance(beat, dict):
        timeline = normalized.get("beat_checkpoint_timeline")
        if not isinstance(timeline, list):
            for key in ("beat_checkpoint_timeline", "beatCheckpointTimeline", "timeline", "beats"):
                if isinstance(beat.get(key), list):
                    normalized["beat_checkpoint_timeline"] = beat[key]
                    break
        explanation = normalized.get("checkpoint_explanation")
        if not isinstance(explanation, dict):
            for key in ("checkpoint_explanation", "checkpointExplanation", "explanation", "beat_explanation"):
                if isinstance(beat.get(key), (dict, str)):
                    normalized["checkpoint_explanation"] = beat[key]
                    break


def _normalize_stage_10_episode_fields(normalized: dict[str, Any]) -> None:
    plan = normalized.get("allEnrichedEpisodePlan")
    if isinstance(plan, list):
        normalized.setdefault("episode_plan", plan)
        normalized.setdefault("enriched_episode_plan", plan)


def _normalize_stage_11_conflict_fields(normalized: dict[str, Any]) -> None:
    if "batchCausalConflictPlan" in normalized:
        normalized.setdefault("conflicts", normalized["batchCausalConflictPlan"])
    if "conflictMemory" in normalized:
        normalized.setdefault("memory", normalized["conflictMemory"])


def _normalize_stage_12_script_fields(normalized: dict[str, Any]) -> None:
    if "batchScriptText" in normalized:
        normalized.setdefault("script_text", normalized["batchScriptText"])
        normalized.setdefault("scripts", normalized["batchScriptText"])
    if "scriptMemory" in normalized:
        normalized.setdefault("memory", normalized["scriptMemory"])


def _has_any_stage_field(normalized: dict[str, Any], spec: StageOutputSpec) -> bool:
    return any(field.name in normalized and normalized[field.name] not in (None, "", [], {}) for field in spec.fields)


def _apply_plain_text_fallback(normalized: dict[str, Any], spec: StageOutputSpec, text: str) -> None:
    primary = spec.fields[0]
    if primary.kind == "string":
        normalized.setdefault(primary.name, text)
        for mirror in primary.mirror_to:
            normalized.setdefault(mirror, text)
    elif primary.kind == "list":
        normalized.setdefault(primary.name, [])
    else:
        normalized.setdefault(primary.name, {"summary": text})


def _apply_empty_fallback(normalized: dict[str, Any], spec: StageOutputSpec) -> None:
    for field in spec.fields:
        if field.name in normalized and normalized[field.name] not in (None, "", [], {}):
            continue
        if field.kind == "list":
            normalized[field.name] = []
        elif field.kind == "string":
            normalized[field.name] = ""
        else:
            normalized[field.name] = {}
        for mirror in field.mirror_to:
            normalized.setdefault(mirror, normalized[field.name])


def _display_text_from_structure(normalized: dict[str, Any], spec: StageOutputSpec) -> str:
    for field in spec.fields:
        value = normalized.get(field.name)
        text = _summarize_value(value)
        if text:
            return text
    return ""


def _summarize_value(value: Any) -> str:
    if isinstance(value, dict):
        for key in (
            "display_text",
            "summary",
            "overview",
            "title",
            "source_title",
            "core_logline",
            "world_type",
            "core_setting",
            "core_premise",
            "main_conflict",
        ):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        meaningful = [str(key) for key in value.keys() if key not in RAW_DEBUG_KEYS]
        return f"已生成结构化结果：{', '.join(meaningful[:6])}" if meaningful else ""
    if isinstance(value, list):
        if not value:
            return ""
        first = value[0]
        if isinstance(first, dict):
            title = first.get("title") or first.get("name") or first.get("episode_title") or first.get("beat_name")
            if title:
                return f"已生成 {len(value)} 条结构化结果，首项：{title}"
        return f"已生成 {len(value)} 条结构化结果。"
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _first_plain_text_candidate(candidates: list[tuple[str, Any]]) -> str:
    for _path, candidate in candidates:
        if isinstance(candidate, str) and candidate.strip() and not _looks_jsonish_text(candidate):
            return candidate.strip()
    return ""


def _first_raw_content(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("content", "answerText", "textOutput", "message", "text"):
            item = value.get(key)
            if item not in (None, "", [], {}):
                return item
        raw = value.get("raw_response") or value.get("raw_result")
        if raw not in (None, "", [], {}):
            return raw
    return value if isinstance(value, str) else ""


def _strip_raw_debug_keys(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in RAW_DEBUG_KEYS}


def _json_text_variants(text: str) -> list[str]:
    stripped = strip_code_fence(text).strip()
    variants = [stripped]
    repaired = _repair_json_text(stripped)
    if repaired != stripped:
        variants.append(repaired)
    return _dedupe(variants)


def _repair_json_text(text: str) -> str:
    text = strip_code_fence(text).strip()
    text = _normalize_delimiter_quotes_and_punctuation(text)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text.strip()


def _normalize_delimiter_quotes_and_punctuation(text: str) -> str:
    result: list[str] = []
    in_string = False
    quote = ""
    escaping = False
    for char in text:
        if in_string:
            if escaping:
                result.append(char)
                escaping = False
                continue
            if char == "\\":
                result.append(char)
                escaping = True
                continue
            if quote == "double" and char == '"':
                result.append('"')
                in_string = False
                quote = ""
                continue
            if quote == "smart_double" and char in {"\u201c", "\u201d"}:
                result.append('"')
                in_string = False
                quote = ""
                continue
            if quote == "single" and char == "'":
                result.append('"')
                in_string = False
                quote = ""
                continue
            if quote == "smart_single" and char in {"\u2018", "\u2019"}:
                result.append('"')
                in_string = False
                quote = ""
                continue
            if char == '"' and quote in {"single", "smart_single"}:
                result.append('\\"')
            else:
                result.append(char)
            continue

        if char == '"':
            result.append('"')
            in_string = True
            quote = "double"
        elif char in {"\u201c", "\u201d"}:
            result.append('"')
            in_string = True
            quote = "smart_double"
        elif char == "'":
            result.append('"')
            in_string = True
            quote = "single"
        elif char in {"\u2018", "\u2019"}:
            result.append('"')
            in_string = True
            quote = "smart_single"
        elif char == "：":
            result.append(":")
        elif char == "，":
            result.append(",")
        else:
            result.append(char)
    return "".join(result)


def _loads_json(text: str) -> Any | None:
    if not text:
        return None
    for candidate in (text, _repair_json_text(text)):
        try:
            return json.loads(candidate, strict=False)
        except Exception:
            continue
    return None


def _balanced_json_snippets(text: str) -> list[str]:
    snippets: list[str] = []
    starts = [index for index, char in enumerate(text) if char in "{["]
    for start in starts:
        end = _balanced_json_end(text, start)
        if end > start:
            snippets.append(text[start : end + 1])
    return _dedupe(snippets)


def _balanced_json_end(text: str, start: int) -> int:
    stack: list[str] = []
    in_string = False
    quote = ""
    escaping = False
    pairs = {"{": "}", "[": "]"}
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaping:
                escaping = False
                continue
            if char == "\\":
                escaping = True
                continue
            if quote == "double" and char == '"':
                in_string = False
                quote = ""
            elif quote == "smart_double" and char in {"\u201c", "\u201d"}:
                in_string = False
                quote = ""
            elif quote == "single" and char == "'":
                in_string = False
                quote = ""
            elif quote == "smart_single" and char in {"\u2018", "\u2019"}:
                in_string = False
                quote = ""
            continue
        if char == '"':
            in_string = True
            quote = "double"
            continue
        if char in {"\u201c", "\u201d"}:
            in_string = True
            quote = "smart_double"
            continue
        if char == "'":
            in_string = True
            quote = "single"
            continue
        if char in {"\u2018", "\u2019"}:
            in_string = True
            quote = "smart_single"
            continue
        if char in pairs:
            stack.append(pairs[char])
            continue
        if stack and char == stack[-1]:
            stack.pop()
            if not stack:
                return index
    return -1


def _looks_jsonish_text(text: str) -> bool:
    stripped = strip_code_fence(str(text or "")).strip()
    if not stripped:
        return False
    if stripped[:1] in "{[":
        return True
    lowered = stripped.lower()
    return "```json" in lowered or bool(re.search(r"\{[\s\S]{0,200}(source_brief|display_text|worldview|character|script|scene)", stripped))


def _dict_from_variable_item(value: dict[str, Any]) -> dict[str, Any] | None:
    if "value" not in value:
        return None
    key = value.get("key") or value.get("name") or value.get("variable")
    if isinstance(key, list) and key:
        key = key[-1]
    if isinstance(key, str) and key.strip():
        return {key.strip(): value.get("value")}
    return None


def _dict_from_variable_items(values: list[Any]) -> dict[str, Any] | None:
    result: dict[str, Any] = {}
    for item in values:
        if not isinstance(item, dict):
            continue
        mapped = _dict_from_variable_item(item)
        if mapped:
            result.update(mapped)
    return result or None


def _preview(value: Any, *, limit: int = 500) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            value = str(value)
    text = " ".join(str(value).split())
    return text if len(text) <= limit else f"{text[:limit]}..."


def _dedupe(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) if not isinstance(value, str) else value
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)
    return result
