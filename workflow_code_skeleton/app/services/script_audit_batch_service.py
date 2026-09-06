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
MAX_COLLECTED_FAILURES = 80
ACTIVE_RUN_STATUSES = {"pending", "running"}

_EPISODE_HEADER = re.compile(
    r"(?m)^[ \t]*(?:#{1,6}[ \t]*)?第[ \t]*"
    r"(?P<number>[0-9０-９零〇一二三四五六七八九十百两]+)"
    r"[ \t]*集(?:[ \t]*[：:\-—][ \t]*(?P<title>[^\r\n]*))?[ \t]*$"
)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).astimezone().isoformat()


def _process_is_alive(pid: int) -> bool:
    """Check a persisted runner PID without sending it a signal on Windows."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes

            process_query_limited_information = 0x1000
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            # Access denied still proves that the process exists.
            return ctypes.get_last_error() == 5
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


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
        if (
            value.get("schema_version") == BATCH_SCHEMA_VERSION
            or {"batch_meta", "episode_reviews", "next_audit_memory"}.issubset(value)
            or (
                isinstance(value.get("episode_reviews"), list)
                and isinstance(value.get("batch_meta"), dict)
            )
        ):
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
            "心电图远端最终输出只有不完整批次摘要，不能生成逐集心电图。"
            f"{detail}。如果结束节点已经像截图一样引用大模型 Output.Content，"
            "请检查当前 AppKey 是否属于这个应用、修改是否已发布为新版本，并在节点调试中确认"
            "大模型 Content 本身含完整 script_audit_batch_v1 JSON。"
        )
    raise ValueError(
        "心电图工作流未返回可解析的 script_audit_batch_v1 JSON。"
        "请确认结束节点字段为 audit_batch，且引用大模型1.Output.Content。"
    )


def inspect_batch_response(raw: Any) -> dict[str, Any]:
    """Describe response shapes without persisting model text or script excerpts."""
    shapes: list[dict[str, Any]] = []
    seen: set[str] = set()
    complete_candidates = 0
    incomplete_summary_candidates = 0
    truncated_json_candidates = 0
    for source, value in _iter_batch_candidates(raw):
        if isinstance(value, str):
            if BATCH_SCHEMA_VERSION not in value or '"episode_reviews"' not in value:
                continue
            try:
                json.loads(value)
            except json.JSONDecodeError as exc:
                truncated_json_candidates += 1
                signature = f"text:{source}:{len(value)}:{exc.pos}"
                if signature not in seen and len(shapes) < 20:
                    seen.add(signature)
                    shapes.append({
                        "source": source,
                        "kind": "truncated_batch_json",
                        "char_length": len(value),
                        "json_error_line": exc.lineno,
                        "json_error_column": exc.colno,
                    })
            continue
        if not isinstance(value, dict):
            continue
        keys = sorted(str(key) for key in value)
        is_complete = (
            value.get("schema_version") == BATCH_SCHEMA_VERSION
            or {"batch_meta", "episode_reviews", "next_audit_memory"}.issubset(value)
            or (
                isinstance(value.get("episode_reviews"), list)
                and isinstance(value.get("batch_meta"), dict)
            )
        )
        business_keys = {
            "batch_start_episode", "batch_end_episode", "total_episodes",
            "reviewed_episode_numbers", "batch_core_judgement",
        }
        overlap = len(business_keys.intersection(value))
        if not is_complete and not overlap:
            continue
        kind = "complete_batch_candidate" if is_complete else "incomplete_batch_summary"
        complete_candidates += int(is_complete)
        incomplete_summary_candidates += int(not is_complete)
        signature = f"{kind}:{','.join(keys)}"
        if signature in seen or len(shapes) >= 20:
            continue
        seen.add(signature)
        shape: dict[str, Any] = {
            "source": source,
            "kind": kind,
            "keys": keys[:60],
        }
        if overlap:
            shape.update(
                batch_start_episode=_int(value.get("batch_start_episode")),
                batch_end_episode=_int(value.get("batch_end_episode")),
                total_episodes=_int(value.get("total_episodes")),
                reviewed_episode_numbers=[
                    _int(item) for item in value.get("reviewed_episode_numbers", [])
                ] if isinstance(value.get("reviewed_episode_numbers"), list) else [],
            )
        shapes.append(shape)
    try:
        response_char_length = len(json.dumps(raw, ensure_ascii=False, default=str))
    except Exception:
        response_char_length = len(str(raw))
    return {
        "response_type": type(raw).__name__,
        "response_char_length": response_char_length,
        "complete_candidate_count": complete_candidates,
        "incomplete_summary_candidate_count": incomplete_summary_candidates,
        "truncated_json_candidate_count": truncated_json_candidates,
        "candidate_shapes": shapes,
    }


_LOCAL_HOOK_WORDS = (
    "突然", "竟然", "没想到", "发现", "真相", "秘密", "危机", "出事", "死", "杀",
    "抓", "追", "逃", "威胁", "倒计时", "失踪", "背叛", "身份", "等等", "住手",
)
_LOCAL_CONFLICT_WORDS = (
    "冲突", "反对", "拒绝", "争", "打", "杀", "抓", "追", "逃", "逼", "威胁",
    "质问", "怒", "恨", "仇", "敌", "危险", "失败", "阻止", "不能", "不许", "滚",
)
_LOCAL_PAYOFF_WORDS = (
    "反击", "揭穿", "打脸", "胜", "赢", "成功", "救", "夺回", "报仇", "惩罚",
    "真相", "承认", "跪", "求饶", "震惊", "惊呆", "原来", "终于", "证明",
)
_LOCAL_EXPOSITION_WORDS = (
    "解释", "说明", "回忆", "旁白", "因为", "所以", "原来", "其实", "多年以前",
    "换句话说", "也就是说", "众所周知",
)
_LOCAL_RISK_WORDS = ("吸毒", "贩毒", "赌博", "色情", "强奸", "自杀", "虐杀", "迷信", "邪教")


def _best_incomplete_batch_summary(raw: Any) -> dict[str, Any]:
    """Return the richest end-node summary without accepting it as a full audit."""
    business_keys = {
        "batch_start_episode", "batch_end_episode", "total_episodes",
        "reviewed_episode_numbers", "is_final_batch", "batch_core_judgement",
    }
    candidates: list[tuple[int, dict[str, Any]]] = []
    for _source, value in _iter_batch_candidates(raw):
        if not isinstance(value, dict) or isinstance(value.get("episode_reviews"), list):
            continue
        overlap = len(business_keys.intersection(value))
        if overlap:
            candidates.append((overlap, value))
    if not candidates:
        raise ValueError("远端响应中没有可用于本地兼容审核的批次摘要。")
    return copy.deepcopy(max(candidates, key=lambda item: item[0])[1])


def _local_keyword_hits(text: str, words: tuple[str, ...]) -> int:
    return sum(str(text or "").count(word) for word in words)


def _local_excerpt(value: Any, limit: int = 96) -> str:
    return re.sub(r"\s+", " ", _text(value))[:limit]


def _local_episode_lines(episode: dict[str, Any]) -> list[str]:
    lines = [
        re.sub(r"^[△▲○●◆◇]+\s*", "", line.strip())
        for line in _text(episode.get("text")).splitlines()
        if line.strip()
    ]
    if lines and _EPISODE_HEADER.match(lines[0]):
        lines = lines[1:]
    return lines or [f"第{_int(episode.get('episode_no'))}集正文"]


def _local_emotion(text: str, *, default: str = "期待") -> str:
    groups = (
        ("紧张", ("危机", "危险", "追", "逃", "抓", "倒计时", "突然")),
        ("愤怒", ("怒", "恨", "仇", "背叛", "滚", "质问")),
        ("悲伤", ("哭", "泪", "死", "失去", "离开", "绝望")),
        ("畅快", ("反击", "打脸", "赢", "成功", "惩罚", "揭穿")),
        ("惊讶", ("震惊", "竟然", "原来", "真相", "秘密", "发现")),
        ("温暖", ("拥抱", "爱", "相信", "陪", "保护", "团聚")),
    )
    hits, emotion = max(
        ((sum(str(text or "").count(word) for word in words), emotion) for emotion, words in groups),
        default=(0, default),
    )
    return emotion if hits else default


def _local_line_intensity(line: str) -> int:
    positive = sum((
        _local_keyword_hits(line, _LOCAL_HOOK_WORDS),
        _local_keyword_hits(line, _LOCAL_CONFLICT_WORDS),
        _local_keyword_hits(line, _LOCAL_PAYOFF_WORDS),
    ))
    exposition = _local_keyword_hits(line, _LOCAL_EXPOSITION_WORDS)
    return max(-2, min(5, positive * 2 - min(2, exposition)))


def _local_continuity_overlap(previous: str, current: str) -> float:
    def bigrams(value: str) -> set[str]:
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", value or ""))
        return {chinese[index:index + 2] for index in range(max(0, len(chinese) - 1))}

    left, right = bigrams(previous), bigrams(current)
    return len(left & right) / max(1, min(len(left), len(right)))


def _build_local_rule_episode_review(
    episode: dict[str, Any], *, previous_ending: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Create an explicitly labelled deterministic review from the real episode text."""
    number = _int(episode.get("episode_no"))
    title = _text(episode.get("episode_title"), f"第{number}集")
    text = _text(episode.get("text"))
    lines = _local_episode_lines(episode)
    opening_text = " ".join(lines[:min(5, len(lines))])
    ending_text = " ".join(lines[-min(5, len(lines)):])
    opening_excerpt, ending_excerpt = _local_excerpt(lines[0]), _local_excerpt(lines[-1])
    scene_count = max(1, sum(bool(re.search(r"场景|内景|外景|△|▲", line)) for line in lines))
    dialogue_count = sum(bool(re.search(r"[:：]", line)) for line in lines)
    hook_hits = _local_keyword_hits(opening_text, _LOCAL_HOOK_WORDS)
    conflict_hits = _local_keyword_hits(text, _LOCAL_CONFLICT_WORDS)
    payoff_hits = _local_keyword_hits(text, _LOCAL_PAYOFF_WORDS)
    exposition_hits = _local_keyword_hits(text, _LOCAL_EXPOSITION_WORDS)
    ending_hook_hits = _local_keyword_hits(ending_text, _LOCAL_HOOK_WORDS + ("？", "?", "却", "就在这时"))
    risk_hits = _local_keyword_hits(text, _LOCAL_RISK_WORDS)
    clamp = lambda value, maximum: max(0, min(maximum, int(value)))
    scores = {
        "opening_hook": clamp(8 + min(4, hook_hits) + int(dialogue_count > 0), 15),
        "conflict_pacing": clamp(14 + min(6, conflict_hits // 2) + min(2, scene_count - 1) - min(3, exposition_hits // 3), 25),
        "satisfying_payoff": clamp(10 + min(8, payoff_hits) + min(2, ending_hook_hits), 25),
        "character_dialogue_filming": clamp(12 + (3 if dialogue_count / max(1, len(lines)) >= .25 else 1) + min(2, scene_count - 1) - int(len(text) > 4500), 20),
        "market_compliance": clamp(10 + min(2, ending_hook_hits) + int(500 <= len(text) <= 4000) - min(3, risk_hits), 15),
    }
    fixes = {
        "opening_hook": "把首个明确危机、反常信息或人物目标前置到开场。",
        "conflict_pacing": "压缩解释性段落，让阻力、选择与后果在同一场内升级。",
        "satisfying_payoff": "补足可见的反击、揭示或阶段性兑现，让结果改变人物处境。",
        "character_dialogue_filming": "把抽象说明改为人物动作、对抗对白和可见场面。",
        "market_compliance": "强化结尾追看承诺，并复核高风险表达的剧情必要性。",
    }
    summaries = {
        "opening_hook": f"开场规则命中{hook_hits}个钩子信号。",
        "conflict_pacing": f"全文识别{conflict_hits}个冲突信号、约{scene_count}个场景信号。",
        "satisfying_payoff": f"全文识别{payoff_hits}个兑现信号，结尾识别{ending_hook_hits}个追看信号。",
        "character_dialogue_filming": f"正文约{len(lines)}行，其中{dialogue_count}行含对白或角色提示。",
        "market_compliance": f"按篇幅、结尾拉力和{risk_hits}个高风险词信号初筛。",
    }

    ranked = sorted(range(len(lines)), key=lambda index: (_local_line_intensity(lines[index]), index), reverse=True)
    selected = sorted(set((0, len(lines) - 1, ranked[0])))
    points, segments = [], []
    for point_index, line_index in enumerate(selected, start=1):
        excerpt = _local_excerpt(lines[line_index])
        value = _local_line_intensity(lines[line_index])
        if line_index == len(lines) - 1 and ending_hook_hits:
            value = max(2, value)
        position = "开场" if line_index == 0 else "结尾" if line_index == len(lines) - 1 else "高强度节点"
        segment_id = f"local_seg_e{number:03d}_{point_index:02d}"
        points.append({
            "point_id": f"local_ecg_e{number:03d}_{point_index:02d}", "segment_id": segment_id,
            "episode_no": number, "scene_no": 0, "segment_index_in_episode": point_index,
            "x_label": f"第{number}集·{position}", "ecg_value": value, "short_label": position,
            "audit_reason": "按冲突、悬念、兑现及说明性词汇的文本信号计算。",
            "commercial_effect": "在远端缺少逐集明细时保留可复核的相对节奏曲线。",
            "problem_if_any": "低值表示说明性信号强于冲突或兑现信号。" if value < 0 else "",
            "fix_suggestion": "结合原文复核；重要改稿仍建议使用完整大模型审核。",
            "event_type": "本地规则节点", "event_subtype": position,
            "original_text_excerpt": excerpt, "tags": ["本地兜底", "可追溯原文"], "score_impacts": [],
        })
        segments.append({
            "segment_id": segment_id, "episode_no": number, "scene_no": 0,
            "segment_index_in_episode": point_index, "segment_type": "local_rule_evidence",
            "summary": f"{position}文本证据", "original_text_excerpt": excerpt,
        })

    main_conflict = next((line for line in lines if _local_keyword_hits(line, _LOCAL_CONFLICT_WORDS)), lines[len(lines) // 2])
    main_payoff = next((line for line in lines if _local_keyword_hits(line, _LOCAL_PAYOFF_WORDS)), "")
    strongest = lines[ranked[0]]
    total_score = sum(scores.values())
    if number <= 1:
        continuity_score, previous_fact, match = 10, "首集无上一集。", "首集不做跨集事实匹配。"
    else:
        overlap = _local_continuity_overlap(previous_ending, opening_text)
        continuity_score = 8 if overlap >= .12 else 7 if overlap >= .05 else 5
        previous_fact = _local_excerpt(previous_ending) or "上一集交接文本不足。"
        match = f"相邻文本重合度约{overlap:.0%}；" + ("存在直接承接信号。" if overlap >= .05 else "未发现强直接承接词，需人工复核。")
    evidence = {
        "previous_ending_fact": previous_fact,
        "current_opening_fact": _local_excerpt(opening_text),
        "match_judgement": match,
    }
    dimensions = [{
        "dimension_key": key, "dimension_name": name, "max_score": maximum, "score": scores[key],
        "summary": summaries[key], "deduction_reason": "这是本地文本规则分，不等同于完整大模型语义评分。",
        "fix_direction": fixes[key], "evidence_segment_ids": [point["segment_id"] for point in points],
    } for key, name, maximum in AUDIT_DIMENSIONS]
    maxima = {key: maximum for key, _name, maximum in AUDIT_DIMENSIONS}
    weakest_key = min(scores, key=lambda key: scores[key] / maxima[key])
    review = {
        "episode_no": number, "episode_title": title,
        "episode_scope": "本地规则兜底审核（基于当前集真实正文）",
        "episode_score": total_score, "episode_score_explanation": "五维由可追溯文本规则生成；腾讯摘要未提供逐集分数。",
        "level": _score_level(total_score),
        "core_judgement": f"本集为本地规则兜底结果，规则总分{total_score}分。",
        "main_hook": opening_excerpt, "main_conflict": _local_excerpt(main_conflict),
        "main_payoff": _local_excerpt(main_payoff) or "规则未识别到明确兑现词，需人工复核。",
        "largest_retention_loss": summaries[weakest_key], "best_retained_part": _local_excerpt(strongest),
        "next_episode_pull": ending_excerpt, "priority_fix": fixes[weakest_key],
        "episode_structure": {"opening": opening_excerpt, "development": _local_excerpt(lines[len(lines)//2]), "climax": _local_excerpt(strongest), "ending": ending_excerpt},
        "emotional_review": {
            "opening_emotion": _local_emotion(opening_text), "dominant_emotion": _local_emotion(text, default="压迫"),
            "ending_emotion": _local_emotion(ending_text), "emotional_turning_points": [_local_excerpt(strongest)],
            "emotional_payoff": "规则检测到兑现信号。" if payoff_hits else "规则未检测到明确兑现信号。",
            "emotional_curve_score": max(1, min(10, 5 + payoff_hits + min(2, conflict_hits // 3))),
        },
        "continuity_review": {
            "previous_episode_no": number - 1 if number > 1 else 0, "current_episode_no": number,
            "handoff_smoothness_score": continuity_score, "incoming_plot_matches": continuity_score >= 7,
            "character_state_matches": continuity_score >= 7, "time_space_transition_is_clear": continuity_score >= 7,
            "information_progression_is_valid": True, "emotion_transition_is_natural": continuity_score >= 7,
            "continuity_evidence": evidence,
            "break_points": [] if continuity_score >= 7 else ["开场与上一集结尾缺少强文本承接信号。"],
            "fix_suggestion": "在开场补一个承接上一集未完成动作或危机的可见镜头。" if continuity_score < 7 else "",
        },
        "dimension_scores": dimensions, "ecg_points": points,
        "ending_hook": {"hook_type": "文本规则识别", "strength": "强" if ending_hook_hits >= 2 else "中" if ending_hook_hits else "弱", "description": ending_excerpt, "original_text_excerpt": ending_excerpt},
        "satisfying_points": [], "key_issues": [], "risk_scan": [], "rewrite_plan": [],
        "analysis_source": "local_rule_fallback",
    }
    return review, segments, ending_text


def build_local_summary_fallback(
    raw: Any,
    episodes: list[dict[str, Any]],
    expected_numbers: list[int],
    expected_total_episodes: int,
    *,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn a summary or truncated remote output into a complete, explicitly marked batch."""
    try:
        summary = _best_incomplete_batch_summary(raw)
    except ValueError:
        diagnostics = inspect_batch_response(raw)
        if not diagnostics.get("truncated_json_candidate_count"):
            raise
        summary = {}
    by_number = {_int(item.get("episode_no")): item for item in episodes if isinstance(item, dict)}
    if any(number not in by_number for number in expected_numbers):
        raise ValueError("本地兼容审核缺少当前批次的真实分集正文。")
    memory = copy.deepcopy(previous_memory) if isinstance(previous_memory, dict) else {}
    handoff = memory.get("last_episode_handoff") if isinstance(memory.get("last_episode_handoff"), dict) else {}
    previous_ending = _text(handoff.get("ending_text_excerpt") or handoff.get("ending_scene_summary"))
    reviews, segments = [], []
    for number in expected_numbers:
        review, episode_segments, previous_ending = _build_local_rule_episode_review(by_number[number], previous_ending=previous_ending)
        reviews.append(review)
        segments.extend(episode_segments)

    score_index = {
        _int(item.get("episode_no")): {"episode_no": _int(item.get("episode_no")), "score": item.get("score")}
        for item in memory.get("episode_score_index", [])
        if isinstance(item, dict) and _int(item.get("episode_no")) > 0
    }
    for review in reviews:
        score_index[review["episode_no"]] = {"episode_no": review["episode_no"], "score": review["episode_score"]}
    ranked = sorted(score_index.values(), key=lambda item: (float(item.get("score") or 0), -_int(item.get("episode_no"))))
    judgement = _text(summary.get("batch_core_judgement"), "远端仅返回批次摘要。")
    last_review, last_hook = reviews[-1], reviews[-1]["ending_hook"]
    memory.update({
        "reviewed_through_episode": expected_numbers[-1],
        "episode_score_index": [score_index[key] for key in sorted(score_index)][-60:],
        "weak_episode_numbers": [item["episode_no"] for item in score_index.values() if float(item.get("score") or 0) < 65][-30:],
        "best_episode_no": _int(ranked[-1].get("episode_no")) if ranked else 0,
        "best_episode_reason": "按本地规则五维总分暂时最高。",
        "weakest_episode_no": _int(ranked[0].get("episode_no")) if ranked else 0,
        "weakest_episode_reason": "按本地规则五维总分暂时最低。",
        "running_retention_judgement": judgement, "global_strength_summary": judgement,
        "global_weakness_summary": "腾讯未返回逐集语义字段，当前逐集细节为本地文本规则兜底。",
        "largest_problem": "远端输出被截断/退化，逐集深度判断暂由本地规则替代。",
        "best_retained_part": _text(last_review.get("best_retained_part")), "priority_fix": _text(last_review.get("priority_fix")),
        "final_judgement": "可用于展示和定位节奏节点；重要改稿决策建议在远端完整输出恢复后复核。",
        "modification_cost": "中", "retention_curve_summary": "逐集曲线来自统一的本地可追溯文本规则。",
        "fix_suggestion": _text(last_review.get("priority_fix")),
        "next_batch_watch_points": [f"核对下一集开场是否承接：{_text(last_hook.get('description'))}"],
        "last_episode_handoff": {
            "episode_no": expected_numbers[-1], "ending_scene_summary": _text(last_review.get("episode_structure", {}).get("ending")),
            "ending_time_space": "", "ending_emotion": _text(last_review.get("emotional_review", {}).get("ending_emotion")),
            "active_action_or_crisis": _text(last_review.get("main_conflict")), "ending_hook_promise": _text(last_hook.get("description")),
            "ending_text_excerpt": _text(last_hook.get("original_text_excerpt")), "character_state_snapshot": [],
            "information_state": [], "prop_resource_state": [], "relationship_state": [],
            "unresolved_actions": [_text(last_review.get("next_episode_pull"))],
            "continuity_watch_points": ["下一集开场需承接本集结尾事实。"],
        },
    })
    first_continuity = reviews[0]["continuity_review"]
    return {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_meta": {
            "batch_start_episode": expected_numbers[0], "batch_end_episode": expected_numbers[-1],
            "total_episodes": int(expected_total_episodes), "reviewed_episode_numbers": list(expected_numbers),
            "is_final_batch": expected_numbers[-1] == int(expected_total_episodes),
            "analysis_mode": "remote_incomplete_plus_local_rule_fallback",
        },
        "batch_core_judgement": judgement,
        "boundary_review": {
            "previous_episode_no": expected_numbers[0] - 1 if expected_numbers[0] > 1 else 0,
            "current_episode_no": expected_numbers[0], "handoff_smoothness_score": first_continuity["handoff_smoothness_score"],
            "plot_continuity": first_continuity["continuity_evidence"]["match_judgement"],
            "character_state_continuity": "按相邻文本信号初筛。", "information_continuity": "按相邻文本信号初筛。",
            "emotion_continuity": "按相邻文本情绪词初筛。", "continuity_evidence": copy.deepcopy(first_continuity["continuity_evidence"]),
            "break_points": copy.deepcopy(first_continuity["break_points"]), "fix_suggestion": _text(first_continuity.get("fix_suggestion")),
        },
        "segments": segments, "episode_reviews": reviews, "batch_key_issues": [], "batch_rewrite_plan": [],
        "batch_satisfying_points": [], "batch_risk_scan": [], "next_audit_memory": memory,
        "analysis_source": "remote_incomplete_plus_local_rule_fallback",
    }


def _score_level(score: float) -> str:
    return "S" if score >= 90 else "A" if score >= 80 else "B" if score >= 70 else "C" if score >= 60 else "D"


def _build_handoff_from_review(
    review: dict[str, Any],
    memory: dict[str, Any],
    episode_no: int,
) -> dict[str, Any]:
    emotional = review.get("emotional_review") if isinstance(review.get("emotional_review"), dict) else {}
    structure = review.get("episode_structure") if isinstance(review.get("episode_structure"), dict) else {}
    ending_hook = review.get("ending_hook") if isinstance(review.get("ending_hook"), dict) else {}
    return {
        "episode_no": episode_no,
        "ending_scene_summary": _text(structure.get("ending")),
        "ending_time_space": "",
        "ending_emotion": _text(emotional.get("ending_emotion")),
        "active_action_or_crisis": _text(review.get("main_conflict")),
        "ending_hook_promise": _text(ending_hook.get("description") or review.get("next_episode_pull")),
        "ending_text_excerpt": _text(ending_hook.get("original_text_excerpt")),
        "character_state_snapshot": copy.deepcopy(memory.get("current_character_states") or []),
        "information_state": [],
        "prop_resource_state": [],
        "relationship_state": [],
        "unresolved_actions": [
            value for value in (_text(review.get("next_episode_pull")),) if value
        ],
        "continuity_watch_points": copy.deepcopy(memory.get("next_batch_watch_points") or []),
    }


def validate_batch_output(
    raw: Any,
    expected_numbers: list[int],
    expected_total_episodes: int | None = None,
    *,
    previous_memory: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    payload = copy.deepcopy(
        _extract_batch_payload(raw, expected_total_episodes=expected_total_episodes)
    )
    warnings: list[str] = []
    if payload.get("schema_version") in (None, ""):
        payload["schema_version"] = BATCH_SCHEMA_VERSION
        warnings.append("远端漏填 schema_version，本地已按当前审核契约补为 script_audit_batch_v1。")
    elif payload.get("schema_version") != BATCH_SCHEMA_VERSION:
        raise ValueError(f"批次 schema_version 必须是 {BATCH_SCHEMA_VERSION}。")
    reviews = payload.get("episode_reviews") if isinstance(payload.get("episode_reviews"), list) else []
    actual_numbers = [_int(item.get("episode_no")) for item in reviews if isinstance(item, dict)]
    if actual_numbers != expected_numbers:
        raise ValueError(f"批次逐集结果不完整：期望 {expected_numbers}，实际 {actual_numbers}。")
    required_dimensions = [item[0] for item in AUDIT_DIMENSIONS]
    dimension_max_scores = {item[0]: item[2] for item in AUDIT_DIMENSIONS}
    for review in reviews:
        episode_no = _int(review.get("episode_no"))
        raw_dimensions = review.get("dimension_scores")
        if isinstance(raw_dimensions, dict):
            dimensions = []
            for key, value in raw_dimensions.items():
                item = copy.deepcopy(value) if isinstance(value, dict) else {"score": value}
                item["dimension_key"] = _text(item.get("dimension_key") or item.get("key") or key)
                dimensions.append(item)
            warnings.append(f"远端第{episode_no}集 dimension_scores 使用了对象形式，本地已转换为标准数组。")
        else:
            dimensions = raw_dimensions if isinstance(raw_dimensions, list) else []
        actual_dimension_keys = [
            _text(item.get("dimension_key") or item.get("key"))
            for item in dimensions
            if isinstance(item, dict)
        ]
        if len(actual_dimension_keys) != len(set(actual_dimension_keys)) or set(actual_dimension_keys) != set(required_dimensions):
            raise ValueError(f"第{episode_no}集五维评分不完整或顺序错误：{actual_dimension_keys}。")
        if actual_dimension_keys != required_dimensions:
            by_key = {
                _text(item.get("dimension_key") or item.get("key")): item
                for item in dimensions
                if isinstance(item, dict)
            }
            dimensions = [by_key[key] for key in required_dimensions]
            warnings.append(f"远端第{episode_no}集五维评分顺序错误，本地已按固定维度顺序重排。")
        score_sum = 0.0
        for index, dimension in enumerate(dimensions):
            key, name, maximum = AUDIT_DIMENSIONS[index]
            dimension["dimension_key"] = key
            dimension["dimension_name"] = name
            dimension["max_score"] = maximum
            maximum = dimension_max_scores[key]
            try:
                score = float(dimension.get("score"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"第{episode_no}集 {key} 的分数不是数字。") from exc
            if not 0 <= score <= maximum:
                raise ValueError(f"第{episode_no}集 {key} 的 score/max_score 超出约定范围。")
            dimension["score"] = int(score) if score.is_integer() else score
            score_sum += score
        review["dimension_scores"] = dimensions
        try:
            episode_score = float(review.get("episode_score"))
        except (TypeError, ValueError):
            episode_score = -1
        if abs(episode_score - score_sum) > 0.01:
            review["episode_score"] = int(score_sum) if score_sum.is_integer() else score_sum
            warnings.append(
                f"远端第{episode_no}集 episode_score 与五维合计不一致或缺失，"
                f"本地已按五维得分重算为 {score_sum:g}。"
            )
        else:
            review["episode_score"] = int(episode_score) if episode_score.is_integer() else episode_score
        if not _text(review.get("level")):
            review["level"] = _score_level(score_sum)
        for key in ("satisfying_points", "key_issues", "risk_scan", "rewrite_plan"):
            if not isinstance(review.get(key), list):
                review[key] = []
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
    expected_meta = {
        "batch_start_episode": expected_numbers[0],
        "batch_end_episode": expected_numbers[-1],
        "reviewed_episode_numbers": list(expected_numbers),
    }
    if expected_total_episodes:
        expected_meta["total_episodes"] = int(expected_total_episodes)
        expected_meta["is_final_batch"] = expected_numbers[-1] == expected_total_episodes
    repaired_meta_fields = [
        key for key, value in expected_meta.items() if meta.get(key) != value
    ]
    if repaired_meta_fields:
        meta.update(expected_meta)
        warnings.append(
            "远端 batch_meta 的确定性元数据缺失或不一致，本地已按输入剧本校正："
            + ", ".join(repaired_meta_fields)
            + "。"
        )
    payload["batch_meta"] = meta
    boundary = payload.get("boundary_review") if isinstance(payload.get("boundary_review"), dict) else {}
    expected_previous = expected_numbers[0] - 1 if expected_numbers[0] > 1 else 0
    if not boundary:
        first_continuity = reviews[0].get("continuity_review")
        first_continuity = first_continuity if isinstance(first_continuity, dict) else {}
        evidence = first_continuity.get("continuity_evidence")
        match_judgement = _text(evidence.get("match_judgement")) if isinstance(evidence, dict) else ""
        boundary = {
            "previous_episode_no": expected_previous,
            "current_episode_no": expected_numbers[0],
            "handoff_smoothness_score": first_continuity.get("handoff_smoothness_score", 0),
            "plot_continuity": match_judgement,
            "character_state_continuity": "",
            "information_continuity": "",
            "emotion_continuity": "",
            "continuity_evidence": copy.deepcopy(evidence) if isinstance(evidence, dict) else {},
            "break_points": copy.deepcopy(first_continuity.get("break_points") or []),
            "fix_suggestion": _text(first_continuity.get("fix_suggestion")),
        }
        warnings.append("远端漏填 boundary_review，本地已从批首集 continuity_review 生成兼容边界审核。")
    elif (
        _int(boundary.get("previous_episode_no"), -1) != expected_previous
        or _int(boundary.get("current_episode_no"), -1) != expected_numbers[0]
    ):
        boundary["previous_episode_no"] = expected_previous
        boundary["current_episode_no"] = expected_numbers[0]
        warnings.append("远端 boundary_review 集号不一致，本地已按当前批次起点校正。")
    payload["boundary_review"] = boundary
    memory = payload.get("next_audit_memory")
    if not isinstance(memory, dict) or not memory:
        memory = copy.deepcopy(previous_memory) if isinstance(previous_memory, dict) else {}
        warnings.append(
            "远端漏填 next_audit_memory，本地已继承上一批记忆并从当前逐集审核生成最小可续跑记忆。"
        )
    if _int(memory.get("reviewed_through_episode")) != expected_numbers[-1]:
        memory["reviewed_through_episode"] = expected_numbers[-1]
        warnings.append("远端 next_audit_memory.reviewed_through_episode 不正确，本地已校正。")
    score_index = {
        _int(item.get("episode_no")): {
            "episode_no": _int(item.get("episode_no")),
            "score": item.get("score"),
        }
        for item in memory.get("episode_score_index", [])
        if isinstance(item, dict) and _int(item.get("episode_no")) > 0
    }
    for review in reviews:
        score_index[_int(review.get("episode_no"))] = {
            "episode_no": _int(review.get("episode_no")),
            "score": review.get("episode_score"),
        }
    memory["episode_score_index"] = [score_index[key] for key in sorted(score_index)][-12:]
    handoff = memory.get("last_episode_handoff")
    if not isinstance(handoff, dict) or _int(handoff.get("episode_no")) != expected_numbers[-1]:
        # Backward compatibility for the already-published workflow. This snapshot
        # is deterministic extraction from the accepted current-episode review; it
        # keeps the next episode connected until the remote prompt is upgraded to
        # return the richer handoff fields itself.
        memory["last_episode_handoff"] = _build_handoff_from_review(
            reviews[-1], memory, expected_numbers[-1]
        )
        warnings.append(
            f"远端第{expected_numbers[-1]}集记忆缺少 last_episode_handoff，"
            "本地已从本集审核结果生成兼容交接快照；建议按最新提示词更新远端工作流。"
        )
    payload["next_audit_memory"] = memory
    for key in (
        "segments", "batch_key_issues", "batch_rewrite_plan",
        "batch_satisfying_points", "batch_risk_scan",
    ):
        if not isinstance(payload.get(key), list):
            payload[key] = []
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


_AUDIT_FAILURE_CATEGORIES: dict[str, dict[str, Any]] = {
    "end_node_summary": {
        "label": "远端最终输出只返回摘要",
        "phase": "response_contract",
        "retry_current_batch": True,
        "smaller_batch_may_help": False,
        "operator_hint": (
            "远端只回传了六字段摘要；本地会对当前批次做一次强制完整结构的格式纠错重试，"
            "但不会拆成更多批次。若重试仍相同，请核对 AppKey、发布版本，并确认大模型节点"
            "Content 本身包含完整 script_audit_batch_v1。"
        ),
    },
    "input_contract": {
        "label": "开始节点输入契约错误",
        "phase": "request_contract",
        "retry_current_batch": False,
        "smaller_batch_may_help": False,
        "operator_hint": (
            "腾讯接口拒绝了开始节点变量类型。请核对 WorkflowInput 模式及工作流开始节点字段类型；"
            "缩小批次无效。"
        ),
    },
    "output_truncated": {
        "label": "远端输出被截断",
        "phase": "response_transport",
        "retry_current_batch": True,
        "smaller_batch_may_help": True,
        "operator_hint": "完整 JSON 或响应流在中途截断；缩小批次可降低输出体积，仍应检查模型输出上限和网关超时。",
    },
    "transport": {
        "label": "远端网络或网关失败",
        "phase": "transport",
        "retry_current_batch": False,
        "smaller_batch_may_help": False,
        "operator_hint": "远端连接、限流或网关失败。应稍后从当前批次续跑；拆成更多请求通常会放大故障。",
    },
    "output_validation": {
        "label": "模型输出未通过结构校验",
        "phase": "validation",
        "retry_current_batch": True,
        "smaller_batch_may_help": True,
        "operator_hint": "模型返回了批次 JSON，但集数、评分或必填结构不完整；缩小批次可能提高结构完整率。",
    },
    "local_runtime": {
        "label": "本地运行或记忆错误",
        "phase": "local_runtime",
        "retry_current_batch": False,
        "smaller_batch_may_help": False,
        "operator_hint": "错误发生在本地持久化、合并或审核记忆处理；应先修复本地错误，缩小远端批次无效。",
    },
    "unknown": {
        "label": "未分类错误",
        "phase": "unknown",
        "retry_current_batch": False,
        "smaller_batch_may_help": False,
        "operator_hint": "当前证据不足以判断缩小批次是否有效，请先查看最近错误详情和请求 ID。",
    },
}


def classify_audit_failure(
    reason: Any,
    *,
    exception_type: str = "",
    client_debug: Any = None,
) -> dict[str, Any]:
    """Classify failures so deterministic contract errors do not trigger costly splits."""
    debug = _safe_client_debug(client_debug)
    http_status = _int(debug.get("http_status"))
    evidence = " ".join(
        value for value in (
            _text(reason),
            _text(debug.get("last_failure_reason")),
            _text(debug.get("response_preview")),
        ) if value
    ).lower()
    exception_name = _text(exception_type)

    if (
        "不完整批次摘要" in evidence
        or (
            "batch_core_judgement" in evidence
            and "reviewed_episode_numbers" in evidence
            and (
                "episode_reviews" not in evidence
                or "缺少字段" in evidence
                or "only" in evidence
            )
        )
    ):
        category = "end_node_summary"
    elif (
        "cannot unmarshal" in evidence
        or "workflowinput of type string" in evidence
        or "尚未配置 api key" in evidence
        or http_status in {400, 401, 403, 404}
    ):
        category = "input_contract"
    elif (
        exception_name == "WorkflowTransientError"
        or http_status in {408, 409, 425, 429, 500, 502, 503, 504}
        or any(token in evidence for token in (
            "connectionreseterror", "connection broken", "连接", "timeout", "timed out",
        ))
    ):
        category = "transport"
    elif (
        "json 在输出中途被截断" in evidence
        or "truncated" in evidence
        or "response ended prematurely" in evidence
        or "chunkedencodingerror" in evidence
    ):
        category = "output_truncated"
    elif any(token in evidence for token in (
        "批次逐集结果不完整", "schema_version", "五维评分", "episode_score",
        "emotional_review", "continuity_review", "心电节点", "boundary_review",
        "next_audit_memory", "ecg_value",
    )):
        category = "output_validation"
    elif any(token in evidence for token in (
        "审核记忆", "无法合并心电图", "运行记录", "持久化", "写入",
    )):
        category = "local_runtime"
    else:
        category = "unknown"

    meta = _AUDIT_FAILURE_CATEGORIES[category]
    return {
        "category": category,
        "label": meta["label"],
        "phase": meta["phase"],
        "retry_current_batch": bool(meta["retry_current_batch"]),
        "smaller_batch_may_help": bool(meta["smaller_batch_may_help"]),
        "operator_hint": meta["operator_hint"],
    }


def build_audit_error_collection(events: Any) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    batch_size_counts: dict[str, int] = {}
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or _text(event.get("event")) != "workflow_attempt_failed":
            continue
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        diagnosis = {
            key: details.get(key)
            for key in (
                "category", "label", "phase", "retry_current_batch",
                "smaller_batch_may_help", "operator_hint",
            )
            if details.get(key) not in (None, "")
        }
        if not diagnosis.get("category"):
            diagnosis = classify_audit_failure(
                details.get("reason"),
                exception_type=_text(details.get("exception_type")),
                client_debug=details.get("client_debug"),
            )
        category = _text(diagnosis.get("category"), "unknown")
        meta = _AUDIT_FAILURE_CATEGORIES.get(category, _AUDIT_FAILURE_CATEGORIES["unknown"])
        start = _int(details.get("batch_start_episode"))
        end = _int(details.get("batch_end_episode"), start)
        batch_size = max(0, end - start + 1) if start > 0 and end >= start else 0
        category_counts[category] = category_counts.get(category, 0) + 1
        if batch_size:
            batch_size_counts[str(batch_size)] = batch_size_counts.get(str(batch_size), 0) + 1
        client_debug = details.get("client_debug") if isinstance(details.get("client_debug"), dict) else {}
        failures.append({
            "event_index": _int(event.get("index")),
            "timestamp": _text(event.get("timestamp")),
            "batch_start_episode": start,
            "batch_end_episode": end,
            "batch_size": batch_size,
            "attempt": _int(details.get("attempt")),
            "exception_type": _text(details.get("exception_type")),
            "category": category,
            "label": _text(diagnosis.get("label"), meta["label"]),
            "phase": _text(diagnosis.get("phase"), meta["phase"]),
            "retry_current_batch": bool(
                diagnosis.get("retry_current_batch", meta["retry_current_batch"])
            ),
            "smaller_batch_may_help": bool(
                diagnosis.get("smaller_batch_may_help", meta["smaller_batch_may_help"])
            ),
            "reason": safe_truncated_preview(details.get("reason"), limit=1600),
            "operator_hint": _text(diagnosis.get("operator_hint"), meta["operator_hint"]),
            "request_id": _text(client_debug.get("request_id")),
            "http_status": _int(client_debug.get("http_status")) or None,
            "response_diagnostics": copy.deepcopy(details.get("response_diagnostics") or {}),
        })

    categories = []
    for category, count in sorted(category_counts.items(), key=lambda item: (-item[1], item[0])):
        meta = _AUDIT_FAILURE_CATEGORIES.get(category, _AUDIT_FAILURE_CATEGORIES["unknown"])
        categories.append({
            "category": category,
            "label": meta["label"],
            "count": count,
            "retry_current_batch": bool(meta["retry_current_batch"]),
            "smaller_batch_may_help": bool(meta["smaller_batch_may_help"]),
            "operator_hint": meta["operator_hint"],
        })
    latest = copy.deepcopy(failures[-1]) if failures else None
    primary = copy.deepcopy(categories[0]) if categories else None
    return {
        "version": 1,
        "total_failures": len(failures),
        "category_counts": categories,
        "batch_size_counts": batch_size_counts,
        "primary_cause": primary,
        "latest_failure": latest,
        "failures": failures[-MAX_COLLECTED_FAILURES:],
    }


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
        self._instance_id = uuid.uuid4().hex
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}

    def _has_live_runner(self, record: dict[str, Any]) -> bool:
        run_id = _text(record.get("run_id"))
        thread = self._threads.get(run_id)
        if thread and thread.is_alive():
            return True
        runner_pid = _int(record.get("runner_pid"))
        if runner_pid <= 0 or runner_pid == os.getpid():
            return False
        return _process_is_alive(runner_pid)

    def _reconcile_interrupted_run(
        self,
        record: dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any]:
        """Turn a persisted active state with no live runner into a resumable failure."""
        previous_status = _text(record.get("status"))
        if previous_status not in ACTIVE_RUN_STATUSES or self._has_live_runner(record):
            return record

        start = _int(record.get("current_batch_start"))
        end = _int(record.get("current_batch_end"), start)
        completed_numbers = sorted({_int(item) for item in record.get("completed_episode_numbers", []) if _int(item) > 0})
        range_text = f"第{start}-{end}集" if start > 0 and end >= start else "当前批次"
        completed_text = (
            f"已完成的第1-{completed_numbers[-1]}集结果已保留。"
            if completed_numbers and completed_numbers == list(range(1, completed_numbers[-1] + 1))
            else f"已完成的{len(completed_numbers)}集结果已保留。"
        )
        error = (
            f"检测进程在{range_text}运行期间被中断，磁盘记录没有对应的活动任务。"
            f"{completed_text}现在可以点击继续检测、删除记录，或重新提交同一剧本。"
        )
        record.update(
            status="failed",
            error=error,
            interrupted_at=_now_iso(),
            updated_at=_now_iso(),
            runner_pid=0,
            runner_instance_id="",
        )
        self._write(record)
        try:
            self._append_debug_event(
                _text(record.get("run_id")),
                "run_interrupted_detected",
                previous_status=previous_status,
                recovery_source=_text(source),
                current_batch_start=start,
                current_batch_end=end,
                completed_episode_numbers=completed_numbers,
                progress_preserved=True,
            )
            record = self._read(_text(record.get("run_id")))
        except Exception:
            pass
        return record

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
            event_timestamp = _now_iso()
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
                    "timestamp": event_timestamp,
                    "event": _text(event, "debug_event"),
                    "details": safe_details,
                }
            )
            document["events"] = events[-MAX_DEBUG_EVENTS:]
            document["next_index"] = next_index + 1
            error_collection = build_audit_error_collection(document["events"])
            document["error_collection"] = error_collection
            temp = path.with_suffix(".debug.tmp")
            temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, path)
            try:
                record = self._read(run_id)
                record.update(
                    debug_file=str(path),
                    debug_event_count=len(document["events"]),
                    debug_last_event=_text(event),
                    last_activity_at=event_timestamp,
                    error_summary={
                        key: copy.deepcopy(error_collection.get(key))
                        for key in (
                            "version", "total_failures", "category_counts",
                            "batch_size_counts", "primary_cause", "latest_failure",
                        )
                    },
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
                existing = self._reconcile_interrupted_run(existing, source="start_run")
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
                    existing.update(
                        status="pending",
                        error="",
                        updated_at=_now_iso(),
                        current_attempt=0,
                        attempt_started_at="",
                        current_activity="pending",
                    )
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
            "current_attempt": 0, "max_attempts": BATCH_MAX_ATTEMPTS,
            "attempt_started_at": "", "last_activity_at": now,
            "current_activity": "pending",
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
            records: list[dict[str, Any]] = []
            for summary in self._all_summaries():
                if _int(summary.get("user_id")) != int(user_id):
                    continue
                if _text(summary.get("status")) in ACTIVE_RUN_STATUSES:
                    try:
                        private = self._read(_text(summary.get("run_id")))
                        private = self._reconcile_interrupted_run(private, source="list_assets")
                        summary = self.public_record(private, include_source=False)
                        summary["user_id"] = _int(private.get("user_id"))
                    except Exception:
                        pass
                records.append(summary)
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
                record.update(
                    status="running",
                    error="",
                    updated_at=_now_iso(),
                    current_activity="starting",
                    runner_pid=os.getpid(),
                    runner_instance_id=self._instance_id,
                    runner_started_at=_now_iso(),
                )
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
                last_failure_diagnosis: dict[str, Any] = classify_audit_failure("")
                batch_payload: dict[str, Any] | None = None
                batch_warnings: list[str] = []
                attempts_used = 0
                for attempt in range(BATCH_MAX_ATTEMPTS):
                    attempts_used = attempt + 1
                    raw: Any = None
                    attempt_variables = dict(variables)
                    if attempt:
                        retry_instruction = (
                            f"这是当前第{chunk['start_episode']}-{chunk['end_episode']}集的第{attempt + 1}次格式重试。"
                            "上一次远端最终输出只返回摘要或结构不完整。你必须先执行这条格式纠错指令，"
                            "然后重新完成分析并返回完整 script_audit_batch_v1 JSON。"
                            "禁止只返回 batch_start_episode、batch_end_episode、total_episodes、"
                            "reviewed_episode_numbers、is_final_batch、batch_core_judgement；"
                            "episode_reviews 必须逐集齐全，且必须包含 emotional_review、"
                            "continuity_review、dimension_scores、ecg_points 与 next_audit_memory。"
                        )
                        retry_memory = compact_workflow_audit_memory(
                            memory,
                            retry_instruction=retry_instruction,
                        )
                        attempt_variables["previous_audit_memory"] = json.dumps(
                            retry_memory, ensure_ascii=False, separators=(",", ":")
                        )
                    transported = build_workflow_inputs("hot_review", attempt_variables)
                    attempt_started_at = _now_iso()
                    with self._lock:
                        record = self._read(run_id)
                        record.update(
                            current_attempt=attempts_used,
                            max_attempts=BATCH_MAX_ATTEMPTS,
                            attempt_started_at=attempt_started_at,
                            last_activity_at=attempt_started_at,
                            current_activity="waiting_remote",
                            updated_at=attempt_started_at,
                        )
                        self._write(record)
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
                            previous_memory=memory,
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
                        client_debug = _safe_client_debug(
                            getattr(self._workflow_client(), "get_last_stage_debug_info", lambda *_: {})
                            ("hot_review")
                        )
                        last_failure_diagnosis = classify_audit_failure(
                            str(exc),
                            exception_type=type(exc).__name__,
                            client_debug=client_debug,
                        )
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
                            client_debug=client_debug,
                            response_diagnostics=(inspect_batch_response(raw) if raw is not None else {}),
                            **last_failure_diagnosis,
                        )
                        if last_failure_diagnosis.get("category") in {"end_node_summary", "output_truncated"} and raw is not None:
                            try:
                                source_episodes = [
                                    episode_by_number[number] for number in chunk["episode_numbers"]
                                ]
                                fallback_payload = build_local_summary_fallback(
                                    raw,
                                    source_episodes,
                                    chunk["episode_numbers"],
                                    record["total_episodes"],
                                    previous_memory=memory,
                                )
                                batch_payload, repaired_warnings = validate_batch_output(
                                    fallback_payload,
                                    chunk["episode_numbers"],
                                    record["total_episodes"],
                                    previous_memory=memory,
                                )
                                remote_problem = (
                                    "仅返回六字段摘要"
                                    if last_failure_diagnosis.get("category") == "end_node_summary"
                                    else "完整JSON在输出中途被截断"
                                )
                                batch_warnings = [
                                    f"腾讯远端本批{remote_problem}；系统已保留可用远端判断，并基于真实剧本正文生成可追溯的本地规则逐集评分、承接检查和心电节点。该兜底结果不等同于完整大模型语义审核。",
                                    *repaired_warnings,
                                ]
                                fallback_event = (
                                    "local_summary_fallback_succeeded"
                                    if last_failure_diagnosis.get("category") == "end_node_summary"
                                    else "local_truncated_fallback_succeeded"
                                )
                                self._append_debug_event(
                                    run_id,
                                    fallback_event,
                                    batch_index=chunk["batch_index"],
                                    batch_start_episode=chunk["start_episode"],
                                    batch_end_episode=chunk["end_episode"],
                                    attempt=attempt + 1,
                                    returned_episode_numbers=chunk["episode_numbers"],
                                    analysis_source="remote_incomplete_plus_local_rule_fallback",
                                    remote_request_id=_text(client_debug.get("request_id")),
                                    progress_preserved=True,
                                )
                                last_error = None
                                break
                            except Exception as fallback_exc:
                                self._append_debug_event(
                                    run_id,
                                    "local_summary_fallback_failed",
                                    batch_index=chunk["batch_index"],
                                    batch_start_episode=chunk["start_episode"],
                                    batch_end_episode=chunk["end_episode"],
                                    attempt=attempt + 1,
                                    exception_type=type(fallback_exc).__name__,
                                    reason=safe_truncated_preview(str(fallback_exc), limit=3000),
                                    traceback=safe_truncated_preview(traceback.format_exc(), limit=8000),
                                )
                        retry_current_batch = bool(
                            last_failure_diagnosis.get("retry_current_batch")
                        )
                        if attempt + 1 < BATCH_MAX_ATTEMPTS and retry_current_batch:
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
                        elif attempt + 1 < BATCH_MAX_ATTEMPTS:
                            self._append_debug_event(
                                run_id,
                                "batch_retry_skipped",
                                batch_index=chunk["batch_index"],
                                batch_start_episode=chunk["start_episode"],
                                batch_end_episode=chunk["end_episode"],
                                attempts_used=attempts_used,
                                category=last_failure_diagnosis.get("category"),
                                label=last_failure_diagnosis.get("label"),
                                operator_hint=last_failure_diagnosis.get("operator_hint"),
                                reason="deterministic_failure",
                                progress_preserved=True,
                            )
                            break
                if last_error or batch_payload is None:
                    current_size = len(chunk["episode_numbers"])
                    smaller_batch_may_help = bool(
                        last_failure_diagnosis.get("smaller_batch_may_help")
                    )
                    if current_size > 1 and smaller_batch_may_help:
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
                            category=last_failure_diagnosis.get("category"),
                            operator_hint=last_failure_diagnosis.get("operator_hint"),
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
                    if current_size > 1:
                        self._append_debug_event(
                            run_id,
                            "batch_adaptive_split_skipped",
                            failed_batch_start=chunk["start_episode"],
                            failed_batch_end=chunk["end_episode"],
                            failed_batch_size=current_size,
                            category=last_failure_diagnosis.get("category"),
                            label=last_failure_diagnosis.get("label"),
                            reason=safe_truncated_preview(str(last_error), limit=2000),
                            operator_hint=last_failure_diagnosis.get("operator_hint"),
                            progress_preserved=True,
                        )
                    reason = _text(last_error, "远端未返回完整批次结果。")
                    split_note = (
                        "错误分类表明缩小批次无效，系统已停止继续拆分，避免重复消耗调用。"
                        if current_size > 1 and not smaller_batch_may_help else ""
                    )
                    operator_hint = _text(last_failure_diagnosis.get("operator_hint"))
                    attempt_note = (
                        f"第{attempts_used}次远端分析失败；"
                        if attempts_used == 1
                        else f"连续{attempts_used}次远端分析失败；"
                    )
                    raise RuntimeError(
                        f"第{chunk['start_episode']}-{chunk['end_episode']}集{attempt_note}此前已完成的"
                        f"{len(completed_numbers)}集结果均已保留，可稍后点击继续检测，从本批次续跑。"
                        f"{split_note}{operator_hint}最后一次错误：{reason}"
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
                        batches=stored_batches, audit_memory=memory,
                        warnings=list(dict.fromkeys([*(record.get("warnings") or []), *batch_warnings])),
                        completed_batches=len(stored_batches), completed_episode_numbers=completed_numbers,
                        current_attempt=0, attempt_started_at="", current_activity="batch_saved",
                        updated_at=_now_iso(),
                    )
                    self._write(record)
                completed_numbers = set(completed_numbers)
            with self._lock:
                record = self._read(run_id)
                audit, merge_warnings = merge_audit_batches(record["script_title"], record["total_episodes"], record["batches"])
                record.update(
                    status="succeeded", audit=audit,
                    warnings=list(dict.fromkeys([*(record.get("warnings") or []), *merge_warnings])),
                    current_batch_start=0, current_batch_end=0, updated_at=_now_iso(), error="",
                    current_attempt=0, attempt_started_at="", current_activity="succeeded",
                    runner_pid=0, runner_instance_id="", runner_finished_at=_now_iso(),
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
                    record.update(
                        status="failed",
                        error=safe_truncated_preview(
                            _text(exc, "心电图批次审核失败。"),
                            limit=2000,
                        ),
                        updated_at=_now_iso(),
                        current_activity="failed",
                        runner_pid=0,
                        runner_instance_id="",
                        runner_finished_at=_now_iso(),
                    )
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
            # Older clients send recover=1 on every poll. Recovery must never
            # silently relaunch a run whose owning process disappeared; expose it
            # as failed so the user can explicitly continue or delete it.
            record = self._reconcile_interrupted_run(record, source="get_run")
        return self.public_record(record)

    def resume_run(self, run_id: str, *, user_id: int) -> dict[str, Any]:
        record = self.get_run(run_id, user_id=user_id)
        if record["status"] == "succeeded":
            return record
        if record["status"] in ACTIVE_RUN_STATUSES:
            return record
        with self._lock:
            private = self._read(run_id)
            private.update(
                status="pending",
                error="",
                updated_at=_now_iso(),
                current_attempt=0,
                attempt_started_at="",
                current_activity="pending",
                runner_pid=0,
                runner_instance_id="",
            )
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
            record = self._reconcile_interrupted_run(record, source="delete_run")
            thread = self._threads.get(run_id)
            if _text(record.get("status")) in ACTIVE_RUN_STATUSES or (thread and thread.is_alive()):
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
                return {
                    "run_id": run_id,
                    "debug_file": str(path),
                    "events": [],
                    "error_collection": build_audit_error_collection([]),
                }
            document = json.loads(path.read_text(encoding="utf-8"))
        events = document.get("events") if isinstance(document, dict) and isinstance(document.get("events"), list) else []
        error_collection = (
            document.get("error_collection")
            if isinstance(document, dict) and isinstance(document.get("error_collection"), dict)
            else build_audit_error_collection(events)
        )
        return {
            "run_id": run_id,
            "debug_file": str(path),
            "events": events,
            "error_collection": error_collection,
        }

    def public_record(self, record: dict[str, Any], *, include_source: bool = True) -> dict[str, Any]:
        total = max(1, _int(record.get("total_episodes"), 1))
        completed = len(record.get("completed_episode_numbers") or [])
        public_keys = [
            "run_id", "script_title", "status", "created_at", "updated_at", "total_episodes",
            "total_batches", "completed_batches", "completed_episode_numbers", "current_batch_start",
            "current_batch_end", "error", "debug_file", "debug_event_count", "debug_last_event",
            "error_summary", "current_attempt", "max_attempts", "attempt_started_at",
            "last_activity_at", "current_activity",
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
