from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_script_team.py"
SPEC = importlib.util.spec_from_file_location("validate_script_team", SCRIPT_PATH)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def _character(name: str = "林深") -> dict:
    return {
        "name": name,
        "role": "protagonist",
        "first_appearance": 1,
        "voice_recipe": {
            "sentence_length": "短句，压力下更短",
            "evasion_style": "用反问回避",
            "pressure_pattern": "先否认，再突然说出关键事实",
            "forbidden_phrases": ["我来解释一下"],
            "samples": ["别碰它。", "你先回答我。", "我没说我相信你。"],
            "unspoken_truth": "害怕自己写下的人物比自己更真实",
        },
    }


def _episode(number: int, *, bridge: dict | None = None) -> dict:
    return {
        "episode": number,
        "opening_action": "林深按住仍在移动的键盘。",
        "closing_action": "墙后再次传来三声敲击。",
        "core_scenes": ["工作室"],
        "scene_exception_reason": "",
        "continuity_bridge": bridge,
        "character_states": [
            {
                "name": "林深",
                "location": "工作室",
                "knowledge": ["文档会自行改写"],
                "injuries": [],
                "clothing": ["灰色卫衣"],
                "held_props": ["键盘"],
                "relationships": {"林深（小说人物）": "从怀疑转为警惕"},
                "unfinished_actions": ["确认墙后敲击来源"],
            }
        ],
        "introduced_characters": [],
        "introduced_props": [],
        "information_changes": ["确认异常与小说人物有关"],
        "open_loops": ["墙后是谁"],
        "resolved_loops": [],
    }


def _state(episodes: int = 1) -> dict:
    items = [_episode(1)]
    if episodes > 1:
        items.append(
            _episode(
                2,
                bridge={
                    "previous_episode": 1,
                    "from_action": "墙后再次传来三声敲击。",
                    "to_action": "林深贴近墙面听声音。",
                    "reason": "继续确认上一集未完成动作",
                },
            )
        )
    return {
        "schema_version": "1.0",
        "project": {
            "title": "墙后的人",
            "protagonist": "林深",
            "episode_count": episodes,
            "target_words_per_episode": 100,
            "immutable_facts": ["工作室隔壁是电梯井"],
        },
        "characters": [_character()],
        "props": [{"name": "键盘", "first_appearance": 1, "source": "工作室原有物品"}],
        "episodes": items,
        "open_threads": [
            {
                "id": "wall-knock",
                "introduced_episode": 1,
                "description": "墙后的敲击来源",
                "status": "open",
                "resolved_episode": None,
            }
        ],
    }


def _body(seed: str) -> str:
    return "场景1：工作室｜夜｜内\n人物：林深\n" + (
        seed + "林深盯着自动出现的句子，手指停在退格键上。墙后敲了三下，他没有回头，只把手机录音关掉。"
    ) * 3


def test_valid_script_and_state_pass_strict_gate() -> None:
    script = f"片名：墙后的人\n第1集：《墙后三响》\n{_body('别回头。')}"
    report = gate.validate(
        script,
        _state(),
        {"episodes": 1, "episode_word_count": 100},
        mode="strict",
    )

    assert report.errors == []
    assert report.as_dict()["ok"] is True


def test_audit_report_cannot_be_published_as_script() -> None:
    script = "最终验证\n| 戏剧合同项 | 状态 |\n| 五秒钩子 | 质量达标 |"
    report = gate.validate(
        script,
        _state(),
        {"episodes": 1, "episode_word_count": 100},
        mode="strict",
    )

    codes = {item["code"] for item in report.errors}
    assert "script.audit_report" in codes
    assert "script.episodes.sequence" in codes


def test_state_requires_voice_recipe_and_episode_bridge() -> None:
    state = _state(episodes=2)
    state["characters"][0].pop("voice_recipe")
    state["episodes"][1]["continuity_bridge"] = None
    script = f"第1集：《停下》\n{_body('停下。')}\n第2集：《开门》\n{_body('开门。')}"

    report = gate.validate(
        script,
        state,
        {"episodes": 2, "episode_word_count": 100},
        mode="strict",
    )

    codes = {item["code"] for item in report.errors}
    assert "state.voice.missing" in codes
    assert "state.bridge.missing" in codes


