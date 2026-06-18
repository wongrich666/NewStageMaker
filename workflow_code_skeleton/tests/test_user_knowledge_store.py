from __future__ import annotations

import json
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_code_skeleton.app.server import create_app
from workflow_code_skeleton.app.services import framework_planner_service
from workflow_code_skeleton.app.services.auth_store import auth_store
from workflow_code_skeleton.app.services.user_knowledge_store import UserKnowledgeStore
from workflow_code_skeleton.tests.test_support import workspace_tempdir


TEST_PASSWORD = "UserKnowledge!2026_SafePass"


def _auth_headers() -> dict[str, str]:
    username = f"uk_{uuid.uuid4().hex[:10]}"
    user = auth_store.register_user(username, TEST_PASSWORD)
    token = auth_store.create_session_token(user.id)
    return {"Authorization": f"Bearer {token}"}


class UserKnowledgeStoreTests(unittest.TestCase):
    def test_initializes_builtin_tags(self) -> None:
        with workspace_tempdir("knowledge-store-") as temp_dir:
            store = UserKnowledgeStore(temp_dir)
            tags = store.list_tags()

        self.assertGreaterEqual(len(tags), 18)
        self.assertTrue(any(tag["builtin"] and tag["name"] == "规则怪谈" for tag in tags))
        rule_tag = next(tag for tag in tags if tag["name"] == "规则怪谈")
        self.assertIn("stage_prompts", rule_tag)
        self.assertIn("worldview", rule_tag["stage_prompts"])
        self.assertIn("script_text", rule_tag["stage_prompts"])
        self.assertNotEqual(rule_tag["stage_prompts"]["basic"], rule_tag["stage_prompts"]["worldview"])
        self.assertEqual(rule_tag["group"], "default_style")

    def test_initializes_excellent_film_beat_empty_tags_idempotently(self) -> None:
        with workspace_tempdir("knowledge-store-") as temp_dir:
            store = UserKnowledgeStore(temp_dir)
            tags = store.list_tags()
            film_tags = [tag for tag in tags if tag["group"] == "excellent_film_beat"]
            first = next(tag for tag in film_tags if tag["id"] == "excellent_film_beat_001")
            last = next(tag for tag in film_tags if tag["id"] == "excellent_film_beat_050")
            store.update_tag("excellent_film_beat_001", {"stage_prompts": {"basic": "用户填写内容"}, "name": "用户改名"})
            store.ensure_initialized()
            after = store.list_tags()
            after_film_tags = [tag for tag in after if tag["group"] == "excellent_film_beat"]
            updated = next(tag for tag in after_film_tags if tag["id"] == "excellent_film_beat_001")

        self.assertEqual(len(film_tags), 50)
        self.assertEqual(first["name"], "40岁的老处男")
        self.assertEqual(last["name"], "醉酒俏佳人")
        self.assertEqual(first["source"], "save_the_cat_film_beat")
        self.assertTrue(all(value == "" for value in first["stage_prompts"].values()))
        self.assertEqual(len(after_film_tags), 50)
        self.assertEqual(updated["name"], "用户改名")
        self.assertEqual(updated["stage_prompts"]["basic"], "用户填写内容")
        self.assertIn("script_text", updated["stage_prompts"])

    def test_migrates_legacy_prompt_text_to_stage_prompts(self) -> None:
        with workspace_tempdir("knowledge-store-") as temp_dir:
            tags_path = Path(temp_dir) / "tags.json"
            tags_path.parent.mkdir(parents=True, exist_ok=True)
            tags_path.write_text(json.dumps([
                {
                    "id": "custom-legacy",
                    "name": "旧标签",
                    "category": "自定义",
                    "builtin": False,
                    "prompt_text": "旧版通用偏好",
                    "enabled": True,
                }
            ], ensure_ascii=False), encoding="utf-8")
            store = UserKnowledgeStore(temp_dir)
            tag = next(item for item in store.list_tags() if item["id"] == "custom-legacy")

        self.assertEqual(tag["prompt_text"], "旧版通用偏好")
        self.assertEqual(tag["group"], "user_custom")
        self.assertEqual(tag["stage_prompts"]["basic"], "")
        self.assertEqual(tag["stage_prompts"]["package"], "")
        self.assertEqual(tag["stage_prompts"]["script_text"], "")

    def test_apply_tags_allows_empty_selection(self) -> None:
        with workspace_tempdir("knowledge-store-") as temp_dir:
            store = UserKnowledgeStore(temp_dir)
            result = store.apply_tags([], existing_user_preference="保留原偏好")

        self.assertEqual(result["selected_tags"], [])
        self.assertEqual(result["merged_preference_prompt"], "保留原偏好")
        self.assertEqual(result["tag_prompt_text"], "")
        self.assertTrue(all(value == "" for value in result["stage_prompts"].values()))

    def test_apply_tags_returns_metadata_without_merging_prompt_text(self) -> None:
        with workspace_tempdir("knowledge-store-") as temp_dir:
            store = UserKnowledgeStore(temp_dir)
            tag_ids = [tag["id"] for tag in store.list_tags()[:2]]
            result = store.apply_tags(tag_ids, existing_user_preference="用户手写偏好")

        self.assertEqual(result["merged_preference_prompt"], "用户手写偏好")
        self.assertNotIn("来自智慧库标签", result["merged_preference_prompt"])
        self.assertIn("【", result["tag_prompt_text"])
        self.assertEqual(len(result["selected_tags"]), 2)
        self.assertIn("basic", result["stage_prompts"])
        self.assertIn("【", result["stage_prompts"]["worldview"])
        self.assertNotIn("{'", result["merged_preference_prompt"])


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
        builtin = next(tag for tag in payload["tags"] if tag["builtin"])
        self.assertIn("stage_prompts", builtin)
        self.assertIn("package", builtin["stage_prompts"])

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
        self.assertIn("stage_prompts", tag)
        self.assertEqual(tag["stage_prompts"]["script_text"], "")

    def test_update_custom_tag(self) -> None:
        created = self.client.post(
            "/api/user-knowledge/tags",
            headers=self.headers,
            json={"name": "待编辑", "prompt_text": "旧偏好"},
        ).get_json()["tag"]

        response = self.client.patch(
            f"/api/user-knowledge/tags/{created['id']}",
            headers=self.headers,
            json={
                "name": "已编辑",
                "category": "结构",
                "description": "新描述",
                "prompt_text": "新通用偏好",
                "stage_prompts": {"worldview": "新世界观偏好"},
                "enabled": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        tag = response.get_json()["tag"]
        self.assertEqual(tag["name"], "已编辑")
        self.assertEqual(tag["stage_prompts"]["worldview"], "新世界观偏好")

    def test_delete_custom_tag_disables_it(self) -> None:
        created = self.client.post(
            "/api/user-knowledge/tags",
            headers=self.headers,
            json={"name": "待删除", "prompt_text": "偏好"},
        ).get_json()["tag"]

        response = self.client.delete(f"/api/user-knowledge/tags/{created['id']}", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["tag"]["enabled"])

    def test_builtin_tag_can_update_stage_prompts(self) -> None:
        builtin = next(tag for tag in self.store.list_tags() if tag["builtin"])

        response = self.client.patch(
            f"/api/user-knowledge/tags/{builtin['id']}",
            headers=self.headers,
            json={
                "name": "可编辑默认标签",
                "stage_prompts": {"worldview": "只改世界观阶段"},
            },
        )

        self.assertEqual(response.status_code, 200)
        tag = response.get_json()["tag"]
        self.assertTrue(tag["builtin"])
        self.assertEqual(tag["name"], "可编辑默认标签")
        self.assertEqual(tag["stage_prompts"]["worldview"], "只改世界观阶段")

    def test_apply_tags_api_empty_selection(self) -> None:
        response = self.client.post(
            "/api/user-knowledge/apply-tags",
            headers=self.headers,
            json={"selected_tag_ids": [], "existing_user_preference": ""},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["selected_tags"], [])
        self.assertTrue(all(value == "" for value in payload["stage_prompts"].values()))

    def test_apply_tags_api_multiple_tags_returns_stage_prompts(self) -> None:
        tag_ids = [tag["id"] for tag in self.store.list_tags()[:2]]

        response = self.client.post(
            "/api/user-knowledge/apply-tags",
            headers=self.headers,
            json={"selected_tag_ids": tag_ids, "existing_user_preference": "原偏好"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["merged_preference_prompt"], "原偏好")
        self.assertEqual(len(payload["selected_tags"]), 2)
        self.assertIn("【", payload["stage_prompts"]["beat"])

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

    def test_framework_planner_stage_keeps_stage_prompts_payload(self) -> None:
        stage_prompts = {"worldview": "阶段二偏好", "character": "阶段三偏好"}
        fake_payload = {"ok": True, "stage": "02", "data": {"worldview_plan": {}}, "display_text": ""}
        with patch("workflow_code_skeleton.app.server.run_framework_planner_stage", return_value=fake_payload) as mocked:
            response = self.client.post(
                "/api/framework-planner/stage/02",
                headers=self.headers,
                json={
                    "source_brief": {},
                    "prompt_preferences": {"stage_prompts": stage_prompts},
                    "selected_preference_tags": [],
                    "selected_preference_tag_ids": [],
                },
            )

        self.assertEqual(response.status_code, 200)
        input_payload = mocked.call_args.args[1]
        self.assertEqual(input_payload["prompt_preferences"]["stage_prompts"]["worldview"], "阶段二偏好")
        self.assertEqual(input_payload["user_knowledge_stage_prompts"]["worldview"], "阶段二偏好")
        self.assertEqual(input_payload["stage_preference_prompt"], "阶段二偏好")
        self.assertEqual(input_payload["user_preference_prompt"], "阶段二偏好")

    def test_framework_planner_stage_resolves_full_tags_from_ids(self) -> None:
        fake_payload = {"ok": True, "stage": "07", "data": {"framework_plan_package": {}}, "display_text": ""}
        with patch("workflow_code_skeleton.app.server.run_framework_planner_stage", return_value=fake_payload) as mocked:
            response = self.client.post(
                "/api/framework-planner/stage/07",
                headers=self.headers,
                json={
                    "source_brief": {},
                    "selected_preference_tag_ids": ["builtin-规则怪谈"],
                    "selected_preference_tags": [],
                    "prompt_preferences": {"stage_prompts": {"scene": "", "script_text": ""}},
                },
            )

        self.assertEqual(response.status_code, 200)
        input_payload = mocked.call_args.args[1]
        self.assertEqual(input_payload["selected_preference_tag_ids"], ["builtin-规则怪谈"])
        self.assertEqual(input_payload["selected_preference_tags"][0]["id"], "builtin-规则怪谈")
        prompts = input_payload["prompt_preferences"]["stage_prompts"]
        for key in ("scene", "appearance", "episode", "conflict", "script_text"):
            self.assertGreater(len(prompts[key]), 0)

    def test_resolve_stage_preference_prompt_uses_only_current_stage(self) -> None:
        payload = {
            "user_knowledge_stage_prompts": {
                "basic": "阶段一",
                "worldview": "阶段二",
                "character": "阶段三",
                "beat": "阶段四",
                "storylines": "阶段五",
                "guide": "阶段六",
                "package": "阶段七",
            },
            "user_preference_prompt": "全局兜底",
        }

        self.assertEqual(framework_planner_service.resolve_stage_preference_prompt("01", payload), "阶段一")
        self.assertEqual(framework_planner_service.resolve_stage_preference_prompt("04", payload), "阶段四")
        self.assertEqual(framework_planner_service.resolve_stage_preference_prompt("07", payload), "阶段七")
        self.assertNotIn("阶段二", framework_planner_service.resolve_stage_preference_prompt("01", payload))

    def test_resolve_stage_preference_prompt_fallback_order(self) -> None:
        payload = {
            "prompt_preferences": {"stage_prompts": {"character": "prompt_preferences 三阶段"}},
            "user_preference_prompt": "全局兜底",
        }

        self.assertEqual(
            framework_planner_service.resolve_stage_preference_prompt("03", payload),
            "prompt_preferences 三阶段",
        )
        self.assertEqual(
            framework_planner_service.resolve_stage_preference_prompt("06", payload),
            "全局兜底",
        )

    def test_stage07_package_sanitizer_removes_fastgpt_internal_keys(self) -> None:
        package = framework_planner_service._sanitize_framework_plan_package(
            {
                "framework_plan_package": {
                    "title": "最终策划",
                    "d3ixvj8d": "{\"polluted\": true}",
                    "sections": [{"name": "结构"}],
                }
            }
        )

        self.assertIsInstance(package, dict)
        self.assertNotIn("d3ixvj8d", package)
        self.assertIsInstance(package["beat_checkpoint_timeline"], list)
        self.assertIsInstance(package["character_storylines"], list)

    def test_stage07_package_repair_keeps_full_stage_prompts(self) -> None:
        payload_prompts = {
            "scene": "08 场景偏好",
            "appearance": "09 外观偏好",
            "episode": "10 分集偏好",
            "conflict": "11 冲突偏好",
            "script_text": "12 正文偏好",
        }
        repaired = framework_planner_service._repair_stage_output_with_payload(
            "07",
            {"framework_plan_package": {"source_brief": {}}},
            {
                "user_knowledge_stage_prompts": payload_prompts,
                "prompt_preferences": {"stage_prompts": {"scene": ""}},
            },
        )

        package = repaired["framework_plan_package"]
        for key, expected in payload_prompts.items():
            self.assertEqual(package["stage_prompts"][key], expected)
            self.assertEqual(package["prompt_preferences"]["stage_prompts"][key], expected)


if __name__ == "__main__":
    unittest.main()
