from __future__ import annotations

import copy
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

import requests

from ..config import settings
from .json_utils import strip_code_fence
from .simple_fastgpt_tools import DEFAULT_FASTGPT_URL, ToolExecutionError


DEDICATED_API_KEY_ENVS: tuple[str, ...] = (
    "FASTGPT_COUNT_ACTUAL_EPISODES_KEY",
    "FASTGPT_WRITE_CHARACTER_PROFILE_KEY",
    "FASTGPT_REVIEW_CHARACTER_PROFILE_KEY",
    "FASTGPT_REWRITE_CHARACTER_PROFILE_KEY",
    "FASTGPT_SORT_CHARACTER_PROFILE_KEY",
    "FASTGPT_WRITE_CHARACTER_DIALOGUE_KEY",
    "FASTGPT_REVIEW_CHARACTER_DIALOGUE_KEY",
    "FASTGPT_REWRITE_CHARACTER_DIALOGUE_KEY",
    "FASTGPT_WRITE_SCRIPT_BODY_KEY",
    "FASTGPT_REVIEW_SCRIPT_BODY_KEY",
    "FASTGPT_REWRITE_SCRIPT_BODY_KEY",
    "FASTGPT_SCRIPT_MEMORY_KEY",
)

URL_ENV = "FASTGPT_CHAT_COMPLETIONS_URL"
COMMON_TARGET_STYLE_KEYS = ["cUMhDqCG", "zz4re7zP", "target_style", "mubiao_fengge"]
STAGE_LABELS: dict[str, str] = {
    "actual_episode_count": "统计原剧本实际集数",
    "profile_write": "生成人设循环变量",
    "profile_review": "审核人设循环变量",
    "profile_rewrite": "修订人设循环变量",
    "profile_sort": "整理人设",
    "dialogue_write": "编写角色对话",
    "dialogue_review": "审核角色对话",
    "dialogue_rewrite": "修订角色对话",
    "body_write": "编写剧本正文",
    "body_review": "审核剧本正文",
    "body_rewrite": "修订剧本正文",
    "script_memory": "保存剧本记忆",
}

EXPECTED_VARIABLE_KEYS_BY_STAGE: dict[str, list[str]] = {
    "actual_episode_count": ["juben_zhengwen"],
    "profile_write": ["n5ZHYrj8", "ayxWwSpE", "yYYOuumm", "rxmvq2lS", *COMMON_TARGET_STYLE_KEYS],
    "profile_review": ["n5ZHYrj8", "ayxWwSpE", "fFM0mroW"],
    "profile_rewrite": ["n5ZHYrj8", "yYYOuumm", "ayxWwSpE", "va4Et1LA", "fFM0mroW", "zz4re7zP"],
    "profile_sort": ["n5ZHYrj8", "eBEWC07Q", "blkSS7dY", "ayxWwSpE", *COMMON_TARGET_STYLE_KEYS, "rxmvq2lS", "yYYOuumm", "pxtQY7p2", "fFM0mroW"],
    "dialogue_write": ["n5ZHYrj8", "eBEWC07Q", "blkSS7dY", "ayxWwSpE", *COMMON_TARGET_STYLE_KEYS, "rxmvq2lS", "yYYOuumm", "pxtQY7p2", "fFM0mroW", "sKq9Iyza"],
    "dialogue_review": ["n5ZHYrj8", "eBEWC07Q", "blkSS7dY", "ayxWwSpE", *COMMON_TARGET_STYLE_KEYS, "rxmvq2lS", "yYYOuumm", "pxtQY7p2", "fFM0mroW", "mN7Fh38L"],
    "dialogue_rewrite": [
        "n5ZHYrj8",
        "eBEWC07Q",
        "blkSS7dY",
        "ayxWwSpE",
        *COMMON_TARGET_STYLE_KEYS,
        "rxmvq2lS",
        "yYYOuumm",
        "pxtQY7p2",
        "fFM0mroW",
        "mN7Fh38L",
        "rZL0C6f9",
        "sKq9Iyza",
        "blkSS7dY",
    ],
    "body_write": [
        "n5ZHYrj8",
        "eBEWC07Q",
        "blkSS7dY",
        "ayxWwSpE",
        *COMMON_TARGET_STYLE_KEYS,
        "rxmvq2lS",
        "yYYOuumm",
        "pxtQY7p2",
        "fFM0mroW",
        "pS7JzosX",
        "d4sfifeZ",
        "bai4xfdD",
    ],
    "body_review": [
        "n5ZHYrj8",
        "eBEWC07Q",
        "blkSS7dY",
        "ayxWwSpE",
        *COMMON_TARGET_STYLE_KEYS,
        "rxmvq2lS",
        "yYYOuumm",
        "pxtQY7p2",
        "fFM0mroW",
        "pS7JzosX",
        "zS2LXibg",
        "d4sfifeZ",
        "ntBQgrAm",
    ],
    "body_rewrite": [
        "n5ZHYrj8",
        "eBEWC07Q",
        "blkSS7dY",
        "ayxWwSpE",
        *COMMON_TARGET_STYLE_KEYS,
        "rxmvq2lS",
        "yYYOuumm",
        "pxtQY7p2",
        "fFM0mroW",
        "pS7JzosX",
        "zS2LXibg",
        "gJT2URpY",
        "d4sfifeZ",
        "mcUdAISf",
    ],
    "script_memory": ["zS2LXibg"],
}


