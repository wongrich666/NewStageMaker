from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
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

    def _new_framework_payload(self) -> dict[str, object]:
        return {
            "story": "一个律师被迫和宿敌联手，追查一桩二十年前的旧案。",
            "character_count": 4,
            "story_scale": "连载爆款短剧",
            "total_episodes": 60,
            "genre_tone": "悬疑复仇",
            "target_audience": "短剧爽感",
        }

    def test_list_simple_tools_uses_local_workflow_json_and_overrides(self) -> None:
        tool_map = {item["tool_id"]: item for item in tools.list_simple_tools()}

        self.assertEqual(
            set(tool_map),
            {"hot_review", "reskin", "punchup", "character_reskin", "new_framework"},
        )
        self.assertEqual(tool_map["hot_review"]["workflow_json_file"], "爆款文审核.json")
        self.assertEqual(tool_map["hot_review"]["source"], "tool_definition")
        self.assertEqual(tool_map["hot_review"]["fields"][0]["name"], "review_text")
        self.assertEqual(tool_map["hot_review"]["output_variables"], [])
        self.assertEqual(tool_map["reskin"]["workflow_json_file"], "换皮.json")
        self.assertEqual(tool_map["reskin"]["source"], "tool_definition")
        self.assertEqual(
            [field["name"] for field in tool_map["reskin"]["fields"]],
            [
                "title",
                "source_outline",
                "core_scenes",
                "source_characters",
                "source_script",
                "target_style",
                "total_episodes",
                "episode_word_count",
            ],
        )
        self.assertEqual(tool_map["reskin"]["output_variables"][0], "final_output_text")
        self.assertIn("tc3kZbQz", tool_map["reskin"]["output_variables"])
        self.assertEqual(tool_map["new_framework"]["workflow_json_file"], "15内容新框架编写.json")
        self.assertEqual(tool_map["new_framework"]["run_url"], "/api/tools/new-framework")
        self.assertEqual(tool_map["new_framework"]["title"], "15节拍剧本框架")

    def test_diagnose_hot_review_missing_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            diagnosis = tools.diagnose_simple_tool_environment("hot_review")

        self.assertEqual(diagnosis["tool_key"], "hot_review")
        self.assertEqual(diagnosis["api_env"], "FASTGPT_HOT_REVIEW_API_KEY")
        self.assertFalse(diagnosis["api_key_present"])
        self.assertEqual(diagnosis["api_key_length"], 0)
        self.assertEqual(diagnosis["api_key_source"], "missing")
        self.assertTrue(diagnosis["workflow_json_exists"])
        self.assertIn("td2X8WXX", diagnosis["expected_variable_keys"])

    def test_hot_review_missing_api_key_raises_clear_error_without_request(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(tools.requests, "post") as mocked_post:
                with self.assertRaisesRegex(
                    tools.ToolExecutionError,
                    "当前 Python 进程未读取到 FASTGPT_HOT_REVIEW_API_KEY",
                ):
                    tools.run_simple_tool("hot_review", {"review_text": "待审核正文"})

        mocked_post.assert_not_called()

    def test_diagnose_hot_review_uses_dedicated_key_without_leaking_value(self) -> None:
        secret = "fastgpt-secret-123456"
        with patch.dict(
            os.environ,
            {
                "FASTGPT_HOT_REVIEW_API_KEY": secret,
                "FASTGPT_CHAT_COMPLETIONS_URL": "https://tools.example.com/api/v1/chat/completions",
            },
            clear=True,
        ):
            diagnosis = tools.diagnose_simple_tool_environment("hot_review")
            with patch.object(
                tools.requests,
                "post",
                return_value=_FakeResponse(payload={"answerText": "审核报告"}),
            ):
                with patch.object(tools.logger, "info") as mocked_info:
                    result = tools.run_simple_tool("hot_review", {"review_text": "待审核正文"})

        self.assertTrue(diagnosis["api_key_present"])
        self.assertEqual(diagnosis["api_key_length"], len(secret))
        self.assertEqual(diagnosis["api_key_source"], "dedicated")
        self.assertEqual(result["text"], "审核报告")
        serialized = json.dumps(
            {"diagnosis": diagnosis, "logs": [str(call) for call in mocked_info.call_args_list]},
            ensure_ascii=False,
        )
        self.assertNotIn(secret, serialized)

    def test_diagnose_hot_review_reports_global_fallback_source(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FASTGPT_API_KEY": "global-fastgpt-key",
            },
            clear=True,
        ):
            diagnosis = tools.diagnose_simple_tool_environment("hot_review")

        self.assertTrue(diagnosis["api_key_present"])
        self.assertEqual(diagnosis["api_key_source"], "fallback_global")
        self.assertEqual(diagnosis["api_key_env_used"], "FASTGPT_API_KEY")

    def test_hot_review_maps_all_supported_aliases_to_td2X8WXX(self) -> None:
        aliases = ("text", "content", "script", "input", "story", "review_text", "source_text")
        for alias in aliases:
            captured: dict[str, object] = {}

            def _fake_post(url, *, headers=None, json=None, timeout=None):
                captured["url"] = url
                captured["headers"] = headers or {}
                captured["body"] = json or {}
                captured["timeout"] = timeout
                return _FakeResponse(payload={"answerText": "审核意见"})

            with self.subTest(alias=alias):
                with patch.dict(
                    os.environ,
                    {
                        "FASTGPT_HOT_REVIEW_API_KEY": "tool-key",
                    },
                    clear=True,
                ):
                    with patch.object(tools.requests, "post", side_effect=_fake_post):
                        result = tools.run_simple_tool("hot_review", {alias: "测试正文"})

                self.assertEqual(captured["body"]["variables"]["td2X8WXX"], "测试正文")
                self.assertEqual(result["text"], "审核意见")
                self.assertTrue(result["filename"].startswith("爆款文审核意见_"))

    def test_hot_review_empty_input_does_not_call_fastgpt(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FASTGPT_HOT_REVIEW_API_KEY": "tool-key",
            },
            clear=True,
        ):
            with patch.object(tools.requests, "post") as mocked_post:
                with self.assertRaisesRegex(tools.ToolExecutionError, "缺少必填项"):
                    tools.run_simple_tool("hot_review", {"text": "   "})

        mocked_post.assert_not_called()

    def test_reskin_maps_payload_to_workflow_variables_and_prefers_final_output(self) -> None:
        captured: dict[str, object] = {}

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["body"] = json or {}
            captured["timeout"] = timeout
            return _FakeResponse(
                payload={
                    "newVariables": {
                        "source_dna": "中间过程",
                        "final_output_text": "最终换皮剧本",
                        "tc3kZbQz": "备用最终剧本",
                    },
                    "answerText": "answerText 兜底",
                }
            )

        with patch.dict(
            os.environ,
            {
                "FASTGPT_RESKIN_API_KEY": "reskin-key",
            },
            clear=True,
        ):
            with patch.object(tools.requests, "post", side_effect=_fake_post):
                result = tools.run_simple_tool(
                    "reskin",
                    {
                        "title": "雪夜回响",
                        "source_outline": "源故事梗概",
                        "core_scenes": "源核心场景",
                        "source_characters": "源人物小传",
                        "target_style": "都市悬疑复仇",
                    },
                )

        variables = captured["body"]["variables"]
        self.assertEqual(variables["ju_ben_biao_ti"], "雪夜回响")
        self.assertEqual(variables["yuan_juben_genggai"], "源故事梗概")
        self.assertEqual(variables["hexin_changjing"], "源核心场景")
        self.assertEqual(variables["renwu_xiaozhuan"], "源人物小传")
        self.assertEqual(variables["mubiao_fengge"], "都市悬疑复仇")
        self.assertEqual(variables["zong_jishu"], 60)
        self.assertEqual(variables["meiji_zishu"], 600)
        self.assertNotIn("juben_zhengwen", variables)
        self.assertEqual(result["text"], "最终换皮剧本")
        self.assertEqual(result["debug"]["chosen_output_source"], "newVariables.final_output_text")
        self.assertEqual(result["filename"], "换皮剧本_雪夜回响.txt")

    def test_reskin_accepts_workflow_variable_alias_payload(self) -> None:
        captured: dict[str, object] = {}

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, timeout
            captured["body"] = json or {}
            return _FakeResponse(payload={"newVariables": {"tc3kZbQz": "最终剧本"}})

        with patch.dict(
            os.environ,
            {
                "FASTGPT_RESKIN_API_KEY": "reskin-key",
            },
            clear=True,
        ):
            with patch.object(tools.requests, "post", side_effect=_fake_post):
                result = tools.run_simple_tool(
                    "reskin",
                    {
                        "ju_ben_biao_ti": "镜中人",
                        "yuan_juben_genggai": "旧梗概",
                        "renwu_xiaozhuan": "旧人设",
                        "mubiao_fengge": "古装权谋",
                        "zong_jishu": 24,
                        "meiji_zishu": 800,
                    },
                )

        variables = captured["body"]["variables"]
        self.assertEqual(variables["ju_ben_biao_ti"], "镜中人")
        self.assertEqual(variables["zong_jishu"], 24)
        self.assertEqual(variables["meiji_zishu"], 800)
        self.assertEqual(result["text"], "最终剧本")

    def test_reskin_missing_required_input_does_not_call_fastgpt(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FASTGPT_RESKIN_API_KEY": "reskin-key",
            },
            clear=True,
        ):
            with patch.object(tools.requests, "post") as mocked_post:
                with self.assertRaisesRegex(tools.ToolExecutionError, "缺少必填项"):
                    tools.run_simple_tool(
                        "reskin",
                        {
                            "title": "缺少人物",
                            "source_outline": "源故事梗概",
                            "target_style": "都市情感",
                        },
                    )

        mocked_post.assert_not_called()

    def test_hot_review_extracts_root_answer_text(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FASTGPT_HOT_REVIEW_API_KEY": "tool-key",
            },
            clear=True,
        ):
            with patch.object(
                tools.requests,
                "post",
                return_value=_FakeResponse(payload={"answerText": "根节点 answerText"}),
            ):
                result = tools.run_simple_tool("hot_review", {"review_text": "测试正文"})

        self.assertEqual(result["text"], "根节点 answerText")
        self.assertEqual(result["debug"]["chosen_output_source"], "root.answerText")

    def test_hot_review_extracts_choice_content(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FASTGPT_HOT_REVIEW_API_KEY": "tool-key",
            },
            clear=True,
        ):
            with patch.object(
                tools.requests,
                "post",
                return_value=_FakeResponse(
                    payload={"choices": [{"message": {"content": "choice 内容"}}]},
                ),
            ):
                result = tools.run_simple_tool("hot_review", {"review_text": "测试正文"})

        self.assertEqual(result["text"], "choice 内容")
        self.assertEqual(result["debug"]["chosen_output_source"], "choices[0].message.content")

    def test_hot_review_extracts_response_data_outputs_answer_text(self) -> None:
        payload = {
            "responseData": [
                {
                    "outputs": {
                        "answerText": "responseData outputs answerText"
                    }
                }
            ]
        }
        with patch.dict(
            os.environ,
            {
                "FASTGPT_HOT_REVIEW_API_KEY": "tool-key",
            },
            clear=True,
        ):
            with patch.object(tools.requests, "post", return_value=_FakeResponse(payload=payload)):
                result = tools.run_simple_tool("hot_review", {"review_text": "测试正文"})

        self.assertEqual(result["text"], "responseData outputs answerText")
        self.assertEqual(result["debug"]["chosen_output_source"], "responseData[0].outputs.answerText")

    def test_hot_review_extracts_response_data_outputs_text(self) -> None:
        payload = {
            "responseData": [
                {
                    "outputs": {
                        "text": "responseData outputs text"
                    }
                }
            ]
        }
        with patch.dict(
            os.environ,
            {
                "FASTGPT_HOT_REVIEW_API_KEY": "tool-key",
            },
            clear=True,
        ):
            with patch.object(tools.requests, "post", return_value=_FakeResponse(payload=payload)):
                result = tools.run_simple_tool("hot_review", {"review_text": "测试正文"})

        self.assertEqual(result["text"], "responseData outputs text")
        self.assertEqual(result["debug"]["chosen_output_source"], "responseData[0].outputs.text")

    def test_new_framework_prefers_beat_framework_contract_variable(self) -> None:
        payload = {
            "newVariables": {
                "beatFrameworkContractJson": "正式 15 节拍正文"
            },
            "answerText": "备用 answerText",
        }
        with patch.dict(
            os.environ,
            {
                "FASTGPT_NEW_FRAMEWORK_API_KEY": "framework-key",
            },
            clear=True,
        ):
            with patch.object(tools.requests, "post", return_value=_FakeResponse(payload=payload)):
                result = tools.run_simple_tool("new_framework", self._new_framework_payload())

        self.assertEqual(result["text"], "正式 15 节拍正文")
        self.assertEqual(result["debug"]["chosen_output_source"], "newVariables.beatFrameworkContractJson")

    def test_new_framework_falls_back_to_answer_text(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FASTGPT_NEW_FRAMEWORK_API_KEY": "framework-key",
            },
            clear=True,
        ):
            with patch.object(
                tools.requests,
                "post",
                return_value=_FakeResponse(payload={"answerText": "answerText 兜底"}),
            ):
                result = tools.run_simple_tool("new_framework", self._new_framework_payload())

        self.assertEqual(result["text"], "answerText 兜底")
        self.assertEqual(result["debug"]["chosen_output_source"], "root.answerText")

    def test_new_framework_falls_back_to_choices_content(self) -> None:
        payload = {"choices": [{"message": {"content": "choices 兜底"}}]}
        with patch.dict(
            os.environ,
            {
                "FASTGPT_NEW_FRAMEWORK_API_KEY": "framework-key",
            },
            clear=True,
        ):
            with patch.object(tools.requests, "post", return_value=_FakeResponse(payload=payload)):
                result = tools.run_simple_tool("new_framework", self._new_framework_payload())

        self.assertEqual(result["text"], "choices 兜底")
        self.assertEqual(result["debug"]["chosen_output_source"], "choices[0].message.content")

    def test_new_framework_workflow_json_uses_natural_language_output_settings(self) -> None:
        workflow_path = Path(
            r"C:\Users\Administrator\PycharmProjects\new_scriptmaker\workflow_jsons\15内容新框架编写.json"
        )
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        target_node = next(node for node in workflow["nodes"] if node.get("nodeId") == "beatFrameworkPureAi001")
        node_inputs = {item["key"]: item.get("value") for item in target_node.get("inputs", [])}
        variable = next(
            item for item in workflow["chatConfig"]["variables"] if item.get("key") == "beatFrameworkContractJson"
        )

        self.assertEqual(target_node["name"], "15节拍剧本框架自然语言生成")
        self.assertEqual(node_inputs["maxToken"], 32000)
        self.assertFalse(node_inputs["aiChatVision"])
        self.assertFalse(node_inputs["aiChatReasoning"])
        self.assertEqual(node_inputs["aiChatResponseFormat"], "")
        self.assertEqual(node_inputs["aiChatJsonSchema"], "")
        self.assertIn("不要返回空内容", node_inputs["userChatInput"])
        self.assertEqual(variable["label"], "15节拍框架文本")
        self.assertIn("正式自然语言文本", variable["description"])

    def test_new_framework_retries_after_empty_output_then_succeeds(self) -> None:
        request_bodies: list[dict[str, object]] = []
        responses = [
            _FakeResponse(payload={}),
            _FakeResponse(payload={"answerText": "第二次成功返回正文"}),
        ]

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, timeout
            request_bodies.append(json or {})
            return responses.pop(0)

        with patch.dict(
            os.environ,
            {
                "FASTGPT_NEW_FRAMEWORK_API_KEY": "framework-key",
            },
            clear=True,
        ):
            with patch.object(tools.requests, "post", side_effect=_fake_post) as mocked_post:
                result = tools.run_simple_tool("new_framework", self._new_framework_payload())

        self.assertEqual(mocked_post.call_count, 2)
        self.assertEqual(result["text"], "第二次成功返回正文")
        self.assertEqual(len(request_bodies), 2)
        self.assertNotEqual(
            request_bodies[0]["messages"][0]["content"],
            request_bodies[1]["messages"][0]["content"],
        )
        self.assertIn("不要返回空内容", request_bodies[1]["messages"][0]["content"])

    def test_new_framework_repeated_empty_output_writes_debug_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            with patch.dict(
                os.environ,
                {
                    "FASTGPT_NEW_FRAMEWORK_API_KEY": "framework-key",
                },
                clear=True,
            ):
                with patch.object(
                    tools.requests,
                    "post",
                    return_value=_FakeResponse(payload={}),
                ) as mocked_post:
                    with patch.object(tools, "get_runtime_data_dir", return_value=runtime_root):
                        with self.assertRaisesRegex(
                            tools.ToolExecutionError,
                            "15节拍剧本框架没有返回可展示结果",
                        ) as ctx:
                            tools.run_simple_tool("new_framework", self._new_framework_payload())

            self.assertEqual(mocked_post.call_count, 3)
            artifact_files = sorted((runtime_root / "debug" / "simple_tools").glob("new_framework__*.json"))
            self.assertEqual(len(artifact_files), 1)
            artifact = json.loads(artifact_files[0].read_text(encoding="utf-8"))
            self.assertEqual(artifact["tool_key"], "new_framework")
            self.assertEqual(artifact["final_failure_reason"], "empty_output")
            self.assertEqual(len(artifact["retry_attempts"]), 3)
            self.assertTrue(ctx.exception.debug.get("debug_artifact_path", "").endswith(".json"))


if __name__ == "__main__":
    unittest.main()
