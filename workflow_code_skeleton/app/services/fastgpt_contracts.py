from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..workflow_ids import (
    CHARACTER_BIOS_VAR,
    CHARACTER_MAX_RETRY_VAR,
    CHARACTER_VAR,
    CORE_SCENE_FINAL_VAR,
    CORE_SCENE_INPUT_VAR,
    DIALOGUE_CURRENT_VAR,
    DIALOGUE_FINAL_VAR,
    DIALOGUE_START_VAR,
    DIALOGUE_MAX_RETRY_VAR,
    EPISODE_PLAN_VAR,
    EPISODE_PLAN_NORMALIZED_VAR,
    EPISODE_WORD_COUNT_VAR,
    FINAL_CHARACTER_VAR,
    FINAL_SCENE_VAR,
    FRAMEWORK_CHARACTER_BIOS_VAR,
    FRAMEWORK_CHARACTER_COUNT_VAR,
    FRAMEWORK_CORE_SCENE_VAR,
    FRAMEWORK_EPISODE_PLAN_VAR,
    FRAMEWORK_TITLE_VAR,
    FRAMEWORK_TOTAL_EPISODES_VAR,
    FRAMEWORK_STORY_OUTLINE_VAR,
    FRAMEWORK_USER_EXPECTATION_VAR,
    HOOK_CURRENT_VAR,
    HOOK_FINAL_VAR,
    HOOK_START_VAR,
    HOOK_MAX_RETRY_VAR,
    MEMORY_VAR,
    SCENE_MAX_RETRY_VAR,
    SCENE_VAR,
    SCRIPT_CURRENT_VAR,
    SCRIPT_FINAL_VAR,
    SCRIPT_START_VAR,
    SCRIPT_MAX_RETRY_VAR,
    STORY_OUTLINE_VAR,
    TITLE_VAR,
    TOTAL_EPISODES_VAR,
    WORLDVIEW_MAX_RETRY_VAR,
    WORLDVIEW_VAR,
)
from .json_utils import parse_json

SCRIPT_TITLE = "script_title"
TOTAL_EPISODES = "total_episodes"
EPISODE_WORD_COUNT = "episode_word_count"
USER_EXPECTATION = "user_expectation"
CHARACTER_COUNT = "character_count"
EPISODE_PLAN = "episode_plan"
STORY_OUTLINE = "story_outline"
USER_SCENES = "user_scenes"
USER_CHARACTERS = "user_characters"
USER_CONTENT_BASELINE = "user_content_baseline"
MAX_RETRIES = "max_retries"
WORLDVIEW = "worldview"
CHARACTERS = "characters"
SCENES = "scenes"
BATCH_HOOKS = "batch_hooks"
ALL_HOOKS = "all_hooks"
BATCH_DIALOGUES = "batch_dialogues"
ALL_DIALOGUES = "all_dialogues"
BATCH_SCRIPT = "batch_script"
ALL_SCRIPT = "all_script"
LAST_SUMMARY = "last_summary"
FINAL_SCRIPT = "final_script"
IS_CONSISTENT = "is_consistent"
BATCH_START_EPISODE = "batch_start_episode"
NORMALIZED_EPISODE_PLAN = "normalized_episode_plan"

STAGE_FRAMEWORK = "framework"
STAGE_CONSISTENCY = "consistency"
STAGE_EPISODE_PLAN_NORMALIZE = "episode_plan_normalize"
STAGE_WORLDVIEW = "worldview"
STAGE_CHARACTERS = "characters"
STAGE_SCENES = "scenes"
STAGE_HOOKS = "hooks"
STAGE_DIALOGUES = "dialogues"
STAGE_SCRIPT = "script"
STAGE_MEMORY = "memory"
STAGE_FINAL = "final"


@dataclass(frozen=True, slots=True)
class FastGPTVariable:
    name: str
    type_name: str
    description: str
    source: str