@dataclass(frozen=True, slots=True)
class StageSpec:
    stage: str
    api_env: str
    preferred_output_keys: tuple[str, ...] = ()
    json_output: bool = False


def diagnose_character_reskin_environment() -> dict[str, Any]:
    present = [name for name in DEDICATED_API_KEY_ENVS if _env(name)]
    missing = [name for name in DEDICATED_API_KEY_ENVS if name not in present]
    return {
        "tool_key": "character_reskin",
        "api_env": DEDICATED_API_KEY_ENVS[0],
        "missing_api_key_envs": missing,
        "present_api_key_envs": present,
        "api_key_present": not missing,
        "api_key_length": 0,
        "api_key_source": "dedicated_multi_stage" if present else "missing",
        "api_key_env_used": ",".join(present),
        "url_env": URL_ENV,
        "url_present": bool(_env(URL_ENV)),
        "expected_variable_keys_by_stage": copy.deepcopy(EXPECTED_VARIABLE_KEYS_BY_STAGE),
        "expected_variable_keys": sorted({key for keys in EXPECTED_VARIABLE_KEYS_BY_STAGE.values() for key in keys}),
        "request_variable_keys": [],
    }


def run_character_reskin_chain(user_payload: dict[str, Any]) -> dict[str, Any]:
    payload = user_payload if isinstance(user_payload, dict) else {}
    state = _initial_state(payload)
    debug: dict[str, Any] = {
        "stages": [],
        "missing_api_key_envs": [],
        "present_api_key_envs": [],
        "url_present": bool(_env(URL_ENV)),
        "expected_variable_keys_by_stage": copy.deepcopy(EXPECTED_VARIABLE_KEYS_BY_STAGE),
    }
    _validate_required_env(debug)

    actual_episode_count = _call_stage(
        StageSpec("actual_episode_count", "FASTGPT_COUNT_ACTUAL_EPISODES_KEY", ("kpoOTOUP",)),
        {
            "juben_zhengwen": state["source_script"],
        },
        debug,
    )
    state["actual_episodes_raw"] = str(actual_episode_count or "").strip()
    state["total_episodes"] = _normalize_actual_episode_count(state["actual_episodes_raw"], debug)

    profile_write = StageSpec(
        "profile_write",
        "FASTGPT_WRITE_CHARACTER_PROFILE_KEY",
        ("fFM0mroW",),
        json_output=True,
    )
    state["profile_json"] = _call_stage(
        profile_write,
        _profile_write_variables(state),
        debug,
    )

    profile_review = StageSpec("profile_review", "FASTGPT_REVIEW_CHARACTER_PROFILE_KEY", ("u3ymVRAj",), json_output=True)
    profile_rewrite = StageSpec(
        "profile_rewrite",
        "FASTGPT_REWRITE_CHARACTER_PROFILE_KEY",
        ("wQrZxzeL",),
        json_output=True,
    )
    for rewrite_index in range(0, 6):
        state["profile_review_json"] = _call_stage(
            profile_review,
            _profile_review_variables(state),
            debug,
        )
        if not _review_needs_rewrite(state["profile_review_json"]) or rewrite_index >= 5:
            break
        state["profile_json"] = _call_stage(
            profile_rewrite,
            _profile_rewrite_variables(state),
            debug,
        )

    profile_sort = StageSpec("profile_sort", "FASTGPT_SORT_CHARACTER_PROFILE_KEY", ("vVtCqEXZ",))
    state["profile_text"] = _call_stage(
        profile_sort,
        _with_common_variables(state, {
            "fFM0mroW": state["profile_json"],
            "yYYOuumm": state["source_characters"],
        }),
        debug,
    )

    for start_episode in range(1, int(state["total_episodes"]) + 1, 5):
        dialogue_write = StageSpec(
            "dialogue_write",
            "FASTGPT_WRITE_CHARACTER_DIALOGUE_KEY",
            ("mN7Fh38L",),
            json_output=True,
        )
        state["dialogue_json"] = _call_stage(
            dialogue_write,
            _with_common_variables(
                state,
                {
                "fFM0mroW": state["profile_json"],
                "sKq9Iyza": start_episode,
                },
            ),
            debug,
        )

        dialogue_review = StageSpec("dialogue_review", "FASTGPT_REVIEW_CHARACTER_DIALOGUE_KEY", json_output=True)
        dialogue_rewrite = StageSpec(
            "dialogue_rewrite",
            "FASTGPT_REWRITE_CHARACTER_DIALOGUE_KEY",
            ("mN7Fh38L",),
            json_output=True,
        )
        for rewrite_index in range(0, 6):
            state["dialogue_review_json"] = _call_stage(
                dialogue_review,
                _with_common_variables(
                    state,
                    {
                    "fFM0mroW": state["profile_json"],
                    "mN7Fh38L": state["dialogue_json"],
                    "sKq9Iyza": start_episode,
                    },
                ),
                debug,
            )
            if not _review_needs_rewrite(state["dialogue_review_json"]) or rewrite_index >= 5:
                break
            state["dialogue_json"] = _call_stage(
                dialogue_rewrite,
                _with_common_variables(
                    state,
                    {
                    "fFM0mroW": state["profile_json"],
                    "mN7Fh38L": state["dialogue_json"],
                    "rZL0C6f9": state["dialogue_review_json"],
                    "sKq9Iyza": start_episode,
                    },
                ),
                debug,
            )
        state["final_dialogue_json"] = state["dialogue_json"]

        body_write = StageSpec("body_write", "FASTGPT_WRITE_SCRIPT_BODY_KEY", ("zS2LXibg",))
        state["body_batch_text"] = _call_stage(
            body_write,
            _with_common_variables(
                state,
                {
                "fFM0mroW": state["profile_json"],
                "pS7JzosX": state["final_dialogue_json"],
                "d4sfifeZ": start_episode,
                "bai4xfdD": state["script_memory_json"],
                },
            ),
            debug,
        )

        body_review = StageSpec("body_review", "FASTGPT_REVIEW_SCRIPT_BODY_KEY", json_output=True)
        body_rewrite = StageSpec("body_rewrite", "FASTGPT_REWRITE_SCRIPT_BODY_KEY", ("zS2LXibg",))
        for rewrite_index in range(0, 6):
            state["body_review_json"] = _call_stage(
                body_review,
                _with_common_variables(
                    state,
                    {
                    "fFM0mroW": state["profile_json"],
                    "pS7JzosX": state["final_dialogue_json"],
                    "zS2LXibg": state["body_batch_text"],
                    "d4sfifeZ": start_episode,
                    "ntBQgrAm": state["script_memory_json"],
                    },
                ),
                debug,
            )
            if not _review_needs_rewrite(state["body_review_json"]) or rewrite_index >= 5:
                break
            state["body_batch_text"] = _call_stage(
                body_rewrite,
                _with_common_variables(
                    state,
                    {
                    "fFM0mroW": state["profile_json"],
                    "pS7JzosX": state["final_dialogue_json"],
                    "zS2LXibg": state["body_batch_text"],
                    "gJT2URpY": state["body_review_json"],
                    "d4sfifeZ": start_episode,
                    "mcUdAISf": state["script_memory_json"],
                    },
                ),
                debug,
            )

        memory = StageSpec("script_memory", "FASTGPT_SCRIPT_MEMORY_KEY", ("vxkKH1SV",), json_output=True)
        state["script_memory_json"] = _call_stage(
            memory,
            {
                "zS2LXibg": state["body_batch_text"],
            },
            debug,
        )
        state["script_batches"].append(state["body_batch_text"])

    state["final_output_text"] = "\n\n".join(str(item).strip() for item in state["script_batches"] if str(item).strip())
    if not state["final_output_text"].strip():
        raise ToolExecutionError(
            "只换人设工具没有生成最终剧本正文。",
            tool_id="character_reskin",
            debug=debug,
            status_code=502,
        )

    return {
        "ok": True,
        "success": True,
        "tool_id": "character_reskin",
        "title": "只换人设",
        "output": state["final_output_text"],
        "text": state["final_output_text"],
        "final_output_text": state["final_output_text"],
        "character_profile": state["profile_text"],
        "character_profile_json": state["profile_json"],
        "script_batches": state["script_batches"],
        "output_type": "text",
        "filename": _filename(state["title"]),
        "debug": debug,
    }


