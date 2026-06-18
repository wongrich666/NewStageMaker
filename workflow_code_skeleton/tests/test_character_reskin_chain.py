from __future__ import annotations

import json
import os
from collections import Counter
from unittest.mock import patch

import pytest

from workflow_code_skeleton.app.services import character_reskin_chain as chain
from workflow_code_skeleton.app.services import simple_fastgpt_tools as tools


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


def _payload(total_episodes: int = 6) -> dict[str, object]:
    return {
        "title": "镜中雪",
        "source_outline": "原故事大纲",
        "target_style": "换成都市复仇人设",
        "core_scenes": "核心场景",
        "source_characters": "旧人物小传",
        "source_script": "原剧本正文",
        "total_episodes": total_episodes,
        "episode_word_count": 600,
    }


def _env() -> dict[str, str]:
    return {name: f"key-{index}" for index, name in enumerate(chain.DEDICATED_API_KEY_ENVS, start=1)} | {
        "FASTGPT_CHAT_COMPLETIONS_URL": "https://fastgpt.example.test/api/v1/chat/completions"
    }


def _stage_from_headers(headers: dict[str, str]) -> str:
    token = str(headers.get("Authorization") or "").replace("Bearer ", "")
    reverse = {f"key-{index}": name for index, name in enumerate(chain.DEDICATED_API_KEY_ENVS, start=1)}
    env_name = reverse[token]
    return {
        "FASTGPT_COUNT_ACTUAL_EPISODES_KEY": "actual_episode_count",
        "FASTGPT_REWRITE_CHARACTER_PROFILE_KEY": "profile_rewrite",
        "FASTGPT_REVIEW_CHARACTER_PROFILE_KEY": "profile_review",
        "FASTGPT_WRITE_CHARACTER_PROFILE_KEY": "profile_write",
        "FASTGPT_SORT_CHARACTER_PROFILE_KEY": "profile_sort",
        "FASTGPT_WRITE_CHARACTER_DIALOGUE_KEY": "dialogue_write",
        "FASTGPT_REVIEW_CHARACTER_DIALOGUE_KEY": "dialogue_review",
        "FASTGPT_REWRITE_CHARACTER_DIALOGUE_KEY": "dialogue_rewrite",
        "FASTGPT_WRITE_SCRIPT_BODY_KEY": "body_write",
        "FASTGPT_REVIEW_SCRIPT_BODY_KEY": "body_review",
        "FASTGPT_REWRITE_SCRIPT_BODY_KEY": "body_rewrite",
        "FASTGPT_SCRIPT_MEMORY_KEY": "script_memory",
    }[env_name]


