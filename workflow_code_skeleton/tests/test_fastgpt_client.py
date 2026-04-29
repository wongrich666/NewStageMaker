from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import requests

from workflow_code_skeleton.app.config import settings
from workflow_code_skeleton.app.services.fastgpt_client import (
    FastGPTClient,
    FastGPTEndpoint,
    FastGPTPayloadTooLargeError,
    FastGPTTransientError,
    logger as fastgpt_client_logger,
)
from workflow_code_skeleton.app.services.fastgpt_contracts import (
    APPEARANCE_MAPPING,
    CHARACTER_COUNT,
    EPISODE_PLAN,
    NORMALIZED_EPISODE_PLAN,
    PASS_REVIEW_JSON,
    SCRIPT_TITLE,
    STAGE_APPEARANCE_ALIAS_GENERATION,
    STAGE_APPEARANCE_ALIAS_REVIEW,
    STAGE_APPEARANCE_ALIAS_REWRITE,
    STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
    STAGE_APPEARANCE_ALIAS_WRITING,
    STAGE_CHARACTERS,
    STAGE_DIALOGUE_REVIEW,
    STAGE_EPISODE_PLAN_NORMALIZE,
    STAGE_FRAMEWORK,
    STAGE_FRAMEWORK_NATURALIZE,
    STAGE_HOOK_REVIEW,
    STAGE_SCENES,
    STAGE_SCRIPT_REVIEW,
    STAGE_WORLDVIEW_NATURALIZE,
    STORY_OUTLINE,
    TOTAL_EPISODES,
    USER_CHARACTERS,
    USER_EXPECTATION,
    USER_SCENES,
    contract_for,
)
from workflow_code_skeleton.app.workflow_ids import (
    APPEARANCE_MAPPING_VAR,
    APPEARANCE_NATURAL_LANGUAGE_VAR,
    APPEARANCE_REVIEW_VAR,
    CHARACTER_NATURAL_LANGUAGE_VAR,
    CHARACTER_VAR,
    SCENE_NATURAL_LANGUAGE_VAR,
    SCENE_VAR,
)
from workflow_code_skeleton.tests.test_stage_output_repair import (
    _appearance_input_variables,
    _appearance_mapping_json,
    _character_setting_json,
    _input_variables,
    _scene_setting_json,
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


def _normalized_episode_plan_payload(total_episodes: int = 10) -> dict[str, object]:
    return {
        "parsed_episode_count": total_episodes,
        "appearance_alias_planning": {},
        "episodes": [
            {
                "episode": episode,
                "title": f"第{episode}集",
                "content": f"第{episode}集主线推进",
                "main_character_aliases": [],
                "appearance_events": [],
                "long_term_stage_flags": [],
                "scene_based_alias_hints": [],
            }
            for episode in range(1, total_episodes + 1)
        ],
    }


def _episode_plan_normalize_inputs(total_episodes: int = 10) -> dict[str, object]:
    framework_payload = _framework_payload()
    return {
        TOTAL_EPISODES: total_episodes,
        STORY_OUTLINE: framework_payload[STORY_OUTLINE],
        USER_CHARACTERS: framework_payload[USER_CHARACTERS],
        EPISODE_PLAN: framework_payload[EPISODE_PLAN],
        "character_alias_naming_rules": "统一使用正式中文名",
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


def _appearance_review_json(
    *,
    passed: bool,
    rewrite_required: bool,
    blocking_issues: list[str] | None = None,
) -> dict[str, object]:
    return {
        "passed": passed,
        "rewrite_required": rewrite_required,
        "summary": "审核通过" if passed else "需要修订",
        "blocking_issues": list(blocking_issues or []),
        "non_blocking_issues": [],
    }


def _pass_review_json(
    *,
    passed: bool,
    rewrite_required: bool,
    summary: str = "",
    blocking_issues: list[str] | None = None,
    non_blocking_issues: list[str] | None = None,
    rewrite_start_episode: int = 1,
    stage: str = "five_episode_continuity_review",
) -> dict[str, object]:
    return {
        "passed": passed,
        "rewrite_required": rewrite_required,
        "summary": summary,
        "blocking_issues": list(blocking_issues or []),
        "non_blocking_issues": list(non_blocking_issues or []),
        "rewrite_start_episode": rewrite_start_episode,
        "stage": stage,
    }


class FastGPTClientFrameworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_reruns = settings.fastgpt_stage_local_restart_retries
        self._original_http_retries = settings.fastgpt_http_retries
        self._original_warn_chars = settings.fastgpt_stage_payload_warn_chars
        self._original_hard_chars = settings.fastgpt_stage_payload_hard_chars
        self._original_characters_detail = settings.fastgpt_characters_detail
        self._original_scenes_detail = settings.fastgpt_scenes_detail
        self._original_appearance_detail = settings.fastgpt_appearance_alias_generation_detail
        settings.fastgpt_stage_local_restart_retries = 0

    def tearDown(self) -> None:
        settings.fastgpt_stage_local_restart_retries = self._original_reruns
        settings.fastgpt_http_retries = self._original_http_retries
        settings.fastgpt_stage_payload_warn_chars = self._original_warn_chars
        settings.fastgpt_stage_payload_hard_chars = self._original_hard_chars
        settings.fastgpt_characters_detail = self._original_characters_detail
        settings.fastgpt_scenes_detail = self._original_scenes_detail
        settings.fastgpt_appearance_alias_generation_detail = self._original_appearance_detail

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

        with self.assertLogs(fastgpt_client_logger.name, level="ERROR") as logs:
            with self.assertRaises(ValueError):
                client._extract_output_payload(
                    data,
                    contract,
                    _framework_inputs(),
                    allow_fallback=False,
                )

        joined = "\n".join(logs.output)
        self.assertNotIn(huge, joined)
        self.assertIn("answerText 预览", joined)
        debug_info = client.get_last_stage_debug_info(STAGE_FRAMEWORK)
        self.assertEqual(debug_info.get("raw_response"), data)
        self.assertIn("candidate_keys", str(debug_info.get("response_preview") or ""))
        self.assertIn("candidate_sources", debug_info)

    def test_episode_plan_normalize_uses_choices_content_when_newvariables_empty(self) -> None:
        response = {
            "responseData": {"newVariables": []},
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                NORMALIZED_EPISODE_PLAN: _normalized_episode_plan_payload(10)
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ],
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(
            STAGE_EPISODE_PLAN_NORMALIZE,
            _episode_plan_normalize_inputs(),
        )

        self.assertEqual(output[NORMALIZED_EPISODE_PLAN]["parsed_episode_count"], 10)
        debug_info = client.get_last_stage_debug_info(STAGE_EPISODE_PLAN_NORMALIZE)
        self.assertIn("choices[0].message.content", str(debug_info.get("candidate_sources") or ""))

    def test_episode_plan_normalize_markdown_code_fence_json_parses(self) -> None:
        fenced = "```json\n" + json.dumps(
            {
                NORMALIZED_EPISODE_PLAN: _normalized_episode_plan_payload(8)
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n```"
        client = FastGPTClient()

        output = client._extract_output_payload(
            {"answerText": fenced},
            contract_for(STAGE_EPISODE_PLAN_NORMALIZE),
            _framework_inputs(),
            allow_fallback=False,
        )

        self.assertEqual(output[NORMALIZED_EPISODE_PLAN]["parsed_episode_count"], 8)

    def test_episode_plan_normalize_double_nested_json_string_parses(self) -> None:
        nested = json.dumps(
            json.dumps(
                {
                    NORMALIZED_EPISODE_PLAN: _normalized_episode_plan_payload(6)
                },
                ensure_ascii=False,
            ),
            ensure_ascii=False,
        )
        client = FastGPTClient()

        output = client._extract_output_payload(
            {"choices": [{"message": {"content": nested}}]},
            contract_for(STAGE_EPISODE_PLAN_NORMALIZE),
            _framework_inputs(),
            allow_fallback=False,
        )

        self.assertEqual(output[NORMALIZED_EPISODE_PLAN]["parsed_episode_count"], 6)

    def test_episode_plan_normalize_truncated_json_sets_probable_truncated_debug_info(self) -> None:
        truncated = json.dumps(
            {
                NORMALIZED_EPISODE_PLAN: _normalized_episode_plan_payload(3)
            },
            ensure_ascii=False,
        )[:-2]
        client = FastGPTClient()

        with self.assertRaises(ValueError):
            client._extract_output_payload(
                {"answerText": truncated},
                contract_for(STAGE_EPISODE_PLAN_NORMALIZE),
                _framework_inputs(),
                allow_fallback=False,
            )

        debug_info = client.get_last_stage_debug_info(STAGE_EPISODE_PLAN_NORMALIZE)
        self.assertTrue(bool(debug_info.get("probable_truncated_json")))
        self.assertIn(NORMALIZED_EPISODE_PLAN, debug_info.get("missing_fields") or [])
        self.assertTrue(str(debug_info.get("answer_text_preview") or ""))

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

    def test_unstructured_stage_prefers_unstructured_api_key(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "FASTGPT_UNSTRUCTURED_API_KEY": "unstructured-key",
                "FASTGPT_API_KEY": "default-key",
            },
            clear=False,
        ):
            client = FastGPTClient()
            endpoint = client._endpoint_for(STAGE_FRAMEWORK_NATURALIZE)

        self.assertEqual(endpoint.api_key, "unstructured-key")

    def test_unstructured_stage_falls_back_to_default_api_key(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "FASTGPT_UNSTRUCTURED_API_KEY": "",
                "FASTGPT_API_KEY": "default-key",
            },
            clear=False,
        ):
            client = FastGPTClient()
            endpoint = client._endpoint_for(STAGE_WORLDVIEW_NATURALIZE)

        self.assertEqual(endpoint.api_key, "default-key")

    def test_appearance_stages_prefer_dedicated_api_keys(self) -> None:
        stage_to_env = {
            STAGE_APPEARANCE_ALIAS_WRITING: "FASTGPT_APPEARANCE_ALIAS_WRITING_API_KEY",
            STAGE_APPEARANCE_ALIAS_REVIEW: "FASTGPT_APPEARANCE_ALIAS_REVIEW_API_KEY",
            STAGE_APPEARANCE_ALIAS_REWRITE: "FASTGPT_APPEARANCE_ALIAS_REWRITE_API_KEY",
            STAGE_APPEARANCE_ALIAS_UNSTRUCTURED: "FASTGPT_APPEARANCE_ALIAS_UNSTRUCTURED_API_KEY",
        }
        for stage_name, env_name in stage_to_env.items():
            with self.subTest(stage_name=stage_name):
                with patch.dict(
                    "os.environ",
                    {
                        env_name: f"{stage_name}-key",
                        "FASTGPT_API_KEY": "default-key",
                    },
                    clear=False,
                ):
                    client = FastGPTClient()
                    endpoint = client._endpoint_for(stage_name)
                self.assertEqual(endpoint.api_key, f"{stage_name}-key")

    def test_appearance_stages_fall_back_to_default_api_key(self) -> None:
        for stage_name in (
            STAGE_APPEARANCE_ALIAS_WRITING,
            STAGE_APPEARANCE_ALIAS_REVIEW,
            STAGE_APPEARANCE_ALIAS_REWRITE,
            STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
        ):
            with self.subTest(stage_name=stage_name):
                with patch.dict(
                    "os.environ",
                    {
                        "FASTGPT_API_KEY": "default-key",
                    },
                    clear=True,
                ):
                    client = FastGPTClient()
                    endpoint = client._endpoint_for(stage_name)
                self.assertEqual(endpoint.api_key, "default-key")

    def test_appearance_stages_read_stage_specific_timeouts(self) -> None:
        stage_to_timeout = {
            STAGE_APPEARANCE_ALIAS_WRITING: 601,
            STAGE_APPEARANCE_ALIAS_REVIEW: 302,
            STAGE_APPEARANCE_ALIAS_REWRITE: 603,
            STAGE_APPEARANCE_ALIAS_UNSTRUCTURED: 304,
        }
        for stage_name, timeout_value in stage_to_timeout.items():
            env_prefix = f"FASTGPT_{stage_name.upper()}"
            with self.subTest(stage_name=stage_name):
                with patch.dict(
                    "os.environ",
                    {
                        f"{env_prefix}_TIMEOUT": str(timeout_value),
                        "FASTGPT_API_KEY": "default-key",
                    },
                    clear=False,
                ):
                    client = FastGPTClient()
                    endpoint = client._endpoint_for(stage_name)
                self.assertEqual(endpoint.timeout, timeout_value)

    def test_payload_warn_limit_logs_length_summary(self) -> None:
        settings.fastgpt_stage_payload_warn_chars = 50
        settings.fastgpt_stage_payload_hard_chars = 10000
        huge_expectation = "Z" * 400
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

        with self.assertLogs(fastgpt_client_logger.name, level="WARNING") as logs:
            output = client.run_stage(
                STAGE_FRAMEWORK,
                {
                    TOTAL_EPISODES: 10,
                    USER_EXPECTATION: huge_expectation,
                    CHARACTER_COUNT: 4,
                },
            )

        self.assertEqual(output[SCRIPT_TITLE], "长夜回潮")
        self.assertEqual(client.request_count, 1)
        joined = "\n".join(logs.output)
        self.assertIn("payload 过大", joined)
        self.assertIn("最大字段", joined)
        self.assertNotIn(huge_expectation, joined)
        debug_info = client.get_last_stage_debug_info(STAGE_FRAMEWORK)
        self.assertIn("payload_stats", debug_info)
        self.assertGreater(int(debug_info["payload_stats"]["body_chars"]), 50)

    def test_payload_hard_limit_blocks_request_before_http(self) -> None:
        settings.fastgpt_stage_payload_warn_chars = 50
        settings.fastgpt_stage_payload_hard_chars = 100
        huge_expectation = "Q" * 400
        client = _QueuedFastGPTClient([])

        with self.assertRaises(FastGPTPayloadTooLargeError) as ctx:
            client.run_stage(
                STAGE_FRAMEWORK,
                {
                    TOTAL_EPISODES: 10,
                    USER_EXPECTATION: huge_expectation,
                    CHARACTER_COUNT: 4,
                },
            )

        self.assertEqual(client.request_count, 0)
        self.assertIn("请求体过大", str(ctx.exception))
        self.assertEqual(ctx.exception.stage_name, STAGE_FRAMEWORK)
        self.assertNotIn(huge_expectation, str(ctx.exception))
        self.assertTrue(bool(ctx.exception.largest_variables))

    def test_detail_false_characters_stage_still_extracts_formal_output(self) -> None:
        settings.fastgpt_characters_detail = False
        response = {
            "responseData": {
                "updateVarResult": [
                    {
                        "variable": ["VARIABLE_NODE_ID", CHARACTER_VAR],
                        "value": json.dumps(_character_setting_json(), ensure_ascii=False),
                    }
                ]
            }
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_CHARACTERS, _input_variables())

        parsed = json.loads(output["characters"])
        self.assertEqual(parsed["character_setting"]["characters"][0]["character_name"], "林夏")
        self.assertFalse(client.get_last_stage_debug_info(STAGE_CHARACTERS).get("request_detail"))

    def test_characters_stage_captures_natural_language_auxiliary_output(self) -> None:
        response = {
            "responseData": {
                "updateVarResult": [
                    {
                        "variable": ["VARIABLE_NODE_ID", CHARACTER_VAR],
                        "value": json.dumps(_character_setting_json(), ensure_ascii=False),
                    },
                    {
                        "variable": ["VARIABLE_NODE_ID", CHARACTER_NATURAL_LANGUAGE_VAR],
                        "value": "人物小传自然语言版",
                    },
                ]
            }
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_CHARACTERS, _input_variables())

        self.assertIn("characters", output)
        self.assertEqual(output[CHARACTER_NATURAL_LANGUAGE_VAR], "人物小传自然语言版")

    def test_characters_stage_reads_natural_language_alias_from_answer_node_json(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "characters": json.dumps(_character_setting_json(), ensure_ascii=False),
                                "character_summary": "角色设定自然语言说明",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_CHARACTERS, _input_variables())

        self.assertEqual(output[CHARACTER_NATURAL_LANGUAGE_VAR], "角色设定自然语言说明")

    def test_detail_false_scenes_stage_still_extracts_formal_output(self) -> None:
        settings.fastgpt_scenes_detail = False
        response = {
            "responseData": {
                "updateVarResult": [
                    {
                        "variable": ["VARIABLE_NODE_ID", SCENE_VAR],
                        "value": json.dumps(_scene_setting_json(), ensure_ascii=False),
                    }
                ]
            }
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_SCENES, _input_variables())

        parsed = json.loads(output["scenes"])
        self.assertEqual(parsed["scene_setting"]["scenes"][0]["scene_name"], "玻璃会议室")
        self.assertFalse(client.get_last_stage_debug_info(STAGE_SCENES).get("request_detail"))

    def test_scenes_stage_accepts_top_level_scenes_wrapper(self) -> None:
        response = {
            "responseData": {
                "updateVarResult": [
                    {
                        "key": "scenes",
                        "value": {
                            "scene_setting": _scene_setting_json()["scene_setting"],
                        },
                    }
                ]
            }
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_SCENES, _input_variables())

        parsed = json.loads(output["scenes"])
        self.assertEqual(parsed["scene_setting"]["scenes"][0]["scene_name"], "玻璃会议室")

    def test_scenes_stage_accepts_legacy_scene_setting_object_wrapper(self) -> None:
        response = {
            "responseData": {
                "scene_setting": _scene_setting_json()["scene_setting"],
            }
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_SCENES, _input_variables())

        parsed = json.loads(output["scenes"])
        self.assertGreaterEqual(len(parsed["scene_setting"]["scenes"]), 3)
        self.assertIn(
            "玻璃会议室",
            [item["scene_name"] for item in parsed["scene_setting"]["scenes"]],
        )

    def test_scenes_stage_captures_natural_language_auxiliary_output(self) -> None:
        response = {
            "responseData": {
                "updateVarResult": [
                    {
                        "variable": ["VARIABLE_NODE_ID", SCENE_VAR],
                        "value": json.dumps(_scene_setting_json(), ensure_ascii=False),
                    },
                    {
                        "variable": ["VARIABLE_NODE_ID", SCENE_NATURAL_LANGUAGE_VAR],
                        "value": "核心场景自然语言版",
                    },
                ]
            }
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_SCENES, _input_variables())

        self.assertIn("scenes", output)
        self.assertEqual(output[SCENE_NATURAL_LANGUAGE_VAR], "核心场景自然语言版")

    def test_scenes_natural_language_auxiliary_output_does_not_override_structured_output(self) -> None:
        response = {
            "responseData": {
                "updateVarResult": [
                    {
                        "variable": ["VARIABLE_NODE_ID", SCENE_VAR],
                        "value": json.dumps(_scene_setting_json(), ensure_ascii=False),
                    },
                    {
                        "variable": ["VARIABLE_NODE_ID", SCENE_NATURAL_LANGUAGE_VAR],
                        "value": "核心场景自然语言版",
                    },
                ]
            }
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_SCENES, _input_variables())

        parsed = json.loads(output["scenes"])
        self.assertEqual(parsed["scene_setting"]["scenes"][0]["scene_name"], "玻璃会议室")
        self.assertEqual(output[SCENE_NATURAL_LANGUAGE_VAR], "核心场景自然语言版")

    def test_scenes_stage_reads_natural_language_alias_from_choices_content(self) -> None:
        response = {
            "responseData": {
                "updateVarResult": [
                    {
                        "variable": ["VARIABLE_NODE_ID", SCENE_VAR],
                        "value": json.dumps(_scene_setting_json(), ensure_ascii=False),
                    }
                ]
            },
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "core_scene_summary": "核心场景说明",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(STAGE_SCENES, _input_variables())

        self.assertEqual(output[SCENE_NATURAL_LANGUAGE_VAR], "核心场景说明")

    def test_scenes_choices_message_content_json_is_not_used_as_formal_output(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(_scene_setting_json(), ensure_ascii=False)
                    }
                }
            ]
        }
        client = _QueuedFastGPTClient([response])

        with self.assertRaises(ValueError):
            client.run_stage(STAGE_SCENES, _input_variables())

    def test_scenes_toolcall_answertext_json_is_not_used_as_formal_output(self) -> None:
        response = {
            "responseData": {
                "toolCall": {
                    "answerText": json.dumps(_scene_setting_json(), ensure_ascii=False)
                }
            }
        }
        client = _QueuedFastGPTClient([response])

        with self.assertRaises(ValueError):
            client.run_stage(STAGE_SCENES, _input_variables())

    def test_detail_false_appearance_stage_still_extracts_formal_output(self) -> None:
        settings.fastgpt_appearance_alias_generation_detail = False
        response = {
            "responseData": {
                "variableUpdate": {
                    APPEARANCE_MAPPING_VAR: json.dumps(
                        _appearance_mapping_json(),
                        ensure_ascii=False,
                    )
                }
            }
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(
            STAGE_APPEARANCE_ALIAS_GENERATION,
            _appearance_input_variables(),
        )

        self.assertEqual(
            output[APPEARANCE_MAPPING]["characters"][0]["canonical_name"],
            "林夏",
        )
        self.assertFalse(
            client.get_last_stage_debug_info(
                STAGE_APPEARANCE_ALIAS_GENERATION
            ).get("request_detail")
        )

    def test_detail_false_appearance_writing_stage_extracts_from_choices_message_content(self) -> None:
        settings.fastgpt_appearance_alias_generation_detail = False
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            _appearance_mapping_json(),
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        client = _QueuedFastGPTClient([response])

        output = client.run_stage(
            STAGE_APPEARANCE_ALIAS_WRITING,
            _appearance_input_variables(),
        )

        self.assertEqual(
            output[APPEARANCE_MAPPING]["characters"][0]["canonical_name"],
            "林夏",
        )
        self.assertFalse(
            client.get_last_stage_debug_info(
                STAGE_APPEARANCE_ALIAS_WRITING
            ).get("request_detail")
        )

    def test_detail_false_appearance_rewrite_stage_extracts_from_choices_message_content(self) -> None:
        settings.fastgpt_appearance_alias_generation_detail = False
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            _appearance_mapping_json(),
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        client = _QueuedFastGPTClient([response])
        variables = _appearance_input_variables()
        variables[APPEARANCE_MAPPING] = _appearance_mapping_json()
        variables[PASS_REVIEW_JSON] = _appearance_review_json(
            passed=False,
            rewrite_required=True,
            blocking_issues=["alias_name 需要统一"],
        )

        output = client.run_stage(
            STAGE_APPEARANCE_ALIAS_REWRITE,
            variables,
        )

        self.assertEqual(
            output[APPEARANCE_MAPPING]["scene_level_usage_plan"][0]["scene_name"],
            "玻璃会议室",
        )
        self.assertFalse(
            client.get_last_stage_debug_info(
                STAGE_APPEARANCE_ALIAS_REWRITE
            ).get("request_detail")
        )

    def test_detail_false_appearance_review_stage_extracts_review_json_from_choices(self) -> None:
        settings.fastgpt_appearance_alias_generation_detail = False
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                APPEARANCE_REVIEW_VAR: json.dumps(
                                    _appearance_review_json(
                                        passed=True,
                                        rewrite_required=False,
                                    ),
                                    ensure_ascii=False,
                                )
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        client = _QueuedFastGPTClient([response])
        variables = _appearance_input_variables()
        variables[APPEARANCE_MAPPING] = _appearance_mapping_json()

        output = client.run_stage(
            STAGE_APPEARANCE_ALIAS_REVIEW,
            variables,
        )

        self.assertTrue(output["passed"])
        self.assertEqual(output["blocking_issues"], [])
        self.assertFalse(
            client.get_last_stage_debug_info(
                STAGE_APPEARANCE_ALIAS_REVIEW
            ).get("request_detail")
        )

    def test_detail_false_appearance_unstructured_stage_extracts_text_from_choices(self) -> None:
        settings.fastgpt_appearance_alias_generation_detail = False
        response = {
            "choices": [
                {
                    "message": {
                        "content": "林夏常态默认使用“林夏【会议室交锋态】”，回到公寓后切回更松弛的居家版本。"
                    }
                }
            ]
        }
        client = _QueuedFastGPTClient([response])
        variables = _appearance_input_variables()
        variables[APPEARANCE_MAPPING] = _appearance_mapping_json()

        output = client.run_stage(
            STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
            variables,
        )

        self.assertIn("林夏", output[APPEARANCE_NATURAL_LANGUAGE_VAR])
        self.assertFalse(
            client.get_last_stage_debug_info(
                STAGE_APPEARANCE_ALIAS_UNSTRUCTURED
            ).get("request_detail")
        )

    def test_script_review_complete_json_from_choices_passes_contract(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            _pass_review_json(
                                passed=True,
                                rewrite_required=False,
                                summary="review ok",
                                blocking_issues=[],
                                non_blocking_issues=["措辞可更紧"],
                                rewrite_start_episode=1,
                                stage="five_episode_continuity_review",
                            ),
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        client = FastGPTClient()

        output = client._extract_output_payload(
            response,
            contract_for(STAGE_SCRIPT_REVIEW),
            {},
            allow_fallback=True,
        )

        self.assertTrue(output["passed"])
        self.assertEqual(output["summary"], "review ok")
        self.assertEqual(output["non_blocking_issues"], ["措辞可更紧"])
        self.assertEqual(output["rewrite_start_episode"], 1)
        self.assertEqual(output["stage"], "five_episode_continuity_review")

    def test_script_review_thinking_plus_json_extracts_last_json_object(self) -> None:
        earlier = {"passed": False, "note": "ignore"}
        final_review = _pass_review_json(
            passed=True,
            rewrite_required=False,
            summary="final ok",
            blocking_issues=[],
            non_blocking_issues=[],
            rewrite_start_episode=6,
            stage="five_episode_continuity_review",
        )
        response = {
            "choices": [
                {
                    "message": {
                        "content": (
                            "思考过程：先比较节奏和连续性。\n"
                            f"{json.dumps(earlier, ensure_ascii=False)}\n"
                            "最终审核结论如下：\n"
                            f"{json.dumps(final_review, ensure_ascii=False)}"
                        )
                    }
                }
            ]
        }
        client = FastGPTClient()

        output = client._extract_output_payload(
            response,
            contract_for(STAGE_SCRIPT_REVIEW),
            {},
            allow_fallback=True,
        )

        self.assertTrue(output["passed"])
        self.assertEqual(output["summary"], "final ok")
        self.assertEqual(output["rewrite_start_episode"], 6)

    def test_script_review_reasoning_content_block_is_not_treated_as_output(self) -> None:
        final_review = _pass_review_json(
            passed=True,
            rewrite_required=False,
            summary="array ok",
            blocking_issues=[],
            non_blocking_issues=[],
            rewrite_start_episode=1,
            stage="five_episode_continuity_review",
        )
        response = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {
                                "type": "reasoning",
                                "text": {
                                    "content": json.dumps(
                                        {"passed": False, "rewrite_required": True},
                                        ensure_ascii=False,
                                    )
                                },
                            },
                            {
                                "type": "text",
                                "text": {
                                    "content": json.dumps(final_review, ensure_ascii=False)
                                },
                            },
                        ]
                    }
                }
            ]
        }
        client = FastGPTClient()

        output = client._extract_output_payload(
            response,
            contract_for(STAGE_SCRIPT_REVIEW),
            {},
            allow_fallback=True,
        )

        self.assertTrue(output["passed"])
        self.assertEqual(output["summary"], "array ok")

    def test_hook_and_dialogue_review_also_prefer_choices_json(self) -> None:
        review_payload = _pass_review_json(
            passed=True,
            rewrite_required=False,
            summary="ok",
            blocking_issues=[],
            non_blocking_issues=["可以更锐利"],
        )
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(review_payload, ensure_ascii=False)
                    }
                }
            ]
        }
        client = FastGPTClient()

        for stage_name in (STAGE_HOOK_REVIEW, STAGE_DIALOGUE_REVIEW):
            with self.subTest(stage_name=stage_name):
                output = client._extract_output_payload(
                    response,
                    contract_for(stage_name),
                    {},
                    allow_fallback=True,
                )
                self.assertTrue(output["passed"])
                self.assertEqual(output["summary"], "ok")
                self.assertEqual(output["non_blocking_issues"], ["可以更锐利"])


if __name__ == "__main__":
    unittest.main()