def _initial_state(payload: dict[str, Any]) -> dict[str, Any]:
    title = _first_text(payload, "title", "ju_ben_biao_ti", "script_title")
    source_outline = _first_text(payload, "source_outline", "yuan_juben_genggai", "outline", "story_outline")
    target_style = _first_text(payload, "cUMhDqCG", "zz4re7zP", "target_style", "mubiao_fengge", "style")
    state = {
        "title": title,
        "episode_word_count": _first_positive_int(payload, 600, "episode_word_count", "meiji_zishu"),
        "total_episodes": _first_positive_int(payload, 50, "total_episodes", "zong_jishu"),
        "source_outline": source_outline,
        "target_style": target_style,
        "core_scenes": _first_text(payload, "core_scenes", "hexin_changjing"),
        "source_characters": _first_text(payload, "source_characters", "renwu_xiaozhuan", "characters"),
        "source_script": _first_text(payload, "source_script", "juben_zhengwen", "script"),
        "actual_episodes_raw": "",
        "profile_json": "",
        "profile_review_json": "",
        "profile_text": "",
        "dialogue_json": "",
        "dialogue_review_json": "",
        "final_dialogue_json": "",
        "script_memory_json": "",
        "body_batch_text": "",
        "body_review_json": "",
        "script_batches": [],
        "final_output_text": "",
    }
    missing = [key for key in ("title", "source_characters", "source_script") if not state[key]]
    if not source_outline:
        missing.append("source_outline")
    if missing:
        raise ToolExecutionError(
            f"只换人设缺少必填项：{', '.join(missing)}",
            tool_id="character_reskin",
            debug={"missing_fields": missing},
            status_code=400,
        )
    return state


