from __future__ import annotations

import copy
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
from .json_utils import strip_code_fence

logger = get_logger("simple_fastgpt_tools")


DEFAULT_FASTGPT_URL = "https://api.fastgpt.in/api/v1/chat/completions"
TOOL_RESPONSE_TEXT_KEYS = ("answerText", "answer", "content", "text", "response", "result")


@dataclass(frozen=True, slots=True)
class SimpleToolField:
    name: str
    label: str
    input_type: str
    placeholder: str
    required: bool = False
    source: str = "workflow_json"


@dataclass(frozen=True, slots=True)
class SimpleToolDefinition:
    key: str
    label: str
    env_prefix: str
    help_text: str
    json_name_patterns: tuple[str, ...]
    fallback_fields: tuple[SimpleToolField, ...] = ()
    fallback_message_field: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedSimpleTool:
    definition: SimpleToolDefinition
    fields: tuple[SimpleToolField, ...]
    required_fields: tuple[str, ...]
    variable_aliases: dict[str, str]
    message_field: str | None
    help_text: str
    source: str
    json_path: Path | None
    answer_node_names: tuple[str, ...]
    updated_variables: tuple[str, ...]
    input_variables: tuple[str, ...]
    internal_variables: tuple[str, ...]
    visible_output_fields: tuple[str, ...]
    api_key_envs: tuple[str, ...]
    url_envs: tuple[str, ...]


class ToolExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        tool_id: str = "",
        debug: dict[str, Any] | None = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.tool_id = tool_id
        self.debug = debug or {}
        self.status_code = status_code


TOOL_DEFINITIONS: dict[str, SimpleToolDefinition] = {
    "hot_review": SimpleToolDefinition(
        key="hot_review",
        label="爆款文审核",
        env_prefix="FASTGPT_HOT_REVIEW",
        help_text="提交一段文本，让工具返回爆款爽剧诊断意见。",
        json_name_patterns=("爆款文审核",),
        fallback_fields=(
            SimpleToolField(
                name="text",
                label="待审核文本",
                input_type="textarea",
                placeholder="粘贴待审核的剧本、大纲或片段。",
                required=True,
                source="fallback",
            ),
        ),
        fallback_message_field="text",
    ),
    "reskin": SimpleToolDefinition(
        key="reskin",
        label="换皮",
        env_prefix="FASTGPT_RESKIN",
        help_text="保留故事骨架，按目标风格完整换皮。",
        json_name_patterns=("换皮",),
    ),
    "punchup": SimpleToolDefinition(
        key="punchup",
        label="增加爽感",
        env_prefix="FASTGPT_PUNCHUP",
        help_text="不改主干情节，重点增强爽点、节奏与表达力度。",
        json_name_patterns=("增加爽感",),
    ),
    "character_reskin": SimpleToolDefinition(
        key="character_reskin",
        label="只换人设",
        env_prefix="FASTGPT_CHARACTER_RESKIN",
        help_text="保留主剧情结构，重点替换人物设定与角色表现。",
        json_name_patterns=("只换人设", "换皮只换人设"),
    ),
}


VISIBLE_TOOL_KEYS: tuple[str, ...] = tuple(TOOL_DEFINITIONS.keys())


def list_simple_tools() -> list[dict[str, Any]]:
    return [
        _serialize_tool(_resolved_tool(tool_key))
        for tool_key in VISIBLE_TOOL_KEYS
    ]


