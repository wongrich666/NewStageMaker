from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import requests

from workflow_code_skeleton.app.config import settings
from workflow_code_skeleton.app.services.fastgpt_client import (
    FastGPTClient,
    FastGPTEndpoint,
    FastGPTTransientError,
    logger as fastgpt_client_logger,
)
from workflow_code_skeleton.app.services.fastgpt_contracts import (
    CHARACTER_COUNT,
    EPISODE_PLAN,
    SCRIPT_TITLE,
    STAGE_FRAMEWORK,
    STORY_OUTLINE,
    TOTAL_EPISODES,
    USER_CHARACTERS,
    USER_EXPECTATION,
    USER_SCENES,
    contract_for,
)


class _FakeResponse:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data
        self.status_code = 200
        self.reason = "OK"
        self.text = json.dumps(data, ensure_ascii=False)

    def json(self) -> dict[str, object]:
        return self._data

    def raise_for_status(self) -> None:
        return None


class _QueuedFastGPTClient(FastGPTClient):
    def __init__(self, responses: list[dict[str, object]]) -> None:
        super().__init__()
        self._responses = list(responses)
        self.request_count = 0

    def _endpoint_for(self, stage_name: str):  # type: ignore[override]
        return FastGPTEndpoint(
            url="https://example.test/api/v1/chat/completions",
            url_source="test",
            api_key="test-key",
            api_key_source="test",
            chat_id=f"test-{stage_name}-{self.request_count + 1}",
            timeout=30,
        )

    def _post_with_retries(self, endpoint, headers, body, stage_name):  # type: ignore[override]
        del endpoint, headers, body, stage_name
        self.request_count += 1
        if not self._responses:
            raise AssertionError("No fake FastGPT response left for test")
        return _FakeResponse(self._responses.pop(0))


def _framework_inputs() -> dict[str, object]:
    return {
        TOTAL_EPISODES: 10,
        USER_EXPECTATION: "都市情感悬疑短剧",
        CHARACTER_COUNT: 4,
    }


def _framework_payload(*, title_key: str = "script_title") -> dict[str, object]:
    return {
        title_key: "长夜回潮",
        STORY_OUTLINE: {
            "opening": "主角被迫回到早已断联的故乡。",
            "inciting_incident": "一宗旧案重启调查。",
            "early_goal": "先查清失踪者最后出现的位置。",
            "middle_escalation": "线索指向主角最亲近的人。",
            "relationship_changes": "盟友与嫌疑人的边界开始崩塌。",
            "larger_crisis_or_truth": "旧案牵出更大的利益链。",
            "late_direction": "主角决定公开站到对立面。",
            "final_climax": "真相在众人面前被逼出水面。",
            "ending_resolution": "主角付出代价后完成收束。",
            "theme": "真相、代价与重新选择。",
        },
        USER_CHARACTERS: [
            {
                "name": "林夏",
                "role_type": "主角",
                "identity": "返乡记者",
                "personality": "克制敏锐",
                "core_desire": "查明真相",
                "deep_motivation": "弥补当年的缺席",
                "strengths": "调查能力强",
                "weaknesses": "不愿示弱",
                "appearance_anchor": "总穿深色风衣",
                "relationship_to_protagonist": "本人",
                "relationships_with_others": "与故友既亲近又防备",
                "growth_arc": "学会在真相和情感之间承担后果",
                "plot_function": "推动主线调查",
            }
        ],
        USER_SCENES: {
            "era_background": "当代沿海小城",
            "world_state": "熟人社会下消息传播极快",
            "core_locations": [
                {
                    "name": "旧码头",
                    "function": "案件关键地点",
                    "conflict_soil": "适合目击、跟踪与围堵",
                    "key_characters": ["林夏"],
                }
            ],
            "rules": "熟人关系会迅速影响线索流向",
            "danger_sources": "旧势力掩盖真相",
            "resource_or_stakes": "警方线索与舆论窗口",
            "power_distribution": "地方势力控制多数资源",
            "special_rules": "",
            "overall_atmosphere": "潮湿、压抑、彼此试探",
        },
        EPISODE_PLAN: [
            {
                "episode": 1,
                "title": "回到故乡",
                "main_plot": "主角返乡后重新接触旧案线索。",
                "conflicts": ["同乡排斥", "旧友隐瞒", "线索中断"],
                "ending_hook": "主角收到匿名短信。",
            }
        ],
    }


class FastGPTClientFrameworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_reruns = settings.fastgpt_stage_local_restart_retries
        self._original_http_retries = settings.fastgpt_http_retries
        settings.fastgpt_stage_local_restart_retries = 0

    def tearDown(self) -> None:
        settings.fastgpt_stage_local_restart_retries = self._original_reruns
        settings.fastgpt_http_retries = self._original_http_retries

    def test_framework_answertext_script_title_alias_normalizes_without_retry(self) -> None:
        response = {
            "responseData": [
                {
                    "answerText": json.dumps(
                        _framework_payload(title_key="script_title"),
                        ensure_ascii=False,
                    )
                }
            ]
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_FRAMEWORK, _framework_inputs())

        self.assertEqual(output[SCRIPT_TITLE], "长夜回潮")
        self.assertIn(STORY_OUTLINE, output)
        self.assertIn(USER_CHARACTERS, output)
        self.assertIn(USER_SCENES, output)
        self.assertIn(EPISODE_PLAN, output)
        self.assertEqual(client.request_count, 1)

    def test_framework_choices_title_alias_normalizes_without_retry(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            _framework_payload(title_key="title"),
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_FRAMEWORK, _framework_inputs())

        self.assertEqual(output[SCRIPT_TITLE], "长夜回潮")
        self.assertEqual(client.request_count, 1)

    def test_framework_newvariables_script_title_alias_normalizes_without_retry(self) -> None:
        payload = _framework_payload(title_key="script_title_content")
        response = {
            "responseData": {
                "newVariables": [
                    {"key": "script_title_content", "value": payload["script_title_content"]},
                    {"key": STORY_OUTLINE, "value": payload[STORY_OUTLINE]},
                    {"key": USER_CHARACTERS, "value": payload[USER_CHARACTERS]},
                    {"key": USER_SCENES, "value": payload[USER_SCENES]},
                    {"key": EPISODE_PLAN, "value": payload[EPISODE_PLAN]},
                ]
            }
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_FRAMEWORK, _framework_inputs())

        self.assertEqual(output[SCRIPT_TITLE], "长夜回潮")
        self.assertEqual(client.request_count, 1)

    def test_framework_frameworkcontractjson_string_wrapper_normalizes_without_retry(self) -> None:
        payload = _framework_payload(title_key="script_title_content")
        response = {
            "responseData": {
                "frameworkContractJson": json.dumps(payload, ensure_ascii=False),
            }
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_FRAMEWORK, _framework_inputs())

        self.assertEqual(output[SCRIPT_TITLE], "长夜回潮")
        self.assertEqual(client.request_count, 1)

    def test_framework_textoutput_string_wrapper_normalizes_without_retry(self) -> None:
        payload = _framework_payload(title_key="script_title_content")
        response = {
            "responseData": {
                "textOutput": json.dumps(payload, ensure_ascii=False),
            }
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_FRAMEWORK, _framework_inputs())

        self.assertEqual(output[SCRIPT_TITLE], "长夜回潮")
        self.assertEqual(client.request_count, 1)

    def test_framework_updatevarresult_frameworkcontractjson_normalizes_without_retry(self) -> None:
        payload = _framework_payload(title_key="script_title_content")
        response = {
            "responseData": {
                "updateVarResult": [
                    {
                        "key": "frameworkContractJson",
                        "value": json.dumps(payload, ensure_ascii=False),
                    }
                ]
            }
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_FRAMEWORK, _framework_inputs())

        self.assertEqual(output[SCRIPT_TITLE], "长夜回潮")
        self.assertEqual(client.request_count, 1)

    def test_framework_response_answertext_mixed_text_extracts_best_json_candidate(self) -> None:
        payload = _framework_payload(title_key="script_title_content")
        mixed = (
            "系统调试信息：{\"note\":\"ignore\"}\n"
            "最终契约如下：\n"
            f"{json.dumps(payload, ensure_ascii=False)}\n"
            "请以此为准。"
        )
        response = {"responseData": [{"answerText": mixed}]}
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_FRAMEWORK, _framework_inputs())

        self.assertEqual(output[SCRIPT_TITLE], "长夜回潮")
        self.assertEqual(client.request_count, 1)

    def test_framework_choices_content_array_uses_text_block_only(self) -> None:
        payload = _framework_payload(title_key="script_title_content")
        response = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {
                                "type": "reasoning",
                                "text": {"content": "{\"passed\": false}"},
                            },
                            {
                                "type": "text",
                                "text": {
                                    "content": json.dumps(payload, ensure_ascii=False)
                                },
                            },
                        ]
                    }
                }
            ]
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_FRAMEWORK, _framework_inputs())

        self.assertEqual(output[SCRIPT_TITLE], "长夜回潮")
        self.assertEqual(client.request_count, 1)

    def test_framework_invalid_output_logs_truncated_preview_and_keeps_raw_response(self) -> None:
        huge = "X" * 5000
        data = {
            "responseData": {
                "answerText": huge,
                "newVariables": [{"key": "debugHuge", "value": huge}],
            },
            "choices": [{"message": {"content": huge}}],
        }
        client = FastGPTClient()
        contract = contract_for(STAGE_FRAMEWORK)

        with patch(
            "workflow_code_skeleton.app.services.fastgpt_client.build_stage_output_fallback",
            return_value=None,
        ):
            with self.assertLogs(fastgpt_client_logger.name, level="ERROR") as logs:
                with self.assertRaises(ValueError):
                    client._extract_output_payload(
                        data,
                        contract,
                        _framework_inputs(),
                        allow_fallback=True,
                    )

        joined = "\n".join(logs.output)
        self.assertNotIn(huge, joined)
        self.assertIn("answerText 预览", joined)
        debug_info = client.get_last_stage_debug_info(STAGE_FRAMEWORK)
        self.assertEqual(debug_info.get("raw_response"), data)
        self.assertIn("candidate_keys", str(debug_info.get("response_preview") or ""))

    def test_post_with_retries_uses_endpoint_timeout_and_raises_transient_on_timeout(self) -> None:
        client = FastGPTClient()
        settings.fastgpt_http_retries = 0
        endpoint = FastGPTEndpoint(
            url="https://example.test/api/v1/chat/completions",
            url_source="test",
            api_key="test-key",
            api_key_source="test",
            chat_id="timeout-test",
            timeout=17,
        )

        with patch("requests.post", side_effect=requests.Timeout("boom")) as mock_post:
            with self.assertRaises(FastGPTTransientError):
                client._post_with_retries(
                    endpoint,
                    {"Authorization": "Bearer test"},
                    {"messages": []},
                    STAGE_FRAMEWORK,
                )

        self.assertEqual(mock_post.call_args.kwargs.get("timeout"), 17)


if __name__ == "__main__":
    unittest.main()
