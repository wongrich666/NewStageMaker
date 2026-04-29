from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from workflow_code_skeleton.app.services.fastgpt_contracts import (
    CHARACTERS,
    EPISODE_PLAN,
    SCENES,
    STORY_OUTLINE,
    USER_CHARACTERS,
    USER_SCENES,
    WORLDVIEW,
)
from workflow_code_skeleton.app.services.task_manager import (
    EPISODE_PLAN_DISPLAY_ARTIFACT,
    LOCAL_SCRIPT_BATCHES,
    LOCAL_SCRIPT_EPISODES,
    PARTIAL_SCRIPT_ARTIFACT,
    PARTIAL_SCRIPT_EPISODES_ARTIFACT,
    SCRIPT_BATCHES_DISPLAY_ARTIFACT,
    SCRIPT_BATCH_PREVIEW_ARTIFACT,
    SCRIPT_BATCH_RANGE_ARTIFACT,
    TaskManager,
    TaskRecord,
    WorkflowRuntime,
)
from workflow_code_skeleton.app.models.inputs import WorkflowInput
from workflow_code_skeleton.app.models.state import WorkflowState
from workflow_code_skeleton.app.workflow_ids import (
    CHARACTER_NATURAL_LANGUAGE_VAR,
    CHARACTER_VAR,
    SCENE_NATURAL_LANGUAGE_VAR,
    SCENE_VAR,
)


def _iso_now() -> str:
    return "2026-04-28T12:00:00+08:00"


def _structured_story_outline() -> dict[str, object]:
    return {
        "opening": "故事开场",
        "theme": "身份与选择",
    }


def _structured_worldview() -> dict[str, object]:
    return {
        "worldview_summary": "资源紧张的近未来都市。",
        "social_rules": ["效率优先", "资源决定话语权"],
    }


def _structured_episode_plan() -> dict[str, object]:
    return {
        "episodes": [
            {"episode": 1, "title": "危机来临", "content": "主角被迫做出选择。"},
            {"episode": 2, "title": "代价显现", "content": "关系开始失衡。"},
        ]
    }


def _structured_characters() -> dict[str, object]:
    return {
        "character_setting": {
            "characters": [
                {"character_name": "林夏", "story_role": "主角", "core_motivation": "保住团队"},
                {"character_name": "周衡", "story_role": "对手", "core_motivation": "夺取项目"},
                {"character_name": "顾遥", "story_role": "盟友", "core_motivation": "查清真相"},
            ]
        }
    }


def _snapshot(*, current_stage: str = "framework", framework_natural: str = "框架自然语言版", worldview_natural: str = "世界观自然语言版") -> dict[str, object]:
    story_outline = _structured_story_outline()
    worldview = _structured_worldview()
    episode_plan = _structured_episode_plan()
    return {
        "user_id": 1,
        "project_id": 1,
        "task_id": "task-001",
        "status": "running",
        "title": "测试项目",
        "message": "",
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
        "finished_at": None,
        "workflow_spec_path": "spec.json",
        "input_payload": {
            "title": "测试项目",
            "story_outline": "用户输入梗概",
            "total_episodes": 10,
        },
        "model_option": {},
        "artifacts": {
            "script_title_content": "测试项目",
            "framework_natural_language": framework_natural,
            "story_outline": story_outline,
            "character_bios": [
                {"name": "林夏", "goal": "保住工作并守住家庭关系"},
            ],
            "core_scene_input": {
                "core_scene": "深夜会议室对峙",
                "mood": "高压、克制",
            },
            "episode_plan": episode_plan,
            "worldview": worldview,
            "worldview_natural_language": worldview_natural,
            "character_summary": "人物关系已经整理成自然语言说明。",
            "core_scene_summary": "核心场景已经整理成自然语言说明。",
        },
        "total_episodes": 10,
        "progress_percent": 40,
        "generated_episodes": 0,
        "current_stage": current_stage,
        "current_stage_label": "测试阶段",
        "cache_retained": True,
        "awaiting_user_confirmation": False,
        "completion_confirmed": False,
        "debug_state": {
            "variables": {
                STORY_OUTLINE: story_outline,
                USER_CHARACTERS: [{"name": "林夏"}],
                USER_SCENES: [{"scene_name": "深夜会议室"}],
                EPISODE_PLAN: episode_plan,
                WORLDVIEW: worldview,
            },
            "node_outputs": {},
        },
    }