@dataclass(frozen=True, slots=True)
class FastGPTStageContract:
    stage_name: str
    label: str
    input_names: tuple[str, ...]
    output_types: dict[str, str]
    fastgpt_responsibility: str
    local_responsibility: str

    @property
    def output_names(self) -> tuple[str, ...]:
        return tuple(self.output_types.keys())

    def build_input_payload(self, variables: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        missing: list[str] = []
        for name in self.input_names:
            if name in variables:
                payload[name] = variables[name]
            elif name == LAST_SUMMARY:
                payload[name] = ""
            elif name in {ALL_HOOKS, ALL_DIALOGUES}:
                payload[name] = {}
            else:
                missing.append(name)
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"FastGPT 阶段 {self.stage_name} 缺少输入变量：{joined}")
        return payload

    def validate_output_payload(self, output: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        missing: list[str] = []
        for name, type_name in self.output_types.items():
            if name not in output:
                missing.append(name)
                continue
            normalized[name] = coerce_fastgpt_value(output[name], type_name)
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"FastGPT 阶段 {self.stage_name} 缺少输出变量：{joined}")
        return normalized


GLOBAL_VARIABLES: dict[str, FastGPTVariable] = {
    TOTAL_EPISODES: FastGPTVariable(
        TOTAL_EPISODES,
        "number",
        "总集数",
        "用户输入",
    ),
    EPISODE_PLAN: FastGPTVariable(
        EPISODE_PLAN,
        "string",
        "用户分集计划。consistency/worldview 阶段传原始全文；hooks/dialogues/script 阶段传当前批次规范化 JSON 字符串。",
        "用户输入/本地批次裁剪",
    ),
    USER_EXPECTATION: FastGPTVariable(
        USER_EXPECTATION,
        "string",
        "用户对剧本的期待/想要的故事。",
        "用户输入",
    ),
    CHARACTER_COUNT: FastGPTVariable(
        CHARACTER_COUNT,
        "number",
        "角色数量。",
        "用户输入",
    ),
    NORMALIZED_EPISODE_PLAN: FastGPTVariable(
        NORMALIZED_EPISODE_PLAN,
        "object",
        "代码侧保存的规范化分集计划对象。",
        "FastGPT 输出/本地缓存",
    ),
    STORY_OUTLINE: FastGPTVariable(
        STORY_OUTLINE,
        "string",
        "故事大纲。当前可由框架阶段先生成，也兼容用户直传。",
        "框架阶段输出/用户输入兼容",
    ),
    USER_SCENES: FastGPTVariable(
        USER_SCENES,
        "string",
        "核心场景。当前可由框架阶段先生成，也兼容用户直传。",
        "框架阶段输出/用户输入兼容",
    ),
    USER_CHARACTERS: FastGPTVariable(
        USER_CHARACTERS,
        "string",
        "人物小传。当前可由框架阶段先生成，也兼容用户直传。",
        "框架阶段输出/用户输入兼容",
    ),
    SCRIPT_TITLE: FastGPTVariable(
        SCRIPT_TITLE,
        "string",
        "剧本标题。优先使用框架阶段生成标题；若缺失，再回退到本地基于用户期待生成的标题。",
        "框架阶段输出/本地回退",
    ),
    WORLDVIEW: FastGPTVariable(
        WORLDVIEW,
        "string",
        "生成的世界观内容",
        "FastGPT 输出",
    ),
    CHARACTERS: FastGPTVariable(
        CHARACTERS,
        "string",
        "生成的人设内容",
        "FastGPT 输出",
    ),
    SCENES: FastGPTVariable(
        SCENES,
        "string",
        "生成的核心场景内容",
        "FastGPT 输出",
    ),
    BATCH_HOOKS: FastGPTVariable(
        BATCH_HOOKS,
        "object",
        "当前批次 5 集的开头冲突钩子 JSON",
        "FastGPT 输出",
    ),
    ALL_HOOKS: FastGPTVariable(
        ALL_HOOKS,
        "object",
        "完整开头冲突钩子 JSON",
        "本地拼接",
    ),
    BATCH_DIALOGUES: FastGPTVariable(
        BATCH_DIALOGUES,
        "object",
        "当前批次 5 集的角色对话 JSON",
        "FastGPT 输出",
    ),
    ALL_DIALOGUES: FastGPTVariable(
        ALL_DIALOGUES,
        "object",
        "完整角色对话 JSON",
        "本地拼接",
    ),
    BATCH_SCRIPT: FastGPTVariable(
        BATCH_SCRIPT,
        "string",
        "当前批次 5 集的剧本正文",
        "FastGPT 输出",
    ),
    ALL_SCRIPT: FastGPTVariable(
        ALL_SCRIPT,
        "string",
        "完整剧本正文",
        "本地拼接",
    ),
    LAST_SUMMARY: FastGPTVariable(
        LAST_SUMMARY,
        "string",
        "最近一次剧本摘要，覆盖式保存",
        "FastGPT 输出/本地覆盖",
    ),
    FINAL_SCRIPT: FastGPTVariable(
        FINAL_SCRIPT,
        "string",
        "最终完整剧本",
        "FastGPT 输出",
    ),
    IS_CONSISTENT: FastGPTVariable(
        IS_CONSISTENT,
        "boolean",
        "集数一致性检查结果",
        "FastGPT 输出",
    ),
    EPISODE_WORD_COUNT: FastGPTVariable(
        EPISODE_WORD_COUNT,
        "number",
        "每集正文字数。仅当前 legacy FastGPT 剧本正文工作流需要。",
        "用户输入",
    ),
    USER_CONTENT_BASELINE: FastGPTVariable(
        USER_CONTENT_BASELINE,
        "string",
        "用户内容提取基准 JSON。仅当前 legacy FastGPT 工作流需要。",
        "本地整理",
    ),
    MAX_RETRIES: FastGPTVariable(
        MAX_RETRIES,
        "number",
        "FastGPT 内部审核修订最大轮次。仅当前 legacy 工作流需要。",
        "本地配置",
    ),
    BATCH_START_EPISODE: FastGPTVariable(
        BATCH_START_EPISODE,
        "number",
        "当前批次起始集数。仅传给当前 legacy 批处理智能体，用于约束从第几集开始。",
        "本地批次控制",
    ),
}


