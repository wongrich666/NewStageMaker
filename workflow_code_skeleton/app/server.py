from __future__ import annotations

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
from .services.simple_fastgpt_tools import list_simple_tools, run_simple_tool
from .services.task_manager import task_manager


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

    @app.get("/")
    def index():
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
            return redirect(url_for("index", auth_token=_current_auth_token()))
        return render_template("login.html")

    @app.post("/login")
    def login_submit():
        username = str(request.form.get("username") or "").strip()
        password = str(request.form.get("password") or "")
        user = auth_store.authenticate(username, password)
        if not user:
            return render_template("login.html", error="用户名或密码错误", username=username), 400
        auth_token = _login_user(user)
        return redirect(url_for("index", auth_token=auth_token))

    @app.get("/register")
    def register_page():
        if _current_user():
            return redirect(url_for("index", auth_token=_current_auth_token()))
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
        return redirect(url_for("index", auth_token=auth_token))

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
        return _json_ok(tools=list_simple_tools())

    @app.post("/api/tools/<tool_key>/run")
    @_login_required
    def run_tool(tool_key: str):
        data = request.get_json(silent=True) or {}
        try:
            result = run_simple_tool(tool_key, data)
        except Exception as exc:
            return _json_error(str(exc), status=400, fallback="工具执行失败，请稍后重试。")
        return _json_ok(result=result)

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
            "character_appearance_requirements": "",
            "character_alias_naming_rules": "",
            "outfit_switch_rules": "",
            "story_outline": data.get("story_outline", ""),
            "core_scene_input": data.get("core_scene_input", ""),
            "character_bios": data.get("character_bios", ""),
            "episode_plan": data.get("episode_plan", ""),
        }
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
            "character_appearance_requirements": "",
            "character_alias_naming_rules": "",
            "outfit_switch_rules": "",
            "story_outline": data.get("story_outline", ""),
            "core_scene_input": data.get("core_scene_input", ""),
            "character_bios": data.get("character_bios", ""),
            "episode_plan": data.get("episode_plan", ""),
        }
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

    return app
