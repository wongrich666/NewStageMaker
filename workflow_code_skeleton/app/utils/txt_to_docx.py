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
import sys
from pathlib import Path
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


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

    # 提取所有 ```json ... ``` 块（含位置信息）
    json_pattern = re.compile(r'```json\s*(.*?)```', re.DOTALL)
    json_matches = list(json_pattern.finditer(text))

    # 移除 JSON 块后的纯文本部分
    plain_text = json_pattern.sub('<<<JSON_BLOCK>>>', text)
    plain_parts = plain_text.split('<<<JSON_BLOCK>>>')

    # 第一个纯文本块包含标题和故事梗概
    header_block = plain_parts[0].strip() if plain_parts else ""
    lines = header_block.splitlines()
    title = lines[0].strip() if lines else ""
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
    synopsis = "\n".join(synopsis_lines).strip()

    # 找剧本正文（最后一个 JSON 块之后的文本）
    script_text = ""
    if len(plain_parts) > len(json_matches):
        last_part = plain_parts[-1]
        # 找"剧本正文"标记
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
        "json_blocks": json_blocks,
        "script": script_text,
    }


# ─────────────────────── 渲染人物小传 ───────────────────────────

def render_character(doc: Document, char: dict):
    """渲染单个人物信息"""
    name = char.get("character_name", "未知角色")
    add_heading(doc, f"👤 {name}", level=2)

    simple_fields = {
        "故事角色": "story_role",
        "核心动机": "core_motivation",
        "戏剧价值": "dramatic_value",
    }
    for label, key in simple_fields.items():
        if key in char:
            add_kv(doc, label, char[key])

    # 性格
    personality = char.get("personality", {})
    if personality:
        add_para(doc, "性格特征", bold=True, size=10, indent=0.5)
        traits = personality.get("traits", [])
        if traits:
            add_kv(doc, "特质", "、".join(traits) if isinstance(traits, list) else traits)
        for k, label in [("surface_impression", "外在印象"), ("inner_contradiction", "内在矛盾")]:
            if k in personality:
                add_kv(doc, label, personality[k])

    # 家庭背景
    family = char.get("family", {})
    if family:
        add_para(doc, "家庭背景", bold=True, size=10, indent=0.5)
        for k, label in [("family_background", "家世"), ("upbringing", "成长经历"),
                          ("key_family_influence", "关键影响")]:
            if k in family:
                add_kv(doc, label, family[k])

    # 外貌
    appearance = char.get("appearance", {})
    if appearance:
        add_para(doc, "外貌描述", bold=True, size=10, indent=0.5)
        for k, label in [("overall_look", "整体形象"), ("external_impression_effect", "外貌效果")]:
            if k in appearance:
                add_kv(doc, label, appearance[k])
        features = appearance.get("recognizable_features", [])
        if features:
            add_kv(doc, "标志性特征", "；".join(features) if isinstance(features, list) else features)

    # 行为模式
    behavior = char.get("behavior", {})
    if behavior:
        add_para(doc, "行为模式", bold=True, size=10, indent=0.5)
        for k, label in [("emotional_response_pattern", "情感反应"), ("social_interaction_style", "社交风格")]:
            if k in behavior:
                add_kv(doc, label, behavior[k])


# ─────────────────────── 渲染核心场景 ───────────────────────────

def render_scene(doc: Document, scene: dict):
    """渲染单个场景信息"""
    name = scene.get("scene_name", "未知场景")
    s_type = scene.get("scene_type", "")
    add_heading(doc, f"🎬 {name}", level=2)
    if s_type:
        add_para(doc, s_type, italic=True, size=10, color="888888")

    field_map = [
        ("story_function", "场景功能"),
        ("environment_description", "环境描述"),
        ("atmosphere_description", "氛围描述"),
        ("character_interaction_effect", "人物互动效果"),
        ("worldview_support", "世界观支撑"),
    ]
    for key, label in field_map:
        if key in scene:
            add_kv(doc, label, scene[key])

    elements = scene.get("visual_elements", [])
    if elements:
        add_kv(doc, "视觉元素", "、".join(elements) if isinstance(elements, list) else elements)

    conflicts = scene.get("conflict_potential", [])
    if conflicts:
        add_para(doc, "冲突潜力", bold=True, size=10, indent=0.5)
        for c in (conflicts if isinstance(conflicts, list) else [conflicts]):
            p = doc.add_paragraph(style='List Bullet')
            p.paragraph_format.left_indent = Cm(1)
            run = p.add_run(re.sub(r'\*\*(.+?)\*\*', r'\1', str(c)))
            run.font.size = Pt(10)


# ─────────────────────── 渲染剧本正文 ───────────────────────────

def render_script(doc: Document, script_text: str):
    """渲染剧本正文"""
    if not script_text.strip():
        return

    lines = script_text.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            doc.add_paragraph()
            continue

        # 集标题（第N集：...）
        if re.match(r'^第\d+集[:：]', stripped):
            add_heading(doc, stripped, level=2)

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
            add_heading(doc, stripped, level=1)

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

    # ── 故事梗概 ──
    if parsed["synopsis"]:
        add_heading(doc, "故事梗概", level=1)
        for line in parsed["synopsis"].splitlines():
            if line.strip():
                add_para(doc, line.strip())
        add_divider(doc)

    # ── JSON 块渲染 ──
    for block in parsed["json_blocks"]:
        label = block["label"]
        data = block["data"]

        if "_parse_error" in data:
            add_heading(doc, label or "数据块", level=1)
            add_para(doc, f"⚠️ JSON 解析失败：{data['_parse_error']}", color="CC0000")
            continue

        # 人物小传
        if "character_setting" in data:
            add_heading(doc, "人物小传", level=1)
            cs = data["character_setting"]
            if "character_design_principle" in cs:
                add_kv(doc, "角色设计原则", cs["character_design_principle"])
            if "core_relation_logic" in cs:
                add_kv(doc, "核心关系逻辑", cs["core_relation_logic"])
            doc.add_paragraph()
            for char in cs.get("characters", []):
                render_character(doc, char)
                add_divider(doc)

        # 场景设定
        elif "scene_setting" in data:
            add_heading(doc, "核心场景", level=1)
            ss = data["scene_setting"]
            if "scene_design_principle" in ss:
                add_kv(doc, "场景设计原则", ss["scene_design_principle"])
            doc.add_paragraph()
            for scene in ss.get("scenes", []):
                render_scene(doc, scene)
                add_divider(doc)

        # 通用 JSON（未知结构）
        else:
            add_heading(doc, label or "附加数据", level=1)
            add_para(doc, json.dumps(data, ensure_ascii=False, indent=2), size=9)

    # ── 剧本正文 ──
    if parsed["script"]:
        doc.add_page_break()
        render_script(doc, parsed["script"])

    # 3. 保存
    doc.save(output_path)
    print(f"✅ 已生成：{output_path}")
    return output_path


# ─────────────────────── 命令行入口 ───────────────────────────

if __name__ == "__main__":
    convert(r'C:\Users\Administrator\Desktop\txt_script\txt\西幻：葬爱武神.txt',
            r'C:\Users\Administrator\Desktop\西幻：葬爱武神.docx')
    # if len(sys.argv) < 3:
    #     print("用法: python txt_to_docx.py <input.txt> <output.docx>")
    #     sys.exit(1)
    # convert(sys.argv[1], sys.argv[2])
