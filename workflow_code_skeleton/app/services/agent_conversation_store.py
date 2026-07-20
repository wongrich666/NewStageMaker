from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtime_paths import get_runtime_data_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except Exception:
        return fallback


class AgentConversationStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else get_runtime_data_dir() / "agent_conversations.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 20000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_conversations (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    project_id INTEGER,
                    task_id TEXT,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES agent_conversations(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS agent_requests (
                    request_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    response_json TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES agent_conversations(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS agent_actions (
                    action_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES agent_conversations(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS agent_attachments (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    script_text TEXT NOT NULL,
                    source_document_id TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES agent_conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_agent_conversations_user
                    ON agent_conversations(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_agent_messages_conversation
                    ON agent_messages(conversation_id, id);
                CREATE INDEX IF NOT EXISTS idx_agent_attachments_conversation
                    ON agent_attachments(conversation_id, created_at DESC);
                """
            )
            conn.commit()

    def _conversation(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "user_id": int(row["user_id"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "project_id": int(row["project_id"]) if row["project_id"] is not None else None,
            "task_id": str(row["task_id"] or ""),
            "state": _loads(row["state_json"], {}),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def create(self, user_id: int, *, title: str = "新的创作对话") -> dict[str, Any]:
        conversation_id = uuid.uuid4().hex
        now = _now_iso()
        clean_title = str(title or "新的创作对话").strip()[:80] or "新的创作对话"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_conversations
                    (id, user_id, title, status, state_json, created_at, updated_at)
                VALUES (?, ?, ?, 'active', '{}', ?, ?)
                """,
                (conversation_id, int(user_id), clean_title, now, now),
            )
            conn.commit()
        return self.get(user_id, conversation_id) or {}

    def get(self, user_id: int, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_conversations WHERE id = ? AND user_id = ?",
                (str(conversation_id), int(user_id)),
            ).fetchone()
        return self._conversation(row)

    def list(self, user_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_conversations
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (int(user_id), min(max(int(limit), 1), 100)),
            ).fetchall()
        return [item for row in rows if (item := self._conversation(row)) is not None]

    def update(
        self,
        user_id: int,
        conversation_id: str,
        *,
        title: str | None = None,
        project_id: int | None = None,
        task_id: str | None = None,
        state: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        current = self.get(user_id, conversation_id)
        if not current:
            return None
        values = {
            "title": str(title if title is not None else current["title"]).strip()[:80] or current["title"],
            "project_id": project_id if project_id is not None else current.get("project_id"),
            "task_id": str(task_id if task_id is not None else current.get("task_id") or ""),
            "state": state if state is not None else current.get("state") or {},
            "status": str(status if status is not None else current.get("status") or "active"),
            "updated_at": _now_iso(),
        }
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_conversations
                SET title = ?, project_id = ?, task_id = ?, state_json = ?, status = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    values["title"],
                    values["project_id"],
                    values["task_id"],
                    _json(values["state"]),
                    values["status"],
                    values["updated_at"],
                    str(conversation_id),
                    int(user_id),
                ),
            )
            conn.commit()
        return self.get(user_id, conversation_id)

    def delete(self, user_id: int, conversation_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM agent_conversations WHERE id = ? AND user_id = ?",
                (str(conversation_id), int(user_id)),
            )
            conn.commit()
        return cursor.rowcount > 0

    def save_attachment(
        self,
        user_id: int,
        conversation_id: str,
        *,
        filename: str,
        extension: str,
        script_text: str,
        source_document_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.get(user_id, conversation_id):
            raise ValueError("对话不存在或无权访问。")
        attachment_id = uuid.uuid4().hex
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_attachments
                    (id, conversation_id, user_id, filename, extension, script_text,
                     source_document_id, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment_id,
                    str(conversation_id),
                    int(user_id),
                    str(filename or "剧本附件"),
                    str(extension or ""),
                    str(script_text or ""),
                    str(source_document_id or ""),
                    _json(metadata or {}),
                    now,
                ),
            )
            conn.commit()
        return self.get_attachment(user_id, conversation_id, attachment_id) or {}

    def get_attachment(
        self,
        user_id: int,
        conversation_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_attachments
                WHERE id = ? AND conversation_id = ? AND user_id = ?
                """,
                (str(attachment_id), str(conversation_id), int(user_id)),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "conversation_id": str(row["conversation_id"]),
            "filename": str(row["filename"]),
            "extension": str(row["extension"]),
            "script_text": str(row["script_text"]),
            "source_document_id": str(row["source_document_id"] or ""),
            "metadata": _loads(row["metadata_json"], {}),
            "created_at": str(row["created_at"]),
        }

    def add_message(
        self,
        user_id: int,
        conversation_id: str,
        *,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.get(user_id, conversation_id):
            raise ValueError("对话不存在或无权访问。")
        now = _now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent_messages
                    (conversation_id, user_id, role, content, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(conversation_id),
                    int(user_id),
                    str(role),
                    str(content),
                    _json(metadata or {}),
                    now,
                ),
            )
            conn.execute(
                "UPDATE agent_conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
                (now, str(conversation_id), int(user_id)),
            )
            conn.commit()
            message_id = int(cursor.lastrowid)
        return {
            "id": message_id,
            "conversation_id": str(conversation_id),
            "role": str(role),
            "content": str(content),
            "metadata": metadata or {},
            "created_at": now,
        }

    def messages(self, user_id: int, conversation_id: str, *, limit: int = 80) -> list[dict[str, Any]]:
        if not self.get(user_id, conversation_id):
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, conversation_id, role, content, metadata_json, created_at
                FROM agent_messages
                WHERE conversation_id = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (str(conversation_id), int(user_id), min(max(int(limit), 1), 200)),
            ).fetchall()
        items = [
            {
                "id": int(row["id"]),
                "conversation_id": str(row["conversation_id"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                "metadata": _loads(row["metadata_json"], {}),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]
        items.reverse()
        return items

    def begin_request(self, user_id: int, conversation_id: str, request_id: str) -> dict[str, Any] | None:
        clean_request_id = str(request_id or "").strip()
        if not clean_request_id:
            return None
        now = _now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT status, response_json FROM agent_requests WHERE request_id = ? AND user_id = ?",
                (clean_request_id, int(user_id)),
            ).fetchone()
            if existing is not None:
                response = _loads(existing["response_json"], None)
                return {"status": str(existing["status"]), "response": response}
            conn.execute(
                """
                INSERT INTO agent_requests
                    (request_id, conversation_id, user_id, status, created_at, updated_at)
                VALUES (?, ?, ?, 'running', ?, ?)
                """,
                (clean_request_id, str(conversation_id), int(user_id), now, now),
            )
            conn.commit()
        return None

    def finish_request(self, user_id: int, request_id: str, response: dict[str, Any], *, status: str = "completed") -> None:
        clean_request_id = str(request_id or "").strip()
        if not clean_request_id:
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_requests
                SET response_json = ?, status = ?, updated_at = ?
                WHERE request_id = ? AND user_id = ?
                """,
                (_json(response), str(status), _now_iso(), clean_request_id, int(user_id)),
            )
            conn.commit()

    def cached_action(self, user_id: int, action_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, result_json FROM agent_actions WHERE action_id = ? AND user_id = ?",
                (str(action_id), int(user_id)),
            ).fetchone()
        if row is None or str(row["status"]) != "completed":
            return None
        result = _loads(row["result_json"], None)
        return result if isinstance(result, dict) else None

    def save_action(
        self,
        user_id: int,
        conversation_id: str,
        action_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_actions
                    (action_id, conversation_id, user_id, tool_name, arguments_json, result_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    result_json = excluded.result_json,
                    status = 'completed',
                    updated_at = excluded.updated_at
                """,
                (
                    str(action_id),
                    str(conversation_id),
                    int(user_id),
                    str(tool_name),
                    _json(arguments),
                    _json(result),
                    now,
                    now,
                ),
            )
            conn.commit()


agent_conversation_store = AgentConversationStore()
