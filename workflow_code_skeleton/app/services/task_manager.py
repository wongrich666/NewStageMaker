from __future__ import annotations

import copy
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..config import ModelOption, settings
from ..models.inputs import WorkflowInput
from ..models.state import WorkflowState
from ..orchestrators.runner import run_configured_workflow
from .workflow_spec import WorkflowSpec
from ..utils.logger import get_logger
from ..workflow_ids import (
    CHARACTER_VAR,
    CORE_SCENE_FINAL_VAR,
    DIALOGUE_FINAL_VAR,
    HOOK_FINAL_VAR,
    MEMORY_VAR,
    SCENE_VAR,
    SCRIPT_CURRENT_VAR,
    SCRIPT_FINAL_VAR,
    WORLDVIEW_VAR,
)

logger = get_logger("task_manager")

PROJECT_RUNNING_STATUSES = {"pending", "running", "pausing", "paused"}
STAGE_LABELS = {
    "validation": "正在检查集数",
    "worldview": "正在整理故事规则",
    "character": "正在梳理人物",
    "scene": "正在整理关键场景",
    "hook": "正在设计开场冲突",
    "dialogue": "正在补充人物对白",
    "script": "正在生成正文",
    "finalize": "正在整理完整稿件",
    "finished": "已完成",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class TaskTerminated(RuntimeError):
    pass


@dataclass(slots=True)
class TaskControl:
    pause_requested: bool = False
    terminate_requested: bool = False
    condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock())
    )

    def request_pause(self) -> None:
        with self.condition:
            self.pause_requested = True
            self.condition.notify_all()

    def request_resume(self) -> None:
        with self.condition:
            self.pause_requested = False
            self.condition.notify_all()

    def request_terminate(self) -> None:
        with self.condition:
            self.terminate_requested = True
            self.pause_requested = False
            self.condition.notify_all()

    def is_pause_requested(self) -> bool:
        with self.condition:
            return self.pause_requested

    def checkpoint(self, *, on_paused: Callable[[], None] | None = None) -> None:
        with self.condition:
            while self.pause_requested and not self.terminate_requested:
                if on_paused is not None:
                    on_paused()
                self.condition.wait(timeout=0.5)
            if self.terminate_requested:
                raise TaskTerminated("任务已终止")


@dataclass(slots=True)
class TaskRecord:
    user_id: int
    project_id: int
    task_id: str
    workflow_spec_path: str
    input_payload: dict[str, Any]
    model_option: ModelOption
    snapshot: dict[str, Any]
    control: TaskControl = field(default_factory=TaskControl)
    thread: threading.Thread | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    def clone_snapshot(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self.snapshot)


