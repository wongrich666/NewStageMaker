from __future__ import annotations

import os
import uuid
import unittest
from unittest.mock import patch

import requests

from workflow_code_skeleton.app.server import create_app
from workflow_code_skeleton.app.services.auth_store import auth_store


def _auth_headers() -> dict[str, str]:
    username = f"fp_{uuid.uuid4().hex[:8]}"
    user = auth_store.register_user(username, "password123")
    token = auth_store.create_session_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def _basic_config() -> dict[str, object]:
    return {
        "project_title": "夜行审判",
        "mode": "创作",
        "source_text": "一个律师重返故乡，调查父亲之死与地方财团的关系。",
        "source_title": "夜行审判",
        "target_format": "短剧",
        "season_count": 1,
        "episodes_per_season": 60,
        "minutes_per_episode": 2,
        "adaptation_direction": "强化反转",
        "user_constraints": "",
        "user_requirements": "保持主角成长弧线",
    }


def _planner_payload() -> dict[str, object]:
    return {
        "basic_config": _basic_config(),
        "source_brief": {"source_title": "夜行审判"},
        "worldview_plan": {"world_type": "近未来都市"},
        "character_plan": {"protagonist": {"name": "林渡"}},
        "beat_checkpoint_timeline": [],
        "checkpoint_explanation": {},
        "character_storylines": [],
        "storyline_decisions": [],
        "adaptation_guide": {},
        "user_edit_history": [],
        "framework_plan_package": {},
        "validation_report": {},
    }


class ServerFrameworkPlannerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.headers = _auth_headers()

    def test_framework_planner_page_renders_config_bootstrap(self) -> None:
        response = self.client.get("/framework-planner", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("frameworkPlannerConfig", text)
        self.assertIn("frameworkPlannerState.v2", text)

    def test_stage_04_api_returns_mock_timeline_shape(self) -> None:
        payload = {
            "mode": "创作",
            "source_brief": {"source_title": "夜行审判"},
            "basic_config": _basic_config(),
            "worldview_plan": {"world_type": "近未来都市"},
            "character_plan": {"protagonist": {"name": "林渡"}},
            "previous_beat_checkpoint_timeline": [],
            "user_feedback": "",
            "framework_score_report": "",
            "adaptation_direction": "强化反转",
            "user_requirements": "固定 15 beat",
        }
        with patch.dict(os.environ, {"FRAMEWORK_PLANNER_USE_MOCK": "true"}, clear=False):
            response = self.client.post("/api/framework-planner/stage/04", headers=self.headers, json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["stage"], "04")
        self.assertEqual(len(data["data"]["beat_checkpoint_timeline"]), 15)

    def test_stage_04_score_api_returns_string_report(self) -> None:
        with patch.dict(os.environ, {"FRAMEWORK_PLANNER_USE_MOCK": "true"}, clear=False):
            beat_payload = self.client.post(
                "/api/framework-planner/stage/04",
                headers=self.headers,
                json={
                    "mode": "创作",
                    "source_brief": {"source_title": "夜行审判"},
                    "basic_config": _basic_config(),
                    "worldview_plan": {"world_type": "近未来都市"},
                    "character_plan": {"protagonist": {"name": "林渡"}},
                    "previous_beat_checkpoint_timeline": [],
                    "user_feedback": "",
                    "framework_score_report": "",
                    "adaptation_direction": "强化反转",
                    "user_requirements": "固定 15 beat",
                },
            ).get_json()
            response = self.client.post(
                "/api/framework-planner/stage/04/score",
                headers=self.headers,
                json={
                    "beat_checkpoint_timeline": beat_payload["data"]["beat_checkpoint_timeline"],
                    "checkpoint_explanation": beat_payload["data"]["checkpoint_explanation"],
                    "basic_config": _basic_config(),
                    "source_brief": {"source_title": "夜行审判"},
                    "worldview_plan": {"world_type": "近未来都市"},
                    "character_plan": {"protagonist": {"name": "林渡"}},
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertIsInstance(data["data"]["framework_score_report"], str)
        self.assertIn("PASS", data["data"]["framework_score_report"])

    def test_stage_07_api_returns_framework_package_and_validation_report(self) -> None:
        payload = _planner_payload()
        payload["beat_checkpoint_timeline"] = [{"beat_no": 1, "beat_name": "开场"}] * 15
        payload["checkpoint_explanation"] = {"overview": "ok"}
        payload["character_storylines"] = [{"id": "main", "title": "主角成长线", "decision": "keep"}]
        payload["storyline_decisions"] = [{"storyline_id": "main", "decision": "keep"}]
        payload["adaptation_guide"] = {"core_setting_adjustments": "保留规则对抗骨架"}

        with patch.dict(os.environ, {"FRAMEWORK_PLANNER_USE_MOCK": "true"}, clear=False):
            response = self.client.post("/api/framework-planner/stage/07", headers=self.headers, json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("framework_plan_package", data["data"])
        self.assertIn("validation_report", data["data"])

    def test_generate_script_requires_framework_plan_package(self) -> None:
        response = self.client.post(
            "/api/framework-planner/generate-script",
            headers=self.headers,
            json={"basic_config": _basic_config()},
        )

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["message"], "缺少 framework_plan_package，请先完成并确认 07 最终策划包输出。")

    def test_generate_script_starts_framework_to_script_chain(self) -> None:
        fake_snapshot = {
            "project_id": 123,
            "task_id": "task-framework-script",
            "status": "running",
            "current_stage": "framework_scene_dictionary",
            "current_stage_label": "框架转剧本场景字典",
            "progress_percent": 5,
        }
        payload = _planner_payload()
        payload.update(
            {
                "title": "夜行审判",
                "project_title": "夜行审判",
                "source_title": "夜行审判",
                "target_format": "短剧",
                "season_count": 1,
                "episodes_per_season": 60,
                "total_episodes": 60,
                "minutes_per_episode": 2,
                "episode_word_count": 900,
                "user_expectation": "走新框架转剧本链路",
                "user_requirements": "保留主角成长线",
                "adaptation_direction": "强化反转",
                "framework_plan_package": {"package_id": "stage07", "source_brief": {"source_title": "夜行审判"}},
                "source_brief": {"source_title": "夜行审判"},
                "worldview_plan": {"world_type": "近未来都市"},
                "character_plan": {"protagonist": {"name": "林渡"}},
                "beat_checkpoint_timeline": [{"beat_no": 1, "beat_name": "开场"}],
                "checkpoint_explanation": {"overview": "ok"},
                "character_storylines": [{"id": "main", "decision": "keep"}],
                "storyline_decisions": [{"storyline_id": "main", "decision": "keep"}],
                "adaptation_guide": {"structure_and_rhythm": "强钩子"},
                "prompt_preferences": {"stage_prompts": {"package": "进入下游"}},
                "user_knowledge_stage_prompts": {"package": "进入下游"},
                "user_knowledge_step_prompts": {"framework_script": "正文更强冲突"},
                "selected_preference_tag_ids": ["tag-a"],
                "selected_preference_tags": [{"id": "tag-a", "name": "短剧强钩子"}],
            }
        )

        with patch("workflow_code_skeleton.app.server.task_manager.start_task", return_value=fake_snapshot) as mocked:
            response = self.client.post(
                "/api/framework-planner/generate-script",
                headers=self.headers,
                json=payload,
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["task"]["project_id"], 123)
        self.assertEqual(data["task"]["task_id"], "task-framework-script")
        self.assertEqual(data["task"]["status"], "running")
        self.assertEqual(data["task"]["current_stage"], "framework_scene_dictionary")
        self.assertEqual(data["task"]["current_stage_label"], "框架转剧本场景字典")
        self.assertEqual(data["task"]["progress_percent"], 5)

        start_payload = mocked.call_args.kwargs["input_payload"]
        self.assertEqual(start_payload["workflow_mode"], "framework_to_script")
        self.assertEqual(start_payload["generation_chain"], "framework_to_script")
        self.assertTrue(start_payload["framework_to_script"])
        self.assertTrue(start_payload["framework_planner_source"])
        self.assertEqual(start_payload["basic_config"]["project_title"], "夜行审判")
        self.assertEqual(start_payload["framework_plan_package"]["package_id"], "stage07")
        self.assertEqual(start_payload["user_knowledge_step_prompts"]["framework_script"], "正文更强冲突")
        self.assertEqual(start_payload["selected_preference_tag_ids"], ["tag-a"])
        self.assertNotIn("all_hooks", start_payload)
        self.assertNotIn("all_dialogues", start_payload)
        self.assertNotIn("all_script", start_payload)

    def test_save_framework_planner_asset_returns_project_id_and_restorable_state(self) -> None:
        payload = _planner_payload()
        payload.update(
            {
                "project_title": "夜行审判",
                "framework_plan_package": {"package_id": "stage07"},
                "validation_report": {"status": "pass"},
                "display_texts": {"07": "最终策划包可进入资产化链路"},
                "prompt_preferences": {"stage_prompts": {"package": "保持强钩子"}},
                "selected_preference_tag_ids": ["tag-a"],
                "selected_preference_tags": [{"id": "tag-a", "name": "短剧强钩子"}],
                "asset_state": {"status": "completed", "current_stage": "package"},
                "stage_state": {
                    "package": {"status": "confirmed", "confirmed": True, "locked": True},
                },
                "current_view": "package",
            }
        )

        response = self.client.post(
            "/api/framework-planner/assets/save",
            headers=self.headers,
            json=payload,
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        project_id = data["project_id"]
        self.assertIsInstance(project_id, int)
        self.assertGreater(project_id, 0)
        self.assertEqual(data["asset"]["asset_kind"], "framework_planner")

        restored_response = self.client.get(f"/api/projects/{project_id}", headers=self.headers)
        self.assertEqual(restored_response.status_code, 200)
        restored = restored_response.get_json()["project"]
        self.assertEqual(restored["project_id"], project_id)
        self.assertEqual(restored["asset_kind"], "framework_planner")
        framework_state = restored["framework_planner_state"]
        self.assertEqual(framework_state["project_id"], project_id)
        self.assertEqual(framework_state["framework_plan_package"]["package_id"], "stage07")
        self.assertEqual(framework_state["validation_report"]["status"], "pass")
        self.assertEqual(framework_state["display_texts"]["07"], "最终策划包可进入资产化链路")
        self.assertEqual(framework_state["prompt_preferences"]["stage_prompts"]["package"], "保持强钩子")
        self.assertEqual(framework_state["selected_preference_tag_ids"], ["tag-a"])
        self.assertTrue(framework_state["stage_state"]["package"]["confirmed"])
        self.assertEqual(framework_state["asset_state"]["project_id"], project_id)

    def test_stage_success_autosaves_framework_asset_outputs(self) -> None:
        create_response = self.client.post(
            "/api/framework-planner/assets",
            headers=self.headers,
            json={
                "title": "夜行审判",
                "season_count": 1,
                "episodes_per_season": 60,
                "target_format": "短剧",
                "style": "强反转",
                "description": "一个律师重返故乡调查旧案。",
            },
        )
        self.assertEqual(create_response.status_code, 200)
        project_id = create_response.get_json()["asset"]["project_id"]

        payload = _planner_payload()
        payload.update(
            {
                "project_id": project_id,
                "project_title": "夜行审判",
                "beat_checkpoint_timeline": [{"beat_no": index + 1, "beat_name": f"节拍{index + 1}"} for index in range(15)],
                "character_storylines": [{"id": "main", "title": "主角成长线", "decision": "keep"}],
                "storyline_decisions": [{"storyline_id": "main", "decision": "keep"}],
            }
        )

        with patch.dict(os.environ, {"FRAMEWORK_PLANNER_USE_MOCK": "true"}, clear=False):
            response = self.client.post("/api/framework-planner/stage/06", headers=self.headers, json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["autosaved"])
        self.assertEqual(data["project_id"], project_id)

        restored_response = self.client.get(f"/api/projects/{project_id}", headers=self.headers)
        self.assertEqual(restored_response.status_code, 200)
        restored = restored_response.get_json()["project"]
        framework_state = restored["framework_planner_state"]
        self.assertEqual(framework_state["project_id"], project_id)
        self.assertIn("core_setting_adjustments", framework_state["adaptation_guide"])
        self.assertTrue(framework_state["stage_state"]["guide"]["stageCommitted"])
        self.assertFalse(framework_state["stage_state"]["package"]["locked"])

    def test_generate_script_receives_source_framework_project_id(self) -> None:
        fake_snapshot = {
            "project_id": 456,
            "task_id": "task-framework-script",
            "status": "running",
            "current_stage": "framework_scene_dictionary",
            "current_stage_label": "框架转剧本场景字典",
            "progress_percent": 5,
        }
        payload = _planner_payload()
        payload.update(
            {
                "title": "夜行审判",
                "framework_plan_package": {"package_id": "stage07"},
                "source_framework_project_id": 321,
            }
        )

        with patch("workflow_code_skeleton.app.server.task_manager.start_task", return_value=fake_snapshot) as mocked:
            response = self.client.post(
                "/api/framework-planner/generate-script",
                headers=self.headers,
                json=payload,
            )

        self.assertEqual(response.status_code, 200)
        start_payload = mocked.call_args.kwargs["input_payload"]
        self.assertEqual(start_payload["source_framework_project_id"], 321)

    def test_stage_api_returns_stable_error_shape_when_required_inputs_missing(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "FASTGPT_API_KEY": "fastgpt-global-key",
                "FASTGPT_CHAT_COMPLETIONS_URL": "https://api.fastgpt.in/api/v1/chat/completions",
            },
            clear=False,
        ):
            response = self.client.post("/api/framework-planner/stage/02", headers=self.headers, json={})

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["stage"], "02")
        self.assertIn("缺少必填项", data["error"])
        self.assertIn("missing_fields", data["detail"])

    def test_stage_01_timeout_returns_structured_fastgpt_failure_detail(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "FASTGPT_FRAMEWORK_API_KEY": "fastgpt-framework-key",
                "FASTGPT_API_URL": "https://api.fastgpt.in/api/v1",
            },
            clear=True,
        ):
            with patch(
                "workflow_code_skeleton.app.services.framework_planner_service.requests.post",
                side_effect=requests.Timeout("upstream timeout"),
            ):
                response = self.client.post(
                    "/api/framework-planner/stage/01",
                    headers=self.headers,
                    json=_basic_config(),
                )

        self.assertEqual(response.status_code, 504)
        data = response.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["stage"], "01")
        self.assertEqual(data["error"], "阶段 01 请求 FastGPT 失败")
        self.assertEqual(data["detail"]["reason"], "FastGPT 请求超时，已重试 3 次仍失败")
        self.assertEqual(data["detail"]["url"], "https://api.fastgpt.in/api/v1/chat/completions")
        self.assertEqual(data["detail"]["attempts"], 3)
        self.assertTrue(data["detail"]["has_api_key"])
        self.assertFalse(data["detail"]["has_workflow_id"])
        self.assertTrue(data["detail"]["base_url_configured"])
        self.assertTrue(data["detail"]["entered_fastgpt_request"])
        self.assertEqual(data["detail"]["exception_type"], "Timeout")
        self.assertIn("upstream timeout", data["detail"]["exception_message"])
        self.assertEqual(data["detail"]["last_exception_type"], "Timeout")
        self.assertIn("upstream timeout", data["detail"]["last_exception_message"])

    def test_stage_05_connect_timeout_returns_actionable_connection_error(self) -> None:
        payload = _planner_payload()
        payload["beat_checkpoint_timeline"] = [{"beat_no": 1, "beat_name": "开场"}] * 15
        with patch.dict(
            os.environ,
            {
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "FASTGPT_API_KEY": "fastgpt-global-key",
                "FASTGPT_CHAT_COMPLETIONS_URL": "http://192.168.2.203:3000/api/v1/chat/completions",
            },
            clear=True,
        ):
            with patch(
                "workflow_code_skeleton.app.services.framework_planner_service.requests.post",
                side_effect=requests.ConnectTimeout("connect timed out"),
            ):
                response = self.client.post(
                    "/api/framework-planner/stage/05",
                    headers=self.headers,
                    json=payload,
                )

        self.assertEqual(response.status_code, 504)
        data = response.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["stage"], "05")
        self.assertEqual(data["error"], "阶段 05 无法连接 FastGPT 服务")
        self.assertEqual(data["detail"]["exception_type"], "ConnectTimeout")
        self.assertEqual(data["detail"]["endpoint"], "http://192.168.2.203:3000/api/v1/chat/completions")
        self.assertEqual(data["detail"]["host"], "192.168.2.203")
        self.assertEqual(data["detail"]["port"], 3000)
        self.assertIn("3000", data["detail"]["suggestion"])

    def test_fastgpt_diagnostics_endpoint_returns_safe_config(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "FASTGPT_API_KEY": "fastgpt-global-key",
                "FASTGPT_CHAT_COMPLETIONS_URL": "http://192.168.2.203:3000/api/v1/chat/completions",
            },
            clear=True,
        ):
            response = self.client.get(
                "/api/framework-planner/diagnostics/fastgpt",
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["endpoint"], "http://192.168.2.203:3000/api/v1/chat/completions")
        self.assertEqual(data["host"], "192.168.2.203")
        self.assertEqual(data["port"], 3000)
        self.assertTrue(data["has_api_key"])
        self.assertEqual(data["api_key_config_name"], "FASTGPT_API_KEY")
        self.assertFalse(data["mock_enabled"])
        self.assertNotIn("fastgpt-global-key", str(data))


if __name__ == "__main__":
    unittest.main()
