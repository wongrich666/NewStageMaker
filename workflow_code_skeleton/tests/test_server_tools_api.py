from __future__ import annotations

import uuid
import unittest
from unittest.mock import ANY, patch

from workflow_code_skeleton.app.server import create_app
from workflow_code_skeleton.app.services.auth_store import auth_store
from workflow_code_skeleton.app.services.simple_fastgpt_tools import ToolExecutionError


def _auth_headers() -> dict[str, str]:
    username = f"tool_api_{uuid.uuid4().hex[:10]}"
    user = auth_store.register_user(username, "CodexTest9")
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
        reskin = next(item for item in tools if item["tool_id"] == "reskin")
        self.assertEqual(reskin["workflow_json_file"], "换皮.json")
        self.assertEqual(reskin["fields"][0]["name"], "title")
        self.assertEqual(reskin["fields"][1]["name"], "source_outline")
        self.assertEqual(reskin["fields"][3]["name"], "source_characters")
        self.assertFalse(reskin["fields"][4]["required"])

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

    def test_new_framework_api_saves_successful_result_into_user_assets(self) -> None:
        fake_result = {
            "ok": True,
            "tool_id": "new_framework",
            "title": "15节拍剧本框架",
            "output": "第一行\n第二行",
            "text": "第一行\n第二行",
            "filename": "15节拍剧本框架_夜行审判.txt",
            "debug": {"chosen_output_source": "root.answerText"},
            "schema": {"fields": [{"name": "story"}]},
        }
        saved_asset = {
            "project_id": 99,
            "asset_kind": "tool_result",
            "title": "15节拍剧本框架｜夜行审判",
        }
        request_payload = {
            "story": "测试故事",
            "character_count": 5,
            "story_scale": "连载爆款短剧",
            "total_episodes": 60,
            "genre_tone": "",
            "target_audience": "",
        }
        with patch("workflow_code_skeleton.app.server.run_simple_tool", return_value=fake_result), patch(
            "workflow_code_skeleton.app.server.task_manager.save_auxiliary_asset",
            return_value=saved_asset,
        ) as mocked_save:
            response = self.client.post(
                "/api/tools/new-framework",
                headers=self.headers,
                json=request_payload,
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["asset_saved"])
        self.assertEqual(payload["saved_asset"], saved_asset)
        self.assertTrue(payload["result"]["asset_saved"])
        self.assertEqual(payload["result"]["saved_asset"], saved_asset)
        mocked_save.assert_called_once_with(
            user_id=ANY,
            tool_key="new_framework",
            request_payload=request_payload,
            result=fake_result,
        )

    def test_new_framework_api_reports_asset_save_failure_without_losing_result(self) -> None:
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
        with patch("workflow_code_skeleton.app.server.run_simple_tool", return_value=fake_result), patch(
            "workflow_code_skeleton.app.server.task_manager.save_auxiliary_asset",
            side_effect=RuntimeError("磁盘写入失败"),
        ):
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
        self.assertFalse(payload["asset_saved"])
        self.assertIn("写入用户资产失败", payload["asset_save_error"])
        self.assertFalse(payload["result"]["asset_saved"])
        self.assertIn("写入用户资产失败", payload["result"]["asset_save_error"])
        self.assertEqual(payload["text"], "15 节拍框架正文")

    def test_hot_review_manual_save_creates_and_updates_asset(self) -> None:
        raw_json = (
            '{"schema_version":"script_audit_compact_v1",'
            '"meta":{"script_title":"测试爆款文"},'
            '"overall":{"total_score":80,"core_judgement":"可上线"},'
            '"dimension_scores":[],"segments":[],"global_review":{},'
            '"episode_reviews":[],"cross_episode_analysis":{}}'
        )
        response = self.client.post(
            "/api/tools/hot_review/save",
            headers=self.headers,
            json={
                "request_payload": {"text": "第一行正文"},
                "result": {
                    "title": "爆款文审核",
                    "text": raw_json,
                    "answer_text": raw_json,
                    "result_type": "script_audit_ecg",
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["asset_saved"])
        saved_asset = payload["saved_asset"]
        self.assertEqual(saved_asset["asset_type"], "hot_review")
        self.assertEqual((saved_asset.get("artifacts") or {}).get("raw_json"), raw_json)

        update_response = self.client.post(
            "/api/tools/hot_review/save",
            headers=self.headers,
            json={
                "asset_id": saved_asset["project_id"],
                "request_payload": {"text": "第二版正文"},
                "result": {
                    "title": "爆款文审核",
                    "text": raw_json.replace("80", "81"),
                    "answer_text": raw_json.replace("80", "81"),
                    "result_type": "script_audit_ecg",
                    "saved_asset": saved_asset,
                },
            },
        )
        self.assertEqual(update_response.status_code, 200)
        update_payload = update_response.get_json()
        self.assertEqual(update_payload["saved_asset"]["project_id"], saved_asset["project_id"])
        self.assertEqual(update_payload["saved_asset"]["asset_type"], "hot_review")

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
        user = auth_store.register_user(username, "CodexTest9")
        token = auth_store.create_session_token(user.id)

        for path in ("/", "/login", "/register"):
            response = self.client.get(f"{path}?auth_token={token}", follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/workspace", response.headers["Location"])
            self.assertIn(f"auth_token={token}", response.headers["Location"])

    def test_login_and_register_submit_redirect_directly_to_workspace(self) -> None:
        username = f"lg_{uuid.uuid4().hex[:8]}"
        auth_store.register_user(username, "CodexTest9")

        login_response = self.client.post(
            "/login",
            data={"username": username, "password": "CodexTest9"},
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
                "password": "CodexTest9",
                "confirm_password": "CodexTest9",
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

    def test_home_page_links_to_community_for_prelogin_users(self) -> None:
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
        self.assertIn("社区好剧", text)
        self.assertIn("#community", text)
        self.assertIn("未登录状态下会先进入登录页。", text)


if __name__ == "__main__":
    unittest.main()
