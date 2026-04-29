from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from workflow_code_skeleton.app.services import simple_fastgpt_tools as tools


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, payload=None, text: str = "", reason: str = "OK") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.reason = reason

    def json(self):
        return self._payload


class SimpleFastGPTToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        tools._resolved_tool.cache_clear()
        tools._workflow_json_dir.cache_clear()

    def test_list_simple_tools_uses_workflow_json_for_schema(self) -> None:
        tool_map = {item["tool_id"]: item for item in tools.list_simple_tools()}

        self.assertEqual(
            set(tool_map),
            {"hot_review", "reskin", "punchup", "character_reskin"},
        )
        self.assertEqual(tool_map["hot_review"]["workflow_json_file"], "爆款文审核.json")
        self.assertEqual(tool_map["reskin"]["workflow_json_file"], "换皮.json")
        self.assertEqual(tool_map["punchup"]["workflow_json_file"], "增加爽感.json")
        self.assertEqual(tool_map["character_reskin"]["workflow_json_file"], "只换人设.json")
        self.assertEqual(tool_map["hot_review"]["source"], "fallback")
        self.assertEqual(tool_map["hot_review"]["fields"][0]["name"], "text")
        self.assertIn("ju_ben_biao_ti", tool_map["reskin"]["input_variables"])
        self.assertIn("a1LYQ4vP", tool_map["punchup"]["input_variables"])
        self.assertIn("n5ZHYrj8", tool_map["character_reskin"]["input_variables"])

    def test_run_simple_tool_returns_answernode_content_for_user(self) -> None:
        captured: dict[str, object] = {}

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["body"] = json or {}
            captured["timeout"] = timeout
            return _FakeResponse(
                payload={
                    "choices": [
                        {
                            "message": {
                                "content": "审核结果：建议补强前两集冲突和人设记忆点。"
                            }
                        }
                    ]
                }
            )

        with patch.dict(
            os.environ,
            {
                "FASTGPT_HOT_REVIEW_API_KEY": "tool-key",
                "FASTGPT_HOT_REVIEW_CHAT_COMPLETIONS_URL": "https://tools.example.com/api/v1/chat/completions",
            },
            clear=False,
        ):
            with patch.object(tools.requests, "post", side_effect=_fake_post):
                result = tools.run_simple_tool("hot_review", {"text": "测试正文"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["tool_id"], "hot_review")
        self.assertEqual(result["output"], "审核结果：建议补强前两集冲突和人设记忆点。")
        self.assertEqual(result["output_type"], "text")
        self.assertEqual(captured["url"], "https://tools.example.com/api/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer tool-key")
        self.assertEqual(captured["body"]["messages"][0]["content"], "测试正文")
        self.assertEqual(result["debug"]["chosen_output_source"], "choices[0].message.content")

    def test_run_simple_tool_reports_missing_required_fields(self) -> None:
        with self.assertRaisesRegex(tools.ToolExecutionError, "缺少必填项"):
            tools.run_simple_tool("hot_review", {})


if __name__ == "__main__":
    unittest.main()
