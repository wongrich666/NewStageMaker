from __future__ import annotations

import json
import os
import unittest
import uuid
from unittest.mock import Mock, patch

import requests

from workflow_code_skeleton.app.services.tencent_workflow_client import (
    TencentWorkflowClient,
    _build_request_body,
    _extract_contract_output,
    _parse_sse,
    _response_payload,
)
from workflow_code_skeleton.app.services.tencent_workflow_registry import (
    TENCENT_WORKFLOWS,
    workflow_spec,
)
from workflow_code_skeleton.app.services.workflow_contracts import (
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE,
    STAGE_FRAMEWORK_APPEARANCE_MAPPING,
    contract_for,
)


class ByteResponse:
    headers = {"Content-Type": "text/event-stream"}
    encoding = "ISO-8859-1"
    apparent_encoding = "utf-8"

    def __init__(self, text: str) -> None:
        self.content = text.encode("utf-8")
        # Simulate requests' incorrect default decoding for SSE without charset.
        self.text = self.content.decode("ISO-8859-1")


class TencentPrivatePlatformTests(unittest.TestCase):
    def test_http_400_response_is_preserved_in_stage_debug_info(self) -> None:
        response = Mock(
            status_code=400,
            content=(
                b'{"Type":"error","Error":{"Code":999,'
                b'"Message":"json: cannot unmarshal number into WorkflowInput of type string"}}'
            ),
            headers={"Content-Type": "application/json"},
        )
        client = TencentWorkflowClient()
        with patch(
            "workflow_code_skeleton.app.services.tencent_workflow_client.requests.post",
            return_value=response,
        ):
            with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
                client._post_with_retries(
                    stage_name="hot_review",
                    url="http://example.invalid/adp/v2/chat",
                    headers={"Content-Type": "application/json"},
                    body={"WorkflowInput": {"total_episodes": 48}},
                )

        debug = client.get_last_stage_debug_info("hot_review")
        self.assertEqual("http_error", debug["status"])
        self.assertEqual(400, debug["http_status"])
        self.assertIn("cannot unmarshal number", debug["response_preview"])

    def test_chunked_response_disconnect_is_retried(self) -> None:
        successful_response = Mock(status_code=200)
        client = TencentWorkflowClient()
        with (
            patch.dict(
                os.environ,
                {
                    "TENCENT_WORKFLOW_HTTP_RETRIES": "1",
                    "TENCENT_WORKFLOW_HTTP_RETRY_DELAY_SECONDS": "0",
                },
                clear=False,
            ),
            patch(
                "workflow_code_skeleton.app.services.tencent_workflow_client.requests.post",
                side_effect=[
                    requests.exceptions.ChunkedEncodingError("Response ended prematurely"),
                    successful_response,
                ],
            ) as post,
        ):
            response = client._post_with_retries(
                stage_name="framework_enriched_episode_plan",
                url="http://example.invalid/adp/v2/chat",
                headers={"Content-Type": "application/json"},
                body={"RequestId": "retry-test"},
            )

        self.assertIs(successful_response, response)
        self.assertEqual(2, post.call_count)

    def test_private_v2_uses_top_level_workflow_input(self) -> None:
        spec = TENCENT_WORKFLOWS["01"]
        workflow_inputs = {
            "source_title": "连接诊断",
            "target_format": "短剧",
        }
        with patch.dict(
            os.environ,
            {"TENCENT_WORKFLOW_V2_INPUT_MODE": "workflow_input"},
            clear=False,
        ):
            body = _build_request_body(
                url="http://101.42.184.216/adp/v2/chat",
                spec=spec,
                api_key="test-app-key",
                workflow_inputs=workflow_inputs,
                request_id=uuid.uuid4().hex,
            )

        self.assertEqual(workflow_inputs, body["WorkflowInput"])
        self.assertFalse(
            any(item.get("Type") == "custom_variables" for item in body["Contents"])
        )

    def test_sse_bytes_are_decoded_as_utf8(self) -> None:
        response = ByteResponse(
            "\n".join(
                [
                    "event: error",
                    'data: {"Type":"error","Error":{"Code":4505004,"Message":"应用密钥无效"}}',
                    "",
                ]
            )
        )
        parsed = _response_payload(response)
        self.assertIn("应用密钥无效", json.dumps(parsed, ensure_ascii=False))
        self.assertNotIn("åº", json.dumps(parsed, ensure_ascii=False))

    def test_private_v2_prefers_workflow_end_node_over_thought(self) -> None:
        end_output = {
            "confirmed_info": json.dumps(
                {"source_brief": {"title": "正确业务结果"}},
                ensure_ascii=False,
            )
        }
        completed = {
            "Type": "response.completed",
            "Response": {
                "Status": "success",
                "Messages": [
                    {
                        "Type": "thought",
                        "Contents": [{"Type": "text", "Text": "这不是业务输出"}],
                    },
                    {"Type": "reply", "Contents": []},
                ],
                "Procedures": [
                    {
                        "Type": "workflow",
                        "Workflow": {
                            "Outputs": [],
                            "RunNodes": [
                                {
                                    "NodeType": 16,
                                    "NodeName": "结束",
                                    "Output": json.dumps(
                                        end_output,
                                        ensure_ascii=False,
                                    ),
                                }
                            ],
                        },
                    }
                ],
            },
        }
        text = "\n".join(
            [
                "event: message.done",
                'data: {"Type":"message.done","Message":{"Type":"thought","Contents":[{"Type":"text","Text":"错误的思考内容"}]}}',
                "",
                "event: response.completed",
                f"data: {json.dumps(completed, ensure_ascii=False)}",
                "",
            ]
        )
        parsed = _parse_sse(text)
        self.assertEqual(
            {"confirmed_info": {"source_brief": {"title": "正确业务结果"}}},
            parsed["reply"],
        )

    def test_stage09_extracts_complete_mapping_from_end_node_alias(self) -> None:
        business_output = {
            "appearanceMapping": {
                "mapping_version": "appearance_mapping_v1",
                "global_alias_rules": ["禁止正文阶段自造 alias。"],
                "characters": [
                    {
                        "character_id": "hero",
                        "name": "苏砚",
                        "default_name": "苏砚",
                        "outfit_versions": [],
                    }
                ],
            }
        }
        end_output = {"alias": json.dumps(business_output, ensure_ascii=False)}
        completed = {
            "Type": "response.completed",
            "Response": {
                "Status": "success",
                "Messages": [],
                "Procedures": [
                    {
                        "Type": "workflow",
                        "Workflow": {
                            "RunNodes": [
                                {
                                    "NodeType": 16,
                                    "NodeName": "结束",
                                    "Output": json.dumps(end_output, ensure_ascii=False),
                                }
                            ]
                        },
                    }
                ],
            },
        }
        text = "\n".join(
            [
                "event: response.completed",
                f"data: {json.dumps(completed, ensure_ascii=False)}",
                "",
            ]
        )

        parsed = _parse_sse(text)
        contract = contract_for(STAGE_FRAMEWORK_APPEARANCE_MAPPING)
        spec = workflow_spec(STAGE_FRAMEWORK_APPEARANCE_MAPPING)
        output, _ = _extract_contract_output(
            parsed,
            contract=contract,
            response_fields=spec.response_fields,
        )

        self.assertEqual("苏砚", output["appearanceMapping"]["characters"][0]["name"])
        self.assertNotIn("events", output["appearanceMapping"])

    def test_stage09_contract_rejects_sse_envelope_as_mapping(self) -> None:
        contract = contract_for(STAGE_FRAMEWORK_APPEARANCE_MAPPING)
        with self.assertRaisesRegex(ValueError, "characters"):
            contract.validate_output_payload(
                {"appearanceMapping": {"events": [], "reply": {"alias": []}}}
            )

    def test_stage11_does_not_wrap_sse_envelope_as_conflict_plan(self) -> None:
        envelope = {
            "events": [{"event": "response.completed", "data": {"Response": {}}}],
            "reply": {"conflicts": ""},
        }
        contract = contract_for(STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE)
        spec = workflow_spec(STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE)

        output, _ = _extract_contract_output(
            envelope,
            contract=contract,
            response_fields=spec.response_fields,
        )

        self.assertFalse(
            isinstance(output, dict)
            and isinstance(output.get("batchCausalConflictPlan"), dict)
            and "events" in output["batchCausalConflictPlan"]
        )


if __name__ == "__main__":
    unittest.main()
