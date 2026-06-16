from __future__ import annotations

import json
import os
import re
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
import yaml

from ..config import settings
from ..utils.logger import get_logger
from .json_utils import parse_json, strip_code_fence
from .runtime_paths import get_runtime_data_dir
from .coze_defaults import (
    DEFAULT_NS_API_BASE,
    DEFAULT_NS_HTTP_RETRIES,
    DEFAULT_NS_HTTP_RETRY_DELAY_SECONDS,
    DEFAULT_NS_TIMEOUT_SECONDS,
    DEFAULT_NS_WORKFLOW_URL,
    FRAMEWORK_PLANNER_WORKFLOW_IDS,
)
from .workflow_output_parser import (
    parse_workflow_output,
    safe_truncated_preview,
    wrap_payload_for_expected_output,
)

logger = get_logger("framework_planner_service")

DEFAULT_FASTGPT_URL = "https://api.fastgpt.in/api/v1/chat/completions"
FRAMEWORK_PLANNER_STORAGE_KEY = "frameworkPlannerState.v2"
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
FRAMEWORK_CONTRACT_GLOB = "00_*.md"
FASTGPT_RAW_RESPONSE_KEYS = (
    "responseData",
    "reasoningText",
    "historyPreview",
    "raw",
    "answerText",
    "display_text",
    "choices",
    "usage",
)
FRAMEWORK_BUSINESS_FIELDS = {
    "source_brief",
    "worldview_plan",
    "character_plan",
    "beat_checkpoint_timeline",
    "checkpoint_explanation",
    "character_storylines",
    "storyline_decisions",
    "adaptation_guide",
    "framework_plan_package",
    "validation_report",
}
STAGE_DEBUG_PREVIEW_LIMIT = 200
FRAMEWORK_BUSINESS_LIST_FIELDS = {
    "beat_checkpoint_timeline",
    "character_storylines",
    "storyline_decisions",
}
STAGE_05_INPUT_LENGTH_LIMITS = {
    "source_brief": 30000,
    "basic_config": 10000,
    "worldview_plan": 50000,
    "character_plan": 80000,
    "beat_checkpoint_timeline": 80000,
}
REQUIRED_BEAT_FIELDS = (
    "beat_no",
    "beat_name",
    "act",
    "episode_range",
    "checkpoint_title",
    "narrative_function",
    "plot_content",
    "character_change",
    "conflict_upgrade",
    "hook_or_reversal",
    "linked_storylines",
)
FIFTEEN_BEAT_NAMES = (
    "开场",
    "主体呈现",
    "铺垫",
    "推动催化剂",
    "争执",
    "第二幕衔接点",
    "B故事线",
    "游戏及斗争",
    "中点",
    "危险逼近",
    "一败涂地",
    "灵魂黑夜",
    "第三幕衔接点",
    "结局",
    "终场画面",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _safe_project_history_name(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
    text = re.sub(r"\s+", "_", text).strip("._ ")
    return text[:80] or "未命名项目"


def _payload_project_name(payload: Any) -> str:
    """
    提取 payload 中可用的项目名，确保不会返回空。
    """
    if not isinstance(payload, dict):
        return "未命名项目"
    for key in ("project_title", "project_name", "title", "source_title", "script_title", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for container_name in ("basic_config", "input_payload", "asset", "project", "source_brief"):
        container = payload.get(container_name)
        if isinstance(container, dict):
            for key in ("project_title", "project_name", "title", "source_title", "script_title", "name"):
                value = container.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    asset_state = payload.get("asset_state")
    if isinstance(asset_state, dict):
        for key in ("project_title", "title", "source_title", "name"):
            value = asset_state.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    project_id = payload.get("project_id")
    if project_id not in (None, "", 0, "0"):
        text = str(project_id).strip()
        if text and text.lower() != "unsaved":
            return f"project_{text}" if text.isdigit() else text
    return "未命名项目"


def _ensure_payload_project_title(payload: Any, project_id: Any = None) -> dict[str, Any]:
    source = dict(payload) if isinstance(payload, dict) else {}
    if project_id not in (None, "") and source.get("project_id") in (None, ""):
        source["project_id"] = project_id
    project_name = _payload_project_name(source)
    if not str(source.get("project_title") or "").strip():
        source["project_title"] = project_name
    if not str(source.get("title") or "").strip():
        source["title"] = project_name
    if not str(source.get("source_title") or "").strip():
        source["source_title"] = project_name
    basic_config = source.get("basic_config")
    if isinstance(basic_config, dict):
        basic = dict(basic_config)
        if not str(basic.get("project_title") or "").strip():
            basic["project_title"] = project_name
        if not str(basic.get("title") or "").strip():
            basic["title"] = project_name
        if not str(basic.get("source_title") or "").strip():
            basic["source_title"] = project_name
        source["basic_config"] = basic
    return source


def _project_history_id(project_id: Any, project_name: Any = "") -> str:
    name = str(project_name or "").strip()
    if name:
        return _safe_project_history_name(name)
    text = str(project_id or "").strip()
    if text and text.lower() != "unsaved":
        return _safe_project_history_name(f"project_{text}" if text.isdigit() else text)
    return "未命名项目"


def _history_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S-%f")[:-3]


def _history_iso_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _history_stage_slug(stage_or_module: Any) -> str:
    text = str(stage_or_module or "module").strip().lower()
    text = re.sub(r"[^a-z0-9_\-]+", "_", text)
    if text.isdigit():
        return f"stage{text.zfill(2)}"
    if re.fullmatch(r"stage\d+", text):
        return f"stage{text.removeprefix('stage').zfill(2)}"
    return text or "module"


def _history_project_dir(project_id: Any, project_name: Any = "") -> Path:
    # 如果 project_name 空则 fallback
    safe_name = _project_history_id(project_id, project_name)
    path = _repo_root() / "cache" / safe_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _history_log_dir(project_id: Any, project_name: Any = "") -> Path:
    path = _repo_root() / "logs" / _project_history_id(project_id, project_name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _history_payload_keys(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    return sorted(str(key) for key in payload.keys() if not str(key).startswith("_"))


def _raw_payload_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"type": type(payload).__name__, "preview": _preview_return_object(payload, limit=300)}
    summary: dict[str, Any] = {
        "type": "dict",
        "payload_keys": _history_payload_keys(payload),
        "field_summary": {},
        "suspected_raw_response_fields": [],
    }
    field_summary: dict[str, Any] = {}
    polluted_fields: list[str] = []
    for key, value in payload.items():
        if str(key).startswith("_"):
            continue
        value_summary = _value_diagnostic_summary(value)
        field_summary[str(key)] = {
            "type": value_summary["type"],
            "length": value_summary["length"],
            "dict_keys": value_summary["dict_keys"][:12],
            "list_length": value_summary["list_length"],
            "first_item_type": value_summary["first_item_type"],
            "preview": value_summary["preview"],
        }
        if _pollution_keys_in_value(value):
            polluted_fields.append(str(key))
    summary["field_summary"] = field_summary
    summary["suspected_raw_response_fields"] = polluted_fields
    return summary


def _debug_project_dir(payload: Any) -> Path:
    safe_payload = _ensure_payload_project_title(payload)
    project_name = _payload_project_name(safe_payload)
    path = _repo_root() / "debug" / _project_history_id(safe_payload.get("project_id"), project_name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _debug_cache_project_dir(payload: Any) -> Path:
    safe_payload = _ensure_payload_project_title(payload)
    project_name = _payload_project_name(safe_payload)
    path = _repo_root() / "cache" / _project_history_id(safe_payload.get("project_id"), project_name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _debug_value_summary(value: Any, *, limit: int = STAGE_DEBUG_PREVIEW_LIMIT) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        text = value
        prefix = f"str(len={len(value)}) "
    elif isinstance(value, dict):
        keys = [str(key) for key in value.keys()]
        preview_keys = ", ".join(keys[:12])
        text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
        prefix = f"dict(keys=[{preview_keys}], size={len(value)}) "
    elif isinstance(value, list):
        text = json.dumps(value[:3], ensure_ascii=False, default=str, separators=(",", ":"))
        prefix = f"list(len={len(value)}) "
    else:
        text = str(value)
        prefix = f"{type(value).__name__} "
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = f"{text[:limit]}..."
    return f"{prefix}{text}".strip()


def _debug_payload_lines(payload: Any, *, prefix: str = "payload") -> list[str]:
    if not isinstance(payload, dict):
        return [f"{prefix}: {_debug_value_summary(payload)}"]
    lines: list[str] = []
    for key in sorted(str(item) for item in payload.keys() if not str(item).startswith("_")):
        lines.append(f"{prefix}.{key}: {_debug_value_summary(payload.get(key))}")
    return lines or [f"{prefix}: dict(empty)"]


def _debug_response_status(response_json: Any) -> str:
    if not isinstance(response_json, dict):
        return "unknown"
    if response_json.get("ok") is False:
        return "failed"
    if response_json.get("status") in {"failed", "error"}:
        return str(response_json.get("status"))
    if response_json.get("error") or response_json.get("exception_type"):
        return "failed"
    return "success"


def _debug_error_summary(response_json: Any) -> list[str]:
    if not isinstance(response_json, dict):
        return []
    lines: list[str] = []
    detail = response_json.get("detail") if isinstance(response_json.get("detail"), dict) else {}
    for key in (
        "reason",
        "error",
        "message",
        "exception_type",
        "exception_message",
        "status_code",
        "response_status",
        "response_error",
        "traceback",
    ):
        value = response_json.get(key)
        if value in (None, "", [], {}):
            value = detail.get(key)
        if value not in (None, "", [], {}):
            lines.append(f"{key}: {_debug_value_summary(value)}")
    return lines


def _debug_collect_response_variables(response_json: Any) -> dict[str, Any]:
    if not isinstance(response_json, dict):
        return {"response": response_json}
    variables: dict[str, Any] = {}
    for container_key in ("data", "output", "raw", "response"):
        container = response_json.get(container_key)
        if isinstance(container, dict):
            for key, value in container.items():
                if key not in variables:
                    variables[str(key)] = value
    for key, value in response_json.items():
        if key in {"data", "output", "raw", "response", "detail"}:
            continue
        if key not in variables and key not in {"ok", "stage", "status"}:
            variables[str(key)] = value
    return variables


def print_stage_debug(stage_number: Any, response_json: Any, payload: Any) -> None:
    stage = str(stage_number or "").zfill(2)
    definition = STAGE_DEFINITIONS.get(stage)
    stage_name = definition.label if definition else "未知阶段"
    status = _debug_response_status(response_json)
    response_variables = _debug_collect_response_variables(response_json)
    payload_variables = _ensure_payload_project_title(payload)
    key_order: list[str] = []
    if definition is not None:
        key_order.extend(definition.input_fields)
        key_order.extend(definition.output_fields)
    key_order.extend(sorted(FRAMEWORK_BUSINESS_FIELDS))
    key_order.extend(str(key) for key in payload_variables.keys() if not str(key).startswith("_"))
    key_order.extend(response_variables.keys())

    seen: set[str] = set()
    ordered_keys = [key for key in key_order if not (key in seen or seen.add(key))]
    lines = [
        "=== Framework Planner Stage Debug ===",
        f"timestamp: {_history_iso_timestamp()}",
        f"stage: {stage} - {stage_name}",
        f"status: {status}",
    ]
    error_lines = _debug_error_summary(response_json)
    if error_lines:
        lines.append("-- failure --")
        lines.extend(error_lines)
    lines.append("-- variables --")
    for key in ordered_keys:
        if key in response_variables:
            value = response_variables[key]
        elif key in payload_variables:
            value = payload_variables[key]
        else:
            continue
        lines.append(f"{key}: {_debug_value_summary(value)}")
    if not ordered_keys:
        lines.append("empty: no payload or response variables")

    debug_text = "\n".join(lines)
    print(f"\n{debug_text}\n", flush=True)
    try:
        debug_dir = _debug_project_dir(payload)
        (debug_dir / f"stage{stage}_debug.txt").write_text(debug_text + "\n", encoding="utf-8")
        cache_dir = _debug_cache_project_dir(payload)
        cache_path = cache_dir / f"stage{stage}_debug.txt"
        cache_path.write_text(debug_text + "\n", encoding="utf-8")
        print(f"[framework_planner_cache_debug] wrote {cache_path}", flush=True)
    except Exception as exc:
        logger.warning("写入阶段调试文件失败：stage=%s error=%s", stage, exc)


def write_framework_frontend_debug_event(
    *,
    project_id: Any,
    event: str,
    payload: dict[str, Any] | None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_payload = _ensure_payload_project_title(payload, project_id=project_id)
    safe_detail = detail if isinstance(detail, dict) else {}
    project_name = _payload_project_name(safe_payload) or _payload_project_name(safe_detail) or project_id
    debug_payload = {
        **safe_payload,
        "project_id": project_id,
        "project_title": _payload_project_name(safe_payload) or _payload_project_name(safe_detail) or "",
    }
    timestamp = _history_iso_timestamp()
    lines = [
        "=== Framework Planner Frontend Debug ===",
        f"timestamp: {timestamp}",
        f"event: {str(event or '').strip() or 'unknown'}",
        f"project: {_project_history_id(project_id, project_name)}",
        "-- payload --",
        *_debug_payload_lines(safe_payload, prefix="payload"),
        "-- detail --",
        *_debug_payload_lines(safe_detail, prefix="detail"),
        "",
    ]
    text = "\n".join(lines)
    cache_dir = _debug_cache_project_dir(debug_payload)
    debug_dir = _debug_project_dir(debug_payload)
    cache_path = cache_dir / "frontend_debug.txt"
    debug_path = debug_dir / "frontend_debug.txt"
    with cache_path.open("a", encoding="utf-8") as file:
        file.write(text)
    with debug_path.open("a", encoding="utf-8") as file:
        file.write(text)
    print(text, flush=True)
    print(f"[framework_planner_cache_debug] wrote {cache_path}", flush=True)
    return {
        "ok": True,
        "event": str(event or "").strip() or "unknown",
        "cache_path": str(cache_path),
        "debug_path": str(debug_path),
        "project_name": _project_history_id(project_id, project_name),
    }


def save_framework_stage_history(
    *,
    project_id: Any,
    stage: str,
    payload: dict[str, Any] | None,
    output: Any,
    status: str,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_payload = _ensure_payload_project_title(payload, project_id=project_id)
    project_name = _payload_project_name(safe_payload)
    project_dir = _history_project_dir(safe_payload.get("project_id"), project_name)
    slug = _history_stage_slug(stage)
    timestamp = _history_timestamp()
    record = {
        "stage": slug,
        "timestamp": timestamp,
        "status": "success" if status == "success" else "failed",
        "payload_project_name": project_name,
        "payload_keys": _history_payload_keys(safe_payload),
        "payload_debug_summary": _raw_payload_summary(safe_payload),
        "output": output if status == "success" else {},
    }
    if error:
        record["error"] = error
    filename = f"{slug}_{timestamp}.json"
    path = project_dir / filename
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    latest_path = project_dir / f"latest_{slug}.json"
    if status == "success":
        latest_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        f"[framework_planner_cache] stage={slug} status={record['status']} path={path} latest={latest_path if status == 'success' else ''}",
        flush=True,
    )
    return {
        "project_id": _project_history_id(safe_payload.get("project_id"), project_name),
        "project_name": _project_history_id(safe_payload.get("project_id"), project_name),
        "stage": slug,
        "filename": filename,
        "latest_filename": latest_path.name if status == "success" else "",
        "timestamp": timestamp,
        "status": record["status"],
        "payload_keys": record["payload_keys"],
    }


def write_framework_stage_exception_log(
    *,
    project_id: Any,
    stage: str,
    payload: dict[str, Any] | None,
    exc_type: str,
    message: str,
    status_code: int | None = None,
) -> dict[str, Any]:
    safe_payload = _ensure_payload_project_title(payload, project_id=project_id)
    project_name = _payload_project_name(safe_payload)
    log_dir = _history_log_dir(safe_payload.get("project_id"), project_name)
    timestamp = _history_timestamp()
    entry = {
        "stage": _history_stage_slug(stage),
        "timestamp": timestamp,
        "status": "failed",
        "payload_project_name": project_name,
        "payload_keys": _history_payload_keys(safe_payload),
        "exception_type": exc_type,
        "exception_message": str(message or ""),
        "status_code": status_code,
        "raw_payload_summary": _raw_payload_summary(safe_payload),
    }
    logger.error(
        "framework planner stage exception timestamp=%s stage=%s payload_keys=%s exception_type=%s exception_message=%s status_code=%s",
        timestamp,
        entry["stage"],
        entry["payload_keys"],
        exc_type,
        message,
        status_code,
    )
    print_stage_debug(
        stage,
        {
            "ok": False,
            "stage": _history_stage_slug(stage),
            "status": "failed",
            "reason": str(message or ""),
            "exception_type": exc_type,
            "exception_message": str(message or ""),
            "status_code": status_code,
            "detail": entry,
        },
        safe_payload,
    )
    filename = f"{entry['stage']}_{timestamp}.json"
    (log_dir / filename).write_text(json.dumps(entry, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"filename": filename, "project_name": _project_history_id(safe_payload.get("project_id"), project_name), **entry}


def _history_project_candidate_dirs(project_id: Any, project_name: Any = "") -> list[Path]:
    """返回兼容旧版/新版命名的历史目录候选。

    目前前端可能传 project_id=1，保存阶段可能落到 cache/1；
    但 _project_history_id(1) 会读 cache/project_1。
    这里同时兼容 cache/1、cache/project_1 和项目名目录。
    """
    root = _repo_root() / "cache"
    candidates: list[Path] = []

    def add_candidate(value: Any) -> None:
        text = str(value or "").strip()
        if not text:
            return
        safe = _safe_project_history_name(text)
        path = root / safe
        if path not in candidates:
            candidates.append(path)

    # 1. 原始 project_name 优先，兼容 save_framework_stage_history 传入项目名的情况。
    add_candidate(project_name)

    # 2. 原始 project_id，兼容当前实际落盘的 cache/1。
    add_candidate(project_id)

    # 3. 标准化后的 project_id，兼容历史接口当前返回的 cache/project_1。
    add_candidate(_project_history_id(project_id, project_name))

    text = str(project_id or "").strip()
    if text.isdigit():
        add_candidate(f"project_{text}")

    return candidates


def list_framework_stage_history(project_id: Any, stage: str | None = None) -> dict[str, Any]:
    slug = _history_stage_slug(stage) if stage else ""
    entries: list[dict[str, Any]] = []
    seen_files: set[str] = set()

    for project_dir in _history_project_candidate_dirs(project_id):
        if not project_dir.exists():
            continue

        for path in sorted(project_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            if path.name.startswith("latest_"):
                continue
            if slug and not path.name.startswith(f"{slug}_"):
                continue

            file_key = str(path.resolve())
            if file_key in seen_files:
                continue
            seen_files.add(file_key)

            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue

            entries.append(
                {
                    "filename": path.name,
                    "stage": data.get("stage") or _history_stage_slug(path.stem),
                    "status": data.get("status") or "unknown",
                    "created_at": data.get("created_at") or data.get("timestamp") or "",
                    "summary": data.get("summary") or "",
                    "payload_keys": data.get("payload_keys") or [],
                    "project_name": data.get("project_name") or project_dir.name,
                }
            )

    return {
        "project_id": str(project_id or "").strip() or _project_history_id(project_id),
        "project_name": str(project_id or "").strip() or _project_history_id(project_id),
        "stage": slug,
        "entries": entries,
    }


def load_framework_stage_history(project_id: Any, filename: str) -> dict[str, Any]:
    safe_filename = Path(str(filename or "")).name
    if not safe_filename or safe_filename != str(filename or "").strip():
        raise FrameworkPlannerStageError("历史版本路径无效", stage="history", status_code=400)

    for project_dir in _history_project_candidate_dirs(project_id):
        path = project_dir / safe_filename
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise FrameworkPlannerStageError("历史版本读取失败", stage="history", status_code=500) from exc

    raise FrameworkPlannerStageError("历史版本不存在", stage="history", status_code=404)

@dataclass(frozen=True, slots=True)
class FrameworkPlannerStageDefinition:
    stage: str
    label: str
    env_prefix: str
    workflow_glob: str
    input_fields: tuple[str, ...]
    output_fields: tuple[str, ...]
    required_fields: tuple[str, ...]
    input_aliases: dict[str, tuple[str, ...]]
    output_aliases: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class FrameworkPlannerWorkflowSpec:
    stage: str
    path: Path
    public_variable_keys: tuple[str, ...]
    internal_variable_keys: tuple[str, ...]
    answer_node_names: tuple[str, ...]
    contract_path: Path | None


@dataclass(frozen=True, slots=True)
class FrameworkPlannerEndpoint:
    url: str
    url_source: str
    api_key: str
    api_key_source: str
    workflow_id: str
    workflow_id_source: str
    chat_id: str
    timeout: int


LEGACY_STAGE_API_KEY_ENVS: dict[str, tuple[str, ...]] = {
    "01": ("FASTGPT_BETTER_FRAMEWORK_EXTRACT",),
    "02": ("FASTGPT_BETTER_FRAMEWORK_WORLDVIEW",),
    "03": ("FASTGPT_BETTER_FRAMEWORK_CHARACTERS",),
    "04": ("FASTGPT_BETTER_FRAMEWORK_PLOT_KEY_POINT_PLANNING",),
    "05": ("FASTGPT_BETTER_FRAMEWORK_CHARACTER_STORYLINE",),
    "06": ("FASTGPT_BETTER_FRAMEWORK_GENERATE_UPDATE",),
    "07": ("FASTGPT_BETTER_FRAMEWORK_FRAMEWORK_INSPECTION",),
}


class FrameworkPlannerStageError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str,
        status_code: int = 400,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.status_code = status_code
        self.detail = detail or {}


STAGE_DEFINITIONS: dict[str, FrameworkPlannerStageDefinition] = {
    "01": FrameworkPlannerStageDefinition(
        stage="01",
        label="原文信息提取",
        env_prefix="FASTGPT_FRAMEWORK_01_SOURCE_BRIEF",
        workflow_glob="extract01*.yaml",
        input_fields=(
            "mode",
            "source_text",
            "source_title",
            "target_format",
            "season_count",
            "episodes_per_season",
            "minutes_per_episode",
            "adaptation_direction",
            "user_constraints",
            "user_requirements",
        ),
        output_fields=("source_brief",),
        required_fields=(
            "source_title",
            "target_format",
            "season_count",
            "episodes_per_season",
        ),
        input_aliases={
            "mode": ("mode", "zHrEcynX"),
            "source_text": ("source_text",),
            "source_title": ("source_title",),
            "target_format": ("target_format",),
            "season_count": ("season_count",),
            "episodes_per_season": ("episodes_per_season",),
            "minutes_per_episode": ("minutes_per_episode",),
            "adaptation_direction": ("adaptation_direction",),
            "user_constraints": ("user_constraints",),
            "user_requirements": ("user_requirements",),
        },
        output_aliases={
            "source_brief": ("source_brief", "confirmed_info"),
        },
    ),
    "02": FrameworkPlannerStageDefinition(
        stage="02",
        label="世界观方案生成更新",
        env_prefix="FASTGPT_FRAMEWORK_02_WORLDVIEW",
        workflow_glob="worldview02*.yaml",
        input_fields=(
            "mode",
            "source_brief",
            "locked_basic_config",
            "previous_worldview",
            "user_feedback",
            "adaptation_direction",
            "user_requirements",
        ),
        output_fields=("worldview_plan",),
        required_fields=("source_brief", "locked_basic_config"),
        input_aliases={
            "mode": ("mode",),
            "source_brief": ("source_brief",),
            "locked_basic_config": ("locked_basic_config", "basic_config"),
            "previous_worldview": ("previous_worldview", "previous_worldview_plan"),
            "user_feedback": ("user_feedback",),
            "adaptation_direction": ("adaptation_direction",),
            "user_requirements": ("user_requirements",),
        },
        output_aliases={
            "worldview_plan": ("worldview_plan", "worldview"),
        },
    ),
    "03": FrameworkPlannerStageDefinition(
        stage="03",
        label="人设方案生成更新",
        env_prefix="FASTGPT_FRAMEWORK_03_CHARACTER",
        workflow_glob="character03*.yaml",
        input_fields=(
            "mode",
            "source_brief",
            "locked_basic_config",
            "worldview_plan",
            "previous_character",
            "user_feedback",
            "adaptation_direction",
            "user_requirements",
        ),
        output_fields=("character_plan",),
        required_fields=("source_brief", "locked_basic_config", "worldview_plan"),
        input_aliases={
            "mode": ("mode",),
            "source_brief": ("source_brief",),
            "locked_basic_config": ("locked_basic_config", "basic_config"),
            "worldview_plan": ("worldview_plan",),
            "previous_character": ("previous_character", "previous_character_plan"),
            "user_feedback": ("user_feedback",),
            "adaptation_direction": ("adaptation_direction",),
            "user_requirements": ("user_requirements",),
        },
        output_aliases={
            "character_plan": ("character_plan", "character"),
        },
    ),
    "04": FrameworkPlannerStageDefinition(
        stage="04",
        label="三幕十五节拍卡点规划生成更新",
        env_prefix="FASTGPT_FRAMEWORK_04_BEAT",
        workflow_glob="beat04*.yaml",
        input_fields=(
            "mode",
            "source_brief",
            "basic_config",
            "season_count",
            "episodes_per_season",
            "total_episodes",
            "episode_count_guard",
            "worldview_plan",
            "character_plan",
            "previous_beat",
            "user_feedback",
            "framework_score_repo",
            "adaptation_direction",
            "user_requirements",
            "keyword",
        ),
        output_fields=("beat_checkpoint_timeline", "checkpoint_explanation"),
        required_fields=("source_brief", "basic_config", "worldview_plan", "character_plan"),
        input_aliases={
            "mode": ("mode",),
            "source_brief": ("source_brief",),
            "basic_config": ("basic_config",),
            "season_count": ("season_count",),
            "episodes_per_season": ("episodes_per_season",),
            "total_episodes": ("total_episodes",),
            "episode_count_guard": ("episode_count_guard",),
            "worldview_plan": ("worldview_plan",),
            "character_plan": ("character_plan",),
            "previous_beat": ("previous_beat", "previous_beat_checkpoint_timeline"),
            "user_feedback": ("user_feedback",),
            "framework_score_repo": ("framework_score_repo", "framework_score_report"),
            "adaptation_direction": ("adaptation_direction",),
            "user_requirements": ("user_requirements",),
            "keyword": ("keyword",),
        },
        output_aliases={
            "beat_checkpoint_timeline": (
                "beat_checkpoint_timeline",
                "beatCheckpointTimeline",
                "checkpoint_timeline",
                "checkpointTimeline",
                "beat_timeline",
                "beatTimeline",
                "timeline",
                "beats",
                "checkpoints",
                "beat_checkpoints",
                "beatCheckpoints",
                "beat_checkpoint",
                "beatCheckpoint",
            ),
            "checkpoint_explanation": (
                "checkpoint_explanation",
                "checkpointExplanation",
                "explanation",
                "beat_explanation",
                "beatExplanation",
                "checkpoint_explain",
                "checkpointExplain",
            ),
        },
    ),
    "05": FrameworkPlannerStageDefinition(
        stage="05",
        label="人物故事线生成更新",
        env_prefix="FASTGPT_FRAMEWORK_05_STORYLINE",
        workflow_glob="storyline05*.yaml",
        input_fields=(
            "mode",
            "source_brief",
            "basic_config",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint_time",
            "previous_character",
            "current_storyline",
            "user_feedback",
            "adaptation_direction",
            "user_requirements",
        ),
        output_fields=("character_storylines",),
        required_fields=(
            "source_brief",
            "basic_config",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint_time",
        ),
        input_aliases={
            "mode": ("mode",),
            "source_brief": ("source_brief",),
            "basic_config": ("basic_config",),
            "worldview_plan": ("worldview_plan",),
            "character_plan": ("character_plan",),
            "beat_checkpoint_time": ("beat_checkpoint_time", "beat_checkpoint_timeline"),
            "previous_character": ("previous_character", "previous_character_storylines"),
            "current_storyline": ("current_storyline", "current_storyline_decisions", "storyline_decisions"),
            "user_feedback": ("user_feedback",),
            "adaptation_direction": ("adaptation_direction",),
            "user_requirements": ("user_requirements",),
        },
        output_aliases={
            "character_storylines": ("character_storylines", "storylines", "storyline"),
        },
    ),
    "06": FrameworkPlannerStageDefinition(
        stage="06",
        label="整体改编指引生成更新",
        env_prefix="FASTGPT_FRAMEWORK_06_GUIDE",
        workflow_glob="adaptation06*.yaml",
        input_fields=(
            "mode",
            "source_brief",
            "basic_config",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint_time",
            "character_storylines",
            "storyline_decisions",
            "previous_adaptation",
            "user_feedback",
            "adaptation_direction",
            "user_requirements",
        ),
        output_fields=("adaptation_guide",),
        required_fields=(
            "source_brief",
            "basic_config",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint_time",
            "character_storylines",
        ),
        input_aliases={
            "mode": ("mode",),
            "source_brief": ("source_brief",),
            "basic_config": ("basic_config",),
            "worldview_plan": ("worldview_plan",),
            "character_plan": ("character_plan",),
            "beat_checkpoint_time": ("beat_checkpoint_time", "beat_checkpoint_timeline"),
            "character_storylines": ("character_storylines",),
            "storyline_decisions": ("storyline_decisions",),
            "previous_adaptation": ("previous_adaptation", "previous_adaptation_guide"),
            "user_feedback": ("user_feedback",),
            "adaptation_direction": ("adaptation_direction",),
            "user_requirements": ("user_requirements",),
        },
        output_aliases={
            "adaptation_guide": ("adaptation_guide", "guide", "adaptation"),
        },
    ),
    "07": FrameworkPlannerStageDefinition(
        stage="07",
        label="框架策划包校验",
        env_prefix="FASTGPT_FRAMEWORK_07_PACKAGE",
        workflow_glob="framework07*.yaml",
        input_fields=(
            "mode",
            "basic_config",
            "source_brief",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint",
            "checkpoint_explain",
            "character_storylines",
            "storyline_decisions",
            "adaptation_guide",
            "user_edit_history",
            "previous_framework",
            "user_feedback",
            "adaptation_direction",
            "user_requirements",
        ),
        output_fields=("framework_plan_package", "validation_report"),
        required_fields=(
            "basic_config",
            "source_brief",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint",
            "character_storylines",
            "adaptation_guide",
        ),
        input_aliases={
            "mode": ("mode",),
            "basic_config": ("basic_config",),
            "source_brief": ("source_brief",),
            "worldview_plan": ("worldview_plan",),
            "character_plan": ("character_plan",),
            "beat_checkpoint": ("beat_checkpoint", "beat_checkpoint_timeline"),
            "checkpoint_explain": ("checkpoint_explain", "checkpoint_explanation"),
            "character_storylines": ("character_storylines",),
            "storyline_decisions": ("storyline_decisions",),
            "adaptation_guide": (
                "adaptation_guide",
                "adaptationGuide",
                "overallAdaptationGuide",
                "overall_adaptation_guide",
                "guide",
                "previous_adaptation_guide",
            ),
            "user_edit_history": ("user_edit_history",),
            "previous_framework": ("previous_framework", "previous_framework_plan_package"),
            "user_feedback": ("user_feedback",),
            "adaptation_direction": ("adaptation_direction",),
            "user_requirements": ("user_requirements",),
        },
        output_aliases={
            "framework_plan_package": ("framework_plan_package", "package", "framework"),
            "validation_report": ("validation_report", "validation", "framework"),
        },
    ),
}


def stage_definition(stage: str) -> FrameworkPlannerStageDefinition:
    definition = STAGE_DEFINITIONS.get(str(stage).zfill(2))
    if definition is None:
        raise FrameworkPlannerStageError(
            "未知的框架策划阶段",
            stage=str(stage),
            status_code=404,
            detail={"stage": stage},
        )
    return definition


def framework_planner_backend_ready() -> bool:
    return any(stage_has_real_backend(stage) for stage in STAGE_DEFINITIONS)


def framework_planner_fastgpt_diagnostics(stage: str = "05") -> dict[str, Any]:
    definition = stage_definition(stage)
    diagnostics = _stage_runtime_diagnostics(definition, {})
    endpoint = str(diagnostics.get("resolved_url") or DEFAULT_NS_WORKFLOW_URL)
    host, port = _endpoint_host_port(endpoint)
    return {
        "ok": True,
        "stage": definition.stage,
        "endpoint": endpoint,
        "host": host,
        "port": port,
        "has_api_key": bool(diagnostics.get("has_api_key")),
        "api_key_config_name": diagnostics.get("api_key_source") or "",
        "mock_enabled": bool(diagnostics.get("mock_enabled")),
        "url_config_name": diagnostics.get("url_source") or "default",
        "timeout_seconds": diagnostics.get("timeout_seconds") or 0,
    }


def stage_has_real_backend(stage: str) -> bool:
    definition = stage_definition(stage)
    _, token = _coze_api_token_with_name()
    _, workflow_id = _stage_workflow_id_with_name(definition)
    return bool(token and workflow_id)


def _parse_coze_framework_response(
    definition: FrameworkPlannerStageDefinition,
    response_json: Any,
) -> Any:
    if isinstance(response_json, dict):
        code = response_json.get("code")
        if code not in (None, 0, "0"):
            message = response_json.get("msg") or response_json.get("message") or response_json.get("error")
            raise FrameworkPlannerStageError(
                "Coze 工作流返回失败",
                stage=definition.stage,
                status_code=502,
                detail={
                    "reason": str(message or "Coze workflow returned failure"),
                    "coze_code": code,
                    "response_preview": safe_truncated_preview(response_json, limit=1000),
                },
            )

    # Stage04 必须先走专用解析。
    # 原因：Coze 当前返回是 data:String -> beat:String -> 真正业务 JSON。
    # 通用 parse_workflow_output 很容易只解析到 data.beat 的局部对象，然后丢失 15 节拍。
    if definition.stage == "04":
        extracted = _stage04_extract_payload_from_nested_coze(response_json)

        if isinstance(extracted, dict) and isinstance(extracted.get("beat_checkpoint_timeline"), list):
            logger.warning(
                "[stage04 coze parser] extracted nested payload directly: timeline_len=%s keys=%s",
                len(extracted.get("beat_checkpoint_timeline") or []),
                sorted(extracted.keys()),
            )
            return extracted

        logger.warning(
            "[stage04 coze parser] nested payload not found, fallback to generic parser; response_preview=%s",
            safe_truncated_preview(response_json, limit=1000),
        )

    parsed = parse_workflow_output(response_json)
    return wrap_payload_for_expected_output(
        parsed,
        output_names=definition.output_fields,
        output_aliases=definition.output_aliases,
        stage_name=f"framework_{definition.stage}",
    )


def run_framework_planner_stage(stage: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    definition = stage_definition(stage)
    normalized_payload = _ensure_payload_project_title(_normalize_payload(payload))
    print(
        "[framework_planner_entry] "
        f"stage={definition.stage} project_name={_payload_project_name(normalized_payload)} "
        f"project_id={normalized_payload.get('project_id', '')} "
        f"payload_keys={_history_payload_keys(normalized_payload)}",
        flush=True,
    )
    workflow_spec = load_stage_workflow_spec(definition.stage)
    diagnostics = _stage_runtime_diagnostics(definition, normalized_payload)
    _log_stage_entry(definition, diagnostics)
    if _should_use_mock_backend(definition):
        reason = "FRAMEWORK_PLANNER_USE_MOCK=true, using mock output"
        _log_stage_not_entering_fastgpt(definition, diagnostics, reason=reason)
        data, display_text = _build_mock_stage_output(definition.stage, normalized_payload)
        print_stage_debug(
            definition.stage,
            {"ok": True, "stage": definition.stage, "status": "success", "data": data, "display_text": display_text},
            normalized_payload,
        )
        return {
            "ok": True,
            "stage": definition.stage,
            "data": data,
            "raw": {
                "mock": True,
                "workflow_json_path": str(workflow_spec.path),
                "workflow_contract_path": str(workflow_spec.contract_path) if workflow_spec.contract_path else "",
                "parse_warning": [],
                "diagnostics": diagnostics,
            },
            "display_text": display_text,
        }

    request_variables = _build_stage_request_variables(definition, normalized_payload, workflow_spec)
    if definition.stage == "05":
        _log_stage_05_input_diagnostics(normalized_payload, request_variables)
    try:
        endpoint = _resolve_stage_endpoint(definition)
    except FrameworkPlannerStageError as exc:
        _log_stage_not_entering_fastgpt(
            definition,
            diagnostics,
            reason=exc.detail.get("reason") or str(exc),
        )
        print_stage_debug(
            definition.stage,
            {
                "ok": False,
                "stage": definition.stage,
                "status": "failed",
                "reason": exc.detail.get("reason") or str(exc),
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "detail": exc.detail,
                "traceback": traceback.format_exc(),
            },
            normalized_payload,
        )
        raise

    logger.info(
        "Coze endpoint resolved: stage=%s url_source=%s endpoint=%s workflow_id_source=%s",
        definition.stage,
        endpoint.url_source or "default",
        endpoint.url,
        endpoint.workflow_id_source or "",
    )
    body = _build_request_body(definition, request_variables, endpoint)
    headers = {
        "Authorization": f"Bearer {endpoint.api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = _post_with_retries(
            definition,
            endpoint,
            headers,
            body,
            diagnostics=diagnostics,
        )
    except FrameworkPlannerStageError as exc:
        print_stage_debug(
            definition.stage,
            {
                "ok": False,
                "stage": definition.stage,
                "status": "failed",
                "reason": exc.detail.get("reason") or str(exc),
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "detail": exc.detail,
                "traceback": traceback.format_exc(),
            },
            normalized_payload,
        )
        raise
    response_text = _safe_response_text(response)
    http_response_json: Any = None
    try:
        response_json = response.json()
        http_response_json = response_json
        # ================================
        # Stage04 Coze unwrap fix（必须）
        # ================================
        if definition.stage == "04":
            try:
                if isinstance(response_json, dict):
                    data = response_json.get("data")

                    extracted_beat = None

                    if isinstance(data, dict):
                        if "beat_checkpoint_timeline" in data:
                            extracted_beat = data
                        elif "beat" in data:
                            extracted_beat = data["beat"]

                            if isinstance(extracted_beat, str):
                                extracted_beat = json.loads(extracted_beat)

                    if extracted_beat:
                        # ❗不要覆盖 response_json
                        response_json["_stage04_unwrapped"] = extracted_beat

                        logger.warning(
                            f"[stage04 unwrap hint] extracted type={type(extracted_beat).__name__}"
                        )

            except Exception as e:
                logger.warning(f"[stage04 unwrap failed] {e}")
    except ValueError as exc:
        _log_stage_output_parse_exception(
            stage=definition.stage,
            payload_keys=sorted(normalized_payload.keys()),
            exc=exc,
            raw_return_object=response_text,
        )
        if _is_coze_backend() or definition.stage in {"01", "02", "03", "04", "05"}:
            response_json = response_text
            http_response_json = response_text
        else:
            debug_detail = _write_debug_artifact(
                stage=definition.stage,
                workflow_spec=workflow_spec,
                request_variables=request_variables,
                payload=normalized_payload,
                response_raw=response_text,
                parse_error="response.json invalid",
            )
            logger.warning(
                "框架策划阶段 %s 返回非法 JSON 响应，payload_keys=%s",
                definition.stage,
                sorted(normalized_payload.keys()),
            )
            print_stage_debug(
                definition.stage,
                {
                    "ok": False,
                    "stage": definition.stage,
                    "status": "failed",
                    "reason": "FastGPT 返回非法 JSON 响应",
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "response": safe_truncated_preview(response_text, limit=1000),
                    "detail": debug_detail,
                    "traceback": traceback.format_exc(),
                },
                normalized_payload,
            )
            raise FrameworkPlannerStageError(
                "当前阶段返回格式异常，请重试或查看日志",
                stage=definition.stage,
                status_code=502,
                detail=debug_detail,
            ) from exc

    if definition.stage == "04":
        _write_stage04_coze_http_debug(
            response=response,
            endpoint=endpoint,
            body=body,
            response_text=response_text,
        )

    if _is_coze_backend():
        try:
            response_json = _parse_coze_framework_response(definition, response_json)
        except FrameworkPlannerStageError as exc:
            print_stage_debug(
                definition.stage,
                {
                    "ok": False,
                    "stage": definition.stage,
                    "status": "failed",
                    "reason": exc.detail.get("reason") or str(exc),
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "detail": exc.detail,
                    "response": safe_truncated_preview(response_json, limit=1000),
                    "traceback": traceback.format_exc(),
                },
                normalized_payload,
            )
            raise
        except Exception as exc:
            _log_stage_output_parse_exception(
                stage=definition.stage,
                payload_keys=sorted(normalized_payload.keys()),
                exc=exc,
                raw_return_object=response_json,
            )
            debug_detail = _write_debug_artifact(
                stage=definition.stage,
                workflow_spec=workflow_spec,
                request_variables=request_variables,
                payload=normalized_payload,
                response_raw=response_json,
                parse_error=f"Coze response parse failed: {type(exc).__name__}: {exc}",
            )
            print_stage_debug(
                definition.stage,
                {
                    "ok": False,
                    "stage": definition.stage,
                    "status": "failed",
                    "reason": "Coze 工作流返回解析失败",
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "response": safe_truncated_preview(response_json, limit=1000),
                    "detail": debug_detail,
                    "traceback": traceback.format_exc(),
                },
                normalized_payload,
            )
            raise FrameworkPlannerStageError(
                "当前阶段返回格式异常，请重试或查看日志",
                stage=definition.stage,
                status_code=502,
                detail=debug_detail,
            ) from exc

    try:
        raw_debug_dir = _repo_root() / "cache" / "raw_coze_debug"
        raw_debug_dir.mkdir(parents=True, exist_ok=True)
        raw_debug_path = raw_debug_dir / f"stage{definition.stage}_raw_response.json"
        raw_debug_payload = {
            "stage": definition.stage,
            "backend": "coze",
            "data": response_json if definition.stage == "04" else None,
            "data_keys": sorted(response_json.keys()) if definition.stage == "04" and isinstance(response_json, dict) else [],
            "response": response_json if definition.stage == "04" else None,
            "safe_response_preview": safe_truncated_preview(response_json, limit=4000),
        }
        if definition.stage != "04":
            raw_debug_payload.pop("response", None)
            raw_debug_payload.pop("data", None)
            raw_debug_payload.pop("data_keys", None)
        raw_debug_path.write_text(
            json.dumps(raw_debug_payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.warning(
            "[framework_planner_raw_debug] wrote raw Coze response stage=%s path=%s",
            definition.stage,
            raw_debug_path,
        )
    except Exception:
        logger.exception("[framework_planner_raw_debug] failed to write raw response")

    try:
        data, display_text, parse_warnings = _extract_stage_output(
            definition=definition,
            workflow_spec=workflow_spec,
            response_json=response_json,
            payload_keys=sorted(normalized_payload.keys()),
        )
    except Exception as exc:
        _log_stage_output_parse_exception(
            stage=definition.stage,
            payload_keys=sorted(normalized_payload.keys()),
            exc=exc,
            raw_return_object=response_json,
        )
        if definition.stage in {"01", "02", "03", "04", "05"}:
            parse_warnings = [
                f"阶段 {definition.stage} 输出解析异常，已回退到安全解析：{type(exc).__name__}: {exc}"
            ]
            safe_output, safe_warnings = safe_parse_stage_output(
                response_json,
                (*definition.output_fields, "display_text"),
            )
            parse_warnings.extend(safe_warnings)
            data = _normalize_stage_output(
                definition.stage,
                safe_output,
                parse_warnings=parse_warnings,
                payload=normalized_payload,
            )
            _log_stage_parse_warnings(definition.stage, parse_warnings)
            display_text = _extract_display_text(
                response_json,
                data,
                stage=definition.stage,
                payload_keys=sorted(normalized_payload.keys()),
            )
        else:
            debug_detail = _write_debug_artifact(
                stage=definition.stage,
                workflow_spec=workflow_spec,
                request_variables=request_variables,
                payload=normalized_payload,
                response_raw=response_json,
                parse_error=str(exc),
            )
            logger.warning(
                "框架策划阶段 %s 输出解析失败，payload_keys=%s，error=%s",
                definition.stage,
                sorted(normalized_payload.keys()),
                exc,
            )
            data, display_text, parse_warnings = _force_repair_stage_output_from_raw_fastgpt(
                definition=definition,
                response_json=response_json,
                data=data,
                display_text=display_text,
                parse_warnings=parse_warnings,
            )

            data = _repair_stage_output_with_payload(
                definition.stage,
                data,
                normalized_payload,
            )
            if not display_text:
                display_text = _extract_display_text(
                    response_json,
                    data,
                    stage=definition.stage,
                    payload_keys=sorted(normalized_payload.keys()),
                )

            print_stage_debug(
                definition.stage,
                {
                    "ok": False,
                    "stage": definition.stage,
                    "status": "failed",
                    "reason": "阶段输出解析失败",
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "response": safe_truncated_preview(response_json, limit=1000),
                    "detail": debug_detail,
                    "traceback": traceback.format_exc(),
                },
                normalized_payload,
            )
            raise FrameworkPlannerStageError(
                "当前阶段返回格式异常，请重试或查看日志",
                stage=definition.stage,
                status_code=502,
                detail=debug_detail,
            ) from exc

    # FastGPT raw response repair must run on the normal success path.
    # _extract_stage_output may return a safe placeholder without raising,
    # so relying on the except branch is not enough.
    data, display_text, parse_warnings = _force_repair_stage_output_from_raw_fastgpt(
        definition=definition,
        response_json=response_json,
        data=data,
        display_text=display_text,
        parse_warnings=parse_warnings,
    )

    data = _normalize_stage_output(
        definition.stage,
        data,
        parse_warnings=parse_warnings,
        payload=normalized_payload,
    )

    data = _repair_stage_output_with_payload(
        definition.stage,
        data,
        normalized_payload,
    )

    if not display_text:
        display_text = _extract_display_text(
            response_json,
            data,
            stage=definition.stage,
            payload_keys=sorted(normalized_payload.keys()),
        )

    if definition.stage == "04":
        _write_stage04_parser_debug(
            data=data,
            display_text=display_text,
            parsed_response=response_json,
            parse_warnings=parse_warnings,
        )

    if definition.stage == "04":
        _validate_stage04_output_or_raise(
            data=data,
            payload=normalized_payload,
            parse_warnings=parse_warnings,
            response_json=response_json,
            raw_response_json=http_response_json,
        )

    stage_detail = {}
    if definition.stage == "05":
        stage_detail = _stage_05_output_detail(
            response_json=response_json,
            workflow_spec=workflow_spec,
            diagnostics=diagnostics,
            data=data,
            parse_warnings=parse_warnings,
        )

    print_stage_debug(
        definition.stage,
        {
            "ok": not bool(stage_detail),
            "stage": definition.stage,
            "status": "failed" if stage_detail else "success",
            "data": data,
            "display_text": display_text,
            "parse_warnings": parse_warnings,
            **({"error": "阶段 05 未解析到有效人物故事线", "detail": stage_detail} if stage_detail else {}),
        },
        normalized_payload,
    )
    return {
        "ok": True,
        "stage": definition.stage,
        "data": data,
            "raw": {
                "mock": False,
                "workflow_json_path": str(workflow_spec.path),
                "workflow_contract_path": str(workflow_spec.contract_path) if workflow_spec.contract_path else "",
                "url": endpoint.url,
                "workflow_id": endpoint.workflow_id,
                "response": response_json,
                "parse_warning": parse_warnings,
                "diagnostics": diagnostics,
            },
            "display_text": display_text,
            **({"error": "阶段 05 未解析到有效人物故事线", "detail": stage_detail} if stage_detail else {}),
        }


def run_framework_planner_score(payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized_payload = _normalize_payload(payload)
    timeline = normalized_payload.get("beat_checkpoint_timeline")
    explanation = normalized_payload.get("checkpoint_explanation")
    missing_fields: list[str] = []
    beat_count = 0
    if isinstance(timeline, list):
        beat_count = len(timeline)
        for index, item in enumerate(timeline, start=1):
            if not isinstance(item, dict):
                missing_fields.append(f"beat[{index}]")
                continue
            for field in (
                "beat_no",
                "beat_name",
                "act",
                "episode_range",
                "checkpoint_title",
                "narrative_function",
                "plot_content",
                "hook_or_reversal",
            ):
                if _is_blank(item.get(field)):
                    missing_fields.append(f"beat[{index}].{field}")
    else:
        missing_fields.append("beat_checkpoint_timeline")
    if explanation in (None, "", {}):
        missing_fields.append("checkpoint_explanation")

    if beat_count == 15 and not missing_fields:
        report = (
            "PASS\n"
            "总评：当前三幕十五节拍卡点时间轴结构完整，关键字段齐全，可进入下一阶段。\n"
            "建议：后续只需在人物故事线阶段继续核对 linked_storylines 与节拍分布的一致性。"
        )
    else:
        missing_text = "、".join(missing_fields) if missing_fields else "未知缺口"
        report = (
            "REVISE\n"
            f"总评：当前框架仍需修订，beat 数量={beat_count}。\n"
            f"问题定位：缺少或不完整字段 {missing_text}。\n"
            "建议：补齐 15 条节拍，并完善每条节拍的核心叙事字段后重新评分。"
        )

    return {
        "ok": True,
        "stage": "04",
        "data": {"framework_score_report": report},
        "raw": {
            "mock": True,
            "score_source": "framework_planner_score_mock",
            "beat_count": beat_count,
            "missing_fields": missing_fields,
        },
        "display_text": report,
    }


@lru_cache(maxsize=1)
def framework_workflow_dir() -> Path:
    yaml_default = Path(__file__).resolve().parents[3] / "BETTER_FRAMEWORK_YAML"
    configured = _env("FRAMEWORK_PLANNER_WORKFLOW_DIR", "BETTER_FRAMEWORK_YAML_DIR")
    if configured:
        path = Path(configured).expanduser().resolve()
    elif yaml_default.exists():
        path = yaml_default.resolve()
    else:
        legacy_configured = _env("BETTER_FRAMEWORK_JSONS_DIR")
        path = Path(legacy_configured).expanduser().resolve() if legacy_configured else yaml_default
    if not path.exists():
        raise FrameworkPlannerStageError(
            "未找到 BETTER_FRAMEWORK_YAML 工作流目录",
            stage="00",
            status_code=500,
            detail={"workflow_dir": str(path)},
        )
    return path


@lru_cache(maxsize=1)
def resolve_framework_contract_path() -> Path | None:
    exact = framework_workflow_dir() / "00_CONTRACT.md"
    if exact.exists():
        return exact
    matches = sorted(framework_workflow_dir().glob(FRAMEWORK_CONTRACT_GLOB))
    if matches:
        return matches[0]
    return None


@lru_cache(maxsize=None)
def resolve_stage_workflow_path(stage: str) -> Path:
    definition = stage_definition(stage)
    matches = sorted(framework_workflow_dir().glob(definition.workflow_glob))
    if not matches:
        raise FrameworkPlannerStageError(
            f"未找到阶段 {definition.stage} 对应的工作流 JSON",
            stage=definition.stage,
            status_code=500,
            detail={
                "workflow_dir": str(framework_workflow_dir()),
                "workflow_glob": definition.workflow_glob,
            },
        )
    return matches[0]


def _load_workflow_document(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".yaml", ".yml"}:
        loaded = yaml.safe_load(text)
    else:
        loaded = json.loads(text)
    return loaded if isinstance(loaded, dict) else {}


def _yaml_workflow_public_keys(workflow: dict[str, Any]) -> tuple[str, ...]:
    keys: list[str] = []
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("type") or "") != "start":
            continue
        outputs = (node.get("parameters") or {}).get("node_outputs") or {}
        if not isinstance(outputs, dict):
            continue
        for key in outputs.keys():
            key_text = str(key or "").strip()
            if key_text:
                keys.append(key_text)
    return tuple(dict.fromkeys(keys))


def _yaml_workflow_answer_names(workflow: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("type") or "") != "end":
            continue
        inputs = (node.get("parameters") or {}).get("node_inputs") or []
        if not isinstance(inputs, list):
            continue
        for item in inputs:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name:
                names.append(name)
    return tuple(dict.fromkeys(names))


@lru_cache(maxsize=None)
def load_stage_workflow_spec(stage: str) -> FrameworkPlannerWorkflowSpec:
    path = resolve_stage_workflow_path(stage)
    try:
        workflow = _load_workflow_document(path)
    except Exception as exc:
        raise FrameworkPlannerStageError(
            f"无法读取阶段 {stage} 工作流 JSON",
            stage=stage,
            status_code=500,
            detail={"workflow_json_path": str(path)},
        ) from exc

    yaml_public_keys = _yaml_workflow_public_keys(workflow)
    if yaml_public_keys:
        return FrameworkPlannerWorkflowSpec(
            stage=str(stage).zfill(2),
            path=path,
            public_variable_keys=yaml_public_keys,
            internal_variable_keys=(),
            answer_node_names=_yaml_workflow_answer_names(workflow),
            contract_path=resolve_framework_contract_path(),
        )

    public_keys: list[str] = []
    internal_keys: list[str] = []
    for item in (workflow.get("chatConfig") or {}).get("variables") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        if str(item.get("type") or "").strip().lower() == "internal":
            internal_keys.append(key)
        else:
            public_keys.append(key)

    answer_node_names = tuple(
        str(node.get("name") or node.get("nodeId") or "").strip()
        for node in (workflow.get("nodes") or [])
        if isinstance(node, dict) and str(node.get("flowNodeType") or "").strip() == "answerNode"
    )
    return FrameworkPlannerWorkflowSpec(
        stage=str(stage).zfill(2),
        path=path,
        public_variable_keys=tuple(public_keys),
        internal_variable_keys=tuple(internal_keys),
        answer_node_names=tuple(name for name in answer_node_names if name),
        contract_path=resolve_framework_contract_path(),
    )


def _normalize_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(payload or {})
    stage_prompts = normalized.get("user_knowledge_stage_prompts")
    prompt_preferences = normalized.get("prompt_preferences") if isinstance(normalized.get("prompt_preferences"), dict) else {}
    if not isinstance(stage_prompts, dict):
        stage_prompts = prompt_preferences.get("stage_prompts") if isinstance(prompt_preferences.get("stage_prompts"), dict) else {}
    merged_stage_prompts = _merge_stage_prompt_payloads_non_empty(
        prompt_preferences.get("stage_prompts") if isinstance(prompt_preferences.get("stage_prompts"), dict) else {},
        normalized.get("stage_prompts") if isinstance(normalized.get("stage_prompts"), dict) else {},
        stage_prompts,
    )
    normalized["user_knowledge_stage_prompts"] = merged_stage_prompts
    prompt_preferences = dict(prompt_preferences)
    prompt_preferences["stage_prompts"] = merged_stage_prompts
    normalized["prompt_preferences"] = prompt_preferences
    if "selected_preference_tags" not in normalized or not isinstance(normalized.get("selected_preference_tags"), list):
        normalized["selected_preference_tags"] = []
    if "selected_preference_tag_ids" not in normalized or not isinstance(normalized.get("selected_preference_tag_ids"), list):
        normalized["selected_preference_tag_ids"] = []
    normalized["user_preference_prompt"] = _coerce_text_payload(normalized.get("user_preference_prompt"))
    normalized["user_knowledge_tag_prompt"] = _coerce_text_payload(normalized.get("user_knowledge_tag_prompt"))
    return normalized


FRAMEWORK_PLANNER_STAGE_KEY_BY_STAGE = {
    "01": "basic",
    "02": "worldview",
    "03": "character",
    "04": "beat",
    "05": "storylines",
    "06": "guide",
    "07": "package",
}


def framework_planner_stage_key(stage: Any) -> str:
    return FRAMEWORK_PLANNER_STAGE_KEY_BY_STAGE.get(str(stage or "").zfill(2), "")


def resolve_stage_preference_prompt(stage: Any, payload: dict[str, Any] | None) -> str:
    """Resolve only the current 01-07 stage preference prompt."""
    stage_key = framework_planner_stage_key(stage)
    if not stage_key:
        return ""
    source = payload if isinstance(payload, dict) else {}
    stage_prompts = source.get("user_knowledge_stage_prompts")
    if isinstance(stage_prompts, dict):
        prompt = _coerce_text_payload(stage_prompts.get(stage_key))
        if prompt:
            return prompt
    prompt_preferences = source.get("prompt_preferences") if isinstance(source.get("prompt_preferences"), dict) else {}
    pref_stage_prompts = prompt_preferences.get("stage_prompts") if isinstance(prompt_preferences.get("stage_prompts"), dict) else {}
    prompt = _coerce_text_payload(pref_stage_prompts.get(stage_key))
    if prompt:
        return prompt
    return _coerce_text_payload(source.get("user_preference_prompt") or source.get("user_knowledge_tag_prompt"))


def _normalize_stage_prompt_payload(value: Any) -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    return {
        key: _coerce_text_payload(source.get(key))
        for key in (
            "basic",
            "worldview",
            "character",
            "beat",
            "storylines",
            "guide",
            "package",
            "scene",
            "appearance",
            "episode",
            "conflict",
            "script_text",
        )
    }


def _merge_stage_prompt_payloads_non_empty(*sources: Any) -> dict[str, str]:
    result = _normalize_stage_prompt_payload({})
    for source in sources:
        normalized = _normalize_stage_prompt_payload(source)
        for key, value in normalized.items():
            if value:
                result[key] = value
    return result


def _coerce_text_payload(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value).strip()


def _should_use_mock_backend(definition: FrameworkPlannerStageDefinition) -> bool:
    return _env_bool("FRAMEWORK_PLANNER_USE_MOCK", default=False)


def _build_stage_request_variables(
    definition: FrameworkPlannerStageDefinition,
    payload: dict[str, Any],
    workflow_spec: FrameworkPlannerWorkflowSpec,
) -> dict[str, Any]:
    variables: dict[str, Any] = {}
    missing_fields: list[str] = []
    public_keys = set(workflow_spec.public_variable_keys)

    for field in definition.input_fields:
        aliases = definition.input_aliases.get(field, (field,))
        value = _first_present_value(payload, aliases)
        if field == "locked_basic_config" and _is_blank(value):
            value = payload.get("basic_config")
        if field == "basic_config" and _is_blank(value):
            value = payload.get("locked_basic_config")
        if definition.stage == "07" and field == "adaptation_guide" and _is_blank(value):
            framework_plan_package = payload.get("framework_plan_package")
            if isinstance(framework_plan_package, dict):
                value = (
                        framework_plan_package.get("adaptation_guide")
                        or framework_plan_package.get("adaptationGuide")
                        or framework_plan_package.get("overallAdaptationGuide")
                        or framework_plan_package.get("overall_adaptation_guide")
                        or framework_plan_package.get("guide")
                )
            if _is_blank(value):
                value = (
                        payload.get("adaptation_guide")
                        or payload.get("adaptationGuide")
                        or payload.get("overallAdaptationGuide")
                        or payload.get("overall_adaptation_guide")
                        or payload.get("guide")
                        or payload.get("previous_adaptation_guide")
                )

        if field in definition.required_fields and _is_blank(value):
            missing_fields.append(field)
            continue
        if _is_blank(value):
            continue
        cleaned_value = _sanitize_stage_input_value(definition.stage, field, value)
        if cleaned_value is not value:
            logger.warning(
                "framework planner payload field cleaned before FastGPT request: stage=%s field=%s original_type=%s cleaned_type=%s original_preview=%s",
                definition.stage,
                field,
                type(value).__name__,
                type(cleaned_value).__name__,
                _preview_return_object(value, limit=300),
            )
            value = cleaned_value
        if field in definition.required_fields and _is_blank(value):
            missing_fields.append(field)
            continue
        wire_value = _wire_value(value)
        variables[field] = wire_value
        for alias in aliases:
            if alias == field or alias in public_keys:
                variables[alias] = wire_value
    # Stage 07 compatibility fallback:
    # Some frontend payloads carry adaptation_guide with the new schema
    # but the generic required-field loop may still mark it as missing.
    # Resolve it one final time before failing the request.
    if definition.stage == "07" and "adaptation_guide" in missing_fields:
        raw_guide = (
            payload.get("adaptation_guide")
            or payload.get("adaptationGuide")
            or payload.get("overallAdaptationGuide")
            or payload.get("overall_adaptation_guide")
            or payload.get("guide")
            or payload.get("previous_adaptation_guide")
        )

        framework_plan_package = payload.get("framework_plan_package")
        if not raw_guide and isinstance(framework_plan_package, dict):
            raw_guide = (
                framework_plan_package.get("adaptation_guide")
                or framework_plan_package.get("adaptationGuide")
                or framework_plan_package.get("overallAdaptationGuide")
                or framework_plan_package.get("overall_adaptation_guide")
                or framework_plan_package.get("guide")
            )

        normalized_guide = _normalize_adaptation_guide(raw_guide)

        if isinstance(normalized_guide, dict) and normalized_guide:
            wire_value = _wire_value(normalized_guide)

            variables["adaptation_guide"] = wire_value
            variables["adaptationGuide"] = wire_value

            payload["adaptation_guide"] = normalized_guide
            payload["adaptationGuide"] = normalized_guide

            missing_fields = [
                field for field in missing_fields
                if field != "adaptation_guide"
            ]

            logger.warning(
                "stage07 adaptation_guide recovered before missing_fields failure: keys=%s",
                list(normalized_guide.keys()),
            )

    if missing_fields:
        logger.error(
            "framework planner payload missing required fields timestamp=%s stage=%s payload_keys=%s exception_type=%s exception_message=%s missing_fields=%s; request not sent",
            _history_iso_timestamp(),
            definition.stage,
            sorted(payload.keys()),
            "MissingRequiredFields",
            f"missing required fields: {', '.join(missing_fields)}",
            missing_fields,
        )
        print_stage_debug(
            definition.stage,
            {
                "ok": False,
                "stage": definition.stage,
                "status": "failed",
                "reason": f"payload 缺少必填字段：{', '.join(missing_fields)}",
                "exception_type": "MissingRequiredFields",
                "exception_message": f"missing required fields: {', '.join(missing_fields)}",
                "missing_fields": missing_fields,
            },
            payload,
        )
        raise FrameworkPlannerStageError(
            f"阶段 {definition.stage} 缺少必填项：{', '.join(missing_fields)}",
            stage=definition.stage,
            status_code=400,
            detail={"missing_fields": missing_fields},
        )

    stage_preference_prompt = resolve_stage_preference_prompt(definition.stage, payload)
    if stage_preference_prompt:
        for preference_key in (
            "stagePreference",
            "stage_preference",
            "stage_preference_prompt",
            "user_stage_preference_prompt",
            "user_feedback",
            "user_preference_prompt",
            "user_preferences",
            "userPreferences",
            "userRequirements",
            "user_constraints",
        ):
            existing = _coerce_text_payload(variables.get(preference_key))
            if existing and preference_key in {"user_preferences", "userPreferences", "userRequirements", "user_constraints"}:
                variables[preference_key] = _wire_value(f"{existing}\n\n{stage_preference_prompt}")
            elif not existing:
                variables[preference_key] = _wire_value(stage_preference_prompt)

    for key, value in payload.items():
        if key in variables or _is_blank(value):
            continue
        if definition.stage in STAGE_DEFINITIONS and key not in public_keys and key not in {
            "selected_preference_tags",
            "selected_preference_tag_ids",
            "user_preference_prompt",
            "user_knowledge_tag_prompt",
            "user_knowledge_stage_prompts",
            "stage_preference_prompt",
            "user_stage_preference_prompt",
            "prompt_preferences",
        }:
            continue
        variables[key] = _wire_value(value)

    if _is_coze_backend():
        _ensure_coze_public_parameters(variables, workflow_spec)

    stage_key = framework_planner_stage_key(definition.stage)
    selected_tags = payload.get("selected_preference_tags") if isinstance(payload.get("selected_preference_tags"), list) else []
    tags_with_stage_preference_count = 0
    for tag in selected_tags:
        if not isinstance(tag, dict):
            continue
        prompts = tag.get("stage_prompts") if isinstance(tag.get("stage_prompts"), dict) else {}
        if _coerce_text_payload(prompts.get(stage_key)):
            tags_with_stage_preference_count += 1
    logger.info(
        "framework planner user knowledge fields: stage_key=%s stage_name=%s preference_source=智慧库标签 preference_stage_key=%s preference_stage_label=%s selected_tag_count=%s tags_with_stage_preference_count=%s has_stage_preference=%s preference_length=%s",
        definition.stage,
        {
            "basic": "01 原文提取偏好",
            "worldview": "02 世界观偏好",
            "character": "03 人设偏好",
            "beat": "04 节拍规划偏好",
            "storylines": "05 人物故事线偏好",
            "guide": "06 改编指引偏好",
            "package": "07 框架校验偏好",
        }.get(stage_key, ""),
        stage_key,
        {
            "basic": "01 原文提取偏好",
            "worldview": "02 世界观偏好",
            "character": "03 人设偏好",
            "beat": "04 节拍规划偏好",
            "storylines": "05 人物故事线偏好",
            "guide": "06 改编指引偏好",
            "package": "07 框架校验偏好",
        }.get(stage_key, ""),
        len(selected_tags or payload.get("selected_preference_tag_ids") or []),
        tags_with_stage_preference_count,
        bool(stage_preference_prompt),
        len(stage_preference_prompt),
    )

    return variables


def _ensure_coze_public_parameters(
    variables: dict[str, Any],
    workflow_spec: FrameworkPlannerWorkflowSpec,
) -> None:
    """Coze validates declared start-node parameters by key presence."""
    for key in workflow_spec.public_variable_keys:
        key_text = str(key or "").strip()
        if key_text and key_text not in variables:
            variables[key_text] = ""


def _resolve_stage_endpoint(definition: FrameworkPlannerStageDefinition) -> FrameworkPlannerEndpoint:
    api_key_source, api_key = _coze_api_token_with_name()
    if not api_key:
        raise FrameworkPlannerStageError(
            "Coze API token is not configured for this stage",
            stage=definition.stage,
            status_code=500,
            detail={
                "reason": "Missing Coze API token configuration",
                "expected_envs": list(_coze_api_token_env_names()),
            },
        )

    workflow_id_source, workflow_id = _stage_workflow_id_with_name(definition)
    if not workflow_id:
        raise FrameworkPlannerStageError(
            "Coze workflow_id is not hardcoded for this stage",
            stage=definition.stage,
            status_code=500,
            detail={
                "reason": "Missing hardcoded Coze workflow_id configuration",
                "expected_config": _stage_workflow_id_config_key(definition),
            },
        )


    url_source, raw_url = _coze_api_base_with_name(api_key_source)
    return FrameworkPlannerEndpoint(
        url=_normalize_coze_workflow_url(raw_url or DEFAULT_NS_WORKFLOW_URL),
        url_source=url_source or "default",
        api_key=api_key,
        api_key_source=api_key_source or "ns_primary_api_token",
        workflow_id=str(workflow_id or "").strip(),
        workflow_id_source=workflow_id_source or "",
        chat_id=f"framework-planner-{definition.stage}-{uuid.uuid4().hex[:8]}",
        timeout=DEFAULT_NS_TIMEOUT_SECONDS,
    )


def _stage_api_key_env_names(definition: FrameworkPlannerStageDefinition) -> tuple[str, ...]:
    return (
        f"{definition.env_prefix}_API_KEY",
        *LEGACY_STAGE_API_KEY_ENVS.get(definition.stage, ()),
        "FASTGPT_FRAMEWORK_API_KEY",
        "FASTGPT_NEW_FRAMEWORK_API_KEY",
        "FASTGPT_API_KEY",
    )


def _stage_url_env_names(definition: FrameworkPlannerStageDefinition) -> tuple[str, ...]:
    return (
        f"{definition.env_prefix}_URL",
        f"{definition.env_prefix}_API_URL",
        f"{definition.env_prefix}_CHAT_COMPLETIONS_URL",
        f"{definition.env_prefix}_BASE_URL",
        "FASTGPT_FRAMEWORK_URL",
        "FASTGPT_FRAMEWORK_API_URL",
        "FASTGPT_FRAMEWORK_CHAT_COMPLETIONS_URL",
        "FASTGPT_FRAMEWORK_BASE_URL",
        "FASTGPT_CHAT_COMPLETIONS_URL",
        "FASTGPT_API_URL",
        "FASTGPT_BASE_URL",
    )


def _stage_workflow_id_env_names(definition: FrameworkPlannerStageDefinition) -> tuple[str, ...]:
    return (
        _stage_workflow_id_config_key(definition),
    )


def _stage_workflow_id_config_key(definition: FrameworkPlannerStageDefinition) -> str:
    return f"ns_workflow_stage_{definition.stage}_id"


def _stage_workflow_id_with_name(definition: FrameworkPlannerStageDefinition) -> tuple[str, str]:
    return "hardcoded", str(FRAMEWORK_PLANNER_WORKFLOW_IDS.get(definition.stage, "") or "").strip()


def _build_request_body(
    definition: FrameworkPlannerStageDefinition,
    variables: dict[str, Any],
    endpoint: FrameworkPlannerEndpoint,
) -> dict[str, Any]:
    return {
        "workflow_id": endpoint.workflow_id,
        "parameters": variables,
    }


def _post_with_retries(
    definition: FrameworkPlannerStageDefinition,
    endpoint: FrameworkPlannerEndpoint,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    diagnostics: dict[str, Any] | None = None,
) -> requests.Response:
    attempts = max(1, DEFAULT_NS_HTTP_RETRIES + 1)
    delay = max(0.0, DEFAULT_NS_HTTP_RETRY_DELAY_SECONDS)
    last_exception: Exception | None = None
    last_response: requests.Response | None = None
    safe_diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    parameter_keys = sorted(str(key) for key in (body.get("parameters") or {}).keys()) if isinstance(body, dict) else []

    def build_error(
        *,
        reason: str,
        status_code: int,
        exc: Exception | None = None,
        response: requests.Response | None = None,
    ) -> FrameworkPlannerStageError:
        preview = safe_truncated_preview(_safe_response_text(response), limit=1200) if response is not None else ""
        detail = {
            "reason": reason,
            "stage": definition.stage,
            "endpoint": endpoint.url,
            "url_source": endpoint.url_source or "default",
            "workflow_id_source": endpoint.workflow_id_source or "",
            "attempts": attempts,
            "response_status_code": getattr(response, "status_code", None),
            "response_preview": preview,
            "diagnostics": safe_diagnostics,
        }
        if exc is not None:
            detail["exception_type"] = type(exc).__name__
            detail["exception_message"] = str(exc)
        return FrameworkPlannerStageError(
            f"Stage {definition.stage} Coze request failed",
            stage=definition.stage,
            status_code=status_code,
            detail=detail,
        )

    for attempt_index in range(1, attempts + 1):
        logger.info(
            "Coze request start: stage=%s attempt=%s/%s endpoint=%s timeout_seconds=%s workflow_id_source=%s parameter_keys=%s",
            definition.stage,
            attempt_index,
            attempts,
            endpoint.url,
            endpoint.timeout,
            endpoint.workflow_id_source or "",
            parameter_keys,
        )
        attempt_started_at = time.monotonic()
        try:
            response = requests.post(
                endpoint.url,
                headers=headers,
                json=body,
                timeout=endpoint.timeout,
            )
        except requests.Timeout as exc:
            last_exception = exc
            response = _exception_response(exc)
            if response is not None:
                last_response = response
            logger.warning(
                "Coze request timeout: stage=%s attempt=%s/%s elapsed_seconds=%.3f exception=%s",
                definition.stage,
                attempt_index,
                attempts,
                time.monotonic() - attempt_started_at,
                exc,
            )
            if attempt_index >= attempts:
                raise build_error(
                    reason=f"Coze request timed out after {attempts} attempts",
                    status_code=504,
                    exc=exc,
                    response=response,
                ) from exc
            time.sleep(delay * attempt_index)
            continue
        except requests.RequestException as exc:
            last_exception = exc
            response = _exception_response(exc)
            if response is not None:
                last_response = response
            logger.warning(
                "Coze request exception: stage=%s attempt=%s/%s elapsed_seconds=%.3f exception_type=%s exception=%s response_preview=%s",
                definition.stage,
                attempt_index,
                attempts,
                time.monotonic() - attempt_started_at,
                type(exc).__name__,
                exc,
                safe_truncated_preview(_safe_response_text(response), limit=800) if response is not None else "",
            )
            if attempt_index >= attempts:
                raise build_error(
                    reason=f"Coze network request failed after {attempts} attempts",
                    status_code=502,
                    exc=exc,
                    response=response,
                ) from exc
            time.sleep(delay * attempt_index)
            continue

        last_response = response
        logger.info(
            "Coze request response: stage=%s attempt=%s status_code=%s elapsed_seconds=%.3f response_preview=%s",
            definition.stage,
            attempt_index,
            response.status_code,
            time.monotonic() - attempt_started_at,
            safe_truncated_preview(_safe_response_text(response), limit=800),
        )
        if response.status_code in RETRYABLE_HTTP_STATUSES and attempt_index < attempts:
            time.sleep(delay * attempt_index)
            continue
        if response.status_code >= 400:
            raise build_error(
                reason=f"Coze returned HTTP {response.status_code}",
                status_code=502 if response.status_code >= 500 else 400,
                response=response,
            )
        return response

    raise build_error(
        reason="Coze request did not complete successfully",
        status_code=502,
        exc=last_exception,
        response=last_response,
    )


def _json_objects_from_text(text: Any) -> list[Any]:
    """从字符串中提取一个或多个 JSON 对象。

    FastGPT 某些 answerText/text.content 会出现：
    1. 单个 JSON 字符串；
    2. 两个 JSON 对象连续拼接；
    3. 前后带空白或非 JSON 文本。
    这里不能只用 json.loads()，需要 raw_decode 扫描。
    """
    if not isinstance(text, str):
        return []
    raw = text.strip()
    if not raw:
        return []

    try:
        return [json.loads(raw)]
    except Exception:
        pass

    decoder = json.JSONDecoder()
    results: list[Any] = []
    index = 0
    length = len(raw)

    while index < length:
        next_object = raw.find("{", index)
        next_array = raw.find("[", index)
        starts = [pos for pos in (next_object, next_array) if pos >= 0]
        if not starts:
            break

        index = min(starts)
        try:
            value, end = decoder.raw_decode(raw[index:])
        except Exception:
            index += 1
            continue

        results.append(value)
        index += max(end, 1)

    return results


def _candidate_has_stage_output_field(candidate: Any, output_fields: tuple[str, ...]) -> bool:
    """判断候选对象是否包含当前阶段约定输出字段。"""
    if not isinstance(candidate, dict):
        return False

    for field in output_fields:
        value = candidate.get(field)
        if value not in (None, "", [], {}):
            return True

    data = candidate.get("data")
    if isinstance(data, dict):
        for field in output_fields:
            value = data.get(field)
            if value not in (None, "", [], {}):
                return True

    output = candidate.get("output")
    if isinstance(output, dict):
        for field in output_fields:
            value = output.get(field)
            if value not in (None, "", [], {}):
                return True

    return False


def _iter_choice_message_texts(response_json: Any) -> list[str]:
    """兼容 FastGPT/OpenAI 风格 choices[].message.content。

    当前 FastGPT 返回里 content 可能不是 str，而是 list：
    [
      {"type": "reasoning", ...},
      {"type": "text", "text": {"content": "..."}}
    ]
    """
    if not isinstance(response_json, dict):
        return []

    texts: list[str] = []
    choices = response_json.get("choices")
    if not isinstance(choices, list):
        return texts

    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue

        content = message.get("content")
        if isinstance(content, str) and content.strip():
            texts.append(content)
            continue

        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue

                text_block = block.get("text")
                if isinstance(text_block, dict):
                    text_content = text_block.get("content")
                    if isinstance(text_content, str) and text_content.strip():
                        texts.append(text_content)

                direct_content = block.get("content")
                if isinstance(direct_content, str) and direct_content.strip():
                    texts.append(direct_content)

                # 工具调用返回里有时也会包一层 response 字符串。
                tools = block.get("tools")
                if isinstance(tools, list):
                    for tool in tools:
                        if isinstance(tool, dict):
                            response_text = tool.get("response")
                            if isinstance(response_text, str) and response_text.strip():
                                texts.append(response_text)

    return texts


def _iter_fastgpt_structured_output_candidates(
    response_json: Any,
    output_fields: tuple[str, ...],
) -> list[tuple[str, Any]]:
    """从 FastGPT 原始返回中优先提取真正的阶段业务 JSON。

    优先级：
    1. responseData[].textOutput
    2. responseData[].updateVarResult[]
    3. newVariables 中所有字符串变量
    4. choices[].message.content 的 text 块
    """
    candidates: list[tuple[str, Any]] = []
    seen: set[str] = set()

    def add_candidate(source: str, value: Any) -> None:
        parsed_values: list[Any]

        if isinstance(value, str):
            parsed_values = _json_objects_from_text(value)
        else:
            parsed_values = [value]

        for parsed in parsed_values:
            if not _candidate_has_stage_output_field(parsed, output_fields):
                continue
            try:
                key = json.dumps(parsed, ensure_ascii=False, sort_keys=True, default=str)
            except Exception:
                key = repr(parsed)
            if key in seen:
                continue
            seen.add(key)
            candidates.append((source, parsed))

    if not isinstance(response_json, dict):
        return candidates

    response_data = response_json.get("responseData")
    if isinstance(response_data, list):
        for index, item in enumerate(response_data):
            if not isinstance(item, dict):
                continue

            add_candidate(f"responseData[{index}].textOutput", item.get("textOutput"))
            add_candidate(f"responseData[{index}].answerText", item.get("answerText"))

            update_results = item.get("updateVarResult")
            if isinstance(update_results, list):
                for sub_index, value in enumerate(update_results):
                    add_candidate(f"responseData[{index}].updateVarResult[{sub_index}]", value)

            tool_detail = item.get("toolDetail")
            if isinstance(tool_detail, list):
                for sub_index, detail in enumerate(tool_detail):
                    if not isinstance(detail, dict):
                        continue
                    add_candidate(f"responseData[{index}].toolDetail[{sub_index}].response", detail.get("response"))
                    add_candidate(
                        f"responseData[{index}].toolDetail[{sub_index}].toolParamsResult",
                        detail.get("toolParamsResult"),
                    )

    new_variables = response_json.get("newVariables")
    if isinstance(new_variables, dict):
        for key, value in new_variables.items():
            add_candidate(f"newVariables.{key}", value)

    for index, text in enumerate(_iter_choice_message_texts(response_json)):
        add_candidate(f"choices.message.content[{index}]", text)

    return candidates


def _stage_payload_object_from_candidate(candidate: Any, output_fields: tuple[str, ...]) -> dict[str, Any]:
    """从候选对象中取出真正包含阶段输出字段的 dict。"""
    if not isinstance(candidate, dict):
        return {}

    for wrapper_key in ("output", "data"):
        wrapped = candidate.get(wrapper_key)
        if isinstance(wrapped, dict):
            for field in output_fields:
                value = wrapped.get(field)
                if value not in (None, "", [], {}):
                    return wrapped

    for field in output_fields:
        value = candidate.get(field)
        if value not in (None, "", [], {}):
            return candidate

    return {}


def _force_repair_stage_output_from_raw_fastgpt(
    *,
    definition: Any,
    response_json: Any,
    data: Any,
    display_text: str,
    parse_warnings: list[str],
) -> tuple[dict[str, Any], str, list[str]]:
    """用 FastGPT 原始返回里的有效业务 JSON 覆盖兜底结果。"""
    output_fields = tuple(getattr(definition, "output_fields", ()) or ())
    if not output_fields:
        return dict(data if isinstance(data, dict) else {}), display_text, parse_warnings

    repaired = dict(data if isinstance(data, dict) else {})
    warnings = list(parse_warnings or [])

    candidates = _iter_fastgpt_structured_output_candidates(response_json, output_fields)
    if not candidates:
        return repaired, display_text, warnings

    for source, candidate in candidates:
        stage_object = _stage_payload_object_from_candidate(candidate, output_fields)
        if not stage_object:
            continue

        copied_fields: list[str] = []
        for field in output_fields:
            value = stage_object.get(field)
            if value not in (None, "", [], {}):
                repaired[field] = value
                copied_fields.append(field)

        raw_display_text = stage_object.get("display_text")
        if isinstance(raw_display_text, str) and raw_display_text.strip():
            display_text = raw_display_text.strip()
            repaired["display_text"] = display_text

        if copied_fields:
            warnings.append(
                f"已从 FastGPT 原始返回修复阶段输出 source={source} fields={','.join(copied_fields)}"
            )
            try:
                logger.warning(
                    "[framework_planner_parser_repair] stage=%s source=%s fields=%s",
                    getattr(definition, "stage", ""),
                    source,
                    copied_fields,
                )
            except Exception:
                pass
            return repaired, display_text, warnings

    return repaired, display_text, warnings


def _extract_stage_output(
    *,
    definition: FrameworkPlannerStageDefinition,
    workflow_spec: FrameworkPlannerWorkflowSpec,
    response_json: Any,
    payload_keys: list[str] | None = None,
) -> tuple[dict[str, Any], str, list[str]]:
    output_aliases = definition.output_aliases
    parse_warnings: list[str] = []
    stage_payload_keys = sorted(set(payload_keys or []))
    if definition.stage == "04":
        extracted = _stage04_extract_payload_from_nested_coze(response_json)
        if isinstance(extracted, dict) and isinstance(extracted.get("beat_checkpoint_timeline"), list):
            parse_warnings.append(
                "Stage04 已通过专用嵌套解析器提取 beat_checkpoint_timeline/checkpoint_explanation"
            )
            normalized = _normalize_stage_output(
                definition.stage,
                extracted,
                parse_warnings=parse_warnings,
            )
            display_text = _extract_display_text(
                response_json,
                normalized,
                stage=definition.stage,
                payload_keys=stage_payload_keys,
            )
            return normalized, display_text, parse_warnings
    try:
        # Normalize 01~07 root responses before any .get() access in candidate iteration.
        root_response = normalize_stage_response(
            response_json,
            stage=definition.stage,
            payload_keys=stage_payload_keys,
        )
    except Exception as exc:
        _log_stage_output_parse_exception(
            stage=definition.stage,
            payload_keys=stage_payload_keys,
            exc=exc,
            raw_return_object=response_json,
        )
        parse_warnings.append(
            f"阶段 {definition.stage} 根响应解析异常，已回退为空对象：{type(exc).__name__}: {exc}"
        )
        root_response = {}

    try:
        response_candidates = list(
            _iter_response_candidates(
                response_json,
                workflow_spec,
                root_response=root_response,
                stage=definition.stage,
                payload_keys=stage_payload_keys,
            )
        )
        structured_candidates = _iter_fastgpt_structured_output_candidates(
            response_json,
            definition.output_fields,
        )
        if structured_candidates:
            response_candidates = structured_candidates + response_candidates
    except Exception as exc:
        _log_stage_output_parse_exception(
            stage=definition.stage,
            payload_keys=stage_payload_keys,
            exc=exc,
            raw_return_object=response_json,
        )
        parse_warnings.append(
            f"阶段 {definition.stage} 候选输出提取异常，已回退到安全解析：{type(exc).__name__}: {exc}"
        )
        response_candidates = [("safe_root_fallback", root_response or response_json)]

    if definition.stage == "05":
        _log_stage_05_candidate_diagnostics(response_candidates, root_response)

    for source, candidate in response_candidates:
        if definition.stage == "05":
            selected = _select_stage_05_candidate(candidate)
            if selected is not None:
                normalized = _normalize_stage_output(
                    definition.stage,
                    selected,
                    parse_warnings=parse_warnings,
                )
                logger.info(
                    "stage=05 selected_candidate_source=%s selected_candidate_keys=%s character_storylines_length=%s fallback_used=%s",
                    source,
                    sorted(selected.keys()),
                    len(selected.get("character_storylines") or []),
                    source in {"root_fallback", "raw_response_fallback", "safe_root_fallback"},
                )
                display_text = _extract_display_text(
                    response_json,
                    normalized,
                    stage=definition.stage,
                    payload_keys=stage_payload_keys,
                )
                return normalized, display_text, parse_warnings
        try:
            mapped, candidate_warnings = _coerce_candidate_to_stage_output(
                definition,
                candidate,
                output_aliases,
                allow_dict_as_field=False,
            )
        except Exception as exc:
            _log_stage_output_parse_exception(
                stage=definition.stage,
                payload_keys=stage_payload_keys,
                exc=exc,
                raw_return_object=candidate,
            )
            parse_warnings.append(
                f"阶段 {definition.stage} 候选 {source} 解析异常，已跳过：{type(exc).__name__}: {exc}"
            )
            continue
        if mapped is not None:
            parse_warnings.extend(candidate_warnings)
            safe_output, safe_warnings = safe_parse_stage_output(
                mapped,
                (*definition.output_fields, "display_text"),
            )
            parse_warnings.extend(safe_warnings)
            normalized = _normalize_stage_output(
                definition.stage,
                safe_output,
                parse_warnings=parse_warnings,
            )
            if definition.stage == "05" and not normalized.get("character_storylines"):
                continue
            _log_stage_parse_warnings(definition.stage, parse_warnings)
            display_text = _extract_display_text(
                response_json,
                normalized,
                stage=definition.stage,
                payload_keys=stage_payload_keys,
            )
            return normalized, display_text, parse_warnings

    parse_warnings.append(
        f"未能提取阶段 {definition.stage} 约定输出字段 {definition.output_fields}，已回退到安全解析占位"
    )
    if definition.stage == "05":
        logger.warning(
            "stage=05 no_valid_candidate_found checked_candidate_count=%s required_keys=%s",
            len(response_candidates),
            ["character_storylines", "display_text"],
        )
    parse_warnings.extend(_candidate_diagnostics(definition, response_candidates, output_aliases))
    safe_output, safe_warnings = safe_parse_stage_output(
        root_response or response_json or _empty_stage_output(definition.stage),
        (*definition.output_fields, "display_text"),
    )
    parse_warnings.extend(safe_warnings)
    normalized = _normalize_stage_output(
        definition.stage,
        safe_output,
        parse_warnings=parse_warnings,
    )
    _log_stage_parse_warnings(definition.stage, parse_warnings)
    display_text = _extract_display_text(
        response_json,
        normalized,
        stage=definition.stage,
        payload_keys=stage_payload_keys,
    )
    return normalized, display_text, parse_warnings


def _iter_response_candidates(
    response_json: Any,
    workflow_spec: FrameworkPlannerWorkflowSpec,
    *,
    root_response: dict[str, Any] | None = None,
    stage: str = "",
    payload_keys: list[str] | None = None,
):
    stage_payload_keys = sorted(set(payload_keys or []))
    root_response = normalize_stage_response(
        root_response if root_response is not None else response_json,
        stage=stage,
        payload_keys=stage_payload_keys,
    )
    definition = STAGE_DEFINITIONS.get(str(stage).zfill(2))
    response_data = root_response.get("responseData")
    response_data_dict = response_data if isinstance(response_data, dict) else {}
    response_data_items = _response_data_items(response_data)
    yielded: set[tuple[str, int]] = set()

    def emit(source: str, value: Any):
        if value in (None, "", [], {}):
            return
        marker = (source, id(value))
        if marker in yielded:
            return
        yielded.add(marker)
        yield source, value

    if definition is not None and definition.stage == "04":
        yield from emit("root.beat", root_response.get("beat"))
        data_value = root_response.get("data")
        if isinstance(data_value, dict):
            yield from emit("root.data.beat", data_value.get("beat"))

    if definition is not None:
        for index, node in reversed(response_data_items):
            value = node.get("answerText")
            if value in (None, "", [], {}):
                continue
            if _candidate_has_required_output_key(definition, value):
                module_name = str(node.get("moduleName") or node.get("name") or "").strip()
                source = f"responseData[{index}].answerText"
                logger.info(
                    "stage=%s candidate_source=responseData.answerText moduleName=%s required_key_hit=True summary=%s keys=%s",
                    definition.stage,
                    module_name,
                    _candidate_summary(value, limit=300),
                    _candidate_keys(value),
                )
                yield from emit(source, value)

    for index, node in response_data_items:
        if str(node.get("moduleType") or node.get("flowNodeType") or "").strip() != "answerNode":
            continue
        for field, value in _iter_text_fields(node):
            yield from emit(f"responseData[{index}].{field}", value)

    for index, node in reversed(response_data_items):
        if str(node.get("moduleType") or node.get("flowNodeType") or "").strip() != "chatNode":
            continue
        value = node.get("answerText")
        if value not in (None, "", [], {}):
            yield from emit(f"responseData[{index}].answerText", value)

    variable_containers = [
        ("root.newVariables", root_response.get("newVariables")),
        ("root.variables", root_response.get("variables")),
        ("root.responseData.newVariables", response_data_dict.get("newVariables")),
        ("root.responseData.variables", response_data_dict.get("variables")),
    ]
    for source, value in variable_containers:
        yield from emit(source, value)
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in workflow_spec.internal_variable_keys or key in workflow_spec.public_variable_keys:
                    yield from emit(f"{source}.{key}", nested)

    for list_source, items in (
        ("root.updateVarResult", root_response.get("updateVarResult")),
        ("root.responseData.updateVarResult", response_data_dict.get("updateVarResult")),
    ):
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            variable = item.get("variable")
            if isinstance(variable, list):
                variable_key = str(variable[-1] or "").strip()
            else:
                variable_key = str(variable or item.get("key") or "").strip()
            value = item.get("value")
            if variable_key in workflow_spec.internal_variable_keys or variable_key in workflow_spec.public_variable_keys:
                yield from emit(f"{list_source}[{index}].value", value)

    for source, value in (
        ("root.answerText", root_response.get("answerText")),
        ("root.responseData.answerText", response_data_dict.get("answerText")),
        ("root.responseData.responseText", response_data_dict.get("responseText")),
    ):
        yield from emit(source, value)

    for index, choice in enumerate(root_response.get("choices") or []):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") or {}
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        yield from emit(f"choices[{index}].message.content", content)

    yield from emit("root_fallback", root_response)
    if response_json is not root_response:
        yield from emit("raw_response_fallback", response_json)


def _response_data_items(response_data: Any) -> list[tuple[int, dict[str, Any]]]:
    if isinstance(response_data, list):
        return [(index, item) for index, item in enumerate(response_data) if isinstance(item, dict)]
    if isinstance(response_data, dict):
        return [(0, response_data)]
    return []


def _iter_text_fields(node: dict[str, Any]):
    for field in ("answerText", "responseText", "text", "content"):
        value = node.get(field)
        if value not in (None, "", [], {}):
            yield field, value
    outputs = node.get("outputs")
    if isinstance(outputs, dict):
        for field in ("answerText", "responseText", "text", "content"):
            value = outputs.get(field)
            if value not in (None, "", [], {}):
                yield f"outputs.{field}", value
    answer_node = node.get("answerNode")
    if isinstance(answer_node, dict):
        for field in ("answerText", "responseText", "text", "content"):
            value = answer_node.get(field)
            if value not in (None, "", [], {}):
                yield f"answerNode.{field}", value


def _candidate_has_required_output_key(
    definition: FrameworkPlannerStageDefinition,
    candidate: Any,
) -> bool:
    parsed = _parse_candidate_value(candidate)
    if not isinstance(parsed, dict):
        return False
    return _dict_contains_output_aliases(definition, parsed, definition.output_aliases)


def _candidate_keys(candidate: Any) -> list[str]:
    try:
        parsed = _parse_candidate_value(candidate)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return sorted(str(key) for key in parsed.keys())
    return []


def _candidate_summary(candidate: Any, *, limit: int = 300) -> str:
    if isinstance(candidate, str):
        return _truncate_text(candidate.strip(), limit=limit)
    return _preview_return_object(candidate, limit=limit)


def _candidate_diagnostics(
    definition: FrameworkPlannerStageDefinition,
    response_candidates: list[tuple[str, Any]],
    output_aliases: dict[str, tuple[str, ...]],
) -> list[str]:
    diagnostics = [f"checked_candidate_count={len(response_candidates)}"]
    for source, candidate in response_candidates:
        parsed = _parse_candidate_value(candidate)
        parse_success = isinstance(parsed, (dict, list))
        keys = sorted(str(key) for key in parsed.keys()) if isinstance(parsed, dict) else []
        if isinstance(parsed, dict):
            missing = []
            for field in definition.output_fields:
                aliases = output_aliases.get(field, (field,))
                if _find_value_by_aliases(parsed, aliases) is None:
                    missing.append(field)
            reason = "required_key_hit=True" if not missing else f"missing_required_keys={missing}"
        else:
            reason = f"parsed_type={type(parsed).__name__}"
        diagnostics.append(
            f"candidate_source={source} candidate_type={type(candidate).__name__} "
            f"json_parse_success={parse_success} candidate_keys={keys} reason={reason}"
        )
    return diagnostics


def _log_stage_05_candidate_diagnostics(
    response_candidates: list[tuple[str, Any]],
    root_response: dict[str, Any],
) -> None:
    for index, (source, candidate) in enumerate(response_candidates, start=1):
        module_name, module_type = _candidate_module_info(source, root_response)
        diagnostic = _stage_05_candidate_diagnostic(source, candidate)
        logger.info(
            "stage=05 candidate_diagnostic index=%s source=%s moduleName=%s moduleType=%s raw_type=%s raw_length=%s json_parse_success=%s parsed_type=%s parsed_keys=%s required_key_hit=%s character_storylines_type=%s character_storylines_length=%s",
            index,
            source,
            module_name,
            module_type,
            diagnostic["raw_type"],
            diagnostic["raw_length"],
            diagnostic["json_parse_success"],
            diagnostic["parsed_type"],
            diagnostic["parsed_keys"],
            diagnostic["required_key_hit"],
            diagnostic["character_storylines_type"],
            diagnostic["character_storylines_length"],
        )


def _select_stage_05_candidate(candidate: Any) -> dict[str, Any] | None:
    parsed = _parse_candidate_value(candidate)
    if isinstance(parsed, list):
        if parsed and all(isinstance(item, dict) for item in parsed):
            return {"character_storylines": parsed}
        return None
    if not isinstance(parsed, dict):
        return None
    storylines = parsed.get("character_storylines")
    if storylines is None and isinstance(parsed.get("data"), dict):
        storylines = parsed["data"].get("character_storylines")
    if isinstance(storylines, list) and storylines:
        result = {"character_storylines": storylines}
        display_text = parsed.get("display_text") or parsed.get("displayText")
        if not display_text and isinstance(parsed.get("data"), dict):
            display_text = parsed["data"].get("display_text") or parsed["data"].get("displayText")
        if isinstance(display_text, str) and display_text.strip():
            result["display_text"] = display_text.strip()
        return result
    return None


def _stage_05_candidate_diagnostic(source: str, candidate: Any) -> dict[str, Any]:
    del source
    parsed = _parse_candidate_value(candidate)
    json_parse_success = isinstance(parsed, (dict, list))
    storylines = parsed.get("character_storylines") if isinstance(parsed, dict) else None
    return {
        "raw_type": type(candidate).__name__,
        "raw_length": len(candidate) if isinstance(candidate, str) else len(_preview_return_object(candidate, limit=1000000)),
        "json_parse_success": json_parse_success,
        "parsed_type": type(parsed).__name__,
        "parsed_keys": sorted(str(key) for key in parsed.keys()) if isinstance(parsed, dict) else [],
        "required_key_hit": isinstance(parsed, dict) and "character_storylines" in parsed,
        "character_storylines_type": type(storylines).__name__ if storylines is not None else "none",
        "character_storylines_length": len(storylines) if isinstance(storylines, (list, dict, str)) else 0,
    }


def _candidate_module_info(source: str, root_response: dict[str, Any]) -> tuple[str, str]:
    match = re.search(r"responseData\[(\d+)\]", source)
    if not match:
        return "", ""
    response_data = root_response.get("responseData") if isinstance(root_response, dict) else None
    if not isinstance(response_data, list):
        return "", ""
    index = int(match.group(1))
    if index < 0 or index >= len(response_data) or not isinstance(response_data[index], dict):
        return "", ""
    node = response_data[index]
    return (
        str(node.get("moduleName") or node.get("name") or "").strip(),
        str(node.get("moduleType") or node.get("flowNodeType") or "").strip(),
    )


def _stage_05_output_detail(
    *,
    response_json: Any,
    workflow_spec: FrameworkPlannerWorkflowSpec,
    diagnostics: dict[str, Any],
    data: dict[str, Any],
    parse_warnings: list[str],
) -> dict[str, Any]:
    storylines = data.get("character_storylines") if isinstance(data, dict) else None
    warning_text = " | ".join(str(item) for item in parse_warnings)
    if isinstance(storylines, list) and storylines and "character_storylines 不是 list" not in warning_text:
        return {}
    root_response = normalize_stage_response(response_json, stage="05", payload_keys=diagnostics.get("payload_keys", []))
    candidates = list(_iter_response_candidates(response_json, workflow_spec, root_response=root_response, stage="05"))
    best_source = ""
    best_keys: list[str] = []
    actual_type = "none"
    for source, candidate in candidates:
        parsed = _parse_candidate_value(candidate)
        if isinstance(parsed, dict):
            keys = sorted(str(key) for key in parsed.keys())
            if not best_source:
                best_source = source
                best_keys = keys
            if "character_storylines" in parsed:
                best_source = source
                best_keys = keys
                value = parsed.get("character_storylines")
                actual_type = type(value).__name__ if value is not None else "none"
                break
    reason = "character_storylines_not_list"
    if actual_type == "none":
        reason = "character_storylines_missing"
    return {
        "reason": reason,
        "checked_candidate_count": len(candidates),
        "best_candidate_source": best_source,
        "best_candidate_keys": best_keys,
        "character_storylines_actual_type": actual_type,
        "input_pollution_detected": bool(diagnostics.get("input_pollution_detected")),
        "polluted_fields": diagnostics.get("polluted_fields", []),
    }


def _coerce_candidate_to_stage_output(
    definition: FrameworkPlannerStageDefinition,
    candidate: Any,
    output_aliases: dict[str, tuple[str, ...]],
    *,
    allow_dict_as_field: bool = False,
) -> tuple[dict[str, Any] | None, list[str]]:
    parsed = _parse_candidate_value(candidate)
    if parsed is None:
        return None, []

    if isinstance(parsed, list):
        return _coerce_list_candidate_to_stage_output(
            definition,
            parsed,
            output_aliases,
            allow_dict_as_field=allow_dict_as_field,
        )

    return _coerce_non_list_candidate_to_stage_output(
        definition,
        parsed,
        output_aliases,
        allow_dict_as_field=allow_dict_as_field,
    )


def _coerce_list_candidate_to_stage_output(
    definition: FrameworkPlannerStageDefinition,
    parsed: list[Any],
    output_aliases: dict[str, tuple[str, ...]],
    *,
    allow_dict_as_field: bool = False,
) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    first_item = _first_non_empty_list_item(parsed)
    if first_item is not None:
        first_parsed = _parse_candidate_value(first_item)
        if isinstance(first_parsed, dict) and _dict_contains_output_aliases(definition, first_parsed, output_aliases):
            warnings.append("收到 list 返回，已取第一个元素作为解析对象")
            mapped, nested_warnings = _coerce_non_list_candidate_to_stage_output(
                definition,
                first_parsed,
                output_aliases,
                allow_dict_as_field=allow_dict_as_field,
            )
            return mapped, warnings + nested_warnings
        if definition.stage not in {"05", "06"}:
            warnings.append("收到 list 返回，已取第一个元素作为解析对象")
            mapped, nested_warnings = _coerce_non_list_candidate_to_stage_output(
                definition,
                first_parsed,
                output_aliases,
                allow_dict_as_field=allow_dict_as_field,
            )
            if mapped is not None:
                return mapped, warnings + nested_warnings

    if len(definition.output_fields) == 1:
        warnings.append(f"收到 list 返回，已按 {definition.output_fields[0]} 原样接收")
        return {definition.output_fields[0]: parsed}, warnings

    if definition.stage == "04":
        warnings.append("收到 list 返回，已按 beat_checkpoint_timeline 原样接收，并为 checkpoint_explanation 使用占位结构")
        return {
            "beat_checkpoint_timeline": parsed,
            "checkpoint_explanation": {},
        }, warnings

    warnings.append("收到 list 返回，但未能识别为多字段输出对象，已回退为空结构")
    return _empty_stage_output(definition.stage), warnings


def _unwrap_stage_alias_value(
    value: Any,
    field: str,
    output_aliases: dict[str, tuple[str, ...]],
) -> Any:
    parsed_value = _parse_candidate_value(value)
    if isinstance(parsed_value, dict):
        nested = _find_value_by_aliases(parsed_value, output_aliases.get(field, (field,)))
        if nested is not None:
            return nested
        data = parsed_value.get("data")
        if isinstance(data, dict):
            nested = _find_value_by_aliases(data, output_aliases.get(field, (field,)))
            if nested is not None:
                return nested
    return parsed_value


def _coerce_non_list_candidate_to_stage_output(
    definition: FrameworkPlannerStageDefinition,
    parsed: Any,
    output_aliases: dict[str, tuple[str, ...]],
    *,
    allow_dict_as_field: bool = False,
) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    if len(definition.output_fields) == 1:
        field = definition.output_fields[0]
        if isinstance(parsed, dict):
            direct = _find_value_by_aliases(parsed, output_aliases.get(field, (field,)))
            if direct is not None:
                return _with_optional_display_text({field: _unwrap_stage_alias_value(direct, field, output_aliases)}, parsed), warnings
            if "data" in parsed and isinstance(parsed["data"], dict):
                nested = _find_value_by_aliases(parsed["data"], output_aliases.get(field, (field,)))
                if nested is not None:
                    return _with_optional_display_text({field: _unwrap_stage_alias_value(nested, field, output_aliases)}, parsed, parsed["data"]), warnings
            if field in parsed:
                return _with_optional_display_text({field: parsed[field]}, parsed), warnings
            if allow_dict_as_field:
                warnings.append(f"未找到 {field} 对应键，已将整个 dict 作为 {field} 的解析对象")
                return _with_optional_display_text({field: parsed}, parsed), warnings
            warnings.append(f"未找到 {field} 对应键，已跳过该 dict 候选")
            return None, warnings
        return {field: parsed}, warnings

    if not isinstance(parsed, dict):
        warnings.append(f"多字段输出解析结果不是 dict，而是 {type(parsed).__name__}")
        return None, warnings

    data_source = parsed.get("data") if isinstance(parsed.get("data"), dict) else None
    mapped: dict[str, Any] = {}
    for field in definition.output_fields:
        aliases = output_aliases.get(field, (field,))
        value = _find_value_by_aliases(parsed, aliases)
        if value is None and data_source is not None:
            value = _find_value_by_aliases(data_source, aliases)
        if value is None and field == "framework_plan_package":
            value = parsed
        if value is None and field == "validation_report" and "validation" in parsed:
            value = parsed.get("validation")
        if value is not None:
            mapped[field] = _unwrap_stage_alias_value(value, field, output_aliases)
    if mapped:
        mapped = _with_optional_display_text(mapped, parsed, data_source)
        missing_fields = [field for field in definition.output_fields if field not in mapped]
        if missing_fields:
            warnings.append(f"缺少输出字段 {missing_fields}，已使用阶段默认占位补齐")
        return mapped, warnings
    warnings.append(f"未能从 dict 中识别阶段 {definition.stage} 的输出字段 {definition.output_fields}")
    return None, warnings


def _parse_candidate_value(candidate: Any) -> Any:
    parsed = parse_workflow_output(candidate)
    if isinstance(parsed, (dict, list)):
        return parsed
    candidate = parsed
    text = str(candidate or "").strip()
    if not text:
        return None
    cleaned = strip_code_fence(text)
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    try:
        return parse_json(text)
    except Exception:
        return cleaned


def _stage04_strip_json_fence(text: str) -> str:
    """去掉 Coze/LLM 常见的 ```json ... ``` 包裹。"""
    source = str(text or "").strip()
    if not source:
        return ""

    source = re.sub(r"^\s*```(?:json|JSON)?\s*", "", source)
    source = re.sub(r"\s*```\s*$", "", source)
    return source.strip()


def _stage04_repair_unquoted_json_string_values(text: str) -> str:
    """
    修复 Stage04 Coze/LLM 偶发的 JSON 漏引号问题。

    典型坏输出：
    "conflict_upgrade": 主角找到了新的第三幕路径。",
    "plot_content": 伊芙琳和韦蒙德携手...
    "display_text": 本规划为20集短剧...

    只修复已知应为字符串的字段，避免误伤数组、对象、数字、布尔值。
    """
    source = str(text or "")
    if not source.strip():
        return source

    string_fields = (
        "narrative_function",
        "plot_content",
        "character_change",
        "conflict_upgrade",
        "hook_or_reversal",
        "display_text",
        "act_one_logic",
        "act_two_logic",
        "act_three_logic",
        "opening_hook",
        "first_three_episodes",
        "midpoint",
        "dark_night_and_turn",
        "ending_closure",
    )

    repaired = source
    for field in string_fields:
        pattern = re.compile(
            rf'("{re.escape(field)}"\s*:)'
            rf'(?!\s*(?:"|{{|\[|\-?\d|true\b|false\b|null\b))'
            rf'\s*([^,\n}}][^\n}}]*?)'
            rf'(?=\s*,\s*\n|\s*\n\s*}})',
            re.M,
        )

        def replace_unquoted(match: re.Match[str]) -> str:
            prefix = match.group(1)
            raw_value = match.group(2).strip()

            # 常见坏形态：开头漏了引号，但结尾还残留一个引号
            if raw_value.endswith('"') and not raw_value.startswith('"'):
                raw_value = raw_value[:-1].rstrip()

            return prefix + " " + json.dumps(raw_value, ensure_ascii=False)

        repaired = pattern.sub(replace_unquoted, repaired)

    return repaired


def _stage04_try_parse_json_text(value: Any) -> Any:
    """
    Stage04 专用 JSON 字符串解析。

    注意：这里不能优先调用 parse_workflow_output / _parse_candidate_value。
    原因是 Stage04 的 Coze 返回经常是：
    data: "{\"beat\":\"{...beat_checkpoint_timeline...}\"}"

    如果先走通用解析器，坏 JSON 可能会被截断成单个 beat，甚至变成 None。
    """
    if not isinstance(value, str):
        return value

    text = _stage04_strip_json_fence(value)
    if not text:
        return value

    candidates: list[str] = [text]

    # 有些 Coze 字符串前后会夹杂少量说明，尝试截取最大 JSON 对象/数组。
    first_obj = text.find("{")
    last_obj = text.rfind("}")
    first_arr = text.find("[")
    last_arr = text.rfind("]")

    if first_obj != -1 and last_obj > first_obj:
        candidates.append(text[first_obj:last_obj + 1])
    if first_arr != -1 and last_arr > first_arr:
        candidates.append(text[first_arr:last_arr + 1])

    def acceptable(parsed: Any) -> bool:
        if isinstance(parsed, list):
            return True
        if isinstance(parsed, dict):
            # parse_json 有时会从坏 JSON 里只抠出第一条 beat。
            # 这种单 beat 不能被当作 Stage04 成功解析。
            if _stage04_is_beat_object(parsed) and "beat_checkpoint_timeline" not in parsed:
                return False
            return True
        return False

    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)

        # 1. 严格 JSON
        try:
            parsed = json.loads(candidate)
            if acceptable(parsed):
                return parsed
        except Exception:
            pass

        # 2. Stage04 专用修复：先修复漏引号，再严格解析
        repaired = _stage04_repair_unquoted_json_string_values(candidate)
        if repaired != candidate:
            try:
                parsed = json.loads(repaired)
                if acceptable(parsed):
                    return parsed
            except Exception:
                pass

            try:
                parsed = parse_json(repaired)
                if acceptable(parsed):
                    return parsed
            except Exception:
                pass

        # 3. 最后才允许项目通用 parse_json，而且拒绝单 beat 截断结果
        try:
            parsed = parse_json(candidate)
            if acceptable(parsed):
                return parsed
        except Exception:
            pass

    return value


def _stage04_deep_parse_json_like(value: Any, *, depth: int = 0) -> Any:
    """
    Stage04 专用递归解析。

    这里故意不先调用 _parse_candidate_value()。
    _parse_candidate_value() 会进入通用 parse_workflow_output，
    对 Stage04 的双层 JSON 字符串可能产生截断：完整 timeline 会变成单个 beat 或 None。
    """
    if depth > 20:
        return value

    if isinstance(value, str):
        parsed = _stage04_try_parse_json_text(value)

        # 没解析动就原样返回。
        if parsed is value or parsed == value:
            return value

        return _stage04_deep_parse_json_like(parsed, depth=depth + 1)

    if isinstance(value, dict):
        return {
            str(key): _stage04_deep_parse_json_like(child, depth=depth + 1)
            for key, child in value.items()
        }

    if isinstance(value, list):
        return [
            _stage04_deep_parse_json_like(item, depth=depth + 1)
            for item in value
        ]

    return value


def _stage04_is_beat_object(value: Any) -> bool:
    """判断是否是单条 beat，而不是 timeline。"""
    if not isinstance(value, dict):
        return False
    return (
        "beat_no" in value
        and "beat_name" in value
        and "episode_range" in value
        and "plot_content" in value
    )


def _stage04_is_timeline_list(value: Any) -> bool:
    """判断是否像十五节拍数组。这里只判断形态，不替代最终严格校验。"""
    if not isinstance(value, list):
        return False
    if not value:
        return False
    return all(isinstance(item, dict) for item in value) and any(
        _stage04_is_beat_object(item) for item in value
    )


def _stage04_extract_payload_from_nested_coze(value: Any, *, depth: int = 0) -> dict[str, Any] | None:
    """
    从任意 Coze 嵌套返回中提取 Stage04 标准结构。

    只接受：
    {
      "beat_checkpoint_timeline": list,
      "checkpoint_explanation": dict/string/可空,
      "display_text": string/可空
    }

    或者直接 list 形式的 timeline。

    明确不接受：
    data.beat = 单个 beat object
    """
    if depth > 24:
        return None

    parsed = _stage04_deep_parse_json_like(value, depth=depth)

    # 情况：Coze/模型直接返回了 15 条数组。
    if _stage04_is_timeline_list(parsed):
        return {
            "beat_checkpoint_timeline": parsed,
            "checkpoint_explanation": {},
            "display_text": "",
        }

    if isinstance(parsed, dict):
        # 情况：标准结构在当前层。
        timeline = parsed.get("beat_checkpoint_timeline")
        if timeline is None:
            # 兼容少量命名变体，但不把单个 beat 当 timeline。
            for alias in (
                "beatCheckpointTimeline",
                "checkpoint_timeline",
                "checkpointTimeline",
                "beat_timeline",
                "beatTimeline",
                "timeline",
                "beats",
                "checkpoints",
                "beat_checkpoints",
                "beatCheckpoints",
                "beat_checkpoint",
                "beatCheckpoint",
            ):
                if alias in parsed:
                    timeline = parsed.get(alias)
                    break

        if _stage04_is_timeline_list(timeline):
            explanation = (
                parsed.get("checkpoint_explanation")
                or parsed.get("checkpointExplanation")
                or parsed.get("explanation")
                or parsed.get("beat_explanation")
                or parsed.get("beatExplanation")
                or parsed.get("checkpoint_explain")
                or parsed.get("checkpointExplain")
                or {}
            )
            display_text = parsed.get("display_text") or parsed.get("displayText") or ""

            return {
                "beat_checkpoint_timeline": timeline,
                "checkpoint_explanation": explanation,
                "display_text": str(display_text or "").strip(),
            }

        # 重要：如果当前层是单个 beat 对象，不允许伪装成功。
        if _stage04_is_beat_object(parsed):
            return None

        # 优先拆 Coze 常见包装字段。
        for key in (
            "data",
            "output",
            "result",
            "answer",
            "content",
            "text",
            "message",
            "response",
            "raw",
            "beat",
        ):
            if key in parsed:
                found = _stage04_extract_payload_from_nested_coze(parsed.get(key), depth=depth + 1)
                if found:
                    return found

        # 兼容 Coze outputs / variables / newVariables / responseData 等容器。
        for container_key in (
            "outputs",
            "variables",
            "newVariables",
            "responseData",
            "updateVarResult",
        ):
            container = parsed.get(container_key)
            found = _stage04_extract_payload_from_nested_coze(container, depth=depth + 1)
            if found:
                return found

        # 最后兜底遍历所有字段。
        for child in parsed.values():
            found = _stage04_extract_payload_from_nested_coze(child, depth=depth + 1)
            if found:
                return found

    if isinstance(parsed, list):
        for item in parsed:
            found = _stage04_extract_payload_from_nested_coze(item, depth=depth + 1)
            if found:
                return found

    return None


def safe_parse_stage_output(
    stage_response: Any,
    required_keys: tuple[str, ...] | list[str],
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    parsed = _parse_candidate_value(stage_response)

    if isinstance(parsed, list):
        warnings.append("阶段输出为 list，已取第一个元素作为解析对象")
        first_item = _first_non_empty_list_item(parsed)
        parsed = _parse_candidate_value(first_item) if first_item is not None else {}

    if isinstance(parsed, str):
        text = parsed.strip()
        if text:
            try:
                parsed = json.loads(text)
            except Exception:
                try:
                    parsed = parse_json(text)
                except Exception:
                    warnings.append("阶段输出字符串无法解析为 JSON，已回退为空对象")
                    parsed = {}
        else:
            parsed = {}

    if isinstance(parsed, list):
        warnings.append("阶段输出二次解析后仍为 list，已再次取第一个元素作为解析对象")
        first_item = _first_non_empty_list_item(parsed)
        parsed = _parse_candidate_value(first_item) if first_item is not None else {}

    if not isinstance(parsed, dict):
        warnings.append(f"阶段输出不是 dict，而是 {type(parsed).__name__}，已回退为空对象")
        parsed = {}

    safe_output = dict(parsed)
    for key in tuple(required_keys):
        if key in safe_output and safe_output.get(key) not in (None, "", [], {}):
            continue
        safe_output[key] = _stage_output_placeholder(key)
        if key != "display_text":
            warnings.append(f"缺少关键字段 {key}，已填充占位结构")
    return safe_output, warnings


def _log_field_type_mismatch(stage: str, field: str, expected: str, value: Any) -> None:
    logger.warning(
        "字段类型不符 timestamp=%s stage=%s field=%s expected_type=%s actual_type=%s value_preview=%s",
        _history_iso_timestamp(),
        stage,
        field,
        expected,
        type(value).__name__ if value is not None else "none",
        _preview_return_object(value, limit=300),
    )


def _normalize_stage_output(
    stage: str,
    data: dict[str, Any],
    *,
    parse_warnings: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    warnings = parse_warnings if parse_warnings is not None else []
    normalized = dict(data if isinstance(data, dict) else {})
    if stage == "01":
        if not isinstance(normalized.get("source_brief"), dict):
            warnings.append("source_brief 不是 dict，已回退为对象占位")
            _log_field_type_mismatch(stage, "source_brief", "dict", normalized.get("source_brief"))
        normalized["source_brief"] = _normalize_object_like(normalized.get("source_brief"), key_name="content")
        normalized["source_brief"] = _ensure_source_brief_core_fields(normalized["source_brief"])
        return normalized
    if stage == "02":
        if not isinstance(normalized.get("worldview_plan"), dict):
            warnings.append("worldview_plan 不是 dict，已回退为对象占位")
            _log_field_type_mismatch(stage, "worldview_plan", "dict", normalized.get("worldview_plan"))
        normalized["worldview_plan"] = _normalize_object_like(normalized.get("worldview_plan"), key_name="content")
        normalized["worldview_plan"] = _ensure_worldview_core_fields(normalized["worldview_plan"])
        return normalized
    if stage == "03":
        if not isinstance(normalized.get("character_plan"), dict):
            warnings.append("character_plan 不是 dict，已回退为对象占位")
            _log_field_type_mismatch(stage, "character_plan", "dict", normalized.get("character_plan"))
        normalized["character_plan"] = _normalize_object_like(normalized.get("character_plan"), key_name="content")
        normalized["character_plan"] = _ensure_character_core_fields(normalized["character_plan"])
        return normalized
    if stage == "04":
        checkpoint_missing = normalized.get("checkpoint_explanation") in (None, "", [], {})
        if not isinstance(normalized.get("beat_checkpoint_timeline"), list):
            warnings.append("beat_checkpoint_timeline 不是 list，未生成占位节拍，阶段将按解析失败处理")
            _log_field_type_mismatch(stage, "beat_checkpoint_timeline", "list", normalized.get("beat_checkpoint_timeline"))
            normalized["beat_checkpoint_timeline"] = []
            normalized["checkpoint_explanation"] = _normalize_checkpoint_explanation(
                normalized.get("checkpoint_explanation"),
                [],
            )
            return normalized
        if checkpoint_missing:
            warnings.append("checkpoint_explanation 缺失，将从有效节拍内容派生说明；若节拍内容不足则阶段失败")
            logger.warning(
                "框架策划阶段 04 checkpoint_explanation 缺失，将尝试从节拍内容派生说明；raw_output=%s",
                _preview_return_object(data),
            )
        elif not isinstance(normalized.get("checkpoint_explanation"), (dict, str)):
            warnings.append("checkpoint_explanation 不是 dict/str，已回退为说明占位")
            _log_field_type_mismatch(stage, "checkpoint_explanation", "dict/str", normalized.get("checkpoint_explanation"))
        normalized["beat_checkpoint_timeline"] = _normalize_beat_timeline(
            normalized.get("beat_checkpoint_timeline"),
            total_episodes=_total_episodes_from_payload(payload),
        )
        normalized["checkpoint_explanation"] = _normalize_checkpoint_explanation(
            normalized.get("checkpoint_explanation"),
            normalized["beat_checkpoint_timeline"],
        )
        return normalized
    if stage == "05":
        if not isinstance(normalized.get("character_storylines"), list):
            warnings.append("character_storylines 不是 list，已回退为空数组的旧逻辑已替换为自动归一化为数组")
            _log_field_type_mismatch(stage, "character_storylines", "list", normalized.get("character_storylines"))
            logger.warning(
                "框架策划阶段 05 character_storylines 类型不一致，已自动归一化为 list；actual_type=%s raw_object=%s",
                type(normalized.get("character_storylines")).__name__,
                _preview_return_object(normalized.get("character_storylines")),
            )
        normalized["character_storylines"] = _normalize_character_storylines(
            normalized.get("character_storylines")
        )
        return normalized
    if stage == "06":
        adaptation_guide = _first_present_value(
            normalized,
            (
                "adaptation_guide",
                "adaptationGuide",
                "overallAdaptationGuide",
                "overall_adaptation_guide",
                "guide",
            ),
        )
        if not isinstance(adaptation_guide, (dict, list, str)):
            warnings.append("adaptation_guide 类型异常，已回退为空对象")
            _log_field_type_mismatch(stage, "adaptation_guide", "dict/list/str", adaptation_guide)
        normalized["adaptation_guide"] = _normalize_adaptation_guide(
            adaptation_guide
        )
        return normalized
    if stage == "07":
        raw_validation_missing = normalized.get("validation_report") in (None, "", [], {})

        if not isinstance(normalized.get("framework_plan_package"), dict):
            warnings.append("framework_plan_package 不是 dict，已尝试清洗为对象")
            _log_field_type_mismatch(stage, "framework_plan_package", "dict", normalized.get("framework_plan_package"))

        if (not raw_validation_missing) and not isinstance(normalized.get("validation_report"), (dict, list, str)):
            warnings.append("validation_report 类型异常，已回退为对象占位")
            _log_field_type_mismatch(stage, "validation_report", "dict/list/str", normalized.get("validation_report"))
            normalized["validation_report"] = _stage_output_placeholder("validation_report")

        normalized["framework_plan_package"] = _sanitize_framework_plan_package(
            normalized.get("framework_plan_package")
        )

        validation_report = _normalize_validation_report(normalized.get("validation_report"))
        summary_text = str(validation_report.get("summary") or "").strip() if isinstance(validation_report, dict) else ""
        warning_text = json.dumps(validation_report, ensure_ascii=False, default=str) if isinstance(validation_report, dict) else ""

        is_placeholder_validation = (
            raw_validation_missing
            or summary_text in {"", "未明确，需后续确认……"}
            or "缺少关键字段 validation_report" in warning_text
            or "缺少输出字段 ['validation_report']" in warning_text
            or "缺少输出字段 [\\u0027validation_report\\u0027]" in warning_text
        )

        used_local_validation_report = False
        if is_placeholder_validation:
            validation_report = _build_validation_report_from_package(
                normalized["framework_plan_package"],
                parse_warnings=[],
            )
            used_local_validation_report = True

        normalized["validation_report"] = validation_report

        # 如果 stage07 已经基于清洗后的 framework_plan_package 生成本地校验报告，
        # 不再把“缺少 validation_report”的旧解析警告附回最终报告。
        if warnings and not used_local_validation_report:
            normalized["validation_report"] = _attach_parse_warnings_to_validation_report(
                normalized["validation_report"],
                warnings,
            )

        return normalized
    return normalized


def _find_display_text_recursive(value: Any, *, depth: int = 0) -> str:
    """递归查找 display_text / displayText，用于兼容 Stage06 Coze 嵌套输出。"""
    if depth > 12:
        return ""

    if value in (None, "", [], {}):
        return ""

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""

        if text.startswith("{") or text.startswith("["):
            try:
                parsed = json.loads(text)
                found = _find_display_text_recursive(parsed, depth=depth + 1)
                if found:
                    return found
            except Exception:
                pass

        return ""

    if isinstance(value, dict):
        for key in ("display_text", "displayText"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()

        for key in (
            "data",
            "output",
            "result",
            "adaptation",
            "content",
            "text",
            "message",
            "response",
        ):
            if key in value:
                found = _find_display_text_recursive(value.get(key), depth=depth + 1)
                if found:
                    return found

        for item in value.values():
            found = _find_display_text_recursive(item, depth=depth + 1)
            if found:
                return found

    if isinstance(value, list):
        for item in value:
            found = _find_display_text_recursive(item, depth=depth + 1)
            if found:
                return found

    return ""


def _extract_display_text(
    response_json: Any,
    data: dict[str, Any],
    *,
    stage: str = "",
    payload_keys: list[str] | None = None,
) -> str:
    safe_data = data if isinstance(data, dict) else {}
    stage_payload_keys = sorted(set(payload_keys or []))

    # 1. 原有逻辑：先查最终业务 data 的顶层 display_text。
    for key in ("display_text", "displayText"):
        value = safe_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # 2. 只对 Stage06 开启递归查找。
    # 目的：兼容 Coze 返回 data.adaptation.display_text 的情况。
    # 不影响其他阶段。
    if str(stage).zfill(2) == "06":
        found = _find_display_text_recursive(safe_data)
        if found:
            return found

        found = _find_display_text_recursive(response_json)
        if found:
            return found

    # 3. 保留原来的 normalize 逻辑，兼容旧 FastGPT / OpenAI 风格。
    try:
        root_response = normalize_stage_response(
            response_json,
            stage=stage,
            payload_keys=stage_payload_keys,
        )
    except Exception as exc:
        if stage:
            _log_stage_output_parse_exception(
                stage=stage,
                payload_keys=stage_payload_keys,
                exc=exc,
                raw_return_object=response_json,
            )
        root_response = {}

    # 4. Stage06 的 normalize 之后再兜一次递归。
    if str(stage).zfill(2) == "06":
        found = _find_display_text_recursive(root_response)
        if found:
            return found

    response_data = root_response.get("responseData")
    if not isinstance(response_data, dict):
        response_data = {}

    for value in (
        root_response.get("answerText"),
        response_data.get("answerText"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()

    return _stage_text_placeholder()


def _empty_stage_output(stage: str) -> dict[str, Any]:
    if stage == "01":
        return {"source_brief": {}}
    if stage == "02":
        return {"worldview_plan": {}}
    if stage == "03":
        return {"character_plan": {}}
    if stage == "04":
        return {
            "beat_checkpoint_timeline": [],
            "checkpoint_explanation": {},
        }
    if stage == "05":
        return {"character_storylines": []}
    if stage == "06":
        return {"adaptation_guide": {}}
    if stage == "07":
        return {
            "framework_plan_package": {},
            "validation_report": {},
        }
    return {}


def _stage_output_placeholder(key: str) -> Any:
    if key == "display_text":
        return ""
    if key == "beat_checkpoint_timeline":
        return []
    if key == "checkpoint_explanation":
        return {
            "overview": "未明确，需后续确认……",
            "beat_notes": [],
        }
    if key == "character_storylines":
        return []
    if key == "adaptation_guide":
        return {}
    if key == "framework_plan_package":
        return {}
    if key == "validation_report":
        return {
            "summary": "未明确，需后续确认……",
            "parse_warning": [],
        }
    return {}


def _stage_text_placeholder() -> str:
    return "未明确，需后续确认……"


def normalize_stage_response(
    root_response: Any,
    *,
    stage: str = "",
    payload_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize 01~07 FastGPT stage output into a dict so downstream .get() calls stay safe."""
    try:
        parsed = _parse_candidate_value(root_response)
    except Exception as exc:
        if stage:
            _log_stage_output_parse_exception(
                stage=stage,
                payload_keys=sorted(set(payload_keys or [])),
                exc=exc,
                raw_return_object=root_response,
            )
        return {}

    while isinstance(parsed, list):
        first_item = _first_non_empty_list_item(parsed)
        if first_item is None:
            return {}
        try:
            parsed = _parse_candidate_value(first_item)
        except Exception as exc:
            if stage:
                _log_stage_output_parse_exception(
                    stage=stage,
                    payload_keys=sorted(set(payload_keys or [])),
                    exc=exc,
                    raw_return_object=first_item,
                )
            return {}

    if isinstance(parsed, str):
        text = parsed.strip()
        if not text:
            return {}
        try:
            reparsed = json.loads(text)
        except Exception as exc:
            if stage:
                _log_stage_output_parse_exception(
                    stage=stage,
                    payload_keys=sorted(set(payload_keys or [])),
                    exc=exc,
                    raw_return_object=text,
                )
            try:
                reparsed = parse_json(text)
            except Exception:
                return {}
        return normalize_stage_response(
            reparsed,
            stage=stage,
            payload_keys=payload_keys,
        )

    if isinstance(parsed, dict):
        data_value = parsed.get("data")
        if isinstance(data_value, str) and data_value.strip():
            nested = _parse_candidate_value(data_value)
            if isinstance(nested, dict):
                parsed = dict(parsed)
                parsed["data"] = nested
        return parsed
    return {}


def _safe_root_mapping(value: Any) -> dict[str, Any]:
    return normalize_stage_response(value)


def extract_business_field(value: Any, field_name: str) -> Any:
    if value in (None, ""):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        parsed = _parse_candidate_value(text)
        if parsed is text or parsed == text:
            return value
        extracted = extract_business_field(parsed, field_name)
        return extracted if extracted is not parsed else value
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return value

    direct = _find_value_by_aliases(value, (field_name,))
    if direct is not None:
        return direct
    data = value.get("data")
    if isinstance(data, dict):
        nested = _find_value_by_aliases(data, (field_name,))
        if nested is not None:
            return nested

    for container_name in ("newVariables", "variables"):
        container = value.get(container_name)
        if isinstance(container, dict):
            nested = _find_value_by_aliases(container, (field_name,))
            if nested is not None:
                return extract_business_field(nested, field_name)
        if isinstance(container, list):
            for item in container:
                if not isinstance(item, dict):
                    continue
                variable = item.get("variable")
                if isinstance(variable, list):
                    variable_key = str(variable[-1] or "").strip()
                else:
                    variable_key = str(variable or item.get("key") or item.get("name") or "").strip()
                if variable_key == field_name:
                    return extract_business_field(item.get("value"), field_name)

    response_data = value.get("responseData")
    for _, node in reversed(_response_data_items(response_data)):
        for _, text_value in _iter_text_fields(node):
            parsed = _parse_candidate_value(text_value)
            if isinstance(parsed, dict):
                nested = _find_value_by_aliases(parsed, (field_name,))
                if nested is not None:
                    return nested
                data = parsed.get("data")
                if isinstance(data, dict):
                    nested = _find_value_by_aliases(data, (field_name,))
                    if nested is not None:
                        return nested

    for text_key in ("answerText", "responseText", "text", "content"):
        text_value = value.get(text_key)
        if text_value in (None, "", [], {}):
            continue
        parsed = _parse_candidate_value(text_value)
        if isinstance(parsed, dict):
            nested = _find_value_by_aliases(parsed, (field_name,))
            if nested is not None:
                return nested
    return value


def _sanitize_stage_input_value(stage: str, field_name: str, value: Any) -> Any:
    if field_name == "basic_config":
        return _compact_stage_05_basic_config(value)
    if field_name in FRAMEWORK_BUSINESS_FIELDS:
        cleaned = extract_business_field(value, field_name)
        if _pollution_keys_in_value(cleaned):
            logger.warning(
                "framework planner sanitized_input_rejected stage=%s field=%s reason=raw_response_keys_still_present original_type=%s preview=%s",
                stage,
                field_name,
                type(value).__name__,
                _preview_return_object(value, limit=300),
            )
            return [] if field_name in FRAMEWORK_BUSINESS_LIST_FIELDS else {}
        if field_name in FRAMEWORK_BUSINESS_LIST_FIELDS:
            return cleaned if isinstance(cleaned, list) else []
        if field_name in {"source_brief", "worldview_plan", "character_plan", "checkpoint_explanation", "adaptation_guide", "framework_plan_package", "validation_report"}:
            return cleaned if isinstance(cleaned, dict) else {}
        return cleaned
    return extract_business_field(value, field_name)


def _sanitize_stage_05_input_value(field_name: str, value: Any) -> Any:
    return _sanitize_stage_input_value("05", field_name, value)


def _compact_stage_05_basic_config(value: Any) -> dict[str, Any]:
    parsed = extract_business_field(value, "basic_config")
    if isinstance(parsed, str):
        reparsed = _parse_candidate_value(parsed)
        parsed = reparsed if isinstance(reparsed, dict) else {}
    if not isinstance(parsed, dict):
        parsed = {}
    allowed = (
        "project_title",
        "source_title",
        "mode",
        "target_format",
        "season_count",
        "episodes_per_season",
        "minutes_per_episode",
        "adaptation_direction",
        "user_constraints",
        "user_requirements",
    )
    compact: dict[str, Any] = {}
    for key in allowed:
        value_item = parsed.get(key)
        if value_item in (None, "", [], {}):
            continue
        if key in {"user_constraints", "user_requirements", "adaptation_direction"}:
            compact[key] = _truncate_text(str(value_item), limit=1200)
        else:
            compact[key] = value_item
    if "source_title" not in compact and compact.get("project_title"):
        compact["source_title"] = compact["project_title"]
    if "project_title" not in compact and compact.get("source_title"):
        compact["project_title"] = compact["source_title"]
    return compact


def _first_non_empty_list_item(items: list[Any]) -> Any:
    for item in items:
        if item not in (None, "", [], {}):
            return item
    return None


def _dict_contains_output_aliases(
    definition: FrameworkPlannerStageDefinition,
    parsed: dict[str, Any],
    output_aliases: dict[str, tuple[str, ...]],
) -> bool:
    nested = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
    for field in definition.output_fields:
        aliases = output_aliases.get(field, (field,))
        if any(alias in parsed for alias in aliases):
            return True
        if isinstance(nested, dict) and any(alias in nested for alias in aliases):
            return True
    return False


def _with_optional_display_text(
    mapped: dict[str, Any],
    *sources: Any,
) -> dict[str, Any]:
    result = dict(mapped)
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("display_text", "displayText"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                result["display_text"] = value.strip()
                return result
    return result


def _attach_parse_warnings_to_validation_report(
    report: dict[str, Any],
    parse_warnings: list[str],
) -> dict[str, Any]:
    normalized = dict(report if isinstance(report, dict) else {})

    def is_stale_validation_missing_warning(text: str) -> bool:
        return (
            "validation_report" in text
            and (
                "缺少输出字段" in text
                or "缺少关键字段" in text
                or "已使用阶段默认占位补齐" in text
                or "已填充占位结构" in text
            )
        )

    def clean_warning_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item).strip()
            if not text:
                continue
            if normalized.get("passed") is True and is_stale_validation_missing_warning(text):
                continue
            if text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    if normalized.get("passed") is True:
        existing_warnings = clean_warning_list(normalized.get("warnings"))
        existing_parse_warnings = clean_warning_list(normalized.get("parse_warning"))

        if existing_warnings:
            normalized["warnings"] = existing_warnings
        else:
            normalized.pop("warnings", None)

        if existing_parse_warnings:
            normalized["parse_warning"] = existing_parse_warnings
        else:
            normalized.pop("parse_warning", None)

    if not parse_warnings:
        return normalized

    warning_list = [str(item).strip() for item in parse_warnings if str(item).strip()]
    if normalized.get("passed") is True:
        warning_list = [
            item for item in warning_list
            if not is_stale_validation_missing_warning(item)
        ]

    if not warning_list:
        return normalized

    existing_warnings = clean_warning_list(normalized.get("warnings"))
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*existing_warnings, *warning_list]:
        if item in seen:
            continue
        seen.add(item)
        merged.append(item)

    normalized["warnings"] = merged
    normalized["parse_warning"] = warning_list
    return normalized

def _log_stage_output_parse_exception(
    *,
    stage: str,
    payload_keys: list[str],
    exc: Exception,
    raw_return_object: Any,
) -> None:
    logger.exception(
        "框架策划阶段 %s 输出解析异常 timestamp=%s payload_keys=%s exception_type=%s exception_message=%s raw_return_object=%s",
        stage,
        _history_iso_timestamp(),
        payload_keys,
        type(exc).__name__,
        str(exc),
        safe_truncated_preview(raw_return_object, limit=1200),
    )


def _log_stage_parse_warnings(stage: str, parse_warnings: list[str]) -> None:
    warning_list = [str(item).strip() for item in parse_warnings if str(item).strip()]
    if not warning_list:
        return
    logger.warning(
        "框架策划阶段 %s 输出解析出现降级处理：%s",
        stage,
        " | ".join(warning_list),
    )


def _stage_runtime_diagnostics(
    definition: FrameworkPlannerStageDefinition,
    payload: dict[str, Any],
) -> dict[str, Any]:
    api_key_source, api_key = _coze_api_token_with_name()
    url_source, configured_url = _coze_api_base_with_name(api_key_source)
    timeout_seconds = DEFAULT_NS_TIMEOUT_SECONDS
    resolved_url = _normalize_coze_workflow_url(configured_url or DEFAULT_NS_WORKFLOW_URL)
    url_error = ""
    workflow_id_source, workflow_id = _stage_workflow_id_with_name(definition)
    input_pollution = _stage_05_input_pollution(payload) if definition.stage == "05" else {
        "input_pollution_detected": False,
        "polluted_fields": [],
    }
    return {
        "payload_keys": sorted(payload.keys()),
        "source_text_length": _source_text_length_from_payload(payload),
        "mock_enabled": _env_bool("FRAMEWORK_PLANNER_USE_MOCK", default=False),
        "has_api_key": bool(api_key),
        "api_key_source": api_key_source or "",
        "api_key_env_candidates": list(_coze_api_token_env_names()),
        "has_workflow_id": bool(workflow_id),
        "workflow_id_source": workflow_id_source or "",
        "workflow_id_env_candidates": [],
        "workflow_id_config_key": _stage_workflow_id_config_key(definition),
        "base_url_configured": bool(configured_url),
        "url_source": url_source or ("default" if not configured_url else ""),
        "configured_url": str(configured_url or "").strip(),
        "resolved_url": resolved_url,
        "url_normalize_error": url_error,
        "timeout_seconds": max(1, timeout_seconds),
        "workflow_id_missing_but_api_key_mode_enabled": bool(api_key) and not bool(workflow_id),
        **input_pollution,
    }


def _log_stage_entry(
    definition: FrameworkPlannerStageDefinition,
    diagnostics: dict[str, Any],
) -> None:
    logger.info(
        "框架策划阶段入口：stage=%s payload_keys=%s source_text_length=%s current_api_key_config=%s mock_enabled=%s has_api_key=%s has_workflow_id=%s workflow_id_config=%s base_url_config=%s endpoint=%s workflow_id_missing_but_api_key_mode_enabled=%s",
        definition.stage,
        diagnostics.get("payload_keys", []),
        diagnostics.get("source_text_length", 0),
        diagnostics.get("api_key_source") or "未命中",
        diagnostics.get("mock_enabled", False),
        diagnostics.get("has_api_key", False),
        diagnostics.get("has_workflow_id", False),
        diagnostics.get("workflow_id_source") or "未命中",
        diagnostics.get("url_source") or "default",
        diagnostics.get("resolved_url") or DEFAULT_NS_WORKFLOW_URL,
        diagnostics.get("workflow_id_missing_but_api_key_mode_enabled", False),
    )


def _stage_05_input_pollution(payload: dict[str, Any]) -> dict[str, Any]:
    polluted_fields: list[str] = []
    for field in (
        "source_brief",
        "basic_config",
        "worldview_plan",
        "character_plan",
        "beat_checkpoint_timeline",
        "previous_character_storylines",
        "current_storyline_decisions",
    ):
        if _pollution_keys_in_value(payload.get(field)):
            polluted_fields.append(field)
    return {
        "input_pollution_detected": bool(polluted_fields),
        "polluted_fields": polluted_fields,
    }


def _log_stage_05_input_diagnostics(
    payload: dict[str, Any],
    request_variables: dict[str, Any],
) -> None:
    logger.info("stage=05 input_payload_keys=%s", sorted(payload.keys()))
    for field in (
        "source_brief",
        "basic_config",
        "worldview_plan",
        "character_plan",
        "beat_checkpoint_timeline",
        "previous_character_storylines",
        "current_storyline_decisions",
    ):
        original_value = payload.get(field)
        sent_value = request_variables.get(field, original_value)
        pollution_keys = _pollution_keys_in_value(original_value)
        summary = _value_diagnostic_summary(sent_value)
        suspected = bool(pollution_keys)
        logger.info(
            "stage=05 input_field_diagnostic field=%s type=%s length=%s dict_keys=%s list_length=%s first_item_type=%s suspected_raw_response=%s contains_keys=%s preview=%s",
            field,
            summary["type"],
            summary["length"],
            summary["dict_keys"],
            summary["list_length"],
            summary["first_item_type"],
            suspected,
            ",".join(pollution_keys),
            summary["preview"],
        )
        if suspected:
            logger.warning(
                "stage=05 输入疑似污染：field=%s 包含 FastGPT raw response，请检查前端 state 保存逻辑或后端业务字段提取逻辑",
                field,
            )
        limit = STAGE_05_INPUT_LENGTH_LIMITS.get(field)
        if limit is not None and int(summary["length"] or 0) > limit:
            logger.warning(
                "stage=05 input_field_length_warning field=%s length=%s threshold=%s possible_raw_response=True message=可能传入了完整 raw response，而不是业务字段。",
                field,
                summary["length"],
                limit,
            )


def _value_diagnostic_summary(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": type(value).__name__,
        "length": 0,
        "dict_keys": [],
        "list_length": 0,
        "first_item_type": "",
        "preview": _preview_return_object(value, limit=300),
    }
    if isinstance(value, str):
        result["length"] = len(value)
    elif isinstance(value, dict):
        result["length"] = len(json.dumps(value, ensure_ascii=False, default=str))
        result["dict_keys"] = sorted(str(key) for key in value.keys())
    elif isinstance(value, list):
        result["length"] = len(json.dumps(value, ensure_ascii=False, default=str))
        result["list_length"] = len(value)
        if value:
            result["first_item_type"] = type(value[0]).__name__
    else:
        result["length"] = len(str(value or ""))
    return result


def _pollution_keys_in_value(value: Any) -> list[str]:
    found: set[str] = set()

    def visit(item: Any, depth: int = 0) -> None:
        if depth > 4 or len(found) == len(FASTGPT_RAW_RESPONSE_KEYS):
            return
        if isinstance(item, str):
            for key in FASTGPT_RAW_RESPONSE_KEYS:
                if key in item:
                    found.add(key)
            if len(item) > 2 and ("{" in item or "[" in item):
                parsed = _parse_candidate_value(item)
                if parsed is not item:
                    visit(parsed, depth + 1)
            return
        if isinstance(item, dict):
            for key, nested in item.items():
                key_text = str(key)
                if key_text in FASTGPT_RAW_RESPONSE_KEYS:
                    found.add(key_text)
                visit(nested, depth + 1)
            return
        if isinstance(item, list):
            for nested in item[:8]:
                visit(nested, depth + 1)

    visit(value)
    return [key for key in FASTGPT_RAW_RESPONSE_KEYS if key in found]


def _log_stage_not_entering_fastgpt(
    definition: FrameworkPlannerStageDefinition,
    diagnostics: dict[str, Any],
    *,
    reason: str,
) -> None:
    logger.warning(
        "stage %s 未进入 FastGPT 调用，reason=%s payload_keys=%s source_text_length=%s mock_enabled=%s has_api_key=%s has_workflow_id=%s base_url_configured=%s api_key_source=%s workflow_id_source=%s url_source=%s endpoint=%s",
        definition.stage,
        reason,
        diagnostics.get("payload_keys", []),
        diagnostics.get("source_text_length", 0),
        diagnostics.get("mock_enabled", False),
        diagnostics.get("has_api_key", False),
        diagnostics.get("has_workflow_id", False),
        diagnostics.get("base_url_configured", False),
        diagnostics.get("api_key_source") or "未命中",
        diagnostics.get("workflow_id_source") or "未命中",
        diagnostics.get("url_source") or "default",
        diagnostics.get("resolved_url") or DEFAULT_NS_WORKFLOW_URL,
    )


def _log_fastgpt_pre_request(
    *,
    definition: FrameworkPlannerStageDefinition,
    endpoint: FrameworkPlannerEndpoint,
    headers: dict[str, str],
    body: dict[str, Any],
    attempt_index: int,
    attempts: int,
) -> None:
    host, port = _endpoint_host_port(endpoint.url)
    logger.info(
        "即将请求 FastGPT：stage=%s attempt=%s/%s endpoint=%s host=%s port=%s timeout_seconds=%s url_config_name=%s current_env_FASTGPT_CHAT_COMPLETIONS_URL=%s has_authorization=%s workflow_id_missing_but_api_key_mode_enabled=%s payload_keys=%s payload_lengths=%s",
        definition.stage,
        attempt_index,
        attempts,
        endpoint.url,
        host,
        port,
        endpoint.timeout,
        endpoint.url_source or "default",
        "FASTGPT_CHAT_COMPLETIONS_URL",
        bool(str(headers.get("Authorization") or "").strip()),
        not bool(endpoint.workflow_id) and bool(endpoint.api_key),
        sorted(body.keys()),
        _mapping_length_summary(body),
    )


def _log_fastgpt_response(
    *,
    definition: FrameworkPlannerStageDefinition,
    response: requests.Response,
    attempt_index: int,
    elapsed_seconds: float,
) -> None:
    logger.info(
        "FastGPT 请求成功返回：stage=%s attempt=%s status_code=%s content_type=%s elapsed_seconds=%.3f response_preview=%s json_decode_success=%s",
        definition.stage,
        attempt_index,
        getattr(response, "status_code", 0),
        _safe_header_lookup(response, "Content-Type"),
        elapsed_seconds,
        safe_truncated_preview(_safe_response_text(response), limit=500),
        _response_json_decode_success(response),
    )


def _log_fastgpt_request_exception(
    *,
    definition: FrameworkPlannerStageDefinition,
    endpoint: FrameworkPlannerEndpoint,
    attempt_index: int,
    attempts: int,
    elapsed_seconds: float,
    entered_requests_post: bool,
    response: requests.Response | None,
    exc: Exception | None = None,
    reason: str = "",
) -> None:
    message = str(exc) if exc else str(reason or "").strip()
    logger.warning(
        "FastGPT 请求异常：stage=%s attempt=%s/%s url=%s timeout_seconds=%s exception_type=%s exception_message=%s requests_exception_category=%s elapsed_seconds=%.3f entered_requests_post=%s response_received=%s status_code=%s content_type=%s response_preview=%s",
        definition.stage,
        attempt_index,
        attempts,
        endpoint.url,
        endpoint.timeout,
        type(exc).__name__ if exc else "",
        message,
        _classify_request_exception(exc, response=response),
        elapsed_seconds,
        entered_requests_post,
        response is not None,
        getattr(response, "status_code", 0) if response is not None else 0,
        _safe_header_lookup(response, "Content-Type") if response is not None else "",
        safe_truncated_preview(_safe_response_text(response), limit=500) if response is not None else "",
    )


def _log_fastgpt_attempts_exhausted(
    *,
    definition: FrameworkPlannerStageDefinition,
    endpoint: FrameworkPlannerEndpoint,
    attempts: int,
    exc: Exception | None,
    response: requests.Response | None,
    status_code: int,
) -> None:
    logger.error(
        "FastGPT 请求三次均失败，返回 %s：stage=%s attempts=%s url=%s last_exception_type=%s last_exception_message=%s response_received=%s response_status_code=%s response_preview=%s",
        status_code,
        definition.stage,
        attempts,
        endpoint.url,
        type(exc).__name__ if exc else "",
        str(exc) if exc else "",
        response is not None,
        getattr(response, "status_code", 0) if response is not None else 0,
        safe_truncated_preview(_safe_response_text(response), limit=500) if response is not None else "",
    )


def _build_fastgpt_stage_error(
    *,
    definition: FrameworkPlannerStageDefinition,
    diagnostics: dict[str, Any],
    reason: str,
    status_code: int,
    entered_fastgpt_request: bool,
    exc: Exception | None = None,
    endpoint: FrameworkPlannerEndpoint | None = None,
    response: requests.Response | None = None,
    attempts: int = 0,
    extra_detail: dict[str, Any] | None = None,
) -> FrameworkPlannerStageError:
    is_connect_timeout = isinstance(exc, requests.ConnectTimeout)
    message = (
        f"阶段 {definition.stage} 无法连接 FastGPT 服务"
        if is_connect_timeout
        else f"阶段 {definition.stage} 请求 FastGPT 失败"
    )
    return FrameworkPlannerStageError(
        message,
        stage=definition.stage,
        status_code=status_code,
        detail=_fastgpt_failure_detail(
            diagnostics=diagnostics,
            reason=reason,
            entered_fastgpt_request=entered_fastgpt_request,
            exc=exc,
            endpoint=endpoint,
            response=response,
            attempts=attempts,
            extra_detail=extra_detail,
        ),
    )


def _fastgpt_failure_detail(
    *,
    diagnostics: dict[str, Any],
    reason: str,
    entered_fastgpt_request: bool,
    exc: Exception | None = None,
    endpoint: FrameworkPlannerEndpoint | None = None,
    response: requests.Response | None = None,
    attempts: int = 0,
    extra_detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    endpoint_url = str((endpoint.url if endpoint else diagnostics.get("resolved_url")) or "")
    host, port = _endpoint_host_port(endpoint_url)
    is_connect_timeout = isinstance(exc, requests.ConnectTimeout)
    detail: dict[str, Any] = {
        "reason": str(reason or "").strip() or "阶段未成功请求 FastGPT",
        "has_api_key": bool((endpoint.api_key if endpoint else None) or diagnostics.get("has_api_key")),
        "has_workflow_id": bool((endpoint.workflow_id if endpoint else None) or diagnostics.get("has_workflow_id")),
        "base_url_configured": bool(diagnostics.get("base_url_configured")),
        "entered_fastgpt_request": bool(entered_fastgpt_request),
        "exception_type": type(exc).__name__ if exc else "",
        "exception_message": str(exc) if exc else "",
        "last_exception_type": type(exc).__name__ if exc else "",
        "last_exception_message": str(exc) if exc else "",
        "api_key_source": diagnostics.get("api_key_source") or "",
        "workflow_id_source": (endpoint.workflow_id_source if endpoint else "") or diagnostics.get("workflow_id_source") or "",
        "url_source": (endpoint.url_source if endpoint else "") or diagnostics.get("url_source") or "",
        "url": endpoint_url,
        "endpoint_url": endpoint_url,
        "endpoint": endpoint_url,
        "host": host,
        "port": port,
        "timeout_seconds": (endpoint.timeout if endpoint else diagnostics.get("timeout_seconds")) or 0,
        "attempts": attempts or int(getattr(settings, "fastgpt_http_retries", 2) or 0) + 1,
        "payload_keys": diagnostics.get("payload_keys", []),
        "source_text_length": diagnostics.get("source_text_length", 0),
        "workflow_id_missing_but_api_key_mode_enabled": diagnostics.get("workflow_id_missing_but_api_key_mode_enabled", False),
    }
    if is_connect_timeout:
        detail["suggestion"] = "请检查 FASTGPT_CHAT_COMPLETIONS_URL、FastGPT 服务是否启动、3000 端口是否开放、当前机器是否能访问该 IP。"
    if response is not None:
        detail.update(
            {
                "status_code": getattr(response, "status_code", 0),
                "content_type": _safe_header_lookup(response, "Content-Type"),
                "response_preview": _truncate_text(_safe_response_text(response), limit=500),
                "json_decode_success": _response_json_decode_success(response),
            }
        )
    if isinstance(extra_detail, dict):
        for key, value in extra_detail.items():
            if key in {"Authorization", "authorization", "token", "api_key", "apiKey"}:
                continue
            detail.setdefault(key, value)
    return detail


def _normalize_object_like(value: Any, *, key_name: str = "content") -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {key_name: value}
    text = str(value or "").strip()
    return {key_name: text} if text else {}


def _ensure_source_brief_core_fields(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value if isinstance(value, dict) else {})
    content = str(result.get("content") or result.get("summary") or result.get("core_premise") or "").strip()
    result.setdefault("source_title", result.get("title") or result.get("project_title") or "未命名项目")
    result.setdefault("target_format", result.get("format") or "短剧")
    result.setdefault("season_count", 1)
    result.setdefault("episodes_per_season", result.get("total_episodes") or "")
    result.setdefault("minutes_per_episode", 2)
    result.setdefault("core_premise", content or "核心故事信息待人工补充")
    result.setdefault("story_outline", result.get("outline") or result["core_premise"])
    result.setdefault("adaptation_direction", result.get("direction") or "保持强钩子、强反转、强情绪推进")
    result["ready_for_script_workflow"] = True
    return result


def _ensure_worldview_core_fields(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value if isinstance(value, dict) else {})

    summary = str(result.get("summary") or result.get("content") or result.get("core_setting") or "").strip()

    result.setdefault("world_type", result.get("type") or "现实/类型化世界")

    if "core_setting" not in result or result.get("core_setting") in (None, "", [], {}):
        result["core_setting"] = summary or result.get("setting") or "核心世界设定待人工补充"

    if "main_conflict" not in result or result.get("main_conflict") in (None, "", [], {}):
        conflict_engine = result.get("conflict_engine")
        if isinstance(conflict_engine, list) and conflict_engine:
            result["main_conflict"] = str(conflict_engine[0])
        else:
            result["main_conflict"] = result.get("conflict") or "主角目标与外部阻力形成持续对抗"

    if "rules" not in result or result.get("rules") in (None, "", [], {}):
        core_rules = result.get("core_rules")
        world_rules = result.get("world_rules")
        if isinstance(core_rules, list) and core_rules:
            result["rules"] = core_rules
        elif isinstance(world_rules, list) and world_rules:
            result["rules"] = world_rules
        else:
            result["rules"] = []

    if "tone" not in result or result.get("tone") in (None, "", [], {}):
        visual_style = result.get("visual_style")
        if isinstance(visual_style, list) and visual_style:
            result["tone"] = str(visual_style[0])
        else:
            result["tone"] = result.get("style") or "强情绪、强节奏、强反转"

    result["ready_for_script_workflow"] = True
    return result


CHARACTER_NAME_ALIASES = (
    "name",
    "legal_name",
    "legalName",
    "character_name",
    "characterName",
    "display_name",
    "displayName",
    "姓名",
    "姓名 / 合法称呼",
    "姓名/合法称呼",
    "合法称呼",
    "角色姓名",
    "角色名",
    "称呼",
)
CHARACTER_ROLE_ALIASES = (
    "role",
    "role_type",
    "roleType",
    "character_role",
    "characterRole",
    "identity",
    "定位",
    "角色定位",
    "身份",
    "人物定位",
)


def _normalize_character_entry(value: dict[str, Any], *, index: int = 0) -> dict[str, Any]:
    item = dict(value if isinstance(value, dict) else {})
    name = _first_present_value(item, CHARACTER_NAME_ALIASES)
    if name is not None:
        item["name"] = str(name).strip()
    role = _first_present_value(item, CHARACTER_ROLE_ALIASES)
    if role is not None and not str(item.get("role") or "").strip():
        item["role"] = str(role).strip()
    if not str(item.get("name") or "").strip() and index > 0:
        item["name"] = f"角色{index}"
    return item


def _ensure_character_core_fields(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value if isinstance(value, dict) else {})

    characters = (
        result.get("characters")
        if isinstance(result.get("characters"), list)
        else result.get("main_characters")
        if isinstance(result.get("main_characters"), list)
        else result.get("mainCharacters")
    )
    if isinstance(characters, list) and characters:
        normalized_characters = [
            _normalize_character_entry(item, index=index)
            for index, item in enumerate(characters, start=1)
            if isinstance(item, dict)
        ]
        result["characters"] = normalized_characters
    else:
        normalized_characters = []

    protagonist = result.get("protagonist")
    if not isinstance(protagonist, dict):
        protagonist = {}
    protagonist = _normalize_character_entry(protagonist)

    if not protagonist and normalized_characters:
        for item in normalized_characters:
            role_text = str(item.get("role") or item.get("id") or "").lower()
            if "protagonist" in role_text or "主角" in str(item.get("role") or ""):
                protagonist = item
                break
        if not protagonist:
            protagonist = normalized_characters[0]

    if not protagonist:
        protagonist = {}

    result["protagonist"] = protagonist

    main_characters = result.get("main_characters")
    if not isinstance(main_characters, list) or not main_characters:
        main_characters = normalized_characters or [protagonist]
    main_characters = [
        _normalize_character_entry(item, index=index)
        for index, item in enumerate(main_characters, start=1)
        if isinstance(item, dict)
    ]
    result["main_characters"] = main_characters

    if "character_relationships" not in result or result.get("character_relationships") in (None, "", [], {}):
        relationship_map = result.get("relationship_map")
        if isinstance(relationship_map, list) and relationship_map:
            result["character_relationships"] = relationship_map
        else:
            result["character_relationships"] = result.get("relationships") or []

    if "emotion_engine" not in result or result.get("emotion_engine") in (None, "", [], {}):
        result["emotion_engine"] = (
            result.get("character_system_summary")
            or result.get("emotional_core")
            or "围绕目标、阻力、关系变化持续推进情绪"
        )

    result["ready_for_script_workflow"] = True
    return result


def _total_episodes_from_payload(payload: dict[str, Any] | None) -> int:
    source = payload if isinstance(payload, dict) else {}
    basic = source.get("basic_config") if isinstance(source.get("basic_config"), dict) else {}
    for candidate in (
        source.get("total_episodes"),
        basic.get("total_episodes"),
    ):
        try:
            number = int(candidate)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    season_count = 0
    episodes_per_season = 0
    for candidate in (source.get("season_count"), basic.get("season_count")):
        try:
            season_count = int(candidate)
        except (TypeError, ValueError):
            season_count = 0
        if season_count > 0:
            break
    for candidate in (source.get("episodes_per_season"), basic.get("episodes_per_season")):
        try:
            episodes_per_season = int(candidate)
        except (TypeError, ValueError):
            episodes_per_season = 0
        if episodes_per_season > 0:
            break
    return season_count * episodes_per_season if season_count > 0 and episodes_per_season > 0 else 0


def _normalize_beat_timeline(value: Any, *, total_episodes: int = 0) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else []
    ranges = (
        _split_episode_ranges(total_episodes)
        if total_episodes > 0
        else ["未明确，需后续确认集数后重排"] * 15
    )
    normalized: list[dict[str, Any]] = []
    for index in range(15):
        raw = items[index] if index < len(items) and isinstance(items[index], dict) else {}
        beat_no = index + 1
        normalized.append(
            {
                "beat_no": raw.get("beat_no") or raw.get("beatNo") or raw.get("no") or beat_no,
                "beat_name": str(_first_present_value(raw, ("beat_name", "beatName", "name", "title", "节拍名称")) or FIFTEEN_BEAT_NAMES[index]),
                "act": str(raw.get("act") or _act_for_beat(beat_no)),
                "episode_range": str(_first_present_value(raw, ("episode_range", "episodeRange", "range", "episodes", "集数范围")) or ranges[index]),
                "checkpoint_title": str(_first_present_value(raw, ("checkpoint_title", "checkpointTitle", "title", "card_title", "卡点标题")) or f"{FIFTEEN_BEAT_NAMES[index]}卡点"),
                "narrative_function": str(_first_present_value(raw, ("narrative_function", "narrativeFunction", "function", "purpose", "叙事功能")) or ""),
                "plot_content": str(_first_present_value(raw, ("plot_content", "plotContent", "content", "plot", "story", "剧情内容")) or ""),
                "character_change": str(_first_present_value(raw, ("character_change", "characterChange", "arc_change", "characterArc", "人物变化")) or ""),
                "conflict_upgrade": str(_first_present_value(raw, ("conflict_upgrade", "conflictUpgrade", "conflict", "conflict_escalation", "冲突升级")) or ""),
                "hook_or_reversal": str(_first_present_value(raw, ("hook_or_reversal", "hookOrReversal", "hook", "reversal", "twist", "钩子或反转")) or ""),
                "linked_storylines": _normalize_string_list(_first_present_value(raw, ("linked_storylines", "linkedStorylines", "storylines", "related_storylines", "关联故事线"))),
            }
        )
    return normalized


def _normalize_checkpoint_explanation(value: Any, timeline: list[dict[str, Any]]) -> dict[str, Any]:
    def _as_int(raw: Any, default: int = 0) -> int:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    def _aligned_notes(raw_notes: Any) -> list[dict[str, Any]]:
        source_notes = raw_notes if isinstance(raw_notes, list) else []
        by_beat: dict[int, dict[str, Any]] = {}
        for item in source_notes:
            if not isinstance(item, dict):
                continue
            beat_no = _as_int(item.get("beat_no"), 0)
            if beat_no > 0:
                by_beat[beat_no] = item
        notes: list[dict[str, Any]] = []
        for item in timeline:
            beat_no = _as_int(item.get("beat_no"), 0) or len(notes) + 1
            raw = by_beat.get(beat_no) or {}
            explanation = str(
                raw.get("explanation")
                or raw.get("summary")
                or raw.get("note")
                or raw.get("content")
                or item.get("plot_content")
                or item.get("narrative_function")
                or ""
            )
            notes.append({"beat_no": beat_no, "explanation": explanation})
        return notes

    if isinstance(value, dict):
        overview = str(value.get("overview") or value.get("summary") or "").strip()
        beat_notes = value.get("beat_notes")
        if beat_notes or overview:
            return {
                "overview": overview or "该卡点说明与同一条十五节拍时间轴一一对应，用于解释各节拍的叙事功能与阶段作用。",
                "beat_notes": _aligned_notes(beat_notes),
            }
    elif isinstance(value, str) and value.strip():
        return {
            "overview": value.strip(),
            "beat_notes": _aligned_notes([]),
        }
    return {
        "overview": "该卡点说明与同一条十五节拍时间轴一一对应，用于解释各节拍的叙事功能与阶段作用。",
        "beat_notes": _aligned_notes([]),
    }


STAGE04_CONTENT_FIELDS = (
    "plot_content",
    "narrative_function",
    "conflict_upgrade",
    "hook_or_reversal",
    "character_change",
)
STAGE04_MIN_FILLED_PER_FIELD = 10
STAGE04_MIN_STRONG_BEATS = 10
STAGE04_AMBIGUOUS_RANGE_MARKERS = ("未明确", "待确认", "重排", "未知", "?")


def _write_stage04_coze_http_debug(
    *,
    response: requests.Response,
    endpoint: FrameworkPlannerEndpoint,
    body: dict[str, Any],
    response_text: str,
) -> None:
    try:
        raw_debug_dir = _repo_root() / "cache" / "raw_coze_debug"
        raw_debug_dir.mkdir(parents=True, exist_ok=True)
        debug_path = raw_debug_dir / "stage04_http_raw_latest.json"
        debug_path.write_text(
            json.dumps(
                {
                    "stage": "04",
                    "backend": "coze",
                    "status_code": getattr(response, "status_code", None),
                    "endpoint_url": endpoint.url,
                    "workflow_id": endpoint.workflow_id,
                    "workflow_id_source": endpoint.workflow_id_source,
                    "api_key_source": endpoint.api_key_source,
                    "request_body": body,
                    "response_text": response_text,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        logger.warning("[framework_planner_raw_debug] wrote stage04 raw Coze HTTP response path=%s", debug_path)
    except Exception:
        logger.exception("[framework_planner_raw_debug] failed to write stage04 raw Coze HTTP response")


def _write_stage04_parser_debug(
    *,
    data: dict[str, Any],
    display_text: str,
    parsed_response: Any,
    parse_warnings: list[str],
) -> None:
    try:
        raw_debug_dir = _repo_root() / "cache" / "raw_coze_debug"
        raw_debug_dir.mkdir(parents=True, exist_ok=True)
        debug_path = raw_debug_dir / "stage04_raw_response.json"
        final_data = dict(data if isinstance(data, dict) else {})
        final_data["display_text"] = display_text or final_data.get("display_text") or ""
        debug_path.write_text(
            json.dumps(
                {
                    "stage": "04",
                    "backend": "coze",
                    "data": final_data,
                    "data_keys": sorted(final_data.keys()),
                    "parsed_response": parsed_response,
                    "parse_warnings": [str(item) for item in parse_warnings if str(item).strip()],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        logger.warning("[framework_planner_raw_debug] wrote stage04 parsed Coze response path=%s", debug_path)
    except Exception:
        logger.exception("[framework_planner_raw_debug] failed to write stage04 parsed Coze response")


def _coze_data_keys(value: Any) -> list[str]:
    """调试用：尽量展示 Coze data 层的 key。"""
    parsed = _stage04_deep_parse_json_like(value)

    if isinstance(parsed, dict):
        data = parsed.get("data")
        data = _stage04_deep_parse_json_like(data)
        if isinstance(data, dict):
            return sorted(str(key) for key in data.keys())

        if isinstance(parsed, dict):
            return sorted(str(key) for key in parsed.keys())

    return []


def _coze_stage04_returned_single_beat_object(value: Any) -> bool:
    """
    判断 Coze 是否只返回了单个 beat 对象。
    这种情况必须失败，不能包装成 1 条 timeline。
    """
    parsed = _stage04_deep_parse_json_like(value)

    if isinstance(parsed, dict):
        data = _stage04_deep_parse_json_like(parsed.get("data"))
        if isinstance(data, dict):
            beat = _stage04_deep_parse_json_like(data.get("beat"))
            if _stage04_is_beat_object(beat):
                return True

        beat = _stage04_deep_parse_json_like(parsed.get("beat"))
        if _stage04_is_beat_object(beat):
            return True

    return False


def _stage04_raw_timeline_value(value: Any) -> Any:
    """
    从原始/解析后 response 中尽量拿到 beat_checkpoint_timeline。
    仅用于校验 detail；不负责放行。
    """
    extracted = _stage04_extract_payload_from_nested_coze(value)
    if isinstance(extracted, dict):
        return extracted.get("beat_checkpoint_timeline")

    parsed = _stage04_deep_parse_json_like(value)
    if isinstance(parsed, dict):
        aliases = STAGE_DEFINITIONS["04"].output_aliases.get(
            "beat_checkpoint_timeline",
            ("beat_checkpoint_timeline",),
        )
        direct = _find_value_by_aliases(parsed, aliases)
        if direct is not None:
            return _stage04_deep_parse_json_like(direct)

        data = _stage04_deep_parse_json_like(parsed.get("data"))
        if isinstance(data, dict):
            nested = _find_value_by_aliases(data, aliases)
            if nested is not None:
                return _stage04_deep_parse_json_like(nested)

    return None


def _validate_stage04_output_or_raise(
    *,
    data: dict[str, Any],
    payload: dict[str, Any] | None,
    parse_warnings: list[str],
    response_json: Any,
    raw_response_json: Any = None,
) -> None:
    timeline = data.get("beat_checkpoint_timeline") if isinstance(data, dict) else None
    explanation = data.get("checkpoint_explanation") if isinstance(data, dict) else None
    raw_timeline = _stage04_raw_timeline_value(response_json)
    total_episodes = _total_episodes_from_payload(payload)
    detail: dict[str, Any] = {
        "reason": "",
        "stage": "04",
        "raw_type": type(response_json).__name__,
        "coze_data_keys": _coze_data_keys(raw_response_json if raw_response_json is not None else response_json),
        "normalized_keys": sorted(data.keys()) if isinstance(data, dict) else [],
        "timeline_type": type(timeline).__name__ if timeline is not None else "none",
        "timeline_length": len(timeline) if isinstance(timeline, list) else 0,
        "raw_timeline_type": type(raw_timeline).__name__ if raw_timeline is not None else "none",
        "raw_timeline_length": len(raw_timeline) if isinstance(raw_timeline, list) else 0,
        "total_episodes": total_episodes,
        "checked_timeline_aliases": list(STAGE_DEFINITIONS["04"].output_aliases.get("beat_checkpoint_timeline", ())),
        "checked_explanation_aliases": list(STAGE_DEFINITIONS["04"].output_aliases.get("checkpoint_explanation", ())),
        "checked_content_fields": list(STAGE04_CONTENT_FIELDS),
        "parse_warnings": [str(item) for item in parse_warnings if str(item).strip()],
        "response_preview": safe_truncated_preview(response_json, limit=1200),
    }
    failures: list[str] = []

    if _coze_stage04_returned_single_beat_object(raw_response_json if raw_response_json is not None else response_json):
        failures.append("coze_stage04_returned_single_beat_object")

    if raw_timeline is not None and not isinstance(raw_timeline, list):
        failures.append("beat_checkpoint_timeline_not_list")
    elif isinstance(raw_timeline, list) and len(raw_timeline) != 15:
        failures.append("beat_checkpoint_timeline_length_not_15")

    if not isinstance(timeline, list):
        failures.append("beat_checkpoint_timeline_not_list")
    elif len(timeline) != 15:
        failures.append("beat_checkpoint_timeline_length_not_15")

    field_non_empty_counts = {field: 0 for field in STAGE04_CONTENT_FIELDS}
    strong_beats = 0
    bad_episode_ranges: list[dict[str, Any]] = []
    max_detected_episode = 0
    if isinstance(timeline, list):
        for index, item in enumerate(timeline, start=1):
            if not isinstance(item, dict):
                failures.append(f"beat_{index}_not_object")
                continue
            filled = 0
            for field in STAGE04_CONTENT_FIELDS:
                if str(item.get(field) or "").strip():
                    field_non_empty_counts[field] += 1
                    filled += 1
            if filled >= 4:
                strong_beats += 1
            range_detail = _stage04_episode_range_problem(item.get("episode_range"), total_episodes)
            max_detected_episode = max(max_detected_episode, range_detail.get("max_episode") or 0)
            if range_detail.get("problem"):
                bad_episode_ranges.append(
                    {
                        "beat_no": item.get("beat_no") or index,
                        "episode_range": item.get("episode_range"),
                        **range_detail,
                    }
                )

    sparse_fields = [
        field for field, count in field_non_empty_counts.items()
        if count < STAGE04_MIN_FILLED_PER_FIELD
    ]
    if sparse_fields:
        failures.append("stage04_content_fields_sparse")
    if strong_beats < STAGE04_MIN_STRONG_BEATS:
        failures.append("stage04_too_many_empty_or_weak_beats")
    if total_episodes <= 0:
        failures.append("stage04_missing_total_episodes")
    if bad_episode_ranges:
        failures.append("stage04_episode_range_invalid")

    beat_notes = []
    if isinstance(explanation, dict):
        raw_notes = explanation.get("beat_notes") or explanation.get("beatNotes") or []
        beat_notes = raw_notes if isinstance(raw_notes, list) else []
    explanation_non_empty_count = 0
    for item in beat_notes:
        if isinstance(item, dict):
            text = item.get("explanation") or item.get("summary") or item.get("note") or item.get("content")
        else:
            text = item
        if str(text or "").strip():
            explanation_non_empty_count += 1
    if explanation_non_empty_count < STAGE04_MIN_FILLED_PER_FIELD:
        failures.append("checkpoint_explanation_beat_notes_sparse")

    detail.update(
        {
            "failures": failures,
            "field_non_empty_counts": field_non_empty_counts,
            "strong_beat_count": strong_beats,
            "explanation_non_empty_count": explanation_non_empty_count,
            "max_detected_episode": max_detected_episode,
            "bad_episode_ranges": bad_episode_ranges[:20],
        }
    )

    if failures:
        detail["reason"] = failures[0]
        logger.warning(
            "framework planner stage04 invalid output: reason=%s raw_type=%s timeline_type=%s timeline_length=%s total_episodes=%s field_counts=%s bad_ranges=%s parse_warnings=%s preview=%s",
            detail["reason"],
            detail["raw_type"],
            detail["timeline_type"],
            detail["timeline_length"],
            total_episodes,
            field_non_empty_counts,
            bad_episode_ranges[:5],
            detail["parse_warnings"],
            detail["response_preview"],
        )
        raise FrameworkPlannerStageError(
            "04 阶段输出为空壳或集数不合法，未保存为成功结果。",
            stage="04",
            status_code=422,
            detail=detail,
        )


def _stage04_episode_range_problem(raw_range: Any, total_episodes: int) -> dict[str, Any]:
    text = str(raw_range or "").strip()
    if not text:
        return {"problem": "empty_episode_range", "max_episode": 0}
    for marker in STAGE04_AMBIGUOUS_RANGE_MARKERS:
        if marker in text:
            return {"problem": "ambiguous_episode_range", "max_episode": 0}
    numbers = [int(value) for value in re.findall(r"\d+", text)]
    if not numbers:
        return {"problem": "unparseable_episode_range", "max_episode": 0}
    max_episode = max(numbers)
    if total_episodes <= 0:
        return {"problem": "missing_total_episodes", "max_episode": max_episode}
    if max_episode > total_episodes:
        return {"problem": "episode_range_exceeds_total", "max_episode": max_episode}
    if total_episodes == 1 and text != "第1集":
        return {"problem": "single_episode_range_must_equal第1集", "max_episode": max_episode}
    return {"problem": "", "max_episode": max_episode}


def _normalize_character_storylines(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        parsed = _parse_candidate_value(value)
        if isinstance(parsed, (dict, list)):
            return _normalize_character_storylines(parsed)
        text = value.strip()
        items = [{"summary": text, "detailed_storyline": text}] if text else []
    elif isinstance(value, dict):
        nested = value.get("character_storylines")
        if nested is None and isinstance(value.get("data"), dict):
            nested = value["data"].get("character_storylines")
        if nested is not None:
            return _normalize_character_storylines(nested)
        storyline_keys = {
            "id",
            "title",
            "character_name",
            "summary",
            "content",
            "detailed_storyline",
            "linked_beats",
            "episode_distribution",
            "edit_notes",
            "decision",
        }
        if storyline_keys.intersection(value.keys()):
            items = [value]
        else:
            items = []
            for key, item in value.items():
                if isinstance(item, dict):
                    merged = dict(item)
                    merged.setdefault("id", str(key))
                    items.append(merged)
                elif isinstance(item, str) and item.strip():
                    items.append({"id": str(key), "title": str(key), "summary": item.strip()})
    else:
        items = value if isinstance(value, list) else []
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            continue
        title = raw.get("title") or raw.get("character_name") or raw.get("name") or f"故事线 {index}"
        normalized.append(
            {
                "id": str(raw.get("id") or f"storyline_{index}"),
                "title": str(title),
                "summary": str(raw.get("summary") or raw.get("content") or ""),
                "detailed_storyline": str(raw.get("detailed_storyline") or raw.get("detail") or raw.get("summary") or ""),
                "linked_beats": _normalize_int_list(raw.get("linked_beats") or raw.get("linked_storylines")),
                "episode_distribution": _normalize_episode_distribution(raw.get("episode_distribution")),
                "edit_notes": str(raw.get("edit_notes") or raw.get("detailNote") or ""),
                "decision": _normalize_storyline_decision(raw.get("decision")),
            }
        )
    return normalized


def _decode_jsonish_value(value: Any, *, max_depth: int = 8) -> Any:
    """递归解开被字符串化的 JSON object / array。

    只解析以 { 或 [ 开头的字符串，避免把普通字符串如 "3" 误转成数字。
    """
    if max_depth <= 0:
        return value

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value

        if text.startswith("{") or text.startswith("["):
            try:
                parsed = json.loads(text)
            except Exception:
                parsed_values = _json_objects_from_text(text)
                if len(parsed_values) == 1:
                    return _decode_jsonish_value(parsed_values[0], max_depth=max_depth - 1)
                return value

            return _decode_jsonish_value(parsed, max_depth=max_depth - 1)

        return value

    if isinstance(value, dict):
        return {
            str(key): _decode_jsonish_value(item, max_depth=max_depth - 1)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            _decode_jsonish_value(item, max_depth=max_depth - 1)
            for item in value
        ]

    return value


def _ensure_object_value(value: Any) -> dict[str, Any]:
    value = _decode_jsonish_value(value)
    return value if isinstance(value, dict) else {}


def _ensure_list_value(value: Any) -> list[Any]:
    value = _decode_jsonish_value(value)
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


def _normalize_adaptation_guide(value: Any) -> dict[str, Any]:
    def first_text(source: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            item = source.get(key)
            if item in (None, "", [], {}):
                continue
            if isinstance(item, (dict, list)):
                return json.dumps(item, ensure_ascii=False, indent=2)
            return str(item)
        return ""

    value = _decode_jsonish_value(value)

    if isinstance(value, dict):
        nested = value.get("adaptation_guide")
        if nested not in (None, "", [], {}) and nested is not value:
            return _normalize_adaptation_guide(nested)

        packed = value.get("core_setting_adjustments")
        if isinstance(packed, dict):
            merged = dict(packed)
            for key, item in value.items():
                if key != "core_setting_adjustments" and item not in (None, "", [], {}):
                    merged.setdefault(key, item)
            return _normalize_adaptation_guide(merged)

        result = {
            "core_setting_adjustments": first_text(
                value,
                (
                    "core_setting_adjustments",
                    "core_setting_adjustment",
                    "core_setting",
                    "setting_adjustments",
                    "worldview_adjustments",
                ),
            ),
            "structure_and_rhythm": first_text(
                value,
                (
                    "structure_and_rhythm",
                    "narrative_rhythm_structure",
                    "rhythm_structure",
                    "structure_rhythm",
                    "narrative_structure",
                ),
            ),
            "visualization_strategy": first_text(
                value,
                (
                    "visualization_strategy",
                    "visualization",
                    "visual_strategy",
                    "visual_design",
                ),
            ),
            "character_emotion_strategy": first_text(
                value,
                (
                    "character_emotion_strategy",
                    "character_emotion_shaping",
                    "emotion_strategy",
                    "emotional_strategy",
                ),
            ),
        }

        constraints = value.get("hard_constraints_for_script_workflow") or value.get("hard_constraints")
        if constraints not in (None, "", [], {}):
            result["hard_constraints_for_script_workflow"] = constraints

        return result

    if isinstance(value, list):
        items = [item for item in value if isinstance(item, dict)]
        if len(items) == 1:
            return _normalize_adaptation_guide(items[0])

    text = str(value or "").strip()
    return {
        "core_setting_adjustments": text,
        "structure_and_rhythm": "",
        "visualization_strategy": "",
        "character_emotion_strategy": "",
    }


def _sanitize_framework_plan_package(value: Any) -> dict[str, Any]:
    """清洗 stage07 最终策划包。

    目标：
    1. JSON 字符串转回 object / array；
    2. 移除 d3ixvj8d 这类 FastGPT 内部变量名；
    3. 保留后续剧本链路所需的稳定字段。
    """
    package = _decode_jsonish_value(value)

    if isinstance(package, dict) and isinstance(package.get("framework_plan_package"), dict):
        package = package["framework_plan_package"]

    if not isinstance(package, dict):
        package = {}

    cleaned: dict[str, Any] = {
        "mode": package.get("mode") or "创作",
        "basic_config": _ensure_object_value(package.get("basic_config")),
        "source_brief": _ensure_object_value(package.get("source_brief")),
        "worldview_plan": _ensure_object_value(package.get("worldview_plan")),
        "character_plan": _ensure_object_value(package.get("character_plan")),
        "beat_checkpoint_timeline": _ensure_list_value(package.get("beat_checkpoint_timeline")),
        "checkpoint_explanation": _ensure_object_value(package.get("checkpoint_explanation")),
        "character_storylines": _ensure_list_value(package.get("character_storylines")),
        "storyline_decisions": _ensure_list_value(package.get("storyline_decisions")),
        "adaptation_guide": _normalize_adaptation_guide(
            package.get("adaptation_guide")
            or package.get("adaptationGuide")
            or package.get("overallAdaptationGuide")
            or package.get("overall_adaptation_guide")
            or package.get("guide")
            or package.get("previous_adaptation_guide")
        ),
        "user_edit_history": _ensure_list_value(package.get("user_edit_history")),
    }

    adaptation_direction = package.get("adaptation_direction")
    if adaptation_direction not in (None, "", [], {}):
        cleaned["adaptation_direction"] = str(adaptation_direction)

    handoff_notes = package.get("handoff_notes")
    if handoff_notes not in (None, "", [], {}):
        cleaned["handoff_notes"] = str(handoff_notes)

    storage_key = package.get("storage_key")
    if storage_key not in (None, "", [], {}):
        cleaned["storage_key"] = str(storage_key)

    stage_prompts = _merge_stage_prompt_payloads_non_empty(
        package.get("stage_prompts"),
        package.get("stagePrompts"),
        package.get("user_knowledge_stage_prompts"),
        (package.get("prompt_preferences") or {}).get("stage_prompts") if isinstance(package.get("prompt_preferences"), dict) else {},
    )
    if any(stage_prompts.values()):
        cleaned["stage_prompts"] = stage_prompts
        cleaned["user_knowledge_stage_prompts"] = stage_prompts
        cleaned["prompt_preferences"] = {
            **(package.get("prompt_preferences") if isinstance(package.get("prompt_preferences"), dict) else {}),
            "stage_prompts": stage_prompts,
        }

    source_brief = cleaned.get("source_brief")
    if isinstance(source_brief, dict):
        source_title = str(source_brief.get("source_title") or "").strip()
        if source_title:
            if str(source_brief.get("title") or "").strip() in {"", "未命名项目"}:
                source_brief["title"] = source_title
            if str(source_brief.get("project_title") or "").strip() in {"", "未命名项目"}:
                source_brief["project_title"] = source_title

    return cleaned


def _build_validation_report_from_package(
    package: dict[str, Any],
    *,
    parse_warnings: list[str] | None = None,
) -> dict[str, Any]:
    beat_count = len(package.get("beat_checkpoint_timeline") or [])
    storyline_count = len(package.get("character_storylines") or [])

    missing: list[str] = []
    for key in (
        "basic_config",
        "source_brief",
        "worldview_plan",
        "character_plan",
        "beat_checkpoint_timeline",
        "character_storylines",
        "adaptation_guide",
    ):
        if package.get(key) in (None, "", [], {}):
            missing.append(key)

    adaptation_guide = package.get("adaptation_guide") or {}
    guide_empty_fields: list[str] = []
    if isinstance(adaptation_guide, dict):
        for key in (
            "core_setting_adjustments",
            "structure_and_rhythm",
            "visualization_strategy",
            "character_emotion_strategy",
        ):
            if adaptation_guide.get(key) in (None, "", [], {}):
                guide_empty_fields.append(key)

    warnings = list(parse_warnings or [])
    if beat_count != 15:
        warnings.append(f"beat_checkpoint_timeline 数量不是 15：当前 {beat_count}")
    if missing:
        warnings.append(f"框架策划包缺少字段：{', '.join(missing)}")
    if guide_empty_fields:
        warnings.append(f"adaptation_guide 存在空字段：{', '.join(guide_empty_fields)}")

    passed = not missing and beat_count == 15 and not guide_empty_fields

    return {
        "passed": passed,
        "summary": "框架策划包结构完整，可交付后续正式剧本生成链路。" if passed else "框架策划包仍有缺口，需要修订后再交付。",
        "checks": {
            "beat_count": beat_count,
            "storyline_count": storyline_count,
            "has_basic_config": bool(package.get("basic_config")),
            "has_source_brief": bool(package.get("source_brief")),
            "has_worldview_plan": bool(package.get("worldview_plan")),
            "has_character_plan": bool(package.get("character_plan")),
            "has_adaptation_guide": bool(package.get("adaptation_guide")),
            "missing_fields": missing,
            "adaptation_guide_empty_fields": guide_empty_fields,
        },
        "warnings": warnings,
    }

def _normalize_validation_report(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    return {"summary": text} if text else {}


def _normalize_storyline_decision(value: Any) -> str:
    decision = str(value or "keep").strip().lower()
    if decision not in {"keep", "simplify", "delete"}:
        return "keep"
    return decision


def _normalize_episode_distribution(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(
                {
                    "episode_range": str(item.get("episode_range") or item.get("range") or ""),
                    "focus": str(item.get("focus") or item.get("title") or item.get("content") or ""),
                }
            )
        else:
            text = str(item or "").strip()
            if text:
                normalized.append({"episode_range": "", "focus": text})
    return normalized


def _normalize_int_list(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    result: list[int] = []
    for item in items:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        result.append(number)
    return result


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _first_present_value(payload: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        if alias in payload and not _is_blank(payload.get(alias)):
            return payload.get(alias)
    return None


def _find_value_by_aliases(data: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        if alias in data and data.get(alias) not in (None, "", [], {}):
            return data.get(alias)
    return None


def _wire_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return value


def _safe_response_text(response: requests.Response) -> str:
    try:
        return response.text
    except Exception:
        return ""


def _endpoint_host_port(endpoint: str) -> tuple[str, int | None]:
    try:
        parsed = urlsplit(str(endpoint or ""))
        host = parsed.hostname or ""
        port = parsed.port
        if port is None:
            if parsed.scheme == "https":
                port = 443
            elif parsed.scheme == "http":
                port = 80
        return host, port
    except Exception:
        return "", None


def _safe_header_lookup(response: requests.Response, key: str) -> str:
    try:
        if response is None:
            return ""
        headers = getattr(response, "headers", {}) or {}
        value = headers.get(key)
        return str(value).strip() if value is not None else ""
    except Exception:
        return ""


def _response_json_decode_success(response: requests.Response) -> bool:
    try:
        if response is None:
            return False
        response.json()
        return True
    except Exception:
        return False


def _exception_response(exc: Exception) -> requests.Response | None:
    response = getattr(exc, "response", None)
    return response if response is not None else None


def _classify_request_exception(
    exc: Exception | None,
    *,
    response: requests.Response | None = None,
) -> str:
    if isinstance(exc, requests.ConnectTimeout):
        return "ConnectTimeout"
    if isinstance(exc, requests.ReadTimeout):
        return "ReadTimeout"
    if isinstance(exc, requests.Timeout):
        return "Timeout"
    if isinstance(exc, requests.ConnectionError):
        return "ConnectionError"
    if isinstance(exc, requests.HTTPError):
        return "HTTPError"
    if isinstance(exc, json.JSONDecodeError):
        return "JSONDecodeError"
    if response is not None and getattr(response, "status_code", 0) >= 400:
        return "HTTPError"
    if exc is None:
        return "Other"
    return "Other"


def _mapping_length_summary(value: Any) -> dict[str, Any]:
    mapping = value if isinstance(value, dict) else {}
    return {
        key: _value_length_summary(item)
        for key, item in mapping.items()
    }


def _value_length_summary(value: Any) -> Any:
    if isinstance(value, str):
        return {"type": "str", "length": len(value)}
    if isinstance(value, dict):
        return {
            "type": "dict",
            "size": len(value),
            "keys": sorted(value.keys()),
            "field_lengths": {
                key: _value_size_metric(item)
                for key, item in value.items()
            },
        }
    if isinstance(value, (list, tuple, set)):
        return {
            "type": type(value).__name__,
            "size": len(value),
        }
    return {
        "type": type(value).__name__,
        "length": len(str(value)) if value not in (None, "") else 0,
    }


def _value_size_metric(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return len(str(value))


def _source_text_length_from_payload(payload: dict[str, Any]) -> int:
    source_text = payload.get("source_text")
    if source_text is None and isinstance(payload.get("basic_config"), dict):
        source_text = payload["basic_config"].get("source_text")
    return len(str(source_text or ""))


def _write_debug_artifact(
    *,
    stage: str,
    workflow_spec: FrameworkPlannerWorkflowSpec,
    request_variables: dict[str, Any],
    payload: dict[str, Any],
    response_raw: Any,
    parse_error: str,
) -> dict[str, Any]:
    debug_dir = get_runtime_data_dir(Path(__file__).resolve().parents[2]) / "debug_dumps" / "framework_planner"
    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = debug_dir / f"framework_planner_stage_{stage}_{timestamp}_{uuid.uuid4().hex[:8]}.json"
    artifact = {
        "stage": stage,
        "workflow_json_path": str(workflow_spec.path),
        "payload_keys": sorted(payload.keys()),
        "request_variable_keys": sorted(request_variables.keys()),
        "request_variable_preview": {
            key: safe_truncated_preview(value, limit=300)
            for key, value in request_variables.items()
        },
        "response_raw_preview": safe_truncated_preview(response_raw, limit=4000),
        "parse_error": parse_error,
    }
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "debug_artifact_path": str(path),
        "workflow_json_path": str(workflow_spec.path),
        "payload_keys": sorted(payload.keys()),
        "parse_error": parse_error,
    }


def _build_mock_stage_output(stage: str, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if stage == "01":
        source_title = str(payload.get("source_title") or "未命名原作")
        target_format = str(payload.get("target_format") or "短剧")
        source_text = str(payload.get("source_text") or "").strip()
        source_brief = {
            "source_title": source_title,
            "target_format": target_format,
            "season_plan": {
                "season_count": int(payload.get("season_count") or 1),
                "episodes_per_season": int(payload.get("episodes_per_season") or 0),
                "minutes_per_episode": int(payload.get("minutes_per_episode") or 2),
            },
            "core_premise": source_text[:180] or "当前为 mock 提取结果，请在接入真实原文后替换。",
            "main_conflict": "主角被旧秩序压制，被迫进入更高风险的规则体系中完成自我翻盘。",
            "tone_keywords": ["强钩子", "强反转", "强情绪"],
            "adaptation_direction": str(payload.get("adaptation_direction") or ""),
            "user_constraints": str(payload.get("user_constraints") or ""),
            "user_requirements": str(payload.get("user_requirements") or ""),
        }
        return {"source_brief": source_brief}, json.dumps(source_brief, ensure_ascii=False, indent=2)

    if stage == "02":
        worldview_plan = {
            "world_type": "近未来高压都市短剧世界",
            "core_rules": [
                "资源被平台、资本与隐秘组织共同垄断。",
                "主角每跨过一个等级门槛，都会暴露更大的代价与真相。",
                "公开羞辱、限时任务、身份揭露与资源争夺是主要戏剧化手段。",
            ],
            "power_structure": [
                "平台方负责制定准入规则。",
                "地方财团负责操盘资源流向。",
                "地下信息网络负责掌握灰色真相。",
            ],
            "main_conflict": "主角必须在看似公开公平、实则被操控的规则体系中撕开上升通道。",
            "visual_style": "高压、节奏快、场面外化、冲突可拍摄。",
        }
        return {"worldview_plan": worldview_plan}, json.dumps(worldview_plan, ensure_ascii=False, indent=2)

    if stage == "03":
        character_plan = {
            "protagonist": {
                "name": "林渡",
                "identity": "被排挤的底层执行者",
                "goal": "查清旧案真相并反向夺回资源入口",
                "flaw": "过度逞强，不愿信任他人",
                "growth_arc": "从单点反击走向主动承担与联手破局",
            },
            "antagonist": {
                "name": "周砺",
                "identity": "掌握规则解释权的既得利益代表",
                "goal": "维持既得秩序并清除不稳定因素",
                "methods": ["身份压制", "信息差操控", "公开羞辱", "资源封锁"],
            },
            "b_story_role": {
                "name": "沈念",
                "identity": "与主角相互试探的关键同伴",
                "function": "承担情感与价值观回流，让主角完成内在转向",
            },
            "supporting_roles": [
                {"name": "顾行舟", "function": "提供关键线索并制造阶段性误解"},
                {"name": "梁澈", "function": "提供资源通道，同时制造背叛风险"},
            ],
            "relationship_map": [
                "主角 vs 反派：规则体系的正面对抗",
                "主角 vs B 故事人物：从互相利用到建立信任",
                "主角 vs 配角群：阶段性联盟、背叛与回收",
            ],
        }
        return {"character_plan": character_plan}, json.dumps(character_plan, ensure_ascii=False, indent=2)

    if stage == "04":
        total = _episodes_per_season_from_basic_config(payload.get("basic_config"))
        ranges = _split_episode_ranges(total)
        linked_storylines = [
            ["主角成长线", "反派压迫线"],
            ["主角成长线", "B故事情感线"],
            ["秘密揭露线"],
            ["主角成长线", "反派压迫线"],
            ["主角成长线", "B故事情感线"],
            ["主角成长线", "秘密揭露线"],
            ["B故事情感线"],
            ["主角成长线", "反派压迫线"],
            ["秘密揭露线", "主角成长线"],
            ["反派压迫线", "B故事情感线"],
            ["反派压迫线", "秘密揭露线"],
            ["主角成长线", "B故事情感线"],
            ["主角成长线", "秘密揭露线"],
            ["主角成长线", "反派压迫线", "秘密揭露线"],
            ["主角成长线", "B故事情感线"],
        ]
        timeline: list[dict[str, Any]] = []
        for index, beat_name in enumerate(FIFTEEN_BEAT_NAMES, start=1):
            timeline.append(
                {
                    "beat_no": index,
                    "beat_name": beat_name,
                    "act": _act_for_beat(index),
                    "episode_range": ranges[index - 1],
                    "checkpoint_title": f"{beat_name}卡点",
                    "narrative_function": f"承接{beat_name}对应的核心叙事功能，并为下一个节拍蓄压。",
                    "plot_content": f"第 {index} 节拍围绕 {beat_name} 展开，推动主角与规则体系的冲突继续升级。",
                    "character_change": "主角逐渐从被动应对转向主动破局。",
                    "conflict_upgrade": "旧秩序的压制手段升级，迫使人物关系和资源分配重新洗牌。",
                    "hook_or_reversal": f"{beat_name}结尾抛出下一阶段必须立即处理的钩子或反转。",
                    "linked_storylines": linked_storylines[index - 1],
                }
            )
        explanation = {
            "overview": "该 checkpoint_explanation 仅用于解释同一条十五节拍时间轴，不再额外复制一套 checkpointPlan 结构。",
            "beat_notes": [
                {
                    "beat_no": item["beat_no"],
                    "explanation": f"{item['beat_name']}主要承担 {item['narrative_function']}",
                }
                for item in timeline
            ],
        }
        return {
            "beat_checkpoint_timeline": timeline,
            "checkpoint_explanation": explanation,
        }, json.dumps(
            {"beat_checkpoint_timeline": timeline, "checkpoint_explanation": explanation},
            ensure_ascii=False,
            indent=2,
        )

    if stage == "05":
        storylines = [
            {
                "id": "protagonist_growth",
                "title": "主角成长线",
                "summary": "主角从被规则压制到主动掌控反击节奏，是全季主引擎。",
                "detailed_storyline": "前半段承担处境、缺陷与被迫入局，后半段承担崩盘、转向与反攻闭环。",
                "linked_beats": [1, 2, 4, 6, 9, 11, 12, 13, 14, 15],
                "episode_distribution": [
                    {"episode_range": "前 10 集", "focus": "低位处境与被迫入局"},
                    {"episode_range": "中段", "focus": "阶段胜利后的认知反转"},
                    {"episode_range": "后段", "focus": "崩盘、转向与最终反攻"},
                ],
                "edit_notes": "重点保留，后续剧本必须持续体现成长递进。",
                "decision": "keep",
            },
            {
                "id": "antagonist_pressure",
                "title": "反派压迫线",
                "summary": "反派以规则解释权、资源封锁和公开羞辱推动冲突升级。",
                "detailed_storyline": "用于持续制造门槛、围剿和阶段性失败，是主线爽点与危机感的重要来源。",
                "linked_beats": [1, 3, 4, 8, 10, 11, 14],
                "episode_distribution": [
                    {"episode_range": "前段", "focus": "压迫与规则展示"},
                    {"episode_range": "中段", "focus": "围剿升级与局部压制"},
                    {"episode_range": "后段", "focus": "反制与秩序崩塌"},
                ],
                "edit_notes": "必须与主角成长线同步升级。",
                "decision": "keep",
            },
            {
                "id": "b_story_relationship",
                "title": "B故事情感线",
                "summary": "承担信任修复与主题回流，但不应压过主线节奏。",
                "detailed_storyline": "建议保留关键节点，弱化独立展开，确保它服务于主角在最低谷后的转向。",
                "linked_beats": [3, 7, 10, 12, 15],
                "episode_distribution": [
                    {"episode_range": "前中段", "focus": "建立误解与合作试探"},
                    {"episode_range": "后中段", "focus": "价值观碰撞与支撑"},
                    {"episode_range": "结尾", "focus": "情感闭环"},
                ],
                "edit_notes": "适合精简保留。",
                "decision": "simplify",
            },
            {
                "id": "secret_reveal",
                "title": "秘密揭露线",
                "summary": "围绕旧案、身份与资源真相埋伏笔，并在中点与第三幕前集中回收。",
                "detailed_storyline": "该线主要服务于悬念和反转，是主线升级的重要燃料。",
                "linked_beats": [2, 3, 9, 11, 13, 14],
                "episode_distribution": [
                    {"episode_range": "前段", "focus": "埋伏笔与异常点"},
                    {"episode_range": "中点", "focus": "揭露第一层真相"},
                    {"episode_range": "后段", "focus": "真相代价与最终回收"},
                ],
                "edit_notes": "保留，以支撑反转密度。",
                "decision": "keep",
            },
        ]
        return {"character_storylines": storylines}, json.dumps(storylines, ensure_ascii=False, indent=2)

    if stage == "06":
        guide = {
            "core_setting_adjustments": "保留资源垄断与规则对抗的大骨架，改动时不得削弱主角与规则体系的硬碰撞。",
            "structure_and_rhythm": "按强开局、高频小高潮、中点反转、低谷转向、终局反攻的节奏执行。",
            "visualization_strategy": "把心理冲突尽量外化成公开对峙、限时任务、证据展示、排名变化与身份揭露。",
            "character_emotion_strategy": "主角情绪从屈辱、不甘、逞强，推进到清醒、承担与主动反攻。",
        }
        return {"adaptation_guide": guide}, json.dumps(guide, ensure_ascii=False, indent=2)

    if stage == "07":
        storylines = _normalize_character_storylines(payload.get("character_storylines"))
        decisions = _normalize_storyline_decisions(payload.get("storyline_decisions"), storylines)
        selected_storylines = [
            {
                **item,
                "decision": decisions.get(item["id"], item.get("decision", "keep")),
            }
            for item in storylines
            if decisions.get(item["id"], item.get("decision", "keep")) != "delete"
        ]
        package = {
            "basic_config": payload.get("basic_config") or {},
            "source_brief": payload.get("source_brief") or {},
            "worldview_plan": payload.get("worldview_plan") or {},
            "character_plan": payload.get("character_plan") or {},
            "beat_checkpoint_timeline": payload.get("beat_checkpoint_timeline") or [],
            "checkpoint_explanation": payload.get("checkpoint_explanation") or {},
            "character_storylines": selected_storylines,
            "storyline_decisions": payload.get("storyline_decisions") or [],
            "adaptation_guide": _normalize_adaptation_guide(
                payload.get("adaptation_guide")
                or payload.get("adaptationGuide")
                or payload.get("overallAdaptationGuide")
                or payload.get("overall_adaptation_guide")
                or payload.get("guide")
                or payload.get("previous_adaptation_guide")
                or {}
            ),
            "user_edit_history": payload.get("user_edit_history") or [],
            "handoff_notes": "该策划包已按框架工作台输出，可直接交给正式剧本生成链路。",
            "storage_key": FRAMEWORK_PLANNER_STORAGE_KEY,
        }
        validation = {
            "passed": True,
            "warnings": [],
            "checks": {
                "beat_count": len(package["beat_checkpoint_timeline"]),
                "storyline_count": len(selected_storylines),
                "has_adaptation_guide": bool(package["adaptation_guide"]),
            },
            "summary": "框架策划包结构完整，可交付后续正式剧本生成链路。",
        }
        return {
            "framework_plan_package": package,
            "validation_report": validation,
        }, json.dumps(
            {"framework_plan_package": package, "validation_report": validation},
            ensure_ascii=False,
            indent=2,
        )

    raise FrameworkPlannerStageError("未知阶段", stage=stage, status_code=404)


def _normalize_storyline_decisions(
    value: Any,
    storylines: list[dict[str, Any]],
) -> dict[str, str]:
    if isinstance(value, list):
        decisions: dict[str, str] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            identifier = str(item.get("storyline_id") or item.get("id") or "").strip()
            if not identifier:
                continue
            decisions[identifier] = _normalize_storyline_decision(item.get("decision"))
        return decisions
    decisions = {
        item["id"]: _normalize_storyline_decision(item.get("decision"))
        for item in storylines
    }
    return decisions


def _episodes_per_season_from_basic_config(value: Any) -> int:
    config = value if isinstance(value, dict) else {}

    def positive_int(raw: Any) -> int:
        try:
            number = int(raw)
        except (TypeError, ValueError):
            return 0
        return number if number > 0 else 0

    total = positive_int(config.get("total_episodes") or config.get("totalEpisodes"))
    if total > 0:
        return total
    season_count = positive_int(config.get("season_count") or config.get("seasonCount"))
    episodes = positive_int(config.get("episodes_per_season") or config.get("episodesPerSeason"))
    if season_count > 0 and episodes > 0:
        return season_count * episodes
    return episodes


def _split_episode_ranges(total_episodes: int) -> list[str]:
    try:
        total_episodes = int(total_episodes)
    except (TypeError, ValueError):
        total_episodes = 0
    if total_episodes <= 0:
        return ["未明确，需后续确认集数后重排"] * 15
    if total_episodes < 15:
        ranges: list[str] = []
        for index in range(15):
            start = min(total_episodes, (index * total_episodes) // 15 + 1)
            end = min(total_episodes, ((index + 1) * total_episodes + 14) // 15)
            end = max(start, end)
            if start == end:
                ranges.append(f"第{start}集")
            else:
                ranges.append(f"第{start}-{end}集")
        return ranges

    weights = [3, 4, 4, 4, 4, 5, 5, 7, 5, 5, 4, 4, 3, 2, 1]
    weight_sum = sum(weights)
    start = 1
    ranges: list[str] = []
    for index, weight in enumerate(weights, start=1):
        remaining = 15 - index
        if index == 15:
            length = total_episodes - start + 1
        else:
            length = max(1, round(total_episodes * weight / weight_sum))
            if start + length + remaining - 1 > total_episodes:
                length = max(1, total_episodes - start - remaining + 1)
        end = min(total_episodes, start + length - 1)
        if start == end:
            ranges.append(f"第{start}集")
        else:
            ranges.append(f"第{start}-{end}集")
        start = end + 1
    return ranges


def _act_for_beat(beat_no: int) -> str:
    if beat_no <= 6:
        return "第一幕"
    if beat_no <= 12:
        return "第二幕"
    return "第三幕"


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def _env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_with_name(*names: str) -> tuple[str, str]:
    expanded_names = []
    for name in names:
        text = str(name or "").strip()
        if not text:
            continue
        expanded_names.append(text)

    seen = set()
    for name in expanded_names:
        if name in seen:
            continue
        seen.add(name)
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return name, str(value).strip()
    return "", ""


def _workflow_backend() -> str:
    return "coze"


def _is_coze_backend() -> bool:
    return _workflow_backend() == "coze"


def _coze_api_token_env_names() -> tuple[str, ...]:
    return ("ns_primary_api_token",)


def _coze_api_token_with_name() -> tuple[str, str]:
    return _env_with_name(*_coze_api_token_env_names())


def _coze_api_base_with_name(token_source: str = "") -> tuple[str, str]:
    return "hardcoded", DEFAULT_NS_API_BASE


def _normalize_coze_workflow_url(raw_url: str) -> str:
    url = str(raw_url or "").strip().rstrip("/")
    if not url:
        return DEFAULT_NS_WORKFLOW_URL
    if url.endswith("/v1/workflow/run"):
        return url
    if url.endswith("/workflow/run"):
        return url
    if "/v1/" in url:
        return f"{url}/workflow/run"
    return f"{url}/v1/workflow/run"


def _normalize_fastgpt_url(raw_url: str) -> str:
    url = str(raw_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("FastGPT 接口地址不能为空")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"FastGPT 接口地址必须以 http:// 或 https:// 开头：{url}")
    if url.endswith("/api/v1/chat/completions"):
        return url
    if url.endswith("/api/v1/chat/completions/"):
        return url.rstrip("/")
    if url.endswith("/api/v1"):
        return f"{url}/chat/completions"
    if url.endswith("/api"):
        return f"{url}/v1/chat/completions"
    parts = urlsplit(url)
    normalized_path = parts.path.rstrip("/")
    if not normalized_path:
        normalized_path = "/api/v1/chat/completions"
        return urlunsplit((parts.scheme, parts.netloc, normalized_path, parts.query, parts.fragment))
    return url


def _truncate_text(value: str, *, limit: int = 800) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _preview_return_object(value: Any, *, limit: int = 2400) -> str:
    try:
        return _truncate_text(repr(value), limit=limit)
    except Exception:
        try:
            return _truncate_text(
                json.dumps(value, ensure_ascii=False, default=str),
                limit=limit,
            )
        except Exception:
            return "<unprintable>"


def _payload_config_value(payload: dict[str, Any], key: str) -> Any:
    """按优先级从 payload/basic_config/locked_basic_config 读取用户锁定配置。"""
    if not isinstance(payload, dict):
        return None

    value = payload.get(key)
    if value not in (None, "", [], {}):
        return value

    for container_name in ("locked_basic_config", "basic_config"):
        container = payload.get(container_name)
        if isinstance(container, dict):
            value = container.get(key)
            if value not in (None, "", [], {}):
                return value

    return None


def _overlay_source_brief_locked_fields(
    source_brief: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """stage01 输出必须继承用户明确填写的基础配置。"""
    result = dict(source_brief if isinstance(source_brief, dict) else {})

    for key in (
        "source_title",
        "target_format",
        "season_count",
        "episodes_per_season",
        "minutes_per_episode",
        "adaptation_direction",
    ):
        value = _payload_config_value(payload, key)
        if value not in (None, "", [], {}):
            result[key] = value

    project_title = _payload_config_value(payload, "project_title") or _payload_config_value(payload, "title")
    if result.get("source_title") in (None, "", "未命名项目") and project_title not in (None, "", [], {}):
        result["source_title"] = project_title

    source_title = str(result.get("source_title") or "").strip()
    if source_title:
        if str(result.get("title") or "").strip() in {"", "未命名项目"}:
            result["title"] = source_title
        if str(result.get("project_title") or "").strip() in {"", "未命名项目"}:
            result["project_title"] = source_title

    return result


def _repair_stage_output_with_payload(
    stage: str,
    data: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """用用户锁定输入修复阶段输出中的关键继承字段。"""
    result = dict(data if isinstance(data, dict) else {})

    if stage == "01":
        source_brief = result.get("source_brief")
        source_brief = _overlay_source_brief_locked_fields(source_brief, payload)
        result["source_brief"] = _ensure_source_brief_core_fields(source_brief)

    if stage == "07":
        package = result.get("framework_plan_package") if isinstance(result.get("framework_plan_package"), dict) else {}

        stage_prompts = _merge_stage_prompt_payloads_non_empty(
            package.get("stage_prompts"),
            package.get("user_knowledge_stage_prompts"),
            (package.get("prompt_preferences") or {}).get("stage_prompts") if isinstance(
                package.get("prompt_preferences"), dict) else {},
            payload.get("stage_prompts") if isinstance(payload.get("stage_prompts"), dict) else {},
            payload.get("user_knowledge_stage_prompts") if isinstance(payload.get("user_knowledge_stage_prompts"),
                                                                      dict) else {},
            (payload.get("prompt_preferences") or {}).get("stage_prompts") if isinstance(
                payload.get("prompt_preferences"), dict) else {},
        )

        def stage07_package_has_core_fields(pkg: dict[str, Any]) -> bool:
            return (
                    isinstance(pkg.get("basic_config"), dict) and bool(pkg.get("basic_config"))
                    and isinstance(pkg.get("source_brief"), dict) and bool(pkg.get("source_brief"))
                    and isinstance(pkg.get("worldview_plan"), dict) and bool(pkg.get("worldview_plan"))
                    and isinstance(pkg.get("character_plan"), dict) and bool(pkg.get("character_plan"))
                    and isinstance(pkg.get("beat_checkpoint_timeline"), list) and bool(
                pkg.get("beat_checkpoint_timeline"))
                    and isinstance(pkg.get("checkpoint_explanation"), dict) and bool(pkg.get("checkpoint_explanation"))
                    and isinstance(pkg.get("character_storylines"), list) and bool(pkg.get("character_storylines"))
                    and isinstance(pkg.get("adaptation_guide"), dict) and bool(pkg.get("adaptation_guide"))
            )

        # Coze Stage07 可能只返回很薄的 framework/package，甚至被清洗成空壳。
        # 只要最终包缺核心字段，就直接用前 1-6 阶段 payload 重建最终包。
        if not stage07_package_has_core_fields(package):
            package = {
                "mode": payload.get("mode") or "创作",
                "basic_config": payload.get("basic_config") if isinstance(payload.get("basic_config"), dict) else {},
                "source_brief": payload.get("source_brief") if isinstance(payload.get("source_brief"), dict) else {},
                "worldview_plan": payload.get("worldview_plan") if isinstance(payload.get("worldview_plan"),
                                                                              dict) else {},
                "character_plan": payload.get("character_plan") if isinstance(payload.get("character_plan"),
                                                                              dict) else {},
                "beat_checkpoint_timeline": payload.get("beat_checkpoint_timeline") if isinstance(
                    payload.get("beat_checkpoint_timeline"), list) else [],
                "checkpoint_explanation": payload.get("checkpoint_explanation") if isinstance(
                    payload.get("checkpoint_explanation"), dict) else {},
                "character_storylines": payload.get("character_storylines") if isinstance(
                    payload.get("character_storylines"), list) else [],
                "storyline_decisions": payload.get("storyline_decisions") if isinstance(
                    payload.get("storyline_decisions"), list) else [],
                "adaptation_guide": (
                        payload.get("adaptation_guide")
                        or payload.get("adaptationGuide")
                        or payload.get("overallAdaptationGuide")
                        or payload.get("overall_adaptation_guide")
                        or payload.get("guide")
                        or {}
                ),
                "user_edit_history": payload.get("user_edit_history") if isinstance(payload.get("user_edit_history"),
                                                                                    list) else [],
            }

        if any(stage_prompts.values()):
            package = dict(package)
            package["stage_prompts"] = stage_prompts
            package["user_knowledge_stage_prompts"] = stage_prompts
            package["prompt_preferences"] = {
                **(package.get("prompt_preferences") if isinstance(package.get("prompt_preferences"), dict) else {}),
                "stage_prompts": stage_prompts,
            }

        package = _sanitize_framework_plan_package(package)

        # 补交接说明，避免 07 直接进入正文生成。
        package["handoff_to_script_workflow"] = {
            "target": "framework_asset_pipeline",
            "ready_for_script_workflow": True,
            "input_summary": "该框架策划包已整合基础配置、原文提取、世界观、人设、十五节拍、人物故事线和整体改编指引，用于后续资产化流程。",
            "locked_sections": [
                "basic_config",
                "source_brief",
                "worldview_plan",
                "character_plan",
                "beat_checkpoint_timeline",
                "checkpoint_explanation",
                "character_storylines",
                "storyline_decisions",
                "adaptation_guide",
            ],
            "generation_priorities": [
                "先执行 08 sceneDictionary，提炼 2-3 个核心场景。",
                "再执行 09 appearanceMapping，固定人物外观、身份识别点、服装版本和 alias。",
                "再执行 10 enrichedEpisodePlan，将十五节拍和人物故事线转为按集分布的分集计划。",
                "因果冲突推进计划只读取 batchEnrichedEpisodePlan、sceneDictionary、appearanceMapping、scriptWorldRulesDigest、conflictMemory。",
                "禁止把完整 framework_plan_package 直接传给因果冲突或正文阶段。",
            ],
            "storyline_decision_effects": [
                "decision=keep 的人物线在后续剧本中完整保留。",
                "decision=simplify 的人物线只保留核心节点和功能。",
                "decision=delete 的人物线不得继续展开。",
            ],
            "hard_constraints": (
                package.get("adaptation_guide", {}).get("hard_constraints_for_script_workflow")
                if isinstance(package.get("adaptation_guide"), dict)
                   and isinstance(package.get("adaptation_guide", {}).get("hard_constraints_for_script_workflow"), list)
                else ["遵循 adaptation_guide 中的核心设定、节奏、视觉化和人物情绪约束。"]
            ),
            "do_not_change": [
                "不得推翻已确认世界观规则。",
                "不得重排十五节拍。",
                "不得新增与 character_plan 冲突的人物关系。",
                "不得删除已标记 keep 的核心人物线。",
            ],
            "risk_flags": [
                "framework_plan_package 信息量较大，不应直接传入因果冲突推进计划或剧本正文工作流；必须先压缩为 sceneDictionary、appearanceMapping、enrichedEpisodePlan 和 scriptWorldRulesDigest。"
            ],
            "recommended_next_action": "下一步先执行 08 sceneDictionary，基于 worldview_plan、beat_checkpoint_timeline、character_storylines 提炼 2-3 个核心场景；随后执行 09 appearanceMapping；再执行 10 enrichedEpisodePlan；最后进入因果冲突推进计划与剧本正文生成。",
            "asset_pipeline_order": [
                "08_sceneDictionary",
                "09_appearanceMapping",
                "10_enrichedEpisodePlan",
                "causalConflictPlan",
                "scriptWriting",
            ],
            "downstream_variable_contract": {
                "sceneDictionary": "由 worldview_plan + beat_checkpoint_timeline + character_storylines 提炼 2-3 个核心场景字典",
                "appearanceMapping": "由 character_plan + sceneDictionary + beat_checkpoint_timeline 生成，整合人设、动机、关系、服装、alias",
                "allEnrichedEpisodePlan": "由 beat_checkpoint_timeline + character_storylines + sceneDictionary + appearanceMapping 生成按集丰富分集计划",
                "batchEnrichedEpisodePlan": "allEnrichedEpisodePlan 按 5 集切片后传给因果冲突推进计划",
                "scriptWorldRulesDigest": "从 worldview_plan 压缩得到，只保留规则、限制、危险源和行动逻辑",
            },
        }

        result["framework_plan_package"] = package

        # 关键：用修复后的 package 重新生成 validation_report，覆盖 Coze/旧清洗得到的空壳校验。
        result["validation_report"] = _build_validation_report_from_package(
            package,
            parse_warnings=[],
        )

        if not str(result.get("display_text") or "").strip():
            result["display_text"] = (
                "最终框架策划包已完成结构合并和一致性校验，已整合基础配置、原文提取、世界观、人设、十五节拍、人物故事线和整体改编指引。"
                "当前包应先进入 08 sceneDictionary、09 appearanceMapping、10 enrichedEpisodePlan 的资产化流程，"
                "再进入因果冲突推进计划和剧本正文生成；禁止直接把完整 framework_plan_package 传给冲突或正文工作流。"
            )

    return result
