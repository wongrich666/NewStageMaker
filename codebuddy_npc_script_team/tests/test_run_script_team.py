from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_script_team.py"
SPEC = importlib.util.spec_from_file_location("run_script_team", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _episode_card(episode: int) -> str:
    fields = (
        "承接事实", "开场钩子", "最短因果锚", "主角目标", "主角主动动作",
        "阻力", "选择与代价", "本集主线推进", "结尾状态", "下一集第一有效动作",
    )
    return f"第{episode}集：《测试{episode}》\n" + "\n".join(
        f"**{field}**：第{episode}集{field}的有效内容" for field in fields
    )


def _episode_card_json(start: int, end: int) -> str:
    return json.dumps(
        {
            "episodes": [
                {
                    "episode": episode,
                    "title": f"测试{episode}",
                    "carryover_fact": "旧动作尚未结束",
                    "opening_hook": "警报突然响起",
                    "causal_anchor": "追兵已经靠近",
                    "protagonist_goal": "逃出封锁",
                    "protagonist_action": "主动拆除门锁",
                    "obstacle": "出口被封死",
                    "choice_and_cost": "以受伤换取时间",
                    "mainline_advance": "主角取得关键线索",
                    "ending_state": "暗门打开",
                    "next_opening_action": "主角冲进暗门",
                    "scenes": [
                        {
                            "location": "工作室",
                            "time": "夜",
                            "interior_exterior": "内",
                            "characters": ["主角"],
                            "props": ["门锁"],
                            "dramatic_task": "突破封锁",
                        }
                    ],
                }
                for episode in range(start, end + 1)
            ]
        },
        ensure_ascii=False,
    )


def test_single_scene_contract_means_one_scene_per_whole_episode() -> None:
    instruction = MODULE.scene_contract_instruction({"scenes_per_episode": "1"})

    assert "每一大集必须且只能有1个场景" in instruction
    assert "不是集内的小阶段" in instruction
    assert "剧情需要时可以增加" not in MODULE.PROMPTS["episode_continuity"]


def test_duration_contract_uses_dynamic_episode_and_total_seconds() -> None:
    instruction = MODULE.duration_contract_instruction(
        {"episodes": 30, "episode_duration_seconds": 75}
    )

    assert "每集目标约75秒" in instruction
    assert "全剧约2250秒" in instruction
    assert "眨眼" in instruction
    assert "每秒约4个汉字" in instruction


def test_opening_hook_keeps_a_short_causal_anchor_after_the_first_beat() -> None:
    episode_prompt = MODULE.PROMPTS["episode_continuity"]
    writer_prompt = MODULE.PROMPTS["script_writer"]
    editor_prompt = MODULE.PROMPTS["final_editor"]

    assert "开场因果锚" in episode_prompt
    assert "强钩子后的1至3个有效拍内" in writer_prompt
    assert "不得固定使用路人解释" in writer_prompt
    assert "缺少开场因果锚" in editor_prompt


def test_mainline_and_continuity_contracts_survive_every_writing_stage() -> None:
    assert "MAINLINE_LOCK_JSON" in MODULE.PROMPTS["showrunner"]
    assert "主线推进账本" in MODULE.PROMPTS["story_architect"]
    assert "本集主线推进" in MODULE.PROMPTS["episode_continuity"]
    assert "结尾状态" in MODULE.PROMPTS["episode_continuity"]
    assert "MAINLINE_LOCK_JSON→逐集卡" in MODULE.PROMPTS["script_writer"]
    assert "不得新增重大人物" in MODULE.PROMPTS["script_writer"]
    assert "plan_alignment" in MODULE.PROMPTS["state_recorder"]
    assert "只允许重写开头1至3个有效拍" in MODULE.PROMPTS["final_editor"]
    assert MODULE.CONTEXT_FILES["final_editor"] == (
        "showrunner",
        "character_emotion",
        "episode_continuity",
        "script_writer",
        "state_recorder",
    )
    assert "showrunner" in MODULE.CONTEXT_FILES["state_recorder"]


def test_original_os_format_and_performance_rules_reach_writer_and_editor() -> None:
    character_prompt = MODULE.PROMPTS["character_emotion"]
    writer_prompt = MODULE.PROMPTS["script_writer"]
    editor_prompt = MODULE.PROMPTS["final_editor"]

    assert "表演指纹" in character_prompt
    assert "心理活动采用假设、验证、被推翻" in character_prompt
    assert "所有心理活动必须采用" in writer_prompt
    assert "人物名OS：心理活动" in writer_prompt
    assert "不得为了满足数量给每句加括号" in editor_prompt
    assert "所有心理活动保持" in editor_prompt
    assert "发现无人物归属的对白或心理活动时补齐人物名" in editor_prompt


def test_continuation_contract_uses_actual_episode_range(monkeypatch) -> None:
    monkeypatch.setenv(
        "scriptRequest",
        json.dumps(
            {
                "mode": "续写",
                "episodes": 5,
                "source_last_episode": 5,
                "episode_start": 6,
                "episode_end": 10,
                "continuation_bible": "女主不能失去左眼；第9集关系彻底决裂。",
            },
            ensure_ascii=False,
        ),
    )

    request = MODULE.read_request()
    instruction = MODULE.continuation_contract_instruction(request)

    assert request["episode_start"] == 6
    assert request["episode_end"] == 10
    assert "第6集至第10集" in request["episode_contract"]
    assert "已有第5集结尾" in instruction
    assert "只输出第6集至第10集" in instruction
    assert "续写创作圣经" in instruction
    assert "已有正文明确事实 > 续写创作圣经" in instruction
    assert "第9集关系彻底决裂" in instruction


def test_single_scene_contract_rejects_three_scene_headers() -> None:
    script = """
第1集：《第98次死亡》
场景1：暗巷｜夜｜外
人物：林烬
林烬：我活了。
场景2：巷口｜夜｜外
人物：秦墨
秦墨：找到你了。
场景3：暗巷深处｜夜｜外
人物：林烬、秦墨
林烬：带路。
"""

    assert MODULE.scene_contract_violations(
        script,
        {"scenes_per_episode": "1"},
    ) == ["第1集要求1个场景，实际检测到3个"]


def test_flexible_scene_contract_accepts_three_scene_headers() -> None:
    script = """
第1集：《第98次死亡》
场景1：暗巷｜夜｜外
场景2：巷口｜夜｜外
场景3：暗巷深处｜夜｜外
"""

    assert MODULE.scene_contract_violations(
        script,
        {"scenes_per_episode": "flexible"},
    ) == []


def test_draft_scene_contract_drift_is_nonblocking_until_final_editor() -> None:
    script = """第1集：《测试》

场景1：办公室｜日｜内

人物：甲

甲：开始。
"""
    request_payload = {"scenes_per_episode": "2-3"}

    assert MODULE.scene_contract_violations(script, request_payload) == [
        "第1集要求2至3个场景，实际检测到1个"
    ]
    assert MODULE.blocking_scene_contract_message(
        "script_writer",
        script,
        request_payload,
    ) == ""
    assert MODULE.blocking_scene_contract_message(
        "final_editor",
        script,
        request_payload,
    ) == "逐集场景合同未满足：第1集要求2至3个场景，实际检测到1个"


def test_scene_contract_accepts_markdown_bold_scene_header() -> None:
    script = """
第1集：《第98次死亡》
**场景1：暗巷｜夜｜外**
**人物**：林烬、秦墨
林烬：带路。
"""

    assert MODULE.scene_contract_violations(
        script,
        {"scenes_per_episode": "1"},
    ) == []


def test_scene_contract_accepts_standard_scene_number_header() -> None:
    script = """
第12集：《古堡枪声》
12-1 古堡大厅｜日｜内
人物：伊莎贝拉、塞缪尔
塞缪尔：别动。
"""

    assert MODULE.scene_contract_violations(
        script,
        {"scenes_per_episode": "1"},
    ) == []


def test_episode_range_contract_rejects_partial_stage_output() -> None:
    output = "\n".join(
        f"第{episode}集：《测试{episode}》\n场景1：工作室｜夜｜内"
        for episode in range(1, 6)
    )

    assert MODULE.episode_range_violations(
        output,
        {"episode_start": 1, "episode_end": 10, "episodes": 10},
    ) == ["要求完整交付第1-10集，实际集号为[1, 2, 3, 4, 5]"]


def test_cloud_stage_batches_long_episode_ranges(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []

    def fake_call_model(_system_prompt, user_prompt, **_kwargs):
        start = int(re.search(r'"episode_start":\s*(\d+)', user_prompt).group(1))
        end = int(re.search(r'"episode_end":\s*(\d+)', user_prompt).group(1))
        calls.append((start, end))
        return _episode_card_json(start, end)

    monkeypatch.setattr(MODULE, "call_model", fake_call_model)

    result = MODULE.generate_stage_result(
        "episode_continuity",
        {
            "episodes": 10,
            "episode_start": 1,
            "episode_end": 10,
            "scenes_per_episode": "1",
        },
        modules="",
    )

    assert calls == [(1, 10)]
    assert MODULE.episode_numbers(result) == list(range(1, 11))


def test_cloud_stage_repairs_only_missing_episodes(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []

    def fake_call_model(_system_prompt, user_prompt, **_kwargs):
        start = int(re.search(r'"episode_start":\s*(\d+)', user_prompt).group(1))
        end = int(re.search(r'"episode_end":\s*(\d+)', user_prompt).group(1))
        calls.append((start, end))
        actual_end = 4 if len(calls) == 1 else end
        return _episode_card_json(start, actual_end)

    monkeypatch.setattr(MODULE, "call_model", fake_call_model)

    result = MODULE.generate_stage_result(
        "episode_continuity",
        {
            "episodes": 10,
            "episode_start": 1,
            "episode_end": 10,
            "scenes_per_episode": "1",
        },
        modules="",
    )

    assert calls == [(1, 10), (1, 10)]
    assert MODULE.episode_numbers(result) == list(range(1, 11))


def _state_batch_json(start: int, end: int) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "project": {"episode_count": 30, "protagonist": "主角"},
            "mainline_lock": {"protagonist": "主角", "goal": "完成目标"},
            "characters": [],
            "props": [],
            "episodes": [
                {
                    "episode": number,
                    "opening_action": f"开场动作{number}",
                    "closing_action": f"结尾动作{number}",
                    "core_scenes": ["工作室"],
                    "continuity_bridge": None if number == 1 else {
                        "previous_episode": number - 1,
                        "from_action": f"结尾动作{number - 1}",
                        "to_action": f"开场动作{number}",
                        "reason": "动作承接",
                    },
                    "character_states": [],
                    "introduced_characters": [],
                    "introduced_props": [],
                    "information_changes": [],
                    "open_loops": [],
                    "resolved_loops": [],
                }
                for number in range(start, end + 1)
            ],
            "open_threads": [],
            "plan_alignment": [
                {
                    "episode": number,
                    "planned_mainline_advance": "推进",
                    "actual_mainline_advance": "推进",
                    "status": "aligned",
                    "issue": "",
                }
                for number in range(start, end + 1)
            ],
            "narrative_pressure": {
                "adversity_payoff_level": "off",
                "pressure_lines": [],
                "emotional_debts": [],
                "reversal_assets": [],
            },
        },
        ensure_ascii=False,
    )


def test_state_audit_batches_30_episodes_in_tens(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SCRIPT_TEAM_STATE_MODEL", "1")
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)

    def fake_call_model(_system_prompt, user_prompt, **_kwargs):
        start = int(re.search(r'"episode_start":\s*(\d+)', user_prompt).group(1))
        end = int(re.search(r'"episode_end":\s*(\d+)', user_prompt).group(1))
        calls.append((start, end))
        return _state_batch_json(start, end)

    monkeypatch.setattr(MODULE, "call_model", fake_call_model)
    request = {"episodes": 30, "episode_start": 1, "episode_end": 30}
    result = MODULE.generate_stage_result("state_recorder", request, modules="")

    assert calls == [(1, 10), (11, 20), (21, 30)]
    assert MODULE._state_episode_numbers(result) == list(range(1, 31))
    assert json.loads(result)["state_status"] == "audited"


def test_continuation_automatically_enables_nonblocking_state_audit(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("SCRIPT_TEAM_STATE_MODEL", raising=False)
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    calls: list[tuple[int, int]] = []

    def fake_call_model(_system_prompt, user_prompt, **_kwargs):
        start = int(re.search(r'"episode_start":\s*(\d+)', user_prompt).group(1))
        end = int(re.search(r'"episode_end":\s*(\d+)', user_prompt).group(1))
        calls.append((start, end))
        return _state_batch_json(start, end)

    monkeypatch.setattr(MODULE, "call_model", fake_call_model)
    result = MODULE.generate_stage_result(
        "state_recorder",
        {
            "mode": "续写",
            "episodes": 12,
            "episode_start": 6,
            "episode_end": 17,
            "series_total_episodes": 17,
        },
        modules="",
    )
    payload = json.loads(result)

    assert calls == [(6, 15), (16, 17)]
    assert payload["state_status"] == "audited"
    assert payload["state_audit"]["batch_count"] == 2


def test_state_recorder_degrades_without_breaking_30_episode_flow(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SCRIPT_TEAM_STATE_MODEL", "1")
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    lock = {
        "protagonist": "林夏",
        "goal": "保住餐厅",
        "core_obstacle": "资金链断裂",
        "protagonist_action": "重建菜单和客源",
        "stakes": "失去家业",
        "pursuit_question": "她能否在期限前救回餐厅",
        "ending_direction": "餐厅重开",
    }
    (tmp_path / MODULE.ROLE_FILES["showrunner"]).write_text(
        "MAINLINE_LOCK_JSON: " + json.dumps(lock, ensure_ascii=False) + "\n"
        'SKILL_ROUTING_JSON: {"adversity_payoff":"off"}',
        encoding="utf-8",
    )
    cards = "\n\n".join(_episode_card(number) for number in range(1, 31))
    draft = "\n\n".join(
        f"第{number}集：《测试{number}》\n场景1：餐厅｜日｜内\n人物：林夏\n"
        f"林夏：先解决第{number}个问题。\n林夏把第{number}张订单放进抽屉。"
        for number in range(1, 31)
    )
    (tmp_path / MODULE.ROLE_FILES["episode_continuity"]).write_text(cards, encoding="utf-8")
    (tmp_path / MODULE.ROLE_FILES["script_writer"]).write_text(draft, encoding="utf-8")
    calls = 0

    def malformed_state(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return '{"episodes": [{"episode": 1}'

    monkeypatch.setattr(MODULE, "call_model", malformed_state)
    result = MODULE.generate_stage_result(
        "state_recorder",
        {
            "title": "重启小馆",
            "episodes": 30,
            "episode_start": 1,
            "episode_end": 30,
            "episode_word_count": 400,
        },
        modules="",
    )
    payload = json.loads(result)

    assert calls == 3
    assert payload["state_status"] == "audit_partial"
    assert payload["mainline_lock"] == lock
    assert MODULE._state_episode_numbers(result) == list(range(1, 31))
    assert len(payload["plan_alignment"]) == 30
    assert payload["state_audit"]["successful_batches"] == 0


def test_batch_upper_bound_respects_frontend_episode_count(monkeypatch) -> None:
    calls: list[str] = []

    def fake_call_model(_system_prompt, user_prompt, *, stage="unknown"):
        calls.append(stage)
        match = re.search(r'"episode_start":\s*(\d+).*?"episode_end":\s*(\d+)', user_prompt, re.S)
        assert match
        return _episode_card_json(int(match.group(1)), int(match.group(2)))

    monkeypatch.setattr(MODULE, "call_model", fake_call_model)
    for count, expected in ((5, ["episode_continuity"]), (11, ["episode_continuity:1-10", "episode_continuity:11-11"])):
        calls.clear()
        result = MODULE.generate_stage_result(
            "episode_continuity",
            {"episodes": count, "episode_start": 1, "episode_end": count},
            modules="",
        )
        assert MODULE.episode_numbers(result) == list(range(1, count + 1))
        assert calls == expected


def test_json_parser_uses_first_complete_object() -> None:
    payload = MODULE.parse_json_result('{"episodes": []}\n附加说明')
    assert payload == {"episodes": []}


def _episode_script_batch(start: int, end: int) -> str:
    body = "主角必须立刻做出选择并承担代价。" * 22
    return "\n\n".join(
        f"第{number}集：《测试{number}》\n场景1：餐厅｜日｜内\n人物：主角\n"
        f"主角：我现在就做。\n主角把关键文件收进抽屉。\n{body}"
        for number in range(start, end + 1)
    )


def test_full_chain_runs_30_episodes_when_state_model_degrades(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "prepare_final_editor_gate", lambda _request: None)
    monkeypatch.setenv(
        "scriptRequest",
        json.dumps(
            {
                "title": "30集链路测试",
                "episodes": 30,
                "episode_start": 1,
                "episode_end": 30,
                "episode_word_count": 400,
                "episode_word_count_max": 440,
                "scenes_per_episode": "1",
            },
            ensure_ascii=False,
        ),
    )
    lock = {
        "protagonist": "主角",
        "goal": "完成任务",
        "core_obstacle": "时间不足",
        "protagonist_action": "主动解决问题",
        "stakes": "任务失败",
        "pursuit_question": "主角能否完成任务",
        "ending_direction": "完成任务并付出代价",
    }
    calls: list[str] = []

    def fake_call_model(system_prompt, user_prompt, *, stage="unknown"):
        calls.append(stage)
        if stage == "showrunner":
            return (
                "MAINLINE_LOCK_JSON: " + json.dumps(lock, ensure_ascii=False) + "\n"
                'SKILL_ROUTING_JSON: {"adversity_payoff":"off"}'
            )
        if stage == "story_architect":
            return "MAINLINE_LOCK_JSON: " + json.dumps(lock, ensure_ascii=False) + "\n主线推进账本"
        if stage == "character_emotion":
            return "人物声音圣经：主角短句、主动行动、承担代价。"
        if stage.startswith("episode_continuity"):
            start = int(re.search(r"(\d+)-(\d+)$", stage).group(1))
            end = int(re.search(r"(\d+)-(\d+)$", stage).group(2))
            return _episode_card_json(start, end)
        if stage.startswith("state_recorder"):
            return '{"episodes": [{"episode": 1}'
        if stage.startswith("script_writer") or stage.startswith("final_editor"):
            match = re.search(r"(\d+)-(\d+)$", stage)
            return _episode_script_batch(int(match.group(1)), int(match.group(2)))
        raise AssertionError(f"unexpected stage {stage}")

    monkeypatch.setattr(MODULE, "call_model", fake_call_model)
    for stage in MODULE.ROLE_ORDER:
        MODULE.run(stage)

    final_script = (tmp_path / MODULE.ROLE_FILES["final_editor"]).read_text(encoding="utf-8")
    state = json.loads((tmp_path / MODULE.ROLE_FILES["state_recorder"]).read_text(encoding="utf-8"))
    assert MODULE.episode_numbers(final_script) == list(range(1, 31))
    assert [number for number in MODULE._state_episode_numbers(json.dumps(state))] == list(range(1, 31))
    assert state["state_status"] == "deterministic"
    assert len([stage for stage in calls if stage.startswith("episode_continuity")]) == 3
    assert len([stage for stage in calls if stage.startswith("script_writer")]) == 3
    assert len([stage for stage in calls if stage.startswith("state_recorder")]) == 0
    assert len([stage for stage in calls if stage.startswith("final_editor")]) == 3


def test_cloud_episode_cards_reject_placeholder_sections() -> None:
    content = "\n\n".join(
        [_episode_card(episode) for episode in range(1, 5)]
        + ["第5集：《占位》\n**承接事实**："]
    )

    merged = MODULE._merge_episode_outputs(
        "",
        content,
        episode_start=1,
        episode_end=5,
        stage="episode_continuity",
    )

    assert MODULE.episode_numbers(merged) == [1, 2, 3, 4]
    assert MODULE._missing_episode_ranges(merged, episode_start=1, episode_end=5) == [(5, 5)]


def test_model_timeout_defaults_to_twenty_minutes(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_TIMEOUT", raising=False)

    assert MODULE._positive_env_int(
        "DEEPSEEK_TIMEOUT",
        1200,
        minimum=60,
        maximum=3600,
    ) == 1200


def test_heartbeat_reports_stage_and_elapsed_time(capsys) -> None:
    class StopAfterOneHeartbeat:
        calls = 0

        def wait(self, _interval):
            self.calls += 1
            return self.calls > 1

    MODULE._emit_heartbeats(
        StopAfterOneHeartbeat(),
        30,
        "script_writer",
        started_at=100,
        clock=lambda: 130,
    )

    output = capsys.readouterr().out
    assert "stage=script_writer" in output
    assert "sequence=1" in output
    assert "elapsed_seconds=30" in output


def test_distilled_skill_loads_only_modules_routed_to_current_stage() -> None:
    request = {
        "distilled_skill": {
            "schema_version": "script-team-skill/v1",
            "name": "现实情感",
            "version": "v1.2",
            "manifest": {
                "modules": [
                    {"key": "genre_profile", "stages": ["showrunner"]},
                    {"key": "hook_craft", "stages": ["script_writer", "final_editor"]},
                ]
            },
            "modules": {
                "genre_profile": "题材情绪承诺",
                "hook_craft": "开篇钩子规则",
            },
        }
    }

    writer = MODULE.distilled_skill_modules("script_writer", request)
    showrunner = MODULE.distilled_skill_modules("showrunner", request)

    assert "开篇钩子规则" in writer
    assert "题材情绪承诺" not in writer
    assert "题材情绪承诺" in showrunner
    assert "开篇钩子规则" not in showrunner
    assert "v1.2" in writer


def test_distilled_skill_is_prioritized_and_capped_per_stage() -> None:
    huge = "钩" * 8_000
    request = {
        "distilled_skill": {
            "schema_version": "script-team-skill/v1",
            "name": "混合题材",
            "manifest": {
                "modules": [
                    {"key": "anti_patterns", "stages": ["final_editor"]},
                    {"key": "hook_craft", "stages": ["final_editor"]},
                    {"key": "quality_gate", "stages": ["final_editor"]},
                    {"key": "dialogue_voice", "stages": ["final_editor"]},
                ]
            },
            "modules": {
                "anti_patterns": huge,
                "hook_craft": huge,
                "quality_gate": huge,
                "dialogue_voice": huge,
            },
        }
    }

    text = MODULE.distilled_skill_modules("final_editor", request)

    assert text.index("quality_gate") < text.index("hook_craft")
    assert len(text) < 13_500
    assert "示例是方法，不是必须照搬的事件、人物或道具" in text
    assert "不得迁移Skill样本中的人物身份、关系套路、职业、场景、道具、证据手段" in text
