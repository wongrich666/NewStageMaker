from __future__ import annotations

import copy
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


@lru_cache(maxsize=1)
def _ensure_simple_tools_env_loaded() -> tuple[str, ...]:
    loaded_paths: list[str] = []
    load_dotenv(override=False)
    module_path = Path(__file__).resolve()
    repo_root = module_path.parents[3]
    app_root = module_path.parents[2]
    for candidate in (repo_root / ".env", app_root / ".env"):
        if not candidate.exists():
            continue
        load_dotenv(candidate, override=False)
        loaded_paths.append(str(candidate))
    return tuple(loaded_paths)


_ensure_simple_tools_env_loaded()

from ..config import settings
from ..utils.logger import get_logger
from .json_utils import strip_code_fence
from .runtime_paths import get_runtime_data_dir

logger = get_logger("simple_fastgpt_tools")


DEFAULT_FASTGPT_URL = "https://api.fastgpt.in/api/v1/chat/completions"
TOOL_RESPONSE_TEXT_KEYS = ("answerText", "answer", "content", "text", "response", "result")
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}


@dataclass(frozen=True, slots=True)
class SimpleToolField:
    name: str
    label: str
    input_type: str
    placeholder: str
    required: bool = False
    source: str = "workflow_json"
    default_value: Any = ""


@dataclass(frozen=True, slots=True)
class SimpleToolDefinition:
    key: str
    label: str
    env_prefix: str
    help_text: str
    json_name_patterns: tuple[str, ...]
    fallback_fields: tuple[SimpleToolField, ...] = ()
    fallback_message_field: str | None = None
    field_overrides: tuple[SimpleToolField, ...] = ()
    field_aliases: tuple[tuple[str, str], ...] = ()
    payload_aliases: tuple[tuple[str, str], ...] = ()
    force_field_overrides: bool = False
    prefer_structured_output: bool = False
    prefer_named_text_over_choices: bool = False
    output_field_overrides: tuple[str, ...] = ()
    filename_prefix: str | None = None
    run_path: str | None = None
    max_attempts: int = 1
    retry_instruction: str | None = None
    empty_output_message: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedSimpleTool:
    definition: SimpleToolDefinition
    fields: tuple[SimpleToolField, ...]
    required_fields: tuple[str, ...]
    variable_aliases: dict[str, str]
    message_field: str | None
    help_text: str
    source: str
    json_path: Path | None
    answer_node_names: tuple[str, ...]
    updated_variables: tuple[str, ...]
    input_variables: tuple[str, ...]
    internal_variables: tuple[str, ...]
    visible_output_fields: tuple[str, ...]
    api_key_envs: tuple[str, ...]
    url_envs: tuple[str, ...]
    prefer_structured_output: bool
    prefer_named_text_over_choices: bool
    output_field_overrides: tuple[str, ...]
    filename_prefix: str | None
    run_path: str


class ToolExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        tool_id: str = "",
        debug: dict[str, Any] | None = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.tool_id = tool_id
        self.debug = debug or {}
        self.status_code = status_code


def _tool_timeout_seconds(definition: "SimpleToolDefinition") -> int:
    default_timeout = 4500 if definition.key == "hot_review" else int(getattr(settings, "fastgpt_timeout", 300))
    if definition.key == "hot_review":
        raw = os.getenv(f"{definition.env_prefix}_TIMEOUT") or str(default_timeout)
    else:
        raw = os.getenv(f"{definition.env_prefix}_TIMEOUT") or os.getenv("FASTGPT_TIMEOUT") or str(default_timeout)
    try:
        parsed = int(raw)
        if definition.key == "hot_review":
            return max(1500, parsed)
        return max(1, parsed)
    except (TypeError, ValueError):
        return default_timeout