def run_simple_tool(tool_key: str, user_payload: dict[str, Any]) -> dict[str, Any]:
    resolved = _resolved_tool(tool_key)
    definition = resolved.definition
    payload = user_payload if isinstance(user_payload, dict) else {}
    missing = [
        field_name
        for field_name in resolved.required_fields
        if str(payload.get(field_name) or "").strip() == ""
    ]
    if missing:
        raise ToolExecutionError(
            f"{definition.label} 缺少必填项：{', '.join(missing)}",
            tool_id=definition.key,
            debug={"missing_fields": missing},
            status_code=400,
        )

    api_key_envs = resolved.api_key_envs
    api_key_name, api_key = _env_with_name(*api_key_envs)
    if not api_key:
        raise ToolExecutionError(
            f"{definition.label} 还未配置 API Key，请先配置 {api_key_envs[0]} 或 FASTGPT_API_KEY。",
            tool_id=definition.key,
            debug={"api_key_envs": list(api_key_envs)},
            status_code=400,
        )
    url_name, url = _env_with_name(*resolved.url_envs)
    url = (url or DEFAULT_FASTGPT_URL).strip().rstrip("/")

    variables = {
        alias: _normalize_value(payload.get(field_name))
        for field_name, alias in resolved.variable_aliases.items()
        if field_name in payload and str(payload.get(field_name) or "").strip() != ""
    }
    content = _tool_message_content(resolved, payload)
    body = {
        "chatId": f"scriptmaker-tool-{definition.key}-{uuid.uuid4().hex[:8]}",
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
        "调用辅助工具 %s，json=%s，source=%s，url_env=%s，api_env=%s，输入字段=%s",
        definition.key,
        resolved.json_path.name if resolved.json_path else "",
        resolved.source,
        url_name or resolved.url_envs[0],
        api_key_name or resolved.api_key_envs[0],
        ", ".join(sorted(variables.keys())),
    )
    response = requests.post(
        url,
        headers=headers,
        json=body,
        timeout=int(getattr(settings, "fastgpt_timeout", 300)),
    )
    if response.status_code >= 400:
        text = " ".join((response.text or "").strip().split())
        message = f"{definition.label} 请求失败（HTTP {response.status_code}）。"
        debug = {
            "status_code": response.status_code,
            "reason": response.reason or "",
            "response_preview": _truncate_text(text, limit=600),
            "url": url,
        }
        if response.status_code in {429, 500, 502, 503, 504}:
            raise FastGPTTransientError(
                message,
                stage_name=definition.key,
                status_code=response.status_code,
                url=url,
                response_text=text,
            )
        raise ToolExecutionError(message, tool_id=definition.key, debug=debug, status_code=400)
    try:
        data = response.json()
    except Exception as exc:
        raise ToolExecutionError(
            f"{definition.label} 返回了无法解析的响应。",
            tool_id=definition.key,
            debug={"response_preview": _truncate_text(response.text, limit=1000), "url": url},
            status_code=400,
        ) from exc

    extracted = _extract_tool_output(data, resolved)
    if extracted is None:
        raise ToolExecutionError(
            f"{definition.label} 没有返回可展示结果。请检查 workflow 是否缺少 answerNode，或确认最终输出是否写到了正式变量。",
            tool_id=definition.key,
            debug={
                "workflow_json_file": resolved.json_path.name if resolved.json_path else None,
                "answer_node_names": list(resolved.answer_node_names),
                "updated_variables": list(resolved.updated_variables),
                "visible_output_fields": list(resolved.visible_output_fields),
                "api_key_envs": list(resolved.api_key_envs),
                "response_preview": _truncate_text(_json_text(data), limit=1200),
            },
            status_code=400,
        )

    output, output_source = extracted
    debug = {
        "workflow_json_file": resolved.json_path.name if resolved.json_path else None,
        "workflow_json_path": str(resolved.json_path) if resolved.json_path else "",
        "source": resolved.source,
        "answer_node_names": list(resolved.answer_node_names),
        "updated_variables": list(resolved.updated_variables),
        "input_variables": list(resolved.input_variables),
        "internal_variables": list(resolved.internal_variables),
        "visible_output_fields": list(resolved.visible_output_fields),
        "chosen_output_source": output_source,
        "response_preview": _truncate_text(_json_text(data), limit=1200),
    }
    return {
        "ok": True,
        "tool_id": definition.key,
        "title": definition.label,
        "output": output,
        "output_type": "json" if isinstance(output, (dict, list)) else "text",
        "debug": debug,
        "schema": _serialize_tool(resolved),
    }


def _serialize_tool(resolved: ResolvedSimpleTool) -> dict[str, Any]:
    definition = resolved.definition
    api_key_name, _ = _env_with_name(*resolved.api_key_envs)
    url_name, url_value = _env_with_name(*resolved.url_envs)
    return {
        "tool_id": definition.key,
        "key": definition.key,
        "title": definition.label,
        "label": definition.label,
        "configured": bool(_env(*resolved.api_key_envs)),
        "configured_api_key_env": api_key_name,
        "configured_url_env": url_name,
        "configured_url": (url_value or DEFAULT_FASTGPT_URL).strip().rstrip("/"),
        "help": resolved.help_text,
        "source": resolved.source,
        "json_file": resolved.json_path.name if resolved.json_path else None,
        "workflow_json_file": resolved.json_path.name if resolved.json_path else None,
        "api_key_envs": list(resolved.api_key_envs),
        "workflow_url_envs": list(resolved.url_envs),
        "input_variables": list(resolved.input_variables),
        "internal_variables": list(resolved.internal_variables),
        "output_variables": list(resolved.updated_variables),
        "visible_output_fields": list(resolved.visible_output_fields),
        "answer_node_names": list(resolved.answer_node_names),
        "required_fields": list(resolved.required_fields),
        "fields": [
            {
                "name": field.name,
                "label": field.label,
                "type": field.input_type,
                "placeholder": field.placeholder,
                "required": field.required,
                "source": field.source,
            }
            for field in resolved.fields
        ],
        "schema": {
            "fields": [
                {
                    "name": field.name,
                    "label": field.label,
                    "type": field.input_type,
                    "placeholder": field.placeholder,
                    "required": field.required,
                    "source": field.source,
                }
                for field in resolved.fields
            ],
            "input_variables": list(resolved.input_variables),
            "internal_variables": list(resolved.internal_variables),
            "output_variables": list(resolved.updated_variables),
            "visible_output_fields": list(resolved.visible_output_fields),
            "answer_node_names": list(resolved.answer_node_names),
        },
    }


