from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_code_skeleton.app.config import settings
from workflow_code_skeleton.app.models.inputs import WorkflowInput
from workflow_code_skeleton.app.models.state import WorkflowState
from workflow_code_skeleton.app.orchestrators import fastgpt_hybrid_workflow as flow
from workflow_code_skeleton.app.services.fastgpt_client import FastGPTTransientError
from workflow_code_skeleton.app.services.fastgpt_contracts import (
    ALL_DIALOGUES,
    ALL_HOOKS,
    ALL_SCRIPT,
    APPEARANCE_MAPPING,
    BATCH_DIALOGUES,
    BATCH_HOOKS,
    BATCH_SCRIPT,
    BATCH_START_EPISODE,
    EPISODE_ALIAS_PLAN,
    CHARACTER_APPEARANCE_REQUIREMENTS,
    CHARACTER_ALIAS_NAMING_RULES,
    CHARACTERS,
    EPISODE_PLAN,
    EPISODE_WORD_COUNT,
    FRAMEWORK_NATURAL_LANGUAGE,
    IS_CONSISTENT,
    LAST_SUMMARY,
    MAX_RETRIES,
    NORMALIZED_EPISODE_PLAN,
    OUTFIT_SWITCH_RULES,
    SCENES,
    SCRIPT_TITLE,
    STORY_OUTLINE,
    TOTAL_EPISODES,
    WORLDVIEW,
    WORLDVIEW_NATURAL_LANGUAGE,
    STAGE_APPEARANCE_PRE_STRATEGY,
    STAGE_CONSISTENCY,
    STAGE_DIALOGUES,
    STAGE_DIALOGUE_MEMORY,
    STAGE_DIALOGUE_REVIEW,
    STAGE_DIALOGUES_REVIEW,
    STAGE_DIALOGUES_REWRITE,
    STAGE_DIALOGUES_WRITING,
    STAGE_EPISODE_PLAN_NORMALIZE,
    STAGE_FRAMEWORK,
    STAGE_FRAMEWORK_NATURALIZE,
    STAGE_CHARACTERS_NATURALIZE,
    STAGE_HOOKS,
    STAGE_HOOK_MEMORY,
    STAGE_HOOK_REVIEW,
    STAGE_HOOKS_REVIEW,
    STAGE_HOOKS_REWRITE,
    STAGE_HOOKS_WRITING,
    STAGE_SCRIPT,
    STAGE_SCRIPT_MEMORY,
    STAGE_SCRIPT_REVIEW,
    STAGE_SCRIPT_REWRITE,
    STAGE_SCRIPT_WRITING,
    STAGE_WORLDVIEW,
    STAGE_WORLDVIEW_NATURALIZE,
    USER_CHARACTERS,
    USER_SCENES,
)
from workflow_code_skeleton.app.utils.episode import BatchWindow, iter_episode_batches
from workflow_code_skeleton.app.workflow_ids import (
    CHARACTER_NATURAL_LANGUAGE_VAR,
    DIALOGUE_CURRENT_VAR,
    DIALOGUE_CURRENT_WORKFLOW_VAR,
    DIALOGUE_CURRENT_WRITE_VAR,
    DIALOGUE_HOOK_BATCH_VAR,
    DIALOGUE_HOOK_INPUT_VAR,
    DIALOGUE_HOOK_REVIEW_VAR,
    DIALOGUE_HOOK_REWRITE_VAR,
    DIALOGUE_MEMORY_INPUT_VAR,
    DIALOGUE_MEMORY_LEGACY_OUTPUT_VAR,
    DIALOGUE_MEMORY_OUTPUT_VAR,
    DIALOGUE_MEMORY_SEARCH_VAR,
    DIALOGUE_REVIEW_LEGACY_VAR,
    DIALOGUE_REVIEW_OUTPUT_VAR,
    DIALOGUE_REVIEW_WORKFLOW_VAR,
    HOOK_CURRENT_VAR,
    HOOK_CURRENT_WRITE_VAR,
    HOOK_MEMORY_INPUT_VAR,
    HOOK_MEMORY_OUTPUT_VAR,
    HOOK_MEMORY_REVIEW_VAR,
    HOOK_MEMORY_REVISE_VAR,
    HOOK_REVIEW_OUTPUT_VAR,
    MEMORY_VAR,
    SCENE_NATURAL_LANGUAGE_VAR,
    SCRIPT_DIALOGUE_BATCH_VAR,
    SCRIPT_CURRENT_VAR,
    SCRIPT_CURRENT_WRITE_VAR,
    SCRIPT_HOOK_BATCH_VAR,
    SCRIPT_MEMORY_OUTPUT_VAR,
    SCRIPT_MEMORY_WRITE_INPUT_VAR,
    SCRIPT_REVIEW_OUTPUT_VAR,
    SCRIPT_REVIEW_WRITE_VAR,
    UNSTRUCTURED_KIND_VAR,
    UNSTRUCTURED_OUTPUT_VAR,
    UNSTRUCTURED_SOURCE_VAR,
)
from workflow_code_skeleton.app.services.workflow_output_validation import resolve_workflow_json_path
from workflow_code_skeleton.app.services.workflow_output_validation import (
    WorkflowOutputValidationError,
    load_workflow_output_contract,
    validate_stage_output_with_workflow_contract,
)
from workflow_code_skeleton.tests.test_stage_output_repair import (
    _character_setting_json,
    _scene_setting_json,
)
from workflow_code_skeleton.tests.test_support import workspace_tempdir


def _workflow_input(total_episodes: int) -> WorkflowInput:
    return WorkflowInput(
        title="测试剧本",
        episode_word_count=1200,
        total_episodes=total_episodes,
        user_expectation="测试三段式批处理",
        character_count=3,
        character_appearance_requirements="",
        character_alias_naming_rules="统一使用正式中文名",
        outfit_switch_rules="",
        story_outline="测试大纲",
        core_scene_input="测试核心场景",
        character_bios="测试人物小传",
        episode_plan="",
    )


def _normalized_plan(total_episodes: int) -> dict[str, object]:
    return {
        "parsed_episode_count": total_episodes,
        "appearance_alias_planning": {},
        "episodes": [
            {
                "episode": episode,
                "title": f"第{episode}集",
                "content": f"第{episode}集主线推进",
                "main_character_aliases": [],
                "appearance_events": [],
                "long_term_stage_flags": [],
                "scene_based_alias_hints": [],
            }
            for episode in range(1, total_episodes + 1)
        ],
    }


def _framework_story_outline() -> dict[str, str]:
    return {
        "opening": "主角回到旧城，准备重启停摆多年的项目。",
        "inciting_incident": "一场公开竞标让主角被迫提前入局。",
        "early_goal": "主角想在第一阶段先拿下关键合作与启动资金。",
        "middle_escalation": "竞争对手开始围堵资源，团队内部也出现裂痕。",
        "relationship_changes": "主角与搭档从互相试探逐渐建立信任。",
        "larger_crisis_or_truth": "主角发现项目背后牵涉更大的利益交易。",
        "late_direction": "团队决定公开真相并赌上最后一次发布机会。",
        "final_climax": "主角在终局发布会上正面对抗幕后操盘者。",
        "ending_resolution": "项目重启成功，团队以新的关系进入下一阶段。",
        "theme": "在压力与诱惑中坚持选择真正重要的人与事。",
    }


def _framework_characters() -> list[dict[str, str]]:
    return [
        {
            "name": "林夏",
            "role_type": "主角",
            "identity": "回到故乡的青年产品负责人",
            "personality": "冷静克制，但在关键时刻会冒险一搏",
            "core_desire": "证明自己能把停摆项目重新拉起来",
            "deep_motivation": "想弥补当年离开团队留下的遗憾",
            "strengths": "善于整合资源、判断局势",
            "weaknesses": "不愿轻易求助，容易把压力藏起来",
            "appearance_anchor": "总穿深色外套，讲话前会下意识揉眉心",
            "relationship_to_protagonist": "本人",
            "relationships_with_others": "与搭档互补，与对手长期存在旧怨",
            "growth_arc": "从独自扛压走向真正信任团队",
            "plot_function": "推动主线决策并承担情感转折",
        }
    ]


def _framework_scenes() -> dict[str, object]:
    return {
        "era_background": "近未来沿海工业城市转型期",
        "world_state": "城市表面平稳，实则资源与话语权重新洗牌",
        "core_locations": [
            {
                "name": "旧港实验楼",
                "function": "项目团队的主要办公与研发场所",
                "conflict_soil": "人手不足、设备陈旧、各方势力都在争夺控制权",
                "key_characters": ["林夏", "搭档", "竞争对手"],
            }
        ],
        "rules": "项目审批、资本注入与舆论窗口期共同决定行动节奏",
        "danger_sources": "资金断裂、核心资料泄露、竞争方渗透",
        "resource_or_stakes": "项目主导权、城市更新名额与团队声誉",
        "power_distribution": "资本方与管理层掌握资源，执行团队掌握真实进度",
        "special_rules": "关键发布前所有对外信息都需要二次确认",
        "overall_atmosphere": "潮湿、压抑、逼仄，但始终带着向上突围的张力",
    }


def _framework_episode_plan(total_episodes: int = 10) -> list[dict[str, object]]:
    episodes: list[dict[str, object]] = []
    for episode in range(1, total_episodes + 1):
        episodes.append(
            {
                "episode": episode,
                "title": f"第{episode}集",
                "main_plot": f"第{episode}集主线推进与局势升级。",
                "conflicts": [f"第{episode}集核心冲突", f"第{episode}集次级阻碍"],
                "ending_hook": f"第{episode}集结尾留下新的悬念。",
            }
        )
    return episodes


def _hook_batch(episodes: list[int]) -> dict[str, object]:
    return {
        "batch_meta": {
            "start_episode": episodes[0],
            "end_episode": episodes[-1],
        },
        "global_hook_engine": {
            "batch_label": f"{episodes[0]}-{episodes[-1]}",
        },
        "episodes": [
            {
                "episode": episode,
                "hook": f"hook-{episode}",
                "opening_alias_plan": {"primary_alias": "A"},
                "opening_action": f"open-{episode}",
                "current_goal": f"goal-{episode}",
                "core_obstacle": f"obstacle-{episode}",
                "ending_hook": f"ending-{episode}",
                "next_episode_priority_response": f"next-{episode}",
            }
            for episode in episodes
        ],
    }


def _dialogue_batch(episodes: list[int]) -> dict[str, object]:
    return {
        "batch_meta": {
            "start_episode": episodes[0],
            "end_episode": episodes[-1],
        },
        "character_voice_bibles": [
            {
                "character_name": "A",
                "voice": "direct",
            }
        ],
        "episode_dialogue_blocks": [
            {
                "episode": episode,
                "title": f"第{episode}集",
                "dialogue_blocks": [
                    {
                        "scene_hint": f"scene-{episode}",
                        "conflict_type": "argument",
                        "dialogues": [
                            {
                                "speaker": "A",
                                "line": f"dialogue-{episode}-1",
                            },
                            {
                                "speaker": "B",
                                "line": f"dialogue-{episode}-2",
                            },
                        ],
                    }
                ],
            }
            for episode in episodes
        ],
    }


def _dialogue_batch_flat_legacy(episodes: list[int]) -> dict[str, object]:
    return {
        "batch_meta": {
            "start_episode": episodes[0],
            "end_episode": episodes[-1],
        },
        "character_voice_bibles": [
            {
                "character_name": "A",
                "voice": "direct",
            }
        ],
        "episode_dialogue_blocks": [
            {
                "episode": episode,
                "participants": ["A", "B"],
                "speaker": "A",
                "dialogue_block": f"dialogue-{episode}",
            }
            for episode in episodes
        ],
    }


def _script_batch_text(episodes: list[int]) -> str:
    return "\n\n".join(
        f"第{episode}集\n{episode}-1\n正文内容 {episode}"
        for episode in episodes
    )


def _script_batch_text_without_scene_headings(episodes: list[int]) -> str:
    return "\n\n".join(
        f"第{episode}集\n正文内容 {episode}"
        for episode in episodes
    )


def _hook_memory_json(*, label: str = "hook end") -> str:
    return json.dumps(
        {
            "final_hook_of_this_turn": label,
            "must_carry_into_next_turn": [],
            "appearance_alias_continuity_summary": "alias ok",
        },
        ensure_ascii=False,
    )


def _dialogue_memory_json(*, label: str = "voice ok") -> str:
    return json.dumps(
        {
            "dialogue_voice_summary": label,
            "must_carry_into_next_turn": [],
            "alias_usage_continuity": "alias ok",
        },
        ensure_ascii=False,
    )


def _script_memory_json(*, label: str = "summary-1") -> str:
    return json.dumps(
        {
            "final_hook_of_this_turn": f"{label}-hook",
            "must_carry_into_next_turn": [],
            "appearance_continuity_summary": label,
        },
        ensure_ascii=False,
    )


def _rich_characters_text() -> str:
    return json.dumps(
        {
            "character_setting": {
                "characters": [
                    {
                        "character_name": "林夏",
                        "story_role": "主角",
                        "core_motivation": "扛住项目并保住团队。",
                        "appearance": {
                            "overall_look": "清瘦利落，深色通勤装。",
                            "recognizable_features": ["总把头发束紧", "说话前会先停顿"],
                        },
                        "behavior": {
                            "habitual_actions": ["说话前先停顿半秒", "焦虑时反复整理桌面"],
                        },
                        "speech_profile": {
                            "baseline_register": "简短克制",
                            "sentence_rhythm": "句子偏短",
                            "keyword_habits": ["先这样", "我来处理"],
                            "conflict_style": "不大喊，但会逼近核心矛盾",
                        },
                        "relation_modes": [
                            {
                                "target": "周沉",
                                "relation_type": "危险盟友",
                                "default_posture": "先试探再靠近",
                                "speech_difference": "会更少废话",
                                "conflict_trigger": "对方替她决定时会反弹",
                            }
                        ],
                        "family": {
                            "family_background": "普通工薪家庭出身",
                            "upbringing": "从小被教育要懂事能忍",
                        },
                        "dramatic_function": {
                            "scene_value": "能把压抑情绪变成持续张力",
                        },
                        "dramatic_value": "她的选择决定主线何时正式反击。",
                    }
                ]
            }
        },
        ensure_ascii=False,
    )


def _rich_scenes_text() -> str:
    return json.dumps(
        {
            "scene_setting": {
                "scenes": [
                    {
                        "scene_name": "玻璃会议室",
                        "scene_type": "核心博弈场",
                        "story_function": "推动公开站队冲突。",
                        "scene_time_or_period": "深夜加班时段",
                        "weather_or_environment_state": "冷白灯长亮",
                        "visual_condition_summary": "冷硬压迫，适合观察权力差。",
                        "identity_or_status_requirements": ["带着明显职级差进入场景"],
                        "styling_condition_summary": "造型要保留精英感与疲态。",
                        "naming_condition_summary": "称谓要体现权力距离。",
                        "conflict_potential": ["公开站队与背锅切割随时爆发"],
                        "outfit_requirements": [{"character_id": "linxia"}],
                    }
                ]
            }
        },
        ensure_ascii=False,
    )


def _episode_alias_plan(total_episodes: int) -> dict[str, object]:
    return {
        "planning_scope": "current_batch_only",
        "global_naming_style": "统一使用角色中文全名【状态】",
        "global_rules": ["禁止使用男主、女主等泛称"],
        "episodes": [
            {
                "episode": episode,
                "title": f"第{episode}集",
                "main_character_aliases": [
                    {
                        "character_id": "linxia",
                        "character_name": "林夏",
                        "recommended_alias_name": f"林夏【第{episode}集状态】",
                        "reason": f"第{episode}集剧情状态变化",
                    }
                ],
                "appearance_events": [f"event-{episode}"],
                "scene_based_alias_hints": [],
            }
            for episode in range(1, total_episodes + 1)
        ],
        "scene_level_usage_plan": [
            {
                "scene_name": "玻璃会议室",
                "expected_alias_usage": [
                    {
                        "character_id": "linxia",
                        "character_name": "林夏",
                        "alias_name": "林夏【会议室交锋态】",
                        "reason": "进入公开博弈场景时使用",
                    }
                ],
            }
        ],
        "uncertain_or_missing_items": [],
    }


