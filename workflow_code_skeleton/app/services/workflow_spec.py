from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..models.state import WorkflowState
from .json_utils import to_pretty_json
from .prompt_normalizer import PromptFix, normalize_prompt

_PLACEHOLDER_PATTERN = re.compile(r"\{\{\$(.+?)\$\}\}")


class WorkflowSpec:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        raw_text = self.path.read_text(encoding="utf-8-sig")
        self.raw: dict[str, Any] = json.loads(raw_text)
        self.nodes: dict[str, dict[str, Any]] = {
            node["nodeId"]: node for node in self.raw.get("nodes", [])
        }
        self.variables: dict[str, dict[str, Any]] = {
            item["key"]: item
            for item in self.raw.get("chatConfig", {}).get("variables", [])
        }
        self.prompt_fixes: dict[tuple[str, str], list[PromptFix]] = {}

    def get_default_variables(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {}
        for key, variable in self.variables.items():
            if "defaultValue" in variable:
                defaults[key] = variable["defaultValue"]
                continue

            value_type = variable.get("valueType")
            if value_type == "number":
                defaults[key] = 0
            elif value_type in {"arrayString", "arrayNumber", "arrayBoolean", "arrayAny"}:
                defaults[key] = []
            elif value_type == "boolean":
                defaults[key] = False
            else:
                defaults[key] = ""
        return defaults

    def has_input(self, node_id: str, key: str) -> bool:
        return any(item.get("key") == key for item in self.nodes[node_id].get("inputs", []))

    def get_node_name(self, node_id: str) -> str:
        return str(self.nodes.get(node_id, {}).get("name", node_id))

    def list_chat_models(self) -> list[str]:
        models: list[str] = []
        for node in self.nodes.values():
            if node.get("flowNodeType") != "chatNode":
                continue
            for item in node.get("inputs", []):
                if item.get("key") == "model" and item.get("value"):
                    models.append(str(item["value"]).strip())
        return sorted({model for model in models if model})

    def get_prompt_fixes(self) -> list[dict[str, str]]:
        seen: set[tuple[str, str, str]] = set()
        fixes: list[dict[str, str]] = []
        for (node_id, input_key), fix_items in self.prompt_fixes.items():
            for item in fix_items:
                key = (node_id, input_key, item.description)
                if key in seen:
                    continue
                seen.add(key)
                fixes.append(
                    {
                        "node_id": node_id,
                        "node_name": self.get_node_name(node_id),
                        "input_key": input_key,
                        "description": item.description,
                    }
                )
        return fixes

    def get_input_value(self, node_id: str, key: str) -> Any:
        for item in self.nodes[node_id].get("inputs", []):
            if item.get("key") == key:
                value = item.get("value")
                if isinstance(value, str):
                    normalized, fixes = normalize_prompt(node_id, key, value)
                    if fixes:
                        self.prompt_fixes.setdefault((node_id, key), []).extend(fixes)
                    return normalized
                return value
        raise KeyError(f"Node {node_id} does not have input '{key}'")

    def render_input(self, node_id: str, key: str, state: WorkflowState) -> Any:
        return self.render_value(self.get_input_value(node_id, key), state)

    def render_value(self, value: Any, state: WorkflowState) -> Any:
        if value is None:
            return ""
        if isinstance(value, str):
            return self.render_text(value, state)
        if (
            isinstance(value, list)
            and len(value) == 2
            and all(isinstance(item, str) for item in value)
        ):
            return self.resolve_reference(value[0], value[1], state)
        if isinstance(value, list):
            return [self.render_value(item, state) for item in value]
        if isinstance(value, dict):
            return {key: self.render_value(item, state) for key, item in value.items()}
        return value

    def render_text(self, text: str, state: WorkflowState) -> str:
        def _replace(match: re.Match[str]) -> str:
            expression = match.group(1)
            if "." not in expression:
                return match.group(0)

            source, key = expression.split(".", 1)
            value = self.resolve_reference(source, key, state)
            return self.stringify(value)

        return _PLACEHOLDER_PATTERN.sub(_replace, text)

    def resolve_reference(self, source: str, key: str, state: WorkflowState) -> Any:
        if source == "VARIABLE_NODE_ID":
            return state.get_var(key, "")
        return state.get_output(source, key, "")

    def stringify(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return to_pretty_json(value)
        return str(value)