class WorkflowRuntime:
    def __init__(
        self,
        *,
        manager: "TaskManager",
        record: TaskRecord,
        spec: WorkflowSpec,
    ) -> None:
        self.manager = manager
        self.record = record
        self.spec = spec

    def checkpoint(self) -> None:
        def _mark_paused() -> None:
            snapshot = self.record.clone_snapshot()
            if snapshot.get("status") != "paused":
                self.manager._update_snapshot(
                    self.record,
                    status="paused",
                    message="已暂停，等待继续。",
                )

        if self.record.control.is_pause_requested():
            _mark_paused()
        self.record.control.checkpoint(on_paused=_mark_paused)
        if self.record.clone_snapshot().get("status") in {"paused", "pausing"}:
            self.manager._update_snapshot(
                self.record,
                status="running",
                message="已继续执行。",
            )

    def set_stage(
        self,
        stage_key: str,
        message: str,
        *,
        batch_label: str | None = None,
        progress_percent: int | None = None,
        generated_episodes: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "current_stage": stage_key,
            "current_stage_label": STAGE_LABELS.get(stage_key, stage_key),
            "message": message,
        }
        if batch_label is not None:
            payload["current_batch"] = batch_label
        if progress_percent is not None:
            payload["progress_percent"] = max(0, min(100, int(progress_percent)))
        if generated_episodes is not None:
            payload["generated_episodes"] = max(0, int(generated_episodes))
        self.manager._update_snapshot(self.record, **payload)

    def before_node(self, node_id: str, state: WorkflowState) -> None:
        self.checkpoint()
        node_name = self.spec.get_node_name(node_id)
        self.manager._append_log(
            self.record,
            title=f"开始节点：{node_name}",
            message=f"{node_id} 正在执行。",
            node_id=node_id,
        )
        self.manager._update_snapshot(
            self.record,
            status="running",
            current_node_id=node_id,
            current_node_name=node_name,
            message=f"正在执行：{node_name}",
        )
        self.sync_from_state(state)

    def after_node(self, node_id: str, state: WorkflowState, output_text: str) -> None:
        node_name = self.spec.get_node_name(node_id)
        preview = str(output_text or "").strip().replace("\n", " ")[:180]
        self.manager._append_log(
            self.record,
            title=f"完成节点：{node_name}",
            message=preview or "节点已完成。",
            node_id=node_id,
        )
        self.sync_from_state(state)
        self.checkpoint()

    def fastgpt_stage_started(self, stage_name: str, input_names: list[str]) -> None:
        self.checkpoint()
        self.manager._append_log(
            self.record,
            title=f"开始 FastGPT 阶段：{stage_name}",
            message=f"传入变量：{', '.join(input_names)}",
            node_id=f"fastgpt:{stage_name}",
        )

    def fastgpt_stage_finished(self, stage_name: str, output: dict[str, Any]) -> None:
        preview_parts: list[str] = []
        for key, value in output.items():
            text = str(value or "").strip().replace("\n", " ")
            preview_parts.append(f"{key}={text[:80]}")
        self.manager._append_log(
            self.record,
            title=f"完成 FastGPT 阶段：{stage_name}",
            message="；".join(preview_parts)[:240] or "阶段已完成。",
            node_id=f"fastgpt:{stage_name}",
        )

    def sync_from_state(self, state: WorkflowState) -> None:
        artifacts = {
            "worldview": state.get_var(WORLDVIEW_VAR, ""),
            "character_summary": state.get_var(CHARACTER_VAR, ""),
            "scene_json": state.get_var(SCENE_VAR, ""),
            "core_scene_summary": state.get_var(CORE_SCENE_FINAL_VAR, ""),
            "hook_plan": state.get_var(HOOK_FINAL_VAR, ""),
            "dialogue_plan": state.get_var(DIALOGUE_FINAL_VAR, ""),
            "script_batch": state.get_var(SCRIPT_CURRENT_VAR, ""),
            "final_script": state.get_var(SCRIPT_FINAL_VAR, ""),
            "continuity_memory": state.get_var(MEMORY_VAR, ""),
            "halted_message": state.halted_message or "",
            "final_output_text": state.final_output_text or "",
        }
        self.manager._update_snapshot(
            self.record,
            artifacts=artifacts,
            debug_state=state.as_debug_dict(),
            prompt_fixes=state.prompt_fixes,
        )


