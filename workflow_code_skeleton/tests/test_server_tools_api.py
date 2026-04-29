from __future__ import annotations

import uuid
import unittest
from unittest.mock import patch

from workflow_code_skeleton.app.server import create_app
from workflow_code_skeleton.app.services.auth_store import auth_store
from workflow_code_skeleton.app.services.simple_fastgpt_tools import ToolExecutionError


def _auth_headers() -> dict[str, str]:
    username = f"tool_api_{uuid.uuid4().hex[:10]}"
    user = auth_store.register_user(username, "password123")
    token = auth_store.create_session_token(user.id)
    return {"Authorization": f"Bearer {token}"}


class ServerToolsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.headers = _auth_headers()

    def test_list_tools_api_returns_scanned_tool_configs(self) -> None:
        response = self.client.get("/api/tools", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["ok"])
        tools = payload["tools"]
        tool_ids = {item["tool_id"] for item in tools}
        self.assertIn("hot_review", tool_ids)
        self.assertIn("reskin", tool_ids)
        hot_review = next(item for item in tools if item["tool_id"] == "hot_review")
        self.assertEqual(hot_review["workflow_json_file"], "爆款文审核.json")
        self.assertEqual(hot_review["fields"][0]["name"], "text")

    def test_run_tool_api_returns_user_visible_result_payload(self) -> None:
        fake_result = {
            "ok": True,
            "tool_id": "hot_review",
            "title": "爆款文审核",
            "output": "审核通过，节奏顺畅。",
            "debug": {"chosen_output_source": "choices[0].message.content"},
            "schema": {"fields": [{"name": "text"}]},
        }
        with patch("workflow_code_skeleton.app.server.run_simple_tool", return_value=fake_result) as mocked:
            response = self.client.post(
                "/api/tools/hot_review/run",
                headers=self.headers,
                json={"text": "测试正文"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tool_id"], "hot_review")
        self.assertEqual(payload["output"], "审核通过，节奏顺畅。")
        self.assertEqual(payload["result"]["output"], "审核通过，节奏顺畅。")
        mocked.assert_called_once_with("hot_review", {"text": "测试正文"})

    def test_run_tool_api_surfaces_specific_tool_error(self) -> None:
        error = ToolExecutionError(
            "爆款文审核缺少必填项：text",
            tool_id="hot_review",
            debug={"missing_fields": ["text"]},
            status_code=400,
        )
        with patch("workflow_code_skeleton.app.server.run_simple_tool", side_effect=error):
            response = self.client.post(
                "/api/tools/hot_review/run",
                headers=self.headers,
                json={},
            )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["tool_id"], "hot_review")
        self.assertIn("缺少必填项", payload["message"])
        self.assertEqual(payload["debug"]["missing_fields"], ["text"])

    def test_tools_api_requires_login_with_specific_message(self) -> None:
        response = self.client.get("/api/tools")

        self.assertEqual(response.status_code, 401)
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertIn("请先登录", payload["message"])

    def test_home_login_and_register_pages_render_workspace_shell(self) -> None:
        for path in ("/", "/login", "/register"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            text = response.get_data(as_text=True)
            self.assertIn("chat-workspace-shell", text)
            self.assertIn("workspace-sidebar", text)

    def test_workspace_page_contains_community_section_and_refresh_controls(self) -> None:
        response = self.client.get("/workspace", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn('id="community"', text)
        self.assertIn('id="communityList"', text)
        self.assertIn('id="refreshCommunityBtn"', text)
        self.assertIn('id="closeCommunityPanelBtn"', text)
        self.assertIn('id="openCommunityPanelLink"', text)
        self.assertIn('class="tool-panel community-panel hidden"', text)
        self.assertIn("section=community", text)

    def test_home_page_renders_public_community_entries(self) -> None:
        fake_assets = [
            {
                "project_id": 7,
                "title": "公开短剧",
                "summary": "这是一部已经公开的社区短剧。",
            }
        ]
        with patch("workflow_code_skeleton.app.server.task_manager.list_public_assets", return_value=fake_assets):
            app = create_app()
            app.config["TESTING"] = True
            client = app.test_client()
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn('id="community"', text)
        self.assertIn("公开短剧", text)
        self.assertIn("/community/7", text)


if __name__ == "__main__":
    unittest.main()
