from __future__ import annotations

import unittest
from pathlib import Path

from docx import Document

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

    def test_character_reskin_asset_uses_script_title_and_appears_in_project_list(self) -> None:
        asset = self.manager.save_auxiliary_asset(
            user_id=1,
            tool_key="character_reskin",
            request_payload={
                "title": "镜中雪",
                "source_outline": "原故事大纲",
                "source_characters": "旧人物小传",
                "source_script": "原剧本正文",
                "total_episodes": 6,
            },
            result={
                "title": "只换人设",
                "text": "最终正文",
                "filename": "只换人设_镜中雪.txt",
                "output_type": "text",
                "character_profile": "人物小传纯文本",
                "character_profile_json": {
                    "plot_causality_map": {
                        "cause": "新人设驱动旧剧情结果",
                    },
                    "character_setting": {
                        "character_design_principle": "人物创作原则内容",
                        "core_relation_logic": "核心关系逻辑内容",
                        "characters": [
                            {
                                "character_name": "林雪",
                                "core_motivation": "查清真相",
                            }
                        ],
                    },
                },
                "script_batches": ["第1集：开端\n正文一", "第2集：推进\n正文二"],
                "debug": {},
            },
        )

        self.assertEqual(asset["title"], "镜中雪")
        self.assertEqual(asset["asset_kind"], AUXILIARY_TOOL_ASSET_KIND)
        self.assertEqual(asset["asset_type"], "character_reskin")

        projects = self.manager.list_user_projects(1)
        self.assertEqual([item["project_id"] for item in projects], [asset["project_id"]])
        self.assertEqual(projects[0]["tool_key"], "character_reskin")
        self.assertEqual(projects[0]["title"], "镜中雪")

        public_snapshot = self.manager.get_project_snapshot(int(asset["project_id"]), user_id=1, public_view=True) or {}
        self.assertEqual(public_snapshot["tool_request_payload"]["source_script"], "原剧本正文")
        self.assertEqual((public_snapshot.get("artifacts") or {}).get("final_output_text"), "最终正文")

        docx_path = self.manager.save_final_script(int(asset["project_id"]), user_id=1)
        text = "\n".join(
            paragraph.text
            for paragraph in Document(str(docx_path)).paragraphs
            if paragraph.text.strip()
        )
        self.assertIn("剧本标题", text)
        self.assertIn("镜中雪", text)
        self.assertIn("故事大纲", text)
        self.assertIn("剧情因果脉络", text)
        self.assertIn("人物创作原则", text)
        self.assertIn("核心关系逻辑", text)
        self.assertIn("人物详情", text)
        self.assertIn("剧本正文", text)
        self.assertIn("正文一", text)
        self.assertIn("正文二", text)


if __name__ == "__main__":
    unittest.main()
