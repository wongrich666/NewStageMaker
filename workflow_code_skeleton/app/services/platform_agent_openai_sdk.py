from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from .deepseek_agent import get_deepseek_agent_config


class PlatformAgentSdkError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        tools_executed: bool = False,
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.tools_executed = tools_executed
        self.events = list(events or [])


def _sdk_imports() -> dict[str, Any] | None:
    try:
        from agents import (
            Agent,
            FunctionTool,
            ModelSettings,
            OpenAIChatCompletionsModel,
            RunConfig,
            Runner,
        )
        from openai import AsyncOpenAI
    except ImportError:
        return None
    return {
        "Agent": Agent,
        "AsyncOpenAI": AsyncOpenAI,
        "FunctionTool": FunctionTool,
        "ModelSettings": ModelSettings,
        "OpenAIChatCompletionsModel": OpenAIChatCompletionsModel,
        "RunConfig": RunConfig,
        "Runner": Runner,
    }


def agents_sdk_available() -> bool:
    return _sdk_imports() is not None


def configured_agent_engine() -> str:
    value = str(os.getenv("PLATFORM_AGENT_ENGINE") or "auto").strip().lower().replace("-", "_")
    if value in {"legacy", "openai_agents", "auto"}:
        return value
    return "auto"


def _api_base_url(base_url: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    if value.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")].rstrip("/")
    if not value.endswith("/v1"):
        value = f"{value}/v1"
    return value


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return str(value)


def _usage_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        result = _json_safe(value.to_dict())
        return result if isinstance(result, dict) else {}
    if is_dataclass(value):
        result = _json_safe(asdict(value))
        return result if isinstance(result, dict) else {}
    if isinstance(value, dict):
        return _json_safe(value)
    return _json_safe({
        key: getattr(value, key)
        for key in ("requests", "input_tokens", "output_tokens", "total_tokens")
        if getattr(value, key, None) is not None
    })


def _input_items(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = str(message.get("content") or "")
        if content:
            items.append({"role": role, "content": content})
    return items


def run_openai_agents_platform_turn(
    *,
    instructions: str,
    messages: list[dict[str, Any]],
    tool_definitions: list[dict[str, Any]],
    execute_tool: Callable[[str, dict[str, Any], str], dict[str, Any]],
    max_turns: int,
    max_tokens: int,
    group_id: str,
) -> dict[str, Any]:
    sdk = _sdk_imports()
    if sdk is None:
        raise PlatformAgentSdkError("OpenAI Agents SDK 尚未安装。")

    config = get_deepseek_agent_config()
    if not config.configured:
        raise PlatformAgentSdkError("剧本 Agent 尚未配置完成。")

    executed = False
    events: list[dict[str, Any]] = []
    function_tools: list[Any] = []
    FunctionTool = sdk["FunctionTool"]

    for definition in tool_definitions:
        function = definition.get("function") if isinstance(definition, dict) else None
        if not isinstance(function, dict):
            continue
        tool_name = str(function.get("name") or "").strip()
        if not tool_name:
            continue

        async def invoke(context: Any, raw_arguments: str, *, name: str = tool_name) -> str:
            nonlocal executed
            try:
                arguments = json.loads(raw_arguments or "{}")
                if not isinstance(arguments, dict):
                    arguments = {}
            except json.JSONDecodeError:
                arguments = {}
            call_id = str(getattr(context, "tool_call_id", "") or "")
            result = execute_tool(name, arguments, call_id)
            executed = True
            events.append({"tool": name, "result": result})
            return json.dumps(result, ensure_ascii=False, default=str)

        function_tools.append(
            FunctionTool(
                name=tool_name,
                description=str(function.get("description") or ""),
                params_json_schema=(
                    dict(function.get("parameters"))
                    if isinstance(function.get("parameters"), dict)
                    else {"type": "object", "properties": {}}
                ),
                on_invoke_tool=invoke,
                strict_json_schema=False,
            )
        )

    try:
        client = sdk["AsyncOpenAI"](
            api_key=config.api_key,
            base_url=_api_base_url(config.base_url),
            timeout=float(config.timeout_seconds),
            max_retries=0,
        )
        model = sdk["OpenAIChatCompletionsModel"](
            model=config.model,
            openai_client=client,
            buffer_streamed_tool_calls=True,
        )
        agent = sdk["Agent"](
            name="IDEA TO SCRIPT 剧本 Agent",
            instructions=instructions,
            tools=function_tools,
            model=model,
            model_settings=sdk["ModelSettings"](
                temperature=0.15,
                max_tokens=max_tokens,
                parallel_tool_calls=False,
            ),
        )
        result = sdk["Runner"].run_sync(
            agent,
            _input_items(messages),
            max_turns=max_turns,
            run_config=sdk["RunConfig"](
                tracing_disabled=True,
                workflow_name="IDEA TO SCRIPT Platform Agent",
                group_id=group_id,
            ),
        )
    except Exception as exc:
        raise PlatformAgentSdkError(
            f"Agents SDK 调用失败：{exc}",
            tools_executed=executed,
            events=events,
        ) from exc

    awaiting = next(
        (
            event["result"]
            for event in reversed(events)
            if isinstance(event.get("result"), dict) and event["result"].get("awaiting_user_input")
        ),
        None,
    )
    final_output = str(result.final_output or "").strip()
    if isinstance(awaiting, dict):
        final_output = str(awaiting.get("question") or final_output).strip()
    return {
        "content": final_output,
        "events": events,
        "usage": _usage_dict(getattr(result.context_wrapper, "usage", None)),
        "model": config.model,
        "engine": "openai_agents",
    }
