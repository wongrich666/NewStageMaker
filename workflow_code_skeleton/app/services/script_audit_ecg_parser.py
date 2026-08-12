from __future__ import annotations

import json
import re
from typing import Any

from .workflow_output_parser import parse_workflow_output


SCHEMA_VERSION = "script_audit_compact_v1"

AUDIT_DIMENSIONS = (
    ("opening_hook", "开场吸引力", 15),
    ("conflict_pacing", "冲突与节奏", 25),
    ("satisfying_payoff", "爽点兑现", 25),
    ("character_dialogue_filming", "人物对白与可拍性", 20),
    ("market_compliance", "市场适配与平台合规", 15),
)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _clamp(value: Any, low: float, high: float) -> float:
    return min(high, max(low, _number(value)))


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "是"}:
            return True
        if lowered in {"false", "0", "no", "否"}:
            return False
    return default if value in (None, "") else bool(value)


def _extract_json_fragment(text: str) -> Any:
    cleaned = str(text or "").lstrip("\ufeff").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except (TypeError, ValueError):
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
            return value
        except ValueError:
            continue
    return None


def extract_audit_payload(raw: Any) -> dict[str, Any]:
    """Unwrap Tencent envelopes, end-node fields and stringified model JSON."""
    value: Any = parse_workflow_output(raw)
    wrapper_keys = (
        "audit",
        "script_audit",
        "scriptAudit",
        "content",
        "Content",
        "output",
        "Output",
        "result",
        "data",
        "answer_text",
        "answerText",
        "text",
    )
    seen: set[int] = set()
    for _ in range(10):
        if isinstance(value, dict):
            if (
                value.get("schema_version") == SCHEMA_VERSION
                or {"overall", "dimension_scores", "global_review"}.issubset(value)
            ):
                return value
            identity = id(value)
            if identity in seen:
                break
            seen.add(identity)
            nested = next(
                (
                    value[key]
                    for key in wrapper_keys
                    if key in value and value[key] not in (None, "", [], {})
                ),
                None,
            )
            if nested is None and len(value) == 1:
                nested = next(iter(value.values()))
            if nested is None:
                break
            value = nested
            continue
        if isinstance(value, list):
            if not value:
                break
            value = value[0]
            continue
        if isinstance(value, str):
            parsed = parse_workflow_output(value)
            if parsed == value:
                parsed = _extract_json_fragment(value)
            if parsed in (None, "", [], {}) or parsed == value:
                break
            value = parsed
            continue
        break
    raise ValueError("剧本心电图工作流未返回可解析的 script_audit_compact_v1 JSON。")


def _normalize_dimensions(value: Any, warnings: list[str], *, scope: str) -> list[dict[str, Any]]:
    source_by_key: dict[str, dict[str, Any]] = {}
    loose: list[dict[str, Any]] = []
    for item in _list(value):
        if not isinstance(item, dict):
            continue
        key = _text(item.get("dimension_key") or item.get("key"))
        if key:
            source_by_key[key] = item
        else:
            loose.append(item)

    result: list[dict[str, Any]] = []
    for index, (key, name, max_score) in enumerate(AUDIT_DIMENSIONS):
        item = source_by_key.get(key)
        if item is None and index < len(loose):
            item = loose[index]
            warnings.append(f"{scope}第{index + 1}个维度缺少 dimension_key，已按固定顺序读取。")
        if item is None:
            item = {}
            warnings.append(f"{scope}缺少评分维度“{name}”，已补零。")
        score = round(_clamp(item.get("score"), 0, max_score), 2)
        result.append(
            {
                "dimension_key": key,
                "dimension_name": _text(item.get("dimension_name"), name),
                "max_score": max_score,
                "score": score,
                "summary": _text(item.get("summary")),
                "deduction_reason": _text(
                    item.get("deduction_reason") or item.get("main_deduction")
                ),
                "fix_direction": _text(
                    item.get("fix_direction")
                    or item.get("priority_fix")
                    or item.get("fix_suggestion")
                ),
                "evidence_segment_ids": [
                    _text(segment_id)
                    for segment_id in _list(item.get("evidence_segment_ids"))
                    if _text(segment_id)
                ],
            }
        )
    return result


