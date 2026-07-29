from __future__ import annotations

from workflow_code_skeleton.app.services.codebuddy_npc_stage_runner import (
    _dynamic_skill_level,
    _module_text,
)


def test_dynamic_skill_level_reads_machine_contract() -> None:
    contract = (
        'SKILL_ROUTING_JSON: {"adversity_payoff":"core",'
        '"reason":"主角逆风翻盘是核心情绪承诺"}'
    )

    assert _dynamic_skill_level(contract, "adversity_payoff") == "core"


def test_adversity_module_is_loaded_only_when_selected() -> None:
    selected = {
        "contract": (
            'SKILL_ROUTING_JSON: {"adversity_payoff":"support",'
            '"reason":"成长线需要阶段性压力"}'
        )
    }
    disabled = {
        "contract": (
            'SKILL_ROUTING_JSON: {"adversity_payoff":"off",'
            '"reason":"纯日常治愈不适合逆风翻盘"}'
        )
    }

    assert "主角逆风、情绪债与反转兑现生产模块" in _module_text(
        "story_architect",
        selected,
    )
    assert "主角逆风、情绪债与反转兑现生产模块" not in _module_text(
        "story_architect",
        disabled,
    )


def test_showrunner_always_receives_skill_router() -> None:
    assert "创作技能智能路由" in _module_text("showrunner", {})
