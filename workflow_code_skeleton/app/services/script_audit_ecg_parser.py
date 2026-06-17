from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

SCHEMA_VERSION = "script_audit_ecg_v2"
SCHEMA_VERSION_V3 = "script_audit_ecg_v3_episode_global"
SUPPORTED_SCHEMA_VERSIONS = {SCHEMA_VERSION, SCHEMA_VERSION_V3}


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
    data = json.loads(_strip_code_fence(text))
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
    ecg = _dict(global_review.get("ecg") or audit.get("ecg"))
    main_series = _dict(ecg.get("main_series"))
    points = _list(main_series.get("points"))
    episode_score_map = _list(global_review.get("episode_score_map"))
    episode_cards = _list(audit.get("episode_reviews")) or _list(audit.get("episode_summaries"))
    structure = _dict(global_review.get("global_structure_judgement"))
    cross_episode = _dict(audit.get("cross_episode_analysis"))

    export_lines = [
        f"《{meta.get('script_title') or '未命名剧本'}》爆款文审核报告",
        "",
        "一、整体剧本评价",
        f"总评分：{overall.get('total_score', 0)}/100",
        f"评级：{overall.get('level', '')}",
        f"修改成本：{overall.get('modification_cost', '')}",
        f"核心判断：{overall.get('core_judgement', '')}",
        f"最大硬伤：{overall.get('largest_hard_problem', '')}",
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
        episode_overall = _dict(episode.get("episode_overall"))
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
            "peak_points": _list(ecg.get("peak_points")),
            "valley_points": _list(ecg.get("valley_points")),
        },
        "dimension_cards": _list(audit.get("dimension_scores")),
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
