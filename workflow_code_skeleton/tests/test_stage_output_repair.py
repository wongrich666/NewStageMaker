from __future__ import annotations

import json
import unittest

from workflow_code_skeleton.app.config import settings
from workflow_code_skeleton.app.orchestrators.fastgpt_hybrid_workflow import (
    _ensure_scene_outputs,
    _ensure_appearance_outputs,
    _prepare_appearance_stage_inputs,
    _prepare_scene_stage_inputs,
)
from workflow_code_skeleton.app.models.inputs import WorkflowInput
from workflow_code_skeleton.app.models.state import WorkflowState
from workflow_code_skeleton.app.services.fastgpt_client import (
    FastGPTClient,
    FastGPTStageFormatError,
)
from workflow_code_skeleton.app.services.stage_output_repair import (
    normalize_appearanceMapping_candidate,
    validate_appearanceMapping_output,
)
from workflow_code_skeleton.app.services.fastgpt_contracts import (
    APPEARANCE_MAPPING,
    CHARACTERS,
    CHARACTER_ALIAS_NAMING_RULES,
    CHARACTER_APPEARANCE_REQUIREMENTS,
    EPISODE_PLAN,
    PASS_REVIEW_JSON,
    SCENES,
    STAGE_APPEARANCE_ALIAS_GENERATION,
    STAGE_APPEARANCE_ALIAS_REVIEW,
    STAGE_APPEARANCE_ALIAS_REWRITE,
    STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
    STAGE_APPEARANCE_ALIAS_WRITING,
    STAGE_CHARACTERS,
    STAGE_SCENES,
    STAGE_WORLDVIEW,
    STORY_OUTLINE,
    USER_CHARACTERS,
    USER_SCENES,
    WORLDVIEW,
    contract_for,
)
from workflow_code_skeleton.app.workflow_ids import (
    APPEARANCE_MAPPING_VAR,
    APPEARANCE_NATURAL_LANGUAGE_VAR,
    APPEARANCE_REVIEW_VAR,
    CHARACTER_VAR,
    CORE_SCENE_FINAL_VAR,
    SCENE_VAR,
    WORLDVIEW_VAR,
)


class _FakeResponse:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data
        self.status_code = 200
        self.reason = "OK"

    def json(self) -> dict[str, object]:
        return self._data


class _QueuedFastGPTClient(FastGPTClient):
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = list(responses)
        self.request_count = 0

    def _endpoint_for(self, stage_name: str):  # type: ignore[override]
        from workflow_code_skeleton.app.services.fastgpt_client import FastGPTEndpoint

        return FastGPTEndpoint(
            url="https://example.test/api/v1/chat/completions",
            url_source="test",
            api_key="test-key",
            api_key_source="test",
            chat_id=f"test-{stage_name}-{self.request_count + 1}",
            timeout=30,
        )

    def _post_with_retries(self, endpoint, headers, body, stage_name):  # type: ignore[override]
        self.request_count += 1
        if not self._responses:
            raise AssertionError("No fake FastGPT response left for test")
        return _FakeResponse(self._responses.pop(0))


class _QueuedStageRunner:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = list(responses)
        self.request_count = 0
        self.stage_calls: list[str] = []
        self.variable_snapshots: list[dict[str, object]] = []

    def run_stage(self, stage_name: str, variables: dict[str, object]) -> dict[str, object]:
        self.request_count += 1
        self.stage_calls.append(stage_name)
        self.variable_snapshots.append(dict(variables))
        if not self._responses:
            raise AssertionError("No fake stage response left for test")
        return self._responses.pop(0)


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


def _worldview_json() -> dict[str, object]:
    return {
        "worldview_summary": "现代都市职场与家庭双线挤压下，角色必须在规则与情感之间求生。",
        "era_background": "现代都市互联网行业寒冬期。",
        "social_rules": "效率优先、绩效导向，弱者在制度面前缺少话语权。",
        "space_logic": "故事主要发生在高压写字楼、合租公寓与夜间通勤空间，公共与私密空间不断挤压角色。",
        "key_settings": ["裁员阴影长期存在", "主角必须维持表面体面", "关系资源决定升迁机会"],
        "conflict_mechanisms": ["绩效考核触发资源争夺", "家庭期待与职场规则对撞", "公开站队会改变人际秩序"],
        "visual_keywords": ["冷白灯", "深夜地铁", "玻璃会议室"],
    }


def _character_setting_json(name: str = "林夏") -> dict[str, object]:
    return {
        "character_setting": {
            "character_design_principle": "每个角色都必须在高压制度里显出自己的生存姿态。",
            "core_relation_logic": "角色关系围绕资源交换、情感依赖与权力压迫展开。",
            "search_strategy_summary": "未提供联网参考，本轮仅基于世界观、故事大纲和人物小传生成",
            "characters": [
                {
                    "character_name": name,
                    "story_role": "主角",
                    "core_motivation": "在城市中站稳脚跟并守住尊严。",
                    "external_goal": "保住工作并完成关键项目。",
                    "inner_need": "学会承认自己的脆弱与需求。",
                    "deep_fear": "害怕再次被环境抛下。",
                    "self_deception": "总以为自己还能独自扛住一切。",
                    "personality": {
                        "traits": ["克制", "敏感"],
                        "surface_impression": "看起来稳重能扛事。",
                        "inner_contradiction": "想要被理解，却习惯先把自己藏起来。",
                    },
                    "family": {
                        "family_background": "普通工薪家庭出身。",
                        "upbringing": "从小被教育要懂事能忍。",
                        "key_family_influence": "家庭期待让她把责任看得比情绪更重。",
                    },
                    "appearance": {
                        "overall_look": "清瘦利落，常穿通勤装。",
                        "recognizable_features": ["总把头发束紧", "指节常因用力而发白"],
                        "external_impression_effect": "给人可靠但不好靠近的第一印象。",
                    },
                    "behavior": {
                        "habitual_actions": ["说话前先停顿半秒", "焦虑时反复整理桌面"],
                        "emotional_response_pattern": "先压住情绪，独处时才会崩开。",
                        "social_interaction_style": "对陌生人礼貌疏离，对熟人会突然嘴硬。",
                    },
                    "dimension_relations": {
                        "family_to_personality": "被要求懂事让她习惯先承担后表达。",
                        "personality_to_behavior": "克制使她在冲突里先收再发。",
                        "appearance_to_social_effect": "清冷外表让同事误判她不需要帮助。",
                        "behavior_to_character_reveal": "细小整理动作暴露她对失控的恐惧。",
                    },
                    "decision_logic": {
                        "when_under_pressure": "优先保住底线与结果，再慢慢回收代价。",
                        "when_facing_authority": "表面服从、暗中保留转圜空间。",
                        "when_facing_desire": "会先压抑欲望，确认代价后才行动。",
                        "when_losing_control": "嘴上更硬，行动却会突然冒险。",
                        "moral_bottom_line": "不愿牺牲无辜者换取个人利益。",
                        "self_justification": "把所有痛苦包装成自己应该承担的责任。",
                    },
                    "speech_profile": {
                        "baseline_register": "简短克制，不轻易说满。",
                        "sentence_rhythm": "句子偏短，关键处会突然停顿。",
                        "keyword_habits": ["先这样", "我来处理"],
                        "conflict_style": "不大喊，但会一句句逼近核心矛盾。",
                        "intimacy_style": "会用反问掩饰关心。",
                        "command_style": "语气平静但带执行要求。",
                        "humor_style": "偶尔用冷幽默卸压。",
                        "when_angry": "声音更轻，措辞更锋利。",
                        "when_hiding_truth": "会把重点挪到工作流程上。",
                    },
                    "relation_modes": [
                        {
                            "target": "周沉",
                            "relation_type": "危险盟友",
                            "what_this_character_wants": "希望从对方身上获得资源与理解。",
                            "what_this_character_fears": "害怕自己被看透后失去主动权。",
                            "default_posture": "先试探，再谨慎靠近。",
                            "speech_difference": "面对他会更少废话、更常反问。",
                            "conflict_trigger": "一旦对方替她决定，她就会立刻反弹。",
                        }
                    ],
                    "actable_evidence": {
                        "signature_actions": ["开会前先把笔摆正", "压力大时会捏紧工牌"],
                        "micro_reactions": ["听到否定时下颌会先绷住"],
                        "props_or_style_clues": ["旧工牌套"],
                        "first_appearance_must_show": ["深夜加班后仍把衬衫扣好最后一颗扣子"],
                    },
                    "dramatic_function": {
                        "best_conflict_type": "尊严与生存的拉扯型冲突。",
                        "easiest_wrong_choice": "把求助误判成软弱。",
                        "turning_point": "第一次主动承认自己也需要别人。",
                        "scene_value": "能把压抑情绪变成持续可演的张力。",
                    },
                    "search_reference_usage": {
                        "borrowed_domains": ["未提供联网参考"],
                        "absorbed_patterns": ["未提供联网参考"],
                        "forbidden_copying": ["未照搬真实人物经历或原句"],
                    },
                    "dramatic_value": "她的选择决定主线冲突是继续隐忍还是正式反击。",
                }
            ],
        }
    }