def test_character_reskin_runs_all_stages_and_concatenates_batches() -> None:
    calls: list[dict[str, object]] = []

    def fake_post(url, *, headers=None, json=None, timeout=None):
        del url, timeout
        stage = _stage_from_headers(headers or {})
        variables = (json or {})["variables"]
        calls.append({"stage": stage, "variables": variables})
        if stage == "profile_write":
            return _FakeResponse({"answerText": '{"name":"新主角"}'})
        if stage == "actual_episode_count":
            return _FakeResponse({"answerText": "6"})
        if stage == "profile_review":
            return _FakeResponse({"u3ymVRAj": '{"passed":true,"rewrite_required":false}'})
        if stage == "profile_sort":
            return _FakeResponse({"vVtCqEXZ": "新人设小传"})
        if stage == "dialogue_write":
            return _FakeResponse({"answerText": '{"dialogue":"批次对话"}'})
        if stage == "dialogue_review":
            return _FakeResponse({"answerText": '{"passed":true,"rewrite_required":false}'})
        if stage == "body_write":
            return _FakeResponse({"answerText": f"第{variables['d4sfifeZ']}批正文"})
        if stage == "body_review":
            return _FakeResponse({"answerText": '{"passed":true,"rewrite_required":false}'})
        if stage == "script_memory":
            return _FakeResponse({"answerText": f'{{"memory":"第{variables["zS2LXibg"]}记忆"}}'})
        raise AssertionError(stage)

    with patch.dict(os.environ, _env(), clear=True), patch.object(chain.requests, "post", side_effect=fake_post):
        result = tools.run_simple_tool("character_reskin", _payload(total_episodes=6))

    assert result["success"] is True
    assert result["output"] == "第1批正文\n\n第6批正文"
    assert result["final_output_text"] == result["output"]
    assert result["character_profile"] == "新人设小传"
    assert result["script_batches"] == ["第1批正文", "第6批正文"]
    assert [call["variables"]["sKq9Iyza"] for call in calls if call["stage"] == "dialogue_write"] == [1, 6]
    assert [call["variables"]["d4sfifeZ"] for call in calls if call["stage"] == "body_write"] == [1, 6]
    first_profile = next(call for call in calls if call["stage"] == "profile_write")
    assert first_profile["variables"]["ayxWwSpE"] == "原故事大纲"
    assert first_profile["variables"]["cUMhDqCG"] == "换成都市复仇人设"
    assert first_profile["variables"]["target_style"] == "换成都市复仇人设"
    assert first_profile["variables"]["mubiao_fengge"] == "换成都市复仇人设"
    assert first_profile["variables"]["mYdSy5nr"] == "换成都市复仇人设"
    assert "pxtQY7p2" not in first_profile["variables"]
    assert "eBEWC07Q" not in first_profile["variables"]
    assert "blkSS7dY" not in first_profile["variables"]
    for key, expected in {
        "n5ZHYrj8": "镜中雪",
        "rxmvq2lS": "核心场景",
        "yYYOuumm": "旧人物小传",
    }.items():
        assert first_profile["variables"][key] == expected
    first_profile_review = next(call for call in calls if call["stage"] == "profile_review")
    assert first_profile_review["variables"] == {
        "n5ZHYrj8": "镜中雪",
        "ayxWwSpE": "原故事大纲",
        "fFM0mroW": {"name": "新主角"},
    }
    first_profile_sort = next(call for call in calls if call["stage"] == "profile_sort")
    assert first_profile_sort["variables"] == {
        "fFM0mroW": {"name": "新主角"},
        "ayxWwSpE": "原故事大纲",
        "ti6oIFwf": "旧人物小传",
    }
    first_dialogue_write = next(call for call in calls if call["stage"] == "dialogue_write")
    assert first_dialogue_write["variables"]["ayxWwSpE"] == "原故事大纲"
    assert first_dialogue_write["variables"]["mYdSy5nr"] == "换成都市复仇人设"


def test_character_reskin_bridges_review_and_memory_variables() -> None:
    calls: list[dict[str, object]] = []

    def fake_post(url, *, headers=None, json=None, timeout=None):
        del url, timeout
        stage = _stage_from_headers(headers or {})
        variables = (json or {})["variables"]
        calls.append({"stage": stage, "variables": variables})
        if stage == "profile_write":
            return _FakeResponse({"answerText": '{"profile":"draft"}'})
        if stage == "actual_episode_count":
            return _FakeResponse({"answerText": "6"})
        if stage == "profile_review":
            return _FakeResponse({"u3ymVRAj": '{"passed":false,"rewrite_required":true,"note":"profile review"}'})
        if stage == "profile_rewrite":
            return _FakeResponse({"wQrZxzeL": '{"profile":"fixed"}'})
        if stage == "profile_sort":
            return _FakeResponse({"vVtCqEXZ": "新人设小传"})
        if stage == "dialogue_write":
            return _FakeResponse({"answerText": '{"dialogue":"draft"}'})
        if stage == "dialogue_review":
            return _FakeResponse({"answerText": '{"passed":false,"rewrite_required":true,"note":"dialogue review"}'})
        if stage == "dialogue_rewrite":
            return _FakeResponse({"answerText": '{"dialogue":"fixed"}'})
        if stage == "body_write":
            return _FakeResponse({"answerText": f"第{variables['d4sfifeZ']}批正文初稿"})
        if stage == "body_review":
            return _FakeResponse({"answerText": '{"passed":false,"rewrite_required":true,"note":"body review"}'})
        if stage == "body_rewrite":
            return _FakeResponse({"answerText": f"第{variables['d4sfifeZ']}批正文修订"})
        if stage == "script_memory":
            return _FakeResponse({"answerText": '{"memory":"承接记忆"}'})
        raise AssertionError(stage)

    with patch.dict(os.environ, _env(), clear=True), patch.object(chain.requests, "post", side_effect=fake_post):
        result = tools.run_simple_tool("character_reskin", _payload(total_episodes=6))

    profile_rewrite = next(call for call in calls if call["stage"] == "profile_rewrite")
    assert profile_rewrite["variables"] == {
        "n5ZHYrj8": "镜中雪",
        "yYYOuumm": "旧人物小传",
        "ayxWwSpE": "原故事大纲",
        "va4Et1LA": {"passed": False, "rewrite_required": True, "note": "profile review"},
        "fFM0mroW": {"profile": "draft"},
        "zz4re7zP": "换成都市复仇人设",
    }
    dialogue_rewrite = next(call for call in calls if call["stage"] == "dialogue_rewrite")
    assert dialogue_rewrite["variables"]["rZL0C6f9"]["note"] == "dialogue review"
    body_rewrite = next(call for call in calls if call["stage"] == "body_rewrite")
    assert body_rewrite["variables"]["gJT2URpY"]["note"] == "body review"
    body_writes = [call for call in calls if call["stage"] == "body_write"]
    body_reviews = [call for call in calls if call["stage"] == "body_review"]
    second_batch_review = next(call for call in body_reviews if call["variables"]["d4sfifeZ"] == 6)
    second_body_rewrite = next(
        call for call in calls
        if call["stage"] == "body_rewrite" and call["variables"]["d4sfifeZ"] == 6
    )
    assert body_writes[0]["variables"]["bai4xfdD"] == ""
    assert body_writes[1]["variables"]["bai4xfdD"]["memory"] == "承接记忆"
    assert second_batch_review["variables"]["ntBQgrAm"]["memory"] == "承接记忆"
    assert second_body_rewrite["variables"]["mcUdAISf"]["memory"] == "承接记忆"
    assert all("pS7JzosX" in call["variables"] for call in body_writes)
    assert result["output"] == "第1批正文修订\n\n第6批正文修订"


