from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from workflow_code_skeleton.app.services.coze_client import CozeWorkflowClient
from workflow_code_skeleton.app.services.fastgpt_contracts import (
    APPEARANCE_MAPPING,
    BATCH_CAUSAL_CONFLICT_PLAN,
    BATCH_ENRICHED_EPISODE_PLAN,
    BATCH_SCRIPT_TEXT,
    CONFLICT_MEMORY,
    CONFLICT_START_EPISODE,
    EPISODE_WORD_COUNT,
    SCENE_DICTIONARY,
    SCRIPT_MEMORY,
    SCRIPT_START_EPISODE,
    SCRIPT_WORLD_RULES_DIGEST,
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE,
    STAGE_FRAMEWORK_SCRIPT_WRITE,
    TOTAL_EPISODES,
)


class _FakeResponse:
    status_code = 200

    def __init__(self, payload: dict[str, object], *, text: str = "") -> None:
        self._payload = payload
        self.text = text

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _FakeInvalidJsonResponse(_FakeResponse):
    def json(self) -> dict[str, object]:
        raise ValueError("invalid json")


class CozeWorkflowClientTests(unittest.TestCase):
    def test_conflict_write_maps_internal_variables_to_yaml_parameters(self) -> None:
        captured: dict[str, object] = {}

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["body"] = json or {}
            captured["timeout"] = timeout
            return _FakeResponse(
                {
                    "code": 0,
                    "data": json_module.dumps(
                        {"conflicts": {"episodes": [{"episode": 1, "conflict": "A pushes B"}]}},
                        ensure_ascii=False,
                    ),
                }
            )

        variables = _conflict_write_variables()

        with patch.dict(
            os.environ,
            {
                "COZE_CREDENTIALS_ORDER": "primary,secondary",
                "COZE_PRIMARY_API_TOKEN": "coze-token",
                "COZE_PRIMARY_API_BASE": "https://api.coze.cn",
                "COZE_WORKFLOW_STAGE_11_WRITE_ID": "stage-11-write",
            },
            clear=False,
        ):
            with patch("workflow_code_skeleton.app.services.coze_client.requests.post", side_effect=_fake_post):
                output = CozeWorkflowClient().run_stage(STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE, variables)

        self.assertEqual(captured["url"], "https://api.coze.cn/v1/workflow/run")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer coze-token")
        body = captured["body"]
        self.assertEqual(body["workflow_id"], "stage-11-write")
        parameters = body["parameters"]
        self.assertEqual(parameters["episode_num"], 60)
        self.assertEqual(parameters["start_epi"], 1)
        self.assertEqual(json.loads(parameters["enriched_epiplan"])[0]["episode"], 1)
        self.assertEqual(json.loads(parameters["scene"])["scenes"][0]["id"], "court")
        self.assertEqual(json.loads(parameters["worldview"])["world"], "rules")
        self.assertEqual(parameters["user_feedback"], "keep it sharp")
        self.assertEqual(output[BATCH_CAUSAL_CONFLICT_PLAN]["episodes"][0]["episode"], 1)

    def test_script_write_maps_conflict_and_episode_plan_to_coze_names(self) -> None:
        captured: dict[str, object] = {}

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["body"] = json or {}
            captured["timeout"] = timeout
            return _FakeResponse(
                {
                    "code": 0,
                    "data": json_module.dumps({"script": "第1集 正文"}, ensure_ascii=False),
                }
            )

        variables = _script_write_variables()

        with patch.dict(
            os.environ,
            {
                "COZE_CREDENTIALS_ORDER": "primary,secondary",
                "COZE_PRIMARY_API_TOKEN": "coze-token",
                "COZE_WORKFLOW_STAGE_12_WRITE_ID": "stage-12-write",
            },
            clear=False,
        ):
            with patch("workflow_code_skeleton.app.services.coze_client.requests.post", side_effect=_fake_post):
                output = CozeWorkflowClient().run_stage(STAGE_FRAMEWORK_SCRIPT_WRITE, variables)

        body = captured["body"]
        self.assertEqual(body["workflow_id"], "stage-12-write")
        parameters = body["parameters"]
        self.assertEqual(parameters["episode_num"], 60)
        self.assertEqual(parameters["start_epi"], 1)
        self.assertEqual(parameters["character_count"], 800)
        self.assertEqual(json.loads(parameters["according_epiplan"])[0]["summary"], "plan")
        self.assertEqual(json.loads(parameters["according_conflict"])["episodes"][0]["episode"], 1)
        self.assertEqual(json.loads(parameters["alias"])["characters"][0]["name"], "A")
        self.assertEqual(output[BATCH_SCRIPT_TEXT], "第1集 正文")

    def test_conflict_write_wraps_direct_array_output(self) -> None:
        def _fake_post(url, *, headers=None, json=None, timeout=None):
            return _FakeResponse(
                {
                    "code": 0,
                    "data": json_module.dumps(
                        [{"episode": 1, "conflict": "A pushes B"}],
                        ensure_ascii=False,
                    ),
                }
            )

        with patch.dict(os.environ, _coze_env("COZE_WORKFLOW_STAGE_11_WRITE_ID", "stage-11-write"), clear=False):
            with patch("workflow_code_skeleton.app.services.coze_client.requests.post", side_effect=_fake_post):
                output = CozeWorkflowClient().run_stage(
                    STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE,
                    _conflict_write_variables(),
                )

        self.assertEqual(output[BATCH_CAUSAL_CONFLICT_PLAN]["episodes"][0]["episode"], 1)

    def test_script_write_accepts_markdown_json_fence(self) -> None:
        def _fake_post(url, *, headers=None, json=None, timeout=None):
            return _FakeResponse({"code": 0, "data": '```json\n{"script": "正文"}\n```'})

        with patch.dict(os.environ, _coze_env("COZE_WORKFLOW_STAGE_12_WRITE_ID", "stage-12-write"), clear=False):
            with patch("workflow_code_skeleton.app.services.coze_client.requests.post", side_effect=_fake_post):
                output = CozeWorkflowClient().run_stage(
                    STAGE_FRAMEWORK_SCRIPT_WRITE,
                    _script_write_variables(),
                )

        self.assertEqual(output[BATCH_SCRIPT_TEXT], "正文")

    def test_script_write_wraps_direct_array_as_json_text(self) -> None:
        def _fake_post(url, *, headers=None, json=None, timeout=None):
            return _FakeResponse({"code": 0, "data": [{"episode": 1, "title": "正文"}]})

        with patch.dict(os.environ, _coze_env("COZE_WORKFLOW_STAGE_12_WRITE_ID", "stage-12-write"), clear=False):
            with patch("workflow_code_skeleton.app.services.coze_client.requests.post", side_effect=_fake_post):
                output = CozeWorkflowClient().run_stage(
                    STAGE_FRAMEWORK_SCRIPT_WRITE,
                    _script_write_variables(),
                )

        self.assertEqual(json.loads(output[BATCH_SCRIPT_TEXT])[0]["episode"], 1)

    def test_script_write_prefers_variables_over_output_text(self) -> None:
        def _fake_post(url, *, headers=None, json=None, timeout=None):
            return _FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "variables": {"script": "变量正文"},
                        "output": "这段不是主结果",
                    },
                }
            )

        with patch.dict(os.environ, _coze_env("COZE_WORKFLOW_STAGE_12_WRITE_ID", "stage-12-write"), clear=False):
            with patch("workflow_code_skeleton.app.services.coze_client.requests.post", side_effect=_fake_post):
                output = CozeWorkflowClient().run_stage(
                    STAGE_FRAMEWORK_SCRIPT_WRITE,
                    _script_write_variables(),
                )

        self.assertEqual(output[BATCH_SCRIPT_TEXT], "变量正文")

    def test_script_write_parses_response_text_when_response_json_invalid(self) -> None:
        def _fake_post(url, *, headers=None, json=None, timeout=None):
            return _FakeInvalidJsonResponse({}, text='下面是结果：\n{"script": "正文"}\n请确认。')

        with patch.dict(os.environ, _coze_env("COZE_WORKFLOW_STAGE_12_WRITE_ID", "stage-12-write"), clear=False):
            with patch("workflow_code_skeleton.app.services.coze_client.requests.post", side_effect=_fake_post):
                output = CozeWorkflowClient().run_stage(
                    STAGE_FRAMEWORK_SCRIPT_WRITE,
                    _script_write_variables(),
                )

        self.assertEqual(output[BATCH_SCRIPT_TEXT], "正文")


    def test_credentials_order_secondary_is_strict(self) -> None:
        captured: dict[str, object] = {}

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, json, timeout
            captured["headers"] = headers or {}
            return _FakeResponse({"code": 0, "data": {"variables": {"script": "??"}}})

        with patch.dict(
            os.environ,
            {
                "COZE_CREDENTIALS_ORDER": "secondary",
                "COZE_PRIMARY_API_TOKEN": "primary-token",
                "COZE_SECONDARY_API_TOKEN": "secondary-token",
                "COZE_WORKFLOW_STAGE_12_WRITE_ID": "stage-12-write",
            },
            clear=False,
        ):
            with patch("workflow_code_skeleton.app.services.coze_client.requests.post", side_effect=_fake_post):
                CozeWorkflowClient().run_stage(
                    STAGE_FRAMEWORK_SCRIPT_WRITE,
                    _script_write_variables(),
                )

        self.assertEqual(captured["headers"]["Authorization"], "Bearer secondary-token")