def _common_variables(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "n5ZHYrj8": state["title"],
        "eBEWC07Q": state["episode_word_count"],
        "blkSS7dY": state["total_episodes"],
        "ayxWwSpE": state["source_outline"],
        "cUMhDqCG": state["target_style"],
        "zz4re7zP": state["target_style"],
        "target_style": state["target_style"],
        "mubiao_fengge": state["target_style"],
        "rxmvq2lS": state["core_scenes"],
        "yYYOuumm": state["source_characters"],
        "pxtQY7p2": state["source_script"],
    }


def _profile_write_variables(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "n5ZHYrj8": state["title"],
        "ayxWwSpE": state["source_outline"],
        "yYYOuumm": state["source_characters"],
        "rxmvq2lS": state["core_scenes"],
        "cUMhDqCG": state["target_style"],
        "zz4re7zP": state["target_style"],
        "target_style": state["target_style"],
        "mubiao_fengge": state["target_style"],
    }


def _profile_review_variables(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "n5ZHYrj8": state["title"],
        "ayxWwSpE": state["source_outline"],
        "fFM0mroW": state["profile_json"],
    }


def _profile_rewrite_variables(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "n5ZHYrj8": state["title"],
        "yYYOuumm": state["source_characters"],
        "ayxWwSpE": state["source_outline"],
        "va4Et1LA": state["profile_review_json"],
        "fFM0mroW": state["profile_json"],
        "zz4re7zP": state["target_style"],
    }


