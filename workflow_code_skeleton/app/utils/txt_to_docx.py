"""
txt_to_docx.py
将包含 JSON 块的 txt 剧本文件解析并生成结构化 Word 文档。

文件结构支持：
  - 纯文本（标题、故事梗概等）
  - ```json ... ``` 代码块（人物小传、场景设定等 JSON 数据）
  - 剧本正文（带场景标记的对白）

用法：
  python txt_to_docx.py <input.txt> <output.docx>
  或直接调用 convert(input_path, output_path)
"""

import re
import json
import logging
import sys
from pathlib import Path
from typing import Any
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

logger = logging.getLogger(__name__)

PLAIN_SECTION_HEADINGS = (
    "故事梗概",
    "世界观设定",
    "人物小传",
    "人物服饰说明",
    "核心场景",
    "分集计划",
    "剧本正文",
)


# ─────────────────────────── 样式辅助 ───────────────────────────

def set_run_color(run, hex_color: str):
    """设置文字颜色，hex_color 如 '2E75B6'"""
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    run.font.color.rgb = RGBColor(r, g, b)


def add_heading(doc: Document, text: str, level: int = 1):
    """添加标题段落"""
    p = doc.add_heading(text, level=level)
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(6)
    return p


def add_para(doc: Document, text: str, bold=False, italic=False,
             size=11, color=None, indent=0):
    """添加普通段落"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(4)
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    run = p.add_run(text)
    run.bold = bold
    run.italic = italic
    run.font.size = Pt(size)
    if color:
        set_run_color(run, color)
    return p


def add_divider(doc: Document):
    """添加分隔线"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '6')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), 'AAAAAA')
    pBdr.append(bottom)
    pPr.append(pBdr)


def add_kv(doc: Document, key: str, value: str):
    """添加键值对段落"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.left_indent = Cm(0.5)
    run_k = p.add_run(f"{key}：")
    run_k.bold = True
    run_k.font.size = Pt(10)
    # 去除 Markdown 粗体标记
    clean_val = re.sub(r'\*\*(.+?)\*\*', r'\1', str(value))
    run_v = p.add_run(clean_val)
    run_v.font.size = Pt(10)


def safe_get(obj: Any, key: str, default=None):
    """仅在 dict 上安全读取字段。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


def _json_fallback(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        return str(value)


def normalize_list(value: Any, *, _depth: int = 0) -> list[str]:
    """把任意值尽量转换成可读字符串列表。"""
    if _depth > 5:
        text = _json_fallback(value).strip()
        return [text] if text else []
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, dict):
        preferred_items: list[str] = []
        for key in ("name", "value", "description", "text", "label", "title"):
            text = normalize_text(safe_get(value, key), _depth=_depth + 1)
            if text:
                preferred_items.append(text)
        if preferred_items:
            return preferred_items
        items: list[str] = []
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            child_items = normalize_list(item, _depth=_depth + 1)
            if not child_items:
                child_text = normalize_text(item, _depth=_depth + 1)
                if child_text:
                    items.append(f"{key}：{child_text}")
                continue
            if len(child_items) == 1:
                items.append(f"{key}：{child_items[0]}")
            else:
                items.append(f"{key}：")
                items.extend(f"- {entry}" for entry in child_items)
        return items or [item for item in [_json_fallback(value).strip()] if item]
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            child_items = normalize_list(item, _depth=_depth + 1)
            if child_items:
                items.extend(child_items)
                continue
            child_text = normalize_text(item, _depth=_depth + 1)
            if child_text:
                items.append(child_text)
        return items
    text = str(value).strip()
    return [text] if text else []


def normalize_text(value: Any, *, _depth: int = 0) -> str:
    """把任意值尽量转换成单段可读文本。"""
    if _depth > 5:
        return _json_fallback(value).strip()
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, tuple, set, dict)):
        items = normalize_list(value, _depth=_depth + 1)
        if items:
            return "\n".join(item for item in items if item)
        return _json_fallback(value).strip()
    return str(value).strip()


