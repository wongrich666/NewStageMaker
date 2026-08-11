from __future__ import annotations

import re
import json
from typing import Any


FIELD_LABELS_CN: dict[str, str] = {
    "source_brief": "原文信息提取",
    "worldview_plan": "世界观方案",
    "character_plan": "人物设定",
    "beat_checkpoint_timeline": "三幕十五节拍",
    "checkpoint_explanation": "节拍说明",
    "character_storylines": "人物故事线",
    "storyline_decisions": "故事线处理",
    "adaptation_guide": "整体改编指引",
    "framework_plan_package": "最终框架策划包",
    "character_emotion_strategy": "人物情绪策略",
    "core_setting_adjustments": "核心设定调整",
    "hard_constraints_for_script_workflow": "后续剧本硬性约束",
    "structure_and_rhythm": "结构与节奏",
    "visualization_strategy": "视觉化策略",
    "original_retention": "原文保留内容",
    "character_relationships": "人物关系",
    "character_rules": "人物规则",
    "character_system_summary": "人物系统概述",
    "main_characters": "主要人物",
    "protagonist": "主角",
    "emotion_engine": "情绪引擎",
    "relationship_map": "关系图谱",
    "ready_for_script_workflow": "是否可进入剧本正文阶段",
    "ability_or_resource": "能力 / 资源",
    "external_goal": "外部目标",
    "internal_need": "内在需求",
    "forbidden_write": "禁止写法",
    "growth_arc": "成长弧线",
    "identity": "身份定位",
    "role": "角色功能",
    "story_function": "故事功能",
    "weakness": "弱点",
    "relationship_hooks": "关系钩子",
    "scene_count": "场景数量",
    "selection_principle": "场景选择原则",
    "core_scenes": "核心场景",
    "scene_id": "场景编号",
    "scene_type": "场景类型",
    "source_basis": "来源依据",
    "visual_anchor": "视觉锚点",
    "dramatic_function": "戏剧功能",
    "conflict_soil": "冲突土壤",
    "common_characters": "常见出场人物",
    "usable_episode_range": "可使用集数范围",
    "rules_or_limits": "场景规则 / 限制",
    "key_props": "关键道具",
    "allowed_actions": "允许发生的动作",
    "do_not_use_as": "禁止用途",
    "continuity_notes": "连续性注意事项",
    "scene_usage_notes": "场景使用说明",
    "scriptWorldRulesDigest": "世界规则摘要",
    "script_world_rules_digest": "世界规则摘要",
    "world_type": "世界类型",
    "core_rules": "核心规则",
    "action_limits": "行动限制",
    "danger_sources": "危险来源",
    "resource_or_stakes": "资源 / 利害关系",
    "power_distribution": "权力分布",
    "special_rules": "特殊规则",
    "overall_atmosphere": "整体氛围",
    "do_not_break_rules": "不可破坏的规则",
    "sceneDictionary": "场景字典",
    "appearanceMapping": "角色外观匹配场景",
    "allEnrichedEpisodePlan": "完整分集细化方案",
    "allEnrichedEpisodePlanText": "完整分集细化文本",
    "batchScriptText": "正文及对话",
    "title": "标题",
    "name": "名称",
    "summary": "摘要",
    "description": "说明",
    "episode": "集数",
    "episode_range": "集数范围",
    "focus": "重点",
}

HIDDEN_FIELD_KEYS_CN = {
    "id", "nodeId", "moduleName", "moduleType", "moduleLogo", "raw", "debug",
    "schema", "schema_version", "token", "tokens", "inputTokens", "outputTokens",
    "responseData", "updateVarResult", "newVariables", "reasoningText", "historyPreview",
    "choices", "usage", "cache", "logs", "_meta", "metadata", "raw_stage_responses",
}

WORD_LABELS_CN = {
    "world": "世界", "worldview": "世界观", "script": "剧本", "rules": "规则",
    "digest": "摘要", "core": "核心", "character": "人物", "characters": "人物",
    "emotion": "情绪", "strategy": "策略", "relationship": "关系", "relationships": "关系",
    "scene": "场景", "visual": "视觉", "anchor": "锚点", "conflict": "冲突",
    "goal": "目标", "internal": "内在", "external": "外部", "need": "需求",
    "ability": "能力", "resource": "资源", "growth": "成长", "arc": "弧线",
    "function": "功能", "type": "类型", "source": "来源", "basis": "依据",
    "notes": "注意事项", "action": "行动", "limits": "限制", "danger": "危险",
    "power": "权力", "distribution": "分布", "special": "特殊", "atmosphere": "氛围",
    "count": "数量", "principle": "原则", "props": "道具", "allowed": "允许",
    "forbidden": "禁止", "write": "写法", "workflow": "工作流", "hard": "硬性",
    "constraints": "约束", "original": "原文", "retention": "保留", "structure": "结构",
    "rhythm": "节奏", "summary": "概述", "plan": "方案", "text": "文本", "episode": "集数",
}


def readable_label(key: Any) -> str:
    raw = str(key or "").strip()
    if not raw:
        return "其他信息"
    if re.search(r"[\u4e00-\u9fff]", raw):
        return raw
    if raw in FIELD_LABELS_CN:
        return FIELD_LABELS_CN[raw]
    spaced = re.sub(r"([a-z])([A-Z])", r"\1_\2", raw).replace("-", "_").replace(" ", "_")
    if spaced in FIELD_LABELS_CN:
        return FIELD_LABELS_CN[spaced]
    translated = [WORD_LABELS_CN.get(part.lower(), "") for part in spaced.split("_") if part]
    translated = [part for part in translated if part]
    return " / ".join(translated) if translated else "其他信息"


def is_hidden_readable_key(key: Any) -> bool:
    raw = str(key or "").strip()
    return raw in HIDDEN_FIELD_KEYS_CN or bool(re.search(r"token|debug|schema|response|raw|module|node", raw, re.I))


def readable_scalar(value: Any) -> str:
    if value is None or value == "":
        return "暂无"
    if isinstance(value, bool):
        return "是" if value else "否"
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or "暂无"


def readable_text(value: Any, indent: int = 0) -> str:
    pad = " " * max(0, int(indent or 0))
    if value is None or value == "":
        return "暂无"
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("{", "[")):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, (dict, list)):
                    return readable_text(parsed, indent)
            except Exception:
                pass
        return readable_scalar(value)
    if isinstance(value, (int, float, bool)):
        return readable_scalar(value)
    if isinstance(value, list):
        if not value:
            return "暂无"
        lines: list[str] = []
        for index, item in enumerate(value, start=1):
            prefix = f"{pad}{index}. "
            if isinstance(item, (dict, list)):
                nested = readable_text(item, indent + 2)
                lines.append(f"{prefix}{'暂无' if nested == '暂无' else ''}".rstrip())
                if nested != "暂无":
                    lines.append(nested)
            else:
                lines.append(f"{prefix}{readable_scalar(item)}")
        return "\n".join(line for line in lines if line.strip()) or "暂无"
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if is_hidden_readable_key(key) or item in (None, ""):
                continue
            label = readable_label(key)
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{label}：")
                lines.append(readable_text(item, indent + 2))
            else:
                lines.append(f"{pad}{label}：{readable_scalar(item)}")
        return "\n".join(line for line in lines if line.strip()) or "暂无"
    return readable_scalar(value)