def _with_common_variables(state: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    variables = _common_variables(state)
    variables.update(extra or {})
    return variables


def _call_stage(spec: StageSpec, variables: dict[str, Any], debug: dict[str, Any]) -> Any:
    api_key = _env(spec.api_env)
    url = str(_env(URL_ENV) or DEFAULT_FASTGPT_URL).strip().rstrip("/")
    variable_keys = list(variables.keys())
    stage_debug: dict[str, Any] = {
        "stage": spec.stage,
        "stage_label": STAGE_LABELS.get(spec.stage, spec.stage),
        "api_env": spec.api_env,
        "request_variable_keys": variable_keys,
        "output_source": "",
    }
    debug.setdefault("stages", []).append(stage_debug)
    body = {
        "chatId": f"scriptmaker-character-reskin-{spec.stage}-{uuid.uuid4().hex[:8]}",
        "stream": False,
        "detail": True,
        "variables": copy.deepcopy(variables),
        "messages": [{"role": "user", "content": f"请执行只换人设多阶段链路：{spec.stage}。"}],
    }
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=int(getattr(settings, "fastgpt_timeout", 300)),
        )
    except requests.RequestException as exc:
        stage_debug["response_preview"] = _truncate(str(exc), 800)
        raise ToolExecutionError(
            f"只换人设阶段 {spec.stage} 请求失败。",
            tool_id="character_reskin",
            debug=debug,
            status_code=502,
        ) from exc

    response_preview = _truncate(response.text, 1200)
    stage_debug["response_preview"] = response_preview
    if int(response.status_code or 0) >= 400:
        raise ToolExecutionError(
            f"只换人设阶段 {spec.stage} 请求失败（HTTP {response.status_code}）。",
            tool_id="character_reskin",
            debug=debug,
            status_code=400,
        )
    try:
        data = response.json()
    except Exception as exc:
        raise ToolExecutionError(
            f"只换人设阶段 {spec.stage} 返回了无法解析的响应。",
            tool_id="character_reskin",
            debug=debug,
            status_code=502,
        ) from exc

    value, source = _extract_stage_output(data, spec.preferred_output_keys)
    if _is_blank(value):
        stage_debug["response_preview"] = _truncate(_json_text(data), 1200)
        raise ToolExecutionError(
            f"只换人设阶段 {spec.stage} 返回空输出。",
            tool_id="character_reskin",
            debug=debug,
            status_code=502,
        )
    stage_debug["output_source"] = source
    if spec.json_output:
        parsed, warning = _parse_json_stage_value(value)
        if warning:
            stage_debug["parse_warning"] = warning
        return parsed
    return _render_text(value)


def _extract_stage_output(data: Any, preferred_keys: tuple[str, ...]) -> tuple[Any, str]:
    for source, bucket in _iter_variable_buckets(data):
        for key in preferred_keys:
            if key in bucket and not _is_blank(bucket[key]):
                return bucket[key], f"{source}.{key}"
    for key in preferred_keys:
        if isinstance(data, dict) and key in data and not _is_blank(data[key]):
            return data[key], f"root.{key}"
    for source, bucket in _iter_variable_buckets(data):
        for key, value in bucket.items():
            if not _is_blank(value):
                return value, f"{source}.{key}"
    for source, value in _iter_text_candidates(data):
        if not _is_blank(value):
            return value, source
    return "", ""


def _iter_variable_buckets(data: Any) -> list[tuple[str, dict[str, Any]]]:
    buckets: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(data, dict):
        return buckets
    response_data = data.get("responseData")
    if isinstance(response_data, dict):
        for key in ("updateVarResult", "variableUpdate", "newVariables"):
            bucket = _coerce_variable_bucket(response_data.get(key))
            if bucket:
                buckets.append((f"responseData.{key}", bucket))
    elif isinstance(response_data, list):
        for index, item in enumerate(response_data):
            if not isinstance(item, dict):
                continue
            for key in ("updateVarResult", "variableUpdate", "newVariables"):
                bucket = _coerce_variable_bucket(item.get(key))
                if bucket:
                    buckets.append((f"responseData[{index}].{key}", bucket))
    for key in ("newVariables", "updateVarResult", "variableUpdate"):
        bucket = _coerce_variable_bucket(data.get(key))
        if bucket:
            buckets.append((key, bucket))
    return buckets


def _coerce_variable_bucket(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, list):
        return {}
    bucket: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        variable = item.get("variable")
        if not key and isinstance(variable, list) and len(variable) >= 2:
            key = str(variable[1] or "").strip()
        if not key and isinstance(variable, str):
            key = variable.strip()
        if key and "value" in item:
            bucket[key] = item.get("value")
    return bucket