def split_plain_sections(text: str) -> tuple[str, dict[str, str]]:
    """按导出用的一级中文标题切分纯文本章节，兼容新导出格式。"""
    source = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = source.split("\n")
    title = ""
    index = 0
    while index < len(lines):
        line = str(lines[index] or "").strip()
        if line:
            title = line
            index += 1
            break
        index += 1

    sections: dict[str, list[str]] = {}
    current_heading = ""
    buffer: list[str] = []
    known = set(PLAIN_SECTION_HEADINGS)
    for raw_line in lines[index:]:
        line = str(raw_line or "")
        stripped = line.strip()
        if stripped in known:
            if current_heading:
                sections[current_heading] = buffer[:]
            current_heading = stripped
            buffer = []
            continue
        if current_heading:
            buffer.append(line)
    if current_heading:
        sections[current_heading] = buffer[:]

    return title, {
        key: "\n".join(value).strip()
        for key, value in sections.items()
        if "\n".join(value).strip()
    }


def _section_is_code_fence(text: str) -> bool:
    content = str(text or "").strip()
    return content.startswith("```json") or content.startswith("```")


def render_plain_section(doc: Document, title: str, text: Any):
    content = normalize_text(text)
    if not content:
        return
    add_heading(doc, title, level=1)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    if not paragraphs:
        paragraphs = [line.strip() for line in str(content).splitlines() if line.strip()]
    for paragraph in paragraphs:
        add_para(doc, paragraph)
    add_divider(doc)


def render_field(doc: Document, label: str, value: Any):
    """按字段类型安全渲染键值、列表或复杂对象。"""
    items = normalize_list(value)
    text = normalize_text(value)
    if not items and not text:
        return
    if len(items) <= 1:
        add_kv(doc, label, items[0] if items else text)
        return
    add_para(doc, label, bold=True, size=10, indent=0.5)
    for item in items:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(1)
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.left_indent = Cm(1.0)
        run = p.add_run(f"• {item}")
        run.font.size = Pt(10)


def _extract_script_text(value: Any, *, _depth: int = 0) -> str:
    """从任意正文载体中递归提取可读文本。"""
    if _depth > 6:
        return normalize_text(value)
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in (
            "final_script",
            "script",
            "content",
            "text",
            "body",
            "dialogue",
            "dialogues",
        ):
            text = _extract_script_text(safe_get(value, key), _depth=_depth + 1)
            if text:
                return text
        parts = [
            _extract_script_text(item, _depth=_depth + 1)
            for item in value.values()
        ]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, (list, tuple, set)):
        parts = [_extract_script_text(item, _depth=_depth + 1) for item in value]
        return "\n".join(part for part in parts if part).strip()
    return normalize_text(value)


# ─────────────────────────── 解析 txt ───────────────────────────

def fix_json_block(raw: str) -> str:
    """
    修复文件中常见的非标准 JSON 写法：

    1. 值以 ** 开头（Markdown 粗体替代了开头引号）
       "key": **文字...  →  "key": "文字...
    2. 值以中文左引号 " (U+201C) 开头
       "key": "文字  →  "key": "文字
    3. 行内剩余 ** 粗体标记（在字符串内部）→ 直接去除
    4. 字符串内部的中文弯引号 " " → 转义为 \"
    5. 行尾多余反斜杠：...\",  或  ...\"  →  ...",  或  ..."
    """
    lines = raw.split('\n')
    result = []
    for line in lines:
        # 修复1：值以 ** 开头 —— 添加缺失的开引号，移除 **
        line = re.sub(r'(:\s*)\*\*', r'\1"', line)

        # 修复2：值以中文左引号开头
        line = re.sub(r'(:\s*)\u201c', r'\1"', line)

        # 修复3：去除字符串内部剩余的 ** 标记
        line = line.replace('**', '')

        # 修复4：转义字符串内部的中文弯引号
        line = line.replace('\u201c', '\\"').replace('\u201d', '\\"')

        # 修复5：行尾多余反斜杠  ...\"  或  ...\",  →  ..."  或  ...",
        line = re.sub(r'\\"(\s*,?\s*)$', r'"\1', line)

        result.append(line)
    return '\n'.join(result)