def test_supporting_voice_sample_gap_is_warning_not_release_blocker() -> None:
    state = _state()
    supporting = _character("老陈")
    supporting["role"] = "supporting"
    supporting["voice_recipe"]["samples"] = ["别出声。"]
    state["characters"].append(supporting)
    script = f"片名：墙后的人\n第1集：《墙后三响》\n{_body('别回头。')}"

    report = gate.validate(
        script,
        state,
        {"episodes": 1, "episode_word_count": 100},
        mode="strict",
    )

    assert not any(item["code"] == "state.voice.samples" for item in report.errors)
    assert any(item["code"] == "state.voice.samples" for item in report.warnings)


def test_validator_accepts_english_episode_headers() -> None:
    script = "\n\n".join(
        [
            'BLOOD MOON\nEpisode 1 - "The Blade"\n' + ("Action dialogue " * 12),
            'Episode 2: "The Debt"\n' + ("Consequence choice " * 12),
        ]
    )
    state = _state(episodes=2)

    report = gate.validate(
        script,
        state,
        {"episodes": 2, "episode_word_count": 100},
        mode="strict",
    )

    assert report.metrics["actual_episode_count"] == 2
    assert not any(item["code"] == "script.episodes.sequence" for item in report.errors)


def test_english_word_target_is_not_compared_to_character_count() -> None:
    body = " ".join(
        f"Kael chooses evidence over revenge while the council watches him {index}."
        for index in range(28)
    )
    script = f'THE LAST HOWL\n第1集：The Return\n{body}'

    report = gate.validate(
        script,
        _state(),
        {"episodes": 1, "episode_word_count": 350},
        mode="strict",
    )

    episode_metric = report.metrics["episodes"][0]
    assert episode_metric["chars"] > 630
    assert 175 <= episode_metric["word_units"] <= 630
    assert not any(item["code"] == "script.episode.too_long" for item in report.errors)


def test_default_scene_contract_rejects_extra_state_scenes() -> None:
    state = _state()
    state["episodes"][0]["core_scenes"] = ["工作室", "楼道", "电梯井"]
    script = f"第1集：《第三扇门》\n{_body('别动。')}"

    report = gate.validate(
        script,
        state,
        {"episodes": 1, "episode_word_count": 100},
        mode="strict",
    )

    assert any(item["code"] == "state.scenes.contract" for item in report.errors)


def test_two_scene_contract_accepts_two_scenes() -> None:
    state = _state()
    state["episodes"][0]["core_scenes"] = ["工作室", "楼道"]
    script = (
        "第1集：《第二扇门》\n"
        f"{_body('别动。')}\n"
        "场景2：楼道｜夜｜内\n人物：林深\n"
        "△林深撞开门。\n林深：（急促，眉头紧锁）快走。"
    )

    report = gate.validate(
        script,
        state,
        {"episodes": 1, "episode_word_count": 100, "scenes_per_episode": "2"},
        mode="strict",
    )

    assert not any(item["code"] == "state.scenes.contract" for item in report.errors)
    assert not any(item["code"] == "script.scene_headers.contract" for item in report.errors)


def test_flexible_scene_contract_allows_more_scenes() -> None:
    state = _state()
    state["episodes"][0]["core_scenes"] = ["工作室", "楼道", "电梯井"]
    script = (
        "第1集：《第三扇门》\n"
        f"{_body('别动。')}\n"
        "场景2：楼道｜夜｜内\n人物：林深\n△林深冲进楼道。\n"
        "场景3：电梯井｜夜｜内\n人物：林深\n△钢索在他头顶断裂。"
    )

    report = gate.validate(
        script,
        state,
        {
            "episodes": 1,
            "episode_word_count": 100,
            "scenes_per_episode": "flexible",
        },
        mode="strict",
    )

    assert not any(item["code"] == "state.scenes.contract" for item in report.errors)
    assert not any(item["code"] == "script.scene_headers.contract" for item in report.errors)


def test_each_episode_requires_scene_header() -> None:
    script = "片名：墙后的人\n第1集：《墙后三响》\n" + (
        "别回头。林深盯着自动出现的句子，手指停在退格键上。" * 5
    )
    report = gate.validate(
        script,
        _state(),
        {"episodes": 1, "episode_word_count": 100},
        mode="strict",
    )

    assert any(item["code"] == "script.scene_headers.missing" for item in report.errors)