@lru_cache(maxsize=None)
def _resolved_tool(tool_key: str) -> ResolvedSimpleTool:
    definition = TOOL_DEFINITIONS.get(tool_key)
    if definition is None:
        raise ToolExecutionError(f"未知工具：{tool_key}", tool_id=tool_key, status_code=404)

    json_path = _find_tool_json(definition)
    workflow = _load_workflow_json(json_path) if json_path else None
    input_variables, internal_variables = _workflow_variables(workflow)
    fields = _infer_fields_from_workflow_json(workflow)
    updated_variables = _infer_updated_variables(workflow)
    answer_node_names = _infer_answer_node_names(workflow)
    visible_output_fields = _visible_output_fields(
        answer_node_names=answer_node_names,
        updated_variables=updated_variables,
    )

    if fields:
        required_fields = tuple(field.name for field in fields if field.required)
        variable_aliases = {field.name: field.name for field in fields}
        message_field = None
        source = "workflow_json"
        help_text = f"{definition.help_text} 当前表单字段来自 {json_path.name}。"
    else:
        fields = definition.fallback_fields
        required_fields = tuple(field.name for field in fields if field.required)
        variable_aliases = {field.name: field.name for field in fields if field.name != definition.fallback_message_field}
        message_field = definition.fallback_message_field
        source = "fallback"
        help_text = (
            f"{definition.help_text} 当前 workflow 未暴露公开输入变量，已使用代码侧兜底表单。"
            if json_path
            else definition.help_text
        )

    return ResolvedSimpleTool(
        definition=definition,
        fields=fields,
        required_fields=required_fields,
        variable_aliases=variable_aliases,
        message_field=message_field,
        help_text=help_text,
        source=source,
        json_path=json_path,
        answer_node_names=answer_node_names,
        updated_variables=updated_variables,
        input_variables=input_variables,
        internal_variables=internal_variables,
        visible_output_fields=visible_output_fields,
        api_key_envs=(f"{definition.env_prefix}_API_KEY", "FASTGPT_API_KEY"),
        url_envs=(f"{definition.env_prefix}_CHAT_COMPLETIONS_URL", "FASTGPT_CHAT_COMPLETIONS_URL"),
    )


@lru_cache(maxsize=1)
def _workflow_json_dir() -> Path | None:
    repo_root = Path(__file__).resolve().parents[3]
    for child in repo_root.iterdir():
        if child.is_dir() and "workflow_jsons" in child.name:
            return child
    return None


def _find_tool_json(definition: SimpleToolDefinition) -> Path | None:
    folder = _workflow_json_dir()
    if folder is None:
        return None
    files = sorted(folder.glob("*.json"))
    lowered_patterns = tuple(pattern.lower() for pattern in definition.json_name_patterns)
    for pattern in definition.json_name_patterns:
        exact = next((item for item in files if item.stem == pattern), None)
        if exact is not None:
            return exact
    for item in files:
        stem = item.stem.lower()
        if definition.key == "reskin" and "只换人设" in stem:
            continue
        if any(pattern in stem for pattern in lowered_patterns):
            return item
    return None


def _load_workflow_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        logger.warning("辅助工具 workflow JSON 读取失败：%s", path, exc_info=True)
        return None