def parse_txt(filepath: str) -> dict:
    """
    解析 txt 文件，返回结构化内容：
    {
      "title": str,
      "synopsis": str,
      "json_blocks": [{"label": str, "data": dict}, ...],
      "script": str
    }
    """
    text = Path(filepath).read_text(encoding='utf-8')
    title, plain_sections = split_plain_sections(text)

    # 提取所有 ```json ... ``` 块（含位置信息）
    json_pattern = re.compile(r'```json\s*(.*?)```', re.DOTALL)
    json_matches = list(json_pattern.finditer(text))

    # 移除 JSON 块后的纯文本部分
    plain_text = json_pattern.sub('<<<JSON_BLOCK>>>', text)
    plain_parts = plain_text.split('<<<JSON_BLOCK>>>')

    # 兼容旧格式：第一个纯文本块包含标题和故事梗概
    header_block = plain_parts[0].strip() if plain_parts else ""
    lines = header_block.splitlines()
    legacy_title = lines[0].strip() if lines else ""
    title = title or legacy_title
    synopsis_lines = []
    in_synopsis = False
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "故事梗概":
            in_synopsis = True
            continue
        if in_synopsis and stripped and any(
            stripped.startswith(h) for h in ["人物小传", "核心场景", "剧本正文"]
        ):
            break
        if in_synopsis:
            synopsis_lines.append(line)
    synopsis = plain_sections.get("故事梗概") or "\n".join(synopsis_lines).strip()

    # 找剧本正文（最后一个 JSON 块之后的文本）
    script_text = plain_sections.get("剧本正文", "")
    if not script_text and len(plain_parts) > len(json_matches):
        last_part = plain_parts[-1]
        script_match = re.search(r'剧本正文(.*)', last_part, re.DOTALL)
        if script_match:
            script_text = script_match.group(0).strip()

    # 解析每个 JSON 块并打标签
    json_blocks = []
    # 从 JSON 块前面的文本推断 label
    for i, m in enumerate(json_matches):
        # 取该 JSON 块前面那段纯文本的最后非空行作为 label
        label = ""
        if i < len(plain_parts):
            prev_text = plain_parts[i].strip()
            prev_lines = [l.strip() for l in prev_text.splitlines() if l.strip()]
            if prev_lines:
                label = prev_lines[-1]

        raw_json = m.group(1).strip()
        # 应用全面修复（中文引号、** 标记、行尾反斜杠等）
        raw_json = fix_json_block(raw_json)
        # 尝试解析
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as e:
            data = {"_parse_error": str(e), "_raw": raw_json[:300]}

        json_blocks.append({"label": label, "data": data})

    return {
        "title": title,
        "synopsis": synopsis,
        "sections": plain_sections,
        "json_blocks": json_blocks,
        "script": script_text,
    }


# ─────────────────────── 渲染人物小传 ───────────────────────────