def _script_review_payload(
    *,
    passed: bool,
    rewrite_required: bool,
    blocking_issues: list[str] | None = None,
    non_blocking_issues: list[str] | None = None,
    summary: str = "",
    rewrite_start_episode: int = 1,
    stage: str = "five_episode_continuity_review",
) -> dict[str, object]:
    return {
        "passed": passed,
        "rewrite_required": rewrite_required,
        "blocking_issues": list(blocking_issues or []),
        "non_blocking_issues": list(non_blocking_issues or []),
        "summary": summary,
        "rewrite_start_episode": rewrite_start_episode,
        "stage": stage,
    }


def _episode_numbers_from_plan(plan_value: object) -> list[int]:
    candidate = plan_value
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except Exception:
            return []
    if not isinstance(candidate, dict):
        return []
    episodes = candidate.get("episodes")
    if not isinstance(episodes, list):
        return []
    return [
        int(item["episode"])
        for item in episodes
        if isinstance(item, dict) and int(item.get("episode", 0)) > 0
    ]


def _episode_numbers_from_object(value: object) -> list[int]:
    if not isinstance(value, dict):
        return []
    if isinstance(value.get("episodes"), list):
        source = value["episodes"]
    elif isinstance(value.get("episode_dialogue_blocks"), list):
        source = value["episode_dialogue_blocks"]
    else:
        return []
    return [
        int(item["episode"])
        for item in source
        if isinstance(item, dict) and int(item.get("episode", 0)) > 0
    ]


def _jsonish(value: object) -> object:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _appearance_plan_episodes(value: object) -> list[int]:
    candidate = _jsonish(value)
    if isinstance(candidate, dict):
        return _episode_numbers_from_object(candidate)
    return []


