from __future__ import annotations

import copy
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_code_skeleton.app.services.fastgpt_contracts import (
    CHARACTERS,
    EPISODE_PLAN,
    FRAMEWORK_NATURAL_LANGUAGE,
    SCENES,
    STORY_OUTLINE,
    USER_CHARACTERS,
    USER_SCENES,
    WORLDVIEW,
    WORLDVIEW_NATURAL_LANGUAGE,
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
    APPEARANCE_NATURAL_LANGUAGE_VAR,
    CHARACTER_NATURAL_LANGUAGE_VAR,
    CHARACTER_VAR,
    SCENE_NATURAL_LANGUAGE_VAR,
    SCENE_VAR,
)
from workflow_code_skeleton.tests.test_support import WorkspaceTempDir


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


class _DummyThread:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.started = False

    def start(self) -> None:
        self.started = True


class _BlockingSnapshotRecord:
    def __init__(
        self,
        snapshot: dict[str, object],
        *,
        iteration_started: threading.Event,
        allow_continue: threading.Event,
    ) -> None:
        self._snapshot = copy.deepcopy(snapshot)
        self._iteration_started = iteration_started
        self._allow_continue = allow_continue

    def clone_snapshot(self) -> dict[str, object]:
        self._iteration_started.set()
        self._allow_continue.wait(timeout=2.0)
        return copy.deepcopy(self._snapshot)


class TaskManagerPublicSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = WorkspaceTempDir(prefix="task-manager-public-")
        self.addCleanup(self.temp_dir.cleanup)
        self.manager = TaskManager()
        base_dir = Path(self.temp_dir.name) / "runtime_data"
        self.manager.set_storage_root(base_dir, runtime_archive_dir=Path(self.temp_dir.name) / "runtime_archive")
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

    def _task_record(self, snapshot: dict[str, object]) -> TaskRecord:
        return TaskRecord(
            user_id=int(snapshot["user_id"]),
            project_id=int(snapshot["project_id"]),
            task_id=str(snapshot["task_id"]),
            workflow_spec_path=str(snapshot["workflow_spec_path"]),
            input_payload=copy.deepcopy(snapshot.get("input_payload") or {}),
            model_option=None,
            snapshot=copy.deepcopy(snapshot),
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

    def test_start_task_returns_pending_snapshot_before_debug_variables_are_initialized(self) -> None:
        payload = {
            "title": "外包专属格式测试",
            "user_expectation": "写一个外包专属格式的都市短剧",
            "character_count": 6,
            "total_episodes": 15,
            "episode_word_count": 600,
            "script_format_mode": "waibao",
        }

        with patch("workflow_code_skeleton.app.services.task_lifecycle.use_fastgpt_backend", return_value=True), patch(
            "workflow_code_skeleton.app.services.task_lifecycle.threading.Thread",
            _DummyThread,
        ):
            public = self.manager.start_task(
                user_id=1,
                input_payload=payload,
                workflow_spec_path="spec.json",
                model_selection_id=None,
            )

        self.assertEqual(public["status"], "pending")
        self.assertEqual(public["display_stage_key"], "")
        self.assertEqual(public["display_stage_output"], "")
        self.assertEqual(public["message"], "任务已创建，准备开始生成。")
        self.assertEqual(public["input_payload"]["script_format_mode"], "waibao")

    def test_list_user_projects_tolerates_concurrent_project_store_mutation(self) -> None:
        first_snapshot = _snapshot(current_stage="framework")
        first_snapshot["project_id"] = 1
        first_snapshot["task_id"] = "task-blocking"
        first_snapshot["title"] = "项目 1"
        first_snapshot["updated_at"] = "2026-04-28T12:00:01+08:00"
        second_snapshot = _snapshot(current_stage="worldview")
        second_snapshot["project_id"] = 2
        second_snapshot["task_id"] = "task-normal"
        second_snapshot["title"] = "项目 2"
        second_snapshot["updated_at"] = "2026-04-28T12:00:02+08:00"
        third_snapshot = _snapshot(current_stage="script")
        third_snapshot["project_id"] = 3
        third_snapshot["task_id"] = "task-added"
        third_snapshot["title"] = "项目 3"
        third_snapshot["updated_at"] = "2026-04-28T12:00:03+08:00"

        iteration_started = threading.Event()
        allow_continue = threading.Event()
        mutation_done = threading.Event()
        mutation_errors: list[Exception] = []

        self.manager._project_record_set(
            1,
            _BlockingSnapshotRecord(
                first_snapshot,
                iteration_started=iteration_started,
                allow_continue=allow_continue,
            ),
        )
        self.manager._project_record_set(2, self._task_record(second_snapshot))

        def mutate_project_store() -> None:
            try:
                if not iteration_started.wait(timeout=2.0):
                    mutation_errors.append(AssertionError("项目遍历没有按预期开始"))
                    return
                self.manager._project_record_set(3, self._task_record(third_snapshot))
            except Exception as exc:  # pragma: no cover - failure path captured by assertion
                mutation_errors.append(exc)
            finally:
                mutation_done.set()
                allow_continue.set()

        modifier = threading.Thread(target=mutate_project_store, name="project-store-mutation")
        modifier.start()
        try:
            projects = self.manager.list_user_projects(user_id=1)
        finally:
            allow_continue.set()
            modifier.join(timeout=2.0)

        self.assertFalse(modifier.is_alive(), "并发修改线程未能按预期结束")
        self.assertFalse(mutation_errors, f"并发修改线程出现异常：{mutation_errors}")
        self.assertTrue(mutation_done.is_set())
        project_ids = {item["project_id"] for item in projects}
        self.assertIn(1, project_ids)
        self.assertIn(2, project_ids)

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
        state.set_var(APPEARANCE_NATURAL_LANGUAGE_VAR, "林夏在会议室场景使用交锋态服装。")
        state.set_var(SCENES, json.dumps({"scene_setting": {"scenes": [{"scene_name": "旧码头"}]}}, ensure_ascii=False))
        state.set_var(SCENE_VAR, state.get_var(SCENES))
        state.set_var(SCENE_NATURAL_LANGUAGE_VAR, "核心场景自然语言版")

        runtime.sync_from_state(state)
        snapshot = record.clone_snapshot()
        public = self.manager._public_snapshot(snapshot)

        self.assertEqual(snapshot["artifacts"]["character_natural_language"], "人物小传自然语言版")
        self.assertEqual(snapshot["artifacts"]["appearance_natural_language"], "林夏在会议室场景使用交锋态服装。")
        self.assertEqual(snapshot["artifacts"]["scene_natural_language"], "核心场景自然语言版")
        self.assertEqual(snapshot["artifacts"]["characters"], state.get_var(CHARACTERS))
        self.assertEqual(snapshot["artifacts"]["scene_json"], state.get_var(SCENES))
        self.assertEqual(public["display_stage_output"], "")
        self.assertNotIn("character_natural_language", public["artifacts"])
        self.assertNotIn("appearance_natural_language", public["artifacts"])
        self.assertNotIn("scene_natural_language", public["artifacts"])
        self.assertNotIn("characters", public["artifacts"])
        self.assertNotIn("scene_json", public["artifacts"])

    def test_runtime_sync_preserves_framework_and_worldview_paragraph_breaks(self) -> None:
        record = TaskRecord(
            user_id=1,
            project_id=1,
            task_id="task-runtime-paragraphs",
            workflow_spec_path="spec.json",
            input_payload={"title": "测试项目"},
            model_option=None,
            snapshot=_snapshot(current_stage="framework", framework_natural="", worldview_natural=""),
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
        framework_text = "框架第一段\n\n框架第二段"
        worldview_text = "世界观第一段\n\n世界观第二段"
        state.set_var(FRAMEWORK_NATURAL_LANGUAGE, framework_text)
        state.set_var(WORLDVIEW_NATURAL_LANGUAGE, worldview_text)

        runtime.sync_from_state(state)
        snapshot = record.clone_snapshot()
        public = self.manager._public_snapshot(snapshot)

        self.assertEqual(snapshot["artifacts"]["framework_natural_language"], framework_text)
        self.assertEqual(snapshot["artifacts"]["worldview_natural_language"], worldview_text)
        self.assertEqual(public["display_stage_output"], framework_text)
        self.assertEqual(public["artifacts"]["framework_natural_language"], framework_text)
        self.assertEqual(public["artifacts"]["worldview_natural_language"], worldview_text)

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

    def test_public_snapshot_does_not_leak_structured_character_scene_or_placeholder_content(self) -> None:
        snapshot = _snapshot(current_stage="characters", framework_natural="框架自然语言版", worldview_natural="世界观自然语言版")
        snapshot["artifacts"]["character_summary"] = "【待补全：补充人物定位】"
        snapshot["artifacts"]["scene_natural_language"] = ""
        snapshot["artifacts"]["characters"] = json.dumps(
            {
                "character_setting": {
                    "characters": [
                        {
                            "character_name": "林夏",
                            "story_role": "主角",
                            "core_motivation": "查清真相",
                        }
                    ]
                }
            },
            ensure_ascii=False,
        )
        snapshot["artifacts"]["scene_json"] = json.dumps(
            {
                "scene_setting": {
                    "scenes": [
                        {
                            "scene_name": "旧港调度塔",
                            "story_function": "推进旧案调查",
                        }
                    ]
                }
            },
            ensure_ascii=False,
        )

        public = self.manager._public_snapshot(snapshot)
        visible_text = "\n".join(
            [
                str(public.get("display_stage_output") or ""),
                str(public.get("message") or ""),
                "\n".join(str(value or "") for value in (public.get("artifacts") or {}).values()),
            ]
        )

        self.assertNotIn("【待补全：补充人物定位】", visible_text)
        self.assertNotIn("character_setting", visible_text)
        self.assertNotIn("scene_setting", visible_text)
        self.assertNotIn("[object Object]", visible_text)
        self.assertNotIn("待补全", visible_text)

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
        self.assertIn("\n\n", public["display_stage_output"])
        self.assertIn("第1集", artifacts[PARTIAL_SCRIPT_ARTIFACT])
        self.assertIn("第10集", artifacts[PARTIAL_SCRIPT_ARTIFACT])
        self.assertIn("\n\n", artifacts[PARTIAL_SCRIPT_ARTIFACT])

    def test_compact_completed_snapshot_preserves_multiline_story_outline_and_stage_outputs(self) -> None:
        snapshot = _snapshot(current_stage="final", framework_natural="", worldview_natural="")
        snapshot["status"] = "completed"
        snapshot["completion_confirmed"] = True
        snapshot["awaiting_user_confirmation"] = False
        snapshot["cache_retained"] = False
        snapshot["input_payload"]["story_outline"] = "输入第一段\n\n输入第二段"
        snapshot["artifacts"].update(
            {
                "story_outline": "梗概第一段\n\n梗概第二段",
                "framework_natural_language": "框架第一段\n\n框架第二段",
                "final_script": "第1集\n场景1\n\n场景2",
                "final_output_text": "第1集\n场景1\n\n场景2",
            }
        )

        compacted = self.manager._compact_completed_snapshot(snapshot)

        self.assertEqual(compacted["input_payload"]["story_outline"], "梗概第一段\n\n梗概第二段")
        self.assertEqual(compacted["artifacts"]["framework_natural_language"], "框架第一段\n\n框架第二段")
        self.assertEqual(compacted["artifacts"]["final_script"], "第1集\n场景1\n\n场景2")
        self.assertEqual(compacted["artifacts"]["final_output_text"], "第1集\n场景1\n\n场景2")

    def test_public_snapshot_preserves_wrapped_final_script_line_breaks(self) -> None:
        snapshot = _snapshot(current_stage="script", framework_natural="", worldview_natural="")
        snapshot["status"] = "running"
        snapshot["current_stage_label"] = "剧本正文"
        snapshot["artifacts"]["final_output_text"] = {
            "content": "第1集\n场景1：旧码头\n林夏：先查人。\n\n场景2：会议室\n顾川：你查得太深了。"
        }

        public = self.manager._public_snapshot(snapshot)

        self.assertEqual(public["display_stage_key"], "final")
        self.assertEqual(
            public["display_stage_output"],
            "第1集\n场景1：旧码头\n林夏：先查人。\n\n场景2：会议室\n顾川：你查得太深了。",
        )
        self.assertNotIn("final_output_text", public["artifacts"])
