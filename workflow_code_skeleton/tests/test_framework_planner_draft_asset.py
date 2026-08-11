from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from workflow_code_skeleton.app.services.task_manager import TaskManager


class FrameworkPlannerDraftAssetTests(unittest.TestCase):
    def test_framework_draft_can_be_saved_before_episode_count_is_known(self):
        with TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime_data"
            with patch.dict("os.environ", {"RUNTIME_DATA_DIR": str(runtime_dir)}):
                manager = TaskManager()

                asset = manager.save_framework_planner_asset(
                    user_id=7,
                    payload={
                        "project_id": "unsaved",
                        "project_title": "待补总集数的框架",
                        "basic_config": {
                            "project_title": "待补总集数的框架",
                            "source_title": "待补总集数的框架",
                            "episodes_per_season": 0,
                            "total_episodes": 0,
                            "episode_word_count": 600,
                        },
                        "source_brief": {"core_logline": "测试故事"},
                        "asset_state": {"asset_kind": "framework_planner"},
                        "stage_state": {"basic": {"status": "generated"}},
                    },
                )

                self.assertEqual(asset["project_id"], 1)
                self.assertEqual(asset["asset_kind"], "framework_planner")
                self.assertEqual(asset["status"], "in_progress")
                self.assertEqual(asset["total_episodes"], 0)
                self.assertTrue((runtime_dir / "projects" / "1.json").exists())


if __name__ == "__main__":
    unittest.main()
