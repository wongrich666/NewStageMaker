from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

from ..config import settings
from ..utils.logger import get_logger
from .fastgpt_client import FastGPTTransientError

logger = get_logger("simple_fastgpt_tools")


@dataclass(frozen=True, slots=True)
class SimpleToolField:
    name: str
    label: str
    input_type: str
    placeholder: str
    required: bool = False


@dataclass(frozen=True, slots=True)
class SimpleTool:
    key: str
    label: str
    env_prefix: str
    required_fields: tuple[str, ...]
    variable_aliases: dict[str, str]
    message_field: str | None = None
    help_text: str = ""
    json_name_patterns: tuple[str, ...] = ()
    default_fields: tuple[SimpleToolField, ...] = ()


SIMPLE_TOOLS: dict[str, SimpleTool] = {
    "hot_review": SimpleTool(
        key="hot_review",
        label="爆款文审核",
        env_prefix="FASTGPT_HOT_REVIEW",
        required_fields=("text",),
        variable_aliases={"text": "userChatInput"},
        message_field="text",
        help_text="提交一段文本，让工具返回审核意见。",
        json_name_patterns=("爆款文审核",),
        default_fields=(
            SimpleToolField("text", "待检测文本", "textarea", "粘贴要审核的正文、大纲或片段。", True),
        ),
    ),
    "reskin": SimpleTool(
        key="reskin",
        label="换皮",
        env_prefix="FASTGPT_RESKIN",
        required_fields=(
            "title",
            "source_outline",
            "source_characters",
            "source_script",
            "target_style",
            "total_episodes",
            "episode_word_count",
        ),
        variable_aliases={
            "title": "ju_ben_biao_ti",
            "source_outline": "yuan_juben_genggai",
            "core_scenes": "hexin_changjing",
            "source_characters": "renwu_xiaozhuan",
            "source_script": "juben_zhengwen",
            "target_style": "mubiao_fengge",
            "total_episodes": "zong_jishu",
            "episode_word_count": "meiji_zishu",
        },
        help_text="保留原剧本骨架，按目标风格做整套换皮。",
        json_name_patterns=("换皮",),
        default_fields=(
            SimpleToolField("title", "剧本标题", "input", "新剧本标题。", True),
            SimpleToolField("source_outline", "源剧本梗概", "textarea", "源故事梗概。", True),
            SimpleToolField("core_scenes", "源剧本核心场景", "textarea", "可选，源剧本核心场景。"),
            SimpleToolField("source_characters", "源剧本人设", "textarea", "源人物小传。", True),
            SimpleToolField("source_script", "源剧本正文", "textarea", "源剧本正文。", True),
            SimpleToolField("target_style", "目标风格", "textarea", "希望换成的题材、风格、爽点方向。", True),
            SimpleToolField("total_episodes", "总集数", "number", "例如 60。", True),
            SimpleToolField("episode_word_count", "每集字数", "number", "例如 500。", True),
        ),
    ),
    "punchup": SimpleTool(
        key="punchup",
        label="增加爽感",
        env_prefix="FASTGPT_PUNCHUP",
        required_fields=(
            "title",
            "story_outline",
            "characters",
            "core_scenes",
            "script",
            "total_episodes",
        ),
        variable_aliases={
            "title": "a1LYQ4vP",
            "story_outline": "n3RRWZ0z",
            "characters": "dNExYMr3",
            "core_scenes": "a55F8PVP",
            "script": "lfuBXcCA",
            "total_episodes": "tg0Gvxtp",
        },
        help_text="不改主干情节，重点增强爽点、节奏和表达力度。",
        json_name_patterns=("增加爽感",),
        default_fields=(
            SimpleToolField("title", "剧本名", "input", "原剧本名。", True),
            SimpleToolField("story_outline", "故事梗概", "textarea", "故事梗概。", True),
            SimpleToolField("characters", "人物小传", "textarea", "人物设定。", True),
            SimpleToolField("core_scenes", "核心场景", "textarea", "核心场景。", True),
            SimpleToolField("script", "剧本正文", "textarea", "需要增爽的剧本正文。", True),
            SimpleToolField("total_episodes", "总集数", "number", "总集数。", True),
        ),
    ),
    "character_reskin": SimpleTool(
        key="character_reskin",
        label="只换人设",
        env_prefix="FASTGPT_CHARACTER_RESKIN",
        required_fields=(
            "title",
            "story_outline",
            "characters",
            "core_scenes",
            "source_script",
            "total_episodes",
            "episode_word_count",
        ),
        variable_aliases={
            "title": "n5ZHYrj8",
            "story_outline": "ayxWwSpE",
            "characters": "yYYOuumm",
            "core_scenes": "rxmvq2lS",
            "source_script": "pxtQY7p2",
            "total_episodes": "blkSS7dY",
            "episode_word_count": "eBEWC07Q",
        },
        help_text="保留剧情结构，重点替换人物设定和人设表现。",
        json_name_patterns=("换皮只换人设", "只换人设"),
        default_fields=(
            SimpleToolField("title", "剧本标题", "input", "新剧本标题。", True),
            SimpleToolField("story_outline", "故事大纲", "textarea", "故事大纲。", True),
            SimpleToolField("characters", "人物小传", "textarea", "需要换皮的人物小传。", True),
            SimpleToolField("core_scenes", "核心场景", "textarea", "核心场景。", True),
            SimpleToolField("source_script", "原剧本正文", "textarea", "原剧本正文。", True),
            SimpleToolField("total_episodes", "总集数", "number", "总集数。", True),
            SimpleToolField("episode_word_count", "每集字数", "number", "每集字数。", True),
        ),
    ),
}

