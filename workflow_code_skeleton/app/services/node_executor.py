from __future__ import annotations

from typing import Any

from ..models.state import WorkflowState
from .json_utils import parse_json, to_pretty_json
from .llm_client import llm_client
from .workflow_spec import WorkflowSpec
from ..utils.logger import get_logger

logger = get_logger("node_executor")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def execute_chat_node(
    state: WorkflowState,
    spec: WorkflowSpec,
    node_id: str,
    *,
    expect_json: bool = False,
) -> str:
    runtime = state.runtime
    if runtime:
        runtime.before_node(node_id, state)

    system_prompt = _as_text(spec.render_input(node_id, "systemPrompt", state))
    user_prompt = _as_text(spec.render_input(node_id, "userChatInput", state))
    state.prompt_fixes = spec.get_prompt_fixes()

    model = state.preferred_model
    if not model and spec.has_input(node_id, "model"):
        raw_model = spec.render_input(node_id, "model", state)
        model = _as_text(raw_model).strip() or None

    provider = state.preferred_provider

    temperature = 0.7
    if spec.has_input(node_id, "temperature"):
        raw_temperature = spec.render_input(node_id, "temperature", state)
        if raw_temperature not in ("", None):
            temperature = float(raw_temperature)

    max_tokens = 4096
    if spec.has_input(node_id, "maxToken"):
        raw_max_tokens = spec.render_input(node_id, "maxToken", state)
        if raw_max_tokens not in ("", None):
            max_tokens = int(raw_max_tokens)

    logger.info("运行节点 %s", node_id)
    content = llm_client.chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    stored = content.strip()
    if expect_json:
        stored = to_pretty_json(parse_json(content))

    state.set_output(node_id, "answerText", stored)
    if runtime:
        runtime.after_node(node_id, state, stored)
    return stored


def execute_text_editor_node(
    state: WorkflowState,
    spec: WorkflowSpec,
    node_id: str,
) -> str:
    runtime = state.runtime
    if runtime:
        runtime.before_node(node_id, state)

    content = _as_text(spec.render_input(node_id, "system_textareaInput", state)).strip()
    state.prompt_fixes = spec.get_prompt_fixes()
    state.set_output(node_id, "system_text", content)

    if runtime:
        runtime.after_node(node_id, state, content)
    return content


def execute_answer_node(
    state: WorkflowState,
    spec: WorkflowSpec,
    node_id: str,
) -> str:
    runtime = state.runtime
    if runtime:
        runtime.before_node(node_id, state)

    content = _as_text(spec.render_input(node_id, "text", state)).strip()
    state.prompt_fixes = spec.get_prompt_fixes()
    state.set_output(node_id, "text", content)

    if runtime:
        runtime.after_node(node_id, state, content)
    return content