LEGACY_INPUT_ALIASES: dict[str, dict[str, str]] = {
    STAGE_FRAMEWORK: {
        TOTAL_EPISODES: FRAMEWORK_TOTAL_EPISODES_VAR,
        USER_EXPECTATION: FRAMEWORK_USER_EXPECTATION_VAR,
        CHARACTER_COUNT: FRAMEWORK_CHARACTER_COUNT_VAR,
    },
    STAGE_CONSISTENCY: {
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
    },
    STAGE_EPISODE_PLAN_NORMALIZE: {
        EPISODE_PLAN: EPISODE_PLAN_VAR,
    },
    STAGE_WORLDVIEW: {
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        USER_SCENES: CORE_SCENE_INPUT_VAR,
        USER_CHARACTERS: CHARACTER_BIOS_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        MAX_RETRIES: WORLDVIEW_MAX_RETRY_VAR,
    },
    STAGE_CHARACTERS: {
        WORLDVIEW: WORLDVIEW_VAR,
        USER_CHARACTERS: CHARACTER_BIOS_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        USER_CONTENT_BASELINE: "userContentBaselineJson",
        MAX_RETRIES: CHARACTER_MAX_RETRY_VAR,
    },
    STAGE_SCENES: {
        WORLDVIEW: WORLDVIEW_VAR,
        USER_CONTENT_BASELINE: "userContentBaselineJson",
        USER_SCENES: CORE_SCENE_INPUT_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        USER_CHARACTERS: CHARACTER_BIOS_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        MAX_RETRIES: SCENE_MAX_RETRY_VAR,
    },
    STAGE_HOOKS: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        BATCH_START_EPISODE: HOOK_START_VAR,
        ALL_HOOKS: HOOK_FINAL_VAR,
        MAX_RETRIES: HOOK_MAX_RETRY_VAR,
    },
    STAGE_DIALOGUES: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        SCENES: SCENE_VAR,
        ALL_HOOKS: HOOK_FINAL_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        BATCH_START_EPISODE: DIALOGUE_START_VAR,
        ALL_DIALOGUES: DIALOGUE_FINAL_VAR,
        MAX_RETRIES: DIALOGUE_MAX_RETRY_VAR,
    },
    STAGE_SCRIPT: {
        WORLDVIEW: WORLDVIEW_VAR,
        CHARACTERS: CHARACTER_VAR,
        ALL_HOOKS: HOOK_FINAL_VAR,
        ALL_DIALOGUES: DIALOGUE_FINAL_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        EPISODE_PLAN: EPISODE_PLAN_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        EPISODE_WORD_COUNT: EPISODE_WORD_COUNT_VAR,
        LAST_SUMMARY: MEMORY_VAR,
        BATCH_START_EPISODE: SCRIPT_START_VAR,
        ALL_SCRIPT: SCRIPT_FINAL_VAR,
        MAX_RETRIES: SCRIPT_MAX_RETRY_VAR,
    },
    STAGE_MEMORY: {
        BATCH_SCRIPT: SCRIPT_CURRENT_VAR,
        LAST_SUMMARY: MEMORY_VAR,
    },
    STAGE_FINAL: {
        SCRIPT_TITLE: TITLE_VAR,
        TOTAL_EPISODES: TOTAL_EPISODES_VAR,
        STORY_OUTLINE: STORY_OUTLINE_VAR,
        CHARACTERS: FINAL_CHARACTER_VAR,
        SCENES: FINAL_SCENE_VAR,
        ALL_SCRIPT: SCRIPT_FINAL_VAR,
    },
}


