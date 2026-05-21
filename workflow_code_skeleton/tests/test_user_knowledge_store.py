from __future__ import annotations

import uuid
import unittest
from unittest.mock import patch

from workflow_code_skeleton.app.server import create_app
from workflow_code_skeleton.app.services.auth_store import auth_store
from workflow_code_skeleton.app.services.user_knowledge_store import UserKnowledgeStore
from workflow_code_skeleton.tests.test_support import workspace_tempdir


def _auth_headers() -> dict[str, str]:
    username = f"uk_{uuid.uuid4().hex[:10]}"
    user = auth_store.register_user(username, "password123")
    token = auth_store.create_session_token(user.id)
    return {"Authorization": f"Bearer {token}"}


class UserKnowledgeStoreTests(unittest.TestCase):
    def test_initializes_builtin_tags(self) -> None:
        with workspace_tempdir("knowledge-store-") as temp_dir:
            store = UserKnowledgeStore(temp_dir)
            tags = store.list_tags()

        self.assertGreaterEqual(len(tags), 18)
        self.assertTrue(any(tag["builtin"] and tag["name"] == "规则怪谈" for tag in tags))

    def test_apply_tags_allows_empty_selection(self) -> None:
        with workspace_tempdir("knowledge-store-") as temp_dir:
            store = UserKnowledgeStore(temp_dir)
            result = store.apply_tags([], existing_user_preference="保留原偏好")

        self.assertEqual(result["selected_tags"], [])
        self.assertEqual(result["merged_preference_prompt"], "保留原偏好")
        self.assertEqual(result["tag_prompt_text"], "")

    def test_apply_tags_merges_multiple_prompts(self) -> None:
        with workspace_tempdir("knowledge-store-") as temp_dir:
            store = UserKnowledgeStore(temp_dir)
            tag_ids = [tag["id"] for tag in store.list_tags()[:2]]
            result = store.apply_tags(tag_ids, existing_user_preference="用户手写偏好")

        self.assertIn("用户手写偏好", result["merged_preference_prompt"])
        self.assertIn("来自智慧库标签", result["merged_preference_prompt"])
        self.assertEqual(len(result["selected_tags"]), 2)


class UserKnowledgeApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = workspace_tempdir("knowledge-api-")
        self.store_dir = self.temp_dir.__enter__()
        self.store = UserKnowledgeStore(self.store_dir)
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.headers = _auth_headers()
        self.store_patch = patch("workflow_code_skeleton.app.server.user_knowledge_store", self.store)
        self.store_patch.start()

    def tearDown(self) -> None:
        self.store_patch.stop()
        self.temp_dir.__exit__(None, None, None)

    def test_get_tags_returns_builtin_tags(self) -> None:
        response = self.client.get("/api/user-knowledge/tags", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(any(tag["builtin"] for tag in payload["tags"]))

    def test_create_custom_tag(self) -> None:
        response = self.client.post(
            "/api/user-knowledge/tags",
            headers=self.headers,
            json={
                "name": "我的爽点",
                "category": "自定义",
                "description": "偏好描述",
                "prompt_text": "强化主角反击。",
            },
        )

        self.assertEqual(response.status_code, 200)
        tag = response.get_json()["tag"]
        self.assertFalse(tag["builtin"])
        self.assertEqual(tag["name"], "我的爽点")

    def test_start_workflow_accepts_empty_selected_tags(self) -> None:
        fake_snapshot = {
            "project_id": 101,
            "task_id": "task-empty-tags",
            "status": "pending",
            "input_payload": {},
        }
        with patch("workflow_code_skeleton.app.server.task_manager.start_task", return_value=fake_snapshot) as mocked:
            response = self.client.post(
                "/api/workflows/start",
                headers=self.headers,
                json={
                    "user_expectation": "写一个都市短剧",
                    "character_count": 5,
                    "total_episodes": 12,
                    "model_selection_id": "default",
                    "selected_preference_tags": [],
                    "selected_preference_tag_ids": [],
                },
            )

        self.assertEqual(response.status_code, 200)
        input_payload = mocked.call_args.kwargs["input_payload"]
        self.assertEqual(input_payload["selected_preference_tags"], [])
        self.assertEqual(input_payload["selected_preference_tag_ids"], [])

    def test_start_workflow_keeps_object_tags_structured(self) -> None:
        fake_snapshot = {
            "project_id": 102,
            "task_id": "task-object-tags",
            "status": "pending",
            "input_payload": {},
        }
        selected_tags = [
            {"id": "builtin-规则怪谈", "name": "规则怪谈", "category": "题材", "builtin": True, "prompt_text": "建立规则。"}
        ]
        with patch("workflow_code_skeleton.app.server.task_manager.start_task", return_value=fake_snapshot) as mocked:
            response = self.client.post(
                "/api/workflows/start",
                headers=self.headers,
                json={
                    "user_expectation": "写一个规则怪谈短剧",
                    "character_count": 4,
                    "total_episodes": 10,
                    "model_selection_id": "default",
                    "selected_preference_tags": selected_tags,
                    "selected_preference_tag_ids": ["builtin-规则怪谈"],
                    "user_preference_prompt": {"stage": "avoid_str"},
                },
            )

        self.assertEqual(response.status_code, 200)
        input_payload = mocked.call_args.kwargs["input_payload"]
        self.assertIsInstance(input_payload["selected_preference_tags"], list)
        self.assertIsInstance(input_payload["selected_preference_tags"][0], dict)
        self.assertNotIn("{'stage':", input_payload["user_preference_prompt"])
        self.assertIn('"stage"', input_payload["user_preference_prompt"])


if __name__ == "__main__":
    unittest.main()
