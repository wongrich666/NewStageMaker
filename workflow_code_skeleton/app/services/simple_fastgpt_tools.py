from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

import requests

from ..config import settings
from ..utils.logger import get_logger
from .fastgpt_client import FastGPTTransientError

logger = get_logger("simple_fastgpt_tools")


@dataclass(frozen=True, slots=True)
class SimpleTool:
    key: str
    label: str
    env_prefix: str
    required_fields: tuple[str, ...]
    variable_aliases: dict[str, str]
    message_field: str | None = None


SIMPLE_TOOLS: dict[str, SimpleTool] = {
    "hot_review": SimpleTool(
        key="hot_review",
        label="爆款文审核",
        env_prefix="FASTGPT_HOT_REVIEW",
        required_fields=("text",),
        variable_aliases={"text": "userChatInput"},
        message_field="text",
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
    ),
    "character_reskin": SimpleTool(
        key="character_reskin",
        label="换皮只换人设",
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
    ),
}


def list_simple_tools() -> list[dict[str, Any]]:
    return [
        {
            "key": tool.key,
            "label": tool.label,
            "required_fields": list(tool.required_fields),
            "configured": bool(_env(f"{tool.env_prefix}_API_KEY", "FASTGPT_API_KEY")),
        }
        for tool in SIMPLE_TOOLS.values()
    ]


def run_simple_tool(tool_key: str, user_payload: dict[str, Any]) -> dict[str, Any]:
    tool = SIMPLE_TOOLS.get(tool_key)
    if not tool:
        raise ValueError(f"未知工具：{tool_key}")
    missing = [
        field
        for field in tool.required_fields
        if str(user_payload.get(field) or "").strip() == ""
    ]
    if missing:
        raise ValueError(f"{tool.label} 缺少必填项：{', '.join(missing)}")

    api_key = _env(f"{tool.env_prefix}_API_KEY", "FASTGPT_API_KEY")
    if not api_key:
        raise ValueError(f"请在 .env 配置 {tool.env_prefix}_API_KEY 或 FASTGPT_API_KEY")
    url = _env("FASTGPT_CHAT_COMPLETIONS_URL") or "https://api.fastgpt.in/api/v1/chat/completions"
    variables = {
        alias: _normalize_value(user_payload.get(field))
        for field, alias in tool.variable_aliases.items()
        if field in user_payload
    }
    content = (
        str(user_payload.get(tool.message_field) or "").strip()
        if tool.message_field
        else f"执行工具：{tool.label}。请读取 variables，并直接输出本工具结果。"
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
        "调用单次 FastGPT 工具 %s，URL：%s，变量：%s",
        tool.key,
        url,
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
    }


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