def _normalize_points(value: Any, *, default_episode: int = 0, prefix: str = "global") -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for index, item in enumerate(_list(value), start=1):
        if not isinstance(item, dict):
            continue
        episode_no = _integer(item.get("episode_no"), default_episode)
        points.append(
            {
                "point_id": _text(item.get("point_id"), f"{prefix}_p_{index:04d}"),
                "segment_id": _text(item.get("segment_id")),
                "episode_no": episode_no,
                "scene_no": _integer(item.get("scene_no")),
                "segment_index_global": _integer(
                    item.get("segment_index_global") or item.get("segment_index"), index
                ),
                "segment_index_in_episode": _integer(
                    item.get("segment_index_in_episode"), index
                ),
                "start_offset": _integer(item.get("start_offset")),
                "end_offset": _integer(item.get("end_offset")),
                "x_label": _text(
                    item.get("x_label") or item.get("label"),
                    f"第{episode_no}集节点{index}" if episode_no else f"节点{index}",
                ),
                "ecg_value": round(_clamp(item.get("ecg_value", item.get("value")), -5, 5), 2),
                "short_label": _text(item.get("short_label") or item.get("label")),
                "audit_reason": _text(item.get("audit_reason") or item.get("reason")),
                "commercial_effect": _text(item.get("commercial_effect")),
                "problem_if_any": _text(item.get("problem_if_any")),
                "fix_suggestion": _text(item.get("fix_suggestion") or item.get("fix")),
                "event_type": _text(item.get("event_type")),
                "event_subtype": _text(item.get("event_subtype")),
                "original_text_excerpt": _text(item.get("original_text_excerpt")),
                "tags": [_text(tag) for tag in _list(item.get("tags")) if _text(tag)],
                "score_impacts": _list(item.get("score_impacts")),
            }
        )
    return sorted(
        points,
        key=lambda point: (
            point["episode_no"],
            point["segment_index_global"],
            point["segment_index_in_episode"],
        ),
    )