TOOL_DEFINITIONS: dict[str, SimpleToolDefinition] = {
    "hot_review": SimpleToolDefinition(
        key="hot_review",
        label="爆款文审核",
        env_prefix="FASTGPT_HOT_REVIEW",
        help_text="提交待审核剧本，让工具返回完整爆款文审核意见，并支持下载 TXT。",
        json_name_patterns=("爆款文审核",),
        field_overrides=(
            SimpleToolField(
                name="review_text",
                label="待审核剧本",
                input_type="textarea",
                placeholder="粘贴待审核的剧本、大纲或片段。",
                required=True,
                source="tool_definition",
            ),
        ),
        field_aliases=(("review_text", "td2X8WXX"),),
        payload_aliases=(
            ("review_text", "td2X8WXX"),
            ("review_text", "text"),
            ("review_text", "content"),
            ("review_text", "script"),
            ("review_text", "input"),
            ("review_text", "story"),
            ("review_text", "review_text"),
            ("review_text", "source_text"),
        ),
        force_field_overrides=True,
        filename_prefix="爆款文审核意见",
        max_attempts=3,
        retry_instruction="请直接按照系统提示词输出完整审核报告，不要返回空内容。",
        empty_output_message=(
            "爆款文审核没有返回可展示结果。可能原因：FASTGPT_HOT_REVIEW_API_KEY 未被当前进程读取、"
            "待审核文本未映射到 td2X8WXX、AI 节点未产生 answerText、或 FastGPT 返回空输出。"
            "请查看后端 debug 文件。"
        ),
    ),
    "reskin": SimpleToolDefinition(
        key="reskin",
        label="换皮",
        env_prefix="FASTGPT_RESKIN",
        help_text="保留故事骨架，按目标风格完整换皮，并返回新故事梗概、人设、核心场景和最终剧本。",
        json_name_patterns=("换皮",),
        field_overrides=(
            SimpleToolField(
                name="title",
                label="剧本标题",
                input_type="input",
                placeholder="输入换皮后的剧本标题。",
                required=True,
                source="tool_definition",
            ),
            SimpleToolField(
                name="source_outline",
                label="源剧本梗概",
                input_type="textarea",
                placeholder="粘贴源剧本梗概。",
                required=True,
                source="tool_definition",
            ),
            SimpleToolField(
                name="core_scenes",
                label="源剧本核心场景",
                input_type="textarea",
                placeholder="可选，粘贴源剧本核心场景。",
                required=False,
                source="tool_definition",
            ),
            SimpleToolField(
                name="source_characters",
                label="源剧本人物小传",
                input_type="textarea",
                placeholder="粘贴源剧本人物小传。",
                required=True,
                source="tool_definition",
            ),
            SimpleToolField(
                name="source_script",
                label="源剧本正文",
                input_type="textarea",
                placeholder="可选，粘贴源剧本正文。",
                required=False,
                source="tool_definition",
            ),
            SimpleToolField(
                name="target_style",
                label="目标风格",
                input_type="textarea",
                placeholder="输入目标题材、风格、爽点方向和改写要求。",
                required=True,
                source="tool_definition",
            ),
            SimpleToolField(
                name="total_episodes",
                label="总集数",
                input_type="number",
                placeholder="例如：60。",
                required=True,
                source="tool_definition",
                default_value=60,
            ),
            SimpleToolField(
                name="episode_word_count",
                label="每集字数",
                input_type="number",
                placeholder="例如：600。",
                required=True,
                source="tool_definition",
                default_value=600,
            ),
        ),
        field_aliases=(
            ("title", "ju_ben_biao_ti"),
            ("source_outline", "yuan_juben_genggai"),
            ("core_scenes", "hexin_changjing"),
            ("source_characters", "renwu_xiaozhuan"),
            ("source_script", "juben_zhengwen"),
            ("target_style", "mubiao_fengge"),
            ("total_episodes", "zong_jishu"),
            ("episode_word_count", "meiji_zishu"),
        ),
        payload_aliases=(
            ("title", "ju_ben_biao_ti"),
            ("title", "script_title"),
            ("source_outline", "yuan_juben_genggai"),
            ("source_outline", "outline"),
            ("source_outline", "story_outline"),
            ("core_scenes", "hexin_changjing"),
            ("source_characters", "renwu_xiaozhuan"),
            ("source_characters", "characters"),
            ("source_script", "juben_zhengwen"),
            ("source_script", "script"),
            ("target_style", "mubiao_fengge"),
            ("target_style", "style"),
            ("total_episodes", "zong_jishu"),
            ("episode_word_count", "meiji_zishu"),
        ),
        force_field_overrides=True,
        prefer_structured_output=True,
        prefer_named_text_over_choices=True,
        output_field_overrides=(
            "final_output_text",
            "tc3kZbQz",
            "kuLf5sSZ",
            "m9TAB4GF",
            "ytCxjd4U",
            "script_batch_current",
        ),
        filename_prefix="换皮剧本",
        max_attempts=3,
        retry_instruction="请直接输出完整换皮结果，优先返回最终剧本，不要返回空内容。",
        empty_output_message=(
            "换皮工具没有返回可展示结果。可能原因：FASTGPT_RESKIN_API_KEY 未被当前进程读取、"
            "输入未映射到换皮 workflow 的变量、AI 节点未产生最终输出、或 FastGPT 返回空输出。"
            "请查看后端 debug 文件。"
        ),
    ),
    "punchup": SimpleToolDefinition(
        key="punchup",
        label="增加爽感",
        env_prefix="FASTGPT_PUNCHUP",
        help_text="不改主干情节，重点增强爽点、节奏与表达力度。",
        json_name_patterns=("增加爽感",),
    ),
    "character_reskin": SimpleToolDefinition(
        key="character_reskin",
        label="只换人设",
        env_prefix="FASTGPT_CHARACTER_RESKIN",
        help_text="保留主剧情结构，重点替换人物设定与角色表现。",
        json_name_patterns=("只换人设", "换皮只换人设"),
        field_overrides=(
            SimpleToolField(
                name="title",
                label="剧本标题",
                input_type="input",
                placeholder="输入新剧本标题。",
                required=True,
                source="tool_definition",
            ),
            SimpleToolField(
                name="source_outline",
                label="故事大纲",
                input_type="textarea",
                placeholder="粘贴原故事大纲。",
                required=True,
                source="tool_definition",
            ),
            SimpleToolField(
                name="core_scenes",
                label="核心场景",
                input_type="textarea",
                placeholder="粘贴核心场景。",
                required=False,
                source="tool_definition",
            ),
            SimpleToolField(
                name="source_characters",
                label="人物小传",
                input_type="textarea",
                placeholder="粘贴原人物小传。",
                required=True,
                source="tool_definition",
            ),
            SimpleToolField(
                name="source_script",
                label="原剧本正文",
                input_type="textarea",
                placeholder="粘贴原剧本正文。",
                required=True,
                source="tool_definition",
            ),
            SimpleToolField(
                name="target_style",
                label="目标风格 / 换人设要求",
                input_type="textarea",
                placeholder="输入目标风格、题材、人设替换方向和换人设要求。",
                required=False,
                source="tool_definition",
            ),
            SimpleToolField(
                name="total_episodes",
                label="总集数",
                input_type="number",
                placeholder="例如：50。",
                required=True,
                source="tool_definition",
                default_value=50,
            ),
            SimpleToolField(
                name="episode_word_count",
                label="每集正文字数",
                input_type="number",
                placeholder="例如：600。",
                required=True,
                source="tool_definition",
                default_value=600,
            ),
        ),
        payload_aliases=(
            ("title", "ju_ben_biao_ti"),
            ("title", "script_title"),
            ("source_outline", "yuan_juben_genggai"),
            ("source_outline", "outline"),
            ("source_outline", "story_outline"),
            ("core_scenes", "hexin_changjing"),
            ("source_characters", "renwu_xiaozhuan"),
            ("source_characters", "characters"),
            ("source_script", "juben_zhengwen"),
            ("source_script", "script"),
            ("target_style", "mubiao_fengge"),
            ("target_style", "style"),
            ("total_episodes", "zong_jishu"),
            ("episode_word_count", "meiji_zishu"),
        ),
        force_field_overrides=True,
        output_field_overrides=("final_output_text", "character_profile"),
        filename_prefix="只换人设",
    ),
    "sitcom_generator": SimpleToolDefinition(
        key="sitcom_generator",
        label="情景剧生成",
        env_prefix="FASTGPT_SITCOM",
        help_text="固定人物与核心关系，每集生成一个独立闭环故事；支持按集数分批生成，结果自动保存到新剧本资产。",
        json_name_patterns=("情景剧一键生成", "情景剧生成"),
        field_overrides=(
            SimpleToolField("project_title", "情景剧名称", "input", "例如：合租屋奇遇记。", True, "tool_definition"),
            SimpleToolField("sitcom_requirement", "创作要求", "textarea", "说明题材、受众、单集结构、笑点或冲突方向。", True, "tool_definition"),
            SimpleToolField("total_episodes", "总集数", "number", "例如：20。", True, "tool_definition", 20),
            SimpleToolField("episode_word_count", "每集字数", "number", "例如：1200。", True, "tool_definition", 1200),
            SimpleToolField("batch_start_episode", "本次起始集", "number", "首次生成填 1。", True, "tool_definition", 1),
            SimpleToolField("batch_end_episode", "本次结束集", "number", "建议每批生成 3-5 集。", True, "tool_definition", 3),
            SimpleToolField("fixed_characters", "固定人物设定", "textarea", "填写每位固定人物的姓名、身份、性格、关系、口头禅和不可改变项。", True, "tool_definition"),
            SimpleToolField("main_scenes", "主要场景", "textarea", "填写常驻场景及可变化的临时场景。", True, "tool_definition"),
            SimpleToolField("style_requirements", "风格要求", "textarea", "例如：轻喜剧、强反转、每集结尾有记忆点。", False, "tool_definition", "轻喜剧、节奏明快、单集闭环、人物性格稳定"),
            SimpleToolField("continuity_level", "连续性强度", "input", "弱 / 中 / 强；情景剧推荐弱或中。", False, "tool_definition", "弱"),
            SimpleToolField("existing_sitcom_bible", "已有情景剧设定总表（续写时填写）", "textarea", "首次生成可留空；续写时粘贴上次返回的 sitcom_bible。", False, "tool_definition"),
            SimpleToolField("existing_season_topic_matrix", "已有选题矩阵（续写时填写）", "textarea", "首次生成可留空；续写时粘贴上次返回的 season_topic_matrix。", False, "tool_definition"),
            SimpleToolField("used_episode_fingerprints", "已用故事指纹（续写时填写）", "textarea", "用于避免后续分集重复。", False, "tool_definition"),
            SimpleToolField("relationship_state", "当前人物关系状态（续写时填写）", "textarea", "记录上一批结束后的人物关系变化。", False, "tool_definition"),
            SimpleToolField("user_preferences", "补充偏好", "textarea", "可填写禁忌、平台规范、必须出现或避免的内容。", False, "tool_definition"),
        ),
        payload_aliases=(
            ("project_title", "projectTitle"),
            ("sitcom_requirement", "sitcomRequirement"),
            ("total_episodes", "totalEpisodes"),
            ("episode_word_count", "episodeWordCount"),
            ("batch_start_episode", "batchStartEpisode"),
            ("batch_end_episode", "batchEndEpisode"),
            ("fixed_characters", "fixedCharacters"),
            ("main_scenes", "mainScenes"),
            ("style_requirements", "styleRequirements"),
            ("continuity_level", "continuityLevel"),
            ("existing_sitcom_bible", "existingSitcomBible"),
            ("existing_season_topic_matrix", "existingSeasonTopicMatrix"),
            ("used_episode_fingerprints", "usedEpisodeFingerprints"),
            ("relationship_state", "relationshipState"),
            ("user_preferences", "userPreferences"),
        ),
        force_field_overrides=True,
        prefer_structured_output=True,
        prefer_named_text_over_choices=True,
        output_field_overrides=("final_script_text", "episode_scripts", "sitcom_bible", "season_topic_matrix", "updated_memory"),
        filename_prefix="情景剧",
        max_attempts=2,
        retry_instruction="请严格返回完整情景剧生成结果，必须包含本批分集正文，并保留可供下一批续写的设定与去重信息。",
        empty_output_message="情景剧工作流没有返回可展示结果，请检查 FastGPT 应用发布状态、变量名和回答节点输出。",
    ),
    "new_framework": SimpleToolDefinition(
        key="new_framework",
        label="15节拍剧本框架",
        env_prefix="FASTGPT_NEW_FRAMEWORK",
        help_text="单独生成 15 节拍剧本框架 / 剧本大纲，并支持下载 TXT。",
        json_name_patterns=("15内容新框架编写", "【新】15内容剧本框架"),
        field_overrides=(
            SimpleToolField(
                name="story",
                label="用户想要的故事",
                input_type="textarea",
                placeholder="输入故事方向、题材、人设、世界观、核心设定或一句话梗概。",
                required=True,
                source="tool_definition",
            ),
            SimpleToolField(
                name="character_count",
                label="角色数量",
                input_type="number",
                placeholder="需要生成的核心角色数量。",
                required=True,
                source="tool_definition",
            ),
            SimpleToolField(
                name="story_scale",
                label="故事体量",
                input_type="input",
                placeholder="例如：电影、短剧、长篇连续剧、单集剧本。",
                required=False,
                source="tool_definition",
                default_value="连载爆款短剧",
            ),
            SimpleToolField(
                name="total_episodes",
                label="总集数或章节数",
                input_type="number",
                placeholder="例如 60。",
                required=True,
                source="tool_definition",
                default_value=60,
            ),
            SimpleToolField(
                name="genre_tone",
                label="题材风格",
                input_type="input",
                placeholder="例如：悬疑复仇、都市情感、古装权谋、奇幻冒险。",
                required=False,
                source="tool_definition",
            ),
            SimpleToolField(
                name="target_audience",
                label="目标受众或平台风格",
                input_type="input",
                placeholder="例如：短剧爽感、长剧强情节、女性向、年轻观众。",
                required=False,
                source="tool_definition",
            ),
        ),
        field_aliases=(
            ("story", "wjmWDwbg"),
            ("character_count", "tsv3A9ac"),
            ("story_scale", "storyScale"),
            ("total_episodes", "bFgF0xfY"),
            ("genre_tone", "genreTone"),
            ("target_audience", "targetAudience"),
        ),
        payload_aliases=(
            ("story", "wjmWDwbg"),
            ("character_count", "tsv3A9ac"),
            ("story_scale", "storyScale"),
            ("total_episodes", "bFgF0xfY"),
            ("genre_tone", "genreTone"),
            ("target_audience", "targetAudience"),
        ),
        force_field_overrides=True,
        prefer_structured_output=True,
        prefer_named_text_over_choices=True,
        filename_prefix="15节拍剧本框架",
        run_path="/api/tools/new-framework",
        max_attempts=3,
        retry_instruction="请直接输出完整的 15 节拍剧本框架正文，不要返回空内容。",
        empty_output_message=(
            "15节拍剧本框架没有返回可展示结果。可能原因：AI 节点未产生 answerText、"
            "工作流 response_format 与提示词冲突、输入变量缺失、或 beatFrameworkContractJson 未写入。"
            "请查看后端 debug 文件。"
        ),
    ),
}


