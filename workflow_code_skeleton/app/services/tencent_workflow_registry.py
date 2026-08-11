from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


DEFAULT_TENCENT_ADP_API_URL = "https://wss.lke.cloud.tencent.com/adp/v2/chat"
DEFAULT_TENCENT_TIMEOUT_SECONDS = 600
DEFAULT_TENCENT_HTTP_RETRIES = 2
DEFAULT_TENCENT_HTTP_RETRY_DELAY_SECONDS = 1.5


@dataclass(frozen=True, slots=True)
class TencentWorkflowSpec:
    key: str
    label: str
    workflow_id: str
    api_key_env: str
    api_url_env: str
    input_sources: dict[str, tuple[str, ...]]
    response_fields: tuple[str, ...]

    @property
    def input_names(self) -> tuple[str, ...]:
        return tuple(self.input_sources)


def _sources(*names: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(name) for name in names if str(name).strip()))


TENCENT_WORKFLOWS: dict[str, TencentWorkflowSpec] = {
    "01": TencentWorkflowSpec(
        key="01",
        label="01 提取故事梗概",
        workflow_id="91d30e35-e3d5-490b-ae50-9fc10461048f",
        api_key_env="TENCENT_WORKFLOW_01_API_KEY",
        api_url_env="TENCENT_WORKFLOW_01_API_URL",
        input_sources={
            "source_title": _sources("source_title"),
            "target_format": _sources("target_format", "target_form"),
            "episode_number": _sources(
                "episode_number",
                "episodes_number",
                "total_episodes",
                "episodes_per_season",
            ),
            "mode": _sources("mode"),
            "chars_per_epi": _sources(
                "chars_per_epi",
                "episode_word_count",
                "chars_per_episode",
                "episodeWordCount",
            ),
            "adaptation_direction": _sources("adaptation_direction"),
            "user_constraints": _sources("user_constraints"),
            "source_text": _sources("source_text"),
            "user_requirements": _sources("user_requirements"),
        },
        response_fields=("confirmed_info",),
    ),
    "02": TencentWorkflowSpec(
        key="02",
        label="02 世界观",
        workflow_id="0457d68f-77c3-49af-9ca8-e37ccc727f54",
        api_key_env="TENCENT_WORKFLOW_02_API_KEY",
        api_url_env="TENCENT_WORKFLOW_02_API_URL",
        input_sources={
            "user_requirements": _sources("user_requirements"),
            "mode": _sources("mode"),
            "source_brief": _sources("source_brief"),
            "locked_basic_config": _sources("locked_basic_config", "basic_config"),
            "previous_worldview_plan": _sources(
                "previous_worldview_plan",
                "previous_worldview",
            ),
            "user_feedback": _sources("user_feedback"),
            "adaptation_direction": _sources("adaptation_direction"),
        },
        response_fields=("worldview",),
    ),
    "03": TencentWorkflowSpec(
        key="03",
        label="03 人设方案撰写",
        workflow_id="c49fdce1-64d3-42f9-9b9f-1f1ed6bde557",
        api_key_env="TENCENT_WORKFLOW_03_API_KEY",
        api_url_env="TENCENT_WORKFLOW_03_API_URL",
        input_sources={
            "user_requirements": _sources("user_requirements"),
            "mode": _sources("mode"),
            "source_brief": _sources("source_brief"),
            "locked_basic_config": _sources("locked_basic_config", "basic_config"),
            "worldview_plan": _sources("worldview_plan"),
            "previous_character_plan": _sources(
                "previous_character_plan",
                "previous_character",
            ),
            "user_feedback": _sources("user_feedback"),
            "adaptation_direction": _sources("adaptation_direction"),
        },
        response_fields=("character",),
    ),
    "04": TencentWorkflowSpec(
        key="04",
        label="04 三幕十五节拍生成",
        workflow_id="7c71e404-4638-410f-9430-55ac57afeb48",
        api_key_env="TENCENT_WORKFLOW_04_API_KEY",
        api_url_env="TENCENT_WORKFLOW_04_API_URL",
        input_sources={
            "user_requirements": _sources("user_requirements"),
            "mode": _sources("mode"),
            "source_brief": _sources("source_brief"),
            "basic_config": _sources("basic_config", "locked_basic_config"),
            "total_episodes": _sources(
                "total_episodes",
                "episodes_number",
            ),
            "worldview_plan": _sources("worldview_plan"),
            "character_plan": _sources("character_plan"),
            "previous_beat_checkpoint_timeline": _sources(
                "previous_beat_checkpoint_timeline",
                "previous_beat",
            ),
            "user_feedback": _sources("user_feedback"),
            "framework_score_report": _sources(
                "framework_score_report",
                "framework_score_repo",
            ),
            "adaptation_direction": _sources("adaptation_direction"),
            "keyword": _sources("keyword"),
        },
        response_fields=("beat",),
    ),
    "05": TencentWorkflowSpec(
        key="05",
        label="05 人物故事线整理",
        workflow_id="5e0cabab-9558-422d-a80b-1170d5302af7",
        api_key_env="TENCENT_WORKFLOW_05_API_KEY",
        api_url_env="TENCENT_WORKFLOW_05_API_URL",
        input_sources={
            "user_requirements": _sources("user_requirements"),
            "mode": _sources("mode"),
            "source_brief": _sources("source_brief"),
            "basic_config": _sources("basic_config"),
            "worldview_plan": _sources("worldview_plan"),
            "character_plan": _sources("character_plan"),
            "beat_checkpoint_timeline": _sources(
                "beat_checkpoint_timeline",
                "beat_checkpoint_time",
            ),
            "previous_character_storylines": _sources(
                "previous_character_storylines",
                "previous_character",
            ),
            "current_storyline_decisions": _sources(
                "current_storyline_decisions",
                "current_storyline",
                "storyline_decisions",
            ),
            "user_feedback": _sources("user_feedback"),
            "adaptation_direction": _sources("adaptation_direction"),
        },
        response_fields=("storyline",),
    ),
    "06": TencentWorkflowSpec(
        key="06",
        label="06 整体改编指引",
        workflow_id="dd14453e-2c85-4711-bc9c-934c3622a4bf",
        api_key_env="TENCENT_WORKFLOW_06_API_KEY",
        api_url_env="TENCENT_WORKFLOW_06_API_URL",
        input_sources={
            "user_requirements": _sources("user_requirements"),
            "mode": _sources("mode"),
            "source_brief": _sources("source_brief"),
            "basic_config": _sources("basic_config"),
            "worldview_plan": _sources("worldview_plan"),
            "character_plan": _sources("character_plan"),
            "beat_checkpoint_timeline": _sources(
                "beat_checkpoint_timeline",
                "beat_checkpoint_time",
            ),
            "character_storylines": _sources("character_storylines"),
            "storyline_decisions": _sources("storyline_decisions"),
            "previous_adaptation_guide": _sources(
                "previous_adaptation_guide",
                "previous_adaptation",
            ),
            "user_feedback": _sources("user_feedback"),
            "adaptation_direction": _sources("adaptation_direction"),
        },
        response_fields=("adaptation",),
    ),
    "07": TencentWorkflowSpec(
        key="07",
        label="07 最终框架策划包",
        workflow_id="56cd1923-67de-4f9d-a013-cf215e0d0208",
        api_key_env="TENCENT_WORKFLOW_07_API_KEY",
        api_url_env="TENCENT_WORKFLOW_07_API_URL",
        input_sources={
            "user_requirements": _sources("user_requirements"),
            "mode": _sources("mode"),
            "basic_config": _sources("basic_config"),
            "source_brief": _sources("source_brief"),
            "worldview_plan": _sources("worldview_plan"),
            "character_plan": _sources("character_plan"),
            "beat_checkpoint_timeline": _sources(
                "beat_checkpoint_timeline",
                "beat_checkpoint",
            ),
            "checkpoint_explanation": _sources(
                "checkpoint_explanation",
                "checkpoint_explain",
            ),
            "character_storylines": _sources("character_storylines"),
            "storyline_decisions": _sources("storyline_decisions"),
            "adaptation_guide": _sources("adaptation_guide"),
            "user_edit_history": _sources("user_edit_history"),
            "previous_framework_plan_package": _sources(
                "previous_framework_plan_package",
                "previous_framework",
            ),
            "user_feedback": _sources("user_feedback"),
            "adaptation_direction": _sources(
                "adaptation_direction",
                "adaption_direction",
            ),
        },
        response_fields=("framework",),
    ),
    "framework_scene_dictionary": TencentWorkflowSpec(
        key="08",
        label="08 场景字典提炼",
        workflow_id="fef0bf16-cd7b-4b60-94c6-94dcb92e6700",
        api_key_env="TENCENT_WORKFLOW_08_API_KEY",
        api_url_env="TENCENT_WORKFLOW_08_API_URL",
        input_sources={
            "framework": _sources("frameworkPlanPackage"),
            "worldview": _sources("worldviewPlan"),
            "beat": _sources("beatCheckpointTimeline"),
            "character_storyline": _sources("characterStorylines"),
            "user_feedback": _sources(
                "stagePreference",
                "stage_preference",
                "user_feedback",
                "user_requirements",
            ),
        },
        response_fields=("output",),
    ),
    "framework_appearanceMapping": TencentWorkflowSpec(
        key="09",
        label="09 人物服饰映射",
        workflow_id="6422e15e-7ad1-4c63-8e67-ab8ca68c316c",
        api_key_env="TENCENT_WORKFLOW_09_API_KEY",
        api_url_env="TENCENT_WORKFLOW_09_API_URL",
        input_sources={
            "character": _sources("characterPlan"),
            "scene": _sources("sceneDictionary"),
            "framework": _sources("frameworkPlanPackage"),
            "user_feedback": _sources(
                "stagePreference",
                "stage_preference",
                "user_feedback",
            ),
            "beat": _sources("beatCheckpointTimeline"),
        },
        response_fields=("alias",),
    ),
    "framework_enriched_episode_plan": TencentWorkflowSpec(
        key="10",
        label="10 丰富分集计划",
        workflow_id="6cf796dd-b496-4f56-848e-00660683441a",
        api_key_env="TENCENT_WORKFLOW_10_API_KEY",
        api_url_env="TENCENT_WORKFLOW_10_API_URL",
        input_sources={
            "framework": _sources("frameworkPlanPackage"),
            "scene": _sources("sceneDictionary"),
            "alias": _sources("appearanceMapping"),
            "user_feedback": _sources(
                "stagePreference",
                "stage_preference",
                "user_feedback",
            ),
        },
        response_fields=("episodeplan",),
    ),
    "framework_causal_conflict_write": TencentWorkflowSpec(
        key="11_01",
        label="11_01 开头冲突钩子撰写",
        workflow_id="4fe4f6c8-2bf5-4f4c-9906-facfdd35a21b",
        api_key_env="TENCENT_WORKFLOW_11_01_API_KEY",
        api_url_env="TENCENT_WORKFLOW_11_01_API_URL",
        input_sources={
            "episode_num": _sources("totalEpisodes"),
            "start_epi": _sources("conflictStartEpisode"),
            "enriched_epiplan": _sources("batchEnrichedEpisodePlan"),
            "scene": _sources("sceneDictionary"),
            "worldview": _sources("scriptWorldRulesDigest", "worldviewPlan"),
            "alias": _sources("appearanceMapping"),
            "memory": _sources("conflictMemory"),
            "user_feedback": _sources(
                "stagePreference",
                "stage_preference",
                "user_feedback",
            ),
        },
        response_fields=("conflicts",),
    ),
    "framework_causal_conflict_review": TencentWorkflowSpec(
        key="11_02",
        label="11_02 开头冲突钩子审核",
        workflow_id="9ce79973-3751-499b-8e71-11cb96823ca1",
        api_key_env="TENCENT_WORKFLOW_11_02_API_KEY",
        api_url_env="TENCENT_WORKFLOW_11_02_API_URL",
        input_sources={
            "episode_num": _sources("totalEpisodes"),
            "start_epi": _sources("conflictStartEpisode"),
            "enriched_epiplan": _sources("batchEnrichedEpisodePlan"),
            "scene": _sources("sceneDictionary"),
            "worldview": _sources("scriptWorldRulesDigest", "worldviewPlan"),
            "alias": _sources("appearanceMapping"),
            "memory": _sources("conflictMemory"),
            "user_feedback": _sources(
                "stagePreference",
                "stage_preference",
                "user_feedback",
            ),
            "conflict": _sources("batchCausalConflictPlan"),
        },
        response_fields=("conflictreview",),
    ),
    "framework_causal_conflict_rewrite": TencentWorkflowSpec(
        key="11_03",
        label="11_03 开头冲突钩子修订",
        workflow_id="b3efa12d-1ce0-41c3-bf13-c267b8aaab09",
        api_key_env="TENCENT_WORKFLOW_11_03_API_KEY",
        api_url_env="TENCENT_WORKFLOW_11_03_API_URL",
        input_sources={
            "episode_num": _sources("totalEpisodes"),
            "start_epi": _sources("conflictStartEpisode"),
            "enriched_epiplan": _sources("batchEnrichedEpisodePlan"),
            "scene": _sources("sceneDictionary"),
            "alias": _sources("appearanceMapping"),
            "memory": _sources("conflictMemory"),
            "user_feedback": _sources(
                "stagePreference",
                "stage_preference",
                "user_feedback",
            ),
            "feedback": _sources(
                "stagePreference",
                "stage_preference",
                "user_feedback",
            ),
            "conflict": _sources("batchCausalConflictPlan"),
            "review": _sources("batchCausalConflictReview"),
        },
        response_fields=("rewrite",),
    ),
    "framework_causal_conflict_memory": TencentWorkflowSpec(
        key="11_04",
        label="11_04 开头冲突钩子记忆",
        workflow_id="7ec26d96-b8dc-4735-a294-1225f11cbe56",
        api_key_env="TENCENT_WORKFLOW_11_04_API_KEY",
        api_url_env="TENCENT_WORKFLOW_11_04_API_URL",
        input_sources={
            "conflict": _sources("batchCausalConflictPlan"),
            "start_epi": _sources("conflictStartEpisode"),
        },
        response_fields=("memory",),
    ),
    "framework_script_write": TencentWorkflowSpec(
        key="12_01",
        label="12_01 剧本正文撰写",
        workflow_id="d4ce909f-5cd3-4481-83af-79221cded913",
        api_key_env="TENCENT_WORKFLOW_12_01_API_KEY",
        api_url_env="TENCENT_WORKFLOW_12_01_API_URL",
        input_sources={
            "episode_num": _sources("totalEpisodes"),
            "start_epi": _sources("scriptStartEpisode"),
            # 腾讯工作流把该字段命名为 character_count，但其值就是每集目标字数。
            "character_count": _sources("episodeWordCount", "episode_word_count"),
            "according_conflict": _sources("batchCausalConflictPlan"),
            "according_epiplan": _sources("batchEnrichedEpisodePlan"),
            "worldview": _sources("scriptWorldRulesDigest", "worldviewPlan"),
            "alias": _sources("appearanceMapping"),
            "memory": _sources("scriptMemory"),
            "user_feedback": _sources(
                "stagePreference",
                "stage_preference",
                "user_feedback",
            ),
        },
        response_fields=("script",),
    ),
    "framework_script_review": TencentWorkflowSpec(
        key="12_02",
        label="12_02 剧本正文审核",
        workflow_id="f57d1e32-37af-41c9-b1cb-d680217f80b4",
        api_key_env="TENCENT_WORKFLOW_12_02_API_KEY",
        api_url_env="TENCENT_WORKFLOW_12_02_API_URL",
        input_sources={
            "episode_num": _sources("totalEpisodes"),
            "start_epi": _sources("scriptStartEpisode"),
            "character_count": _sources("episodeWordCount", "episode_word_count"),
            "according_conflict": _sources("batchCausalConflictPlan"),
            "according_epiplan": _sources("batchEnrichedEpisodePlan"),
            "memory": _sources("scriptMemory"),
            "user_feedback": _sources(
                "stagePreference",
                "stage_preference",
                "user_feedback",
            ),
            "script": _sources("batchScriptText"),
        },
        response_fields=("scriptreview",),
    ),
    "framework_script_rewrite": TencentWorkflowSpec(
        key="12_03",
        label="12_03 剧本正文修订",
        workflow_id="90b84dd6-f9bc-4342-9f7c-2bd7d257f6fe",
        api_key_env="TENCENT_WORKFLOW_12_03_API_KEY",
        api_url_env="TENCENT_WORKFLOW_12_03_API_URL",
        input_sources={
            "episode_num": _sources("totalEpisodes"),
            "start_epi": _sources("scriptStartEpisode"),
            "character_count": _sources("episodeWordCount", "episode_word_count"),
            "according_conflict": _sources("batchCausalConflictPlan"),
            "according_epiplan": _sources("batchEnrichedEpisodePlan"),
            "worldview": _sources("scriptWorldRulesDigest", "worldviewPlan"),
            "alias": _sources("appearanceMapping"),
            "memory": _sources("scriptMemory"),
            "user_feedback": _sources(
                "stagePreference",
                "stage_preference",
                "user_feedback",
            ),
            "current_script": _sources("batchScriptText"),
            "current_review": _sources("batchScriptReview"),
        },
        response_fields=("script",),
    ),
    "framework_script_memory": TencentWorkflowSpec(
        key="12_04",
        label="12_04 剧本正文记忆",
        workflow_id="8ac496c6-bcfb-4c98-bfdd-74e016b471fd",
        api_key_env="TENCENT_WORKFLOW_12_04_API_KEY",
        api_url_env="TENCENT_WORKFLOW_12_04_API_URL",
        input_sources={
            "script": _sources("batchScriptText"),
        },
        response_fields=("memory",),
    ),
}