VISIBLE_TOOL_KEYS: tuple[str, ...] = (
    "hot_review",
    "reskin",
    "punchup",
    "character_reskin",
)


def list_simple_tools() -> list[dict[str, Any]]:
    return [
        _serialize_tool(_resolved_tool(tool.key))
        for key, tool in SIMPLE_TOOLS.items()
        if key in VISIBLE_TOOL_KEYS
    ]


def run_simple_tool(tool_key: str, user_payload: dict[str, Any]) -> dict[str, Any]:
    resolved = _resolved_tool(tool_key)
    tool = resolved["tool"]
    missing = [
        field
        for field in resolved["required_fields"]
        if str(user_payload.get(field) or "").strip() == ""
    ]
    if missing:
        raise ValueError(f"{tool.label} 缺少必填项：{', '.join(missing)}")

    api_key = _env(f"{tool.env_prefix}_API_KEY", "FASTGPT_API_KEY")
    if not api_key:
        raise ValueError(f"请在 .env 配置 {tool.env_prefix}_API_KEY 或 FASTGPT_API_KEY")
    url = _env(f"{tool.env_prefix}_CHAT_COMPLETIONS_URL", "FASTGPT_CHAT_COMPLETIONS_URL") or "https://api.fastgpt.in/api/v1/chat/completions"

    variables = {
        alias: _normalize_value(user_payload.get(field))
        for field, alias in resolved["variable_aliases"].items()
        if field in user_payload and str(user_payload.get(field) or "").strip() != ""
    }
    content = (
        str(user_payload.get(resolved["message_field"]) or "").strip()
        if resolved["message_field"]
        else f"执行工具：{tool.label}。请严格读取 variables，并只返回最终结果。"
    )
    body = {
        "chatId": f"scriptmaker-tool-{tool.key}-{uuid.uuid4().hex[:8]}",
        "stream": False,
        "detail": True,
        "variables": variables,
        "messages": [{"role": "user", "content": content}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    logger.info(
        "调用单次 FastGPT 工具 %s，URL：%s，字段来源：%s，变量：%s",
        tool.key,
        url,
        resolved["source"],
        ", ".join(variables.keys()),
    )
    response = requests.post(
        url.strip().rstrip("/"),
        headers=headers,
        json=body,
        timeout=int(getattr(settings, "fastgpt_timeout", 300)),
    )
    if response.status_code >= 400:
        text = " ".join((response.text or "").strip().split())
        message = f"{tool.label} HTTP {response.status_code} {response.reason or ''}，响应：{text or '空'}"
        if response.status_code in {429, 500, 502, 503, 504}:
            raise FastGPTTransientError(
                message,
                stage_name=tool.key,
                status_code=response.status_code,
                url=url,
                response_text=text,
            )
        raise RuntimeError(message)
    data = response.json()
    return {
        "tool": tool.key,
        "label": tool.label,
        "result": _extract_text(data),
        "raw": data,
        "source": resolved["source"],
        "json_file": resolved["json_file"],
    }


def _serialize_tool(resolved: dict[str, Any]) -> dict[str, Any]:
    tool: SimpleTool = resolved["tool"]
    return {
        "key": tool.key,
        "label": tool.label,
        "configured": bool(_env(f"{tool.env_prefix}_API_KEY", "FASTGPT_API_KEY")),
        "help": resolved["help_text"],
        "source": resolved["source"],
        "json_file": resolved["json_file"],
        "required_fields": list(resolved["required_fields"]),
        "fields": [
            {
                "name": field.name,
                "label": field.label,
                "type": field.input_type,
                "placeholder": field.placeholder,
                "required": field.required,
            }
            for field in resolved["fields"]
        ],
    }


@lru_cache(maxsize=None)
def _resolved_tool(tool_key: str) -> dict[str, Any]:
    tool = SIMPLE_TOOLS.get(tool_key)
    if not tool:
        raise ValueError(f"未知工具：{tool_key}")

    json_path = _find_tool_json(tool)
    if json_path:
        fields = _infer_fields_from_workflow_json(json_path)
        if fields:
            return {
                "tool": tool,
                "fields": fields,
                "required_fields": tuple(field.name for field in fields if field.required),
                "variable_aliases": {field.name: field.name for field in fields},
                "message_field": None,
                "help_text": f"{tool.help_text} 当前字段从 {json_path.name} 自动推断。",
                "source": "json",
                "json_file": json_path.name,
            }

    return {
        "tool": tool,
        "fields": tool.default_fields,
        "required_fields": tool.required_fields,
        "variable_aliases": tool.variable_aliases,
        "message_field": tool.message_field,
        "help_text": tool.help_text,
        "source": "fallback",
        "json_file": None,
    }


@lru_cache(maxsize=1)
def _workflow_json_dir() -> Path | None:
    repo_root = Path(__file__).resolve().parents[3]
    for child in repo_root.iterdir():
        if child.is_dir() and "workflow_jsons" in child.name:
            return child
    return None


def _find_tool_json(tool: SimpleTool) -> Path | None:
    folder = _workflow_json_dir()
    if folder is None:
        return None
    files = sorted(folder.glob("*.json"))
    for pattern in tool.json_name_patterns:
        exact = next((item for item in files if item.stem == pattern), None)
        if exact:
            return exact
    lowered_patterns = tuple(pattern.lower() for pattern in tool.json_name_patterns)
    for item in files:
        stem = item.stem.lower()
        if tool.key == "reskin" and "只换人设" in stem:
            continue
        if any(pattern in stem for pattern in lowered_patterns):
            return item
    return None


def _infer_fields_from_workflow_json(path: Path) -> tuple[SimpleToolField, ...]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        logger.warning("辅助工具 JSON 读取失败：%s", path)
        return ()

    variables = data.get("chatConfig", {}).get("variables", [])
    fields: list[SimpleToolField] = []
    for item in variables:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip().lower() == "internal":
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        label = str(item.get("label") or key).strip() or key
        description = str(item.get("description") or "").strip()
        fields.append(
            SimpleToolField(
                name=key,
                label=label,
                input_type=_field_input_type(item, label),
                placeholder=description or f"请输入{label}",
                required=bool(item.get("required")),
            )
        )
    return tuple(fields)


def _field_input_type(item: dict[str, Any], label: str) -> str:
    value_type = str(item.get("valueType") or "").strip().lower()
    field_type = str(item.get("type") or "").strip().lower()
    lowered_label = label.lower()
    if field_type == "numberinput" or value_type == "number":
        return "number"
    if any(token in lowered_label for token in ("标题", "title", "名称", "name")):
        return "input"
    return "textarea"


def _env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def _extract_text(data: Any) -> str:
    if isinstance(data, dict):
        choices = data.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                message = choice.get("message") if isinstance(choice, dict) else None
                if isinstance(message, dict):
                    content = message.get("content")
                    text = _content_to_text(content)
                    if text:
                        return text
        for key in ("answerText", "answer", "content", "text", "response", "result"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, (dict, list)):
                nested = _extract_text(value)
                if nested:
                    return nested
        return json.dumps(data, ensure_ascii=False)
    if isinstance(data, str):
        return data.strip()
    return json.dumps(data, ensure_ascii=False, default=str)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"].strip()
        text = content.get("text")
        if isinstance(text, dict) and isinstance(text.get("content"), str):
            return text["content"].strip()
        if isinstance(content.get("content"), str):
            return content["content"].strip()
    if isinstance(content, list):
        parts = [_content_to_text(item) for item in content]
        return "\n".join(part for part in parts if part).strip()
    return ""
