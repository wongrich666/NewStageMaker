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