json_module = json


def _coze_env(workflow_env_name: str, workflow_id: str) -> dict[str, str]:
    return {
        "COZE_CREDENTIALS_ORDER": "primary,secondary",
        "COZE_PRIMARY_API_TOKEN": "coze-token",
        workflow_env_name: workflow_id,
    }


def _conflict_write_variables() -> dict[str, object]:
    return {
        TOTAL_EPISODES: 60,
        CONFLICT_START_EPISODE: 1,
        BATCH_ENRICHED_EPISODE_PLAN: [{"episode": 1, "summary": "plan"}],
        SCENE_DICTIONARY: {"scenes": [{"id": "court"}]},
        APPEARANCE_MAPPING: {"characters": [{"name": "A"}]},
        SCRIPT_WORLD_RULES_DIGEST: {"world": "rules"},
        CONFLICT_MEMORY: "",
        "user_feedback": "keep it sharp",
    }


def _script_write_variables() -> dict[str, object]:
    return {
        TOTAL_EPISODES: 60,
        SCRIPT_START_EPISODE: 1,
        EPISODE_WORD_COUNT: 800,
        BATCH_ENRICHED_EPISODE_PLAN: [{"episode": 1, "summary": "plan"}],
        BATCH_CAUSAL_CONFLICT_PLAN: {"episodes": [{"episode": 1, "conflict": "A pushes B"}]},
        SCENE_DICTIONARY: {"scenes": [{"id": "court"}]},
        APPEARANCE_MAPPING: {"characters": [{"name": "A"}]},
        SCRIPT_WORLD_RULES_DIGEST: {"world": "rules"},
        SCRIPT_MEMORY: "",
        "user_feedback": "tight dialogue",
    }


if __name__ == "__main__":
    unittest.main()
