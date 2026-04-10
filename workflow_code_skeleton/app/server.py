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

from .services.auth_store import auth_store
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

    def _json_ok(**payload):
        return jsonify({"success": True, **payload})

    def _json_error(message: str, status: int = 400):
        return jsonify({"success": False, "message": message}), status

    def _current_user():
        return auth_store.get_user(session.get("user_id"))

    def _login_user(user) -> None:
        session.clear()
        session["user_id"] = user.id
        session["username"] = user.username
        session.permanent = True

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
    @_login_required
    def index():
        return render_template("index.html", current_user=_current_user())

    @app.get("/login")
    def login_page():
        if _current_user():
            return redirect(url_for("index"))
        return render_template("login.html")

    @app.post("/login")
    def login_submit():
        username = str(request.form.get("username") or "").strip()
        password = str(request.form.get("password") or "")
        user = auth_store.authenticate(username, password)
        if not user:
            return render_template("login.html", error="用户名或密码错误", username=username), 400
        _login_user(user)
        return redirect(url_for("index"))

    @app.get("/register")
    def register_page():
        if _current_user():
            return redirect(url_for("index"))
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
        _login_user(user)
        return redirect(url_for("index"))

    @app.get("/logout")
    def logout():
        _logout_user()
        return redirect(url_for("login_page"))

    @app.get("/api/me")
    @_login_required
    def current_user_api():
        user = _current_user()
        return _json_ok(user={"id": user.id, "username": user.username})

    @app.get("/api/models")
    @_login_required
    def list_models():
        spec_path = str(request.args.get("workflow_spec_path") or app.config["WORKFLOW_SPEC_PATH"])
        try:
            models = task_manager.list_model_options(spec_path)
        except Exception as exc:
            return _json_error(str(exc), status=500)
        return _json_ok(models=models, workflow_spec_path=spec_path)

    @app.get("/api/projects/latest")
    @_login_required
    def latest_project():
        snapshot = task_manager.latest_project_snapshot(user_id=_require_user_id())
        return _json_ok(project=snapshot)

    @app.get("/api/projects/<int:project_id>")
    @_login_required
    def get_project(project_id: int):
        snapshot = task_manager.get_project_snapshot(project_id, user_id=_require_user_id())
        if not snapshot:
            return _json_error("项目不存在", status=404)
        return _json_ok(project=snapshot)

    @app.post("/api/workflows/start")
    @_login_required
    def start_workflow():
        data = request.get_json(silent=True) or {}
        spec_path = _resolve_spec_path(data)
        payload = {
            "title": data.get("title", ""),
            "episode_word_count": data.get("episode_word_count", 0),
            "total_episodes": data.get("total_episodes", 0),
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
            return _json_error(str(exc), status=400)
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
            return _json_error(str(exc), status=400)
        return _json_ok(project_id=project_id, saved_file=str(path))

    @app.get("/api/projects/<int:project_id>/download")
    @_login_required
    def download_project(project_id: int):
        try:
            path = task_manager.save_final_script(project_id, user_id=_require_user_id())
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return send_file(
            path,
            as_attachment=True,
            download_name=path.name,
            mimetype="text/plain; charset=utf-8",
        )

    return app