VISIBLE_TOOL_KEYS: tuple[str, ...] = tuple(TOOL_DEFINITIONS.keys())


def list_simple_tools() -> list[dict[str, Any]]:
    return [_serialize_tool(_resolved_tool(tool_key)) for tool_key in VISIBLE_TOOL_KEYS]


def diagnose_simple_tool_environment(
    tool_key: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if tool_key == "character_reskin":
        from .character_reskin_chain import diagnose_character_reskin_environment

        diagnosis = diagnose_character_reskin_environment()
        if isinstance(payload, dict):
            diagnosis["request_variable_keys"] = sorted(
                {
                    "n5ZHYrj8",
                    "eBEWC07Q",
                    "blkSS7dY",
                    "ayxWwSpE",
                    "rxmvq2lS",
                    "yYYOuumm",
                    "pxtQY7p2",
                }
            )
        return diagnosis
    resolved = _resolved_tool(tool_key)
    api_info = _resolve_api_key_info(resolved)
    url_info = _resolve_url_info(resolved)
    request_variable_keys: list[str] = []
    if isinstance(payload, dict):
        try:
            prepared_payload, _ = _prepare_tool_payload(resolved, payload)
        except ToolExecutionError:
            prepared_payload = {}
        request_variable_keys = sorted(_build_tool_variables(resolved, prepared_payload).keys())
    expected_variable_keys = list(dict.fromkeys(resolved.variable_aliases.values())) or list(resolved.input_variables)
    return {
        "tool_key": resolved.definition.key,
        "api_env": resolved.api_key_envs[0],
        "api_key_env_used": api_info["env_used"],
        "api_key_present": api_info["present"],
        "api_key_length": api_info["length"],
        "api_key_source": api_info["source"],
        "url_env": url_info["env"],
        "url_present": url_info["present"],
        "workflow_json_exists": bool(resolved.json_path and resolved.json_path.exists()),
        "workflow_json_path": str(resolved.json_path) if resolved.json_path else "",
        "request_variable_keys": request_variable_keys,
        "expected_variable_keys": expected_variable_keys,
    }


def run_simple_tool(tool_key: str, user_payload: dict[str, Any]) -> dict[str, Any]:
    if tool_key == "character_reskin":
        from .character_reskin_chain import run_character_reskin_chain

        return run_character_reskin_chain(user_payload)
    resolved = _resolved_tool(tool_key)
    definition = resolved.definition
    payload = user_payload if isinstance(user_payload, dict) else {}
    prepared_payload, payload_debug = _prepare_tool_payload(resolved, payload)
    variables = _build_tool_variables(resolved, prepared_payload)

    env_debug = diagnose_simple_tool_environment(definition.key, prepared_payload)
    api_info = _resolve_api_key_info(resolved)
    url_info = _resolve_url_info(resolved)

    if not api_info["value"]:
        raise ToolExecutionError(
            _missing_api_key_message(resolved),
            tool_id=definition.key,
            debug={
                **env_debug,
                "request_variables": copy.deepcopy(variables),
            },
            status_code=400,
        )

    url = str(url_info["value"] or DEFAULT_FASTGPT_URL).strip().rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_info['value']}",
        "Content-Type": "application/json",
    }
    base_content = _tool_message_content(resolved, prepared_payload)
    request_variable_keys = sorted(variables.keys())
    logger.info(
        "调用辅助工具 %s，api_env=%s，api_key_present=%s，api_key_length=%s，api_key_source=%s，url_env=%s，url_present=%s，workflow_json_path=%s，请求变量=%s",
        definition.key,
        resolved.api_key_envs[0],
        api_info["present"],
        api_info["length"],
        api_info["source"],
        url_info["env"],
        url_info["present"],
        str(resolved.json_path) if resolved.json_path else "",
        ", ".join(request_variable_keys),
    )

    attempts_debug: list[dict[str, Any]] = []
    final_error_message = definition.empty_output_message or _generic_empty_output_message(definition.label)
    final_failure_reason = "unknown"
    final_status_code = 502
    last_response_preview = ""
    last_candidate_paths: list[str] = []
    last_updated_variables: dict[str, Any] = {}
    last_data: Any = None
    timeout_seconds = _tool_timeout_seconds(definition)

    for attempt_index in range(1, max(1, definition.max_attempts) + 1):
        content = _tool_message_content_for_attempt(base_content, definition.retry_instruction, attempt_index)
        body = _build_request_body(definition.key, variables, content)
        status_code: int | None = None
        response_preview = ""
        candidate_paths: list[str] = []
        updated_variables: dict[str, Any] = {}
        visible_output_fields = list(resolved.visible_output_fields)
        failure_reason = ""

        try:
            response = requests.post(
                url,
                headers=headers,
                json=body,
                timeout=timeout_seconds,
            )
        except requests.Timeout as exc:
            failure_reason = "timeout"
            final_error_message = f"{definition.label} 请求超时，请稍后重试。"
            final_failure_reason = failure_reason
            attempt_debug = _build_attempt_debug(
                tool_key=definition.key,
                attempt_index=attempt_index,
                status_code=None,
                api_info=api_info,
                request_variable_keys=request_variable_keys,
                response_preview="",
                candidate_paths=[],
                updated_variables={},
                visible_output_fields=visible_output_fields,
                failure_reason=failure_reason,
            )
            attempts_debug.append(attempt_debug)
            _log_attempt_failure(attempt_debug)
            if attempt_index < max(1, definition.max_attempts):
                continue
            debug = _build_failure_debug(
                resolved,
                env_debug=env_debug,
                variables=variables,
                payload_debug=payload_debug,
                status_code=504,
                response_preview="",
                parsed_response=last_data,
                candidate_paths=[],
                updated_variables={},
                retry_attempts=attempts_debug,
                final_failure_reason=final_failure_reason,
            )
            debug["debug_artifact_path"] = _write_simple_tool_debug_artifact(debug)
            raise ToolExecutionError(
                final_error_message,
                tool_id=definition.key,
                debug=debug,
                status_code=504,
            ) from exc
        except requests.RequestException as exc:
            final_error_message = f"{definition.label} 请求失败，请稍后重试。"
            final_failure_reason = "request_exception"
            final_status_code = 502
            attempt_debug = _build_attempt_debug(
                tool_key=definition.key,
                attempt_index=attempt_index,
                status_code=None,
                api_info=api_info,
                request_variable_keys=request_variable_keys,
                response_preview=_truncate_text(str(exc), limit=800),
                candidate_paths=[],
                updated_variables={},
                visible_output_fields=visible_output_fields,
                failure_reason=final_failure_reason,
            )
            attempts_debug.append(attempt_debug)
            _log_attempt_failure(attempt_debug)
            debug = _build_failure_debug(
                resolved,
                env_debug=env_debug,
                variables=variables,
                payload_debug=payload_debug,
                status_code=502,
                response_preview=_truncate_text(str(exc), limit=800),
                parsed_response=None,
                candidate_paths=[],
                updated_variables={},
                retry_attempts=attempts_debug,
                final_failure_reason=final_failure_reason,
            )
            debug["debug_artifact_path"] = _write_simple_tool_debug_artifact(debug)
            raise ToolExecutionError(
                final_error_message,
                tool_id=definition.key,
                debug=debug,
                status_code=502,
            ) from exc

        status_code = int(response.status_code or 0)
        response_preview = _truncate_text(response.text, limit=1200)
        if status_code >= 400:
            auth_error_text = _find_auth_error_text(response.text, status_code=status_code)
            if auth_error_text:
                failure_reason = "auth_error"
                final_error_message = _unauthorized_api_key_message(resolved, url_info)
            else:
                failure_reason = f"http_{status_code}"
                final_error_message = f"{definition.label} 请求失败（HTTP {status_code}）。"
            final_failure_reason = failure_reason
            final_status_code = status_code if status_code in RETRYABLE_HTTP_STATUSES else 400
            attempt_debug = _build_attempt_debug(
                tool_key=definition.key,
                attempt_index=attempt_index,
                status_code=status_code,
                api_info=api_info,
                request_variable_keys=request_variable_keys,
                response_preview=response_preview,
                candidate_paths=[],
                updated_variables={},
                visible_output_fields=visible_output_fields,
                failure_reason=failure_reason,
            )
            attempts_debug.append(attempt_debug)
            _log_attempt_failure(attempt_debug)
            if status_code in RETRYABLE_HTTP_STATUSES and attempt_index < max(1, definition.max_attempts):
                continue
            debug = _build_failure_debug(
                resolved,
                env_debug=env_debug,
                variables=variables,
                payload_debug=payload_debug,
                status_code=status_code,
                response_preview=response_preview,
                parsed_response=None,
                candidate_paths=[],
                updated_variables={},
                retry_attempts=attempts_debug,
                final_failure_reason=final_failure_reason,
            )
            debug["debug_artifact_path"] = _write_simple_tool_debug_artifact(debug)
            raise ToolExecutionError(
                final_error_message,
                tool_id=definition.key,
                debug=debug,
                status_code=final_status_code,
            )

        try:
            data = response.json()
        except Exception as exc:
            final_error_message = f"{definition.label} 返回了无法解析的响应。"
            final_failure_reason = "invalid_json"
            final_status_code = 502
            debug = _build_failure_debug(
                resolved,
                env_debug=env_debug,
                variables=variables,
                payload_debug=payload_debug,
                status_code=status_code,
                response_preview=response_preview,
                parsed_response=None,
                candidate_paths=[],
                updated_variables={},
                retry_attempts=attempts_debug,
                final_failure_reason=final_failure_reason,
            )
            debug["debug_artifact_path"] = _write_simple_tool_debug_artifact(debug)
            raise ToolExecutionError(
                final_error_message,
                tool_id=definition.key,
                debug=debug,
                status_code=502,
            ) from exc

        last_data = data
        response_preview = _truncate_text(_json_text(data), limit=1200)
        candidate_paths = _collect_candidate_paths(data, resolved)
        updated_variables = _collect_updated_variable_values(data, resolved)
        extracted = _extract_tool_output(data, resolved)
        auth_error_text = _find_auth_error_text(data, status_code=status_code)
        system_error_text = _find_system_error_text(data)
        transient_error_text = _find_transient_error_text(data)

        if extracted is not None:
            output, output_source = extracted
            if definition.key == "sitcom_generator" and isinstance(output, str):
                recovered_output = _recover_sitcom_jsonish_output(output)
                if recovered_output:
                    output = recovered_output
                    output_source = f"{output_source}.recovered_sitcom_fields"
            debug = {
                **env_debug,
                "workflow_json_file": resolved.json_path.name if resolved.json_path else None,
                "workflow_json_path": str(resolved.json_path) if resolved.json_path else "",
                "source": resolved.source,
                "answer_node_names": list(resolved.answer_node_names),
                "updated_variables": updated_variables,
                "input_variables": list(resolved.input_variables),
                "internal_variables": list(resolved.internal_variables),
                "visible_output_fields": list(resolved.visible_output_fields),
                "chosen_output_source": output_source,
                "normalized_payload": payload_debug,
                "request_variables": copy.deepcopy(variables),
                "request_variable_keys": request_variable_keys,
                "response_preview": response_preview,
                "candidate_paths": candidate_paths,
                "retry_attempts": attempts_debug,
                "api_key_source": api_info["source"],
            }
            rendered_text = _render_tool_user_text(definition, output)
            filename_payload = dict(payload_debug)
            project_title = str(payload.get("project_title") or "").strip()
            if project_title:
                filename_payload["project_title"] = project_title
            filename = _build_tool_filename(resolved, output, filename_payload)
            return {
                "ok": True,
                "tool_id": definition.key,
                "title": definition.label,
                "output": output,
                "output_type": "json" if isinstance(output, (dict, list)) else "text",
                "text": rendered_text,
                "filename": filename,
                "debug": debug,
                "schema": _serialize_tool(resolved),
            }

        if auth_error_text:
            failure_reason = "auth_error"
            final_error_message = _unauthorized_api_key_message(resolved, url_info)
            final_failure_reason = failure_reason
            final_status_code = 400
            response_preview = _truncate_text(auth_error_text, limit=1200)
        elif system_error_text:
            failure_reason = "system_error_text"
            final_error_message = f"{definition.label} 返回了临时错误，请稍后重试。"
            final_failure_reason = failure_reason
            final_status_code = 502
            response_preview = _truncate_text(system_error_text, limit=1200)
        elif transient_error_text:
            failure_reason = "transient_error"
            final_error_message = f"{definition.label} 返回了临时错误，请稍后重试。"
            final_failure_reason = failure_reason
            final_status_code = 502
            response_preview = _truncate_text(transient_error_text, limit=1200)
        else:
            failure_reason = "empty_output"
            final_error_message = definition.empty_output_message or _generic_empty_output_message(definition.label)
            final_failure_reason = failure_reason
            final_status_code = 502

        last_response_preview = response_preview
        last_candidate_paths = candidate_paths
        last_updated_variables = updated_variables
        attempt_debug = _build_attempt_debug(
            tool_key=definition.key,
            attempt_index=attempt_index,
            status_code=status_code,
            api_info=api_info,
            request_variable_keys=request_variable_keys,
            response_preview=response_preview,
            candidate_paths=candidate_paths,
            updated_variables=updated_variables,
            visible_output_fields=visible_output_fields,
            failure_reason=failure_reason,
        )
        attempts_debug.append(attempt_debug)
        _log_attempt_failure(attempt_debug)
        if attempt_index < max(1, definition.max_attempts):
            continue

    debug = _build_failure_debug(
        resolved,
        env_debug=env_debug,
        variables=variables,
        payload_debug=payload_debug,
        status_code=final_status_code,
        response_preview=last_response_preview,
        parsed_response=last_data,
        candidate_paths=last_candidate_paths,
        updated_variables=last_updated_variables,
        retry_attempts=attempts_debug,
        final_failure_reason=final_failure_reason,
    )
    debug["debug_artifact_path"] = _write_simple_tool_debug_artifact(debug)
    raise ToolExecutionError(
        final_error_message,
        tool_id=definition.key,
        debug=debug,
        status_code=final_status_code,
    )


