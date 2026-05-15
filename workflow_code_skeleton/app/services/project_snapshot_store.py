
from __future__ import annotations

"""Extracted TaskManager mixin for ProjectSnapshotStoreMixin."""

from . import task_manager_common as _task_manager_common
from .task_manager_common import *
globals().update(
    {name: getattr(_task_manager_common, name) for name in dir(_task_manager_common) if name.startswith("_")}
)
from .task_state import TaskRecord

SNAPSHOT_LOG_LIMIT = 200


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        try:
            _task_manager_common.logger.warning("读取项目快照失败：path=%s error=%s", path, exc)
        except Exception:
            pass
        return None
    if not isinstance(data, dict):
        try:
            _task_manager_common.logger.warning("项目快照不是 JSON object：path=%s type=%s", path, type(data).__name__)
        except Exception:
            pass
        return None
    return data


def _write_json_object(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _normalized_log_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    logs: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            logs.append(dict(item))
    return logs[-SNAPSHOT_LOG_LIMIT:]


def _next_log_index(logs: list[dict[str, Any]]) -> int:
    if not logs:
        return 1
    last = logs[-1]
    return max(1, _safe_int(last.get("index"), len(logs))) + 1


def _sync_wait_tracking(
    snapshot: dict[str, Any],
    *,
    previous_status: Any,
    current_status: Any,
    current_time_iso: str,
) -> None:
    """同步任务等待/运行耗时字段。

    wait_started_at 表示当前 running/pending/pausing 区间的开始时间。
    wait_elapsed_ms 表示已经累计完成的等待/运行毫秒数。
    """

    from datetime import datetime, timezone

    running_statuses = set(WAITING_STATUSES)
    previous = str(previous_status or "").strip().lower()
    current = str(current_status or "").strip().lower()

    def _parse_iso(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            return None

    current_dt = _parse_iso(current_time_iso) or datetime.now(timezone.utc)
    elapsed_ms = max(0, _safe_int(snapshot.get("wait_elapsed_ms"), 0))

    was_running = previous in running_statuses
    is_running = current in running_statuses

    if is_running:
        if not was_running or not snapshot.get("wait_started_at"):
            snapshot["wait_started_at"] = current_time_iso
        snapshot["wait_elapsed_ms"] = max(0, elapsed_ms)
        return

    if was_running:
        started_at = _parse_iso(snapshot.get("wait_started_at"))
        if started_at is not None:
            delta_ms = int(max(0, (current_dt - started_at).total_seconds() * 1000))
            elapsed_ms += delta_ms

    snapshot["wait_elapsed_ms"] = max(0, elapsed_ms)
    snapshot["wait_started_at"] = None


class ProjectSnapshotStoreMixin:
    def set_storage_root(
        self,
        runtime_data_dir: Path,
        *,
        runtime_archive_dir: Path | None = None,
    ) -> None:
        self.base_dir = Path(runtime_data_dir).resolve()
        self.runtime_root = (
            self.base_dir.parent
            if self.base_dir.name == "runtime_data"
            else self.base_dir
        )
        self.runtime_archive_dir = (
            Path(runtime_archive_dir).resolve()
            if runtime_archive_dir is not None
            else self.runtime_root / "runtime_archive"
        )
        self.runtime_manifest_path = self.runtime_archive_dir / "manifest.json"
        self.projects_dir = self.base_dir / "projects"
        self.exports_dir = self.base_dir / "exports"
        self.index_path = self.base_dir / "index.json"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> dict[str, Any]:
        if self.index_path.exists():
            data = _read_json_object(self.index_path)
            if data is not None:
                changed = False
                next_project_id = max(1, _safe_int(data.get("next_project_id"), 1))
                if data.get("next_project_id") != next_project_id:
                    data["next_project_id"] = next_project_id
                    changed = True
                latest_project_id = data.get("latest_project_id")
                if latest_project_id is not None:
                    normalized_latest = _safe_int(latest_project_id, 0)
                    data["latest_project_id"] = normalized_latest or None
                    changed = changed or data["latest_project_id"] != latest_project_id
                latest_by_user = data.get("latest_project_by_user")
                if not isinstance(latest_by_user, dict):
                    data["latest_project_by_user"] = {}
                    changed = True
                if changed:
                    self._save_index(data)
                return data
        data = {"next_project_id": 1, "latest_project_id": None}
        self._save_index(data)
        return data

    def _save_index(self, data: dict[str, Any] | None = None) -> None:
        payload = data or self._index
        _write_json_object(self.index_path, payload)

    def _repair_persisted_snapshots(self) -> None:
        for path in self.projects_dir.glob("*.json"):
            data = _read_json_object(path)
            if data is None:
                continue
            changed = False
            if data.get("status") in PROJECT_RUNNING_STATUSES:
                data["status"] = "terminated"
                data["message"] = TERMINATED_PUBLIC_MESSAGE
                data["updated_at"] = now_iso()
                changed = True
            elif str(data.get("status") or "") == "failed":
                if str(data.get("message") or "").strip() != FAILED_PUBLIC_MESSAGE:
                    data["message"] = FAILED_PUBLIC_MESSAGE
                    data["updated_at"] = now_iso()
                    changed = True
            elif str(data.get("status") or "") == "terminated":
                if str(data.get("message") or "").strip() != TERMINATED_PUBLIC_MESSAGE:
                    data["message"] = TERMINATED_PUBLIC_MESSAGE
                    data["updated_at"] = now_iso()
                    changed = True
            elif str(data.get("status") or "") == "completed":
                if "completion_confirmed" not in data:
                    data["completion_confirmed"] = True
                    data["awaiting_user_confirmation"] = False
                    data["cache_retained"] = False
                    changed = True
                if _completion_confirmed(data):
                    compacted = self._compact_completed_snapshot(data)
                    if compacted != data:
                        data = compacted
                        changed = True
                else:
                    if not _awaiting_completion_confirmation(data):
                        data["awaiting_user_confirmation"] = True
                        changed = True
                    if not data.get("cache_retained"):
                        data["cache_retained"] = True
                        changed = True
                    if str(data.get("message") or "").strip() != COMPLETION_PENDING_MESSAGE:
                        data["message"] = COMPLETION_PENDING_MESSAGE
                        changed = True
            if changed:
                _write_json_object(path, data)

    def _project_path(self, project_id: int) -> Path:
        return self.projects_dir / f"{project_id}.json"

    def _runtime_relpath(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.runtime_root).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    def _iter_project_snapshot_paths(self) -> list[Path]:
        active_paths = sorted(self.projects_dir.glob("*.json"))
        seen_project_ids: set[int] = set()
        paths: list[Path] = []

        for path in active_paths:
            paths.append(path)
            try:
                seen_project_ids.add(int(path.stem))
            except ValueError:
                continue

        manifest = load_runtime_manifest(manifest_path=self.runtime_manifest_path)
        for entry in manifest.get("entries", {}).values():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("category") or "") != "projects":
                continue
            project_id = _safe_int(entry.get("project_id"), 0)
            if project_id in seen_project_ids:
                continue
            archived_path_text = str(entry.get("archived_path") or "").strip()
            if not archived_path_text:
                continue
            archived_path = Path(archived_path_text)
            if not archived_path.is_absolute():
                archived_path = (self.runtime_root / archived_path).resolve()
            if archived_path.exists():
                paths.append(archived_path)
                if project_id > 0:
                    seen_project_ids.add(project_id)
        return paths

    def _persist_snapshot(self, record: TaskRecord) -> None:
        path = self._project_path(record.project_id)
        with record.lock:
            if bool(record.snapshot.get("_deleted")):
                return
            snapshot = copy.deepcopy(record.snapshot)
        _write_json_object(path, snapshot)

    def _build_resume_checkpoint(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        checkpoint = copy.deepcopy(snapshot)
        checkpoint.pop("_resume_checkpoint", None)
        checkpoint.pop("error", None)
        checkpoint.pop("finished_at", None)
        return checkpoint

    def _save_resume_checkpoint(self, record: TaskRecord) -> None:
        with record.lock:
            record.snapshot["_resume_checkpoint"] = self._build_resume_checkpoint(record.snapshot)
        self._persist_snapshot(record)

    def _restore_from_resume_checkpoint(self, record: TaskRecord) -> None:
        checkpoint = record.clone_snapshot().get("_resume_checkpoint")
        if not isinstance(checkpoint, dict):
            return

        fields_to_restore = (
            "artifacts",
            "display_stage",
            "display_payload",
            "display_history",
            "stage_summaries",
            "stage_inputs",
            "stage_outputs",
            "stage_errors",
            "stage_statuses",
            "stage_payloads",
            "stage_artifacts",
            "stage_cache",
            "runtime_state",
            "runtime_cache_notice",
            "cache_retained",
            "current_stage",
            "current_stage_label",
            "current_node_id",
            "current_node_name",
            "current_batch",
            "progress_percent",
            "generated_episodes",
            "approved_batches",
            "latest_batch_preview",
            "final_output_text",
            "final_docx_path",
            "final_txt_path",
            "awaiting_user_confirmation",
            "needs_user_intervention",
            "intervention_reason",
            "debug_state",
            "prompt_fixes",
        )

        restored = self._build_resume_checkpoint(checkpoint)

        with record.lock:
            existing_logs = copy.deepcopy(record.snapshot.get("logs", []))
            existing_last_log = copy.deepcopy(record.snapshot.get("last_log"))

            for key in fields_to_restore:
                if key in restored:
                    record.snapshot[key] = copy.deepcopy(restored[key])

            if existing_logs:
                record.snapshot["logs"] = existing_logs[-200:]
            elif isinstance(restored.get("logs"), list):
                record.snapshot["logs"] = copy.deepcopy(restored["logs"][-200:])
            else:
                record.snapshot.setdefault("logs", [])

            if existing_last_log:
                record.snapshot["last_log"] = existing_last_log
            elif record.snapshot.get("logs"):
                record.snapshot["last_log"] = record.snapshot["logs"][-1]
            else:
                record.snapshot.pop("last_log", None)

            record.snapshot["_resume_checkpoint"] = restored
            record.snapshot["updated_at"] = now_iso()

        self._persist_snapshot(record)

    def _append_log(
            self,
            record: TaskRecord,
            *,
            title: str,
            message: str,
            node_id: str | None = None,
            level: str = "info",
    ) -> None:
        entry = {
            "time": now_iso(),
            "level": str(level or "info").lower(),
            "title": str(title or "").strip(),
            "message": str(message or "").strip(),
            "node_id": node_id,
        }

        try:
            _task_manager_common.logger.info(
                "[task:%s project:%s] %s%s%s",
                record.task_id,
                record.project_id,
                entry["title"],
                f" node={node_id}" if node_id else "",
                f" - {entry['message']}" if entry["message"] else "",
            )
        except Exception:
            pass

        with record.lock:
            logs = list(record.snapshot.get("logs", []))
            entry["index"] = len(logs) + 1
            logs.append(entry)
            record.snapshot["logs"] = logs[-200:]
            record.snapshot["last_log"] = entry
            record.snapshot["updated_at"] = now_iso()

        self._persist_snapshot(record)

    def _update_snapshot(self, record: TaskRecord, **changes: Any) -> None:
        with record.lock:
            previous_status = record.snapshot.get("status")

            if "artifacts" in changes and isinstance(changes["artifacts"], dict):
                merged_artifacts = dict(record.snapshot.get("artifacts", {}))
                merged_artifacts.update(changes.pop("artifacts"))
                record.snapshot["artifacts"] = merged_artifacts

            record.snapshot.update(changes)

            current_time = now_iso()
            current_status = record.snapshot.get("status", previous_status)

            _sync_wait_tracking(
                record.snapshot,
                previous_status=previous_status,
                current_status=current_status,
                current_time_iso=current_time,
            )

            record.snapshot["updated_at"] = current_time

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

    def _load_project_snapshot_raw(self, project_id: int) -> dict[str, Any] | None:
        record = self._projects.get(project_id)
        if record:
            return record.clone_snapshot()
        path = resolve_project_snapshot_path(
            project_id,
            projects_dir=self.projects_dir,
            base_root=self.runtime_root,
            manifest_path=self.runtime_manifest_path,
            archive_dir=self.runtime_archive_dir,
        )
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_task_snapshot_raw(self, task_id: str) -> dict[str, Any] | None:
        record = self._tasks.get(task_id)
        if record:
            return record.clone_snapshot()
        for path in self._iter_project_snapshot_paths():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("task_id") == task_id:
                return data
        return None

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
        extra_models: list[str] = []
        if not use_fastgpt_backend():
            spec = WorkflowSpec(workflow_spec_path)
            extra_models = spec.list_chat_models()
        options = settings.list_model_options(extra_models=extra_models)
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
                snapshot = self.get_project_snapshot(
                    int(latest_project_id),
                    user_id=user_id,
                    public_view=False,
                )
                if snapshot and not self._is_auxiliary_tool_asset(snapshot):
                    return self._public_snapshot(snapshot)

            candidates: list[dict[str, Any]] = []
            for path in self._iter_project_snapshot_paths():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if (
                    self._snapshot_belongs_to_user(data, user_id)
                    and not self._is_auxiliary_tool_asset(data)
                ):
                    candidates.append(data)
            if not candidates:
                return None
            candidates.sort(
                key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
                reverse=True,
            )
            return self._public_snapshot(candidates[0])

        latest_project_id = self._index.get("latest_project_id")
        if not latest_project_id:
            return None
        snapshot = self.get_project_snapshot(int(latest_project_id), public_view=False)
        if snapshot and not self._is_auxiliary_tool_asset(snapshot):
            return self._public_snapshot(snapshot)

        candidates = [
            item
            for item in self._all_project_snapshots()
            if not self._is_auxiliary_tool_asset(item)
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )
        return self._public_snapshot(candidates[0])

    def get_project_snapshot(
        self,
        project_id: int,
        *,
        user_id: int | None = None,
        public_view: bool = True,
    ) -> dict[str, Any] | None:
        snapshot = self._load_project_snapshot_raw(project_id)
        if snapshot is None:
            return None
        if not self._snapshot_belongs_to_user(snapshot, user_id):
            return None
        return self._public_snapshot(snapshot) if public_view else snapshot

    def get_task_snapshot(
        self,
        task_id: str,
        *,
        user_id: int | None = None,
        public_view: bool = True,
    ) -> dict[str, Any] | None:
        snapshot = self._load_task_snapshot_raw(task_id)
        if snapshot is None:
            return None
        if not self._snapshot_belongs_to_user(snapshot, user_id):
            return None
        return self._public_snapshot(snapshot) if public_view else snapshot

    def list_user_assets(self, user_id: int) -> list[dict[str, Any]]:
        assets = [
            self._asset_summary(snapshot, include_private=True, use_teaser=True)
            for snapshot in self._all_project_snapshots()
            if self._snapshot_belongs_to_user(snapshot, user_id)
        ]
        assets.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return assets

    def list_user_projects(self, user_id: int) -> list[dict[str, Any]]:
        projects = [
            self._asset_summary(snapshot, include_private=True, use_teaser=False)
            for snapshot in self._all_project_snapshots()
            if self._snapshot_belongs_to_user(snapshot, user_id)
            and str(snapshot.get("asset_kind") or "").strip() != AUXILIARY_TOOL_ASSET_KIND
        ]
        projects.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return projects

    def list_public_assets(self) -> list[dict[str, Any]]:
        assets = [
            self._asset_summary(snapshot, include_private=False, use_teaser=True)
            for snapshot in self._all_project_snapshots()
            if str(snapshot.get("visibility") or "private") == "public"
            and str(snapshot.get("status") or "") == "completed"
            and _completion_confirmed(snapshot)
            and str(snapshot.get("asset_kind") or "").strip() != AUXILIARY_TOOL_ASSET_KIND
            and bool(self._best_final_script_text(snapshot))
        ]
        assets.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return assets[:24]

    def get_public_asset(self, project_id: int) -> dict[str, Any] | None:
        snapshot = self.get_project_snapshot(project_id, public_view=False)
        if not snapshot:
            return None
        if str(snapshot.get("visibility") or "private") != "public":
            return None
        if str(snapshot.get("status") or "") != "completed":
            return None
        if not _completion_confirmed(snapshot):
            return None
        if str(snapshot.get("asset_kind") or "").strip() == AUXILIARY_TOOL_ASSET_KIND:
            return None
        artifacts = snapshot.get("artifacts") or {}
        final_script = self._best_final_script_text(snapshot)
        if not final_script:
            return None

        payload = self._asset_summary(snapshot, include_private=False, use_teaser=True)
        payload["final_script"] = final_script
        payload["story_outline"] = str(
            artifacts.get("story_outline")
            or (snapshot.get("input_payload") or {}).get("story_outline")
            or ""
        ).strip()
        return payload

    def _all_project_snapshots(self) -> list[dict[str, Any]]:
        snapshots: dict[int, dict[str, Any]] = {}
        for project_id, record in self._projects.items():
            snapshots[int(project_id)] = record.clone_snapshot()
        for path in self._iter_project_snapshot_paths():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            project_id = int(data.get("project_id") or path.stem or 0)
            snapshots.setdefault(project_id, data)
        return list(snapshots.values())

