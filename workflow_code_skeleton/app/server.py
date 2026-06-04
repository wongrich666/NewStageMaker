from __future__ import annotations

import json
import copy
import threading
import tempfile
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
from .services.fastgpt_client import FastGPTTransientError
from .services.framework_planner_service import (
    FRAMEWORK_PLANNER_STORAGE_KEY,
    FrameworkPlannerStageError,
    framework_planner_backend_ready,
    framework_planner_fastgpt_diagnostics,
    list_framework_stage_history,
    load_framework_stage_history,
    run_framework_planner_score,
    run_framework_planner_stage,
    save_framework_stage_history,
    write_framework_frontend_debug_event,
    write_framework_stage_exception_log,
)
from .services.simple_fastgpt_tools import ToolExecutionError, list_simple_tools, run_simple_tool
from .services.task_manager import task_manager
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


def default_workflow_spec_path() -> str:
    return str(Path.home() / "Downloads" / "剧本生成_0401_loops.json")


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
            "fastgpt",
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

    raw_fastgpt_response_keys = {
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
    framework_stage_runs: set[tuple[int, str, str]] = set()
    framework_stage_runs_lock = threading.Lock()

    def _now_iso() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat()

    def _strip_raw_fastgpt_fields(value):
        if isinstance(value, list):
            return [_strip_raw_fastgpt_fields(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if str(key) in raw_fastgpt_response_keys:
                continue
            result[key] = _strip_raw_fastgpt_fields(item)
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
        return _strip_raw_fastgpt_fields(outputs)

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
            return _strip_raw_fastgpt_fields(synthesized)
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
            return copy.deepcopy(basic)
        existing_basic = existing_state.get("basic_config") if isinstance(existing_state.get("basic_config"), dict) else {}
        merged = copy.deepcopy(existing_basic)
        for key in (
            "project_title",
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
        ):
            if key in data and _framework_value_present(data.get(key)):
                merged[key] = copy.deepcopy(data.get(key))
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

        raw_project_id = (
            request_payload.get("project_id")
            or request_payload.get("asset_id")
            or request_payload.get("source_framework_project_id")
        )
        existing_state: dict = {}
        if raw_project_id:
            try:
                snapshot = task_manager.get_project_snapshot(int(raw_project_id), user_id=user_id, public_view=False)
            except Exception:
                snapshot = None
            if snapshot and str(snapshot.get("asset_kind") or "").strip() == "framework_planner":
                existing_state = _framework_state_from_project(snapshot)

        save_payload: dict = copy.deepcopy(existing_state)
        if raw_project_id:
            save_payload["project_id"] = raw_project_id
        save_payload["basic_config"] = _framework_basic_config_from_stage_payload(request_payload, existing_state)
        save_payload["project_title"] = (
            request_payload.get("project_title")
            or save_payload.get("project_title")
            or save_payload.get("title")
            or save_payload.get("basic_config", {}).get("project_title")
            or save_payload.get("basic_config", {}).get("source_title")
            or "未命名框架策划"
        )
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
            "selected_preference_tag_ids",
            "selected_preference_tags",
            "user_edit_history",
        ):
            if field in request_payload and _framework_value_present(request_payload.get(field)):
                save_payload[field] = copy.deepcopy(request_payload.get(field))
            elif field not in save_payload:
                save_payload[field] = [] if field in {"selected_preference_tag_ids", "selected_preference_tags", "user_edit_history"} else {}

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
        stage_prompts = _stage_prompts_from_snapshot(preference_snapshot)
        title = str(
            framework_state.get("project_title")
            or project.get("title")
            or basic.get("project_title")
            or basic.get("source_title")
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
        asset = {
            "asset_id": str(project.get("project_id") or framework_state.get("project_id") or ""),
            "project_id": project.get("project_id") or framework_state.get("project_id"),
            "title": title,
            "source_title": source_title,
            "target_format": str(basic.get("target_format") or project.get("target_format") or "短剧"),
            "episodes_per_season": _safe_positive_int(basic.get("episodes_per_season") or project.get("total_episodes"), 0),
            "minutes_per_episode": _safe_positive_int(basic.get("minutes_per_episode"), 0),
            "season_count": _safe_positive_int(basic.get("season_count"), 1),
            "created_at": project.get("created_at") or framework_state.get("created_at"),
            "updated_at": project.get("updated_at") or framework_state.get("updated_at"),
            "summary": summary or "已保存的框架资产，可导入后继续 框架到剧本链路。",
            "can_import": bool(package),
            "import_disabled_reason": "" if package else "缺少可恢复的框架策划包或阶段输出。",
            "stage_prompts": _strip_raw_fastgpt_fields(copy.deepcopy(stage_prompts)),
            "preference_snapshot": _strip_raw_fastgpt_fields(copy.deepcopy(preference_snapshot)),
        }
        if include_detail:
            workspace_state = artifacts.get("framework_to_script_state") if isinstance(artifacts.get("framework_to_script_state"), dict) else {}
            workspace_stage_outputs = (
                workspace_state.get("stageOutputs")
                if isinstance(workspace_state.get("stageOutputs"), dict)
                else {}
            )
            asset.update(
                {
                    "framework_plan_package": _strip_raw_fastgpt_fields(copy.deepcopy(package)),
                    "stage_outputs": _strip_raw_fastgpt_fields({**copy.deepcopy(stage_outputs), **copy.deepcopy(workspace_stage_outputs)}),
                    "framework_to_script_state": _strip_raw_fastgpt_fields(copy.deepcopy(workspace_state)),
                    "scriptStages": _strip_raw_fastgpt_fields(copy.deepcopy(workspace_state.get("scriptStages") or {})),
                    "stage_prompts": _strip_raw_fastgpt_fields(copy.deepcopy(stage_prompts)),
                    "preference_snapshot": _strip_raw_fastgpt_fields(copy.deepcopy(preference_snapshot)),
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

    def _try_begin_framework_stage(user_id: int, asset_id: str, stage: str) -> bool:
        key = (int(user_id), str(asset_id or "").strip(), str(stage or "").strip())
        if not key[1] or not key[2]:
            return True
        with framework_stage_runs_lock:
            if key in framework_stage_runs:
                return False
            framework_stage_runs.add(key)
        return True

    def _end_framework_stage(user_id: int, asset_id: str, stage: str) -> None:
        key = (int(user_id), str(asset_id or "").strip(), str(stage or "").strip())
        with framework_stage_runs_lock:
            framework_stage_runs.discard(key)

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
        clean_output = _strip_raw_fastgpt_fields(copy.deepcopy(output))
        artifacts = snapshot.setdefault("artifacts", {})
        if not isinstance(artifacts, dict):
            artifacts = {}
            snapshot["artifacts"] = artifacts
        workspace_state = artifacts.get("framework_to_script_state")
        if not isinstance(workspace_state, dict):
            workspace_state = {"scriptStages": {}}
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
                stage_outputs[key] = _strip_raw_fastgpt_fields(copy.deepcopy(value))
        for downstream_stage in cascade.get(str(stage_key), ()):
            output_key = downstream_stage.replace("stage", "")
            for key in tuple(stage_outputs.keys()):
                if output_key in str(key):
                    stage_outputs.pop(key, None)
        stages_state = workspace_state.get("stages")
        if not isinstance(stages_state, dict):
            stages_state = {}
        stage_number = str(stage_key).replace("stage", "")
        stages_state[stage_number] = {
            "status": "completed",
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
        completed_set.add(stage_number)
        for downstream_stage in cascade.get(str(stage_key), ()):
            completed_set.discard(str(downstream_stage).replace("stage", ""))
        workspace_state["completedStages"] = sorted(completed_set, key=lambda item: int(item) if item.isdigit() else 999)
        workspace_state["scriptStages"] = script_stages
        workspace_state["stageOutputs"] = stage_outputs
        workspace_state["stages"] = stages_state
        workspace_state["framework_asset_id"] = str(asset_id)
        workspace_state["project_id"] = project_id
        workspace_state["updated_at"] = now
        artifacts["framework_to_script_state"] = workspace_state
        snapshot["updated_at"] = now
        record = task_manager._projects.get(project_id)
        if record:
            with record.lock:
                record.snapshot = snapshot
            task_manager._persist_snapshot(record)
        else:
            try:
                task_manager._project_path(project_id).write_text(
                    json.dumps(snapshot, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                logger.exception("framework-to-script stage snapshot persist failed project_id=%s", project_id)

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
        if not isinstance(merged.get("preference_snapshot"), dict) or not merged.get("preference_snapshot"):
            merged["preference_snapshot"] = (
                asset.get("preference_snapshot")
                if isinstance(asset.get("preference_snapshot"), dict)
                else {}
            )
        if not isinstance(merged.get("stage_prompts"), dict) or not any(_coerce_prompt_text(v) for v in merged.get("stage_prompts", {}).values()):
            merged["stage_prompts"] = (
                asset.get("stage_prompts")
                if isinstance(asset.get("stage_prompts"), dict)
                else {}
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
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("```"):
                text = text.strip("`").strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()
            try:
                value = json.loads(text)
            except Exception as exc:
                return {}, unwrapped, f"string JSON parse failed: {exc}"
        for key in keys:
            if isinstance(value, dict) and isinstance(value.get(key), dict):
                value = value.get(key)
                unwrapped = True
                break
            if isinstance(value, dict) and isinstance(value.get(key), str):
                try:
                    value = json.loads(value.get(key).strip())
                    unwrapped = True
                    break
                except Exception as exc:
                    return {}, unwrapped, f"wrapped string JSON parse failed: {exc}"
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
        return "\n\n".join(
            [
                f"《{title}》",
                "一、故事梗概\n" + _txt_readable(story),
                "二、人物小传\n" + _txt_readable(characters),
                "三、核心场景\n" + _txt_readable(scenes),
                "四、剧本正文\n" + script_text,
            ]
        ) + "\n"

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
        return str(
            request.args.get("auth_token")
            or request.form.get("auth_token")
            or ""
        ).strip()

    def _current_user():
        token = _request_auth_token()
        return auth_store.get_user_by_token(token)

    def _current_auth_token() -> str:
        return _request_auth_token()

    def _login_user(user) -> str:
        session.clear()
        return auth_store.create_session_token(user.id)

    def _logout_user() -> None:
        session.clear()

    def _login_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not _current_user():
                if request.path.startswith("/api/"):
                    return _json_error("请先登录", status=401)
                return redirect(url_for("login_page"))
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
        "appearance": "09 角色外观映射偏好",
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
        result = {}
        sources = [
            data.get("stage_prompts"),
            data.get("stagePrompts"),
            data.get("stagePreferences"),
            data.get("stage_preferences"),
            data.get("user_knowledge_stage_prompts"),
        ]
        prompt_preferences = data.get("prompt_preferences") if isinstance(data.get("prompt_preferences"), dict) else {}
        sources.append(prompt_preferences.get("stage_prompts"))
        for source in sources:
            if isinstance(source, dict):
                normalized = _stage_prompt_lookup_from_mapping(source)
                for stage_key, text in normalized.items():
                    if text and not result.get(stage_key):
                        result[stage_key] = text
        return result

    def _framework_asset_stage_prompts(framework_asset: dict | None) -> dict:
        if not isinstance(framework_asset, dict):
            return {}
        direct = _stage_prompt_lookup_from_mapping(framework_asset.get("stage_prompts"))
        if any(direct.values()):
            return direct
        return _stage_prompts_from_snapshot(framework_asset.get("preference_snapshot"))

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
        tags_by_id = {str(tag.get("id") or ""): tag for tag in user_knowledge_store.list_tags(enabled_only=True)}
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
        payload["selected_preference_tags"] = selected_tags
        payload["selected_preference_tag_ids"] = selected_ids
        payload["user_preference_prompt"] = _coerce_prompt_text(data.get("user_preference_prompt"))
        payload["user_knowledge_tag_prompt"] = _coerce_prompt_text(data.get("user_knowledge_tag_prompt"))
        prompt_preferences = data.get("prompt_preferences") if isinstance(data.get("prompt_preferences"), dict) else {}
        prompt_preferences = dict(prompt_preferences)
        prompt_preferences["stage_prompts"] = _coerce_stage_prompts(prompt_preferences.get("stage_prompts"))
        stage_prompt_source = data.get("user_knowledge_stage_prompts")
        if not isinstance(stage_prompt_source, dict):
            stage_prompt_source = prompt_preferences.get("stage_prompts")
        payload["user_knowledge_stage_prompts"] = _coerce_stage_prompts(stage_prompt_source)
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
        if _current_user():
            return redirect(url_for("workspace_page", auth_token=_current_auth_token()))
        return render_template("login.html")

    @app.post("/login")
    def login_submit():
        username = str(request.form.get("username") or "").strip()
        password = str(request.form.get("password") or "")
        user = auth_store.authenticate(username, password)
        if not user:
            return render_template("login.html", error="用户名或密码错误", username=username), 400
        auth_token = _login_user(user)
        return redirect(url_for("workspace_page", auth_token=auth_token))

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
        except FastGPTTransientError as exc:
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
            return _json_ok(tags=user_knowledge_store.list_tags(enabled_only=True))
        except Exception as exc:
            logger.exception("user knowledge tags list failed")
            return _json_error(str(exc), status=500, fallback="智慧库标签加载失败，请稍后重试。")

    @app.post("/api/user-knowledge/tags")
    @_login_required
    def create_user_knowledge_tag_api():
        data = request.get_json(silent=True) or {}
        try:
            tag = user_knowledge_store.create_tag(data if isinstance(data, dict) else {})
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
            tag = user_knowledge_store.update_tag(tag_id, data if isinstance(data, dict) else {})
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
            tag = user_knowledge_store.delete_tag(tag_id)
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

    @app.get("/api/framework-planner/diagnostics/fastgpt")
    @_login_required
    def framework_planner_fastgpt_diagnostics_api():
        stage = str(request.args.get("stage") or "05").zfill(2)
        try:
            payload = framework_planner_fastgpt_diagnostics(stage)
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
            payload = run_framework_planner_score(data)
            payload["history"] = save_framework_stage_history(
                project_id=project_id,
                stage="stage04_score",
                payload=data,
                output=payload.get("data") or {},
                status="success",
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
        if isinstance(data, dict):
            _attach_user_knowledge_payload(data, data, stage)
        project_id = data.get("project_id") if isinstance(data, dict) else None
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
            payload = run_framework_planner_stage(stage, data)
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
                    payload["autosaved_asset"] = _strip_raw_fastgpt_fields(autosaved_asset)
                    payload["project_id"] = autosaved_asset.get("project_id")
            except Exception as autosave_exc:
                logger.exception(
                    "framework planner stage autosave failed: stage=%s project_id=%s",
                    str(stage).zfill(2),
                    project_id,
                )
                payload["autosaved"] = False
                payload["autosave_error"] = str(autosave_exc)
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
        # print("[framework-planner-history] route hit", flush=True)
        project_id = request.args.get("project_id") or "unsaved"
        stage = request.args.get("stage") or ""
        return jsonify(list_framework_stage_history(project_id, stage or None))

    @app.get("/api/framework-planner/history/<project_id>/<filename>")
    @_login_required
    def load_framework_planner_history_api(project_id: str, filename: str):
        try:
            return jsonify(load_framework_stage_history(project_id, filename))
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
            result = write_framework_frontend_debug_event(
                project_id=project_id,
                event=event,
                payload=payload,
                detail=detail,
            )
            return jsonify(result)
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
            task_manager._public_snapshot(snapshot)
            for snapshot in task_manager._all_project_snapshots()
            if task_manager._snapshot_belongs_to_user(snapshot, user_id)
            and str(snapshot.get("asset_kind") or "").strip() == "framework_planner"
        ]
        assets = [
            _framework_asset_payload(project, include_detail=False)
            for project in projects
        ]
        assets.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        return _json_ok(assets=_strip_raw_fastgpt_fields(assets))

    @app.get("/api/framework-assets/<asset_id>")
    @_login_required
    def get_framework_asset_api(asset_id: str):
        asset = _load_framework_asset_for_user(asset_id, _require_user_id())
        if not asset:
            return _json_error("框架资产不存在，或尚未完成 07 最终策划包。", status=404)
        return _json_ok(asset=_strip_raw_fastgpt_fields(asset))

    @app.post("/api/framework-planner/assets")
    @_login_required
    def create_framework_planner_asset_api():
        data = request.get_json(silent=True) or {}
        try:
            asset = task_manager.create_framework_planner_asset(
                user_id=_require_user_id(),
                title=str(data.get("title") or data.get("project_title") or ""),
                season_count=int(data.get("season_count") or 1),
                episodes_per_season=int(data.get("episodes_per_season") or data.get("total_episodes") or 60),
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
        """单独运行 08 场景字典提炼。只跑 08，不继续 09/10。"""
        import json as _json

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _json_error("请求体必须是 JSON object。", status=400)
        try:
            user_id = _require_user_id()
            data, framework_asset = _inject_framework_asset(data, user_id)
        except ValueError as exc:
            return _json_error(str(exc), status=400)

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
                from .services.fastgpt_client import fastgpt_client
                from .services.fastgpt_contracts import STAGE_FRAMEWORK_SCENE_DICTIONARY

                raw_output = fastgpt_client.run_stage(
                    STAGE_FRAMEWORK_SCENE_DICTIONARY,
                    variables,
                )
            except Exception as exc:
                return _json_error(
                    str(exc),
                    status=500,
                    fallback="08 场景字典提炼调用失败，请检查 FASTGPT_FRAMEWORK_SCENE_DICTIONARY_API_KEY 和工作流变量。",
                )

            scene_dictionary, rules_digest = _extract_scene_payload(raw_output)
            if not scene_dictionary or not rules_digest:
                return _json_error(
                    "08 场景字典阶段输出缺少 sceneDictionary 或 scriptWorldRulesDigest。",
                    status=500,
                    fallback="请检查 08_场景字典提炼.json 是否把 sceneDictionary 和 scriptWorldRulesDigest 写入变量或 answerText JSON。",
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



    @app.post("/api/framework-to-script/stage/09")
    @_login_required
    def run_framework_to_script_stage09_api():
        """单独运行 09 人设服装 alias 映射。只跑 09，不继续 10。"""
        import json as _json

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _json_error("请求体必须是 JSON object。", status=400)
        try:
            user_id = _require_user_id()
            data, framework_asset = _inject_framework_asset(data, user_id)
        except ValueError as exc:
            return _json_error(str(exc), status=400)

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

        stage08 = _framework_script_stage_cache(framework_asset, "stage08")
        scene_dictionary = (
            data.get("sceneDictionary")
            or data.get("scene_dictionary")
            or stage08.get("sceneDictionary")
            or {}
        )
        if not isinstance(scene_dictionary, dict) or not scene_dictionary:
            return _json_error(
                "缺少 sceneDictionary，请先运行并确认 08 场景字典提炼。",
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

                    # 09 ???????? outfit_versions?
                    # ???????? outfit_variants?????????????????????
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



        asset_id = str((framework_asset or {}).get("asset_id") or data.get("framework_asset_id") or "").strip()
        if not _try_begin_framework_stage(user_id, asset_id, "09"):
            return _json_error("09 正在运行中，请稍后刷新页面，已完成输出会自动恢复。", status=409)
        try:
            try:
                from .services.fastgpt_client import fastgpt_client
                from .services.fastgpt_contracts import STAGE_FRAMEWORK_APPEARANCE_MAPPING

                raw_output = fastgpt_client.run_stage(
                    STAGE_FRAMEWORK_APPEARANCE_MAPPING,
                    variables,
                )
            except Exception as exc:
                return _json_error(
                    str(exc),
                    status=500,
                    fallback="09 人设服装 alias 映射调用失败，请检查 FASTGPT_FRAMEWORK_APPEARANCE_MAPPING_API_KEY 和工作流变量。",
                )

            appearanceMapping = _extract_appearance_payload(raw_output)
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
            if asset_id:
                _save_framework_to_script_stage(
                    user_id=user_id,
                    asset_id=asset_id,
                    stage_key="stage09",
                    output={"appearanceMapping": appearanceMapping},
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

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _json_error("请求体必须是 JSON object。", status=400)
        try:
            user_id = _require_user_id()
            data, framework_asset = _inject_framework_asset(data, user_id)
        except ValueError as exc:
            return _json_error(str(exc), status=400)

        framework_plan_package = (
            data.get("framework_plan_package")
            or data.get("frameworkPlanPackage")
            or {}
        )
        if not isinstance(framework_plan_package, dict) or not framework_plan_package:
            return _json_error("缺少 framework_plan_package，请先导入框架资产。", status=400)

        stage08 = _framework_script_stage_cache(framework_asset, "stage08")
        stage09 = _framework_script_stage_cache(framework_asset, "stage09")
        scene_dictionary = data.get("sceneDictionary") or data.get("scene_dictionary") or stage08.get("sceneDictionary") or {}
        if not isinstance(scene_dictionary, dict) or not scene_dictionary:
            return _json_error("缺少 sceneDictionary，请先完成 08 场景字典提炼。", status=400)

        rules_digest = (
            data.get("scriptWorldRulesDigest")
            or data.get("script_world_rules_digest")
            or stage08.get("scriptWorldRulesDigest")
            or {}
        )
        if not isinstance(rules_digest, dict) or not rules_digest:
            return _json_error("缺少 scriptWorldRulesDigest，请先完成 08 场景字典提炼。", status=400)

        appearance_mapping = (
            data.get("appearanceMapping")
            or data.get("appearance_mapping")
            or stage09.get("appearanceMapping")
            or {}
        )
        if not isinstance(appearance_mapping, dict) or not appearance_mapping:
            return _json_error("缺少 appearanceMapping，请先完成 09 角色外观映射。", status=400)

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
            "sourceFrameworkProjectId": data.get("source_framework_project_id") or data.get("sourceFrameworkProjectId") or "",
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

            def visit(obj):
                if isinstance(obj, dict):
                    candidates.append(obj)
                    for text_key in ("answerText", "text", "content"):
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
                    for key in ("data", "result", "output", "response", "responseData", "enrichedEpisodePlanResult", "enriched_episode_plan_result"):
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
                nested = item.get("enrichedEpisodePlanResult") or item.get("enriched_episode_plan_result")
                if isinstance(nested, str):
                    nested = _try_parse_json_text(nested) or {}
                if isinstance(nested, dict):
                    candidates.append(nested)

            for item in candidates:
                if not isinstance(item, dict):
                    continue
                plan = (
                    item.get("allEnrichedEpisodePlan")
                    or item.get("enrichedEpisodePlan")
                    or item.get("all_enriched_episode_plan")
                    or item.get("enriched_episode_plan")
                )
                text = (
                    item.get("allEnrichedEpisodePlanText")
                    or item.get("enrichedEpisodePlanText")
                    or item.get("all_enriched_episode_plan_text")
                    or item.get("enriched_episode_plan_text")
                    or ""
                )
                if isinstance(plan, str):
                    parsed_plan = _try_parse_json_text(plan)
                    if isinstance(parsed_plan, list):
                        plan = parsed_plan
                if isinstance(plan, list) and plan:
                    return plan, str(text or "")
            return None, ""

        asset_id = str((framework_asset or {}).get("asset_id") or data.get("framework_asset_id") or "").strip()
        if not _try_begin_framework_stage(user_id, asset_id, "10"):
            return _json_error("10 正在运行中，请稍后刷新页面，已完成输出会自动恢复。", status=409)
        try:
            try:
                from .services.fastgpt_client import fastgpt_client
                from .services.fastgpt_contracts import STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN

                raw_output = fastgpt_client.run_stage(
                    STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN,
                    variables,
                )
            except Exception as exc:
                return _json_error(
                    str(exc),
                    status=500,
                    fallback="10 分集细化方案调用失败，请检查 FASTGPT_FRAMEWORK_ENRICHED_EPISODE_PLAN_API_KEY 和工作流变量。",
                )

            plan, plan_text = _extract_enriched_payload(raw_output)
            if not plan:
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
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _json_error("请求体必须是 JSON object。", status=400)
        try:
            user_id = _require_user_id()
            data, framework_asset = _inject_framework_asset(data, user_id)
        except ValueError as exc:
            return _json_error(str(exc), status=400)

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
            return _json_error("缺少 sceneDictionary，请先完成 08 场景字典提炼。", status=400)
        if not isinstance(appearance_mapping, dict) or not appearance_mapping:
            return _json_error("缺少 appearanceMapping，请先完成 09 角色外观映射。", status=400)
        if not isinstance(rules_digest, dict) or not rules_digest:
            return _json_error("缺少 scriptWorldRulesDigest，请先完成 08 场景字典提炼。", status=400)

        existing_stage11 = _framework_script_stage_cache(framework_asset, "stage11")
        existing_batches = existing_stage11.get("batches") if isinstance(existing_stage11.get("batches"), dict) else {}
        reset_stage11 = bool(data.get("reset_stage11") or data.get("resetStage11"))
        if reset_stage11:
            existing_batches = {}
            existing_stage11 = {}
            reset_asset_id = str((framework_asset or {}).get("asset_id") or data.get("framework_asset_id") or "").strip()
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
        if not _try_begin_framework_stage(user_id, asset_id, "11"):
            return _json_error("11 正在运行中，请稍后刷新页面，已完成输出会自动恢复。", status=409)
        try:
            failed_sub_stage = "stage11_prepare"
            base_vars = {}
            total_episodes = 0
            try:
                from .services.fastgpt_client import FastGPTStageFormatError, fastgpt_client
                from .services.fastgpt_contracts import (
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
                    "totalEpisodes": total_episodes,
                    "conflictStartEpisode": start_episode,
                    "batchEnrichedEpisodePlan": batch_plan,
                    "sceneDictionary": scene_dictionary,
                    "appearanceMapping": appearance_mapping,
                    "scriptWorldRulesDigest": rules_digest,
                    "conflictMemory": conflict_memory,
                }
                _merge_aliases(base_vars, {"totalEpisodes": ("total_episodes",), "conflictMemory": ("conflict_memory",)})
                base_vars = _inject_snapshot_stage_preference(
                    base_vars,
                    data,
                    "11",
                    framework_asset=framework_asset,
                    workflow_stage="11_write",
                )
                first_batch_item = batch_plan[0] if batch_plan and isinstance(batch_plan[0], dict) else {}
                appearance_characters = appearance_mapping.get("characters") if isinstance(appearance_mapping, dict) else []
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
                max_write_retries = 3
                for retry_count in range(max_write_retries + 1):
                    write_retry_count = retry_count
                    if retry_count:
                        logger.warning(
                            "framework-to-script stage11 causal_conflict_write retry: asset_id=%s retry_count=%s "
                            "start_episode=%s end_episode=%s reason=%s",
                            asset_id,
                            retry_count,
                            start_episode,
                            end_episode,
                            write_failure_reason,
                        )
                    try:
                        write_output = fastgpt_client.run_stage(STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE, base_vars)
                        write_output_data = write_output if isinstance(write_output, dict) else {}
                        write_output_keys = sorted(write_output_data.keys())
                        conflict_plan, conflict_plan_unwrapped, write_failure_reason = _normalize_dict_output_alias(
                            write_output_data,
                            "batchCausalConflictPlan",
                            "batch_causal_conflict_plan",
                        )
                    except FastGPTStageFormatError as exc:
                        write_output_data = {}
                        write_output_keys = []
                        write_failure_reason = (
                            f"{exc.failure_reason}; missing_fields={list(exc.missing_fields)}; "
                            f"probable_truncated_json={exc.probable_truncated_json}; "
                            f"raw_output_source={exc.raw_output_source}"
                        )
                        if retry_count >= max_write_retries:
                            break
                        continue
                    except Exception as exc:
                        write_failure_reason = f"{type(exc).__name__}: {exc}"
                        if retry_count >= max_write_retries:
                            break
                        continue
                    if isinstance(conflict_plan, dict) and conflict_plan:
                        contract_issues = _validate_stage11_causal_conflict_plan(
                            conflict_plan,
                            start_episode=start_episode,
                            end_episode=end_episode,
                        )
                        if not contract_issues:
                            break
                        write_failure_reason = "contract validation failed: " + "; ".join(contract_issues[:8])
                        conflict_plan = {}
                        if retry_count >= max_write_retries:
                            break
                        continue
                    if not write_failure_reason:
                        write_failure_reason = "normalized batchCausalConflictPlan is empty"
                    if retry_count >= max_write_retries:
                        break
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
                            "message": "11 write 阶段未返回可用的 batchCausalConflictPlan，已自动重试 3 次；请查看后端调试终端日志。",
                            "detail": {
                                "failed_sub_stage": "causal_conflict_write",
                                "retry_count": write_retry_count,
                                "max_write_retries": max_write_retries,
                                "start_episode": start_episode,
                                "end_episode": end_episode,
                                "write_failure_reason": write_failure_reason,
                                "write_output_keys": write_output_keys,
                            },
                        }
                    ), 500
                max_review_rounds = 5
                conflict_review = {}
                rewrite_round = 0
                for review_round in range(1, max_review_rounds + 1):
                    failed_sub_stage = "causal_conflict_review"
                    try:
                        review_output = fastgpt_client.run_stage(
                            STAGE_FRAMEWORK_CAUSAL_CONFLICT_REVIEW,
                            {
                                **base_vars,
                                "batchCausalConflictPlan": conflict_plan,
                            },
                        )
                    except FastGPTStageFormatError as exc:
                        logger.warning(
                            "framework-to-script stage11 review missing fields, using defaults: "
                            "asset_id=%s missing_fields=%s error=%s",
                            asset_id,
                            list(exc.missing_fields),
                            str(exc),
                        )
                        review_output = {}
                    review_output_data = review_output if isinstance(review_output, dict) else {}
                    review_passed = _get_bool_alias(review_output_data, "reviewPassed", "passed", default=None)
                    rewrite_required = _get_bool_alias(review_output_data, "rewriteRequired", "rewrite_required", default=None)
                    blocking_issues = _get_list_alias(review_output_data, "blockingIssues", "blocking_issues")
                    non_blocking_issues = _get_list_alias(review_output_data, "nonBlockingIssues", "non_blocking_issues")
                    rewrite_brief = _first_present(review_output_data, "rewriteBrief", "rewrite_brief", default="")
                    if review_passed is None and rewrite_required is None:
                        logger.warning(
                            "framework-to-script stage11 review output missing reviewPassed/passed and rewriteRequired/rewrite_required; "
                            "treating as rewrite needed: "
                            "asset_id=%s review_output_keys=%s",
                            asset_id,
                            sorted(review_output_data.keys()),
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
                            **base_vars,
                            "batchCausalConflictPlan": conflict_plan,
                            "batchCausalConflictReview": conflict_review,
                        },
                        data,
                        "11",
                        framework_asset=framework_asset,
                        workflow_stage="11_rewrite",
                    )
                    rewrite_output = fastgpt_client.run_stage(
                        STAGE_FRAMEWORK_CAUSAL_CONFLICT_REWRITE,
                        rewrite_vars,
                    )
                    logger.info(
                        "framework-to-script stage11 rewrite done: asset_id=%s rewrite_output_keys=%s",
                        asset_id,
                        sorted(rewrite_output.keys()) if isinstance(rewrite_output, dict) else [],
                    )
                    rewrite_output_data = rewrite_output if isinstance(rewrite_output, dict) else {}
                    rewrite_conflict_plan, rewrite_unwrapped = _unwrap_dict_alias(
                        rewrite_output_data,
                        "batchCausalConflictPlan",
                        "batch_causal_conflict_plan",
                    )
                    conflict_plan = rewrite_conflict_plan or conflict_plan
                    rewrite_episodes = conflict_plan.get("episodes") if isinstance(conflict_plan, dict) else []
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
                    memory_output = fastgpt_client.run_stage(
                        STAGE_FRAMEWORK_CAUSAL_CONFLICT_MEMORY,
                        {
                            "batchCausalConflictPlan": conflict_plan,
                            "conflictMemory": conflict_memory,
                            "conflictStartEpisode": start_episode,
                        },
                    )
                except FastGPTStageFormatError as exc:
                    logger.warning(
                        "framework-to-script stage11 memory missing conflictMemory, keeping previous memory: "
                        "asset_id=%s missing_fields=%s error=%s",
                        asset_id,
                        list(exc.missing_fields),
                        str(exc),
                    )
                    memory_output = {}
                memory_output_data = memory_output if isinstance(memory_output, dict) else {}
                memory_value = _first_present(memory_output_data, "conflictMemory", "conflict_memory", default=None)
                if memory_value is None:
                    logger.warning(
                        "framework-to-script stage11 memory output missing conflictMemory/conflict_memory, keeping previous memory: "
                        "asset_id=%s memory_output_keys=%s",
                        asset_id,
                        sorted(memory_output_data.keys()),
                    )
                else:
                    conflict_memory = str(memory_value)
                logger.info(
                    "framework-to-script stage11 memory done: asset_id=%s memory_output_keys=%s normalized_keys=%s conflictMemory_length=%s",
                    asset_id,
                    sorted(memory_output_data.keys()),
                    ["conflictMemory", "conflict_memory"],
                    len(conflict_memory),
                )
            except Exception as exc:
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
                        },
                    }
                ), 500

            batch_key = str(start_episode)
            batches = dict(existing_batches)
            batch_output = {
                "batchStartEpisode": start_episode,
                "batchEndEpisode": end_episode,
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
        finally:
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
        if not _try_begin_framework_stage(user_id, asset_id, "12"):
            return _json_error("12 正在运行中，请稍后刷新页面，已完成输出会自动恢复。", status=409)
        try:
            failed_sub_stage = "stage12_prepare"
            start_episode = None
            end_episode = None
            base_vars = {}
            try:
                from .services.fastgpt_client import fastgpt_client
                from .services.fastgpt_contracts import (
                    STAGE_CONTRACTS,
                    STAGE_FRAMEWORK_SCRIPT_MEMORY,
                    STAGE_FRAMEWORK_SCRIPT_REVIEW,
                    STAGE_FRAMEWORK_SCRIPT_REWRITE,
                    STAGE_FRAMEWORK_SCRIPT_WRITE,
                )

                start_episode = _positive_int(stage11_batch.get("batchStartEpisode"), _positive_int(batch_key, 1))
                end_episode = _positive_int(stage11_batch.get("batchEndEpisode"), start_episode + 4)
                minutes = _positive_int((framework_asset or {}).get("minutes_per_episode"), 2)
                episode_word_count = _positive_int(data.get("episode_word_count"), max(600, minutes * 450))
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
                        "episodeWordCount": ("episode_word_count",),
                        "scriptMemory": ("script_memory",),
                    },
                )
                base_vars = _inject_snapshot_stage_preference(
                    base_vars,
                    data,
                    "12",
                    framework_asset=framework_asset,
                    workflow_stage="12_write",
                )
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
                    "framework-to-script stage12 entering FastGPT asset_id=%s start_episode=%s end_episode=%s "
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
                write_output = fastgpt_client.run_stage(STAGE_FRAMEWORK_SCRIPT_WRITE, base_vars)
                write_keys = sorted(write_output.keys()) if isinstance(write_output, dict) else []
                batch_script_value = _first_present(write_output, "batchScriptText", "batch_script_text", default=None)
                batch_script = str(batch_script_value or "")
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
                    return jsonify(
                        {
                            "success": False,
                            "message": "12 正文对白批次调用失败",
                            "detail": {
                                "failed_sub_stage": "script_write",
                                "error_message": "12 write/rewrite 阶段未返回 batchScriptText",
                                "write_output_keys": write_keys,
                            },
                        }
                    ), 500
                max_review_rounds = 5
                script_review = {}
                rewrite_round = 0
                for review_round in range(1, max_review_rounds + 1):
                    failed_sub_stage = "script_review"
                    review_output = fastgpt_client.run_stage(
                        STAGE_FRAMEWORK_SCRIPT_REVIEW,
                        {
                            **base_vars,
                            "batchScriptText": batch_script,
                        },
                    )
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
                        return jsonify(
                            {
                                "success": False,
                                "message": "12 正文对白审核修订 5 轮后仍未通过，已停止保存当前批次。",
                                "detail": {
                                    "failed_sub_stage": "script_review",
                                    "max_review_rounds": max_review_rounds,
                                    "review_round": review_round,
                                    "rewrite_round": rewrite_round,
                                    "start_episode": start_episode,
                                    "end_episode": end_episode,
                                    "last_review": script_review,
                                    "blockingIssues": blocking_issues,
                                    "blocking_issues": blocking_issues,
                                },
                            }
                        ), 422
                    failed_sub_stage = "script_rewrite"
                    rewrite_round += 1
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
                    rewrite_output = fastgpt_client.run_stage(
                        STAGE_FRAMEWORK_SCRIPT_REWRITE,
                        rewrite_vars,
                    )
                    rewrite_keys = sorted(rewrite_output.keys()) if isinstance(rewrite_output, dict) else []
                    rewrite_script_value = _first_present(rewrite_output, "batchScriptText", "batch_script_text", default=None)
                    batch_script = str(rewrite_script_value or "")
                    logger.info(
                        "framework-to-script stage12 script_rewrite output rewrite_output_keys=%s batchScriptText_length=%s "
                        "normalized_keys=%s",
                        rewrite_keys,
                        len(batch_script),
                        ["batchScriptText", "batch_script_text"],
                    )
                    if not batch_script.strip():
                        return jsonify(
                            {
                                "success": False,
                                "message": "12 正文对白批次调用失败",
                                "detail": {
                                    "failed_sub_stage": "script_rewrite",
                                    "error_message": "12 write/rewrite 阶段未返回 batchScriptText",
                                    "rewrite_output_keys": rewrite_keys,
                                },
                            }
                        ), 500
                failed_sub_stage = "script_memory"
                memory_output = fastgpt_client.run_stage(
                    STAGE_FRAMEWORK_SCRIPT_MEMORY,
                    {
                        "batchScriptText": batch_script,
                        "scriptMemory": script_memory,
                        "scriptStartEpisode": start_episode,
                    },
                )
                memory_keys = sorted(memory_output.keys()) if isinstance(memory_output, dict) else []
                memory_value = _first_present(memory_output, "scriptMemory", "script_memory", default=None)
                if memory_value is None:
                    logger.warning(
                        "framework-to-script stage12 script_memory missing scriptMemory/script_memory, keeping previous memory memory_output_keys=%s",
                        memory_keys,
                    )
                else:
                    script_memory = str(memory_value)
                logger.info(
                    "framework-to-script stage12 script_memory output memory_output_keys=%s normalized_keys=%s scriptMemory_length=%s",
                    memory_keys,
                    ["scriptMemory", "script_memory"],
                    len(script_memory),
                )
            except Exception as exc:
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
                        "message": "12 正文对白批次调用失败",
                        "detail": {
                            "failed_sub_stage": failed_sub_stage,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "asset_id": asset_id,
                            "start_episode": start_episode,
                            "end_episode": end_episode,
                            "batch_plan_count": len(batch_plan),
                            "base_var_keys": sorted(base_vars.keys()),
                        },
                    }
                ), 500

            batches = dict(existing_batches)
            batch_output = {
                "batchStartEpisode": start_episode,
                "batchEndEpisode": end_episode,
                "batchEnrichedEpisodePlan": batch_plan,
                "batchCausalConflictPlan": conflict_plan,
                "batch_causal_conflict_plan": conflict_plan,
                "batchScriptText": batch_script,
                "batch_script_text": batch_script,
                "batchScriptReview": script_review,
                "batch_script_review": script_review,
                "scriptMemory": script_memory,
                "script_memory": script_memory,
            }
            batches[str(start_episode)] = batch_output
            output = {**batch_output, "batches": batches}
            if asset_id:
                _save_framework_to_script_stage(
                    user_id=user_id,
                    asset_id=asset_id,
                    stage_key="stage12",
                    output=output,
                )
        finally:
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
            asset = task_manager.save_framework_planner_asset(
                user_id=_require_user_id(),
                payload=data,
            )
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        except Exception as exc:
            logger.exception("framework planner asset save failed")
            return _json_error(str(exc), status=500, fallback="当前框架保存失败，请稍后重试。")
        return _json_ok(asset=asset, project=asset, project_id=asset.get("project_id"))

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
            str(data.get("title") or "")
            or str(data.get("project_title") or "")
            or str(basic_config.get("project_title") or "")
            or str(basic_config.get("source_title") or "")
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
        minutes_per_episode = _safe_int(
            data.get("minutes_per_episode") or basic_config.get("minutes_per_episode"),
            2,
        )
        episode_word_count = _safe_int(
            data.get("episode_word_count"),
            max(600, minutes_per_episode * 450),
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
            "minutes_per_episode": minutes_per_episode,
            "episode_word_count": episode_word_count,
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
                fallback="框架转剧本任务创建失败，请检查新链路 FastGPT API Key 和工作流配置。",
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
            "episode_word_count": data.get("episode_word_count", 600) or 600,
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
            "episode_word_count": data.get("episode_word_count", 600) or 600,
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