def _iter_text_candidates(data: Any) -> list[tuple[str, Any]]:
    if not isinstance(data, dict):
        return [("response", data)]
    candidates: list[tuple[str, Any]] = []
    response_data = data.get("responseData")
    if isinstance(response_data, list):
        for index, item in enumerate(response_data):
            if isinstance(item, dict):
                candidates.extend(_named_text_candidates(f"responseData[{index}]", item))
    elif isinstance(response_data, dict):
        candidates.extend(_named_text_candidates("responseData", response_data))
    candidates.extend(_named_text_candidates("root", data))
    choices = data.get("choices")
    if isinstance(choices, list):
        for index, choice in enumerate(choices):
            if isinstance(choice, dict):
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if not _is_blank(content):
                        candidates.append((f"choices[{index}].message.content", content))
    return candidates


def _named_text_candidates(prefix: str, data: dict[str, Any]) -> list[tuple[str, Any]]:
    candidates: list[tuple[str, Any]] = []
    for key in ("answerText", "textOutput", "answer", "content", "text", "response", "result"):
        if key in data and not _is_blank(data[key]):
            candidates.append((f"{prefix}.{key}", data[key]))
    return candidates


def _parse_json_stage_value(value: Any) -> tuple[Any, str]:
    if not isinstance(value, str):
        return value, ""
    text = strip_code_fence(value).strip()
    try:
        return json.loads(text), ""
    except Exception:
        return text, "json.loads failed; kept raw text"


def _review_needs_rewrite(value: Any) -> bool:
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(strip_code_fence(value).strip())
        except Exception:
            return False
    if not isinstance(parsed, dict):
        return False
    if parsed.get("rewrite_required") is True:
        return True
    if parsed.get("passed") is False:
        return True
    if parsed.get("pass") is False:
        return True
    return False


def _normalize_actual_episode_count(value: Any, debug: dict[str, Any]) -> int:
    text = str(value or "").strip()
    debug["actual_episodes_raw"] = text
    if text.upper() == "X":
        raise ToolExecutionError(
            "原剧本正文存在跳集、漏集或残缺内容，请补全所有集数后再运行只换人设。",
            tool_id="character_reskin",
            debug=debug,
            status_code=400,
        )
    if text == "0":
        raise ToolExecutionError(
            "原剧本正文为空或未识别到有效集数，请先粘贴完整原剧本正文。",
            tool_id="character_reskin",
            debug=debug,
            status_code=400,
        )
    try:
        number = int(text)
    except Exception as exc:
        raise ToolExecutionError(
            f"实际集数检查返回无效结果：{text or '空'}。请检查统计实际集数 workflow 是否只输出非零自然数、0 或 X。",
            tool_id="character_reskin",
            debug=debug,
            status_code=502,
        ) from exc
    if number <= 0:
        raise ToolExecutionError(
            f"实际集数检查返回无效结果：{text}。请检查统计实际集数 workflow。",
            tool_id="character_reskin",
            debug=debug,
            status_code=502,
        )
    debug["actual_episodes"] = number
    return number


def _validate_required_env(debug: dict[str, Any]) -> None:
    present = [name for name in DEDICATED_API_KEY_ENVS if _env(name)]
    missing = [name for name in DEDICATED_API_KEY_ENVS if name not in present]
    debug["present_api_key_envs"] = present
    debug["missing_api_key_envs"] = missing
    if missing:
        raise ToolExecutionError(
            "只换人设缺少 FastGPT 阶段 API Key：" + ", ".join(missing),
            tool_id="character_reskin",
            debug=debug,
            status_code=400,
        )


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _first_positive_int(payload: dict[str, Any], default: int, *keys: str) -> int:
    for key in keys:
        value = payload.get(key)
        if value is None or str(value).strip() == "":
            continue
        try:
            number = float(value)
        except Exception:
            continue
        if number.is_integer() and number > 0:
            return int(number)
    return default


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return value in ([], {})


def _render_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        return str(value).strip()


def _filename(title: str) -> str:
    safe = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in str(title or "").strip()).strip(" ._")
    return f"只换人设_{(safe or '剧本')[:60]}.txt"


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= limit else f"{text[:limit]}..."


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _env(name: str) -> str:
    return str(os.getenv(name) or "").strip()
