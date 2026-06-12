from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from workflow_code_skeleton.app.services import framework_planner_service as service


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload=None,
        text: str = "",
        reason: str = "OK",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.reason = reason
        self.headers = headers or {"Content-Type": "application/json"}

    def json(self):
        return self._payload


class _FakeInvalidJsonResponse(_FakeResponse):
    def json(self):
        raise ValueError("invalid json payload")


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


def _valid_stage04_output(*, total_episodes: int = 60, camel_case: bool = False) -> dict[str, object]:
    timeline: list[dict[str, object]] = []
    for index in range(15):
        episode = 1 if total_episodes == 1 else min(total_episodes, index + 1)
        beat = {
            "beat_no": index + 1,
            "beat_name": service.FIFTEEN_BEAT_NAMES[index],
            "act": "第一幕" if index < 6 else "第二幕" if index < 12 else "第三幕",
            "episode_range": f"第{episode}集",
            "checkpoint_title": f"{service.FIFTEEN_BEAT_NAMES[index]}卡点",
            "narrative_function": f"第{index + 1}节拍推动主线进入新压力点",
            "plot_content": f"第{index + 1}节拍中林渡发现新线索并被迫作出选择",
            "character_change": f"林渡在第{index + 1}节拍完成一次认知或行动转向",
            "conflict_upgrade": f"反派压力在第{index + 1}节拍升级",
            "hook_or_reversal": f"第{index + 1}节拍结尾留下反转钩子",
            "linked_storylines": ["主角成长线"],
        }
        if camel_case:
            beat = {
                "beatNo": beat["beat_no"],
                "beatName": beat["beat_name"],
                "act": beat["act"],
                "episodeRange": beat["episode_range"],
                "checkpointTitle": beat["checkpoint_title"],
                "narrativeFunction": beat["narrative_function"],
                "plotContent": beat["plot_content"],
                "characterChange": beat["character_change"],
                "conflictUpgrade": beat["conflict_upgrade"],
                "hookOrReversal": beat["hook_or_reversal"],
                "linkedStorylines": beat["linked_storylines"],
            }
        timeline.append(beat)
    return {
        "beat_checkpoint_timeline": timeline,
        "checkpoint_explanation": {
            "overview": "十五节拍均围绕旧案真相和人物转向推进。",
            "beat_notes": [
                {"beat_no": index + 1, "explanation": f"第{index + 1}节拍说明"}
                for index in range(15)
            ],
        },
        "display_text": "stage04 valid output",
    }


def _stage_05_payload() -> dict[str, object]:
    return {
        "mode": "创作",
        "source_brief": {"source_title": "夜行审判"},
        "basic_config": _basic_config(),
        "worldview_plan": {"world_type": "近未来都市"},
        "character_plan": {"protagonist": {"name": "林渡"}},
        "beat_checkpoint_timeline": [{"beat_no": 1, "beat_name": "开场"}] * 15,
        "previous_character_storylines": [],
        "current_storyline_decisions": [],
        "user_feedback": "",
        "adaptation_direction": "强化中点反转和强情绪推进。",
        "user_requirements": "保留主角成长线。",
    }


def _stage_06_payload() -> dict[str, object]:
    return {
        "mode": "创作",
        "source_brief": {"source_title": "夜行审判"},
        "basic_config": _basic_config(),
        "worldview_plan": {"world_type": "近未来都市"},
        "character_plan": {"protagonist": {"name": "林渡"}},
        "beat_checkpoint_timeline": [{"beat_no": 1, "beat_name": "开场"}] * 15,
        "character_storylines": [{"id": "main", "title": "主角成长线"}],
        "storyline_decisions": [{"storyline_id": "main", "decision": "keep"}],
        "previous_adaptation_guide": {},
        "user_feedback": "",
        "adaptation_direction": "强化中点反转和强情绪推进。",
        "user_requirements": "突出情绪推进。",
    }


def _stage_02_payload() -> dict[str, object]:
    return {
        "mode": "创作",
        "source_brief": {"source_title": "夜行审判"},
        "locked_basic_config": _basic_config(),
        "previous_worldview_plan": {},
        "user_feedback": "",
        "adaptation_direction": "强化中点反转和强情绪推进。",
        "user_requirements": "世界观需服务悬疑主线。",
    }


def _stage_03_payload() -> dict[str, object]:
    return {
        "mode": "创作",
        "source_brief": {"source_title": "夜行审判"},
        "locked_basic_config": _basic_config(),
        "worldview_plan": {"world_type": "近未来都市"},
        "previous_character_plan": {},
        "user_feedback": "",
        "adaptation_direction": "强化中点反转和强情绪推进。",
        "user_requirements": "主角必须有明显成长弧光。",
    }


def _stage_07_payload() -> dict[str, object]:
    return {
        "mode": "创作",
        "basic_config": _basic_config(),
        "source_brief": {"source_title": "夜行审判"},
        "worldview_plan": {"world_type": "近未来都市"},
        "character_plan": {"protagonist": {"name": "林渡"}},
        "beat_checkpoint_timeline": [{"beat_no": 1, "beat_name": "开场"}] * 15,
        "checkpoint_explanation": {"overview": "ok"},
        "character_storylines": [{"id": "main", "title": "主角成长线", "decision": "keep"}],
        "storyline_decisions": [{"storyline_id": "main", "decision": "keep"}],
        "adaptation_guide": {"core_setting_adjustments": "ok"},
        "user_edit_history": [],
        "previous_framework_plan_package": {},
        "user_feedback": "",
        "adaptation_direction": "强化中点反转和强情绪推进。",
        "user_requirements": "保持主角成长弧。",
    }


class FrameworkPlannerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._previous_backend = os.environ.get("WORKFLOW_BACKEND")
        os.environ["WORKFLOW_BACKEND"] = "fastgpt"
        service.framework_workflow_dir.cache_clear()
        service.resolve_framework_contract_path.cache_clear()
        service.resolve_stage_workflow_path.cache_clear()
        service.load_stage_workflow_spec.cache_clear()

    def tearDown(self) -> None:
        if self._previous_backend is None:
            os.environ.pop("WORKFLOW_BACKEND", None)
        else:
            os.environ["WORKFLOW_BACKEND"] = self._previous_backend

    def test_resolve_stage_workflow_path_reads_better_framework_jsons(self) -> None:
        path = service.resolve_stage_workflow_path("04")
        self.assertIsInstance(path, Path)
        self.assertTrue(path.name.startswith("beat04"))
        self.assertIn("BETTER_FRAMEWORK_YAML", str(path))

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

    def test_stage_04_mock_output_respects_one_episode_total(self) -> None:
        stage_payload = _stage_04_payload()
        stage_payload["basic_config"] = {
            **_basic_config(),
            "season_count": 1,
            "episodes_per_season": 1,
            "total_episodes": 1,
        }
        with patch.dict(os.environ, {"FRAMEWORK_PLANNER_USE_MOCK": "true"}, clear=False):
            payload = service.run_framework_planner_stage("04", stage_payload)

        beats = payload["data"]["beat_checkpoint_timeline"]
        self.assertEqual(len(beats), 15)
        for item in beats:
            numbers = [int(value) for value in re.findall(r"\d+", item["episode_range"])]
            self.assertTrue(numbers)
            self.assertLessEqual(max(numbers), 1)

    def test_stage_01_sends_yaml_variables_to_coze_parameters(self) -> None:
        captured: dict[str, object] = {}

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["body"] = json or {}
            captured["timeout"] = timeout
            return _FakeResponse(
                payload={
                    "code": 0,
                    "data": service.json.dumps(
                        {
                            "confirmed_info": service.json.dumps(
                                {"source_brief": {"source_title": "coze-source"}},
                                ensure_ascii=False,
                            )
                        },
                        ensure_ascii=False,
                    ),
                }
            )
        with patch.dict(
            os.environ,
            {
                "WORKFLOW_BACKEND": "coze",
                "COZE_CREDENTIALS_ORDER": "primary,secondary",
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "COZE_PRIMARY_API_TOKEN": "coze-token",
                "COZE_PRIMARY_API_BASE": "https://api.coze.cn",
                "COZE_WORKFLOW_STAGE_01_ID": "stage-01-workflow",
                "FASTGPT_API_KEY": "fastgpt-global-key",
                "FASTGPT_CHAT_COMPLETIONS_URL": "https://api.fastgpt.in/api/v1/chat/completions",
            },
            clear=False,
        ):
            with patch.object(service.requests, "post", side_effect=_fake_post):
                payload = service.run_framework_planner_stage("01", _basic_config())

        self.assertTrue(payload["ok"])
        self.assertEqual(captured["url"], "https://api.coze.cn/v1/workflow/run")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer coze-token")
        body = captured["body"]
        self.assertEqual(body["workflow_id"], "stage-01-workflow")
        parameters = body["parameters"]
        self.assertEqual(parameters["mode"], _basic_config()["mode"])
        self.assertNotIn("zHrEcynX", parameters)
        self.assertIn("user_requirements", parameters)
        self.assertIn("source_brief", payload["data"])

    def test_stage_01_coze_sends_blank_declared_yaml_parameters(self) -> None:
        captured: dict[str, object] = {}

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, timeout
            captured["body"] = json or {}
            return _FakeResponse(
                payload={
                    "code": 0,
                    "data": service.json.dumps(
                        {"confirmed_info": {"source_brief": {"source_title": "coze-source"}}},
                        ensure_ascii=False,
                    ),
                }
            )

        request_payload = _basic_config()
        request_payload.update(
            {
                "source_text": "",
                "adaptation_direction": "",
                "user_constraints": "",
                "user_requirements": "",
            }
        )
        with patch.dict(
            os.environ,
            {
                "WORKFLOW_BACKEND": "coze",
                "COZE_CREDENTIALS_ORDER": "secondary",
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "COZE_PRIMARY_API_TOKEN": "primary-token",
                "COZE_SECONDARY_API_TOKEN": "secondary-token",
                "COZE_SECONDARY_API_BASE": "https://api.coze.cn",
                "COZE_WORKFLOW_STAGE_01_ID": "stage-01-workflow",
            },
            clear=False,
        ):
            with patch.object(service.requests, "post", side_effect=_fake_post):
                service.run_framework_planner_stage("01", request_payload)

        parameters = captured["body"]["parameters"]
        self.assertEqual(parameters["source_text"], "")
        self.assertEqual(parameters["adaptation_direction"], "")
        self.assertEqual(parameters["user_constraints"], "")
        self.assertEqual(parameters["user_requirements"], "")

    def test_coze_credentials_order_secondary_is_strict_for_framework_planner(self) -> None:
        captured: dict[str, object] = {}

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, json, timeout
            captured["headers"] = headers or {}
            return _FakeResponse(
                payload={
                    "code": 0,
                    "data": service.json.dumps(
                        {"confirmed_info": {"source_brief": {"source_title": "coze-source"}}},
                        ensure_ascii=False,
                    ),
                }
            )

        with patch.dict(
            os.environ,
            {
                "WORKFLOW_BACKEND": "coze",
                "COZE_CREDENTIALS_ORDER": "secondary",
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "COZE_PRIMARY_API_TOKEN": "primary-token",
                "COZE_SECONDARY_API_TOKEN": "secondary-token",
                "COZE_SECONDARY_API_BASE": "https://api.coze.cn",
                "COZE_WORKFLOW_STAGE_01_ID": "stage-01-workflow",
            },
            clear=False,
        ):
            with patch.object(service.requests, "post", side_effect=_fake_post):
                service.run_framework_planner_stage("01", _basic_config())

        self.assertEqual(captured["headers"]["Authorization"], "Bearer secondary-token")

    def test_stage_02_coze_wraps_direct_business_object(self) -> None:
        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(
                payload={
                    "code": 0,
                    "data": service.json.dumps(
                        {
                            "background": "rules-first world",
                            "rules": ["one visible rule"],
                        },
                        ensure_ascii=False,
                    ),
                }
            )

        with patch.dict(
            os.environ,
            {
                "WORKFLOW_BACKEND": "coze",
                "COZE_CREDENTIALS_ORDER": "primary,secondary",
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "COZE_PRIMARY_API_TOKEN": "coze-token",
                "COZE_WORKFLOW_STAGE_02_ID": "stage-02-workflow",
            },
            clear=False,
        ):
            with patch.object(service.requests, "post", side_effect=_fake_post):
                payload = service.run_framework_planner_stage("02", _stage_02_payload())

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["worldview_plan"]["background"], "rules-first world")

    def test_stage_03_coze_preserves_chinese_character_name_aliases(self) -> None:
        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(
                payload={
                    "code": 0,
                    "data": {
                        "output": "```json\n"
                        + service.json.dumps(
                            {
                                "characters": [
                                    {"姓名 / 合法称呼": "林渡", "角色定位": "主角", "goal": "查明旧案"},
                                    {"姓名 / 合法称呼": "沈念", "角色定位": "盟友", "goal": "协助查案"},
                                ],
                                "display_text": "character aliases ok",
                            },
                            ensure_ascii=False,
                        )
                        + "\n```"
                    },
                }
            )

        with patch.dict(
            os.environ,
            {
                "WORKFLOW_BACKEND": "coze",
                "COZE_CREDENTIALS_ORDER": "primary,secondary",
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "COZE_PRIMARY_API_TOKEN": "coze-token",
                "COZE_WORKFLOW_STAGE_03_ID": "stage-03-workflow",
            },
            clear=False,
        ):
            with patch.object(service.requests, "post", side_effect=_fake_post):
                payload = service.run_framework_planner_stage("03", _stage_03_payload())

        characters = payload["data"]["character_plan"]["main_characters"]
        names = [item.get("name") for item in characters]
        self.assertIn("林渡", names)
        self.assertIn("沈念", names)
        self.assertNotEqual(names, ["主角", "主角"])
        self.assertEqual(payload["data"]["character_plan"]["protagonist"]["name"], "林渡")

    def test_stage_04_coze_parses_wrapped_markdown_alias_payload(self) -> None:
        valid = _valid_stage04_output(total_episodes=1, camel_case=True)
        coze_payload = {
            "result": {
                "beatCheckpointTimeline": valid["beat_checkpoint_timeline"],
                "checkpointExplanation": valid["checkpoint_explanation"],
                "display_text": "alias stage04 ok",
            }
        }

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(
                payload={
                    "code": 0,
                    "data": {
                        "output": "```json\n"
                        + service.json.dumps(coze_payload, ensure_ascii=False)
                        + "\n```"
                    },
                }
            )

        request_payload = _stage_04_payload()
        request_payload["basic_config"] = {
            **_basic_config(),
            "season_count": 1,
            "episodes_per_season": 1,
            "total_episodes": 1,
            "episode_count_guard": {"season_count": 1, "episodes_per_season": 1, "total_episodes": 1},
        }
        request_payload.update(
            {
                "season_count": 1,
                "episodes_per_season": 1,
                "total_episodes": 1,
                "episode_count_guard": {"season_count": 1, "episodes_per_season": 1, "total_episodes": 1},
            }
        )

        with patch.dict(
            os.environ,
            {
                "WORKFLOW_BACKEND": "coze",
                "COZE_CREDENTIALS_ORDER": "primary,secondary",
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "COZE_PRIMARY_API_TOKEN": "coze-token",
                "COZE_WORKFLOW_STAGE_04_ID": "stage-04-workflow",
            },
            clear=False,
        ):
            with patch.object(service.requests, "post", side_effect=_fake_post):
                payload = service.run_framework_planner_stage("04", request_payload)

        beats = payload["data"]["beat_checkpoint_timeline"]
        self.assertEqual(len(beats), 15)
        self.assertTrue(all(item["episode_range"] == "第1集" for item in beats))
        self.assertTrue(all(item["plot_content"] for item in beats))
        self.assertEqual(payload["display_text"], "alias stage04 ok")

    def test_stage_04_coze_rejects_empty_placeholder_timeline(self) -> None:
        bad_timeline = [
            {
                "beatNo": index + 1,
                "beatName": service.FIFTEEN_BEAT_NAMES[index],
                "episodeRange": "未明确，需后续确认集数后重排",
            }
            for index in range(15)
        ]

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(
                payload={
                    "code": 0,
                    "data": {
                        "output": service.json.dumps(
                            {
                                "beatCheckpointTimeline": bad_timeline,
                                "checkpointExplanation": {
                                    "beat_notes": [{"beat_no": index + 1, "explanation": ""} for index in range(15)]
                                },
                            },
                            ensure_ascii=False,
                        )
                    },
                }
            )

        request_payload = _stage_04_payload()
        request_payload["basic_config"] = {
            **_basic_config(),
            "season_count": 1,
            "episodes_per_season": 1,
            "total_episodes": 1,
            "episode_count_guard": {"season_count": 1, "episodes_per_season": 1, "total_episodes": 1},
        }

        with patch.dict(
            os.environ,
            {
                "WORKFLOW_BACKEND": "coze",
                "COZE_CREDENTIALS_ORDER": "primary,secondary",
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "COZE_PRIMARY_API_TOKEN": "coze-token",
                "COZE_WORKFLOW_STAGE_04_ID": "stage-04-workflow",
            },
            clear=False,
        ):
            with patch.object(service.requests, "post", side_effect=_fake_post):
                with self.assertRaises(service.FrameworkPlannerStageError) as raised:
                    service.run_framework_planner_stage("04", request_payload)

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("stage04_content_fields_sparse", raised.exception.detail["failures"])
        self.assertIn("stage04_episode_range_invalid", raised.exception.detail["failures"])

    def test_stage_04_sends_yaml_score_repo_and_user_requirements_to_coze(self) -> None:
        captured: dict[str, object] = {}

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["body"] = json or {}
            captured["timeout"] = timeout
            return _FakeResponse(
                payload={
                    "code": 0,
                    "data": service.json.dumps(
                        {
                            "beat": service.json.dumps(
                                _valid_stage04_output(),
                                ensure_ascii=False,
                            )
                        },
                        ensure_ascii=False,
                    ),
                }
            )
        with patch.dict(
            os.environ,
            {
                "WORKFLOW_BACKEND": "coze",
                "COZE_CREDENTIALS_ORDER": "primary,secondary",
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "COZE_PRIMARY_API_TOKEN": "coze-token",
                "COZE_WORKFLOW_STAGE_04_ID": "stage-04-workflow",
                "FASTGPT_API_KEY": "fastgpt-global-key",
                "FASTGPT_CHAT_COMPLETIONS_URL": "https://api.fastgpt.in/api/v1/chat/completions",
            },
            clear=False,
        ):
            with patch.object(service.requests, "post", side_effect=_fake_post):
                payload = _stage_04_payload()
                payload["framework_score_report"] = "REVISE\\n需要补强中点反转。"
                payload.update(
                    {
                        "season_count": 1,
                        "episodes_per_season": 60,
                        "total_episodes": 60,
                        "episode_count_guard": {
                            "season_count": 1,
                            "episodes_per_season": 60,
                            "total_episodes": 60,
                        },
                    }
                )
                service.run_framework_planner_stage("04", payload)

        parameters = captured["body"]["parameters"]
        self.assertEqual(captured["body"]["workflow_id"], "stage-04-workflow")
        self.assertIn("user_requirements", parameters)
        self.assertIn("framework_score_repo", parameters)
        self.assertNotIn("framework_score_report", parameters)
        self.assertEqual(parameters["season_count"], 1)
        self.assertEqual(parameters["episodes_per_season"], 60)
        self.assertEqual(parameters["total_episodes"], 60)
        self.assertEqual(service.json.loads(parameters["episode_count_guard"])["total_episodes"], 60)

    def test_stage_has_real_backend_accepts_legacy_and_framework_api_key_envs(self) -> None:
        with patch.dict(
            os.environ,
            {
                "WORKFLOW_BACKEND": "fastgpt",
                "FASTGPT_FRAMEWORK_API_KEY": "fastgpt-framework-key",
                "FASTGPT_BETTER_FRAMEWORK_PLOT_KEY_POINT_PLANNING": "fastgpt-legacy-stage-key",
            },
            clear=True,
        ):
            self.assertTrue(service.stage_has_real_backend("01"))
            self.assertTrue(service.stage_has_real_backend("04"))

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

    def test_safe_parse_stage_output_accepts_list_string_and_dict(self) -> None:
        parsed_from_list, list_warnings = service.safe_parse_stage_output(
            [{"source_brief": {"source_title": "夜行审判"}}],
            ("source_brief", "display_text"),
        )
        self.assertEqual(parsed_from_list["source_brief"]["source_title"], "夜行审判")
        self.assertIsInstance(list_warnings, list)

        parsed_from_string, string_warnings = service.safe_parse_stage_output(
            service.json.dumps({"worldview_plan": {"world_type": "近未来都市"}}, ensure_ascii=False),
            ("worldview_plan", "display_text"),
        )
        self.assertEqual(parsed_from_string["worldview_plan"]["world_type"], "近未来都市")
        self.assertIsInstance(string_warnings, list)

        parsed_from_dict, dict_warnings = service.safe_parse_stage_output(
            {"character_plan": {"protagonist": {"name": "林渡"}}},
            ("character_plan", "display_text"),
        )
        self.assertEqual(parsed_from_dict["character_plan"]["protagonist"]["name"], "林渡")
        self.assertIsInstance(dict_warnings, list)

    def test_normalize_stage_response_accepts_list_string_and_dict(self) -> None:
        normalized_from_list = service.normalize_stage_response(
            [{"source_brief": {"source_title": "夜行审判"}}],
            stage="01",
            payload_keys=["source_text"],
        )
        self.assertIsInstance(normalized_from_list, dict)
        self.assertEqual(normalized_from_list["source_brief"]["source_title"], "夜行审判")

        normalized_from_string = service.normalize_stage_response(
            service.json.dumps({"responseData": {"answerText": "ok"}}, ensure_ascii=False),
            stage="01",
            payload_keys=["source_text"],
        )
        self.assertIsInstance(normalized_from_string, dict)
        self.assertEqual(normalized_from_string["responseData"]["answerText"], "ok")

        normalized_from_dict = service.normalize_stage_response(
            {"answerText": "done"},
            stage="01",
            payload_keys=["source_text"],
        )
        self.assertIsInstance(normalized_from_dict, dict)
        self.assertEqual(normalized_from_dict["answerText"], "done")

    def test_iter_response_candidates_accepts_list_root_response(self) -> None:
        workflow_spec = service.load_stage_workflow_spec("01")
        candidates = list(
            service._iter_response_candidates(
                [
                    {
                        "responseData": {
                            "answerText": "list root answer",
                        }
                    }
                ],
                workflow_spec,
                stage="01",
                payload_keys=["source_text"],
            )
        )

        self.assertTrue(candidates)
        self.assertIn(("root.responseData.answerText", "list root answer"), candidates)

    def test_stage_01_accepts_list_root_response_and_uses_first_dict(self) -> None:
        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(
                payload=[
                    {
                        "source_brief": {"source_title": "夜行审判", "core_premise": "list root"},
                        "display_text": "list root ok",
                    }
                ]
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
        self.assertEqual(payload["data"]["source_brief"]["source_title"], "夜行审判")
        self.assertEqual(payload["display_text"], "list root ok")

    def test_stage_01_handles_invalid_json_response_text_and_keeps_source_brief_dict(self) -> None:
        raw_text = service.json.dumps(
            [
                {
                    "source_brief": {
                        "source_title": "夜行审判",
                        "core_premise": "invalid json fallback",
                    }
                }
            ],
            ensure_ascii=False,
        )

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeInvalidJsonResponse(text=raw_text)

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
        self.assertIsInstance(payload["data"]["source_brief"], dict)
        self.assertEqual(payload["data"]["source_brief"]["source_title"], "夜行审判")
        self.assertEqual(payload["display_text"], "未明确，需后续确认……")

    def test_stage_02_accepts_list_root_response_and_keeps_worldview_plan_dict(self) -> None:
        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(
                payload=[
                    {
                        "worldview_plan": {
                            "world_type": "近未来都市",
                            "tone": "悬疑压迫",
                        },
                        "display_text": "worldview list root ok",
                    }
                ]
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
                payload = service.run_framework_planner_stage("02", _stage_02_payload())

        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["data"]["worldview_plan"], dict)
        self.assertEqual(payload["data"]["worldview_plan"]["world_type"], "近未来都市")
        self.assertEqual(payload["display_text"], "worldview list root ok")

    def test_stage_03_accepts_string_root_response_and_keeps_character_plan_dict(self) -> None:
        raw_text = service.json.dumps(
            {
                "character_plan": {
                    "protagonist": {"name": "林渡"},
                    "antagonist": {"name": "沈峥"},
                },
                "display_text": "character string root ok",
            },
            ensure_ascii=False,
        )

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(payload=raw_text)

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
                payload = service.run_framework_planner_stage("03", _stage_03_payload())

        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["data"]["character_plan"], dict)
        self.assertEqual(payload["data"]["character_plan"]["protagonist"]["name"], "林渡")
        self.assertEqual(payload["display_text"], "character string root ok")

    def test_stage_04_accepts_string_root_json_response(self) -> None:
        raw_text = service.json.dumps(
            {
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
                "checkpoint_explanation": {"overview": "string root ok"},
                "display_text": "string root display",
            },
            ensure_ascii=False,
        )

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(payload=raw_text)

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
        self.assertEqual(payload["data"]["checkpoint_explanation"]["overview"], "string root ok")
        self.assertEqual(payload["display_text"], "string root display")

    def test_stage_04_accepts_direct_list_root_timeline_and_keeps_checkpoint_placeholder(self) -> None:
        raw_timeline = [
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
        ]

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(payload=raw_timeline)

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
        self.assertIsInstance(payload["data"]["checkpoint_explanation"], dict)
        self.assertIn("overview", payload["data"]["checkpoint_explanation"])

    def test_stage_05_accepts_direct_list_root_storylines_and_keeps_list(self) -> None:
        raw_storylines = [
            {
                "id": "main",
                "title": "主角成长线",
                "summary": "律师回乡追查旧案真相。",
                "detailed_storyline": "主角在父亲旧案与现实阴谋之间不断做出艰难抉择。",
                "linked_beats": [1, 4, 9, 15],
                "episode_distribution": [{"episode_range": "第1-10集", "focus": "回乡调查"}],
                "edit_notes": "保持情绪递进",
                "decision": "keep",
            }
        ]

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(payload=raw_storylines)

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
                payload = service.run_framework_planner_stage("05", _stage_05_payload())

        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["data"]["character_storylines"], list)
        self.assertEqual(payload["data"]["character_storylines"][0]["id"], "main")

    def test_stage_05_prefers_fastgpt_response_data_answer_text_business_json(self) -> None:
        answer_payload = {
            "character_storylines": [
                {
                    "id": "protagonist_main_line",
                    "character_name": "A",
                    "line_type": "主角线",
                    "importance": "main",
                    "decision": "keep",
                    "summary": "...",
                    "linked_beats": [1],
                    "episode_distribution": [
                        {
                            "episode_range": "1-3",
                            "function": "...",
                            "event": "...",
                            "relation_to_beat": "对应第1节拍：开场",
                        }
                    ],
                    "detailed_storyline": "...",
                    "edit_notes": "...",
                }
            ],
            "display_text": "人物故事线已生成",
        }
        fastgpt_root = {
            "responseData": [
                {"moduleName": "workflowStart", "moduleType": "workflowStart"},
                {
                    "moduleName": "05 人物故事线生成更新",
                    "moduleType": "chatNode",
                    "answerText": service.json.dumps(answer_payload, ensure_ascii=False),
                },
                {
                    "moduleName": "输出05 人物故事线生成更新",
                    "moduleType": "answerNode",
                    "text": "answer node fallback text",
                },
            ],
            "answerText": "root fallback should not win",
        }

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(payload=fastgpt_root)

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
                payload = service.run_framework_planner_stage("05", _stage_05_payload())

        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["data"]["character_storylines"], list)
        self.assertTrue(payload["data"]["character_storylines"])
        self.assertEqual(payload["data"]["character_storylines"][0]["id"], "protagonist_main_line")
        self.assertEqual(payload["display_text"], "人物故事线已生成")
        self.assertNotIn(
            "character_storylines 不是 list，已回退为空数组",
            " | ".join(payload["raw"]["parse_warning"]),
        )

    def test_stage_05_request_variables_clean_polluted_character_plan(self) -> None:
        definition = service.stage_definition("05")
        workflow_spec = service.load_stage_workflow_spec("05")
        polluted_source_brief = {
            "responseData": [
                {
                    "moduleName": "01 原文信息提取",
                    "moduleType": "chatNode",
                    "answerText": service.json.dumps(
                        {"source_brief": {"source_title": "夜行审判"}},
                        ensure_ascii=False,
                    ),
                }
            ],
            "choices": [{"message": {"content": "raw"}}],
            "usage": {"inputTokens": 1000},
            "historyPreview": "历史预览",
        }
        polluted_worldview_plan = {
            "responseData": [
                {
                    "moduleName": "02 世界观",
                    "moduleType": "chatNode",
                    "answerText": service.json.dumps(
                        {"worldview_plan": {"world_type": "近未来都市"}},
                        ensure_ascii=False,
                    ),
                }
            ],
            "reasoningText": "不要传给 FastGPT",
        }
        polluted_character_plan = {
            "responseData": [
                {"moduleName": "start", "moduleType": "workflowStart"},
                {
                    "moduleName": "03 人物设定",
                    "moduleType": "chatNode",
                    "answerText": service.json.dumps(
                        {"character_plan": {"protagonist": {"name": "林渡"}}},
                        ensure_ascii=False,
                    ),
                },
            ],
            "reasoningText": "不要传给 FastGPT",
            "historyPreview": "历史预览",
        }
        payload = {
            **_stage_05_payload(),
            "source_brief": polluted_source_brief,
            "worldview_plan": polluted_worldview_plan,
            "character_plan": polluted_character_plan,
        }

        variables = service._build_stage_request_variables(definition, payload, workflow_spec)

        for key in ("source_brief", "worldview_plan", "character_plan"):
            self.assertNotIn("responseData", variables[key])
            self.assertNotIn("reasoningText", variables[key])
            self.assertNotIn("historyPreview", variables[key])
            self.assertNotIn("choices", variables[key])
            self.assertNotIn("usage", variables[key])
        self.assertIn("夜行审判", variables["source_brief"])
        self.assertIn("近未来都市", variables["worldview_plan"])
        self.assertIn("character_plan", variables)
        self.assertIn("林渡", variables["character_plan"])

    def test_stage_05_request_variables_exclude_raw_fastgpt_debug_payloads(self) -> None:
        definition = service.stage_definition("05")
        workflow_spec = service.load_stage_workflow_spec("05")
        payload = {
            **_stage_05_payload(),
            "previous_character_storylines": [{"id": "old", "title": "旧线"}],
            "current_storyline_decisions": [{"storyline_id": "old", "decision": "keep"}],
            "user_feedback": "保留主线",
            "basic_config": {**_basic_config(), "source_text": "很长原文" * 5000},
            "raw": {"responseData": [{"answerText": "huge"}]},
            "responseData": [{"answerText": "huge"}],
            "reasoningText": "hidden reasoning",
            "historyPreview": "long history",
            "display_text": "previous display text",
        }

        variables = service._build_stage_request_variables(definition, payload, workflow_spec)

        self.assertIn("source_brief", variables)
        self.assertIn("basic_config", variables)
        self.assertIn("worldview_plan", variables)
        self.assertIn("character_plan", variables)
        self.assertIn("beat_checkpoint_time", variables)
        self.assertIn("previous_character", variables)
        self.assertIn("current_storyline", variables)
        self.assertIn("user_feedback", variables)
        self.assertIn("adaptation_direction", variables)
        self.assertIn("user_requirements", variables)
        self.assertIn("basic_config", variables)
        self.assertNotIn("beat_checkpoint_timeline", variables)
        self.assertNotIn("previous_character_storylines", variables)
        self.assertNotIn("current_storyline_decisions", variables)
        self.assertNotIn("source_text", variables["basic_config"])
        self.assertIn("project_title", variables["basic_config"])
        self.assertNotIn("raw", variables)
        self.assertNotIn("responseData", variables)
        self.assertNotIn("reasoningText", variables)
        self.assertNotIn("historyPreview", variables)
        self.assertNotIn("display_text", variables)

    def test_stage_05_character_storylines_wrong_type_returns_detail(self) -> None:
        fastgpt_root = {
            "responseData": [
                {
                    "moduleName": "05 人物故事线生成更新",
                    "moduleType": "chatNode",
                    "answerText": service.json.dumps(
                        {
                            "character_storylines": {"id": "not-a-list"},
                            "display_text": "类型错误",
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        }

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(payload=fastgpt_root)

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
                payload = service.run_framework_planner_stage("05", _stage_05_payload())

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["error"], "阶段 05 未解析到有效人物故事线")
        self.assertEqual(payload["detail"]["reason"], "character_storylines_not_list")
        self.assertEqual(payload["detail"]["best_candidate_source"], "responseData[0].answerText")
        self.assertEqual(payload["detail"]["character_storylines_actual_type"], "dict")
        self.assertIn("character_storylines 不是 list，已回退为空数组", " | ".join(payload["raw"]["parse_warning"]))

    def test_stage_05_valid_new_variables_candidate_is_not_overridden_by_root_fallback(self) -> None:
        fastgpt_root = {
            "responseData": [
                {"moduleName": "workflowStart", "moduleType": "workflowStart"},
                {
                    "moduleName": "05 chat invalid",
                    "moduleType": "chatNode",
                    "answerText": service.json.dumps({"foo": "bar"}, ensure_ascii=False),
                },
            ],
            "newVariables": {
                "d3ixvj8d": {
                    "character_storylines": [
                        {
                            "id": "main",
                            "title": "主角成长线",
                            "summary": "有效候选",
                            "detailed_storyline": "有效候选详情",
                            "linked_beats": [1],
                            "episode_distribution": [{"episode_range": "1-3", "focus": "开场"}],
                            "edit_notes": "保留",
                            "decision": "keep",
                        }
                    ],
                    "display_text": "来自变量",
                }
            },
            "answerText": "root fallback should not win",
            "usage": {"inputTokens": 1},
        }

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(payload=fastgpt_root)

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
                payload = service.run_framework_planner_stage("05", _stage_05_payload())

        self.assertTrue(payload["ok"])
        self.assertNotIn("error", payload)
        self.assertEqual(payload["data"]["character_storylines"][0]["id"], "main")
        self.assertEqual(payload["display_text"], "来自变量")
        self.assertNotIn("character_storylines 不是 list，已回退为空数组", " | ".join(payload["raw"]["parse_warning"]))

    def test_stage_06_accepts_string_root_response_and_keeps_adaptation_guide_dict(self) -> None:
        raw_text = service.json.dumps(
            {
                "adaptation_guide": {
                    "core_setting_adjustments": "强化地方财团压迫感",
                    "structure_and_rhythm": "中段加快节奏",
                    "visualization_strategy": "突出夜景与压迫空间",
                    "character_emotion_strategy": "强化父子旧案创伤",
                },
                "display_text": "guide string root ok",
            },
            ensure_ascii=False,
        )

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(payload=raw_text)

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
                payload = service.run_framework_planner_stage("06", _stage_06_payload())

        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["data"]["adaptation_guide"], dict)
        self.assertEqual(payload["data"]["adaptation_guide"]["core_setting_adjustments"], "强化地方财团压迫感")
        self.assertEqual(payload["display_text"], "guide string root ok")

    def test_stage_06_accepts_overall_adaptation_guide_alias(self) -> None:
        fastgpt_root = {
            "overallAdaptationGuide": {
                "core_setting_adjustments": "保留规则对抗骨架",
                "structure_and_rhythm": "前十集加快钩子密度",
                "visualization_strategy": "突出夜景和封闭空间",
                "character_emotion_strategy": "强化主角创伤与复仇动机",
            },
            "display_text": "guide alias ok",
        }

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(payload=fastgpt_root)

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
                payload = service.run_framework_planner_stage("06", _stage_06_payload())

        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["data"]["adaptation_guide"], dict)
        self.assertEqual(payload["data"]["adaptation_guide"]["core_setting_adjustments"], "保留规则对抗骨架")
        self.assertEqual(payload["display_text"], "guide alias ok")

    def test_stage_07_accepts_list_wrapped_object_and_keeps_package_and_validation_dict(self) -> None:
        wrapped_payload = [
            {
                "framework_plan_package": {
                    "basic_config": _basic_config(),
                    "source_brief": {"source_title": "夜行审判"},
                },
                "validation_report": {
                    "summary": "结构完整",
                    "warnings": [],
                },
                "display_text": "package list root ok",
            }
        ]

        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(payload=wrapped_payload)

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
                payload = service.run_framework_planner_stage("07", _stage_07_payload())

        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["data"]["framework_plan_package"], dict)
        self.assertIsInstance(payload["data"]["validation_report"], dict)
        self.assertEqual(payload["data"]["validation_report"]["summary"], "结构完整")
        self.assertEqual(payload["display_text"], "package list root ok")

    def test_stage_07_falls_back_to_empty_structures_and_sets_parse_warning(self) -> None:
        def _fake_post(url, *, headers=None, json=None, timeout=None):
            del url, headers, json, timeout
            return _FakeResponse(payload=["not-a-dict"])

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
                payload = service.run_framework_planner_stage("07", _stage_07_payload())

        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["data"]["framework_plan_package"], dict)
        self.assertIsInstance(payload["data"]["framework_plan_package"].get("beat_checkpoint_timeline"), list)
        self.assertIsInstance(payload["data"]["framework_plan_package"].get("character_storylines"), list)
        self.assertIsInstance(payload["data"]["validation_report"].get("parse_warning"), list)
        self.assertTrue(payload["raw"]["parse_warning"])

    def test_stage_endpoint_resolution_accepts_fastgpt_api_url_and_new_framework_api_key_alias(self) -> None:
        definition = service.stage_definition("01")
        with patch.dict(
            os.environ,
            {
                "WORKFLOW_BACKEND": "fastgpt",
                "FASTGPT_NEW_FRAMEWORK_API_KEY": "framework-new-key",
                "FASTGPT_API_URL": "https://api.fastgpt.in/api/v1",
            },
            clear=True,
        ):
            endpoint = service._resolve_stage_endpoint(definition)

        self.assertEqual(endpoint.api_key_source, "FASTGPT_NEW_FRAMEWORK_API_KEY")
        self.assertEqual(endpoint.url_source, "FASTGPT_API_URL")
        self.assertEqual(endpoint.url, "https://api.fastgpt.in/api/v1/chat/completions")

    def test_stage_01_timeout_returns_structured_fastgpt_failure_detail(self) -> None:
        with patch.dict(
            os.environ,
            {
                "WORKFLOW_BACKEND": "fastgpt",
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "FASTGPT_FRAMEWORK_API_KEY": "fastgpt-framework-key",
                "FASTGPT_API_URL": "https://api.fastgpt.in/api/v1",
            },
            clear=True,
        ):
            with patch.object(service.requests, "post", side_effect=requests.Timeout("upstream timeout")):
                with self.assertRaises(service.FrameworkPlannerStageError) as ctx:
                    service.run_framework_planner_stage("01", _basic_config())

        exc = ctx.exception
        self.assertEqual(str(exc), "阶段 01 请求 FastGPT 失败")
        self.assertEqual(exc.status_code, 504)
        self.assertEqual(exc.detail["reason"], "FastGPT 请求超时，已重试 3 次仍失败")
        self.assertEqual(exc.detail["url"], "https://api.fastgpt.in/api/v1/chat/completions")
        self.assertEqual(exc.detail["attempts"], 3)
        self.assertTrue(exc.detail["has_api_key"])
        self.assertFalse(exc.detail["has_workflow_id"])
        self.assertTrue(exc.detail["base_url_configured"])
        self.assertTrue(exc.detail["entered_fastgpt_request"])
        self.assertEqual(exc.detail["exception_type"], "Timeout")
        self.assertIn("upstream timeout", exc.detail["exception_message"])
        self.assertEqual(exc.detail["last_exception_type"], "Timeout")
        self.assertIn("upstream timeout", exc.detail["last_exception_message"])

    def test_stage_05_connect_timeout_returns_connection_diagnostics(self) -> None:
        with patch.dict(
            os.environ,
            {
                "WORKFLOW_BACKEND": "fastgpt",
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "FASTGPT_API_KEY": "fastgpt-global-key",
                "FASTGPT_CHAT_COMPLETIONS_URL": "http://192.168.2.203:3000/api/v1/chat/completions",
            },
            clear=True,
        ):
            with patch.object(service.requests, "post", side_effect=requests.ConnectTimeout("connect timed out")):
                with self.assertRaises(service.FrameworkPlannerStageError) as ctx:
                    service.run_framework_planner_stage("05", _stage_05_payload())

        exc = ctx.exception
        self.assertEqual(str(exc), "阶段 05 无法连接 FastGPT 服务")
        self.assertEqual(exc.status_code, 504)
        self.assertEqual(exc.detail["exception_type"], "ConnectTimeout")
        self.assertEqual(exc.detail["endpoint"], "http://192.168.2.203:3000/api/v1/chat/completions")
        self.assertEqual(exc.detail["host"], "192.168.2.203")
        self.assertEqual(exc.detail["port"], 3000)
        self.assertIn("FASTGPT_CHAT_COMPLETIONS_URL", exc.detail["suggestion"])

    def test_fastgpt_diagnostics_do_not_expose_api_key(self) -> None:
        with patch.dict(
            os.environ,
            {
                "WORKFLOW_BACKEND": "fastgpt",
                "FRAMEWORK_PLANNER_USE_MOCK": "false",
                "FASTGPT_API_KEY": "fastgpt-global-key",
                "FASTGPT_CHAT_COMPLETIONS_URL": "http://192.168.2.203:3000/api/v1/chat/completions",
            },
            clear=True,
        ):
            diagnostics = service.framework_planner_fastgpt_diagnostics("05")

        self.assertEqual(diagnostics["endpoint"], "http://192.168.2.203:3000/api/v1/chat/completions")
        self.assertEqual(diagnostics["host"], "192.168.2.203")
        self.assertEqual(diagnostics["port"], 3000)
        self.assertTrue(diagnostics["has_api_key"])
        self.assertEqual(diagnostics["api_key_config_name"], "FASTGPT_API_KEY")
        self.assertNotIn("fastgpt-global-key", str(diagnostics))

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
