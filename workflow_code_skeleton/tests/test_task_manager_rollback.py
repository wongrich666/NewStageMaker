from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from workflow_code_skeleton.app.services import task_manager as task_manager_module
from workflow_code_skeleton.app.services.fastgpt_contracts import (
    ALL_DIALOGUES,
    ALL_HOOKS,
    ALL_SCRIPT,
    APPEARANCE_CONTINUITY_MEMORY,
    BATCH_START_EPISODE,
    LAST_SUMMARY,
)
from workflow_code_skeleton.app.services.task_manager import TaskManager


class _FakeThread:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.started = False

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return False

    def join(self, timeout: float | None = None) -> None:
        del timeout


def _iso_now() -> str:
    return "2026-04-28T12:00:00+08:00"


def _episode_object(start_episode: int, end_episode: int, label: str) -> dict[str, object]:
    return {
        "episodes": [
            {
                "episode": episode,
                "label": f"{label}-{episode}",
            }
            for episode in range(start_episode, end_episode + 1)
        ]
    }


def _script_text(start_episode: int, end_episode: int) -> str:
    return "\n\n".join(
        f"第{episode}集\n{episode}-1 场景\n正文 {episode}"
        for episode in range(start_episode, end_episode + 1)
    )


def _base_snapshot() -> dict[str, object]:
    script_1_5 = _script_text(1, 5)
    script_6_10 = _script_text(6, 10)
    return {
        "user_id": 1,
        "project_id": 1,
        "task_id": "task-001",
        "status": "failed",
        "title": "测试项目",
        "message": "已失败，可回退",
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
        "finished_at": _iso_now(),
        "workflow_spec_path": "spec.json",
        "input_payload": {
            "title": "测试项目",
            "story_outline": "测试大纲",
            "total_episodes": 10,
        },
        "model_option": {},
        "artifacts": {
            "script_title_content": "测试项目",
            "story_outline": "测试大纲",
            "final_script": _script_text(1, 10),
            "final_output_text": _script_text(1, 10),
        },
        "total_episodes": 10,
        "progress_percent": 100,
        "generated_episodes": 10,
        "current_stage": "script",
        "current_stage_label": "剧本正文",
        "cache_retained": True,
        "awaiting_user_confirmation": False,
        "completion_confirmed": False,
        "debug_state": {
            "variables": {
                ALL_HOOKS: _episode_object(1, 10, "hook"),
                ALL_DIALOGUES: _episode_object(1, 10, "dialogue"),
                ALL_SCRIPT: _script_text(1, 10),
                LAST_SUMMARY: "summary-6",
                APPEARANCE_CONTINUITY_MEMORY: {"memory": "appearance-6"},
                task_manager_module.LOCAL_SCRIPT_BATCHES: {
                    "1": script_1_5,
                    "6": script_6_10,
                },
                task_manager_module.LOCAL_SCRIPT_EPISODES: {},
                task_manager_module.LOCAL_SUMMARY_BY_BATCH: {
                    "1": "summary-1",
                    "6": "summary-6",
                },
                task_manager_module.LOCAL_APPEARANCE_MEMORY_BY_BATCH: {
                    "1": {"memory": "appearance-1"},
                    "6": {"memory": "appearance-6"},
                },
                task_manager_module.LOCAL_COMPLETED_BATCHES: 2,
                task_manager_module.LOCAL_CURRENT_BATCH_INDEX: 1,
                task_manager_module.LOCAL_CURRENT_BATCH_STAGE: "script",
                BATCH_START_EPISODE: 6,
            },
            "node_outputs": {},
        },
    }


class TaskManagerRollbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.manager = TaskManager()
        base_dir = Path(self.temp_dir.name)
        self.manager.base_dir = base_dir
        self.manager.projects_dir = base_dir / "projects"
        self.manager.exports_dir = base_dir / "exports"
        self.manager.index_path = base_dir / "index.json"
        self.manager.projects_dir.mkdir(parents=True, exist_ok=True)
        self.manager.exports_dir.mkdir(parents=True, exist_ok=True)
        self.manager._tasks.clear()
        self.manager._projects.clear()
        self.manager._index = {
            "next_project_id": 2,
            "latest_project_id": None,
            "latest_project_by_user": {},
        }
        self.manager._save_index()

    def _persist_snapshot(self, snapshot: dict[str, object]) -> None:
        project_id = int(snapshot["project_id"])
        self.manager._project_path(project_id).write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _raw_project_snapshot(self, project_id: int = 1) -> dict[str, object]:
        return self.manager.get_project_snapshot(project_id, user_id=1, public_view=False) or {}

    def test_public_snapshot_exposes_stage_range_options_and_dependencies(self) -> None:
        snapshot = _base_snapshot()
        public = self.manager._public_snapshot(snapshot)

        self.assertEqual(public["rollback_stage_dependencies"]["hooks"], ["hooks", "dialogues", "script"])
        self.assertEqual(public["rollback_stage_dependencies"]["dialogues"], ["dialogues", "script"])
        self.assertEqual(public["rollback_stage_dependencies"]["script"], ["script"])
        self.assertEqual(
            [item["value"] for item in public["rollback_stage_start_options"]["hooks"]],
            [1, 6],
        )
        self.assertEqual(
            [item["value"] for item in public["rollback_stage_start_options"]["dialogues"]],
            [1, 6],
        )
        self.assertEqual(
            [item["value"] for item in public["rollback_stage_start_options"]["script"]],
            [1, 6],
        )
        self.assertEqual(
            [item["value"] for item in public["rollback_script_start_options"]],
            [1, 6],
        )

    def test_hooks_rollback_requires_valid_start_episode(self) -> None:
        snapshot = _base_snapshot()
        self._persist_snapshot(snapshot)

        with patch.object(task_manager_module.threading, "Thread", _FakeThread):
            with self.assertRaisesRegex(ValueError, "请选择有效的开头冲突钩子重写起始集数"):
                self.manager.rollback_project_to_stage(1, user_id=1, stage_key="hooks", start_episode=99)

    def test_dialogues_rollback_requires_valid_start_episode(self) -> None:
        snapshot = _base_snapshot()
        self._persist_snapshot(snapshot)

        with patch.object(task_manager_module.threading, "Thread", _FakeThread):
            with self.assertRaisesRegex(ValueError, "请选择有效的角色对白重写起始集数"):
                self.manager.rollback_project_to_stage(1, user_id=1, stage_key="dialogues", start_episode=99)

    def test_hooks_rollback_clears_dialogues_and_script_from_selected_batch(self) -> None:
        snapshot = _base_snapshot()
        self._persist_snapshot(snapshot)

        with patch.object(task_manager_module.threading, "Thread", _FakeThread):
            public = self.manager.rollback_project_to_stage(
                1,
                user_id=1,
                stage_key="hooks",
                start_episode=6,
            )

        self.assertEqual(public["current_stage"], "hooks")
        raw = self._raw_project_snapshot()
        variables = raw["debug_state"]["variables"]
        self.assertEqual(
            [item["episode"] for item in variables[ALL_HOOKS]["episodes"]],
            [1, 2, 3, 4, 5],
        )
        self.assertNotIn(ALL_DIALOGUES, variables)
        self.assertNotIn(ALL_SCRIPT, variables)
        self.assertEqual(variables[task_manager_module.LOCAL_CURRENT_BATCH_STAGE], "hook")
        self.assertEqual(variables[BATCH_START_EPISODE], 6)
        self.assertEqual(raw["rollback_start_episode"], 6)

    def test_dialogues_rollback_preserves_hooks_and_clears_dialogues_and_script(self) -> None:
        snapshot = _base_snapshot()
        self._persist_snapshot(snapshot)

        with patch.object(task_manager_module.threading, "Thread", _FakeThread):
            public = self.manager.rollback_project_to_stage(
                1,
                user_id=1,
                stage_key="dialogues",
                start_episode=6,
            )

        self.assertEqual(public["current_stage"], "dialogues")
        raw = self._raw_project_snapshot()
        variables = raw["debug_state"]["variables"]
        self.assertEqual(
            [item["episode"] for item in variables[ALL_HOOKS]["episodes"]],
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        )
        self.assertEqual(
            [item["episode"] for item in variables[ALL_DIALOGUES]["episodes"]],
            [1, 2, 3, 4, 5],
        )
        self.assertNotIn(ALL_SCRIPT, variables)
        self.assertEqual(variables[task_manager_module.LOCAL_CURRENT_BATCH_STAGE], "dialogue")
        self.assertEqual(variables[BATCH_START_EPISODE], 6)

    def test_script_rollback_only_clears_script_and_preserves_previous_memory(self) -> None:
        snapshot = _base_snapshot()
        self._persist_snapshot(snapshot)

        with patch.object(task_manager_module.threading, "Thread", _FakeThread):
            public = self.manager.rollback_project_to_stage(
                1,
                user_id=1,
                stage_key="script",
                start_episode=6,
            )

        self.assertEqual(public["current_stage"], "script")
        raw = self._raw_project_snapshot()
        variables = raw["debug_state"]["variables"]
        self.assertIn(ALL_HOOKS, variables)
        self.assertIn(ALL_DIALOGUES, variables)
        self.assertEqual(variables[ALL_SCRIPT], _script_text(1, 5))
        self.assertEqual(variables[LAST_SUMMARY], "summary-1")
        self.assertEqual(variables[APPEARANCE_CONTINUITY_MEMORY], {"memory": "appearance-1"})
        self.assertEqual(variables[task_manager_module.LOCAL_CURRENT_BATCH_STAGE], "script")
        self.assertEqual(variables[BATCH_START_EPISODE], 6)


if __name__ == "__main__":
    unittest.main()
