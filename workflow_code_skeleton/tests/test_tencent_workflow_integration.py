from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_code_skeleton.app.services.workflow_contracts import (
    BATCH_SCRIPT_TEXT,
    STAGE_FRAMEWORK_SCRIPT_WRITE,
    contract_for,
)
from workflow_code_skeleton.app.services.tencent_workflow_client import (
    TencentWorkflowClient,
    _extract_contract_output,
    _parse_sse,
)
from workflow_code_skeleton.app.services.tencent_workflow_registry import (
    TENCENT_WORKFLOWS,
    build_workflow_inputs,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORT_ROOT = REPO_ROOT / "腾讯智能平台工作流文件"
EXPORT_STAGE_KEYS = {
    "export-01提取故事梗概": "01",
    "export-02世界观": "02",
    "export-03人设方案撰写": "03",
    "export-04三幕十五节拍生成": "04",
    "export-05人物故事线整理": "05",
    "export-06整体改编指引": "06",
    "export-07最终框架策划包": "07",
    "export-08场景字典提炼": "framework_scene_dictionary",
    "export-09人物服饰映射": "framework_appearanceMapping",
    "export-10丰富分集计划": "framework_enriched_episode_plan",
    "export-11_01开头冲突钩子撰写": "framework_causal_conflict_write",
    "export-11_02开头冲突钩子审核": "framework_causal_conflict_review",
    "export-11_03开头冲突钩子修订": "framework_causal_conflict_rewrite",
    "export-11_04开头冲突钩子记忆": "framework_causal_conflict_memory",
    "export-12_01剧本正文撰写": "framework_script_write",
    "export-12_02剧本正文审核": "framework_script_review",
    "export-12_03剧本正文修订": "framework_script_rewrite",
    "export-12_04剧本正文记忆": "framework_script_memory",
}

def load_export(directory_name: str) -> dict:
    paths = list((EXPORT_ROOT / directory_name).glob("*_workflow.json"))
    if len(paths) != 1:
        raise AssertionError(f"{directory_name} workflow json count={len(paths)}")
    return json.loads(paths[0].read_text(encoding="utf-8"))


class FakeResponse:
    status_code = 200
    headers = {"Content-Type": "application/json"}
    text = ""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> dict:
        return self._payload


class TencentWorkflowRegistryTests(unittest.TestCase):
    def test_registry_matches_all_exported_start_inputs_and_end_fields(self) -> None:
        self.assertEqual(18, len(EXPORT_STAGE_KEYS))
        for directory_name, stage_key in EXPORT_STAGE_KEYS.items():
            with self.subTest(directory=directory_name):
                workflow = load_export(directory_name)
                spec = TENCENT_WORKFLOWS[stage_key]
                self.assertEqual(spec.workflow_id, workflow["WorkflowID"])

                start = next(node for node in workflow["Nodes"] if node["NodeType"] == "START")
                actual_inputs = tuple(item["Name"] for item in start.get("Inputs") or [])
                self.assertEqual(spec.input_names, actual_inputs)

                end = next(node for node in workflow["Nodes"] if node["NodeType"] == "END")
                actual_fields = tuple(
                    prop["Title"]
                    for output in end.get("Outputs") or []
                    for prop in output.get("Properties") or []
                )
                self.assertEqual(spec.response_fields, actual_fields)

    def test_declared_inputs_are_connected_to_model_prompts(self) -> None:
        for directory_name in EXPORT_STAGE_KEYS:
            with self.subTest(directory=directory_name):
                workflow = load_export(directory_name)
                start = next(node for node in workflow["Nodes"] if node["NodeType"] == "START")
                declared = {item["Name"] for item in start.get("Inputs") or []}
                referenced: set[str] = set()
                for node in workflow["Nodes"]:
                    if node.get("NodeType") != "LLM":
                        continue
                    llm = node.get("LLMNodeData") or {}
                    for text in (llm.get("Prompt"), llm.get("SystemPrompt")):
                        referenced.update(
                            re.findall(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", str(text or ""))
                        )

                # 12_01/12_03 的第二个 LLM 节点通过节点连线接收第一个 LLM 的 script。
                undeclared_external = referenced - declared - {"script"}
                self.assertEqual(set(), undeclared_external)
                self.assertEqual(set(), declared - referenced)

    def test_conflict_review_workflow_returns_review_contract(self) -> None:
        workflow = load_export("export-11_02开头冲突钩子审核")
        llm = next(node for node in workflow["Nodes"] if node["NodeType"] == "LLM")
        system_prompt = str(llm["LLMNodeData"]["SystemPrompt"])
        self.assertIn('"passed"', system_prompt)
        self.assertIn('"rewrite_required"', system_prompt)
        self.assertIn('"blocking_issues"', system_prompt)
        self.assertIn('"stage": "causal_conflict_review"', system_prompt)
        self.assertIn("只负责审核", system_prompt)

    def test_episode_word_count_is_sent_directly_as_character_count(self) -> None:
        payload = build_workflow_inputs(
            STAGE_FRAMEWORK_SCRIPT_WRITE,
            {
                "totalEpisodes": 80,
                "scriptStartEpisode": 6,
                "episodeWordCount": 733,
                "batchCausalConflictPlan": {"episodes": []},
                "batchEnrichedEpisodePlan": {"episodes": []},
                "scriptWorldRulesDigest": {"rules": []},
                "appearanceMapping": {"characters": []},
                "scriptMemory": "",
            },
        )
        self.assertEqual("733", payload["character_count"])
        self.assertNotIn("minutes_per_episode", payload)
        self.assertNotIn("duration", payload)

    def test_nested_output_wrapper_normalizes_script_text(self) -> None:
        contract = contract_for(STAGE_FRAMEWORK_SCRIPT_WRITE)
        raw = {
            "data": json.dumps(
                {
                    "Output": {
                        "script": "第1集：\n1-1 日 内 场景\n人物：台词。",
                    }
                },
                ensure_ascii=False,
            )
        }
        output, sources = _extract_contract_output(
            raw,
            contract=contract,
            response_fields=("script",),
        )
        self.assertTrue(sources)
        self.assertEqual(
            "第1集：\n1-1 日 内 场景\n人物：台词。",
            output[BATCH_SCRIPT_TEXT],
        )

    def test_sse_final_reply_is_selected(self) -> None:
        text = "\n".join(
            [
                "event:reply",
                'data:{"content":"处理中","is_final":false}',
                "",
                "event:reply",
                'data:{"content":"{\\\"Output\\\":{\\\"script\\\":\\\"完成\\\"}}","is_final":true}',
                "",
            ]
        )
        parsed = _parse_sse(text)
        self.assertEqual(
            {"Output": {"script": "完成"}},
            parsed["reply"]["content"],
        )

    def test_v2_sse_message_done_is_selected(self) -> None:
        text = "\n".join(
            [
                "event:message.done",
                'data:{"Type":"message.done","Message":{"Type":"reply","Contents":[{"Type":"text","Text":"{\\\"Output\\\":{\\\"script\\\":\\\"新版完成\\\"}}"}]}}',
                "",
                "event:response.completed",
                'data:{"Type":"response.completed","Response":{"Status":"success","Messages":[]}}',
                "",
                "event:done",
                "data:[DONE]",
                "",
            ]
        )
        parsed = _parse_sse(text)
        self.assertEqual(
            {"Output": {"script": "新版完成"}},
            parsed["reply"],
        )

    def test_run_raw_uses_stage_app_key_and_custom_variables(self) -> None:
        response = FakeResponse(
            {
                "Output": {
                    "confirmed_info": json.dumps(
                        {"source_brief": {"title": "测试项目"}},
                        ensure_ascii=False,
                    )
                }
            }
        )
        captured: dict = {}

        def fake_post(url, *, headers, json, timeout):
            captured.update(
                {
                    "url": url,
                    "headers": headers,
                    "body": json,
                    "timeout": timeout,
                }
            )
            return response

        env = {
            "TENCENT_WORKFLOW_01_API_KEY": "test-app-key",
            "TENCENT_ADP_API_URL": "https://wss.lke.cloud.tencent.com/adp/v2/chat",
            "TENCENT_WORKFLOW_V2_INPUT_MODE": "custom_variables",
            "TENCENT_WORKFLOW_HTTP_RETRIES": "0",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "workflow_code_skeleton.app.services.tencent_workflow_client.requests.post",
            side_effect=fake_post,
        ):
            result = TencentWorkflowClient().run_raw(
                "01",
                {
                    "source_title": "测试项目",
                    "target_format": "短剧",
                    "episodes_number": 24,
                    "mode": "创作",
                    "episode_word_count": 600,
                    "source_text": "故事正文",
                    "user_requirements": "保持因果连续",
                },
            )

        self.assertEqual({"source_brief": {"title": "测试项目"}}, result)
        self.assertEqual("test-app-key", captured["body"]["AppKey"])
        custom_variables = next(
            item["CustomVariables"]
            for item in captured["body"]["Contents"]
            if item["Type"] == "custom_variables"
        )
        self.assertEqual("24", custom_variables["episode_number"])
        self.assertEqual("600", custom_variables["chars_per_epi"])
        self.assertNotIn("Authorization", captured["headers"])


if __name__ == "__main__":
    unittest.main()