LEGACY_OUTPUT_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    STAGE_FRAMEWORK: {
        SCRIPT_TITLE: (FRAMEWORK_TITLE_VAR,),
        STORY_OUTLINE: (FRAMEWORK_STORY_OUTLINE_VAR,),
        USER_CHARACTERS: (FRAMEWORK_CHARACTER_BIOS_VAR,),
        USER_SCENES: (FRAMEWORK_CORE_SCENE_VAR,),
        EPISODE_PLAN: (FRAMEWORK_EPISODE_PLAN_VAR,),
    },
    STAGE_EPISODE_PLAN_NORMALIZE: {
        NORMALIZED_EPISODE_PLAN: (EPISODE_PLAN_NORMALIZED_VAR,),
    },
    STAGE_WORLDVIEW: {WORLDVIEW: (WORLDVIEW_VAR,)},
    STAGE_CHARACTERS: {CHARACTERS: (CHARACTER_VAR,)},
    STAGE_SCENES: {SCENES: (CORE_SCENE_FINAL_VAR, SCENE_VAR)},
    STAGE_HOOKS: {BATCH_HOOKS: (HOOK_CURRENT_VAR, HOOK_FINAL_VAR)},
    STAGE_DIALOGUES: {BATCH_DIALOGUES: (DIALOGUE_CURRENT_VAR, DIALOGUE_FINAL_VAR)},
    STAGE_SCRIPT: {BATCH_SCRIPT: (SCRIPT_CURRENT_VAR, SCRIPT_FINAL_VAR)},
    STAGE_MEMORY: {LAST_SUMMARY: (MEMORY_VAR,)},
    STAGE_FINAL: {FINAL_SCRIPT: (SCRIPT_FINAL_VAR,)},
}


