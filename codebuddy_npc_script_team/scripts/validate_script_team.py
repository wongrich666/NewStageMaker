from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


AUDIT_MARKERS = (
    "最终验证",
    "逐项验证",
    "质量达标",
    "审核报告",
    "修改说明",
    "优点总结",
)
EPISODE_HEADER = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*|__)?\s*"
    r"(?:(?:第\s*(?P<zh>\d{1,3})\s*集)|(?:Episode\s*(?P<en>\d{1,3})))"
    r"(?:\s*[-—:：].*)?(?:\*\*|__)?\s*$"
)
SCENE_HEADER = re.compile(
    r"(?m)^\s*(?:#{1,6}\s+)?(?:[-+*]\s+)?(?:\*\*|__)?\s*"
    r"(?:场景\s*(?:\d+|[一二三四五六七八九十百零〇两]+)?\s*(?=[：:])"
    r"|\d{1,3}\s*[-－—]\s*\d{1,2}(?=\s|[：:])"
    r"|(?:内|外|内外)\s*[·.．]|(?:INT|EXT)\s*[.．])",
    re.IGNORECASE,
)
TITLED_EPISODE_HEADER = re.compile(
    r"(?i)(?:第\s*\d{1,3}\s*集\s*[：:]\s*《[^》\r\n]{2,30}》"
    r"|Episode\s*\d{1,3}\s*[-—:]\s*[^\r\n]{2,60})"
)
FORBIDDEN_PLANNING_FIELD = re.compile(r"(?m)^\s*(?:场景任务|道具)\s*[：:]")
UNATTRIBUTED_DIALOGUE = re.compile(
    r"(?m)^\s*(?:[-*]\s*)?[“\"「『]"
)
UNATTRIBUTED_OS = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:OS|内心OS|内心独白|心理活动)\s*[：:]"
)
ATTRIBUTED_DIALOGUE = re.compile(
    r"(?m)^\s*(?!场景\s*\d+\s*[：:])(?!人物\s*[：:])"
    r"(?![\w\u4e00-\u9fff·]{1,20}OS\s*[：:])"
    r"[\w\u4e00-\u9fff·]{1,20}\s*[：:]\s*\S[^\r\n]*$"
)
PERFORMANCE_CUE_DIALOGUE = re.compile(
    r"(?m)^\s*(?![\w\u4e00-\u9fff·]{1,20}OS\s*[：:])"
    r"[\w\u4e00-\u9fff·]{1,20}\s*[：:]\s*（[^）\r\n]{2,36}）\s*\S[^\r\n]*$"
)
SPEAKER_LINE = re.compile(
    r"^\s*(?!场景\s*\d+\s*[：:])(?!人物\s*[：:])"
    r"[\w\u4e00-\u9fff·]{1,20}(?:OS)?\s*[：:]\s*(?P<content>.+)$"
)


def _scene_contract(request: dict[str, Any]) -> tuple[str, int, int | None]:
    policy = str(request.get("scenes_per_episode") or "1").strip().lower()
    contracts = {
        "1": (1, 1),
        "1-2": (1, 2),
        "2": (2, 2),
        "2-3": (2, 3),
        "flexible": (1, None),
    }
    minimum, maximum = contracts.get(policy, contracts["1"])
    return policy if policy in contracts else "1", minimum, maximum


@dataclass
class GateReport:
    mode: str
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def issue(self, code: str, message: str, *, episode: int | None = None, error: bool = True) -> None:
        item: dict[str, Any] = {"code": code, "message": message}
        if episode is not None:
            item["episode"] = episode
        (self.errors if error else self.warnings).append(item)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "mode": self.mode,
            "ok": not self.errors,
            "errors": self.errors,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }


def _load_request() -> dict[str, Any]:
    raw = os.getenv("scriptRequest") or os.getenv("SCRIPT_REQUEST") or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"scriptRequest 不是有效 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("scriptRequest 必须是 JSON 对象")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"缺少状态文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"状态文件不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("story_state.json 顶层必须是对象")
    return payload


def _split_episodes(script: str) -> list[tuple[int, str]]:
    matches = list(EPISODE_HEADER.finditer(script))
    episodes: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(script)
        episode_number = match.group("zh") or match.group("en")
        episodes.append((int(episode_number), script[match.end():end].strip()))
    return episodes


