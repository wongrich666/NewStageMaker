from __future__ import annotations

import json
import re
from typing import Any

from ..utils.logger import get_logger

logger = get_logger("workflow_output_parser")

MAX_PARSE_DEPTH = 6
TEXT_FIELD_KEYS = (
    "answer_text",
    "answerText",
    "textOutput",
    "output",
    "content",
    "answer",
    "message",
    "text",
    "response",
    "result",
)
STRUCTURED_FIELD_KEYS = (
    "variables",
    "outputs",
    "newVariables",
    "outputVariables",
    "output_variables",
)
CONTAINER_FIELD_KEYS = (
    "data",
    "responseData",
    "result",
    "response",
)
WRAPPER_FIELD_KEYS = {
    "code",
    "msg",
    "message",
    "detail",
    "error",
    "status",
    "debug",
    "data",
    "responseData",
    "result",
    "response",
    "variables",
    "outputs",
    "newVariables",
    "outputVariables",
    "output_variables",
    "answer_text",
    "answerText",
    "textOutput",
    "output",
    "content",
    "answer",
    "text",
}
SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,\"'}]+"),
    re.compile(r"(?i)(\"?(?:api[_-]?key|token|authorization|secret)\"?\s*[:=]\s*\")([^\"]+)"),
    re.compile(r"(?i)(pat_)[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{12,}"),
)
FENCE_PATTERN = re.compile(
    r"(?P<fence>`{3,}|'{3,})(?P<label>[^\r\n]*)\r?\n(?P<body>.*?)(?:\r?\n)?(?P=fence)",
    re.DOTALL,
)


def parse_workflow_output(raw: Any, *, max_depth: int = MAX_PARSE_DEPTH) -> Any:
    """Parse model/workflow output into the most useful JSON-like payload.

    The parser deliberately accepts 腾讯工作流/工作流-style wrapper objects, fenced JSON,
    JSON embedded in prose, and double-encoded strings. If no JSON can be extracted,
    the original text is returned so the stage contract can fail with context.
    """
    try:
        return _parse_value(raw, max_depth=max(1, int(max_depth)))
    except Exception as exc:
        logger.warning(
            "workflow output parse failed: type=%s error=%s preview=%s",
            type(raw).__name__,
            exc,
            safe_truncated_preview(raw),
        )
        return raw


def extract_json_payload(raw: Any, *, max_depth: int = MAX_PARSE_DEPTH) -> Any:
    return parse_workflow_output(raw, max_depth=max_depth)


def wrap_payload_for_expected_output(
    payload: Any,
    *,
    output_names: tuple[str, ...] | list[str],
    output_aliases: dict[str, tuple[str, ...]] | None = None,
    output_types: dict[str, str] | None = None,
    stage_name: str = "",
) -> Any:
    parsed = parse_workflow_output(payload)
    names = tuple(str(item) for item in output_names if str(item).strip())
    if len(names) != 1:
        return parsed

    field = names[0]
    aliases = _all_output_aliases(names, output_aliases)
    if isinstance(parsed, dict):
        if _contains_any_key(parsed, aliases):
            return parsed
        if _looks_like_business_object(parsed):
            logger.info(
                "workflow output fallback wrapping: stage=%s output=%s payload_type=dict preview=%s",
                stage_name or "unknown",
                field,
                safe_truncated_preview(parsed, limit=600),
            )
            return {field: _coerce_wrapped_value(field, parsed, output_types)}
        return parsed

    if isinstance(parsed, list):
        logger.info(
            "workflow output fallback wrapping: stage=%s output=%s payload_type=list length=%s preview=%s",
            stage_name or "unknown",
            field,
            len(parsed),
            safe_truncated_preview(parsed, limit=600),
        )
        return {field: _coerce_wrapped_value(field, parsed, output_types)}

    if isinstance(parsed, str) and str(output_types.get(field, "") if output_types else "") == "string":
        text = parsed.strip()
        if text:
            logger.info(
                "workflow output fallback wrapping: stage=%s output=%s payload_type=str preview=%s",
                stage_name or "unknown",
                field,
                safe_truncated_preview(text, limit=600),
            )
            return {field: text}
    return parsed


