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


class NewFrameworkToolTests(unittest.TestCase):
    def setUp(self) -> None:
        tools._resolved_tool.cache_clear()
        tools._workflow_json_dir.cache_clear()

    def test_new_framework_maps_user_payload_to_workflow_variables(self) -> None:
        captured: dict[str, object] = {}

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["body"] = json or {}
            captured["timeout"] = timeout
            return _FakeResponse(
                payload={
                    "answerText": "15 节拍框架正文"
                }
            )

        payload = {
            "story": "一个背负旧案的女律师重返故乡，发现父亲之死与地方财团有关。",
            "character_count": 5,
            "story_scale": "",
            "total_episodes": 60,
            "genre_tone": "",
            "target_audience": "",
        }
        with patch.dict(
            os.environ,
            {
                "FASTGPT_NEW_FRAMEWORK_API_KEY": "tool-key",
            },
            clear=False,
        ):
            with patch.object(tools.requests, "post", side_effect=_fake_post):
                result = tools.run_simple_tool("new_framework", payload)

        self.assertTrue(result["ok"])
        variables = captured["body"]["variables"]
        self.assertEqual(variables["wjmWDwbg"], payload["story"])
        self.assertEqual(variables["tsv3A9ac"], 5)
        self.assertEqual(variables["storyScale"], "连载爆款短剧")
        self.assertEqual(variables["bFgF0xfY"], 60)
        self.assertEqual(variables["genreTone"], "")
        self.assertEqual(variables["targetAudience"], "")

    def test_new_framework_prefers_contract_variable_output_over_choices(self) -> None:
        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(
                payload={
                    "newVariables": {
                        "beatFrameworkContractJson": {
                            "script_title_content": "夜行审判"
                        }
                    },
                    "choices": [
                        {
                            "message": {
                                "content": "不应优先使用的 choices 文本"
                            }
                        }
                    ],
                }
            )

        with patch.dict(os.environ, {"FASTGPT_NEW_FRAMEWORK_API_KEY": "tool-key"}, clear=False):
            with patch.object(tools.requests, "post", side_effect=_fake_post):
                result = tools.run_simple_tool(
                    "new_framework",
                    {
                        "story": "测试故事",
                        "character_count": 4,
                        "story_scale": "连载爆款短剧",
                        "total_episodes": 40,
                        "genre_tone": "",
                        "target_audience": "",
                    },
                )

        self.assertEqual(result["output_type"], "json")
        self.assertIn("夜行审判", result["text"])
        self.assertEqual(result["debug"]["chosen_output_source"], "newVariables.beatFrameworkContractJson")
        self.assertTrue(str(result["filename"]).startswith("【新】15内容剧本框架_"))
        self.assertTrue(str(result["filename"]).endswith(".txt"))

    def test_new_framework_accepts_answer_text_fallback(self) -> None:
        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(payload={"answerText": "自然语言版 15 节拍框架"})

        with patch.dict(os.environ, {"FASTGPT_NEW_FRAMEWORK_API_KEY": "tool-key"}, clear=False):
            with patch.object(tools.requests, "post", side_effect=_fake_post):
                result = tools.run_simple_tool(
                    "new_framework",
                    {
                        "story": "测试故事",
                        "character_count": 3,
                        "story_scale": "连载爆款短剧",
                        "total_episodes": 24,
                        "genre_tone": "",
                        "target_audience": "",
                    },
                )

        self.assertEqual(result["text"], "自然语言版 15 节拍框架")
        self.assertEqual(result["debug"]["chosen_output_source"], "root.answerText")

    def test_new_framework_accepts_choices_content_fallback(self) -> None:
        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(
                payload={
                    "choices": [
                        {
                            "message": {
                                "content": "choices 中的 15 节拍框架"
                            }
                        }
                    ]
                }
            )

        with patch.dict(os.environ, {"FASTGPT_NEW_FRAMEWORK_API_KEY": "tool-key"}, clear=False):
            with patch.object(tools.requests, "post", side_effect=_fake_post):
                result = tools.run_simple_tool(
                    "new_framework",
                    {
                        "story": "测试故事",
                        "character_count": 3,
                        "story_scale": "连载爆款短剧",
                        "total_episodes": 24,
                        "genre_tone": "",
                        "target_audience": "",
                    },
                )

        self.assertEqual(result["text"], "choices 中的 15 节拍框架")
        self.assertEqual(result["debug"]["chosen_output_source"], "choices[0].message.content")

    def test_new_framework_validates_story_required(self) -> None:
        with self.assertRaisesRegex(tools.ToolExecutionError, "缺少必填项"):
            tools.run_simple_tool(
                "new_framework",
                {
                    "story": "",
                    "character_count": 3,
                    "story_scale": "连载爆款短剧",
                    "total_episodes": 24,
                    "genre_tone": "",
                    "target_audience": "",
                },
            )

    def test_new_framework_validates_character_count_positive_integer(self) -> None:
        with self.assertRaisesRegex(tools.ToolExecutionError, "character_count"):
            tools.run_simple_tool(
                "new_framework",
                {
                    "story": "测试故事",
                    "character_count": 0,
                    "story_scale": "连载爆款短剧",
                    "total_episodes": 24,
                    "genre_tone": "",
                    "target_audience": "",
                },
            )

    def test_new_framework_validates_total_episodes_positive_integer(self) -> None:
        with self.assertRaisesRegex(tools.ToolExecutionError, "total_episodes"):
            tools.run_simple_tool(
                "new_framework",
                {
                    "story": "测试故事",
                    "character_count": 3,
                    "story_scale": "连载爆款短剧",
                    "total_episodes": -1,
                    "genre_tone": "",
                    "target_audience": "",
                },
            )


if __name__ == "__main__":
    unittest.main()