def _workflow_variables(workflow: dict[str, Any] | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    input_variables: list[str] = []
    internal_variables: list[str] = []
    for item in (workflow or {}).get("chatConfig", {}).get("variables", []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        if str(item.get("type") or "").strip().lower() == "internal":
            internal_variables.append(key)
        else:
            input_variables.append(key)
    return tuple(input_variables), tuple(internal_variables)


def _infer_fields_from_workflow_json(workflow: dict[str, Any] | None) -> tuple[SimpleToolField, ...]:
    fields: list[SimpleToolField] = []
    for item in (workflow or {}).get("chatConfig", {}).get("variables", []):
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
                source="workflow_json",
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


def _infer_updated_variables(workflow: dict[str, Any] | None) -> tuple[str, ...]:
    variables: list[str] = []
    for node in (workflow or {}).get("nodes", []):
        if not isinstance(node, dict) or node.get("flowNodeType") != "variableUpdate":
            continue
        for input_item in node.get("inputs") or []:
            if not isinstance(input_item, dict):
                continue
            for update in input_item.get("value") or []:
                if not isinstance(update, dict):
                    continue
                variable = update.get("variable")
                if (
                    isinstance(variable, list)
                    and len(variable) >= 2
                    and str(variable[1] or "").strip()
                ):
                    variables.append(str(variable[1]).strip())
    return tuple(dict.fromkeys(variables))


def _infer_answer_node_names(workflow: dict[str, Any] | None) -> tuple[str, ...]:
    answer_nodes: list[str] = []
    for node in (workflow or {}).get("nodes", []):
        if not isinstance(node, dict):
            continue
        if str(node.get("flowNodeType") or "").strip() == "answerNode":
            name = str(node.get("name") or "answerNode").strip() or "answerNode"
            answer_nodes.append(name)
    return tuple(dict.fromkeys(answer_nodes))


def _visible_output_fields(
    *,
    answer_node_names: tuple[str, ...],
    updated_variables: tuple[str, ...],
) -> tuple[str, ...]:
    fields: list[str] = []
    if answer_node_names:
        fields.append("choices.message.content")
    fields.extend(updated_variables)
    if not fields:
        fields.append("answerText")
    return tuple(dict.fromkeys(fields))


def _tool_message_content(resolved: ResolvedSimpleTool, payload: dict[str, Any]) -> str:
    if resolved.message_field:
        return str(payload.get(resolved.message_field) or "").strip()
    return (
        f"请执行辅助工具“{resolved.definition.label}”。"
        "请严格读取 variables，并只返回最终给用户看的结果。"
    )


def _extract_tool_output(
    data: Any,
    resolved: ResolvedSimpleTool,
) -> tuple[Any, str] | None:
    for source, value in _iter_tool_text_candidates(data):
        normalized = _normalize_tool_output_value(value)
        if normalized not in (None, "", [], {}):
            return normalized, source
    structured = _extract_structured_output(data, resolved)
    if structured is not None:
        return structured
    return None


def _extract_structured_output(
    data: Any,
    resolved: ResolvedSimpleTool,
) -> tuple[Any, str] | None:
    for source, candidate in _iter_structured_candidate_sources(data):
        for field in resolved.updated_variables:
            if not isinstance(candidate, dict) or field not in candidate:
                continue
            normalized = _normalize_tool_output_value(candidate.get(field))
            if normalized not in (None, "", [], {}):
                return normalized, f"{source}.{field}"
    if isinstance(data, dict):
        for field in resolved.updated_variables:
            if field not in data:
                continue
            normalized = _normalize_tool_output_value(data.get(field))
            if normalized not in (None, "", [], {}):
                return normalized, f"root.{field}"
    return None


def _iter_tool_text_candidates(data: Any) -> list[tuple[str, Any]]:
    candidates: list[tuple[str, Any]] = []
    if isinstance(data, dict):
        candidates.extend(_iter_choice_text_candidates(data))
        candidates.extend(_iter_named_text_candidates("root", data))
        response_data = data.get("responseData")
        if isinstance(response_data, dict):
            candidates.extend(_iter_named_text_candidates("responseData", response_data))
        elif isinstance(response_data, list):
            for index, item in enumerate(response_data):
                if isinstance(item, dict):
                    candidates.extend(_iter_named_text_candidates(f"responseData[{index}]", item))
    elif data not in (None, "", [], {}):
        candidates.append(("response", data))
    return candidates


def _iter_structured_candidate_sources(data: Any) -> list[tuple[str, dict[str, Any]]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(data, dict):
        return candidates
    for key in ("newVariables", "updateVarResult", "variableUpdate"):
        normalized = _coerce_variable_bucket(data.get(key))
        if normalized:
            candidates.append((key, normalized))
    response_data = data.get("responseData")
    if isinstance(response_data, dict):
        for key in ("variableUpdate", "newVariables", "updateVarResult"):
            normalized = _coerce_variable_bucket(response_data.get(key))
            if normalized:
                candidates.append((f"responseData.{key}", normalized))
        for key in ("output", "outputs"):
            value = response_data.get(key)
            if isinstance(value, dict):
                candidates.append((f"responseData.{key}", value))
    elif isinstance(response_data, list):
        for index, item in enumerate(response_data):
            if not isinstance(item, dict):
                continue
            for key in ("variableUpdate", "newVariables", "updateVarResult"):
                normalized = _coerce_variable_bucket(item.get(key))
                if normalized:
                    candidates.append((f"responseData[{index}].{key}", normalized))
            if isinstance(item.get("output"), dict):
                candidates.append((f"responseData[{index}].output", item["output"]))
            if isinstance(item.get("outputs"), dict):
                candidates.append((f"responseData[{index}].outputs", item["outputs"]))
    return candidates


def _iter_choice_text_candidates(data: dict[str, Any]) -> list[tuple[str, Any]]:
    candidates: list[tuple[str, Any]] = []
    choices = data.get("choices")
    if not isinstance(choices, list):
        return candidates
    for index, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict):
            content = _message_content_to_text(message.get("content"))
            if content:
                candidates.append((f"choices[{index}].message.content", content))
    return candidates


def _iter_named_text_candidates(
    prefix: str,
    data: dict[str, Any],
    *,
    _depth: int = 0,
) -> list[tuple[str, Any]]:
    candidates: list[tuple[str, Any]] = []
    for key in ("answerText", "textOutput", *TOOL_RESPONSE_TEXT_KEYS):
        value = data.get(key)
        if value not in (None, "", [], {}):
            candidates.append((f"{prefix}.{key}", value))
    for key in ("output", "outputs"):
        value = data.get(key)
        if isinstance(value, dict):
            candidates.extend(_iter_named_text_candidates(f"{prefix}.{key}", value, _depth=_depth + 1))
    if _depth >= 2:
        return candidates
    for key, value in data.items():
        if key in {
            "choices",
            "message",
            "content",
            "usage",
            "model",
            "id",
            "responseData",
            "newVariables",
            "updateVarResult",
            "variableUpdate",
            "toolCall",
            "pluginOutput",
        }:
            continue
        if isinstance(value, dict):
            candidates.extend(_iter_named_text_candidates(f"{prefix}.{key}", value, _depth=_depth + 1))
    return candidates


def _coerce_variable_bucket(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, list):
        return None
    normalized: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not isinstance(key, str) or not key.strip():
            variable = item.get("variable")
            if isinstance(variable, list) and len(variable) >= 2 and str(variable[1] or "").strip():
                key = str(variable[1]).strip()
            elif isinstance(variable, str) and variable.strip():
                key = variable.strip()
        if not isinstance(key, str) or not key.strip():
            continue
        if "value" in item:
            normalized[key.strip()] = item.get("value")
    return normalized or None


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return _message_content_to_text(content.get("text") or content.get("content"))
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                item_type = str(item.get("type") or "").strip().lower()
                if item_type and item_type != "text":
                    continue
                text = _message_content_to_text(item.get("text") or item.get("content"))
                if text:
                    parts.append(text)
            else:
                text = _message_content_to_text(item)
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _normalize_tool_output_value(value: Any) -> Any:
    normalized = _unwrap_jsonish_value(value)
    if isinstance(normalized, str):
        text = normalized.strip()
        if not text:
            return ""
        parsed = _parse_jsonish_text(text)
        if parsed is not None:
            return parsed
        return text
    if isinstance(normalized, list):
        if len(normalized) == 1:
            nested = _normalize_tool_output_value(normalized[0])
            if nested not in (None, "", [], {}):
                return nested
        return normalized
    return normalized


def _unwrap_jsonish_value(value: Any) -> Any:
    candidate = value
    for _ in range(3):
        if isinstance(candidate, dict):
            if isinstance(candidate.get("text"), str):
                candidate = candidate["text"]
                continue
            if isinstance(candidate.get("content"), str):
                candidate = candidate["content"]
                continue
            break
        if isinstance(candidate, list):
            text = _message_content_to_text(candidate)
            if text:
                candidate = text
                continue
            break
        if isinstance(candidate, str):
            text = strip_code_fence(candidate).strip()
            parsed = _parse_jsonish_text(text)
            if parsed is None:
                candidate = text
                break
            candidate = parsed
            continue
        break
    return candidate


def _parse_jsonish_text(text: str) -> Any | None:
    stripped = strip_code_fence(str(text or "")).strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except Exception:
        return None
    if isinstance(parsed, str) and parsed.strip() and parsed.strip()[0] in "[{":
        try:
            nested = json.loads(parsed)
        except Exception:
            return parsed.strip()
        return nested
    return parsed


def _env(*names: str) -> str | None:
    return _env_with_name(*names)[1]


def _env_with_name(*names: str) -> tuple[str | None, str | None]:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return name, str(value).strip()
    return None, None


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def _truncate_text(value: Any, *, limit: int = 200) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)
