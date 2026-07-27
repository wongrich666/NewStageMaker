from __future__ import annotations

import ast
import copy
import json
import re
from typing import Any

JSON_FENCE_PATTERN = re.compile(r"```(?:json|text|markdown)?\s*([\s\S]*?)```", re.IGNORECASE)
TECHNICAL_KEY_PATTERN = re.compile(r'^\s*"?([A-Za-z_][A-Za-z0-9_]*)"?\s*[:：]\s*(.*)$')
PLACEHOLDER_PATTERN = re.compile(
    r"(待补全|补充人物定位|待完善|未提供|未补充|暂无|待填写|待定|省略|TBD|TODO|N/?A|None|null)",
    re.IGNORECASE,
)
SECTION_TITLE_PATTERN = re.compile(
    r"^(人物小传|人物设定|人物定位|关系特点|出场记忆点|场景设定|核心场景|服饰映射|服装版本映射|"
    r"服装版本映射内容|世界观|世界观设定|剧本框架|故事梗概|人物服饰说明|分集计划|服饰版本)"
    r"(?:说明|内容)?\s*[：:]?$"
)
MACHINE_LABEL_ONLY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{1,}$")
PUNCT_ONLY_PATTERN = re.compile(r"^[\s\[\]\{\},:：\"'`]+$")
PLACEHOLDER_EXACT_TOKENS = {
    "待补全",
    "补充人物定位",
    "待完善",
    "未提供",
    "未补充",
    "暂无",
    "待填写",
    "待定",
    "省略",
    "tbd",
    "todo",
    "na",
    "none",
    "null",
    "待补全补充人物定位",
}
PLACEHOLDER_STAGE_OUTPUTS = {
    "剧本框架自然语言说明暂未生成。",
    "世界观自然语言说明暂未生成。",
    "人物设定自然语言说明暂未生成。",
    "核心场景自然语言说明暂未生成。",
}
PREFERRED_TEXT_KEYS = (
    "content",
    "text",
    "description",
    "summary",
    "value",
    "title",
    "name",
    "label",
    "character_name",
    "scene_name",
    "default_name",
    "alias_name",
    "worldview_summary",
    "overall_look",
    "story_role",
)


def strip_code_fences(text: str) -> str:
    content = str(text or "").strip()
    match = JSON_FENCE_PATTERN.fullmatch(content)
    if match:
        return str(match.group(1) or "").strip()
    return JSON_FENCE_PATTERN.sub(lambda item: str(item.group(1) or "").strip(), content).strip()


def parse_structured_value(value: Any) -> Any | None:
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if isinstance(value, (list, tuple, set)):
        return list(copy.deepcopy(value))
    text = strip_code_fences(str(value or "")).strip()
    if not text or text[0] not in "[{":
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            return None
    if isinstance(parsed, dict):
        return copy.deepcopy(parsed)
    if isinstance(parsed, (list, tuple, set)):
        return list(copy.deepcopy(parsed))
    return None


def is_machine_key(key: Any) -> bool:
    text = str(key or "").strip()
    if not text:
        return True
    if re.search(r"[\u4e00-\u9fff]", text):
        return False
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text))


def _append_unique(parts: list[str], value: str) -> None:
    text = str(value or "").strip()
    if not text:
        return
    if text not in parts:
        parts.append(text)


def _collapse_lines(lines: list[str]) -> str:
    normalized: list[str] = []
    previous_blank = True
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line:
            if not previous_blank:
                normalized.append("")
            previous_blank = True
            continue
        normalized.append(line)
        previous_blank = False
    while normalized and normalized[0] == "":
        normalized.pop(0)
    while normalized and normalized[-1] == "":
        normalized.pop()
    paragraphs: list[str] = []
    current: list[str] = []
    for line in normalized:
        if line == "":
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(" ".join(current).strip())
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph).strip()


def _clean_text_line(line: str) -> str:
    text = str(line or "").strip()
    if not text or PUNCT_ONLY_PATTERN.fullmatch(text):
        return ""
    match = TECHNICAL_KEY_PATTERN.match(text)
    if match:
        key = str(match.group(1) or "").strip()
        value = str(match.group(2) or "").strip().strip(",")
        if value in {"", "{", "}", "[", "]"}:
            return ""
        if is_machine_key(key):
            return value.strip(' "')
        cleaned_value = value.strip(' \"')
        return f"{key}：{cleaned_value}"
    return text.strip(' "')


