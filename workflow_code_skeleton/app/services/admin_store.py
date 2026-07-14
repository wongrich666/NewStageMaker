from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .runtime_paths import get_runtime_data_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _today_start_iso() -> str:
    now = datetime.now(timezone.utc).astimezone()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _safe_text(value: Any, limit: int = 240) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _safe_metadata(value: dict[str, Any] | None) -> str:
    source = value if isinstance(value, dict) else {}
    safe: dict[str, Any] = {}
    blocked_fragments = ("password", "secret", "token", "api_key", "authorization", "cookie", "script", "content", "prompt")
    for key, item in source.items():
        normalized = str(key or "").lower()
        if any(fragment in normalized for fragment in blocked_fragments):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[str(key)[:80]] = _safe_text(item, 300) if isinstance(item, str) else item
    return json.dumps(safe, ensure_ascii=False, separators=(",", ":"))


class AdminStore:
    """Small, append-only operations store for the admin MVP.

    It deliberately stores request metadata only. Request bodies, credentials, API keys,
    cookies and script content are never persisted here.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else get_runtime_data_dir() / "users.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS admin_roles (
                    user_id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL DEFAULT 'admin',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    granted_at TEXT NOT NULL,
                    granted_by INTEGER
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    status TEXT NOT NULL,
                    http_method TEXT,
                    path TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    duration_ms INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workflow_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    user_id INTEGER,
                    username TEXT,
                    workflow_key TEXT NOT NULL,
                    workflow_label TEXT,
                    status TEXT NOT NULL,
                    http_method TEXT,
                    path TEXT,
                    ip_address TEXT,
                    request_bytes INTEGER NOT NULL DEFAULT 0,
                    response_bytes INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER,
                    http_status INTEGER,
                    error_code TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_events_user ON audit_events(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events(action, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_workflow_runs_started ON workflow_runs(started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_workflow_runs_user ON workflow_runs(user_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_workflow_runs_key ON workflow_runs(workflow_key, started_at DESC);
                """
            )
            conn.commit()

    @staticmethod
    def configured_admin_usernames() -> set[str]:
        raw = os.getenv("SCRIPTMAKER_ADMIN_USERNAMES", "admin")
        return {item.strip().lower() for item in raw.split(",") if item.strip()}

    def is_admin(self, user_id: int | None, username: str | None = None) -> bool:
        if not user_id:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT role, is_active FROM admin_roles WHERE user_id = ?",
                (int(user_id),),
            ).fetchone()
        if row is not None:
            return bool(row["is_active"])
        if str(username or "").strip().lower() in self.configured_admin_usernames():
            self.grant_admin(int(user_id), role="owner")
            return True
        return False

    def grant_admin(self, user_id: int, *, role: str = "admin", granted_by: int | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO admin_roles (user_id, role, is_active, granted_at, granted_by)
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    role = excluded.role,
                    is_active = 1,
                    granted_at = excluded.granted_at,
                    granted_by = excluded.granted_by
                """,
                (int(user_id), _safe_text(role, 32) or "admin", _now_iso(), granted_by),
            )
            conn.commit()

    def record_event(
        self,
        *,
        user_id: int | None,
        username: str | None,
        category: str,
        action: str,
        status: str,
        target_type: str = "",
        target_id: str = "",
        http_method: str = "",
        path: str = "",
        ip_address: str = "",
        user_agent: str = "",
        duration_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_events (
                    user_id, username, category, action, target_type, target_id,
                    status, http_method, path, ip_address, user_agent, duration_ms,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(user_id) if user_id else None,
                    _safe_text(username, 80),
                    _safe_text(category, 48) or "system",
                    _safe_text(action, 120) or "unknown",
                    _safe_text(target_type, 48),
                    _safe_text(target_id, 120),
                    _safe_text(status, 32) or "unknown",
                    _safe_text(http_method, 12),
                    _safe_text(path, 240),
                    _safe_text(ip_address, 80),
                    _safe_text(user_agent, 240),
                    max(0, int(duration_ms)) if duration_ms is not None else None,
                    _safe_metadata(metadata),
                    _now_iso(),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def start_workflow_run(
        self,
        *,
        user_id: int | None,
        username: str | None,
        workflow_key: str,
        workflow_label: str = "",
        http_method: str = "",
        path: str = "",
        ip_address: str = "",
        request_bytes: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        run_id = f"run_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, user_id, username, workflow_key, workflow_label, status,
                    http_method, path, ip_address, request_bytes, metadata_json, started_at
                ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    int(user_id) if user_id else None,
                    _safe_text(username, 80),
                    _safe_text(workflow_key, 120) or "unknown",
                    _safe_text(workflow_label, 120),
                    _safe_text(http_method, 12),
                    _safe_text(path, 240),
                    _safe_text(ip_address, 80),
                    max(0, int(request_bytes or 0)),
                    _safe_metadata(metadata),
                    _now_iso(),
                ),
            )
            conn.commit()
        return run_id

    def finish_workflow_run(
        self,
        run_id: str,
        *,
        status: str,
        duration_ms: int,
        http_status: int,
        response_bytes: int = 0,
        error_code: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE workflow_runs
                SET status = ?, duration_ms = ?, http_status = ?, response_bytes = ?,
                    error_code = ?, finished_at = ?
                WHERE run_id = ?
                """,
                (
                    _safe_text(status, 32) or "unknown",
                    max(0, int(duration_ms or 0)),
                    int(http_status or 0),
                    max(0, int(response_bytes or 0)),
                    _safe_text(error_code, 80),
                    _now_iso(),
                    _safe_text(run_id, 80),
                ),
            )
            conn.commit()

    @staticmethod
    def _pagination(page: int, page_size: int) -> tuple[int, int, int]:
        safe_page = max(1, int(page or 1))
        safe_size = min(100, max(10, int(page_size or 25)))
        return safe_page, safe_size, (safe_page - 1) * safe_size

    def overview(self) -> dict[str, Any]:
        today = _today_start_iso()
        with self._connect() as conn:
            total_users = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            new_users_today = int(conn.execute("SELECT COUNT(*) FROM users WHERE created_at >= ?", (today,)).fetchone()[0])
            active_today = int(conn.execute("SELECT COUNT(DISTINCT user_id) FROM audit_events WHERE created_at >= ? AND user_id IS NOT NULL", (today,)).fetchone()[0])
            runs_today = int(conn.execute("SELECT COUNT(*) FROM workflow_runs WHERE started_at >= ?", (today,)).fetchone()[0])
            successful_today = int(conn.execute("SELECT COUNT(*) FROM workflow_runs WHERE started_at >= ? AND status IN ('success','accepted')", (today,)).fetchone()[0])
            failed_today = int(conn.execute("SELECT COUNT(*) FROM workflow_runs WHERE started_at >= ? AND status = 'failed'", (today,)).fetchone()[0])
            running_now = int(conn.execute("SELECT COUNT(*) FROM workflow_runs WHERE status = 'running'").fetchone()[0])
            events_today = int(conn.execute("SELECT COUNT(*) FROM audit_events WHERE created_at >= ?", (today,)).fetchone()[0])
            top_workflows = [dict(row) for row in conn.execute(
                """
                SELECT workflow_key, COALESCE(NULLIF(workflow_label, ''), workflow_key) AS workflow_label,
                       COUNT(*) AS run_count,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count
                FROM workflow_runs
                WHERE started_at >= ?
                GROUP BY workflow_key, workflow_label
                ORDER BY run_count DESC, workflow_key ASC
                LIMIT 6
                """,
                (today,),
            ).fetchall()]
        return {
            "total_users": total_users,
            "new_users_today": new_users_today,
            "active_users_today": active_today,
            "runs_today": runs_today,
            "successful_runs_today": successful_today,
            "failed_runs_today": failed_today,
            "running_now": running_now,
            "events_today": events_today,
            "top_workflows": top_workflows,
            "generated_at": _now_iso(),
        }

    def list_users(self, *, search: str = "", page: int = 1, page_size: int = 25) -> dict[str, Any]:
        page, page_size, offset = self._pagination(page, page_size)
        term = f"%{_safe_text(search, 80)}%"
        where = "WHERE (u.username LIKE ? OR CAST(u.id AS TEXT) LIKE ?)" if search else ""
        params: list[Any] = [term, term] if search else []
        with self._connect() as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM users u {where}", params).fetchone()[0])
            rows = conn.execute(
                f"""
                SELECT u.id, u.username, u.created_at,
                       (SELECT MAX(s.created_at) FROM auth_sessions s WHERE s.user_id = u.id) AS last_session_at,
                       (SELECT COUNT(*) FROM auth_sessions s WHERE s.user_id = u.id) AS session_count,
                       (SELECT COUNT(*) FROM audit_events e WHERE e.user_id = u.id) AS event_count,
                       (SELECT COUNT(*) FROM workflow_runs r WHERE r.user_id = u.id) AS workflow_run_count,
                       (SELECT MAX(e.created_at) FROM audit_events e WHERE e.user_id = u.id) AS last_active_at,
                       COALESCE(ar.role, '') AS admin_role,
                       COALESCE(ar.is_active, 0) AS admin_active
                FROM users u
                LEFT JOIN admin_roles ar ON ar.user_id = u.id
                {where}
                ORDER BY COALESCE(
                    (SELECT MAX(e.created_at) FROM audit_events e WHERE e.user_id = u.id),
                    (SELECT MAX(s.created_at) FROM auth_sessions s WHERE s.user_id = u.id),
                    u.created_at
                ) DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    def list_events(
        self,
        *,
        search: str = "",
        category: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 30,
    ) -> dict[str, Any]:
        page, page_size, offset = self._pagination(page, page_size)
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            clauses.append("(username LIKE ? OR action LIKE ? OR path LIKE ? OR ip_address LIKE ?)")
            term = f"%{_safe_text(search, 80)}%"
            params.extend([term, term, term, term])
        if category:
            clauses.append("category = ?")
            params.append(_safe_text(category, 48))
        if status:
            clauses.append("status = ?")
            params.append(_safe_text(status, 32))
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM audit_events {where}", params).fetchone()[0])
            rows = conn.execute(
                f"""
                SELECT id, user_id, username, category, action, target_type, target_id,
                       status, http_method, path, ip_address, duration_ms, created_at
                FROM audit_events
                {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    def list_workflow_runs(
        self,
        *,
        search: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 30,
    ) -> dict[str, Any]:
        page, page_size, offset = self._pagination(page, page_size)
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            clauses.append("(username LIKE ? OR workflow_key LIKE ? OR workflow_label LIKE ? OR run_id LIKE ?)")
            term = f"%{_safe_text(search, 80)}%"
            params.extend([term, term, term, term])
        if status:
            clauses.append("status = ?")
            params.append(_safe_text(status, 32))
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM workflow_runs {where}", params).fetchone()[0])
            rows = conn.execute(
                f"""
                SELECT id, run_id, user_id, username, workflow_key, workflow_label,
                       status, path, ip_address, request_bytes, response_bytes,
                       duration_ms, http_status, error_code, started_at, finished_at
                FROM workflow_runs
                {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}


admin_store = AdminStore()