def render_character(doc: Document, char: Any):
    """渲染单个人物信息"""
    char_dict = char if isinstance(char, dict) else {}
    name = normalize_text(
        safe_get(char_dict, "character_name")
        or safe_get(char_dict, "name")
    )
    if not name:
        name = "角色信息" if not isinstance(char, dict) else "未知角色"
    add_heading(doc, f"👤 {name}", level=2)

    if not isinstance(char, dict):
        fallback_text = normalize_text(char)
        render_field(doc, "人物信息", fallback_text or "未提供")
        return

    simple_fields = {
        "故事角色": "story_role",
        "核心动机": "core_motivation",
        "外在目标": "external_goal",
        "内在需求": "inner_need",
        "深层恐惧": "deep_fear",
        "自我欺骗": "self_deception",
        "戏剧价值": "dramatic_value",
        "背景": "background",
        "动机": "motivation",
    }
    for label, key in simple_fields.items():
        render_field(doc, label, safe_get(char_dict, key))

    # 性格
    personality = safe_get(char_dict, "personality")
    if personality not in (None, "", [], {}):
        if isinstance(personality, dict):
            add_para(doc, "性格特征", bold=True, size=10, indent=0.5)
            render_field(doc, "特质", safe_get(personality, "traits"))
            render_field(doc, "外在印象", safe_get(personality, "surface_impression"))
            render_field(doc, "内在矛盾", safe_get(personality, "inner_contradiction"))
            for key, value in personality.items():
                if key in {"traits", "surface_impression", "inner_contradiction"}:
                    continue
                render_field(doc, key, value)
        else:
            render_field(doc, "性格特征", personality)

    # 家庭背景
    family = safe_get(char_dict, "family")
    if family not in (None, "", [], {}):
        if isinstance(family, dict):
            add_para(doc, "家庭背景", bold=True, size=10, indent=0.5)
            render_field(doc, "家世", safe_get(family, "family_background"))
            render_field(doc, "成长经历", safe_get(family, "upbringing"))
            render_field(doc, "关键影响", safe_get(family, "key_family_influence"))
            for key, value in family.items():
                if key in {"family_background", "upbringing", "key_family_influence"}:
                    continue
                render_field(doc, key, value)
        else:
            render_field(doc, "家庭背景", family)

    # 外貌
    appearance = safe_get(char_dict, "appearance")
    if appearance not in (None, "", [], {}):
        if isinstance(appearance, dict):
            add_para(doc, "外貌描述", bold=True, size=10, indent=0.5)
            render_field(doc, "整体形象", safe_get(appearance, "overall_look"))
            render_field(doc, "外貌效果", safe_get(appearance, "external_impression_effect"))
            render_field(doc, "标志性特征", safe_get(appearance, "recognizable_features"))
            for key, value in appearance.items():
                if key in {"overall_look", "external_impression_effect", "recognizable_features"}:
                    continue
                render_field(doc, key, value)
        else:
            render_field(doc, "外貌描述", appearance)

    # 行为模式
    behavior = safe_get(char_dict, "behavior")
    if behavior not in (None, "", [], {}):
        if isinstance(behavior, dict):
            add_para(doc, "行为模式", bold=True, size=10, indent=0.5)
            render_field(doc, "情感反应", safe_get(behavior, "emotional_response_pattern"))
            render_field(doc, "社交风格", safe_get(behavior, "social_interaction_style"))
            for key, value in behavior.items():
                if key in {"emotional_response_pattern", "social_interaction_style"}:
                    continue
                render_field(doc, key, value)
        else:
            render_field(doc, "行为模式", behavior)

    for label, key in (
        ("人物关系", "relationships"),
        ("说话风格", "speech_profile"),
        ("决策逻辑", "decision_logic"),
        ("关系模式", "relation_modes"),
        ("可演证据", "actable_evidence"),
        ("成长弧线", "growth_arc"),
        ("剧情功能", "plot_function"),
    ):
        render_field(doc, label, safe_get(char_dict, key))


# ─────────────────────── 渲染核心场景 ───────────────────────────

def render_scene(doc: Document, scene: Any):
    """渲染单个场景信息"""
    scene_dict = scene if isinstance(scene, dict) else {}
    name = normalize_text(
        safe_get(scene_dict, "scene_name")
        or safe_get(scene_dict, "name")
    ) or ("场景说明" if not isinstance(scene, dict) else "未知场景")
    s_type = normalize_text(safe_get(scene_dict, "scene_type"))
    add_heading(doc, f"🎬 {name}", level=2)
    if s_type:
        add_para(doc, s_type, italic=True, size=10, color="888888")

    if not isinstance(scene, dict):
        render_field(doc, "场景说明", scene)
        return

    field_map = [
        ("story_function", "场景功能"),
        ("environment_description", "环境描述"),
        ("atmosphere_description", "氛围描述"),
        ("character_interaction_effect", "人物互动效果"),
        ("worldview_support", "世界观支撑"),
    ]
    for key, label in field_map:
        render_field(doc, label, safe_get(scene_dict, key))

    render_field(doc, "视觉元素", safe_get(scene_dict, "visual_elements"))
    render_field(doc, "冲突潜力", safe_get(scene_dict, "conflict_potential"))


