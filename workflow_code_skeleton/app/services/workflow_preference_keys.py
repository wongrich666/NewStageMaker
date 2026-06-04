from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PREFERENCE_LABEL = "用户偏好提示词"

FALLBACK_PREFERENCE_KEYS: dict[str, tuple[str, ...]] = {
    "08": ("gsf2Zudx",),
    "09": ("oDaFpjKr",),
    "10": ("shmRs8OT",),
    "11_write": ("tFeUfwch",),
    "11_rewrite": ("sfQm5kD7",),
    "12_write": ("xOgb7piW",),
    "12_rewrite": ("ls0n1182",),
}

FRAMEWORK_TO_SCRIPT_STAGE_PREFS: dict[str, dict[str, Any]] = {
    "08": {
        "stage_prompt_key": "scene",
        "workflow_keys": ["gsf2Zudx"],
    },
    "09": {
        "stage_prompt_key": "appearance",
        "workflow_keys": ["oDaFpjKr"],
    },
    "10": {
        "stage_prompt_key": "episode",
        "workflow_keys": ["shmRs8OT"],
    },
    "11_write": {
        "stage_prompt_key": "conflict",
        "workflow_keys": ["tFeUfwch"],
    },
    "11_rewrite": {
        "stage_prompt_key": "conflict",
        "workflow_keys": ["sfQm5kD7"],
    },
    "12_write": {
        "stage_prompt_key": "script_text",
        "workflow_keys": ["xOgb7piW"],
    },
    "12_rewrite": {
        "stage_prompt_key": "script_text",
        "workflow_keys": ["ls0n1182"],
    },
}

COMMON_PREFERENCE_KEYS: tuple[str, ...] = (
    "stagePreference",
    "stage_preference",
    "stage_preference_prompt",
    "userPreference",
    "user_preferences",
    "userPreferences",
    "user_stage_preference_prompt",
    "userRequirements",
    "user_constraints",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _workflow_root() -> Path:
    return _repo_root() / "BETTER_FRAMEWORK_JSONS"


def _logical_stage_from_path(path: Path) -> str:
    name = path.name
    parent = path.parent.name
    if name.startswith("08_"):
        return "08"
    if name.startswith("09_"):
        return "09"
    if name.startswith("10_"):
        return "10"
    if "开头冲突钩子" in parent:
        if name.startswith("01"):
            return "11_write"
        if name.startswith("03"):
            return "11_rewrite"
    if "正文及对话" in parent:
        if name.startswith("01"):
            return "12_write"
        if name.startswith("03"):
            return "12_rewrite"
    return ""


def _iter_objects(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _iter_objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_objects(item)


def _preference_keys_from_json(path: Path) -> tuple[str, ...]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return ()
    keys: list[str] = []

    chat_config = data.get("chatConfig") if isinstance(data, dict) else {}
    variables = chat_config.get("variables") if isinstance(chat_config, dict) else []
    search_items = variables if isinstance(variables, list) else []
    if not search_items:
        search_items = list(_iter_objects(data))

    for item in search_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("label") or "").strip() != PREFERENCE_LABEL:
            continue
        key = str(item.get("key") or "").strip()
        if key and key not in keys:
            keys.append(key)
    return tuple(keys)


@lru_cache(maxsize=1)
def scanned_preference_key_map() -> dict[str, tuple[str, ...]]:
    root = _workflow_root()
    result: dict[str, list[str]] = {}
    if root.exists():
        for path in sorted(root.rglob("*.json")):
            logical_stage = _logical_stage_from_path(path)
            if not logical_stage:
                continue
            for key in _preference_keys_from_json(path):
                result.setdefault(logical_stage, [])
                if key not in result[logical_stage]:
                    result[logical_stage].append(key)
    merged: dict[str, tuple[str, ...]] = {}
    for stage, fallback_keys in FALLBACK_PREFERENCE_KEYS.items():
        keys = result.get(stage) or list(fallback_keys)
        merged[stage] = tuple(keys)
    return merged


def preference_keys_for(logical_stage: str) -> tuple[str, ...]:
    return scanned_preference_key_map().get(str(logical_stage or ""), ())


def framework_to_script_stage_pref(logical_stage: str) -> dict[str, Any]:
    return dict(FRAMEWORK_TO_SCRIPT_STAGE_PREFS.get(str(logical_stage or ""), {}))


def stage_prompt_key_for(logical_stage: str) -> str:
    return str(framework_to_script_stage_pref(logical_stage).get("stage_prompt_key") or "")


def inject_stage_preference(
    variables: dict[str, Any],
    preference_text: str,
    workflow_keys: list[str] | tuple[str, ...],
) -> None:
    text = str(preference_text or "").strip()
    for key in workflow_keys:
        if key:
            variables[str(key)] = text
    for key in COMMON_PREFERENCE_KEYS:
        variables[key] = text


def all_preference_wire_keys() -> tuple[str, ...]:
    keys: list[str] = list(COMMON_PREFERENCE_KEYS)
    for stage_keys in scanned_preference_key_map().values():
        for key in stage_keys:
            if key not in keys:
                keys.append(key)
    return tuple(keys)
