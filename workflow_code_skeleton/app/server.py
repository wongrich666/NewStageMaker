from __future__ import annotations

import json
import copy
import re
import shutil
import threading
import tempfile
import time
import traceback
import uuid
from io import BytesIO
from functools import wraps
import os
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from .models.inputs import derive_script_title_content
from .services.auth_store import auth_store
from .services.workflow_errors import WorkflowTransientError
from .services.framework_planner_service import (
    FRAMEWORK_PLANNER_STORAGE_KEY,
    FrameworkPlannerStageError,
    framework_planner_backend_ready,
    framework_planner_workflow_diagnostics,
    list_framework_stage_history,
    load_framework_stage_history,
    run_framework_planner_score,
    run_framework_planner_stage,
    save_framework_stage_history,
    write_framework_frontend_debug_event,
    write_framework_stage_exception_log,
)
from .services.simple_workflow_tools import ToolExecutionError, list_simple_tools, run_simple_tool
from .services.task_manager import task_manager
from .services.stage10_resume import (
    load_stage10_resume,
    save_stage10_resume,
    stage10_input_fingerprint,
)
from .services.stage11_chunks import (
    compact_appearance_mapping,
    compact_conflict_plan_for_review,
    compact_enriched_episode_plan,
    compact_scene_dictionary,
    episode_number as stage11_episode_number,
    load_stage11_write_resume,
    merge_causal_conflict_plans,
    save_stage11_write_resume,
    split_episode_plan,
    stage11_input_fingerprint,
)
from .services.user_knowledge_store import user_knowledge_store
from .services.workflow_preference_keys import (
    FRAMEWORK_TO_SCRIPT_STAGE_PREFS,
    inject_stage_preference,
    preference_keys_for,
    stage_prompt_key_for,
)
from .utils.logger import get_logger
from .utils.readable_labels import readable_label, readable_scalar, readable_text


logger = get_logger("server")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _writable_root() -> Path:
    """腾讯工作流 部署时项目目录可能只读，写入目录跟随 WRITABLE_ROOT。"""
    env = os.environ.get("WRITABLE_ROOT", "").strip()
    if env:
        return Path(env).resolve()
    return _repo_root()


def default_workflow_spec_path() -> str:
    return str(Path.home() / "Downloads" / "剧本生成_0401_loops.json")


def _framework_stage01_missing_fields(data: dict | None) -> list[str]:
    payload = data if isinstance(data, dict) else {}
    basic = payload.get("basic_config") if isinstance(payload.get("basic_config"), dict) else {}

    def first_text(*keys: str) -> str:
        for key in keys:
            for container in (payload, basic):
                text = str(container.get(key) or "").strip()
                if text:
                    return text
        return ""

    def first_positive_int(*keys: str) -> int | None:
        for key in keys:
            for container in (payload, basic):
                try:
                    number = int(container.get(key))
                except (TypeError, ValueError):
                    continue
                if number > 0:
                    return number
        return None

    checks = (
        ("作品标题", bool(first_text("source_title", "project_title", "title"))),
        ("写作模式", bool(first_text("mode"))),
        ("目标形式", bool(first_text("target_format"))),
        (
            "总集数",
            first_positive_int(
                "episodes_per_season",
                "total_episodes",
                "episodes_number",
                "episode_number",
            )
            is not None,
        ),
        (
            "每集字数",
            first_positive_int(
                "episode_word_count",
                "chars_per_episode",
                "chars_per_epi",
            )
            is not None,
        ),
        ("改编方向", bool(first_text("adaptation_direction"))),
        ("用户提示词", bool(first_text("user_requirements"))),
        ("原文材料", bool(first_text("source_text"))),
        ("限制条件", bool(first_text("user_constraints"))),
    )
    return [label for label, valid in checks if not valid]


def create_app(*, workflow_spec_path: str | None = None) -> Flask:
    template_dir = Path(__file__).resolve().parent / "web" / "templates"
    static_dir = Path(__file__).resolve().parent / "web" / "static"
    app = Flask(
        __name__,
        template_folder=str(template_dir),
        static_folder=str(static_dir),
    )
    app.config["WORKFLOW_SPEC_PATH"] = workflow_spec_path or default_workflow_spec_path()
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or os.getenv("FLASK_SECRET_KEY") or "scriptmaker-dev-secret"

    @app.before_request
    def _sync_auth_token():
        url_token = str(
            request.args.get("auth_token")
            or request.form.get("auth_token")
            or ""
        ).strip()
        if url_token and url_token != session.get("auth_token"):
            session["auth_token"] = url_token
            session.permanent = True

    @app.after_request
    def _disable_html_cache(response):
        if request.method == "GET" and response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    def _json_ok(**payload):
        return jsonify({"success": True, **payload})

    def _sanitize_error_message(
        message: str,
        *,
        status: int,
        fallback: str | None = None,
    ) -> str:
        text = str(message or "").strip()
        if status >= 500:
            return fallback or "服务暂时不可用，请稍后重试。"
        if not text:
            return fallback or "请求未能完成，请稍后重试。"
        technical_markers = (
            "workflow",
            "traceback",
            "http ",
            "response.text",
            "url:",
            "url：",
            "requests.",
            "exception",
            "typeerror",
            "keyerror",
            "bad gateway",
            "failed to fetch",
            "json",
            "校验失败",
            "无法转换",
            ".py",
        )
        lowered = text.lower()
        if len(text) > 120 or any(marker in lowered for marker in technical_markers):
            return fallback or "请求未能完成，请稍后重试。"
        return text

    def _json_error(message: str, status: int = 400, *, fallback: str | None = None):
        public_message = _sanitize_error_message(message, status=status, fallback=fallback)
        return jsonify({"success": False, "message": public_message}), status

    raw_workflow_response_keys = {
        "responseData",
        "choices",
        "reasoningText",
        "historyPreview",
        "newVariables",
        "updateVarResult",
        "raw_stage_responses",
        "raw_output",
        "raw",
        "answerText",
        "usage",
        "debug",
        "logs",
        "cache",
    }
    framework_stage_runs: dict[tuple[int, str, str], dict] = {}
    framework_stage_runs_by_id: dict[str, tuple[int, str, str]] = {}
    framework_stage_runs_lock = threading.Lock()

    def _now_iso() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat()

    def _stage12_debug_safe_name(value) -> str:
        text = str(value or "").strip()
        invalid = '<>:"/\\|?*'
        text = "".join("_" if (char in invalid or ord(char) < 32) else char for char in text)
        text = "_".join(text.split()).strip("._ ")
        return text[:80] or "未命名项目"

    def _stage12_debug_project_title(data: dict, framework_asset: dict | None) -> str:
        candidates = [
            data.get("project_title"),
            data.get("project_name"),
            data.get("title"),
            data.get("source_title"),
            (framework_asset or {}).get("project_title") if isinstance(framework_asset, dict) else "",
            (framework_asset or {}).get("title") if isinstance(framework_asset, dict) else "",
            (framework_asset or {}).get("source_title") if isinstance(framework_asset, dict) else "",
        ]
        package = data.get("framework_plan_package") if isinstance(data.get("framework_plan_package"), dict) else {}
        basic_config = package.get("basic_config") if isinstance(package.get("basic_config"), dict) else {}
        candidates.extend(
            [
                package.get("project_title"),
                package.get("title"),
                basic_config.get("project_title"),
                basic_config.get("title"),
            ]
        )
        for item in candidates:
            text = str(item or "").strip()
            if text:
                return text
        project_id = str(data.get("project_id") or data.get("framework_asset_id") or "").strip()
        return f"project_{project_id}" if project_id else "未命名项目"

    def _stage12_debug_preview(value, *, limit: int = 240):
        if value is None:
            return ""
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
            except Exception:
                text = str(value)
        text = " ".join(str(text).split())
        if len(text) > limit:
            return text[:limit] + "..."
        return text

    def _stage12_debug_summary(value, *, preview_limit: int = 240):
        if value is None:
            return {"type": "null", "exists": False, "length": 0, "preview": ""}
        if isinstance(value, str):
            return {
                "type": "str",
                "exists": bool(value),
                "length": len(value),
                "preview": _stage12_debug_preview(value, limit=preview_limit),
            }
        if isinstance(value, dict):
            return {
                "type": "dict",
                "exists": bool(value),
                "length": len(value),
                "keys": sorted(str(key) for key in value.keys())[:40],
                "json_length": len(json.dumps(value, ensure_ascii=False, default=str)),
                "preview": _stage12_debug_preview(value, limit=preview_limit),
            }
        if isinstance(value, list):
            return {
                "type": "list",
                "exists": bool(value),
                "length": len(value),
                "json_length": len(json.dumps(value, ensure_ascii=False, default=str)),
                "preview": _stage12_debug_preview(value[:2], limit=preview_limit),
            }
        text = str(value)
        return {
            "type": type(value).__name__,
            "exists": bool(text),
            "length": len(text),
            "preview": _stage12_debug_preview(text, limit=preview_limit),
        }

    def _stage12_script_structure_issues(
        script_text: str,
        *,
        start_episode: int,
        end_episode: int,
    ) -> list[str]:
        """Cheap local safety gate used only when Tencent's review stream has no final output."""
        text = str(script_text or "").strip()
        issues: list[str] = []
        if not text:
            return ["正文为空"]
        if text.startswith(("{", "[")):
            issues.append("正文疑似仍是 JSON 包装")
        expected = list(range(int(start_episode), int(end_episode) + 1))
        missing = []
        for episode in expected:
            patterns = (
                rf"第\s*{episode}\s*集",
                rf"(?m)^\s*{episode}\s*(?:集|[：:\-])",
            )
            if not any(re.search(pattern, text) for pattern in patterns):
                missing.append(episode)
        if missing:
            issues.append(f"正文缺少集标题：{missing}")
        minimum_chars = max(300, len(expected) * 180)
        if len(text) < minimum_chars:
            issues.append(f"正文过短：{len(text)} < {minimum_chars}")
        return issues

    def _stage12_debug_dir(data: dict, framework_asset: dict | None) -> Path:
        title = _stage12_debug_project_title(data, framework_asset)
        path = _writable_root() / "cache" / _stage12_debug_safe_name(title) / "framework_to_script" / "stage12"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_stage12_debug_file(
        debug_record: dict,
        *,
        data: dict,
        framework_asset: dict | None,
        success: bool = False,
    ) -> str:
        try:
            start_episode = debug_record.get("batch_start_episode") or "unknown"
            end_episode = debug_record.get("batch_end_episode") or start_episode
            if not debug_record.get("_debug_timestamp"):
                debug_record["_debug_timestamp"] = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S-%f")[:-3]
            filename = (
                f"stage12_episodes_{start_episode}_{end_episode}_success.json"
                if success
                else f"stage12_episodes_{start_episode}_{end_episode}_{debug_record['_debug_timestamp']}.json"
            )
            path = _stage12_debug_dir(data, framework_asset) / filename
            public_record = {key: value for key, value in debug_record.items() if not str(key).startswith("_")}
            public_record["debug_path"] = str(path)
            path.write_text(json.dumps(public_record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            return str(path)
        except Exception:
            logger.exception("framework-to-script stage12 debug file write failed")
            return ""
    def _framework_to_script_debug_dir(
        data: dict,
        framework_asset: dict | None,
        stage_no: str,
    ) -> Path:
        title = _stage12_debug_project_title(data, framework_asset)
        path = (
            _writable_root()
            / "cache"
            / _stage12_debug_safe_name(title)
            / "framework_to_script"
            / f"stage{str(stage_no).zfill(2)}"
        )
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _framework_to_script_raw_debug_dir() -> Path:
        path = _writable_root() / "cache" / "raw_tencent_debug"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _json_len_for_debug(value) -> int:
        try:
            return len(json.dumps(value, ensure_ascii=False, default=str))
        except Exception:
            return -1

    def _write_framework_to_script_debug_file(
        *,
        stage_no: str,
        data: dict,
        framework_asset: dict | None,
        record: dict,
        filename: str | None = None,
    ) -> str:
        try:
            stage = str(stage_no).zfill(2)
            timestamp = record.get("_debug_timestamp") or datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S-%f")[:-3]
            record["_debug_timestamp"] = timestamp

            public_record = {
                key: value
                for key, value in record.items()
                if not str(key).startswith("_")
            }
            public_record.setdefault("stage", stage)
            public_record.setdefault("created_at", _now_iso())

            path = _framework_to_script_debug_dir(data, framework_asset, stage) / (
                filename or f"stage{stage}_{timestamp}.json"
            )
            public_record["debug_path"] = str(path)
            path.write_text(
                json.dumps(public_record, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            return str(path)
        except Exception:
            logger.exception("framework-to-script stage%s debug file write failed", stage_no)
            return ""

    def _write_framework_to_script_raw_tencent_debug(
        *,
        stage_no: str,
        stage_name: str,
        variables: dict,
        raw_output,
        parsed_output=None,
        error: str = "",
    ) -> str:
        try:
            stage = str(stage_no).zfill(2)
            path = _framework_to_script_raw_debug_dir() / f"stage{stage}_raw_response.json"
            payload = {
                "stage": stage,
                "stage_name": stage_name,
                "backend": "tencent",
                "variable_keys": sorted(variables.keys()) if isinstance(variables, dict) else [],
                "variable_size_summary": {
                    key: {
                        "type": type(value).__name__,
                        "json_length": _json_len_for_debug(value),
                        "preview": _stage12_debug_preview(value, limit=500),
                    }
                    for key, value in (variables.items() if isinstance(variables, dict) else [])
                },
                "raw_output_type": type(raw_output).__name__,
                "raw_output_keys": sorted(raw_output.keys()) if isinstance(raw_output, dict) else [],
                "raw_output": raw_output,
                "parsed_output": parsed_output,
                "error": error,
                "created_at": _now_iso(),
            }
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            logger.warning(
                "[framework_to_script_raw_debug] wrote stage%s raw 腾讯工作流 response path=%s",
                stage,
                path,
            )
            return str(path)
        except Exception:
            logger.exception("[framework_to_script_raw_debug] failed to write stage%s raw response", stage_no)
            return ""

    def _stage12_workflow_debug_summary(client, stage_name: str) -> dict:
        try:
            info = client.get_last_stage_debug_info(stage_name)
        except Exception:
            info = {}
        if not isinstance(info, dict):
            return {}
        return {
            "status": info.get("status"),
            "http_status": info.get("http_status"),
            "http_reason": info.get("http_reason"),
            "payload_stats": info.get("payload_stats"),
            "payload_stats_before_compact": info.get("payload_stats_before_compact"),
            "payload_compaction": info.get("payload_compaction"),
            "raw_output_source": info.get("raw_output_source"),
            "matched_fields": info.get("matched_fields"),
            "matched_aliases": info.get("matched_aliases"),
            "missing_fields": info.get("missing_fields"),
            "candidate_sources": info.get("candidate_sources"),
            "probable_truncated_json": info.get("probable_truncated_json"),
            "response_preview": _stage12_debug_preview(info.get("response_preview"), limit=600),
            "answer_text_preview": _stage12_debug_preview(info.get("answer_text_preview"), limit=600),
            "output_keys": info.get("output_keys"),
            "last_failure_reason": info.get("last_failure_reason"),
        }

    def _strip_raw_workflow_fields(value):
        if isinstance(value, list):
            return [_strip_raw_workflow_fields(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if str(key) in raw_workflow_response_keys:
                continue
            result[key] = _strip_raw_workflow_fields(item)
        return result

    def _framework_state_from_project(project: dict) -> dict:
        if not isinstance(project, dict):
            return {}
        artifacts = project.get("artifacts") if isinstance(project.get("artifacts"), dict) else {}
        input_payload = project.get("input_payload") if isinstance(project.get("input_payload"), dict) else {}
        state = (
            project.get("framework_planner_state")
            or artifacts.get("framework_planner_state")
            or input_payload.get("framework_planner_state")
            or {}
        )
        return state if isinstance(state, dict) else {}

    def _framework_stage_outputs(framework_state: dict) -> dict:
        package = framework_state.get("framework_plan_package") if isinstance(framework_state.get("framework_plan_package"), dict) else {}
        outputs = {
            "source_brief": framework_state.get("source_brief") or package.get("source_brief") or {},
            "worldview_plan": framework_state.get("worldview_plan") or package.get("worldview_plan") or {},
            "character_plan": framework_state.get("character_plan") or package.get("character_plan") or {},
            "beat_checkpoint_timeline": framework_state.get("beat_checkpoint_timeline") or package.get("beat_checkpoint_timeline") or [],
            "checkpoint_explanation": framework_state.get("checkpoint_explanation") or package.get("checkpoint_explanation") or {},
            "character_storylines": framework_state.get("character_storylines") or package.get("character_storylines") or [],
            "storyline_decisions": framework_state.get("storyline_decisions") or package.get("storyline_decisions") or [],
            "adaptation_guide": framework_state.get("adaptation_guide") or package.get("adaptation_guide") or {},
        }
        return _strip_raw_workflow_fields(outputs)

    def _framework_import_package(framework_state: dict, stage_outputs: dict | None = None) -> dict:
        package = framework_state.get("framework_plan_package") if isinstance(framework_state.get("framework_plan_package"), dict) else {}
        if package:
            return copy.deepcopy(package)
        outputs = stage_outputs if isinstance(stage_outputs, dict) else _framework_stage_outputs(framework_state)
        synthesized = {
            "source_brief": outputs.get("source_brief") or framework_state.get("source_brief") or {},
            "worldview_plan": outputs.get("worldview_plan") or framework_state.get("worldview_plan") or {},
            "character_plan": outputs.get("character_plan") or framework_state.get("character_plan") or {},
            "beat_checkpoint_timeline": outputs.get("beat_checkpoint_timeline") or framework_state.get("beat_checkpoint_timeline") or [],
            "checkpoint_explanation": outputs.get("checkpoint_explanation") or framework_state.get("checkpoint_explanation") or {},
            "character_storylines": outputs.get("character_storylines") or framework_state.get("character_storylines") or [],
            "storyline_decisions": outputs.get("storyline_decisions") or framework_state.get("storyline_decisions") or [],
            "adaptation_guide": outputs.get("adaptation_guide") or framework_state.get("adaptation_guide") or {},
            "basic_config": framework_state.get("basic_config") if isinstance(framework_state.get("basic_config"), dict) else {},
        }
        meaningful_keys = (
            "source_brief",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint_timeline",
            "checkpoint_explanation",
            "character_storylines",
            "storyline_decisions",
            "adaptation_guide",
        )
        if any(_framework_value_present(synthesized.get(key)) for key in meaningful_keys):
            synthesized["package_id"] = framework_state.get("project_id") or "synthesized_framework_asset"
            synthesized["import_package_synthesized"] = True
            return _strip_raw_workflow_fields(synthesized)
        return {}

    def _framework_value_present(value) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True

    def _framework_basic_config_from_stage_payload(data: dict, existing_state: dict) -> dict:
        basic = data.get("basic_config") if isinstance(data.get("basic_config"), dict) else {}
        if basic:
            copied_basic = copy.deepcopy(basic)
            title = str(copied_basic.get("source_title") or copied_basic.get("project_title") or "").strip()
            if title:
                copied_basic["source_title"] = title
                copied_basic["project_title"] = title
            episodes_number = (
                copied_basic.get("episodes_number")
                or copied_basic.get("total_episodes")
                or copied_basic.get("episodes_per_season")
            )
            if episodes_number:
                copied_basic["episodes_number"] = episodes_number
                copied_basic["total_episodes"] = episodes_number
                copied_basic["episodes_per_season"] = episodes_number
            episode_word_count = (
                copied_basic.get("chars_per_epi")
                or copied_basic.get("episode_word_count")
                or copied_basic.get("chars_per_episode")
            )
            if episode_word_count:
                copied_basic["chars_per_epi"] = episode_word_count
                copied_basic["episode_word_count"] = episode_word_count
                copied_basic["chars_per_episode"] = episode_word_count
            return copied_basic
        existing_basic = existing_state.get("basic_config") if isinstance(existing_state.get("basic_config"), dict) else {}
        merged = copy.deepcopy(existing_basic)
        for key in (
            "project_title",
            "mode",
            "source_text",
            "source_title",
            "target_format",
            "episodes_number",
            "chars_per_epi",
            "season_count",
            "episodes_per_season",
            "chars_per_episode",
            "episode_word_count",
            "adaptation_direction",
            "user_constraints",
            "user_requirements",
        ):
            if key in data and _framework_value_present(data.get(key)):
                merged[key] = copy.deepcopy(data.get(key))
        title = str(merged.get("source_title") or merged.get("project_title") or "").strip()
        if title:
            merged["source_title"] = title
            merged["project_title"] = title
        episodes_number = (
            merged.get("episodes_number")
            or merged.get("total_episodes")
            or merged.get("episodes_per_season")
        )
        if episodes_number:
            merged["episodes_number"] = episodes_number
            merged["total_episodes"] = episodes_number
            merged["episodes_per_season"] = episodes_number
        episode_word_count = (
            merged.get("chars_per_epi")
            or merged.get("episode_word_count")
            or merged.get("chars_per_episode")
        )
        if episode_word_count:
            merged["chars_per_epi"] = episode_word_count
            merged["episode_word_count"] = episode_word_count
            merged["chars_per_episode"] = episode_word_count
        return merged

    def _framework_stage_output_fields(stage_no: str) -> tuple[str, ...]:
        return {
            "01": ("source_brief",),
            "02": ("worldview_plan",),
            "03": ("character_plan",),
            "04": ("beat_checkpoint_timeline", "checkpoint_explanation"),
            "05": ("character_storylines", "storyline_decisions"),
            "06": ("adaptation_guide",),
            "07": ("framework_plan_package", "validation_report"),
        }.get(str(stage_no or "").zfill(2), ())

    def _merge_framework_stage_state(existing_state: dict, stage_no: str, stage_output: dict) -> dict:
        stage_key = _framework_planner_stage_key(stage_no)
        stage_state = copy.deepcopy(existing_state.get("stage_state") if isinstance(existing_state.get("stage_state"), dict) else {})
        if not stage_key:
            return stage_state
        has_output = any(_framework_value_present(stage_output.get(field)) for field in _framework_stage_output_fields(stage_no))
        if not has_output:
            return stage_state
        current = stage_state.get(stage_key) if isinstance(stage_state.get(stage_key), dict) else {}
        stage_state[stage_key] = {
            **current,
            "locked": False,
            "confirmed": False,
            "status": "generated",
            "stageCommitted": True,
            "stageDraftDirty": False,
        }
        sequence = ("basic", "worldview", "character", "beat", "storylines", "guide", "package")
        if stage_key in sequence:
            index = sequence.index(stage_key)
            if index + 1 < len(sequence):
                next_key = sequence[index + 1]
                next_stage = stage_state.get(next_key) if isinstance(stage_state.get(next_key), dict) else {}
                if not next_stage.get("confirmed"):
                    stage_state[next_key] = {**next_stage, "locked": False, "status": "idle"}
        return stage_state

    def _autosave_framework_planner_stage(
        *,
        user_id: int,
        stage: str,
        request_payload: dict,
        stage_payload: dict,
    ) -> dict | None:
        if not isinstance(request_payload, dict) or not isinstance(stage_payload, dict):
            return None
        stage_no = str(stage or "").zfill(2)
        stage_output = stage_payload.get("data") if isinstance(stage_payload.get("data"), dict) else {}
        if not stage_output:
            return None

        requested_project_id = (
            request_payload.get("project_id")
            or request_payload.get("asset_id")
            or request_payload.get("source_framework_project_id")
        )
        raw_project_id = _positive_int_or_none(requested_project_id)
        existing_state: dict = {}
        if raw_project_id:
            snapshot = task_manager.get_project_snapshot(raw_project_id, user_id=user_id, public_view=False)
            if snapshot and str(snapshot.get("asset_kind") or "").strip() == "framework_planner":
                existing_state = _framework_state_from_project(snapshot)

        save_payload: dict = copy.deepcopy(existing_state)
        if raw_project_id:
            save_payload["project_id"] = raw_project_id
        save_payload["basic_config"] = _framework_basic_config_from_stage_payload(request_payload, existing_state)
        save_payload["project_title"] = (
            request_payload.get("source_title")
            or save_payload.get("source_title")
            or save_payload.get("basic_config", {}).get("source_title")
            or request_payload.get("project_title")
            or save_payload.get("project_title")
            or save_payload.get("title")
            or save_payload.get("basic_config", {}).get("project_title")
            or "未命名框架策划"
        )
        save_payload["source_title"] = save_payload["project_title"]
        save_payload["title"] = save_payload["project_title"]

        for field in (
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
        ):
            if field in request_payload and _framework_value_present(request_payload.get(field)):
                save_payload[field] = copy.deepcopy(request_payload.get(field))
            elif field not in save_payload:
                save_payload[field] = [] if field in {"beat_checkpoint_timeline", "character_storylines", "storyline_decisions"} else {}
            if field in stage_output and _framework_value_present(stage_output.get(field)):
                save_payload[field] = copy.deepcopy(stage_output.get(field))

        display_texts = save_payload.get("display_texts") if isinstance(save_payload.get("display_texts"), dict) else {}
        if isinstance(request_payload.get("display_texts"), dict):
            display_texts.update(copy.deepcopy(request_payload["display_texts"]))
        if _framework_value_present(stage_payload.get("display_text")):
            display_texts[stage_no] = stage_payload.get("display_text")
        save_payload["display_texts"] = display_texts

        for field in (
            "prompt_preferences",
            "preference_snapshot",
            "stage_prompts",
            "user_knowledge_stage_prompts",
            "selected_preference_tag_ids",
            "selected_preference_tags",
            "user_edit_history",
        ):
            if field in request_payload and _framework_value_present(request_payload.get(field)):
                save_payload[field] = copy.deepcopy(request_payload.get(field))
            elif field not in save_payload:
                save_payload[field] = [] if field in {"selected_preference_tag_ids", "selected_preference_tags", "user_edit_history"} else {}

        merged_stage_prompts = _merge_stage_prompts_non_empty(
            save_payload.get("stage_prompts"),
            save_payload.get("user_knowledge_stage_prompts"),
            (save_payload.get("prompt_preferences") or {}).get("stage_prompts") if isinstance(save_payload.get("prompt_preferences"), dict) else {},
        )
        save_payload["stage_prompts"] = merged_stage_prompts
        save_payload["user_knowledge_stage_prompts"] = merged_stage_prompts
        prompt_preferences = save_payload.get("prompt_preferences") if isinstance(save_payload.get("prompt_preferences"), dict) else {}
        prompt_preferences = dict(prompt_preferences)
        prompt_preferences["stage_prompts"] = merged_stage_prompts
        save_payload["prompt_preferences"] = prompt_preferences
        if isinstance(save_payload.get("framework_plan_package"), dict):
            save_payload["framework_plan_package"]["stage_prompts"] = copy.deepcopy(merged_stage_prompts)
            save_payload["framework_plan_package"]["prompt_preferences"] = {
                **(save_payload["framework_plan_package"].get("prompt_preferences") if isinstance(save_payload["framework_plan_package"].get("prompt_preferences"), dict) else {}),
                "stage_prompts": copy.deepcopy(merged_stage_prompts),
            }

        save_payload["stage_state"] = _merge_framework_stage_state(save_payload, stage_no, stage_output)
        current_view = {
            "01": "basic",
            "02": "worldview",
            "03": "character",
            "04": "beat_timeline",
            "05": "storylines",
            "06": "guide",
            "07": "package",
        }.get(stage_no)
        save_payload["current_view"] = current_view or save_payload.get("current_view") or "basic"
        asset_state = save_payload.get("asset_state") if isinstance(save_payload.get("asset_state"), dict) else {}
        save_payload["asset_state"] = {
            **asset_state,
            "asset_kind": "framework_planner",
            "asset_type": "framework",
            "project_id": raw_project_id or asset_state.get("project_id"),
            "asset_id": raw_project_id or asset_state.get("asset_id"),
            "status": "completed" if stage_no == "07" and _framework_value_present(save_payload.get("framework_plan_package")) else "in_progress",
            "current_stage": _framework_planner_stage_key(stage_no) or asset_state.get("current_stage") or "framework_planner",
            "last_action": f"autosave:stage{stage_no}",
        }

        asset = task_manager.save_framework_planner_asset(user_id=user_id, payload=save_payload)
        logger.info(
            "framework planner stage autosaved: user_id=%s project_id=%s stage=%s output_fields=%s",
            user_id,
            asset.get("project_id") if isinstance(asset, dict) else raw_project_id,
            stage_no,
            sorted(stage_output.keys()),
        )
        return asset

    def _framework_asset_payload(project: dict, *, include_detail: bool) -> dict:
        def _safe_positive_int(value, default=0):
            try:
                number = int(value)
                return number if number > 0 else default
            except Exception:
                return default

        framework_state = _framework_state_from_project(project)
        basic = framework_state.get("basic_config") if isinstance(framework_state.get("basic_config"), dict) else {}
        stage_outputs = _framework_stage_outputs(framework_state)
        package = _framework_import_package(framework_state, stage_outputs)
        artifacts = project.get("artifacts") if isinstance(project.get("artifacts"), dict) else {}
        input_payload = project.get("input_payload") if isinstance(project.get("input_payload"), dict) else {}
        metadata = project.get("metadata") if isinstance(project.get("metadata"), dict) else {}
        project_id = _safe_positive_int(project.get("project_id"), 0)
        owner_user_id = _safe_positive_int(project.get("user_id"), 0)
        script_snapshot = (
            task_manager.get_framework_to_script_asset_for_source(
                project_id,
                user_id=owner_user_id,
                public_view=False,
            )
            if project_id > 0 and owner_user_id > 0
            else None
        )
        script_artifacts = script_snapshot.get("artifacts") if isinstance((script_snapshot or {}).get("artifacts"), dict) else {}
        workspace_state = (
            script_artifacts.get("framework_to_script_state")
            if isinstance(script_artifacts.get("framework_to_script_state"), dict)
            else artifacts.get("framework_to_script_state")
            if isinstance(artifacts.get("framework_to_script_state"), dict)
            else {}
        )
        script_locked = bool(
            workspace_state.get("script_locked")
            or workspace_state.get("scriptLocked")
            or workspace_state.get("locked")
            or (script_snapshot or {}).get("script_locked")
            or (script_snapshot or {}).get("asset_locked")
        )
        script_locked_at = str(
            workspace_state.get("script_locked_at")
            or workspace_state.get("scriptLockedAt")
            or workspace_state.get("locked_at")
            or (script_snapshot or {}).get("locked_at")
            or ""
        ).strip()
        script_flags = (
            task_manager._asset_completion_flags(script_snapshot, "framework_to_script", "new_script")
            if isinstance(script_snapshot, dict)
            else {
                "asset_completed": False,
                "asset_status": "not_created",
                "asset_status_label": "未创建",
            }
        )
        if script_locked:
            script_flags = {
                **script_flags,
                "asset_completed": True,
                "asset_status": "completed",
                "asset_status_label": "已锁定",
            }
        preference_snapshot = (
            framework_state.get("preference_snapshot")
            or project.get("preference_snapshot")
            or metadata.get("preference_snapshot")
            or artifacts.get("preference_snapshot")
            or input_payload.get("preference_snapshot")
            or {}
        )
        if not isinstance(preference_snapshot, dict):
            preference_snapshot = {}
        stage_prompts = _merge_stage_prompts_non_empty(
            framework_state.get("stage_prompts") if isinstance(framework_state.get("stage_prompts"), dict) else {},
            framework_state.get("user_knowledge_stage_prompts") if isinstance(framework_state.get("user_knowledge_stage_prompts"), dict) else {},
            (framework_state.get("prompt_preferences") or {}).get("stage_prompts") if isinstance(framework_state.get("prompt_preferences"), dict) else {},
            _stage_prompts_from_snapshot(preference_snapshot),
        )
        title = str(
            framework_state.get("source_title")
            or basic.get("source_title")
            or framework_state.get("project_title")
            or project.get("title")
            or basic.get("project_title")
            or "未命名框架资产"
        ).strip()
        source_title = str(basic.get("source_title") or title).strip()
        summary_source = (
            package.get("summary")
            or package.get("logline")
            or package.get("core_summary")
            or basic.get("adaptation_direction")
            or basic.get("source_text")
            or project.get("summary")
            or ""
        )
        summary = str(summary_source or "").replace("\r", "\n").strip()
        if len(summary) > 220:
            summary = summary[:220].rstrip() + "..."
        asset_flags = task_manager._asset_completion_flags(project, "framework_planner", "framework")
        asset = {
            "asset_id": str(project.get("project_id") or framework_state.get("project_id") or ""),
            "project_id": project.get("project_id") or framework_state.get("project_id"),
            "task_id": project.get("task_id"),
            "title": title,
            "source_title": source_title,
            "target_format": str(basic.get("target_format") or project.get("target_format") or "短剧"),
            "episodes_per_season": _safe_positive_int(basic.get("episodes_per_season") or project.get("total_episodes"), 0),
            "episode_word_count": _safe_positive_int(basic.get("episode_word_count") or basic.get("chars_per_episode"), 600),
            "chars_per_episode": _safe_positive_int(basic.get("chars_per_episode") or basic.get("episode_word_count"), 600),
            "season_count": _safe_positive_int(basic.get("season_count"), 1),
            "created_at": project.get("created_at") or framework_state.get("created_at"),
            "updated_at": project.get("updated_at") or framework_state.get("updated_at"),
            "summary": summary or "已保存的框架资产，可导入后继续 框架到剧本链路。",
            "asset_kind": "framework_planner",
            "asset_type": "framework",
            "status": asset_flags.get("asset_status") or "in_progress",
            "runtime_status": project.get("status") or "",
            **asset_flags,
            "can_import": bool(package),
            "import_disabled_reason": "" if package else "缺少可恢复的框架策划包或阶段输出。",
            "stage_prompts": _strip_raw_workflow_fields(copy.deepcopy(stage_prompts)),
            "preference_snapshot": _strip_raw_workflow_fields(copy.deepcopy(preference_snapshot)),
            "framework_to_script_locked": script_locked,
            "script_locked": script_locked,
            "script_locked_at": script_locked_at,
            "asset_locked": script_locked,
            "script_asset_id": (script_snapshot or {}).get("project_id"),
            "has_script_asset": isinstance(script_snapshot, dict),
            "script_asset_status": script_flags.get("asset_status") or "not_created",
            "script_asset_status_label": script_flags.get("asset_status_label") or "未创建",
            "script_asset_completed": bool(script_flags.get("asset_completed")),
            "script_asset_updated_at": (script_snapshot or {}).get("updated_at"),
            "script_asset_created_at": (script_snapshot or {}).get("created_at"),
            "script_asset_runtime_status": (script_snapshot or {}).get("status"),
        }
        if include_detail:
            workspace_stage_outputs = (
                workspace_state.get("stageOutputs")
                if isinstance(workspace_state.get("stageOutputs"), dict)
                else {}
            )
            asset.update(
                {
                    "framework_plan_package": _strip_raw_workflow_fields(copy.deepcopy(package)),
                    "stage_outputs": _strip_raw_workflow_fields({**copy.deepcopy(stage_outputs), **copy.deepcopy(workspace_stage_outputs)}),
                    "framework_to_script_state": _strip_raw_workflow_fields(copy.deepcopy(workspace_state)),
                    "scriptStages": _strip_raw_workflow_fields(
    copy.deepcopy(
        workspace_state.get("scriptStages")
        or workspace_state.get("script_stages")
        or {}
    )
),
                    "stage_prompts": _strip_raw_workflow_fields(copy.deepcopy(stage_prompts)),
                    "preference_snapshot": _strip_raw_workflow_fields(copy.deepcopy(preference_snapshot)),
                }
            )
        return asset

    def _load_framework_asset_for_user(asset_id: str, user_id: int) -> dict | None:
        project_id = 0
        try:
            project_id = int(str(asset_id or "").strip())
        except Exception:
            project_id = 0
        if project_id <= 0:
            return None
        project = task_manager.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not project or str(project.get("asset_kind") or "").strip() != "framework_planner":
            return None
        asset = _framework_asset_payload(project, include_detail=True)
        return asset if asset.get("can_import") else None

    def _framework_to_script_lock_info_from_state(workspace_state: dict | None) -> dict:
        state = workspace_state if isinstance(workspace_state, dict) else {}
        locked = bool(
            state.get("script_locked")
            or state.get("scriptLocked")
            or state.get("locked")
            or state.get("framework_to_script_locked")
        )
        locked_at = str(
            state.get("script_locked_at")
            or state.get("scriptLockedAt")
            or state.get("locked_at")
            or ""
        ).strip()
        return {"locked": locked, "locked_at": locked_at}

    def _framework_asset_script_lock_info(framework_asset: dict | None) -> dict:
        if not isinstance(framework_asset, dict):
            return {"locked": False, "locked_at": ""}
        workspace_state = framework_asset.get("framework_to_script_state")
        info = _framework_to_script_lock_info_from_state(workspace_state if isinstance(workspace_state, dict) else {})
        if not info["locked"] and (
            framework_asset.get("framework_to_script_locked")
            or framework_asset.get("script_locked")
            or framework_asset.get("asset_locked")
        ):
            info["locked"] = True
            info["locked_at"] = str(framework_asset.get("script_locked_at") or framework_asset.get("locked_at") or "").strip()
        return info

    def _framework_snapshot_script_lock_info(snapshot: dict | None) -> dict:
        if not isinstance(snapshot, dict):
            return {"locked": False, "locked_at": ""}
        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        workspace_state = artifacts.get("framework_to_script_state") if isinstance(artifacts.get("framework_to_script_state"), dict) else {}
        info = _framework_to_script_lock_info_from_state(workspace_state)
        if not info["locked"] and (
            snapshot.get("asset_locked")
            or snapshot.get("framework_to_script_locked")
            or artifacts.get("asset_locked")
        ):
            info["locked"] = True
            info["locked_at"] = str(snapshot.get("locked_at") or artifacts.get("locked_at") or "").strip()
        return info

    def _framework_to_script_locked_error(framework_asset: dict | None):
        lock_info = _framework_asset_script_lock_info(framework_asset)
        if not lock_info.get("locked"):
            return None
        locked_at = str(lock_info.get("locked_at") or "").strip()
        suffix = f"（锁定时间：{locked_at}）" if locked_at else ""
        return _json_error(f"剧本已锁定保存，不能回退或重新运行 08-12 阶段{suffix}。", status=423)

    def _clear_framework_stage_runs_for_asset(user_id: int, asset_id: str) -> None:
        asset = str(asset_id or "").strip()
        if not asset:
            return
        with framework_stage_runs_lock:
            keys = [
                key
                for key in framework_stage_runs.keys()
                if int(key[0]) == int(user_id)
                and str(key[1]) == asset
                and str(key[2]) in {"08", "09", "10", "11", "12"}
            ]
            for key in keys:
                run_id = str((framework_stage_runs.get(key) or {}).get("run_id") or "")
                framework_stage_runs.pop(key, None)
                if run_id:
                    framework_stage_runs_by_id.pop(run_id, None)

    def _cleanup_framework_to_script_debug_files(asset_id: str, framework_asset: dict | None) -> dict:
        deleted_files = 0
        deleted_dirs = 0
        errors: list[str] = []

        def _delete_file(path: Path) -> None:
            nonlocal deleted_files
            try:
                if path.is_file():
                    path.unlink()
                    deleted_files += 1
            except Exception as exc:
                errors.append(f"{path}: {exc}")

        def _delete_dir(path: Path) -> None:
            nonlocal deleted_dirs
            try:
                if path.exists() and path.is_dir():
                    shutil.rmtree(path)
                    deleted_dirs += 1
            except Exception as exc:
                errors.append(f"{path}: {exc}")

        title = _stage12_debug_project_title({}, framework_asset)
        safe_title = _stage12_debug_safe_name(title)
        if safe_title:
            _delete_dir(_writable_root() / "cache" / safe_title / "framework_to_script")

        raw_dir = _writable_root() / "cache" / "raw_tencent_debug"
        if raw_dir.exists() and raw_dir.is_dir():
            asset_token = f"asset{str(asset_id or '').strip()}"
            for item in raw_dir.iterdir():
                if not item.is_file():
                    continue
                name = item.name
                if asset_token and asset_token in name:
                    _delete_file(item)
                elif re.match(r"stage(?:08|09|10|11|12)_raw_response\.json$", name):
                    _delete_file(item)

        return {
            "deleted_files": deleted_files,
            "deleted_dirs": deleted_dirs,
            "errors": errors[:10],
        }

    def _framework_stage_run_key(user_id: int, asset_id: str, stage: str) -> tuple[int, str, str]:
        return (int(user_id), str(asset_id or "").strip(), str(stage or "").strip())

    def _framework_stage_run_public(record: dict | None) -> dict:
        if not isinstance(record, dict):
            return {}
        public_keys = (
            "run_id",
            "asset_id",
            "stage",
            "status",
            "current_sub_stage",
            "progress_text",
            "started_at",
            "updated_at",
            "completed_at",
            "latest_result_preview",
            "latest_partial_result",
            "latest_error",
            "raw_debug_paths",
            "history_debug_paths",
        )
        return {
            key: copy.deepcopy(record.get(key))
            for key in public_keys
            if key in record
        }

    def _framework_stage_run_snapshot(
        *,
        run_id: str | None = None,
        user_id: int | None = None,
        asset_id: str = "",
        stage: str = "",
    ) -> dict:
        with framework_stage_runs_lock:
            record = None
            if run_id:
                key = framework_stage_runs_by_id.get(str(run_id))
                record = framework_stage_runs.get(key) if key else None
            elif user_id is not None:
                key = _framework_stage_run_key(user_id, asset_id, stage)
                record = framework_stage_runs.get(key)
            return _framework_stage_run_public(record)

    def _merge_framework_stage_run_paths(record: dict, key: str, values) -> None:
        if not values:
            return
        current = record.get(key)
        if not isinstance(current, list):
            current = []
        incoming = values if isinstance(values, list) else [values]
        seen = {str(item) for item in current}
        for item in incoming:
            text = str(item or "").strip()
            if text and text not in seen:
                current.append(text)
                seen.add(text)
        record[key] = current[-80:]

    def _begin_or_get_framework_stage_run(
        *,
        user_id: int,
        asset_id: str,
        stage: str,
        current_sub_stage: str = "",
        progress_text: str = "",
        latest_result_preview=None,
        latest_partial_result=None,
        retain_completed: bool = True,
    ) -> tuple[dict, bool]:
        key = _framework_stage_run_key(user_id, asset_id, stage)
        now = _now_iso()
        if not key[1] or not key[2]:
            run_id = uuid.uuid4().hex
            return _framework_stage_run_public(
                {
                    "run_id": run_id,
                    "user_id": int(user_id),
                    "asset_id": key[1],
                    "stage": key[2],
                    "status": "running",
                    "current_sub_stage": current_sub_stage,
                    "progress_text": progress_text,
                    "started_at": now,
                    "updated_at": now,
                    "completed_at": "",
                    "latest_result_preview": latest_result_preview,
                    "latest_partial_result": latest_partial_result,
                    "latest_error": "",
                    "raw_debug_paths": [],
                    "history_debug_paths": [],
                    "retain_completed": retain_completed,
                    "worker_token": uuid.uuid4().hex,
                }
            ), True
        with framework_stage_runs_lock:
            existing = framework_stage_runs.get(key)
            if isinstance(existing, dict) and existing.get("status") in {"pending", "running"}:
                return _framework_stage_run_public(existing), False
            if isinstance(existing, dict):
                old_run_id = str(existing.get("run_id") or "")
                if old_run_id:
                    framework_stage_runs_by_id.pop(old_run_id, None)
            run_id = uuid.uuid4().hex
            record = {
                "run_id": run_id,
                "user_id": int(user_id),
                "asset_id": key[1],
                "stage": key[2],
                "status": "pending",
                "current_sub_stage": current_sub_stage,
                "progress_text": progress_text,
                "started_at": now,
                "updated_at": now,
                "completed_at": "",
                "latest_result_preview": latest_result_preview,
                "latest_partial_result": latest_partial_result,
                "latest_error": "",
                "raw_debug_paths": [],
                "history_debug_paths": [],
                "retain_completed": retain_completed,
                "worker_token": uuid.uuid4().hex,
            }
            framework_stage_runs[key] = record
            framework_stage_runs_by_id[run_id] = key
            return _framework_stage_run_public(record), True

    def _framework_stage_run_private(run_id: str) -> dict:
        with framework_stage_runs_lock:
            key = framework_stage_runs_by_id.get(str(run_id or ""))
            record = framework_stage_runs.get(key) if key else None
            return copy.deepcopy(record) if isinstance(record, dict) else {}

    def _framework_stage_worker_allowed(
        *,
        run_id: str,
        worker_token: str,
        user_id: int,
        asset_id: str,
        stage: str,
    ) -> bool:
        key = _framework_stage_run_key(user_id, asset_id, stage)
        with framework_stage_runs_lock:
            record = framework_stage_runs.get(key)
            if not isinstance(record, dict):
                return False
            return (
                str(record.get("run_id") or "") == str(run_id or "")
                and str(record.get("worker_token") or "") == str(worker_token or "")
                and record.get("status") in {"pending", "running"}
            )

    def _update_framework_stage_run(
        *,
        run_id: str,
        status: str | None = None,
        current_sub_stage: str | None = None,
        progress_text: str | None = None,
        latest_result_preview=None,
        latest_partial_result=None,
        latest_error: str | None = None,
        raw_debug_path: str = "",
        history_debug_path: str = "",
        raw_debug_paths=None,
        history_debug_paths=None,
    ) -> dict:
        now = _now_iso()
        with framework_stage_runs_lock:
            key = framework_stage_runs_by_id.get(str(run_id or ""))
            record = framework_stage_runs.get(key) if key else None
            if not isinstance(record, dict):
                return {}
            if status is not None:
                record["status"] = status
            if current_sub_stage is not None:
                record["current_sub_stage"] = current_sub_stage
            if progress_text is not None:
                record["progress_text"] = progress_text
            if latest_result_preview is not None:
                record["latest_result_preview"] = _strip_raw_workflow_fields(copy.deepcopy(latest_result_preview))
            if latest_partial_result is not None:
                next_partial = _strip_raw_workflow_fields(copy.deepcopy(latest_partial_result))
                previous_partial = record.get("latest_partial_result") if isinstance(record.get("latest_partial_result"), dict) else {}
                if isinstance(next_partial, dict) and isinstance(previous_partial, dict):
                    for progress_key in ("expected_batch_starts", "completed_batch_starts", "remaining_batch_starts"):
                        if progress_key not in next_partial and progress_key in previous_partial:
                            next_partial[progress_key] = copy.deepcopy(previous_partial.get(progress_key))
                record["latest_partial_result"] = next_partial
            if latest_error is not None:
                record["latest_error"] = str(latest_error or "")
            _merge_framework_stage_run_paths(record, "raw_debug_paths", raw_debug_path)
            _merge_framework_stage_run_paths(record, "history_debug_paths", history_debug_path)
            _merge_framework_stage_run_paths(record, "raw_debug_paths", raw_debug_paths)
            _merge_framework_stage_run_paths(record, "history_debug_paths", history_debug_paths)
            record["updated_at"] = now
            return _framework_stage_run_public(record)

    def _finish_framework_stage_run(
        *,
        run_id: str,
        status: str,
        progress_text: str = "",
        latest_result_preview=None,
        latest_partial_result=None,
        latest_error: str = "",
        forget: bool = False,
    ) -> dict:
        now = _now_iso()
        with framework_stage_runs_lock:
            key = framework_stage_runs_by_id.get(str(run_id or ""))
            record = framework_stage_runs.get(key) if key else None
            if not isinstance(record, dict):
                return {}
            record["status"] = status
            record["updated_at"] = now
            record["completed_at"] = now
            if progress_text:
                record["progress_text"] = progress_text
            if latest_result_preview is not None:
                record["latest_result_preview"] = _strip_raw_workflow_fields(copy.deepcopy(latest_result_preview))
            if latest_partial_result is not None:
                record["latest_partial_result"] = _strip_raw_workflow_fields(copy.deepcopy(latest_partial_result))
            if latest_error:
                record["latest_error"] = str(latest_error)
            public = _framework_stage_run_public(record)
            if forget or not record.get("retain_completed", True):
                framework_stage_runs.pop(key, None)
                framework_stage_runs_by_id.pop(str(run_id or ""), None)
            return public

    def _list_framework_stage_runs(
        *,
        user_id: int,
        asset_id: str = "",
        stage: str = "",
        include_completed: bool = True,
    ) -> list[dict]:
        asset = str(asset_id or "").strip()
        stage_text = str(stage or "").strip()
        with framework_stage_runs_lock:
            records = []
            for (record_user_id, record_asset_id, record_stage), record in framework_stage_runs.items():
                if int(record_user_id) != int(user_id):
                    continue
                if asset and str(record_asset_id) != asset:
                    continue
                if stage_text and str(record_stage) != stage_text:
                    continue
                if not include_completed and record.get("status") not in {"pending", "running"}:
                    continue
                records.append(_framework_stage_run_public(record))
        records.sort(key=lambda item: str(item.get("updated_at") or item.get("started_at") or ""), reverse=True)
        return records

    def _try_begin_framework_stage(user_id: int, asset_id: str, stage: str) -> bool:
        key = _framework_stage_run_key(user_id, asset_id, stage)
        if not key[1] or not key[2]:
            return True
        _, created = _begin_or_get_framework_stage_run(
            user_id=user_id,
            asset_id=asset_id,
            stage=stage,
            current_sub_stage=f"stage{stage}",
            progress_text=f"{stage} 正在运行",
            retain_completed=False,
        )
        return created

    def _end_framework_stage(user_id: int, asset_id: str, stage: str) -> None:
        key = _framework_stage_run_key(user_id, asset_id, stage)
        with framework_stage_runs_lock:
            record = framework_stage_runs.get(key)
            run_id = str((record or {}).get("run_id") or "")
        if run_id:
            _finish_framework_stage_run(run_id=run_id, status="succeeded", forget=True)

    def _save_framework_to_script_stage(
        *,
        user_id: int,
        asset_id: str,
        stage_key: str,
        output: dict,
    ) -> None:
        try:
            project_id = int(str(asset_id or "").strip())
        except Exception:
            return
        if project_id <= 0 or not isinstance(output, dict):
            return
        snapshot = task_manager.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot or str(snapshot.get("asset_kind") or "").strip() != "framework_planner":
            return
        now = _now_iso()
        clean_output = _strip_raw_workflow_fields(copy.deepcopy(output))
        framework_artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        script_snapshot = task_manager.get_framework_to_script_asset_for_source(
            project_id,
            user_id=user_id,
            public_view=False,
        )
        script_artifacts = script_snapshot.get("artifacts") if isinstance((script_snapshot or {}).get("artifacts"), dict) else {}
        workspace_state = script_artifacts.get("framework_to_script_state")
        if not isinstance(workspace_state, dict):
            workspace_state = framework_artifacts.get("framework_to_script_state")
        if not isinstance(workspace_state, dict):
            workspace_state = {"scriptStages": {}}
        else:
            workspace_state = copy.deepcopy(workspace_state)
        script_stages = workspace_state.get("scriptStages")
        if not isinstance(script_stages, dict):
            script_stages = {}
        cascade = {
            "stage08": ("stage09", "stage10", "stage11", "stage12"),
            "stage09": ("stage10", "stage11", "stage12"),
            "stage10": ("stage11", "stage12"),
            "stage11": ("stage12",),
        }
        for downstream_stage in cascade.get(str(stage_key), ()):
            script_stages.pop(downstream_stage, None)
        stage_output_aliases = {
            "stage08": {
                "framework_scene_dictionary": clean_output,
                "sceneDictionary": clean_output.get("sceneDictionary"),
                "scriptWorldRulesDigest": clean_output.get("scriptWorldRulesDigest"),
            },
            "stage09": {
                "framework_appearanceMapping": clean_output,
                "appearanceMapping": clean_output.get("appearanceMapping"),
            },
            "stage10": {
                "framework_enriched_episode_plan": clean_output,
                "allEnrichedEpisodePlan": clean_output.get("allEnrichedEpisodePlan") or clean_output.get("enrichedEpisodePlan"),
                "allEnrichedEpisodePlanText": clean_output.get("allEnrichedEpisodePlanText") or clean_output.get("enrichedEpisodePlanText"),
                "batchEnrichedEpisodePlan": clean_output.get("batchEnrichedEpisodePlan")
                or clean_output.get("allEnrichedEpisodePlan")
                or clean_output.get("enrichedEpisodePlan"),
            },
            "stage11": {
                "framework_causal_conflict_plan": clean_output,
                "batchCausalConflictPlan": clean_output.get("batchCausalConflictPlan"),
                "conflictMemory": clean_output.get("conflictMemory"),
            },
            "stage12": {
                "framework_script_text": clean_output,
                "batchScriptText": clean_output.get("batchScriptText"),
                "scriptMemory": clean_output.get("scriptMemory"),
            },
        }
        clean_output["updated_at"] = now
        script_stages[str(stage_key)] = clean_output
        stage_outputs = workspace_state.get("stageOutputs")
        if not isinstance(stage_outputs, dict):
            stage_outputs = {}
        for key, value in stage_output_aliases.get(str(stage_key), {}).items():
            if _framework_value_present(value):
                stage_outputs[key] = _strip_raw_workflow_fields(copy.deepcopy(value))
        for downstream_stage in cascade.get(str(stage_key), ()):
            output_key = downstream_stage.replace("stage", "")
            for key in tuple(stage_outputs.keys()):
                if output_key in str(key):
                    stage_outputs.pop(key, None)
        stages_state = workspace_state.get("stages")
        if not isinstance(stages_state, dict):
            stages_state = {}
        stage_number = str(stage_key).replace("stage", "")
        stage_is_complete = True
        if str(stage_key) in {"stage11", "stage12"}:
            stage10_output = script_stages.get("stage10") if isinstance(script_stages.get("stage10"), dict) else {}
            full_episode_plan = (
                stage10_output.get("allEnrichedEpisodePlan")
                or stage10_output.get("enrichedEpisodePlan")
                or stage_outputs.get("allEnrichedEpisodePlan")
                or []
            )
            expected_batch_starts = {
                str(number)
                for number in range(1, len(full_episode_plan) + 1, 5)
            }
            output_batches = clean_output.get("batches") if isinstance(clean_output.get("batches"), dict) else {}
            completed_batch_starts = {
                str(key)
                for key, batch in output_batches.items()
                if isinstance(batch, dict)
                and str(
                    batch.get("batchPipelineStatus")
                    or batch.get("batch_pipeline_status")
                    or "complete"
                ).strip().lower() == "complete"
            }
            stage_is_complete = bool(expected_batch_starts) and expected_batch_starts.issubset(completed_batch_starts)
        stages_state[stage_number] = {
            "status": "completed" if stage_is_complete else "partial",
            "stage_key": str(stage_key),
            "updated_at": now,
        }
        for downstream_stage in cascade.get(str(stage_key), ()):
            stages_state[str(downstream_stage).replace("stage", "")] = {
                "status": "pending",
                "stage_key": str(downstream_stage),
                "updated_at": now,
            }
        completed_stages = workspace_state.get("completedStages")
        if not isinstance(completed_stages, list):
            completed_stages = []
        completed_set = {str(item) for item in completed_stages}
        if stage_is_complete:
            completed_set.add(stage_number)
        else:
            completed_set.discard(stage_number)
        for downstream_stage in cascade.get(str(stage_key), ()):
            completed_set.discard(str(downstream_stage).replace("stage", ""))
        workspace_state["completedStages"] = sorted(completed_set, key=lambda item: int(item) if item.isdigit() else 999)
        workspace_state["scriptStages"] = script_stages
        workspace_state["stageOutputs"] = stage_outputs
        workspace_state["stages"] = stages_state
        workspace_state["framework_asset_id"] = str(asset_id)
        workspace_state["project_id"] = project_id
        workspace_state["updated_at"] = now
        final_text = ""
        if str(stage_key) == "stage12":
            try:
                staged_snapshot = copy.deepcopy(snapshot)
                staged_snapshot.setdefault("artifacts", {})["framework_to_script_state"] = workspace_state
                export_asset = _framework_asset_payload(staged_snapshot, include_detail=True)
                export_asset["framework_to_script_state"] = _strip_raw_workflow_fields(copy.deepcopy(workspace_state))
                export_asset["scriptStages"] = _strip_raw_workflow_fields(copy.deepcopy(script_stages))
                export_asset["stage_outputs"] = _strip_raw_workflow_fields(copy.deepcopy(stage_outputs))
                final_text = _framework_to_script_txt(export_asset)
            except Exception:
                logger.exception("framework-to-script final text projection failed project_id=%s", project_id)
                final_text = ""
        try:
            task_manager.save_framework_to_script_asset(
                user_id=user_id,
                framework_snapshot=snapshot,
                workspace_state=workspace_state,
                final_text=final_text,
            )
        except Exception:
            logger.exception("framework-to-script script asset persist failed project_id=%s stage=%s", project_id, stage_key)

    def _inject_framework_asset(data: dict, user_id: int) -> tuple[dict, dict | None]:
        asset_id = str(data.get("framework_asset_id") or data.get("asset_id") or "").strip()
        if not asset_id:
            return data, None
        asset = _load_framework_asset_for_user(asset_id, user_id)
        if not asset:
            raise ValueError("框架资产不存在、无权访问，或尚未生成 07 最终策划包。")
        merged = dict(data)
        package = asset.get("framework_plan_package") if isinstance(asset.get("framework_plan_package"), dict) else {}
        stage_outputs = asset.get("stage_outputs") if isinstance(asset.get("stage_outputs"), dict) else {}
        merged["framework_asset_id"] = asset.get("asset_id")
        merged["source_framework_project_id"] = asset.get("project_id")
        merged["framework_plan_package"] = package
        package_stage_prompts = _stage_prompt_lookup_from_mapping(package.get("stage_prompts")) if isinstance(package, dict) else {}
        if not isinstance(merged.get("preference_snapshot"), dict) or not merged.get("preference_snapshot"):
            merged["preference_snapshot"] = (
                asset.get("preference_snapshot")
                if isinstance(asset.get("preference_snapshot"), dict)
                else {}
            )
        merged["stage_prompts"] = _merge_stage_prompts_non_empty(
            package_stage_prompts,
            asset.get("stage_prompts") if isinstance(asset.get("stage_prompts"), dict) else {},
            merged.get("stage_prompts") if isinstance(merged.get("stage_prompts"), dict) else {},
        )
        prompt_preferences = merged.get("prompt_preferences") if isinstance(merged.get("prompt_preferences"), dict) else {}
        prompt_preferences = dict(prompt_preferences)
        prompt_preferences["stage_prompts"] = _merge_stage_prompts_non_empty(
            merged.get("stage_prompts"),
            prompt_preferences.get("stage_prompts"),
        )
        merged["prompt_preferences"] = prompt_preferences
        logger.info(
            "framework-to-script asset preference handoff: asset_id=%s non_empty_keys=%s",
            asset.get("asset_id"),
            [key for key, value in merged["stage_prompts"].items() if _coerce_prompt_text(value)],
        )
        for key, value in stage_outputs.items():
            merged.setdefault(key, value)
        return merged, asset

    def _framework_script_stage_cache(framework_asset: dict | None, stage_key: str) -> dict:
        if not isinstance(framework_asset, dict):
            return {}
        stages = framework_asset.get("scriptStages")
        if not isinstance(stages, dict):
            state = framework_asset.get("framework_to_script_state")
            stages = state.get("scriptStages") if isinstance(state, dict) else {}
        if not isinstance(stages, dict):
            return {}
        cached = stages.get(stage_key)
        if isinstance(cached, dict) and cached:
            return cached
        stage_outputs = framework_asset.get("stage_outputs") if isinstance(framework_asset.get("stage_outputs"), dict) else {}
        if stage_key == "stage10" and isinstance(stage_outputs, dict):
            framework_output = stage_outputs.get("framework_enriched_episode_plan")
            if isinstance(framework_output, dict) and framework_output:
                return framework_output
            plan = (
                stage_outputs.get("allEnrichedEpisodePlan")
                or stage_outputs.get("batchEnrichedEpisodePlan")
                or stage_outputs.get("all_enriched_episode_plan")
                or []
            )
            text = stage_outputs.get("allEnrichedEpisodePlanText") or stage_outputs.get("all_enriched_episode_plan_text") or ""
            if _framework_value_present(plan) or _framework_value_present(text):
                return {
                    "allEnrichedEpisodePlan": plan,
                    "enrichedEpisodePlan": plan,
                    "batchEnrichedEpisodePlan": plan,
                    "allEnrichedEpisodePlanText": text,
                    "enrichedEpisodePlanText": text,
                }
        return {}

    def _positive_int(value, default: int) -> int:
        try:
            number = int(value)
            return number if number > 0 else default
        except Exception:
            return default

    def _first_present(mapping, *keys, default=None):
        if not isinstance(mapping, dict):
            return default
        for key in keys:
            if key in mapping and mapping.get(key) is not None:
                return mapping.get(key)
        return default

    def _get_bool_alias(mapping, *keys, default=None):
        value = _first_present(mapping, *keys, default=default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y", "passed", "pass", "通过", "是"}:
                return True
            if normalized in {"false", "0", "no", "n", "failed", "fail", "不通过", "否"}:
                return False
        return default if value is None else bool(value)

    def _get_list_alias(mapping, *keys):
        value = _first_present(mapping, *keys, default=[])
        return value if isinstance(value, list) else []

    def _get_dict_alias(mapping, *keys):
        value = _first_present(mapping, *keys, default={})
        return value if isinstance(value, dict) else {}

    def _merge_aliases(base_vars, aliases):
        if not isinstance(base_vars, dict) or not isinstance(aliases, dict):
            return base_vars
        for source_key, alias_keys in aliases.items():
            if source_key not in base_vars:
                continue
            for alias_key in alias_keys:
                base_vars.setdefault(alias_key, base_vars[source_key])
        return base_vars

    def _unwrap_dict_alias(mapping, *keys):
        value = _get_dict_alias(mapping, *keys)
        for key in keys:
            if isinstance(value, dict) and isinstance(value.get(key), dict):
                return value.get(key), True
        return value, False

    def _normalize_dict_output_alias(mapping, *keys):
        value = _first_present(mapping, *keys, default=None)
        unwrapped = False
        if value is None and isinstance(mapping, (dict, list, str)):
            value = mapping

        def _parse_json_like(candidate):
            if isinstance(candidate, str):
                text = candidate.strip()
                if text.startswith("```"):
                    text = text.strip("`").strip()
                    if text.lower().startswith("json"):
                        text = text[4:].strip()
                try:
                    return json.loads(text), ""
                except Exception as exc:
                    return candidate, f"string JSON parse failed: {exc}"
            return candidate, ""

        def _looks_like_batch_causal_conflict_plan(candidate):
            if not isinstance(candidate, dict):
                return False
            episodes = candidate.get("episodes")
            if not isinstance(episodes, list) or not episodes:
                return False
            return (
                isinstance(candidate.get("batch_meta"), dict)
                or isinstance(candidate.get("global_conflict_engine"), dict)
                or "episode_title" in episodes[0]
                or "scene_cause_chain" in episodes[0]
            )

        def _is_target_candidate(candidate):
            if not isinstance(candidate, dict):
                return False

            normalized_keys = {str(key) for key in keys}

            if (
                "batchCausalConflictPlan" in normalized_keys
                or "batch_causal_conflict_plan" in normalized_keys
            ):
                return _looks_like_batch_causal_conflict_plan(candidate)

            return False

        def _iter_nested_candidates(candidate):
            if not isinstance(candidate, dict):
                return

            # ????????????
            # {"batchCausalConflictPlan": {...}}
            for key in keys:
                if key in candidate:
                    yield candidate.get(key)

            # ?? 腾讯工作流/code ??????????
            # {"data":{"conflicts":{"batchCausalConflictPlan": {...}}}}
            # {"conflicts":{"batchCausalConflictPlan": {...}}}
            wrapper_keys = (
                "data",
                "conflicts",
                "result",
                "output",
                "outputs",
                "response",
                "responseData",
                "newVariables",
                "variables",
                "payload",
                "review",
                "rewrite",
                "conflictreview",
                "conflictrewrite",
                "conflictsReview",
                "conflictsRewrite",
            )
            for key in wrapper_keys:
                if key in candidate:
                    yield candidate.get(key)

            # ??????? value??????????
            for nested_key, nested_value in candidate.items():
                if nested_key in keys or nested_key in wrapper_keys:
                    continue
                if isinstance(nested_value, (dict, list, str)):
                    yield nested_value

        def _find_target_candidate(candidate, *, depth=0, seen=None):
            if seen is None:
                seen = set()
            if depth > 12:
                return None, False, ""

            candidate, parse_error = _parse_json_like(candidate)
            if parse_error and not isinstance(candidate, (dict, list)):
                return None, False, parse_error

            marker = id(candidate)
            if marker in seen:
                return None, False, ""
            seen.add(marker)

            if _is_target_candidate(candidate):
                return candidate, depth > 0, ""

            if isinstance(candidate, dict):
                for nested in _iter_nested_candidates(candidate):
                    found, nested_unwrapped, nested_error = _find_target_candidate(
                        nested,
                        depth=depth + 1,
                        seen=seen,
                    )
                    if isinstance(found, dict):
                        return found, True, ""
                return None, False, ""

            if isinstance(candidate, list):
                for item in candidate:
                    found, nested_unwrapped, nested_error = _find_target_candidate(
                        item,
                        depth=depth + 1,
                        seen=seen,
                    )
                    if isinstance(found, dict):
                        return found, True, ""
                return None, False, ""

            return None, False, ""

        value, parse_error = _parse_json_like(value)
        if parse_error and not isinstance(value, (dict, list)):
            return {}, unwrapped, parse_error

        found, found_unwrapped, found_error = _find_target_candidate(value)
        if isinstance(found, dict) and found:
            return found, bool(found_unwrapped), ""

        # ??????? stage11 ????????????????
        for key in keys:
            if isinstance(value, dict) and isinstance(value.get(key), dict):
                value = value.get(key)
                unwrapped = True
                break
            if isinstance(value, dict) and isinstance(value.get(key), str):
                parsed, parse_error = _parse_json_like(value.get(key))
                if parse_error and not isinstance(parsed, dict):
                    return {}, unwrapped, f"wrapped string JSON parse failed: {parse_error}"
                value = parsed
                unwrapped = True
                break

        if isinstance(value, dict) and value:
            return value, unwrapped, ""
        if value is None:
            return {}, unwrapped, "missing output alias"
        return {}, unwrapped, f"output alias is {type(value).__name__}, expected object"

    def _validate_stage11_causal_conflict_plan(plan, *, start_episode: int, end_episode: int) -> list[str]:
        if not isinstance(plan, dict) or not plan:
            return ["batchCausalConflictPlan must be a non-empty JSON object"]
        issues = []
        required_root = ("batch_meta", "global_conflict_engine", "episodes")
        missing_root = [key for key in required_root if key not in plan]
        if missing_root:
            issues.append(f"batchCausalConflictPlan missing root fields: {', '.join(missing_root)}")
        episodes = plan.get("episodes")
        if not isinstance(episodes, list) or not episodes:
            issues.append("batchCausalConflictPlan.episodes must be a non-empty array")
            return issues
        expected_episodes = set(range(int(start_episode), int(end_episode) + 1))
        actual_episodes = set()
        required_episode_fields = (
            "episode",
            "episode_title",
            "active_characters",
            "scene_refs",
            "carry_in",
            "why_now",
            "character_motivation",
            "emotional_precondition",
            "scene_cause_chain",
            "non_conflict_moment",
            "natural_transition",
            "opening_image",
            "opening_action",
            "current_goal",
            "core_obstacle",
            "episode_state_change",
            "ending_hook",
            "dialogue_strategy",
        )
        if len(episodes) != len(expected_episodes) and len(episodes) > 5:
            issues.append("batchCausalConflictPlan.episodes count must match the current batch or be no more than 5")
        for index, episode_payload in enumerate(episodes, start=1):
            if not isinstance(episode_payload, dict):
                issues.append(f"batchCausalConflictPlan.episodes[{index}] must be an object")
                continue
            episode_no = _positive_int(episode_payload.get("episode"), 0)
            if episode_no > 0:
                actual_episodes.add(episode_no)
            missing_fields = [key for key in required_episode_fields if key not in episode_payload]
            if missing_fields:
                issues.append(
                    f"batchCausalConflictPlan.episodes[{index}] missing fields: {', '.join(missing_fields)}"
                )
        missing_episodes = sorted(expected_episodes - actual_episodes)
        if missing_episodes:
            issues.append(f"batchCausalConflictPlan missing episodes: {missing_episodes}")
        return issues

    def _framework_batch_from_plan(plan: list, requested_start=None, completed_starts=None) -> tuple[int, int, list]:
        completed = {int(item) for item in (completed_starts or []) if str(item).strip().isdigit()}
        episode_numbers = []
        for index, item in enumerate(plan, start=1):
            if not isinstance(item, dict):
                continue
            episode_numbers.append(
                _positive_int(
                    item.get("episode")
                    or item.get("episodeNumber")
                    or item.get("episode_number")
                    or item.get("ep")
                    or index,
                    index,
                )
            )
        if requested_start:
            start_episode = _positive_int(requested_start, 1)
        else:
            starts = sorted({((episode - 1) // 5) * 5 + 1 for episode in episode_numbers if episode > 0})
            start_episode = next((start for start in starts if start not in completed), starts[0] if starts else 1)
        end_episode = start_episode + 4
        batch = []
        batch_episode_numbers = []
        for index, item in enumerate(plan, start=1):
            if not isinstance(item, dict):
                continue
            episode = _positive_int(
                item.get("episode")
                or item.get("episodeNumber")
                or item.get("episode_number")
                or item.get("ep")
                or index,
                index,
            )
            if start_episode <= episode <= end_episode:
                batch.append(item)
                batch_episode_numbers.append(episode)
        if batch:
            end_episode = max(batch_episode_numbers)
        return start_episode, end_episode, batch

    def _sorted_numeric_batch_keys(batches: dict) -> list[str]:
        if not isinstance(batches, dict):
            return []
        return sorted(
            [str(key) for key in batches.keys() if str(key).strip().isdigit()],
            key=lambda item: int(item),
        )

    def _txt_label(key) -> str:
        return readable_label(key)

    def _txt_scalar(value) -> str:
        return readable_scalar(value)

    def _txt_readable(value, indent: int = 0) -> str:
        return readable_text(value, indent)

    def _framework_script_text_from_batches(stage12: dict) -> str:
        if not isinstance(stage12, dict):
            return ""
        batches = stage12.get("batches") if isinstance(stage12.get("batches"), dict) else {}
        parts = []
        for key in _sorted_numeric_batch_keys(batches):
            batch = batches.get(key)
            if not isinstance(batch, dict):
                continue
            text = _first_present(batch, "batchScriptText", "batch_script_text", default="")
            if str(text or "").strip():
                parts.append(str(text).replace("\r\n", "\n").replace("\r", "\n").strip())
        if parts:
            return "\n\n".join(parts)
        return str(_first_present(stage12, "batchScriptText", "batch_script_text", default="") or "").strip()


    # FRAMEWORK_TO_SCRIPT_EXPORT_PRUNE_NOISE_V1
    def _clean_framework_to_script_export_text(text: str) -> str:
        """Remove internal workflow notes from exported TXT/DOCX content."""
        lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        result = []
        skip_indent = None

        for line in lines:
            stripped = line.strip()

            # Remove internal adaptation-guide meta text:
            # "文本：本次整体改编指引..."
            if (
                stripped.startswith("\u6587\u672c\uff1a\u672c\u6b21\u6574\u4f53\u6539\u7f16\u6307\u5f15")
                or stripped.startswith("\u6587\u672c:\u672c\u6b21\u6574\u4f53\u6539\u7f16\u6307\u5f15")
            ):
                continue

            # Remove source-trace blocks under scenes:
            # "来源依据：" and all child lines until the next same/lower-indent field.
            if (
                stripped.startswith("\u6765\u6e90\u4f9d\u636e\uff1a")
                or stripped.startswith("\u6765\u6e90\u4f9d\u636e:")
            ):
                skip_indent = len(line) - len(line.lstrip(" "))
                continue

            if skip_indent is not None:
                if not stripped:
                    continue
                indent = len(line) - len(line.lstrip(" "))
                if indent > skip_indent:
                    continue
                skip_indent = None

            result.append(line.rstrip())

        cleaned = "\n".join(result).strip()
        while "\n\n\n" in cleaned:
            cleaned = cleaned.replace("\n\n\n", "\n\n")
        return cleaned + "\n"

    def _framework_to_script_txt(asset: dict) -> str:
        package = asset.get("framework_plan_package") if isinstance(asset.get("framework_plan_package"), dict) else {}
        stage_outputs = asset.get("stage_outputs") if isinstance(asset.get("stage_outputs"), dict) else {}
        workspace_state = asset.get("framework_to_script_state") if isinstance(asset.get("framework_to_script_state"), dict) else {}
        script_stages = asset.get("scriptStages") if isinstance(asset.get("scriptStages"), dict) else {}
        if not script_stages and isinstance(workspace_state.get("scriptStages"), dict):
            script_stages = workspace_state.get("scriptStages")
        stage03 = _get_dict_alias(stage_outputs, "stage03")
        stage06 = _get_dict_alias(stage_outputs, "stage06")
        stage07 = _get_dict_alias(stage_outputs, "stage07")
        stage08 = _get_dict_alias(script_stages, "stage08")
        stage12 = _get_dict_alias(script_stages, "stage12")

        stage07_package = _get_dict_alias(stage07, "frameworkPlanPackage", "framework_plan_package")
        story = (
            _first_present(package, "story_synopsis", "synopsis", "summary", default=None)
            or _first_present(stage07_package, "story_synopsis", "synopsis", "summary", default=None)
            or _first_present(stage06, "overallAdaptationGuide", "overall_adaptation_guide", default=None)
            or _first_present(stage_outputs, "overallAdaptationGuide", "overall_adaptation_guide", "adaptation_guide", default=None)
            or "暂无"
        )
        characters = (
            _first_present(package, "characterPlan", "character_plan", default=None)
            or _first_present(stage03, "characterPlan", "character_plan", default=None)
            or _first_present(stage_outputs, "characterPlan", "character_plan", default=None)
            or "暂无"
        )
        scenes = (
            _first_present(stage08, "sceneDictionary", "scene_dictionary", default=None)
            or _first_present(package, "sceneDictionary", "scene_dictionary", "coreScenes", "core_scenes", default=None)
            or _first_present(stage_outputs, "sceneDictionary", "scene_dictionary", "coreScenes", "core_scenes", default=None)
            or "暂无"
        )
        script_text = _txt_readable(_framework_script_text_from_batches(stage12) or "暂无")
        title = _txt_scalar(asset.get("title") or package.get("title") or package.get("project_title") or "未命名框架剧本")
        export_text = "\n\n".join(
            [
                f"《{title}》",
                "一、故事梗概\n" + _txt_readable(story),
                "二、人物小传\n" + _txt_readable(characters),
                "三、核心场景\n" + _txt_readable(scenes),
                "四、剧本正文\n" + script_text,
            ]
        ) + "\n"
        return _clean_framework_to_script_export_text(export_text)

    def _framework_review_needs_rewrite(review: dict) -> bool:
        if not isinstance(review, dict):
            return False
        if bool(review.get("rewriteRequired") or review.get("rewrite_required")):
            return True
        if (
            review.get("reviewPassed") is False
            or review.get("passed") is False
            or review.get("approved") is False
        ):
            return True
        return False

    def _request_auth_token() -> str:
        auth_header = str(request.headers.get("Authorization") or "").strip()
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()
        url_token = str(
            request.args.get("auth_token")
            or request.form.get("auth_token")
            or ""
        ).strip()
        if url_token:
            return url_token
        return str(session.get("auth_token") or "").strip()

    def _current_user():
        token = _request_auth_token()
        return auth_store.get_user_by_token(token)

    def _current_auth_token() -> str:
        return _request_auth_token()

    def _safe_next_url(value: str | None) -> str:
        text = str(value or "").strip()
        if not text or not text.startswith("/") or text.startswith("//"):
            return ""
        return text

    def _login_user(user) -> str:
        session.clear()
        token = auth_store.create_session_token(user.id)
        session["auth_token"] = token
        session.permanent = True
        return token

    def _logout_user() -> None:
        session.pop("auth_token", None)

    def _login_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not _current_user():
                if request.path.startswith("/api/"):
                    return _json_error("请先登录", status=401)
                next_url = request.full_path.rstrip("?")
                return redirect(url_for("login_page", next=next_url))
            return view(*args, **kwargs)

        return wrapper

    def _require_user_id() -> int:
        user = _current_user()
        if not user:
            raise ValueError("请先登录")
        return int(user.id)

    def _resolve_spec_path(data: dict) -> str:
        custom = str(data.get("workflow_spec_path") or "").strip()
        return custom or str(app.config["WORKFLOW_SPEC_PATH"])

    def _coerce_string_list(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            text = str(item.get("id") if isinstance(item, dict) else item or "").strip()
            if text and text not in result:
                result.append(text)
        return result

    def _coerce_tag_list(value) -> list[dict]:
        if not isinstance(value, list):
            return []
        result: list[dict] = []
        for item in value:
            if isinstance(item, dict):
                tag = {
                    "id": str(item.get("id") or "").strip(),
                    "name": str(item.get("name") or "").strip(),
                    "category": str(item.get("category") or "").strip(),
                    "builtin": bool(item.get("builtin")),
                    "group": str(item.get("group") or "").strip(),
                    "group_label": str(item.get("group_label") or "").strip(),
                    "source": str(item.get("source") or "").strip(),
                    "type": str(item.get("type") or "").strip(),
                    "is_default": bool(item.get("is_default")) if "is_default" in item else bool(item.get("builtin")),
                    "is_user_editable": item.get("is_user_editable") is not False,
                    "description": str(item.get("description") or "").strip(),
                    "prompt_text": str(item.get("prompt_text") or "").strip(),
                    "stage_prompts": _coerce_stage_prompts(item.get("stage_prompts")),
                }
                if tag["id"] or tag["name"]:
                    result.append(tag)
            else:
                text = str(item or "").strip()
                if text:
                    result.append({"id": text, "name": text, "category": "", "builtin": False, "description": "", "prompt_text": "", "stage_prompts": _coerce_stage_prompts({})})
        return result

    _USER_KNOWLEDGE_STAGE_LABELS = {
        "basic": "01 原文提取偏好",
        "worldview": "02 世界观偏好",
        "character": "03 人设偏好",
        "beat": "04 节拍规划偏好",
        "storylines": "05 人物故事线偏好",
        "guide": "06 改编指引偏好",
        "package": "07 框架校验偏好",
        "scene": "08 场景字典偏好",
        "appearance": "09 角色外观匹配场景偏好",
        "episode": "10 分集细化偏好",
        "conflict": "11 开头冲突钩子偏好",
        "script_text": "12 正文写作偏好",
    }

    def _coerce_stage_prompts(value) -> dict:
        source = value if isinstance(value, dict) else {}
        return {
            key: _coerce_prompt_text(source.get(key))
            for key in _USER_KNOWLEDGE_STAGE_LABELS
        }

    def _merge_stage_prompts_non_empty(*sources) -> dict:
        result = _coerce_stage_prompts({})
        for source in sources:
            normalized = _stage_prompt_lookup_from_mapping(source) if isinstance(source, dict) else _coerce_stage_prompts({})
            for key, value in normalized.items():
                text = _coerce_prompt_text(value)
                if text:
                    result[key] = text
        return result

    def _coerce_prompt_text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value).strip()

    def _stage_prompt_lookup_from_mapping(value) -> dict:
        source = value if isinstance(value, dict) else {}
        result = {}
        stage_numbers = {
            "basic": "01",
            "worldview": "02",
            "character": "03",
            "beat": "04",
            "storylines": "05",
            "guide": "06",
            "package": "07",
            "scene": "08",
            "appearance": "09",
            "episode": "10",
            "conflict": "11",
            "script_text": "12",
        }
        for stage_key, label in _USER_KNOWLEDGE_STAGE_LABELS.items():
            stage_no = stage_numbers.get(stage_key, "")
            result[stage_key] = _coerce_prompt_text(
                source.get(stage_key)
                or source.get(stage_no)
                or source.get(label)
            )
        return result

    def _stage_prompts_from_snapshot(snapshot) -> dict:
        if not isinstance(snapshot, dict):
            return {}
        result = {}
        for key in ("stage_prompts", "stagePrompts", "stage_preferences", "stagePreferences"):
            prompts = snapshot.get(key)
            if isinstance(prompts, dict):
                normalized = _stage_prompt_lookup_from_mapping(prompts)
                for stage_key, text in normalized.items():
                    if text and not result.get(stage_key):
                        result[stage_key] = text
        return result

    def _stage_prompts_from_payload(data: dict) -> dict:
        if not isinstance(data, dict):
            return {}
        sources = [
            data.get("stage_prompts"),
            data.get("stagePrompts"),
            data.get("stagePreferences"),
            data.get("stage_preferences"),
            data.get("user_knowledge_stage_prompts"),
        ]
        prompt_preferences = data.get("prompt_preferences") if isinstance(data.get("prompt_preferences"), dict) else {}
        sources.append(prompt_preferences.get("stage_prompts"))
        framework_plan_package = data.get("framework_plan_package") or data.get("frameworkPlanPackage")
        if isinstance(framework_plan_package, dict):
            sources.append(framework_plan_package.get("stage_prompts"))
            sources.append(framework_plan_package.get("user_knowledge_stage_prompts"))
            package_prompt_preferences = framework_plan_package.get("prompt_preferences")
            if isinstance(package_prompt_preferences, dict):
                sources.append(package_prompt_preferences.get("stage_prompts"))
        return _merge_stage_prompts_non_empty(*sources)

    def _framework_asset_stage_prompts(framework_asset: dict | None) -> dict:
        if not isinstance(framework_asset, dict):
            return {}
        direct = _stage_prompt_lookup_from_mapping(framework_asset.get("stage_prompts"))
        if any(direct.values()):
            return direct
        return _stage_prompts_from_snapshot(framework_asset.get("preference_snapshot"))

    def _framework_context_vars(data: dict, framework_plan_package: dict | None) -> dict:
        package = framework_plan_package if isinstance(framework_plan_package, dict) else {}
        worldview_plan = (
            data.get("worldview_plan")
            or data.get("worldviewPlan")
            or package.get("worldview_plan")
            or package.get("worldviewPlan")
            or {}
        )
        character_plan = (
            data.get("character_plan")
            or data.get("characterPlan")
            or package.get("character_plan")
            or package.get("characterPlan")
            or {}
        )
        beat_checkpoint_timeline = (
            data.get("beat_checkpoint_timeline")
            or data.get("beatCheckpointTimeline")
            or package.get("beat_checkpoint_timeline")
            or package.get("beatCheckpointTimeline")
            or []
        )
        character_storylines = (
            data.get("character_storylines")
            or data.get("characterStorylines")
            or package.get("character_storylines")
            or package.get("characterStorylines")
            or []
        )
        alias_rules = (
            data.get("character_alias_naming_rules")
            or data.get("characterAliasNamingRules")
            or package.get("character_alias_naming_rules")
            or package.get("characterAliasNamingRules")
            or ""
        )
        core_scene_input = (
            data.get("core_scene_input")
            or data.get("coreSceneInput")
            or package.get("core_scene_input")
            or package.get("coreSceneInput")
            or ""
        )
        return {
            "frameworkPlanPackage": package,
            "framework_plan_package": package,
            "worldviewPlan": worldview_plan,
            "worldview_plan": worldview_plan,
            "characterPlan": character_plan,
            "character_plan": character_plan,
            "beatCheckpointTimeline": beat_checkpoint_timeline,
            "beat_checkpoint_timeline": beat_checkpoint_timeline,
            "characterStorylines": character_storylines,
            "character_storylines": character_storylines,
            "characterAliasNamingRules": alias_rules,
            "character_alias_naming_rules": alias_rules,
            "coreSceneInput": core_scene_input,
            "core_scene_input": core_scene_input,
        }

    def _framework_planner_stage_key(stage) -> str:
        return {
            "01": "basic",
            "02": "worldview",
            "03": "character",
            "04": "beat",
            "05": "storylines",
            "06": "guide",
            "07": "package",
        }.get(str(stage or "").zfill(2), "")

    def _user_knowledge_stage_key(stage) -> str:
        return {
            "01": "basic",
            "02": "worldview",
            "03": "character",
            "04": "beat",
            "05": "storylines",
            "06": "guide",
            "07": "package",
            "08": "scene",
            "09": "appearance",
            "10": "episode",
            "11": "conflict",
            "12": "script_text",
        }.get(str(stage or "").zfill(2), "")

    def _stage_preference_from_tags(stage: str, selected_tags: list[dict]) -> tuple[str, int]:
        stage_key = _user_knowledge_stage_key(stage)
        if not stage_key:
            return "", 0
        sections = []
        for tag in selected_tags or []:
            prompts = tag.get("stage_prompts") if isinstance(tag.get("stage_prompts"), dict) else {}
            text = _coerce_prompt_text(prompts.get(stage_key))
            if not text:
                continue
            name = str(tag.get("name") or tag.get("id") or "").strip()
            label = _USER_KNOWLEDGE_STAGE_LABELS.get(stage_key, stage_key)
            sections.append(f"【智慧库标签偏好：{name} / {label}】\n{text}")
        return "\n\n".join(sections), len(sections)

    def _resolve_stage_preference(data: dict, stage: str, framework_asset: dict | None = None) -> tuple[str, str]:
        stage_no = str(stage or "").zfill(2)
        stage_key = _user_knowledge_stage_key(stage_no)
        request_stage_prompts = _stage_prompts_from_payload(data)
        preference = _coerce_prompt_text(request_stage_prompts.get(stage_key))
        if preference:
            return preference, "request_stage_prompts"

        asset_stage_prompts = _framework_asset_stage_prompts(framework_asset)
        preference = _coerce_prompt_text(asset_stage_prompts.get(stage_key))
        if preference:
            return preference, "framework_asset_stage_prompts"

        snapshot = data.get("preference_snapshot") if isinstance(data.get("preference_snapshot"), dict) else {}
        if not snapshot and isinstance(data.get("preferenceSnapshot"), dict):
            snapshot = data.get("preferenceSnapshot")
        if not snapshot and isinstance(data.get("metadata"), dict):
            metadata_snapshot = data["metadata"].get("preference_snapshot") or data["metadata"].get("preferenceSnapshot")
            snapshot = metadata_snapshot if isinstance(metadata_snapshot, dict) else {}
        snapshot_stage_prompts = _stage_prompts_from_snapshot(snapshot)
        preference = _coerce_prompt_text(snapshot_stage_prompts.get(stage_key))
        if preference:
            return preference, "source_framework_stage_prompts"

        for key in (
            "stagePreference",
            "stage_preference",
            "stage_preference_prompt",
            "user_stage_preference_prompt",
            "userPreference",
            "user_preferences",
            "userPreferences",
            "userRequirements",
            "user_constraints",
        ):
            if key in data:
                preference = _coerce_prompt_text(data.get(key))
                if preference:
                    return preference, "request_legacy_preference"

        preference = _coerce_prompt_text(data.get("prompt_text"))
        if preference:
            return preference, "prompt_text_fallback"
        return "", "none"

    def _inject_snapshot_stage_preference(
        variables: dict,
        data: dict,
        stage: str,
        *,
        framework_asset: dict | None,
        workflow_stage: str | None = None,
    ) -> dict:
        preference, source = _resolve_stage_preference(data, stage, framework_asset)
        stage_no = str(stage or "").zfill(2)
        stage_key = _user_knowledge_stage_key(stage_no)
        stage_prompt_key = stage_prompt_key_for(workflow_stage or stage_no) or stage_key
        workflow_preference_keys = tuple(
            FRAMEWORK_TO_SCRIPT_STAGE_PREFS.get(workflow_stage or stage_no, {}).get("workflow_keys")
            or preference_keys_for(workflow_stage or stage_no)
        )
        asset_id = str(
            (framework_asset or {}).get("asset_id")
            or data.get("framework_asset_id")
            or data.get("asset_id")
            or ""
        ).strip()
        inject_stage_preference(variables, preference, workflow_preference_keys)
        logger.info(
            "framework_to_script stage preference injected",
            extra={
                "stage": workflow_stage or stage_no,
                "stage_prompt_key": stage_prompt_key,
                "has_stage_preference": bool(preference),
                "preference_length": len(preference or ""),
                "workflow_preference_keys": list(workflow_preference_keys),
                "preference_source": source,
                "asset_id": asset_id,
            },
        )
        return variables

    def _resolve_saved_preference_tags(user_id: int | str, selected_ids: list[str]) -> list[dict]:
        if not selected_ids:
            try:
                selected_ids = _coerce_string_list(
                    user_knowledge_store.get_preferences(user_id).get("selected_preference_tag_ids")
                )
            except Exception:
                selected_ids = []
        if not selected_ids:
            return []
        tags_by_id = {str(tag.get("id") or ""): tag for tag in user_knowledge_store.list_tags(user_id, enabled_only=True)}
        result = []
        for tag_id in selected_ids:
            tag = tags_by_id.get(str(tag_id))
            if tag:
                result.append(tag)
        return result

    def _inject_stage_preference_variables(variables: dict, data: dict, stage: str, *, user_id: int | str) -> dict:
        selected_tags = _coerce_tag_list(data.get("selected_preference_tags"))
        selected_ids = _coerce_string_list(data.get("selected_preference_tag_ids"))
        if selected_tags and not selected_ids:
            selected_ids = [tag["id"] for tag in selected_tags if tag.get("id")]
        if not selected_tags:
            selected_tags = _resolve_saved_preference_tags(user_id, selected_ids)
            if not selected_ids:
                selected_ids = [tag["id"] for tag in selected_tags if tag.get("id")]
        stage_key = _user_knowledge_stage_key(stage)
        stage_label = _USER_KNOWLEDGE_STAGE_LABELS.get(stage_key, "")
        stage_preference_prompt, tags_with_preference_count = _stage_preference_from_tags(stage, selected_tags)
        if stage_preference_prompt:
            source_names = "、".join(str(tag.get("name") or tag.get("id") or "").strip() for tag in selected_tags if tag.get("id"))
            header = f"【当前阶段智慧库偏好：{stage_label}】\n来源标签：{source_names}\n"
            stage_preference_prompt = header + stage_preference_prompt
            for key in (
                "stagePreference",
                "stage_preference",
                "stage_preference_prompt",
                "user_stage_preference_prompt",
                "user_preferences",
                "userPreferences",
                "userRequirements",
                "user_constraints",
            ):
                if key not in variables or not _coerce_prompt_text(variables.get(key)):
                    variables[key] = stage_preference_prompt
                elif key in {"user_preferences", "userPreferences", "userRequirements", "user_constraints"}:
                    variables[key] = f"{_coerce_prompt_text(variables.get(key))}\n\n{stage_preference_prompt}"
        logger.info(
            "stage preference injection: stage_key=%s stage_name=%s preference_source=智慧库标签 preference_stage_key=%s preference_stage_label=%s selected_tag_count=%s tags_with_stage_preference_count=%s has_stage_preference=%s preference_length=%s",
            str(stage or "").zfill(2),
            stage_label,
            stage_key,
            stage_label,
            len(selected_tags or selected_ids),
            tags_with_preference_count,
            bool(stage_preference_prompt),
            len(stage_preference_prompt),
        )
        return variables

    def _attach_user_knowledge_payload(payload: dict, data: dict, stage: str | None = None) -> None:
        selected_tags = _coerce_tag_list(data.get("selected_preference_tags"))
        selected_ids = _coerce_string_list(data.get("selected_preference_tag_ids"))
        if not selected_ids and selected_tags:
            selected_ids = [tag["id"] for tag in selected_tags if tag.get("id")]
        if not selected_tags and selected_ids:
            current_user = _current_user()
            selected_tags = _resolve_saved_preference_tags(current_user.id if current_user else "", selected_ids)
        payload["selected_preference_tags"] = selected_tags
        payload["selected_preference_tag_ids"] = selected_ids
        payload["user_preference_prompt"] = _coerce_prompt_text(data.get("user_preference_prompt"))
        payload["user_knowledge_tag_prompt"] = _coerce_prompt_text(data.get("user_knowledge_tag_prompt"))
        prompt_preferences = data.get("prompt_preferences") if isinstance(data.get("prompt_preferences"), dict) else {}
        prompt_preferences = dict(prompt_preferences)
        tag_stage_prompts = {}
        if selected_tags:
            for key in _USER_KNOWLEDGE_STAGE_LABELS:
                sections = []
                for tag in selected_tags:
                    prompts = tag.get("stage_prompts") if isinstance(tag.get("stage_prompts"), dict) else {}
                    text = _coerce_prompt_text(prompts.get(key))
                    if not text:
                        continue
                    name = str(tag.get("name") or tag.get("id") or "").strip()
                    label = _USER_KNOWLEDGE_STAGE_LABELS.get(key, key)
                    sections.append(f"【智慧库标签偏好：{name} / {label}】\n{text}")
                if sections:
                    tag_stage_prompts[key] = "\n\n".join(sections)
        merged_stage_prompts = _merge_stage_prompts_non_empty(
            prompt_preferences.get("stage_prompts"),
            data.get("stage_prompts"),
            data.get("stagePrompts"),
            data.get("stage_preferences"),
            data.get("stagePreferences"),
            data.get("user_knowledge_stage_prompts"),
            tag_stage_prompts,
        )
        prompt_preferences["stage_prompts"] = merged_stage_prompts
        payload["user_knowledge_stage_prompts"] = merged_stage_prompts
        payload["prompt_preferences"] = prompt_preferences
        stage_key = _framework_planner_stage_key(stage)
        current_stage_prompt = payload["user_knowledge_stage_prompts"].get(stage_key, "") if stage_key else ""
        if current_stage_prompt:
            payload["stage_preference_prompt"] = current_stage_prompt
            payload["user_stage_preference_prompt"] = current_stage_prompt
            payload["user_preference_prompt"] = current_stage_prompt
        if any(key in data for key in ("selected_preference_tags", "selected_preference_tag_ids", "user_preference_prompt", "user_knowledge_tag_prompt", "user_knowledge_stage_prompts", "prompt_preferences")):
            selected_prompt, tags_with_preference_count = _stage_preference_from_tags(stage or "", selected_tags)
            logger.info(
                "workflow user knowledge fields: stage_key=%s stage_name=%s preference_source=智慧库标签 preference_stage_key=%s preference_stage_label=%s selected_tag_count=%s tags_with_stage_preference_count=%s has_stage_preference=%s preference_length=%s",
                str(stage or "").zfill(2) if stage else "",
                _USER_KNOWLEDGE_STAGE_LABELS.get(_user_knowledge_stage_key(stage), ""),
                stage_key,
                _USER_KNOWLEDGE_STAGE_LABELS.get(stage_key, ""),
                len(selected_tags or selected_ids),
                tags_with_preference_count,
                bool(current_stage_prompt or selected_prompt),
                len(current_stage_prompt or selected_prompt),
            )

    @app.get("/")
    def index():
        if _current_user():
            return redirect(url_for("workspace_page", auth_token=_current_auth_token()))
        return render_template(
            "home.html",
            current_user=_current_user(),
            current_auth_token=_current_auth_token(),
            community_assets=task_manager.list_public_assets(),
        )

    @app.get("/workspace")
    def workspace_page():
        return render_template(
            "index.html",
            current_user=_current_user(),
            current_auth_token=_current_auth_token(),
        )

    @app.get("/framework-planner")
    @_login_required
    def framework_planner_page():
        return render_template(
            "framework_planner.html",
            current_user=_current_user(),
            current_auth_token=_current_auth_token(),
            framework_backend_ready=framework_planner_backend_ready(),
            framework_planner_storage_key=FRAMEWORK_PLANNER_STORAGE_KEY,
        )

    @app.get("/community/<int:project_id>")
    def community_detail_page(project_id: int):
        asset = task_manager.get_public_asset(project_id)
        if not asset:
            return render_template(
                "community_detail.html",
                current_user=_current_user(),
                current_auth_token=_current_auth_token(),
                asset=None,
            ), 404
        return render_template(
            "community_detail.html",
            current_user=_current_user(),
            current_auth_token=_current_auth_token(),
            asset=asset,
        )

    @app.get("/login")
    def login_page():
        next_url = _safe_next_url(request.args.get("next"))
        if _current_user():
            return redirect(next_url or url_for("workspace_page", auth_token=_current_auth_token()))
        return render_template("login.html", next_url=next_url)

    @app.post("/login")
    def login_submit():
        next_url = _safe_next_url(request.form.get("next") or request.args.get("next"))
        username = str(request.form.get("username") or "").strip()
        password = str(request.form.get("password") or "")
        user = auth_store.authenticate(username, password)
        if not user:
            return render_template(
                "login.html",
                error="用户名或密码错误",
                username=username,
                next_url=next_url,
            ), 400
        auth_token = _login_user(user)
        return redirect(next_url or url_for("workspace_page", auth_token=auth_token))

    @app.get("/register")
    def register_page():
        if _current_user():
            return redirect(url_for("workspace_page", auth_token=_current_auth_token()))
        return render_template("register.html")

    @app.post("/register")
    def register_submit():
        username = str(request.form.get("username") or "").strip()
        password = str(request.form.get("password") or "")
        confirm_password = str(request.form.get("confirm_password") or "")
        if password != confirm_password:
            return render_template(
                "register.html",
                error="两次输入的密码不一致",
                username=username,
            ), 400
        try:
            user = auth_store.register_user(username, password)
        except ValueError as exc:
            return render_template(
                "register.html",
                error=str(exc),
                username=username,
            ), 400
        auth_token = _login_user(user)
        return redirect(url_for("workspace_page", auth_token=auth_token))

    @app.get("/logout")
    def logout():
        _logout_user()
        return redirect(url_for("login_page"))

    @app.get("/api/me")
    @_login_required
    def current_user_api():
        user = _current_user()
        return _json_ok(user={"id": user.id, "username": user.username})

    @app.patch("/api/me/username")
    @_login_required
    def update_username_api():
        data = request.get_json(silent=True) or {}
        try:
            user = auth_store.update_username(
                _require_user_id(),
                str(data.get("username") or ""),
            )
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return _json_ok(user={"id": user.id, "username": user.username})

    @app.patch("/api/me/password")
    @_login_required
    def update_password_api():
        data = request.get_json(silent=True) or {}
        new_password = str(data.get("new_password") or "")
        confirm_password = str(data.get("confirm_password") or "")
        if new_password != confirm_password:
            return _json_error("两次输入的新密码不一致", status=400)
        try:
            auth_store.update_password(
                _require_user_id(),
                str(data.get("current_password") or ""),
                new_password,
            )
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return _json_ok(message="密码已修改")

    @app.get("/api/models")
    @_login_required
    def list_models():
        spec_path = str(request.args.get("workflow_spec_path") or app.config["WORKFLOW_SPEC_PATH"])
        try:
            models = task_manager.list_model_options(spec_path)
        except Exception as exc:
            return _json_error(str(exc), status=500, fallback="模型列表加载失败，请稍后重试。")
        return _json_ok(models=models, workflow_spec_path=spec_path)

    @app.get("/api/tools")
    @_login_required
    def list_tools():
        try:
            tools = list_simple_tools()
            for tool in tools:
                if str(tool.get("tool_id") or "") != "hot_review":
                    continue
                fields = tool.get("fields") or []
                for field in fields:
                    if str(field.get("name") or "") == "review_text":
                        field["name"] = "text"
        except Exception as exc:
            return _json_error(str(exc), status=500, fallback="辅助工具列表加载失败，请稍后重试。")
        return _json_ok(ok=True, tools=tools)

    def _run_tool_request(tool_key: str, data: dict):
        try:
            result = run_simple_tool(tool_key, data)
        except ToolExecutionError as exc:
            return jsonify(
                {
                    "success": False,
                    "ok": False,
                    "tool_id": exc.tool_id or tool_key,
                    "message": str(exc),
                    "debug": exc.debug,
                }
            ), int(exc.status_code or 400)
        except WorkflowTransientError as exc:
            return jsonify(
                {
                    "success": False,
                    "ok": False,
                    "tool_id": tool_key,
                    "message": "工具上游暂时不可用，请稍后重试。",
                    "debug": {
                        "stage_name": exc.stage_name,
                        "status_code": exc.status_code,
                        "url": exc.url,
                    },
                }
            ), 503
        except Exception as exc:
            return _json_error(str(exc), status=500, fallback="工具执行失败，请稍后重试。")
        flattened = dict(result)
        asset_saved = False
        saved_asset = None
        asset_save_error = ""
        if str(flattened.get("text") or "").strip():
            try:
                saved_asset = task_manager.save_auxiliary_asset(
                    user_id=_require_user_id(),
                    tool_key=tool_key,
                    request_payload=data if isinstance(data, dict) else {},
                    result=result,
                )
                asset_saved = True
            except Exception as exc:
                asset_save_error = _sanitize_error_message(
                    str(exc),
                    status=500,
                    fallback="结果已生成，但写入用户资产失败，请稍后重试。",
                )
        flattened["asset_saved"] = asset_saved
        if saved_asset is not None:
            flattened["saved_asset"] = saved_asset
        if asset_save_error:
            flattened["asset_save_error"] = asset_save_error
        result["asset_saved"] = asset_saved
        if saved_asset is not None:
            result["saved_asset"] = saved_asset
        if asset_save_error:
            result["asset_save_error"] = asset_save_error
        ok = bool(flattened.pop("ok", True))
        return _json_ok(ok=ok, result=result, **flattened)

    @app.post("/api/tools/<tool_key>/run")
    @_login_required
    def run_tool(tool_key: str):
        data = request.get_json(silent=True) or {}
        return _run_tool_request(tool_key, data)

    @app.post("/api/tools/new-framework")
    @_login_required
    def run_new_framework_tool():
        data = request.get_json(silent=True) or {}
        return _run_tool_request("new_framework", data)

    @app.get("/api/user-knowledge/tags")
    @_login_required
    def list_user_knowledge_tags_api():
        try:
            return _json_ok(tags=user_knowledge_store.list_tags(_require_user_id(), enabled_only=True))
        except Exception as exc:
            logger.exception("user knowledge tags list failed")
            return _json_error(str(exc), status=500, fallback="智慧库标签加载失败，请稍后重试。")

    @app.post("/api/user-knowledge/tags")
    @_login_required
    def create_user_knowledge_tag_api():
        data = request.get_json(silent=True) or {}
        try:
            tag = user_knowledge_store.create_tag(_require_user_id(), data if isinstance(data, dict) else {})
            return _json_ok(tag=tag)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        except Exception as exc:
            logger.exception("user knowledge tag create failed")
            return _json_error(str(exc), status=500, fallback="智慧库标签创建失败，请稍后重试。")

    @app.patch("/api/user-knowledge/tags/<tag_id>")
    @_login_required
    def update_user_knowledge_tag_api(tag_id: str):
        data = request.get_json(silent=True) or {}
        try:
            tag = user_knowledge_store.update_tag(_require_user_id(), tag_id, data if isinstance(data, dict) else {})
            return _json_ok(tag=tag)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        except Exception as exc:
            logger.exception("user knowledge tag update failed")
            return _json_error(str(exc), status=500, fallback="智慧库标签更新失败，请稍后重试。")

    @app.delete("/api/user-knowledge/tags/<tag_id>")
    @_login_required
    def delete_user_knowledge_tag_api(tag_id: str):
        try:
            tag = user_knowledge_store.delete_tag(_require_user_id(), tag_id)
            return _json_ok(tag=tag)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        except Exception as exc:
            logger.exception("user knowledge tag delete failed")
            return _json_error(str(exc), status=500, fallback="智慧库标签删除失败，请稍后重试。")

    @app.get("/api/user-knowledge/preferences")
    @_login_required
    def get_user_knowledge_preferences_api():
        try:
            return _json_ok(preferences=user_knowledge_store.get_preferences(_require_user_id()))
        except Exception as exc:
            logger.exception("user knowledge preferences get failed")
            return _json_error(str(exc), status=500, fallback="用户偏好加载失败，请稍后重试。")

    @app.put("/api/user-knowledge/preferences")
    @_login_required
    def save_user_knowledge_preferences_api():
        data = request.get_json(silent=True) or {}
        try:
            preferences = user_knowledge_store.save_preferences(_require_user_id(), data if isinstance(data, dict) else {})
            return _json_ok(preferences=preferences)
        except Exception as exc:
            logger.exception("user knowledge preferences save failed")
            return _json_error(str(exc), status=500, fallback="用户偏好保存失败，请稍后重试。")

    @app.post("/api/user-knowledge/apply-tags")
    @_login_required
    def apply_user_knowledge_tags_api():
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            data = {}
        try:
            result = user_knowledge_store.apply_tags(
                _require_user_id(),
                data.get("selected_tag_ids") if "selected_tag_ids" in data else data.get("selected_preference_tag_ids"),
                existing_user_preference=data.get("existing_user_preference") or data.get("user_preference_prompt") or "",
            )
            return _json_ok(**result)
        except Exception as exc:
            logger.exception("user knowledge apply tags failed")
            return _json_error(str(exc), status=500, fallback="智慧库标签应用失败，请稍后重试。")

    def _framework_planner_error(
        stage: str,
        message: str,
        *,
        status: int = 400,
        detail: dict | None = None,
    ):
        return jsonify(
            {
                "ok": False,
                "stage": stage,
                "error": message,
                "detail": detail or {},
            }
        ), status

    def _positive_int_or_none(value) -> int | None:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    def _framework_basic_config_from_state(existing_state: dict | None) -> dict:
        if not isinstance(existing_state, dict):
            return {}
        direct = existing_state.get("basic_config")
        if isinstance(direct, dict):
            return direct
        framework_state = _framework_state_from_project(existing_state)
        nested = framework_state.get("basic_config") if isinstance(framework_state, dict) else {}
        if isinstance(nested, dict):
            return nested
        input_payload = existing_state.get("input_payload") if isinstance(existing_state.get("input_payload"), dict) else {}
        nested = input_payload.get("basic_config") if isinstance(input_payload, dict) else {}
        if isinstance(nested, dict):
            return nested
        return input_payload if isinstance(input_payload, dict) else {}

    def _normalize_framework_episode_config(data: dict, existing_state: dict | None = None) -> dict:
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON object。")
        basic_config = data.get("basic_config") if isinstance(data.get("basic_config"), dict) else {}
        if basic_config is not data.get("basic_config"):
            basic_config = {}
            data["basic_config"] = basic_config
        existing_basic = _framework_basic_config_from_state(existing_state)
        source_brief = data.get("source_brief") if isinstance(data.get("source_brief"), dict) else {}
        framework_package = data.get("framework_plan_package") if isinstance(data.get("framework_plan_package"), dict) else {}
        package_basic = framework_package.get("basic_config") if isinstance(framework_package.get("basic_config"), dict) else {}
        package_source_brief = framework_package.get("source_brief") if isinstance(framework_package.get("source_brief"), dict) else {}

        def _episode_count_from_container(container: dict | None) -> int | None:
            if not isinstance(container, dict):
                return None
            for key in (
                "episodes_number",
                "episodesNumber",
                "total_episodes",
                "totalEpisodes",
                "episodes_per_season",
                "episodesPerSeason",
                "episode_count",
                "episodeCount",
            ):
                value = _positive_int_or_none(container.get(key))
                if value is not None:
                    return value
            for key in ("episode_count_guard", "episodeCountGuard", "season_plan", "seasonPlan", "basic_config", "basicConfig"):
                value = _episode_count_from_container(container.get(key) if isinstance(container.get(key), dict) else None)
                if value is not None:
                    return value
            season = _positive_int_or_none(container.get("season_count") or container.get("seasonCount"))
            episodes = _positive_int_or_none(container.get("episodes_per_season") or container.get("episodesPerSeason"))
            if season is not None and episodes is not None:
                return season * episodes
            return None

        season_count = 1
        episodes_per_season = (
            _positive_int_or_none(basic_config.get("episodes_number"))
            or _positive_int_or_none(data.get("episodes_number"))
            or _positive_int_or_none(existing_basic.get("episodes_number"))
            or _positive_int_or_none(basic_config.get("total_episodes"))
            or _positive_int_or_none(data.get("total_episodes"))
            or _positive_int_or_none(existing_basic.get("total_episodes"))
            or _episode_count_from_container(source_brief)
            or _episode_count_from_container(package_basic)
            or _episode_count_from_container(package_source_brief)
            or _episode_count_from_container(framework_package)
            or _positive_int_or_none(basic_config.get("episodes_per_season"))
            or _positive_int_or_none(data.get("episodes_per_season"))
            or _positive_int_or_none(existing_basic.get("episodes_per_season"))
        )
        missing = []
        if episodes_per_season is None:
            missing.append("episodes_per_season")
        if missing:
            raise ValueError(f"04 阶段缺少集数配置：{', '.join(missing)}。请先填写基础信息里的总集数。")

        total_episodes = int(season_count) * int(episodes_per_season)
        guard = {
            "season_count": int(season_count),
            "episodes_per_season": int(episodes_per_season),
            "total_episodes": total_episodes,
        }
        basic_config.update(guard)
        basic_config["episodes_number"] = total_episodes
        data.update(guard)
        data["episodes_number"] = total_episodes
        data["episode_count_guard"] = copy.deepcopy(guard)
        basic_config["episode_count_guard"] = copy.deepcopy(guard)
        return data

    def _load_framework_planner_existing_state(data: dict, user_id: int) -> dict | None:
        asset_state = data.get("asset_state") if isinstance(data.get("asset_state"), dict) else {}
        raw_project_id = data.get("project_id") or data.get("asset_id") or asset_state.get("project_id")
        project_id = _positive_int_or_none(raw_project_id)
        if not project_id:
            return None
        return task_manager.get_project_snapshot(project_id, user_id=user_id, public_view=False)

    def _owned_framework_project_id(raw_project_id, user_id: int, *, allow_unsaved: bool = False) -> int | None:
        value = str(raw_project_id or "").strip()
        normalized = value.lower()
        unsaved_sentinels = {"", "unsaved", "draft", "null", "undefined"}
        is_user_unsaved = bool(re.fullmatch(r"user-\d+-unsaved", normalized))
        if normalized in unsaved_sentinels or is_user_unsaved:
            if allow_unsaved:
                return None
            raise ValueError("缺少有效的框架资产 ID")
        try:
            project_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("框架资产 ID 格式不正确") from exc
        snapshot = task_manager.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot or str(snapshot.get("asset_kind") or "").strip() != "framework_planner":
            raise ValueError("框架资产不存在或无权访问")
        return project_id

    def _stage04_episode_range_detail(stage_payload: dict, total_episodes: int) -> dict:
        data = stage_payload.get("data") if isinstance(stage_payload.get("data"), dict) else {}
        timeline = data.get("beat_checkpoint_timeline")
        if not isinstance(timeline, list):
            timeline = []
        bad_ranges = []
        max_detected = 0
        for index, item in enumerate(timeline, start=1):
            if not isinstance(item, dict):
                continue
            episode_range = str(item.get("episode_range") or "").strip()
            detected_numbers = [int(value) for value in re.findall(r"\d+", episode_range)]
            if not detected_numbers:
                continue
            local_max = max(detected_numbers)
            max_detected = max(max_detected, local_max)
            if local_max > total_episodes:
                bad_ranges.append(
                    {
                        "beat_no": item.get("beat_no") or index,
                        "episode_range": episode_range,
                        "max_episode": local_max,
                    }
                )
        return {
            "total_episodes": total_episodes,
            "max_detected_episode": max_detected,
            "bad_episode_ranges": bad_ranges,
        }

    @app.get("/api/framework-planner/diagnostics/workflow")
    @_login_required
    def framework_planner_workflow_diagnostics_api():
        stage = str(request.args.get("stage") or "05").zfill(2)
        try:
            payload = framework_planner_workflow_diagnostics(stage)
        except ValueError as exc:
            return _framework_planner_error(
                str(stage).zfill(2),
                str(exc),
                status=400,
                detail={"message": str(exc)},
            )
        except FrameworkPlannerStageError as exc:
            return _framework_planner_error(
                exc.stage,
                str(exc),
                status=exc.status_code,
                detail=exc.detail,
            )
        return jsonify(payload)

    @app.post("/api/framework-planner/stage/04/score")
    @_login_required
    def run_framework_planner_stage_score():
        data = request.get_json(silent=True) or {}
        project_id = data.get("project_id") if isinstance(data, dict) else None
        try:
            user_id = _require_user_id()
            _owned_framework_project_id(project_id, user_id, allow_unsaved=True)
            payload = run_framework_planner_score(data)
            payload["history"] = save_framework_stage_history(
                project_id=project_id,
                stage="stage04_score",
                payload=data,
                output=payload.get("data") or {},
                status="success",
            )
        except ValueError as exc:
            return _framework_planner_error(
                "04",
                str(exc),
                status=400,
                detail={"message": str(exc)},
            )
        except FrameworkPlannerStageError as exc:
            write_framework_stage_exception_log(
                project_id=project_id,
                stage=exc.stage or "stage04_score",
                payload=data,
                exc_type=type(exc).__name__,
                message=str(exc),
                status_code=exc.status_code,
            )
            save_framework_stage_history(
                project_id=project_id,
                stage=exc.stage or "stage04_score",
                payload=data,
                output={},
                status="failed",
                error={"type": type(exc).__name__, "message": str(exc)},
            )
            return _framework_planner_error(
                exc.stage,
                str(exc),
                status=exc.status_code,
                detail=exc.detail,
            )
        except Exception as exc:
            write_framework_stage_exception_log(
                project_id=project_id,
                stage="stage04_score",
                payload=data,
                exc_type=type(exc).__name__,
                message=str(exc),
                status_code=500,
            )
            save_framework_stage_history(
                project_id=project_id,
                stage="stage04_score",
                payload=data,
                output={},
                status="failed",
                error={"type": type(exc).__name__, "message": str(exc)},
            )
            return _framework_planner_error(
                "04",
                "评分接口执行失败，请稍后重试。",
                status=500,
                detail={"message": str(exc)},
            )
        return jsonify(payload)

    @app.post("/api/framework-planner/stage/<stage>")
    @_login_required
    def run_framework_planner_stage_api(stage: str):
        data = request.get_json(silent=True) or {}
        project_id = data.get("project_id") if isinstance(data, dict) else None
        stage_no = str(stage).zfill(2)
        source_text = ""
        if isinstance(data, dict):
            source_text = str(data.get("source_text") or "")
            if not source_text and isinstance(data.get("basic_config"), dict):
                source_text = str(data["basic_config"].get("source_text") or "")
        logger.info(
            "framework planner api request: stage=%s payload_keys=%s source_text_length=%s",
            str(stage).zfill(2),
            sorted(data.keys()) if isinstance(data, dict) else [],
            len(source_text),
        )
        try:
            user_id = _require_user_id()
            _owned_framework_project_id(project_id, user_id, allow_unsaved=True)
            if stage_no == "01":
                missing_fields = _framework_stage01_missing_fields(data)
                if missing_fields:
                    raise ValueError(
                        "01 阶段基础信息未填写完整："
                        + "、".join(missing_fields)
                        + "。请补全后再生成。"
                    )
            if isinstance(data, dict):
                _attach_user_knowledge_payload(data, data, stage)
            if str(stage).zfill(2) == "04":
                existing_state = _load_framework_planner_existing_state(data, user_id) if isinstance(data, dict) else None
                data = _normalize_framework_episode_config(data if isinstance(data, dict) else {}, existing_state=existing_state)
                project_id = data.get("project_id")
                logger.info(
                    "framework planner stage04 episode config: project_id=%s season_count=%s episodes_per_season=%s total_episodes=%s",
                    project_id,
                    data.get("season_count"),
                    data.get("episodes_per_season"),
                    data.get("total_episodes"),
                )
                print(
                    "[framework_planner_stage04_episode_config] "
                    f"project_id={project_id} season_count={data.get('season_count')} "
                    f"episodes_per_season={data.get('episodes_per_season')} "
                    f"total_episodes={data.get('total_episodes')}",
                    flush=True,
                )
            payload = run_framework_planner_stage(stage, data)
            if str(stage).zfill(2) == "04":
                range_detail = _stage04_episode_range_detail(payload, int(data.get("total_episodes") or 0))
                if range_detail["bad_episode_ranges"]:
                    logger.warning(
                        "framework planner stage04 episode_range exceeded total_episodes: project_id=%s detail=%s",
                        project_id,
                        range_detail,
                    )
                    return _framework_planner_error(
                        "04",
                        "04 阶段输出 episode_range 超出用户输入集数，请重试或调整提示词。",
                        status=422,
                        detail=range_detail,
                    )
            payload["history"] = save_framework_stage_history(
                project_id=project_id,
                stage=str(stage).zfill(2),
                payload=data,
                output=payload.get("data") or {},
                status="success",
            )
            try:
                autosaved_asset = _autosave_framework_planner_stage(
                    user_id=user_id,
                    stage=stage,
                    request_payload=data if isinstance(data, dict) else {},
                    stage_payload=payload,
                )
                if autosaved_asset:
                    payload["autosaved"] = True
                    payload["autosaved_asset"] = _strip_raw_workflow_fields(autosaved_asset)
                    payload["project_id"] = autosaved_asset.get("project_id")
            except Exception as autosave_exc:
                logger.exception(
                    "framework planner stage autosave failed: stage=%s project_id=%s",
                    str(stage).zfill(2),
                    project_id,
                )
                payload["autosaved"] = False
                payload["autosave_error"] = str(autosave_exc)
        except ValueError as exc:
            return _framework_planner_error(
                str(stage).zfill(2),
                str(exc),
                status=400,
                detail={"message": str(exc)},
            )
        except FrameworkPlannerStageError as exc:
            write_framework_stage_exception_log(
                project_id=project_id,
                stage=exc.stage or str(stage).zfill(2),
                payload=data,
                exc_type=type(exc).__name__,
                message=str(exc),
                status_code=exc.status_code,
            )
            save_framework_stage_history(
                project_id=project_id,
                stage=exc.stage or str(stage).zfill(2),
                payload=data,
                output={},
                status="failed",
                error={"type": type(exc).__name__, "message": str(exc)},
            )
            return _framework_planner_error(
                exc.stage,
                str(exc),
                status=exc.status_code,
                detail=exc.detail,
            )
        except Exception as exc:
            logger.exception(
                "framework planner api unexpected error: stage=%s payload_keys=%s",
                str(stage).zfill(2),
                sorted(data.keys()) if isinstance(data, dict) else [],
            )
            write_framework_stage_exception_log(
                project_id=project_id,
                stage=str(stage).zfill(2),
                payload=data,
                exc_type=type(exc).__name__,
                message=str(exc),
                status_code=500,
            )
            save_framework_stage_history(
                project_id=project_id,
                stage=str(stage).zfill(2),
                payload=data,
                output={},
                status="failed",
                error={"type": type(exc).__name__, "message": str(exc)},
            )
            return _framework_planner_error(
                str(stage).zfill(2),
                "模型暂时不可用，请稍后重试。",
                status=500,
                detail={"message": str(exc)},
            )
        return jsonify(payload)

    @app.get("/api/framework-planner/history")
    @_login_required
    def list_framework_planner_history_api():
        user_id = _require_user_id()
        raw_project_id = request.args.get("project_id") or "unsaved"
        stage = request.args.get("stage") or ""
        try:
            project_id = _owned_framework_project_id(raw_project_id, user_id, allow_unsaved=True)
        except ValueError as exc:
            return _json_error(str(exc), status=404)
        if project_id is None:
            return jsonify([])
        return jsonify(list_framework_stage_history(project_id, stage or None))

    @app.get("/api/framework-planner/history/<project_id>/<filename>")
    @_login_required
    def load_framework_planner_history_api(project_id: str, filename: str):
        try:
            owned_project_id = _owned_framework_project_id(project_id, _require_user_id())
            return jsonify(load_framework_stage_history(owned_project_id, filename))
        except ValueError as exc:
            return _json_error(str(exc), status=404)
        except FrameworkPlannerStageError as exc:
            return _framework_planner_error(
                exc.stage,
                str(exc),
                status=exc.status_code,
                detail=exc.detail,
            )

    @app.post("/api/framework-planner/debug/frontend")
    @_login_required
    def framework_planner_frontend_debug_api():
        data = request.get_json(silent=True) or {}
        project_id = data.get("project_id") if isinstance(data, dict) else None
        event = str(data.get("event") or "frontend_event") if isinstance(data, dict) else "frontend_event"
        payload = data.get("payload") if isinstance(data, dict) and isinstance(data.get("payload"), dict) else {}
        detail = data.get("detail") if isinstance(data, dict) and isinstance(data.get("detail"), dict) else {}
        try:
            user_id = _require_user_id()
            owned_project_id = _owned_framework_project_id(project_id, user_id, allow_unsaved=True)
            result = write_framework_frontend_debug_event(
                project_id=owned_project_id if owned_project_id is not None else f"user-{user_id}-unsaved",
                event=event,
                payload=payload,
                detail=detail,
            )
            return jsonify(result)
        except ValueError as exc:
            return _json_error(str(exc), status=404)
        except Exception as exc:
            logger.exception("framework planner frontend debug write failed")
            return _json_error(str(exc), status=500, fallback="前端调试日志写入失败")

    @app.get("/api/projects/latest")
    @_login_required
    def latest_project():
        snapshot = task_manager.latest_project_snapshot(user_id=_require_user_id())
        return _json_ok(project=snapshot)

    @app.get("/api/projects")
    @_login_required
    def list_projects():
        projects = task_manager.list_user_projects(user_id=_require_user_id())
        return _json_ok(projects=projects)

    @app.get("/api/assets")
    @_login_required
    def list_assets():
        assets = task_manager.list_user_assets(user_id=_require_user_id())
        return _json_ok(assets=assets)

    @app.get("/api/framework-assets")
    @_login_required
    def list_framework_assets_api():
        user_id = _require_user_id()
        projects = [
            snapshot
            for snapshot in task_manager._all_project_snapshots()
            if task_manager._snapshot_belongs_to_user(snapshot, user_id)
            and str(snapshot.get("asset_kind") or "").strip() == "framework_planner"
        ]
        assets = [
            _framework_asset_payload(project, include_detail=False)
            for project in projects
        ]
        assets.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        return _json_ok(assets=_strip_raw_workflow_fields(assets))

    @app.get("/api/framework-assets/<asset_id>")
    @_login_required
    def get_framework_asset_api(asset_id: str):
        asset = _load_framework_asset_for_user(asset_id, _require_user_id())
        if not asset:
            return _json_error("框架资产不存在，或尚未完成 07 最终策划包。", status=404)
        return _json_ok(asset=_strip_raw_workflow_fields(asset))

    @app.get("/api/framework-to-script/results-sync")
    @_login_required
    def sync_framework_to_script_results_api():
        asset_id = str(
            request.args.get("framework_asset_id")
            or request.args.get("asset_id")
            or ""
        ).strip()
        if not asset_id:
            return _json_error("缺少 framework_asset_id。", status=400)
        asset = _load_framework_asset_for_user(asset_id, _require_user_id())
        if not asset:
            return _json_error("框架资产不存在，或尚未完成 07 最终策划包。", status=404)

        def _known_batch_keys(param_name: str) -> set[str]:
            raw = str(request.args.get(param_name) or "")
            return {
                item
                for item in (part.strip() for part in raw.split(","))
                if item.isdigit() and int(item) > 0
            }

        known_stage11 = _known_batch_keys("known_stage11")
        known_stage12 = _known_batch_keys("known_stage12")
        stage11 = _framework_script_stage_cache(asset, "stage11")
        stage12 = _framework_script_stage_cache(asset, "stage12")
        stage11_batches = stage11.get("batches") if isinstance(stage11.get("batches"), dict) else {}
        stage12_batches = stage12.get("batches") if isinstance(stage12.get("batches"), dict) else {}
        new_stage11_batches = {
            str(key): value
            for key, value in stage11_batches.items()
            if str(key) not in known_stage11 and isinstance(value, dict)
        }
        new_stage12_batches = {
            str(key): value
            for key, value in stage12_batches.items()
            if str(key) not in known_stage12 and isinstance(value, dict)
        }
        workspace_state = asset.get("framework_to_script_state")
        workspace_state = workspace_state if isinstance(workspace_state, dict) else {}
        payload = {
            "framework_asset_id": str(asset.get("asset_id") or asset_id),
            "stage11": {"batches": new_stage11_batches},
            "stage12": {"batches": new_stage12_batches},
            "stage11_batch_starts": _sorted_numeric_batch_keys(stage11_batches),
            "stage12_batch_starts": _sorted_numeric_batch_keys(stage12_batches),
            "script_locked": bool(
                asset.get("framework_to_script_locked")
                or asset.get("script_locked")
                or asset.get("asset_locked")
                or workspace_state.get("script_locked")
                or workspace_state.get("scriptLocked")
                or workspace_state.get("locked")
            ),
        }
        payload["changed"] = bool(new_stage11_batches or new_stage12_batches)
        return _json_ok(**_strip_raw_workflow_fields(payload))

    @app.get("/api/framework-to-script/runs")
    @_login_required
    def list_framework_to_script_runs_api():
        user_id = _require_user_id()
        asset_id = str(
            request.args.get("framework_asset_id")
            or request.args.get("asset_id")
            or ""
        ).strip()
        stage = str(request.args.get("stage") or "").strip()
        runs = _list_framework_stage_runs(user_id=user_id, asset_id=asset_id, stage=stage)
        return _json_ok(runs=runs)

    @app.get("/api/framework-to-script/runs/<run_id>")
    @_login_required
    def get_framework_to_script_run_api(run_id: str):
        user_id = _require_user_id()
        record = _framework_stage_run_private(run_id)
        if not record or int(record.get("user_id") or 0) != int(user_id):
            return _json_error("运行记录不存在。", status=404)
        return _json_ok(run=_framework_stage_run_public(record))

    @app.post("/api/framework-to-script/lock")
    @_login_required
    def lock_framework_to_script_asset_api():
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _json_error("请求体必须是 JSON object。", status=400)
        user_id = _require_user_id()
        asset_id = str(data.get("framework_asset_id") or data.get("asset_id") or "").strip()
        if not asset_id:
            return _json_error("缺少 framework_asset_id。", status=400)
        try:
            project_id = int(asset_id)
        except Exception:
            return _json_error("framework_asset_id 必须是有效资产 ID。", status=400)

        snapshot = task_manager.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot or str(snapshot.get("asset_kind") or "").strip() != "framework_planner":
            return _json_error("框架资产不存在，或无权访问。", status=404)

        framework_artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        script_snapshot = task_manager.get_framework_to_script_asset_for_source(
            project_id,
            user_id=user_id,
            public_view=False,
        )
        script_artifacts = script_snapshot.get("artifacts") if isinstance((script_snapshot or {}).get("artifacts"), dict) else {}
        existing_workspace_state = (
            script_artifacts.get("framework_to_script_state")
            if isinstance(script_artifacts.get("framework_to_script_state"), dict)
            else framework_artifacts.get("framework_to_script_state")
            if isinstance(framework_artifacts.get("framework_to_script_state"), dict)
            else {}
        )
        incoming_workspace_state = data.get("workspace_state") if isinstance(data.get("workspace_state"), dict) else {}
        workspace_state = copy.deepcopy(incoming_workspace_state or existing_workspace_state)
        if not isinstance(workspace_state, dict):
            workspace_state = {}
        workspace_state["framework_asset_id"] = str(project_id)
        workspace_state["project_id"] = project_id

        input_payload = snapshot.get("input_payload") if isinstance(snapshot.get("input_payload"), dict) else {}
        basic_config = input_payload.get("basic_config") if isinstance(input_payload.get("basic_config"), dict) else {}
        total_episodes = _positive_int(
            snapshot.get("total_episodes")
            or input_payload.get("total_episodes")
            or basic_config.get("total_episodes")
            or basic_config.get("episodes_per_season"),
            0,
        )
        try:
            _, all_batches_complete = task_manager._framework_to_script_batch_coverage(workspace_state, total_episodes)
        except Exception:
            logger.exception("framework-to-script lock coverage check failed project_id=%s", project_id)
            all_batches_complete = False

        staged_snapshot = copy.deepcopy(snapshot)
        staged_artifacts = staged_snapshot.setdefault("artifacts", {})
        staged_artifacts["framework_to_script_state"] = workspace_state
        final_text = ""
        try:
            export_asset = _framework_asset_payload(staged_snapshot, include_detail=True)
            export_asset["framework_to_script_state"] = _strip_raw_workflow_fields(copy.deepcopy(workspace_state))
            export_asset["scriptStages"] = _strip_raw_workflow_fields(
                copy.deepcopy(workspace_state.get("scriptStages") or workspace_state.get("script_stages") or {})
            )
            export_asset["stage_outputs"] = _strip_raw_workflow_fields(
                copy.deepcopy(workspace_state.get("stageOutputs") or {})
            )
            final_text = _framework_to_script_txt(export_asset)
        except Exception:
            logger.exception("framework-to-script lock final text render failed project_id=%s", project_id)
            final_text = ""
        if not all_batches_complete or not str(final_text or "").strip():
            return _json_error("剧本阶段尚未完整生成，必须完成 12 阶段全部批次后才能锁定保存。", status=400)

        now = _now_iso()
        completed_stages = workspace_state.get("completedStages") if isinstance(workspace_state.get("completedStages"), list) else []
        completed_set = {str(item) for item in completed_stages}
        completed_set.add("12")
        workspace_state["completedStages"] = sorted(completed_set, key=lambda item: int(item) if str(item).isdigit() else 999)
        workspace_state["script_locked"] = True
        workspace_state["scriptLocked"] = True
        workspace_state["framework_to_script_locked"] = True
        workspace_state["locked"] = True
        workspace_state["script_locked_at"] = now
        workspace_state["scriptLockedAt"] = now
        workspace_state["locked_at"] = now
        workspace_state["updated_at"] = now

        script_asset = task_manager.save_framework_to_script_asset(
            user_id=user_id,
            framework_snapshot=snapshot,
            workspace_state=workspace_state,
            final_text=final_text,
        )
        framework_asset = _framework_asset_payload(snapshot, include_detail=True)
        cleanup = _cleanup_framework_to_script_debug_files(str(project_id), framework_asset)
        _clear_framework_stage_runs_for_asset(user_id, str(project_id))
        return _json_ok(
            locked=True,
            locked_at=now,
            asset=_strip_raw_workflow_fields(framework_asset),
            script_asset=script_asset,
            cleanup=cleanup,
        )

    @app.get("/api/framework-to-script/stage/11/status")
    @_login_required
    def get_framework_to_script_stage11_status_api():
        user_id = _require_user_id()
        asset_id = str(
            request.args.get("framework_asset_id")
            or request.args.get("asset_id")
            or ""
        ).strip()
        if not asset_id:
            return _json_error("缺少 framework_asset_id。", status=400)
        runs = _list_framework_stage_runs(user_id=user_id, asset_id=asset_id, stage="11")
        run = runs[0] if runs else {}
        return _json_ok(run=run, runs=runs)

    @app.post("/api/framework-planner/assets")
    @_login_required
    def create_framework_planner_asset_api():
        data = request.get_json(silent=True) or {}
        try:
            season_count = _positive_int_or_none(data.get("season_count")) or 1
            episodes_per_season = _positive_int_or_none(
                data.get("episodes_number")
                or data.get("total_episodes")
                or data.get("episodes_per_season")
            )
            missing = []
            if episodes_per_season is None:
                missing.append("episodes_per_season")
            if missing:
                raise ValueError("新建框架资产缺少总集数。")
            asset = task_manager.create_framework_planner_asset(
                user_id=_require_user_id(),
                title=str(data.get("source_title") or data.get("title") or data.get("project_title") or ""),
                season_count=season_count,
                episodes_per_season=episodes_per_season,
                episode_word_count=_positive_int_or_none(
                    data.get("chars_per_epi")
                    or data.get("episode_word_count")
                    or data.get("chars_per_episode")
                ) or 600,
                target_format=str(data.get("target_format") or data.get("genre") or "短剧"),
                style=str(data.get("style") or ""),
                description=str(data.get("description") or data.get("story_outline") or ""),
            )
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        except Exception as exc:
            logger.exception("framework planner asset create failed")
            return _json_error(str(exc), status=500, fallback="新建剧本失败，请稍后重试。")
        return _json_ok(asset=asset)



    @app.post("/api/framework-to-script/stage/08")
    @_login_required
    def run_framework_to_script_stage08_api():
        """单独运行 08 核心场景提炼。只跑 08，不继续 09/10。"""
        import json as _json

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _json_error("请求体必须是 JSON object。", status=400)
        try:
            user_id = _require_user_id()
            data, framework_asset = _inject_framework_asset(data, user_id)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        locked_response = _framework_to_script_locked_error(framework_asset)
        if locked_response:
            return locked_response

        framework_plan_package = (
            data.get("framework_plan_package")
            or data.get("frameworkPlanPackage")
            or {}
        )
        if not isinstance(framework_plan_package, dict) or not framework_plan_package:
            return _json_error(
                "缺少 framework_plan_package，请先从 07 最终策划包进入框架转剧本工作台。",
                status=400,
            )

        worldview_plan = (
            data.get("worldview_plan")
            or data.get("worldviewPlan")
            or framework_plan_package.get("worldview_plan")
            or framework_plan_package.get("worldviewPlan")
            or {}
        )
        beat_checkpoint_timeline = (
            data.get("beat_checkpoint_timeline")
            or data.get("beatCheckpointTimeline")
            or framework_plan_package.get("beat_checkpoint_timeline")
            or framework_plan_package.get("beatCheckpointTimeline")
            or []
        )
        character_storylines = (
            data.get("character_storylines")
            or data.get("characterStorylines")
            or framework_plan_package.get("character_storylines")
            or framework_plan_package.get("characterStorylines")
            or []
        )

        variables = {
            "frameworkPlanPackage": framework_plan_package,
            "framework_plan_package": framework_plan_package,
            "worldviewPlan": worldview_plan,
            "worldview_plan": worldview_plan,
            "beatCheckpointTimeline": beat_checkpoint_timeline,
            "beat_checkpoint_timeline": beat_checkpoint_timeline,
            "characterStorylines": character_storylines,
            "character_storylines": character_storylines,
            "sourceFrameworkProjectId": data.get("source_framework_project_id") or data.get("sourceFrameworkProjectId") or "",
        }
        variables = _inject_snapshot_stage_preference(
            variables,
            data,
            "08",
            framework_asset=framework_asset,
            workflow_stage="08",
        )
        def _try_parse_json_text(value):
            if not isinstance(value, str):
                return None
            text = value.strip()
            if not text:
                return None
            if text.startswith("```"):
                text = text.strip("`").strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()
            try:
                return _json.loads(text)
            except Exception:
                return None

        def _extract_update_vars(payload):
            found = {}
            if not isinstance(payload, dict):
                return found
            response_data = payload.get("responseData")
            if not isinstance(response_data, dict):
                return found
            update_results = response_data.get("updateVarResult")
            if not isinstance(update_results, list):
                return found
            for item in update_results:
                if not isinstance(item, dict):
                    continue
                variable = item.get("variable")
                value = item.get("value")
                key = ""
                if isinstance(variable, list) and variable:
                    key = str(variable[-1] or "")
                elif isinstance(variable, str):
                    key = variable
                if key:
                    found[key] = value
            return found

        def _extract_scene_payload(payload):
            candidates = []

            def visit(obj):
                if isinstance(obj, dict):
                    candidates.append(obj)

                    parsed_answer = _try_parse_json_text(obj.get("answerText"))
                    if parsed_answer is not None:
                        visit(parsed_answer)

                    parsed_text = _try_parse_json_text(obj.get("text"))
                    if parsed_text is not None:
                        visit(parsed_text)

                    update_vars = _extract_update_vars(obj)
                    if update_vars:
                        candidates.append(update_vars)
                        for val in update_vars.values():
                            parsed = _try_parse_json_text(val)
                            if parsed is not None:
                                visit(parsed)

                    for key in ("data", "result", "output", "response", "responseData"):
                        val = obj.get(key)
                        if isinstance(val, (dict, list)):
                            visit(val)
                        else:
                            parsed = _try_parse_json_text(val)
                            if parsed is not None:
                                visit(parsed)

                elif isinstance(obj, list):
                    for item in obj:
                        visit(item)
                else:
                    parsed = _try_parse_json_text(obj)
                    if parsed is not None:
                        visit(parsed)

            visit(payload)

            for item in candidates:
                if not isinstance(item, dict):
                    continue
                scene_dictionary = (
                    item.get("sceneDictionary")
                    or item.get("scene_dictionary")
                    or item.get("scene_dictionary_result")
                )
                rules_digest = (
                    item.get("scriptWorldRulesDigest")
                    or item.get("script_world_rules_digest")
                    or item.get("worldRulesDigest")
                )
                if scene_dictionary and rules_digest:
                    return scene_dictionary, rules_digest

            return None, None

        asset_id = str((framework_asset or {}).get("asset_id") or data.get("framework_asset_id") or "").strip()
        if not _try_begin_framework_stage(user_id, asset_id, "08"):
            return _json_error("08 正在运行中，请稍后刷新页面，已完成输出会自动恢复。", status=409)
        try:
            try:
                from .services.tencent_workflow_client import tencent_workflow_client
                from .services.workflow_contracts import STAGE_FRAMEWORK_SCENE_DICTIONARY

                raw_output = tencent_workflow_client.run_stage(
                    STAGE_FRAMEWORK_SCENE_DICTIONARY,
                    variables,
                )
            except Exception as exc:
                return _json_error(
                    str(exc),
                    status=500,
                    fallback="08 核心场景提炼调用失败，请检查 腾讯工作流 token 和工作流变量。",
                )

            scene_dictionary, rules_digest = _extract_scene_payload(raw_output)
            if not scene_dictionary or not rules_digest:
                return _json_error(
                    "08 场景字典阶段输出缺少 sceneDictionary 或 scriptWorldRulesDigest。",
                    status=500,
                    fallback="请检查 08_核心场景提炼.json 是否把 sceneDictionary 和 scriptWorldRulesDigest 写入变量或 answerText JSON。",
                )
            if asset_id:
                _save_framework_to_script_stage(
                    user_id=user_id,
                    asset_id=asset_id,
                    stage_key="stage08",
                    output={
                        "sceneDictionary": scene_dictionary,
                        "scriptWorldRulesDigest": rules_digest,
                    },
                )
        finally:
            _end_framework_stage(user_id, asset_id, "08")

        return _json_ok(
            stage="08",
            framework_asset_id=asset_id,
            sceneDictionary=scene_dictionary,
            scriptWorldRulesDigest=rules_digest,
        )


    def _stage09_ascii_id(value: object, fallback: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").lower()
        return text or fallback

    def _stage09_character_display_name(character: dict, index: int) -> str:
        for key in ("default_name", "name", "character_name", "canonical_name", "character_id"):
            text = str(character.get(key) or "").strip()
            if text:
                return text
        return f"角色{index}"

    def _stage09_string_list(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item or "").strip()]
        text = str(value or "").strip()
        return [text] if text else []

    def _ensure_stage09_usable_appearance_mapping(appearance_mapping: dict) -> tuple[dict, dict]:
        """Ensure stage 09 output has minimal outfit IDs for downstream stage 10.

        腾讯工作流 can return a structurally valid appearanceMapping with empty outfit_variants.
        Stage 10 then emits outfit_unknown. This does not invent detailed costume design;
        it only creates a deterministic default outfit version so downstream stages have
        a stable outfit_version_id to reference.
        """
        if not isinstance(appearance_mapping, dict):
            return appearance_mapping, {"repaired": False, "reason": "appearanceMapping_not_dict"}

        mapping = copy.deepcopy(appearance_mapping)
        characters = mapping.get("characters")
        if not isinstance(characters, list):
            return mapping, {"repaired": False, "reason": "characters_not_list"}

        warnings = list(mapping.get("stage09_quality_warnings") or [])
        repaired_characters = 0
        normalized_variants = 0
        total_variants = 0

        for index, character in enumerate(characters, start=1):
            if not isinstance(character, dict):
                continue

            display_name = _stage09_character_display_name(character, index)
            character_id = _stage09_ascii_id(
                character.get("character_id") or character.get("canonical_name") or display_name,
                f"character_{index}",
            )
            default_name = str(character.get("default_name") or "").strip() or display_name
            character.setdefault("character_id", character_id)
            character.setdefault("canonical_name", character_id)
            character.setdefault("default_name", default_name)

            variants = character.get("outfit_variants")
            if not isinstance(variants, list):
                variants = []

            versions = character.get("outfit_versions")
            if not variants and isinstance(versions, list) and versions:
                converted = []
                for version_index, version in enumerate(versions, start=1):
                    version_id = f"{character_id}_v{version_index}"
                    if isinstance(version, dict):
                        item = copy.deepcopy(version)
                        version_id = str(
                            item.get("outfit_version_id")
                            or item.get("variant_id")
                            or item.get("version_id")
                            or item.get("linked_outfit_version")
                            or version_id
                        ).strip()
                        item.setdefault("alias_name", default_name)
                        item.setdefault("outfit_description", item.get("description") or item.get("clothing") or "")
                        item.setdefault("usage_rule", item.get("trigger_condition") or "")
                    else:
                        item = {
                            "alias_name": default_name,
                            "outfit_description": str(version or "").strip(),
                            "usage_rule": "",
                        }
                    item["outfit_version_id"] = version_id
                    item["variant_id"] = str(item.get("variant_id") or version_id).strip()
                    item["version_id"] = str(item.get("version_id") or version_id).strip()
                    item["linked_outfit_version"] = str(item.get("linked_outfit_version") or version_id).strip()
                    converted.append(item)
                variants = converted

            if not variants:
                version_id = f"{character_id}_default"
                anchor = character.get("same_person_anchor") if isinstance(character.get("same_person_anchor"), dict) else {}
                visual_keypoints = (
                    _stage09_string_list(anchor.get("stable_appearance_traits"))
                    or _stage09_string_list(anchor.get("stable_recognition_points"))
                    or [default_name]
                )
                variants = [
                    {
                        "variant_id": version_id,
                        "version_id": version_id,
                        "outfit_version_id": version_id,
                        "linked_outfit_version": version_id,
                        "alias_name": default_name,
                        "outfit_type": "常态",
                        "applicable_identity_state": "常态",
                        "outfit_description": f"{default_name}的常态服装版本；09 阶段未提供细化服装，后续可按场景继续细化。",
                        "visual_keypoints": visual_keypoints,
                        "episode_range_hint": "全剧兜底",
                        "usage_rule": f"未命中特定服装版本时使用 {default_name} 的常态版本。",
                        "scene_trigger_rules": {
                            "scene_types": [],
                            "identity_states": ["常态"],
                            "status_keywords": [],
                        },
                        "must_use_when_triggered": True,
                        "fallback_allowed": True,
                        "source": "backend_minimal_fallback",
                    }
                ]
                repaired_characters += 1
                warnings.append(
                    f"角色 {default_name} 的 outfit_variants 为空，后端已补常态 outfit_version_id={version_id}。"
                )

            for variant_index, variant in enumerate(variants, start=1):
                if not isinstance(variant, dict):
                    continue
                version_id = str(
                    variant.get("outfit_version_id")
                    or variant.get("variant_id")
                    or variant.get("version_id")
                    or variant.get("linked_outfit_version")
                    or f"{character_id}_v{variant_index}"
                ).strip()
                variant["outfit_version_id"] = version_id
                variant["variant_id"] = str(variant.get("variant_id") or version_id).strip()
                variant["version_id"] = str(variant.get("version_id") or version_id).strip()
                variant["linked_outfit_version"] = str(
                    variant.get("linked_outfit_version") or version_id
                ).strip()
                variant.setdefault("alias_name", default_name)
                normalized_variants += 1

            character["outfit_variants"] = variants
            total_variants += len([item for item in variants if isinstance(item, dict)])

        quality = {
            "repaired": repaired_characters > 0,
            "repaired_characters": repaired_characters,
            "characters": len([item for item in characters if isinstance(item, dict)]),
            "outfit_variants": total_variants,
            "normalized_variants": normalized_variants,
            "warnings": warnings,
        }
        mapping["stage09_quality"] = quality
        if warnings:
            mapping["stage09_quality_warnings"] = warnings
        return mapping, quality


    @app.post("/api/framework-to-script/stage/09")
    @_login_required
    def run_framework_to_script_stage09_api():
        """单独运行 09 人设服装 alias 映射。只跑 09，不继续 10。"""
        import json as _json

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _json_error("请求体必须是 JSON object。", status=400)

        logger.info(
            "framework-to-script stage09 raw request received: payload_keys=%s",
            sorted(data.keys()),
        )

        try:
            user_id = _require_user_id()
            data, framework_asset = _inject_framework_asset(data, user_id)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        locked_response = _framework_to_script_locked_error(framework_asset)
        if locked_response:
            return locked_response

        asset_id_for_log = str(
            (framework_asset or {}).get("asset_id")
            or data.get("framework_asset_id")
            or data.get("asset_id")
            or ""
        ).strip()

        logger.info(
            "framework-to-script stage09 asset injected: asset_id=%s data_keys=%s has_framework_plan_package=%s",
            asset_id_for_log,
            sorted(data.keys()),
            isinstance(data.get("framework_plan_package") or data.get("frameworkPlanPackage"), dict),
        )

        framework_plan_package = (
            data.get("framework_plan_package")
            or data.get("frameworkPlanPackage")
            or {}
        )
        if not isinstance(framework_plan_package, dict) or not framework_plan_package:
            return _json_error(
                "缺少 framework_plan_package，请先从 07 最终策划包进入框架转剧本工作台。",
                status=400,
            )

        character_plan = (
            data.get("character_plan")
            or data.get("characterPlan")
            or framework_plan_package.get("character_plan")
            or framework_plan_package.get("characterPlan")
            or {}
        )
        if not isinstance(character_plan, dict) or not character_plan:
            return _json_error(
                "缺少 character_plan，无法运行 09 人设服装 alias 映射。",
                status=400,
            )

        cached_stage09 = _framework_script_stage_cache(framework_asset, "stage09")
        cached_appearance_mapping = (
            cached_stage09.get("appearanceMapping")
            if isinstance(cached_stage09, dict)
            else None
        )
        cached_stage09_usable = bool(
            isinstance(cached_appearance_mapping, dict)
            and isinstance(cached_appearance_mapping.get("characters"), list)
            and cached_appearance_mapping.get("characters")
        )

        stage08 = _framework_script_stage_cache(framework_asset, "stage08")
        scene_dictionary = (
            data.get("sceneDictionary")
            or data.get("scene_dictionary")
            or stage08.get("sceneDictionary")
            or {}
        )
        if not isinstance(scene_dictionary, dict) or not scene_dictionary:
            return _json_error(
                "缺少 sceneDictionary，请先运行并确认 08 核心场景提炼。",
                status=400,
            )

        beat_checkpoint_timeline = (
            data.get("beat_checkpoint_timeline")
            or data.get("beatCheckpointTimeline")
            or framework_plan_package.get("beat_checkpoint_timeline")
            or framework_plan_package.get("beatCheckpointTimeline")
            or []
        )

        variables = {
            "frameworkPlanPackage": framework_plan_package,
            "framework_plan_package": framework_plan_package,
            "characterPlan": character_plan,
            "character_plan": character_plan,
            "sceneDictionary": scene_dictionary,
            "scene_dictionary": scene_dictionary,
            "beatCheckpointTimeline": beat_checkpoint_timeline,
            "beat_checkpoint_timeline": beat_checkpoint_timeline,
            "sourceFrameworkProjectId": data.get("source_framework_project_id") or data.get("sourceFrameworkProjectId") or "",
        }
        variables = _inject_snapshot_stage_preference(
            variables,
            data,
            "09",
            framework_asset=framework_asset,
            workflow_stage="09",
        )
        stage09_compact_instruction = (
            "【系统长度约束】必须在一次响应内返回完整合法 JSON。每个角色的数组字段只保留 1 条最关键记录，"
            "每个字符串控制在 30 个汉字以内，outfit_versions 每人只保留 1 个默认版本，"
            "relationships_with_others、alias_rules、scene_trigger_rules、episode_usage_plan、"
            "forbidden_write 各只保留 1 条；严禁省略 characters 中的任何角色，优先保证所有括号闭合。"
        )
        stage09_preference = _coerce_prompt_text(
            variables.get("stagePreference")
            or variables.get("stage_preference")
            or variables.get("user_feedback")
        )
        variables["stagePreference"] = "\n\n".join(
            item for item in (stage09_preference, stage09_compact_instruction) if item
        )
        scene_count = 0
        if isinstance(scene_dictionary, dict):
            core_scenes = scene_dictionary.get("core_scenes") or scene_dictionary.get("coreScenes")
            scene_count = len(core_scenes) if isinstance(core_scenes, list) else 0

        character_count = 0
        if isinstance(character_plan, dict):
            characters = character_plan.get("characters") or character_plan.get("main_characters")
            character_count = len(characters) if isinstance(characters, list) else 0

        logger.info(
            "framework-to-script stage09 prepared: asset_id=%s variable_keys=%s "
            "has_frameworkPlanPackage=%s has_characterPlan=%s has_sceneDictionary=%s "
            "scene_count=%s character_count=%s beat_count=%s",
            asset_id_for_log,
            sorted(variables.keys()),
            isinstance(variables.get("frameworkPlanPackage"), dict) and bool(variables.get("frameworkPlanPackage")),
            isinstance(variables.get("characterPlan"), dict) and bool(variables.get("characterPlan")),
            isinstance(variables.get("sceneDictionary"), dict) and bool(variables.get("sceneDictionary")),
            scene_count,
            character_count,
            len(beat_checkpoint_timeline) if isinstance(beat_checkpoint_timeline, list) else 0,
        )
        def _try_parse_json_text(value):
            if not isinstance(value, str):
                return None
            text = value.strip()
            if not text:
                return None
            if text.startswith("```"):
                text = text.strip("`").strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()
            try:
                return _json.loads(text)
            except Exception:
                return None

        def _extract_json_object_candidates(value):
            if not isinstance(value, str):
                return []
            text = value.strip()
            if not text:
                return []
            parsed = _try_parse_json_text(text)
            candidates = []
            seen = set()
            if isinstance(parsed, dict):
                fingerprint = _json.dumps(parsed, ensure_ascii=False, sort_keys=True, default=str)
                seen.add(fingerprint)
                candidates.append(parsed)

            in_string = False
            escaping = False
            depth = 0
            start = None
            for index, char in enumerate(text):
                if depth > 0:
                    if escaping:
                        escaping = False
                        continue
                    if char == "\\":
                        escaping = True
                        continue
                    if char == '"':
                        in_string = not in_string
                        continue
                    if in_string:
                        continue
                    if char == "{":
                        depth += 1
                        continue
                    if char == "}":
                        depth -= 1
                        if depth == 0 and start is not None:
                            parsed = _try_parse_json_text(text[start : index + 1])
                            if isinstance(parsed, dict):
                                fingerprint = _json.dumps(parsed, ensure_ascii=False, sort_keys=True, default=str)
                                if fingerprint not in seen:
                                    seen.add(fingerprint)
                                    candidates.append(parsed)
                            start = None
                        continue
                elif char == "{":
                    depth = 1
                    start = index
                    in_string = False
                    escaping = False
            return candidates

        def _extract_update_vars(payload):
            found = {}
            if isinstance(payload, list):
                for item in payload:
                    found.update(_extract_update_vars(item))
                return found
            if not isinstance(payload, dict):
                return found
            update_results = payload.get("updateVarResult")
            if not isinstance(update_results, list):
                response_data = payload.get("responseData")
                if isinstance(response_data, (dict, list)):
                    found.update(_extract_update_vars(response_data))
                return found
            for item in update_results:
                if not isinstance(item, dict):
                    continue
                variable = item.get("variable")
                value = item.get("value")
                key = ""
                if isinstance(variable, list) and variable:
                    key = str(variable[-1] or "")
                elif isinstance(variable, str):
                    key = variable
                if key:
                    found[key] = value
            return found

        def _extract_appearance_payload(payload):
            candidates = []

            def _list_count(value):
                return len(value) if isinstance(value, list) else 0

            def _mapping_from_candidate(item):
                if not isinstance(item, dict):
                    return None
                mapping = (
                    item.get("appearanceMapping")
                    or item.get("appearance_mapping")
                    or item.get("appearanceMappingResult")
                    or item.get("appearance_mapping_result")
                )
                if isinstance(mapping, str):
                    parsed = _try_parse_json_text(mapping)
                    mapping = parsed if isinstance(parsed, dict) else mapping
                if isinstance(mapping, dict) and isinstance(mapping.get("appearanceMapping"), dict):
                    mapping = mapping.get("appearanceMapping")
                if isinstance(mapping, dict):
                    return mapping
                if isinstance(item.get("characters"), list):
                    return item
                return None

            def _rich_counts(mapping):
                if not isinstance(mapping, dict):
                    return {
                        "characters": 0,
                        "outfit_versions": 0,
                        "outfit_variants": 0,
                        "alias_rules": 0,
                        "scene_trigger_rules": 0,
                        "episode_usage_plan": 0,
                        "episode_level_usage_plan": 0,
                        "global_alias_rules": 0,
                    }

                counts = {
                    "characters": 0,
                    "outfit_versions": 0,
                    "outfit_variants": 0,
                    "alias_rules": 0,
                    "scene_trigger_rules": _list_count(mapping.get("scene_level_usage_plan")),
                    "episode_usage_plan": _list_count(mapping.get("episode_level_usage_plan")),
                    "episode_level_usage_plan": _list_count(mapping.get("episode_level_usage_plan")),
                    "global_alias_rules": _list_count(mapping.get("global_alias_rules")),
                }

                characters = mapping.get("characters")
                if isinstance(characters, list):
                    counts["characters"] = len(characters)
                    for character in characters:
                        if not isinstance(character, dict):
                            continue
                        counts["outfit_versions"] += _list_count(character.get("outfit_versions"))
                        counts["outfit_variants"] += _list_count(character.get("outfit_variants"))
                        counts["alias_rules"] += _list_count(character.get("alias_rules"))
                        counts["scene_trigger_rules"] += _list_count(character.get("scene_trigger_rules"))
                        counts["episode_usage_plan"] += _list_count(character.get("episode_usage_plan"))
                        counts["episode_level_usage_plan"] += _list_count(character.get("episode_level_usage_plan"))

                return counts

            def _score_mapping(mapping, source):
                counts = _rich_counts(mapping)
                return (
                    counts["outfit_versions"] + counts["outfit_variants"],
                    counts["outfit_versions"],
                    counts["outfit_variants"],
                    counts["alias_rules"],
                    counts["scene_trigger_rules"],
                    counts["episode_usage_plan"] + counts["episode_level_usage_plan"],
                    counts["global_alias_rules"],
                    counts["characters"],
                    1 if any(key in str(source).lower() for key in ("textoutput", "answertext", "choices")) else 0,
                )

            def _normalize_mapping(mapping):
                if not isinstance(mapping, dict):
                    return mapping

                normalized = copy.deepcopy(mapping)
                characters = normalized.get("characters")
                if not isinstance(characters, list):
                    return normalized

                normalized_characters = []
                for character in characters:
                    if not isinstance(character, dict):
                        normalized_characters.append(character)
                        continue

                    item = copy.deepcopy(character)
                    outfit_versions = item.get("outfit_versions")
                    outfit_variants = item.get("outfit_variants")

                    # Stage 09 may return outfit_versions only.
                    # Convert it to outfit_variants so later export paths can reuse the same shape.
                    if isinstance(outfit_versions, list) and outfit_versions and not outfit_variants:
                        converted = []
                        default_name = (
                            item.get("default_name")
                            or item.get("name")
                            or item.get("canonical_name")
                            or item.get("character_id")
                            or ""
                        )
                        for version in outfit_versions:
                            if isinstance(version, dict):
                                version_item = copy.deepcopy(version)
                                version_id = (
                                    version_item.get("variant_id")
                                    or version_item.get("version_id")
                                    or version_item.get("linked_outfit_version")
                                    or ""
                                )
                                version_item.setdefault("variant_id", version_id)
                                version_item.setdefault("linked_outfit_version", version_id)
                                version_item.setdefault("alias_name", version_item.get("alias_name") or default_name)
                                version_item.setdefault(
                                    "outfit_description",
                                    version_item.get("outfit_description")
                                    or version_item.get("clothing")
                                    or version_item.get("description")
                                    or "",
                                )
                                version_item.setdefault(
                                    "usage_rule",
                                    version_item.get("usage_rule")
                                    or version_item.get("trigger_condition")
                                    or "",
                                )
                                if "scene_trigger_rules" not in version_item:
                                    scene_refs = version_item.get("scene_refs")
                                    version_item["scene_trigger_rules"] = scene_refs if isinstance(scene_refs, list) else []
                                converted.append(version_item)
                            elif isinstance(version, str) and version.strip():
                                converted.append({
                                    "variant_id": version.strip(),
                                    "linked_outfit_version": version.strip(),
                                    "alias_name": default_name,
                                    "outfit_description": "",
                                    "usage_rule": "",
                                    "scene_trigger_rules": [],
                                })
                        item["outfit_variants"] = converted

                    if "episode_level_usage_plan" not in item and isinstance(item.get("episode_usage_plan"), list):
                        item["episode_level_usage_plan"] = item.get("episode_usage_plan")

                    normalized_characters.append(item)

                normalized["characters"] = normalized_characters
                return normalized

            def _add_candidate(source, obj):
                mapping = _mapping_from_candidate(obj)
                if isinstance(mapping, dict) and mapping:
                    candidates.append((source, mapping))

            def visit(obj, source="root"):
                if isinstance(obj, dict):
                    _add_candidate(source, obj)

                    for text_key in ("textOutput", "answerText", "text", "content"):
                        text_value = obj.get(text_key)
                        for candidate_index, parsed in enumerate(_extract_json_object_candidates(text_value)):
                            visit(parsed, f"{source}.{text_key}" if candidate_index == 0 else f"{source}.{text_key}[json_object:{candidate_index}]")

                    choices = obj.get("choices")
                    if isinstance(choices, list):
                        for index, choice in enumerate(choices):
                            if not isinstance(choice, dict):
                                continue
                            message = choice.get("message")
                            if isinstance(message, dict):
                                for candidate_index, parsed in enumerate(_extract_json_object_candidates(message.get("content"))):
                                    visit(parsed, f"{source}.choices[{index}].message.content" if candidate_index == 0 else f"{source}.choices[{index}].message.content[json_object:{candidate_index}]")

                    update_vars = _extract_update_vars(obj)
                    if update_vars:
                        _add_candidate(f"{source}.updateVars", update_vars)
                        for key, val in update_vars.items():
                            for candidate_index, parsed in enumerate(_extract_json_object_candidates(val)):
                                visit(parsed, f"{source}.updateVars.{key}" if candidate_index == 0 else f"{source}.updateVars.{key}[json_object:{candidate_index}]")

                    for key in (
                        "data",
                        "result",
                        "output",
                        "outputs",
                        "response",
                        "responseData",
                        "newVariables",
                        "updateVarResult",
                    ):
                        val = obj.get(key)
                        if isinstance(val, (dict, list)):
                            visit(val, f"{source}.{key}")
                        else:
                            for candidate_index, parsed in enumerate(_extract_json_object_candidates(val)):
                                visit(parsed, f"{source}.{key}" if candidate_index == 0 else f"{source}.{key}[json_object:{candidate_index}]")

                elif isinstance(obj, list):
                    for index, item in enumerate(obj):
                        visit(item, f"{source}[{index}]")
                else:
                    for parsed in _extract_json_object_candidates(obj):
                        visit(parsed, source)

            visit(payload)

            if not candidates:
                return None

            scored = []
            for source, mapping in candidates:
                normalized = _normalize_mapping(mapping)
                counts = _rich_counts(normalized)
                score = _score_mapping(normalized, source)
                scored.append((score, source, counts, normalized))

            scored.sort(key=lambda item: item[0], reverse=True)
            best_score, best_source, best_counts, best_mapping = scored[0]

            logger.info(
                "stage09 appearanceMapping selected source=%s counts=%s",
                best_source,
                best_counts,
            )

            return best_mapping
        def _stage09_merge_meta(target: dict, source: dict) -> dict:
            if not isinstance(source, dict):
                return target
            for key in ("execute_id", "debug_url", "logid", "workflow_id", "space_id"):
                if source.get(key) and not target.get(key):
                    target[key] = str(source.get(key))
            if source.get("usage") and not target.get("usage"):
                target["usage"] = source.get("usage")
            if source.get("token_count") and not target.get("token_count"):
                target["token_count"] = source.get("token_count")
            return target

        def _stage09_extract_tencent_meta(value, *, _depth: int = 0) -> dict:
            meta = {
                "execute_id": "",
                "debug_url": "",
                "logid": "",
                "workflow_id": "",
                "space_id": "",
                "usage": None,
                "token_count": None,
            }
            if _depth > 6:
                return meta

            if isinstance(value, dict):
                if value.get("execute_id") is not None:
                    meta["execute_id"] = str(value.get("execute_id") or "")
                if value.get("debug_url") is not None:
                    meta["debug_url"] = str(value.get("debug_url") or "")
                if value.get("workflow_id") is not None:
                    meta["workflow_id"] = str(value.get("workflow_id") or "")
                if value.get("space_id") is not None:
                    meta["space_id"] = str(value.get("space_id") or "")
                if isinstance(value.get("detail"), dict) and value["detail"].get("logid"):
                    meta["logid"] = str(value["detail"].get("logid") or "")
                if value.get("logid") is not None:
                    meta["logid"] = str(value.get("logid") or "")
                if isinstance(value.get("usage"), dict):
                    meta["usage"] = value.get("usage")
                    if value["usage"].get("token_count") is not None:
                        meta["token_count"] = value["usage"].get("token_count")
                if value.get("token_count") is not None:
                    meta["token_count"] = value.get("token_count")

                for item in value.values():
                    meta = _stage09_merge_meta(meta, _stage09_extract_tencent_meta(item, _depth=_depth + 1))
                return meta

            if isinstance(value, list):
                for item in value:
                    meta = _stage09_merge_meta(meta, _stage09_extract_tencent_meta(item, _depth=_depth + 1))
                return meta

            if isinstance(value, str):
                text = value.strip()
                if not text:
                    return meta

                parsed = _try_parse_json_text(text)
                if parsed is not None:
                    meta = _stage09_merge_meta(meta, _stage09_extract_tencent_meta(parsed, _depth=_depth + 1))

                # 从 debug_url 或异常文本里兜底提取 execute_id。
                execute_match = re.search(r"execute_id[=\":\s]+(\d{8,})", text)
                if execute_match and not meta.get("execute_id"):
                    meta["execute_id"] = execute_match.group(1)

                debug_url_match = re.search(r"https://www\.tencent\.cn/work_flow\?[^\"'\s]+", text)
                if debug_url_match and not meta.get("debug_url"):
                    meta["debug_url"] = debug_url_match.group(0)
                    execute_from_url = re.search(r"execute_id=(\d{8,})", meta["debug_url"])
                    if execute_from_url and not meta.get("execute_id"):
                        meta["execute_id"] = execute_from_url.group(1)

                logid_match = re.search(r'"logid"\s*:\s*"([^"]+)"', text)
                if logid_match and not meta.get("logid"):
                    meta["logid"] = logid_match.group(1)

                return meta

            return meta

        def _stage09_collect_tencent_debug_snapshot(client_obj, stage_name: str, exc: Exception | None = None) -> dict:
            debug_info = {}
            try:
                if client_obj is not None and hasattr(client_obj, "get_last_stage_debug_info"):
                    maybe_debug = client_obj.get_last_stage_debug_info(stage_name)
                    debug_info = maybe_debug if isinstance(maybe_debug, dict) else {}
            except Exception as debug_exc:
                debug_info = {
                    "debug_collect_error": f"{type(debug_exc).__name__}: {debug_exc}",
                }

            meta = _stage09_extract_tencent_meta(debug_info)
            if exc is not None:
                meta = _stage09_merge_meta(meta, _stage09_extract_tencent_meta(str(exc)))

            return {
                "meta": meta,
                "debug_info_type": type(debug_info).__name__,
                "debug_info_keys": sorted(debug_info.keys()) if isinstance(debug_info, dict) else [],
                # 不要只存 preview；这里直接存完整 debug_info，方便你查 execute_id / debug_url / 原始返回预览。
                "debug_info": debug_info,
                "exception_text": str(exc or ""),
            }


        asset_id = str((framework_asset or {}).get("asset_id") or data.get("framework_asset_id") or "").strip()
        if not _try_begin_framework_stage(user_id, asset_id, "09"):
            return _json_error("09 正在运行中，请稍后刷新页面，已完成输出会自动恢复。", status=409)
        try:
            debug_record = {
                "stage": "09",
                "stage_name": "framework_appearanceMapping",
                "status": "started",
                "asset_id": asset_id,
                "request_payload_keys": sorted(data.keys()),
                "variable_keys": sorted(variables.keys()),
                "variable_size_summary": {
                    key: {
                        "type": type(value).__name__,
                        "json_length": _json_len_for_debug(value),
                        "preview": _stage12_debug_preview(value, limit=500),
                    }
                    for key, value in variables.items()
                },
                "has_frameworkPlanPackage": isinstance(variables.get("frameworkPlanPackage"), dict) and bool(variables.get("frameworkPlanPackage")),
                "has_characterPlan": isinstance(variables.get("characterPlan"), dict) and bool(variables.get("characterPlan")),
                "has_sceneDictionary": isinstance(variables.get("sceneDictionary"), dict) and bool(variables.get("sceneDictionary")),
                "beat_count": len(beat_checkpoint_timeline) if isinstance(beat_checkpoint_timeline, list) else 0,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            debug_path = _write_framework_to_script_debug_file(
                stage_no="09",
                data=data,
                framework_asset=framework_asset,
                record=debug_record,
                filename="stage09_latest.json",
            )
            try:
                from .services.tencent_workflow_client import tencent_workflow_client
                from .services.workflow_contracts import STAGE_FRAMEWORK_APPEARANCE_MAPPING

                debug_record.update(
                    {
                        "status": "requesting_tencent",
                        "tencent_request_started_at": _now_iso(),
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_framework_to_script_debug_file(
                    stage_no="09",
                    data=data,
                    framework_asset=framework_asset,
                    record=debug_record,
                    filename="stage09_latest.json",
                )

                logger.info(
                    "framework-to-script stage09 entering 腾讯工作流: asset_id=%s stage_name=%s variable_keys=%s",
                    asset_id_for_log,
                    STAGE_FRAMEWORK_APPEARANCE_MAPPING,
                    sorted(variables.keys()),
                )

                stage09_started = time.monotonic()
                try:
                    raw_output = tencent_workflow_client.run_stage(
                        STAGE_FRAMEWORK_APPEARANCE_MAPPING,
                        variables,
                    )
                except Exception as first_exc:
                    from .services.workflow_errors import WorkflowStageFormatError

                    if not isinstance(first_exc, WorkflowStageFormatError):
                        raise
                    compact_retry_instruction = (
                        "【系统二次格式重试】上一轮仍未形成合法 JSON。请进一步压缩措辞，"
                        "不得增加数组条目或解释文字，确保所有角色齐全、所有括号闭合且 JSON.parse 可解析。"
                    )
                    retry_variables = copy.deepcopy(variables)
                    current_preference = _coerce_prompt_text(
                        retry_variables.get("stagePreference")
                        or retry_variables.get("stage_preference")
                        or retry_variables.get("user_feedback")
                    )
                    retry_variables["stagePreference"] = "\n\n".join(
                        item for item in (current_preference, compact_retry_instruction) if item
                    )
                    debug_record.update(
                        {
                            "status": "retrying_compact_json",
                            "first_format_error": str(first_exc),
                            "compact_retry_started_at": _now_iso(),
                            "updated_at": _now_iso(),
                        }
                    )
                    _write_framework_to_script_debug_file(
                        stage_no="09",
                        data=data,
                        framework_asset=framework_asset,
                        record=debug_record,
                        filename="stage09_latest.json",
                    )
                    raw_output = tencent_workflow_client.run_stage(
                        STAGE_FRAMEWORK_APPEARANCE_MAPPING,
                        retry_variables,
                    )
                stage09_duration_ms = int((time.monotonic() - stage09_started) * 1000)

                debug_record.update(
                    {
                        "status": "tencent_returned",
                        "tencent_request_ended_at": _now_iso(),
                        "duration_ms": stage09_duration_ms,
                        "raw_output_summary": _stage12_debug_summary(raw_output, preview_limit=800),
                        "raw_output_keys": sorted(raw_output.keys()) if isinstance(raw_output, dict) else [],
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_framework_to_script_debug_file(
                    stage_no="09",
                    data=data,
                    framework_asset=framework_asset,
                    record=debug_record,
                    filename="stage09_latest.json",
                )

                logger.info(
                    "framework-to-script stage09 腾讯工作流 returned: asset_id=%s duration_ms=%s raw_type=%s raw_keys=%s",
                    asset_id_for_log,
                    stage09_duration_ms,
                    type(raw_output).__name__,
                    sorted(raw_output.keys()) if isinstance(raw_output, dict) else [],
                )
            except Exception as exc:
                stage09_stage_name = (
                    STAGE_FRAMEWORK_APPEARANCE_MAPPING
                    if "STAGE_FRAMEWORK_APPEARANCE_MAPPING" in locals()
                    else "framework_appearanceMapping"
                )
                tencent_debug_snapshot = _stage09_collect_tencent_debug_snapshot(
                    tencent_workflow_client if "tencent_workflow_client" in locals() else None,
                    stage09_stage_name,
                    exc,
                )
                tencent_meta = tencent_debug_snapshot.get("meta") if isinstance(tencent_debug_snapshot, dict) else {}
                if not isinstance(tencent_meta, dict):
                    tencent_meta = {}

                raw_error_debug_path = _write_framework_to_script_raw_tencent_debug(
                    stage_no="09",
                    stage_name=stage09_stage_name,
                    variables=variables,
                    raw_output=tencent_debug_snapshot,
                    parsed_output={},
                    error=str(exc),
                )

                logger.exception(
                    "framework-to-script stage09 腾讯工作流 call failed: asset_id=%s stage_name=%s execute_id=%s debug_url=%s",
                    asset_id_for_log,
                    stage09_stage_name,
                    tencent_meta.get("execute_id") or "",
                    tencent_meta.get("debug_url") or "",
                )

                debug_record.update(
                    {
                        "status": "failed",
                        "failure_phase": "tencent_call",
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                        "traceback": traceback.format_exc(),
                        "execute_id": tencent_meta.get("execute_id") or "",
                        "debug_url": tencent_meta.get("debug_url") or "",
                        "logid": tencent_meta.get("logid") or "",
                        "workflow_id": tencent_meta.get("workflow_id") or "",
                        "space_id": tencent_meta.get("space_id") or "",
                        "usage": tencent_meta.get("usage"),
                        "token_count": tencent_meta.get("token_count"),
                        "tencent_raw_error_debug_path": raw_error_debug_path,
                        "tencent_last_stage_debug": tencent_debug_snapshot,
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_framework_to_script_debug_file(
                    stage_no="09",
                    data=data,
                    framework_asset=framework_asset,
                    record=debug_record,
                    filename="stage09_latest.json",
                )
                if cached_stage09_usable:
                    restored_mapping, restored_quality = _ensure_stage09_usable_appearance_mapping(
                        copy.deepcopy(cached_appearance_mapping)
                    )
                    debug_record.update(
                        {
                            "status": "fallback_cached_success",
                            "fallback_used": True,
                            "fallback_reason": str(exc),
                            "characters_count": len(restored_mapping.get("characters") or []),
                            "appearance_mapping_quality": restored_quality,
                            "updated_at": _now_iso(),
                        }
                    )
                    _write_framework_to_script_debug_file(
                        stage_no="09",
                        data=data,
                        framework_asset=framework_asset,
                        record=debug_record,
                        filename="stage09_latest.json",
                    )
                    logger.warning(
                        "framework-to-script stage09 rerun failed; restored last valid mapping: asset_id=%s characters=%s",
                        asset_id_for_log,
                        len(restored_mapping.get("characters") or []),
                    )
                    return _json_ok(
                        stage="09",
                        framework_asset_id=asset_id,
                        appearanceMapping=restored_mapping,
                        fallback_used=True,
                        warning="09 本次远端输出被截断，已保留并恢复上一次有效人物映射。",
                    )
                return _json_error(
                    str(exc),
                    status=500,
                        fallback="09 人设服装 alias 映射调用失败，请检查 腾讯工作流 token 和工作流变量。",
                )

            appearanceMapping = _extract_appearance_payload(raw_output)
            _write_framework_to_script_raw_tencent_debug(
                stage_no="09",
                stage_name=STAGE_FRAMEWORK_APPEARANCE_MAPPING,
                variables=variables,
                raw_output=raw_output,
                parsed_output={"appearanceMapping": appearanceMapping} if appearanceMapping else {},
            )

            debug_record.update(
                {
                    "status": "parsed",
                    "appearanceMapping_type": type(appearanceMapping).__name__,
                    "appearanceMapping_keys": sorted(appearanceMapping.keys()) if isinstance(appearanceMapping, dict) else [],
                    "characters_count": len(appearanceMapping.get("characters") or []) if isinstance(appearanceMapping, dict) and isinstance(appearanceMapping.get("characters"), list) else 0,
                    "updated_at": _now_iso(),
                }
            )
            debug_path = _write_framework_to_script_debug_file(
                stage_no="09",
                data=data,
                framework_asset=framework_asset,
                record=debug_record,
                filename="stage09_latest.json",
            )

            parsed_characters = (
                appearanceMapping.get("characters")
                if isinstance(appearanceMapping, dict)
                else []
            )
            logger.info(
                "framework-to-script stage09 parsed: asset_id=%s appearance_type=%s "
                "appearance_keys=%s characters_count=%s",
                asset_id_for_log,
                type(appearanceMapping).__name__,
                sorted(appearanceMapping.keys()) if isinstance(appearanceMapping, dict) else [],
                len(parsed_characters) if isinstance(parsed_characters, list) else 0,
            )

            if not appearanceMapping:
                return _json_error(
                    "09 人设服装 alias 映射输出缺少 appearanceMapping。",
                    status=500,
                    fallback="请检查 09_人设服装alias映射.json 是否把 appearanceMapping 写入变量或 answerText JSON。",
                )

            characters = appearanceMapping.get("characters")
            if not isinstance(characters, list) or not characters:
                return _json_error(
                    "09 人设服装 alias 映射输出缺少 appearanceMapping.characters。",
                    status=500,
                    fallback="请检查 09 工作流输出 schema。",
                )
            appearanceMapping, appearance_quality = _ensure_stage09_usable_appearance_mapping(appearanceMapping)
            characters = appearanceMapping.get("characters")
            if isinstance(appearance_quality, dict) and appearance_quality.get("repaired"):
                logger.warning(
                    "framework-to-script stage09 output had empty outfit variants; "
                    "backend added minimal outfit_version_id fallbacks: asset_id=%s repaired_characters=%s outfit_variants=%s",
                    asset_id_for_log,
                    appearance_quality.get("repaired_characters"),
                    appearance_quality.get("outfit_variants"),
                )
            debug_record.update(
                {
                    "appearance_mapping_quality": appearance_quality,
                    "outfit_variants_count": appearance_quality.get("outfit_variants") if isinstance(appearance_quality, dict) else 0,
                    "updated_at": _now_iso(),
                }
            )
            debug_path = _write_framework_to_script_debug_file(
                stage_no="09",
                data=data,
                framework_asset=framework_asset,
                record=debug_record,
                filename="stage09_latest.json",
            )
            if asset_id:
                _save_framework_to_script_stage(
                    user_id=user_id,
                    asset_id=asset_id,
                    stage_key="stage09",
                    output={"appearanceMapping": appearanceMapping},
                )
                logger.info(
                    "framework-to-script stage09 saved: asset_id=%s characters_count=%s",
                    asset_id,
                    len(characters) if isinstance(characters, list) else 0,
                )
                debug_record.update(
                    {
                        "status": "success",
                        "saved": True,
                        "characters_count": len(characters) if isinstance(characters, list) else 0,
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_framework_to_script_debug_file(
                    stage_no="09",
                    data=data,
                    framework_asset=framework_asset,
                    record=debug_record,
                    filename="stage09_latest.json",
                )
        finally:
            _end_framework_stage(user_id, asset_id, "09")

        return _json_ok(
            stage="09",
            framework_asset_id=asset_id,
            appearanceMapping=appearanceMapping,
        )

    @app.post("/api/framework-to-script/stage/10")
    @_login_required
    def run_framework_to_script_stage10_api():
        """单独运行 10 分集细化方案。只跑 10，不继续后续因果冲突。"""
        import json as _json

        def _stage10_debug_dir(data: dict, framework_asset: dict | None) -> Path:
            title = _stage12_debug_project_title(data, framework_asset)
            path = (
                    _writable_root()
                    / "cache"
                    / _stage12_debug_safe_name(title)
                    / "framework_to_script"
                    / "stage10"
            )
            path.mkdir(parents=True, exist_ok=True)
            return path

        def _stage10_raw_debug_dir() -> Path:
            path = _writable_root() / "cache" / "raw_tencent_debug"
            path.mkdir(parents=True, exist_ok=True)
            return path

        def _stage10_json_len(value) -> int:
            try:
                return len(_json.dumps(value, ensure_ascii=False, default=str))
            except Exception:
                return -1

        def _write_stage10_debug(record: dict, *, filename: str = "stage10_latest.json") -> str:
            try:
                path = _stage10_debug_dir(data, framework_asset) / filename
                public_record = {
                    key: value
                    for key, value in record.items()
                    if not str(key).startswith("_")
                }
                public_record["debug_path"] = str(path)
                path.write_text(
                    _json.dumps(public_record, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                return str(path)
            except Exception:
                logger.exception("framework-to-script stage10 debug file write failed")
                return ""

        def _write_stage10_raw_debug(*, raw_output=None, parsed_output=None, error: str = "", tencent_debug_snapshot=None, tencent_meta=None) -> str:
            try:
                path = _stage10_raw_debug_dir() / "stage10_raw_response.json"
                meta = tencent_meta if isinstance(tencent_meta, dict) else {}
                debug_snapshot = tencent_debug_snapshot if isinstance(tencent_debug_snapshot, dict) else {}
                debug_info = debug_snapshot.get("debug_info") if isinstance(debug_snapshot.get("debug_info"), dict) else {}
                tencent_raw_response = debug_info.get("raw_response")
                payload = {
                    "stage": "10",
                    "stage_name": "framework_enriched_episode_plan",
                    "backend": "tencent",
                    "asset_id": asset_id if "asset_id" in locals() else "",
                    "execute_id": meta.get("execute_id") or "",
                    "debug_url": meta.get("debug_url") or "",
                    "logid": meta.get("logid") or "",
                    "workflow_id": meta.get("workflow_id") or "",
                    "space_id": meta.get("space_id") or "",
                    "usage": meta.get("usage"),
                    "input_count": meta.get("input_count"),
                    "output_count": meta.get("output_count"),
                    "token_count": meta.get("token_count"),
                    "tencent_meta": meta,
                    "tencent_debug_info_keys": sorted(debug_info.keys()) if isinstance(debug_info, dict) else [],
                    "tencent_raw_response_type": type(tencent_raw_response).__name__,
                    "tencent_raw_response_keys": sorted(tencent_raw_response.keys()) if isinstance(tencent_raw_response, dict) else [],
                    "tencent_raw_response": tencent_raw_response,
                    "tencent_last_stage_debug": debug_snapshot,
                    "variable_keys": sorted(variables.keys()) if isinstance(variables, dict) else [],
                    "variable_size_summary": {
                        key: {
                            "type": type(value).__name__,
                            "json_length": _stage10_json_len(value),
                            "preview": _stage12_debug_preview(value, limit=500),
                        }
                        for key, value in (variables.items() if isinstance(variables, dict) else [])
                    },
                    "raw_output_type": type(raw_output).__name__,
                    "raw_output_keys": sorted(raw_output.keys()) if isinstance(raw_output, dict) else [],
                    "raw_output": raw_output,
                    "parsed_output": parsed_output,
                    "error": error,
                    "created_at": _now_iso(),
                }
                path.write_text(
                    _json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                logger.warning(
                    "[framework_to_script_raw_debug] wrote stage10 raw 腾讯工作流 response path=%s",
                    path,
                )
                return str(path)
            except Exception:
                logger.exception("[framework_to_script_raw_debug] failed to write stage10 raw response")
                return ""


        def _stage10_merge_meta(target: dict, source: dict) -> dict:
            if not isinstance(source, dict):
                return target
            for key in ("execute_id", "debug_url", "logid", "workflow_id", "space_id"):
                if source.get(key) and not target.get(key):
                    target[key] = str(source.get(key))
            for key in ("usage", "input_count", "output_count", "token_count"):
                if source.get(key) is not None and target.get(key) is None:
                    target[key] = source.get(key)
            return target

        def _stage10_try_parse_json_text(value):
            if not isinstance(value, str):
                return None
            text = value.strip()
            if not text:
                return None
            if text.startswith("```"):
                text = text.strip("`").strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()
            try:
                return _json.loads(text)
            except Exception:
                return None

        def _stage10_extract_tencent_meta(value, *, _depth: int = 0) -> dict:
            meta = {
                "execute_id": "",
                "debug_url": "",
                "logid": "",
                "workflow_id": "",
                "space_id": "",
                "usage": None,
                "input_count": None,
                "output_count": None,
                "token_count": None,
            }
            if _depth > 8:
                return meta

            if isinstance(value, dict):
                if value.get("execute_id") is not None:
                    meta["execute_id"] = str(value.get("execute_id") or "")
                if value.get("debug_url") is not None:
                    meta["debug_url"] = str(value.get("debug_url") or "")
                if value.get("workflow_id") is not None:
                    meta["workflow_id"] = str(value.get("workflow_id") or "")
                if value.get("space_id") is not None:
                    meta["space_id"] = str(value.get("space_id") or "")
                if isinstance(value.get("detail"), dict) and value["detail"].get("logid"):
                    meta["logid"] = str(value["detail"].get("logid") or "")
                if value.get("logid") is not None:
                    meta["logid"] = str(value.get("logid") or "")
                if isinstance(value.get("usage"), dict):
                    meta["usage"] = value.get("usage")
                    for key in ("input_count", "output_count", "token_count"):
                        if value["usage"].get(key) is not None:
                            meta[key] = value["usage"].get(key)
                for key in ("input_count", "output_count", "token_count"):
                    if value.get(key) is not None:
                        meta[key] = value.get(key)

                for item in value.values():
                    meta = _stage10_merge_meta(meta, _stage10_extract_tencent_meta(item, _depth=_depth + 1))
                return meta

            if isinstance(value, list):
                for item in value:
                    meta = _stage10_merge_meta(meta, _stage10_extract_tencent_meta(item, _depth=_depth + 1))
                return meta

            if isinstance(value, str):
                text_value = value.strip()
                if not text_value:
                    return meta

                parsed = _stage10_try_parse_json_text(text_value)
                if parsed is not None:
                    meta = _stage10_merge_meta(meta, _stage10_extract_tencent_meta(parsed, _depth=_depth + 1))

                execute_match = re.search(r"execute_id[=\":\s]+(\d{8,})", text_value)
                if execute_match and not meta.get("execute_id"):
                    meta["execute_id"] = execute_match.group(1)

                debug_url_match = re.search(r"https://www\.tencent\.cn/work_flow\?[^\"'\s]+", text_value)
                if debug_url_match and not meta.get("debug_url"):
                    meta["debug_url"] = debug_url_match.group(0)
                    execute_from_url = re.search(r"execute_id=(\d{8,})", meta["debug_url"])
                    if execute_from_url and not meta.get("execute_id"):
                        meta["execute_id"] = execute_from_url.group(1)

                logid_match = re.search(r'"logid"\s*:\s*"([^"]+)"', text_value)
                if logid_match and not meta.get("logid"):
                    meta["logid"] = logid_match.group(1)

                return meta

            return meta

        def _stage10_collect_tencent_debug_snapshot(client_obj, stage_name: str, exc: Exception | None = None) -> dict:
            debug_info = {}
            try:
                if client_obj is not None and hasattr(client_obj, "get_last_stage_debug_info"):
                    maybe_debug = client_obj.get_last_stage_debug_info(stage_name)
                    debug_info = maybe_debug if isinstance(maybe_debug, dict) else {}
            except Exception as debug_exc:
                debug_info = {
                    "debug_collect_error": f"{type(debug_exc).__name__}: {debug_exc}",
                }

            meta = _stage10_extract_tencent_meta(debug_info)
            if exc is not None:
                meta = _stage10_merge_meta(meta, _stage10_extract_tencent_meta(str(exc)))

            return {
                "meta": meta,
                "debug_info_type": type(debug_info).__name__,
                "debug_info_keys": sorted(debug_info.keys()) if isinstance(debug_info, dict) else [],
                "debug_info": debug_info,
                "exception_text": str(exc or ""),
            }

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _json_error("请求体必须是 JSON object。", status=400)

        try:
            user_id = _require_user_id()
            data, framework_asset = _inject_framework_asset(data, user_id)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        locked_response = _framework_to_script_locked_error(framework_asset)
        if locked_response:
            return locked_response

        framework_plan_package = (
                data.get("framework_plan_package")
                or data.get("frameworkPlanPackage")
                or {}
        )
        if not isinstance(framework_plan_package, dict) or not framework_plan_package:
            return _json_error("缺少 framework_plan_package，请先导入框架资产。", status=400)

        stage08 = _framework_script_stage_cache(framework_asset, "stage08")
        stage09 = _framework_script_stage_cache(framework_asset, "stage09")
        scene_dictionary = data.get("sceneDictionary") or data.get("scene_dictionary") or stage08.get(
            "sceneDictionary") or {}
        if not isinstance(scene_dictionary, dict) or not scene_dictionary:
            return _json_error("缺少 sceneDictionary，请先完成 08 核心场景提炼。", status=400)

        rules_digest = (
                data.get("scriptWorldRulesDigest")
                or data.get("script_world_rules_digest")
                or stage08.get("scriptWorldRulesDigest")
                or {}
        )
        if not isinstance(rules_digest, dict) or not rules_digest:
            return _json_error("缺少 scriptWorldRulesDigest，请先完成 08 核心场景提炼。", status=400)

        appearance_mapping = (
                data.get("appearanceMapping")
                or data.get("appearance_mapping")
                or stage09.get("appearanceMapping")
                or {}
        )
        if not isinstance(appearance_mapping, dict) or not appearance_mapping:
            return _json_error("缺少 appearanceMapping，请先完成 09 角色外观匹配场景。", status=400)

        appearance_mapping, stage10_appearance_quality = _ensure_stage09_usable_appearance_mapping(appearance_mapping)

        beat_checkpoint_timeline = (
                data.get("beat_checkpoint_timeline")
                or data.get("beatCheckpointTimeline")
                or framework_plan_package.get("beat_checkpoint_timeline")
                or framework_plan_package.get("beatCheckpointTimeline")
                or []
        )
        character_storylines = (
                data.get("character_storylines")
                or data.get("characterStorylines")
                or framework_plan_package.get("character_storylines")
                or framework_plan_package.get("characterStorylines")
                or []
        )

        basic_config = framework_plan_package.get("basic_config") if isinstance(
            framework_plan_package.get("basic_config"), dict) else {}
        source_brief = framework_plan_package.get("source_brief") if isinstance(
            framework_plan_package.get("source_brief"), dict) else {}
        adaptation_guide = framework_plan_package.get("adaptation_guide") if isinstance(
            framework_plan_package.get("adaptation_guide"), dict) else {}

        stage10_framework_context = {
            "project_title": (
                    framework_plan_package.get("project_title")
                    or framework_plan_package.get("title")
                    or basic_config.get("project_title")
                    or basic_config.get("source_title")
                    or data.get("project_title")
                    or data.get("title")
                    or ""
            ),
            "target_format": basic_config.get("target_format") or "短剧",
            "season_count": basic_config.get("season_count"),
            "episodes_per_season": basic_config.get("episodes_per_season"),
            "episode_word_count": basic_config.get("episode_word_count") or basic_config.get("chars_per_episode"),
            "chars_per_episode": basic_config.get("chars_per_episode") or basic_config.get("episode_word_count"),
            "core_logline": source_brief.get("core_logline") or source_brief.get("logline") or "",
            "genre": source_brief.get("genre") or "",
            "core_conflict": source_brief.get("core_conflict") or "",
            "must_keep_elements": source_brief.get("must_keep_elements") or [],
            "forbidden_deviations": source_brief.get("forbidden_deviations") or [],
            "hard_constraints_for_script_workflow": (
                adaptation_guide.get("hard_constraints_for_script_workflow")
                if isinstance(adaptation_guide.get("hard_constraints_for_script_workflow"), list)
                else []
            ),
        }
        stage10_total_episodes = _positive_int(
            data.get("total_episodes")
            or data.get("episodes_per_season")
            or basic_config.get("total_episodes")
            or basic_config.get("episodes_per_season")
            or (framework_asset or {}).get("episodes_per_season"),
            0,
        )
        if stage10_total_episodes:
            stage10_framework_context["total_episodes"] = stage10_total_episodes

        variables = {
            "frameworkPlanPackage": stage10_framework_context,
            "framework_plan_package": stage10_framework_context,
            "sceneDictionary": scene_dictionary,
            "scene_dictionary": scene_dictionary,
            "scriptWorldRulesDigest": rules_digest,
            "script_world_rules_digest": rules_digest,
            "appearanceMapping": appearance_mapping,
            "appearance_mapping": appearance_mapping,
            "beatCheckpointTimeline": beat_checkpoint_timeline,
            "beat_checkpoint_timeline": beat_checkpoint_timeline,
            "characterStorylines": character_storylines,
            "character_storylines": character_storylines,
            "sourceFrameworkProjectId": data.get("source_framework_project_id") or data.get(
                "sourceFrameworkProjectId") or "",
        }
        variables = _inject_snapshot_stage_preference(
            variables,
            data,
            "10",
            framework_asset=framework_asset,
            workflow_stage="10",
        )

        def _try_parse_json_text(value):
            if not isinstance(value, str):
                return None
            text = value.strip()
            if not text:
                return None
            if text.startswith("```"):
                text = text.strip("`").strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()
            try:
                return _json.loads(text)
            except Exception:
                return None

        def _extract_update_vars(payload):
            found = {}
            if not isinstance(payload, dict):
                return found
            response_data = payload.get("responseData")
            if not isinstance(response_data, dict):
                return found
            update_results = response_data.get("updateVarResult")
            if not isinstance(update_results, list):
                return found
            for item in update_results:
                if not isinstance(item, dict):
                    continue
                variable = item.get("variable")
                value = item.get("value")
                key = ""
                if isinstance(variable, list) and variable:
                    key = str(variable[-1] or "")
                elif isinstance(variable, str):
                    key = variable
                if key:
                    found[key] = value
            return found

        def _extract_enriched_payload(payload):
            candidates = []

            def _normalize_plan_value(value):
                if isinstance(value, str):
                    parsed = _try_parse_json_text(value)
                    if parsed is not None:
                        value = parsed
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
                if isinstance(value, dict):
                    nested_plan = (
                            value.get("allEnrichedEpisodePlan")
                            or value.get("enrichedEpisodePlan")
                            or value.get("all_enriched_episode_plan")
                            or value.get("enriched_episode_plan")
                    )
                    if nested_plan is not None:
                        nested = _normalize_plan_value(nested_plan)
                        if nested:
                            return nested
                    lowered = {str(key).lower() for key in value.keys()}
                    if lowered & {"episode", "episodenumber", "episode_number", "title", "specific_plot", "text_view", "ending_hook"}:
                        return [value]
                return []

            def _plan_text_from_items(plan, explicit_text=""):
                if isinstance(explicit_text, str) and explicit_text.strip():
                    return explicit_text.strip()
                parts = []
                for item in plan or []:
                    if not isinstance(item, dict):
                        continue
                    text = str(
                        item.get("text_view")
                        or item.get("textView")
                        or item.get("episode_text")
                        or item.get("episodeText")
                        or ""
                    ).strip()
                    if text:
                        parts.append(text)
                if parts:
                    return "\n\n".join(parts)
                return ""

            def visit(obj):
                if isinstance(obj, dict):
                    candidates.append(obj)
                    for text_key in ("answerText", "textOutput", "text", "content"):
                        parsed = _try_parse_json_text(obj.get(text_key))
                        if parsed is not None:
                            visit(parsed)
                    update_vars = _extract_update_vars(obj)
                    if update_vars:
                        candidates.append(update_vars)
                        for value in update_vars.values():
                            parsed = _try_parse_json_text(value)
                            if parsed is not None:
                                visit(parsed)
                    for key in (
                            "episodeplan",
                            "episodePlan",
                            "episode_plan",
                            "data",
                            "result",
                            "output",
                            "outputs",
                            "response",
                            "responseData",
                            "newVariables",
                            "variables",
                            "enrichedEpisodePlanResult",
                            "enriched_episode_plan_result",
                    ):
                        value = obj.get(key)
                        if isinstance(value, (dict, list)):
                            visit(value)
                        else:
                            parsed = _try_parse_json_text(value)
                            if parsed is not None:
                                visit(parsed)
                elif isinstance(obj, list):
                    candidates.append({"allEnrichedEpisodePlan": obj})
                    for item in obj:
                        visit(item)
                else:
                    parsed = _try_parse_json_text(obj)
                    if parsed is not None:
                        visit(parsed)

            visit(payload)

            for item in candidates:
                if not isinstance(item, dict):
                    continue
                plan_value = (
                        item.get("allEnrichedEpisodePlan")
                        or item.get("enrichedEpisodePlan")
                        or item.get("all_enriched_episode_plan")
                        or item.get("enriched_episode_plan")
                        or item.get("batchEnrichedEpisodePlan")
                        or item.get("batch_enriched_episode_plan")
                        or item.get("episodeplan")
                        or item.get("episodePlan")
                        or item.get("episode_plan")
                )
                text = (
                        item.get("allEnrichedEpisodePlanText")
                        or item.get("enrichedEpisodePlanText")
                        or item.get("all_enriched_episode_plan_text")
                        or item.get("enriched_episode_plan_text")
                        or ""
                )
                plan = _normalize_plan_value(plan_value)
                if not plan and isinstance(item, dict):
                    plan = _normalize_plan_value(item)
                if plan:
                    return plan, _plan_text_from_items(plan, str(text or ""))
            return None, ""

        asset_id = str((framework_asset or {}).get("asset_id") or data.get("framework_asset_id") or "").strip()
        if (
            isinstance(stage10_appearance_quality, dict)
            and stage10_appearance_quality.get("repaired")
            and asset_id
        ):
            _save_framework_to_script_stage(
                user_id=user_id,
                asset_id=asset_id,
                stage_key="stage09",
                output={"appearanceMapping": appearance_mapping},
            )
            logger.warning(
                "framework-to-script stage10 repaired cached stage09 appearanceMapping before 腾讯工作流 call: "
                "asset_id=%s repaired_characters=%s outfit_variants=%s",
                asset_id,
                stage10_appearance_quality.get("repaired_characters"),
                stage10_appearance_quality.get("outfit_variants"),
            )
        if not _try_begin_framework_stage(user_id, asset_id, "10"):
            return _json_error("10 正在运行中，请稍后刷新页面，已完成输出会自动恢复。", status=409)

        debug_record = {
            "stage": "10",
            "stage_name": "framework_enriched_episode_plan",
            "status": "started",
            "asset_id": asset_id,
            "request_payload_keys": sorted(data.keys()),
            "variable_keys": sorted(variables.keys()),
            "variable_size_summary": {
                key: {
                    "type": type(value).__name__,
                    "json_length": _stage10_json_len(value),
                    "preview": _stage12_debug_preview(value, limit=500),
                }
                for key, value in variables.items()
            },
            "has_frameworkPlanPackage": isinstance(variables.get("frameworkPlanPackage"), dict) and bool(
                variables.get("frameworkPlanPackage")),
            "has_sceneDictionary": isinstance(variables.get("sceneDictionary"), dict) and bool(
                variables.get("sceneDictionary")),
            "has_scriptWorldRulesDigest": isinstance(variables.get("scriptWorldRulesDigest"), dict) and bool(
                variables.get("scriptWorldRulesDigest")),
            "has_appearanceMapping": isinstance(variables.get("appearanceMapping"), dict) and bool(
                variables.get("appearanceMapping")),
            "appearance_mapping_quality": stage10_appearance_quality,
            "outfit_variants_count": stage10_appearance_quality.get("outfit_variants") if isinstance(stage10_appearance_quality, dict) else 0,
            "beat_count": len(beat_checkpoint_timeline) if isinstance(beat_checkpoint_timeline, list) else 0,
            "character_storyline_count": len(character_storylines) if isinstance(character_storylines, list) else 0,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        debug_path = _write_stage10_debug(debug_record)

        try:
            try:
                from .services.tencent_workflow_client import tencent_workflow_client
                from .services.workflow_contracts import STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN

                debug_record.update(
                    {
                        "status": "requesting_tencent",
                        "tencent_request_started_at": _now_iso(),
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage10_debug(debug_record)

                logger.info(
                    "framework-to-script stage10 entering 腾讯工作流: asset_id=%s stage_name=%s variable_keys=%s",
                    asset_id,
                    STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN,
                    sorted(variables.keys()),
                )

                started = time.monotonic()
                configured_batch_size = _positive_int(
                    os.getenv("TENCENT_WORKFLOW_10_BATCH_SIZE"),
                    8,
                )
                stage10_batch_size = min(max(configured_batch_size, 1), 10)
                if stage10_total_episodes > stage10_batch_size:
                    resume_path = _stage10_debug_dir(data, framework_asset) / "stage10_resume.json"
                    resume_fingerprint = stage10_input_fingerprint(
                        {
                            "asset_id": asset_id,
                            "total_episodes": stage10_total_episodes,
                            "batch_size": stage10_batch_size,
                            "variables": variables,
                        }
                    )
                    resume_state = load_stage10_resume(
                        resume_path,
                        fingerprint=resume_fingerprint,
                        asset_id=asset_id,
                        total_episodes=stage10_total_episodes,
                        batch_size=stage10_batch_size,
                    )
                    combined_plan_by_episode = dict((resume_state or {}).get("episodes") or {})
                    combined_text_by_batch = dict((resume_state or {}).get("text_by_batch") or {})
                    batch_debug = []
                    base_preference = _coerce_prompt_text(
                        variables.get("stagePreference")
                        or variables.get("stage_preference")
                        or variables.get("user_feedback")
                    )

                    for batch_start in range(1, stage10_total_episodes + 1, stage10_batch_size):
                        batch_end = min(stage10_total_episodes, batch_start + stage10_batch_size - 1)
                        expected_batch_numbers = list(range(batch_start, batch_end + 1))
                        if all(episode_no in combined_plan_by_episode for episode_no in expected_batch_numbers):
                            batch_debug.append(
                                {
                                    "start_episode": batch_start,
                                    "end_episode": batch_end,
                                    "received_episodes": expected_batch_numbers,
                                    "missing_episodes": [],
                                    "resumed_from_checkpoint": True,
                                }
                            )
                            debug_record.update(
                                {
                                    "status": "resuming_tencent_batches",
                                    "batch_size": stage10_batch_size,
                                    "batch_progress": batch_debug,
                                    "resume_path": str(resume_path),
                                    "updated_at": _now_iso(),
                                }
                            )
                            _write_stage10_debug(debug_record)
                            continue
                        batch_instruction = (
                            f"【系统分批输出指令】全剧共 {stage10_total_episodes} 集。"
                            f"本次只输出第 {batch_start}-{batch_end} 集，allEnrichedEpisodePlan 必须且只能包含这一区间，"
                            "不得从第1集重写，不得输出区间外集数。每集字段保持完整但文字精简，"
                            "最外层仍严格使用 allEnrichedEpisodePlan 和 allEnrichedEpisodePlanText，确保 JSON 完整闭合。"
                        )
                        batch_variables = copy.deepcopy(variables)
                        batch_variables["stagePreference"] = "\n\n".join(
                            item for item in (base_preference, batch_instruction) if item
                        )
                        batch_context = copy.deepcopy(stage10_framework_context)
                        batch_context.update(
                            {
                                "total_episodes": stage10_total_episodes,
                                "batch_start_episode": batch_start,
                                "batch_end_episode": batch_end,
                                "generation_instruction": batch_instruction,
                            }
                        )
                        batch_variables["frameworkPlanPackage"] = batch_context
                        batch_variables["framework_plan_package"] = batch_context
                        batch_output = tencent_workflow_client.run_stage(
                            STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN,
                            batch_variables,
                        )
                        batch_plan, batch_text = _extract_enriched_payload(batch_output)
                        batch_episode_numbers = []
                        for item in batch_plan or []:
                            if not isinstance(item, dict):
                                continue
                            raw_episode = (
                                item.get("episode")
                                or item.get("episodeNumber")
                                or item.get("episode_number")
                                or item.get("episode_no")
                            )
                            match = re.search(r"\d+", str(raw_episode or ""))
                            if not match:
                                continue
                            episode_no = int(match.group(0))
                            if batch_start <= episode_no <= batch_end:
                                item["episode"] = episode_no
                                combined_plan_by_episode[episode_no] = item
                                batch_episode_numbers.append(episode_no)
                        missing_batch_numbers = sorted(
                            set(expected_batch_numbers) - set(batch_episode_numbers)
                        )
                        batch_debug.append(
                            {
                                "start_episode": batch_start,
                                "end_episode": batch_end,
                                "received_episodes": sorted(set(batch_episode_numbers)),
                                "missing_episodes": missing_batch_numbers,
                            }
                        )
                        debug_record.update(
                            {
                                "status": "requesting_tencent_batches",
                                "batch_size": stage10_batch_size,
                                "batch_progress": batch_debug,
                                "updated_at": _now_iso(),
                            }
                        )
                        _write_stage10_debug(debug_record)
                        if missing_batch_numbers:
                            raise RuntimeError(
                                f"10 分批生成第 {batch_start}-{batch_end} 集不完整，"
                                f"缺少第 {missing_batch_numbers} 集。"
                            )
                        if str(batch_text or "").strip():
                            combined_text_by_batch[str(batch_start)] = str(batch_text).strip()
                        save_stage10_resume(
                            resume_path,
                            status="partial",
                            fingerprint=resume_fingerprint,
                            asset_id=asset_id,
                            total_episodes=stage10_total_episodes,
                            batch_size=stage10_batch_size,
                            episodes=combined_plan_by_episode,
                            text_by_batch=combined_text_by_batch,
                            updated_at=_now_iso(),
                        )

                    missing_all = sorted(
                        set(range(1, stage10_total_episodes + 1))
                        - set(combined_plan_by_episode)
                    )
                    if missing_all:
                        raise RuntimeError(f"10 分批合并后缺少第 {missing_all} 集。")
                    combined_plan = [
                        combined_plan_by_episode[index]
                        for index in range(1, stage10_total_episodes + 1)
                    ]
                    raw_output = {
                        "allEnrichedEpisodePlan": combined_plan,
                        "allEnrichedEpisodePlanText": "\n\n".join(
                            combined_text_by_batch[str(batch_start)]
                            for batch_start in range(1, stage10_total_episodes + 1, stage10_batch_size)
                            if str(combined_text_by_batch.get(str(batch_start)) or "").strip()
                        ),
                    }
                    save_stage10_resume(
                        resume_path,
                        status="completed",
                        fingerprint=resume_fingerprint,
                        asset_id=asset_id,
                        total_episodes=stage10_total_episodes,
                        batch_size=stage10_batch_size,
                        episodes=combined_plan_by_episode,
                        text_by_batch=combined_text_by_batch,
                        updated_at=_now_iso(),
                    )
                else:
                    raw_output = tencent_workflow_client.run_stage(
                        STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN,
                        variables,
                    )
                duration_ms = int((time.monotonic() - started) * 1000)

                tencent_debug_snapshot = _stage10_collect_tencent_debug_snapshot(
                    tencent_workflow_client,
                    STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN,
                )
                tencent_meta = tencent_debug_snapshot.get("meta") if isinstance(tencent_debug_snapshot, dict) else {}
                if not isinstance(tencent_meta, dict):
                    tencent_meta = {}

                debug_record.update(
                    {
                        "status": "tencent_returned",
                        "execute_id": tencent_meta.get("execute_id") or "",
                        "debug_url": tencent_meta.get("debug_url") or "",
                        "logid": tencent_meta.get("logid") or "",
                        "workflow_id": tencent_meta.get("workflow_id") or "",
                        "space_id": tencent_meta.get("space_id") or "",
                        "usage": tencent_meta.get("usage"),
                        "input_count": tencent_meta.get("input_count"),
                        "output_count": tencent_meta.get("output_count"),
                        "token_count": tencent_meta.get("token_count"),
                        "tencent_debug_info_keys": tencent_debug_snapshot.get("debug_info_keys") if isinstance(tencent_debug_snapshot, dict) else [],
                        "tencent_request_ended_at": _now_iso(),
                        "duration_ms": duration_ms,
                        "raw_output_summary": _stage12_debug_summary(raw_output, preview_limit=800),
                        "raw_output_keys": sorted(raw_output.keys()) if isinstance(raw_output, dict) else [],
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage10_debug(debug_record)

                logger.info(
                    "framework-to-script stage10 腾讯工作流 returned: asset_id=%s duration_ms=%s raw_type=%s raw_keys=%s execute_id=%s debug_url=%s",
                    asset_id,
                    duration_ms,
                    type(raw_output).__name__,
                    sorted(raw_output.keys()) if isinstance(raw_output, dict) else [],
                    tencent_meta.get("execute_id") or "",
                    tencent_meta.get("debug_url") or "",
                )
            except Exception as exc:
                debug_record.update(
                    {
                        "status": "failed",
                        "failure_phase": "tencent_call",
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                        "traceback": traceback.format_exc(),
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage10_debug(debug_record)
                try:
                    stage10_stage_name = (
                        STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN
                        if "STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN" in locals()
                        else "framework_enriched_episode_plan"
                    )
                    if "_stage10_collect_tencent_debug_snapshot" in locals():
                        tencent_debug_snapshot = _stage10_collect_tencent_debug_snapshot(
                            tencent_workflow_client if "tencent_workflow_client" in locals() else None,
                            stage10_stage_name,
                            exc,
                        )
                    else:
                        tencent_debug_snapshot = {}
                except Exception as debug_exc:
                    tencent_debug_snapshot = {
                        "debug_collect_error": f"{type(debug_exc).__name__}: {debug_exc}",
                        "exception_text": str(exc),
                    }

                tencent_meta = (
                    tencent_debug_snapshot.get("meta")
                    if isinstance(tencent_debug_snapshot, dict)
                    else {}
                )
                if not isinstance(tencent_meta, dict):
                    tencent_meta = {}

                try:
                    stage10_stage_name = (
                        STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN
                        if "STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN" in locals()
                        else "framework_enriched_episode_plan"
                    )

                    stage10_debug_info = {}
                    if "tencent_workflow_client" in locals() and hasattr(tencent_workflow_client, "get_last_stage_debug_info"):
                        maybe_debug = tencent_workflow_client.get_last_stage_debug_info(stage10_stage_name)
                        if isinstance(maybe_debug, dict):
                            stage10_debug_info = maybe_debug

                    tencent_raw_response = (
                        stage10_debug_info.get("raw_response")
                        if isinstance(stage10_debug_info, dict)
                        else None
                    )

                    raw_error_debug_path = _write_framework_to_script_raw_tencent_debug(
                        stage_no="10",
                        stage_name=stage10_stage_name,
                        variables=variables,
                        raw_output={
                            "exception_type": type(exc).__name__,
                            "exception_message": str(exc),
                            "traceback": traceback.format_exc(),
                            "last_stage_debug_info": stage10_debug_info,
                            "tencent_raw_response": tencent_raw_response,
                        },
                        parsed_output={},
                        error=str(exc),
                    )

                    debug_record["tencent_raw_error_debug_path"] = raw_error_debug_path
                    debug_record["tencent_last_stage_debug"] = stage10_debug_info
                    debug_path = _write_stage10_debug(debug_record)
                except Exception as raw_debug_exc:
                    logger.exception(
                        "framework-to-script stage10 raw debug write failed after 腾讯工作流 error: %s",
                        raw_debug_exc,
                    )
                logger.exception("framework-to-script stage10 腾讯工作流 call failed: asset_id=%s", asset_id)
                return _json_error(
                    str(exc),
                    status=500,
                    fallback="10 分集细化方案调用失败，请检查 腾讯工作流 token 和工作流变量。",
                )

            plan, plan_text = _extract_enriched_payload(raw_output)
            _write_stage10_raw_debug(
                raw_output=raw_output,
                parsed_output={
                    "allEnrichedEpisodePlan": plan or [],
                    "allEnrichedEpisodePlanText": plan_text or "",
                },
                tencent_debug_snapshot=tencent_debug_snapshot if "tencent_debug_snapshot" in locals() else {},
                tencent_meta=tencent_meta if "tencent_meta" in locals() else {},
            )

            debug_record.update(
                {
                    "status": "parsed",
                    "plan_type": type(plan).__name__,
                    "plan_count": len(plan) if isinstance(plan, list) else 0,
                    "plan_text_length": len(plan_text or ""),
                    "updated_at": _now_iso(),
                }
            )
            debug_path = _write_stage10_debug(debug_record)

            if not plan:
                debug_record.update(
                    {
                        "status": "failed",
                        "failure_phase": "parse",
                        "exception_message": "10 分集细化方案输出缺少 allEnrichedEpisodePlan。",
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage10_debug(debug_record)
                return _json_error(
                    "10 分集细化方案输出缺少 allEnrichedEpisodePlan。",
                    status=500,
                    fallback="请检查 10 工作流是否把 allEnrichedEpisodePlan 写入变量或 answerText JSON。",
                )

            if asset_id:
                _save_framework_to_script_stage(
                    user_id=user_id,
                    asset_id=asset_id,
                    stage_key="stage10",
                    output={
                        "framework_enriched_episode_plan": {
                            "allEnrichedEpisodePlan": plan,
                            "allEnrichedEpisodePlanText": plan_text,
                            "batchEnrichedEpisodePlan": plan,
                        },
                        "allEnrichedEpisodePlan": plan,
                        "allEnrichedEpisodePlanText": plan_text,
                        "batchEnrichedEpisodePlan": plan,
                        "enrichedEpisodePlan": plan,
                        "enrichedEpisodePlanText": plan_text,
                    },
                )
                debug_record.update(
                    {
                        "status": "success",
                        "saved": True,
                        "plan_count": len(plan) if isinstance(plan, list) else 0,
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage10_debug(debug_record)
        finally:
            _end_framework_stage(user_id, asset_id, "10")

        return _json_ok(
            stage="10",
            framework_asset_id=asset_id,
            framework_enriched_episode_plan={
                "allEnrichedEpisodePlan": plan,
                "allEnrichedEpisodePlanText": plan_text,
                "batchEnrichedEpisodePlan": plan,
            },
            allEnrichedEpisodePlan=plan,
            allEnrichedEpisodePlanText=plan_text,
            batchEnrichedEpisodePlan=plan,
            enrichedEpisodePlan=plan,
            enrichedEpisodePlanText=plan_text,
            stageOutputs={
                "framework_enriched_episode_plan": {
                    "allEnrichedEpisodePlan": plan,
                    "allEnrichedEpisodePlanText": plan_text,
                    "batchEnrichedEpisodePlan": plan,
                },
                "allEnrichedEpisodePlan": plan,
                "allEnrichedEpisodePlanText": plan_text,
                "batchEnrichedEpisodePlan": plan,
            },
            stages={"10": {"status": "completed"}},
            completedStages=["10"],
        )

    @app.post("/api/framework-to-script/stage/11")
    @_login_required
    def run_framework_to_script_stage11_api():
        """单独运行 11 当前批次因果冲突：write -> review -> rewrite(必要时) -> memory。"""
        import json as _json

        def _stage11_debug_dir(data: dict, framework_asset: dict | None) -> Path:
            title = _stage12_debug_project_title(data, framework_asset)
            path = (
                    _writable_root()
                    / "cache"
                    / _stage12_debug_safe_name(title)
                    / "framework_to_script"
                    / "stage11"
            )
            path.mkdir(parents=True, exist_ok=True)
            return path

        def _stage11_raw_debug_dir() -> Path:
            path = _writable_root() / "cache" / "raw_tencent_debug"
            path.mkdir(parents=True, exist_ok=True)
            return path

        def _stage11_json_len(value) -> int:
            try:
                return len(_json.dumps(value, ensure_ascii=False, default=str))
            except Exception:
                return -1

        def _write_stage11_debug(record: dict, *, filename: str | None = None) -> str:
            try:
                start = record.get("start_episode") or "unknown"
                path = _stage11_debug_dir(data, framework_asset) / (filename or f"stage11_batch_{start}_latest.json")
                public_record = {
                    key: value
                    for key, value in record.items()
                    if not str(key).startswith("_")
                }
                public_record["debug_path"] = str(path)
                path.write_text(
                    _json.dumps(public_record, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                return str(path)
            except Exception:
                logger.exception("framework-to-script stage11 debug file write failed")
                return ""

        def _write_stage11_raw_debug(
                *,
                sub_stage: str,
                stage_name: str,
                variables: dict,
                raw_output=None,
                parsed_output=None,
                error: str = "",
                review_round=None,
                rewrite_round=None,
        ) -> str:
            try:
                debug_dir = _stage11_raw_debug_dir()
                latest_path = debug_dir / f"stage11_{sub_stage}_raw_response.json"
                generic_latest_path = debug_dir / "stage11_raw_response.json"
                created_at = _now_iso()
                timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S-%f")[:-3]

                def _filename_part(value, *, prefix: str = "") -> str:
                    text = str(value if value is not None and value != "" else "unknown").strip() or "unknown"
                    text = _stage12_debug_safe_name(text).replace(" ", "_")
                    return f"{prefix}{text}" if prefix else text

                def _round_part(value, label: str) -> str:
                    try:
                        number = int(value)
                    except Exception:
                        return f"{label}unknown"
                    return f"{label}{number:02d}"

                debug_start_episode = _positive_int(
                    (variables or {}).get("conflictStartEpisode")
                    or (variables or {}).get("conflict_start_episode"),
                    start_episode,
                )
                debug_batch_plan = (
                    (variables or {}).get("batchEnrichedEpisodePlan")
                    or (variables or {}).get("batch_enriched_episode_plan")
                    or []
                )
                debug_end_episode = stage11_episode_number(
                    debug_batch_plan[-1] if isinstance(debug_batch_plan, list) and debug_batch_plan else {},
                    debug_start_episode,
                )
                history_filename = "_".join(
                    [
                        "stage11",
                        _filename_part(sub_stage),
                        _filename_part(asset_id if "asset_id" in locals() else "", prefix="asset"),
                        (
                            f"ep{int(debug_start_episode):03d}-{int(debug_end_episode):03d}"
                            if "start_episode" in locals() and "end_episode" in locals()
                            else "epunknown"
                        ),
                        _round_part(review_round, "review"),
                        _round_part(rewrite_round, "rewrite"),
                        timestamp,
                        "raw_response.json",
                    ]
                )
                history_path = debug_dir / history_filename
                payload = {
                    "stage": "11",
                    "sub_stage": sub_stage,
                    "stage_name": stage_name,
                    "backend": "tencent",
                    "asset_id": asset_id if "asset_id" in locals() else "",
                    "start_episode": start_episode if "start_episode" in locals() else None,
                    "end_episode": end_episode if "end_episode" in locals() else None,
                    "request_start_episode": debug_start_episode,
                    "request_end_episode": debug_end_episode,
                    "review_round": review_round,
                    "rewrite_round": rewrite_round,
                    "created_at": created_at,
                    "latest_path": str(latest_path),
                    "history_path": str(history_path),
                    "variable_keys": sorted(variables.keys()) if isinstance(variables, dict) else [],
                    "variable_size_summary": {
                        key: {
                            "type": type(value).__name__,
                            "json_length": _stage11_json_len(value),
                            "preview": _stage12_debug_preview(value, limit=500),
                        }
                        for key, value in (variables.items() if isinstance(variables, dict) else [])
                    },
                    "raw_output_type": type(raw_output).__name__,
                    "raw_output_keys": sorted(raw_output.keys()) if isinstance(raw_output, dict) else [],
                    "raw_output": raw_output,
                    "parsed_output": parsed_output,
                    "error": error,
                }
                latest_path.write_text(
                    _json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                generic_latest_path.write_text(
                    _json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                history_path.write_text(
                    _json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                index_record = {
                    "created_at": created_at,
                    "asset_id": payload.get("asset_id"),
                    "stage": "11",
                    "sub_stage": sub_stage,
                    "stage_name": stage_name,
                    "start_episode": payload.get("start_episode"),
                    "end_episode": payload.get("end_episode"),
                    "review_round": review_round,
                    "rewrite_round": rewrite_round,
                    "latest_path": str(latest_path),
                    "generic_latest_path": str(generic_latest_path),
                    "history_path": str(history_path),
                    "error": error,
                }
                with (debug_dir / "stage11_debug_index.jsonl").open("a", encoding="utf-8") as index_file:
                    index_file.write(_json.dumps(index_record, ensure_ascii=False, default=str) + "\n")
                try:
                    _stage11_set_run(
                        raw_debug_paths=[str(latest_path), str(generic_latest_path)],
                        history_debug_paths=[str(history_path)],
                        latest_result_preview={
                            "sub_stage": sub_stage,
                            "latest_path": str(latest_path),
                            "history_path": str(history_path),
                        },
                    )
                except Exception:
                    logger.exception("framework-to-script stage11 run debug path update failed")

                logger.warning(
                    "[framework_to_script_raw_debug] wrote stage11 %s raw 腾讯工作流 response path=%s",
                    sub_stage,
                    latest_path,
                )
                return str(latest_path)
            except Exception:
                logger.exception("[framework_to_script_raw_debug] failed to write stage11 raw response")
                return ""

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _json_error("请求体必须是 JSON object。", status=400)

        try:
            user_id = _require_user_id()
            data, framework_asset = _inject_framework_asset(data, user_id)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        locked_response = _framework_to_script_locked_error(framework_asset)
        if locked_response:
            return locked_response

        framework_plan_package = (
                data.get("framework_plan_package")
                or data.get("frameworkPlanPackage")
                or {}
        )
        stage10 = _framework_script_stage_cache(framework_asset, "stage10")
        plan = (
                data.get("allEnrichedEpisodePlan")
                or data.get("enrichedEpisodePlan")
                or stage10.get("allEnrichedEpisodePlan")
                or stage10.get("enrichedEpisodePlan")
                or []
        )
        if not isinstance(plan, list) or not plan:
            return _json_error("缺少 allEnrichedEpisodePlan，请先完成 10 分集细化方案。", status=400)

        stage08 = _framework_script_stage_cache(framework_asset, "stage08")
        stage09 = _framework_script_stage_cache(framework_asset, "stage09")
        scene_dictionary = data.get("sceneDictionary") or stage08.get("sceneDictionary") or {}
        rules_digest = data.get("scriptWorldRulesDigest") or stage08.get("scriptWorldRulesDigest") or {}
        appearance_mapping = data.get("appearanceMapping") or stage09.get("appearanceMapping") or {}

        if not isinstance(scene_dictionary, dict) or not scene_dictionary:
            return _json_error("缺少 sceneDictionary，请先完成 08 核心场景提炼。", status=400)
        if not isinstance(appearance_mapping, dict) or not appearance_mapping:
            return _json_error("缺少 appearanceMapping，请先完成 09 角色外观匹配场景。", status=400)
        if not isinstance(rules_digest, dict) or not rules_digest:
            return _json_error("缺少 scriptWorldRulesDigest，请先完成 08 核心场景提炼。", status=400)

        existing_stage11 = _framework_script_stage_cache(framework_asset, "stage11")
        existing_batches = existing_stage11.get("batches") if isinstance(existing_stage11.get("batches"), dict) else {}

        reset_stage11 = bool(data.get("reset_stage11") or data.get("resetStage11"))
        if reset_stage11:
            existing_batches = {}
            existing_stage11 = {}
            reset_asset_id = str(
                (framework_asset or {}).get("asset_id") or data.get("framework_asset_id") or "").strip()
            if reset_asset_id:
                _save_framework_to_script_stage(
                    user_id=user_id,
                    asset_id=reset_asset_id,
                    stage_key="stage12",
                    output={"batches": {}},
                )
        else:
            valid_existing_batches = {}
            for existing_key, existing_batch in existing_batches.items():
                if not isinstance(existing_batch, dict):
                    continue
                existing_start = _positive_int(
                    existing_batch.get("batchStartEpisode") or existing_key,
                    _positive_int(existing_key, 1),
                )
                existing_end = _positive_int(existing_batch.get("batchEndEpisode"), existing_start + 4)
                existing_plan, _ = _unwrap_dict_alias(
                    existing_batch,
                    "batchCausalConflictPlan",
                    "batch_causal_conflict_plan",
                )
                existing_issues = _validate_stage11_causal_conflict_plan(
                    existing_plan,
                    start_episode=existing_start,
                    end_episode=existing_end,
                )
                existing_review = _first_present(
                    existing_batch,
                    "batchCausalConflictReview",
                    "batch_causal_conflict_review",
                    default=None,
                )
                existing_memory = _first_present(
                    existing_batch,
                    "conflictMemory",
                    "conflict_memory",
                    default=None,
                )
                if not _framework_value_present(existing_review) or not _framework_value_present(existing_memory):
                    existing_issues.append("batch pipeline incomplete: missing review or memory")
                if existing_issues:
                    logger.warning(
                        "framework-to-script stage11 dropping invalid cached batch before retry: "
                        "asset_id=%s batchStartEpisode=%s batchEndEpisode=%s reason=%s",
                        str((framework_asset or {}).get("asset_id") or data.get("framework_asset_id") or "").strip(),
                        existing_start,
                        existing_end,
                        "; ".join(existing_issues[:8]),
                    )
                    continue
                valid_existing_batches[str(existing_start)] = existing_batch
            existing_batches = valid_existing_batches

        start_episode, end_episode, batch_plan = _framework_batch_from_plan(
            plan,
            data.get("batchStartEpisode") or data.get("batch_start_episode"),
            completed_starts=existing_batches.keys(),
        )
        if not batch_plan:
            return _json_error("当前批次缺少 batchEnrichedEpisodePlan，请检查 10 输出集数。", status=400)

        asset_id = str((framework_asset or {}).get("asset_id") or data.get("framework_asset_id") or "").strip()
        stage11_worker_run_id = str(data.get("_stage11_run_id") or "").strip()
        stage11_worker_token = str(data.get("_stage11_worker_token") or "").strip()
        stage11_worker_requested = str(request.headers.get("X-Framework-Stage11-Worker") or "").strip() == "1"
        is_stage11_worker = stage11_worker_requested and _framework_stage_worker_allowed(
            run_id=stage11_worker_run_id,
            worker_token=stage11_worker_token,
            user_id=user_id,
            asset_id=asset_id,
            stage="11",
        )
        if stage11_worker_requested and not is_stage11_worker:
            return _json_error("无效的 11 阶段后台运行请求。", status=403)

        def _stage11_set_run(**updates) -> dict:
            if not is_stage11_worker or not stage11_worker_run_id:
                return {}
            try:
                return _update_framework_stage_run(run_id=stage11_worker_run_id, **updates)
            except Exception:
                logger.exception("framework-to-script stage11 run state update failed")
                return {}

        if not is_stage11_worker and asset_id:
            requested_start = data.get("batchStartEpisode") or data.get("batch_start_episode")
            expected_starts = _sorted_numeric_batch_keys(
                {
                    str(_positive_int(
                        item.get("episode")
                        or item.get("episodeNumber")
                        or item.get("episode_number")
                        or item.get("ep")
                        or index,
                        index,
                    ) - 1 - ((_positive_int(
                        item.get("episode")
                        or item.get("episodeNumber")
                        or item.get("episode_number")
                        or item.get("ep")
                        or index,
                        index,
                    ) - 1) % 5) + 1): True
                    for index, item in enumerate(plan, start=1)
                    if isinstance(item, dict)
                }
            )
            if requested_start:
                expected_starts = [str(start_episode)]
            run, created = _begin_or_get_framework_stage_run(
                user_id=user_id,
                asset_id=asset_id,
                stage="11",
                current_sub_stage="stage11_prepare",
                progress_text=f"第 11 阶段准备运行：第 {start_episode}-{end_episode} 集",
                latest_partial_result={
                    "start_episode": start_episode,
                    "end_episode": end_episode,
                    "expected_batch_starts": expected_starts,
                    "completed_batch_starts": _sorted_numeric_batch_keys(existing_batches),
                },
                retain_completed=True,
            )
            if not created:
                return jsonify({"success": True, "existing": True, "run": run}), 202

            private_run = _framework_stage_run_private(str(run.get("run_id") or ""))
            worker_token = str(private_run.get("worker_token") or "")
            worker_payload = copy.deepcopy(data)
            worker_payload["_stage11_run_id"] = str(run.get("run_id") or "")
            worker_payload["_stage11_worker_token"] = worker_token
            auth_token = _current_auth_token()

            def _stage11_worker_loop() -> None:
                run_id = str(run.get("run_id") or "")
                latest_result = {}
                conflict_memory_value = worker_payload.get("conflictMemory") or worker_payload.get("conflict_memory") or ""
                try:
                    _update_framework_stage_run(
                        run_id=run_id,
                        status="running",
                        current_sub_stage="stage11_prepare",
                        progress_text=f"第 11 阶段后台运行中：第 {start_episode}-{end_episode} 集",
                    )
                    first_request = True
                    guard = 0
                    completed_starts = set(_sorted_numeric_batch_keys(existing_batches))
                    batch_auto_retry_counts = {}
                    max_batch_auto_retries = min(
                        max(_positive_int(os.getenv("TENCENT_WORKFLOW_11_BATCH_MAX_AUTO_RETRIES"), 2), 0),
                        5,
                    )
                    while guard < 200:
                        guard += 1
                        request_payload = copy.deepcopy(worker_payload)
                        request_payload["reset_stage11"] = bool(reset_stage11 and first_request)
                        request_payload["resetStage11"] = bool(reset_stage11 and first_request)
                        if conflict_memory_value:
                            request_payload["conflictMemory"] = conflict_memory_value
                        elif not first_request:
                            request_payload.pop("conflictMemory", None)
                            request_payload.pop("conflict_memory", None)
                        path = "/api/framework-to-script/stage/11"
                        if auth_token:
                            path = f"{path}?auth_token={quote(auth_token)}"
                        with app.app_context():
                            with app.test_client() as worker_client:
                                response = worker_client.post(
                                    path,
                                    headers={"X-Framework-Stage11-Worker": "1"},
                                    json=request_payload,
                                )
                                response_data = response.get_json(silent=True) or {}
                        latest_result = response_data if isinstance(response_data, dict) else {}
                        if response.status_code >= 400 or latest_result.get("success") is False:
                            detail = latest_result.get("detail") if isinstance(latest_result.get("detail"), dict) else {}
                            message = (
                                detail.get("error_message")
                                or detail.get("message")
                                or latest_result.get("message")
                                or latest_result.get("error")
                                or f"stage11 worker returned HTTP {response.status_code}"
                            )
                            next_missing_start = next(
                                (key for key in expected_starts if key not in completed_starts),
                                str(detail.get("start_episode") or start_episode),
                            )
                            failed_batch_start = str(
                                detail.get("start_episode")
                                or detail.get("batchStartEpisode")
                                or next_missing_start
                            )
                            batch_retry_count = int(batch_auto_retry_counts.get(failed_batch_start) or 0) + 1
                            batch_auto_retry_counts[failed_batch_start] = batch_retry_count
                            if batch_retry_count <= max_batch_auto_retries:
                                logger.warning(
                                    "framework-to-script stage11 batch auto retry: asset_id=%s "
                                    "batch_start=%s retry=%s/%s reason=%s",
                                    asset_id,
                                    failed_batch_start,
                                    batch_retry_count,
                                    max_batch_auto_retries,
                                    message,
                                )
                                _update_framework_stage_run(
                                    run_id=run_id,
                                    status="running",
                                    current_sub_stage="stage11_batch_auto_retry",
                                    progress_text=(
                                        f"第 11 阶段第 {failed_batch_start} 集起批次暂时失败，"
                                        f"正在自动恢复 {batch_retry_count}/{max_batch_auto_retries}"
                                    ),
                                    latest_error="",
                                    latest_partial_result={
                                        "failed_batch_start": failed_batch_start,
                                        "batch_auto_retry_count": batch_retry_count,
                                        "batch_auto_retry_limit": max_batch_auto_retries,
                                        "completed_batch_starts": sorted(
                                            completed_starts,
                                            key=lambda item: int(item) if str(item).isdigit() else 999,
                                        ),
                                        "expected_batch_starts": expected_starts,
                                    },
                                )
                                first_request = False
                                time.sleep(min(batch_retry_count, 2))
                                continue
                            _finish_framework_stage_run(
                                run_id=run_id,
                                status="failed",
                                progress_text="第 11 阶段运行失败",
                                latest_error=str(message),
                                latest_result_preview=latest_result,
                            )
                            return
                        batches = latest_result.get("batches") if isinstance(latest_result.get("batches"), dict) else {}
                        completed_starts = set(_sorted_numeric_batch_keys(batches))
                        completed_batch_start = str(latest_result.get("batchStartEpisode") or "")
                        if completed_batch_start:
                            batch_auto_retry_counts.pop(completed_batch_start, None)
                        conflict_memory_value = str(
                            latest_result.get("conflictMemory")
                            or latest_result.get("conflict_memory")
                            or conflict_memory_value
                            or ""
                        )
                        missing = [key for key in expected_starts if key not in completed_starts]
                        latest_partial = {
                            "start_episode": latest_result.get("batchStartEpisode") or start_episode,
                            "end_episode": latest_result.get("batchEndEpisode") or end_episode,
                            "completed_batch_starts": sorted(completed_starts, key=lambda item: int(item) if str(item).isdigit() else 999),
                            "expected_batch_starts": expected_starts,
                            "remaining_batch_starts": missing,
                            "latest_batch_done": latest_result.get("batchStartEpisode"),
                        }
                        _update_framework_stage_run(
                            run_id=run_id,
                            status="running",
                            current_sub_stage="stage11_batch_saved",
                            progress_text=(
                                f"第 11 阶段已保存第 {latest_partial['start_episode']}-{latest_partial['end_episode']} 集，"
                                f"进度 {len(completed_starts)}/{len(expected_starts) or '?'}"
                            ),
                            latest_partial_result=latest_partial,
                            latest_result_preview={
                                "batchStartEpisode": latest_result.get("batchStartEpisode"),
                                "batchEndEpisode": latest_result.get("batchEndEpisode"),
                                "batches": sorted(completed_starts, key=lambda item: int(item) if str(item).isdigit() else 999),
                            },
                        )
                        if not missing:
                            break
                        first_request = False
                    else:
                        _finish_framework_stage_run(
                            run_id=run_id,
                            status="failed",
                            progress_text="第 11 阶段运行超出批次数保护上限",
                            latest_error="stage11 worker exceeded batch guard limit",
                            latest_result_preview=latest_result,
                        )
                        return
                    _finish_framework_stage_run(
                        run_id=run_id,
                        status="succeeded",
                        progress_text="第 11 阶段已完成",
                        latest_result_preview={
                            "batchStartEpisode": latest_result.get("batchStartEpisode"),
                            "batchEndEpisode": latest_result.get("batchEndEpisode"),
                            "completed_batch_starts": sorted(completed_starts, key=lambda item: int(item) if str(item).isdigit() else 999),
                        },
                        latest_partial_result={
                            "completed_batch_starts": sorted(completed_starts, key=lambda item: int(item) if str(item).isdigit() else 999),
                            "expected_batch_starts": expected_starts,
                            "remaining_batch_starts": [],
                        },
                    )
                except Exception as exc:
                    logger.exception("framework-to-script stage11 background worker failed")
                    _finish_framework_stage_run(
                        run_id=run_id,
                        status="failed",
                        progress_text="第 11 阶段后台运行失败",
                        latest_error=str(exc),
                    )

            thread = threading.Thread(
                target=_stage11_worker_loop,
                name=f"framework-stage11-{run.get('run_id')}",
                daemon=True,
            )
            thread.start()
            run = _update_framework_stage_run(
                run_id=str(run.get("run_id") or ""),
                status="running",
                current_sub_stage="stage11_prepare",
                progress_text=f"第 11 阶段已开始后台运行：第 {start_episode}-{end_episode} 集",
            )
            return jsonify({"success": True, "accepted": True, "run": run}), 202

        if not is_stage11_worker and not _try_begin_framework_stage(user_id, asset_id, "11"):
            return _json_error("11 正在运行中，请稍后刷新页面，已完成输出会自动恢复。", status=409)

        debug_record = {
            "stage": "11",
            "stage_name": "framework_causal_conflict_plan",
            "status": "started",
            "asset_id": asset_id,
            "start_episode": start_episode,
            "end_episode": end_episode,
            "batch_plan_count": len(batch_plan) if isinstance(batch_plan, list) else 0,
            "events": [],
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        debug_path = _write_stage11_debug(debug_record)
        _stage11_set_run(
            status="running",
            current_sub_stage="stage11_prepare",
            progress_text=f"第 11 阶段准备中：第 {start_episode}-{end_episode} 集",
            latest_partial_result={
                "start_episode": start_episode,
                "end_episode": end_episode,
            },
        )

        try:
            failed_sub_stage = "stage11_prepare"
            base_vars = {}
            total_episodes = 0

            try:
                from .services.workflow_errors import WorkflowStageFormatError
                from .services.tencent_workflow_client import tencent_workflow_client
                from .services.workflow_contracts import (
                    STAGE_FRAMEWORK_CAUSAL_CONFLICT_MEMORY,
                    STAGE_FRAMEWORK_CAUSAL_CONFLICT_REVIEW,
                    STAGE_FRAMEWORK_CAUSAL_CONFLICT_REWRITE,
                    STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE,
                )

                total_episodes = _positive_int(
                    data.get("total_episodes") or (framework_asset or {}).get("episodes_per_season"),
                    len(plan),
                )
                conflict_memory = str(
                    _first_present(data, "conflictMemory", "conflict_memory", default=None)
                    or _first_present(existing_stage11, "conflictMemory", "conflict_memory", default="")
                    or ""
                )
                if reset_stage11:
                    conflict_memory = ""

                base_vars = {
                    **_framework_context_vars(data, framework_plan_package),
                    "totalEpisodes": total_episodes,
                    "conflictStartEpisode": start_episode,
                    "batchEnrichedEpisodePlan": batch_plan,
                    "sceneDictionary": scene_dictionary,
                    "appearanceMapping": appearance_mapping,
                    "scriptWorldRulesDigest": rules_digest,
                    "conflictMemory": conflict_memory,
                }
                _merge_aliases(
                    base_vars,
                    {
                        "totalEpisodes": ("total_episodes",),
                        "conflictMemory": ("conflict_memory",),
                        "batchEnrichedEpisodePlan": ("batch_enriched_episode_plan",),
                        "sceneDictionary": ("scene_dictionary",),
                        "appearanceMapping": ("appearance_mapping",),
                        "scriptWorldRulesDigest": ("script_world_rules_digest",),
                    },
                )
                base_vars = _inject_snapshot_stage_preference(
                    base_vars,
                    data,
                    "11",
                    framework_asset=framework_asset,
                    workflow_stage="11_write",
                )

                debug_record.update(
                    {
                        "status": "prepared",
                        "base_vars_keys": sorted(base_vars.keys()),
                        "base_vars_size_summary": {
                            key: {
                                "type": type(value).__name__,
                                "json_length": _stage11_json_len(value),
                                "preview": _stage12_debug_preview(value, limit=500),
                            }
                            for key, value in base_vars.items()
                        },
                        "total_episodes": total_episodes,
                        "conflictMemory_length": len(conflict_memory),
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage11_debug(debug_record)

                first_batch_item = batch_plan[0] if batch_plan and isinstance(batch_plan[0], dict) else {}
                appearance_characters = appearance_mapping.get("characters") if isinstance(appearance_mapping,
                                                                                           dict) else []
                appearance_character_count = (
                    len(appearance_characters)
                    if isinstance(appearance_characters, list)
                    else len(appearance_mapping)
                    if isinstance(appearance_mapping, dict)
                    else 0
                )

                logger.info(
                    "framework-to-script stage11 start: asset_id=%s start_episode=%s end_episode=%s "
                    "batch_plan_count=%s total_episodes=%s has_sceneDictionary=%s "
                    "has_scriptWorldRulesDigest=%s has_appearanceMapping=%s appearanceMapping.characters_count=%s "
                    "first_batch_episode=%s first_batch_title=%s first_batch_characters=%s stage_names=%s",
                    asset_id,
                    start_episode,
                    end_episode,
                    len(batch_plan),
                    total_episodes,
                    bool(scene_dictionary),
                    bool(rules_digest),
                    bool(appearance_mapping),
                    appearance_character_count,
                    first_batch_item.get("episode"),
                    first_batch_item.get("title"),
                    first_batch_item.get("characters"),
                    {
                        "write": STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE,
                        "review": STAGE_FRAMEWORK_CAUSAL_CONFLICT_REVIEW,
                        "rewrite": STAGE_FRAMEWORK_CAUSAL_CONFLICT_REWRITE,
                        "memory": STAGE_FRAMEWORK_CAUSAL_CONFLICT_MEMORY,
                    },
                )

                failed_sub_stage = "causal_conflict_write"
                write_output_data = {}
                conflict_plan = {}
                conflict_plan_unwrapped = False
                write_failure_reason = ""
                write_output_keys = []
                write_retry_count = 0
                max_write_retries = min(
                    max(_positive_int(os.getenv("TENCENT_WORKFLOW_11_WRITE_MAX_RETRIES"), 5), 1),
                    7,
                )
                write_chunk_size = min(
                    max(_positive_int(os.getenv("TENCENT_WORKFLOW_11_WRITE_CHUNK_SIZE"), 1), 1),
                    2,
                )
                write_chunks = split_episode_plan(batch_plan, write_chunk_size)
                chunk_conflict_plans = []
                chunk_failed = False
                write_output_key_set = set()
                write_resume_path = (
                    _stage11_debug_dir(data, framework_asset)
                    / f"stage11_batch_{start_episode}_write_checkpoint.json"
                )
                write_resume_fingerprint = stage11_input_fingerprint(batch_plan)
                resumed_chunk_plans = {} if reset_stage11 else load_stage11_write_resume(
                    write_resume_path,
                    fingerprint=write_resume_fingerprint,
                    asset_id=asset_id,
                    start_episode=start_episode,
                    end_episode=end_episode,
                )
                if reset_stage11:
                    try:
                        write_resume_path.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("framework-to-script stage11 checkpoint cleanup failed: %s", write_resume_path)

                for chunk_index, write_chunk in enumerate(write_chunks, start=1):
                    chunk_start = stage11_episode_number(
                        write_chunk[0] if write_chunk else {},
                        start_episode + (chunk_index - 1) * write_chunk_size,
                    )
                    chunk_end = stage11_episode_number(
                        write_chunk[-1] if write_chunk else {},
                        chunk_start,
                    )
                    chunk_plan = {}
                    chunk_unwrapped = False
                    chunk_failure_reason = ""
                    chunk_instruction = (
                        f"【系统分段生成指令】当前批次原范围为第 {start_episode}-{end_episode} 集；"
                        f"本次只生成第 {chunk_start}-{chunk_end} 集。episodes 必须且只能覆盖这一小段。"
                        "请把合法 JSON 直接写入 Content，严禁只在 Thought 中推演后令 Content 为空。"
                    )
                    chunk_vars = copy.deepcopy(base_vars)
                    chunk_vars.update(
                        {
                            "conflictStartEpisode": chunk_start,
                            "conflict_start_episode": chunk_start,
                            "batchEnrichedEpisodePlan": write_chunk,
                            "batch_enriched_episode_plan": write_chunk,
                        }
                    )
                    chunk_character_names = [
                        name
                        for item in write_chunk
                        if isinstance(item, dict)
                        for name in (item.get("characters") or [])
                        if str(name or "").strip()
                    ]
                    compact_write_aliases = compact_appearance_mapping(
                        appearance_mapping,
                        relevant_names=chunk_character_names,
                    )
                    chunk_vars["appearanceMapping"] = compact_write_aliases
                    chunk_vars["appearance_mapping"] = compact_write_aliases
                    chunk_preference = _coerce_prompt_text(
                        chunk_vars.get("stagePreference")
                        or chunk_vars.get("stage_preference")
                        or chunk_vars.get("user_feedback")
                    )
                    chunk_preference = "\n\n".join(
                        item for item in (chunk_preference, chunk_instruction) if item
                    )
                    chunk_vars["stagePreference"] = chunk_preference
                    chunk_vars["stage_preference"] = chunk_preference
                    chunk_vars["user_feedback"] = chunk_preference

                    resumed_plan = resumed_chunk_plans.get(chunk_start)
                    if isinstance(resumed_plan, dict) and resumed_plan:
                        resume_issues = _validate_stage11_causal_conflict_plan(
                            resumed_plan,
                            start_episode=chunk_start,
                            end_episode=chunk_end,
                        )
                        if not resume_issues:
                            chunk_conflict_plans.append(resumed_plan)
                            write_output_key_set.add("batchCausalConflictPlan")
                            debug_record["events"].append(
                                {
                                    "sub_stage": "causal_conflict_write",
                                    "chunk_index": chunk_index,
                                    "chunk_start_episode": chunk_start,
                                    "chunk_end_episode": chunk_end,
                                    "status": "resumed_from_checkpoint",
                                    "ended_at": _now_iso(),
                                }
                            )
                            debug_record.update(
                                {
                                    "status": "write_chunk_resumed",
                                    "write_chunk_size": write_chunk_size,
                                    "write_chunk_count": len(write_chunks),
                                    "current_write_chunk": chunk_index,
                                    "resumed_write_chunks": len(chunk_conflict_plans),
                                    "updated_at": _now_iso(),
                                }
                            )
                            _write_stage11_debug(debug_record)
                            _stage11_set_run(
                                status="running",
                                current_sub_stage="causal_conflict_write",
                                progress_text=(
                                    f"第 11 阶段续跑：已恢复第 {chunk_start}-{chunk_end} 集 "
                                    f"（分段 {chunk_index}/{len(write_chunks)}）"
                                ),
                                latest_partial_result={
                                    "sub_stage": "write_chunk_resume",
                                    "start_episode": start_episode,
                                    "end_episode": end_episode,
                                    "current_chunk_start": chunk_start,
                                    "current_chunk_end": chunk_end,
                                    "completed_write_chunks": len(chunk_conflict_plans),
                                    "total_write_chunks": len(write_chunks),
                                },
                            )
                            continue
                        resumed_chunk_plans.pop(chunk_start, None)

                    for retry_count in range(max_write_retries + 1):
                        if retry_count:
                            retry_instruction = (
                                f"【第 {retry_count} 次结构纠错】上次输出被截断或只返回了 batch_meta。"
                                "不要解释、不要复述输入、不要使用 Markdown，立即在 Content 中输出完整 JSON。"
                                "压缩 Thought；每个文字字段最多一句，完整保留 batch_meta、"
                                "global_conflict_engine、episodes 三个根字段并闭合 JSON，总正文控制在 4500 汉字内。"
                            )
                            retry_preference = "\n\n".join(
                                item for item in (chunk_preference, retry_instruction) if item
                            )
                            chunk_vars["stagePreference"] = retry_preference
                            chunk_vars["stage_preference"] = retry_preference
                            chunk_vars["user_feedback"] = retry_preference
                        write_retry_count += int(retry_count > 0)
                        write_attempt = len(
                            [event for event in debug_record["events"] if event.get("sub_stage") == "causal_conflict_write"]
                        ) + 1
                        debug_record["events"].append(
                            {
                                "sub_stage": "causal_conflict_write",
                                "attempt": write_attempt,
                                "chunk_index": chunk_index,
                                "chunk_start_episode": chunk_start,
                                "chunk_end_episode": chunk_end,
                                "status": "requesting_tencent",
                                "started_at": _now_iso(),
                                "reason_before_retry": chunk_failure_reason,
                            }
                        )
                        debug_record.update(
                            {
                                "status": "requesting_tencent",
                                "failed_sub_stage": failed_sub_stage,
                                "write_attempt": write_attempt,
                                "write_chunk_size": write_chunk_size,
                                "write_chunk_count": len(write_chunks),
                                "current_write_chunk": chunk_index,
                                "updated_at": _now_iso(),
                            }
                        )
                        debug_path = _write_stage11_debug(debug_record)
                        _stage11_set_run(
                            status="running",
                            current_sub_stage="causal_conflict_write",
                            progress_text=(
                                f"第 11 阶段创作中：第 {chunk_start}-{chunk_end} 集 "
                                f"（分段 {chunk_index}/{len(write_chunks)}）"
                            ),
                            latest_partial_result={
                                "sub_stage": "write_chunk",
                                "start_episode": start_episode,
                                "end_episode": end_episode,
                                "current_chunk_start": chunk_start,
                                "current_chunk_end": chunk_end,
                                "completed_write_chunks": len(chunk_conflict_plans),
                                "total_write_chunks": len(write_chunks),
                            },
                        )

                        try:
                            started = time.monotonic()
                            write_output = tencent_workflow_client.run_stage(
                                STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE,
                                chunk_vars,
                            )
                            duration_ms = int((time.monotonic() - started) * 1000)
                            write_output_data = write_output if isinstance(write_output, dict) else {}
                            write_output_key_set.update(write_output_data.keys())
                            chunk_plan, chunk_unwrapped, chunk_failure_reason = _normalize_dict_output_alias(
                                write_output_data,
                                "batchCausalConflictPlan",
                                "batch_causal_conflict_plan",
                            )
                            _write_stage11_raw_debug(
                                sub_stage="write",
                                stage_name=STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE,
                                variables=chunk_vars,
                                raw_output=write_output,
                                parsed_output={"batchCausalConflictPlan": chunk_plan} if chunk_plan else {},
                                error=chunk_failure_reason,
                                review_round=0,
                                rewrite_round=0,
                            )
                            if isinstance(chunk_plan, dict) and chunk_plan:
                                contract_issues = _validate_stage11_causal_conflict_plan(
                                    chunk_plan,
                                    start_episode=chunk_start,
                                    end_episode=chunk_end,
                                )
                                if contract_issues:
                                    chunk_failure_reason = (
                                        "contract validation failed: " + "; ".join(contract_issues[:8])
                                    )
                                    chunk_plan = {}
                            elif not chunk_failure_reason:
                                chunk_failure_reason = "normalized batchCausalConflictPlan is empty"
                            debug_record["events"][-1].update(
                                {
                                    "status": "returned" if chunk_plan else "invalid",
                                    "duration_ms": duration_ms,
                                    "write_output_keys": sorted(write_output_data.keys()),
                                    "conflict_plan_type": type(chunk_plan).__name__,
                                    "conflict_plan_empty": not bool(chunk_plan),
                                    "write_failure_reason": chunk_failure_reason,
                                    "ended_at": _now_iso(),
                                }
                            )
                        except WorkflowStageFormatError as exc:
                            chunk_plan = {}
                            chunk_failure_reason = (
                                f"{exc.failure_reason}; missing_fields={list(exc.missing_fields)}; "
                                f"probable_truncated_json={exc.probable_truncated_json}; "
                                f"raw_output_source={exc.raw_output_source}"
                            )
                            debug_record["events"][-1].update(
                                {
                                    "status": "format_error",
                                    "error": chunk_failure_reason,
                                    "ended_at": _now_iso(),
                                }
                            )
                        except Exception as exc:
                            chunk_plan = {}
                            chunk_failure_reason = f"{type(exc).__name__}: {exc}"
                            debug_record["events"][-1].update(
                                {
                                    "status": "exception",
                                    "error": chunk_failure_reason,
                                    "traceback": traceback.format_exc(),
                                    "ended_at": _now_iso(),
                                }
                            )

                        debug_record.update(
                            {
                                "status": "write_chunk_returned" if chunk_plan else "write_chunk_failed",
                                "write_failure_reason": chunk_failure_reason,
                                "updated_at": _now_iso(),
                            }
                        )
                        debug_path = _write_stage11_debug(debug_record)
                        if chunk_plan:
                            break
                        if retry_count < max_write_retries:
                            logger.warning(
                                "framework-to-script stage11 write chunk retry: asset_id=%s "
                                "chunk=%s/%s range=%s-%s reason=%s",
                                asset_id,
                                chunk_index,
                                len(write_chunks),
                                chunk_start,
                                chunk_end,
                                chunk_failure_reason,
                            )

                    if not chunk_plan:
                        chunk_failed = True
                        write_failure_reason = (
                            f"第 {chunk_start}-{chunk_end} 集分段生成失败：{chunk_failure_reason}"
                        )
                        break
                    chunk_conflict_plans.append(chunk_plan)
                    resumed_chunk_plans[chunk_start] = chunk_plan
                    save_stage11_write_resume(
                        write_resume_path,
                        status=("complete" if len(resumed_chunk_plans) >= len(write_chunks) else "partial"),
                        fingerprint=write_resume_fingerprint,
                        asset_id=asset_id,
                        start_episode=start_episode,
                        end_episode=end_episode,
                        plans=resumed_chunk_plans,
                        updated_at=_now_iso(),
                    )
                    conflict_plan_unwrapped = conflict_plan_unwrapped or chunk_unwrapped

                if not chunk_failed:
                    conflict_plan = merge_causal_conflict_plans(
                        chunk_conflict_plans,
                        start_episode=start_episode,
                        end_episode=end_episode,
                    )
                    if not conflict_plan:
                        write_failure_reason = "分段结果合并后缺少连续完整的 episodes"
                    else:
                        contract_issues = _validate_stage11_causal_conflict_plan(
                            conflict_plan,
                            start_episode=start_episode,
                            end_episode=end_episode,
                        )
                        if contract_issues:
                            write_failure_reason = (
                                "merged contract validation failed: " + "; ".join(contract_issues[:8])
                            )
                            conflict_plan = {}
                        else:
                            write_failure_reason = ""
                            write_output_data = {"batchCausalConflictPlan": conflict_plan}
                            write_output_key_set.add("batchCausalConflictPlan")
                            _stage11_set_run(
                                current_sub_stage="causal_conflict_write",
                                progress_text=f"第 11 阶段创作已完成：第 {start_episode}-{end_episode} 集",
                                latest_partial_result={
                                    "sub_stage": "write",
                                    "start_episode": start_episode,
                                    "end_episode": end_episode,
                                    "batchCausalConflictPlan_episodes_count": len(conflict_plan.get("episodes") or []),
                                    "batchCausalConflictPlan": conflict_plan,
                                },
                            )

                write_output_keys = sorted(write_output_key_set)
                debug_record.update(
                    {
                        "status": "write_returned" if conflict_plan else "write_failed",
                        "write_output_keys": write_output_keys,
                        "conflict_plan_type": type(conflict_plan).__name__,
                        "conflict_plan_empty": not bool(conflict_plan),
                        "write_failure_reason": write_failure_reason,
                        "write_retry_count": write_retry_count,
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage11_debug(debug_record)

                conflict_episodes = conflict_plan.get("episodes") if isinstance(conflict_plan, dict) else []
                logger.info(
                    "framework-to-script stage11 write done: asset_id=%s write_output_keys=%s "
                    "conflict_plan_type=%s conflict_plan_empty=%s normalized_keys=%s unwrapped=%s "
                    "batchCausalConflictPlan_episodes_count=%s input_keys=%s write_failure_reason=%s",
                    asset_id,
                    write_output_keys,
                    type(conflict_plan).__name__,
                    not bool(conflict_plan),
                    sorted(conflict_plan.keys()) if isinstance(conflict_plan, dict) else [],
                    conflict_plan_unwrapped,
                    len(conflict_episodes) if isinstance(conflict_episodes, list) else 0,
                    sorted(base_vars.keys()),
                    write_failure_reason,
                )

                if not isinstance(conflict_plan, dict) or not conflict_plan:
                    debug_record.update(
                        {
                            "status": "failed",
                            "failure_phase": "causal_conflict_write",
                            "write_retry_count": write_retry_count,
                            "write_failure_reason": write_failure_reason,
                            "write_output_keys": write_output_keys,
                            "updated_at": _now_iso(),
                        }
                    )
                    debug_path = _write_stage11_debug(debug_record)
                    logger.error(
                        "framework-to-script stage11 causal_conflict_write failed after retries: asset_id=%s "
                        "start_episode=%s end_episode=%s retry_count=%s max_write_retries=%s "
                        "reason=%s write_output_keys=%s input_keys=%s",
                        asset_id,
                        start_episode,
                        end_episode,
                        write_retry_count,
                        max_write_retries,
                        write_failure_reason,
                        write_output_keys,
                        sorted(base_vars.keys()),
                    )
                    return jsonify(
                        {
                            "success": False,
                            "message": "11 write 阶段分段生成后仍未返回可用的 batchCausalConflictPlan；请查看后端调试日志。",
                            "detail": {
                                "failed_sub_stage": "causal_conflict_write",
                                "retry_count": write_retry_count,
                                "max_write_retries": max_write_retries,
                                "start_episode": start_episode,
                                "end_episode": end_episode,
                                "write_failure_reason": write_failure_reason,
                                "write_output_keys": write_output_keys,
                                "debug_path": debug_path,
                            },
                        }
                    ), 500

                max_review_rounds = 5
                conflict_review = {}
                rewrite_round = 0
                review_base_vars = copy.deepcopy(base_vars)
                compact_review_plan = compact_enriched_episode_plan(batch_plan)
                compact_review_scenes = compact_scene_dictionary(scene_dictionary)
                review_character_names = [
                    name
                    for item in batch_plan
                    if isinstance(item, dict)
                    for name in (item.get("characters") or [])
                    if str(name or "").strip()
                ]
                compact_review_aliases = compact_appearance_mapping(
                    appearance_mapping,
                    relevant_names=review_character_names,
                )
                review_base_vars.update(
                    {
                        "batchEnrichedEpisodePlan": compact_review_plan,
                        "batch_enriched_episode_plan": compact_review_plan,
                        "sceneDictionary": compact_review_scenes,
                        "scene_dictionary": compact_review_scenes,
                        "appearanceMapping": compact_review_aliases,
                        "appearance_mapping": compact_review_aliases,
                    }
                )
                compact_review_conflict_plan = compact_conflict_plan_for_review(conflict_plan)
                debug_record["review_compaction"] = {
                    "batch_plan_json_length_before": _stage11_json_len(batch_plan),
                    "batch_plan_json_length_after": _stage11_json_len(compact_review_plan),
                    "scene_json_length_before": _stage11_json_len(scene_dictionary),
                    "scene_json_length_after": _stage11_json_len(compact_review_scenes),
                    "alias_json_length_before": _stage11_json_len(appearance_mapping),
                    "alias_json_length_after": _stage11_json_len(compact_review_aliases),
                    "conflict_json_length": _stage11_json_len(conflict_plan),
                    "conflict_review_json_length": _stage11_json_len(compact_review_conflict_plan),
                }

                for review_round in range(1, max_review_rounds + 1):
                    failed_sub_stage = "causal_conflict_review"

                    debug_record["events"].append(
                        {
                            "sub_stage": "causal_conflict_review",
                            "review_round": review_round,
                            "rewrite_round": rewrite_round,
                            "status": "requesting_tencent",
                            "started_at": _now_iso(),
                        }
                    )
                    debug_record.update(
                        {
                            "status": "requesting_tencent",
                            "failed_sub_stage": failed_sub_stage,
                            "review_round": review_round,
                            "rewrite_round": rewrite_round,
                            "updated_at": _now_iso(),
                        }
                    )
                    debug_path = _write_stage11_debug(debug_record)
                    _stage11_set_run(
                        status="running",
                        current_sub_stage="causal_conflict_review",
                        progress_text=f"第 11 阶段审核中：第 {start_episode}-{end_episode} 集，第 {review_round} 轮",
                    )

                    try:
                        review_vars = {
                            **review_base_vars,
                            "batchCausalConflictPlan": compact_review_conflict_plan,
                        }
                        started = time.monotonic()
                        review_output = tencent_workflow_client.run_stage(
                            STAGE_FRAMEWORK_CAUSAL_CONFLICT_REVIEW,
                            review_vars,
                        )
                        duration_ms = int((time.monotonic() - started) * 1000)

                        _write_stage11_raw_debug(
                            sub_stage="review",
                            stage_name=STAGE_FRAMEWORK_CAUSAL_CONFLICT_REVIEW,
                            variables=review_vars,
                            raw_output=review_output,
                            review_round=review_round,
                            rewrite_round=rewrite_round,
                        )

                    except WorkflowStageFormatError as exc:
                        logger.warning(
                            "framework-to-script stage11 review missing fields, using defaults: "
                            "asset_id=%s missing_fields=%s error=%s",
                            asset_id,
                            list(exc.missing_fields),
                            str(exc),
                        )
                        review_output = {}
                        duration_ms = 0

                    review_output_data = review_output if isinstance(review_output, dict) else {}
                    review_conflict_plan, review_plan_unwrapped, review_plan_error = _normalize_dict_output_alias(
                        review_output_data,
                        "batchCausalConflictPlan",
                        "batch_causal_conflict_plan",
                    )
                    review_passed = _get_bool_alias(review_output_data, "reviewPassed", "passed", default=None)
                    rewrite_required = _get_bool_alias(review_output_data, "rewriteRequired", "rewrite_required",
                                                       default=None)
                    blocking_issues = _get_list_alias(review_output_data, "blockingIssues", "blocking_issues")
                    non_blocking_issues = _get_list_alias(review_output_data, "nonBlockingIssues",
                                                          "non_blocking_issues")
                    rewrite_brief = _first_present(review_output_data, "rewriteBrief", "rewrite_brief", default="")

                    if review_passed is None and rewrite_required is None:
                        if review_conflict_plan and not blocking_issues:
                            logger.warning(
                                "framework-to-script stage11 review output missing explicit pass/rewrite fields but contains usable "
                                "batchCausalConflictPlan; treating as passed: asset_id=%s review_output_keys=%s unwrapped=%s",
                                asset_id,
                                sorted(review_output_data.keys()),
                                review_plan_unwrapped,
                            )
                            if not conflict_plan:
                                conflict_plan = review_conflict_plan
                            review_passed = True
                            rewrite_required = False
                            blocking_issues = []
                        else:
                            logger.warning(
                                "framework-to-script stage11 review output missing reviewPassed/passed and rewriteRequired/rewrite_required; "
                                "treating as rewrite needed: asset_id=%s review_output_keys=%s parse_error=%s",
                                asset_id,
                                sorted(review_output_data.keys()),
                                review_plan_error,
                            )
                            review_passed = False
                            rewrite_required = True
                            blocking_issues = []

                    conflict_review = {
                        "reviewPassed": review_passed,
                        "passed": review_passed,
                        "rewriteRequired": rewrite_required,
                        "rewrite_required": rewrite_required,
                        "blockingIssues": blocking_issues,
                        "blocking_issues": blocking_issues,
                        "nonBlockingIssues": non_blocking_issues,
                        "non_blocking_issues": non_blocking_issues,
                        "rewriteBrief": rewrite_brief,
                        "rewrite_brief": rewrite_brief,
                    }
                    rewrite_triggered = _framework_review_needs_rewrite(conflict_review)

                    debug_record["events"][-1].update(
                        {
                            "status": "returned",
                            "duration_ms": duration_ms,
                            "review_output_keys": sorted(review_output_data.keys()),
                            "reviewPassed": review_passed,
                            "rewriteRequired": rewrite_required,
                            "blockingIssues_count": len(blocking_issues),
                            "rewriteBrief_length": len(str(rewrite_brief or "")),
                            "rewrite_triggered": rewrite_triggered,
                            "ended_at": _now_iso(),
                        }
                    )
                    debug_record.update(
                        {
                            "status": "review_returned",
                            "review_round": review_round,
                            "rewrite_round": rewrite_round,
                            "reviewPassed": review_passed,
                            "rewriteRequired": rewrite_required,
                            "blockingIssues_count": len(blocking_issues),
                            "rewriteBrief_length": len(str(rewrite_brief or "")),
                            "updated_at": _now_iso(),
                        }
                    )
                    debug_path = _write_stage11_debug(debug_record)
                    _stage11_set_run(
                        current_sub_stage="causal_conflict_review",
                        progress_text=(
                            f"第 11 阶段审核已返回：第 {start_episode}-{end_episode} 集，"
                            f"{'通过' if review_passed is True and rewrite_required is False else '需要 rewrite'}"
                        ),
                        latest_partial_result={
                            "sub_stage": "review",
                            "start_episode": start_episode,
                            "end_episode": end_episode,
                            "review_round": review_round,
                            "rewrite_round": rewrite_round,
                            "reviewPassed": review_passed,
                            "rewriteRequired": rewrite_required,
                            "blockingIssues_count": len(blocking_issues),
                            "batchCausalConflictPlan": conflict_plan,
                            "batchCausalConflictReview": conflict_review,
                        },
                    )

                    logger.info(
                        "framework-to-script stage11 review loop: stage=%s batchStartEpisode=%s review_round=%s "
                        "rewrite_round=%s reviewPassed=%s rewriteRequired=%s blockingIssues_count=%s "
                        "asset_id=%s review_output_keys=%s nonBlockingIssues_count=%s rewriteBrief_length=%s "
                        "rewrite_triggered=%s input_keys=%s",
                        "stage11",
                        start_episode,
                        review_round,
                        rewrite_round,
                        review_passed,
                        rewrite_required,
                        len(blocking_issues),
                        asset_id,
                        sorted(review_output_data.keys()),
                        len(non_blocking_issues),
                        len(str(rewrite_brief or "")),
                        rewrite_triggered,
                        sorted(base_vars.keys()),
                    )

                    if review_passed is True and rewrite_required is False:
                        break

                    if review_round >= max_review_rounds:
                        debug_record.update(
                            {
                                "status": "failed",
                                "failure_phase": "causal_conflict_review",
                                "review_round": review_round,
                                "rewrite_round": rewrite_round,
                                "last_review": conflict_review,
                                "updated_at": _now_iso(),
                            }
                        )
                        debug_path = _write_stage11_debug(debug_record)
                        return jsonify(
                            {
                                "success": False,
                                "message": "11 因果冲突审核修订 5 轮后仍未通过，已停止保存当前批次。",
                                "detail": {
                                    "failed_sub_stage": "causal_conflict_review",
                                    "max_review_rounds": max_review_rounds,
                                    "review_round": review_round,
                                    "rewrite_round": rewrite_round,
                                    "start_episode": start_episode,
                                    "end_episode": end_episode,
                                    "last_review": conflict_review,
                                    "blockingIssues": blocking_issues,
                                    "blocking_issues": blocking_issues,
                                    "debug_path": debug_path,
                                },
                            }
                        ), 422

                    failed_sub_stage = "causal_conflict_rewrite"
                    rewrite_round += 1

                    logger.info(
                        "framework-to-script stage11 rewrite loop: stage=%s batchStartEpisode=%s review_round=%s "
                        "rewrite_round=%s reviewPassed=%s rewriteRequired=%s blockingIssues_count=%s asset_id=%s",
                        "stage11",
                        start_episode,
                        review_round,
                        rewrite_round,
                        review_passed,
                        rewrite_required,
                        len(blocking_issues),
                        asset_id,
                    )

                    rewrite_vars = _inject_snapshot_stage_preference(
                        {
                            **review_base_vars,
                            "batchCausalConflictPlan": compact_review_conflict_plan,
                            "batchCausalConflictReview": conflict_review,
                        },
                        data,
                        "11",
                        framework_asset=framework_asset,
                        workflow_stage="11_rewrite",
                    )

                    debug_record["events"].append(
                        {
                            "sub_stage": "causal_conflict_rewrite",
                            "review_round": review_round,
                            "rewrite_round": rewrite_round,
                            "status": "requesting_tencent",
                            "started_at": _now_iso(),
                        }
                    )
                    debug_record.update(
                        {
                            "status": "requesting_tencent",
                            "failed_sub_stage": failed_sub_stage,
                            "review_round": review_round,
                            "rewrite_round": rewrite_round,
                            "updated_at": _now_iso(),
                        }
                    )
                    debug_path = _write_stage11_debug(debug_record)
                    _stage11_set_run(
                        status="running",
                        current_sub_stage="causal_conflict_rewrite",
                        progress_text=f"第 11 阶段修订中：第 {start_episode}-{end_episode} 集，第 {rewrite_round} 轮",
                    )

                    started = time.monotonic()
                    rewrite_output = tencent_workflow_client.run_stage(
                        STAGE_FRAMEWORK_CAUSAL_CONFLICT_REWRITE,
                        rewrite_vars,
                    )
                    duration_ms = int((time.monotonic() - started) * 1000)

                    _write_stage11_raw_debug(
                        sub_stage="rewrite",
                        stage_name=STAGE_FRAMEWORK_CAUSAL_CONFLICT_REWRITE,
                        variables=rewrite_vars,
                        raw_output=rewrite_output,
                        review_round=review_round,
                        rewrite_round=rewrite_round,
                    )

                    logger.info(
                        "framework-to-script stage11 rewrite done: asset_id=%s rewrite_output_keys=%s",
                        asset_id,
                        sorted(rewrite_output.keys()) if isinstance(rewrite_output, dict) else [],
                    )

                    rewrite_output_data = rewrite_output if isinstance(rewrite_output, dict) else {}
                    rewrite_conflict_plan, rewrite_unwrapped, rewrite_parse_error = _normalize_dict_output_alias(
                        rewrite_output_data,
                        "batchCausalConflictPlan",
                        "batch_causal_conflict_plan",
                    )
                    conflict_plan = rewrite_conflict_plan or conflict_plan
                    rewrite_episodes = conflict_plan.get("episodes") if isinstance(conflict_plan, dict) else []

                    debug_record["events"][-1].update(
                        {
                            "status": "returned",
                            "duration_ms": duration_ms,
                            "rewrite_output_keys": sorted(rewrite_output_data.keys()),
                            "normalized_keys": sorted(conflict_plan.keys()) if isinstance(conflict_plan, dict) else [],
                            "batchCausalConflictPlan_episodes_count": len(rewrite_episodes) if isinstance(
                                rewrite_episodes, list) else 0,
                            "ended_at": _now_iso(),
                        }
                    )
                    debug_record.update(
                        {
                            "status": "rewrite_returned",
                            "rewrite_output_keys": sorted(rewrite_output_data.keys()),
                            "normalized_keys": sorted(conflict_plan.keys()) if isinstance(conflict_plan, dict) else [],
                            "updated_at": _now_iso(),
                        }
                    )
                    debug_path = _write_stage11_debug(debug_record)
                    _stage11_set_run(
                        current_sub_stage="causal_conflict_rewrite",
                        progress_text=f"第 11 阶段修订已返回：第 {start_episode}-{end_episode} 集",
                        latest_partial_result={
                            "sub_stage": "rewrite",
                            "start_episode": start_episode,
                            "end_episode": end_episode,
                            "review_round": review_round,
                            "rewrite_round": rewrite_round,
                            "batchCausalConflictPlan_episodes_count": (
                                len(rewrite_episodes) if isinstance(rewrite_episodes, list) else 0
                            ),
                            "batchCausalConflictPlan": conflict_plan,
                            "parse_error": rewrite_parse_error,
                        },
                    )

                    logger.info(
                        "framework-to-script stage11 rewrite normalized: asset_id=%s normalized_keys=%s "
                        "unwrapped=%s batchCausalConflictPlan_episodes_count=%s",
                        asset_id,
                        sorted(conflict_plan.keys()) if isinstance(conflict_plan, dict) else [],
                        rewrite_unwrapped,
                        len(rewrite_episodes) if isinstance(rewrite_episodes, list) else 0,
                    )

                failed_sub_stage = "causal_conflict_memory"
                try:
                    memory_vars = {
                        **base_vars,
                        "batchCausalConflictPlan": conflict_plan,
                        "conflictMemory": conflict_memory,
                        "conflictStartEpisode": start_episode,
                    }

                    debug_record["events"].append(
                        {
                            "sub_stage": "causal_conflict_memory",
                            "status": "requesting_tencent",
                            "started_at": _now_iso(),
                        }
                    )
                    debug_record.update(
                        {
                            "status": "requesting_tencent",
                            "failed_sub_stage": failed_sub_stage,
                            "updated_at": _now_iso(),
                        }
                    )
                    debug_path = _write_stage11_debug(debug_record)
                    _stage11_set_run(
                        status="running",
                        current_sub_stage="causal_conflict_memory",
                        progress_text=f"第 11 阶段记忆写入中：第 {start_episode}-{end_episode} 集",
                        latest_partial_result={
                            "sub_stage": "causal_conflict_memory",
                            "start_episode": start_episode,
                            "end_episode": end_episode,
                            "review_round": review_round if "review_round" in locals() else 0,
                            "rewrite_round": rewrite_round if "rewrite_round" in locals() else 0,
                            "batchCausalConflictPlan": conflict_plan,
                            "batchCausalConflictReview": conflict_review if "conflict_review" in locals() else {},
                        },
                    )

                    started = time.monotonic()
                    memory_output = tencent_workflow_client.run_stage(
                        STAGE_FRAMEWORK_CAUSAL_CONFLICT_MEMORY,
                        memory_vars,
                    )
                    duration_ms = int((time.monotonic() - started) * 1000)

                    _write_stage11_raw_debug(
                        sub_stage="memory",
                        stage_name=STAGE_FRAMEWORK_CAUSAL_CONFLICT_MEMORY,
                        variables=memory_vars,
                        raw_output=memory_output,
                        review_round=review_round if "review_round" in locals() else None,
                        rewrite_round=rewrite_round if "rewrite_round" in locals() else None,
                    )

                except WorkflowStageFormatError as exc:
                    raise RuntimeError(
                        "11 memory 阶段未返回 conflictMemory，当前批次不会保存，请重试本批次。"
                    ) from exc

                memory_output_data = memory_output if isinstance(memory_output, dict) else {}
                memory_value = _first_present(memory_output_data, "conflictMemory", "conflict_memory", default=None)
                if memory_value is None or not str(memory_value).strip():
                    raise RuntimeError("11 memory 阶段未返回有效 conflictMemory，当前批次不会保存，请重试本批次。")
                conflict_memory = str(memory_value)

                debug_record["events"][-1].update(
                    {
                        "status": "returned",
                        "duration_ms": duration_ms,
                        "memory_output_keys": sorted(memory_output_data.keys()),
                        "conflictMemory_length": len(conflict_memory),
                        "ended_at": _now_iso(),
                    }
                )
                debug_record.update(
                    {
                        "status": "memory_returned",
                        "memory_output_keys": sorted(memory_output_data.keys()),
                        "conflictMemory_length": len(conflict_memory),
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage11_debug(debug_record)
                _stage11_set_run(
                    status="running",
                    current_sub_stage="causal_conflict_memory",
                    progress_text=f"第 11 阶段记忆已返回：第 {start_episode}-{end_episode} 集",
                    latest_partial_result={
                        "sub_stage": "causal_conflict_memory",
                        "start_episode": start_episode,
                        "end_episode": end_episode,
                        "review_round": review_round if "review_round" in locals() else 0,
                        "rewrite_round": rewrite_round if "rewrite_round" in locals() else 0,
                        "conflictMemory_length": len(conflict_memory),
                        "batchCausalConflictPlan": conflict_plan,
                        "batchCausalConflictReview": conflict_review if "conflict_review" in locals() else {},
                        "conflictMemory": conflict_memory,
                    },
                )

                logger.info(
                    "framework-to-script stage11 memory done: asset_id=%s memory_output_keys=%s normalized_keys=%s conflictMemory_length=%s",
                    asset_id,
                    sorted(memory_output_data.keys()),
                    ["conflictMemory", "conflict_memory"],
                    len(conflict_memory),
                )

            except Exception as exc:
                debug_record.update(
                    {
                        "status": "failed",
                        "failure_phase": failed_sub_stage,
                        "failed_sub_stage": failed_sub_stage,
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                        "traceback": traceback.format_exc(),
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage11_debug(debug_record)
                logger.exception(
                    "framework-to-script stage11 failed: failed_sub_stage=%s asset_id=%s start_episode=%s "
                    "end_episode=%s batch_plan_count=%s base_vars_keys=%s error_type=%s error=%s",
                    failed_sub_stage,
                    asset_id,
                    start_episode,
                    end_episode,
                    len(batch_plan) if isinstance(batch_plan, list) else 0,
                    sorted(base_vars.keys()) if isinstance(base_vars, dict) else [],
                    type(exc).__name__,
                    str(exc),
                )
                return jsonify(
                    {
                        "success": False,
                        "message": "11 因果冲突批次调用失败",
                        "detail": {
                            "failed_sub_stage": failed_sub_stage,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "asset_id": asset_id,
                            "start_episode": start_episode,
                            "end_episode": end_episode,
                            "batch_plan_count": len(batch_plan) if isinstance(batch_plan, list) else 0,
                            "base_var_keys": sorted(base_vars.keys()) if isinstance(base_vars, dict) else [],
                            "debug_path": debug_path,
                        },
                    }
                ), 500

            batch_key = str(start_episode)
            batches = dict(existing_batches)
            batch_output = {
                "batchStartEpisode": start_episode,
                "batchEndEpisode": end_episode,
                "batchPipelineStatus": "complete",
                "batch_pipeline_status": "complete",
                "completedSubStages": [
                    "causal_conflict_write",
                    "causal_conflict_review",
                    *([] if not rewrite_round else ["causal_conflict_rewrite"]),
                    "causal_conflict_memory",
                ],
                "completed_sub_stages": [
                    "causal_conflict_write",
                    "causal_conflict_review",
                    *([] if not rewrite_round else ["causal_conflict_rewrite"]),
                    "causal_conflict_memory",
                ],
                "batchEnrichedEpisodePlan": batch_plan,
                "batchCausalConflictPlan": conflict_plan,
                "batch_causal_conflict_plan": conflict_plan,
                "batchCausalConflictReview": conflict_review,
                "batch_causal_conflict_review": conflict_review,
                "conflictMemory": conflict_memory,
                "conflict_memory": conflict_memory,
            }
            batches[batch_key] = batch_output
            output = {**batch_output, "batches": batches}

            if asset_id:
                _save_framework_to_script_stage(
                    user_id=user_id,
                    asset_id=asset_id,
                    stage_key="stage11",
                    output=output,
                )
            try:
                write_resume_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("framework-to-script stage11 checkpoint cleanup failed: %s", write_resume_path)

            debug_record.update(
                {
                    "status": "success",
                    "saved": bool(asset_id),
                    "final_output_keys": sorted(output.keys()),
                    "conflict_plan_keys": sorted(conflict_plan.keys()) if isinstance(conflict_plan, dict) else [],
                    "conflictMemory_length": len(conflict_memory),
                    "updated_at": _now_iso(),
                }
            )
            debug_path = _write_stage11_debug(debug_record)
            _stage11_set_run(
                current_sub_stage="stage11_batch_saved",
                progress_text=f"第 11 阶段第 {start_episode}-{end_episode} 集已保存",
                latest_partial_result={
                    "start_episode": start_episode,
                    "end_episode": end_episode,
                    "completed_batch_starts": _sorted_numeric_batch_keys(batches),
                    "latest_batch_done": start_episode,
                },
                latest_result_preview={
                    "batchStartEpisode": start_episode,
                    "batchEndEpisode": end_episode,
                    "batches": _sorted_numeric_batch_keys(batches),
                },
            )

        finally:
            if not is_stage11_worker:
                _end_framework_stage(user_id, asset_id, "11")

        return _json_ok(stage="11", framework_asset_id=asset_id, **output)

    @app.post("/api/framework-to-script/stage/12")
    @_login_required
    def run_framework_to_script_stage12_api():
        """单独运行 12 当前批次正文：write -> review -> rewrite(必要时) -> memory。"""
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _json_error("请求体必须是 JSON object。", status=400)
        try:
            user_id = _require_user_id()
            data, framework_asset = _inject_framework_asset(data, user_id)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        locked_response = _framework_to_script_locked_error(framework_asset)
        if locked_response:
            return locked_response

        framework_plan_package = (
            data.get("framework_plan_package")
            or data.get("frameworkPlanPackage")
            or {}
        )
        stage08 = data.get("stage08") if isinstance(data.get("stage08"), dict) else _framework_script_stage_cache(framework_asset, "stage08")
        stage09 = data.get("stage09") if isinstance(data.get("stage09"), dict) else _framework_script_stage_cache(framework_asset, "stage09")
        stage11 = data.get("stage11") if isinstance(data.get("stage11"), dict) else _framework_script_stage_cache(framework_asset, "stage11")
        stage11_batches = stage11.get("batches") if isinstance(stage11.get("batches"), dict) else {}
        existing_stage12 = data.get("stage12") if isinstance(data.get("stage12"), dict) else _framework_script_stage_cache(framework_asset, "stage12")
        existing_batches = existing_stage12.get("batches") if isinstance(existing_stage12.get("batches"), dict) else {}
        reset_stage12 = bool(data.get("reset_stage12") or data.get("resetStage12"))
        if reset_stage12:
            existing_stage12 = {}
            existing_batches = {}
        else:
            valid_existing_stage12_batches = {}
            for existing_key, existing_batch in existing_batches.items():
                if not isinstance(existing_batch, dict):
                    continue
                has_script = _framework_value_present(
                    _first_present(existing_batch, "batchScriptText", "batch_script_text", default=None)
                )
                has_review = _framework_value_present(
                    _first_present(existing_batch, "batchScriptReview", "batch_script_review", default=None)
                )
                has_memory = _framework_value_present(
                    _first_present(existing_batch, "scriptMemory", "script_memory", default=None)
                )
                if has_script and has_review and has_memory:
                    valid_existing_stage12_batches[str(existing_key)] = existing_batch
                else:
                    logger.warning(
                        "framework-to-script stage12 dropping incomplete cached batch before retry: "
                        "asset_id=%s batchStartEpisode=%s has_script=%s has_review=%s has_memory=%s",
                        str((framework_asset or {}).get("asset_id") or data.get("framework_asset_id") or "").strip(),
                        existing_key,
                        has_script,
                        has_review,
                        has_memory,
                    )
            existing_batches = valid_existing_stage12_batches
        requested_start = data.get("batchStartEpisode") or data.get("batch_start_episode")
        selected_batch_source = ""
        if requested_start:
            batch_key = str(_positive_int(requested_start, 1))
            selected_batch_source = "explicit_request"
            if not stage11_batches and _first_present(stage11, "batchCausalConflictPlan", "batch_causal_conflict_plan", default=None):
                stage11_batches = {batch_key: stage11}
                logger.warning(
                    "framework-to-script stage12 stage11.batches empty, falling back to top-level stage11 batch: "
                    "asset_id=%s batchStartEpisode=%s",
                    str((framework_asset or {}).get("asset_id") or data.get("framework_asset_id") or "").strip(),
                    batch_key,
                )
        else:
            stage11_batch_keys = _sorted_numeric_batch_keys(stage11_batches)
            existing_stage12_keys = set(_sorted_numeric_batch_keys(existing_batches))
            batch_key = next((key for key in stage11_batch_keys if key not in existing_stage12_keys), "")
            selected_batch_source = "first_missing_from_stage11_batches"
            if not batch_key and not stage11_batch_keys and _first_present(stage11, "batchCausalConflictPlan", "batch_causal_conflict_plan", default=None):
                batch_key = str(_positive_int(stage11.get("batchStartEpisode"), 1))
                stage11_batches = {batch_key: stage11}
                selected_batch_source = "fallback_top_level"
                logger.warning(
                    "framework-to-script stage12 stage11.batches empty, falling back to top-level stage11 batch: "
                    "asset_id=%s batchStartEpisode=%s",
                    str((framework_asset or {}).get("asset_id") or data.get("framework_asset_id") or "").strip(),
                    batch_key,
                )
        stage11_batch = stage11_batches.get(batch_key) if isinstance(stage11_batches, dict) else None
        logger.info(
            "framework-to-script stage12 selected batchStartEpisode=%s source=%s stage11_batch_keys=%s stage12_batch_keys=%s",
            batch_key,
            selected_batch_source,
            _sorted_numeric_batch_keys(stage11_batches),
            _sorted_numeric_batch_keys(existing_batches),
        )
        if not isinstance(stage11_batch, dict):
            return _json_error("请先完成 11 当前批次因果冲突。", status=400)

        batch_plan = _first_present(stage11_batch, "batchEnrichedEpisodePlan", "batch_enriched_episode_plan", default=[]) or []
        conflict_plan, conflict_plan_unwrapped = _unwrap_dict_alias(
            stage11_batch,
            "batchCausalConflictPlan",
            "batch_causal_conflict_plan",
        )
        scene_dictionary = stage08.get("sceneDictionary") or {}
        appearance_mapping = stage09.get("appearanceMapping") or {}
        if not isinstance(batch_plan, list) or not batch_plan:
            return _json_error("缺少第11阶段批次分集计划，请先重新运行11。", status=400)
        if not isinstance(conflict_plan, dict) or not conflict_plan:
            return _json_error("缺少第11阶段因果冲突计划，请先重新运行11。", status=400)
        if not scene_dictionary:
            return _json_error("缺少第08阶段场景字典，请先重新运行08。", status=400)
        if not appearance_mapping:
            return _json_error("缺少第09阶段人设服装映射，请先重新运行09。", status=400)

        asset_id = str((framework_asset or {}).get("asset_id") or data.get("framework_asset_id") or "").strip()

        stage12_worker_run_id = str(data.get("_stage12_run_id") or "").strip()
        stage12_worker_token = str(data.get("_stage12_worker_token") or "").strip()
        stage12_worker_requested = str(request.headers.get("X-Framework-Stage12-Worker") or "").strip() == "1"
        is_stage12_worker = stage12_worker_requested and _framework_stage_worker_allowed(
            run_id=stage12_worker_run_id,
            worker_token=stage12_worker_token,
            user_id=user_id,
            asset_id=asset_id,
            stage="12",
        )

        if stage12_worker_requested and not is_stage12_worker:
            return _json_error("无效的 12 阶段后台运行请求。", status=403)

        def _stage12_set_run(**updates) -> dict:
            if not is_stage12_worker or not stage12_worker_run_id:
                return {}
            try:
                return _update_framework_stage_run(run_id=stage12_worker_run_id, **updates)
            except Exception:
                logger.exception("framework-to-script stage12 run state update failed")
                return {}

        if not is_stage12_worker and asset_id:
            expected_starts = _sorted_numeric_batch_keys(stage11_batches)
            if requested_start:
                expected_starts = [str(batch_key)]
            if not expected_starts and batch_key:
                expected_starts = [str(batch_key)]

            run, created = _begin_or_get_framework_stage_run(
                user_id=user_id,
                asset_id=asset_id,
                stage="12",
                current_sub_stage="stage12_prepare",
                progress_text=f"第 12 阶段准备后台运行：第 {batch_key} 集起",
                latest_partial_result={
                    "selected_batch_source": selected_batch_source,
                    "selected_batch_start": batch_key,
                    "expected_batch_starts": expected_starts,
                    "completed_batch_starts": _sorted_numeric_batch_keys(existing_batches),
                    "remaining_batch_starts": [
                        key for key in expected_starts
                        if key not in set(_sorted_numeric_batch_keys(existing_batches))
                    ],
                },
                retain_completed=True,
            )

            if not created:
                return jsonify({"success": True, "existing": True, "run": run}), 202

            private_run = _framework_stage_run_private(str(run.get("run_id") or ""))
            worker_token = str(private_run.get("worker_token") or "")
            worker_payload = copy.deepcopy(data)
            worker_payload["_stage12_run_id"] = str(run.get("run_id") or "")
            worker_payload["_stage12_worker_token"] = worker_token
            auth_token = _current_auth_token()

            def _stage12_worker_loop() -> None:
                run_id = str(run.get("run_id") or "")
                latest_result = {}
                try:
                    _update_framework_stage_run(
                        run_id=run_id,
                        status="running",
                        current_sub_stage="stage12_prepare",
                        progress_text=f"第 12 阶段后台运行中：第 {batch_key} 集起",
                        latest_partial_result={
                            "selected_batch_start": batch_key,
                            "expected_batch_starts": expected_starts,
                            "completed_batch_starts": _sorted_numeric_batch_keys(existing_batches),
                        },
                    )

                    first_request = True
                    guard = 0
                    completed_starts = set(_sorted_numeric_batch_keys(existing_batches))
                    batch_auto_retry_counts = {}
                    max_batch_auto_retries = min(
                        max(_positive_int(os.getenv("TENCENT_WORKFLOW_12_BATCH_MAX_AUTO_RETRIES"), 2), 0),
                        5,
                    )

                    while guard < 200:
                        guard += 1
                        request_payload = copy.deepcopy(worker_payload)

                        request_payload["reset_stage12"] = bool(reset_stage12 and first_request)
                        request_payload["resetStage12"] = bool(reset_stage12 and first_request)

                        # 关键：不要一直带前端旧 stage12，否则每轮都可能看到旧 batches。
                        if not first_request:
                            request_payload.pop("stage12", None)
                            request_payload.pop("stage_12", None)

                        path = "/api/framework-to-script/stage/12"
                        if auth_token:
                            path = f"{path}?auth_token={quote(auth_token)}"

                        with app.app_context():
                            with app.test_client() as worker_client:
                                response = worker_client.post(
                                    path,
                                    headers={"X-Framework-Stage12-Worker": "1"},
                                    json=request_payload,
                                )
                                response_data = response.get_json(silent=True) or {}

                        latest_result = response_data if isinstance(response_data, dict) else {}

                        if response.status_code >= 400 or latest_result.get("success") is False:
                            detail = latest_result.get("detail") if isinstance(latest_result.get("detail"),
                                                                               dict) else {}
                            message = (
                                    detail.get("error_message")
                                    or detail.get("message")
                                    or latest_result.get("message")
                                     or latest_result.get("error")
                                     or f"stage12 worker returned HTTP {response.status_code}"
                            )
                            next_missing_start = next(
                                (key for key in expected_starts if key not in completed_starts),
                                str(detail.get("start_episode") or batch_key),
                            )
                            failed_batch_start = str(
                                detail.get("start_episode")
                                or detail.get("batchStartEpisode")
                                or next_missing_start
                            )
                            batch_retry_count = int(batch_auto_retry_counts.get(failed_batch_start) or 0) + 1
                            batch_auto_retry_counts[failed_batch_start] = batch_retry_count
                            if batch_retry_count <= max_batch_auto_retries:
                                logger.warning(
                                    "framework-to-script stage12 batch auto retry: asset_id=%s "
                                    "batch_start=%s retry=%s/%s reason=%s",
                                    asset_id,
                                    failed_batch_start,
                                    batch_retry_count,
                                    max_batch_auto_retries,
                                    message,
                                )
                                _update_framework_stage_run(
                                    run_id=run_id,
                                    status="running",
                                    current_sub_stage="stage12_batch_auto_retry",
                                    progress_text=(
                                        f"第 12 阶段第 {failed_batch_start} 集起正文批次暂时失败，"
                                        f"正在自动恢复 {batch_retry_count}/{max_batch_auto_retries}"
                                    ),
                                    latest_error="",
                                    latest_partial_result={
                                        "failed_batch_start": failed_batch_start,
                                        "batch_auto_retry_count": batch_retry_count,
                                        "batch_auto_retry_limit": max_batch_auto_retries,
                                        "completed_batch_starts": sorted(
                                            completed_starts,
                                            key=lambda item: int(item) if str(item).isdigit() else 999,
                                        ),
                                        "expected_batch_starts": expected_starts,
                                    },
                                )
                                first_request = False
                                time.sleep(min(batch_retry_count, 2))
                                continue
                            _finish_framework_stage_run(
                                run_id=run_id,
                                status="failed",
                                progress_text="第 12 阶段运行失败",
                                latest_error=str(message),
                                latest_result_preview=latest_result,
                            )
                            return

                        batches = latest_result.get("batches") if isinstance(latest_result.get("batches"), dict) else {}
                        completed_starts = set(_sorted_numeric_batch_keys(batches))
                        completed_batch_start = str(latest_result.get("batchStartEpisode") or "")
                        if completed_batch_start:
                            batch_auto_retry_counts.pop(completed_batch_start, None)
                        missing = [key for key in expected_starts if key not in completed_starts]

                        debug_path = str(
                            latest_result.get("stage12DebugPath")
                            or latest_result.get("stage12_debug_path")
                            or ""
                        ).strip()

                        latest_partial = {
                            "latest_batch_done": latest_result.get("batchStartEpisode"),
                            "start_episode": latest_result.get("batchStartEpisode"),
                            "end_episode": latest_result.get("batchEndEpisode"),
                            "completed_batch_starts": sorted(
                                completed_starts,
                                key=lambda item: int(item) if str(item).isdigit() else 999,
                            ),
                            "expected_batch_starts": expected_starts,
                            "remaining_batch_starts": missing,
                        }

                        _update_framework_stage_run(
                            run_id=run_id,
                            status="running",
                            current_sub_stage="stage12_batch_saved",
                            progress_text=(
                                f"第 12 阶段已保存第 {latest_partial['start_episode']}-"
                                f"{latest_partial['end_episode']} 集，"
                                f"进度 {len(completed_starts)}/{len(expected_starts) or '?'}"
                            ),
                            raw_debug_path=debug_path,
                            latest_partial_result=latest_partial,
                            latest_result_preview={
                                "batchStartEpisode": latest_result.get("batchStartEpisode"),
                                "batchEndEpisode": latest_result.get("batchEndEpisode"),
                                "batches": sorted(
                                    completed_starts,
                                    key=lambda item: int(item) if str(item).isdigit() else 999,
                                ),
                            },
                        )

                        if not missing:
                            break

                        first_request = False

                    else:
                        _finish_framework_stage_run(
                            run_id=run_id,
                            status="failed",
                            progress_text="第 12 阶段运行超出批次数保护上限",
                            latest_error="stage12 worker exceeded batch guard limit",
                            latest_result_preview=latest_result,
                        )
                        return

                    _finish_framework_stage_run(
                        run_id=run_id,
                        status="succeeded",
                        progress_text="第 12 阶段已完成",
                        latest_result_preview={
                            "completed_batch_starts": sorted(
                                completed_starts,
                                key=lambda item: int(item) if str(item).isdigit() else 999,
                            ),
                        },
                        latest_partial_result={
                            "completed_batch_starts": sorted(
                                completed_starts,
                                key=lambda item: int(item) if str(item).isdigit() else 999,
                            ),
                            "expected_batch_starts": expected_starts,
                            "remaining_batch_starts": [],
                        },
                    )

                except Exception as exc:
                    logger.exception("framework-to-script stage12 background worker failed")
                    _finish_framework_stage_run(
                        run_id=run_id,
                        status="failed",
                        progress_text="第 12 阶段后台运行失败",
                        latest_error=str(exc),
                    )

            thread = threading.Thread(
                target=_stage12_worker_loop,
                name=f"framework-stage12-{run.get('run_id')}",
                daemon=True,
            )
            thread.start()

            run = _update_framework_stage_run(
                run_id=str(run.get("run_id") or ""),
                status="running",
                current_sub_stage="stage12_prepare",
                progress_text=f"第 12 阶段已开始后台运行：第 {batch_key} 集起",
            )

            return jsonify({"success": True, "accepted": True, "run": run}), 202

        if not is_stage12_worker and not _try_begin_framework_stage(user_id, asset_id, "12"):
            return _json_error("12 正在运行中，请稍后刷新页面，已完成输出会自动恢复。", status=409)

        try:
            failed_sub_stage = "stage12_prepare"
            start_episode = None
            end_episode = None
            base_vars = {}
            debug_record = {
                "project_id": asset_id or data.get("project_id") or data.get("source_framework_project_id"),
                "project_title": _stage12_debug_project_title(data, framework_asset),
                "stage": 12,
                "status": "started",
                "selected_batch_source": selected_batch_source,
                "batch_key": batch_key,
                "attempt": 1,
                "rewrite_attempt": 0,
                "review_attempt": 0,
                "events": [],
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            debug_path = ""
            try:
                from .services.workflow_errors import WorkflowStageFormatError
                from .services.tencent_workflow_client import tencent_workflow_client
                from .services.workflow_contracts import (
                    STAGE_CONTRACTS,
                    STAGE_FRAMEWORK_SCRIPT_MEMORY,
                    STAGE_FRAMEWORK_SCRIPT_REVIEW,
                    STAGE_FRAMEWORK_SCRIPT_REWRITE,
                    STAGE_FRAMEWORK_SCRIPT_WRITE,
                )

                start_episode = _positive_int(stage11_batch.get("batchStartEpisode"), _positive_int(batch_key, 1))
                end_episode = _positive_int(stage11_batch.get("batchEndEpisode"), start_episode + 4)
                debug_record.update(
                    {
                        "batch_start_episode": start_episode,
                        "batch_end_episode": end_episode,
                        "episode_count": max(0, end_episode - start_episode + 1),
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                episode_word_count = _positive_int(
                    data.get("episode_word_count")
                    or data.get("chars_per_episode")
                    or (framework_asset or {}).get("episode_word_count")
                    or (framework_asset or {}).get("chars_per_episode"),
                    600,
                )
                total_episodes = _positive_int(
                    data.get("total_episodes") or (framework_asset or {}).get("episodes_per_season"),
                    end_episode,
                )
                script_memory = str(
                    _first_present(data, "scriptMemory", "script_memory", default=None)
                    or _first_present(existing_stage12, "scriptMemory", "script_memory", default="")
                    or ""
                )
                base_vars = {
                    **_framework_context_vars(data, framework_plan_package),
                    "totalEpisodes": total_episodes,
                    "scriptStartEpisode": start_episode,
                    "episodeWordCount": episode_word_count,
                    "batchEnrichedEpisodePlan": batch_plan,
                    "batchCausalConflictPlan": conflict_plan,
                    "sceneDictionary": scene_dictionary,
                    "appearanceMapping": appearance_mapping,
                    "scriptWorldRulesDigest": stage08.get("scriptWorldRulesDigest") or {},
                    "scriptMemory": script_memory,
                }
                _merge_aliases(
                    base_vars,
                    {
                        "totalEpisodes": ("total_episodes",),
                        "episodeWordCount": ("episode_word_count", "chars_per_episode"),
                        "scriptMemory": ("script_memory",),
                        "scriptStartEpisode": ("script_start_episode",),
                        "batchEnrichedEpisodePlan": ("batch_enriched_episode_plan",),
                        "batchCausalConflictPlan": ("batch_causal_conflict_plan",),
                        "sceneDictionary": ("scene_dictionary",),
                        "appearanceMapping": ("appearance_mapping",),
                        "scriptWorldRulesDigest": ("script_world_rules_digest",),
                    },
                )
                base_vars = _inject_snapshot_stage_preference(
                    base_vars,
                    data,
                    "12",
                    framework_asset=framework_asset,
                    workflow_stage="12_write",
                )
                preference_snapshot = data.get("preference_snapshot") if isinstance(data.get("preference_snapshot"), dict) else {}
                prompt_preferences = data.get("prompt_preferences") if isinstance(data.get("prompt_preferences"), dict) else {}
                user_preference_payload = {
                    "preference_snapshot": preference_snapshot,
                    "prompt_preferences": prompt_preferences,
                }
                debug_record.update(
                    {
                        "status": "prepared",
                        "request_variable_keys_before_tencent": sorted(base_vars.keys()),
                        "variable_length_summary": {
                            key: _stage12_debug_summary(base_vars.get(key))
                            for key in sorted(base_vars.keys())
                            if key
                            in {
                                "totalEpisodes",
                                "scriptStartEpisode",
                                "episodeWordCount",
                                "batchEnrichedEpisodePlan",
                                "batchCausalConflictPlan",
                                "sceneDictionary",
                                "appearanceMapping",
                                "scriptWorldRulesDigest",
                                "scriptMemory",
                                "userPreference",
                                "userPreferences",
                                "preferenceSnapshot",
                                "promptPreferences",
                            }
                        },
                        "scriptMemory_length": len(script_memory),
                        "scriptMemory_preview": _stage12_debug_preview(script_memory),
                        "batchEnrichedEpisodePlan_length": len(json.dumps(batch_plan, ensure_ascii=False, default=str)),
                        "batchEnrichedEpisodePlan_preview": _stage12_debug_preview(batch_plan),
                        "batchCausalConflictPlan_length": len(json.dumps(conflict_plan, ensure_ascii=False, default=str)),
                        "batchCausalConflictPlan_preview": _stage12_debug_preview(conflict_plan),
                        "appearanceMapping_exists": bool(appearance_mapping),
                        "scriptWorldRulesDigest_exists": bool(stage08.get("scriptWorldRulesDigest") or {}),
                        "user_preference_exists": bool(preference_snapshot or prompt_preferences),
                        "user_preference_length": len(json.dumps(user_preference_payload, ensure_ascii=False, default=str)),
                        "user_preference_preview": _stage12_debug_preview(user_preference_payload),
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                first_plan = batch_plan[0] if isinstance(batch_plan[0], dict) else {}
                first_plan_summary = {
                    "episode": first_plan.get("episode"),
                    "title": first_plan.get("title"),
                    "characters": first_plan.get("characters"),
                }
                appearance_characters = (
                    appearance_mapping.get("characters")
                    if isinstance(appearance_mapping, dict)
                    else []
                )
                conflict_episodes = conflict_plan.get("episodes") if isinstance(conflict_plan, dict) else []
                stage_names = {
                    "script_write": getattr(STAGE_CONTRACTS.get(STAGE_FRAMEWORK_SCRIPT_WRITE), "stage_name", STAGE_FRAMEWORK_SCRIPT_WRITE),
                    "script_review": getattr(STAGE_CONTRACTS.get(STAGE_FRAMEWORK_SCRIPT_REVIEW), "stage_name", STAGE_FRAMEWORK_SCRIPT_REVIEW),
                    "script_rewrite": getattr(STAGE_CONTRACTS.get(STAGE_FRAMEWORK_SCRIPT_REWRITE), "stage_name", STAGE_FRAMEWORK_SCRIPT_REWRITE),
                    "script_memory": getattr(STAGE_CONTRACTS.get(STAGE_FRAMEWORK_SCRIPT_MEMORY), "stage_name", STAGE_FRAMEWORK_SCRIPT_MEMORY),
                }
                logger.info(
                    "framework-to-script stage12 entering 腾讯工作流 asset_id=%s start_episode=%s end_episode=%s "
                    "batch_plan_count=%s has_batchCausalConflictPlan=%s has_sceneDictionary=%s "
                    "has_appearanceMapping=%s appearanceMapping.characters_count=%s base_vars_keys=%s "
                    "first_batchEnrichedEpisodePlan=%s batchCausalConflictPlan_episodes_count=%s "
                    "batchCausalConflictPlan_unwrapped=%s normalized_conflict_keys=%s stage_names=%s",
                    asset_id,
                    start_episode,
                    end_episode,
                    len(batch_plan),
                    isinstance(conflict_plan, dict) and bool(conflict_plan),
                    bool(scene_dictionary),
                    bool(appearance_mapping),
                    len(appearance_characters) if isinstance(appearance_characters, list) else 0,
                    sorted(base_vars.keys()),
                    first_plan_summary,
                    len(conflict_episodes) if isinstance(conflict_episodes, list) else 0,
                    conflict_plan_unwrapped,
                    sorted(conflict_plan.keys()) if isinstance(conflict_plan, dict) else [],
                    stage_names,
                )
                failed_sub_stage = "script_write"
                write_event = {
                    "sub_stage": "script_write",
                    "attempt": 1,
                    "review_attempt": 0,
                    "rewrite_attempt": 0,
                    "tencent_request_started_at": _now_iso(),
                    "request_variable_keys": sorted(base_vars.keys()),
                }
                debug_record["events"].append(write_event)
                debug_record.update({"status": "requesting_tencent", "failed_sub_stage": failed_sub_stage, "updated_at": _now_iso()})
                debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                _stage12_set_run(
                    status="running",
                    current_sub_stage="script_write",
                    progress_text=f"第 12 阶段正文写作中：第 {start_episode}-{end_episode} 集",
                    raw_debug_path=debug_path,
                    latest_partial_result={
                        "sub_stage": "script_write",
                        "start_episode": start_episode,
                        "end_episode": end_episode,
                    },
                )
                write_started = time.monotonic()
                write_output = tencent_workflow_client.run_stage(STAGE_FRAMEWORK_SCRIPT_WRITE, base_vars)
                write_event["tencent_request_ended_at"] = _now_iso()
                write_event["duration_ms"] = int((time.monotonic() - write_started) * 1000)
                write_event["tencent_debug"] = _stage12_workflow_debug_summary(tencent_workflow_client, STAGE_FRAMEWORK_SCRIPT_WRITE)
                write_keys = sorted(write_output.keys()) if isinstance(write_output, dict) else []
                batch_script_value = _first_present(write_output, "batchScriptText", "batch_script_text", default=None)
                batch_script = str(batch_script_value or "")
                write_event["raw_response_summary"] = _stage12_debug_summary(write_output, preview_limit=600)
                write_event["parsed_fields"] = write_keys
                write_event["batchScriptText_length"] = len(batch_script)
                write_event["parse_failure_reason"] = "" if batch_script.strip() else "missing_or_empty_batchScriptText"
                debug_record.update(
                    {
                        "status": "script_write_done" if batch_script.strip() else "parse_failed",
                        "parsed_fields": write_keys,
                        "raw_response_summary": _stage12_debug_summary(write_output, preview_limit=600),
                        "parse_failure_reason": write_event["parse_failure_reason"],
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                _stage12_set_run(
                    status="running",
                    current_sub_stage="script_write_done",
                    progress_text=f"第 12 阶段正文 write 已返回：第 {start_episode}-{end_episode} 集",
                    raw_debug_path=debug_path,
                    latest_partial_result={
                        "sub_stage": "script_write",
                        "start_episode": start_episode,
                        "end_episode": end_episode,
                        "batchScriptText_length": len(batch_script),
                        "batchScriptText_empty": not bool(batch_script.strip()),
                    },
                )
                logger.info(
                    "framework-to-script stage12 script_write output write_output_keys=%s batchScriptText_type=%s "
                    "batchScriptText_length=%s batchScriptText_empty=%s normalized_keys=%s input_keys=%s",
                    write_keys,
                    type(batch_script_value).__name__,
                    len(batch_script),
                    not bool(batch_script.strip()),
                    ["batchScriptText", "batch_script_text"],
                    sorted(base_vars.keys()),
                )
                if not batch_script.strip():
                    debug_record.update(
                        {
                            "status": "failed",
                            "failure_phase": "解析",
                            "failed_sub_stage": "script_write",
                            "exception_type": "",
                            "exception_message": "12 write/rewrite 阶段未返回 batchScriptText",
                            "updated_at": _now_iso(),
                        }
                    )
                    debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                    return jsonify(
                        {
                            "success": False,
                            "message": f"12 阶段第 {start_episode}-{end_episode} 集生成失败/解析失败：write 未返回正文。",
                            "detail": {
                                "failed_sub_stage": "script_write",
                                "error_message": "12 write/rewrite 阶段未返回 batchScriptText",
                                "write_output_keys": write_keys,
                                "debug_path": debug_path,
                            },
                        }
                    ), 500
                max_review_rounds = 5
                script_review = {}
                rewrite_round = 0
                for review_round in range(1, max_review_rounds + 1):
                    failed_sub_stage = "script_review"
                    debug_record.update(
                        {
                            "status": "requesting_tencent",
                            "failed_sub_stage": failed_sub_stage,
                            "review_attempt": review_round,
                            "rewrite_attempt": rewrite_round,
                            "updated_at": _now_iso(),
                        }
                    )
                    review_vars = {
                        **base_vars,
                        "batchScriptText": batch_script,
                    }
                    review_event = {
                        "sub_stage": "script_review",
                        "attempt": 1,
                        "review_attempt": review_round,
                        "rewrite_attempt": rewrite_round,
                        "tencent_request_started_at": _now_iso(),
                        "request_variable_keys": sorted(review_vars.keys()),
                        "batchScriptText_length": len(batch_script),
                        "batchScriptText_preview": _stage12_debug_preview(batch_script),
                    }
                    debug_record["events"].append(review_event)
                    debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                    _stage12_set_run(
                        status="running",
                        current_sub_stage="script_review",
                        progress_text=f"第 12 阶段正文审核中：第 {start_episode}-{end_episode} 集，第 {review_round} 轮",
                        raw_debug_path=debug_path,
                        latest_partial_result={
                            "sub_stage": "script_review",
                            "start_episode": start_episode,
                            "end_episode": end_episode,
                            "review_round": review_round,
                            "rewrite_round": rewrite_round,
                            "batchScriptText_length": len(batch_script),
                        },
                    )
                    review_started = time.monotonic()
                    review_output = {}
                    review_format_errors: list[dict] = []
                    review_format_attempt_limit = min(
                        max(_positive_int(os.getenv("TENCENT_WORKFLOW_12_REVIEW_FORMAT_ATTEMPTS"), 3), 1),
                        5,
                    )
                    for review_format_attempt in range(1, review_format_attempt_limit + 1):
                        review_event["attempt"] = review_format_attempt
                        try:
                            review_output = tencent_workflow_client.run_stage(
                                STAGE_FRAMEWORK_SCRIPT_REVIEW,
                                review_vars,
                            )
                            break
                        except WorkflowStageFormatError as exc:
                            workflow_debug = _stage12_workflow_debug_summary(
                                tencent_workflow_client,
                                STAGE_FRAMEWORK_SCRIPT_REVIEW,
                            )
                            review_format_errors.append(
                                {
                                    "attempt": review_format_attempt,
                                    "missing_fields": list(exc.missing_fields),
                                    "failure_reason": exc.failure_reason,
                                    "response_preview": _stage12_debug_preview(exc.response_preview, limit=600),
                                    "workflow_debug": workflow_debug,
                                }
                            )
                            review_event["format_retry_count"] = review_format_attempt
                            review_event["format_errors"] = review_format_errors
                            debug_record.update(
                                {
                                    "status": "script_review_format_retry",
                                    "review_format_attempt": review_format_attempt,
                                    "review_format_attempt_limit": review_format_attempt_limit,
                                    "updated_at": _now_iso(),
                                }
                            )
                            debug_path = _write_stage12_debug_file(
                                debug_record,
                                data=data,
                                framework_asset=framework_asset,
                            )
                            if review_format_attempt < review_format_attempt_limit:
                                logger.warning(
                                    "framework-to-script stage12 review returned only an unusable event envelope; "
                                    "retrying review without regenerating script: asset_id=%s batch=%s-%s "
                                    "review_round=%s format_attempt=%s/%s missing=%s",
                                    asset_id,
                                    start_episode,
                                    end_episode,
                                    review_round,
                                    review_format_attempt,
                                    review_format_attempt_limit,
                                    list(exc.missing_fields),
                                )
                                _stage12_set_run(
                                    status="running",
                                    current_sub_stage="script_review_format_retry",
                                    progress_text=(
                                        f"第 12 阶段第 {start_episode}-{end_episode} 集审核返回不完整，"
                                        f"正在重试审核 {review_format_attempt}/{review_format_attempt_limit}"
                                    ),
                                    raw_debug_path=debug_path,
                                    latest_partial_result={
                                        "sub_stage": "script_review_format_retry",
                                        "start_episode": start_episode,
                                        "end_episode": end_episode,
                                        "review_round": review_round,
                                        "format_attempt": review_format_attempt,
                                        "format_attempt_limit": review_format_attempt_limit,
                                    },
                                )
                                time.sleep(min(review_format_attempt, 2))
                                continue

                            structure_issues = _stage12_script_structure_issues(
                                batch_script,
                                start_episode=start_episode,
                                end_episode=end_episode,
                            )
                            if structure_issues:
                                review_event["local_structure_issues"] = structure_issues
                                raise
                            review_output = {
                                "passed": True,
                                "rewrite_required": False,
                                "blocking_issues": [],
                            }
                            review_event["accepted_by_local_structure_fallback"] = True
                            review_event["local_structure_issues"] = []
                            logger.warning(
                                "framework-to-script stage12 review unavailable after retries; accepting structurally "
                                "complete current script and continuing: asset_id=%s batch=%s-%s review_round=%s",
                                asset_id,
                                start_episode,
                                end_episode,
                                review_round,
                            )
                            break
                    review_event["tencent_request_ended_at"] = _now_iso()
                    review_event["duration_ms"] = int((time.monotonic() - review_started) * 1000)
                    review_event["tencent_debug"] = _stage12_workflow_debug_summary(tencent_workflow_client, STAGE_FRAMEWORK_SCRIPT_REVIEW)
                    review_event["http_status"] = review_event["tencent_debug"].get("http_status")
                    review_keys = sorted(review_output.keys()) if isinstance(review_output, dict) else []
                    if not isinstance(review_output, dict):
                        review_output = {}
                    review_passed = _get_bool_alias(review_output, "reviewPassed", "passed", default=None)
                    rewrite_required = _get_bool_alias(review_output, "rewriteRequired", "rewrite_required", default=None)
                    blocking_issues = _get_list_alias(review_output, "blockingIssues", "blocking_issues")
                    non_blocking_issues = _get_list_alias(review_output, "nonBlockingIssues", "non_blocking_issues")
                    rewrite_brief = _first_present(review_output, "rewriteBrief", "rewrite_brief", default="")
                    if review_passed is None and rewrite_required is None:
                        logger.warning(
                            "framework-to-script stage12 script_review missing reviewPassed/passed and rewriteRequired/rewrite_required; "
                            "treating as rewrite needed review_output_keys=%s",
                            review_keys,
                        )
                        review_passed = False
                        rewrite_required = True
                    script_review = {
                        "reviewPassed": review_passed,
                        "passed": review_passed,
                        "rewriteRequired": rewrite_required,
                        "rewrite_required": rewrite_required,
                        "blockingIssues": blocking_issues,
                        "blocking_issues": blocking_issues,
                        "nonBlockingIssues": non_blocking_issues,
                        "non_blocking_issues": non_blocking_issues,
                        "rewriteBrief": rewrite_brief,
                        "rewrite_brief": rewrite_brief,
                    }
                    rewrite_triggered = _framework_review_needs_rewrite(script_review)
                    review_result_summary = {
                        "reviewPassed": review_passed,
                        "rewriteRequired": rewrite_required,
                        "blockingIssues_count": len(blocking_issues),
                        "blockingIssues_preview": _stage12_debug_preview(blocking_issues),
                        "nonBlockingIssues_count": len(non_blocking_issues),
                        "nonBlockingIssues_preview": _stage12_debug_preview(non_blocking_issues),
                        "rewriteBrief_length": len(str(rewrite_brief or "")),
                        "rewriteBrief_preview": _stage12_debug_preview(rewrite_brief),
                        "rewrite_triggered": rewrite_triggered,
                    }
                    review_event.update(
                        {
                            "raw_response_summary": _stage12_debug_summary(review_output, preview_limit=600),
                            "parsed_fields": review_keys,
                            "review_result": review_result_summary,
                        }
                    )
                    debug_record.update(
                        {
                            "status": "script_review_done",
                            "parsed_fields": review_keys,
                            "review_result": review_result_summary,
                            "updated_at": _now_iso(),
                        }
                    )
                    debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                    _stage12_set_run(
                        status="running",
                        current_sub_stage="script_review",
                        progress_text=(
                            f"第 12 阶段正文审核已返回：第 {start_episode}-{end_episode} 集，"
                            f"{'通过' if review_passed is True and rewrite_required is False else '需要 rewrite'}"
                        ),
                        raw_debug_path=debug_path,
                        latest_partial_result={
                            "sub_stage": "script_review",
                            "start_episode": start_episode,
                            "end_episode": end_episode,
                            "review_round": review_round,
                            "rewrite_round": rewrite_round,
                            "reviewPassed": review_passed,
                            "rewriteRequired": rewrite_required,
                            "blockingIssues_count": len(blocking_issues),
                        },
                    )
                    logger.info(
                        "framework-to-script stage12 review loop: stage=%s batchStartEpisode=%s review_round=%s "
                        "rewrite_round=%s reviewPassed=%s rewriteRequired=%s blockingIssues_count=%s "
                        "review_output_keys=%s batchScriptReview_type=%s nonBlockingIssues_count=%s "
                        "rewriteBrief_length=%s rewrite_triggered=%s",
                        "stage12",
                        start_episode,
                        review_round,
                        rewrite_round,
                        review_passed,
                        rewrite_required,
                        len(blocking_issues),
                        review_keys,
                        type(script_review).__name__,
                        len(non_blocking_issues),
                        len(str(rewrite_brief or "")),
                        rewrite_triggered,
                    )
                    if review_passed is True and rewrite_required is False:
                        break
                    if review_round >= max_review_rounds:
                        script_review["acceptedAfterMaxReview"] = True
                        script_review["accepted_after_max_review"] = True
                        script_review["maxReviewRounds"] = max_review_rounds
                        script_review["max_review_rounds"] = max_review_rounds
                        debug_record.update(
                            {
                                "status": "script_review_max_rounds_accepting_current",
                                "failure_phase": "审核/重写",
                                "failed_sub_stage": "script_review",
                                "review_attempt": review_round,
                                "rewrite_attempt": rewrite_round,
                                "rewrite_reason": _stage12_debug_preview(blocking_issues or rewrite_brief),
                                "updated_at": _now_iso(),
                            }
                        )
                        debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                        logger.warning(
                            "framework-to-script stage12 review reached max rounds; accepting current script and continuing: "
                            "asset_id=%s batchStartEpisode=%s review_round=%s rewrite_round=%s",
                            asset_id,
                            start_episode,
                            review_round,
                            rewrite_round,
                        )
                        _stage12_set_run(
                            status="running",
                            current_sub_stage="script_review",
                            progress_text=f"第 12 阶段第 {start_episode}-{end_episode} 集审核达到上限，保留当前正文并继续",
                            raw_debug_path=debug_path,
                            latest_partial_result={
                                "sub_stage": "script_review",
                                "start_episode": start_episode,
                                "end_episode": end_episode,
                                "review_round": review_round,
                                "rewrite_round": rewrite_round,
                                "reviewPassed": review_passed,
                                "rewriteRequired": rewrite_required,
                                "acceptedAfterMaxReview": True,
                            },
                        )
                        break
                    failed_sub_stage = "script_rewrite"
                    rewrite_round += 1
                    debug_record.update(
                        {
                            "status": "requesting_tencent",
                            "failed_sub_stage": failed_sub_stage,
                            "review_attempt": review_round,
                            "rewrite_attempt": rewrite_round,
                            "rewrite_reason": _stage12_debug_preview(blocking_issues or rewrite_brief),
                            "updated_at": _now_iso(),
                        }
                    )
                    logger.info(
                        "framework-to-script stage12 rewrite loop: stage=%s batchStartEpisode=%s review_round=%s "
                        "rewrite_round=%s reviewPassed=%s rewriteRequired=%s blockingIssues_count=%s",
                        "stage12",
                        start_episode,
                        review_round,
                        rewrite_round,
                        review_passed,
                        rewrite_required,
                        len(blocking_issues),
                    )
                    rewrite_vars = _inject_snapshot_stage_preference(
                        {
                            **base_vars,
                            "batchScriptText": batch_script,
                            "batchScriptReview": script_review,
                        },
                        data,
                        "12",
                        framework_asset=framework_asset,
                        workflow_stage="12_rewrite",
                    )
                    rewrite_event = {
                        "sub_stage": "script_rewrite",
                        "attempt": 1,
                        "review_attempt": review_round,
                        "rewrite_attempt": rewrite_round,
                        "rewrite_reason": _stage12_debug_preview(blocking_issues or rewrite_brief),
                        "tencent_request_started_at": _now_iso(),
                        "request_variable_keys": sorted(rewrite_vars.keys()),
                        "batchScriptText_length": len(batch_script),
                        "batchScriptText_preview": _stage12_debug_preview(batch_script),
                        "batchScriptReview_summary": _stage12_debug_summary(script_review),
                    }
                    debug_record["events"].append(rewrite_event)
                    debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                    _stage12_set_run(
                        status="running",
                        current_sub_stage="script_rewrite",
                        progress_text=f"第 12 阶段正文重写中：第 {start_episode}-{end_episode} 集，第 {rewrite_round} 轮",
                        raw_debug_path=debug_path,
                        latest_partial_result={
                            "sub_stage": "script_rewrite",
                            "start_episode": start_episode,
                            "end_episode": end_episode,
                            "review_round": review_round,
                            "rewrite_round": rewrite_round,
                            "batchScriptText_length": len(batch_script),
                        },
                    )
                    rewrite_started = time.monotonic()
                    rewrite_output = tencent_workflow_client.run_stage(
                        STAGE_FRAMEWORK_SCRIPT_REWRITE,
                        rewrite_vars,
                    )
                    rewrite_event["tencent_request_ended_at"] = _now_iso()
                    rewrite_event["duration_ms"] = int((time.monotonic() - rewrite_started) * 1000)
                    rewrite_event["tencent_debug"] = _stage12_workflow_debug_summary(tencent_workflow_client, STAGE_FRAMEWORK_SCRIPT_REWRITE)
                    rewrite_event["http_status"] = rewrite_event["tencent_debug"].get("http_status")
                    rewrite_keys = sorted(rewrite_output.keys()) if isinstance(rewrite_output, dict) else []
                    rewrite_script_value = _first_present(rewrite_output, "batchScriptText", "batch_script_text", default=None)
                    batch_script = str(rewrite_script_value or "")
                    rewrite_event["raw_response_summary"] = _stage12_debug_summary(rewrite_output, preview_limit=600)
                    rewrite_event["parsed_fields"] = rewrite_keys
                    rewrite_event["batchScriptText_length_after"] = len(batch_script)
                    rewrite_event["parse_failure_reason"] = "" if batch_script.strip() else "missing_or_empty_batchScriptText"
                    debug_record.update(
                        {
                            "status": "script_rewrite_done" if batch_script.strip() else "parse_failed",
                            "parsed_fields": rewrite_keys,
                            "parse_failure_reason": rewrite_event["parse_failure_reason"],
                            "raw_response_summary": _stage12_debug_summary(rewrite_output, preview_limit=600),
                            "updated_at": _now_iso(),
                        }
                    )
                    debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                    _stage12_set_run(
                        status="running",
                        current_sub_stage="script_rewrite",
                        progress_text=f"第 12 阶段正文重写已返回：第 {start_episode}-{end_episode} 集",
                        raw_debug_path=debug_path,
                        latest_partial_result={
                            "sub_stage": "script_rewrite",
                            "start_episode": start_episode,
                            "end_episode": end_episode,
                            "review_round": review_round,
                            "rewrite_round": rewrite_round,
                            "batchScriptText_length": len(batch_script),
                            "batchScriptText_empty": not bool(batch_script.strip()),
                        },
                    )
                    logger.info(
                        "framework-to-script stage12 script_rewrite output rewrite_output_keys=%s batchScriptText_length=%s "
                        "normalized_keys=%s",
                        rewrite_keys,
                        len(batch_script),
                        ["batchScriptText", "batch_script_text"],
                    )
                    if not batch_script.strip():
                        debug_record.update(
                            {
                                "status": "failed",
                                "failure_phase": "解析",
                                "failed_sub_stage": "script_rewrite",
                                "exception_type": "",
                                "exception_message": "12 write/rewrite 阶段未返回 batchScriptText",
                                "updated_at": _now_iso(),
                            }
                        )
                        debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                        return jsonify(
                            {
                                "success": False,
                                "message": f"12 阶段第 {start_episode}-{end_episode} 集生成失败/解析失败：rewrite 未返回正文。",
                                "detail": {
                                    "failed_sub_stage": "script_rewrite",
                                    "error_message": "12 write/rewrite 阶段未返回 batchScriptText",
                                    "rewrite_output_keys": rewrite_keys,
                                    "debug_path": debug_path,
                                },
                        }
                    ), 500
                failed_sub_stage = "script_memory"
                memory_vars = {
                    **base_vars,
                    "batchScriptText": batch_script,
                    "scriptMemory": script_memory,
                    "scriptStartEpisode": start_episode,
                }
                debug_record.update(
                    {
                        "status": "requesting_tencent",
                        "failed_sub_stage": failed_sub_stage,
                        "review_attempt": review_round if "review_round" in locals() else 0,
                        "rewrite_attempt": rewrite_round,
                        "updated_at": _now_iso(),
                    }
                )
                memory_event = {
                    "sub_stage": "script_memory",
                    "attempt": 1,
                    "review_attempt": review_round if "review_round" in locals() else 0,
                    "rewrite_attempt": rewrite_round,
                    "tencent_request_started_at": _now_iso(),
                    "request_variable_keys": sorted(memory_vars.keys()),
                    "batchScriptText_length": len(batch_script),
                    "batchScriptText_preview": _stage12_debug_preview(batch_script),
                    "scriptMemory_length_before": len(script_memory),
                    "scriptMemory_preview_before": _stage12_debug_preview(script_memory),
                }
                debug_record["events"].append(memory_event)
                debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                _stage12_set_run(
                    status="running",
                    current_sub_stage="script_memory",
                    progress_text=f"第 12 阶段正文记忆写入中：第 {start_episode}-{end_episode} 集",
                    raw_debug_path=debug_path,
                    latest_partial_result={
                        "sub_stage": "script_memory",
                        "start_episode": start_episode,
                        "end_episode": end_episode,
                        "review_round": review_round if "review_round" in locals() else 0,
                        "rewrite_round": rewrite_round,
                        "batchScriptText_length": len(batch_script),
                    },
                )
                memory_started = time.monotonic()
                memory_output = tencent_workflow_client.run_stage(
                    STAGE_FRAMEWORK_SCRIPT_MEMORY,
                    memory_vars,
                )
                memory_event["tencent_request_ended_at"] = _now_iso()
                memory_event["duration_ms"] = int((time.monotonic() - memory_started) * 1000)
                memory_event["tencent_debug"] = _stage12_workflow_debug_summary(tencent_workflow_client, STAGE_FRAMEWORK_SCRIPT_MEMORY)
                memory_event["http_status"] = memory_event["tencent_debug"].get("http_status")
                memory_keys = sorted(memory_output.keys()) if isinstance(memory_output, dict) else []
                memory_value = _first_present(memory_output, "scriptMemory", "script_memory", default=None)
                if memory_value is None or not str(memory_value).strip():
                    raise RuntimeError("12 memory 阶段未返回有效 scriptMemory，当前批次不会保存，请重试本批次。")
                script_memory = str(memory_value)
                memory_event.update(
                    {
                        "raw_response_summary": _stage12_debug_summary(memory_output, preview_limit=600),
                        "parsed_fields": memory_keys,
                        "scriptMemory_length_after": len(script_memory),
                        "scriptMemory_preview_after": _stage12_debug_preview(script_memory),
                    }
                )
                debug_record.update(
                    {
                        "status": "script_memory_done",
                        "parsed_fields": memory_keys,
                        "scriptMemory_length": len(script_memory),
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                _stage12_set_run(
                    status="running",
                    current_sub_stage="script_memory",
                    progress_text=f"第 12 阶段正文记忆已返回：第 {start_episode}-{end_episode} 集",
                    raw_debug_path=debug_path,
                    latest_partial_result={
                        "sub_stage": "script_memory",
                        "start_episode": start_episode,
                        "end_episode": end_episode,
                        "review_round": review_round if "review_round" in locals() else 0,
                        "rewrite_round": rewrite_round,
                        "scriptMemory_length": len(script_memory),
                    },
                )
                logger.info(
                    "framework-to-script stage12 script_memory output memory_output_keys=%s normalized_keys=%s scriptMemory_length=%s",
                    memory_keys,
                    ["scriptMemory", "script_memory"],
                    len(script_memory),
                )
            except Exception as exc:
                debug_record.update(
                    {
                        "status": "failed",
                        "failure_phase": failed_sub_stage,
                        "failed_sub_stage": failed_sub_stage,
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                        "traceback": traceback.format_exc(),
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                logger.exception(
                    "framework-to-script stage12 failed failed_sub_stage=%s asset_id=%s start_episode=%s "
                    "end_episode=%s batch_plan_count=%s base_vars_keys=%s error_type=%s error_message=%s",
                    failed_sub_stage,
                    asset_id,
                    start_episode,
                    end_episode,
                    len(batch_plan),
                    sorted(base_vars.keys()),
                    type(exc).__name__,
                    str(exc),
                )
                return jsonify(
                    {
                        "success": False,
                        "message": f"12 阶段第 {start_episode or batch_key}-{end_episode or '?'} 集生成失败：{failed_sub_stage}",
                        "detail": {
                            "failed_sub_stage": failed_sub_stage,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "asset_id": asset_id,
                            "start_episode": start_episode,
                            "end_episode": end_episode,
                            "batch_plan_count": len(batch_plan),
                            "base_var_keys": sorted(base_vars.keys()),
                            "debug_path": debug_path,
                        },
                    }
                ), 500

            batches = dict(existing_batches)
            batch_output = {
                "batchStartEpisode": start_episode,
                "batchEndEpisode": end_episode,
                "batchPipelineStatus": "complete",
                "batch_pipeline_status": "complete",
                "completedSubStages": [
                    "script_write",
                    "script_review",
                    *([] if not rewrite_round else ["script_rewrite"]),
                    "script_memory",
                ],
                "completed_sub_stages": [
                    "script_write",
                    "script_review",
                    *([] if not rewrite_round else ["script_rewrite"]),
                    "script_memory",
                ],
                "batchEnrichedEpisodePlan": batch_plan,
                "batchCausalConflictPlan": conflict_plan,
                "batch_causal_conflict_plan": conflict_plan,
                "batchScriptText": batch_script,
                "batch_script_text": batch_script,
                "batchScriptReview": script_review,
                "batch_script_review": script_review,
                "scriptMemory": script_memory,
                "script_memory": script_memory,
                "stage12DebugPath": debug_path,
            }
            batches[str(start_episode)] = batch_output
            output = {**batch_output, "batches": batches}
            if asset_id:
                debug_record.update(
                    {
                        "status": "saving",
                        "final_save_fields": sorted(batch_output.keys()),
                        "final_batchScriptText_length": len(batch_script),
                        "final_scriptMemory_length": len(script_memory),
                        "updated_at": _now_iso(),
                    }
                )
                debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
                _save_framework_to_script_stage(
                    user_id=user_id,
                    asset_id=asset_id,
                    stage_key="stage12",
                    output=output,
                )
            debug_record.update(
                {
                    "status": "success",
                    "failure_phase": "",
                    "failed_sub_stage": "",
                    "final_save_fields": sorted(batch_output.keys()),
                    "final_batchScriptText_length": len(batch_script),
                    "final_scriptMemory_length": len(script_memory),
                    "updated_at": _now_iso(),
                }
            )
            debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset)
            success_debug_path = _write_stage12_debug_file(debug_record, data=data, framework_asset=framework_asset, success=True)
            if debug_path:
                output["stage12DebugPath"] = debug_path
            _stage12_set_run(
                status="running",
                current_sub_stage="stage12_batch_saved",
                progress_text=f"第 12 阶段第 {start_episode}-{end_episode} 集已保存",
                raw_debug_path=debug_path,
                latest_partial_result={
                    "start_episode": start_episode,
                    "end_episode": end_episode,
                    "completed_batch_starts": _sorted_numeric_batch_keys(batches),
                    "latest_batch_done": start_episode,
                },
                latest_result_preview={
                    "batchStartEpisode": start_episode,
                    "batchEndEpisode": end_episode,
                    "batches": _sorted_numeric_batch_keys(batches),
                },
            )
            if success_debug_path:
                output["stage12SuccessDebugPath"] = success_debug_path
        finally:
            if not is_stage12_worker:
                _end_framework_stage(user_id, asset_id, "12")

        return _json_ok(stage="12", framework_asset_id=asset_id, **output)


    @app.route("/api/framework-to-script/export/txt", methods=["GET", "POST"])
    @_login_required
    def export_framework_to_script_txt_api():
        data = request.get_json(silent=True) if request.method == "POST" else {}
        data = data if isinstance(data, dict) else {}
        asset_id = str(
            request.args.get("framework_asset_id")
            or data.get("framework_asset_id")
            or request.args.get("asset_id")
            or data.get("asset_id")
            or ""
        ).strip()
        if not asset_id:
            return _json_error("缺少 framework_asset_id。", status=400)
        asset = _load_framework_asset_for_user(asset_id, _require_user_id())
        if not asset:
            return _json_error("框架资产不存在、无权访问，或尚未生成 07 最终策划包。", status=404)
        text = _framework_to_script_txt(asset)
        filename_title = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(asset.get("title") or "framework_script_txt"))
        filename = f"{filename_title[:48] or 'framework_script'}.txt"
        return Response(
            text,
            content_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )

    @app.route("/api/framework-to-script/export/docx", methods=["GET", "POST"])
    @_login_required
    def export_framework_to_script_docx_api():
        data = request.get_json(silent=True) if request.method == "POST" else {}
        data = data if isinstance(data, dict) else {}
        asset_id = str(
            request.args.get("framework_asset_id")
            or data.get("framework_asset_id")
            or request.args.get("asset_id")
            or data.get("asset_id")
            or ""
        ).strip()
        if not asset_id:
            return _json_error("缺少 framework_asset_id。", status=400)
        asset = _load_framework_asset_for_user(asset_id, _require_user_id())
        if not asset:
            return _json_error("框架资产不存在、无权访问，或尚未生成 07 最终策划包。", status=404)
        text = _framework_to_script_txt(asset)
        filename_title = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(asset.get("title") or "framework_script_docx"))
        filename = f"{filename_title[:48] or 'framework_script'}.docx"
        try:
            from .utils.txt_to_docx import convert as convert_txt_to_docx
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                txt_path = tmp_path / "framework_script.txt"
                docx_path = tmp_path / "framework_script.docx"
                txt_path.write_text(text, encoding="utf-8")
                convert_txt_to_docx(str(txt_path), str(docx_path))
                docx_bytes = docx_path.read_bytes()
                return send_file(
                    BytesIO(docx_bytes),
                    as_attachment=True,
                    download_name=filename,
                    mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
        except ModuleNotFoundError as exc:
            if exc.name == "docx":
                return _json_error("当前环境缺少 python-docx，暂时无法导出 DOCX。", status=500)
            raise
        except Exception as exc:
            logger.exception("framework-to-script docx export failed")
            return _json_error(str(exc), status=500, fallback="DOCX 导出失败，请稍后重试。")


    @app.get("/framework-to-script")
    @_login_required
    def framework_to_script_workspace():
        return render_template("framework_to_script.html")

    @app.post("/api/framework-planner/assets/save")
    @_login_required
    def save_framework_planner_asset_api():
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _json_error("保存内容格式不正确", status=400)
        try:
            user_id = _require_user_id()
            asset = task_manager.save_framework_planner_asset(
                user_id=user_id,
                payload=data,
            )
            workspace_state = (
                data.get("framework_to_script_state")
                if isinstance(data.get("framework_to_script_state"), dict)
                else data.get("workspace_state")
                if isinstance(data.get("workspace_state"), dict)
                else {}
            )
            script_asset = None
            if workspace_state:
                framework_snapshot = task_manager.get_project_snapshot(
                    int(asset.get("project_id") or 0),
                    user_id=user_id,
                    public_view=False,
                )
                if framework_snapshot:
                    script_asset = task_manager.save_framework_to_script_asset(
                        user_id=user_id,
                        framework_snapshot=framework_snapshot,
                        workspace_state=workspace_state,
                        final_text=task_manager._framework_to_script_final_text(
                            {"artifacts": {"framework_to_script_state": workspace_state}}
                        ),
                    )
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        except Exception as exc:
            logger.exception("framework planner asset save failed")
            return _json_error(str(exc), status=500, fallback="当前框架保存失败，请稍后重试。")
        return _json_ok(
            asset=asset,
            project=asset,
            project_id=asset.get("project_id"),
            script_asset=script_asset,
        )

    @app.get("/api/community")
    def community_assets():
        assets = task_manager.list_public_assets()
        return _json_ok(assets=assets)

    @app.get("/api/community/<int:project_id>")
    def community_asset_detail(project_id: int):
        asset = task_manager.get_public_asset(project_id)
        if not asset:
            return _json_error("公开作品不存在", status=404)
        return _json_ok(asset=asset)

    @app.get("/api/projects/<int:project_id>")
    @_login_required
    def get_project(project_id: int):
        snapshot = task_manager.get_project_snapshot(project_id, user_id=_require_user_id())
        if not snapshot:
            return _json_error("项目不存在", status=404)
        return _json_ok(project=snapshot)

    @app.patch("/api/projects/<int:project_id>")
    @_login_required
    def update_project(project_id: int):
        data = request.get_json(silent=True) or {}
        try:
            snapshot = task_manager.update_project_asset(
                project_id,
                user_id=_require_user_id(),
                changes=data,
            )
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return _json_ok(project=snapshot)

    @app.post("/api/projects/<int:project_id>/confirm-completion")
    @_login_required
    def confirm_project_completion(project_id: int):
        try:
            snapshot = task_manager.confirm_project_completion(
                project_id,
                user_id=_require_user_id(),
            )
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return _json_ok(project=snapshot)

    @app.post("/api/projects/<int:project_id>/rollback")
    @_login_required
    def rollback_project(project_id: int):
        data = request.get_json(silent=True) or {}
        try:
            snapshot = task_manager.rollback_project_to_stage(
                project_id,
                user_id=_require_user_id(),
                stage_key=str(data.get("stage_key") or ""),
                start_episode=data.get("start_episode"),
            )
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return _json_ok(task=snapshot)


    @app.post("/api/framework-planner/generate-script")
    @_login_required
    def generate_script_from_framework_planner():
        data = request.get_json(silent=True) or {}

        framework_plan_package = data.get("framework_plan_package")
        if not isinstance(framework_plan_package, dict) or not framework_plan_package:
            return _json_error(
                "缺少 framework_plan_package，请先完成并确认 07 最终策划包输出。",
                status=400,
            )

        basic_config = data.get("basic_config") if isinstance(data.get("basic_config"), dict) else {}
        title = (
            str(data.get("source_title") or "")
            or str(basic_config.get("source_title") or "")
            or str(data.get("title") or "")
            or str(data.get("project_title") or "")
            or str(basic_config.get("project_title") or "")
            or "未命名框架剧本"
        ).strip()

        def _safe_int(value, default):
            try:
                number = int(value)
                return number if number > 0 else default
            except Exception:
                return default

        total_episodes = _safe_int(
            data.get("total_episodes")
            or data.get("episodes_per_season")
            or basic_config.get("episodes_per_season"),
            60,
        )
        episode_word_count = _safe_int(
            data.get("episode_word_count")
            or data.get("chars_per_episode")
            or basic_config.get("episode_word_count")
            or basic_config.get("chars_per_episode"),
            600,
        )

        expectation_parts = [
            str(data.get("user_expectation") or "").strip(),
            str(data.get("adaptation_direction") or basic_config.get("adaptation_direction") or "").strip(),
            str(data.get("user_requirements") or basic_config.get("user_requirements") or "").strip(),
        ]
        expectation = "\n".join([item for item in expectation_parts if item]).strip()
        if not expectation:
            expectation = f"基于《{title}》的三幕十五节拍框架策划包生成短剧正文。"

        payload = {
            "title": title,
            "project_title": title,
            "source_title": str(data.get("source_title") or basic_config.get("source_title") or title),
            "target_format": str(data.get("target_format") or basic_config.get("target_format") or "短剧"),
            "season_count": _safe_int(data.get("season_count") or basic_config.get("season_count"), 1),
            "episodes_per_season": total_episodes,
            "total_episodes": total_episodes,
            "episode_word_count": episode_word_count,
            "chars_per_episode": episode_word_count,
            "user_expectation": expectation,
            "user_requirements": str(data.get("user_requirements") or basic_config.get("user_requirements") or ""),
            "adaptation_direction": str(data.get("adaptation_direction") or basic_config.get("adaptation_direction") or ""),
            "basic_config": basic_config,
            "framework_plan_package": framework_plan_package,
            "source_framework_project_id": data.get("source_framework_project_id") or data.get("project_id"),
            "source_brief": data.get("source_brief") or framework_plan_package.get("source_brief") or {},
            "worldview_plan": data.get("worldview_plan") or framework_plan_package.get("worldview_plan") or {},
            "character_plan": data.get("character_plan") or framework_plan_package.get("character_plan") or {},
            "beat_checkpoint_timeline": data.get("beat_checkpoint_timeline") or framework_plan_package.get("beat_checkpoint_timeline") or [],
            "checkpoint_explanation": data.get("checkpoint_explanation") or framework_plan_package.get("checkpoint_explanation") or {},
            "character_storylines": data.get("character_storylines") or framework_plan_package.get("character_storylines") or [],
            "storyline_decisions": data.get("storyline_decisions") or framework_plan_package.get("storyline_decisions") or [],
            "adaptation_guide": data.get("adaptation_guide") or framework_plan_package.get("adaptation_guide") or {},
            "workflow_mode": "framework_to_script",
            "generation_chain": "framework_to_script",
            "framework_to_script": True,
        "script_format_mode": "framework_to_script",
            "framework_planner_source": True,
        }
        if isinstance(data.get("user_knowledge_step_prompts"), dict):
            payload["user_knowledge_step_prompts"] = data.get("user_knowledge_step_prompts")

        _attach_user_knowledge_payload(payload, data)

        try:
            snapshot = task_manager.start_task(
                user_id=_require_user_id(),
                input_payload=payload,
                workflow_spec_path=_resolve_spec_path(data),
                model_selection_id=data.get("model_selection_id"),
            )
        except Exception as exc:
            return _json_error(
                str(exc),
                status=400,
                fallback="框架转剧本任务创建失败，请检查 腾讯工作流 token 和 workflow_id 配置。",
            )

        return _json_ok(task=snapshot)


    @app.post("/api/workflows/start")
    @_login_required
    def start_workflow():
        data = request.get_json(silent=True) or {}
        spec_path = _resolve_spec_path(data)
        expectation = str(data.get("user_expectation", ""))
        payload = {
            "title": data.get("title", "") or derive_script_title_content(expectation),
            "episode_word_count": data.get("episode_word_count") or data.get("chars_per_episode") or 600,
            "chars_per_episode": data.get("chars_per_episode") or data.get("episode_word_count") or 600,
            "total_episodes": data.get("total_episodes", 0),
            "user_expectation": expectation,
            "character_count": data.get("character_count", 0),
        }
        for optional_key in (
            "character_appearance_requirements",
            "character_alias_naming_rules",
            "outfit_switch_rules",
            "story_outline",
            "core_scene_input",
            "character_bios",
            "episode_plan",
            "script_format_mode",
            "framework_plan_package",
            "worldview_plan",
            "beat_checkpoint_timeline",
            "character_storylines",
            "character_plan",
        ):
            value = data.get(optional_key)
            if value not in (None, "", [], {}):
                payload[optional_key] = value
        _attach_user_knowledge_payload(payload, data)
        try:
            snapshot = task_manager.start_task(
                user_id=_require_user_id(),
                input_payload=payload,
                workflow_spec_path=spec_path,
                model_selection_id=data.get("model_selection_id"),
            )
        except Exception as exc:
            return _json_error(str(exc), status=400, fallback="任务创建失败，请稍后重试。")
        return _json_ok(task=snapshot)

    @app.post("/api/projects/<int:project_id>/restart")
    @_login_required
    def restart_project(project_id: int):
        data = request.get_json(silent=True) or {}
        spec_path = _resolve_spec_path(data)
        expectation = str(data.get("user_expectation", ""))
        payload = {
            "title": data.get("title", "") or derive_script_title_content(expectation),
            "episode_word_count": data.get("episode_word_count") or data.get("chars_per_episode") or 600,
            "chars_per_episode": data.get("chars_per_episode") or data.get("episode_word_count") or 600,
            "total_episodes": data.get("total_episodes", 0),
            "user_expectation": expectation,
            "character_count": data.get("character_count", 0),
        }
        for optional_key in (
            "character_appearance_requirements",
            "character_alias_naming_rules",
            "outfit_switch_rules",
            "story_outline",
            "core_scene_input",
            "character_bios",
            "episode_plan",
            "script_format_mode",
            "framework_plan_package",
            "worldview_plan",
            "beat_checkpoint_timeline",
            "character_storylines",
            "character_plan",
        ):
            value = data.get(optional_key)
            if value not in (None, "", [], {}):
                payload[optional_key] = value
        _attach_user_knowledge_payload(payload, data)
        try:
            snapshot = task_manager.restart_project(
                project_id,
                user_id=_require_user_id(),
                input_payload=payload,
                workflow_spec_path=spec_path,
                model_selection_id=data.get("model_selection_id"),
            )
        except Exception as exc:
            return _json_error(str(exc), status=400, fallback="重新开始失败，请稍后重试。")
        return _json_ok(task=snapshot)

    @app.get("/api/tasks/<task_id>")
    @_login_required
    def get_task(task_id: str):
        snapshot = task_manager.get_task_snapshot(task_id, user_id=_require_user_id())
        if not snapshot:
            return _json_error("任务不存在", status=404)
        return _json_ok(task=snapshot)

    @app.get("/api/tasks/<task_id>/debug")
    @_login_required
    def get_task_debug(task_id: str):
        snapshot = task_manager.get_task_snapshot(
            task_id,
            user_id=_require_user_id(),
            public_view=False,
        )
        if not snapshot:
            return _json_error("任务不存在", status=404)

        return _json_ok(
            debug={
                "task_id": snapshot.get("task_id"),
                "project_id": snapshot.get("project_id"),
                "status": snapshot.get("status"),
                "message": snapshot.get("message"),
                "error": snapshot.get("error"),
                "current_stage": snapshot.get("current_stage"),
                "current_stage_label": snapshot.get("current_stage_label"),
                "current_node_id": snapshot.get("current_node_id"),
                "current_node_name": snapshot.get("current_node_name"),
                "current_batch": snapshot.get("current_batch"),
                "progress_percent": snapshot.get("progress_percent"),
                "generated_episodes": snapshot.get("generated_episodes"),
                "cache_retained": snapshot.get("cache_retained"),
                "awaiting_user_confirmation": snapshot.get("awaiting_user_confirmation"),
                "runtime_cache_notice": snapshot.get("runtime_cache_notice"),
                "logs": snapshot.get("logs", []),
                "last_log": snapshot.get("last_log"),
                "resume_checkpoint_exists": isinstance(snapshot.get("_resume_checkpoint"), dict),
                "resume_checkpoint": snapshot.get("_resume_checkpoint"),
                "debug_state": snapshot.get("debug_state", {}),
                "prompt_fixes": snapshot.get("prompt_fixes", []),
            }
        )

    @app.post("/api/tasks/<task_id>/pause")
    @_login_required
    def pause_task(task_id: str):
        try:
            snapshot = task_manager.pause_task(task_id, user_id=_require_user_id())
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return _json_ok(task=snapshot)

    @app.post("/api/tasks/<task_id>/resume")
    @_login_required
    def resume_task(task_id: str):
        try:
            snapshot = task_manager.resume_task(task_id, user_id=_require_user_id())
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return _json_ok(task=snapshot)

    @app.post("/api/tasks/<task_id>/retry")
    @_login_required
    def retry_task(task_id: str):
        try:
            snapshot = task_manager.retry_task(task_id, user_id=_require_user_id())
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return _json_ok(task=snapshot)

    @app.post("/api/tasks/<task_id>/terminate")
    @_login_required
    def terminate_task(task_id: str):
        try:
            snapshot = task_manager.terminate_task(task_id, user_id=_require_user_id())
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return _json_ok(task=snapshot)

    @app.delete("/api/tasks/<task_id>")
    @_login_required
    def delete_task(task_id: str):
        try:
            task_manager.delete_task(task_id, user_id=_require_user_id())
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return _json_ok(task_id=task_id)

    @app.delete("/api/projects/<int:project_id>")
    @_login_required
    def clear_project(project_id: int):
        try:
            task_manager.clear_project(project_id, user_id=_require_user_id())
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return _json_ok(project_id=project_id)

    @app.post("/api/projects/<int:project_id>/save")
    @_login_required
    def save_project(project_id: int):
        try:
            path = task_manager.save_final_script(project_id, user_id=_require_user_id())
        except ValueError as exc:
            return _json_error(str(exc), status=400, fallback="当前剧本暂时无法导出，请确认已生成完成后再试。")
        return _json_ok(project_id=project_id, saved_file=str(path))

    @app.get("/api/projects/<int:project_id>/download")
    @_login_required
    def download_project(project_id: int):
        try:
            path = task_manager.save_final_script(project_id, user_id=_require_user_id())
        except ValueError as exc:
            return _json_error(str(exc), status=400, fallback="当前剧本暂时无法下载，请确认已生成完成后再试。")
        return send_file(
            path,
            as_attachment=True,
            download_name=path.name,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    print(
        "[route-probe] framework history route registered =",
        any(str(rule) == "/api/framework-planner/history" for rule in app.url_map.iter_rules()),
        flush=True,
    )

    return app