def workflow_spec(stage_name: str) -> TencentWorkflowSpec:
    key = str(stage_name or "").strip()
    spec = TENCENT_WORKFLOWS.get(key)
    if spec is None:
        raise ValueError(f"未配置腾讯工作流阶段：{stage_name}")
    return spec


def first_present_value(variables: dict[str, Any], source_names: tuple[str, ...]) -> Any:
    for source_name in source_names:
        if source_name not in variables:
            continue
        value = variables[source_name]
        if value not in (None, "", [], {}):
            return value
    for source_name in source_names:
        if source_name in variables:
            return variables[source_name]
    return ""


def build_workflow_inputs(stage_name: str, variables: dict[str, Any]) -> dict[str, str]:
    spec = workflow_spec(stage_name)
    return {
        input_name: _as_custom_variable(
            first_present_value(variables, source_names),
        )
        for input_name, source_names in spec.input_sources.items()
    }


def api_key_for(stage_name: str) -> tuple[str, str]:
    spec = workflow_spec(stage_name)
    value = str(os.getenv(spec.api_key_env) or "").strip()
    return spec.api_key_env, value


def api_url_for(stage_name: str) -> tuple[str, str]:
    spec = workflow_spec(stage_name)
    if value := str(os.getenv(spec.api_url_env) or "").strip():
        return spec.api_url_env, value
    if value := str(os.getenv("TENCENT_ADP_API_URL") or "").strip():
        return "TENCENT_ADP_API_URL", value
    return "default", DEFAULT_TENCENT_ADP_API_URL


def timeout_seconds() -> int:
    return _non_negative_int("TENCENT_WORKFLOW_TIMEOUT_SECONDS", DEFAULT_TENCENT_TIMEOUT_SECONDS)


def http_retries() -> int:
    return _non_negative_int("TENCENT_WORKFLOW_HTTP_RETRIES", DEFAULT_TENCENT_HTTP_RETRIES)


def retry_delay_seconds() -> float:
    raw = str(os.getenv("TENCENT_WORKFLOW_HTTP_RETRY_DELAY_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_TENCENT_HTTP_RETRY_DELAY_SECONDS
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_TENCENT_HTTP_RETRY_DELAY_SECONDS


def _as_custom_variable(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _non_negative_int(name: str, default: int) -> int:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return int(default)
