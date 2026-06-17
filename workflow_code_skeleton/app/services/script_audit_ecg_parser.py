from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

SCHEMA_VERSION = "script_audit_ecg_v2"
SCHEMA_VERSION_V3 = "script_audit_ecg_v3_episode_global"
COMPACT_SCHEMA_VERSION = "script_audit_compact_v1"
SUPPORTED_SCHEMA_VERSIONS = {SCHEMA_VERSION, SCHEMA_VERSION_V3, COMPACT_SCHEMA_VERSION}

AUDIT_DIMENSIONS = [
    {
        "dimension_key": "opening_hook",
        "dimension_name": "开场吸引力",
        "max_score": 15,
    },
    {
        "dimension_key": "conflict_pacing",
        "dimension_name": "冲突与节奏",
        "max_score": 25,
    },
    {
        "dimension_key": "satisfying_payoff",
        "dimension_name": "爽点兑现",
        "max_score": 25,
    },
    {
        "dimension_key": "character_dialogue_filming",
        "dimension_name": "人物对白与可拍性",
        "max_score": 20,
    },
    {
        "dimension_key": "market_compliance",
        "dimension_name": "市场适配与平台合规",
        "max_score": 15,
    },
]

ECG_COLOR_MAP = {
    "positive": "#16a34a",
    "negative": "#dc2626",
    "neutral": "#6b7280",
}

RISK_COLOR_MAP = {
    "必须修改": "#dc2626",
    "建议修改": "#f97316",
    "可以保留": "#16a34a",
    "证据不足": "#6b7280",
}

