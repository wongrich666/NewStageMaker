from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from workflow_code_skeleton.app.server import (
    _framework_stage01_missing_fields,
    create_app,
)


class FrameworkStage01ValidationTests(unittest.TestCase):
    def valid_payload(self) -> dict:
        return {
            "source_title": "测试项目",
            "mode": "创作",
            "target_format": "短剧",
            "episodes_per_season": 30,
            "episode_word_count": 600,
            "adaptation_direction": "强化人物关系和节奏",
            "user_requirements": "适配短视频平台",
            "source_text": "完整的故事原始材料",
            "user_constraints": "不得改变核心人物关系",
        }

    def test_complete_stage01_payload_passes(self):
        self.assertEqual(_framework_stage01_missing_fields(self.valid_payload()), [])

    def test_all_downstream_required_fields_are_reported(self):
        payload = self.valid_payload()
        payload.update(
            {
                "episodes_per_season": 0,
                "episode_word_count": "",
                "adaptation_direction": "",
                "user_constraints": "",
            }
        )

        self.assertEqual(
            _framework_stage01_missing_fields(payload),
            ["总集数", "每集字数", "改编方向", "限制条件"],
        )

    def test_nested_basic_config_is_supported(self):
        payload = {"basic_config": self.valid_payload()}
        self.assertEqual(_framework_stage01_missing_fields(payload), [])

    @patch("workflow_code_skeleton.app.server.run_framework_planner_stage")
    @patch("workflow_code_skeleton.app.server.auth_store.get_user_by_token")
    def test_incomplete_route_request_never_calls_workflow(
        self,
        get_user_by_token,
        run_framework_planner_stage,
    ):
        get_user_by_token.return_value = SimpleNamespace(id=7)
        app = create_app()
        app.config.update(TESTING=True)
        payload = self.valid_payload()
        payload["project_id"] = "unsaved"
        payload["episodes_per_season"] = 0

        response = app.test_client().post(
            "/api/framework-planner/stage/01",
            json=payload,
            headers={"Authorization": "Bearer test-token"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("总集数", response.get_json()["error"])
        run_framework_planner_stage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
