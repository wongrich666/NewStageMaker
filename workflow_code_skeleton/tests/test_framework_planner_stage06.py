from app.services.framework_planner_service import (
    STAGE_DEFINITIONS,
    _coerce_non_list_candidate_to_stage_output,
    _normalize_adaptation_guide,
    _normalize_stage_output,
)


def test_stage06_maps_rich_guide_without_changing_output_shape():
    raw = {
        "adaptation_guide": {
            "core_logline": "主角必须在家族与良知之间作出选择。",
            "must_keep_elements": ["父子债务", "家族背叛"],
            "beat_checkpoint_timeline_contract": {"opening": "葬礼枪声"},
            "narrative_rhythm_requirements": ["每集推进主角目标"],
            "visual_style_writing_guide": ["低照度", "近景压迫"],
            "character_storyline_contracts": {"男主": "从服从到反抗"},
            "emotion_engine_principles": ["羞耻转愤怒"],
        },
        "hard_constraints_for_script_workflow": {
            "forbidden": ["无因果跳场"]
        },
    }

    normalized = _normalize_stage_output("06", raw, parse_warnings=[])
    guide = normalized["adaptation_guide"]

    assert set(guide) == {
        "core_setting_adjustments",
        "structure_and_rhythm",
        "visualization_strategy",
        "character_emotion_strategy",
        "hard_constraints_for_script_workflow",
    }
    assert "家族与良知" in guide["core_setting_adjustments"]
    assert "葬礼枪声" in guide["structure_and_rhythm"]
    assert "低照度" in guide["visualization_strategy"]
    assert "从服从到反抗" in guide["character_emotion_strategy"]
    assert guide["hard_constraints_for_script_workflow"] == {
        "forbidden": ["无因果跳场"]
    }


def test_nested_guide_keeps_sibling_constraints():
    normalized = _normalize_adaptation_guide(
        {
            "adaptation_guide": {
                "core_setting_adjustment": "保留原作核心设定",
                "narrative_rhythm_structure": "三秒入戏",
                "visualization": "动作可拍",
                "character_emotion_shaping": "人物情绪递进",
            },
            "hard_constraints_for_script_workflow": {"required": ["强钩子"]},
        }
    )

    assert normalized["core_setting_adjustments"] == "保留原作核心设定"
    assert normalized["hard_constraints_for_script_workflow"] == {
        "required": ["强钩子"]
    }


def test_stage06_maps_current_workflow_field_names():
    normalized = _normalize_stage_output(
        "06",
        {
            "adaptation_guide": {
                "core_principles": ["不改变已确认人物命运"],
                "beat_checkpoint_timeline": [{"episode": 1, "hook": "葬礼枪声"}],
                "character_hard_constraints": {"卢卡": "手抖贯穿"},
                "tone_style_requirements": ["克制、压迫"],
                "dialogue_style_requirements": ["短句、有潜台词"],
            },
            "hard_constraints_for_script_workflow": {
                "strong_opening_per_episode": "每集五秒内进入冲突"
            },
        },
        parse_warnings=[],
    )["adaptation_guide"]

    assert "不改变已确认人物命运" in normalized["core_setting_adjustments"]
    assert "葬礼枪声" in normalized["structure_and_rhythm"]
    assert "克制、压迫" in normalized["visualization_strategy"]
    assert "手抖贯穿" in normalized["character_emotion_strategy"]
    assert "短句、有潜台词" in normalized["character_emotion_strategy"]
    assert normalized["hard_constraints_for_script_workflow"] == {
        "strong_opening_per_episode": "每集五秒内进入冲突"
    }


def test_stage06_parser_keeps_root_level_constraints():
    definition = STAGE_DEFINITIONS["06"]
    mapped, warnings = _coerce_non_list_candidate_to_stage_output(
        definition,
        {
            "adaptation_guide": {
                "core_principles": ["人物命运不可改"],
                "beat_checkpoint_timeline": [{"episode": 1, "hook": "枪声"}],
            },
            "hard_constraints_for_script_workflow": {
                "episode_bridge_rule": "下一集承接上一集动作"
            },
        },
        definition.output_aliases,
    )

    assert warnings == []
    assert mapped["adaptation_guide"]["hard_constraints_for_script_workflow"] == {
        "episode_bridge_rule": "下一集承接上一集动作"
    }
