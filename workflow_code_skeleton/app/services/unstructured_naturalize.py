from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping

from ..utils.user_visible_text import (
    clean_user_visible_text,
    is_meaningful_text,
    is_machine_structured_content,
    is_placeholder_text,
    normalize_user_visible_text,
    parse_structured_value,
)
from ..workflow_ids import (
    CHARACTER_BIOS_VAR,
    CHARACTER_NATURAL_LANGUAGE_VAR,
    CHARACTER_VAR,
    UNSTRUCTURED_KIND_VAR,
    UNSTRUCTURED_OUTPUT_VAR,
    UNSTRUCTURED_SOURCE_VAR,
)
from .workflow_contracts import (
    CHARACTERS,
    STAGE_CHARACTERS,
    STAGE_CHARACTERS_NATURALIZE,
    STAGE_FRAMEWORK,
    STAGE_FRAMEWORK_NATURALIZE,
    STAGE_WORLDVIEW,
    STAGE_WORLDVIEW_NATURALIZE,
    USER_CHARACTERS,
)

CHARACTER_PLACEHOLDER_PATTERN = re.compile(
    r"(待补全|补充人物定位|待完善|未提供|未补充|暂无|待填写|待定|TBD|TODO|None|null)",
    re.IGNORECASE,
)


def resolve_unstructured_content_kind(stage_name: str, source_stage: str | None = None) -> str:
    if stage_name == STAGE_FRAMEWORK_NATURALIZE or source_stage == STAGE_FRAMEWORK:
        return "framework"
    if stage_name == STAGE_WORLDVIEW_NATURALIZE or source_stage == STAGE_WORLDVIEW:
        return "worldview"
    if stage_name in {
        STAGE_CHARACTERS_NATURALIZE,
        "character_naturalize",
        "characters_naturalize",
        "character_bio_naturalize",
    } or source_stage in {
        STAGE_CHARACTERS,
        "character_setting",
        "character_bio",
    }:
        return "generic"
    return "generic"


def build_unstructured_stage_variables(
    source_text: Any,
    *,
    stage_name: str,
    source_stage: str | None = None,
    variables: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = str(source_text or "").strip()
    kind = resolve_unstructured_content_kind(stage_name, source_stage)
    stage_variables = dict(variables or {})
    stage_variables["unstructured_source"] = source
    stage_variables["unstructured_content_kind"] = kind
    stage_variables[UNSTRUCTURED_SOURCE_VAR] = source
    stage_variables[UNSTRUCTURED_KIND_VAR] = kind
    return stage_variables


def extract_unstructured_stage_output_text(
    output: Mapping[str, Any] | None,
    *,
    output_field: str,
    text_cleaner: Callable[[Any], str] | None = None,
    text_is_usable: Callable[[Any], bool] | None = None,
) -> str:
    if not isinstance(output, Mapping):
        return ""
    cleaner = text_cleaner or (lambda value: clean_user_visible_text(value).strip())
    usability_checker = text_is_usable or (lambda value: bool(str(value or "").strip()) and not is_placeholder_text(value))
    for key in (output_field, UNSTRUCTURED_OUTPUT_VAR, "answerText"):
        if key not in output:
            continue
        value = output.get(key)
        if is_machine_structured_content(value):
            continue
        text = str(cleaner(value) or "").strip()
        if not usability_checker(text):
            continue
        return text
    return ""


def clean_multiline_character_text(value: Any) -> str:
    if not isinstance(value, str):
        return clean_user_visible_text(value).strip()
    raw = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [clean_user_visible_text(line).strip() for line in raw.split("\n")]
    lines = [line for line in lines if line]
    if len(lines) > 1:
        return "\n".join(lines).strip()
    return clean_user_visible_text(value).strip()


def character_natural_text_is_usable(value: Any) -> bool:
    text = clean_multiline_character_text(value)
    if not text:
        return False
    if CHARACTER_PLACEHOLDER_PATTERN.search(text):
        return False
    return is_meaningful_text(text)


def build_character_unstructured_source(
    variables: Mapping[str, Any] | None,
    *,
    extra_candidates: tuple[Any, ...] = (),
) -> str:
    values = dict(variables or {})
    structured_candidates = (
        values.get(CHARACTERS),
        values.get(CHARACTER_VAR),
        *extra_candidates,
    )
    for candidate in structured_candidates:
        source = _character_source_candidate_text(candidate, prefer_structured=True)
        if source:
            return source

    text_candidates = (
        values.get(USER_CHARACTERS),
        values.get(CHARACTER_BIOS_VAR),
        values.get(CHARACTER_NATURAL_LANGUAGE_VAR),
    )
    for candidate in text_candidates:
        source = _character_source_candidate_text(candidate, prefer_structured=False)
        if source:
            return source
    return ""


def _character_source_candidate_text(value: Any, *, prefer_structured: bool) -> str:
    if value in (None, "", {}, [], (), set()):
        return ""
    structured = parse_structured_value(value)
    if structured is not None:
        if not prefer_structured:
            return ""
        if _structured_character_source_has_placeholder_leaks(structured):
            return ""
        try:
            return json.dumps(structured, ensure_ascii=False, indent=2)
        except Exception:
            return ""

    if prefer_structured:
        return ""
    text = clean_multiline_character_text(value).strip()
    if not text or is_placeholder_text(text):
        return ""
    return text



def _structured_character_source_has_placeholder_leaks(value: Any) -> bool:
    text = normalize_user_visible_text(value).replace("\r", "").strip()
    if not text:
        return True
    if is_placeholder_text(text):
        return True
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return True
    placeholder_lines = [line for line in lines if CHARACTER_PLACEHOLDER_PATTERN.search(line)]
    if not placeholder_lines:
        return False
    informative_lines = [line for line in lines if not CHARACTER_PLACEHOLDER_PATTERN.search(line)]
    if not informative_lines:
        return True
    placeholder_hits = CHARACTER_PLACEHOLDER_PATTERN.findall(text)
    if len(placeholder_hits) >= max(3, len(informative_lines)):
        return True
    if len(placeholder_lines) >= max(3, len(lines) // 2):
        return True
    return False
