from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_code_skeleton.app.services import framework_planner_service as service


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, payload=None, text: str = "", reason: str = "OK") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.reason = reason

    def json(self):
        return self._payload


def _basic_config() -> dict[str, object]:
    return {
        "project_title": "夜行审判",
        "mode": "创作",
        "source_text": "一个背负旧案的律师重返故乡，发现父亲之死与地方财团有关。",
        "source_title": "夜行审判",
        "target_format": "短剧",
        "season_count": 1,
        "episodes_per_season": 60,
        "minutes_per_episode": 2,
        "adaptation_direction": "强化中点反转和强情绪推进。",
        "user_constraints": "不能删除旧案主线。",
        "user_requirements": "主角必须有明显成长弧光。",
    }


def _stage_04_payload() -> dict[str, object]:
    return {
        "mode": "创作",
        "source_brief": {"source_title": "夜行审判"},
        "basic_config": _basic_config(),
        "worldview_plan": {"world_type": "近未来都市"},
        "character_plan": {"protagonist": {"name": "林渡"}},
        "previous_beat_checkpoint_timeline": [],
        "user_feedback": "",
        "framework_score_report": "",
        "adaptation_direction": "强化反转",
        "user_requirements": "固定 15 beat",
    }


class FrameworkPlannerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        service.framework_workflow_dir.cache_clear()
        service.resolve_stage_workflow_path.cache_clear()
        service.load_stage_workflow_spec.cache_clear()

    def test_resolve_stage_workflow_path_reads_better_framework_jsons(self) -> None:
        path = service.resolve_stage_workflow_path("04")
        self.assertIsInstance(path, Path)
        self.assertTrue(path.name.startswith("04_"))
        self.assertIn("BETTER_FRAMEWORK_JSONS", str(path))

    def test_stage_04_mock_output_contains_15_beats_and_required_fields(self) -> None:
        with patch.dict(os.environ, {"FRAMEWORK_PLANNER_USE_MOCK": "true"}, clear=False):
            payload = service.run_framework_planner_stage("04", _stage_04_payload())

        self.assertTrue(payload["ok"])
        beats = payload["data"]["beat_checkpoint_timeline"]
        self.assertEqual(len(beats), 15)
        for item in beats:
            for field in (
                "beat_no",
                "beat_name",
                "act",
                "episode_range",
                "checkpoint_title",
                "narrative_function",
                "plot_content",
                "hook_or_reversal",
            ):
                self.assertIn(field, item)
                self.assertNotEqual(item[field], "")

    def test_stage_01_maps_mode_to_legacy_workflow_variable(self) -> None:
        captured: dict[str, object] = {}

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["body"] = json or {}
            captured["timeout"] = timeout
            return _FakeResponse(
                payload={
                    "newVariables": {
                        "d3ixvj8d": "{\"ignored\": true}",
                    },
                    "answerText": "{\"source_brief\": {\"source_title\": \"夜行审判\"}}",
                }
            )

        with patch.dict(
            os.environ,
            {
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "FASTGPT_API_KEY": "fastgpt-global-key",
                "FASTGPT_CHAT_COMPLETIONS_URL": "https://api.fastgpt.in/api/v1/chat/completions",
            },
            clear=False,
        ):
            with patch.object(service.requests, "post", side_effect=_fake_post):
                payload = service.run_framework_planner_stage("01", _basic_config())

        self.assertTrue(payload["ok"])
        body = captured["body"]
        variables = body["variables"]
        self.assertEqual(variables["mode"], "创作")
        self.assertEqual(variables["zHrEcynX"], "创作")

    def test_stage_04_parses_internal_json_string_from_fastgpt(self) -> None:
        beat_payload = {
            "beat_checkpoint_timeline": [
                {
                    "beat_no": index + 1,
                    "beat_name": service.FIFTEEN_BEAT_NAMES[index],
                    "act": "第一幕" if index < 6 else "第二幕" if index < 12 else "第三幕",
                    "episode_range": f"第{index + 1}集",
                    "checkpoint_title": f"{service.FIFTEEN_BEAT_NAMES[index]}卡点",
                    "narrative_function": "推进主线",
                    "plot_content": "剧情推进",
                    "character_change": "人物变化",
                    "conflict_upgrade": "冲突升级",
                    "hook_or_reversal": "结尾反转",
                    "linked_storylines": ["主角成长线"],
                }
                for index in range(15)
            ],
            "checkpoint_explanation": {
                "overview": "评分后修订版",
                "beat_notes": [{"beat_no": 1, "explanation": "说明"}],
            },
        }

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(
                payload={
                    "newVariables": {
                        "d3ixvj8d": service.json.dumps(beat_payload, ensure_ascii=False),
                    }
                }
            )

        with patch.dict(
            os.environ,
            {
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "FASTGPT_API_KEY": "fastgpt-global-key",
                "FASTGPT_CHAT_COMPLETIONS_URL": "https://api.fastgpt.in/api/v1/chat/completions",
            },
            clear=False,
        ):
            with patch.object(service.requests, "post", side_effect=_fake_post):
                payload = service.run_framework_planner_stage("04", _stage_04_payload())

        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["data"]["beat_checkpoint_timeline"]), 15)
        self.assertEqual(payload["data"]["checkpoint_explanation"]["overview"], "评分后修订版")

    def test_score_endpoint_returns_stable_framework_score_report_string(self) -> None:
        payload = service.run_framework_planner_score(
            {
                "beat_checkpoint_timeline": service._build_mock_stage_output("04", _stage_04_payload())[0]["beat_checkpoint_timeline"],
                "checkpoint_explanation": {"overview": "ok"},
            }
        )

        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["data"]["framework_score_report"], str)
        self.assertIn("PASS", payload["data"]["framework_score_report"])


if __name__ == "__main__":
    unittest.main()
