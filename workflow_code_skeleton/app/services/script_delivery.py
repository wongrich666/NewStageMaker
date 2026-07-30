from __future__ import annotations

import re
from typing import Any


HEADING_RE = re.compile(r"^\s*(#{1,6})\s*(.+?)\s*$")
MARKDOWN_RE = re.compile(r"[*_`]+")


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
        ("成片类型", request.get("production_type")),
        ("目标市场", request.get("target_market")),
        ("题材方向", request.get("genre")),
        ("总集数", f"{request.get('episodes')}集" if request.get("episodes") else ""),
    ]
    basic = "\n".join(
        f"- **{label}**：{str(value).strip()}"
        for label, value in basic_items
        if str(value or "").strip()
    )

    background = _section(contract, ("不可篡改事实", "世界观", "故事背景"), 900)
    if not background:
        background = _section(contract, ("题材与目标观众", "题材定位"), 700)

    synopsis = _section(story, ("主线", "故事梗概"), 1_100)
    if not synopsis:
        synopsis = _section(contract, ("核心欲望",), 800)

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
        "## 故事背景\n" + (background or "以已锁定世界观与创作合同为准。"),
        "## 故事梗概\n" + (synopsis or "详见剧本正文。"),
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
