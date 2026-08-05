from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import workflow_code_skeleton.app.services.platform_agent_openai_sdk as sdk_module


def test_api_base_url_accepts_all_supported_deepseek_shapes() -> None:
    assert sdk_module._api_base_url("https://example.test") == "https://example.test/v1"
    assert sdk_module._api_base_url("https://example.test/v1") == "https://example.test/v1"
    assert (
        sdk_module._api_base_url("https://example.test/v1/chat/completions")
        == "https://example.test/v1"
    )


def test_usage_payload_is_always_json_serializable() -> None:
    nested = SimpleNamespace(
        to_dict=lambda: {
            "total_tokens": 20,
            "details": SimpleNamespace(model_dump=lambda: {"reasoning_tokens": 4}),
        }
    )
    payload = sdk_module._usage_dict(nested)
    assert json.loads(json.dumps(payload)) == {
        "total_tokens": 20,
        "details": {"reasoning_tokens": 4},
    }


def test_sdk_runner_bridges_existing_json_tools(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeFunctionTool:
        def __init__(self, **kwargs):
            self.name = kwargs["name"]
            self.on_invoke_tool = kwargs["on_invoke_tool"]
            self.params_json_schema = kwargs["params_json_schema"]

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

    class FakeModel:
        def __init__(self, **kwargs):
            captured["model"] = kwargs

    class FakeAgent:
        def __init__(self, **kwargs):
            self.tools = kwargs["tools"]
            captured["agent"] = kwargs

    class FakeRunner:
        @staticmethod
        def run_sync(agent, input_items, **kwargs):
            captured["input"] = input_items
            captured["runner"] = kwargs
            context = SimpleNamespace(tool_call_id="call-123")
            output = asyncio.run(agent.tools[0].on_invoke_tool(context, '{"limit": 4}'))
            assert json.loads(output)["count"] == 1
            return SimpleNamespace(
                final_output="已经找到一个项目。",
                context_wrapper=SimpleNamespace(
                    usage={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}
                ),
            )

    monkeypatch.setattr(
        sdk_module,
        "_sdk_imports",
        lambda: {
            "Agent": FakeAgent,
            "AsyncOpenAI": FakeClient,
            "FunctionTool": FakeFunctionTool,
            "ModelSettings": lambda **kwargs: kwargs,
            "OpenAIChatCompletionsModel": FakeModel,
            "RunConfig": lambda **kwargs: kwargs,
            "Runner": FakeRunner,
        },
    )
    monkeypatch.setattr(
        sdk_module,
        "get_deepseek_agent_config",
        lambda: SimpleNamespace(
            configured=True,
            api_key="secret",
            base_url="https://deepseek.example/v1",
            model="deepseek-v4-pro",
            timeout_seconds=180,
        ),
    )

    calls: list[tuple[str, dict, str]] = []
    result = sdk_module.run_openai_agents_platform_turn(
        instructions="理解用户意图并调用工具。",
        messages=[
            {"role": "system", "content": "ignored"},
            {"role": "user", "content": "看看最近的项目"},
        ],
        tool_definitions=[
            {
                "type": "function",
                "function": {
                    "name": "list_projects",
                    "description": "列出项目",
                    "parameters": {
                        "type": "object",
                        "properties": {"limit": {"type": "integer"}},
                    },
                },
            }
        ],
        execute_tool=lambda name, arguments, call_id: (
            calls.append((name, arguments, call_id))
            or {"ok": True, "count": 1}
        ),
        max_turns=6,
        max_tokens=1200,
        group_id="conversation-1",
    )

    assert calls == [("list_projects", {"limit": 4}, "call-123")]
    assert result["content"] == "已经找到一个项目。"
    assert result["events"][0]["tool"] == "list_projects"
    assert result["usage"]["total_tokens"] == 20
    assert captured["input"] == [{"role": "user", "content": "看看最近的项目"}]
    assert captured["runner"]["max_turns"] == 6
    assert captured["runner"]["run_config"]["tracing_disabled"] is True


def test_sdk_raises_non_replayable_error_after_a_tool_side_effect(monkeypatch) -> None:
    class FakeFunctionTool:
        def __init__(self, **kwargs):
            self.on_invoke_tool = kwargs["on_invoke_tool"]

    class FakeAgent:
        def __init__(self, **kwargs):
            self.tools = kwargs["tools"]

    class FakeRunner:
        @staticmethod
        def run_sync(agent, input_items, **kwargs):
            context = SimpleNamespace(tool_call_id="call-side-effect")
            asyncio.run(agent.tools[0].on_invoke_tool(context, "{}"))
            raise RuntimeError("model disconnected")

    monkeypatch.setattr(
        sdk_module,
        "_sdk_imports",
        lambda: {
            "Agent": FakeAgent,
            "AsyncOpenAI": lambda **kwargs: object(),
            "FunctionTool": FakeFunctionTool,
            "ModelSettings": lambda **kwargs: kwargs,
            "OpenAIChatCompletionsModel": lambda **kwargs: object(),
            "RunConfig": lambda **kwargs: kwargs,
            "Runner": FakeRunner,
        },
    )
    monkeypatch.setattr(
        sdk_module,
        "get_deepseek_agent_config",
        lambda: SimpleNamespace(
            configured=True,
            api_key="secret",
            base_url="https://deepseek.example/v1",
            model="deepseek-v4-pro",
            timeout_seconds=180,
        ),
    )

    try:
        sdk_module.run_openai_agents_platform_turn(
            instructions="test",
            messages=[{"role": "user", "content": "run"}],
            tool_definitions=[
                {
                    "type": "function",
                    "function": {
                        "name": "pause_task",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            execute_tool=lambda name, arguments, call_id: {"ok": True},
            max_turns=3,
            max_tokens=400,
            group_id="conversation-2",
        )
    except sdk_module.PlatformAgentSdkError as exc:
        assert exc.tools_executed is True
        assert exc.events == [{"tool": "pause_task", "result": {"ok": True}}]
    else:
        raise AssertionError("Expected PlatformAgentSdkError")
