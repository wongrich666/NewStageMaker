from __future__ import annotations

import os
import uuid
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
