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


def _base_snapshot(total_episodes: int = 10) -> dict[str, object]:
    batch_starts = list(range(1, total_episodes + 1, 5))
    script_batches = {
        str(start_episode): _script_text(start_episode, min(total_episodes, start_episode + 4))
        for start_episode in batch_starts
    }
    summary_by_batch = {
        str(start_episode): f"summary-{start_episode}"
        for start_episode in batch_starts
    }
    appearance_by_batch = {
        str(start_episode): {"memory": f"appearance-{start_episode}"}
        for start_episode in batch_starts
    }
    last_batch_start = batch_starts[-1]
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
            "total_episodes": total_episodes,
        },
        "model_option": {},
        "artifacts": {
            "script_title_content": "测试项目",
            "story_outline": "测试大纲",
            task_manager_module.PARTIAL_SCRIPT_ARTIFACT: _script_text(1, total_episodes),
            task_manager_module.SCRIPT_BATCH_PREVIEW_ARTIFACT: _script_text(
                last_batch_start,
                min(total_episodes, last_batch_start + 4),
            ),
            task_manager_module.SCRIPT_BATCH_RANGE_ARTIFACT: f"{last_batch_start}-{min(total_episodes, last_batch_start + 4)}",
            task_manager_module.SCRIPT_BATCHES_DISPLAY_ARTIFACT: [
                {
                    "start_episode": start_episode,
                    "end_episode": min(total_episodes, start_episode + 4),
                    "content": _script_text(start_episode, min(total_episodes, start_episode + 4)),
                }
                for start_episode in batch_starts
            ],
            task_manager_module.PARTIAL_SCRIPT_EPISODES_ARTIFACT: list(range(1, total_episodes + 1)),
            "final_script": _script_text(1, total_episodes),
            "final_output_text": _script_text(1, total_episodes),
        },
        "total_episodes": total_episodes,
        "progress_percent": 100,
        "generated_episodes": total_episodes,
        "current_stage": "script",
        "current_stage_label": "剧本正文",
        "cache_retained": True,
        "awaiting_user_confirmation": False,
        "completion_confirmed": False,
        "debug_state": {
            "variables": {
                ALL_HOOKS: _episode_object(1, total_episodes, "hook"),
                ALL_DIALOGUES: _episode_object(1, total_episodes, "dialogue"),
                ALL_SCRIPT: _script_text(1, total_episodes),
                LAST_SUMMARY: f"summary-{last_batch_start}",
                APPEARANCE_CONTINUITY_MEMORY: {"memory": f"appearance-{last_batch_start}"},
                task_manager_module.LOCAL_SCRIPT_BATCHES: script_batches,
                task_manager_module.LOCAL_SCRIPT_EPISODES: {},
                task_manager_module.LOCAL_SUMMARY_BY_BATCH: summary_by_batch,
                task_manager_module.LOCAL_APPEARANCE_MEMORY_BY_BATCH: appearance_by_batch,
                task_manager_module.LOCAL_COMPLETED_BATCHES: len(batch_starts),
                task_manager_module.LOCAL_CURRENT_BATCH_INDEX: max(0, len(batch_starts) - 1),
                task_manager_module.LOCAL_CURRENT_BATCH_STAGE: "script",
                BATCH_START_EPISODE: last_batch_start,
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

    def test_public_snapshot_uses_fixed_five_episode_batches_for_rewrite_start_options(self) -> None:
        snapshot = _base_snapshot(15)
        snapshot["debug_state"]["variables"][task_manager_module.LOCAL_SCRIPT_EPISODES] = {
            str(episode): f"正文 {episode}"
            for episode in range(1, 16)
        }
        public = self.manager._public_snapshot(snapshot)

        self.assertEqual(
            [item["value"] for item in public["rollback_stage_start_options"]["hooks"]],
            [1, 6, 11],
        )
        self.assertEqual(
            [item["value"] for item in public["rollback_stage_start_options"]["dialogues"]],
            [1, 6, 11],
        )
        self.assertEqual(
            [item["value"] for item in public["rollback_stage_start_options"]["script"]],
            [1, 6, 11],
        )
        self.assertTrue(
            all("第 2-" not in item["label"] and "第 3-" not in item["label"] for item in public["rollback_stage_start_options"]["script"])
        )

    def test_public_snapshot_uses_actual_tail_batch_for_partial_final_window(self) -> None:
        snapshot = _base_snapshot(12)
        public = self.manager._public_snapshot(snapshot)
        script_options = public["rollback_stage_start_options"]["script"]

        self.assertEqual([item["value"] for item in script_options], [1, 6, 11])
        self.assertEqual(script_options[-1]["start_episode"], 11)
        self.assertEqual(script_options[-1]["end_episode"], 12)
        self.assertIn("第 11-12 集", script_options[-1]["label"])
        self.assertNotIn("11-15", script_options[-1]["label"])

    def test_hooks_rollback_requires_valid_start_episode(self) -> None:
        snapshot = _base_snapshot()
        self._persist_snapshot(snapshot)

        with patch.object(task_manager_module.threading, "Thread", _FakeThread):
            with self.assertRaisesRegex(ValueError, "回退重写只能从每个五集批次的起点开始"):
                self.manager.rollback_project_to_stage(1, user_id=1, stage_key="hooks", start_episode=99)

    def test_dialogues_rollback_requires_valid_start_episode(self) -> None:
        snapshot = _base_snapshot()
        self._persist_snapshot(snapshot)

        with patch.object(task_manager_module.threading, "Thread", _FakeThread):
            with self.assertRaisesRegex(ValueError, "回退重写只能从每个五集批次的起点开始"):
                self.manager.rollback_project_to_stage(1, user_id=1, stage_key="dialogues", start_episode=99)

    def test_batched_rollback_rejects_sliding_window_start_episodes(self) -> None:
        snapshot = _base_snapshot(15)
        self._persist_snapshot(snapshot)

        with patch.object(task_manager_module.threading, "Thread", _FakeThread):
            for stage_key in ("hooks", "dialogues", "script"):
                for invalid_start in (2, 3, 4, 5, 7, 8, 9, 10):
                    with self.subTest(stage_key=stage_key, start_episode=invalid_start):
                        with self.assertRaisesRegex(ValueError, "回退重写只能从每个五集批次的起点开始"):
                            self.manager.rollback_project_to_stage(
                                1,
                                user_id=1,
                                stage_key=stage_key,
                                start_episode=invalid_start,
                            )

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
        self.assertEqual(raw["artifacts"][task_manager_module.PARTIAL_SCRIPT_ARTIFACT], _script_text(1, 5))
        self.assertEqual(raw["artifacts"][task_manager_module.SCRIPT_BATCH_RANGE_ARTIFACT], "1-5")
        self.assertEqual(len(raw["artifacts"][task_manager_module.SCRIPT_BATCHES_DISPLAY_ARTIFACT]), 1)

    def test_hooks_rollback_on_15_episodes_clears_downstream_caches_after_episode_6(self) -> None:
        snapshot = _base_snapshot(15)
        self._persist_snapshot(snapshot)

        with patch.object(task_manager_module.threading, "Thread", _FakeThread):
            self.manager.rollback_project_to_stage(
                1,
                user_id=1,
                stage_key="hooks",
                start_episode=6,
            )

        raw = self._raw_project_snapshot()
        variables = raw["debug_state"]["variables"]
        self.assertEqual(
            [item["episode"] for item in variables[ALL_HOOKS]["episodes"]],
            [1, 2, 3, 4, 5],
        )
        self.assertNotIn(ALL_DIALOGUES, variables)
        self.assertNotIn(ALL_SCRIPT, variables)
        self.assertEqual(variables[task_manager_module.LOCAL_SUMMARY_BY_BATCH], {"1": "summary-1"})
        self.assertEqual(
            variables[task_manager_module.LOCAL_APPEARANCE_MEMORY_BY_BATCH],
            {"1": {"memory": "appearance-1"}},
        )
        self.assertNotIn(task_manager_module.PARTIAL_SCRIPT_ARTIFACT, raw["artifacts"])
        self.assertNotIn(task_manager_module.SCRIPT_BATCHES_DISPLAY_ARTIFACT, raw["artifacts"])

    def test_dialogues_rollback_on_15_episodes_preserves_all_hooks_and_trims_downstream(self) -> None:
        snapshot = _base_snapshot(15)
        self._persist_snapshot(snapshot)

        with patch.object(task_manager_module.threading, "Thread", _FakeThread):
            self.manager.rollback_project_to_stage(
                1,
                user_id=1,
                stage_key="dialogues",
                start_episode=6,
            )

        raw = self._raw_project_snapshot()
        variables = raw["debug_state"]["variables"]
        self.assertEqual(
            [item["episode"] for item in variables[ALL_HOOKS]["episodes"]],
            list(range(1, 16)),
        )
        self.assertEqual(
            [item["episode"] for item in variables[ALL_DIALOGUES]["episodes"]],
            [1, 2, 3, 4, 5],
        )
        self.assertNotIn(ALL_SCRIPT, variables)
        self.assertEqual(variables[task_manager_module.LOCAL_SUMMARY_BY_BATCH], {"1": "summary-1"})
        self.assertEqual(
            variables[task_manager_module.LOCAL_APPEARANCE_MEMORY_BY_BATCH],
            {"1": {"memory": "appearance-1"}},
        )

    def test_script_rollback_on_15_episodes_only_trims_script_and_memory(self) -> None:
        snapshot = _base_snapshot(15)
        self._persist_snapshot(snapshot)

        with patch.object(task_manager_module.threading, "Thread", _FakeThread):
            self.manager.rollback_project_to_stage(
                1,
                user_id=1,
                stage_key="script",
                start_episode=6,
            )

        raw = self._raw_project_snapshot()
        variables = raw["debug_state"]["variables"]
        self.assertEqual(
            [item["episode"] for item in variables[ALL_HOOKS]["episodes"]],
            list(range(1, 16)),
        )
        self.assertEqual(
            [item["episode"] for item in variables[ALL_DIALOGUES]["episodes"]],
            list(range(1, 16)),
        )
        self.assertEqual(variables[ALL_SCRIPT], _script_text(1, 5))
        self.assertEqual(variables[LAST_SUMMARY], "summary-1")
        self.assertEqual(variables[APPEARANCE_CONTINUITY_MEMORY], {"memory": "appearance-1"})
        self.assertEqual(variables[task_manager_module.LOCAL_SUMMARY_BY_BATCH], {"1": "summary-1"})
        self.assertEqual(
            variables[task_manager_module.LOCAL_APPEARANCE_MEMORY_BY_BATCH],
            {"1": {"memory": "appearance-1"}},
        )

    def test_script_rollback_on_partial_tail_batch_only_trims_from_last_valid_batch(self) -> None:
        snapshot = _base_snapshot(12)
        self._persist_snapshot(snapshot)

        with patch.object(task_manager_module.threading, "Thread", _FakeThread):
            public = self.manager.rollback_project_to_stage(
                1,
                user_id=1,
                stage_key="script",
                start_episode=11,
            )

        self.assertEqual(public["current_stage"], "script")
        raw = self._raw_project_snapshot()
        variables = raw["debug_state"]["variables"]
        self.assertEqual(variables[BATCH_START_EPISODE], 11)
        self.assertEqual(raw["current_batch"], "11-12")
        self.assertEqual(
            raw["artifacts"][task_manager_module.SCRIPT_BATCH_RANGE_ARTIFACT],
            "6-10",
        )
        self.assertEqual(
            [item["start_episode"] for item in raw["artifacts"][task_manager_module.SCRIPT_BATCHES_DISPLAY_ARTIFACT]],
            [1, 6],
        )


if __name__ == "__main__":
    unittest.main()
