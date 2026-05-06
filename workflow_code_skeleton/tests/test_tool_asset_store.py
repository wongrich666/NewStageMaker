from __future__ import annotations

import unittest
from pathlib import Path

from workflow_code_skeleton.app.services.task_manager import (
    AUXILIARY_TOOL_ASSET_KIND,
    TaskManager,
)
from workflow_code_skeleton.tests.test_support import WorkspaceTempDir


class ToolAssetStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = WorkspaceTempDir(prefix="tool-asset-store-")
        self.addCleanup(self.temp_dir.cleanup)
        self.manager = TaskManager()
        base_dir = Path(self.temp_dir.name) / "runtime_data"
        self.manager.set_storage_root(
            base_dir,
            runtime_archive_dir=Path(self.temp_dir.name) / "runtime_archive",
        )
        self.manager._tasks.clear()
        self.manager._projects.clear()
        self.manager._index = {
            "next_project_id": 1,
            "latest_project_id": None,
            "latest_project_by_user": {},
        }

    def test_save_auxiliary_asset_keeps_multiline_text_and_stays_out_of_project_lists(self) -> None:
        asset = self.manager.save_auxiliary_asset(
            user_id=1,
            tool_key="new_framework",
            request_payload={
                "story": "一个背负旧案的女律师重返故乡。",
                "project_title": "夜行审判",
                "total_episodes": 60,
            },
            result={
                "title": "15节拍剧本框架",
                "text": "第一行\n第二行",
                "filename": "15节拍剧本框架_夜行审判.txt",
                "output_type": "text",
                "debug": {"chosen_output_source": "root.answerText"},
            },
        )

        project_id = int(asset["project_id"])
        assets = self.manager.list_user_assets(1)
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["asset_kind"], AUXILIARY_TOOL_ASSET_KIND)
        self.assertEqual(assets[0]["tool_label"], "15节拍剧本框架")
        self.assertEqual(assets[0]["final_preview"], "第一行\n第二行")
        self.assertEqual(self.manager.list_user_projects(1), [])
        self.assertIsNone(self.manager.latest_project_snapshot(user_id=1))

        public_snapshot = self.manager.get_project_snapshot(project_id, user_id=1, public_view=True) or {}
        artifacts = public_snapshot.get("artifacts") or {}
        self.assertEqual(public_snapshot["asset_kind"], AUXILIARY_TOOL_ASSET_KIND)
        self.assertEqual(artifacts.get("final_script"), "第一行\n第二行")
        self.assertEqual(artifacts.get("final_output_text"), "第一行\n第二行")

        self.manager.update_project_asset(
            project_id,
            user_id=1,
            changes={"visibility": "public"},
        )
        self.assertEqual(self.manager.list_public_assets(), [])
        self.assertIsNone(self.manager.get_public_asset(project_id))

    def test_update_auxiliary_asset_allows_editing_completed_content_without_flattening_lines(self) -> None:
        asset = self.manager.save_auxiliary_asset(
            user_id=1,
            tool_key="new_framework",
            request_payload={
                "story": "原始故事梗概",
                "project_title": "旧标题",
            },
            result={
                "title": "15节拍剧本框架",
                "text": "原始结果",
                "filename": "15节拍剧本框架_旧标题.txt",
                "output_type": "text",
                "debug": {"chosen_output_source": "root.answerText"},
            },
        )

        updated = self.manager.update_project_asset(
            int(asset["project_id"]),
            user_id=1,
            changes={
                "title": "自定义结果标题",
                "story_outline": "新的摘要内容",
                "final_script": "甲线\n乙线",
                "visibility": "private",
            },
        )

        self.assertEqual(updated["title"], "自定义结果标题")
        self.assertEqual(updated["artifacts"]["final_output_text"], "甲线\n乙线")
        private_snapshot = self.manager.get_project_snapshot(
            int(asset["project_id"]),
            user_id=1,
            public_view=False,
        ) or {}
        self.assertEqual((private_snapshot.get("artifacts") or {}).get("final_script"), "甲线\n乙线")
        self.assertEqual((private_snapshot.get("artifacts") or {}).get("final_output_text"), "甲线\n乙线")
        self.assertEqual((private_snapshot.get("input_payload") or {}).get("story_outline"), "新的摘要内容")


if __name__ == "__main__":
    unittest.main()
