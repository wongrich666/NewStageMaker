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

    def test_new_framework_api_uses_dedicated_route_and_returns_filename(self) -> None:
        fake_result = {
            "ok": True,
            "tool_id": "new_framework",
            "title": "15节拍剧本框架",
            "output": "15 节拍框架正文",
            "text": "15 节拍框架正文",
            "filename": "15节拍剧本框架_20260506_153000.txt",
            "debug": {"chosen_output_source": "root.answerText"},
            "schema": {"fields": [{"name": "story"}]},
        }
        with patch("workflow_code_skeleton.app.server.run_simple_tool", return_value=fake_result) as mocked:
            response = self.client.post(
                "/api/tools/new-framework",
                headers=self.headers,
                json={
                    "story": "测试故事",
                    "character_count": 5,
                    "story_scale": "连载爆款短剧",
                    "total_episodes": 60,
                    "genre_tone": "",
                    "target_audience": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["tool_id"], "new_framework")
        self.assertEqual(payload["filename"], "15节拍剧本框架_20260506_153000.txt")
        mocked.assert_called_once_with(
            "new_framework",
            {
                "story": "测试故事",
                "character_count": 5,
                "story_scale": "连载爆款短剧",
                "total_episodes": 60,
                "genre_tone": "",
                "target_audience": "",
            },
        )

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

    def test_logged_in_pages_redirect_directly_to_workspace(self) -> None:
        username = f"pg_{uuid.uuid4().hex[:8]}"
        user = auth_store.register_user(username, "password123")
        token = auth_store.create_session_token(user.id)

        for path in ("/", "/login", "/register"):
            response = self.client.get(f"{path}?auth_token={token}", follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/workspace", response.headers["Location"])
            self.assertIn(f"auth_token={token}", response.headers["Location"])

    def test_login_and_register_submit_redirect_directly_to_workspace(self) -> None:
        username = f"lg_{uuid.uuid4().hex[:8]}"
        auth_store.register_user(username, "password123")

        login_response = self.client.post(
            "/login",
            data={"username": username, "password": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertIn("/workspace", login_response.headers["Location"])
        self.assertIn("auth_token=", login_response.headers["Location"])

        register_username = f"rg_{uuid.uuid4().hex[:8]}"
        register_response = self.client.post(
            "/register",
            data={
                "username": register_username,
                "password": "password123",
                "confirm_password": "password123",
            },
            follow_redirects=False,
        )
        self.assertEqual(register_response.status_code, 302)
        self.assertIn("/workspace", register_response.headers["Location"])
        self.assertIn("auth_token=", register_response.headers["Location"])

    def test_workspace_page_contains_community_section_and_refresh_controls(self) -> None:
        response = self.client.get("/workspace", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn('id="community"', text)
        self.assertIn('id="communityList"', text)
        self.assertIn('id="refreshCommunityBtn"', text)
        self.assertIn('id="closeCommunityPanelBtn"', text)
        self.assertIn('id="openCommunityPanelLink"', text)
        self.assertIn('id="waibaoScriptBtn"', text)
        self.assertIn('id="scriptFormatText"', text)
        self.assertIn('id="composerModeText"', text)
        self.assertIn('class="tool-panel community-panel hidden"', text)
        self.assertIn("section=community", text)

    def test_start_workflow_keeps_script_format_mode_in_input_payload(self) -> None:
        fake_snapshot = {
            "project_id": 88,
            "task_id": "task-waibao",
            "status": "pending",
            "input_payload": {"script_format_mode": "waibao"},
        }
        with patch("workflow_code_skeleton.app.server.task_manager.start_task", return_value=fake_snapshot) as mocked:
            response = self.client.post(
                "/api/workflows/start",
                headers=self.headers,
                json={
                    "user_expectation": "写一个外包专属格式的都市短剧",
                    "character_count": 6,
                    "total_episodes": 15,
                    "model_selection_id": "default",
                    "script_format_mode": "waibao",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        call = mocked.call_args.kwargs
        self.assertEqual(call["input_payload"]["script_format_mode"], "waibao")

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