class TaskManagerPublicSnapshotTests(unittest.TestCase):
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

    def _persist_snapshot(self, snapshot: dict[str, object]) -> None:
        project_id = int(snapshot["project_id"])
        self.manager._project_path(project_id).write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_framework_public_snapshot_prefers_natural_language_and_hides_structured_objects(self) -> None:
        public = self.manager._public_snapshot(_snapshot(current_stage="framework"))

        self.assertEqual(public["display_stage_key"], "framework")
        self.assertEqual(public["display_stage_output"], "框架自然语言版")
        self.assertNotIn("[object Object]", public["display_stage_output"])
        self.assertIn("framework_natural_language", public["artifacts"])
        self.assertNotIn("story_outline", public["artifacts"])
        self.assertNotIn("character_bios", public["artifacts"])
        self.assertNotIn("core_scene_input", public["artifacts"])
        self.assertNotIn("episode_plan", public["artifacts"])

    def test_worldview_public_snapshot_prefers_natural_language_and_hides_raw_worldview(self) -> None:
        public = self.manager._public_snapshot(_snapshot(current_stage="worldview"))

        self.assertEqual(public["display_stage_key"], "worldview")
        self.assertEqual(public["display_stage_output"], "世界观自然语言版")
        self.assertNotIn("worldview_summary", public["display_stage_output"])
        self.assertNotIn("worldview", public["artifacts"])
        self.assertEqual(public["artifacts"]["worldview_natural_language"], "世界观自然语言版")

    def test_private_snapshot_keeps_structured_framework_and_worldview_for_debug(self) -> None:
        snapshot = _snapshot(current_stage="worldview")
        self._persist_snapshot(snapshot)

        public = self.manager.get_project_snapshot(1, user_id=1, public_view=True) or {}
        private = self.manager.get_project_snapshot(1, user_id=1, public_view=False) or {}

        self.assertNotIn("story_outline", public.get("artifacts") or {})
        self.assertNotIn("worldview", public.get("artifacts") or {})
        self.assertIsInstance((private.get("artifacts") or {}).get("story_outline"), dict)
        self.assertIsInstance((private.get("artifacts") or {}).get("worldview"), dict)
        self.assertEqual(
            ((private.get("debug_state") or {}).get("variables") or {}).get(STORY_OUTLINE),
            _structured_story_outline(),
        )
        self.assertEqual(
            ((private.get("debug_state") or {}).get("variables") or {}).get(WORLDVIEW),
            _structured_worldview(),
        )

    def test_framework_without_natural_language_does_not_pre_render_episode_plan_as_stage_output(self) -> None:
        public = self.manager._public_snapshot(
            _snapshot(current_stage="framework", framework_natural="", worldview_natural="世界观自然语言版")
        )

        self.assertEqual(public["display_stage_key"], "")
        self.assertEqual(public["display_stage_output"], "")
        self.assertIn("第1集《危机来临》", public["artifacts"][EPISODE_PLAN_DISPLAY_ARTIFACT])
        self.assertNotIn("[object Object]", public["artifacts"][EPISODE_PLAN_DISPLAY_ARTIFACT])

    def test_worldview_without_natural_language_does_not_show_placeholder_or_raw_json(self) -> None:
        public = self.manager._public_snapshot(
            _snapshot(current_stage="worldview", framework_natural="框架自然语言版", worldview_natural="")
        )

        self.assertEqual(public["display_stage_output"], "框架自然语言版")
        self.assertNotIn("worldview_natural_language", public["artifacts"])
        self.assertNotIn("worldview_summary", public["display_stage_output"])

    def test_new_running_snapshot_only_shows_runtime_message_before_first_stage_output(self) -> None:
        snapshot = _snapshot(current_stage="framework", framework_natural="", worldview_natural="")
        snapshot["artifacts"] = {}
        snapshot["debug_state"] = {"variables": {}, "node_outputs": {}}
        snapshot["current_stage_label"] = "剧本框架生成"

        public = self.manager._public_snapshot(snapshot)

        self.assertEqual(public["display_stage_key"], "")
        self.assertEqual(public["display_stage_output"], "")
        self.assertEqual(public["message"], "正在生成剧本框架")
        self.assertEqual(public["artifacts"], {})

    def test_placeholder_stage_texts_are_not_exposed_in_public_artifacts(self) -> None:
        snapshot = _snapshot(current_stage="characters")
        snapshot["artifacts"]["character_summary"] = "人物设定自然语言说明暂未生成。"
        snapshot["artifacts"]["scene_natural_language"] = "核心场景自然语言说明暂未生成。"

        public = self.manager._public_snapshot(snapshot)

        self.assertNotIn("character_summary", public["artifacts"])
        self.assertNotIn("scene_natural_language", public["artifacts"])
        self.assertNotEqual(public["display_stage_output"], "人物设定自然语言说明暂未生成。")

    def test_running_public_snapshot_falls_back_to_runtime_stage_message(self) -> None:
        snapshot = _snapshot(current_stage="hook_review")
        snapshot["current_stage_label"] = "开头冲突钩子审核"
        snapshot["current_batch"] = "1-5"
        public = self.manager._public_snapshot(snapshot)

        self.assertEqual(public["current_batch"], "1-5")
        self.assertEqual(public["message"], "正在审核开头冲突钩子：第 1-5 集")

    def test_runtime_sync_keeps_character_and_scene_natural_language_private(self) -> None:
        record = TaskRecord(
            user_id=1,
            project_id=1,
            task_id="task-runtime",
            workflow_spec_path="spec.json",
            input_payload={"title": "测试项目"},
            model_option=None,
            snapshot=_snapshot(current_stage="characters"),
        )
        runtime = WorkflowRuntime(manager=self.manager, record=record, spec=None)
        state = WorkflowState(
            WorkflowInput(
                title="测试项目",
                episode_word_count=1200,
                total_episodes=10,
                user_expectation="需求",
                character_count=3,
                character_appearance_requirements="",
                character_alias_naming_rules="",
                outfit_switch_rules="",
                story_outline="",
                core_scene_input="",
                character_bios="",
                episode_plan="",
            )
        )
        state.set_var(CHARACTERS, json.dumps({"character_setting": {"characters": [{"character_name": "林夏"}]}}, ensure_ascii=False))
        state.set_var(CHARACTER_VAR, state.get_var(CHARACTERS))
        state.set_var(CHARACTER_NATURAL_LANGUAGE_VAR, "人物小传自然语言版")
        state.set_var(SCENES, json.dumps({"scene_setting": {"scenes": [{"scene_name": "旧码头"}]}}, ensure_ascii=False))
        state.set_var(SCENE_VAR, state.get_var(SCENES))
        state.set_var(SCENE_NATURAL_LANGUAGE_VAR, "核心场景自然语言版")

        runtime.sync_from_state(state)
        snapshot = record.clone_snapshot()
        public = self.manager._public_snapshot(snapshot)

        self.assertEqual(snapshot["artifacts"]["character_natural_language"], "人物小传自然语言版")
        self.assertEqual(snapshot["artifacts"]["scene_natural_language"], "核心场景自然语言版")
        self.assertEqual(snapshot["artifacts"]["characters"], state.get_var(CHARACTERS))
        self.assertEqual(snapshot["artifacts"]["scene_json"], state.get_var(SCENES))
        self.assertEqual(public["display_stage_output"], "")
        self.assertNotIn("character_natural_language", public["artifacts"])
        self.assertNotIn("scene_natural_language", public["artifacts"])
        self.assertNotIn("characters", public["artifacts"])
        self.assertNotIn("scene_json", public["artifacts"])

    def test_character_public_snapshot_does_not_promote_character_stage_for_public_view(self) -> None:
        snapshot = _snapshot(current_stage="characters")
        snapshot["artifacts"]["character_natural_language"] = "【主角】林夏\n人物定位：项目负责人。"
        snapshot["artifacts"]["character_summary"] = snapshot["artifacts"]["character_natural_language"]
        snapshot["debug_state"]["variables"][CHARACTERS] = _structured_characters()

        public = self.manager._public_snapshot(snapshot)

        self.assertEqual(public["display_stage_key"], "worldview")
        self.assertEqual(public["display_stage_output"], "世界观自然语言版")
        self.assertNotIn("character_natural_language", public["artifacts"])
        self.assertNotIn("character_summary", public["artifacts"])

    def test_running_public_snapshot_exposes_approved_partial_script_batches_before_final(self) -> None:
        snapshot = _snapshot(current_stage="script")
        snapshot["status"] = "running"
        snapshot["current_stage_label"] = "剧本正文"
        snapshot["debug_state"]["variables"].update(
            {
                LOCAL_SCRIPT_BATCHES: {
                    "1": "第1集\n正文 1\n\n第2集\n正文 2\n\n第3集\n正文 3\n\n第4集\n正文 4\n\n第5集\n正文 5",
                    "6": "第6集\n正文 6\n\n第7集\n正文 7\n\n第8集\n正文 8\n\n第9集\n正文 9\n\n第10集\n正文 10",
                },
                LOCAL_SCRIPT_EPISODES: {},
            }
        )

        public = self.manager._public_snapshot(snapshot)
        artifacts = public["artifacts"]

        self.assertEqual(public["display_stage_key"], "final")
        self.assertEqual(public["display_stage_title"], "已生成正文")
        self.assertIn("第1集", public["display_stage_output"])
        self.assertIn("第10集", public["display_stage_output"])
        self.assertEqual(artifacts[SCRIPT_BATCH_RANGE_ARTIFACT], "6-10")
        self.assertIn("第6集", artifacts[SCRIPT_BATCH_PREVIEW_ARTIFACT])
        self.assertEqual(
            artifacts[PARTIAL_SCRIPT_EPISODES_ARTIFACT],
            list(range(1, 11)),
        )
        self.assertEqual(len(artifacts[SCRIPT_BATCHES_DISPLAY_ARTIFACT]), 2)
        self.assertIn("第1集", artifacts[PARTIAL_SCRIPT_ARTIFACT])
        self.assertIn("第10集", artifacts[PARTIAL_SCRIPT_ARTIFACT])