class TaskManager:
    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parents[2] / "runtime_data"
        self.projects_dir = self.base_dir / "projects"
        self.exports_dir = self.base_dir / "exports"
        self.index_path = self.base_dir / "index.json"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._tasks: dict[str, TaskRecord] = {}
        self._projects: dict[int, TaskRecord] = {}
        self._index = self._load_index()
        self._repair_persisted_snapshots()

    def _load_index(self) -> dict[str, Any]:
        if self.index_path.exists():
            try:
                return json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        data = {"next_project_id": 1, "latest_project_id": None}
        self._save_index(data)
        return data

    def _save_index(self, data: dict[str, Any] | None = None) -> None:
        payload = data or self._index
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _repair_persisted_snapshots(self) -> None:
        for path in self.projects_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("status") in PROJECT_RUNNING_STATUSES:
                data["status"] = "terminated"
                data["message"] = "服务重启后，进行中的任务已停止，请重新开始或重新生成。"
                data["updated_at"] = now_iso()
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    def _project_path(self, project_id: int) -> Path:
        return self.projects_dir / f"{project_id}.json"

    def _persist_snapshot(self, record: TaskRecord) -> None:
        path = self._project_path(record.project_id)
        with record.lock:
            path.write_text(
                json.dumps(record.snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _append_log(
        self,
        record: TaskRecord,
        *,
        title: str,
        message: str,
        node_id: str | None = None,
    ) -> None:
        with record.lock:
            logs = list(record.snapshot.get("logs", []))
            logs.append(
                {
                    "time": now_iso(),
                    "title": title,
                    "message": message,
                    "node_id": node_id,
                }
            )
            record.snapshot["logs"] = logs[-200:]
            record.snapshot["updated_at"] = now_iso()
        self._persist_snapshot(record)

    def _update_snapshot(self, record: TaskRecord, **changes: Any) -> None:
        with record.lock:
            if "artifacts" in changes and isinstance(changes["artifacts"], dict):
                merged_artifacts = dict(record.snapshot.get("artifacts", {}))
                merged_artifacts.update(changes.pop("artifacts"))
                record.snapshot["artifacts"] = merged_artifacts

            record.snapshot.update(changes)
            record.snapshot["updated_at"] = now_iso()
        self._persist_snapshot(record)

    def _next_project_id(self) -> int:
        with self._lock:
            project_id = int(self._index.get("next_project_id", 1))
            self._index["next_project_id"] = project_id + 1
            self._index["latest_project_id"] = project_id
            self._save_index()
            return project_id

    def _remember_latest_project(self, user_id: int, project_id: int) -> None:
        with self._lock:
            latest_by_user = dict(self._index.get("latest_project_by_user", {}))
            latest_by_user[str(int(user_id))] = int(project_id)
            self._index["latest_project_by_user"] = latest_by_user
            self._index["latest_project_id"] = int(project_id)
            self._save_index()

    def _snapshot_belongs_to_user(
        self,
        snapshot: dict[str, Any] | None,
        user_id: int | None,
    ) -> bool:
        if snapshot is None:
            return False
        if user_id is None:
            return True
        return int(snapshot.get("user_id") or 0) == int(user_id)

    def _model_alias(self, provider: str, index: int = 1) -> str:
        provider_name = str(provider or "").strip().lower()
        initials = {
            "deepseek": "D",
            "gemini": "G",
            "claude": "C",
            "ollama": "O",
            "doubao": "D",
            "fastgpt": "F",
        }
        letter = initials.get(provider_name, (provider_name[:1] or "M").upper())
        base = f"XK{letter.upper()}"
        return base if index <= 1 else f"{base}{index}"

    def list_model_options(self, workflow_spec_path: str) -> list[dict[str, Any]]:
        spec = WorkflowSpec(workflow_spec_path)
        options = settings.list_model_options(extra_models=spec.list_chat_models())
        provider_counts: dict[str, int] = {}
        result = []
        for item in options:
            provider_counts[item.provider] = provider_counts.get(item.provider, 0) + 1
            alias = self._model_alias(item.provider, provider_counts[item.provider])
            if not item.configured:
                alias = f"{alias} [未配置]"
            result.append(
                {
                "id": item.id,
                "label": alias,
                "provider": item.provider,
                "model": item.model,
                "is_default": item.is_default,
                "configured": item.configured,
            }
            )
        return result

    def latest_project_snapshot(self, user_id: int | None = None) -> dict[str, Any] | None:
        if user_id is not None:
            latest_by_user = self._index.get("latest_project_by_user", {})
            latest_project_id = latest_by_user.get(str(int(user_id)))
            if latest_project_id:
                snapshot = self.get_project_snapshot(int(latest_project_id), user_id=user_id)
                if snapshot:
                    return snapshot

            candidates: list[dict[str, Any]] = []
            for path in self.projects_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if self._snapshot_belongs_to_user(data, user_id):
                    candidates.append(data)
            if not candidates:
                return None
            candidates.sort(
                key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
                reverse=True,
            )
            return candidates[0]

        latest_project_id = self._index.get("latest_project_id")
        if not latest_project_id:
            return None
        return self.get_project_snapshot(int(latest_project_id))

    def get_project_snapshot(
        self,
        project_id: int,
        *,
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        record = self._projects.get(project_id)
        if record:
            snapshot = record.clone_snapshot()
            return snapshot if self._snapshot_belongs_to_user(snapshot, user_id) else None

        path = self._project_path(project_id)
        if not path.exists():
            return None
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        return snapshot if self._snapshot_belongs_to_user(snapshot, user_id) else None

    def get_task_snapshot(
        self,
        task_id: str,
        *,
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        record = self._tasks.get(task_id)
        if record:
            snapshot = record.clone_snapshot()
            return snapshot if self._snapshot_belongs_to_user(snapshot, user_id) else None
        for path in self.projects_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("task_id") == task_id and self._snapshot_belongs_to_user(data, user_id):
                return data
        return None

    def start_task(
        self,
        *,
        user_id: int,
        input_payload: dict[str, Any],
        workflow_spec_path: str,
        model_selection_id: str | None,
    ) -> dict[str, Any]:
        project_id = self._next_project_id()
        self._remember_latest_project(user_id, project_id)
        task_id = uuid.uuid4().hex[:12]
        model_option = settings.resolve_model_selection(model_selection_id)
        spec = WorkflowSpec(workflow_spec_path)

        snapshot = {
            "user_id": int(user_id),
            "project_id": project_id,
            "task_id": task_id,
            "status": "pending",
            "title": str(input_payload.get("title", "")).strip(),
            "message": "任务已创建，准备开始生成。",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "workflow_spec_path": workflow_spec_path,
            "model_option": {
                "id": model_option.id,
                "label": self._model_alias(model_option.provider),
                "provider": model_option.provider,
                "model": model_option.model,
            }
            if model_option
            else None,
            "input_payload": input_payload,
            "artifacts": {},
            "logs": [],
            "prompt_fixes": spec.get_prompt_fixes(),
            "progress_percent": 0,
            "generated_episodes": 0,
            "total_episodes": int(input_payload.get("total_episodes", 0) or 0),
            "current_stage": "validation",
            "current_stage_label": STAGE_LABELS["validation"],
            "current_node_id": None,
            "current_node_name": None,
            "current_batch": None,
            "debug_state": {},
        }

        record = TaskRecord(
            user_id=int(user_id),
            project_id=project_id,
            task_id=task_id,
            workflow_spec_path=workflow_spec_path,
            input_payload=input_payload,
            model_option=model_option,
            snapshot=snapshot,
        )
        self._tasks[task_id] = record
        self._projects[project_id] = record
        self._persist_snapshot(record)

        thread = threading.Thread(
            target=self._run_task,
            args=(record,),
            daemon=True,
            name=f"workflow-task-{task_id}",
        )
        record.thread = thread
        thread.start()
        return record.clone_snapshot()

    def _run_task(self, record: TaskRecord) -> None:
        self._update_snapshot(record, status="running", message="开始执行工作流。")
        try:
            workflow_input = WorkflowInput.from_dict(record.input_payload)
            spec = WorkflowSpec(record.workflow_spec_path)
            runtime = WorkflowRuntime(manager=self, record=record, spec=spec)

            state = run_configured_workflow(
                workflow_input,
                workflow_spec_path=record.workflow_spec_path,
                runtime=runtime,
                model_option=record.model_option,
            )

            if state.halted_message:
                runtime.sync_from_state(state)
                self._update_snapshot(
                    record,
                    status="failed",
                    current_stage="validation",
                    current_stage_label=STAGE_LABELS["validation"],
                    message=state.halted_message,
                    error=state.halted_message,
                    progress_percent=0,
                )
                return

            runtime.set_stage("finalize", "正在整理最终输出。", progress_percent=100)
            runtime.sync_from_state(state)
            self._update_snapshot(
                record,
                status="completed",
                current_stage="finished",
                current_stage_label=STAGE_LABELS["finished"],
                message="剧本生成完成。",
                finished_at=now_iso(),
                progress_percent=100,
                generated_episodes=record.snapshot.get("total_episodes", 0),
                prompt_fixes=state.prompt_fixes,
            )
        except TaskTerminated as exc:
            self._update_snapshot(
                record,
                status="terminated",
                current_stage="finished",
                current_stage_label=STAGE_LABELS["finished"],
                message=str(exc),
                finished_at=now_iso(),
            )
        except Exception as exc:
            logger.exception("任务执行失败: %s", record.task_id)
            self._update_snapshot(
                record,
                status="failed",
                current_stage="finished",
                current_stage_label=STAGE_LABELS["finished"],
                message=f"任务失败：{exc}",
                error=str(exc),
                finished_at=now_iso(),
            )

    def _get_task_record_for_user(self, task_id: str, user_id: int | None) -> TaskRecord:
        record = self._tasks.get(task_id)
        if not record:
            raise ValueError("任务不存在")
        if user_id is not None and int(record.user_id) != int(user_id):
            raise ValueError("您没有权限操作该任务")
        return record

    def pause_task(self, task_id: str, user_id: int | None = None) -> dict[str, Any]:
        record = self._get_task_record_for_user(task_id, user_id)
        snapshot = record.clone_snapshot()
        status = snapshot.get("status")
        if status in {"paused", "pausing"}:
            return snapshot
        if status not in {"pending", "running"}:
            raise ValueError("只有进行中的任务才能暂停")
        record.control.request_pause()
        self._append_log(
            record,
            title="控制动作：暂停请求",
            message="暂停指令已发出，当前节点完成后会暂停。",
        )
        self._update_snapshot(
            record,
            status="pausing",
            message="暂停指令已发出，当前节点完成后会暂停。",
        )
        return record.clone_snapshot()

    def resume_task(self, task_id: str, user_id: int | None = None) -> dict[str, Any]:
        record = self._get_task_record_for_user(task_id, user_id)
        snapshot = record.clone_snapshot()
        status = snapshot.get("status")
        if status == "running" and not record.control.is_pause_requested():
            return snapshot
        if status not in {"paused", "pausing", "running"}:
            raise ValueError("只有已暂停或正在暂停的任务才能继续")
        record.control.request_resume()
        self._append_log(
            record,
            title="控制动作：继续请求",
            message="继续指令已发出，任务恢复执行。",
        )
        self._update_snapshot(
            record,
            status="running",
            message="继续指令已发出，任务恢复执行。",
        )
        return record.clone_snapshot()

    def terminate_task(self, task_id: str, user_id: int | None = None) -> dict[str, Any]:
        record = self._get_task_record_for_user(task_id, user_id)
        snapshot = record.clone_snapshot()
        if snapshot.get("status") in {"completed", "failed", "terminated"}:
            return snapshot
        record.control.request_terminate()
        self._append_log(
            record,
            title="控制动作：终止请求",
            message="终止指令已发出，当前节点结束后会停止。",
        )
        self._update_snapshot(record, message="终止指令已发出，当前节点结束后会停止。")
        return record.clone_snapshot()

    def clear_project(self, project_id: int, user_id: int | None = None) -> None:
        record = self._projects.get(project_id)
        if record:
            if user_id is not None and int(record.user_id) != int(user_id):
                raise ValueError("您没有权限清空该项目")
            snapshot = record.clone_snapshot()
            if snapshot.get("status") in PROJECT_RUNNING_STATUSES:
                raise ValueError("请先终止当前任务，再执行清空。")
            self._tasks.pop(record.task_id, None)
            self._projects.pop(project_id, None)

        path = self._project_path(project_id)
        if path.exists():
            if user_id is not None:
                try:
                    snapshot = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    snapshot = {}
                if not self._snapshot_belongs_to_user(snapshot, user_id):
                    raise ValueError("您没有权限清空该项目")
            path.unlink()

        if self._index.get("latest_project_id") == project_id:
            self._index["latest_project_id"] = None
            self._save_index()

    def save_final_script(self, project_id: int, user_id: int | None = None) -> Path:
        snapshot = self.get_project_snapshot(project_id, user_id=user_id)
        if not snapshot:
            raise ValueError("项目不存在")
        artifacts = snapshot.get("artifacts", {})
        content = (
            artifacts.get("final_output_text")
            or artifacts.get("final_script")
            or ""
        ).strip()
        if not content:
            raise ValueError("当前项目还没有可保存的最终剧本")
        title = str(snapshot.get("title") or f"project_{project_id}").strip() or f"project_{project_id}"
        safe_title = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in title)[:80]
        path = self.exports_dir / f"{safe_title}_{project_id}.txt"
        path.write_text(content, encoding="utf-8")
        self._update_snapshot(
            self._projects.get(project_id) or TaskRecord(
                user_id=int(snapshot.get("user_id") or 0),
                project_id=project_id,
                task_id=str(snapshot.get("task_id", "")),
                workflow_spec_path=str(snapshot.get("workflow_spec_path", "")),
                input_payload=snapshot.get("input_payload", {}),
                model_option=settings.resolve_model_selection(
                    (snapshot.get("model_option") or {}).get("id")
                ),
                snapshot=snapshot,
            ),
            saved_file=str(path),
        )
        return path


task_manager = TaskManager()