STAGE_CONTRACTS: dict[str, FastGPTStageContract] = {
    STAGE_FRAMEWORK: FastGPTStageContract(
        stage_name=STAGE_FRAMEWORK,
        label="剧本框架撰写",
        input_names=(TOTAL_EPISODES, USER_EXPECTATION, CHARACTER_COUNT),
        output_types={
            SCRIPT_TITLE: "string",
            STORY_OUTLINE: "string",
            USER_CHARACTERS: "string",
            USER_SCENES: "string",
            EPISODE_PLAN: "string",
        },
        fastgpt_responsibility="根据用户期待、角色数量和总集数，生成剧本标题、故事大纲、人物小传、核心场景、分集计划。",
        local_responsibility="缓存并复用五项框架产物，后续阶段统一读取这些结果。",
    ),
    STAGE_CONSISTENCY: FastGPTStageContract(
        stage_name=STAGE_CONSISTENCY,
        label="集数一致性检查",
        input_names=(TOTAL_EPISODES, EPISODE_PLAN),
        output_types={IS_CONSISTENT: "boolean"},
        fastgpt_responsibility="判断分集计划与总集数是否一致。",
        local_responsibility="不做内容判断，只根据布尔结果继续或停止。",
    ),
    STAGE_EPISODE_PLAN_NORMALIZE: FastGPTStageContract(
        stage_name=STAGE_EPISODE_PLAN_NORMALIZE,
        label="分集计划规范化",
        input_names=(EPISODE_PLAN,),
        output_types={NORMALIZED_EPISODE_PLAN: "object"},
        fastgpt_responsibility="只把原始分集计划整理成结构化 JSON，不做改写、润色、摘要或扩写。",
        local_responsibility="缓存规范化结果，后续批处理阶段只读取当前批次需要的集数。",
    ),
    STAGE_WORLDVIEW: FastGPTStageContract(
        stage_name=STAGE_WORLDVIEW,
        label="世界观生成与审核",
        input_names=(STORY_OUTLINE, USER_SCENES, USER_CHARACTERS, EPISODE_PLAN),
        output_types={WORLDVIEW: "string"},
        fastgpt_responsibility="完成世界观提取、生成、审核、修订，返回最终可用世界观。",
        local_responsibility="不做业务审核循环，只校验 worldview 是否按契约返回并缓存。",
    ),
    STAGE_CHARACTERS: FastGPTStageContract(
        stage_name=STAGE_CHARACTERS,
        label="人物设定生成与审核",
        input_names=(USER_CHARACTERS, WORLDVIEW),
        output_types={CHARACTERS: "string"},
        fastgpt_responsibility="完成人设生成、审核、修订、整理。",
        local_responsibility="不做业务审核循环，只校验 characters 是否按契约返回并缓存。",
    ),
    STAGE_SCENES: FastGPTStageContract(
        stage_name=STAGE_SCENES,
        label="核心场景生成与审核",
        input_names=(USER_SCENES, WORLDVIEW),
        output_types={SCENES: "string"},
        fastgpt_responsibility="完成核心场景提炼/复用、生成、审核、修订、整理。",
        local_responsibility="不做业务审核循环，只校验 scenes 是否按契约返回并缓存。",
    ),
    STAGE_HOOKS: FastGPTStageContract(
        stage_name=STAGE_HOOKS,
        label="开头冲突钩子批处理",
        input_names=(
            WORLDVIEW,
            CHARACTERS,
            EPISODE_PLAN,
            TOTAL_EPISODES,
            LAST_SUMMARY,
            BATCH_START_EPISODE,
        ),
        output_types={BATCH_HOOKS: "object"},
        fastgpt_responsibility="生成当前批次 5 集的开头冲突钩子 JSON。",
        local_responsibility="划分批次、裁剪 episode_plan、拼接 all_hooks、推进批次。",
    ),
    STAGE_DIALOGUES: FastGPTStageContract(
        stage_name=STAGE_DIALOGUES,
        label="角色对话批处理",
        input_names=(
            CHARACTERS,
            EPISODE_PLAN,
            TOTAL_EPISODES,
            LAST_SUMMARY,
            BATCH_START_EPISODE,
        ),
        output_types={BATCH_DIALOGUES: "object"},
        fastgpt_responsibility="生成当前批次 5 集的角色对话 JSON。",
        local_responsibility="划分批次、裁剪 episode_plan、拼接 all_dialogues、推进批次。",
    ),
    STAGE_SCRIPT: FastGPTStageContract(
        stage_name=STAGE_SCRIPT,
        label="剧本正文批处理",
        input_names=(
            WORLDVIEW,
            ALL_HOOKS,
            ALL_DIALOGUES,
            EPISODE_PLAN,
            TOTAL_EPISODES,
            LAST_SUMMARY,
            BATCH_START_EPISODE,
        ),
        output_types={BATCH_SCRIPT: "string"},
        fastgpt_responsibility="生成当前批次 5 集剧本正文。",
        local_responsibility="划分批次、裁剪 episode_plan、拼接 all_script、推进批次。",
    ),
    STAGE_MEMORY: FastGPTStageContract(
        stage_name=STAGE_MEMORY,
        label="正文记忆整理",
        input_names=(BATCH_SCRIPT,),
        output_types={LAST_SUMMARY: "string"},
        fastgpt_responsibility="把当前批次正文整理成下一批可用的摘要。",
        local_responsibility="用新 last_summary 覆盖旧 last_summary，不保存历史。",
    ),
    STAGE_FINAL: FastGPTStageContract(
        stage_name=STAGE_FINAL,
        label="最终剧本拼接",
        input_names=(
            SCRIPT_TITLE,
            TOTAL_EPISODES,
            STORY_OUTLINE,
            CHARACTERS,
            SCENES,
            ALL_SCRIPT,
        ),
        output_types={FINAL_SCRIPT: "string"},
        fastgpt_responsibility="输出最终完整剧本。",
        local_responsibility="无额外内容生成，只接收 final_script。",
    ),
}