LEVEL_COLOR_MAP = {
    "S": "#16a34a",
    "A": "#22c55e",
    "B": "#eab308",
    "C": "#f97316",
    "D": "#dc2626",
}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _strip_code_fence(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```[a-zA-Z0-9_+-]*\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


def _iter_balanced_json_candidates(text: str) -> list[str]:
    text = _strip_code_fence(text)
    candidates: list[str] = []

    for start, opening in enumerate(text):
        if opening not in "{[":
            continue

        stack: list[str] = []
        in_string = False
        escape = False

        for idx in range(start, len(text)):
            ch = text[idx]

            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if not stack:
                    break
                expected = "}" if stack[-1] == "{" else "]"
                if ch != expected:
                    break
                stack.pop()
                if not stack:
                    candidates.append(text[start:idx + 1])
                    break

    return candidates


def _json_loads_maybe_nested(text: str) -> Any:
    cleaned = _strip_code_fence(text)
    variants = [
        cleaned,
        cleaned.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'"),
        re.sub(r",\s*([}\]])", r"\1", cleaned),
        re.sub(r",\s*([}\]])", r"\1", cleaned.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")),
    ]
    last_error: Exception | None = None
    data = None
    for variant in variants:
        try:
            data = json.loads(variant)
            break
        except Exception as exc:
            last_error = exc
    if data is None:
        raise last_error or ValueError("JSON parse failed")
    depth = 0
    while isinstance(data, str) and depth < 3:
        nested = _strip_code_fence(data)
        if not nested:
            break
        candidates = [nested, *_iter_balanced_json_candidates(nested)]
        parsed = False
        for candidate in candidates:
            try:
                data = json.loads(candidate)
                parsed = True
                break
            except Exception:
                continue
        if not parsed:
            break
        depth += 1
    return data


def _extract_title_from_text(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    for pattern in (
        r"""["']script_title["']\s*:\s*["']([^"']{1,120})["']""",
        r"""剧本(?:标题|名称)\s*[:：]\s*([^\n\r]{1,80})""",
        r"""作品(?:标题|名称)\s*[:：]\s*([^\n\r]{1,80})""",
        r"""《([^》]{1,80})》""",
    ):
        match = re.search(pattern, value)
        if match:
            return match.group(1).strip().strip("：: -")
    for line in value.replace("\r", "\n").split("\n"):
        cleaned = line.strip().strip("#").strip()
        if cleaned:
            return cleaned[:80]
    return ""


def fallback_audit_from_text(raw_text: str, *, title: str = "", warnings: list[str] | None = None) -> dict:
    text = str(raw_text or "").strip()
    parse_warnings = [str(item) for item in (warnings or []) if str(item or "").strip()]
    excerpt = " ".join(text.split())[:1200]
    script_title = str(title or "").strip() or _extract_title_from_text(text) or "未命名剧本"
    issue = {
        "issue_id": "parse_fallback_001",
        "priority": 1,
        "issue_type": "解析容错",
        "risk_level": "高",
        "title": "模型输出未能完整解析",
        "description": "系统已保留固定可视化面板和原始输出摘要，避免退回裸 JSON。建议重新运行审核，或检查模型是否严格返回指定 JSON schema。",
        "evidence": excerpt,
        "commercial_impact": "当前无法可靠计算心电曲线和单集评分。",
        "fix_strategy": "请让模型只返回合法 JSON，或点击重新运行爆款文审核。",
        "expected_improvement": "重新解析后可恢复完整心电图、全局评价和单集评价。",
    }
    return {
        "schema_version": SCHEMA_VERSION_V3,
        "meta": {
            "script_title": script_title,
            "text_type": "未知",
            "audit_scope": "解析容错",
            "total_episode_count": 0,
            "total_segment_count": 0,
            "is_partial_review": True,
            "is_stage_score": False,
            "evidence_policy": "模型输出解析失败时，仅展示原始输出摘要和解析提示。",
        },
        "overall": {
            "total_score": 0,
            "level": "待重新解析",
            "modification_cost": "未知",
            "core_judgement": "模型输出未能完整解析，已进入容错展示模式。",
            "largest_hard_problem": "缺少合法结构化 JSON。",
            "best_retained_part": "",
            "final_judgement": "请重新运行审核或修正模型输出格式后再查看完整心电图。",
            "top_improvement_metrics": [],
        },
        "dimension_scores": [],
        "segments": [],
        "global_review": {
            "review_scope": "解析容错",
            "global_structure_judgement": {
                "global_retention_problem": "当前结果缺少可解析心电节点。",
                "global_revision_priority": "优先修复模型输出格式。",
            },
            "ecg": {
                "title": "全剧总心电图",
                "x_axis_type": "global_offset",
                "y_axis_range": [-5, 5],
                "baseline": 0,
                "main_series": {
                    "series_key": "global_retention_ecg",
                    "series_name": "全剧商业留存心电图",
                    "description": "解析失败时暂不生成节点。",
                    "points": [],
                },
                "secondary_series": [],
                "negative_zones": [],
                "peak_points": [],
                "valley_points": [],
            },
            "episode_score_map": [],
            "global_satisfying_points": [],
            "global_key_issues": [issue],
            "global_risk_scan": [],
            "global_rewrite_plan": [{
                "task_id": "parse_retry_001",
                "priority": 1,
                "target": "合规",
                "problem": "返回内容不是可解析的 v3 JSON。",
                "specific_action": "重新运行爆款文审核，要求模型只输出合法 JSON。",
                "before_logic": "",
                "after_logic": "可生成全剧心电图与单集评价。",
                "affected_segments": [],
                "expected_result": "恢复完整可视化审核结果。",
            }],
        },
        "episode_reviews": [],
        "cross_episode_analysis": {
            "title": "跨集结构分析",
            "retention_curve_summary": "解析失败，暂无法生成跨集结构分析。",
        },
        "parse_fallback": {
            "enabled": True,
            "warnings": parse_warnings,
            "raw_excerpt": excerpt,
        },
    }


def _extract_text_from_known_fields(raw: Any) -> list[str]:
    texts: list[str] = []
    priority_keys = [
        "answer_text",
        "answerText",
        "text",
        "textOutput",
        "output",
        "response",
        "content",
        "result",
        "data",
        "raw",
        "message",
    ]

    def visit(value: Any, depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(value, str):
            if value.strip():
                texts.append(value)
            return
        if isinstance(value, dict):
            for key in priority_keys:
                if key in value:
                    visit(value.get(key), depth + 1)
            for key, item in value.items():
                if key not in priority_keys:
                    visit(item, depth + 1)
            return
        if isinstance(value, list):
            for item in value:
                visit(item, depth + 1)

    visit(raw)
    return texts


def parse_model_json_loose(raw: Any) -> tuple[dict | None, list[str]]:
    warnings: list[str] = []

    if isinstance(raw, dict) and raw.get("schema_version") in SUPPORTED_SCHEMA_VERSIONS:
        return raw, warnings

    texts = _extract_text_from_known_fields(raw)
    if not texts:
        texts = [_as_text(raw)]

    parsed_objects: list[dict] = []

    for text in texts:
        cleaned = _strip_code_fence(text)
        candidates = [cleaned, *_iter_balanced_json_candidates(cleaned)]
        seen: set[str] = set()

        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)

            try:
                data = _json_loads_maybe_nested(candidate)
            except Exception as exc:
                warnings.append(f"JSON candidate parse failed: {exc}")
                continue

            if isinstance(data, dict):
                parsed_objects.append(data)
            elif isinstance(data, list):
                parsed_objects.extend(item for item in data if isinstance(item, dict))

    for obj in parsed_objects:
        if obj.get("schema_version") in SUPPORTED_SCHEMA_VERSIONS:
            return obj, warnings

    if isinstance(raw, dict):
        return raw, warnings

    if parsed_objects:
        return parsed_objects[0], warnings

    return None, warnings or ["模型输出未解析出 JSON object"]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except Exception:
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(round(_num(value, default)))
    except Exception:
        return default


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    return max(low, min(high, _num(value, default)))


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _str(value: Any, default: str = "") -> str:
    return str(value if value is not None else default).strip()


def _value_type(value: float) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"


def _score_text(value: float) -> str:
    number: int | float = int(value) if float(value).is_integer() else round(value, 1)
    return f"+{number}" if number > 0 else str(number)


def _first_text(*values: Any) -> str:
    for value in values:
        text = _str(value)
        if text:
            return text
    return ""


def _normalize_dimension_scores(items: Any) -> list[dict]:
    normalized = []
    for dim_index, dim in enumerate(_list(items), start=1):
        if not isinstance(dim, dict):
            continue

        sub_items = []
        for sub_index, sub in enumerate(_list(dim.get("sub_items")), start=1):
            if not isinstance(sub, dict):
                continue
            raw_score = _clamp(sub.get("raw_score"), 0, 5)
            weight = _num(sub.get("weight"), 0)
            weighted_score = _num(sub.get("weighted_score"), raw_score / 5 * weight if weight else 0)
            sub_items.append({
                "sub_key": _str(sub.get("sub_key"), f"sub_{sub_index:02d}"),
                "sub_name": _str(sub.get("sub_name"), f"子项{sub_index}"),
                "raw_score": raw_score,
                "raw_score_max": 5,
                "weight": weight,
                "weighted_score": round(weighted_score, 2),
                "evidence": _str(sub.get("evidence")),
                "deduction_reason": _str(sub.get("deduction_reason")),
                "fix_direction": _str(sub.get("fix_direction")),
                "related_segment_ids": _list(sub.get("related_segment_ids")),
            })

        max_score = _num(dim.get("max_score"), 0)
        score = _num(dim.get("score"), sum(item["weighted_score"] for item in sub_items))
        if max_score > 0:
            score = min(score, max_score)

        normalized.append({
            "dimension_key": _str(dim.get("dimension_key"), f"dimension_{dim_index:02d}"),
            "dimension_name": _str(dim.get("dimension_name"), f"维度{dim_index}"),
            "max_score": max_score,
            "score": round(score, 2),
            "summary": _str(dim.get("summary")),
            "core_deductions": _list(dim.get("core_deductions")),
            "priority_fix": _str(dim.get("priority_fix")),
            "sub_items": sub_items,
        })
    return normalized


def _normalize_segments(items: Any) -> list[dict]:
    segments = []
    last_end = 0
    for index, seg in enumerate(_list(items), start=1):
        if not isinstance(seg, dict):
            continue
        start_offset = max(0, _int(seg.get("start_offset"), last_end))
        end_offset = max(start_offset, _int(seg.get("end_offset"), start_offset))
        last_end = end_offset
        segments.append({
            "segment_id": _str(seg.get("segment_id"), f"seg_{index:06d}"),
            "episode_no": _int(seg.get("episode_no"), 0),
            "scene_no": _int(seg.get("scene_no"), 0),
            "segment_index": _int(seg.get("segment_index") or seg.get("segment_index_global"), index),
            "segment_index_global": _int(seg.get("segment_index_global") or seg.get("segment_index"), index),
            "segment_index_in_episode": _int(seg.get("segment_index_in_episode"), 0),
            "start_offset": start_offset,
            "end_offset": end_offset,
            "segment_type": _str(seg.get("segment_type")),
            "original_text_excerpt": _str(seg.get("original_text_excerpt")),
            "segment_function": _str(seg.get("segment_function")),
            "has_goal": bool(seg.get("has_goal", False)),
            "has_obstacle": bool(seg.get("has_obstacle", False)),
            "has_choice": bool(seg.get("has_choice", False)),
            "has_consequence": bool(seg.get("has_consequence", False)),
        })
    return segments


def _normalize_ecg_points(items: Any, *, segments: list[dict], warnings: list[str], scope: str = "global") -> list[dict]:
    segment_by_id = {item["segment_id"]: item for item in segments}
    points = []
    for index, point in enumerate(_list(items), start=1):
        if not isinstance(point, dict):
            continue

        ecg_value = _clamp(point.get("ecg_value"), -5, 5)
        segment_id = _str(point.get("segment_id"))
        segment = segment_by_id.get(segment_id) if segment_id else None
        if not segment_id and index <= len(segments):
            segment = segments[index - 1]
            segment_id = segment["segment_id"]
        if segment_id and segment_by_id and segment_id not in segment_by_id:
            warnings.append(f"{scope} ecg point {index} segment_id not found: {segment_id}")

        hover = _dict(point.get("hover_card"))
        original_text_excerpt = _first_text(point.get("original_text_excerpt"), segment.get("original_text_excerpt") if segment else "")
        audit_reason = _str(point.get("audit_reason"))
        fix_suggestion = _str(point.get("fix_suggestion"))
        event_type = _str(point.get("event_type"))
        short_label = _str(point.get("short_label"))
        global_index = _int(
            point.get("segment_index_global")
            or point.get("segment_index")
            or (segment.get("segment_index_global") if segment else 0),
            index,
        )

        points.append({
            "point_id": _str(point.get("point_id"), f"{scope}_p_{index:06d}"),
            "segment_id": segment_id,
            "episode_no": _int(point.get("episode_no"), segment.get("episode_no", 0) if segment else 0),
            "scene_no": _int(point.get("scene_no"), segment.get("scene_no", 0) if segment else 0),
            "segment_index": global_index,
            "segment_index_global": global_index,
            "segment_index_in_episode": _int(point.get("segment_index_in_episode"), segment.get("segment_index_in_episode", 0) if segment else index),
            "start_offset": _int(point.get("start_offset"), segment.get("start_offset", index) if segment else index),
            "end_offset": _int(point.get("end_offset"), segment.get("end_offset", index) if segment else index),
            "x_label": _str(point.get("x_label"), f"第{global_index}段"),
            "ecg_value": ecg_value,
            "value_type": _value_type(ecg_value),
            "event_type": event_type,
            "event_subtype": _str(point.get("event_subtype")),
            "short_label": short_label,
            "original_text_excerpt": original_text_excerpt,
            "audit_reason": audit_reason,
            "commercial_effect": _str(point.get("commercial_effect")),
            "problem_if_any": _str(point.get("problem_if_any")),
            "fix_suggestion": fix_suggestion,
            "tags": _list(point.get("tags")),
            "hover_card": {
                "title": _str(hover.get("title"), short_label or f"第{global_index}段"),
                "subtitle": _str(hover.get("subtitle"), f"第{_int(point.get('episode_no'), segment.get('episode_no', 0) if segment else 0)}集"),
                "score_text": _str(hover.get("score_text"), _score_text(ecg_value)),
                "body": _str(hover.get("body"), audit_reason),
                "evidence": _str(hover.get("evidence"), original_text_excerpt),
                "fix": _str(hover.get("fix"), fix_suggestion),
            },
            "score_impacts": _list(point.get("score_impacts")),
        })

    return sorted(points, key=lambda item: (
        item.get("episode_no") or 0,
        item.get("segment_index_global") or item.get("segment_index") or 0,
        item.get("start_offset") or 0,
    ))


def _normalize_ecg(ecg_value: Any, *, title: str, segments: list[dict], warnings: list[str], scope: str) -> dict:
    ecg = _dict(ecg_value)
    main_series = _dict(ecg.get("main_series"))
    points = _normalize_ecg_points(main_series.get("points"), segments=segments, warnings=warnings, scope=scope)
    normalized = {
        "title": _str(ecg.get("title"), title),
        "x_axis_type": _str(ecg.get("x_axis_type"), "global_offset" if scope == "global" else "episode_offset"),
        "y_axis_range": [-5, 5],
        "baseline": 0,
        "main_series": {
            "series_key": _str(main_series.get("series_key"), "global_retention_ecg" if scope == "global" else "episode_retention_ecg"),
            "series_name": _str(main_series.get("series_name"), "全剧商业留存心电图" if scope == "global" else "本集商业留存心电图"),
            "description": _str(main_series.get("description"), "正分表示提升继续观看动力，负分表示降低继续观看动力"),
            "points": points,
        },
        "secondary_series": _list(ecg.get("secondary_series")),
        "negative_zones": _list(ecg.get("negative_zones")),
        "peak_points": _list(ecg.get("peak_points")),
        "valley_points": _list(ecg.get("valley_points")),
    }

    if not normalized["peak_points"] and points:
        normalized["peak_points"] = [
            point["point_id"]
            for point in sorted(points, key=lambda item: item["ecg_value"], reverse=True)[:5]
            if point["ecg_value"] > 0
        ]
    if not normalized["valley_points"] and points:
        normalized["valley_points"] = [
            point["point_id"]
            for point in sorted(points, key=lambda item: item["ecg_value"])[:5]
            if point["ecg_value"] < 0
        ]
    if not normalized["negative_zones"] and points:
        zones = []
        current = []
        for point in points:
            if point["ecg_value"] <= -2:
                current.append(point)
                continue
            if len(current) >= 2:
                zones.append(_build_negative_zone(len(zones) + 1, current))
            current = []
        if len(current) >= 2:
            zones.append(_build_negative_zone(len(zones) + 1, current))
        normalized["negative_zones"] = zones
    return normalized


def _normalize_episode_reviews(items: Any, *, segments: list[dict], warnings: list[str]) -> list[dict]:
    normalized = []
    for index, episode in enumerate(_list(items), start=1):
        if not isinstance(episode, dict):
            continue
        episode_no = _int(episode.get("episode_no"), index)
        episode_segments = [item for item in segments if item.get("episode_no") == episode_no] or segments
        normalized.append({
            "episode_no": episode_no,
            "episode_title": _str(episode.get("episode_title"), f"第{episode_no}集"),
            "episode_scope": _dict(episode.get("episode_scope")),
            "episode_overall": _dict(episode.get("episode_overall")),
            "dimension_scores": _normalize_dimension_scores(episode.get("dimension_scores")),
            "ecg": _normalize_ecg(
                episode.get("ecg"),
                title="单集心电图",
                segments=episode_segments,
                warnings=warnings,
                scope=f"episode_{episode_no}",
            ),
            "ending_hook": _dict(episode.get("ending_hook")),
            "satisfying_points": _list(episode.get("satisfying_points")),
            "key_issues": _list(episode.get("key_issues")),
            "risk_scan": _list(episode.get("risk_scan")),
            "rewrite_plan": _list(episode.get("rewrite_plan")),
        })
    return sorted(normalized, key=lambda item: item.get("episode_no") or 0)


def _episode_markers(points: list[dict], episode_score_map: list[dict]) -> list[dict]:
    grouped: dict[int, list[dict]] = {}
    for point in points:
        episode_no = _int(point.get("episode_no"), 0)
        if episode_no:
            grouped.setdefault(episode_no, []).append(point)

    score_by_episode = {
        _int(item.get("episode_no"), 0): item
        for item in episode_score_map
        if isinstance(item, dict)
    }
    markers = []
    for episode_no in sorted(grouped):
        group = grouped[episode_no]
        score = score_by_episode.get(episode_no, {})
        markers.append({
            "episode_no": episode_no,
            "episode_title": _str(score.get("episode_title"), f"第{episode_no}集"),
            "start_index": min(_int(item.get("segment_index_global"), index + 1) for index, item in enumerate(group)),
            "point_count": len(group),
            "episode_score": score.get("episode_score", ""),
            "retention_status": score.get("retention_status", ""),
            "main_problem": score.get("main_problem", ""),
            "next_priority_fix": score.get("next_priority_fix", ""),
        })
    return markers


def _default_audit() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "script_title": "",
            "text_type": "",
            "audit_scope": "",
            "total_episode_count": 0,
            "total_segment_count": 0,
            "is_partial_review": False,
            "is_stage_score": False,
            "evidence_policy": "所有判断基于原文证据，证据不足时不得补设定",
        },
        "overall": {
            "total_score": 0,
            "level": "",
            "modification_cost": "",
            "core_judgement": "",
            "largest_hard_problem": "",
            "best_retained_part": "",
            "final_judgement": "",
            "top_improvement_metrics": [],
        },
        "dimension_scores": [],
        "segments": [],
        "ecg": {
            "title": "剧本心电图",
            "x_axis_type": "offset",
            "y_axis_range": [-5, 5],
            "baseline": 0,
            "main_series": {
                "series_key": "retention_ecg",
                "series_name": "商业留存心电图",
                "description": "正分表示提升继续观看动力，负分表示降低继续观看动力",
                "points": [],
            },
            "secondary_series": [],
            "negative_zones": [],
            "peak_points": [],
            "valley_points": [],
        },
        "episode_summaries": [],
        "satisfying_points": [],
        "key_issues": [],
        "risk_scan": [],
        "rewrite_plan": [],
        "visualization_config": {
            "ecg_chart": {
                "enabled": True,
                "line_animation": True,
                "hover_enabled": True,
                "click_to_detail": True,
                "positive_color": "green",
                "negative_color": "red",
                "zero_line": True,
                "show_episode_markers": True,
            },
            "cards": {
                "show_overall_score": True,
                "show_dimension_cards": True,
                "show_key_issues": True,
                "show_satisfying_points": True,
                "show_risk_scan": True,
                "show_rewrite_plan": True,
            },
            "filters": {
                "by_episode": True,
                "by_issue_type": True,
                "by_risk_level": True,
                "by_ecg_value_range": True,
                "by_satisfying_point_type": True,
            },
        },
    }


def _deep_merge_defaults(default: dict, data: dict) -> dict:
    result = copy.deepcopy(default)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_defaults(result[key], value)
        else:
            result[key] = value
    return result


def _build_negative_zone(index: int, points: list[dict]) -> dict:
    first = points[0]
    last = points[-1]
    min_value = min(float(point.get("ecg_value", 0)) for point in points)
    severity = "高" if min_value <= -4 or len(points) >= 4 else "中"
    return {
        "zone_id": f"zone_{index:03d}",
        "start_segment_id": first.get("segment_id", ""),
        "end_segment_id": last.get("segment_id", ""),
        "episode_no": first.get("episode_no", 0),
        "risk_type": "连续低留存区间",
        "severity": severity,
        "reason": "连续多个心电点位低于 -2，说明该区间存在节奏拖慢、空转或爽点欠账风险。",
        "fix_suggestion": "压缩解释性内容，补入具体目标、阻力、选择、后果或段尾钩子。",
    }


def parse_compact_audit_json(raw_text: str) -> dict:
    """
    解析模型返回的 script_audit_compact_v1 JSON。
    兼容前后空白、BOM、代码块、文本包壳、answerText/data/output/result
    包装字段，以及字符串化 JSON 嵌套。
    """
    if raw_text is None or (isinstance(raw_text, str) and not raw_text.strip()):
        raise ValueError("爆款文审核 compact JSON 为空，无法解析。")

    wrapper_keys = (
        "answerText",
        "answer_text",
        "data",
        "output",
        "result",
        "response",
        "content",
        "text",
    )

    def parse_any(value: Any, depth: int = 0) -> dict:
        if depth > 8:
            raise ValueError("爆款文审核 compact JSON 嵌套过深，无法继续解析。")
        if isinstance(value, dict):
            if value.get("schema_version") == COMPACT_SCHEMA_VERSION:
                return value
            for key in wrapper_keys:
                nested = value.get(key)
                if isinstance(nested, dict) and nested.get("schema_version") == COMPACT_SCHEMA_VERSION:
                    return nested
                if isinstance(nested, str) and nested.strip():
                    try:
                        return parse_any(nested, depth + 1)
                    except Exception:
                        continue
            return value
        if isinstance(value, list):
            for item in value:
                try:
                    return parse_any(item, depth + 1)
                except Exception:
                    continue
            raise ValueError("爆款文审核 compact JSON 数组中没有可解析对象。")
        if not isinstance(value, str):
            raise ValueError(f"爆款文审核 compact JSON 类型不支持：{type(value).__name__}")

        text = value.lstrip("\ufeff").strip()
        if not text:
            raise ValueError("爆款文审核 compact JSON 文本为空。")
        candidates = [_strip_code_fence(text), *_iter_balanced_json_candidates(text)]
        last_error: Exception | None = None
        seen: set[str] = set()
        for candidate in candidates:
            candidate = candidate.lstrip("\ufeff").strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                parsed = _json_loads_maybe_nested(candidate)
            except Exception as exc:
                last_error = exc
                continue
            if isinstance(parsed, str):
                return parse_any(parsed, depth + 1)
            if isinstance(parsed, dict):
                return parse_any(parsed, depth + 1)
        raise ValueError(f"无法解析爆款文审核 compact JSON：{last_error or '未找到 JSON 对象'}")

    parsed = parse_any(raw_text)
    if not isinstance(parsed, dict):
        raise ValueError("爆款文审核 compact JSON 最终结果不是对象。")
    return parsed


def _compact_default() -> dict:
    return {
        "schema_version": COMPACT_SCHEMA_VERSION,
        "meta": {
            "script_title": "",
            "text_type": "",
            "total_episode_count": 0,
            "total_segment_count": 0,
            "is_partial_review": False,
            "episode_detection": {
                "has_explicit_episode_titles": False,
                "detected_episode_numbers": [],
                "missing_episode_numbers": [],
                "duplicate_episode_numbers": [],
                "episode_order_is_valid": True,
                "detection_evidence": "",
            },
        },
        "overall": {
            "total_score": 0,
            "level": "",
            "modification_cost": "",
            "core_judgement": "",
            "largest_problem": "",
            "best_retained_part": "",
            "final_judgement": "",
            "priority_fix": "",
        },
        "dimension_scores": [],
        "segments": [],
        "global_review": {
            "main_genre": "",
            "main_emotional_contract": "",
            "main_conflict_chain": "",
            "protagonist_arc": "",
            "payoff_chain": "",
            "global_retention_problem": "",
            "global_revision_priority": "",
            "global_ecg_points": [],
            "global_satisfying_points": [],
            "global_key_issues": [],
            "global_risk_scan": [],
            "global_rewrite_plan": [],
        },
        "episode_reviews": [],
        "cross_episode_analysis": {
            "retention_curve_summary": "",
            "weak_episode_numbers": [],
            "payoff_distribution_problem": "",
            "hook_continuity_problem": "",
            "character_arc_problem": "",
            "fix_suggestion": "",
        },
    }


def _compact_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "是"}:
            return True
        if lowered in {"false", "0", "no", "否"}:
            return False
    if value is None or value == "":
        return default
    return bool(value)


def _compact_alias_dimension(item: dict) -> dict:
    result = dict(item)
    if "dimension_key" not in result and "key" in result:
        result["dimension_key"] = result.get("key")
    if "deduction_reason" not in result:
        result["deduction_reason"] = result.get("main_deduction") or result.get("deduction") or ""
    if "fix_direction" not in result:
        result["fix_direction"] = result.get("priority_fix") or result.get("fix") or result.get("fix_suggestion") or ""
    if "evidence_segment_ids" not in result:
        result["evidence_segment_ids"] = (
            result.get("related_segment_ids")
            or result.get("affected_segments")
            or []
        )
    return result


def _compact_missing_dimension(spec: dict) -> dict:
    return {
        "dimension_key": spec["dimension_key"],
        "dimension_name": spec["dimension_name"],
        "max_score": spec["max_score"],
        "score": 0,
        "summary": "模型未返回该维度，后端已补齐",
        "deduction_reason": "证据不足",
        "fix_direction": "",
        "evidence_segment_ids": [],
    }


def _normalize_compact_dimensions(items: Any, warnings: list[str], *, scope: str) -> list[dict]:
    raw_by_key: dict[str, dict] = {}
    loose_items: list[dict] = []
    for item in _list(items):
        if not isinstance(item, dict):
            warnings.append(f"{scope} 评分维度包含非对象条目，已忽略。")
            continue
        aliased = _compact_alias_dimension(item)
        key = _str(aliased.get("dimension_key"))
        if key:
            raw_by_key[key] = aliased
        else:
            loose_items.append(aliased)

    normalized: list[dict] = []
    for index, spec in enumerate(AUDIT_DIMENSIONS):
        source = raw_by_key.get(spec["dimension_key"])
        if source is None and index < len(loose_items):
            source = loose_items[index]
            warnings.append(f"{scope} 第{index + 1}个评分维度缺少 dimension_key，已按固定维度顺序兼容。")
        if source is None:
            warnings.append(f"{scope} 缺少评分维度：{spec['dimension_name']}，后端已补齐。")
            normalized.append(_compact_missing_dimension(spec))
            continue

        max_score = _num(source.get("max_score"), spec["max_score"]) or spec["max_score"]
        max_score = max(0, max_score)
        score = _clamp(source.get("score"), 0, max_score)
        normalized.append({
            "dimension_key": spec["dimension_key"],
            "dimension_name": _str(source.get("dimension_name"), spec["dimension_name"]),
            "max_score": max_score,
            "score": round(score, 2),
            "summary": _str(source.get("summary")),
            "deduction_reason": _str(source.get("deduction_reason")),
            "fix_direction": _str(source.get("fix_direction")),
            "evidence_segment_ids": _list(source.get("evidence_segment_ids")),
            "core_deductions": _list(source.get("core_deductions")),
            "priority_fix": _str(source.get("priority_fix") or source.get("fix_direction")),
            "sub_items": _list(source.get("sub_items")),
        })
    return normalized


def _normalize_compact_ecg_points(items: Any, warnings: list[str], *, scope: str) -> list[dict]:
    normalized = []
    for index, item in enumerate(_list(items), start=1):
        if not isinstance(item, dict):
            warnings.append(f"{scope} 心电点位第{index}项不是对象，已忽略。")
            continue
        ecg_value = _clamp(item.get("ecg_value", item.get("value")), -5, 5)
        normalized.append({
            **item,
            "point_id": _str(item.get("point_id"), f"{scope}_p_{index:06d}"),
            "segment_id": _str(item.get("segment_id")),
            "episode_no": _int(item.get("episode_no"), 0),
            "scene_no": _int(item.get("scene_no"), 0),
            "segment_index_global": _int(item.get("segment_index_global") or item.get("segment_index"), index),
            "segment_index_in_episode": _int(item.get("segment_index_in_episode"), index),
            "start_offset": _int(item.get("start_offset"), 0),
            "end_offset": _int(item.get("end_offset"), 0),
            "x_label": _str(item.get("x_label") or item.get("label"), f"第{index}点"),
            "ecg_value": ecg_value,
            "short_label": _str(item.get("short_label") or item.get("label")),
            "audit_reason": _str(item.get("audit_reason") or item.get("reason")),
            "fix_suggestion": _str(item.get("fix_suggestion") or item.get("fix")),
            "commercial_effect": _str(item.get("commercial_effect")),
            "problem_if_any": _str(item.get("problem_if_any")),
            "event_type": _str(item.get("event_type")),
            "event_subtype": _str(item.get("event_subtype")),
            "original_text_excerpt": _str(item.get("original_text_excerpt")),
            "tags": _list(item.get("tags")),
            "score_impacts": _list(item.get("score_impacts")),
        })
    return sorted(normalized, key=lambda point: (
        _int(point.get("episode_no"), 0),
        _int(point.get("segment_index_global"), 0),
        _int(point.get("start_offset"), 0),
    ))


def _extract_compact_global_points(global_review: dict, data: dict) -> list:
    direct = global_review.get("global_ecg_points")
    if isinstance(direct, list):
        return direct
    if isinstance(global_review.get("ecg_points"), list):
        return global_review.get("ecg_points")
    old_points = _dict(_dict(global_review.get("ecg")).get("main_series")).get("points")
    if isinstance(old_points, list):
        return old_points
    old_global = _dict(data.get("ecg"))
    return _list(_dict(old_global.get("main_series")).get("points") or old_global.get("points"))


def _extract_compact_episode_points(episode: dict) -> list:
    if isinstance(episode.get("ecg_points"), list):
        return episode.get("ecg_points")
    return _list(_dict(_dict(episode.get("ecg")).get("main_series")).get("points"))


def normalize_compact_audit_payload(data: dict) -> tuple[dict, list[str]]:
    """
    将模型输出标准化为 canonical script_audit_compact_v1。
    返回 audit 和 warnings。
    """
    warnings: list[str] = []
    if not isinstance(data, dict):
        raise ValueError("爆款文审核 compact payload 必须是 JSON object。")

    if data.get("schema_version") != COMPACT_SCHEMA_VERSION:
        warnings.append("模型输出 schema_version 缺失或不是 script_audit_compact_v1，已按 compact v1 兼容解析。")

    audit = _compact_default()

    meta = _dict(data.get("meta"))
    detection = _dict(meta.get("episode_detection"))
    audit["meta"] = {
        "script_title": _str(meta.get("script_title") or data.get("script_title")),
        "text_type": _str(meta.get("text_type")),
        "total_episode_count": 0,
        "total_segment_count": _int(meta.get("total_segment_count"), 0),
        "is_partial_review": _compact_bool(meta.get("is_partial_review"), False),
        "episode_detection": {
            "has_explicit_episode_titles": _compact_bool(detection.get("has_explicit_episode_titles"), False),
            "detected_episode_numbers": _list(detection.get("detected_episode_numbers")),
            "missing_episode_numbers": _list(detection.get("missing_episode_numbers")),
            "duplicate_episode_numbers": _list(detection.get("duplicate_episode_numbers")),
            "episode_order_is_valid": _compact_bool(detection.get("episode_order_is_valid"), True),
            "detection_evidence": _str(detection.get("detection_evidence")),
        },
    }

    dimension_source = data.get("dimension_scores")
    if dimension_source is None and data.get("global_dimensions") is not None:
        dimension_source = data.get("global_dimensions")
        warnings.append("已将 global_dimensions 转换为 dimension_scores。")
    dimensions = _normalize_compact_dimensions(dimension_source, warnings, scope="全局")
    audit["dimension_scores"] = dimensions

    segments = _normalize_segments(data.get("segments"))
    audit["segments"] = segments

    overall_source = _dict(data.get("overall"))
    total_score = round(sum(_num(item.get("score"), 0) for item in dimensions), 2)
    audit["overall"] = {
        "total_score": total_score,
        "level": _str(overall_source.get("level")),
        "modification_cost": _str(overall_source.get("modification_cost")),
        "core_judgement": _str(overall_source.get("core_judgement")),
        "largest_problem": _str(overall_source.get("largest_problem") or overall_source.get("largest_hard_problem")),
        "best_retained_part": _str(overall_source.get("best_retained_part")),
        "final_judgement": _str(overall_source.get("final_judgement")),
        "priority_fix": _str(overall_source.get("priority_fix")),
    }

    global_source = _dict(data.get("global_review"))
    structure = _dict(global_source.get("global_structure_judgement"))
    global_points = _normalize_compact_ecg_points(
        _extract_compact_global_points(global_source, data),
        warnings,
        scope="global",
    )
    audit["global_review"] = {
        "main_genre": _str(global_source.get("main_genre") or structure.get("main_genre")),
        "main_emotional_contract": _str(global_source.get("main_emotional_contract") or structure.get("main_emotional_contract")),
        "main_conflict_chain": _str(global_source.get("main_conflict_chain") or structure.get("main_conflict_chain")),
        "protagonist_arc": _str(global_source.get("protagonist_arc") or structure.get("protagonist_arc")),
        "payoff_chain": _str(global_source.get("payoff_chain") or structure.get("payoff_chain")),
        "global_retention_problem": _str(global_source.get("global_retention_problem") or structure.get("global_retention_problem")),
        "global_revision_priority": _str(global_source.get("global_revision_priority") or structure.get("global_revision_priority")),
        "global_ecg_points": global_points,
        "global_satisfying_points": _list(global_source.get("global_satisfying_points")),
        "global_key_issues": _list(global_source.get("global_key_issues")),
        "global_risk_scan": _list(global_source.get("global_risk_scan")),
        "global_rewrite_plan": _list(global_source.get("global_rewrite_plan")),
    }

    episode_source = data.get("episode_reviews")
    if episode_source is None and data.get("episodes") is not None:
        episode_source = data.get("episodes")
        warnings.append("已将 episodes 转换为 episode_reviews。")
    episodes = []
    for index, episode in enumerate(_list(episode_source), start=1):
        if not isinstance(episode, dict):
            warnings.append(f"第{index}个单集评价不是对象，已忽略。")
            continue
        episode_no = _int(episode.get("episode_no"), index)
        episode_dimensions_source = episode.get("dimension_scores")
        if episode_dimensions_source is None and episode.get("dimensions") is not None:
            episode_dimensions_source = episode.get("dimensions")
            warnings.append(f"第{episode_no}集已将 dimensions 转换为 dimension_scores。")
        episode_dimensions = _normalize_compact_dimensions(
            episode_dimensions_source,
            warnings,
            scope=f"第{episode_no}集",
        )
        episode_score = round(sum(_num(item.get("score"), 0) for item in episode_dimensions), 2)
        rewrite_plan = episode.get("rewrite_plan")
        if rewrite_plan is None and episode.get("rewrite_tasks") is not None:
            rewrite_plan = episode.get("rewrite_tasks")
            warnings.append(f"第{episode_no}集已将 rewrite_tasks 转换为 rewrite_plan。")
        episode_overall = _dict(episode.get("episode_overall"))
        episodes.append({
            "episode_no": episode_no,
            "episode_title": _str(episode.get("episode_title"), f"第{episode_no}集"),
            "episode_score": episode_score,
            "level": _str(episode.get("level") or episode_overall.get("level")),
            "core_judgement": _str(episode.get("core_judgement") or episode_overall.get("core_judgement")),
            "main_hook": _str(episode.get("main_hook") or episode_overall.get("main_hook")),
            "main_conflict": _str(episode.get("main_conflict") or episode_overall.get("main_conflict")),
            "main_payoff": _str(episode.get("main_payoff") or episode_overall.get("main_payoff")),
            "largest_retention_loss": _str(episode.get("largest_retention_loss") or episode_overall.get("largest_retention_loss")),
            "best_retained_part": _str(episode.get("best_retained_part") or episode_overall.get("best_retained_part")),
            "next_episode_pull": _str(episode.get("next_episode_pull") or episode_overall.get("next_episode_pull")),
            "priority_fix": _str(episode.get("priority_fix") or episode_overall.get("priority_fix")),
            "dimension_scores": episode_dimensions,
            "ecg_points": _normalize_compact_ecg_points(
                _extract_compact_episode_points(episode),
                warnings,
                scope=f"episode_{episode_no}",
            ),
            "ending_hook": _dict(episode.get("ending_hook")),
            "satisfying_points": _list(episode.get("satisfying_points")),
            "key_issues": _list(episode.get("key_issues")),
            "risk_scan": _list(episode.get("risk_scan")),
            "rewrite_plan": _list(rewrite_plan),
        })
    audit["episode_reviews"] = sorted(episodes, key=lambda item: _int(item.get("episode_no"), 0))
    audit["meta"]["total_episode_count"] = len(audit["episode_reviews"])
    if not audit["meta"]["total_segment_count"]:
        audit["meta"]["total_segment_count"] = len(segments)

    cross = _dict(data.get("cross_episode_analysis"))
    payoff = _dict(cross.get("payoff_distribution"))
    hook = _dict(cross.get("hook_continuity"))
    character = _dict(cross.get("character_arc_continuity"))
    audit["cross_episode_analysis"] = {
        "retention_curve_summary": _str(cross.get("retention_curve_summary")),
        "weak_episode_numbers": _list(cross.get("weak_episode_numbers") or hook.get("weak_episode_numbers")),
        "payoff_distribution_problem": _str(cross.get("payoff_distribution_problem") or payoff.get("evidence") or payoff.get("fix_suggestion")),
        "hook_continuity_problem": _str(cross.get("hook_continuity_problem") or hook.get("evidence") or hook.get("fix_suggestion")),
        "character_arc_problem": _str(cross.get("character_arc_problem") or character.get("problem") or character.get("fix_suggestion")),
        "fix_suggestion": _str(cross.get("fix_suggestion") or payoff.get("fix_suggestion") or hook.get("fix_suggestion") or character.get("fix_suggestion")),
    }

    warnings.extend(validate_compact_audit_schema(audit))
    return audit, warnings


def validate_compact_audit_schema(audit: dict) -> list[str]:
    warnings: list[str] = []
    if not isinstance(audit, dict):
        raise ValueError("标准化后的 compact audit 必须是对象。")
    if audit.get("schema_version") != COMPACT_SCHEMA_VERSION:
        raise ValueError("标准化后的 compact audit schema_version 必须是 script_audit_compact_v1。")

    required = (
        "meta",
        "overall",
        "dimension_scores",
        "segments",
        "global_review",
        "episode_reviews",
        "cross_episode_analysis",
    )
    for key in required:
        if key not in audit:
            warnings.append(f"缺少顶层字段 {key}，已由后端补齐默认值。")

    dimension_keys = {item.get("dimension_key") for item in _list(audit.get("dimension_scores")) if isinstance(item, dict)}
    for spec in AUDIT_DIMENSIONS:
        if spec["dimension_key"] not in dimension_keys:
            warnings.append(f"全局评分维度仍缺失：{spec['dimension_name']}。")

    for episode in _list(audit.get("episode_reviews")):
        if not isinstance(episode, dict):
            continue
        episode_keys = {item.get("dimension_key") for item in _list(episode.get("dimension_scores")) if isinstance(item, dict)}
        for spec in AUDIT_DIMENSIONS:
            if spec["dimension_key"] not in episode_keys:
                warnings.append(f"第{episode.get('episode_no') or '?'}集评分维度仍缺失：{spec['dimension_name']}。")

    seen_segments: set[str] = set()
    duplicate_segments: set[str] = set()
    for segment in _list(audit.get("segments")):
        if not isinstance(segment, dict):
            continue
        segment_id = _str(segment.get("segment_id"))
        if not segment_id:
            continue
        if segment_id in seen_segments:
            duplicate_segments.add(segment_id)
        seen_segments.add(segment_id)
    if duplicate_segments:
        warnings.append(f"segments.segment_id 存在重复：{', '.join(sorted(duplicate_segments))}")

    all_points = list(_list(_dict(audit.get("global_review")).get("global_ecg_points")))
    for episode in _list(audit.get("episode_reviews")):
        if isinstance(episode, dict):
            all_points.extend(_list(episode.get("ecg_points")))
    if seen_segments:
        for point in all_points:
            if not isinstance(point, dict):
                continue
            segment_id = _str(point.get("segment_id"))
            if segment_id and segment_id not in seen_segments:
                warnings.append(f"心电点位引用了不存在的 segment_id：{segment_id}，已保留点位供前端展示。")
    return warnings


def _derived_ecg_points(points: list[dict], segment_by_id: dict[str, dict]) -> list[dict]:
    derived = []
    for index, point in enumerate(points, start=1):
        if not isinstance(point, dict):
            continue
        ecg_value = _clamp(point.get("ecg_value"), -5, 5)
        value_type = _value_type(ecg_value)
        segment = segment_by_id.get(_str(point.get("segment_id")))
        segment_excerpt = _first_text(
            point.get("original_text_excerpt"),
            segment.get("original_text_excerpt") if segment else "",
        )
        hover_title = _first_text(
            point.get("short_label"),
            point.get("event_type"),
            point.get("x_label"),
            "心电图节点",
        )
        hover_body = "\n".join([
            f"分值：{_score_text(ecg_value)}",
            f"原因：{_str(point.get('audit_reason'))}",
            f"商业效果：{_str(point.get('commercial_effect'))}",
            f"问题：{_str(point.get('problem_if_any'))}",
            f"建议：{_str(point.get('fix_suggestion'))}",
        ]).strip()
        derived.append({
            **point,
            "x": index,
            "y": ecg_value,
            "ecg_value": ecg_value,
            "value_type": value_type,
            "color": ECG_COLOR_MAP[value_type],
            "hover_title": hover_title,
            "hover_body": hover_body,
            "segment_excerpt": segment_excerpt,
            "original_text_excerpt": segment_excerpt,
            "hover_card": {
                "title": hover_title,
                "subtitle": f"第{point.get('episode_no') or '?'}集",
                "score_text": _score_text(ecg_value),
                "body": _str(point.get("audit_reason")),
                "evidence": segment_excerpt,
                "fix": _str(point.get("fix_suggestion")),
            },
        })
    return derived


def _point_extremes(points: list[dict], *, reverse: bool) -> list[dict]:
    if not points:
        return []
    values = [_num(point.get("ecg_value"), 0) for point in points]
    target = max(values) if reverse else min(values)
    return [
        point
        for point in points
        if _num(point.get("ecg_value"), 0) == target
    ][:3]


def build_audit_visualization_payload(audit: dict) -> dict:
    """
    根据标准化后的 compact audit 派生前端图表和卡片需要的数据。
    这不是模型输出，而是后端生成的 derived payload。
    """
    if not isinstance(audit, dict):
        audit = {}
    segments = _list(audit.get("segments"))
    segment_by_id = {
        _str(segment.get("segment_id")): segment
        for segment in segments
        if isinstance(segment, dict) and _str(segment.get("segment_id"))
    }
    global_review = _dict(audit.get("global_review"))
    global_points = _derived_ecg_points(_list(global_review.get("global_ecg_points")), segment_by_id)

    episode_charts = []
    episode_score_map = []
    for episode in _list(audit.get("episode_reviews")):
        if not isinstance(episode, dict):
            continue
        episode_points = _derived_ecg_points(_list(episode.get("ecg_points")), segment_by_id)
        episode_charts.append({
            "episode_no": _int(episode.get("episode_no"), 0),
            "episode_title": _str(episode.get("episode_title")),
            "points": episode_points,
            "peak_points": _point_extremes(episode_points, reverse=True),
            "valley_points": _point_extremes(episode_points, reverse=False),
        })
        episode_score_map.append({
            "episode_no": _int(episode.get("episode_no"), 0),
            "episode_title": _str(episode.get("episode_title")),
            "episode_score": _num(episode.get("episode_score"), 0),
            "level": _str(episode.get("level")),
            "main_problem": _str(episode.get("largest_retention_loss")),
            "next_priority_fix": _str(episode.get("priority_fix")),
        })

    return {
        "ecg_chart": {
            "global": {
                "points": global_points,
                "peak_points": _point_extremes(global_points, reverse=True),
                "valley_points": _point_extremes(global_points, reverse=False),
            },
            "episodes": episode_charts,
        },
        "episode_score_map": episode_score_map,
        "dimension_cards": [
            {
                **item,
                "level_color": LEVEL_COLOR_MAP.get(_str(item.get("level")), ""),
            }
            for item in _list(audit.get("dimension_scores"))
            if isinstance(item, dict)
        ],
        "issue_cards": _list(global_review.get("global_key_issues")),
        "rewrite_cards": _list(global_review.get("global_rewrite_plan")),
        "risk_cards": [
            {
                **item,
                "risk_color": RISK_COLOR_MAP.get(_str(item.get("risk_level")), ""),
            }
            for item in _list(global_review.get("global_risk_scan"))
            if isinstance(item, dict)
        ],
    }


def normalize_script_audit_ecg(data: dict, raw_answer_text: str = "") -> tuple[dict, list[str]]:
    warnings: list[str] = []
    if not isinstance(data, dict):
        data = {}

    audit = _deep_merge_defaults(_default_audit(), data)
    original_version = _str(data.get("schema_version"), SCHEMA_VERSION)
    audit["schema_version"] = original_version if original_version in SUPPORTED_SCHEMA_VERSIONS else SCHEMA_VERSION

    normalized_dimensions = _normalize_dimension_scores(audit.get("dimension_scores"))
    audit["dimension_scores"] = normalized_dimensions

    segments = _normalize_segments(audit.get("segments"))
    audit["segments"] = segments

    overall = _dict(audit.get("overall"))
    if not _num(overall.get("total_score"), 0) and normalized_dimensions:
        overall["total_score"] = round(sum(dim["score"] for dim in normalized_dimensions), 2)
    audit["overall"] = overall

    global_review = _dict(audit.get("global_review"))
    if global_review:
        global_ecg = _normalize_ecg(
            _dict(global_review.get("ecg")),
            title="全剧总心电图",
            segments=segments,
            warnings=warnings,
            scope="global",
        )
        global_review["ecg"] = global_ecg
        global_review["global_satisfying_points"] = _list(global_review.get("global_satisfying_points"))
        global_review["global_key_issues"] = _list(global_review.get("global_key_issues"))
        global_review["global_risk_scan"] = _list(global_review.get("global_risk_scan"))
        global_review["global_rewrite_plan"] = _list(global_review.get("global_rewrite_plan"))
        global_review["episode_score_map"] = _list(global_review.get("episode_score_map"))
    else:
        global_ecg = _normalize_ecg(
            audit.get("ecg"),
            title="剧本心电图",
            segments=segments,
            warnings=warnings,
            scope="global",
        )
        global_review = {
            "review_scope": "全剧总审核",
            "global_structure_judgement": {},
            "ecg": global_ecg,
            "episode_score_map": _list(audit.get("episode_summaries")),
            "global_satisfying_points": _list(audit.get("satisfying_points")),
            "global_key_issues": _list(audit.get("key_issues")),
            "global_risk_scan": _list(audit.get("risk_scan")),
            "global_rewrite_plan": _list(audit.get("rewrite_plan")),
        }
    audit["global_review"] = global_review
    audit["ecg"] = global_review["ecg"]

    audit["episode_reviews"] = _normalize_episode_reviews(
        audit.get("episode_reviews"),
        segments=segments,
        warnings=warnings,
    )
    audit["cross_episode_analysis"] = _dict(audit.get("cross_episode_analysis"))

    meta = _dict(audit.get("meta"))
    points = _list(_dict(_dict(global_review.get("ecg")).get("main_series")).get("points"))
    meta["total_segment_count"] = _int(meta.get("total_segment_count"), len(segments) or len(points))
    if not _int(meta.get("total_episode_count"), 0):
        episode_numbers = {point.get("episode_no") for point in points if _int(point.get("episode_no"), 0)}
        if audit["episode_reviews"]:
            episode_numbers.update(item.get("episode_no") for item in audit["episode_reviews"] if _int(item.get("episode_no"), 0))
        meta["total_episode_count"] = len(episode_numbers)
    audit["meta"] = meta

    for key in ["episode_summaries", "satisfying_points", "key_issues", "risk_scan", "rewrite_plan"]:
        audit[key] = _list(audit.get(key))

    return audit, warnings


def build_script_audit_view_model(audit: dict) -> dict:
    overall = _dict(audit.get("overall"))
    meta = _dict(audit.get("meta"))
    global_review = _dict(audit.get("global_review"))
    visualization = build_audit_visualization_payload(audit) if audit.get("schema_version") == COMPACT_SCHEMA_VERSION else {}
    compact_global_chart = _dict(_dict(visualization.get("ecg_chart")).get("global"))
    ecg = _dict(global_review.get("ecg") or audit.get("ecg"))
    main_series = _dict(ecg.get("main_series"))
    points = _list(compact_global_chart.get("points") or main_series.get("points"))
    episode_score_map = _list(visualization.get("episode_score_map") or global_review.get("episode_score_map"))
    episode_cards = _list(audit.get("episode_reviews")) or _list(audit.get("episode_summaries"))
    structure = _dict(global_review.get("global_structure_judgement"))
    if not structure and audit.get("schema_version") == COMPACT_SCHEMA_VERSION:
        structure = {
            "main_genre": global_review.get("main_genre", ""),
            "main_emotional_contract": global_review.get("main_emotional_contract", ""),
            "main_conflict_chain": global_review.get("main_conflict_chain", ""),
            "protagonist_arc": global_review.get("protagonist_arc", ""),
            "payoff_chain": global_review.get("payoff_chain", ""),
            "global_retention_problem": global_review.get("global_retention_problem", ""),
            "global_revision_priority": global_review.get("global_revision_priority", ""),
        }
    cross_episode = _dict(audit.get("cross_episode_analysis"))

    export_lines = [
        f"《{meta.get('script_title') or '未命名剧本'}》爆款文审核报告",
        "",
        "一、整体剧本评价",
        f"总评分：{overall.get('total_score', 0)}/100",
        f"评级：{overall.get('level', '')}",
        f"修改成本：{overall.get('modification_cost', '')}",
        f"核心判断：{overall.get('core_judgement', '')}",
        f"最大问题：{overall.get('largest_problem') or overall.get('largest_hard_problem', '')}",
        f"最佳保留：{overall.get('best_retained_part', '')}",
        f"最终判断：{overall.get('final_judgement', '')}",
        "",
        "二、全剧心电图节点摘要",
    ]
    for point in points:
        value = point.get("ecg_value", 0)
        export_lines.append(
            f"- 第{point.get('episode_no') or '?'}集 {point.get('x_label') or point.get('short_label') or point.get('point_id')}: "
            f"{'+' if _num(value) > 0 else ''}{value}，{point.get('audit_reason') or point.get('commercial_effect') or ''}"
        )
    export_lines.extend(["", "三、单集重点评价"])
    for episode in episode_cards:
        if not isinstance(episode, dict):
            continue
        episode_overall = _dict(episode.get("episode_overall") or episode)
        export_lines.append(
            f"- 第{episode.get('episode_no', '')}集 {episode.get('episode_title', '')}: "
            f"{episode_overall.get('episode_score', '')}/100，{episode_overall.get('core_judgement', '')} "
            f"优先修改：{episode_overall.get('priority_fix', '')}"
        )
    if cross_episode:
        export_lines.extend([
            "",
            "四、跨集结构分析",
            f"留存曲线：{cross_episode.get('retention_curve_summary', '')}",
            f"钩子连续性：{_dict(cross_episode.get('hook_continuity')).get('evidence', '') or _dict(cross_episode.get('hook_continuity')).get('fix_suggestion', '')}",
            f"人物弧光：{_dict(cross_episode.get('character_arc_continuity')).get('problem', '') or _dict(cross_episode.get('character_arc_continuity')).get('fix_suggestion', '')}",
        ])

    return {
        "summary_cards": [
            {"key": "total_score", "label": "总评分", "value": overall.get("total_score", 0), "suffix": "/100"},
            {"key": "level", "label": "适配等级", "value": overall.get("level", ""), "suffix": ""},
            {"key": "modification_cost", "label": "修改成本", "value": overall.get("modification_cost", ""), "suffix": ""},
            {"key": "episode_count", "label": "总集数", "value": meta.get("total_episode_count", 0), "suffix": ""},
            {"key": "segment_count", "label": "心电点位", "value": len(points), "suffix": ""},
        ],
        "ecg_chart": {
            "title": ecg.get("title", "剧本心电图"),
            "y_axis_range": ecg.get("y_axis_range", [-5, 5]),
            "baseline": ecg.get("baseline", 0),
            "points": points,
            "episode_markers": _episode_markers(points, episode_score_map),
            "negative_zones": _list(ecg.get("negative_zones")),
            "peak_points": _list(compact_global_chart.get("peak_points") or ecg.get("peak_points")),
            "valley_points": _list(compact_global_chart.get("valley_points") or ecg.get("valley_points")),
        },
        "dimension_cards": _list(visualization.get("dimension_cards") or audit.get("dimension_scores")),
        "global_review": {
            "structure": structure,
            "satisfying_points": _list(global_review.get("global_satisfying_points")),
            "key_issues": _list(global_review.get("global_key_issues")),
            "risk_scan": _list(global_review.get("global_risk_scan")),
            "rewrite_plan": _list(global_review.get("global_rewrite_plan")),
            "episode_score_map": episode_score_map,
        },
        "issue_cards": _list(global_review.get("global_key_issues") or audit.get("key_issues")),
        "satisfying_point_cards": _list(global_review.get("global_satisfying_points") or audit.get("satisfying_points")),
        "risk_cards": _list(global_review.get("global_risk_scan") or audit.get("risk_scan")),
        "rewrite_tasks": _list(global_review.get("global_rewrite_plan") or audit.get("rewrite_plan")),
        "episode_cards": episode_cards,
        "cross_episode_analysis": cross_episode,
        "export_text": "\n".join(str(line).rstrip() for line in export_lines if line is not None).strip(),
        "meta": {
            "script_title": meta.get("script_title", ""),
            "text_type": meta.get("text_type", ""),
            "audit_scope": meta.get("audit_scope", ""),
            "total_episode_count": meta.get("total_episode_count", 0),
            "total_segment_count": meta.get("total_segment_count", 0),
            "is_partial_review": bool(meta.get("is_partial_review", False)),
            "is_stage_score": bool(meta.get("is_stage_score", False)),
        },
    }