# ─────────────────────── 渲染剧本正文 ───────────────────────────

def render_script(doc: Document, script_text: Any):
    """渲染剧本正文"""
    script_body = _extract_script_text(script_text)
    if not script_body.strip():
        return

    heading_added = False
    stripped_body = script_body.lstrip()
    if stripped_body.startswith("剧本正文"):
        normalized_lines = stripped_body.splitlines()
        if normalized_lines and normalized_lines[0].strip() == "剧本正文":
            script_body = "\n".join(normalized_lines[1:]).lstrip()
    add_heading(doc, "剧本正文", level=1)
    heading_added = True

    lines = script_body.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            doc.add_paragraph()
            continue

        # 集标题（支持 Markdown 标题前缀）
        if re.match(r'^[#>\-\s]*第[0-9０-９一二三四五六七八九十百千万两零〇]+集[:：]', stripped):
            clean_heading = re.sub(r'^[#>\-\s]+', '', stripped).strip()
            add_heading(doc, clean_heading, level=2)

        # 场景标记（场景X-Y：...）
        elif re.match(r'^场景\d+', stripped):
            p = doc.add_paragraph()
            run = p.add_run(stripped)
            run.bold = True
            run.font.size = Pt(11)
            set_run_color(run, "2E75B6")

        # 舞台指示（▲ 开头）
        elif stripped.startswith('▲'):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.5)
            run = p.add_run(stripped)
            run.italic = True
            run.font.size = Pt(10)
            set_run_color(run, "666666")

        # 系统/角色对白（含冒号的台词行）
        elif re.match(r'^[\w\u4e00-\u9fff]+（', stripped) or \
             re.match(r'^[\w\u4e00-\u9fff]+：', stripped):
            # 分离角色名与台词
            m = re.match(r'^([\w\u4e00-\u9fff]+(?:（[^）]*）)?)[：:](.+)', stripped)
            if m:
                p = doc.add_paragraph()
                name_run = p.add_run(m.group(1) + "：")
                name_run.bold = True
                name_run.font.size = Pt(11)
                set_run_color(name_run, "1F4E79")
                dialogue_run = p.add_run(m.group(2).strip())
                dialogue_run.font.size = Pt(11)
            else:
                add_para(doc, stripped)

        # 剧本正文标题本身
        elif stripped == "剧本正文":
            if not heading_added:
                add_heading(doc, stripped, level=1)
                heading_added = True

        # 普通段落
        else:
            add_para(doc, stripped)


# ─────────────────────── 主转换函数 ───────────────────────────