def test_character_reskin_review_pass_skips_rewrite_stages() -> None:
    stages: list[str] = []

    def fake_post(url, *, headers=None, json=None, timeout=None):
        del url, json, timeout
        stage = _stage_from_headers(headers or {})
        stages.append(stage)
        if stage.endswith("review"):
            return _FakeResponse({"answerText": '{"passed":true,"rewrite_required":false}'})
        if stage == "actual_episode_count":
            return _FakeResponse({"answerText": "5"})
        if stage == "script_memory":
            return _FakeResponse({"answerText": '{"memory":"ok"}'})
        return _FakeResponse({"answerText": "正文" if stage == "body_write" else '{"ok":true}'})

    with patch.dict(os.environ, _env(), clear=True), patch.object(chain.requests, "post", side_effect=fake_post):
        tools.run_simple_tool("character_reskin", _payload(total_episodes=5))

    counts = Counter(stages)
    assert counts["profile_rewrite"] == 0
    assert counts["dialogue_rewrite"] == 0
    assert counts["body_rewrite"] == 0


def test_character_reskin_missing_dedicated_key_returns_clear_error_without_request() -> None:
    env = _env()
    env.pop("FASTGPT_WRITE_SCRIPT_BODY_KEY")
    with patch.dict(os.environ, env, clear=True), patch.object(chain.requests, "post") as mocked_post:
        with pytest.raises(tools.ToolExecutionError) as exc:
            tools.run_simple_tool("character_reskin", _payload(total_episodes=5))

    assert "FASTGPT_WRITE_SCRIPT_BODY_KEY" in str(exc.value)
    assert "FASTGPT_WRITE_SCRIPT_BODY_KEY" in exc.value.debug["missing_api_key_envs"]
    mocked_post.assert_not_called()


