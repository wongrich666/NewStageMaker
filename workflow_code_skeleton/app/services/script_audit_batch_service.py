from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from .runtime_paths import get_runtime_data_dir
from .script_audit_ecg_parser import (
    AUDIT_DIMENSIONS,
    build_script_audit_view_model,
    normalize_script_audit,
)
from .workflow_output_parser import parse_workflow_output
from .workflow_output_parser import safe_truncated_preview
from .tencent_workflow_registry import build_workflow_inputs


BATCH_SCHEMA_VERSION = "script_audit_batch_v1"
# 每次向腾讯工作流发送最多三集。尾批不足三集时按实际集数发送。
# 每批成功后立即落盘，因此后续批次即使暂时失败，也不会丢失此前审核结果。
BATCH_SIZE = 3
BATCH_MAX_ATTEMPTS = 2
MAX_MEMORY_CHARS = 30000
# Only this compact projection is sent back to the remote workflow. The complete
# accepted batch data remains on disk and is used to build the final report.
WORKFLOW_MEMORY_MAX_CHARS = 6000
MAX_DEBUG_EVENTS = 200

_EPISODE_HEADER = re.compile(
    r"(?m)^[ \t]*(?:#{1,6}[ \t]*)?第[ \t]*"
    r"(?P<number>[0-9０-９零〇一二三四五六七八九十百两]+)"
    r"[ \t]*集(?:[ \t]*[：:\-—][ \t]*(?P<title>[^\r\n]*))?[ \t]*$"
)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).astimezone().isoformat()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _chinese_number(value: str) -> int:
    text = str(value or "").strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if text.isdigit():
        return int(text)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if "百" in text:
        left, right = text.split("百", 1)
        hundreds = digits.get(left, 1) if left else 1
        return hundreds * 100 + (_chinese_number(right) if right else 0)
    if "十" in text:
        left, right = text.split("十", 1)
        tens = digits.get(left, 1) if left else 1
        return tens * 10 + digits.get(right, 0)
    if all(char in digits for char in text):
        return int("".join(str(digits[char]) for char in text))
    return 0


