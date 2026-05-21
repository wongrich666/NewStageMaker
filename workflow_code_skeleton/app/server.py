from __future__ import annotations

import json
from functools import wraps
import os
from pathlib import Path

from flask import (
    Flask,
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
from .utils.logger import get_logger


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

    def _coerce_stage_prompts(value) -> dict:
        source = value if isinstance(value, dict) else {}
        return {
            key: _coerce_prompt_text(source.get(key))
            for key in ("basic", "worldview", "character", "beat", "storylines", "guide", "package")
        }

    def _coerce_prompt_text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value).strip()

    def _attach_user_knowledge_payload(payload: dict, data: dict) -> None:
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
        if any(key in data for key in ("selected_preference_tags", "selected_preference_tag_ids", "user_preference_prompt", "user_knowledge_tag_prompt", "user_knowledge_stage_prompts", "prompt_preferences")):
            stage_prompt_length = sum(len(value or "") for value in payload["user_knowledge_stage_prompts"].values())
            logger.info(
                "workflow user knowledge fields: selected_preference_tags_count=%s selected_preference_tag_ids_count=%s user_preference_prompt_length=%s stage_prompt_length=%s",
                len(selected_tags),
                len(selected_ids),
                len(payload["user_preference_prompt"]),
                stage_prompt_length,
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
            _attach_user_knowledge_payload(data, data)
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
            payload = run_framework_planner_stage(stage, data)
            payload["history"] = save_framework_stage_history(
                project_id=project_id,
                stage=str(stage).zfill(2),
                payload=data,
                output=payload.get("data") or {},
                status="success",
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
