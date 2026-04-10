from __future__ import annotations

import json
import re
from typing import Any

from ..models.state import ReviewResult


def strip_code_fence(text: str) -> str:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_+-]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    return cleaned.strip()


def extract_json_candidate(text: str) -> str:
    cleaned = strip_code_fence(text)
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned
    if cleaned.startswith("[") and cleaned.endswith("]"):
        return cleaned

    obj_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if obj_match:
        return obj_match.group(0)

    arr_match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if arr_match:
        return arr_match.group(0)

    raise ValueError(f"无法从文本中提取 JSON: {cleaned[:300]}")


def parse_json(text: str) -> Any:
    return json.loads(extract_json_candidate(text))


def ensure_dict(text: str) -> dict[str, Any]:
    data = parse_json(text)
    if not isinstance(data, dict):
        raise ValueError("解析结果不是 JSON object")
    return data


def ensure_list(text: str) -> list[Any]:
    data = parse_json(text)
    if not isinstance(data, list):
        raise ValueError("解析结果不是 JSON array")
    return data


def to_pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _normalize_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    result: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def normalize_approval_review(data: dict[str, Any]) -> ReviewResult:
    approved = bool(data.get("approved", False))
    suggestions = _normalize_list(data.get("suggestions", []))
    if approved:
        suggestions = []
    return ReviewResult(
        approved=approved,
        rewrite_required=not approved,
        suggestions=suggestions,
        raw=data,
    )


def normalize_pass_review(data: dict[str, Any]) -> ReviewResult:
    approved = bool(data.get("passed", False))
    blocking_issues = _normalize_list(data.get("blocking_issues", []))
    non_blocking_issues = _normalize_list(data.get("non_blocking_issues", []))
    rewrite_required = bool(data.get("rewrite_required", not approved))
    if approved:
        rewrite_required = False
    rewrite_start_episode = data.get("rewrite_start_episode")
    if rewrite_start_episode in (None, ""):
        parsed_start = None
    else:
        parsed_start = int(rewrite_start_episode)

    return ReviewResult(
        approved=approved,
        rewrite_required=rewrite_required,
        summary=str(data.get("summary", "")).strip(),
        blocking_issues=blocking_issues,
        non_blocking_issues=non_blocking_issues,
        rewrite_start_episode=parsed_start,
        raw=data,
    )