def _script_body(text: str) -> str:
    cleaned = str(text or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    marker = re.search(r"(?m)^\s*四[、.]\s*剧本正文\s*$", cleaned)
    return cleaned[marker.end():].lstrip("\n") if marker else cleaned.strip()


def canonical_script_text(text: str) -> str:
    """Normalize transport-only differences while preserving the authored script."""
    normalized = str(text or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()


def script_content_hash(text: str) -> str:
    return hashlib.sha256(canonical_script_text(text).encode("utf-8")).hexdigest()


def parse_script_episodes(text: str) -> list[dict[str, Any]]:
    body = _script_body(text)
    matches = list(_EPISODE_HEADER.finditer(body))
    if not matches:
        raise ValueError("没有识别到“第N集”格式的集标题，无法安全地按集审核。")
    episodes: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        episode_no = _chinese_number(match.group("number"))
        if episode_no <= 0:
            raise ValueError(f"无法识别集号：{match.group(0).strip()}")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        content = body[match.end():end].strip()
        if not content:
            raise ValueError(f"第{episode_no}集正文为空。")
        title = _text(match.group("title"), f"第{episode_no}集")
        episodes.append(
            {
                "episode_no": episode_no,
                "episode_title": title,
                "text": f"第{episode_no}集：{title}\n{content}" if title != f"第{episode_no}集" else f"第{episode_no}集\n{content}",
            }
        )
    numbers = [item["episode_no"] for item in episodes]
    duplicates = sorted({number for number in numbers if numbers.count(number) > 1})
    if duplicates:
        raise ValueError("检测到重复集号：" + "、".join(f"第{number}集" for number in duplicates) + "。")
    expected = list(range(1, max(numbers) + 1))
    if numbers != expected:
        missing = sorted(set(expected) - set(numbers))
        if missing:
            raise ValueError("剧本集号不连续，缺少：" + "、".join(f"第{number}集" for number in missing) + "。")
        raise ValueError("剧本集号顺序不正确，必须从第1集开始按升序排列。")
    return episodes


def split_episode_batches(episodes: list[dict[str, Any]], batch_size: int = BATCH_SIZE) -> list[dict[str, Any]]:
    size = max(1, min(BATCH_SIZE, _int(batch_size, BATCH_SIZE)))
    batches: list[dict[str, Any]] = []
    for index in range(0, len(episodes), size):
        group = episodes[index:index + size]
        batches.append(
            {
                "batch_index": len(batches) + 1,
                "start_episode": group[0]["episode_no"],
                "end_episode": group[-1]["episode_no"],
                "episode_numbers": [item["episode_no"] for item in group],
                "script_text": "\n\n".join(item["text"] for item in group),
            }
        )
    return batches


def pending_episode_batches(
    episodes: list[dict[str, Any]],
    completed_numbers: set[int],
    batch_size: int = BATCH_SIZE,
) -> list[dict[str, Any]]:
    """Regroup only unfinished episodes without replaying an accepted partial prefix.

    This matters when resuming a run created under a different batch-size policy. For
    example, a former single-episode run that completed 1-9 must continue with 10-12,
    rather than replaying a nominal batch that overlaps episodes 6-9.
    """
    pending = [item for item in episodes if _int(item.get("episode_no")) not in completed_numbers]
    if not pending:
        return []
    numbers = [_int(item.get("episode_no")) for item in pending]
    if numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise ValueError("已保存的心电图进度存在非连续缺口，无法安全地自动续跑。")
    return split_episode_batches(pending, batch_size=batch_size)


def _iter_batch_candidates(raw: Any, *, max_depth: int = 18):
    """Yield every plausible nested payload without letting a summary hide siblings."""
    preferred = (
        "audit_batch", "auditBatch", "audit", "Output", "output", "Outputs", "outputs",
        "reply", "content", "Content", "Contents", "Text", "result", "data", "response",
        "Response", "Messages", "Procedures", "Workflow", "RunNodes", "events", "message", "text",
    )
    seen_containers: set[int] = set()

    def visit(value: Any, source: str, depth: int):
        if depth > max_depth:
            return
        parsed = parse_workflow_output(value, max_depth=12)

        # A JSON string can become a new object/list candidate.
        if isinstance(value, str):
            # Keep the original text candidate as well. A lenient generic parser may
            # discard an unfinished JSON prefix, but here that prefix is important
            # evidence that the remote model hit its output ceiling.
            yield source, value
            if parsed != value and isinstance(parsed, (dict, list)):
                yield from visit(parsed, f"{source}.json", depth + 1)
            return
        yield source, parsed
        if not isinstance(value, (dict, list)):
            return
        identity = id(value)
        if identity in seen_containers:
            return
        seen_containers.add(identity)
        if isinstance(value, list):
            for index, item in enumerate(value):
                yield from visit(item, f"{source}[{index}]", depth + 1)
            return
        visited: set[str] = set()
        for key in preferred:
            if key in value:
                visited.add(key)
                yield from visit(value[key], f"{source}.{key}", depth + 1)
        for key, nested in value.items():
            if str(key) not in visited:
                yield from visit(nested, f"{source}.{key}", depth + 1)

    yield from visit(raw, "response", 0)


def _describe_incomplete_batch(
    candidate: dict[str, Any],
    source: str,
    *,
    expected_total_episodes: int | None = None,
) -> str:
    actual_keys = sorted(str(key) for key in candidate)
    required = ("schema_version", "batch_meta", "episode_reviews", "next_audit_memory")
    missing = [key for key in required if key not in candidate]
    details = [
        f"远端候选位置 {source}",
        f"实际字段：{', '.join(actual_keys) or '(空)'}",
        f"缺少字段：{', '.join(missing) or '(无)'}",
    ]
    if "reviewed_episode_numbers" in candidate and "episode_reviews" not in candidate:
        details.append("当前返回只是批次摘要，不含逐集评分 episode_reviews")
    returned_total = _int(candidate.get("total_episodes"))
    if expected_total_episodes and returned_total and returned_total != expected_total_episodes:
        details.append(
            f"total_episodes 值错误：本地传入 {expected_total_episodes}，远端返回 {returned_total}"
        )
    return "；".join(details)


def _extract_batch_payload(raw: Any, *, expected_total_episodes: int | None = None) -> dict[str, Any]:
    incomplete: list[tuple[int, str]] = []
    truncated: list[tuple[int, str]] = []
    for source, value in _iter_batch_candidates(raw):
        if isinstance(value, str) and BATCH_SCHEMA_VERSION in value and '"episode_reviews"' in value:
            try:
                json.loads(value)
            except json.JSONDecodeError as exc:
                truncated.append((
                    len(value),
                    f"远端候选位置 {source} 的 audit_batch 文本在第{exc.lineno}行第{exc.colno}列"
                    f"中断（已收到{len(value)}字符）",
                ))
        if not isinstance(value, dict):
            continue
        if value.get("schema_version") == BATCH_SCHEMA_VERSION or {
            "batch_meta", "episode_reviews", "next_audit_memory",
        }.issubset(value):
            return value
        business_keys = {
            "batch_start_episode", "batch_end_episode", "total_episodes",
            "reviewed_episode_numbers", "batch_core_judgement",
        }
        overlap = len(business_keys.intersection(value))
        if overlap:
            incomplete.append((overlap, _describe_incomplete_batch(
                value,
                source,
                expected_total_episodes=expected_total_episodes,
            )))
    if truncated:
        detail = max(truncated, key=lambda item: item[0])[1]
        raise ValueError(
            "心电图大模型已开始返回完整 script_audit_batch_v1，但 JSON 在输出中途被截断。"
            f"{detail}；这不是前端解析丢失，也不是结束节点字段名错误。"
        )
    if incomplete:
        detail = max(incomplete, key=lambda item: item[0])[1]
        raise ValueError(
            "心电图远端结束节点返回了不完整批次摘要，不能生成逐集心电图。"
            f"{detail}。请将结束节点改为 Output.audit_batch = 大模型1.Output.Content，"
            "并确认大模型最终回复含完整 script_audit_batch_v1 JSON。"
        )
    raise ValueError(
        "心电图工作流未返回可解析的 script_audit_batch_v1 JSON。"
        "请确认结束节点字段为 audit_batch，且引用大模型1.Output.Content。"
    )


def validate_batch_output(
    raw: Any,
    expected_numbers: list[int],
    expected_total_episodes: int | None = None,
) -> tuple[dict[str, Any], list[str]]:
    payload = _extract_batch_payload(raw, expected_total_episodes=expected_total_episodes)
    warnings: list[str] = []
    if payload.get("schema_version") != BATCH_SCHEMA_VERSION:
        raise ValueError(f"批次 schema_version 必须是 {BATCH_SCHEMA_VERSION}。")
    reviews = payload.get("episode_reviews") if isinstance(payload.get("episode_reviews"), list) else []
    actual_numbers = [_int(item.get("episode_no")) for item in reviews if isinstance(item, dict)]
    if actual_numbers != expected_numbers:
        raise ValueError(f"批次逐集结果不完整：期望 {expected_numbers}，实际 {actual_numbers}。")
    required_dimensions = [item[0] for item in AUDIT_DIMENSIONS]
    dimension_max_scores = {item[0]: item[2] for item in AUDIT_DIMENSIONS}
    for review in reviews:
        episode_no = _int(review.get("episode_no"))
        dimensions = review.get("dimension_scores") if isinstance(review.get("dimension_scores"), list) else []
        actual_dimension_keys = [
            _text(item.get("dimension_key") or item.get("key"))
            for item in dimensions
            if isinstance(item, dict)
        ]
        if actual_dimension_keys != required_dimensions:
            raise ValueError(f"第{episode_no}集五维评分不完整或顺序错误：{actual_dimension_keys}。")
        score_sum = 0.0
        for dimension in dimensions:
            key = _text(dimension.get("dimension_key"))
            maximum = dimension_max_scores[key]
            try:
                score = float(dimension.get("score"))
                reported_maximum = float(dimension.get("max_score"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"第{episode_no}集 {key} 的分数不是数字。") from exc
            if reported_maximum != maximum or not 0 <= score <= maximum:
                raise ValueError(f"第{episode_no}集 {key} 的 score/max_score 超出约定范围。")
            score_sum += score
        try:
            episode_score = float(review.get("episode_score"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"第{episode_no}集 episode_score 不是数字。") from exc
        if abs(episode_score - score_sum) > 0.01:
            raise ValueError(f"第{episode_no}集 episode_score={episode_score:g}，但五维合计为 {score_sum:g}。")
        if not isinstance(review.get("emotional_review"), dict) or not review["emotional_review"]:
            raise ValueError(f"第{episode_no}集缺少 emotional_review 情绪审核。")
        if not isinstance(review.get("continuity_review"), dict) or not review["continuity_review"]:
            raise ValueError(f"第{episode_no}集缺少 continuity_review 承接审核。")
        continuity = review["continuity_review"]
        expected_previous_episode = episode_no - 1 if episode_no > 1 else 0
        reported_previous = continuity.get("previous_episode_no")
        reported_current = continuity.get("current_episode_no")
        if reported_previous is None or reported_current is None:
            continuity["previous_episode_no"] = expected_previous_episode
            continuity["current_episode_no"] = episode_no
            warnings.append(
                f"远端第{episode_no}集 continuity_review 漏填相邻集编号，"
                "本地已按剧本连续集号补齐。"
            )
        elif _int(reported_previous, -1) != expected_previous_episode or _int(reported_current, -1) != episode_no:
            raise ValueError(
                f"第{episode_no}集 continuity_review 集号不正确："
                f"期望 {expected_previous_episode}->{episode_no}。"
            )
        if episode_no > 1:
            continuity_evidence = continuity.get("continuity_evidence")
            if not isinstance(continuity_evidence, dict) or not continuity_evidence:
                warnings.append(
                    f"远端第{episode_no}集 continuity_review 缺少逐项 continuity_evidence；"
                    "现有承接布尔判断和断点仍会保存，建议继续按最新提示词补齐证据。"
                )
        points = review.get("ecg_points") if isinstance(review.get("ecg_points"), list) else []
        if not points:
            raise ValueError(f"第{episode_no}集没有返回心电节点。")
        for point in points:
            if isinstance(point, dict):
                point["episode_no"] = episode_no
                value = _int(point.get("ecg_value"), 99)
                if value < -5 or value > 5:
                    raise ValueError(f"第{episode_no}集存在超出 -5 到 5 的 ecg_value。")
    meta = payload.get("batch_meta") if isinstance(payload.get("batch_meta"), dict) else {}
    reported = [_int(item) for item in meta.get("reviewed_episode_numbers", [])]
    if reported != expected_numbers:
        raise ValueError(f"batch_meta 集号不匹配：期望 {expected_numbers}，实际 {reported}。")
    if _int(meta.get("batch_start_episode")) != expected_numbers[0] or _int(meta.get("batch_end_episode")) != expected_numbers[-1]:
        raise ValueError("batch_meta 的起止集数与当前批次不一致。")
    if expected_total_episodes and _int(meta.get("total_episodes")) != expected_total_episodes:
        reported_total = _int(meta.get("total_episodes"))
        # total_episodes is deterministic local metadata derived from the strictly
        # parsed script. Some Tencent flows mistakenly echo the current batch size;
        # correcting that value is safe and does not alter any model judgement.
        meta["total_episodes"] = int(expected_total_episodes)
        warnings.append(
            f"远端将 batch_meta.total_episodes 返回为 {reported_total}，"
            f"本地已按完整剧本自动校正为 {expected_total_episodes}。"
        )
    if expected_total_episodes:
        meta["is_final_batch"] = expected_numbers[-1] == expected_total_episodes
    boundary = payload.get("boundary_review") if isinstance(payload.get("boundary_review"), dict) else {}
    expected_previous = expected_numbers[0] - 1 if expected_numbers[0] > 1 else 0
    if not boundary or _int(boundary.get("previous_episode_no"), -1) != expected_previous:
        raise ValueError("boundary_review 缺失或 previous_episode_no 不正确。")
    if _int(boundary.get("current_episode_no"), -1) != expected_numbers[0]:
        raise ValueError("boundary_review.current_episode_no 与本批首集不一致。")
    memory = payload.get("next_audit_memory")
    if not isinstance(memory, dict) or not memory:
        raise ValueError("批次缺少 next_audit_memory，无法继续下一批审核。")
    if _int(memory.get("reviewed_through_episode")) < expected_numbers[-1]:
        raise ValueError("next_audit_memory.reviewed_through_episode 未覆盖当前批次。")
    handoff = memory.get("last_episode_handoff")
    if not isinstance(handoff, dict) or _int(handoff.get("episode_no")) != expected_numbers[-1]:
        # Backward compatibility for the already-published workflow. This snapshot
        # is deterministic extraction from the accepted current-episode review; it
        # keeps the next episode connected until the remote prompt is upgraded to
        # return the richer handoff fields itself.
        last_review = reviews[-1]
        emotional = last_review.get("emotional_review") if isinstance(last_review.get("emotional_review"), dict) else {}
        structure = last_review.get("episode_structure") if isinstance(last_review.get("episode_structure"), dict) else {}
        ending_hook = last_review.get("ending_hook") if isinstance(last_review.get("ending_hook"), dict) else {}
        memory["last_episode_handoff"] = {
            "episode_no": expected_numbers[-1],
            "ending_scene_summary": _text(structure.get("ending")),
            "ending_time_space": "",
            "ending_emotion": _text(emotional.get("ending_emotion")),
            "active_action_or_crisis": _text(last_review.get("main_conflict")),
            "ending_hook_promise": _text(ending_hook.get("description") or last_review.get("next_episode_pull")),
            "ending_text_excerpt": _text(ending_hook.get("original_text_excerpt")),
            "character_state_snapshot": copy.deepcopy(memory.get("current_character_states") or []),
            "information_state": [],
            "prop_resource_state": [],
            "relationship_state": [],
            "unresolved_actions": [
                value for value in (_text(last_review.get("next_episode_pull")),) if value
            ],
            "continuity_watch_points": copy.deepcopy(memory.get("next_batch_watch_points") or []),
        }
        warnings.append(
            f"远端第{expected_numbers[-1]}集记忆缺少 last_episode_handoff，"
            "本地已从本集审核结果生成兼容交接快照；建议按最新提示词更新远端工作流。"
        )
    if expected_numbers[0] > 1:
        evidence = boundary.get("continuity_evidence")
        if not isinstance(evidence, dict) or not evidence:
            warnings.append(
                f"第{expected_numbers[0]}集 boundary_review 缺少 continuity_evidence，"
                "当前承接分数可用，但建议按最新提示词补充逐项对照证据。"
            )
    return payload, warnings


def compact_audit_memory(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    allowed = (
        "reviewed_through_episode", "main_genre", "main_emotional_contract", "main_conflict_chain",
        "protagonist_arc", "payoff_chain", "last_episode_handoff", "current_character_states", "unresolved_plot_threads",
        "unpaid_emotional_debts", "resolved_payoffs", "continuity_risks", "episode_score_index",
        "weak_episode_numbers", "best_episode_no", "best_episode_reason", "weakest_episode_no",
        "weakest_episode_reason", "running_retention_judgement", "global_strength_summary",
        "global_weakness_summary", "largest_problem", "best_retained_part", "priority_fix",
        "final_judgement", "modification_cost", "next_batch_watch_points", "cross_batch_findings",
        "global_key_issues", "global_rewrite_plan", "global_risk_scan", "global_satisfying_points",
        "retention_curve_summary", "payoff_distribution_problem", "hook_continuity_problem",
        "character_arc_problem", "score_gap_analysis", "global_dropoff_pattern", "fix_suggestion",
    )

    def shrink(item: Any, depth: int = 0) -> Any:
        if depth > 4:
            return _text(item)[:300]
        if isinstance(item, str):
            return item[:1200]
        if isinstance(item, list):
            return [shrink(child, depth + 1) for child in item[:200]]
        if isinstance(item, dict):
            return {str(key): shrink(child, depth + 1) for key, child in list(item.items())[:40]}
        return item

    result = {key: shrink(source[key]) for key in allowed if key in source}
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > MAX_MEMORY_CHARS:
        for key in ("resolved_payoffs", "cross_batch_findings", "global_satisfying_points", "global_risk_scan", "global_key_issues"):
            if isinstance(result.get(key), list):
                result[key] = result[key][-20:]
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > MAX_MEMORY_CHARS:
        raise ValueError("累计审核记忆超过 30000 字符，请精简远端 next_audit_memory。")
    return result


def compact_workflow_audit_memory(value: Any, *, retry_instruction: str = "") -> dict[str, Any]:
    """Build a bounded continuity memory for the next remote audit call.

    The remote model needs the latest handoff and unresolved state, not every
    verbose issue object accumulated across the whole series. Full accepted
    batches stay persisted locally, so trimming this transport projection does
    not remove scores, evidence, issues, or rewrite tasks from the final report.
    """
    source = compact_audit_memory(value)
    if not source and not retry_instruction:
        return {}

    list_limits = {
        "current_character_states": 20,
        "unresolved_plot_threads": 16,
        "unpaid_emotional_debts": 12,
        "resolved_payoffs": 12,
        "continuity_risks": 10,
        "episode_score_index": 60,
        "weak_episode_numbers": 30,
        "next_batch_watch_points": 10,
        "cross_batch_findings": 6,
        "global_key_issues": 4,
        "global_rewrite_plan": 4,
        "global_risk_scan": 4,
        "global_satisfying_points": 4,
    }

    def shrink(item: Any, depth: int = 0, *, list_limit: int = 12, text_limit: int = 360) -> Any:
        if depth > 4:
            return _text(item)[:160]
        if isinstance(item, str):
            return item[:text_limit if depth < 2 else min(text_limit, 240)]
        if isinstance(item, list):
            selected = item[-list_limit:]
            return [shrink(child, depth + 1, list_limit=8, text_limit=text_limit) for child in selected]
        if isinstance(item, dict):
            return {
                str(key): shrink(child, depth + 1, list_limit=8, text_limit=text_limit)
                for key, child in list(item.items())[:24]
            }
        return item

    result: dict[str, Any] = {}
    for key, item in source.items():
        if isinstance(item, list):
            result[key] = shrink(item, list_limit=list_limits.get(key, 12))
        elif key == "last_episode_handoff":
            result[key] = shrink(item, list_limit=12, text_limit=300)
        else:
            result[key] = shrink(item)
    if retry_instruction:
        result["_format_retry_instruction"] = _text(retry_instruction)[:360]

    def encoded_length() -> int:
        return len(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

    # These verbose cumulative collections are already reconstructible from the
    # accepted per-batch payloads. Drop them first when the transport budget is
    # exceeded, while retaining current continuity and unresolved-story state.
    optional_drop_order = (
        "global_satisfying_points",
        "global_risk_scan",
        "resolved_payoffs",
        "cross_batch_findings",
        "global_rewrite_plan",
        "global_key_issues",
        "episode_score_index",
    )
    for key in optional_drop_order:
        if encoded_length() <= WORKFLOW_MEMORY_MAX_CHARS:
            break
        result.pop(key, None)

    if encoded_length() > WORKFLOW_MEMORY_MAX_CHARS:
        result = {
            key: shrink(item, list_limit=6, text_limit=180)
            for key, item in result.items()
        }

    if encoded_length() > WORKFLOW_MEMORY_MAX_CHARS:
        essential_keys = (
            "reviewed_through_episode", "last_episode_handoff", "main_genre",
            "main_emotional_contract", "main_conflict_chain", "protagonist_arc",
            "payoff_chain", "current_character_states", "unresolved_plot_threads",
            "unpaid_emotional_debts", "continuity_risks", "next_batch_watch_points",
            "weak_episode_numbers", "best_episode_no", "best_episode_reason",
            "weakest_episode_no", "weakest_episode_reason", "running_retention_judgement",
            "largest_problem", "priority_fix", "_format_retry_instruction",
        )
        result = {
            key: shrink(result[key], list_limit=5, text_limit=140)
            for key in essential_keys
            if key in result
        }

    if encoded_length() > WORKFLOW_MEMORY_MAX_CHARS:
        raise ValueError("工作流审核记忆压缩后仍超过 6000 字符。")
    return result


def _records(batches: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for batch in batches:
        for item in batch.get(key, []) if isinstance(batch.get(key), list) else []:
            if not isinstance(item, dict):
                continue
            signature = _text(item.get("issue_id") or item.get("task_id") or item.get("risk_id") or item.get("point_id"))
            signature = signature or hashlib.sha1(json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            if signature not in seen:
                result.append(copy.deepcopy(item))
                seen.add(signature)
    return result


def _safe_client_debug(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    allowed = (
        "status", "workflow_key", "workflow_id", "api_key_env", "api_key_present", "api_url",
        "api_url_source", "input_keys", "input_char_lengths", "input_types", "request_id",
        "http_status", "http_attempt", "http_attempts", "elapsed_seconds", "exception_type",
        "candidate_sources", "output_keys", "response_preview", "last_failure_reason",
    )
    result = {key: copy.deepcopy(source.get(key)) for key in allowed if key in source}
    for key in ("response_preview", "last_failure_reason"):
        if key in result:
            result[key] = safe_truncated_preview(result[key], limit=5000)
    return result


def merge_audit_batches(script_title: str, total_episodes: int, batches: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    reviews = [copy.deepcopy(review) for batch in batches for review in batch.get("episode_reviews", []) if isinstance(review, dict)]
    reviews.sort(key=lambda item: _int(item.get("episode_no")))
    numbers = [_int(item.get("episode_no")) for item in reviews]
    expected = list(range(1, total_episodes + 1))
    if numbers != expected:
        raise ValueError(f"无法合并心电图：期望逐集结果 {expected}，实际 {numbers}。")
    dimensions: list[dict[str, Any]] = []
    for key, name, maximum in AUDIT_DIMENSIONS:
        items = [
            item
            for review in reviews
            for item in review.get("dimension_scores", [])
            if isinstance(item, dict) and _text(item.get("dimension_key")) == key
        ]
        score = round(sum(float(item.get("score") or 0) for item in items) / max(1, len(items)), 2)
        dimensions.append({
            "dimension_key": key, "dimension_name": name, "max_score": maximum,
            "score": min(maximum, max(0, score)),
            "summary": _text((items[-1] if items else {}).get("summary")),
            "deduction_reason": _text((items[-1] if items else {}).get("deduction_reason")),
            "fix_direction": _text((items[-1] if items else {}).get("fix_direction")),
            "evidence_segment_ids": [],
        })
    memory = compact_audit_memory(batches[-1].get("next_audit_memory") if batches else {})
    points = [copy.deepcopy(point) for review in reviews for point in review.get("ecg_points", []) if isinstance(point, dict)]
    points.sort(key=lambda item: (_int(item.get("episode_no")), _int(item.get("segment_index_in_episode"), 9999)))
    for index, point in enumerate(points, start=1):
        point["segment_index_global"] = index
    total_score = round(sum(item["score"] for item in dimensions), 2)
    level = "S" if total_score >= 90 else "A" if total_score >= 80 else "B" if total_score >= 70 else "C" if total_score >= 60 else "D"
    def memory_records(memory_key: str, batch_key: str) -> list[dict[str, Any]]:
        # Transport memory is intentionally bounded, so the final report combines
        # its curated global records with every accepted per-batch record.
        remembered = memory.get(memory_key)
        candidates = [
            *([item for item in remembered if isinstance(item, dict)] if isinstance(remembered, list) else []),
            *_records(batches, batch_key),
        ]
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in candidates:
            signature = _text(item.get("issue_id") or item.get("task_id") or item.get("risk_id") or item.get("point_id"))
            signature = signature or hashlib.sha1(
                json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            if signature not in seen:
                result.append(copy.deepcopy(item))
                seen.add(signature)
        return result

    global_issues = memory_records("global_key_issues", "batch_key_issues")
    global_rewrites = memory_records("global_rewrite_plan", "batch_rewrite_plan")
    global_risks = memory_records("global_risk_scan", "batch_risk_scan")
    global_payoffs = memory_records("global_satisfying_points", "batch_satisfying_points")
    payload = {
        "schema_version": "script_audit_compact_v1",
        "meta": {
            "script_title": script_title or "未命名剧本", "text_type": "短剧剧本",
            "total_episode_count": total_episodes, "total_segment_count": len(points), "is_partial_review": False,
            "episode_detection": {
                "has_explicit_episode_titles": True, "detected_episode_numbers": expected,
                "missing_episode_numbers": [], "duplicate_episode_numbers": [], "episode_order_is_valid": True,
                "detection_evidence": "本地按第N集标题切分并逐批严格校验。",
            },
        },
        "overall": {
            "total_score": total_score, "level": level,
            "modification_cost": _text(memory.get("modification_cost"), "中"),
            "core_judgement": _text(memory.get("running_retention_judgement")),
            "largest_problem": _text(memory.get("largest_problem") or memory.get("global_weakness_summary")),
            "best_retained_part": _text(memory.get("best_retained_part") or memory.get("global_strength_summary")),
            "final_judgement": _text(memory.get("final_judgement")),
            "priority_fix": _text(memory.get("priority_fix") or memory.get("fix_suggestion")),
        },
        "dimension_scores": dimensions,
        "segments": [copy.deepcopy(item) for batch in batches for item in batch.get("segments", []) if isinstance(item, dict)],
        "global_review": {
            "main_genre": _text(memory.get("main_genre")),
            "main_emotional_contract": _text(memory.get("main_emotional_contract")),
            "main_conflict_chain": _text(memory.get("main_conflict_chain")),
            "protagonist_arc": _text(memory.get("protagonist_arc")),
            "payoff_chain": _text(memory.get("payoff_chain")),
            "global_retention_problem": _text(memory.get("largest_problem") or memory.get("global_weakness_summary")),
            "global_revision_priority": _text(memory.get("priority_fix")),
            "global_score_explanation": "全剧五维分数为所有逐集同维度分数的算术平均，总分为五维之和。",
            "global_strength_summary": _text(memory.get("global_strength_summary")),
            "global_weakness_summary": _text(memory.get("global_weakness_summary")),
            "global_ecg_points": points,
            "global_satisfying_points": global_payoffs,
            "global_key_issues": global_issues,
            "global_risk_scan": global_risks,
            "global_rewrite_plan": global_rewrites,
        },
        "episode_reviews": reviews,
        "cross_episode_analysis": {
            "retention_curve_summary": _text(memory.get("retention_curve_summary") or memory.get("running_retention_judgement")),
            "weak_episode_numbers": memory.get("weak_episode_numbers") if isinstance(memory.get("weak_episode_numbers"), list) else [],
            "payoff_distribution_problem": _text(memory.get("payoff_distribution_problem")),
            "hook_continuity_problem": _text(memory.get("hook_continuity_problem")),
            "character_arc_problem": _text(memory.get("character_arc_problem")),
            "fix_suggestion": _text(memory.get("fix_suggestion") or memory.get("priority_fix")),
            "episode_score_trend": [
                {"episode_no": _int(review.get("episode_no")), "score": review.get("episode_score")}
                for review in reviews
            ],
            "best_episode_no": _int(memory.get("best_episode_no")),
            "best_episode_reason": _text(memory.get("best_episode_reason")),
            "weakest_episode_no": _int(memory.get("weakest_episode_no")),
            "weakest_episode_reason": _text(memory.get("weakest_episode_reason")),
            "score_gap_analysis": _text(memory.get("score_gap_analysis")),
            "global_dropoff_pattern": _text(memory.get("global_dropoff_pattern")),
            "batch_boundaries": [copy.deepcopy(batch.get("boundary_review") or {}) for batch in batches],
        },
    }
    return normalize_script_audit(payload)


class ScriptAuditBatchService:
    def __init__(self, base_dir: Path | None = None, client: Any = None) -> None:
        self.base_dir = Path(base_dir or (get_runtime_data_dir() / "script_audits")).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.client = client
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}

    def _path(self, run_id: str) -> Path:
        safe = re.sub(r"[^a-f0-9]", "", str(run_id or "").lower())
        if len(safe) != 32:
            raise ValueError("心电图运行 ID 格式不正确。")
        return self.base_dir / f"{safe}.json"

    def _debug_path(self, run_id: str) -> Path:
        return self._path(run_id).with_suffix(".debug.json")

    def _summary_path(self, run_id: str) -> Path:
        return self._path(run_id).with_suffix(".summary.json")

    def _append_debug_event(self, run_id: str, event: str, **details: Any) -> None:
        with self._lock:
            path = self._debug_path(run_id)
            document: dict[str, Any] = {"run_id": run_id, "events": []}
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        document = loaded
                except Exception:
                    document = {"run_id": run_id, "events": []}
            events = document.get("events") if isinstance(document.get("events"), list) else []
            safe_details = json.loads(json.dumps(details, ensure_ascii=False, default=str))
            next_index = _int(document.get("next_index"), 0)
            if next_index <= 0:
                next_index = max((_int(item.get("index")) for item in events if isinstance(item, dict)), default=0) + 1
            events.append(
                {
                    "index": next_index,
                    "timestamp": _now_iso(),
                    "event": _text(event, "debug_event"),
                    "details": safe_details,
                }
            )
            document["events"] = events[-MAX_DEBUG_EVENTS:]
            document["next_index"] = next_index + 1
            temp = path.with_suffix(".debug.tmp")
            temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, path)
            try:
                record = self._read(run_id)
                record.update(
                    debug_file=str(path),
                    debug_event_count=len(document["events"]),
                    debug_last_event=_text(event),
                )
                self._write(record)
            except Exception:
                pass

    def _read(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id)
        if not path.exists():
            raise ValueError("心电图运行记录不存在。")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, record: dict[str, Any]) -> None:
        path = self._path(record["run_id"])
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(record, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temp, path)
        summary = self.public_record(record, include_source=False)
        summary["user_id"] = _int(record.get("user_id"))
        summary_path = self._summary_path(record["run_id"])
        summary_temp = summary_path.with_suffix(".summary.tmp")
        summary_temp.write_text(json.dumps(summary, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(summary_temp, summary_path)

    def _all_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in self.base_dir.glob("*.json"):
            if path.name.endswith((".debug.json", ".summary.json")):
                continue
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(loaded, dict) and _text(loaded.get("run_id")):
                records.append(loaded)
        return records

    def _all_summaries(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for path in self.base_dir.glob("*.summary.json"):
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(loaded, dict) and _text(loaded.get("run_id")):
                summaries.append(loaded)
        # Existing installations have full run records but no sidecar index yet.
        if not summaries:
            for record in self._all_records():
                summary = self.public_record(record, include_source=False)
                summary["user_id"] = _int(record.get("user_id"))
                summaries.append(summary)
                try:
                    self._summary_path(_text(record.get("run_id"))).write_text(
                        json.dumps(summary, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
                    )
                except Exception:
                    pass
        return summaries

    def _find_user_script(self, user_id: int, content_hash: str) -> dict[str, Any] | None:
        matches = []
        for record in self._all_records():
            if _int(record.get("user_id")) != int(user_id):
                continue
            stored_hash = _text(record.get("script_hash"))
            recalculated_hash = (
                script_content_hash(_text(record.get("script_text")))
                if record.get("script_text") else ""
            )
            if content_hash in {stored_hash, recalculated_hash}:
                matches.append(record)
        if not matches:
            return None
        matches.sort(key=lambda item: _text(item.get("updated_at") or item.get("created_at")), reverse=True)
        return matches[0]

    def start_run(self, *, user_id: int, script_title: str, script_text: str, launch: bool = True) -> dict[str, Any]:
        script_text = canonical_script_text(script_text)
        script_title = _text(script_title)[:120]
        episodes = parse_script_episodes(script_text)
        content_hash = script_content_hash(script_text)
        with self._lock:
            existing = self._find_user_script(user_id, content_hash)
            if existing is not None:
                status = _text(existing.get("status"))
                # 同一正文可以复用评分，但展示名称必须跟随本次上传的文件。
                # 同步 audit.meta，避免资产卡和报告标题显示成两个不同剧本。
                if script_title and script_title != _text(existing.get("script_title")):
                    existing["script_title"] = script_title
                    audit = existing.get("audit")
                    if isinstance(audit, dict):
                        meta = audit.get("meta") if isinstance(audit.get("meta"), dict) else {}
                        meta["script_title"] = script_title
                        audit["meta"] = meta
                    existing["updated_at"] = _now_iso()
                if status == "failed" and launch:
                    existing.update(status="pending", error="", updated_at=_now_iso())
                self._write(existing)
                existing_public = self.public_record(existing)
                existing_public["asset_reused"] = True
                existing_public["reuse_reason"] = (
                    "completed_result" if status == "succeeded"
                    else "resumed_failed_run" if status == "failed"
                    else "active_run"
                )
                run_id = _text(existing.get("run_id"))
                if launch and status != "succeeded":
                    self._launch(run_id)
                return existing_public
        run_id = uuid.uuid4().hex
        now = _now_iso()
        record = {
            "run_id": run_id, "user_id": int(user_id), "script_title": script_title or "未命名剧本",
            "script_text": script_text, "script_hash": content_hash,
            "status": "pending", "created_at": now, "updated_at": now, "total_episodes": len(episodes),
            "total_batches": len(split_episode_batches(episodes)), "completed_batches": 0,
            "completed_episode_numbers": [], "current_batch_start": 0, "current_batch_end": 0,
            "batches": [], "audit_memory": {}, "warnings": [], "error": "", "audit": None,
        }
        with self._lock:
            self._write(record)
        self._append_debug_event(
            run_id,
            "run_created",
            user_id=int(user_id),
            script_title=record["script_title"],
            script_hash=record["script_hash"],
            script_char_length=len(script_text),
            total_episodes=record["total_episodes"],
            total_batches=record["total_batches"],
        )
        if launch:
            self._launch(run_id)
        with self._lock:
            current = self._read(run_id)
        return self.public_record(current)

    def list_assets(self, *, user_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            records = [
                record for record in self._all_summaries()
                if _int(record.get("user_id")) == int(user_id)
            ]
        records.sort(key=lambda item: _text(item.get("updated_at") or item.get("created_at")), reverse=True)
        assets: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()
        for record in records:
            content_hash = _text(record.get("script_hash")) or script_content_hash(_text(record.get("script_text")))
            if content_hash and content_hash in seen_hashes:
                continue
            if content_hash:
                seen_hashes.add(content_hash)
            asset = copy.deepcopy(record)
            asset.pop("user_id", None)
            assets.append(asset)
            if len(assets) >= max(1, min(200, int(limit))):
                break
        return assets

    def _launch(self, run_id: str) -> None:
        with self._lock:
            active = self._threads.get(run_id)
            if active and active.is_alive():
                return
            thread = threading.Thread(target=self._run, args=(run_id,), daemon=True, name=f"script-audit-{run_id[:8]}")
            self._threads[run_id] = thread
            thread.start()

    def _workflow_client(self):
        if self.client is not None:
            return self.client
        from .tencent_workflow_client import tencent_workflow_client

        return tencent_workflow_client

    def _run(self, run_id: str) -> None:
        try:
            with self._lock:
                record = self._read(run_id)
                record.update(status="running", error="", updated_at=_now_iso())
                self._write(record)
            episodes = parse_script_episodes(record["script_text"])
            stored_batches = record.get("batches") if isinstance(record.get("batches"), list) else []
            completed_numbers = {
                _int(item.get("episode_no"))
                for batch in stored_batches
                if isinstance(batch, dict)
                for item in (batch.get("episode_reviews") or [])
                if isinstance(item, dict)
            }
            # Resume by completed episode numbers, then regroup only the unfinished
            # suffix. This is safe for records created by the former single- or
            # five-episode policies and the current three-episode policy.
            pending_chunks = pending_episode_batches(episodes, completed_numbers)
            completed = len(stored_batches)
            memory = compact_audit_memory(record.get("audit_memory"))
            with self._lock:
                record = self._read(run_id)
                record.update(
                    total_batches=completed + len(pending_chunks),
                    completed_batches=completed,
                    completed_episode_numbers=sorted(completed_numbers),
                    updated_at=_now_iso(),
                )
                self._write(record)
            self._append_debug_event(
                run_id,
                "run_started",
                resumed_from_batch=completed + 1,
                completed_batches=completed,
                resumed_from_episode=(pending_chunks[0]["start_episode"] if pending_chunks else 0),
                batch_size=BATCH_SIZE,
            )
            work_queue = list(pending_chunks)
            episode_by_number = {_int(item.get("episode_no")): item for item in episodes}
            while work_queue:
                chunk = work_queue.pop(0)
                with self._lock:
                    record = self._read(run_id)
                    record.update(
                        status="running", current_batch_start=chunk["start_episode"],
                        current_batch_end=chunk["end_episode"], updated_at=_now_iso(),
                    )
                    self._write(record)
                stored_memory_text = json.dumps(memory, ensure_ascii=False, separators=(",", ":")) if memory else "{}"
                workflow_memory = compact_workflow_audit_memory(memory)
                workflow_memory_text = (
                    json.dumps(workflow_memory, ensure_ascii=False, separators=(",", ":"))
                    if workflow_memory else "{}"
                )
                variables = {
                    "script_title": record["script_title"],
                    "total_episodes": record["total_episodes"],
                    "batch_start_episode": chunk["start_episode"],
                    "batch_end_episode": chunk["end_episode"],
                    "previous_audit_memory": workflow_memory_text,
                    "batch_script_text": chunk["script_text"],
                    "is_final_batch": chunk["end_episode"] == record["total_episodes"],
                }
                last_error: Exception | None = None
                batch_payload: dict[str, Any] | None = None
                batch_warnings: list[str] = []
                for attempt in range(BATCH_MAX_ATTEMPTS):
                    attempt_variables = dict(variables)
                    if attempt:
                        retry_instruction = (
                            f"这是当前第{chunk['start_episode']}-{chunk['end_episode']}集的第{attempt + 1}次格式重试。"
                            "上一次只返回摘要或结构不完整。本次必须返回完整 script_audit_batch_v1 JSON，"
                            "不得只返回 batch_meta、reviewed_episode_numbers 或 batch_core_judgement；"
                            "episode_reviews 必须逐集齐全，且必须包含 next_audit_memory。"
                        )
                        retry_memory = compact_workflow_audit_memory(
                            memory,
                            retry_instruction=retry_instruction,
                        )
                        attempt_variables["previous_audit_memory"] = json.dumps(
                            retry_memory, ensure_ascii=False, separators=(",", ":")
                        )
                    transported = build_workflow_inputs("hot_review", attempt_variables)
                    self._append_debug_event(
                        run_id,
                        "workflow_attempt_started",
                        batch_index=chunk["batch_index"],
                        batch_start_episode=chunk["start_episode"],
                        batch_end_episode=chunk["end_episode"],
                        attempt=attempt + 1,
                        max_attempts=BATCH_MAX_ATTEMPTS,
                        workflow_input_keys=sorted(transported),
                        workflow_input_types={key: type(value).__name__ for key, value in transported.items()},
                        workflow_input_char_lengths={key: len(str(value)) for key, value in transported.items()},
                        safe_workflow_values={
                            key: transported.get(key)
                            for key in (
                                "script_title", "total_episodes", "batch_start_episode",
                                "batch_end_episode", "is_final_batch",
                            )
                        },
                        stored_memory_char_length=len(stored_memory_text),
                        transport_memory_char_length=len(transported["previous_audit_memory"]),
                        transport_memory_saved_chars=max(
                            0, len(stored_memory_text) - len(transported["previous_audit_memory"])
                        ),
                        batch_script_hash=hashlib.sha256(chunk["script_text"].encode("utf-8")).hexdigest(),
                        previous_memory_hash=hashlib.sha256(transported["previous_audit_memory"].encode("utf-8")).hexdigest(),
                    )
                    try:
                        raw = self._workflow_client().run_raw("hot_review", attempt_variables)
                        batch_payload, batch_warnings = validate_batch_output(
                            raw,
                            chunk["episode_numbers"],
                            record["total_episodes"],
                        )
                        self._append_debug_event(
                            run_id,
                            "workflow_attempt_succeeded",
                            batch_index=chunk["batch_index"],
                            batch_start_episode=chunk["start_episode"],
                            batch_end_episode=chunk["end_episode"],
                            attempt=attempt + 1,
                            returned_schema=_text(batch_payload.get("schema_version")),
                            returned_episode_numbers=[
                                _int(item.get("episode_no"))
                                for item in batch_payload.get("episode_reviews", [])
                                if isinstance(item, dict)
                            ],
                            next_memory_char_length=len(
                                json.dumps(batch_payload.get("next_audit_memory") or {}, ensure_ascii=False)
                            ),
                            client_debug=_safe_client_debug(
                                getattr(self._workflow_client(), "get_last_stage_debug_info", lambda *_: {})("hot_review")
                            ),
                        )
                        last_error = None
                        break
                    except Exception as exc:
                        last_error = exc
                        self._append_debug_event(
                            run_id,
                            "workflow_attempt_failed",
                            batch_index=chunk["batch_index"],
                            batch_start_episode=chunk["start_episode"],
                            batch_end_episode=chunk["end_episode"],
                            attempt=attempt + 1,
                            exception_type=type(exc).__name__,
                            reason=safe_truncated_preview(str(exc), limit=5000),
                            traceback=safe_truncated_preview(traceback.format_exc(), limit=12000),
                            client_debug=_safe_client_debug(
                                getattr(self._workflow_client(), "get_last_stage_debug_info", lambda *_: {})("hot_review")
                            ),
                        )
                        if attempt + 1 < BATCH_MAX_ATTEMPTS:
                            self._append_debug_event(
                                run_id,
                                "batch_retry_scheduled",
                                batch_index=chunk["batch_index"],
                                batch_start_episode=chunk["start_episode"],
                                batch_end_episode=chunk["end_episode"],
                                next_attempt=attempt + 2,
                                max_attempts=BATCH_MAX_ATTEMPTS,
                                completed_episode_numbers=sorted(completed_numbers),
                                progress_preserved=True,
                            )
                            time.sleep(min(1.5 * (attempt + 1), 5.0))
                if last_error or batch_payload is None:
                    current_size = len(chunk["episode_numbers"])
                    if current_size > 1:
                        fallback_size = 2 if current_size > 2 else 1
                        source_episodes = [episode_by_number[number] for number in chunk["episode_numbers"]]
                        fallback_chunks = split_episode_batches(source_episodes, batch_size=fallback_size)
                        work_queue = fallback_chunks + work_queue
                        self._append_debug_event(
                            run_id,
                            "batch_adaptive_split",
                            failed_batch_start=chunk["start_episode"],
                            failed_batch_end=chunk["end_episode"],
                            failed_batch_size=current_size,
                            fallback_batch_size=fallback_size,
                            fallback_ranges=[
                                [item["start_episode"], item["end_episode"]]
                                for item in fallback_chunks
                            ],
                            reason=safe_truncated_preview(str(last_error), limit=2000),
                            progress_preserved=True,
                        )
                        with self._lock:
                            record = self._read(run_id)
                            record.update(
                                total_batches=len(record.get("batches") or []) + len(work_queue),
                                current_batch_start=fallback_chunks[0]["start_episode"],
                                current_batch_end=fallback_chunks[0]["end_episode"],
                                updated_at=_now_iso(),
                            )
                            self._write(record)
                        continue
                    reason = _text(last_error, "远端未返回完整批次结果。")
                    raise RuntimeError(
                        f"第{chunk['start_episode']}-{chunk['end_episode']}集已自动重试"
                        f"{BATCH_MAX_ATTEMPTS}次仍未成功；此前已完成的"
                        f"{len(completed_numbers)}集结果均已保留，可稍后点击继续检测，从本批次续跑。"
                        f"最后一次错误：{reason}"
                    ) from last_error
                memory = compact_audit_memory(batch_payload["next_audit_memory"])
                with self._lock:
                    record = self._read(run_id)
                    stored_batches = record.get("batches") if isinstance(record.get("batches"), list) else []
                    stored_batches.append(batch_payload)
                    completed_numbers = [
                        _int(item.get("episode_no"))
                        for batch in stored_batches
                        for item in batch.get("episode_reviews", [])
                        if isinstance(item, dict)
                    ]
                    record.update(
                        batches=stored_batches, audit_memory=memory, warnings=(record.get("warnings") or []) + batch_warnings,
                        completed_batches=len(stored_batches), completed_episode_numbers=completed_numbers,
                        updated_at=_now_iso(),
                    )
                    self._write(record)
                completed_numbers = set(completed_numbers)
            with self._lock:
                record = self._read(run_id)
                audit, merge_warnings = merge_audit_batches(record["script_title"], record["total_episodes"], record["batches"])
                record.update(
                    status="succeeded", audit=audit, warnings=(record.get("warnings") or []) + merge_warnings,
                    current_batch_start=0, current_batch_end=0, updated_at=_now_iso(), error="",
                )
                self._write(record)
            self._append_debug_event(
                run_id,
                "run_succeeded",
                completed_batches=record.get("completed_batches"),
                completed_episode_numbers=record.get("completed_episode_numbers"),
            )
        except Exception as exc:
            with self._lock:
                try:
                    record = self._read(run_id)
                    record.update(status="failed", error=_text(exc, "心电图批次审核失败。")[:500], updated_at=_now_iso())
                    self._write(record)
                except Exception:
                    pass
            try:
                self._append_debug_event(
                    run_id,
                    "run_failed",
                    exception_type=type(exc).__name__,
                    reason=safe_truncated_preview(str(exc), limit=5000),
                    traceback=safe_truncated_preview(traceback.format_exc(), limit=12000),
                    client_debug=_safe_client_debug(
                        getattr(self._workflow_client(), "get_last_stage_debug_info", lambda *_: {})("hot_review")
                    ),
                )
            except Exception:
                pass

    def get_run(self, run_id: str, *, user_id: int, relaunch_stale: bool = False) -> dict[str, Any]:
        with self._lock:
            record = self._read(run_id)
        if int(record.get("user_id") or 0) != int(user_id):
            raise ValueError("心电图运行记录不存在。")
        if relaunch_stale and _text(record.get("status")) in {"pending", "running"}:
            self._launch(run_id)
        return self.public_record(record)

    def resume_run(self, run_id: str, *, user_id: int) -> dict[str, Any]:
        record = self.get_run(run_id, user_id=user_id)
        if record["status"] == "succeeded":
            return record
        with self._lock:
            private = self._read(run_id)
            private.update(status="pending", error="", updated_at=_now_iso())
            self._write(private)
        self._append_debug_event(
            run_id,
            "run_resume_requested",
            completed_batches=record.get("completed_batches"),
            previous_error=record.get("error"),
        )
        self._launch(run_id)
        return self.get_run(run_id, user_id=user_id)

    def delete_run(self, run_id: str, *, user_id: int) -> dict[str, Any]:
        """Delete one owned, inactive audit record and its sidecar files."""
        with self._lock:
            record = self._read(run_id)
            if int(record.get("user_id") or 0) != int(user_id):
                raise ValueError("心电图运行记录不存在。")
            thread = self._threads.get(run_id)
            if _text(record.get("status")) in {"pending", "running"} or (thread and thread.is_alive()):
                raise RuntimeError("评分仍在运行，完成或失败后才能删除该记录。")

            record_path = self._path(run_id)
            summary_path = self._summary_path(run_id)
            debug_path = self._debug_path(run_id)
            sidecars = (
                summary_path,
                debug_path,
                record_path.with_suffix(".tmp"),
                summary_path.with_suffix(".summary.tmp"),
                debug_path.with_suffix(".debug.tmp"),
            )
            for path in sidecars:
                path.unlink(missing_ok=True)
            record_path.unlink()
            self._threads.pop(run_id, None)
        return {
            "run_id": _text(run_id),
            "script_title": _text(record.get("script_title"), "未命名剧本"),
            "deleted": True,
        }

    def get_debug(self, run_id: str, *, user_id: int) -> dict[str, Any]:
        with self._lock:
            record = self._read(run_id)
            if int(record.get("user_id") or 0) != int(user_id):
                raise ValueError("心电图运行记录不存在。")
            path = self._debug_path(run_id)
            if not path.exists():
                return {"run_id": run_id, "debug_file": str(path), "events": []}
            document = json.loads(path.read_text(encoding="utf-8"))
        events = document.get("events") if isinstance(document, dict) and isinstance(document.get("events"), list) else []
        return {"run_id": run_id, "debug_file": str(path), "events": events}

    def public_record(self, record: dict[str, Any], *, include_source: bool = True) -> dict[str, Any]:
        total = max(1, _int(record.get("total_episodes"), 1))
        completed = len(record.get("completed_episode_numbers") or [])
        public_keys = [
            "run_id", "script_title", "status", "created_at", "updated_at", "total_episodes",
            "total_batches", "completed_batches", "completed_episode_numbers", "current_batch_start",
            "current_batch_end", "error", "debug_file", "debug_event_count", "debug_last_event",
        ]
        if include_source:
            public_keys.extend(("warnings", "audit"))
        result = {
            key: copy.deepcopy(record.get(key))
            for key in public_keys
        }
        result["progress_percent"] = round(min(100, completed / total * 100), 1)
        result["asset_id"] = _text(record.get("run_id"))
        result["script_hash"] = _text(record.get("script_hash"))
        result["has_result"] = bool(record.get("status") == "succeeded" and isinstance(record.get("audit"), dict))
        if not include_source and isinstance(record.get("audit"), dict):
            overall = record["audit"].get("overall") if isinstance(record["audit"].get("overall"), dict) else {}
            result["total_score"] = overall.get("total_score")
            result["level"] = _text(overall.get("level"))
        if include_source:
            result["script_text"] = _text(record.get("script_text"))
        if include_source and record.get("status") == "succeeded" and isinstance(record.get("audit"), dict):
            result["view"] = build_script_audit_view_model(record["audit"])
            result["result_type"] = "script_audit_ecg"
        return result


script_audit_batch_service = ScriptAuditBatchService()
