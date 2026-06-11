from __future__ import annotations

import unittest

from workflow_code_skeleton.app.services.task_manager import (
    EPISODE_PLAN_DISPLAY_ARTIFACT,
    TaskManager,
    TaskRecord,
    WorkflowRuntime,
    task_manager,
)


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


if __name__ == "__main__":
    unittest.main()
