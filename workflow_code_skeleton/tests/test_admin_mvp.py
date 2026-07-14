from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from workflow_code_skeleton.app.services.admin_store import AdminStore


def make_store(tmp_path):
    db_path = tmp_path / "users.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE auth_sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO users (id, username, password_hash, created_at)
            VALUES (1, 'admin', 'unused', '2026-07-13T09:00:00+08:00');
            INSERT INTO users (id, username, password_hash, created_at)
            VALUES (2, 'writer', 'unused', '2026-07-13T10:00:00+08:00');
            INSERT INTO auth_sessions (token, user_id, created_at)
            VALUES ('session-1', 1, '2026-07-13T09:10:00+08:00');
            """
        )
    return AdminStore(db_path)


def test_admin_store_tracks_events_and_runs_without_sensitive_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRIPTMAKER_ADMIN_USERNAMES", "admin")
    store = make_store(tmp_path)

    assert store.is_admin(1, "admin") is True
    assert store.is_admin(2, "writer") is False

    store.record_event(
        user_id=2,
        username="writer",
        category="request",
        action="POST /api/tools/hot_review/run",
        status="success",
        path="/api/tools/hot_review/run",
        metadata={"http_status": 200, "api_key": "must-not-be-stored", "script_content": "private"},
    )
    run_id = store.start_workflow_run(
        user_id=2,
        username="writer",
        workflow_key="tool:hot_review",
        workflow_label="爆款文审核",
        request_bytes=128,
    )
    store.finish_workflow_run(run_id, status="success", duration_ms=420, http_status=200, response_bytes=256)

    overview = store.overview()
    assert overview["total_users"] == 2
    assert overview["runs_today"] >= 1

    users = store.list_users(search="writer")
    assert users["total"] == 1
    assert users["items"][0]["workflow_run_count"] == 1

    events = store.list_events(search="writer")
    assert events["total"] == 1
    assert events["items"][0]["action"] == "POST /api/tools/hot_review/run"

    runs = store.list_workflow_runs(search=run_id)
    assert runs["total"] == 1
    assert runs["items"][0]["status"] == "success"

    with sqlite3.connect(store.db_path) as conn:
        metadata = conn.execute("SELECT metadata_json FROM audit_events").fetchone()[0]
    assert "must-not-be-stored" not in metadata
    assert "private" not in metadata
    assert "http_status" in metadata


def test_admin_dashboard_routes_require_admin(tmp_path, monkeypatch):
    from workflow_code_skeleton.app import server

    store = make_store(tmp_path)
    monkeypatch.setenv("SCRIPTMAKER_ADMIN_USERNAMES", "admin")
    monkeypatch.setattr(server, "admin_store", store)

    class FakeAuth:
        def get_user(self, user_id):
            if int(user_id) == 1:
                return SimpleNamespace(id=1, username="admin", created_at="2026-07-13T09:00:00+08:00")
            if int(user_id) == 2:
                return SimpleNamespace(id=2, username="writer", created_at="2026-07-13T10:00:00+08:00")
            return None

        def get_user_by_token(self, token):
            if token == "admin-token":
                return self.get_user(1)
            if token == "writer-token":
                return self.get_user(2)
            return None

    monkeypatch.setattr(server, "auth_store", FakeAuth())
    app = server.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    login_redirect = client.get("/admin")
    assert login_redirect.status_code == 302
    assert login_redirect.headers["Location"].endswith("/login?next=admin")

    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 1
    session_page = client.get("/admin")
    assert session_page.status_code == 200
    with client.session_transaction() as browser_session:
        browser_session.clear()

    denied = client.get("/api/admin/overview", headers={"Authorization": "Bearer writer-token"})
    assert denied.status_code == 403

    overview = client.get("/api/admin/overview", headers={"Authorization": "Bearer admin-token"})
    assert overview.status_code == 200
    assert overview.get_json()["overview"]["total_users"] == 2

    page = client.get("/admin?auth_token=admin-token")
    assert page.status_code == 200
    assert "运营管理台" in page.get_data(as_text=True)