class _PhaseRecordingRunner:
    def __init__(
        self,
        *,
        review_sequences: dict[str, list[object]] | None = None,
        stage_outputs: dict[str, list[object]] | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.review_sequences = {
            key: list(value)
            for key, value in (review_sequences or {}).items()
        }
        self.stage_outputs = {
            key: list(value)
            for key, value in (stage_outputs or {}).items()
        }

    def run_stage(self, stage_name: str, variables: dict[str, object]) -> dict[str, object]:
        batch_start = int(variables.get(BATCH_START_EPISODE, 0) or 0)
        plan_episodes = _episode_numbers_from_plan(variables.get(EPISODE_PLAN))
        hooks_episodes = _episode_numbers_from_object(variables.get(ALL_HOOKS))
        dialogue_episodes = _episode_numbers_from_object(variables.get(ALL_DIALOGUES))
        self.calls.append(
            {
                "stage": stage_name,
                "batch_start": batch_start,
                "plan_episodes": plan_episodes,
                "hooks_episodes": hooks_episodes,
                "dialogue_episodes": dialogue_episodes,
                "story_outline_text": str(variables.get(STORY_OUTLINE) or ""),
                "worldview_text": str(variables.get(WORLDVIEW) or ""),
                "characters_text": str(variables.get(CHARACTERS) or ""),
                "scenes_text": str(variables.get(SCENES) or ""),
                "appearance_text": str(variables.get(APPEARANCE_MAPPING) or ""),
                "appearance_plan_episodes": _appearance_plan_episodes(
                    variables.get(APPEARANCE_MAPPING)
                ),
                "hook_write_alias_episodes": _episode_numbers_from_object(
                    variables.get(HOOK_CURRENT_WRITE_VAR)
                ),
                "hook_review_alias_episodes": _episode_numbers_from_object(
                    variables.get(HOOK_CURRENT_VAR)
                ),
                "dialogue_write_alias_episodes": _episode_numbers_from_object(
                    variables.get(DIALOGUE_CURRENT_WRITE_VAR)
                ),
                "dialogue_workflow_alias_episodes": _episode_numbers_from_object(
                    variables.get(DIALOGUE_CURRENT_WORKFLOW_VAR)
                ),
                "dialogue_legacy_alias_episodes": _episode_numbers_from_object(
                    variables.get(DIALOGUE_CURRENT_VAR)
                ),
                "dialogue_hook_batch_alias_episodes": _episode_numbers_from_object(
                    variables.get(DIALOGUE_HOOK_BATCH_VAR)
                ),
                "dialogue_hook_review_alias_episodes": _episode_numbers_from_object(
                    variables.get(DIALOGUE_HOOK_REVIEW_VAR)
                ),
                "dialogue_hook_rewrite_alias_episodes": _episode_numbers_from_object(
                    variables.get(DIALOGUE_HOOK_REWRITE_VAR)
                ),
                "dialogue_hook_prompt_alias_episodes": _episode_numbers_from_object(
                    variables.get(DIALOGUE_HOOK_INPUT_VAR)
                ),
                "script_write_alias_text": str(variables.get(SCRIPT_CURRENT_WRITE_VAR) or ""),
                "script_current_alias_text": str(variables.get(SCRIPT_CURRENT_VAR) or ""),
                "script_review_alias_text": str(variables.get(SCRIPT_REVIEW_WRITE_VAR) or ""),
                "script_hook_alias_episodes": _episode_numbers_from_object(
                    variables.get(SCRIPT_HOOK_BATCH_VAR)
                ),
                "script_dialogue_alias_episodes": _episode_numbers_from_object(
                    variables.get(SCRIPT_DIALOGUE_BATCH_VAR)
                ),
                "unstructured_kind": str(variables.get(UNSTRUCTURED_KIND_VAR) or ""),
                "unstructured_source": str(variables.get(UNSTRUCTURED_SOURCE_VAR) or ""),
            }
        )

        custom_output = self._custom_stage_output(stage_name)
        if custom_output is not None:
            return custom_output

        if stage_name == STAGE_FRAMEWORK:
            return {
                SCRIPT_TITLE: "测试剧本",
                STORY_OUTLINE: _framework_story_outline(),
                USER_CHARACTERS: _framework_characters(),
                USER_SCENES: _framework_scenes(),
                EPISODE_PLAN: _framework_episode_plan(10),
            }
        if stage_name in {STAGE_HOOKS, STAGE_HOOKS_WRITING, STAGE_HOOKS_REWRITE}:
            return {BATCH_HOOKS: _hook_batch(plan_episodes)}
        if stage_name == STAGE_HOOKS_REVIEW:
            return self._review_payload(stage_name)
        if stage_name in {STAGE_DIALOGUES, STAGE_DIALOGUES_WRITING, STAGE_DIALOGUES_REWRITE}:
            return {BATCH_DIALOGUES: _dialogue_batch(plan_episodes)}
        if stage_name == STAGE_DIALOGUES_REVIEW:
            return self._review_payload(stage_name)
        if stage_name in {STAGE_SCRIPT, STAGE_SCRIPT_WRITING, STAGE_SCRIPT_REWRITE}:
            return {BATCH_SCRIPT: _script_batch_text(plan_episodes)}
        if stage_name == STAGE_SCRIPT_REVIEW:
            return self._review_payload(stage_name)
        if stage_name == STAGE_SCRIPT_MEMORY:
            return {
                LAST_SUMMARY: json.dumps(
                    {
                        "this_turn_episodes": plan_episodes,
                        "abstract_of_this_turn": f"summary-{len(self.memory_calls()) + 1}",
                        "final_hook_of_this_turn": f"hook-{plan_episodes[-1] if plan_episodes else 0}",
                        "must_carry_into_next_turn": [],
                        "appearance_continuity_summary": "stable",
                    },
                    ensure_ascii=False,
                )
            }
        if stage_name == STAGE_FRAMEWORK_NATURALIZE:
            return {
                FRAMEWORK_NATURAL_LANGUAGE: "剧本标题：测试剧本\n故事梗概：这是完整框架说明。\n主要人物小传：主角与配角关系清晰。\n核心场景说明：关键场景已整理。\n分集计划说明：第1集到第10集推进明确。"
            }
        if stage_name == STAGE_WORLDVIEW_NATURALIZE:
            return {
                WORLDVIEW_NATURAL_LANGUAGE: "世界设定：测试世界观。\n社会规则：规则清晰。\n冲突机制：外部压力持续推动剧情。\n视觉关键词：潮湿、压抑、霓虹。"
            }
        raise AssertionError(f"Unexpected stage call: {stage_name}")

    def stage_calls(self, stage_name: str) -> list[dict[str, object]]:
        return [call for call in self.calls if call["stage"] == stage_name]

    def memory_calls(self) -> list[dict[str, object]]:
        return self.stage_calls(STAGE_SCRIPT_MEMORY)

    def _review_payload(self, stage_name: str) -> dict[str, object]:
        sequence = self.review_sequences.get(stage_name, [])
        if sequence:
            item = sequence.pop(0)
            if isinstance(item, Exception):
                raise item
            if isinstance(item, dict):
                if stage_name == STAGE_SCRIPT_REVIEW:
                    enriched = _script_review_payload(
                        passed=bool(item.get("passed", False)),
                        rewrite_required=bool(item.get("rewrite_required", False)),
                        blocking_issues=list(item.get("blocking_issues", []) or []),
                        non_blocking_issues=list(item.get("non_blocking_issues", []) or []),
                        summary=str(item.get("summary") or f"{stage_name} custom"),
                        rewrite_start_episode=int(item.get("rewrite_start_episode", 1) or 1),
                        stage=str(item.get("stage") or "five_episode_continuity_review"),
                    )
                    enriched.update(dict(item))
                    return enriched
                return dict(item)
            if item is False:
                if stage_name == STAGE_SCRIPT_REVIEW:
                    return _script_review_payload(
                        passed=False,
                        rewrite_required=True,
                        blocking_issues=[f"{stage_name} failed"],
                        non_blocking_issues=[],
                        summary=f"{stage_name} failed",
                    )
                return {
                    "passed": False,
                    "rewrite_required": True,
                    "blocking_issues": [f"{stage_name} failed"],
                    "summary": f"{stage_name} failed",
                    "non_blocking_issues": [],
                }
        if stage_name == STAGE_SCRIPT_REVIEW:
            return _script_review_payload(
                passed=True,
                rewrite_required=False,
                blocking_issues=[],
                non_blocking_issues=[],
                summary=f"{stage_name} passed",
            )
        return {
            "passed": True,
            "rewrite_required": False,
            "blocking_issues": [],
            "summary": f"{stage_name} passed",
            "non_blocking_issues": [],
        }

    def _custom_stage_output(self, stage_name: str) -> dict[str, object] | None:
        sequence = self.stage_outputs.get(stage_name, [])
        if not sequence:
            return None
        item = sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            return dict(item)
        raise AssertionError(f"Custom stage output for {stage_name} must be dict")


class _RuntimeSpy:
    def __init__(self) -> None:
        self.stage_messages: list[dict[str, object]] = []

    def set_stage(self, stage_key, message, **kwargs) -> None:
        self.stage_messages.append(
            {
                "stage_key": str(stage_key or ""),
                "message": str(message or ""),
                **dict(kwargs),
            }
        )

    def sync_from_state(self, state) -> None:
        del state

    def checkpoint(self) -> None:
        return None


class BatchedGenerationFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_batch_mode = settings.fastgpt_batch_mode
        self._original_batch_size = settings.batch_size
        self._original_review_loops = settings.fastgpt_stage_review_revise_max_loops
        self._original_format_retry_limit = settings.fastgpt_stage_format_retry_limit
        self._original_workflow_json_dir = getattr(settings, "workflow_json_dir", None)
        settings.fastgpt_batch_mode = "local"
        settings.batch_size = 5
        settings.fastgpt_stage_review_revise_max_loops = 10
        settings.fastgpt_stage_format_retry_limit = 3
        self._debug_artifact_dir = (
            Path("workflow_code_skeleton")
            / "runtime_data"
            / "debug"
            / "fastgpt_stage_failures"
        )
        self._cleanup_debug_artifacts()

    def tearDown(self) -> None:
        settings.fastgpt_batch_mode = self._original_batch_mode
        settings.batch_size = self._original_batch_size
        settings.fastgpt_stage_review_revise_max_loops = self._original_review_loops
        settings.fastgpt_stage_format_retry_limit = self._original_format_retry_limit
        settings.workflow_json_dir = self._original_workflow_json_dir
        self._cleanup_debug_artifacts()

    def _cleanup_debug_artifacts(self) -> None:
        if not self._debug_artifact_dir.exists():
            return
        for path in self._debug_artifact_dir.glob("*.json"):
            try:
                path.unlink()
            except OSError:
                pass
        for path in (self._debug_artifact_dir, self._debug_artifact_dir.parent):
            try:
                path.rmdir()
            except OSError:
                pass

    def _base_variables(self, total_episodes: int) -> dict[str, object]:
        normalized_plan = _normalized_plan(total_episodes)
        return {
            TOTAL_EPISODES: total_episodes,
            EPISODE_WORD_COUNT: 1200,
            STORY_OUTLINE: "测试大纲",
            WORLDVIEW: json.dumps({"worldview_summary": "测试世界观"}, ensure_ascii=False),
            CHARACTERS: json.dumps({"character_setting": {"characters": []}}, ensure_ascii=False),
            SCENES: json.dumps({"scene_setting": {"scenes": []}}, ensure_ascii=False),
            APPEARANCE_MAPPING: {"appearance_mapping": {"characters": []}},
            CHARACTER_ALIAS_NAMING_RULES: "统一使用正式中文名",
            EPISODE_PLAN: json.dumps(normalized_plan, ensure_ascii=False),
            NORMALIZED_EPISODE_PLAN: normalized_plan,
            MAX_RETRIES: 10,
            ALL_SCRIPT: "",
            LAST_SUMMARY: "",
        }

    def _state_and_payload(
        self,
        total_episodes: int,
        *,
        variables: dict[str, object] | None = None,
    ) -> tuple[WorkflowState, WorkflowInput, dict[str, object]]:
        payload = _workflow_input(total_episodes)
        merged_variables = self._base_variables(total_episodes)
        if variables:
            merged_variables.update(variables)
        state = WorkflowState(user_input=payload, variables=dict(merged_variables))
        return state, payload, merged_variables

    def test_sync_state_variables_keeps_character_structured_and_natural_outputs_separate(self) -> None:
        state, _, _ = self._state_and_payload(10, variables={CHARACTERS: ""})

        flow._sync_state_variables(
            state,
            {
                CHARACTERS: json.dumps(_character_setting_json(), ensure_ascii=False),
                CHARACTER_NATURAL_LANGUAGE_VAR: "人物小传自然语言版",
            },
        )

        self.assertIn('"character_setting"', str(state.get_var(CHARACTERS)))
        self.assertEqual(state.get_var(CHARACTER_NATURAL_LANGUAGE_VAR), "人物小传自然语言版")

    def test_sync_state_variables_keeps_scene_structured_and_natural_outputs_separate(self) -> None:
        state, _, _ = self._state_and_payload(10, variables={SCENES: ""})

        flow._sync_state_variables(
            state,
            {
                SCENES: json.dumps(_scene_setting_json(), ensure_ascii=False),
                SCENE_NATURAL_LANGUAGE_VAR: "核心场景自然语言版",
            },
        )

        self.assertIn('"scene_setting"', str(state.get_var(SCENES)))
        self.assertEqual(state.get_var(SCENE_NATURAL_LANGUAGE_VAR), "核心场景自然语言版")

    def _script_ready_state(
        self,
        total_episodes: int,
        *,
        variables: dict[str, object] | None = None,
    ) -> tuple[WorkflowState, WorkflowInput, dict[str, object], list[BatchWindow]]:
        all_hooks: dict[str, object] = {}
        all_dialogues: dict[str, object] = {}
        for batch in iter_episode_batches(total_episodes, batch_size=5):
            episodes = list(range(batch.start_episode, batch.end_episode + 1))
            all_hooks = flow.merge_batch_object(all_hooks, _hook_batch(episodes))
            all_dialogues = flow.merge_batch_object(all_dialogues, _dialogue_batch(episodes))
        merged = {
            ALL_HOOKS: all_hooks,
            ALL_DIALOGUES: all_dialogues,
        }
        if variables:
            merged.update(variables)
        state, payload, base_variables = self._state_and_payload(total_episodes, variables=merged)
        batches = list(iter_episode_batches(total_episodes, batch_size=5))
        return state, payload, base_variables, batches

    def _normalize_stage_state(
        self,
        total_episodes: int = 10,
    ) -> tuple[WorkflowState, WorkflowInput, dict[str, object]]:
        payload = _workflow_input(total_episodes)
        variables = {
            TOTAL_EPISODES: total_episodes,
            STORY_OUTLINE: _framework_story_outline(),
            USER_CHARACTERS: _framework_characters(),
            CHARACTER_ALIAS_NAMING_RULES: "统一使用正式中文名",
            EPISODE_PLAN: json.dumps(_framework_episode_plan(total_episodes), ensure_ascii=False),
        }
        state = WorkflowState(user_input=payload, variables=dict(variables))
        return state, payload, variables

    def test_framework_naturalize_uses_complete_framework_snapshot_and_preserves_structured_fields(self) -> None:
        story_outline = {"opening": "故事开场", "theme": "选择"}
        user_characters = [{"name": "林夏", "role_type": "主角"}]
        user_scenes = {"core_locations": [{"name": "旧码头"}]}
        episode_plan = [{"episode": 1, "title": "回城"}]
        state, payload, variables = self._state_and_payload(
            10,
            variables={
                SCRIPT_TITLE: "崛起之路",
                STORY_OUTLINE: story_outline,
                USER_CHARACTERS: user_characters,
                USER_SCENES: user_scenes,
                EPISODE_PLAN: episode_plan,
            },
        )
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_FRAMEWORK_NATURALIZE: [
                    {UNSTRUCTURED_OUTPUT_VAR: "剧本标题：崛起之路\n故事梗概：故事完整展开。\n主要人物小传：人物关系清晰。\n核心场景说明：旧码头是关键舞台。\n分集计划说明：第1集推进主线。"}
                ]
            }
        )

        flow._ensure_framework_natural_language(state, runner, payload, variables)

        call = runner.stage_calls(STAGE_FRAMEWORK_NATURALIZE)[0]
        self.assertEqual(call["unstructured_kind"], "framework")
        self.assertIn('"script_title_content": "崛起之路"', str(call["unstructured_source"]))
        self.assertIn('"story_outline"', str(call["unstructured_source"]))
        self.assertIn('"user_characters"', str(call["unstructured_source"]))
        self.assertIn('"user_scenes"', str(call["unstructured_source"]))
        self.assertIn('"episode_plan"', str(call["unstructured_source"]))
        self.assertIn(FRAMEWORK_NATURAL_LANGUAGE, variables)
        self.assertEqual(variables[SCRIPT_TITLE], "崛起之路")
        self.assertEqual(variables[STORY_OUTLINE], story_outline)
        self.assertEqual(variables[USER_CHARACTERS], user_characters)
        self.assertEqual(variables[USER_SCENES], user_scenes)
        self.assertEqual(variables[EPISODE_PLAN], episode_plan)

    def test_framework_and_consistency_runs_framework_naturalize_before_pre_strategy(self) -> None:
        state, payload, variables = self._state_and_payload(10)
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_FRAMEWORK: [
                    {
                        SCRIPT_TITLE: "测试剧本",
                        STORY_OUTLINE: _framework_story_outline(),
                        USER_CHARACTERS: _framework_characters(),
                        USER_SCENES: _framework_scenes(),
                        EPISODE_PLAN: _framework_episode_plan(10),
                    }
                ],
                STAGE_FRAMEWORK_NATURALIZE: [
                    {UNSTRUCTURED_OUTPUT_VAR: "剧本标题：测试剧本\n故事梗概：完整自然语言框架。\n主要人物小传：主角成长。\n核心场景说明：实验室与城市。\n分集计划说明：第1集到第10集。"}
                ],
                STAGE_APPEARANCE_PRE_STRATEGY: [
                    {
                        CHARACTER_APPEARANCE_REQUIREMENTS: "人物外观要求",
                        CHARACTER_ALIAS_NAMING_RULES: "命名规则",
                        OUTFIT_SWITCH_RULES: "服装切换规则",
                    }
                ],
                STAGE_CONSISTENCY: [{IS_CONSISTENT: True}],
            }
        )

        flow._ensure_framework_and_consistency(
            state,
            runner,
            payload,
            variables,
            resume_snapshot_present=False,
        )

        stages = [str(call["stage"]) for call in runner.calls]
        self.assertEqual(
            stages,
            [
                STAGE_FRAMEWORK,
                STAGE_FRAMEWORK_NATURALIZE,
                STAGE_APPEARANCE_PRE_STRATEGY,
                STAGE_CONSISTENCY,
            ],
        )

    def test_worldview_naturalize_uses_worldview_output_and_keeps_structured_worldview(self) -> None:
        worldview_payload = {
            "era_background": "近未来沿海都市",
            "rules": "信息流高度受控",
            "conflict": "个人意志与系统对撞",
        }
        state, _, variables = self._state_and_payload(
            10,
            variables={WORLDVIEW: worldview_payload},
        )
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_WORLDVIEW_NATURALIZE: [
                    {UNSTRUCTURED_OUTPUT_VAR: "世界设定：近未来沿海都市。\n社会规则：信息流高度受控。\n冲突机制：个人意志与系统对撞。"}
                ]
            }
        )

        flow._ensure_worldview_natural_language(state, runner, variables)

        call = runner.stage_calls(STAGE_WORLDVIEW_NATURALIZE)[0]
        self.assertEqual(call["unstructured_kind"], "worldview")
        self.assertIn("近未来沿海都市", str(call["unstructured_source"]))
        self.assertIn(WORLDVIEW_NATURAL_LANGUAGE, variables)
        self.assertEqual(variables[WORLDVIEW], worldview_payload)

    def test_character_naturalize_uses_structured_characters_and_keeps_formal_output(self) -> None:
        characters_payload = _character_setting_json()
        state, _, variables = self._state_and_payload(
            10,
            variables={CHARACTERS: json.dumps(characters_payload, ensure_ascii=False)},
        )
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_CHARACTERS_NATURALIZE: [
                    {UNSTRUCTURED_OUTPUT_VAR: "林夏：项目负责人，性格冷静克制。\n顾川：主角的重要对手与镜像。"}
                ]
            }
        )

        flow._ensure_character_natural_language(state, runner, variables)

        call = runner.stage_calls(STAGE_CHARACTERS_NATURALIZE)[0]
        self.assertEqual(call["unstructured_kind"], "generic")
        self.assertIn('"character_setting"', str(call["unstructured_source"]))
        self.assertIn(CHARACTER_NATURAL_LANGUAGE_VAR, variables)
        self.assertEqual(variables[CHARACTERS], json.dumps(characters_payload, ensure_ascii=False))
        self.assertEqual(state.get_var(CHARACTER_NATURAL_LANGUAGE_VAR), "林夏：项目负责人，性格冷静克制。\n顾川：主角的重要对手与镜像。")

    def test_framework_and_worldview_natural_language_do_not_overwrite_each_other(self) -> None:
        state, payload, variables = self._state_and_payload(
            10,
            variables={
                SCRIPT_TITLE: "崛起之路",
                STORY_OUTLINE: {"opening": "开场"},
                USER_CHARACTERS: [{"name": "林夏"}],
                USER_SCENES: {"core_locations": [{"name": "旧码头"}]},
                EPISODE_PLAN: [{"episode": 1, "title": "回城"}],
                WORLDVIEW: {"rules": "规则体系"},
            },
        )
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_FRAMEWORK_NATURALIZE: [{UNSTRUCTURED_OUTPUT_VAR: "框架自然语言版"}],
                STAGE_WORLDVIEW_NATURALIZE: [{UNSTRUCTURED_OUTPUT_VAR: "世界观自然语言版"}],
            }
        )

        flow._ensure_framework_natural_language(state, runner, payload, variables)
        flow._ensure_worldview_natural_language(state, runner, variables)

        self.assertEqual(variables[FRAMEWORK_NATURAL_LANGUAGE], "框架自然语言版")
        self.assertEqual(variables[WORLDVIEW_NATURAL_LANGUAGE], "世界观自然语言版")

    def test_unstructured_natural_language_validator_rejects_json_and_empty(self) -> None:
        spec = load_workflow_output_contract(
            stage_name=STAGE_FRAMEWORK_NATURALIZE,
            expected_output_kind="unstructured_natural_language_text",
            workflow_json_name="自然语言化.json",
        )

        with self.assertRaises(WorkflowOutputValidationError):
            validate_stage_output_with_workflow_contract(
                {UNSTRUCTURED_OUTPUT_VAR: '{"title":"bad"}'},
                spec=spec,
                canonical_name=FRAMEWORK_NATURAL_LANGUAGE,
                aliases=(UNSTRUCTURED_OUTPUT_VAR,),
            )

        with self.assertRaises(WorkflowOutputValidationError):
            validate_stage_output_with_workflow_contract(
                {UNSTRUCTURED_OUTPUT_VAR: "   "},
                spec=spec,
                canonical_name=FRAMEWORK_NATURAL_LANGUAGE,
                aliases=(UNSTRUCTURED_OUTPUT_VAR,),
            )

    def test_three_phase_order_runs_all_hooks_before_dialogues_and_script(self) -> None:
        state, payload, variables = self._state_and_payload(10)
        runner = _PhaseRecordingRunner()

        flow._run_batched_generation(state, runner, payload, variables)

        stages = [str(call["stage"]) for call in runner.calls]
        self.assertEqual(
            stages,
            [
                STAGE_HOOKS_WRITING,
                STAGE_HOOKS_REVIEW,
                STAGE_HOOKS_WRITING,
                STAGE_HOOKS_REVIEW,
                STAGE_DIALOGUES_WRITING,
                STAGE_DIALOGUES_REVIEW,
                STAGE_DIALOGUES_WRITING,
                STAGE_DIALOGUES_REVIEW,
                STAGE_SCRIPT_WRITING,
                STAGE_SCRIPT_REVIEW,
                STAGE_SCRIPT_MEMORY,
                STAGE_SCRIPT_WRITING,
                STAGE_SCRIPT_REVIEW,
                STAGE_SCRIPT_MEMORY,
            ],
        )
        self.assertEqual(
            [int(call["batch_start"]) for call in runner.stage_calls(STAGE_HOOKS_WRITING)],
            [1, 6],
        )
        self.assertEqual(
            [int(call["batch_start"]) for call in runner.stage_calls(STAGE_DIALOGUES_WRITING)],
            [1, 6],
        )
        self.assertEqual(
            [call["hooks_episodes"] for call in runner.stage_calls(STAGE_DIALOGUES_WRITING)],
            [list(range(1, 6)), list(range(6, 11))],
        )
        self.assertEqual(
            [call["dialogue_hook_batch_alias_episodes"] for call in runner.stage_calls(STAGE_DIALOGUES_WRITING)],
            [list(range(1, 6)), list(range(6, 11))],
        )
        self.assertEqual(
            [call["hooks_episodes"] for call in runner.stage_calls(STAGE_SCRIPT_WRITING)],
            [list(range(1, 6)), list(range(6, 11))],
        )
        self.assertEqual(
            [call["dialogue_episodes"] for call in runner.stage_calls(STAGE_SCRIPT_WRITING)],
            [list(range(1, 6)), list(range(6, 11))],
        )
        self.assertEqual(
            [call["script_hook_alias_episodes"] for call in runner.stage_calls(STAGE_SCRIPT_WRITING)],
            [list(range(1, 6)), list(range(6, 11))],
        )
        self.assertEqual(
            [call["script_dialogue_alias_episodes"] for call in runner.stage_calls(STAGE_SCRIPT_WRITING)],
            [list(range(1, 6)), list(range(6, 11))],
        )
        self.assertEqual(len(runner.memory_calls()), 2)

    def test_dialogues_stage_requires_complete_hooks(self) -> None:
        state, payload, variables = self._state_and_payload(10)
        batches = list(iter_episode_batches(10, batch_size=5))

        with self.assertRaisesRegex(ValueError, "ALL_HOOKS"):
            flow._run_all_dialogue_batches(
                state,
                _PhaseRecordingRunner(),
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

    def test_script_stage_requires_complete_dialogues(self) -> None:
        variables = self._base_variables(10)
        variables[ALL_HOOKS] = flow.merge_batch_object(_hook_batch([1, 2, 3, 4, 5]), _hook_batch([6, 7, 8, 9, 10]))
        state, payload, variables = self._state_and_payload(10, variables=variables)
        batches = list(iter_episode_batches(10, batch_size=5))

        with self.assertRaisesRegex(ValueError, "ALL_DIALOGUES"):
            flow._run_all_script_batches(
                state,
                _PhaseRecordingRunner(),
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

    def test_resume_skips_completed_hooks_and_continues_from_dialogue_phase(self) -> None:
        complete_hooks = flow.merge_batch_object(
            _hook_batch([1, 2, 3, 4, 5]),
            _hook_batch([6, 7, 8, 9, 10]),
        )
        partial_dialogues = _dialogue_batch([1, 2, 3, 4, 5])
        state, payload, variables = self._state_and_payload(
            10,
            variables={
                ALL_HOOKS: complete_hooks,
                ALL_DIALOGUES: partial_dialogues,
                BATCH_DIALOGUES: partial_dialogues,
            },
        )
        runner = _PhaseRecordingRunner()

        flow._run_batched_generation(state, runner, payload, variables)

        stages = [str(call["stage"]) for call in runner.calls]
        self.assertEqual(
            stages,
            [
                STAGE_DIALOGUES_WRITING,
                STAGE_DIALOGUES_REVIEW,
                STAGE_SCRIPT_WRITING,
                STAGE_SCRIPT_REVIEW,
                STAGE_SCRIPT_MEMORY,
                STAGE_SCRIPT_WRITING,
                STAGE_SCRIPT_REVIEW,
                STAGE_SCRIPT_MEMORY,
            ],
        )
        self.assertEqual(
            [int(call["batch_start"]) for call in runner.stage_calls(STAGE_DIALOGUES_WRITING)],
            [6],
        )

    def test_restored_hooks_batches_must_pass_structure_validation_before_skip(self) -> None:
        invalid_hooks = flow.merge_batch_object(
            _hook_batch([1, 2, 3, 4, 5]),
            _hook_batch([6, 7, 8, 9, 10]),
        )
        invalid_hooks["episodes"][5].pop("opening_action", None)
        state, payload, variables = self._state_and_payload(
            10,
            variables={ALL_HOOKS: invalid_hooks},
        )
        runner = _PhaseRecordingRunner()

        flow._run_batched_generation(state, runner, payload, variables)

        self.assertEqual(
            [int(call["batch_start"]) for call in runner.stage_calls(STAGE_HOOKS_WRITING)],
            [6],
        )
        self.assertEqual(len(runner.stage_calls(STAGE_DIALOGUES_WRITING)), 2)

    def test_restored_dialogue_batches_reject_legacy_or_empty_batch_cache(self) -> None:
        complete_hooks = flow.merge_batch_object(
            _hook_batch([1, 2, 3, 4, 5]),
            _hook_batch([6, 7, 8, 9, 10]),
        )
        invalid_dialogues = flow.merge_batch_object(
            _dialogue_batch([1, 2, 3, 4, 5]),
            _dialogue_batch_flat_legacy([6, 7, 8, 9, 10]),
        )
        invalid_dialogues["batch_meta"] = {"start_episode": 6, "end_episode": 10}
        state, payload, variables = self._state_and_payload(
            10,
            variables={
                ALL_HOOKS: complete_hooks,
                ALL_DIALOGUES: invalid_dialogues,
                BATCH_DIALOGUES: {
                    "batch_meta": {"start_episode": 6, "end_episode": 10},
                    "episode_dialogue_blocks": [],
                },
            },
        )
        runner = _PhaseRecordingRunner()

        flow._run_batched_generation(state, runner, payload, variables)

        self.assertEqual(len(runner.stage_calls(STAGE_HOOKS_WRITING)), 0)
        self.assertEqual(
            [int(call["batch_start"]) for call in runner.stage_calls(STAGE_DIALOGUES_WRITING)],
            [6],
        )

    def test_restored_progress_prefers_dialogue_phase_after_hooks_complete(self) -> None:
        complete_hooks = flow.merge_batch_object(
            _hook_batch([1, 2, 3, 4, 5]),
            _hook_batch([6, 7, 8, 9, 10]),
        )
        partial_dialogues = _dialogue_batch([1, 2, 3, 4, 5])
        variables = self._base_variables(10)
        variables[ALL_HOOKS] = complete_hooks
        variables[ALL_DIALOGUES] = partial_dialogues
        batches = list(iter_episode_batches(10, batch_size=5))

        start_episode, completed_batches = flow._derive_restored_batch_progress(
            variables,
            batches=batches,
            current_stage="",
            rewrite_stage="",
        )

        self.assertEqual(start_episode, 6)
        self.assertEqual(completed_batches, 1)

    def test_rewrite_from_final_requires_strict_script_validation(self) -> None:
        variables = self._base_variables(10)
        variables[ALL_HOOKS] = flow.merge_batch_object(
            _hook_batch([1, 2, 3, 4, 5]),
            _hook_batch([6, 7, 8, 9, 10]),
        )
        variables[ALL_DIALOGUES] = flow.merge_batch_object(
            _dialogue_batch([1, 2, 3, 4, 5]),
            _dialogue_batch([6, 7, 8, 9, 10]),
        )
        variables[ALL_SCRIPT] = _script_batch_text_without_scene_headings([1, 2, 3, 4, 5]) + "\n\n" + _script_batch_text_without_scene_headings(
            [6, 7, 8, 9, 10]
        )
        variables[flow.LOCAL_REWRITE_FROM_STAGE] = "final"
        state, payload, variables = self._state_and_payload(10, variables=variables)
        runner = _PhaseRecordingRunner()

        flow._run_batched_generation(state, runner, payload, variables)

        self.assertEqual(
            [int(call["batch_start"]) for call in runner.stage_calls(STAGE_SCRIPT_WRITING)],
            [1, 6],
        )

    def test_final_guard_rejects_when_script_has_missing_episodes(self) -> None:
        variables = self._base_variables(10)
        variables[ALL_HOOKS] = flow.merge_batch_object(
            _hook_batch([1, 2, 3, 4, 5]),
            _hook_batch([6, 7, 8, 9, 10]),
        )
        variables[ALL_DIALOGUES] = flow.merge_batch_object(
            _dialogue_batch([1, 2, 3, 4, 5]),
            _dialogue_batch([6, 7, 8, 9, 10]),
        )
        variables[ALL_SCRIPT] = _script_batch_text([1, 2, 3, 4, 5])
        payload = _workflow_input(10)

        with self.assertRaisesRegex(ValueError, "剧本正文存在缺集"):
            flow._ensure_complete_batched_outputs_before_final(payload, variables)

    def test_final_guard_rejects_when_hooks_missing(self) -> None:
        variables = self._base_variables(10)
        variables[ALL_HOOKS] = _hook_batch([1, 2, 3, 4, 5])
        variables[ALL_DIALOGUES] = flow.merge_batch_object(
            _dialogue_batch([1, 2, 3, 4, 5]),
            _dialogue_batch([6, 7, 8, 9, 10]),
        )
        variables[ALL_SCRIPT] = _script_batch_text([1, 2, 3, 4, 5]) + "\n\n" + _script_batch_text(
            [6, 7, 8, 9, 10]
        )
        payload = _workflow_input(10)

        with self.assertRaisesRegex(ValueError, "开头冲突钩子存在缺集"):
            flow._ensure_complete_batched_outputs_before_final(payload, variables)

    def test_final_guard_rejects_when_dialogues_missing(self) -> None:
        variables = self._base_variables(10)
        variables[ALL_HOOKS] = flow.merge_batch_object(
            _hook_batch([1, 2, 3, 4, 5]),
            _hook_batch([6, 7, 8, 9, 10]),
        )
        variables[ALL_DIALOGUES] = _dialogue_batch([1, 2, 3, 4, 5])
        variables[ALL_SCRIPT] = _script_batch_text([1, 2, 3, 4, 5]) + "\n\n" + _script_batch_text(
            [6, 7, 8, 9, 10]
        )
        payload = _workflow_input(10)

        with self.assertRaisesRegex(ValueError, "角色对白存在缺集"):
            flow._ensure_complete_batched_outputs_before_final(payload, variables)

    def test_review_failure_triggers_rewrite_but_pass_stops_extra_rewrites(self) -> None:
        state, payload, variables = self._state_and_payload(5)
        runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_HOOKS_REVIEW: [False, True],
                STAGE_DIALOGUES_REVIEW: [True],
                STAGE_SCRIPT_REVIEW: [True],
            }
        )

        flow._run_batched_generation(state, runner, payload, variables)

        self.assertEqual(len(runner.stage_calls(STAGE_HOOKS_REWRITE)), 1)
        self.assertEqual(len(runner.stage_calls(STAGE_DIALOGUES_REWRITE)), 0)
        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 0)
        self.assertEqual(len(runner.stage_calls(STAGE_HOOKS_REVIEW)), 2)

    def test_review_loop_exhaustion_raises_without_polluting_committed_outputs(self) -> None:
        state, payload, variables = self._state_and_payload(5)
        settings.fastgpt_stage_review_revise_max_loops = 3
        runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_HOOKS_REVIEW: [False, False, False],
            }
        )

        with self.assertRaisesRegex(ValueError, "开头冲突钩子 1-5 集审核未通过"):
            flow._run_batched_generation(state, runner, payload, variables)

        self.assertNotIn(ALL_HOOKS, variables)
        self.assertNotIn(ALL_DIALOGUES, variables)
        self.assertEqual(str(variables.get(ALL_SCRIPT, "") or "").strip(), "")
        self.assertEqual(len(runner.stage_calls(STAGE_HOOKS_REVIEW)), 3)
        self.assertEqual(len(runner.stage_calls(STAGE_HOOKS_REWRITE)), 2)

    def test_continue_after_failed_batch_restarts_same_phase_same_batch(self) -> None:
        state, payload, variables = self._state_and_payload(10)
        settings.fastgpt_stage_review_revise_max_loops = 1
        failing_runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_HOOKS_REVIEW: [False],
            }
        )

        with self.assertRaisesRegex(ValueError, "开头冲突钩子 1-5 集审核未通过"):
            flow._run_batched_generation(state, failing_runner, payload, variables)

        self.assertEqual(variables[BATCH_START_EPISODE], 1)
        self.assertEqual(variables.get(flow.LOCAL_CURRENT_BATCH_STAGE), "hook")
        self.assertNotIn(ALL_HOOKS, variables)

        settings.fastgpt_stage_review_revise_max_loops = 10
        resumed_runner = _PhaseRecordingRunner()
        flow._run_batched_generation(state, resumed_runner, payload, variables)

        self.assertEqual(
            [int(call["batch_start"]) for call in resumed_runner.stage_calls(STAGE_HOOKS_WRITING)],
            [1, 6],
        )

    def test_script_batch_local_validation_auto_repairs_duplicate_episode_headings(self) -> None:
        state, payload, variables = self._state_and_payload(5)
        settings.fastgpt_stage_format_retry_limit = 3
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_SCRIPT_WRITING: [
                    {
                        BATCH_SCRIPT: "\n\n".join(
                            [
                                "第1集：\n场景一：第1集正文",
                                "第1集：\n场景一：重复的第1集正文",
                                "第2集：\n场景一：第2集正文",
                                "第3集：\n场景一：第3集正文",
                                "第4集：\n场景一：第4集正文",
                            ]
                        )
                    },
                    {
                        BATCH_SCRIPT: "\n\n".join(
                            [
                                "第1集：\n场景一：第1集正文",
                                "第1集：\n场景一：重复的第1集正文",
                                "第2集：\n场景一：第2集正文",
                                "第3集：\n场景一：第3集正文",
                                "第4集：\n场景一：第4集正文",
                            ]
                        )
                    },
                    {
                        BATCH_SCRIPT: "\n\n".join(
                            [
                                "第1集：\n场景一：第1集正文",
                                "第1集：\n场景一：重复的第1集正文",
                                "第2集：\n场景一：第2集正文",
                                "第3集：\n场景一：第3集正文",
                                "第4集：\n场景一：第4集正文",
                            ]
                        )
                    },
                ]
            }
        )

        with self.assertLogs(flow.logger.name, level="WARNING") as logs:
            flow._run_batched_generation(state, runner, payload, variables)

        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_WRITING)), 4)
        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 0)
        self.assertEqual(len(runner.memory_calls()), 1)
        self.assertIn("第5集", str(variables.get(ALL_SCRIPT, "") or ""))
        self.assertTrue(any("script_auto_repair" in item for item in logs.output))

    def test_final_guard_rejects_duplicate_hook_episodes(self) -> None:
        variables = self._base_variables(10)
        variables[ALL_HOOKS] = {
            "batch_meta": {"start_episode": 1, "end_episode": 10},
            "global_hook_engine": {"batch_label": "1-10"},
            "episodes": [
                {"episode": 1, "hook": "第1集钩子-A"},
                {"episode": 1, "hook": "第1集钩子-B"},
                {"episode": 2, "hook": "第2集钩子"},
                {"episode": 3, "hook": "第3集钩子"},
                {"episode": 4, "hook": "第4集钩子"},
                {"episode": 5, "hook": "第5集钩子"},
                {"episode": 6, "hook": "第6集钩子"},
                {"episode": 7, "hook": "第7集钩子"},
                {"episode": 8, "hook": "第8集钩子"},
                {"episode": 9, "hook": "第9集钩子"},
                {"episode": 10, "hook": "第10集钩子"},
            ],
        }
        variables[ALL_DIALOGUES] = flow.merge_batch_object(
            _dialogue_batch([1, 2, 3, 4, 5]),
            _dialogue_batch([6, 7, 8, 9, 10]),
        )
        variables[ALL_SCRIPT] = _script_batch_text([1, 2, 3, 4, 5]) + "\n\n" + _script_batch_text(
            [6, 7, 8, 9, 10]
        )
        payload = _workflow_input(10)

        with self.assertRaisesRegex(ValueError, "开头冲突钩子存在重复集"):
            flow._ensure_complete_batched_outputs_before_final(payload, variables)


    def test_script_write_stores_current_batch_var_and_review_var(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        runner = _PhaseRecordingRunner()

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertIn("1", str(variables.get(SCRIPT_CURRENT_VAR) or ""))
        self.assertIn("passed", str(variables.get(SCRIPT_REVIEW_OUTPUT_VAR) or ""))
        self.assertIn("1", str(variables.get(ALL_SCRIPT) or ""))

    def test_script_review_failure_runs_revise_then_reviews_again(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        runner = _PhaseRecordingRunner(
            review_sequences={STAGE_SCRIPT_REVIEW: [False, True]}
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 1)
        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REVIEW)), 2)

    def test_script_review_runtime_messages_increment_review_rounds(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        state.runtime = _RuntimeSpy()
        runner = _PhaseRecordingRunner(
            review_sequences={STAGE_SCRIPT_REVIEW: [False, True]}
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        review_messages = [
            item["message"]
            for item in state.runtime.stage_messages
            if item["stage_key"] == STAGE_SCRIPT_REVIEW
        ]
        rewrite_messages = [
            item["message"]
            for item in state.runtime.stage_messages
            if item["stage_key"] == STAGE_SCRIPT_REWRITE
        ]
        self.assertIn("正在审核剧本正文：第 1-5 集，第 1/10 轮", review_messages)
        self.assertIn("正在审核剧本正文：第 1-5 集，第 2/10 轮", review_messages)
        self.assertIn("正在修订剧本正文：第 1-5 集，第 1/10 轮", rewrite_messages)

    def test_script_review_unparseable_counts_as_failure(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        settings.fastgpt_stage_format_retry_limit = 3
        runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_SCRIPT_REVIEW: [
                    ValueError("not json"),
                    ValueError("still not json"),
                    ValueError("again not json"),
                ]
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "script_review|审核输出未通过格式契约校验|not json|1-5",
        ):
            flow._run_all_script_batches(
                state,
                runner,
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REVIEW)), 3)
        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 0)
        self.assertEqual(str(variables.get(ALL_SCRIPT, "") or "").strip(), "")

    def test_script_review_passed_with_blocking_issues_revises(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_SCRIPT_REVIEW: [
                    {
                        "passed": True,
                        "rewrite_required": False,
                        "blocking_issues": ["still broken"],
                        "non_blocking_issues": [],
                    },
                    True,
                ]
            }
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 1)

    def test_script_revise_output_that_is_not_script_is_rejected(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        settings.fastgpt_stage_review_revise_max_loops = 2
        settings.fastgpt_stage_format_retry_limit = 3
        runner = _PhaseRecordingRunner(
            review_sequences={STAGE_SCRIPT_REVIEW: [False, True]},
            stage_outputs={
                STAGE_SCRIPT_REWRITE: [
                    {
                        BATCH_SCRIPT: json.dumps(
                            {"passed": True, "blocking_issues": []},
                            ensure_ascii=False,
                        )
                    },
                    {
                        BATCH_SCRIPT: json.dumps(
                            {"passed": True, "blocking_issues": []},
                            ensure_ascii=False,
                        )
                    },
                    {
                        BATCH_SCRIPT: json.dumps(
                            {"passed": True, "blocking_issues": []},
                            ensure_ascii=False,
                        )
                    },
                ]
            },
        )

        with self.assertRaisesRegex(
            ValueError,
            "script_rewrite|输出未通过正文批次校验|script batch 1-5",
        ):
            flow._run_all_script_batches(
                state,
                runner,
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

        self.assertEqual(str(variables.get(ALL_SCRIPT, "") or "").strip(), "")
        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 3)

    def test_script_out_of_range_and_missing_episode_are_rejected(self) -> None:
        issues = flow._validate_script_batch_output(
            _script_batch_text([1, 2, 3, 4, 6]),
            batch=BatchWindow(start_episode=1, end_episode=5),
        )
        joined = "\n".join(issues)
        self.assertIn("out-of-window", joined)
        self.assertIn("missing", joined)

    def test_script_auto_repair_helpers_detect_missing_and_recoverable_errors(self) -> None:
        failure_reasons = [
            "script batch 46-50 is missing episodes: 第47-50集",
            "script episode 47 is missing a scene heading such as 47-1",
        ]

        self.assertEqual(flow._detect_missing_episodes(failure_reasons), [47, 48, 49, 50])
        self.assertTrue(flow.is_recoverable_script_error(failure_reasons))

    def test_script_write_missing_episodes_auto_repairs_by_appending(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_SCRIPT_WRITING: [
                    {BATCH_SCRIPT: _script_batch_text([1, 2, 3])},
                    {BATCH_SCRIPT: _script_batch_text([1, 2, 3])},
                    {BATCH_SCRIPT: _script_batch_text([1, 2, 3])},
                    {BATCH_SCRIPT: _script_batch_text([4, 5])},
                ]
            }
        )

        with self.assertLogs(flow.logger.name, level="WARNING") as logs:
            flow._run_all_script_batches(
                state,
                runner,
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_WRITING)), 4)
        self.assertEqual(runner.stage_calls(STAGE_SCRIPT_WRITING)[-1]["plan_episodes"], [4, 5])
        self.assertIn("第1集", str(variables.get(ALL_SCRIPT) or ""))
        self.assertIn("第5集", str(variables.get(ALL_SCRIPT) or ""))
        self.assertTrue(any("script_auto_repair" in item and "补写" in item for item in logs.output))

    def test_script_write_missing_scene_heading_auto_repairs_with_structure_rewrite(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_SCRIPT_WRITING: [
                    {BATCH_SCRIPT: _script_batch_text_without_scene_headings([1, 2, 3, 4, 5])},
                    {BATCH_SCRIPT: _script_batch_text_without_scene_headings([1, 2, 3, 4, 5])},
                    {BATCH_SCRIPT: _script_batch_text_without_scene_headings([1, 2, 3, 4, 5])},
                ],
                STAGE_SCRIPT_REWRITE: [
                    {BATCH_SCRIPT: _script_batch_text([1, 2, 3, 4, 5])}
                ],
            }
        )

        with self.assertLogs(flow.logger.name, level="WARNING") as logs:
            flow._run_all_script_batches(
                state,
                runner,
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 1)
        self.assertIn("1-1", str(variables.get(ALL_SCRIPT) or ""))
        self.assertTrue(any("script_auto_repair" in item and "结构修复" in item for item in logs.output))

    def test_script_write_auto_repairs_then_falls_back_to_smaller_batches(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_SCRIPT_WRITING: [
                    {BATCH_SCRIPT: _script_batch_text([1, 2, 3])},
                    {BATCH_SCRIPT: _script_batch_text([1, 2, 3])},
                    {BATCH_SCRIPT: _script_batch_text([1, 2, 3])},
                    {BATCH_SCRIPT: _script_batch_text([4])},
                    {BATCH_SCRIPT: _script_batch_text([1, 2, 3])},
                    {BATCH_SCRIPT: _script_batch_text([4, 5])},
                ],
                STAGE_SCRIPT_REWRITE: [
                    {BATCH_SCRIPT: _script_batch_text([1, 2, 3, 4])}
                ],
            }
        )

        with self.assertLogs(flow.logger.name, level="WARNING") as logs:
            flow._run_all_script_batches(
                state,
                runner,
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

        script_write_starts = [
            int(call["batch_start"])
            for call in runner.stage_calls(STAGE_SCRIPT_WRITING)
        ]
        self.assertEqual(script_write_starts, [1, 1, 1, 4, 1, 4])
        self.assertEqual(sorted(int(key) for key in variables[flow.LOCAL_SCRIPT_BATCHES].keys()), [1, 4])
        self.assertIn("第5集", str(variables.get(ALL_SCRIPT) or ""))
        self.assertTrue(any("script_auto_repair" in item and "缩小批次" in item for item in logs.output))

    def test_script_memory_failure_stops_current_batch_and_resume_replays_memory_only(self) -> None:
        previous_memory = json.dumps(
            {
                "final_hook_of_this_turn": "previous-hook",
                "must_carry_into_next_turn": ["previous-thread"],
                "appearance_continuity_summary": "previous-memory",
            },
            ensure_ascii=False,
        )
        state, payload, variables, batches = self._script_ready_state(
            5,
            variables={
                LAST_SUMMARY: previous_memory,
                flow.SCRIPT_MEMORY: previous_memory,
                SCRIPT_MEMORY_WRITE_INPUT_VAR: previous_memory,
                MEMORY_VAR: previous_memory,
            },
        )
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_SCRIPT_MEMORY: [
                    {LAST_SUMMARY: "not json"},
                    {LAST_SUMMARY: "still not json"},
                    {LAST_SUMMARY: "last not json"},
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "剧本正文 1-5 集记忆生成失败"):
            flow._run_all_script_batches(
                state,
                runner,
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

        self.assertEqual(str(variables[LAST_SUMMARY]), previous_memory)
        self.assertEqual(str(variables[flow.SCRIPT_MEMORY]), previous_memory)
        self.assertEqual(str(variables[SCRIPT_MEMORY_WRITE_INPUT_VAR]), previous_memory)
        self.assertEqual(state.get_var(MEMORY_VAR), previous_memory)
        self.assertEqual(variables[BATCH_START_EPISODE], 1)
        self.assertEqual(variables[flow.LOCAL_CURRENT_BATCH_STAGE], "script")
        self.assertIn("第1集", str(variables[ALL_SCRIPT]))
        self.assertEqual(str(variables[flow.LOCAL_COMMITTED_SCRIPT]), str(variables[ALL_SCRIPT]))
        self.assertIn("1", variables[flow.LOCAL_SCRIPT_BATCHES])
        self.assertNotIn("1", variables.get(flow.LOCAL_SUMMARY_BY_BATCH, {}))
        self.assertNotIn("1", variables.get(flow.LOCAL_APPEARANCE_MEMORY_BY_BATCH, {}))
        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_WRITING)), 1)

        resumed_runner = _PhaseRecordingRunner(
            stage_outputs={STAGE_SCRIPT_MEMORY: [{LAST_SUMMARY: _script_memory_json(label="resume-script")}]}
        )
        flow._run_all_script_batches(
            state,
            resumed_runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(resumed_runner.stage_calls(STAGE_SCRIPT_WRITING)), 0)
        self.assertEqual(len(resumed_runner.stage_calls(STAGE_SCRIPT_MEMORY)), 1)
        self.assertIn("1", variables.get(flow.LOCAL_SUMMARY_BY_BATCH, {}))
        self.assertIn("1", variables.get(flow.LOCAL_APPEARANCE_MEMORY_BY_BATCH, {}))

    def test_script_resume_does_not_rewrite_committed_batch(self) -> None:
        committed = _script_batch_text([1, 2, 3, 4, 5])
        committed_map = flow._extract_script_episode_map(
            committed,
            BatchWindow(start_episode=1, end_episode=5),
        )
        state, payload, variables, batches = self._script_ready_state(
            10,
            variables={
                flow.LOCAL_SCRIPT_BATCHES: {"1": committed},
                flow.LOCAL_SUMMARY_BY_BATCH: {
                    "1": json.dumps(
                        {
                            "final_hook_of_this_turn": "",
                            "must_carry_into_next_turn": [],
                            "appearance_continuity_summary": "",
                        }
                    )
                },
                flow.LOCAL_SCRIPT_EPISODES: flow._string_keyed_batch_map(committed_map),
            },
        )
        runner = _PhaseRecordingRunner()

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(
            [int(call["batch_start"]) for call in runner.stage_calls(STAGE_SCRIPT_WRITING)],
            [6],
        )

    def test_script_resume_with_missing_appearance_memory_replays_memory_before_next_batch(self) -> None:
        committed = _script_batch_text([1, 2, 3, 4, 5])
        committed_map = flow._extract_script_episode_map(
            committed,
            BatchWindow(start_episode=1, end_episode=5),
        )
        state, payload, variables, batches = self._script_ready_state(
            10,
            variables={
                flow.LOCAL_SCRIPT_BATCHES: {"1": committed},
                flow.LOCAL_SCRIPT_EPISODES: flow._string_keyed_batch_map(committed_map),
                flow.LOCAL_SUMMARY_BY_BATCH: {"1": _script_memory_json(label="batch-1")},
                flow.LOCAL_CURRENT_BATCH_STAGE: "script",
                BATCH_START_EPISODE: 1,
            },
        )
        runner = _PhaseRecordingRunner(
            stage_outputs={STAGE_SCRIPT_MEMORY: [{LAST_SUMMARY: _script_memory_json(label="restored-batch-1")}]}
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(
            [int(call["batch_start"]) for call in runner.stage_calls(STAGE_SCRIPT_WRITING)],
            [6],
        )
        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_MEMORY)), 2)

    def test_review_parser_accepts_alias_wrappers_and_rejects_natural_language(self) -> None:
        passed = {
            "passed": True,
            "rewrite_required": False,
            "blocking_issues": [],
            "non_blocking_issues": [],
        }
        for alias in (
            HOOK_REVIEW_OUTPUT_VAR,
            DIALOGUE_REVIEW_WORKFLOW_VAR,
            DIALOGUE_REVIEW_OUTPUT_VAR,
            DIALOGUE_REVIEW_LEGACY_VAR,
            SCRIPT_REVIEW_WRITE_VAR,
            SCRIPT_REVIEW_OUTPUT_VAR,
        ):
            decision = flow.parse_review_result({alias: json.dumps(passed)})
            self.assertTrue(decision.passed, alias)
            self.assertFalse(decision.rewrite_required, alias)

        blocked = flow.parse_review_result(
            {
                SCRIPT_REVIEW_OUTPUT_VAR: json.dumps(
                    {
                        "passed": True,
                        "rewrite_required": False,
                        "blocking_issues": ["bad"],
                        "non_blocking_issues": [],
                    }
                )
            }
        )
        self.assertFalse(blocked.passed)
        self.assertTrue(blocked.rewrite_required)

        natural = flow.parse_review_result("looks good overall")
        self.assertFalse(natural.passed)
        self.assertTrue(natural.rewrite_required)

    def test_review_parser_forces_rewrite_false_schema_and_type_errors(self) -> None:
        decision = flow.parse_review_result(
            {
                DIALOGUE_REVIEW_OUTPUT_VAR: json.dumps(
                    {
                        "passed": "true",
                        "rewrite_required": False,
                        "blocking_issues": [],
                        "non_blocking_issues": [],
                    }
                )
            }
        )
        self.assertFalse(decision.passed)
        self.assertTrue(decision.rewrite_required)
        self.assertIn("must be boolean", "\n".join(decision.blocking_issues))

        rewrite_required_type_error = flow.parse_review_result(
            {
                SCRIPT_REVIEW_OUTPUT_VAR: json.dumps(
                    {
                        "passed": False,
                        "rewrite_required": "false",
                        "blocking_issues": [],
                        "non_blocking_issues": [],
                    }
                )
            }
        )
        self.assertFalse(rewrite_required_type_error.passed)
        self.assertTrue(rewrite_required_type_error.rewrite_required)
        self.assertIn("must be boolean", "\n".join(rewrite_required_type_error.blocking_issues))

        blocking_issue_type_error = flow.parse_review_result(
            {
                SCRIPT_REVIEW_OUTPUT_VAR: json.dumps(
                    {
                        "passed": False,
                        "rewrite_required": True,
                        "blocking_issues": "not-a-list",
                        "non_blocking_issues": [],
                    }
                )
            }
        )
        self.assertFalse(blocking_issue_type_error.passed)
        self.assertTrue(blocking_issue_type_error.rewrite_required)
        self.assertIn("must be array", "\n".join(blocking_issue_type_error.blocking_issues))

        with self.assertLogs(flow.logger.name, level="WARNING") as logs:
            forced = flow.parse_review_result(
                {
                    SCRIPT_REVIEW_OUTPUT_VAR: json.dumps(
                        {
                            "passed": False,
                            "rewrite_required": False,
                            "blocking_issues": ["still broken"],
                            "non_blocking_issues": [],
                        }
                    )
                }
            )
        self.assertFalse(forced.passed)
        self.assertTrue(forced.rewrite_required)
        self.assertTrue(any("forcing revision" in entry for entry in logs.output))

    def test_review_parser_non_blocking_does_not_block_but_blocking_still_forces_failure(self) -> None:
        passed_with_non_blocking = flow.parse_review_result(
            {
                SCRIPT_REVIEW_OUTPUT_VAR: json.dumps(
                    {
                        "passed": True,
                        "rewrite_required": False,
                        "summary": "整体通过",
                        "blocking_issues": [],
                        "non_blocking_issues": ["台词还能更狠一点"],
                    }
                )
            }
        )
        self.assertTrue(passed_with_non_blocking.passed)
        self.assertFalse(passed_with_non_blocking.rewrite_required)
        self.assertEqual(
            passed_with_non_blocking.non_blocking_issues,
            ["台词还能更狠一点"],
        )

        for alias in (HOOK_REVIEW_OUTPUT_VAR, DIALOGUE_REVIEW_OUTPUT_VAR):
            with self.subTest(alias=alias):
                decision = flow.parse_review_result(
                    {
                        alias: json.dumps(
                            {
                                "passed": True,
                                "rewrite_required": False,
                                "summary": "通过",
                                "blocking_issues": [],
                                "non_blocking_issues": ["可优化"],
                            }
                        )
                    }
                )
                self.assertTrue(decision.passed)
                self.assertFalse(decision.rewrite_required)

        blocked = flow.parse_review_result(
            {
                SCRIPT_REVIEW_OUTPUT_VAR: json.dumps(
                    {
                        "passed": True,
                        "rewrite_required": False,
                        "summary": "看似通过",
                        "blocking_issues": ["连续性断裂"],
                        "non_blocking_issues": ["措辞可更简洁"],
                    }
                )
            }
        )
        self.assertFalse(blocked.passed)
        self.assertTrue(blocked.rewrite_required)
        self.assertIn("连续性断裂", blocked.blocking_issues)

    def test_hook_alias_write_review_and_memory_output_mirror(self) -> None:
        state, payload, variables = self._state_and_payload(5)
        batches = list(iter_episode_batches(5, batch_size=5))
        memory_json = json.dumps(
            {
                "final_hook_of_this_turn": "hook end",
                "must_carry_into_next_turn": [],
                "appearance_alias_continuity_summary": "alias ok",
            },
            ensure_ascii=False,
        )
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_HOOKS_WRITING: [{HOOK_CURRENT_WRITE_VAR: _hook_batch([1, 2, 3, 4, 5])}],
                STAGE_HOOK_MEMORY: [{HOOK_MEMORY_OUTPUT_VAR: memory_json}],
            }
        )

        flow._run_all_hook_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(_episode_numbers_from_object(variables[BATCH_HOOKS]), [1, 2, 3, 4, 5])
        self.assertEqual(_episode_numbers_from_object(variables[HOOK_CURRENT_WRITE_VAR]), [1, 2, 3, 4, 5])
        self.assertEqual(_episode_numbers_from_object(variables[HOOK_CURRENT_VAR]), [1, 2, 3, 4, 5])
        review_call = runner.stage_calls(STAGE_HOOKS_REVIEW)[0]
        self.assertEqual(review_call["hook_write_alias_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(review_call["hook_review_alias_episodes"], [1, 2, 3, 4, 5])
        expected_memory = json.loads(memory_json)
        self.assertEqual(json.loads(str(variables[flow.HOOK_MEMORY])), expected_memory)
        self.assertEqual(json.loads(str(variables[HOOK_MEMORY_INPUT_VAR])), expected_memory)
        self.assertEqual(json.loads(str(variables[HOOK_MEMORY_REVIEW_VAR])), expected_memory)
        self.assertEqual(json.loads(str(variables[HOOK_MEMORY_REVISE_VAR])), expected_memory)
        self.assertEqual(json.loads(str(variables[HOOK_MEMORY_OUTPUT_VAR])), expected_memory)

    def test_hook_review_and_rewrite_alias_paths_are_respected(self) -> None:
        state, payload, variables = self._state_and_payload(5)
        batches = list(iter_episode_batches(5, batch_size=5))
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_HOOKS_WRITING: [{HOOK_CURRENT_WRITE_VAR: _hook_batch([1, 2, 3, 4, 5])}],
                STAGE_HOOKS_REVIEW: [
                    {
                        HOOK_REVIEW_OUTPUT_VAR: json.dumps(
                            {
                                "passed": False,
                                "rewrite_required": True,
                                "blocking_issues": ["revise"],
                                "non_blocking_issues": [],
                            },
                            ensure_ascii=False,
                        )
                    },
                    {
                        HOOK_REVIEW_OUTPUT_VAR: json.dumps(
                            {
                                "passed": True,
                                "rewrite_required": False,
                                "blocking_issues": [],
                                "non_blocking_issues": [],
                            },
                            ensure_ascii=False,
                        )
                    },
                ],
                STAGE_HOOKS_REWRITE: [{HOOK_CURRENT_VAR: _hook_batch([1, 2, 3, 4, 5])}],
            }
        )

        flow._run_all_hook_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(runner.stage_calls(STAGE_HOOKS_REWRITE)), 1)
        self.assertEqual(_episode_numbers_from_object(variables[HOOK_CURRENT_WRITE_VAR]), [1, 2, 3, 4, 5])
        self.assertEqual(_episode_numbers_from_object(variables[HOOK_CURRENT_VAR]), [1, 2, 3, 4, 5])
        self.assertIn('"passed": true', str(variables[HOOK_REVIEW_OUTPUT_VAR]).lower())

    def test_hook_validation_accepts_json_string_and_rejects_review_memory_and_bad_meta(self) -> None:
        batch = BatchWindow(start_episode=1, end_episode=5)
        good = json.dumps({BATCH_HOOKS: _hook_batch([1, 2, 3, 4, 5])}, ensure_ascii=False)
        self.assertEqual(flow.validate_batch_hooks(good, batch), [])

        bad_meta = _hook_batch([1, 2, 3, 4, 5])
        bad_meta["batch_meta"]["start_episode"] = 2
        issues = flow.validate_batch_hooks(json.dumps({BATCH_HOOKS: bad_meta}, ensure_ascii=False), batch)
        self.assertIn("batch_meta.start_episode", "\n".join(issues))

        review_json = json.dumps(
            {"passed": True, "rewrite_required": False, "blocking_issues": [], "non_blocking_issues": []},
            ensure_ascii=False,
        )
        memory_json = json.dumps(
            {
                "final_hook_of_this_turn": "end",
                "must_carry_into_next_turn": [],
                "appearance_alias_continuity_summary": "",
            },
            ensure_ascii=False,
        )
        self.assertTrue(flow.validate_batch_hooks(review_json, batch))
        self.assertTrue(flow.validate_batch_hooks(memory_json, batch))
        self.assertTrue(flow.validate_batch_hooks("普通自然语言说明", batch))

    def test_hook_local_validation_rejects_missing_out_of_range_and_duplicate(self) -> None:
        batch = BatchWindow(start_episode=1, end_episode=5)
        bad_missing = _hook_batch([1, 2, 3, 4])
        bad_out = _hook_batch([1, 2, 3, 4, 6])
        bad_dup = _hook_batch([1, 1, 2, 3, 4])
        self.assertTrue(flow.validate_batch_hooks(bad_missing, batch))
        self.assertTrue(flow.validate_batch_hooks(bad_out, batch))
        self.assertTrue(flow.validate_batch_hooks(bad_dup, batch))

    def test_dialogue_alias_write_review_rewrite_and_memory_mirror(self) -> None:
        state, payload, variables = self._state_and_payload(
            5,
            variables={ALL_HOOKS: _hook_batch([1, 2, 3, 4, 5])},
        )
        batches = list(iter_episode_batches(5, batch_size=5))
        memory_json = json.dumps(
            {
                "dialogue_voice_summary": "voice ok",
                "must_carry_into_next_turn": [],
                "alias_usage_continuity": "alias ok",
            },
            ensure_ascii=False,
        )
        runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_DIALOGUES_REVIEW: [
                    {
                        DIALOGUE_REVIEW_WORKFLOW_VAR: json.dumps(
                            {
                                "passed": False,
                                "rewrite_required": True,
                                "blocking_issues": ["revise"],
                                "non_blocking_issues": [],
                            },
                            ensure_ascii=False,
                        )
                    },
                    {
                        DIALOGUE_REVIEW_WORKFLOW_VAR: json.dumps(
                            {
                                "passed": True,
                                "rewrite_required": False,
                                "blocking_issues": [],
                                "non_blocking_issues": [],
                            },
                            ensure_ascii=False,
                        )
                    },
                ]
            },
            stage_outputs={
                STAGE_DIALOGUES_WRITING: [
                    {DIALOGUE_CURRENT_WRITE_VAR: _dialogue_batch([1, 2, 3, 4, 5])}
                ],
                STAGE_DIALOGUES_REWRITE: [
                    {DIALOGUE_CURRENT_WORKFLOW_VAR: _dialogue_batch([1, 2, 3, 4, 5])}
                ],
                STAGE_DIALOGUE_MEMORY: [{DIALOGUE_MEMORY_OUTPUT_VAR: memory_json}],
            }
        )

        flow._run_all_dialogue_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(_episode_numbers_from_object(variables[BATCH_DIALOGUES]), [1, 2, 3, 4, 5])
        self.assertEqual(_episode_numbers_from_object(variables[DIALOGUE_CURRENT_WRITE_VAR]), [1, 2, 3, 4, 5])
        self.assertEqual(_episode_numbers_from_object(variables[DIALOGUE_CURRENT_WORKFLOW_VAR]), [1, 2, 3, 4, 5])
        self.assertEqual(_episode_numbers_from_object(variables[DIALOGUE_CURRENT_VAR]), [1, 2, 3, 4, 5])
        review_call = runner.stage_calls(STAGE_DIALOGUES_REVIEW)[0]
        self.assertEqual(review_call["dialogue_write_alias_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(review_call["dialogue_workflow_alias_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(review_call["dialogue_legacy_alias_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(len(runner.stage_calls(STAGE_DIALOGUES_REWRITE)), 1)
        self.assertIn('"passed": true', str(variables[DIALOGUE_REVIEW_OUTPUT_VAR]).lower())
        self.assertEqual(str(variables[DIALOGUE_REVIEW_WORKFLOW_VAR]), str(variables[DIALOGUE_REVIEW_OUTPUT_VAR]))
        self.assertEqual(str(variables[DIALOGUE_REVIEW_LEGACY_VAR]), str(variables[DIALOGUE_REVIEW_OUTPUT_VAR]))
        expected_memory = json.loads(memory_json)
        self.assertEqual(json.loads(str(variables[flow.DIALOGUE_MEMORY])), expected_memory)
        self.assertEqual(json.loads(str(variables[DIALOGUE_MEMORY_INPUT_VAR])), expected_memory)
        self.assertEqual(json.loads(str(variables[DIALOGUE_MEMORY_OUTPUT_VAR])), expected_memory)
        self.assertEqual(json.loads(str(variables[DIALOGUE_MEMORY_SEARCH_VAR])), expected_memory)
        self.assertEqual(json.loads(str(variables[DIALOGUE_MEMORY_LEGACY_OUTPUT_VAR])), expected_memory)

        bad_revise = {
            "dialogue_voice_summary": "memory",
            "must_carry_into_next_turn": [],
            "alias_usage_continuity": "alias",
        }
        issues = flow.validate_batch_dialogues(bad_revise, BatchWindow(start_episode=1, end_episode=5))
        self.assertIn("角色对话修订 workflow 输出契约错误", "\n".join(issues))

    def test_dialogue_write_json_string_wrapper_is_accepted(self) -> None:
        state, payload, variables = self._state_and_payload(
            5,
            variables={ALL_HOOKS: _hook_batch([1, 2, 3, 4, 5])},
        )
        batches = list(iter_episode_batches(5, batch_size=5))
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_DIALOGUES_WRITING: [
                    {
                        DIALOGUE_CURRENT_WRITE_VAR: json.dumps(
                            {BATCH_DIALOGUES: _dialogue_batch([1, 2, 3, 4, 5])},
                            ensure_ascii=False,
                        )
                    }
                ]
            }
        )

        flow._run_all_dialogue_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(_episode_numbers_from_object(variables[BATCH_DIALOGUES]), [1, 2, 3, 4, 5])
        self.assertEqual(_episode_numbers_from_object(variables[DIALOGUE_CURRENT_WORKFLOW_VAR]), [1, 2, 3, 4, 5])

    def test_dialogue_rewrite_json_string_wrapper_is_accepted(self) -> None:
        state, payload, variables = self._state_and_payload(
            5,
            variables={ALL_HOOKS: _hook_batch([1, 2, 3, 4, 5])},
        )
        batches = list(iter_episode_batches(5, batch_size=5))
        runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_DIALOGUES_REVIEW: [False, True],
            },
            stage_outputs={
                STAGE_DIALOGUES_REWRITE: [
                    {
                        DIALOGUE_CURRENT_WORKFLOW_VAR: json.dumps(
                            {BATCH_DIALOGUES: _dialogue_batch([1, 2, 3, 4, 5])},
                            ensure_ascii=False,
                        )
                    }
                ]
            },
        )

        flow._run_all_dialogue_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(runner.stage_calls(STAGE_DIALOGUES_REWRITE)), 1)
        self.assertEqual(_episode_numbers_from_object(variables[BATCH_DIALOGUES]), [1, 2, 3, 4, 5])
        self.assertEqual(_episode_numbers_from_object(variables[DIALOGUE_CURRENT_WORKFLOW_VAR]), [1, 2, 3, 4, 5])
        self.assertEqual(_episode_numbers_from_object(variables[DIALOGUE_CURRENT_WRITE_VAR]), [1, 2, 3, 4, 5])

    def test_dialogue_review_alias_variants_pass_without_spurious_hookcontent_warning(self) -> None:
        state, payload, variables = self._state_and_payload(
            5,
            variables={ALL_HOOKS: _hook_batch([1, 2, 3, 4, 5])},
        )
        batches = list(iter_episode_batches(5, batch_size=5))
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_DIALOGUES_WRITING: [{DIALOGUE_CURRENT_WRITE_VAR: _dialogue_batch([1, 2, 3, 4, 5])}],
                STAGE_DIALOGUES_REVIEW: [
                    {
                        DIALOGUE_REVIEW_OUTPUT_VAR: json.dumps(
                            {
                                "passed": False,
                                "rewrite_required": True,
                                "blocking_issues": ["revise"],
                                "non_blocking_issues": [],
                            },
                            ensure_ascii=False,
                        )
                    },
                    {
                        DIALOGUE_REVIEW_LEGACY_VAR: json.dumps(
                            {
                                "passed": True,
                                "rewrite_required": False,
                                "blocking_issues": [],
                                "non_blocking_issues": [],
                            },
                            ensure_ascii=False,
                        )
                    },
                ],
            }
        )

        flow._run_all_dialogue_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(runner.stage_calls(STAGE_DIALOGUES_REWRITE)), 1)
        self.assertIn('"passed": true', str(variables[DIALOGUE_REVIEW_OUTPUT_VAR]).lower())
        self.assertEqual(str(variables[DIALOGUE_REVIEW_WORKFLOW_VAR]), str(variables[DIALOGUE_REVIEW_OUTPUT_VAR]))
        self.assertEqual(str(variables[DIALOGUE_REVIEW_LEGACY_VAR]), str(variables[DIALOGUE_REVIEW_OUTPUT_VAR]))
        artifact = state.get_output(STAGE_DIALOGUES_REWRITE, "contract_guard", {})
        self.assertFalse(any("hookContent" in item for item in list(artifact.get("workflow_warnings") or [])))

    def test_hook_review_receives_story_outline_context(self) -> None:
        state, payload, variables = self._state_and_payload(5)
        batches = list(iter_episode_batches(5, batch_size=5))
        runner = _PhaseRecordingRunner()

        flow._run_all_hook_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        review_call = runner.stage_calls(STAGE_HOOKS_REVIEW)[0]
        self.assertEqual(review_call["story_outline_text"], "测试大纲")

    def test_dialogue_validation_accepts_nested_and_json_string_and_legacy_flat(self) -> None:
        batch = BatchWindow(start_episode=1, end_episode=5)
        good = json.dumps({BATCH_DIALOGUES: _dialogue_batch([1, 2, 3, 4, 5])}, ensure_ascii=False)
        self.assertEqual(flow.validate_batch_dialogues(good, batch), [])
        nested_string = {
            BATCH_DIALOGUES: json.dumps(_dialogue_batch([1, 2, 3, 4, 5]), ensure_ascii=False)
        }
        self.assertEqual(flow.validate_batch_dialogues(nested_string, batch), [])
        double_nested_string = json.dumps(
            {BATCH_DIALOGUES: json.dumps({BATCH_DIALOGUES: _dialogue_batch([1, 2, 3, 4, 5])}, ensure_ascii=False)},
            ensure_ascii=False,
        )
        self.assertEqual(flow.validate_batch_dialogues(double_nested_string, batch), [])
        self.assertEqual(
            flow.validate_batch_dialogues(_dialogue_batch_flat_legacy([1, 2, 3, 4, 5]), batch),
            [],
        )

    def test_dialogue_validation_rejects_review_memory_natural_and_bad_nested_lines(self) -> None:
        batch = BatchWindow(start_episode=1, end_episode=5)

        review_json = json.dumps(
            {"passed": True, "rewrite_required": False, "blocking_issues": [], "non_blocking_issues": []},
            ensure_ascii=False,
        )
        memory_json = json.dumps(
            {
                "dialogue_voice_summary": "voice",
                "must_carry_into_next_turn": [],
                "alias_usage_continuity": "",
            },
            ensure_ascii=False,
        )
        self.assertTrue(flow.validate_batch_dialogues(review_json, batch))
        self.assertTrue(flow.validate_batch_dialogues(memory_json, batch))
        self.assertTrue(flow.validate_batch_dialogues("普通自然语言说明", batch))
        self.assertTrue(flow.validate_batch_dialogues("### 修订说明\n- 已修复如下问题", batch))
        self.assertTrue(
            flow.validate_batch_dialogues(
                json.dumps({"rewrite_orders": ["请补强角色对白"]}, ensure_ascii=False),
                batch,
            )
        )

        bad_meta = _dialogue_batch([1, 2, 3, 4, 5])
        bad_meta["batch_meta"]["end_episode"] = 6
        issues = flow.validate_batch_dialogues(json.dumps({BATCH_DIALOGUES: bad_meta}, ensure_ascii=False), batch)
        self.assertIn("batch_meta.end_episode", "\n".join(issues))

        bad_empty_blocks = _dialogue_batch([1, 2, 3, 4, 5])
        bad_empty_blocks["episode_dialogue_blocks"][0]["dialogue_blocks"] = []
        self.assertTrue(flow.validate_batch_dialogues(bad_empty_blocks, batch))

        bad_empty_speaker = _dialogue_batch([1, 2, 3, 4, 5])
        bad_empty_speaker["episode_dialogue_blocks"][0]["dialogue_blocks"][0]["dialogues"][0]["speaker"] = ""
        self.assertTrue(flow.validate_batch_dialogues(bad_empty_speaker, batch))

        bad_empty_line = _dialogue_batch([1, 2, 3, 4, 5])
        bad_empty_line["episode_dialogue_blocks"][0]["dialogue_blocks"][0]["dialogues"][0]["line"] = ""
        self.assertTrue(flow.validate_batch_dialogues(bad_empty_line, batch))

    def test_dialogue_bad_batch_is_rejected(self) -> None:
        batch = BatchWindow(start_episode=1, end_episode=5)
        bad_missing = _dialogue_batch([1, 2, 3, 4])
        bad_out = _dialogue_batch([1, 2, 3, 4, 6])
        bad_dup = _dialogue_batch([1, 1, 2, 3, 4])
        self.assertTrue(flow.validate_batch_dialogues(bad_missing, batch))
        self.assertTrue(flow.validate_batch_dialogues(bad_out, batch))
        self.assertTrue(flow.validate_batch_dialogues(bad_dup, batch))

    def test_dialogue_rewrite_invalid_outputs_are_rejected(self) -> None:
        invalid_rewrite_outputs = [
            "### 修订说明\n- 这里只给补丁说明，不给完整 batch_dialogues",
            json.dumps(
                {
                    "passed": False,
                    "rewrite_required": True,
                    "blocking_issues": ["still bad"],
                    "non_blocking_issues": [],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "dialogue_voice_summary": "voice",
                    "must_carry_into_next_turn": [],
                    "alias_usage_continuity": "keep alias stable",
                },
                ensure_ascii=False,
            ),
        ]
        for invalid_output in invalid_rewrite_outputs:
            with self.subTest(invalid_output=invalid_output[:40]):
                state, payload, variables = self._state_and_payload(
                    5,
                    variables={ALL_HOOKS: _hook_batch([1, 2, 3, 4, 5])},
                )
                batches = list(iter_episode_batches(5, batch_size=5))
                runner = _PhaseRecordingRunner(
                    review_sequences={STAGE_DIALOGUES_REVIEW: [False]},
                    stage_outputs={
                        STAGE_DIALOGUES_REWRITE: [
                            {DIALOGUE_CURRENT_WORKFLOW_VAR: invalid_output},
                            {DIALOGUE_CURRENT_WORKFLOW_VAR: invalid_output},
                            {DIALOGUE_CURRENT_WORKFLOW_VAR: invalid_output},
                        ]
                    },
                )

                with self.assertRaisesRegex(
                    ValueError,
                    "dialogues_rewrite|角色对白修订|dialogue batch 1-5",
                ):
                    flow._run_all_dialogue_batches(
                        state,
                        runner,
                        payload,
                        variables,
                        batches=batches,
                        normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                        episode_alias_plan=None,
                        rewrite_from_stage="",
                    )

                self.assertEqual(len(runner.stage_calls(STAGE_DIALOGUES_REWRITE)), 3)
                self.assertTrue(not variables.get(ALL_DIALOGUES))

    def test_dialogue_rewrite_receives_current_batch_hook_slice_not_full_all_hooks(self) -> None:
        state, payload, variables = self._state_and_payload(
            10,
            variables={
                ALL_HOOKS: flow.merge_batch_object(
                    _hook_batch([1, 2, 3, 4, 5]),
                    _hook_batch([6, 7, 8, 9, 10]),
                )
            },
        )
        batches = list(iter_episode_batches(10, batch_size=5))
        runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_DIALOGUES_REVIEW: [False, True],
            }
        )

        flow._run_all_dialogue_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        rewrite_call = runner.stage_calls(STAGE_DIALOGUES_REWRITE)[0]
        self.assertEqual(rewrite_call["hooks_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(rewrite_call["dialogue_hook_rewrite_alias_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(rewrite_call["dialogue_hook_prompt_alias_episodes"], [1, 2, 3, 4, 5])

    def test_hook_stage_uses_compact_context_and_current_batch_alias_plan(self) -> None:
        alias_plan = _episode_alias_plan(10)
        state, payload, variables = self._state_and_payload(
            10,
            variables={
                CHARACTERS: _rich_characters_text(),
                SCENES: _rich_scenes_text(),
                EPISODE_ALIAS_PLAN: alias_plan,
            },
        )
        original_characters = str(variables[CHARACTERS])
        original_scenes = str(variables[SCENES])
        original_appearance_mapping = json.dumps(
            variables[APPEARANCE_MAPPING],
            ensure_ascii=False,
        )
        batches = list(iter_episode_batches(10, batch_size=5))
        runner = _PhaseRecordingRunner()

        flow._run_all_hook_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=alias_plan,
            rewrite_from_stage="",
        )

        write_call = runner.stage_calls(STAGE_HOOKS_WRITING)[0]
        self.assertEqual(write_call["plan_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(write_call["appearance_plan_episodes"], [1, 2, 3, 4, 5])
        self.assertIn('"core_motivation"', write_call["characters_text"])
        self.assertNotIn("family_background", write_call["characters_text"])
        self.assertNotIn("dramatic_function", write_call["characters_text"])
        self.assertIn('"scene_name":"玻璃会议室"', write_call["scenes_text"])
        self.assertNotIn("outfit_requirements", write_call["scenes_text"])
        self.assertEqual(str(variables[CHARACTERS]), original_characters)
        self.assertEqual(str(variables[SCENES]), original_scenes)
        self.assertEqual(
            json.dumps(variables[APPEARANCE_MAPPING], ensure_ascii=False),
            original_appearance_mapping,
        )

    def test_dialogue_stage_uses_compact_context_and_current_batch_alias_plan(self) -> None:
        alias_plan = _episode_alias_plan(10)
        state, payload, variables = self._state_and_payload(
            10,
            variables={
                ALL_HOOKS: flow.merge_batch_object(
                    _hook_batch([1, 2, 3, 4, 5]),
                    _hook_batch([6, 7, 8, 9, 10]),
                ),
                CHARACTERS: _rich_characters_text(),
                SCENES: _rich_scenes_text(),
                EPISODE_ALIAS_PLAN: alias_plan,
            },
        )
        original_characters = str(variables[CHARACTERS])
        original_scenes = str(variables[SCENES])
        original_appearance_mapping = json.dumps(
            variables[APPEARANCE_MAPPING],
            ensure_ascii=False,
        )
        batches = list(iter_episode_batches(10, batch_size=5))
        runner = _PhaseRecordingRunner()

        flow._run_all_dialogue_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=alias_plan,
            rewrite_from_stage="",
        )

        write_call = runner.stage_calls(STAGE_DIALOGUES_WRITING)[0]
        self.assertEqual(write_call["hooks_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(write_call["appearance_plan_episodes"], [1, 2, 3, 4, 5])
        self.assertIn('"speech_profile"', write_call["characters_text"])
        self.assertNotIn("family_background", write_call["characters_text"])
        self.assertNotIn("dramatic_function", write_call["characters_text"])
        self.assertIn('"scene_name":"玻璃会议室"', write_call["scenes_text"])
        self.assertNotIn("outfit_requirements", write_call["scenes_text"])
        self.assertEqual(str(variables[CHARACTERS]), original_characters)
        self.assertEqual(str(variables[SCENES]), original_scenes)
        self.assertEqual(
            json.dumps(variables[APPEARANCE_MAPPING], ensure_ascii=False),
            original_appearance_mapping,
        )

    def test_script_alias_write_review_revise_and_memory_aliases(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        memory_json = json.dumps(
            {
                "final_hook_of_this_turn": "script end",
                "must_carry_into_next_turn": [],
                "appearance_continuity_summary": "appearance ok",
            },
            ensure_ascii=False,
        )
        runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_SCRIPT_REVIEW: [
                    {
                        **_script_review_payload(
                            passed=False,
                            rewrite_required=True,
                            blocking_issues=["revise"],
                            non_blocking_issues=[],
                            summary="revise",
                        ),
                    },
                    {
                        SCRIPT_REVIEW_WRITE_VAR: json.dumps(
                            _script_review_payload(
                                passed=True,
                                rewrite_required=False,
                                blocking_issues=[],
                                non_blocking_issues=[],
                                summary="passed",
                            ),
                            ensure_ascii=False,
                        )
                    },
                ]
            },
            stage_outputs={
                STAGE_SCRIPT_WRITING: [{SCRIPT_CURRENT_WRITE_VAR: _script_batch_text([1, 2, 3, 4, 5])}],
                STAGE_SCRIPT_REWRITE: [{SCRIPT_CURRENT_VAR: _script_batch_text([1, 2, 3, 4, 5])}],
                STAGE_SCRIPT_MEMORY: [{SCRIPT_MEMORY_OUTPUT_VAR: memory_json}],
            },
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertIn("第1集", str(variables[BATCH_SCRIPT]))
        self.assertEqual(str(variables[SCRIPT_CURRENT_WRITE_VAR]), str(variables[BATCH_SCRIPT]))
        self.assertEqual(str(variables[SCRIPT_CURRENT_VAR]), str(variables[BATCH_SCRIPT]))
        review_call = runner.stage_calls(STAGE_SCRIPT_REVIEW)[0]
        rewrite_call = runner.stage_calls(STAGE_SCRIPT_REWRITE)[0]
        self.assertIn("第1集", review_call["script_write_alias_text"])
        self.assertIn("第1集", review_call["script_current_alias_text"])
        self.assertIn("revise", rewrite_call["script_review_alias_text"])
        self.assertEqual(str(variables[SCRIPT_REVIEW_WRITE_VAR]), str(variables[SCRIPT_REVIEW_OUTPUT_VAR]))
        self.assertIn('"passed": true', str(variables[SCRIPT_REVIEW_OUTPUT_VAR]).lower())
        expected_memory = json.loads(memory_json)
        self.assertEqual(json.loads(str(variables[flow.SCRIPT_MEMORY])), expected_memory)
        self.assertEqual(json.loads(str(variables[SCRIPT_MEMORY_WRITE_INPUT_VAR])), expected_memory)
        self.assertEqual(json.loads(str(variables[MEMORY_VAR])), expected_memory)
        self.assertEqual(json.loads(str(variables[SCRIPT_MEMORY_OUTPUT_VAR])), expected_memory)

    def test_script_review_output_alias_path_mirrors_to_workflow_alias(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_SCRIPT_REVIEW: [
                    {
                        SCRIPT_REVIEW_OUTPUT_VAR: json.dumps(
                            _script_review_payload(
                                passed=False,
                                rewrite_required=True,
                                blocking_issues=["revise"],
                                non_blocking_issues=[],
                                summary="revise",
                            ),
                            ensure_ascii=False,
                        )
                    },
                    {
                        SCRIPT_REVIEW_OUTPUT_VAR: json.dumps(
                            _script_review_payload(
                                passed=True,
                                rewrite_required=False,
                                blocking_issues=[],
                                non_blocking_issues=[],
                                summary="passed",
                            ),
                            ensure_ascii=False,
                        )
                    },
                ]
            }
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 1)
        self.assertEqual(str(variables[SCRIPT_REVIEW_WRITE_VAR]), str(variables[SCRIPT_REVIEW_OUTPUT_VAR]))
        rewrite_call = runner.stage_calls(STAGE_SCRIPT_REWRITE)[0]
        self.assertIn("revise", rewrite_call["script_review_alias_text"])

    def test_script_review_write_alias_path_mirrors_to_rewrite_alias(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_SCRIPT_REVIEW: [
                    {
                        SCRIPT_REVIEW_WRITE_VAR: json.dumps(
                            _script_review_payload(
                                passed=False,
                                rewrite_required=True,
                                blocking_issues=["revise"],
                                non_blocking_issues=[],
                                summary="revise",
                            ),
                            ensure_ascii=False,
                        )
                    },
                    {
                        SCRIPT_REVIEW_WRITE_VAR: json.dumps(
                            _script_review_payload(
                                passed=True,
                                rewrite_required=False,
                                blocking_issues=[],
                                non_blocking_issues=[],
                                summary="passed",
                            ),
                            ensure_ascii=False,
                        )
                    },
                ]
            }
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 1)
        self.assertEqual(str(variables[SCRIPT_REVIEW_WRITE_VAR]), str(variables[SCRIPT_REVIEW_OUTPUT_VAR]))
        rewrite_call = runner.stage_calls(STAGE_SCRIPT_REWRITE)[0]
        self.assertIn("revise", rewrite_call["script_review_alias_text"])

    def test_script_review_missing_optional_schema_fields_uses_defaults(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        settings.fastgpt_stage_format_retry_limit = 3
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_SCRIPT_REVIEW: [
                    {
                        SCRIPT_REVIEW_WRITE_VAR: json.dumps(
                            {
                                "passed": True,
                                "rewrite_required": False,
                                "blocking_issues": [],
                            },
                            ensure_ascii=False,
                        )
                    },
                ]
            }
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_WRITING)), 1)
        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REVIEW)), 1)
        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 0)
        self.assertIn('"rewrite_start_episode": 1', str(variables[SCRIPT_REVIEW_OUTPUT_VAR]))
        self.assertIn('"stage": "five_episode_continuity_review"', str(variables[SCRIPT_REVIEW_OUTPUT_VAR]))

    def test_script_rewrite_receives_current_batch_hook_and_dialogue_slices(self) -> None:
        state, payload, variables, batches = self._script_ready_state(10)
        runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_SCRIPT_REVIEW: [False, True],
            }
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        rewrite_call = runner.stage_calls(STAGE_SCRIPT_REWRITE)[0]
        self.assertEqual(rewrite_call["hooks_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(rewrite_call["dialogue_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(rewrite_call["script_hook_alias_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(rewrite_call["script_dialogue_alias_episodes"], [1, 2, 3, 4, 5])
        self.assertIn("failed", rewrite_call["script_review_alias_text"])

    def test_script_stage_uses_compact_context_and_never_receives_full_hooks_or_dialogues(self) -> None:
        alias_plan = _episode_alias_plan(10)
        state, payload, variables, batches = self._script_ready_state(
            10,
            variables={
                CHARACTERS: _rich_characters_text(),
                SCENES: _rich_scenes_text(),
                EPISODE_ALIAS_PLAN: alias_plan,
            },
        )
        original_characters = str(variables[CHARACTERS])
        original_scenes = str(variables[SCENES])
        original_appearance_mapping = json.dumps(
            variables[APPEARANCE_MAPPING],
            ensure_ascii=False,
        )
        runner = _PhaseRecordingRunner()

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=alias_plan,
            rewrite_from_stage="",
        )

        write_call = runner.stage_calls(STAGE_SCRIPT_WRITING)[0]
        self.assertEqual(write_call["hooks_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(write_call["dialogue_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(write_call["appearance_plan_episodes"], [1, 2, 3, 4, 5])
        self.assertIn('"core_motivation"', write_call["characters_text"])
        self.assertNotIn("family_background", write_call["characters_text"])
        self.assertNotIn("dramatic_function", write_call["characters_text"])
        self.assertIn('"scene_name":"玻璃会议室"', write_call["scenes_text"])
        self.assertNotIn("outfit_requirements", write_call["scenes_text"])
        self.assertEqual(str(variables[CHARACTERS]), original_characters)
        self.assertEqual(str(variables[SCENES]), original_scenes)
        self.assertEqual(
            json.dumps(variables[APPEARANCE_MAPPING], ensure_ascii=False),
            original_appearance_mapping,
        )

    def test_script_memory_answertext_is_accepted_and_invalid_memory_does_not_pollute_batch(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        memory_json = json.dumps(
            {
                "final_hook_of_this_turn": "hook",
                "must_carry_into_next_turn": [],
                "appearance_continuity_summary": "ok",
            },
            ensure_ascii=False,
        )
        runner = _PhaseRecordingRunner(
            stage_outputs={STAGE_SCRIPT_MEMORY: [{"answerText": memory_json}]}
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        expected_memory = json.loads(memory_json)
        self.assertEqual(json.loads(str(variables[LAST_SUMMARY])), expected_memory)
        self.assertIn("第1集", str(variables[BATCH_SCRIPT]))
        self.assertIn("第1集", str(variables[ALL_SCRIPT]))

    def test_hook_write_format_failure_retries_current_stage_and_records_debug_artifact(self) -> None:
        state, payload, variables = self._state_and_payload(5)
        batches = list(iter_episode_batches(5, batch_size=5))
        settings.fastgpt_stage_format_retry_limit = 3
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_HOOKS_WRITING: [
                    {HOOK_CURRENT_WRITE_VAR: "普通自然语言说明"},
                    {HOOK_CURRENT_WRITE_VAR: "仍然不是 batch_hooks"},
                    {HOOK_CURRENT_WRITE_VAR: "最后一次还是坏格式"},
                ]
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "hooks_writing|输出字段 batch_hooks|hook batch 1-5",
        ):
            flow._run_all_hook_batches(
                state,
                runner,
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

        self.assertEqual(len(runner.stage_calls(STAGE_HOOKS_WRITING)), 3)
        self.assertNotIn(ALL_HOOKS, variables)
        artifact = state.get_output(STAGE_HOOKS_WRITING, "contract_guard", {})
        self.assertEqual(artifact.get("status"), "retry_exhausted")
        self.assertEqual(int(artifact.get("format_attempt") or 0), 3)
        self.assertIn("validator_issues", artifact)
        debug_file = Path(str(artifact.get("debug_file_path") or ""))
        self.assertTrue(debug_file.exists())
        debug_payload = json.loads(debug_file.read_text(encoding="utf-8"))
        self.assertEqual(debug_payload.get("stage_name"), STAGE_HOOKS_WRITING)
        self.assertEqual(debug_payload.get("expected_output_kind"), "hooks_batch_json")
        self.assertIn("input_keys", debug_payload)
        self.assertIn("raw_output_preview", debug_payload)
        self.assertIn("fastgpt_client_last_stage_debug_info", debug_payload)

    def test_hook_write_format_failure_then_second_attempt_success_continues(self) -> None:
        state, payload, variables = self._state_and_payload(5)
        batches = list(iter_episode_batches(5, batch_size=5))
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_HOOKS_WRITING: [
                    {HOOK_CURRENT_WRITE_VAR: "普通自然语言说明"},
                    {HOOK_CURRENT_WRITE_VAR: _hook_batch([1, 2, 3, 4, 5])},
                ]
            }
        )

        flow._run_all_hook_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(runner.stage_calls(STAGE_HOOKS_WRITING)), 2)
        self.assertIn(ALL_HOOKS, variables)
        artifact = state.get_output(STAGE_HOOKS_WRITING, "contract_guard", {})
        self.assertEqual(artifact.get("status"), "validated")

    def test_script_review_format_failure_retries_current_stage_without_entering_rewrite_loop(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        settings.fastgpt_stage_format_retry_limit = 3
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_SCRIPT_REVIEW: [
                    {SCRIPT_REVIEW_OUTPUT_VAR: "不是合法 JSON"},
                    {SCRIPT_REVIEW_OUTPUT_VAR: "还是不对"},
                    {SCRIPT_REVIEW_OUTPUT_VAR: "最后一次也不是 review json"},
                ]
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "script_review|审核输出未通过格式契约校验|review output",
        ):
            flow._run_all_script_batches(
                state,
                runner,
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REVIEW)), 3)
        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 0)
        self.assertEqual(str(variables.get(ALL_SCRIPT, "") or "").strip(), "")
        artifact = state.get_output(STAGE_SCRIPT_REVIEW, "contract_guard", {})
        self.assertEqual(artifact.get("status"), "retry_exhausted")
        self.assertEqual(int(artifact.get("format_attempt") or 0), 3)

    def test_episode_plan_normalize_truncated_json_retries_then_succeeds(self) -> None:
        state, payload, variables = self._normalize_stage_state(10)
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_EPISODE_PLAN_NORMALIZE: [
                    {NORMALIZED_EPISODE_PLAN: '{"episodes":[{"episode":1,"title":"第1集"}]'},
                    {NORMALIZED_EPISODE_PLAN: _normalized_plan(10)},
                ]
            }
        )

        result = flow.run_stage_with_contract_guard(
            state,
            runner,
            STAGE_EPISODE_PLAN_NORMALIZE,
            variables,
            stage_key="framework",
            message="分集规划整理",
            output_field=NORMALIZED_EPISODE_PLAN,
            sync_output_to_state=True,
        )

        self.assertEqual(len(runner.stage_calls(STAGE_EPISODE_PLAN_NORMALIZE)), 2)
        self.assertEqual(
            result[NORMALIZED_EPISODE_PLAN]["parsed_episode_count"],
            10,
        )
        self.assertEqual(
            state.variables[NORMALIZED_EPISODE_PLAN]["parsed_episode_count"],
            10,
        )
        artifact = state.get_output(STAGE_EPISODE_PLAN_NORMALIZE, "contract_guard", {})
        self.assertEqual(artifact.get("status"), "validated")

    def test_episode_plan_normalize_truncated_json_three_times_stops_with_recoverable_failure(self) -> None:
        state, payload, variables = self._normalize_stage_state(10)
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_EPISODE_PLAN_NORMALIZE: [
                    {NORMALIZED_EPISODE_PLAN: '{"episodes":[{"episode":1,"title":"第1集"}]'},
                    {NORMALIZED_EPISODE_PLAN: '{"episodes":[{"episode":1,"title":"第1集"}]'},
                    {NORMALIZED_EPISODE_PLAN: '{"episodes":[{"episode":1,"title":"第1集"}]'},
                ]
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "episode_plan_normalize|normalized_episode_plan|workflow 输出是否过长",
        ):
            flow.run_stage_with_contract_guard(
                state,
                runner,
                STAGE_EPISODE_PLAN_NORMALIZE,
                variables,
                stage_key="framework",
                message="分集规划整理",
                output_field=NORMALIZED_EPISODE_PLAN,
                sync_output_to_state=True,
            )

        self.assertEqual(len(runner.stage_calls(STAGE_EPISODE_PLAN_NORMALIZE)), 3)
        self.assertNotIn(NORMALIZED_EPISODE_PLAN, state.variables)
        artifact = state.get_output(STAGE_EPISODE_PLAN_NORMALIZE, "contract_guard", {})
        self.assertEqual(artifact.get("status"), "retry_exhausted")
        self.assertEqual(int(artifact.get("format_attempt") or 0), 3)
        debug_file = Path(str(artifact.get("debug_file_path") or ""))
        self.assertTrue(debug_file.exists())
        debug_payload = json.loads(debug_file.read_text(encoding="utf-8"))
        self.assertEqual(debug_payload.get("stage_name"), STAGE_EPISODE_PLAN_NORMALIZE)
        self.assertTrue(str(debug_payload.get("last_failure_reason") or ""))

    def test_empty_string_output_retries_three_times_without_polluting_state(self) -> None:
        state, payload, variables = self._normalize_stage_state(10)
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_EPISODE_PLAN_NORMALIZE: [
                    {NORMALIZED_EPISODE_PLAN: ""},
                    {NORMALIZED_EPISODE_PLAN: ""},
                    {NORMALIZED_EPISODE_PLAN: ""},
                ]
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "episode_plan_normalize|normalized_episode_plan",
        ):
            flow.run_stage_with_contract_guard(
                state,
                runner,
                STAGE_EPISODE_PLAN_NORMALIZE,
                variables,
                stage_key="framework",
                message="分集规划整理",
                output_field=NORMALIZED_EPISODE_PLAN,
                sync_output_to_state=True,
            )

        self.assertEqual(len(runner.stage_calls(STAGE_EPISODE_PLAN_NORMALIZE)), 3)
        self.assertNotIn(NORMALIZED_EPISODE_PLAN, state.variables)
        artifact = state.get_output(STAGE_EPISODE_PLAN_NORMALIZE, "contract_guard", {})
        self.assertEqual(artifact.get("status"), "retry_exhausted")
        self.assertFalse(bool(artifact.get("probable_truncated_json")))

    def test_http_timeout_retry_does_not_consume_format_retry_budget(self) -> None:
        state, payload, variables = self._normalize_stage_state(10)
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_EPISODE_PLAN_NORMALIZE: [
                    FastGPTTransientError("timeout", stage_name=STAGE_EPISODE_PLAN_NORMALIZE),
                    {NORMALIZED_EPISODE_PLAN: '{"episodes":[{"episode":1,"title":"第1集"}]'},
                    {NORMALIZED_EPISODE_PLAN: '{"episodes":[{"episode":1,"title":"第1集"}]'},
                    {NORMALIZED_EPISODE_PLAN: '{"episodes":[{"episode":1,"title":"第1集"}]'},
                ]
            }
        )

        with patch.object(flow, "_sleep_with_checkpoints", return_value=None):
            with self.assertRaisesRegex(
                ValueError,
                "episode_plan_normalize|normalized_episode_plan|workflow 输出是否过长",
            ):
                flow.run_stage_with_contract_guard(
                    state,
                    runner,
                    STAGE_EPISODE_PLAN_NORMALIZE,
                    variables,
                    stage_key="framework",
                    message="分集规划整理",
                    output_field=NORMALIZED_EPISODE_PLAN,
                    sync_output_to_state=True,
                )

        self.assertEqual(len(runner.stage_calls(STAGE_EPISODE_PLAN_NORMALIZE)), 4)
        artifact = state.get_output(STAGE_EPISODE_PLAN_NORMALIZE, "contract_guard", {})
        self.assertEqual(artifact.get("status"), "retry_exhausted")
        self.assertEqual(int(artifact.get("format_attempt") or 0), 3)

    def test_hook_memory_failure_stops_current_batch_and_resume_replays_memory_only(self) -> None:
        state, payload, variables = self._state_and_payload(5)
        batches = list(iter_episode_batches(5, batch_size=5))
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_HOOK_MEMORY: [
                    {HOOK_MEMORY_OUTPUT_VAR: "bad memory"},
                    {HOOK_MEMORY_OUTPUT_VAR: "still bad memory"},
                    {HOOK_MEMORY_OUTPUT_VAR: "last bad memory"},
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "开头冲突钩子 1-5 集记忆生成失败"):
            flow._run_all_hook_batches(
                state,
                runner,
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

        self.assertEqual(_episode_numbers_from_object(variables[ALL_HOOKS]), [1, 2, 3, 4, 5])
        self.assertEqual(variables[BATCH_START_EPISODE], 1)
        self.assertEqual(variables[flow.LOCAL_CURRENT_BATCH_STAGE], "hook")
        self.assertEqual(len(runner.stage_calls(STAGE_HOOKS_WRITING)), 1)
        self.assertEqual(len(runner.stage_calls(STAGE_HOOK_MEMORY)), 3)
        artifact = state.get_output(STAGE_HOOK_MEMORY, "contract_guard", {})
        self.assertFalse(bool(artifact.get("fallback_used")))
        self.assertEqual(artifact.get("status"), "retry_exhausted")
        self.assertEqual(int(artifact.get("format_attempt") or 0), 3)
        debug_file = Path(str(artifact.get("debug_file_path") or ""))
        self.assertTrue(debug_file.exists())
        debug_payload = json.loads(debug_file.read_text(encoding="utf-8"))
        self.assertTrue(str(debug_payload.get("last_failure_reason") or ""))

        resumed_runner = _PhaseRecordingRunner(
            stage_outputs={STAGE_HOOK_MEMORY: [{HOOK_MEMORY_OUTPUT_VAR: _hook_memory_json(label="resume-hook")}]}
        )
        flow._run_all_hook_batches(
            state,
            resumed_runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(resumed_runner.stage_calls(STAGE_HOOKS_WRITING)), 0)
        self.assertEqual(len(resumed_runner.stage_calls(STAGE_HOOK_MEMORY)), 1)
        self.assertEqual(json.loads(str(variables[flow.HOOK_MEMORY]))["final_hook_of_this_turn"], "resume-hook")

    def test_dialogue_memory_failure_stops_current_batch_and_resume_replays_memory_only(self) -> None:
        state, payload, variables = self._state_and_payload(
            5,
            variables={ALL_HOOKS: _hook_batch([1, 2, 3, 4, 5])},
        )
        batches = list(iter_episode_batches(5, batch_size=5))
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_DIALOGUE_MEMORY: [
                    {DIALOGUE_MEMORY_OUTPUT_VAR: "bad memory"},
                    {DIALOGUE_MEMORY_OUTPUT_VAR: "still bad memory"},
                    {DIALOGUE_MEMORY_OUTPUT_VAR: "last bad memory"},
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "角色对白 1-5 集记忆生成失败"):
            flow._run_all_dialogue_batches(
                state,
                runner,
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

        self.assertEqual(_episode_numbers_from_object(variables[ALL_DIALOGUES]), [1, 2, 3, 4, 5])
        self.assertEqual(variables[BATCH_START_EPISODE], 1)
        self.assertEqual(variables[flow.LOCAL_CURRENT_BATCH_STAGE], "dialogue")
        self.assertEqual(len(runner.stage_calls(STAGE_DIALOGUES_WRITING)), 1)
        self.assertEqual(len(runner.stage_calls(STAGE_DIALOGUE_MEMORY)), 3)
        artifact = state.get_output(STAGE_DIALOGUE_MEMORY, "contract_guard", {})
        self.assertFalse(bool(artifact.get("fallback_used")))
        self.assertEqual(artifact.get("status"), "retry_exhausted")
        self.assertEqual(int(artifact.get("format_attempt") or 0), 3)
        debug_file = Path(str(artifact.get("debug_file_path") or ""))
        self.assertTrue(debug_file.exists())
        debug_payload = json.loads(debug_file.read_text(encoding="utf-8"))
        self.assertTrue(str(debug_payload.get("last_failure_reason") or ""))

        resumed_runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_DIALOGUE_MEMORY: [
                    {DIALOGUE_MEMORY_OUTPUT_VAR: _dialogue_memory_json(label="resume-dialogue")}
                ]
            }
        )
        flow._run_all_dialogue_batches(
            state,
            resumed_runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(resumed_runner.stage_calls(STAGE_DIALOGUES_WRITING)), 0)
        self.assertEqual(len(resumed_runner.stage_calls(STAGE_DIALOGUE_MEMORY)), 1)
        self.assertEqual(json.loads(str(variables[flow.DIALOGUE_MEMORY]))["dialogue_voice_summary"], "resume-dialogue")

    def test_script_memory_invalid_json_records_debug_artifact_before_resume(self) -> None:
        previous_memory = json.dumps(
            {
                "final_hook_of_this_turn": "previous-hook",
                "must_carry_into_next_turn": ["keep-this"],
                "appearance_continuity_summary": "previous-memory",
            },
            ensure_ascii=False,
        )
        state, payload, variables, batches = self._script_ready_state(
            5,
            variables={
                LAST_SUMMARY: previous_memory,
                flow.SCRIPT_MEMORY: previous_memory,
                SCRIPT_MEMORY_WRITE_INPUT_VAR: previous_memory,
                MEMORY_VAR: previous_memory,
            },
        )
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_SCRIPT_MEMORY: [
                    {SCRIPT_MEMORY_OUTPUT_VAR: "not json"},
                    {SCRIPT_MEMORY_OUTPUT_VAR: "still not json"},
                    {SCRIPT_MEMORY_OUTPUT_VAR: "last not json"},
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "剧本正文 1-5 集记忆生成失败"):
            flow._run_all_script_batches(
                state,
                runner,
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

        self.assertEqual(str(variables[LAST_SUMMARY]), previous_memory)
        self.assertEqual(str(variables[flow.SCRIPT_MEMORY]), previous_memory)
        self.assertEqual(str(variables[SCRIPT_MEMORY_WRITE_INPUT_VAR]), previous_memory)
        self.assertEqual(str(variables[MEMORY_VAR]), previous_memory)
        self.assertIn("第1集", str(variables[ALL_SCRIPT]))
        self.assertEqual(variables[BATCH_START_EPISODE], 1)
        self.assertEqual(variables[flow.LOCAL_CURRENT_BATCH_STAGE], "script")
        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_MEMORY)), 3)
        artifact = state.get_output(STAGE_SCRIPT_MEMORY, "contract_guard", {})
        self.assertFalse(bool(artifact.get("fallback_used")))
        self.assertEqual(artifact.get("status"), "retry_exhausted")
        self.assertEqual(int(artifact.get("format_attempt") or 0), 3)
        debug_file = Path(str(artifact.get("debug_file_path") or ""))
        self.assertTrue(debug_file.exists())
        debug_payload = json.loads(debug_file.read_text(encoding="utf-8"))
        self.assertTrue(str(debug_payload.get("last_failure_reason") or ""))

    def test_dialogue_rewrite_contract_guard_accepts_declared_hookcontent_without_warning(self) -> None:
        state, payload, variables = self._state_and_payload(
            5,
            variables={ALL_HOOKS: _hook_batch([1, 2, 3, 4, 5])},
        )
        batches = list(iter_episode_batches(5, batch_size=5))
        runner = _PhaseRecordingRunner(
            review_sequences={STAGE_DIALOGUES_REVIEW: [False, True]}
        )

        flow._run_all_dialogue_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        artifact = state.get_output(STAGE_DIALOGUES_REWRITE, "contract_guard", {})
        warnings = list(artifact.get("workflow_warnings") or [])
        self.assertFalse(any("hookContent" in item for item in warnings))
        rewrite_call = runner.stage_calls(STAGE_DIALOGUES_REWRITE)[0]
        self.assertEqual(rewrite_call["dialogue_hook_prompt_alias_episodes"], [1, 2, 3, 4, 5])

    def test_workflow_json_dir_env_override_is_respected(self) -> None:
        with workspace_tempdir(prefix="workflow-json-dir-") as tmpdir:
            target_dir = Path(tmpdir)
            target_file = target_dir / "角色对话修订.json"
            target_file.write_text("{}", encoding="utf-8")
            settings.workflow_json_dir = str(target_dir)
            resolved = resolve_workflow_json_path("角色对话修订.json")
            self.assertEqual(resolved.resolve(), target_file.resolve())

    def test_script_local_validation_rejects_json_report_missing_out_of_range_duplicate(self) -> None:
        batch = BatchWindow(start_episode=1, end_episode=5)
        cases = [
            json.dumps({"batch_script": "no"}),
            "审核报告\npassed: true",
            _script_batch_text([1, 2, 3, 4]),
            _script_batch_text([1, 2, 3, 4, 6]),
            _script_batch_text([1, 1, 2, 3, 4]),
        ]
        for case in cases:
            self.assertTrue(flow.validate_batch_script_text(case, batch), case)

    def test_merge_and_complete_helpers(self) -> None:
        hooks = flow.merge_batch_hooks({}, _hook_batch([1, 2, 3, 4, 5]), BatchWindow(1, 5))
        hooks = flow.merge_batch_hooks(hooks, _hook_batch([6, 7, 8, 9, 10]), BatchWindow(6, 10))
        dialogues = flow.merge_batch_dialogues({}, _dialogue_batch([1, 2, 3, 4, 5]), BatchWindow(1, 5))
        dialogues = flow.merge_batch_dialogues(dialogues, _dialogue_batch([6, 7, 8, 9, 10]), BatchWindow(6, 10))
        script = flow.merge_batch_script("", _script_batch_text([1, 2, 3, 4, 5]), BatchWindow(1, 5))
        script = flow.merge_batch_script(script, _script_batch_text([6, 7, 8, 9, 10]), BatchWindow(6, 10))
        flow.assert_complete_hooks(hooks, 10)
        flow.assert_complete_dialogues(dialogues, 10)
        flow.assert_complete_script(script, 10)


if __name__ == "__main__":
    unittest.main()
