from __future__ import annotations

import json
import unittest
from pathlib import Path

from workflow_code_skeleton.app.services.runtime_paths import (
    archive_runtime_file,
    load_runtime_manifest,
    render_runtime_entry_text,
    resolve_export_path,
    resolve_project_snapshot_path,
    resolve_runtime_file,
)
from workflow_code_skeleton.app.services.task_manager import TaskManager
from workflow_code_skeleton.tests.test_support import WorkspaceTempDir


class RuntimePathsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = WorkspaceTempDir(prefix="runtime-paths-")
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.runtime_data_dir = self.root / "runtime_data"
        self.runtime_archive_dir = self.root / "runtime_archive"
        self.projects_dir = self.runtime_data_dir / "projects"
        self.exports_dir = self.runtime_data_dir / "exports"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    def test_archive_runtime_file_creates_entry_and_manifest_for_exports(self) -> None:
        export_path = self.exports_dir / "长夜回潮_1.txt"
        export_path.write_text("剧本正文", encoding="utf-8")

        archived_path = archive_runtime_file(
            export_path,
            "exports",
            base_root=self.root,
            archive_dir=self.runtime_archive_dir,
            keep_entry=True,
            metadata={"project_id": 1, "kind": "export_artifact"},
        )

        self.assertTrue(archived_path.exists())
        self.assertTrue(export_path.exists())
        self.assertNotEqual(resolve_runtime_file(export_path, base_root=self.root), export_path)
        self.assertEqual(resolve_runtime_file(export_path, base_root=self.root), archived_path)
        self.assertEqual(
            resolve_export_path(
                1,
                exports_dir=self.exports_dir,
                base_root=self.root,
                archive_dir=self.runtime_archive_dir,
                preferred_suffix=".txt",
            ),
            archived_path,
        )
        manifest = load_runtime_manifest(archive_dir=self.runtime_archive_dir)
        self.assertIn("runtime_data/exports/长夜回潮_1.txt", manifest["entries"])

    def test_resolve_project_snapshot_path_falls_back_to_archived_manifest_entry(self) -> None:
        snapshot_path = self.projects_dir / "41.json"
        snapshot_path.write_text(
            json.dumps({"project_id": 41, "user_id": 1, "status": "completed"}, ensure_ascii=False),
            encoding="utf-8",
        )

        archived_path = archive_runtime_file(
            snapshot_path,
            "projects",
            base_root=self.root,
            archive_dir=self.runtime_archive_dir,
            metadata={"project_id": 41, "status": "completed", "kind": "project_snapshot_json"},
        )

        resolved = resolve_project_snapshot_path(
            41,
            projects_dir=self.projects_dir,
            base_root=self.root,
            archive_dir=self.runtime_archive_dir,
        )

        self.assertEqual(resolved, archived_path)

    def test_task_manager_can_read_and_clear_archived_snapshot(self) -> None:
        manager = TaskManager()
        manager.set_storage_root(self.runtime_data_dir, runtime_archive_dir=self.runtime_archive_dir)
        manager._tasks.clear()
        manager._projects.clear()
        manager._index = {"next_project_id": 2, "latest_project_id": None, "latest_project_by_user": {}}
        manager._save_index()

        snapshot = {
            "user_id": 1,
            "project_id": 52,
            "task_id": "task-52",
            "status": "completed",
            "title": "归档快照",
            "message": "已完成",
            "created_at": "2026-05-03T10:00:00+08:00",
            "updated_at": "2026-05-03T10:00:00+08:00",
            "workflow_spec_path": "spec.json",
            "input_payload": {"title": "归档快照", "story_outline": "测试"},
            "model_option": {},
            "artifacts": {"final_output_text": "第1集\n1-1 场景\n正文"},
            "debug_state": {"variables": {}, "node_outputs": {}},
            "completion_confirmed": True,
            "awaiting_user_confirmation": False,
            "cache_retained": False,
        }
        snapshot_path = manager._project_path(52)
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        archive_runtime_file(
            snapshot_path,
            "projects",
            base_root=self.root,
            archive_dir=self.runtime_archive_dir,
            metadata={"project_id": 52, "status": "completed", "kind": "project_snapshot_json"},
        )

        loaded = manager.get_project_snapshot(52, user_id=1, public_view=False)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["title"], "归档快照")
        self.assertEqual(len(manager.list_user_projects(1)), 1)

        manager.clear_project(52, user_id=1)

        self.assertIsNone(manager.get_project_snapshot(52, user_id=1, public_view=False))
        manifest = load_runtime_manifest(archive_dir=self.runtime_archive_dir)
        self.assertNotIn("runtime_data/projects/52.json", manifest["entries"])

    def test_resolve_runtime_file_follows_entry_to_archived_large_doc_index(self) -> None:
        archived_dir = self.runtime_archive_dir / "large_docs" / "星渊铁壁：终焉战歌_47"
        archived_dir.mkdir(parents=True, exist_ok=True)
        archived_index = archived_dir / "index.md"
        archived_index.write_text("# 拆分索引\n", encoding="utf-8")

        entry_path = self.exports_dir / "星渊铁壁：终焉战歌_47.txt"
        entry_path.write_text(
            render_runtime_entry_text(
                original_path="runtime_data/exports/星渊铁壁：终焉战歌_47.txt",
                archived_path="runtime_archive/large_docs/星渊铁壁：终焉战歌_47",
                category="large_docs",
                note="拆分后的导出正文请改读 index.md",
            ),
            encoding="utf-8",
        )

        resolved = resolve_runtime_file(
            entry_path,
            base_root=self.root,
            archive_dir=self.runtime_archive_dir,
        )

        self.assertEqual(resolved.resolve(), archived_index.resolve())


if __name__ == "__main__":
    unittest.main()