def test_each_episode_requires_a_distinct_title() -> None:
    script = f"片名：墙后的人\n第1集\n{_body('别回头。')}"
    report = gate.validate(
        script,
        _state(),
        {"episodes": 1, "episode_word_count": 100},
        mode="strict",
    )

    assert any(item["code"] == "script.episode.title_missing" for item in report.errors)


def test_planning_fields_are_rejected_from_script_body() -> None:
    script = (
        f"片名：墙后的人\n第1集：《墙后三响》\n{_body('别回头。')}"
        "\n场景任务：确认异响来源\n道具：键盘"
    )
    report = gate.validate(
        script,
        _state(),
        {"episodes": 1, "episode_word_count": 100},
        mode="strict",
    )

    assert any(item["code"] == "script.planning_fields.present" for item in report.errors)


def test_dialogue_and_os_require_character_prefix() -> None:
    script = (
        "片名：墙后的人\n第1集：《墙后三响》\n"
        "场景1：工作室｜夜｜内\n人物：林深\n"
        "“别回头。”\nOS：墙后到底是谁？"
        + _body("林深：别碰。")
    )
    report = gate.validate(
        script,
        _state(),
        {"episodes": 1, "episode_word_count": 100},
        mode="strict",
    )
    codes = {item["code"] for item in report.errors}

    assert "script.dialogue.speaker_missing" in codes
    assert "script.os.speaker_missing" in codes


def test_character_prefixed_dialogue_and_os_pass_format_gate() -> None:
    script = (
        "片名：墙后的人\n第1集：《墙后三响》\n"
        "场景1：工作室｜夜｜内\n人物：林深\n"
        "林深：别回头。\n林深OS：墙后到底是谁？\n"
        + _body("林深：别碰。")
    )
    report = gate.validate(
        script,
        _state(),
        {"episodes": 1, "episode_word_count": 100},
        mode="strict",
    )
    codes = {item["code"] for item in report.errors}

    assert "script.dialogue.speaker_missing" not in codes
    assert "script.os.speaker_missing" not in codes


def test_dialogue_requires_performance_cue_in_strict_gate() -> None:
    script = (
        "片名：墙后的人\n第1集：《墙后三响》\n"
        "场景1：工作室｜夜｜内\n人物：林深\n"
        "林深：别回头。\n"
        + _body("林深：别碰。")
    )
    report = gate.validate(
        script,
        _state(),
        {"episodes": 1, "episode_word_count": 100},
        mode="strict",
    )

    assert any(
        item["code"] == "script.dialogue.performance_cue_missing"
        for item in report.errors
    )


def test_dialogue_performance_cue_format_passes_gate() -> None:
    script = (
        "片名：墙后的人\n第1集：《墙后三响》\n"
        "场景1：工作室｜夜｜内\n人物：林深\n"
        "林深：（压低声音，眉峰绷紧）别回头。\n"
        + _body("林深：别碰。")
    )
    report = gate.validate(
        script,
        _state(),
        {"episodes": 1, "episode_word_count": 100},
        mode="strict",
    )

    assert not any(
        item["code"] == "script.dialogue.performance_cue_missing"
        for item in report.errors
    )


def test_dash_metrics_count_groups_not_individual_characters() -> None:
    metrics = gate._dash_metrics("林深：等等——别开门！\n门开了。")

    assert metrics["dash_groups"] == 1
    assert metrics["dash_groups_per_1000_chars"] > 0


def test_excessive_dash_density_is_a_non_blocking_warning() -> None:
    dash_heavy = (
        "林深：实习生是吧——这个月工资扣一半！\n"
        "林深：说啊——你倒是说啊——\n"
        "林深转身——门在身后关上——\n"
    ) * 8
    script = f"片名：墙后的人\n第1集：《墙后三响》\n{_body(dash_heavy)}"

    report = gate.validate(
        script,
        _state(),
        {"episodes": 1, "episode_word_count": 100},
        mode="strict",
    )

    assert any(item["code"] == "script.punctuation.dash_overuse" for item in report.warnings)
    assert not any(item["code"] == "script.punctuation.dash_overuse" for item in report.errors)