def _scene_setting_json() -> dict[str, object]:
    def _scene_item(name: str, alias_suffix: str, conflict: str) -> dict[str, object]:
        return {
            "scene_name": name,
            "scene_type": "核心博弈场",
            "story_function": f"{name}负责承载主线冲突推进与人物关系变形。",
            "scene_time_or_period": "深夜加班时段",
            "weather_or_environment_state": "冷白灯长亮，空气闷且安静",
            "environment_description": f"{name}空间封闭，任何情绪波动都会被放大。",
            "atmosphere_description": "表面克制，内里高压。",
            "visual_elements": ["玻璃反光", "凌乱文件", "屏幕冷光"],
            "visual_condition_summary": f"{name}需要保持冷硬、压迫、可持续发生权力观察的视觉条件。",
            "identity_or_status_requirements": ["角色必须带着明显的职场身份差异进入场景"],
            "styling_condition_summary": f"{name}里的人物造型要体现职位、疲态与临时应战状态。",
            "outfit_requirements": [
                {
                    "character_id": "林夏",
                    "canonical_name": "林夏",
                    "recommended_alias_name": f"林夏（{alias_suffix}）",
                    "identity_or_status": "项目负责人强撑状态",
                    "outfit_requirement": "通勤衬衫有轻微褶皱，保持精英感但露出疲态",
                    "visual_focus": "袖口与肩线的强撑感",
                    "must_use_alias_when_triggered": True,
                    "trigger_reason": "该场景需要明确角色的当前职场身份与疲态",
                    "forbidden_fallback_names": ["男主", "女主", "反派", "配角"],
                }
            ],
            "naming_condition_summary": f"{name}中的称谓要体现权力距离与身份压力。",
            "alias_usage_rules": [
                {
                    "character_id": "林夏",
                    "canonical_name": "林夏",
                    "recommended_alias_name": f"林夏（{alias_suffix}）",
                    "usage_condition": "当场景强调她的工作身份与外在体面时使用",
                    "fallback_allowed": False,
                    "reason": "避免退化回模糊泛称，保持人物造型与身份一致",
                }
            ],
            "conflict_potential": [conflict],
            "character_interaction_effect": "角色对话会更短、更克制，防御姿态明显上升。",
            "worldview_support": "这个场景让高压制度、资源争夺和身份表演同时可视化。",
        }

    return {
        "scene_setting": {
            "scene_design_principle": "每个场景都必须同时承载剧情推进、视觉条件与角色身份暴露。",
            "scene_visual_styling_naming_strategy": "用冷硬空间、疲态造型和精确 alias 共同固定人物出场条件。",
            "scenes": [
                _scene_item("玻璃会议室", "会议室交锋态", "公开站队与背锅切割随时爆发"),
                _scene_item("深夜开放办公区", "熬夜作战态", "任务失控后责任归属会迅速恶化"),
                _scene_item("合租公寓玄关", "卸甲回家态", "体面外壳与真实崩溃会在此正面撞上"),
            ],
        }
    }


def _scene_setting_from_output_text(output_text: str) -> dict[str, object]:
    parsed = json.loads(output_text)
    if isinstance(parsed, dict) and isinstance(parsed.get("scenes"), dict):
        wrapped = parsed.get("scenes")
        if isinstance(wrapped, dict) and isinstance(wrapped.get("scene_setting"), dict):
            return wrapped["scene_setting"]
    if isinstance(parsed, dict) and isinstance(parsed.get("scene_setting"), dict):
        return parsed["scene_setting"]
    raise AssertionError("scenes 输出未包含可识别的 scene_setting")


def _appearanceMapping_json() -> dict[str, object]:
    return {
        "appearanceMapping": {
            "mapping_principle": "同一角色按场景与身份状态切换服饰别名，但始终保留同一人物识别锚点。",
            "global_naming_style": "统一使用“角色中文全名【场景/状态/身份】”的命名方式。",
            "characters": [
                {
                    "character_id": "linxia",
                    "canonical_name": "林夏",
                    "story_role": "主角",
                    "same_person_anchor": {
                        "stable_appearance_traits": ["清瘦利落", "通勤感强"],
                        "stable_recognition_points": ["总把头发束紧", "说话前会先停顿"],
                        "unchanged_core_impression": "克制冷硬但始终强撑体面。",
                    },
                    "default_name": "林夏",
                    "forbidden_generic_names": ["男主", "女主", "反派", "配角"],
                    "outfit_variants": [
                        {
                            "variant_id": "linxia_meeting",
                            "alias_name": "林夏【会议室交锋态】",
                            "applicable_identity_state": "项目负责人高压博弈状态",
                            "outfit_type": "精英通勤装",
                            "outfit_description": "深色西装外套配利落内搭，保持体面但略有疲态。",
                            "visual_keypoints": ["硬挺肩线", "冷色衬衫", "细金属耳饰"],
                            "episode_range_hint": "第1-3集",
                            "scene_trigger_rules": {
                                "scene_names": ["玻璃会议室"],
                                "scene_types": ["核心博弈场"],
                                "environment_or_time": ["深夜加班时段"],
                                "status_conditions": ["需要公开扛责或正面交锋"],
                            },
                            "usage_rule": "凡是进入公开谈判和站队场景，都优先使用该 alias。",
                            "must_use_when_triggered": True,
                            "fallback_allowed": False,
                            "same_person_confirmation": "仍然是林夏本人，只是进入高压谈判状态。",
                        }
                    ],
                }
            ],
            "episode_level_usage_plan": [
                {
                    "episode_range": "第1-3集",
                    "main_character_aliases": [
                        {
                            "character_id": "linxia",
                            "recommended_alias_name": "林夏【会议室交锋态】",
                            "reason": "前期主线集中发生在公开博弈与背锅切割场景。",
                        }
                    ],
                }
            ],
            "scene_level_usage_plan": [
                {
                    "scene_name": "玻璃会议室",
                    "expected_alias_usage": [
                        {
                            "character_id": "linxia",
                            "alias_name": "林夏【会议室交锋态】",
                            "reason": "该场景需要把她的职场身份与强撑状态直接写进人物名。",
                        }
                    ],
                }
            ],
            "special_naming_rules": ["禁止回退为男主、女主、反派、配角等泛称。"],
        }
    }


def _appearanceMapping_with_principle(principle: str) -> dict[str, object]:
    payload = json.loads(json.dumps(_appearanceMapping_json(), ensure_ascii=False))
    payload["appearanceMapping"]["mapping_principle"] = principle
    return payload


def _appearance_review_json(
    *,
    passed: bool,
    rewrite_required: bool,
    blocking_issues: list[str] | None = None,
) -> dict[str, object]:
    return {
        "passed": passed,
        "rewrite_required": rewrite_required,
        "summary": "审核通过" if passed else "需要修订",
        "blocking_issues": list(blocking_issues or []),
        "non_blocking_issues": [],
    }


def _simplified_appearanceMapping_json() -> dict[str, object]:
    return {
        "appearanceMapping": {
            "characters": [
                {
                    "character_name": "白雪公主",
                    "canonical_name": "白雪公主",
                    "default_name": "白雪公主【日常】",
                    "outfit_variants": [
                        {
                            "alias_name": "白雪公主【日常】",
                            "visual_keypoints": [],
                            "scene_names": ["王宫走廊"],
                            "scene_types": ["宫廷"],
                            "status_conditions": ["常态"],
                            "same_person_confirmation": "",
                        }
                    ],
                }
            ]
        }
    }