def _text_size(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _word_units(text: str) -> int:
    """Count CJK characters and Latin words using the user's writing unit."""
    return len(
        re.findall(
            r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
            r"|[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*",
            text,
        )
    )


def _dash_metrics(text: str) -> dict[str, float | int]:
    compact_size = max(1, _text_size(text))
    dash_groups = text.count("——")
    return {
        "dash_groups": dash_groups,
        "dash_groups_per_1000_chars": round(dash_groups * 1000 / compact_size, 2),
    }


def _estimate_screen_seconds(body: str) -> dict[str, int]:
    spoken_units = 0
    dialogue_pause_seconds = 0.0
    action_seconds = 0.0
    scene_count = len(SCENE_HEADER.findall(body))
    for raw_line in body.splitlines():
        line = re.sub(r"^\s*(?:#{1,6}\s+|[-+*]\s+|[△▲]\s*)", "", raw_line).strip()
        line = line.strip("*_ ")
        if not line or EPISODE_HEADER.match(line) or SCENE_HEADER.match(line):
            continue
        if re.match(r"^人物\s*[：:]", line):
            continue
        speaker = SPEAKER_LINE.match(line)
        if speaker:
            content = re.sub(r"^\s*（[^）\r\n]{1,50}）\s*", "", speaker.group("content"))
            spoken_units += _word_units(content)
            dialogue_pause_seconds += 0.15 * len(re.findall(r"[，、；,;]", content))
            dialogue_pause_seconds += 0.35 * len(re.findall(r"[。！？!?]", content))
            dialogue_pause_seconds += 0.6 * content.count("……")
            continue
        units = _word_units(line)
        if not units:
            continue
        visible_beats = max(1, len(re.findall(r"[。！？!?；;]", line)))
        action_seconds += max(1.0, min(8.0, units / 12 + visible_beats * 0.6))
    estimated = spoken_units / 4.0 + dialogue_pause_seconds + action_seconds + scene_count
    return {
        "estimated_seconds": max(1, round(estimated)),
        "spoken_units": spoken_units,
        "action_seconds": round(action_seconds),
    }


def _require_text(
    report: GateReport,
    obj: dict[str, Any],
    key: str,
    *,
    code: str,
    episode: int | None = None,
) -> None:
    if not str(obj.get(key) or "").strip():
        report.issue(code, f"缺少必填字段 {key}", episode=episode)


def _validate_voice(report: GateReport, characters: Any) -> None:
    if not isinstance(characters, list) or not characters:
        report.issue("state.characters.empty", "story_state 缺少主要人物")
        return
    protagonists = 0
    for character in characters:
        if not isinstance(character, dict):
            report.issue("state.character.invalid", "人物记录必须是对象")
            continue
        name = str(character.get("name") or "").strip()
        role = str(character.get("role") or "").strip().lower()
        strict_voice = role not in {"supporting", "minor", "extra", "group"}
        if not name:
            report.issue("state.character.name", "人物缺少姓名")
        if role == "protagonist":
            protagonists += 1
        recipe = character.get("voice_recipe")
        if not isinstance(recipe, dict):
            report.issue(
                "state.voice.missing",
                f"{name or '未命名人物'}缺少声音配方",
                error=strict_voice,
            )
            continue
        for key in ("sentence_length", "evasion_style", "pressure_pattern", "unspoken_truth"):
            if not str(recipe.get(key) or "").strip():
                report.issue(
                    "state.voice.field",
                    f"{name or '未命名人物'}声音配方缺少 {key}",
                    error=strict_voice,
                )
        samples = recipe.get("samples")
        if not isinstance(samples, list) or len([item for item in samples if str(item).strip()]) < 3:
            report.issue(
                "state.voice.samples",
                f"{name or '未命名人物'}应提供三句声音样本",
                error=strict_voice,
            )
        if not isinstance(recipe.get("forbidden_phrases"), list):
            report.issue(
                "state.voice.forbidden",
                f"{name or '未命名人物'}缺少禁用措辞数组",
                error=strict_voice,
            )
    if protagonists < 1:
        report.issue("state.protagonist.missing", "story_state 未标记主角")


def _validate_state_episodes(
    report: GateReport,
    state_episodes: Any,
    expected_count: int,
    *,
    episode_start: int,
    minimum_scenes: int,
    maximum_scenes: int | None,
    strict: bool,
) -> None:
    if not isinstance(state_episodes, list):
        report.issue("state.episodes.invalid", "story_state.episodes 必须是数组")
        return
    numbers = [item.get("episode") for item in state_episodes if isinstance(item, dict)]
    expected_numbers = list(range(episode_start, episode_start + expected_count))
    if numbers != expected_numbers:
        report.issue(
            "state.episodes.sequence",
            f"状态集号应为 {expected_numbers}，实际为 {numbers}",
        )
    for item in state_episodes:
        if not isinstance(item, dict):
            report.issue("state.episode.invalid", "逐集状态必须是对象")
            continue
        episode = item.get("episode")
        episode_no = episode if isinstance(episode, int) else None
        _require_text(report, item, "opening_action", code="state.opening_action", episode=episode_no)
        _require_text(report, item, "closing_action", code="state.closing_action", episode=episode_no)
        scenes = item.get("core_scenes")
        if not isinstance(scenes, list) or not scenes:
            report.issue("state.scenes.empty", "缺少核心场景", episode=episode_no)
        elif len(scenes) < minimum_scenes or (
            maximum_scenes is not None and len(scenes) > maximum_scenes
        ):
            expected = (
                f"{minimum_scenes}个"
                if maximum_scenes == minimum_scenes
                else f"{minimum_scenes}至{maximum_scenes}个"
            )
            report.issue(
                "state.scenes.contract",
                f"核心场景应为{expected}，实际为{len(scenes)}个",
                episode=episode_no,
                error=strict,
            )
        states = item.get("character_states")
        if not isinstance(states, list) or not states:
            report.issue("state.character_states.empty", "缺少人物集末状态", episode=episode_no)
        else:
            for character_state in states:
                if not isinstance(character_state, dict):
                    report.issue("state.character_state.invalid", "人物状态必须是对象", episode=episode_no)
                    continue
                for key in (
                    "name",
                    "location",
                    "knowledge",
                    "injuries",
                    "clothing",
                    "held_props",
                    "relationships",
                    "unfinished_actions",
                ):
                    if key not in character_state:
                        report.issue(
                            "state.character_state.field",
                            f"人物状态缺少 {key}",
                            episode=episode_no,
                        )
        if episode_no and episode_no > 1:
            bridge = item.get("continuity_bridge")
            if not isinstance(bridge, dict):
                report.issue("state.bridge.missing", "缺少与上一集的承接桥", episode=episode_no)
            else:
                if bridge.get("previous_episode") != episode_no - 1:
                    report.issue("state.bridge.previous", "承接桥上一集编号错误", episode=episode_no)
                for key in ("from_action", "to_action", "reason"):
                    _require_text(report, bridge, key, code="state.bridge.field", episode=episode_no)


def validate(script: str, state: dict[str, Any], request: dict[str, Any], *, mode: str) -> GateReport:
    report = GateReport(mode=mode)
    expected_count = max(1, int(request.get("episodes") or 1))
    episode_start = max(1, int(request.get("episode_start") or 1))
    expected_numbers = list(range(episode_start, episode_start + expected_count))
    target_words = max(100, int(request.get("episode_word_count") or 800))
    target_seconds = max(15, int(request.get("episode_duration_seconds") or 90))
    scene_policy, minimum_scenes, maximum_scenes = _scene_contract(request)
    episodes = _split_episodes(script)
    numbers = [number for number, _ in episodes]
    report.metrics.update(
        {
            "expected_episode_count": expected_count,
            "actual_episode_count": len(episodes),
            "minimum_words_per_episode": target_words,
            "target_seconds_per_episode": target_seconds,
            "target_total_seconds": target_seconds * expected_count,
            "scenes_per_episode": scene_policy,
            "script_chars": _text_size(script),
        }
    )

    if any(marker in script for marker in AUDIT_MARKERS) or re.search(r"\|\s*状态\s*\|", script):
        report.issue("script.audit_report", "最终交付疑似审核报告，不是逐集剧本正文")
    if numbers != expected_numbers:
        report.issue(
            "script.episodes.sequence",
            f"剧本集号应为 {expected_numbers}，实际为 {numbers}",
        )
    header_matches = list(EPISODE_HEADER.finditer(script))
    for index, match in enumerate(header_matches):
        if not TITLED_EPISODE_HEADER.search(match.group(0)):
            episode_number = match.group("zh") or match.group("en")
            report.issue(
                "script.episode.title_missing",
                "每集必须使用“第N集：《本集独有标题》”格式",
                episode=int(episode_number),
            )
    if FORBIDDEN_PLANNING_FIELD.search(script):
        report.issue(
            "script.planning_fields.present",
            "正文不得输出“场景任务”或独立“道具”清单",
        )
    episode_metrics: list[dict[str, Any]] = []
    for episode_no, body in episodes:
        chars = _text_size(body)
        size = _word_units(body)
        scene_count = len(SCENE_HEADER.findall(body))
        dash_metrics = _dash_metrics(body)
        dialogue_count = len(ATTRIBUTED_DIALOGUE.findall(body))
        performance_cue_count = len(PERFORMANCE_CUE_DIALOGUE.findall(body))
        timing = _estimate_screen_seconds(body)
        episode_metrics.append(
            {
                "episode": episode_no,
                "word_units": size,
                "chars": chars,
                "scene_headers": scene_count,
                "dialogue_lines": dialogue_count,
                "performance_cue_dialogues": performance_cue_count,
                **timing,
                **dash_metrics,
            }
        )
        if size < target_words:
            report.issue(
                "script.episode.too_short",
                f"正文 {size} 字，低于前端设定的最低字数 {target_words}",
                episode=episode_no,
            )
        if not body:
            report.issue("script.episode.empty", "该集没有正文", episode=episode_no)
        if UNATTRIBUTED_DIALOGUE.search(body):
            report.issue(
                "script.dialogue.speaker_missing",
                "检测到没有人物名前缀的对白；必须使用“人物名：台词”",
                episode=episode_no,
            )
        if UNATTRIBUTED_OS.search(body):
            report.issue(
                "script.os.speaker_missing",
                "心理活动缺少人物归属；必须使用“人物名OS：心理活动”",
                episode=episode_no,
            )
        if dialogue_count and performance_cue_count < 1:
            report.issue(
                "script.dialogue.performance_cue_missing",
                "该集关键对白缺少“人物名：（语气/情绪，眉眼神情）台词”表演提示",
                episode=episode_no,
                error=mode == "strict",
            )
        if scene_count < 1:
            report.issue(
                "script.scene_headers.missing",
                "该集缺少明确场景标题；必须标注地点、日夜和内外",
                episode=episode_no,
            )
        if scene_count < minimum_scenes or (
            maximum_scenes is not None and scene_count > maximum_scenes
        ):
            expected = (
                f"{minimum_scenes}个"
                if maximum_scenes == minimum_scenes
                else f"{minimum_scenes}至{maximum_scenes}个"
            )
            report.issue(
                "script.scene_headers.contract",
                f"前端场景设置要求每集{expected}场，检测到{scene_count}场",
                episode=episode_no,
                error=mode == "strict",
            )
        if dash_metrics["dash_groups"] >= 4 and dash_metrics["dash_groups_per_1000_chars"] > 6:
            report.issue(
                "script.punctuation.dash_overuse",
                (
                    f"破折号密度为每千字 {dash_metrics['dash_groups_per_1000_chars']} 组；"
                    "请将普通停顿、陈述和动作衔接改用逗号、句号、问号、感叹号或省略号"
                ),
                episode=episode_no,
                error=False,
            )
        duration_ratio = timing["estimated_seconds"] / target_seconds
        if duration_ratio < 0.85 or duration_ratio > 1.15:
            report.issue(
                "script.episode.duration_deviation",
                (
                    f"预计画面时长约 {timing['estimated_seconds']} 秒，"
                    f"前端目标为 {target_seconds} 秒；请通过有效对白、反应、动作和镜头节拍调整"
                ),
                episode=episode_no,
                error=False,
            )
    report.metrics["episodes"] = episode_metrics

    if state.get("schema_version") != "1.0":
        report.issue("state.schema_version", "story_state.schema_version 必须为 1.0")
    project = state.get("project")
    if not isinstance(project, dict):
        report.issue("state.project.invalid", "story_state.project 必须是对象")
    else:
        if project.get("episode_count") != expected_count:
            report.issue("state.project.episode_count", "状态中的总集数与用户要求不一致")
        _require_text(report, project, "protagonist", code="state.project.protagonist")
    _validate_voice(report, state.get("characters"))
    _validate_state_episodes(
        report,
        state.get("episodes"),
        expected_count,
        episode_start=episode_start,
        minimum_scenes=minimum_scenes,
        maximum_scenes=maximum_scenes,
        strict=mode == "strict",
    )
    if not isinstance(state.get("props"), list):
        report.issue("state.props.invalid", "story_state.props 必须是数组")
    if not isinstance(state.get("open_threads"), list):
        report.issue("state.open_threads.invalid", "story_state.open_threads 必须是数组")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--mode", choices=("soft", "strict"), default="strict")
    args = parser.parse_args()

    try:
        request = _load_request()
        script = args.script.read_text(encoding="utf-8")
        state = _read_json(args.state)
        report = validate(script, state, request, mode=args.mode)
    except (OSError, ValueError, TypeError) as exc:
        report = GateReport(mode=args.mode)
        report.issue("gate.input", str(exc))

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False), flush=True)
    return 1 if args.mode == "strict" and report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