def convert(input_path: str, output_path: str):
    """
    主方法：将含 JSON 块的 txt 剧本文件转换为 Word 文档。

    Args:
        input_path: 输入 txt 文件路径
        output_path: 输出 docx 文件路径
    """
    # 1. 解析 txt
    parsed = parse_txt(input_path)

    # 2. 创建 Word 文档
    doc = Document()

    # 页面设置（A4）
    section = doc.sections[0]
    section.page_height = Cm(29.7)
    section.page_width = Cm(21.0)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)

    # 默认字体
    doc.styles['Normal'].font.name = '微软雅黑'

    # 2. 设置中文字体名称 (关键步骤)
    doc.styles['Normal']._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')


    doc.styles['Normal'].font.size = Pt(11)

    # ── 封面标题 ──
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_para.paragraph_format.space_before = Pt(40)
    title_para.paragraph_format.space_after = Pt(20)
    title_run = title_para.add_run(parsed["title"])
    title_run.bold = True
    title_run.font.size = Pt(20)
    set_run_color(title_run, "1F4E79")

    sections = parsed.get("sections") if isinstance(parsed.get("sections"), dict) else {}

    # ── 新版纯文本章节优先 ──
    rendered_character_section = False
    rendered_scene_section = False
    for heading in ("故事梗概", "世界观设定", "人物小传", "人物服饰说明", "核心场景", "分集计划"):
        section_text = sections.get(heading)
        if not section_text:
            continue
        if heading == "人物小传" and _section_is_code_fence(section_text):
            continue
        if heading == "核心场景" and _section_is_code_fence(section_text):
            continue
        render_plain_section(doc, heading, section_text)
        if heading == "人物小传":
            rendered_character_section = True
        if heading == "核心场景":
            rendered_scene_section = True

    # ── 兼容旧版故事梗概 ──
    if not sections.get("故事梗概") and parsed["synopsis"]:
        render_plain_section(doc, "故事梗概", parsed["synopsis"])

    # ── JSON 块渲染 ──
    for block in parsed["json_blocks"]:
        label = block["label"]
        data = block["data"]

        if isinstance(data, dict) and "_parse_error" in data:
            add_heading(doc, label or "数据块", level=1)
            add_para(doc, f"⚠️ JSON 解析失败：{data['_parse_error']}", color="CC0000")
            continue

        # 人物小传
        if isinstance(data, dict) and "character_setting" in data and not rendered_character_section:
            add_heading(doc, "人物小传", level=1)
            cs = data["character_setting"]
            render_field(doc, "角色设计原则", safe_get(cs, "character_design_principle") if isinstance(cs, dict) else None)
            render_field(doc, "核心关系逻辑", safe_get(cs, "core_relation_logic") if isinstance(cs, dict) else None)
            doc.add_paragraph()
            characters = safe_get(cs, "characters", []) if isinstance(cs, dict) else cs
            if isinstance(characters, list):
                for char in characters:
                    try:
                        render_character(doc, char)
                    except Exception as exc:
                        logger.warning("render_character failed, fallback to plain text: %s", exc)
                        render_character(doc, normalize_text(char) or "未提供")
                    add_divider(doc)
            else:
                try:
                    render_character(doc, characters)
                except Exception as exc:
                    logger.warning("render_character fallback block failed: %s", exc)
                    render_field(doc, "人物信息", normalize_text(characters) or "未提供")

        # 场景设定
        elif isinstance(data, dict) and "scene_setting" in data and not rendered_scene_section:
            add_heading(doc, "核心场景", level=1)
            ss = data["scene_setting"]
            render_field(doc, "场景设计原则", safe_get(ss, "scene_design_principle") if isinstance(ss, dict) else None)
            doc.add_paragraph()
            scenes = safe_get(ss, "scenes", []) if isinstance(ss, dict) else ss
            if isinstance(scenes, list):
                for scene in scenes:
                    try:
                        render_scene(doc, scene)
                    except Exception as exc:
                        logger.warning("render_scene failed, fallback to plain text: %s", exc)
                        render_scene(doc, normalize_text(scene) or "未提供")
                    add_divider(doc)
            else:
                try:
                    render_scene(doc, scenes)
                except Exception as exc:
                    logger.warning("render_scene fallback block failed: %s", exc)
                    render_field(doc, "场景说明", normalize_text(scenes) or "未提供")

        # 通用 JSON（未知结构）
        else:
            add_heading(doc, label or "附加数据", level=1)
            add_para(doc, normalize_text(data) or _json_fallback(data), size=9)

    # ── 剧本正文 ──
    if parsed["script"]:
        doc.add_page_break()
        render_script(doc, parsed["script"])

    # 3. 保存
    doc.save(output_path)
    print(f"已生成：{output_path}")
    return output_path


# ─────────────────────── 命令行入口 ───────────────────────────

if __name__ == "__main__":
    convert(r'C:\Users\Administrator\Desktop\txt_script\txt\西幻：葬爱武神.txt',
            r'C:\Users\Administrator\Desktop\西幻：葬爱武神.docx')
    # if len(sys.argv) < 3:
    #     print("用法: python txt_to_docx.py <input.txt> <output.docx>")
    #     sys.exit(1)
    # convert(sys.argv[1], sys.argv[2])