def _normalize_segments(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(_list(value), start=1):
        if not isinstance(item, dict):
            continue
        episode_no = _integer(item.get("episode_no"))
        result.append(
            {
                **item,
                "segment_id": _text(item.get("segment_id"), f"seg_{index:04d}"),
                "episode_no": episode_no,
                "scene_no": _integer(item.get("scene_no")),
                "segment_index_global": _integer(item.get("segment_index_global"), index),
                "segment_index_in_episode": _integer(item.get("segment_index_in_episode"), index),
                "start_offset": _integer(item.get("start_offset")),
                "end_offset": _integer(item.get("end_offset")),
                "segment_type": _text(item.get("segment_type")),
                "summary": _text(item.get("summary")),
                "original_text_excerpt": _text(item.get("original_text_excerpt")),
            }
        )
    return result


def _normalize_records(value: Any, *, kind: str, episode_no: int = 0) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(_list(value), start=1):
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        if kind == "issue":
            normalized.setdefault("issue_id", f"issue_{episode_no}_{index}")
            normalized.setdefault("title", f"问题 {index}")
        elif kind == "rewrite":
            normalized.setdefault("task_id", f"rewrite_{episode_no}_{index}")
        elif kind == "risk":
            normalized.setdefault("risk_id", f"risk_{episode_no}_{index}")
        elif kind == "payoff":
            normalized.setdefault("point_id", f"payoff_{episode_no}_{index}")
        result.append(normalized)
    return result


def normalize_script_audit(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(payload, dict):
        raise ValueError("剧本心电图输出必须是 JSON object。")
    warnings: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        warnings.append(
            f"schema_version 应为 {SCHEMA_VERSION}，已按兼容模式读取。"
        )

    meta = _dict(payload.get("meta"))
    detection = _dict(meta.get("episode_detection"))
    dimensions = _normalize_dimensions(payload.get("dimension_scores"), warnings, scope="全剧")
    computed_total = round(sum(item["score"] for item in dimensions), 2)
    overall_source = _dict(payload.get("overall"))
    overall = {
        "total_score": computed_total,
        "level": _text(overall_source.get("level")),
        "modification_cost": _text(overall_source.get("modification_cost")),
        "core_judgement": _text(overall_source.get("core_judgement")),
        "largest_problem": _text(
            overall_source.get("largest_problem")
            or overall_source.get("largest_hard_problem")
        ),
        "best_retained_part": _text(overall_source.get("best_retained_part")),
        "final_judgement": _text(overall_source.get("final_judgement")),
        "priority_fix": _text(overall_source.get("priority_fix")),
    }
    reported_total = _number(overall_source.get("total_score"), computed_total)
    if abs(reported_total - computed_total) > 0.01:
        warnings.append("overall.total_score 与五项维度之和不一致，已使用维度之和。")

    global_source = _dict(payload.get("global_review"))
    global_points = _normalize_points(
        global_source.get("global_ecg_points") or global_source.get("ecg_points"),
        prefix="global",
    )
    global_review = {
        "main_genre": _text(global_source.get("main_genre")),
        "main_emotional_contract": _text(global_source.get("main_emotional_contract")),
        "main_conflict_chain": _text(global_source.get("main_conflict_chain")),
        "protagonist_arc": _text(global_source.get("protagonist_arc")),
        "payoff_chain": _text(global_source.get("payoff_chain")),
        "global_retention_problem": _text(global_source.get("global_retention_problem")),
        "global_revision_priority": _text(global_source.get("global_revision_priority")),
        "global_score_explanation": _text(global_source.get("global_score_explanation")),
        "global_strength_summary": _text(global_source.get("global_strength_summary")),
        "global_weakness_summary": _text(global_source.get("global_weakness_summary")),
        "global_ecg_points": global_points,
        "global_satisfying_points": _normalize_records(
            global_source.get("global_satisfying_points"), kind="payoff"
        ),
        "global_key_issues": _normalize_records(
            global_source.get("global_key_issues"), kind="issue"
        ),
        "global_risk_scan": _normalize_records(
            global_source.get("global_risk_scan"), kind="risk"
        ),
        "global_rewrite_plan": _normalize_records(
            global_source.get("global_rewrite_plan"), kind="rewrite"
        ),
    }

    episode_reviews: list[dict[str, Any]] = []
    for index, episode in enumerate(_list(payload.get("episode_reviews")), start=1):
        if not isinstance(episode, dict):
            continue
        episode_no = _integer(episode.get("episode_no"), index)
        episode_dimensions = _normalize_dimensions(
            episode.get("dimension_scores"), warnings, scope=f"第{episode_no}集"
        )
        episode_reviews.append(
            {
                "episode_no": episode_no,
                "episode_title": _text(episode.get("episode_title"), f"第{episode_no}集"),
                "episode_scope": _text(episode.get("episode_scope")),
                "episode_score": round(sum(item["score"] for item in episode_dimensions), 2),
                "episode_score_explanation": _text(episode.get("episode_score_explanation")),
                "level": _text(episode.get("level")),
                "core_judgement": _text(episode.get("core_judgement")),
                "main_hook": _text(episode.get("main_hook")),
                "main_conflict": _text(episode.get("main_conflict")),
                "main_payoff": _text(episode.get("main_payoff")),
                "largest_retention_loss": _text(episode.get("largest_retention_loss")),
                "best_retained_part": _text(episode.get("best_retained_part")),
                "next_episode_pull": _text(episode.get("next_episode_pull")),
                "priority_fix": _text(episode.get("priority_fix")),
                "episode_structure": _dict(episode.get("episode_structure")),
                "emotional_review": _dict(episode.get("emotional_review")),
                "continuity_review": _dict(episode.get("continuity_review")),
                "dimension_scores": episode_dimensions,
                "ecg_points": _normalize_points(
                    episode.get("ecg_points"),
                    default_episode=episode_no,
                    prefix=f"episode_{episode_no}",
                ),
                "ending_hook": _dict(episode.get("ending_hook")),
                "satisfying_points": _normalize_records(
                    episode.get("satisfying_points"), kind="payoff", episode_no=episode_no
                ),
                "key_issues": _normalize_records(
                    episode.get("key_issues"), kind="issue", episode_no=episode_no
                ),
                "risk_scan": _normalize_records(
                    episode.get("risk_scan"), kind="risk", episode_no=episode_no
                ),
                "rewrite_plan": _normalize_records(
                    episode.get("rewrite_plan"), kind="rewrite", episode_no=episode_no
                ),
            }
        )
    episode_reviews.sort(key=lambda item: item["episode_no"])

    episode_numbers = {episode["episode_no"] for episode in episode_reviews if episode["episode_no"] > 0}
    detected_numbers = {
        _integer(number)
        for number in _list(detection.get("detected_episode_numbers"))
        if _integer(number) > 0
    }
    missing_reviews = sorted(detected_numbers - episode_numbers)
    if missing_reviews:
        formatted = "、".join(f"第{number}集" for number in missing_reviews)
        raise ValueError(f"剧本心电图输出缺少逐集审核：{formatted}。")

    point_ids = {point["point_id"] for point in global_points}
    point_episode_numbers = {point["episode_no"] for point in global_points if point["episode_no"] > 0}
    for episode in episode_reviews:
        if episode["episode_no"] in point_episode_numbers:
            continue
        for point in episode["ecg_points"]:
            if point["point_id"] not in point_ids:
                global_points.append(point)
                point_ids.add(point["point_id"])
    global_points.sort(
        key=lambda point: (
            point["episode_no"],
            point["segment_index_global"],
            point["segment_index_in_episode"],
        )
    )
    global_review["global_ecg_points"] = global_points
    if not global_points:
        raise ValueError("剧本心电图输出缺少 global_ecg_points 和单集 ecg_points。")
    covered_episode_numbers = {point["episode_no"] for point in global_points if point["episode_no"] > 0}
    missing_point_episodes = sorted(episode_numbers - covered_episode_numbers)
    if missing_point_episodes:
        formatted = "、".join(f"第{number}集" for number in missing_point_episodes)
        raise ValueError(f"剧本心电图输出缺少心电节点：{formatted}。")

    audit = {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "script_title": _text(meta.get("script_title") or payload.get("script_title"), "未命名剧本"),
            "text_type": _text(meta.get("text_type")),
            "total_episode_count": len(episode_reviews),
            "total_segment_count": len(_list(payload.get("segments"))),
            "is_partial_review": _bool(meta.get("is_partial_review")),
            "episode_detection": {
                "has_explicit_episode_titles": _bool(detection.get("has_explicit_episode_titles")),
                "detected_episode_numbers": _list(detection.get("detected_episode_numbers")),
                "missing_episode_numbers": _list(detection.get("missing_episode_numbers")),
                "duplicate_episode_numbers": _list(detection.get("duplicate_episode_numbers")),
                "episode_order_is_valid": _bool(detection.get("episode_order_is_valid"), True),
                "detection_evidence": _text(detection.get("detection_evidence")),
            },
        },
        "overall": overall,
        "dimension_scores": dimensions,
        "segments": _normalize_segments(payload.get("segments")),
        "global_review": global_review,
        "episode_reviews": episode_reviews,
        "cross_episode_analysis": _dict(payload.get("cross_episode_analysis")),
    }
    return audit, warnings


def parse_script_audit_workflow_output(raw: Any) -> tuple[dict[str, Any], list[str]]:
    return normalize_script_audit(extract_audit_payload(raw))


def build_script_audit_view_model(audit: dict[str, Any]) -> dict[str, Any]:
    overall = _dict(audit.get("overall"))
    meta = _dict(audit.get("meta"))
    global_review = _dict(audit.get("global_review"))
    points = _list(global_review.get("global_ecg_points"))
    episodes = _list(audit.get("episode_reviews"))
    report_lines = [
        f"《{meta.get('script_title') or '未命名剧本'}》剧本心电图审核报告",
        f"总评分：{_number(overall.get('total_score', 0)):g}/100",
        f"评级：{overall.get('level', '')}",
        f"修改成本：{overall.get('modification_cost', '')}",
        f"核心判断：{overall.get('core_judgement', '')}",
        f"最大问题：{overall.get('largest_problem', '')}",
        f"优先修改：{overall.get('priority_fix', '')}",
        "",
        "心电节点：",
    ]
    for point in points:
        score = _number(point.get("ecg_value"))
        report_lines.append(
            f"- {point.get('x_label') or point.get('point_id')}："
            f"{'+' if score > 0 else ''}{score:g}；"
            f"{point.get('audit_reason') or point.get('commercial_effect') or ''}"
        )
    return {
        "summary_cards": [
            {"label": "总评分", "value": overall.get("total_score", 0), "suffix": "/100"},
            {"label": "评级", "value": overall.get("level", ""), "suffix": ""},
            {"label": "修改成本", "value": overall.get("modification_cost", ""), "suffix": ""},
            {"label": "总集数", "value": meta.get("total_episode_count", 0), "suffix": ""},
            {"label": "心电点位", "value": len(points), "suffix": ""},
        ],
        "ecg_chart": {"title": "全剧总心电图", "points": points},
        "dimension_cards": _list(audit.get("dimension_scores")),
        "episode_cards": episodes,
        "issue_cards": _list(global_review.get("global_key_issues")),
        "rewrite_tasks": _list(global_review.get("global_rewrite_plan")),
        "risk_cards": _list(global_review.get("global_risk_scan")),
        "satisfying_point_cards": _list(global_review.get("global_satisfying_points")),
        "cross_episode_analysis": _dict(audit.get("cross_episode_analysis")),
        "export_text": "\n".join(report_lines).strip(),
    }