def contract_for(stage_name: str) -> FastGPTStageContract:
    try:
        return STAGE_CONTRACTS[stage_name]
    except KeyError as exc:
        raise ValueError(f"未知 FastGPT 阶段：{stage_name}") from exc


def coerce_fastgpt_value(value: Any, type_name: str) -> Any:
    if type_name == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)

        if isinstance(value, dict):
            for key in ("is_consistent", "passed", "approved", "consistent"):
                if key in value:
                    return coerce_fastgpt_value(value[key], "boolean")

        text = str(value or "").strip()
        try:
            parsed = parse_json(text)
            if parsed is not value:
                return coerce_fastgpt_value(parsed, "boolean")
        except Exception:
            pass

        lowered = text.lower()
        compact = "".join(lowered.split())
        if compact in {"true", "truetrue", "yes", "y", "1", "是", "通过", "一致"}:
            return True
        if compact in {"false", "falsefalse", "no", "n", "0", "否", "不通过", "不一致"}:
            return False

        negative_tokens = (
            "false",
            "不一致",
            "不通过",
            "未通过",
            "否",
            "不符合",
            "不匹配",
            "inconsistent",
            "not consistent",
            "failed",
        )
        positive_tokens = (
            "true",
            "一致",
            "通过",
            "符合",
            "匹配",
            "consistent",
            "passed",
        )
        has_negative = any(token in lowered for token in negative_tokens)
        has_positive = any(token in lowered for token in positive_tokens)
        if has_negative and not has_positive:
            return False
        if has_positive and not has_negative:
            return True
        if has_negative and has_positive:
            first_negative = min(lowered.find(token) for token in negative_tokens if token in lowered)
            first_positive = min(lowered.find(token) for token in positive_tokens if token in lowered)
            return first_positive < first_negative
        raise ValueError(f"无法转换为 boolean：{value!r}")

    if type_name == "number":
        return int(value)

    if type_name == "string":
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = "" if value is None else str(value).strip()
        if not text:
            raise ValueError("FastGPT 输出 string 不能为空")
        return text

    if type_name == "object":
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = parse_json(value)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                text = value.strip()
                if text:
                    return {"raw": text}
        raise ValueError(f"无法转换为 object：{value!r}")

    raise ValueError(f"不支持的 FastGPT 类型：{type_name}")


def to_jsonable_value(value: Any) -> Any:
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
