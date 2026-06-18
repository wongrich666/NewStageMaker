from __future__ import annotations

import unittest
from unittest.mock import patch

from workflow_code_skeleton.app.services.task_manager import (
    EPISODE_PLAN_DISPLAY_ARTIFACT,
    TaskManager,
    TaskRecord,
    WorkflowRuntime,
    task_manager,
)
from workflow_code_skeleton.tests.test_support import WorkspaceTempDir


class _FakeThread:
    instances = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.started = False
        type(self).instances.append(self)

    def start(self) -> None:
        self.started = True


class TaskManagerCompatibilityTests(unittest.TestCase):
    def test_legacy_imports_remain_available_after_split(self) -> None:
        manager = TaskManager()
        record = TaskRecord(
            user_id=1,
            project_id=1,
            task_id="task-compat",
            workflow_spec_path="spec.json",
            input_payload={},
            model_option=None,
            snapshot={"project_id": 1, "status": "pending"},
        )
        runtime = WorkflowRuntime(manager=manager, record=record, spec=None)

        self.assertTrue(hasattr(manager, "start_task"))
        self.assertTrue(hasattr(manager, "save_final_script"))
        self.assertEqual(EPISODE_PLAN_DISPLAY_ARTIFACT, "episode_plan_display")
        self.assertEqual(runtime.record.task_id, "task-compat")
        self.assertIsInstance(task_manager, TaskManager)

    def test_same_user_can_start_multiple_independent_tasks(self) -> None:
        _FakeThread.instances = []
        with WorkspaceTempDir(prefix="task-concurrency-") as temp_dir:
            manager = TaskManager()
            manager.set_storage_root(temp_dir)

            with patch(
                "workflow_code_skeleton.app.services.task_lifecycle.use_fastgpt_backend",
                return_value=True,
            ), patch(
                "workflow_code_skeleton.app.services.task_lifecycle.threading.Thread",
                _FakeThread,
            ):
                first = manager.start_task(
                    user_id=7,
                    input_payload={"title": "并发任务一", "total_episodes": 10},
                    workflow_spec_path="unused.json",
                    model_selection_id=None,
                )
                second = manager.start_task(
                    user_id=7,
                    input_payload={"title": "并发任务二", "total_episodes": 12},
                    workflow_spec_path="unused.json",
                    model_selection_id=None,
                )

        self.assertNotEqual(first["task_id"], second["task_id"])
        self.assertNotEqual(first["project_id"], second["project_id"])
        self.assertEqual(first["status"], "pending")
        self.assertEqual(second["status"], "pending")
        self.assertEqual(len(_FakeThread.instances), 2)
        self.assertTrue(all(thread.started for thread in _FakeThread.instances))


if __name__ == "__main__":
    unittest.main()
