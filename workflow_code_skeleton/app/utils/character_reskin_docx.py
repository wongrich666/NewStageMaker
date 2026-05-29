from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Cm, Pt
from docx.oxml.ns import qn


FIELD_LABELS = {
    "plot_causality_map": "剧情因果脉络",
    "character_setting": "人物小传",
    "character_design_principle": "人物创作原则",
    "character_creation_principle": "人物创作原则",
    "core_relation_logic": "核心关系逻辑",
    "core_relationship_logic": "核心关系逻辑",
    "characters": "人物详情",
    "character_details": "人物详情",
    "character_name": "人物姓名",
    "name": "姓名",
    "story_role": "故事角色",
    "core_motivation": "核心动机",
    "external_goal": "外在目标",
    "inner_need": "内在需求",
    "deep_fear": "深层恐惧",
    "self_deception": "自我欺骗",
    "dramatic_value": "戏剧价值",
    "personality": "性格",
    "relationships": "人物关系",
    "speech_profile": "说话风格",
    "decision_logic": "决策逻辑",
    "growth_arc": "成长弧线",
    "plot_function": "剧情功能",
}


def build_character_reskin_docx(
    *,
    output_path: str | Path,
    title: str,
    profile_json: Any,
    character_profile: Any,
    script_batches: Any,
    final_output_text: str,
    core_scenes: Any = None,
) -> Path:
    doc = Document()
    _configure_doc(doc)

    _add_title(doc, str(title or "只换人设剧本").strip() or "只换人设剧本")

    profile = _coerce_json(profile_json)
    plot_map = profile.get("plot_causality_map") if isinstance(profile, dict) else None
    character_setting = profile.get("character_setting") if isinstance(profile, dict) else None

    _add_heading(doc, "故事大纲", 1)
    if plot_map not in (None, "", [], {}):
        _render_value(doc, "剧情因果脉络", plot_map, level=2)
    else:
        _add_paragraph(doc, "未能从人设循环变量中解析到 plot_causality_map。")

    _add_heading(doc, "人物小传", 1)
    if character_setting not in (None, "", [], {}):
        _render_character_setting(doc, character_setting)
    elif character_profile not in (None, "", [], {}):
        _render_value(doc, "人物详情", character_profile, level=2)
    else:
        _add_paragraph(doc, "未能从人设循环变量中解析到 character_setting。")

    _add_heading(doc, "核心场景", 1)
    if core_scenes not in (None, "", [], {}):
        _render_value(doc, "核心场景", core_scenes, level=2)
    else:
        _add_paragraph(doc, "暂无核心场景信息。")

    _add_heading(doc, "剧本正文", 1)
    for batch in _normalize_batches(script_batches, final_output_text):
        if batch["label"]:
            _add_heading(doc, batch["label"], 2)
        for paragraph in str(batch["text"] or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if paragraph.strip():
                _add_paragraph(doc, paragraph.strip())
            else:
                doc.add_paragraph()

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


def _configure_doc(doc: Document) -> None:
    section = doc.sections[0]
    section.page_height = Cm(29.7)
    section.page_width = Cm(21.0)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)
    doc.styles["Normal"].font.name = "微软雅黑"
    doc.styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    doc.styles["Normal"].font.size = Pt(11)


def _add_title(doc: Document, text: str) -> None:
    _add_heading(doc, "剧本标题", 1)
    paragraph = doc.add_paragraph()
    run = paragraph.add_run(text)
    run.bold = True
    run.font.size = Pt(16)


def _add_heading(doc: Document, text: str, level: int) -> None:
    heading = doc.add_heading(text, level=level)
    heading.paragraph_format.space_before = Pt(10)
    heading.paragraph_format.space_after = Pt(5)


def _add_paragraph(doc: Document, text: str, *, indent: float = 0) -> None:
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(1)
    paragraph.paragraph_format.space_after = Pt(3)
    if indent:
        paragraph.paragraph_format.left_indent = Cm(indent)
    run = paragraph.add_run(str(text or ""))
    run.font.size = Pt(11)