def test_character_reskin_uses_actual_episode_count_and_rejects_incomplete_script() -> None:
    calls: list[dict[str, object]] = []

    def fake_post(url, *, headers=None, json=None, timeout=None):
        del url, timeout
        stage = _stage_from_headers(headers or {})
        variables = (json or {})["variables"]
        calls.append({"stage": stage, "variables": variables})
        if stage == "actual_episode_count":
            return _FakeResponse({"answerText": "3"})
        if stage == "profile_write":
            return _FakeResponse({"answerText": '{"profile":"ok"}'})
        if stage == "profile_review":
            return _FakeResponse({"answerText": '{"passed":true,"rewrite_required":false}'})
        if stage == "profile_sort":
            return _FakeResponse({"vVtCqEXZ": "新人设小传"})
        if stage == "dialogue_write":
            return _FakeResponse({"answerText": '{"dialogue":"1-3"}'})
        if stage == "dialogue_review":
            return _FakeResponse({"answerText": '{"passed":true,"rewrite_required":false}'})
        if stage == "body_write":
            return _FakeResponse({"answerText": "三集正文"})
        if stage == "body_review":
            return _FakeResponse({"answerText": '{"passed":true,"rewrite_required":false}'})
        if stage == "script_memory":
            return _FakeResponse({"answerText": '{"memory":"done"}'})
        raise AssertionError(stage)

    with patch.dict(os.environ, _env(), clear=True), patch.object(chain.requests, "post", side_effect=fake_post):
        result = tools.run_simple_tool("character_reskin", _payload(total_episodes=50))

    assert result["output"] == "三集正文"
    dialogue_writes = [call for call in calls if call["stage"] == "dialogue_write"]
    body_writes = [call for call in calls if call["stage"] == "body_write"]
    assert [call["variables"]["sKq9Iyza"] for call in dialogue_writes] == [1]
    assert body_writes[0]["variables"]["blkSS7dY"] == 3

    def incomplete_post(url, *, headers=None, json=None, timeout=None):
        del url, json, timeout
        assert _stage_from_headers(headers or {}) == "actual_episode_count"
        return _FakeResponse({"answerText": "X"})

    with patch.dict(os.environ, _env(), clear=True), patch.object(chain.requests, "post", side_effect=incomplete_post):
        with pytest.raises(tools.ToolExecutionError) as exc:
            tools.run_simple_tool("character_reskin", _payload(total_episodes=50))

    assert "补全所有集数" in str(exc.value)


def test_character_reskin_rewrites_at_most_five_times_and_uses_latest_version() -> None:
    calls: list[dict[str, object]] = []

    def fake_post(url, *, headers=None, json=None, timeout=None):
        del url, timeout
        stage = _stage_from_headers(headers or {})
        variables = (json or {})["variables"]
        calls.append({"stage": stage, "variables": variables})
        if stage == "actual_episode_count":
            return _FakeResponse({"answerText": "1"})
        if stage == "profile_write":
            return _FakeResponse({"answerText": '{"profile":"v0"}'})
        if stage == "profile_review":
            return _FakeResponse({"answerText": '{"passed":false,"rewrite_required":true}'})
        if stage == "profile_rewrite":
            profile_rewrites = len([call for call in calls if call["stage"] == "profile_rewrite"])
            return _FakeResponse({"wQrZxzeL": f'{{"profile":"v{profile_rewrites}"}}'})
        if stage == "profile_sort":
            return _FakeResponse({"vVtCqEXZ": "最后人设小传"})
        if stage == "dialogue_write":
            return _FakeResponse({"answerText": '{"dialogue":"ok"}'})
        if stage == "dialogue_review":
            return _FakeResponse({"answerText": '{"passed":true,"rewrite_required":false}'})
        if stage == "body_write":
            return _FakeResponse({"answerText": f"正文使用{variables['fFM0mroW']['profile']}"})
        if stage == "body_review":
            return _FakeResponse({"answerText": '{"passed":true,"rewrite_required":false}'})
        if stage == "script_memory":
            return _FakeResponse({"answerText": '{"memory":"ok"}'})
        raise AssertionError(stage)

    with patch.dict(os.environ, _env(), clear=True), patch.object(chain.requests, "post", side_effect=fake_post):
        result = tools.run_simple_tool("character_reskin", _payload(total_episodes=1))

    counts = Counter(call["stage"] for call in calls)
    assert counts["profile_review"] == 6
    assert counts["profile_rewrite"] == 5
    assert result["output"] == "正文使用v5"


def test_character_reskin_diagnosis_lists_dedicated_envs_without_values() -> None:
    secret = "super-secret-fastgpt-key"
    env = _env()
    env["FASTGPT_REWRITE_CHARACTER_PROFILE_KEY"] = secret
    with patch.dict(os.environ, env, clear=True):
        diagnosis = tools.diagnose_simple_tool_environment("character_reskin")

    serialized = json.dumps(diagnosis, ensure_ascii=False)
    assert "FASTGPT_REWRITE_CHARACTER_PROFILE_KEY" in diagnosis["present_api_key_envs"]
    assert diagnosis["url_present"] is True
    assert "expected_variable_keys_by_stage" in diagnosis
    assert secret not in serialized