def safe_truncated_preview(value: Any, *, limit: int = 1600, head: int | None = None, tail: int | None = None) -> str:
    try:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = repr(value)
    text = _redact_secrets(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    head_size = head if head is not None else max(1, int(limit * 0.65))
    tail_size = tail if tail is not None else max(1, limit - head_size - 40)
    return f"{text[:head_size]} ...<truncated {len(text) - head_size - tail_size} chars>... {text[-tail_size:]}"


def _parse_value(value: Any, *, max_depth: int) -> Any:
    if max_depth <= 0:
        return value
    if isinstance(value, dict):
        return _parse_dict(value, max_depth=max_depth)
    if isinstance(value, list):
        variable_map = _dict_from_variable_items(value)
        if variable_map is not None:
            return _parse_value(variable_map, max_depth=max_depth - 1)
        return [_parse_value(item, max_depth=max_depth - 1) for item in value]
    if isinstance(value, str):
        return _parse_text(value, max_depth=max_depth)
    return value


def _parse_dict(value: dict[str, Any], *, max_depth: int) -> Any:
    structured = _find_structured_payload(value, max_depth=max_depth)
    if structured is not _MISSING:
        return _parse_value(structured, max_depth=max_depth - 1)

    if _looks_like_wrapper_object(value):
        wrapped = _parse_wrapper_payload(value, max_depth=max_depth)
        if wrapped is not _MISSING:
            return wrapped

    return {
        str(key): _parse_value(nested, max_depth=max_depth - 1)
        for key, nested in value.items()
    }


def _parse_wrapper_payload(value: dict[str, Any], *, max_depth: int) -> Any:
    for key in CONTAINER_FIELD_KEYS:
        nested = value.get(key)
        if nested in (None, "", [], {}):
            continue
        parsed = _parse_value(nested, max_depth=max_depth - 1)
        if parsed not in (None, "", [], {}):
            return parsed

    for key in TEXT_FIELD_KEYS:
        nested = value.get(key)
        if nested in (None, "", [], {}):
            continue
        parsed = _parse_value(nested, max_depth=max_depth - 1)
        if isinstance(parsed, (dict, list)):
            return parsed
        if isinstance(parsed, str) and parsed.strip() and len(value) == 1:
            return parsed
    return _MISSING


def _find_structured_payload(value: dict[str, Any], *, max_depth: int) -> Any:
    for key in STRUCTURED_FIELD_KEYS:
        nested = value.get(key)
        if nested in (None, "", [], {}):
            continue
        mapped = _dict_from_variable_items(nested)
        return mapped if mapped is not None else nested

    data = value.get("data")
    if isinstance(data, dict):
        nested = _find_structured_payload(data, max_depth=max_depth - 1)
        if nested is not _MISSING:
            return nested

    response_data = value.get("responseData")
    if isinstance(response_data, dict):
        nested = _find_structured_payload(response_data, max_depth=max_depth - 1)
        if nested is not _MISSING:
            return nested
    if isinstance(response_data, list):
        for item in response_data:
            if isinstance(item, dict):
                nested = _find_structured_payload(item, max_depth=max_depth - 1)
                if nested is not _MISSING:
                    return nested
    return _MISSING


def _parse_text(value: str, *, max_depth: int) -> Any:
    text = value.strip()
    if not text:
        return ""

    direct = _json_loads(text)
    if direct is not _MISSING:
        return _parse_value(direct, max_depth=max_depth - 1)

    for block in _iter_code_blocks(text):
        parsed = _json_loads(block.strip())
        if parsed is _MISSING:
            parsed = _extract_first_json_fragment(block)
        if parsed is not _MISSING:
            normalized = _parse_value(parsed, max_depth=max_depth - 1)
            if isinstance(normalized, (dict, list)):
                return normalized

    fragment = _extract_first_json_fragment(text)
    if fragment is not _MISSING:
        return _parse_value(fragment, max_depth=max_depth - 1)
    return text


def _json_loads(text: str) -> Any:
    candidate = text.strip("\ufeff \t\r\n")
    if not candidate:
        return _MISSING
    try:
        return json.loads(candidate)
    except Exception:
        return _MISSING


def _iter_code_blocks(text: str) -> list[str]:
    blocks = [match.group("body").strip() for match in FENCE_PATTERN.finditer(text)]
    if blocks:
        return blocks
    stripped = text.strip()
    for fence in ("```", "'''"):
        if stripped.startswith(fence) and stripped.endswith(fence):
            inner = stripped[len(fence) : -len(fence)].strip()
            if "\n" in inner:
                first_line, rest = inner.split("\n", 1)
                if re.fullmatch(r"[A-Za-z0-9_+-]*", first_line.strip()):
                    inner = rest.strip()
            return [inner]
    return []


def _extract_first_json_fragment(text: str) -> Any:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except Exception:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed
    return _MISSING


def _dict_from_variable_items(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, list):
        return None
    mapped: dict[str, Any] = {}
    found = False
    for item in value:
        if not isinstance(item, dict):
            continue
        key = item.get("key") or item.get("name")
        variable = item.get("variable")
        if key in (None, "") and isinstance(variable, list) and variable:
            key = variable[-1]
        if key in (None, ""):
            continue
        if "value" in item:
            mapped[str(key)] = item.get("value")
            found = True
        elif "content" in item:
            mapped[str(key)] = item.get("content")
            found = True
    return mapped if found else None


def _looks_like_wrapper_object(value: dict[str, Any]) -> bool:
    keys = {str(key) for key in value.keys()}
    return bool(keys) and keys.issubset(WRAPPER_FIELD_KEYS)


def _looks_like_business_object(value: dict[str, Any]) -> bool:
    if not value or _looks_like_wrapper_object(value):
        return False
    keys = {str(key).lower() for key in value}
    if "events" in keys and "reply" in keys:
        return False
    if keys & {"procedures", "runnodes", "requestack"}:
        return False
    if "code" in value and ("data" in value or "msg" in value or "message" in value):
        return False
    return True


def _all_output_aliases(
    output_names: tuple[str, ...],
    output_aliases: dict[str, tuple[str, ...]] | None,
) -> set[str]:
    aliases = set(output_names)
    for items in (output_aliases or {}).values():
        aliases.update(str(item) for item in items if str(item).strip())
    return aliases


def _contains_any_key(value: dict[str, Any], keys: set[str]) -> bool:
    lowered = {str(key).lower() for key in keys}
    for key in value.keys():
        if str(key).lower() in lowered:
            return True
    return False


def _coerce_wrapped_value(field: str, value: Any, output_types: dict[str, str] | None) -> Any:
    type_name = str((output_types or {}).get(field) or "").lower()
    if isinstance(value, list) and type_name == "object" and field == "batchCausalConflictPlan":
        return {"episodes": value}
    if type_name == "string" and isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _redact_secrets(text: str) -> str:
    redacted = text
    redacted = SECRET_PATTERNS[0].sub(r"\1<redacted>", redacted)
    redacted = SECRET_PATTERNS[1].sub(r"\1<redacted>", redacted)
    redacted = SECRET_PATTERNS[2].sub(r"\1<redacted>", redacted)
    redacted = SECRET_PATTERNS[3].sub(r"\1<redacted>", redacted)
    return redacted


class _Missing:
    pass


_MISSING = _Missing()