def _render_character_setting(doc: Document, value: Any) -> None:
    setting = _coerce_json(value)
    if not isinstance(setting, dict):
        _render_value(doc, "人物详情", setting, level=2)
        return
    priority = (
        ("character_design_principle", "人物创作原则"),
        ("character_creation_principle", "人物创作原则"),
        ("core_relation_logic", "核心关系逻辑"),
        ("core_relationship_logic", "核心关系逻辑"),
        ("characters", "人物详情"),
        ("character_details", "人物详情"),
    )
    rendered: set[str] = set()
    for key, label in priority:
        if key in setting and setting[key] not in (None, "", [], {}):
            _render_value(doc, label, setting[key], level=2)
            rendered.add(key)
    for key, item in setting.items():
        if key in rendered or item in (None, "", [], {}):
            continue
        _render_value(doc, _label(key), item, level=2)


def _render_value(doc: Document, label: str, value: Any, *, level: int = 2, indent: float = 0.35) -> None:
    value = _coerce_json(value)
    if isinstance(value, dict):
        _add_heading(doc, label, min(level, 3))
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            _render_value(doc, _label(key), item, level=min(level + 1, 4), indent=indent + 0.2)
        return
    if isinstance(value, list):
        _add_heading(doc, label, min(level, 3))
        for index, item in enumerate(value, start=1):
            item = _coerce_json(item)
            if isinstance(item, dict):
                item_name = str(item.get("character_name") or item.get("name") or f"{label}{index}").strip()
                _render_value(doc, item_name, item, level=min(level + 1, 4), indent=indent + 0.2)
            else:
                _add_paragraph(doc, f"{index}. {_stringify(item)}", indent=indent)
        return
    _add_heading(doc, label, min(level, 3))
    for line in _stringify(value).splitlines() or [""]:
        if line.strip():
            _add_paragraph(doc, line.strip(), indent=indent)


def _normalize_batches(script_batches: Any, final_output_text: str) -> list[dict[str, str]]:
    batches: list[dict[str, str]] = []

    def pick_text(item: Any) -> str:
        item = _coerce_json(item)
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            for key in (
                "text",
                "script_text",
                "scriptText",
                "batchScriptText",
                "batch_script_text",
                "final_output_text",
                "final_script",
                "script_body",
                "scriptBody",
                "juben_zhengwen",
            ):
                value = item.get(key)
                if value not in (None, "", [], {}):
                    return _stringify(value).strip()
            return ""
        return _stringify(item).strip()

    def pick_label(item: Any, fallback: str) -> str:
        item = _coerce_json(item)
        if isinstance(item, dict):
            for key in ("label", "title", "batch_label", "batchLabel"):
                value = item.get(key)
                if value:
                    return str(value).strip()
            start = item.get("start_episode") or item.get("startEpisode")
            end = item.get("end_episode") or item.get("endEpisode")
            if start and end:
                return f"第{start}-{end}集"
            if start:
                return f"第{start}集起"
        return fallback

    if isinstance(script_batches, list):
        for index, item in enumerate(script_batches, start=1):
            text = pick_text(item)
            if text:
                batches.append({
                    "label": pick_label(item, f"正文批次 {index}"),
                    "text": text,
                })

    elif isinstance(script_batches, dict):
        def sort_key(value: Any) -> Any:
            value = str(value)
            return int(value) if value.isdigit() else value

        for index, key in enumerate(sorted(script_batches, key=sort_key), start=1):
            item = script_batches[key]
            text = pick_text(item)
            if text:
                batches.append({
                    "label": pick_label(item, f"第 {key} 集起"),
                    "text": text,
                })

    if not batches and str(final_output_text or "").strip():
        batches.append({"label": "", "text": str(final_output_text).strip()})

    return batches


def _coerce_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except Exception:
        return value


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        return str(value)


def _label(key: Any) -> str:
    text = str(key or "").strip()
    return FIELD_LABELS.get(text, text)