def _appearance_input_variables() -> dict[str, str]:
    variables = _input_variables()
    variables[CHARACTERS] = json.dumps(_character_setting_json(), ensure_ascii=False)
    variables[SCENES] = json.dumps(_scene_setting_json(), ensure_ascii=False)
    variables[CHARACTER_ALIAS_NAMING_RULES] = "统一使用角色中文全名【场景/状态/身份】。"
    return variables


def _workflow_input() -> WorkflowInput:
    return WorkflowInput(
        title="测试剧本",
        episode_word_count=800,
        total_episodes=12,
        user_expectation="现代都市高压职场悬疑剧",
        character_count=4,
        character_appearance_requirements="",
        character_alias_naming_rules="",
        outfit_switch_rules="",
        story_outline="",
        core_scene_input="",
        character_bios="",
        episode_plan="",
    )


def _input_variables() -> dict[str, str]:
    story_outline = {
        "opening": "林夏在互联网公司濒临被裁。",
        "inciting_incident": "核心项目突然失控，她被迫和周沉结盟。",
        "early_goal": "保住岗位并压下丑闻。",
        "middle_escalation": "她发现项目背后牵连到更大的利益交换。",
        "relationship_changes": "她与周沉从互防到互用再到互相依赖。",
        "larger_crisis_or_truth": "真正的危机是她自己也成为了制度的一环。",
        "late_direction": "她开始反向布局，试图撕开游戏规则。",
        "final_climax": "她必须在曝光真相和保全家人之间做选择。",
        "ending_resolution": "她失去一部分体面，但重新拿回选择权。",
        "theme": "高压秩序下的尊严与自我夺回。",
    }
    user_scenes = {
        "era_background": "现代都市互联网寒冬期。",
        "world_state": "公司裁员频发，年轻人被迫在高压规则里卷生卷死。",
        "core_locations": [
            {
                "name": "玻璃会议室",
                "function": "权力谈判",
                "conflict_soil": "公开站队与背锅切割",
                "key_characters": ["林夏", "周沉"],
            },
            {
                "name": "合租公寓",
                "function": "情绪卸甲",
                "conflict_soil": "私人脆弱与现实账单冲突",
                "key_characters": ["林夏"],
            },
        ],
        "rules": "表面讲流程，实际讲资源与站队。",
        "danger_sources": "裁员、项目背锅、舆论扩散。",
        "resource_or_stakes": "项目归属、升职名额、体面与生存权。",
        "power_distribution": "高层掌握资源，中层转嫁风险，基层互相挤压。",
        "special_rules": "",
        "overall_atmosphere": "冷峻、压抑、节奏很快。",
    }
    user_characters = [
        {
            "name": "林夏",
            "role_type": "主角",
            "identity": "互联网项目经理",
            "personality": "克制敏感，越到绝境越不愿示弱。",
            "core_desire": "在城市里拥有真正属于自己的位置。",
            "deep_motivation": "不想再回到被环境决定命运的状态。",
            "strengths": "执行力强、观察细、能扛压。",
            "weaknesses": "过度逞强，不愿求助。",
            "appearance_anchor": "总把头发束紧，神情清冷。",
            "relationship_to_protagonist": "主角本人",
            "relationships_with_others": "与周沉既互防又互用。",
            "growth_arc": "从只会硬扛到学会主动选择与联结。",
            "plot_function": "推动主线冲突升级并完成价值抉择。",
        },
        {
            "name": "周沉",
            "role_type": "盟友/对手",
            "identity": "公司战略负责人",
            "personality": "冷静、算计、极少暴露真实情绪。",
            "core_desire": "借这次动荡完成权力跃迁。",
            "deep_motivation": "害怕再次成为被放弃的人。",
            "strengths": "掌控信息、谈判强、反应快。",
            "weaknesses": "控制欲强，不信任他人。",
            "appearance_anchor": "衣着极简，总是慢半拍开口。",
            "relationship_to_protagonist": "危险盟友",
            "relationships_with_others": "对高层顺从表面、对下属极度克制。",
            "growth_arc": "在利用与真心之间反复摇摆。",
            "plot_function": "持续制造灰度选择和权力诱惑。",
        },
    ]
    episode_plan = [
        {
            "episode": 1,
            "title": "玻璃门后的名单",
            "main_plot": "林夏得知裁员消息，被迫接手即将失控的项目。",
            "conflicts": ["会议室背锅", "同组切割", "周沉突然介入"],
            "ending_hook": "她发现名单上已经有自己的名字。",
        }
    ]
    return {
        STORY_OUTLINE: json.dumps(story_outline, ensure_ascii=False),
        USER_SCENES: json.dumps(user_scenes, ensure_ascii=False),
        USER_CHARACTERS: json.dumps(user_characters, ensure_ascii=False),
        EPISODE_PLAN: json.dumps(episode_plan, ensure_ascii=False),
        WORLDVIEW: json.dumps(_worldview_json(), ensure_ascii=False),
        CHARACTER_APPEARANCE_REQUIREMENTS: "",
        CHARACTER_ALIAS_NAMING_RULES: "",
    }


class StageOutputRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FastGPTClient()
        self.variables = _input_variables()
        self.appearance_variables = _appearance_input_variables()
        self._old_stage_local_restart_retries = getattr(
            settings,
            "fastgpt_stage_local_restart_retries",
            1,
        )
        self._old_stage_output_rerun_retries = getattr(
            settings,
            "fastgpt_stage_output_rerun_retries",
            1,
        )
        self._old_appearance_local_review_retries = getattr(
            settings,
            "fastgpt_appearance_local_review_retries",
            1,
        )
        self._old_stage_review_revise_max_loops = getattr(
            settings,
            "fastgpt_stage_review_revise_max_loops",
            10,
        )
        self._old_stage_format_retry_limit = getattr(
            settings,
            "fastgpt_stage_format_retry_limit",
            3,
        )
        settings.fastgpt_stage_local_restart_retries = 1
        settings.fastgpt_stage_output_rerun_retries = 1
        settings.fastgpt_appearance_local_review_retries = 1
        settings.fastgpt_stage_review_revise_max_loops = 10
        settings.fastgpt_stage_format_retry_limit = 1

    def tearDown(self) -> None:
        settings.fastgpt_stage_local_restart_retries = self._old_stage_local_restart_retries
        settings.fastgpt_stage_output_rerun_retries = self._old_stage_output_rerun_retries
        settings.fastgpt_appearance_local_review_retries = self._old_appearance_local_review_retries
        settings.fastgpt_stage_review_revise_max_loops = self._old_stage_review_revise_max_loops
        settings.fastgpt_stage_format_retry_limit = self._old_stage_format_retry_limit

    def _extract(self, stage_name: str, data: dict[str, object]) -> dict[str, str]:
        contract = contract_for(stage_name)
        payload = self.client._extract_output_payload(data, contract, dict(self.variables))
        return contract.validate_output_payload(payload)

    def test_worldview_direct_standard_json(self) -> None:
        result = self._extract(STAGE_WORLDVIEW, {"answerText": json.dumps(_worldview_json(), ensure_ascii=False)})
        parsed = json.loads(result[WORLDVIEW])
        self.assertEqual(parsed["era_background"], _worldview_json()["era_background"])

    def test_worldview_choices_message_content_json(self) -> None:
        result = self._extract(
            STAGE_WORLDVIEW,
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(_worldview_json(), ensure_ascii=False)
                        }
                    }
                ]
            },
        )
        parsed = json.loads(result[WORLDVIEW])
        self.assertEqual(parsed["space_logic"], _worldview_json()["space_logic"])

    def test_worldview_wrapped_in_internal_variable(self) -> None:
        data = {
            "responseData": {
                "updateVarResult": [
                    {
                        "variable": ["VARIABLE_NODE_ID", WORLDVIEW_VAR],
                        "value": json.dumps(_worldview_json(), ensure_ascii=False),
                    }
                ]
            }
        }
        result = self._extract(STAGE_WORLDVIEW, data)
        parsed = json.loads(result[WORLDVIEW])
        self.assertEqual(parsed["worldview_summary"], _worldview_json()["worldview_summary"])

    def test_worldview_markdown_code_fence(self) -> None:
        fenced = "```json\n" + json.dumps(_worldview_json(), ensure_ascii=False, indent=2) + "\n```"
        result = self._extract(STAGE_WORLDVIEW, {"answerText": fenced})
        parsed = json.loads(result[WORLDVIEW])
        self.assertEqual(parsed["visual_keywords"][0], "冷白灯")

    def test_worldview_missing_arrays_are_filled(self) -> None:
        partial = {
            "worldview_summary": "现代职场高压之下的生存故事。",
            "era_background": "现代都市。",
            "social_rules": "资源决定话语权。",
            "space_logic": "公司与住处之间来回切换。",
        }
        result = self._extract(STAGE_WORLDVIEW, {"answerText": json.dumps(partial, ensure_ascii=False)})
        parsed = json.loads(result[WORLDVIEW])
        self.assertEqual(len(parsed["key_settings"]), 3)
        self.assertEqual(len(parsed["conflict_mechanisms"]), 3)
        self.assertEqual(len(parsed["visual_keywords"]), 3)

    def test_characters_direct_character_setting(self) -> None:
        result = self._extract(
            STAGE_CHARACTERS,
            {"answerText": json.dumps(_character_setting_json(), ensure_ascii=False)},
        )
        parsed = json.loads(result[CHARACTERS])
        self.assertEqual(parsed["character_setting"]["characters"][0]["character_name"], "林夏")

    def test_scenes_direct_scene_setting_json(self) -> None:
        result = self._extract(
            STAGE_SCENES,
            {"answerText": json.dumps(_scene_setting_json(), ensure_ascii=False)},
        )
        scene_setting = _scene_setting_from_output_text(result[SCENES])
        self.assertEqual(len(scene_setting["scenes"]), 3)
        self.assertEqual(scene_setting["scenes"][0]["scene_name"], "玻璃会议室")

    def test_scenes_wrapped_in_internal_variable(self) -> None:
        data = {
            "responseData": {
                "updateVarResult": [
                    {
                        "variable": ["VARIABLE_NODE_ID", SCENE_VAR],
                        "value": json.dumps(_scene_setting_json(), ensure_ascii=False),
                    }
                ]
            }
        }
        result = self._extract(STAGE_SCENES, data)
        scene_setting = _scene_setting_from_output_text(result[SCENES])
        self.assertEqual(scene_setting["scenes"][1]["scene_name"], "深夜开放办公区")

    def test_scenes_markdown_code_fence(self) -> None:
        fenced = "```json\n" + json.dumps(_scene_setting_json(), ensure_ascii=False, indent=2) + "\n```"
        result = self._extract(STAGE_SCENES, {"answerText": fenced})
        scene_setting = _scene_setting_from_output_text(result[SCENES])
        self.assertEqual(scene_setting["scenes"][2]["scene_name"], "合租公寓玄关")

    def test_scenes_output_with_message_content_role_fields_is_rejected(self) -> None:
        polluted = _scene_setting_json()
        first_scene = polluted["scene_setting"]["scenes"][0]
        first_scene["message"] = "tool payload"
        first_scene["role"] = "assistant"
        first_scene["content"] = "审核通过"

        with self.assertRaises(ValueError):
            self._extract(
                STAGE_SCENES,
                {"answerText": json.dumps(polluted, ensure_ascii=False)},
            )

    def test_scenes_legacy_fields_are_rejected(self) -> None:
        legacy_payload = {
            "scene_setting": {
                "scene_design_principle": "旧结构",
                "scene_visual_styling_naming_strategy": "旧结构",
                "scenes": [
                    {
                        "name": "旧码头",
                        "function": "承载对峙",
                        "conflict_soil": "适合围堵",
                        "key_characters": ["林夏"],
                    }
                    for _ in range(3)
                ],
            }
        }

        with self.assertRaises(ValueError):
            self._extract(
                STAGE_SCENES,
                {"answerText": json.dumps(legacy_payload, ensure_ascii=False)},
            )

    def test_scenes_repair_does_not_recurse_into_message_content(self) -> None:
        wrapped = {
            "output": {
                "message": {
                    "content": json.dumps(_scene_setting_json(), ensure_ascii=False)
                }
            }
        }

        with self.assertRaises(FastGPTStageFormatError):
            self._extract(STAGE_SCENES, wrapped)

    def test_characters_wrapped_in_internal_variable(self) -> None:
        data = {
            "responseData": {
                "updateVarResult": [
                    {
                        "variable": ["VARIABLE_NODE_ID", CHARACTER_VAR],
                        "value": json.dumps(_character_setting_json("周沉"), ensure_ascii=False),
                    }
                ]
            }
        }
        result = self._extract(STAGE_CHARACTERS, data)
        parsed = json.loads(result[CHARACTERS])
        self.assertEqual(parsed["character_setting"]["characters"][0]["character_name"], "周沉")

    def test_characters_natural_language_repairs_within_same_attempt(self) -> None:
        result = self._extract(
            STAGE_CHARACTERS,
            {"answerText": "她在高压里习惯先沉默后反击，总以为自己还能一个人扛住所有风险。"},
        )
        parsed = json.loads(result[CHARACTERS])
        first_character = parsed["character_setting"]["characters"][0]
        self.assertEqual(first_character["character_name"], "林夏")
        self.assertTrue(first_character["decision_logic"]["when_under_pressure"])

    def test_scenes_natural_language_requires_orchestrator_retry_not_client_rerun(self) -> None:
        client = _QueuedFastGPTClient(
            [
                {"answerText": "核心场景包括玻璃会议室、深夜办公区和合租公寓，整体偏冷硬压抑。"},
                {"answerText": json.dumps(_scene_setting_json(), ensure_ascii=False)},
            ]
        )
        with self.assertRaises(FastGPTStageFormatError):
            client.run_stage(STAGE_SCENES, dict(self.variables))
        self.assertEqual(client.request_count, 1)

    def test_worldview_unknown_wrapper_is_rejected_without_client_rerun(self) -> None:
        client = _QueuedFastGPTClient(
            [
                {"answerText": json.dumps({"foo": "bar"}, ensure_ascii=False)},
                {"answerText": json.dumps(_worldview_json(), ensure_ascii=False)},
            ]
        )
        with self.assertRaises(FastGPTStageFormatError):
            client.run_stage(STAGE_WORLDVIEW, dict(self.variables))
        self.assertEqual(client.request_count, 1)

    def test_scenes_unknown_wrapper_is_rejected_without_client_rerun(self) -> None:
        client = _QueuedFastGPTClient(
            [
                {"answerText": json.dumps({"foo": "bar"}, ensure_ascii=False)},
                {"answerText": json.dumps(_scene_setting_json(), ensure_ascii=False)},
            ]
        )
        with self.assertRaises(FastGPTStageFormatError):
            client.run_stage(STAGE_SCENES, dict(self.variables))
        self.assertEqual(client.request_count, 1)

    def test_characters_natural_language_requires_orchestrator_retry_not_client_rerun(self) -> None:
        client = _QueuedFastGPTClient(
            [
                {"answerText": "林夏在高压里习惯先沉默后反击，总以为自己还能一个人扛住所有风险。"},
                {"answerText": json.dumps(_character_setting_json("周沉"), ensure_ascii=False)},
            ]
        )
        with self.assertRaises(FastGPTStageFormatError):
            client.run_stage(STAGE_CHARACTERS, dict(self.variables))
        self.assertEqual(client.request_count, 1)

    def test_review_json_is_not_treated_as_formal_worldview(self) -> None:
        review_json = {"approved": False, "suggestions": ["世界观过于空泛", "补充空间逻辑"]}
        with self.assertRaises(FastGPTStageFormatError):
            self._extract(STAGE_WORLDVIEW, {"answerText": json.dumps(review_json, ensure_ascii=False)})

    def test_review_json_is_not_treated_as_formal_characters(self) -> None:
        review_json = {"passed": False, "blocking_issues": ["对白腔调过于一致"], "summary": "需要补强"}
        with self.assertRaises(FastGPTStageFormatError):
            self._extract(STAGE_CHARACTERS, {"answerText": json.dumps(review_json, ensure_ascii=False)})

    def test_review_json_is_not_treated_as_formal_scenes(self) -> None:
        review_json = {"passed": False, "blocking_issues": ["场景数量不足"], "summary": "需要补强"}
        with self.assertRaises(ValueError):
            self._extract(STAGE_SCENES, {"answerText": json.dumps(review_json, ensure_ascii=False)})

    def test_empty_string_requires_contract_retry(self) -> None:
        with self.assertRaises(FastGPTStageFormatError):
            self._extract(STAGE_WORLDVIEW, {"answerText": ""})

    def test_scenes_empty_string_cannot_enter_formal_cache(self) -> None:
        with self.assertRaises(ValueError):
            self._extract(STAGE_SCENES, {"answerText": ""})

    def test_worldview_review_json_requires_orchestrator_retry_not_client_rerun(self) -> None:
        review_json = {"approved": False, "suggestions": ["补充时代背景", "补充视觉关键词"]}
        client = _QueuedFastGPTClient(
            [
                {"answerText": json.dumps(review_json, ensure_ascii=False)},
                {"answerText": json.dumps(_worldview_json(), ensure_ascii=False)},
            ]
        )
        with self.assertRaises(FastGPTStageFormatError):
            client.run_stage(STAGE_WORLDVIEW, dict(self.variables))
        self.assertEqual(client.request_count, 1)

    def test_characters_review_json_requires_orchestrator_retry_not_client_rerun(self) -> None:
        review_json = {"passed": False, "blocking_issues": ["角色动机不完整"], "summary": "需要补强"}
        client = _QueuedFastGPTClient(
            [
                {"answerText": json.dumps(review_json, ensure_ascii=False)},
                {"answerText": json.dumps(_character_setting_json("周沉"), ensure_ascii=False)},
            ]
        )
        with self.assertRaises(FastGPTStageFormatError):
            client.run_stage(STAGE_CHARACTERS, dict(self.variables))
        self.assertEqual(client.request_count, 1)

    def test_scenes_review_json_requires_orchestrator_retry_not_client_rerun(self) -> None:
        review_json = {"passed": False, "blocking_issues": ["缺少 alias_usage_rules"], "summary": "需要补强"}
        client = _QueuedFastGPTClient(
            [
                {"answerText": json.dumps(review_json, ensure_ascii=False)},
                {"answerText": json.dumps(_scene_setting_json(), ensure_ascii=False)},
            ]
        )
        with self.assertRaises(FastGPTStageFormatError):
            client.run_stage(STAGE_SCENES, dict(self.variables))
        self.assertEqual(client.request_count, 1)

    def test_worldview_invalid_output_fails_fast_without_client_fallback(self) -> None:
        review_json = {"approved": False, "suggestions": ["仍未形成正式世界观"]}
        client = _QueuedFastGPTClient(
            [
                {"answerText": json.dumps(review_json, ensure_ascii=False)},
                {"answerText": json.dumps(review_json, ensure_ascii=False)},
            ]
        )
        with self.assertRaises(FastGPTStageFormatError):
            client.run_stage(STAGE_WORLDVIEW, dict(self.variables))
        self.assertEqual(client.request_count, 1)

    def test_scenes_invalid_output_fails_fast_without_client_rerun(self) -> None:
        review_json = {"passed": False, "blocking_issues": ["仍未形成 scene_setting"], "summary": "继续修订"}
        client = _QueuedFastGPTClient(
            [
                {"answerText": json.dumps(review_json, ensure_ascii=False)},
                {"answerText": json.dumps(review_json, ensure_ascii=False)},
            ]
        )
        with self.assertRaises(FastGPTStageFormatError):
            client.run_stage(STAGE_SCENES, dict(self.variables))
        self.assertEqual(client.request_count, 1)

    def test_scene_input_guard_rejects_broken_worldview(self) -> None:
        broken = dict(self.variables)
        broken[WORLDVIEW] = ""
        _prepared, _warnings, fatal_errors = _prepare_scene_stage_inputs(broken)
        self.assertIn("worldview 为空或不是合法世界观 JSON", fatal_errors)

    def test_scene_stage_uses_compact_characters_without_overwriting_formal_output(self) -> None:
        state = WorkflowState.from_defaults(user_input=_workflow_input(), default_variables={})
        variables = dict(self.appearance_variables)
        original_characters = str(variables[CHARACTERS])
        variables.pop(SCENES, None)
        runner = _QueuedStageRunner(
            [
                {
                    SCENES: json.dumps(_scene_setting_json(), ensure_ascii=False),
                }
            ]
        )
        state.variables.update(variables)

        _ensure_scene_outputs(state, runner, variables)

        self.assertEqual(str(variables[CHARACTERS]), original_characters)
        self.assertEqual(runner.stage_calls, [STAGE_SCENES])
        stage_input = runner.variable_snapshots[0]
        compact_user_characters = str(stage_input[USER_CHARACTERS])
        self.assertIn('"character_name":"林夏"', compact_user_characters)
        self.assertIn('"dramatic_value_summary"', compact_user_characters)
        self.assertNotIn("family_background", compact_user_characters)
        self.assertNotIn("speech_profile", compact_user_characters)

    def test_prepare_appearance_stage_inputs_use_compact_characters_and_scenes(self) -> None:
        prepared, warnings, fatal_errors = _prepare_appearance_stage_inputs(
            dict(self.appearance_variables)
        )

        self.assertEqual(warnings, [])
        self.assertEqual(fatal_errors, [])
        self.assertIn('"same_person_traits"', str(prepared[CHARACTERS]))
        self.assertIn('"default_name_candidate":"林夏"', str(prepared[CHARACTERS]))
        self.assertNotIn("dramatic_function", str(prepared[CHARACTERS]))
        self.assertEqual(str(prepared[USER_CHARACTERS]), str(prepared[CHARACTERS]))
        self.assertIn('"scene_name":"玻璃会议室"', str(prepared[SCENES]))
        self.assertIn('"conflict_potential_summary"', str(prepared[SCENES]))
        self.assertNotIn("outfit_requirements", str(prepared[SCENES]))

    def test_prepare_appearance_stage_inputs_do_not_overwrite_formal_mapping(self) -> None:
        variables = dict(self.appearance_variables)
        original_mapping = json.dumps(_appearanceMapping_json(), ensure_ascii=False)
        variables[APPEARANCE_MAPPING] = original_mapping

        prepared, warnings, fatal_errors = _prepare_appearance_stage_inputs(variables)

        self.assertEqual(warnings, [])
        self.assertEqual(fatal_errors, [])
        self.assertEqual(variables[APPEARANCE_MAPPING], original_mapping)
        self.assertEqual(prepared[APPEARANCE_MAPPING], original_mapping)

    def test_appearanceMapping_standard_json_passes(self) -> None:
        result = self._extract(
            STAGE_APPEARANCE_ALIAS_GENERATION,
            {"output": _appearanceMapping_json()},
        )
        mapping = result[APPEARANCE_MAPPING]
        self.assertEqual(mapping["characters"][0]["canonical_name"], "林夏")

    def test_appearanceMapping_choices_json_object_passes(self) -> None:
        result = self._extract(
            STAGE_APPEARANCE_ALIAS_GENERATION,
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                _appearanceMapping_json(),
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )
        mapping = result[APPEARANCE_MAPPING]
        self.assertEqual(mapping["scene_level_usage_plan"][0]["scene_name"], "玻璃会议室")

    def test_appearanceMapping_wrapped_in_answer_node_alias_string_passes(self) -> None:
        answer_node = {
            APPEARANCE_MAPPING_VAR: json.dumps(
                _appearanceMapping_json(),
                ensure_ascii=False,
            )
        }
        result = self._extract(
            STAGE_APPEARANCE_ALIAS_GENERATION,
            {"responseData": {"answerNode": answer_node}},
        )
        mapping = result[APPEARANCE_MAPPING]
        self.assertEqual(mapping["characters"][0]["outfit_variants"][0]["alias_name"], "林夏【会议室交锋态】")

    def test_appearance_answer_text_json_is_not_formal_output(self) -> None:
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {"answerText": json.dumps(_appearanceMapping_json(), ensure_ascii=False)},
            )

    def test_appearanceMapping_wrapped_in_update_var_result_passes(self) -> None:
        data = {
            "responseData": {
                "updateVarResult": [
                    {
                        "variable": ["VARIABLE_NODE_ID", APPEARANCE_MAPPING_VAR],
                        "value": json.dumps(_appearanceMapping_json(), ensure_ascii=False),
                    }
                ]
            }
        }
        result = self._extract(STAGE_APPEARANCE_ALIAS_GENERATION, data)
        mapping = result[APPEARANCE_MAPPING]
        self.assertEqual(mapping["mapping_principle"], _appearanceMapping_json()["appearanceMapping"]["mapping_principle"])

    def test_appearanceMapping_blank_default_name_repairs_from_canonical_name(self) -> None:
        broken = json.loads(json.dumps(_appearanceMapping_json(), ensure_ascii=False))
        broken["appearanceMapping"]["characters"][0]["default_name"] = ""

        result = self._extract(
            STAGE_APPEARANCE_ALIAS_GENERATION,
            {"output": broken},
        )

        mapping = result[APPEARANCE_MAPPING]
        self.assertEqual(mapping["characters"][0]["default_name"], "林夏")
        self.assertEqual(validate_appearanceMapping_output(mapping), [])

    def test_appearanceMapping_blank_default_name_repairs_from_character_id_when_name_missing(self) -> None:
        broken = json.loads(json.dumps(_appearanceMapping_json(), ensure_ascii=False))
        broken["appearanceMapping"]["characters"][0]["canonical_name"] = ""
        broken["appearanceMapping"]["characters"][0]["default_name"] = ""

        normalized = normalize_appearanceMapping_candidate(broken)

        self.assertIsNotNone(normalized)
        repaired = normalized["appearanceMapping"]["characters"][0]
        self.assertEqual(repaired["canonical_name"], "linxia")
        self.assertEqual(repaired["default_name"], "linxia")
        self.assertEqual(
            validate_appearanceMapping_output(normalized["appearanceMapping"]),
            [],
        )

    def test_appearance_empty_h2kpLm91_uses_choices_json_object(self) -> None:
        client = _QueuedFastGPTClient(
            [
                {
                    "responseData": {
                        "newVariables": [
                            {"key": APPEARANCE_MAPPING_VAR, "value": ""},
                        ],
                    },
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    _appearanceMapping_json(),
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ],
                }
            ]
        )

        result = client.run_stage(
            STAGE_APPEARANCE_ALIAS_GENERATION,
            dict(self.appearance_variables),
        )

        self.assertEqual(client.request_count, 1)
        self.assertEqual(
            result[APPEARANCE_MAPPING]["characters"][0]["canonical_name"],
            "林夏",
        )
        debug_info = client.get_last_stage_debug_info(STAGE_APPEARANCE_ALIAS_GENERATION)
        self.assertTrue(debug_info.get("appearance_h2KpLm91_empty"))

    def test_appearance_empty_h2kpLm91_and_core_scene_text_requires_orchestrator_retry(self) -> None:
        client = _QueuedFastGPTClient(
            [
                {
                    "responseData": {
                        "newVariables": [
                            {"key": APPEARANCE_MAPPING_VAR, "value": ""},
                        ],
                        "answerNode": {
                            APPEARANCE_MAPPING_VAR: "核心场景：玻璃会议室、深夜办公区、合租公寓。"
                        },
                    }
                },
                {
                    "responseData": {
                        "answerNode": {
                            APPEARANCE_MAPPING_VAR: json.dumps(
                                _appearanceMapping_json(),
                                ensure_ascii=False,
                            )
                        }
                    },
                },
            ]
        )

        with self.assertRaises(FastGPTStageFormatError):
            client.run_stage(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                dict(self.appearance_variables),
            )

        self.assertEqual(client.request_count, 1)
        debug_info = client.get_last_stage_debug_info(STAGE_APPEARANCE_ALIAS_GENERATION)
        self.assertTrue(debug_info.get("appearance_h2KpLm91_empty"))
        summaries = list(debug_info.get("appearance_candidate_summaries") or [])
        self.assertTrue(
            any("核心场景" in str(item.get("reason") or "") for item in summaries)
        )

    def test_appearance_root_newvariables_beats_update_var_result_and_variable_update(self) -> None:
        preferred = _appearanceMapping_with_principle("FROM_ROOT_NEWVARIABLES")
        update_result = _appearanceMapping_with_principle("FROM_ROOT_UPDATEVARRESULT")
        variable_update = _appearanceMapping_with_principle("FROM_RESPONSE_VARIABLEUPDATE")

        result = self._extract(
            STAGE_APPEARANCE_ALIAS_GENERATION,
            {
                "newVariables": {
                    APPEARANCE_MAPPING_VAR: json.dumps(preferred, ensure_ascii=False)
                },
                "updateVarResult": {
                    APPEARANCE_MAPPING_VAR: json.dumps(update_result, ensure_ascii=False)
                },
                "responseData": {
                    "variableUpdate": {
                        APPEARANCE_MAPPING_VAR: json.dumps(
                            variable_update,
                            ensure_ascii=False,
                        )
                    }
                },
            },
        )

        self.assertEqual(
            result[APPEARANCE_MAPPING]["mapping_principle"],
            "FROM_ROOT_NEWVARIABLES",
        )

    def test_appearance_variable_update_beats_answer_node(self) -> None:
        variable_update = _appearanceMapping_with_principle("FROM_RESPONSE_VARIABLEUPDATE")
        answer_node = _appearanceMapping_with_principle("FROM_ANSWER_NODE")

        result = self._extract(
            STAGE_APPEARANCE_ALIAS_GENERATION,
            {
                "responseData": {
                    "variableUpdate": {
                        APPEARANCE_MAPPING_VAR: json.dumps(
                            variable_update,
                            ensure_ascii=False,
                        )
                    },
                    "answerNode": {
                        APPEARANCE_MAPPING_VAR: json.dumps(
                            answer_node,
                            ensure_ascii=False,
                        )
                    },
                }
            },
        )

        self.assertEqual(
            result[APPEARANCE_MAPPING]["mapping_principle"],
            "FROM_RESPONSE_VARIABLEUPDATE",
        )

    def test_appearance_answer_node_beats_choices(self) -> None:
        answer_node = _appearanceMapping_with_principle("FROM_ANSWER_NODE")
        choice_payload = _appearanceMapping_with_principle("FROM_CHOICES")

        result = self._extract(
            STAGE_APPEARANCE_ALIAS_GENERATION,
            {
                "responseData": {
                    "answerNode": {
                        APPEARANCE_MAPPING_VAR: json.dumps(
                            answer_node,
                            ensure_ascii=False,
                        )
                    }
                },
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                choice_payload,
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
            },
        )

        self.assertEqual(
            result[APPEARANCE_MAPPING]["mapping_principle"],
            "FROM_ANSWER_NODE",
        )

    def test_appearance_natural_language_is_not_formal_output(self) -> None:
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {"answerText": "林夏主要分为会议室交锋态和回家卸甲态，命名保持统一即可。"},
            )

    def test_appearance_review_json_is_not_formal_output(self) -> None:
        review_json = {"passed": False, "blocking_issues": ["alias_name 不统一"], "summary": "需要修订"}
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {"answerText": json.dumps(review_json, ensure_ascii=False)},
            )

    def test_appearance_plain_text_core_scene_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {
                    "responseData": {
                        "answerNode": {
                            APPEARANCE_MAPPING_VAR: "核心场景：玻璃会议室、深夜开放办公区、合租公寓玄关"
                        }
                    }
                },
            )

    def test_appearanceMapping_string_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {
                    "output": {
                        APPEARANCE_MAPPING: "林夏会议室交锋态",
                    }
                },
            )

    def test_appearance_scene_setting_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {"output": _scene_setting_json()},
            )

    def test_appearance_core_scene_final_var_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {
                    "responseData": {
                        "updateVarResult": [
                            {
                                "variable": ["VARIABLE_NODE_ID", CORE_SCENE_FINAL_VAR],
                                "value": "核心场景：玻璃会议室、深夜开放办公区、合租公寓玄关",
                            }
                        ]
                    }
                },
            )

    def test_appearance_auxiliary_natural_language_var_cannot_replace_mapping(self) -> None:
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {
                    "responseData": {
                        "updateVarResult": [
                            {
                                "variable": ["VARIABLE_NODE_ID", APPEARANCE_NATURAL_LANGUAGE_VAR],
                                "value": "林夏在会议室场景统一使用会议室交锋态，回家后切回卸甲状态。",
                            }
                        ]
                    }
                },
            )

    def test_appearance_missing_characters_fails(self) -> None:
        broken = json.loads(json.dumps(_appearanceMapping_json(), ensure_ascii=False))
        broken["appearanceMapping"].pop("characters", None)
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {"answerText": json.dumps(broken, ensure_ascii=False)},
            )

    def test_appearance_missing_outfit_variants_fails(self) -> None:
        broken = json.loads(json.dumps(_appearanceMapping_json(), ensure_ascii=False))
        broken["appearanceMapping"]["characters"][0].pop("outfit_variants", None)
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {"answerText": json.dumps(broken, ensure_ascii=False)},
            )

    def test_appearance_empty_outfit_variants_fails(self) -> None:
        broken = json.loads(json.dumps(_appearanceMapping_json(), ensure_ascii=False))
        broken["appearanceMapping"]["characters"][0]["outfit_variants"] = []
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {"answerText": json.dumps(broken, ensure_ascii=False)},
            )

    def test_appearance_alias_name_without_brackets_fails(self) -> None:
        broken = json.loads(json.dumps(_appearanceMapping_json(), ensure_ascii=False))
        broken["appearanceMapping"]["characters"][0]["outfit_variants"][0]["alias_name"] = "林夏会议室交锋态"
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {"answerText": json.dumps(broken, ensure_ascii=False)},
            )

    def test_appearance_scene_trigger_rules_must_be_object(self) -> None:
        broken = json.loads(json.dumps(_appearanceMapping_json(), ensure_ascii=False))
        broken["appearanceMapping"]["characters"][0]["outfit_variants"][0]["scene_trigger_rules"] = ["玻璃会议室"]
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {"answerText": json.dumps(broken, ensure_ascii=False)},
            )

    def test_appearance_string_booleans_fail(self) -> None:
        broken = json.loads(json.dumps(_appearanceMapping_json(), ensure_ascii=False))
        broken["appearanceMapping"]["characters"][0]["outfit_variants"][0]["must_use_when_triggered"] = "true"
        broken["appearanceMapping"]["characters"][0]["outfit_variants"][0]["fallback_allowed"] = "false"
        with self.assertRaises(ValueError):
            self._extract(
                STAGE_APPEARANCE_ALIAS_GENERATION,
                {"answerText": json.dumps(broken, ensure_ascii=False)},
            )

    def test_appearance_generation_runs_writing_review_unstructured_in_order(self) -> None:
        runner = _QueuedStageRunner(
            [
                {APPEARANCE_MAPPING: _appearanceMapping_json()},
                _appearance_review_json(
                    passed=True,
                    rewrite_required=False,
                ),
                {
                    APPEARANCE_NATURAL_LANGUAGE_VAR: "林夏在会议室与回家场景之间使用不同服装别名，但同一人物锚点保持一致。"
                },
            ]
        )
        state = WorkflowState.from_defaults(user_input=_workflow_input(), default_variables={})
        variables = dict(self.appearance_variables)
        original_characters = str(variables[CHARACTERS])
        original_scenes = str(variables[SCENES])
        state.variables.update(variables)

        _ensure_appearance_outputs(state, runner, variables)

        self.assertEqual(
            runner.stage_calls,
            [
                STAGE_APPEARANCE_ALIAS_WRITING,
                STAGE_APPEARANCE_ALIAS_REVIEW,
                STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
            ],
        )
        self.assertEqual(str(variables[CHARACTERS]), original_characters)
        self.assertEqual(str(variables[SCENES]), original_scenes)
        self.assertIsInstance(variables[APPEARANCE_MAPPING], dict)
        mapping = variables[APPEARANCE_MAPPING]["appearanceMapping"]
        self.assertEqual(
            mapping["characters"][0]["canonical_name"],
            "林夏",
        )
        self.assertIn(APPEARANCE_NATURAL_LANGUAGE_VAR, variables)
        stage_input = runner.variable_snapshots[0]
        self.assertIn('"same_person_traits"', str(stage_input[CHARACTERS]))
        self.assertNotIn("dramatic_function", str(stage_input[CHARACTERS]))
        self.assertIn('"scene_name":"玻璃会议室"', str(stage_input[SCENES]))
        self.assertNotIn("outfit_requirements", str(stage_input[SCENES]))

    def test_appearance_generation_retries_writing_stage_before_review_when_first_output_bad(self) -> None:
        settings.fastgpt_stage_format_retry_limit = 2
        runner = _QueuedStageRunner(
            [
                {APPEARANCE_NATURAL_LANGUAGE_VAR: "这只是自然语言说明，不是结构化映射。"},
                {APPEARANCE_MAPPING: _appearanceMapping_json()},
                _appearance_review_json(
                    passed=True,
                    rewrite_required=False,
                ),
                {
                    APPEARANCE_NATURAL_LANGUAGE_VAR: "林夏在会议室与回家场景之间使用不同服装别名，但同一人物锚点保持一致。"
                },
            ]
        )
        state = WorkflowState.from_defaults(user_input=_workflow_input(), default_variables={})
        variables = dict(self.appearance_variables)
        state.variables.update(variables)

        _ensure_appearance_outputs(state, runner, variables)

        self.assertEqual(
            runner.stage_calls,
            [
                STAGE_APPEARANCE_ALIAS_WRITING,
                STAGE_APPEARANCE_ALIAS_WRITING,
                STAGE_APPEARANCE_ALIAS_REVIEW,
                STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
            ],
        )
        self.assertEqual(
            variables[APPEARANCE_MAPPING]["appearanceMapping"]["characters"][0]["canonical_name"],
            "林夏",
        )
        artifact = state.get_output(STAGE_APPEARANCE_ALIAS_WRITING, "contract_guard", {})
        self.assertEqual(artifact.get("status"), "validated")

    def test_appearance_review_failure_triggers_rewrite_then_review(self) -> None:
        rewritten = _appearanceMapping_with_principle("REWRITTEN_AFTER_REVIEW")
        runner = _QueuedStageRunner(
            [
                {APPEARANCE_MAPPING: _appearanceMapping_json()},
                _appearance_review_json(
                    passed=False,
                    rewrite_required=True,
                    blocking_issues=["alias_name 需要统一"],
                ),
                {APPEARANCE_MAPPING: rewritten},
                _appearance_review_json(
                    passed=True,
                    rewrite_required=False,
                ),
                {
                    APPEARANCE_NATURAL_LANGUAGE_VAR: "修订后统一使用完整角色名加方括号版本名。"
                },
            ]
        )
        state = WorkflowState.from_defaults(user_input=_workflow_input(), default_variables={})
        variables = dict(self.appearance_variables)
        state.variables.update(variables)

        _ensure_appearance_outputs(state, runner, variables)

        self.assertEqual(
            runner.stage_calls,
            [
                STAGE_APPEARANCE_ALIAS_WRITING,
                STAGE_APPEARANCE_ALIAS_REVIEW,
                STAGE_APPEARANCE_ALIAS_REWRITE,
                STAGE_APPEARANCE_ALIAS_REVIEW,
                STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
            ],
        )
        self.assertEqual(
            variables[APPEARANCE_MAPPING]["appearanceMapping"]["mapping_principle"],
            "REWRITTEN_AFTER_REVIEW",
        )

    def test_appearance_runtime_messages_increment_review_rounds(self) -> None:
        rewritten = _appearanceMapping_with_principle("REWRITTEN_AFTER_REVIEW")
        runner = _QueuedStageRunner(
            [
                {APPEARANCE_MAPPING: _appearanceMapping_json()},
                _appearance_review_json(
                    passed=False,
                    rewrite_required=True,
                    blocking_issues=["alias_name 需要统一"],
                ),
                {APPEARANCE_MAPPING: rewritten},
                _appearance_review_json(
                    passed=True,
                    rewrite_required=False,
                ),
                {
                    APPEARANCE_NATURAL_LANGUAGE_VAR: "修订后统一使用完整角色名加方括号版本名。"
                },
            ]
        )
        state = WorkflowState.from_defaults(user_input=_workflow_input(), default_variables={})
        state.runtime = _RuntimeSpy()
        variables = dict(self.appearance_variables)
        state.variables.update(variables)

        _ensure_appearance_outputs(state, runner, variables)

        review_messages = [
            item["message"]
            for item in state.runtime.stage_messages
            if item["stage_key"] == STAGE_APPEARANCE_ALIAS_REVIEW
        ]
        rewrite_messages = [
            item["message"]
            for item in state.runtime.stage_messages
            if item["stage_key"] == STAGE_APPEARANCE_ALIAS_REWRITE
        ]
        self.assertIn("正在审核人物服装版本映射：第 1/10 轮", review_messages)
        self.assertIn("正在审核人物服装版本映射：第 2/10 轮", review_messages)
        self.assertIn("正在修订人物服装版本映射：第 1/10 轮", rewrite_messages)

    def test_appearance_stage_uses_compact_characters_and_scenes_without_overwriting_formal_outputs(self) -> None:
        runner = _QueuedStageRunner(
            [
                {APPEARANCE_MAPPING: _appearanceMapping_json()},
                _appearance_review_json(
                    passed=True,
                    rewrite_required=False,
                ),
                {
                    APPEARANCE_NATURAL_LANGUAGE_VAR: "林夏常态与会议室场景服装版本已整理为自然语言说明。"
                },
            ]
        )
        state = WorkflowState.from_defaults(user_input=_workflow_input(), default_variables={})
        variables = dict(self.appearance_variables)
        original_characters = str(variables[CHARACTERS])
        original_scenes = str(variables[SCENES])
        state.variables.update(variables)

        _ensure_appearance_outputs(state, runner, variables)

        self.assertEqual(str(variables[CHARACTERS]), original_characters)
        self.assertEqual(str(variables[SCENES]), original_scenes)
        self.assertEqual(runner.request_count, 3)
        stage_input = runner.variable_snapshots[0]
        self.assertIn('"same_person_traits"', str(stage_input[CHARACTERS]))
        self.assertNotIn("dramatic_function", str(stage_input[CHARACTERS]))
        self.assertIn('"scene_name":"玻璃会议室"', str(stage_input[SCENES]))
        self.assertNotIn("outfit_requirements", str(stage_input[SCENES]))

    def test_appearance_rewrite_review_limit_raises_without_cache_pollution(self) -> None:
        rewrite_payload = {APPEARANCE_MAPPING: _appearanceMapping_json()}
        responses: list[dict[str, object]] = [{APPEARANCE_MAPPING: _appearanceMapping_json()}]
        for _ in range(9):
            responses.append(
                _appearance_review_json(
                    passed=False,
                    rewrite_required=True,
                    blocking_issues=["blocking issue"],
                )
            )
            responses.append(rewrite_payload)
        responses.append(
            _appearance_review_json(
                passed=False,
                rewrite_required=True,
                blocking_issues=["blocking issue"],
            )
        )
        runner = _QueuedStageRunner(responses)
        state = WorkflowState.from_defaults(user_input=_workflow_input(), default_variables={})
        variables = dict(self.appearance_variables)
        state.variables.update(variables)

        with self.assertRaises(ValueError):
            _ensure_appearance_outputs(state, runner, variables)

        self.assertEqual(runner.request_count, 20)
        self.assertNotIn(APPEARANCE_MAPPING, variables)
        self.assertNotIn("character_registry", variables)
        self.assertNotIn("character_alias_registry", variables)
        self.assertNotIn("episode_alias_plan", variables)
        self.assertNotIn("appearance_continuity_memory", variables)
        self.assertNotIn(APPEARANCE_NATURAL_LANGUAGE_VAR, variables)
        self.assertNotIn(APPEARANCE_MAPPING, state.variables)
        self.assertNotIn("character_registry", state.variables)
        self.assertNotIn("character_alias_registry", state.variables)
        self.assertNotIn("episode_alias_plan", state.variables)
        self.assertNotIn("appearance_continuity_memory", state.variables)
        self.assertNotIn(APPEARANCE_NATURAL_LANGUAGE_VAR, state.variables)

    def test_appearance_broken_upstream_inputs_fail_without_stage_rerun(self) -> None:
        runner = _QueuedStageRunner([{APPEARANCE_MAPPING: _appearanceMapping_json()}])
        state = WorkflowState.from_defaults(user_input=_workflow_input(), default_variables={})
        variables = dict(self.appearance_variables)
        variables[WORLDVIEW] = ""
        state.variables.update(variables)

        with self.assertRaises(ValueError) as ctx:
            _ensure_appearance_outputs(state, runner, variables)

        self.assertIn("上游正式产物损坏", str(ctx.exception))
        self.assertEqual(runner.request_count, 0)
        self.assertNotIn(APPEARANCE_MAPPING, variables)
        self.assertNotIn(APPEARANCE_MAPPING, state.variables)

    def test_appearance_unstructured_failure_does_not_break_structured_output(self) -> None:
        runner = _QueuedStageRunner(
            [
                {APPEARANCE_MAPPING: _appearanceMapping_json()},
                _appearance_review_json(
                    passed=True,
                    rewrite_required=False,
                ),
                {APPEARANCE_MAPPING_VAR: json.dumps(_appearanceMapping_json(), ensure_ascii=False)},
            ]
        )
        state = WorkflowState.from_defaults(user_input=_workflow_input(), default_variables={})
        variables = dict(self.appearance_variables)
        state.variables.update(variables)

        _ensure_appearance_outputs(state, runner, variables)

        self.assertIsInstance(variables[APPEARANCE_MAPPING], dict)
        mapping = variables[APPEARANCE_MAPPING]["appearanceMapping"]
        self.assertEqual(
            mapping["characters"][0]["canonical_name"],
            "林夏",
        )
        self.assertNotIn(APPEARANCE_NATURAL_LANGUAGE_VAR, variables)

    def test_appearance_writing_simplified_mapping_repairs_and_passes(self) -> None:
        runner = _QueuedStageRunner(
            [
                {APPEARANCE_MAPPING: _simplified_appearanceMapping_json()},
                _appearance_review_json(
                    passed=True,
                    rewrite_required=False,
                ),
                {
                    APPEARANCE_NATURAL_LANGUAGE_VAR: "白雪公主常态优先使用“白雪公主【日常】”。"
                },
            ]
        )
        state = WorkflowState.from_defaults(user_input=_workflow_input(), default_variables={})
        variables = dict(self.appearance_variables)
        state.variables.update(variables)

        _ensure_appearance_outputs(state, runner, variables)

        mapping = variables[APPEARANCE_MAPPING]["appearanceMapping"]
        character = mapping["characters"][0]
        variant = character["outfit_variants"][0]
        self.assertEqual(character["story_role"], "关键角色")
        self.assertTrue(bool(character["character_id"]))
        self.assertEqual(character["default_name"], "白雪公主【日常】")
        self.assertEqual(variant["applicable_identity_state"], "日常")
        self.assertEqual(variant["episode_range_hint"], "按场景或状态触发")
        self.assertEqual(validate_appearanceMapping_output(mapping), [])

    def test_appearance_variant_scene_trigger_fields_migrate_from_top_level(self) -> None:
        normalized = normalize_appearanceMapping_candidate(_simplified_appearanceMapping_json())

        self.assertIsNotNone(normalized)
        variant = normalized["appearanceMapping"]["characters"][0]["outfit_variants"][0]
        self.assertEqual(variant["scene_trigger_rules"]["scene_names"], ["王宫走廊"])
        self.assertEqual(variant["scene_trigger_rules"]["scene_types"], ["宫廷"])
        self.assertEqual(variant["scene_trigger_rules"]["status_conditions"], ["常态"])
        self.assertEqual(variant["scene_trigger_rules"]["environment_or_time"], [])

    def test_appearance_auxiliary_natural_language_does_not_override_structured_output(self) -> None:
        client = _QueuedFastGPTClient(
            [
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    _appearanceMapping_json(),
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ],
                    "responseData": {
                        "updateVarResult": [
                            {
                                "variable": ["VARIABLE_NODE_ID", APPEARANCE_NATURAL_LANGUAGE_VAR],
                                "value": "林夏在会议室场景统一使用“林夏【会议室交锋态】”。",
                            }
                        ]
                    },
                }
            ]
        )
        result = client.run_stage(STAGE_APPEARANCE_ALIAS_GENERATION, dict(self.appearance_variables))
        self.assertIsInstance(result[APPEARANCE_MAPPING], dict)
        self.assertEqual(
            result[APPEARANCE_MAPPING]["characters"][0]["canonical_name"],
            "林夏",
        )
        self.assertEqual(
            result[APPEARANCE_NATURAL_LANGUAGE_VAR],
            "林夏在会议室场景统一使用“林夏【会议室交锋态】”。",
        )

    def test_appearance_default_name_empty_repairs_from_canonical_name(self) -> None:
        broken = json.loads(json.dumps(_appearanceMapping_json(), ensure_ascii=False))
        broken["appearanceMapping"]["characters"][0]["default_name"] = ""
        result = self._extract(
            STAGE_APPEARANCE_ALIAS_GENERATION,
            {"output": broken},
        )
        self.assertEqual(
            result[APPEARANCE_MAPPING]["characters"][0]["default_name"],
            result[APPEARANCE_MAPPING]["characters"][0]["canonical_name"],
        )


if __name__ == "__main__":
    unittest.main()
