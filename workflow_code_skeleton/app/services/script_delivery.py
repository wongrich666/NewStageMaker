from __future__ import annotations

import re
from typing import Any


HEADING_RE = re.compile(r"^\s*(#{1,6})\s*(.+?)\s*$")
MARKDOWN_RE = re.compile(r"[*_`]+")
INTERNAL_OVERVIEW_MARKERS = (
    "以已锁定世界观与创作合同为准",
    "详见剧本正文",
    "主线推进逻辑",
    "触发事件→主角行动→阻力反应",
    "技术合规性检查",
    "创作执行指令",
    "终审门禁",
)


def _plain(value: Any) -> str:
    text = MARKDOWN_RE.sub("", str(value or ""))
    text = re.sub(r"^\s*[-+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _trim_lines(value: str, limit: int) -> str:
    lines: list[str] = []
    size = 0
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line or line == "---" or line.startswith("SKILL_ROUTING_JSON"):
            continue
        if size + len(line) > limit and lines:
            break
        lines.append(line)
        size += len(line)
    return _plain("\n".join(lines))


def _section(value: str, names: tuple[str, ...], limit: int) -> str:
    lines = str(value or "").splitlines()
    start = None
    level = 7
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if not match:
            continue
        heading = _plain(match.group(2))
        if any(name in heading for name in names):
            start = index + 1
            level = len(match.group(1))
            break
    if start is None:
        return ""
    selected: list[str] = []
    for line in lines[start:]:
        match = HEADING_RE.match(line)
        if match and len(match.group(1)) <= level:
            break
        selected.append(line)
    return _trim_lines("\n".join(selected), limit)


def _heading_name(value: str) -> str:
    heading = _plain(value)
    return re.sub(
        r"^[一二三四五六七八九十百\d]+[、.．]\s*",
        "",
        heading,
    ).strip()


def _named_section(value: str, names: tuple[str, ...], limit: int) -> str:
    """Read a semantic section without matching internal headings by substring."""
    lines = str(value or "").splitlines()
    start = None
    level = 7
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if not match:
            continue
        heading = _heading_name(match.group(2))
        if any(
            heading == name
            or heading.startswith(f"{name}（")
            or heading.startswith(f"{name}(")
            for name in names
        ):
            start = index + 1
            level = len(match.group(1))
            break
    if start is None:
        return ""
    selected: list[str] = []
    for line in lines[start:]:
        match = HEADING_RE.match(line)
        if match and len(match.group(1)) <= level:
            break
        selected.append(line)
    return _trim_lines("\n".join(selected), limit)


def _reader_facing(value: str) -> bool:
    text = _plain(value)
    return bool(text) and not any(marker in text for marker in INTERNAL_OVERVIEW_MARKERS)


def _first_reader_facing(candidates: list[str]) -> str:
    for candidate in candidates:
        if _reader_facing(candidate):
            return candidate
    return ""


def _bold_field(value: str, names: tuple[str, ...], limit: int = 360) -> str:
    name_pattern = "|".join(re.escape(name) for name in names)
    match = re.search(
        rf"(?m)^\s*(?:[-+]\s*)?\*\*(?:{name_pattern})\*\*\s*[：:]\s*(.+)$",
        str(value or ""),
    )
    return _trim_lines(match.group(1), limit) if match else ""


def _episode_blocks(value: str) -> list[tuple[str, str]]:
    lines = str(value or "").splitlines()
    starts: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^\s*#{2,6}\s*第\s*\d+\s*集\s*[：:]\s*(.+?)\s*$", line)
        if match:
            starts.append((index, _plain(match.group(1))))
    blocks: list[tuple[str, str]] = []
    for position, (start, title) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        blocks.append((title, "\n".join(lines[start + 1 : end])))
    return blocks


def _sample_middle(values: list[str], maximum: int = 4) -> list[str]:
    if len(values) <= maximum:
        return values
    indexes = {
        round(index * (len(values) - 1) / (maximum - 1))
        for index in range(maximum)
    }
    return [value for index, value in enumerate(values) if index in indexes]


def _synthesized_synopsis(story: str, contract: str, title: str) -> str:
    blocks = _episode_blocks(story)
    protagonist = ""
    protagonist_section = _named_section(story, ("主角锁定", "主角"), 1_200)
    match = re.search(r"(?m)^\s*\*\*([^*\n（(]+)(?:[（(][^*\n]+)?\*\*\s*$", protagonist_section)
    if match:
        protagonist = match.group(1).strip()

    goal = _first_reader_facing(
        [
            _bold_field(protagonist_section, ("核心欲望", "外在目标")),
            _named_section(contract, ("核心欲望", "主角目标"), 360),
        ]
    )
    first_event = ""
    ending = ""
    if blocks:
        first_event = _bold_field(blocks[0][1], ("触发事件", "开局事件"), 360)
        ending = _bold_field(
            blocks[-1][1],
            ("结局兑现", "最终兑现", "局势变化", "本集结局"),
            420,
        )

    subject = f"{protagonist}的故事" if protagonist else f"《{title.strip('《》')}》"
    sentences = [f"故事围绕{subject}展开。"]
    if first_event:
        sentences.append(first_event.rstrip("。") + "。")
    if goal:
        sentences.append(f"为实现{goal.rstrip('。')}，主角必须持续行动并承担选择带来的代价。")
    if blocks:
        middle_titles = _sample_middle([item[0] for item in blocks[1:-1]])
        if middle_titles:
            sentences.append("剧情将经过" + "、".join(middle_titles) + "等关键转折。")
        final_direction = ending or blocks[-1][0]
        sentences.append(f"最终推进至{final_direction.rstrip('。')}。")
    synopsis = _trim_lines("".join(sentences), 1_100)
    return synopsis if len(synopsis) >= 20 else ""


def _story_background(story: str, contract: str) -> str:
    return _first_reader_facing(
        [
            _named_section(story, ("故事背景", "世界背景", "背景设定"), 900),
            _named_section(story, ("世界观设定", "世界观", "立意与主题"), 900),
            _named_section(contract, ("故事背景", "世界背景", "背景设定"), 900),
            _named_section(contract, ("世界观设定", "世界观", "不可篡改事实"), 900),
        ]
    )


def _character_summaries(value: str, *, maximum: int = 6) -> list[str]:
    lines = str(value or "").splitlines()
    starts: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if not match or len(match.group(1)) != 2:
            continue
        heading = _plain(match.group(2))
        if any(marker in heading for marker in ("心理活动", "落地检查", "检查表")):
            continue
        starts.append((index, re.sub(r"^[一二三四五六七八九十\d、.．\s]+", "", heading)))

    summaries: list[str] = []
    for position, (start, heading) in enumerate(starts[:maximum]):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        block = "\n".join(lines[start + 1 : end])
        label = _section(block, ("标签",), 180)
        goal = _section(block, ("外在目标",), 180)
        need = _section(block, ("隐藏需求", "内在需求"), 160)
        details = [item for item in (label, goal, need) if item]
        if not details:
            details = [_trim_lines(block, 360)]
        detail = "；".join(item.rstrip("。；") for item in details if item)
        if detail:
            summaries.append(f"- **{heading}**：{detail}。")
    return summaries


def build_script_overview(job: dict[str, Any]) -> str:
    request = job.get("request") if isinstance(job.get("request"), dict) else {}
    recovered = (
        job.get("recovered_files")
        if isinstance(job.get("recovered_files"), dict)
        else {}
    )
    contract = str(recovered.get("contract") or "")
    story = str(recovered.get("story") or "")
    characters = str(recovered.get("characters") or "")

    title = str(request.get("project_title") or "未命名剧本").strip()
    basic_items = [
        ("作品名称", title),
        ("创作模式", request.get("mode")),
        ("成片类型", request.get("production_type")),
        ("目标市场", request.get("target_market")),
        ("题材方向", request.get("genre")),
    ]
    if str(request.get("mode") or "") == "续写":
        episode_start = int(request.get("episode_start") or 1)
        episode_end = int(request.get("episode_end") or episode_start)
        basic_items.extend(
            [
                (
                    "本次续写范围",
                    f"第{episode_start}集至第{episode_end}集"
                    f"（{request.get('episodes')}集）",
                ),
                (
                    "全剧当前目标",
                    f"写至第{request.get('series_total_episodes') or episode_end}集",
                ),
            ]
        )
    else:
        basic_items.append(
            ("总集数", f"{request.get('episodes')}集" if request.get("episodes") else "")
        )
    basic = "\n".join(
        f"- **{label}**：{str(value).strip()}"
        for label, value in basic_items
        if str(value or "").strip()
    )

    background = _story_background(story, contract)
    synopsis = _first_reader_facing(
        [
            _named_section(story, ("故事梗概", "剧情梗概", "故事概述", "核心故事"), 1_100),
            _named_section(contract, ("故事梗概", "剧情梗概", "故事概述", "核心故事"), 1_100),
            _named_section(story, ("剧情主线", "核心主线", "主线"), 1_100),
            _synthesized_synopsis(story, contract, title),
        ]
    )

    mainline_parts: list[str] = []
    for label, names in (
        ("主角目标", ("核心欲望",)),
        ("核心阻力", ("核心阻力",)),
        ("情绪承诺", ("情绪承诺",)),
        ("结局方向", ("结局方向",)),
    ):
        content = _section(contract, names, 500)
        if content:
            mainline_parts.append(f"- **{label}**：{content}")

    character_items = _character_summaries(characters)
    sections = [
        "# 剧本大纲",
        "## 基本信息\n" + (basic or f"- **作品名称**：{title}"),
        "## 故事背景\n" + (background or "故事发生在剧本正文所呈现的核心环境中，人物关系与规则随剧情逐步展开。"),
        "## 故事梗概\n" + (synopsis or f"《{title.strip('《》')}》围绕主角的核心目标、阻力与选择展开，并在连续升级的冲突中完成结局兑现。"),
        "## 核心主线\n" + ("\n".join(mainline_parts) or synopsis or "详见剧本正文。"),
        "## 主要人物\n" + (
            "\n".join(character_items)
            if character_items
            else "主要人物信息以剧本正文中的首次有效出场为准。"
        ),
    ]
    return "\n\n".join(sections).strip()


def build_delivery_script(job: dict[str, Any]) -> str:
    final_script = str(job.get("final_script") or "").strip()
    if not final_script:
        return ""
    if re.search(r"(?m)^\s*#{0,6}\s*剧本大纲\s*$", final_script):
        return final_script
    return f"{build_script_overview(job)}\n\n# 剧本正文\n\n{final_script}".strip()