def normalize_user_visible_text(value: Any, *, _depth: int = 0) -> str:
    if _depth > 6:
        return str(value or "").strip()
    if value is None:
        return ""
    if isinstance(value, str):
        text = strip_code_fences(value)
        parsed = parse_structured_value(text)
        if parsed is not None:
            return normalize_user_visible_text(parsed, _depth=_depth + 1)
        lines = [_clean_text_line(raw_line) for raw_line in text.replace("\r", "").split("\n")]
        return _collapse_lines(lines)
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts: list[str] = []
        for key in PREFERRED_TEXT_KEYS:
            if key not in value:
                continue
            text = normalize_user_visible_text(value.get(key), _depth=_depth + 1)
            if text and not is_placeholder_text(text):
                _append_unique(parts, text)
        for key, item in value.items():
            if item in (None, "", [], {}, (), set()):
                continue
            text = normalize_user_visible_text(item, _depth=_depth + 1)
            if not text:
                continue
            if is_machine_key(key):
                _append_unique(parts, text)
                continue
            _append_unique(parts, f"{key}：{text}")
        return "\n".join(parts).strip()
    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            text = normalize_user_visible_text(item, _depth=_depth + 1)
            if text:
                _append_unique(parts, text)
        return "\n".join(parts).strip()
    return str(value).strip()


def is_machine_structured_content(value: Any) -> bool:
    if isinstance(value, (dict, list, tuple, set)):
        return True
    text = strip_code_fences(str(value or "")).strip()
    if not text:
        return False
    if text in {"{}", "[]", "[object Object]"}:
        return True
    if parse_structured_value(text) is not None:
        return True
    return False


def _compact_for_placeholder(text: str) -> str:
    return re.sub(r"[\s，。；：:、,【】（）()“”\"'`·\\/_\-]", "", str(text or "")).lower()


def _placeholder_analysis_text(value: Any) -> str:
    if isinstance(value, str):
        raw_text = strip_code_fences(value).replace("\r", "").strip()
        parsed = parse_structured_value(raw_text)
        if parsed is None:
            return raw_text
    return normalize_user_visible_text(value).replace("\r", "").strip()


def is_placeholder_text(value: Any) -> bool:
    text = _placeholder_analysis_text(value)
    if not text:
        return True
    if text in PLACEHOLDER_STAGE_OUTPUTS:
        return True
    compact = _compact_for_placeholder(text)
    if compact in PLACEHOLDER_EXACT_TOKENS:
        return True
    non_empty_lines = [line.strip() for line in text.replace("\r", "").split("\n") if line.strip()]
    if not non_empty_lines:
        return True
    if all(SECTION_TITLE_PATTERN.fullmatch(line) for line in non_empty_lines):
        return True
    if all(MACHINE_LABEL_ONLY_PATTERN.fullmatch(line) for line in non_empty_lines):
        return True
    if PLACEHOLDER_PATTERN.search(text) and len(compact) <= 24:
        return True
    informative_lines = [
        line for line in non_empty_lines
        if not SECTION_TITLE_PATTERN.fullmatch(line)
        and not MACHINE_LABEL_ONLY_PATTERN.fullmatch(line)
        and not PLACEHOLDER_PATTERN.search(line)
    ]
    if not informative_lines:
        return True
    return False


def is_meaningful_text(value: Any) -> bool:
    if is_placeholder_text(value):
        return False
    text = normalize_user_visible_text(value).strip()
    if not text:
        return False
    return True


def has_meaningful_content(value: Any) -> bool:
    structured = parse_structured_value(value)
    if structured is not None:
        return is_meaningful_text(normalize_user_visible_text(structured))
    return is_meaningful_text(value)


def clean_user_visible_text(
    value: Any,
    *,
    banned_prefixes: tuple[str, ...] = (),
    fallback_text: str = "",
) -> str:
    text = normalize_user_visible_text(value).strip()
    if not text:
        return str(fallback_text or "").strip()
    if banned_prefixes:
        filtered_lines = [
            line
            for line in text.splitlines()
            if str(line).strip()
            and not any(str(line).strip().startswith(prefix) for prefix in banned_prefixes)
        ]
        text = "\n".join(filtered_lines).strip()
    if not text or is_placeholder_text(text):
        return str(fallback_text or "").strip()
    return text


def pick_best_user_visible_value(
    *values: Any,
    banned_prefixes: tuple[str, ...] = (),
    fallback_text: str = "",
) -> str:
    for value in values:
        text = clean_user_visible_text(value, banned_prefixes=banned_prefixes)
        if text:
            return text
    return clean_user_visible_text(fallback_text, banned_prefixes=banned_prefixes)


def build_user_visible_section(
    stage_name: str,
    structured_value: Any,
    natural_value: Any,
    fallback_value: Any = "",
    *,
    banned_prefixes: tuple[str, ...] = (),
) -> str:
    del stage_name
    return pick_best_user_visible_value(
        natural_value,
        fallback_value,
        structured_value,
        banned_prefixes=banned_prefixes,
    )


def export_safe_text(
    value: Any,
    *,
    banned_prefixes: tuple[str, ...] = (),
    fallback_text: str = "",
) -> str:
    return clean_user_visible_text(
        value,
        banned_prefixes=banned_prefixes,
        fallback_text=fallback_text,
    )