def _prepare_tool_payload(
    resolved: ResolvedSimpleTool,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    prepared: dict[str, Any] = {}
    missing_fields: list[str] = []
    invalid_fields: list[str] = []
    alias_map = _payload_alias_map(resolved.definition)

    for field in resolved.fields:
        raw_value = _payload_value_for_field(payload, field.name, alias_map.get(field.name, ()))
        if field.input_type == "number":
            if _tool_value_is_blank(raw_value):
                if _has_meaningful_tool_value(field.default_value):
                    prepared[field.name] = _coerce_positive_int(field.default_value)
                elif field.required:
                    missing_fields.append(field.name)
                continue
            number = _coerce_positive_int(raw_value)
            if number is None:
                invalid_fields.append(field.name)
                continue
            prepared[field.name] = number
            continue

        text = str(raw_value or "").strip()
        if not text:
            if field.required:
                missing_fields.append(field.name)
            elif _has_meaningful_tool_value(field.default_value):
                prepared[field.name] = _normalize_value(field.default_value)
            elif field.name in payload:
                prepared[field.name] = ""
            continue
        prepared[field.name] = text

    if missing_fields:
        raise ToolExecutionError(
            f"{resolved.definition.label} 缺少必填项：{', '.join(missing_fields)}",
            tool_id=resolved.definition.key,
            debug={"missing_fields": missing_fields},
            status_code=400,
        )
    if invalid_fields:
        raise ToolExecutionError(
            f"{resolved.definition.label} 字段格式无效：{', '.join(invalid_fields)} 必须是正整数",
            tool_id=resolved.definition.key,
            debug={"invalid_fields": invalid_fields},
            status_code=400,
        )

    return prepared, copy.deepcopy(prepared)


def _serialize_tool(resolved: ResolvedSimpleTool) -> dict[str, Any]:
    api_info = _resolve_api_key_info(resolved)
    url_info = _resolve_url_info(resolved)
    definition = resolved.definition
    if definition.key == "character_reskin":
        from .character_reskin_chain import DEDICATED_API_KEY_ENVS, URL_ENV, diagnose_character_reskin_environment

        chain_diagnosis = diagnose_character_reskin_environment()
        api_info = {
            **api_info,
            "present": not chain_diagnosis["missing_api_key_envs"],
            "env_used": ",".join(chain_diagnosis["present_api_key_envs"]),
            "source": "dedicated_multi_stage",
        }
        url_info = {
            **url_info,
            "env": URL_ENV,
            "value": os.getenv(URL_ENV) or DEFAULT_FASTGPT_URL,
            "present": bool(os.getenv(URL_ENV)),
        }
        api_key_envs = list(DEDICATED_API_KEY_ENVS)
        workflow_url_envs = [URL_ENV]
    else:
        api_key_envs = list(resolved.api_key_envs)
        workflow_url_envs = list(resolved.url_envs)
    return {
        "tool_id": definition.key,
        "key": definition.key,
        "title": definition.label,
        "label": definition.label,
        "configured": api_info["present"],
        "configured_api_key_env": api_info["env_used"],
        "configured_api_key_source": api_info["source"],
        "configured_url_env": url_info["env"],
        "configured_url": str(url_info["value"] or DEFAULT_FASTGPT_URL).strip().rstrip("/"),
        "help": resolved.help_text,
        "source": resolved.source,
        "run_url": resolved.run_path,
        "json_file": resolved.json_path.name if resolved.json_path else None,
        "workflow_json_file": resolved.json_path.name if resolved.json_path else None,
        "api_key_envs": api_key_envs,
        "workflow_url_envs": workflow_url_envs,
        "input_variables": list(resolved.input_variables),
        "internal_variables": list(resolved.internal_variables),
        "output_variables": list(resolved.updated_variables),
        "visible_output_fields": list(resolved.visible_output_fields),
        "answer_node_names": list(resolved.answer_node_names),
        "required_fields": list(resolved.required_fields),
        "fields": [
            {
                "name": field.name,
                "label": field.label,
                "type": field.input_type,
                "placeholder": field.placeholder,
                "required": field.required,
                "source": field.source,
                "default_value": field.default_value,
            }
            for field in resolved.fields
        ],
        "schema": {
            "fields": [
                {
                    "name": field.name,
                    "label": field.label,
                    "type": field.input_type,
                    "placeholder": field.placeholder,
                    "required": field.required,
                    "source": field.source,
                    "default_value": field.default_value,
                }
                for field in resolved.fields
            ],
            "input_variables": list(resolved.input_variables),
            "internal_variables": list(resolved.internal_variables),
            "output_variables": list(resolved.updated_variables),
            "visible_output_fields": list(resolved.visible_output_fields),
            "answer_node_names": list(resolved.answer_node_names),
        },
    }


@lru_cache(maxsize=None)
def _resolved_tool(tool_key: str) -> ResolvedSimpleTool:
    definition = TOOL_DEFINITIONS.get(tool_key)
    if definition is None:
        raise ToolExecutionError(f"未知工具：{tool_key}", tool_id=tool_key, status_code=404)

    json_path = _find_tool_json(definition)
    workflow = _load_workflow_json(json_path) if json_path else None
    input_variables, internal_variables = _workflow_variables(workflow)
    fields = _infer_fields_from_workflow_json(workflow)
    updated_variables = _infer_updated_variables(workflow)
    if definition.output_field_overrides:
        updated_variables = tuple(dict.fromkeys((*definition.output_field_overrides, *updated_variables)))
    answer_node_names = _infer_answer_node_names(workflow)
    visible_output_fields = _visible_output_fields(
        answer_node_names=answer_node_names,
        updated_variables=updated_variables,
    )

    override_aliases = {field_name: alias for field_name, alias in definition.field_aliases}
    if definition.force_field_overrides and definition.field_overrides:
        fields = definition.field_overrides
        required_fields = tuple(field.name for field in fields if field.required)
        variable_aliases = {
            field.name: override_aliases.get(field.name, field.name)
            for field in fields
            if field.name != definition.fallback_message_field
        }
        message_field = definition.fallback_message_field
        source = "tool_definition"
        help_text = (
            f"{definition.help_text} 当前表单字段按工具定义映射到 {json_path.name}。"
            if json_path
            else definition.help_text
        )
    elif fields:
        required_fields = tuple(field.name for field in fields if field.required)
        variable_aliases = {field.name: override_aliases.get(field.name, field.name) for field in fields}
        message_field = None
        source = "workflow_json"
        help_text = f"{definition.help_text} 当前表单字段来自 {json_path.name}。"
    else:
        fields = definition.fallback_fields
        required_fields = tuple(field.name for field in fields if field.required)
        variable_aliases = {
            field.name: override_aliases.get(field.name, field.name)
            for field in fields
            if field.name != definition.fallback_message_field
        }
        message_field = definition.fallback_message_field
        source = "fallback"
        help_text = (
            f"{definition.help_text} 当前 workflow 未暴露公开输入变量，已使用代码侧兜底表单。"
            if json_path
            else definition.help_text
        )

    return ResolvedSimpleTool(
        definition=definition,
        fields=fields,
        required_fields=required_fields,
        variable_aliases=variable_aliases,
        message_field=message_field,
        help_text=help_text,
        source=source,
        json_path=json_path,
        answer_node_names=answer_node_names,
        updated_variables=updated_variables,
        input_variables=input_variables,
        internal_variables=internal_variables,
        visible_output_fields=visible_output_fields,
        api_key_envs=(f"{definition.env_prefix}_API_KEY", "FASTGPT_API_KEY"),
        url_envs=(f"{definition.env_prefix}_CHAT_COMPLETIONS_URL", "FASTGPT_CHAT_COMPLETIONS_URL"),
        prefer_structured_output=definition.prefer_structured_output,
        prefer_named_text_over_choices=definition.prefer_named_text_over_choices,
        output_field_overrides=definition.output_field_overrides,
        filename_prefix=definition.filename_prefix,
        run_path=definition.run_path or f"/api/tools/{definition.key}/run",
    )


@lru_cache(maxsize=1)
def _workflow_json_dir() -> Path | None:
    repo_root = Path(__file__).resolve().parents[3]
    exact = repo_root / "workflow_jsons"
    if exact.is_dir():
        return exact
    for child in sorted(repo_root.iterdir()):
        if child.is_dir() and "workflow_jsons" in child.name:
            return child
    return None


def _find_tool_json(definition: SimpleToolDefinition) -> Path | None:
    folder = _workflow_json_dir()
    if folder is None:
        return None
    files = sorted(folder.glob("*.json"))
    lowered_patterns = tuple(pattern.lower() for pattern in definition.json_name_patterns)
    for pattern in definition.json_name_patterns:
        exact = next((item for item in files if item.stem == pattern), None)
        if exact is not None:
            return exact
    for item in files:
        stem = item.stem.lower()
        if definition.key == "reskin" and "只换人设" in stem:
            continue
        if any(pattern in stem for pattern in lowered_patterns):
            return item
    return None


def _load_workflow_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        logger.warning("辅助工具 workflow JSON 读取失败：%s", path, exc_info=True)
        return None


def _workflow_variables(workflow: dict[str, Any] | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    input_variables: list[str] = []
    internal_variables: list[str] = []
    for item in (workflow or {}).get("chatConfig", {}).get("variables", []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        if str(item.get("type") or "").strip().lower() == "internal":
            internal_variables.append(key)
        else:
            input_variables.append(key)
    return tuple(input_variables), tuple(internal_variables)


def _infer_fields_from_workflow_json(workflow: dict[str, Any] | None) -> tuple[SimpleToolField, ...]:
    fields: list[SimpleToolField] = []
    for item in (workflow or {}).get("chatConfig", {}).get("variables", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip().lower() == "internal":
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        label = str(item.get("label") or key).strip() or key
        description = str(item.get("description") or "").strip()
        fields.append(
            SimpleToolField(
                name=key,
                label=label,
                input_type=_field_input_type(item, label),
                placeholder=description or f"请输入{label}",
                required=bool(item.get("required")),
                source="workflow_json",
                default_value=item.get("defaultValue"),
            )
        )
    return tuple(fields)


def _field_input_type(item: dict[str, Any], label: str) -> str:
    value_type = str(item.get("valueType") or "").strip().lower()
    field_type = str(item.get("type") or "").strip().lower()
    lowered_label = label.lower()
    if field_type == "numberinput" or value_type == "number":
        return "number"
    if any(token in lowered_label for token in ("标题", "title", "名称", "name")):
        return "input"
    return "textarea"


def _infer_updated_variables(workflow: dict[str, Any] | None) -> tuple[str, ...]:
    variables: list[str] = []
    for node in (workflow or {}).get("nodes", []):
        if not isinstance(node, dict) or node.get("flowNodeType") != "variableUpdate":
            continue
        for input_item in node.get("inputs") or []:
            if not isinstance(input_item, dict):
                continue
            for update in input_item.get("value") or []:
                if not isinstance(update, dict):
                    continue
                variable = update.get("variable")
                if isinstance(variable, list) and len(variable) >= 2 and str(variable[1] or "").strip():
                    variables.append(str(variable[1]).strip())
    return tuple(dict.fromkeys(variables))


def _infer_answer_node_names(workflow: dict[str, Any] | None) -> tuple[str, ...]:
    answer_nodes: list[str] = []
    for node in (workflow or {}).get("nodes", []):
        if not isinstance(node, dict):
            continue
        if str(node.get("flowNodeType") or "").strip() == "answerNode":
            name = str(node.get("name") or "answerNode").strip() or "answerNode"
            answer_nodes.append(name)
    return tuple(dict.fromkeys(answer_nodes))


def _visible_output_fields(
    *,
    answer_node_names: tuple[str, ...],
    updated_variables: tuple[str, ...],
) -> tuple[str, ...]:
    fields: list[str] = []
    if answer_node_names:
        fields.append("choices.message.content")
    fields.extend(updated_variables)
    if not fields:
        fields.append("answerText")
    return tuple(dict.fromkeys(fields))


def _tool_message_content(resolved: ResolvedSimpleTool, payload: dict[str, Any]) -> str:
    if resolved.message_field:
        return str(payload.get(resolved.message_field) or "").strip()
    return (
        f"请执行辅助工具“{resolved.definition.label}”。"
        "请严格读取 variables，并只返回最终给用户看的结果。"
    )


def _tool_message_content_for_attempt(
    base_content: str,
    retry_instruction: str | None,
    attempt_index: int,
) -> str:
    if attempt_index <= 1 or not retry_instruction:
        return base_content
    if not base_content.strip():
        return retry_instruction.strip()
    return f"{base_content.rstrip()}\n\n{retry_instruction.strip()}"


def _build_request_body(tool_key: str, variables: dict[str, Any], content: str) -> dict[str, Any]:
    return {
        "chatId": f"scriptmaker-tool-{tool_key}-{uuid.uuid4().hex[:8]}",
        "stream": False,
        "detail": True,
        "variables": copy.deepcopy(variables),
        "messages": [{"role": "user", "content": content}],
    }


def _extract_tool_output(
    data: Any,
    resolved: ResolvedSimpleTool,
) -> tuple[Any, str] | None:
    if resolved.prefer_structured_output:
        structured = _extract_structured_output(data, resolved)
        if structured is not None:
            return structured
    for source, value in _iter_tool_text_candidates(
        data,
        prefer_named_text_over_choices=resolved.prefer_named_text_over_choices,
    ):
        normalized = _normalize_tool_output_value(value)
        if normalized not in (None, "", [], {}):
            return normalized, source
    if not resolved.prefer_structured_output:
        structured = _extract_structured_output(data, resolved)
        if structured is not None:
            return structured
    return None


def _extract_structured_output(
    data: Any,
    resolved: ResolvedSimpleTool,
) -> tuple[Any, str] | None:
    for source, candidate in _iter_structured_candidate_sources(data):
        for field in resolved.updated_variables:
            if not isinstance(candidate, dict) or field not in candidate:
                continue
            normalized = _normalize_tool_output_value(candidate.get(field))
            if normalized not in (None, "", [], {}):
                return normalized, f"{source}.{field}"
    if isinstance(data, dict):
        for field in resolved.updated_variables:
            if field not in data:
                continue
            normalized = _normalize_tool_output_value(data.get(field))
            if normalized not in (None, "", [], {}):
                return normalized, f"root.{field}"
    return None


def _iter_tool_text_candidates(
    data: Any,
    *,
    prefer_named_text_over_choices: bool = False,
) -> list[tuple[str, Any]]:
    candidates: list[tuple[str, Any]] = []
    if isinstance(data, dict):
        if prefer_named_text_over_choices:
            candidates.extend(_iter_named_text_candidates("root", data))
            candidates.extend(_iter_choice_text_candidates(data))
        else:
            candidates.extend(_iter_choice_text_candidates(data))
            candidates.extend(_iter_named_text_candidates("root", data))
        response_data = data.get("responseData")
        if isinstance(response_data, dict):
            candidates.extend(_iter_named_text_candidates("responseData", response_data))
        elif isinstance(response_data, list):
            for index, item in enumerate(response_data):
                if isinstance(item, dict):
                    candidates.extend(_iter_named_text_candidates(f"responseData[{index}]", item))
    elif data not in (None, "", [], {}):
        candidates.append(("response", data))
    return candidates


def _iter_structured_candidate_sources(data: Any) -> list[tuple[str, dict[str, Any]]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(data, dict):
        return candidates
    for key in ("newVariables", "updateVarResult", "variableUpdate"):
        normalized = _coerce_variable_bucket(data.get(key))
        if normalized:
            candidates.append((key, normalized))
    response_data = data.get("responseData")
    if isinstance(response_data, dict):
        for key in ("variableUpdate", "newVariables", "updateVarResult"):
            normalized = _coerce_variable_bucket(response_data.get(key))
            if normalized:
                candidates.append((f"responseData.{key}", normalized))
        for key in ("output", "outputs"):
            value = response_data.get(key)
            if isinstance(value, dict):
                candidates.append((f"responseData.{key}", value))
    elif isinstance(response_data, list):
        for index, item in enumerate(response_data):
            if not isinstance(item, dict):
                continue
            for key in ("variableUpdate", "newVariables", "updateVarResult"):
                normalized = _coerce_variable_bucket(item.get(key))
                if normalized:
                    candidates.append((f"responseData[{index}].{key}", normalized))
            if isinstance(item.get("output"), dict):
                candidates.append((f"responseData[{index}].output", item["output"]))
            if isinstance(item.get("outputs"), dict):
                candidates.append((f"responseData[{index}].outputs", item["outputs"]))
    return candidates


def _iter_choice_text_candidates(data: dict[str, Any]) -> list[tuple[str, Any]]:
    candidates: list[tuple[str, Any]] = []
    choices = data.get("choices")
    if not isinstance(choices, list):
        return candidates
    for index, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict):
            content = _message_content_to_text(message.get("content"))
            if content:
                candidates.append((f"choices[{index}].message.content", content))
    return candidates


def _iter_named_text_candidates(
    prefix: str,
    data: dict[str, Any],
    *,
    _depth: int = 0,
) -> list[tuple[str, Any]]:
    candidates: list[tuple[str, Any]] = []
    for key in ("answerText", "textOutput", *TOOL_RESPONSE_TEXT_KEYS):
        value = data.get(key)
        if value not in (None, "", [], {}):
            candidates.append((f"{prefix}.{key}", value))
    for key in ("output", "outputs"):
        value = data.get(key)
        if isinstance(value, dict):
            candidates.extend(_iter_named_text_candidates(f"{prefix}.{key}", value, _depth=_depth + 1))
    if _depth >= 2:
        return candidates
    for key, value in data.items():
        if key in {
            "choices",
            "message",
            "content",
            "usage",
            "model",
            "id",
            "responseData",
            "newVariables",
            "updateVarResult",
            "variableUpdate",
            "toolCall",
            "pluginOutput",
        }:
            continue
        if isinstance(value, dict):
            candidates.extend(_iter_named_text_candidates(f"{prefix}.{key}", value, _depth=_depth + 1))
    return candidates


def _coerce_variable_bucket(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, list):
        return None
    normalized: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not isinstance(key, str) or not key.strip():
            variable = item.get("variable")
            if isinstance(variable, list) and len(variable) >= 2 and str(variable[1] or "").strip():
                key = str(variable[1]).strip()
            elif isinstance(variable, str) and variable.strip():
                key = variable.strip()
        if not isinstance(key, str) or not key.strip():
            continue
        if "value" in item:
            normalized[key.strip()] = item.get("value")
    return normalized or None


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return _message_content_to_text(content.get("text") or content.get("content"))
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                item_type = str(item.get("type") or "").strip().lower()
                if item_type and item_type != "text":
                    continue
                text = _message_content_to_text(item.get("text") or item.get("content"))
                if text:
                    parts.append(text)
            else:
                text = _message_content_to_text(item)
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _normalize_tool_output_value(value: Any) -> Any:
    normalized = _unwrap_jsonish_value(value)
    if isinstance(normalized, str):
        text = normalized.strip()
        if not text:
            return ""
        parsed = _parse_jsonish_text(text)
        if parsed is not None:
            return parsed
        return text
    if isinstance(normalized, list):
        if len(normalized) == 1:
            nested = _normalize_tool_output_value(normalized[0])
            if nested not in (None, "", [], {}):
                return nested
        return normalized
    return normalized


def _unwrap_jsonish_value(value: Any) -> Any:
    candidate = value
    for _ in range(3):
        if isinstance(candidate, dict):
            if isinstance(candidate.get("text"), str):
                candidate = candidate["text"]
                continue
            if isinstance(candidate.get("content"), str):
                candidate = candidate["content"]
                continue
            break
        if isinstance(candidate, list):
            text = _message_content_to_text(candidate)
            if text:
                candidate = text
                continue
            break
        if isinstance(candidate, str):
            text = strip_code_fence(candidate).strip()
            parsed = _parse_jsonish_text(text)
            if parsed is None:
                candidate = text
                break
            candidate = parsed
            continue
        break
    return candidate


def _parse_jsonish_text(text: str) -> Any | None:
    stripped = strip_code_fence(str(text or "")).strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except Exception:
        return None
    if isinstance(parsed, str) and parsed.strip() and parsed.strip()[0] in "[{":
        try:
            nested = json.loads(parsed)
        except Exception:
            return parsed.strip()
        return nested
    return parsed


def _tool_value_is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _has_meaningful_tool_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _coerce_positive_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if not number.is_integer() or number <= 0:
        return None
    return int(number)


def _render_tool_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2).strip()
        except Exception:
            return str(value).strip()
    return str(value or "").strip()


def _render_tool_user_text(definition: SimpleToolDefinition, value: Any) -> str:
    if definition.key == "sitcom_generator" and isinstance(value, dict):
        final_script_text = value.get("final_script_text")
        if isinstance(final_script_text, str) and final_script_text.strip():
            return final_script_text.strip()
    return _render_tool_text(value)


def _extract_balanced_json_value(text: str, field_name: str) -> Any | None:
    match = re.search(rf'"{re.escape(field_name)}"\s*:\s*', text)
    if not match:
        return None
    start = match.end()
    while start < len(text) and text[start].isspace():
        start += 1
    if start >= len(text) or text[start] not in "[{":
        return None
    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:index + 1])
                except Exception:
                    return None
    return None


def _extract_json_string_field(text: str, field_name: str) -> str:
    match = re.search(
        rf'"{re.escape(field_name)}"\s*:\s*"((?:\\.|[^"\\])*)"',
        text,
        flags=re.DOTALL,
    )
    if not match:
        return ""
    try:
        return str(json.loads(f'"{match.group(1)}"')).strip()
    except Exception:
        return match.group(1).replace(r"\n", "\n").replace(r'\"', '"').strip()


def _recover_sitcom_jsonish_output(value: str) -> dict[str, Any] | None:
    text = strip_code_fence(str(value or "")).strip()
    if not text or "sitcom_bible" not in text and "episode_scripts" not in text:
        return None
    recovered: dict[str, Any] = {
        "schema_version": _extract_json_string_field(text, "schema_version") or "sitcom_generation_v1",
        "generation_mode": _extract_json_string_field(text, "generation_mode") or "sitcom",
        "project_title": _extract_json_string_field(text, "project_title"),
    }
    for field_name in (
        "batch",
        "sitcom_bible",
        "season_topic_matrix",
        "episode_outlines",
        "episode_scripts",
        "quality_report",
        "updated_memory",
        "next_batch",
    ):
        extracted = _extract_balanced_json_value(text, field_name)
        if extracted not in (None, "", [], {}):
            recovered[field_name] = extracted
    final_script_text = _extract_json_string_field(text, "final_script_text")
    if final_script_text:
        recovered["final_script_text"] = final_script_text
    episode_scripts = recovered.get("episode_scripts")
    if not final_script_text and isinstance(episode_scripts, list):
        scripts = [
            str(item.get("script_text") or "").strip()
            for item in episode_scripts
            if isinstance(item, dict) and str(item.get("script_text") or "").strip()
        ]
        if scripts:
            recovered["final_script_text"] = "\n\n".join(scripts)
    if not recovered.get("final_script_text") and not recovered.get("episode_scripts"):
        return None
    recovered["ok"] = True
    return recovered


def _build_tool_filename(
    resolved: ResolvedSimpleTool,
    output: Any,
    payload: dict[str, Any],
) -> str | None:
    if not resolved.filename_prefix:
        return None
    suffix = _derive_tool_filename_suffix(resolved, output, payload) or datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_suffix = _sanitize_filename_fragment(suffix) or datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{resolved.filename_prefix}_{safe_suffix}.txt"


def _derive_tool_filename_suffix(
    resolved: ResolvedSimpleTool,
    output: Any,
    payload: dict[str, Any],
) -> str:
    if resolved.definition.key != "new_framework":
        for key in ("project_title", "title", "script_title", "ju_ben_biao_ti"):
            project_title = str(payload.get(key) or "").strip()
            if project_title:
                return project_title
        return ""
    project_title = str(payload.get("project_title") or "").strip()
    if project_title:
        return project_title
    if isinstance(output, dict):
        for key in ("script_title_content", "title", "script_title"):
            value = str(output.get(key) or "").strip()
            if value:
                return value
    text = _render_tool_text(output)
    lines = [line.strip() for line in text.replace("\r", "").split("\n") if line.strip()]
    if len(lines) >= 2 and lines[0] == "剧本标题":
        return lines[1]
    return ""


def _sanitize_filename_fragment(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    cleaned = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in text)
    cleaned = " ".join(cleaned.split()).strip(" ._")
    return cleaned[:60]


def _resolve_api_key_info(resolved: ResolvedSimpleTool) -> dict[str, Any]:
    env_used, value = _env_with_name(*resolved.api_key_envs)
    source = "missing"
    if env_used == resolved.api_key_envs[0]:
        source = "dedicated"
    elif env_used == "FASTGPT_API_KEY":
        source = "fallback_global"
    return {
        "env": resolved.api_key_envs[0],
        "env_used": env_used,
        "value": value,
        "present": bool(value),
        "length": len(value or ""),
        "source": source,
    }


def _resolve_url_info(resolved: ResolvedSimpleTool) -> dict[str, Any]:
    env_used, value = _env_with_name(*resolved.url_envs)
    return {
        "env": env_used or resolved.url_envs[0],
        "env_used": env_used,
        "value": value,
        "present": bool(value),
    }


def _env(*names: str) -> str | None:
    return _env_with_name(*names)[1]


def _env_with_name(*names: str) -> tuple[str | None, str | None]:
    _ensure_simple_tools_env_loaded()
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return name, str(value).strip()
    return None, None


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def _truncate_text(value: Any, *, limit: int = 200) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _payload_alias_map(definition: SimpleToolDefinition) -> dict[str, tuple[str, ...]]:
    alias_map: dict[str, list[str]] = {}
    for target, alias in definition.payload_aliases:
        alias_map.setdefault(target, []).append(alias)
    return {key: tuple(values) for key, values in alias_map.items()}


def _payload_value_for_field(payload: dict[str, Any], field_name: str, aliases: tuple[str, ...]) -> Any:
    if field_name in payload:
        return payload.get(field_name)
    for alias in aliases:
        if alias in payload:
            return payload.get(alias)
    return None


def _build_tool_variables(resolved: ResolvedSimpleTool, prepared_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        alias: _normalize_value(prepared_payload.get(field_name))
        for field_name, alias in resolved.variable_aliases.items()
        if field_name in prepared_payload
    }


def _collect_candidate_paths(data: Any, resolved: ResolvedSimpleTool) -> list[str]:
    paths: list[str] = []
    for source, candidate in _iter_structured_candidate_sources(data):
        paths.append(source)
        if isinstance(candidate, dict):
            for field in resolved.updated_variables:
                if field in candidate:
                    paths.append(f"{source}.{field}")
    for source, _ in _iter_tool_text_candidates(
        data,
        prefer_named_text_over_choices=resolved.prefer_named_text_over_choices,
    ):
        paths.append(source)
    if isinstance(data, dict):
        for field in resolved.updated_variables:
            if field in data:
                paths.append(f"root.{field}")
    return list(dict.fromkeys(paths))


def _collect_updated_variable_values(data: Any, resolved: ResolvedSimpleTool) -> dict[str, Any]:
    collected: dict[str, Any] = {}
    for _, candidate in _iter_structured_candidate_sources(data):
        if not isinstance(candidate, dict):
            continue
        for field in resolved.updated_variables:
            if field in candidate and field not in collected:
                collected[field] = candidate.get(field)
    if isinstance(data, dict):
        for field in resolved.updated_variables:
            if field in data and field not in collected:
                collected[field] = data.get(field)
    return collected


def _find_system_error_text(data: Any) -> str:
    matches = _find_named_values(data, {"system_error_text", "systemerrortext"})
    for value in matches:
        text = _render_tool_text(value).strip()
        if text:
            return text
    return ""


def _find_transient_error_text(data: Any) -> str:
    text = _json_text(data).lower()
    if "transient error" in text:
        return "transient error"
    return ""


def _find_auth_error_text(data: Any, *, status_code: int | None = None) -> str:
    text = _json_text(data)
    lowered = text.lower()
    if "unauthapikey" in lowered or "unauthorized" in lowered:
        return text
    if status_code in {401, 403}:
        return text or f"HTTP {status_code}"
    return ""


def _find_named_values(data: Any, target_keys: set[str], *, _depth: int = 0) -> list[Any]:
    if _depth > 5:
        return []
    matches: list[Any] = []
    if isinstance(data, dict):
        for key, value in data.items():
            normalized = str(key or "").replace("_", "").lower()
            if normalized in target_keys:
                matches.append(value)
            if isinstance(value, (dict, list)):
                matches.extend(_find_named_values(value, target_keys, _depth=_depth + 1))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                matches.extend(_find_named_values(item, target_keys, _depth=_depth + 1))
    return matches


def _build_attempt_debug(
    *,
    tool_key: str,
    attempt_index: int,
    status_code: int | None,
    api_info: dict[str, Any],
    request_variable_keys: list[str],
    response_preview: str,
    candidate_paths: list[str],
    updated_variables: dict[str, Any],
    visible_output_fields: list[str],
    failure_reason: str,
) -> dict[str, Any]:
    return {
        "tool_key": tool_key,
        "attempt_index": attempt_index,
        "status_code": status_code,
        "api_key_present": api_info["present"],
        "api_key_source": api_info["source"],
        "request_variable_keys": list(request_variable_keys),
        "response_preview": response_preview,
        "extracted_candidate_paths": list(candidate_paths),
        "updated_variables": copy.deepcopy(updated_variables),
        "visible_output_fields": list(visible_output_fields),
        "failure_reason": failure_reason,
    }


def _log_attempt_failure(attempt_debug: dict[str, Any]) -> None:
    logger.warning(
        "辅助工具 %s 第 %s 次尝试失败，status=%s，api_key_present=%s，api_key_source=%s，请求变量=%s，failure_reason=%s，candidate_paths=%s，updated_variables=%s，visible_output_fields=%s，response_preview=%s",
        attempt_debug.get("tool_key"),
        attempt_debug.get("attempt_index"),
        attempt_debug.get("status_code"),
        attempt_debug.get("api_key_present"),
        attempt_debug.get("api_key_source"),
        ", ".join(attempt_debug.get("request_variable_keys") or []),
        attempt_debug.get("failure_reason"),
        ", ".join(attempt_debug.get("extracted_candidate_paths") or []),
        ", ".join(sorted((attempt_debug.get("updated_variables") or {}).keys())),
        ", ".join(attempt_debug.get("visible_output_fields") or []),
        _truncate_text(attempt_debug.get("response_preview"), limit=400),
    )


def _build_failure_debug(
    resolved: ResolvedSimpleTool,
    *,
    env_debug: dict[str, Any],
    variables: dict[str, Any],
    payload_debug: dict[str, Any],
    status_code: int,
    response_preview: str,
    parsed_response: Any,
    candidate_paths: list[str],
    updated_variables: dict[str, Any],
    retry_attempts: list[dict[str, Any]],
    final_failure_reason: str,
) -> dict[str, Any]:
    parsed_response_keys: list[str]
    if isinstance(parsed_response, dict):
        parsed_response_keys = sorted(parsed_response.keys())
    elif isinstance(parsed_response, list):
        parsed_response_keys = [f"list[{len(parsed_response)}]"]
    elif parsed_response is None:
        parsed_response_keys = []
    else:
        parsed_response_keys = [type(parsed_response).__name__]
    return {
        **env_debug,
        "workflow_json_path": str(resolved.json_path) if resolved.json_path else "",
        "workflow_json_file": resolved.json_path.name if resolved.json_path else None,
        "status_code": status_code,
        "request_variables": copy.deepcopy(variables),
        "normalized_payload": copy.deepcopy(payload_debug),
        "response_preview": response_preview,
        "parsed_response_keys": parsed_response_keys,
        "candidate_paths": list(candidate_paths),
        "updated_variables": copy.deepcopy(updated_variables),
        "visible_output_fields": list(resolved.visible_output_fields),
        "retry_attempts": copy.deepcopy(retry_attempts),
        "final_failure_reason": final_failure_reason,
    }


def _write_simple_tool_debug_artifact(debug_payload: dict[str, Any]) -> str:
    try:
        base_dir = get_runtime_data_dir() / "debug" / "simple_tools"
        base_dir.mkdir(parents=True, exist_ok=True)
        tool_key = str(debug_payload.get("tool_key") or debug_payload.get("tool_id") or "tool").strip() or "tool"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = base_dir / f"{tool_key}__{timestamp}.json"
        path.write_text(
            json.dumps(debug_payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return str(path)
    except Exception:
        logger.warning("辅助工具 debug artifact 写入失败", exc_info=True)
        return ""


def _missing_api_key_message(resolved: ResolvedSimpleTool) -> str:
    if resolved.definition.key == "hot_review":
        return (
            "当前 Python 进程未读取到 FASTGPT_HOT_REVIEW_API_KEY。"
            "请检查 .env 是否被加载、PyCharm/PowerShell 是否重启、Run Configuration 是否配置环境变量。"
        )
    return (
        f"{resolved.definition.label} 还未配置 API Key，请先配置 {resolved.api_key_envs[0]}。"
        "如需兜底，也可以配置 FASTGPT_API_KEY。"
    )


def _unauthorized_api_key_message(
    resolved: ResolvedSimpleTool,
    url_info: dict[str, Any],
) -> str:
    url_env = str(url_info.get("env") or resolved.url_envs[0])
    return (
        f"{resolved.definition.label} 请求已发出，但 FastGPT 返回 unAuthApiKey。"
        f"这表示当前 {resolved.api_key_envs[0]} 对 {url_env} 指向的 FastGPT 实例或应用没有授权；"
        f"请换成该换皮应用对应的 API Key，或为本工具单独配置 {resolved.url_envs[0]} 指向匹配的服务地址。"
    )


def _generic_empty_output_message(label: str) -> str:
    return f"{label} 没有返回可展示结果。请检查 workflow 最终输出是否写到了正式变量。"
