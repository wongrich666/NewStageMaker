
from __future__ import annotations

"""Compatibility facade for the refactored TaskManager service."""

from .project_snapshot_store import ProjectSnapshotStoreMixin
from .runtime_export_store import RuntimeExportStoreMixin
from .stage_cache import StageCacheMixin
from .task_lifecycle import TaskLifecycleMixin
from . import task_manager_common as _task_manager_common
from .task_manager_common import *
globals().update(
    {name: getattr(_task_manager_common, name) for name in dir(_task_manager_common) if name.startswith("_")}
)
from .task_state import TaskControl, TaskRecord, TaskTerminated, WorkflowRuntime


class TaskManager(
    ProjectSnapshotStoreMixin,
    StageCacheMixin,
    TaskLifecycleMixin,
    RuntimeExportStoreMixin,
):
    """Public facade that preserves the historic TaskManager API."""

    def __init__(self) -> None:
        _ONE_SHOT_WARNING_KEYS.clear()
        self.set_storage_root(get_runtime_data_dir())

        self._lock = threading.RLock()
        self._tasks: dict[str, TaskRecord] = {}
        self._projects: dict[int, TaskRecord] = {}
        self._index = self._load_index()
        self._repair_persisted_snapshots()


task_manager = TaskManager()
