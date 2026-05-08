from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

from ..config import settings
from ..utils.logger import get_logger
from .json_utils import parse_json, strip_code_fence
from .runtime_paths import get_runtime_data_dir

logger = get_logger("framework_planner_service")

DEFAULT_FASTGPT_URL = "https://api.fastgpt.in/api/v1/chat/completions"
FRAMEWORK_PLANNER_STORAGE_KEY = "frameworkPlannerState.v2"
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
FRAMEWORK_CONTRACT_GLOB = "00_*.md"
REQUIRED_BEAT_FIELDS = (
    "beat_no",
    "beat_name",
    "act",
    "episode_range",
    "checkpoint_title",
    "narrative_function",
    "plot_content",
    "character_change",
    "conflict_upgrade",
    "hook_or_reversal",
    "linked_storylines",
)
FIFTEEN_BEAT_NAMES = (
    "开场",
    "主体呈现",
    "铺垫",
    "推动催化剂",
    "争执",
    "第二幕衔接点",
    "B故事线",
    "游戏及斗争",
    "中点",
    "危险逼近",
    "一败涂地",
    "灵魂黑夜",
    "第三幕衔接点",
    "结局",
    "终场画面",
)


@dataclass(frozen=True, slots=True)
class FrameworkPlannerStageDefinition:
    stage: str
    label: str
    env_prefix: str
    workflow_glob: str
    input_fields: tuple[str, ...]
    output_fields: tuple[str, ...]
    required_fields: tuple[str, ...]
    input_aliases: dict[str, tuple[str, ...]]
    output_aliases: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class FrameworkPlannerWorkflowSpec:
    stage: str
    path: Path
    public_variable_keys: tuple[str, ...]
    internal_variable_keys: tuple[str, ...]
    answer_node_names: tuple[str, ...]
    contract_path: Path | None


@dataclass(frozen=True, slots=True)
class FrameworkPlannerEndpoint:
    url: str
    url_source: str
    api_key: str
    api_key_source: str
    workflow_id: str
    workflow_id_source: str
    chat_id: str
    timeout: int


LEGACY_STAGE_API_KEY_ENVS: dict[str, tuple[str, ...]] = {
    "01": ("FASTGPT_BETTER_FRAMEWORK_EXTRACT",),
    "02": ("FASTGPT_BETTER_FRAMEWORK_WORLDVIEW",),
    "03": ("FASTGPT_BETTER_FRAMEWORK_CHARACTERS",),
    "04": ("FASTGPT_BETTER_FRAMEWORK_PLOT_KEY_POINT_PLANNING",),
    "05": ("FASTGPT_BETTER_FRAMEWORK_CHARACTER_STORYLINE",),
    "06": ("FASTGPT_BETTER_FRAMEWORK_GENERATE_UPDATE",),
    "07": ("FASTGPT_BETTER_FRAMEWORK_FRAMEWORK_INSPECTION",),
}


class FrameworkPlannerStageError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str,
        status_code: int = 400,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.status_code = status_code
        self.detail = detail or {}


STAGE_DEFINITIONS: dict[str, FrameworkPlannerStageDefinition] = {
    "01": FrameworkPlannerStageDefinition(
        stage="01",
        label="原文信息提取",
        env_prefix="FASTGPT_FRAMEWORK_01_SOURCE_BRIEF",
        workflow_glob="01_*.json",
        input_fields=(
            "mode",
            "source_text",
            "source_title",
            "target_format",
            "season_count",
            "episodes_per_season",
            "minutes_per_episode",
            "adaptation_direction",
            "user_constraints",
            "user_requirements",
        ),
        output_fields=("source_brief",),
        required_fields=(
            "source_title",
            "target_format",
            "season_count",
            "episodes_per_season",
        ),
        input_aliases={
            "mode": ("mode", "zHrEcynX"),
            "source_text": ("source_text",),
            "source_title": ("source_title",),
            "target_format": ("target_format",),
            "season_count": ("season_count",),
            "episodes_per_season": ("episodes_per_season",),
            "minutes_per_episode": ("minutes_per_episode",),
            "adaptation_direction": ("adaptation_direction",),
            "user_constraints": ("user_constraints",),
            "user_requirements": ("user_requirements",),
        },
        output_aliases={
            "source_brief": ("source_brief",),
        },
    ),
    "02": FrameworkPlannerStageDefinition(
        stage="02",
        label="世界观方案生成更新",
        env_prefix="FASTGPT_FRAMEWORK_02_WORLDVIEW",
        workflow_glob="02_*.json",
        input_fields=(
            "mode",
            "source_brief",
            "locked_basic_config",
            "basic_config",
            "previous_worldview_plan",
            "user_feedback",
            "adaptation_direction",
            "user_requirements",
        ),
        output_fields=("worldview_plan",),
        required_fields=("source_brief", "locked_basic_config"),
        input_aliases={
            "mode": ("mode",),
            "source_brief": ("source_brief",),
            "locked_basic_config": ("locked_basic_config", "basic_config"),
            "basic_config": ("basic_config", "locked_basic_config"),
            "previous_worldview_plan": ("previous_worldview_plan",),
            "user_feedback": ("user_feedback",),
            "adaptation_direction": ("adaptation_direction",),
            "user_requirements": ("user_requirements",),
        },
        output_aliases={
            "worldview_plan": ("worldview_plan",),
        },
    ),
    "03": FrameworkPlannerStageDefinition(
        stage="03",
        label="人设方案生成更新",
        env_prefix="FASTGPT_FRAMEWORK_03_CHARACTER",
        workflow_glob="03_*.json",
        input_fields=(
            "mode",
            "source_brief",
            "locked_basic_config",
            "basic_config",
            "worldview_plan",
            "previous_character_plan",
            "user_feedback",
            "adaptation_direction",
            "user_requirements",
        ),
        output_fields=("character_plan",),
        required_fields=("source_brief", "locked_basic_config", "worldview_plan"),
        input_aliases={
            "mode": ("mode",),
            "source_brief": ("source_brief",),
            "locked_basic_config": ("locked_basic_config", "basic_config"),
            "basic_config": ("basic_config", "locked_basic_config"),
            "worldview_plan": ("worldview_plan",),
            "previous_character_plan": ("previous_character_plan",),
            "user_feedback": ("user_feedback",),
            "adaptation_direction": ("adaptation_direction",),
            "user_requirements": ("user_requirements",),
        },
        output_aliases={
            "character_plan": ("character_plan",),
        },
    ),
    "04": FrameworkPlannerStageDefinition(
        stage="04",
        label="三幕十五节拍卡点规划生成更新",
        env_prefix="FASTGPT_FRAMEWORK_04_BEAT",
        workflow_glob="04_*.json",
        input_fields=(
            "mode",
            "source_brief",
            "basic_config",
            "worldview_plan",
            "character_plan",
            "previous_beat_checkpoint_timeline",
            "user_feedback",
            "framework_score_report",
            "adaptation_direction",
            "user_requirements",
        ),
        output_fields=("beat_checkpoint_timeline", "checkpoint_explanation"),
        required_fields=("source_brief", "basic_config", "worldview_plan", "character_plan"),
        input_aliases={
            "mode": ("mode",),
            "source_brief": ("source_brief",),
            "basic_config": ("basic_config",),
            "worldview_plan": ("worldview_plan",),
            "character_plan": ("character_plan",),
            "previous_beat_checkpoint_timeline": ("previous_beat_checkpoint_timeline",),
            "user_feedback": ("user_feedback",),
            "framework_score_report": ("framework_score_report",),
            "adaptation_direction": ("adaptation_direction",),
            "user_requirements": ("user_requirements",),
        },
        output_aliases={
            "beat_checkpoint_timeline": ("beat_checkpoint_timeline", "timeline"),
            "checkpoint_explanation": ("checkpoint_explanation", "explanation", "beat_explanation"),
        },
    ),
    "05": FrameworkPlannerStageDefinition(
        stage="05",
        label="人物故事线生成更新",
        env_prefix="FASTGPT_FRAMEWORK_05_STORYLINE",
        workflow_glob="05_*.json",
        input_fields=(
            "mode",
            "source_brief",
            "basic_config",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint_timeline",
            "previous_character_storylines",
            "current_storyline_decisions",
            "user_feedback",
            "adaptation_direction",
            "user_requirements",
        ),
        output_fields=("character_storylines",),
        required_fields=(
            "source_brief",
            "basic_config",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint_timeline",
        ),
        input_aliases={
            "mode": ("mode",),
            "source_brief": ("source_brief",),
            "basic_config": ("basic_config",),
            "worldview_plan": ("worldview_plan",),
            "character_plan": ("character_plan",),
            "beat_checkpoint_timeline": ("beat_checkpoint_timeline",),
            "previous_character_storylines": ("previous_character_storylines",),
            "current_storyline_decisions": ("current_storyline_decisions", "storyline_decisions"),
            "user_feedback": ("user_feedback",),
            "adaptation_direction": ("adaptation_direction",),
            "user_requirements": ("user_requirements",),
        },
        output_aliases={
            "character_storylines": ("character_storylines", "storylines"),
        },
    ),
    "06": FrameworkPlannerStageDefinition(
        stage="06",
        label="整体改编指引生成更新",
        env_prefix="FASTGPT_FRAMEWORK_06_GUIDE",
        workflow_glob="06_*.json",
        input_fields=(
            "mode",
            "source_brief",
            "basic_config",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint_timeline",
            "character_storylines",
            "storyline_decisions",
            "previous_adaptation_guide",
            "user_feedback",
            "adaptation_direction",
            "user_requirements",
        ),
        output_fields=("adaptation_guide",),
        required_fields=(
            "source_brief",
            "basic_config",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint_timeline",
            "character_storylines",
        ),
        input_aliases={
            "mode": ("mode",),
            "source_brief": ("source_brief",),
            "basic_config": ("basic_config",),
            "worldview_plan": ("worldview_plan",),
            "character_plan": ("character_plan",),
            "beat_checkpoint_timeline": ("beat_checkpoint_timeline",),
            "character_storylines": ("character_storylines",),
            "storyline_decisions": ("storyline_decisions",),
            "previous_adaptation_guide": ("previous_adaptation_guide",),
            "user_feedback": ("user_feedback",),
            "adaptation_direction": ("adaptation_direction",),
            "user_requirements": ("user_requirements",),
        },
        output_aliases={
            "adaptation_guide": ("adaptation_guide", "guide"),
        },
    ),
    "07": FrameworkPlannerStageDefinition(
        stage="07",
        label="框架策划包校验",
        env_prefix="FASTGPT_FRAMEWORK_07_PACKAGE",
        workflow_glob="07_*.json",
        input_fields=(
            "mode",
            "basic_config",
            "source_brief",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint_timeline",
            "checkpoint_explanation",
            "character_storylines",
            "storyline_decisions",
            "adaptation_guide",
            "user_edit_history",
            "previous_framework_plan_package",
            "user_feedback",
            "adaptation_direction",
            "user_requirements",
        ),
        output_fields=("framework_plan_package", "validation_report"),
        required_fields=(
            "basic_config",
            "source_brief",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint_timeline",
            "character_storylines",
            "adaptation_guide",
        ),
        input_aliases={
            "mode": ("mode",),
            "basic_config": ("basic_config",),
            "source_brief": ("source_brief",),
            "worldview_plan": ("worldview_plan",),
            "character_plan": ("character_plan",),
            "beat_checkpoint_timeline": ("beat_checkpoint_timeline",),
            "checkpoint_explanation": ("checkpoint_explanation",),
            "character_storylines": ("character_storylines",),
            "storyline_decisions": ("storyline_decisions",),
            "adaptation_guide": ("adaptation_guide",),
            "user_edit_history": ("user_edit_history",),
            "previous_framework_plan_package": ("previous_framework_plan_package",),
            "user_feedback": ("user_feedback",),
            "adaptation_direction": ("adaptation_direction",),
            "user_requirements": ("user_requirements",),
        },
        output_aliases={
            "framework_plan_package": ("framework_plan_package", "package"),
            "validation_report": ("validation_report", "validation"),
        },
    ),
}


def stage_definition(stage: str) -> FrameworkPlannerStageDefinition:
    definition = STAGE_DEFINITIONS.get(str(stage).zfill(2))
    if definition is None:
        raise FrameworkPlannerStageError(
            "未知的框架策划阶段",
            stage=str(stage),
            status_code=404,
            detail={"stage": stage},
        )
    return definition


def framework_planner_backend_ready() -> bool:
    return any(stage_has_real_backend(stage) for stage in STAGE_DEFINITIONS)


def stage_has_real_backend(stage: str) -> bool:
    definition = stage_definition(stage)
    for env_name in _stage_api_key_env_names(definition):
        if _env(env_name):
            return True
    return False


def run_framework_planner_stage(stage: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    definition = stage_definition(stage)
    normalized_payload = _normalize_payload(payload)
    workflow_spec = load_stage_workflow_spec(definition.stage)
    if _should_use_mock_backend(definition):
        data, display_text = _build_mock_stage_output(definition.stage, normalized_payload)
        return {
            "ok": True,
            "stage": definition.stage,
            "data": data,
            "raw": {
                "mock": True,
                "workflow_json_path": str(workflow_spec.path),
                "workflow_contract_path": str(workflow_spec.contract_path) if workflow_spec.contract_path else "",
            },
            "display_text": display_text,
        }

    request_variables = _build_stage_request_variables(definition, normalized_payload, workflow_spec)
    endpoint = _resolve_stage_endpoint(definition)
    body = _build_request_body(definition, request_variables, endpoint)
    headers = {
        "Authorization": f"Bearer {endpoint.api_key}",
        "Content-Type": "application/json",
    }
    response = _post_with_retries(definition, endpoint, headers, body)
    response_text = _safe_response_text(response)
    try:
        response_json = response.json()
    except ValueError as exc:
        debug_detail = _write_debug_artifact(
            stage=definition.stage,
            workflow_spec=workflow_spec,
            request_variables=request_variables,
            payload=normalized_payload,
            response_raw=response_text,
            parse_error="response.json invalid",
        )
        logger.warning(
            "框架策划阶段 %s 返回非法 JSON 响应，payload_keys=%s",
            definition.stage,
            sorted(normalized_payload.keys()),
        )
        raise FrameworkPlannerStageError(
            "当前阶段返回格式异常，请重试或查看日志",
            stage=definition.stage,
            status_code=502,
            detail=debug_detail,
        ) from exc

    try:
        data, display_text = _extract_stage_output(
            definition=definition,
            workflow_spec=workflow_spec,
            response_json=response_json,
        )
    except Exception as exc:
        debug_detail = _write_debug_artifact(
            stage=definition.stage,
            workflow_spec=workflow_spec,
            request_variables=request_variables,
            payload=normalized_payload,
            response_raw=response_json,
            parse_error=str(exc),
        )
        logger.warning(
            "框架策划阶段 %s 输出解析失败，payload_keys=%s，error=%s",
            definition.stage,
            sorted(normalized_payload.keys()),
            exc,
        )
        raise FrameworkPlannerStageError(
            "当前阶段返回格式异常，请重试或查看日志",
            stage=definition.stage,
            status_code=502,
            detail=debug_detail,
        ) from exc

    return {
        "ok": True,
        "stage": definition.stage,
        "data": data,
            "raw": {
                "mock": False,
                "workflow_json_path": str(workflow_spec.path),
                "workflow_contract_path": str(workflow_spec.contract_path) if workflow_spec.contract_path else "",
                "url": endpoint.url,
                "workflow_id": endpoint.workflow_id,
                "response": response_json,
        },
        "display_text": display_text,
    }


def run_framework_planner_score(payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized_payload = _normalize_payload(payload)
    timeline = normalized_payload.get("beat_checkpoint_timeline")
    explanation = normalized_payload.get("checkpoint_explanation")
    missing_fields: list[str] = []
    beat_count = 0
    if isinstance(timeline, list):
        beat_count = len(timeline)
        for index, item in enumerate(timeline, start=1):
            if not isinstance(item, dict):
                missing_fields.append(f"beat[{index}]")
                continue
            for field in (
                "beat_no",
                "beat_name",
                "act",
                "episode_range",
                "checkpoint_title",
                "narrative_function",
                "plot_content",
                "hook_or_reversal",
            ):
                if _is_blank(item.get(field)):
                    missing_fields.append(f"beat[{index}].{field}")
    else:
        missing_fields.append("beat_checkpoint_timeline")
    if explanation in (None, "", {}):
        missing_fields.append("checkpoint_explanation")

    if beat_count == 15 and not missing_fields:
        report = (
            "PASS\n"
            "总评：当前三幕十五节拍卡点时间轴结构完整，关键字段齐全，可进入下一阶段。\n"
            "建议：后续只需在人物故事线阶段继续核对 linked_storylines 与节拍分布的一致性。"
        )
    else:
        missing_text = "、".join(missing_fields) if missing_fields else "未知缺口"
        report = (
            "REVISE\n"
            f"总评：当前框架仍需修订，beat 数量={beat_count}。\n"
            f"问题定位：缺少或不完整字段 {missing_text}。\n"
            "建议：补齐 15 条节拍，并完善每条节拍的核心叙事字段后重新评分。"
        )

    return {
        "ok": True,
        "stage": "04",
        "data": {"framework_score_report": report},
        "raw": {
            "mock": True,
            "score_source": "framework_planner_score_mock",
            "beat_count": beat_count,
            "missing_fields": missing_fields,
        },
        "display_text": report,
    }


@lru_cache(maxsize=1)
def framework_workflow_dir() -> Path:
    configured = _env("FRAMEWORK_PLANNER_WORKFLOW_DIR")
    if configured:
        path = Path(configured).expanduser().resolve()
    else:
        path = Path(__file__).resolve().parents[3] / "BETTER_FRAMEWORK_JSONS"
    if not path.exists():
        raise FrameworkPlannerStageError(
            "未找到 BETTER_FRAMEWORK_JSONS 工作流目录",
            stage="00",
            status_code=500,
            detail={"workflow_dir": str(path)},
        )
    return path


@lru_cache(maxsize=1)
def resolve_framework_contract_path() -> Path | None:
    exact = framework_workflow_dir() / "00_CONTRACT.md"
    if exact.exists():
        return exact
    matches = sorted(framework_workflow_dir().glob(FRAMEWORK_CONTRACT_GLOB))
    if matches:
        return matches[0]
    return None


@lru_cache(maxsize=None)
def resolve_stage_workflow_path(stage: str) -> Path:
    definition = stage_definition(stage)
    matches = sorted(framework_workflow_dir().glob(definition.workflow_glob))
    if not matches:
        raise FrameworkPlannerStageError(
            f"未找到阶段 {definition.stage} 对应的工作流 JSON",
            stage=definition.stage,
            status_code=500,
            detail={
                "workflow_dir": str(framework_workflow_dir()),
                "workflow_glob": definition.workflow_glob,
            },
        )
    return matches[0]


@lru_cache(maxsize=None)
def load_stage_workflow_spec(stage: str) -> FrameworkPlannerWorkflowSpec:
    path = resolve_stage_workflow_path(stage)
    try:
        workflow = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise FrameworkPlannerStageError(
            f"无法读取阶段 {stage} 工作流 JSON",
            stage=stage,
            status_code=500,
            detail={"workflow_json_path": str(path)},
        ) from exc

    public_keys: list[str] = []
    internal_keys: list[str] = []
    for item in (workflow.get("chatConfig") or {}).get("variables") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        if str(item.get("type") or "").strip().lower() == "internal":
            internal_keys.append(key)
        else:
            public_keys.append(key)

    answer_node_names = tuple(
        str(node.get("name") or node.get("nodeId") or "").strip()
        for node in (workflow.get("nodes") or [])
        if isinstance(node, dict) and str(node.get("flowNodeType") or "").strip() == "answerNode"
    )
    return FrameworkPlannerWorkflowSpec(
        stage=str(stage).zfill(2),
        path=path,
        public_variable_keys=tuple(public_keys),
        internal_variable_keys=tuple(internal_keys),
        answer_node_names=tuple(name for name in answer_node_names if name),
        contract_path=resolve_framework_contract_path(),
    )


def _normalize_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})


def _should_use_mock_backend(definition: FrameworkPlannerStageDefinition) -> bool:
    configured = _env_bool("FRAMEWORK_PLANNER_USE_MOCK", default=False)
    if configured:
        return True
    return not stage_has_real_backend(definition.stage)


def _build_stage_request_variables(
    definition: FrameworkPlannerStageDefinition,
    payload: dict[str, Any],
    workflow_spec: FrameworkPlannerWorkflowSpec,
) -> dict[str, Any]:
    variables: dict[str, Any] = {}
    missing_fields: list[str] = []
    public_keys = set(workflow_spec.public_variable_keys)

    for field in definition.input_fields:
        aliases = definition.input_aliases.get(field, (field,))
        value = _first_present_value(payload, aliases)
        if field == "locked_basic_config" and _is_blank(value):
            value = payload.get("basic_config")
        if field == "basic_config" and _is_blank(value):
            value = payload.get("locked_basic_config")
        if field in definition.required_fields and _is_blank(value):
            missing_fields.append(field)
            continue
        if _is_blank(value):
            continue
        wire_value = _wire_value(value)
        variables[field] = wire_value
        for alias in aliases:
            if alias == field or alias in public_keys:
                variables[alias] = wire_value

    if missing_fields:
        raise FrameworkPlannerStageError(
            f"阶段 {definition.stage} 缺少必填项：{', '.join(missing_fields)}",
            stage=definition.stage,
            status_code=400,
            detail={"missing_fields": missing_fields},
        )

    for key, value in payload.items():
        if key in variables or _is_blank(value):
            continue
        variables[key] = _wire_value(value)

    return variables


def _resolve_stage_endpoint(definition: FrameworkPlannerStageDefinition) -> FrameworkPlannerEndpoint:
    api_key_envs = _stage_api_key_env_names(definition)
    api_key_source, api_key = _env_with_name(*api_key_envs)
    if not api_key:
        raise FrameworkPlannerStageError(
            "未配置 FastGPT API Key",
            stage=definition.stage,
            status_code=500,
            detail={"expected_envs": list(api_key_envs)},
        )

    url_source, raw_url = _env_with_name(
        f"{definition.env_prefix}_URL",
        f"{definition.env_prefix}_CHAT_COMPLETIONS_URL",
        f"{definition.env_prefix}_BASE_URL",
        "FASTGPT_FRAMEWORK_URL",
        "FASTGPT_FRAMEWORK_CHAT_COMPLETIONS_URL",
        "FASTGPT_FRAMEWORK_BASE_URL",
        "FASTGPT_CHAT_COMPLETIONS_URL",
        "FASTGPT_BASE_URL",
    )
    url = _normalize_fastgpt_url(raw_url or DEFAULT_FASTGPT_URL)

    workflow_id_source, workflow_id = _env_with_name(
        f"{definition.env_prefix}_WORKFLOW_ID",
        "FASTGPT_FRAMEWORK_WORKFLOW_ID",
    )

    timeout = int(_env(f"{definition.env_prefix}_TIMEOUT", "FASTGPT_TIMEOUT") or getattr(settings, "fastgpt_timeout", 300))
    chat_id_prefix = _env("FASTGPT_CHAT_ID_PREFIX") or "framework-planner"
    chat_id = _env(f"{definition.env_prefix}_CHAT_ID") or f"{chat_id_prefix}-{definition.stage}-{uuid.uuid4().hex[:8]}"

    return FrameworkPlannerEndpoint(
        url=url,
        url_source=url_source or "default",
        api_key=api_key,
        api_key_source=api_key_source or "FASTGPT_API_KEY",
        workflow_id=str(workflow_id or "").strip(),
        workflow_id_source=workflow_id_source or "",
        chat_id=chat_id,
        timeout=max(1, timeout),
    )


def _stage_api_key_env_names(definition: FrameworkPlannerStageDefinition) -> tuple[str, ...]:
    return (
        f"{definition.env_prefix}_API_KEY",
        *LEGACY_STAGE_API_KEY_ENVS.get(definition.stage, ()),
        "FASTGPT_FRAMEWORK_API_KEY",
        "FASTGPT_API_KEY",
    )


def _build_request_body(
    definition: FrameworkPlannerStageDefinition,
    variables: dict[str, Any],
    endpoint: FrameworkPlannerEndpoint,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "chatId": endpoint.chat_id,
        "stream": False,
        "detail": True,
        "variables": variables,
        "messages": [
            {
                "role": "user",
                "content": f"执行剧本框架策划阶段 {definition.stage}：{definition.label}。请只返回约定输出。",
            }
        ],
    }
    if endpoint.workflow_id:
        # 兼容“统一 Key + 按 workflow id 指向不同工作流”的场景；
        # 若上游网关不识别该字段，会忽略它，不影响 app-specific key 场景。
        body["appId"] = endpoint.workflow_id
    return body


def _post_with_retries(
    definition: FrameworkPlannerStageDefinition,
    endpoint: FrameworkPlannerEndpoint,
    headers: dict[str, str],
    body: dict[str, Any],
) -> requests.Response:
    attempts = max(1, int(getattr(settings, "fastgpt_http_retries", 2)) + 1)
    delay = max(0.0, float(getattr(settings, "fastgpt_http_retry_delay", 1.5)))
    last_exception: Exception | None = None

    for attempt_index in range(1, attempts + 1):
        try:
            response = requests.post(
                endpoint.url,
                headers=headers,
                json=body,
                timeout=endpoint.timeout,
            )
        except requests.Timeout as exc:
            last_exception = exc
            if attempt_index >= attempts:
                raise FrameworkPlannerStageError(
                    f"阶段 {definition.stage} 请求超时",
                    stage=definition.stage,
                    status_code=504,
                    detail={"url": endpoint.url},
                ) from exc
            time.sleep(delay * attempt_index)
            continue
        except requests.RequestException as exc:
            last_exception = exc
            if attempt_index >= attempts:
                raise FrameworkPlannerStageError(
                    f"阶段 {definition.stage} 网络请求失败",
                    stage=definition.stage,
                    status_code=502,
                    detail={"url": endpoint.url},
                ) from exc
            time.sleep(delay * attempt_index)
            continue

        if response.status_code in RETRYABLE_HTTP_STATUSES and attempt_index < attempts:
            time.sleep(delay * attempt_index)
            continue

        if response.status_code >= 400:
            raise FrameworkPlannerStageError(
                f"阶段 {definition.stage} 请求失败",
                stage=definition.stage,
                status_code=502 if response.status_code >= 500 else 400,
                detail={
                    "url": endpoint.url,
                    "status_code": response.status_code,
                    "response_preview": _truncate_text(_safe_response_text(response), limit=1200),
                },
            )
        return response

    raise FrameworkPlannerStageError(
        f"阶段 {definition.stage} 请求失败：{last_exception}",
        stage=definition.stage,
        status_code=502,
    )


def _extract_stage_output(
    *,
    definition: FrameworkPlannerStageDefinition,
    workflow_spec: FrameworkPlannerWorkflowSpec,
    response_json: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    output_aliases = definition.output_aliases
    for _source, candidate in _iter_response_candidates(response_json, workflow_spec):
        mapped = _coerce_candidate_to_stage_output(definition, candidate, output_aliases)
        if mapped is not None:
            normalized = _normalize_stage_output(definition.stage, mapped)
            display_text = _extract_display_text(response_json, normalized)
            return normalized, display_text
    raise ValueError(
        f"未能从阶段 {definition.stage} 的返回结果中提取输出字段：{definition.output_fields}"
    )


def _iter_response_candidates(
    response_json: dict[str, Any],
    workflow_spec: FrameworkPlannerWorkflowSpec,
):
    containers = [
        ("root", response_json),
        ("root.newVariables", response_json.get("newVariables")),
        ("root.responseData", (response_json.get("responseData") or {})),
        (
            "root.responseData.newVariables",
            ((response_json.get("responseData") or {}).get("newVariables")),
        ),
    ]
    for source, value in containers:
        if value not in (None, "", [], {}):
            yield source, value
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in workflow_spec.internal_variable_keys or key in workflow_spec.public_variable_keys:
                    if nested not in (None, "", [], {}):
                        yield f"{source}.{key}", nested

    for list_source, items in (
        ("root.updateVarResult", response_json.get("updateVarResult")),
        ("root.responseData.updateVarResult", (response_json.get("responseData") or {}).get("updateVarResult")),
    ):
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            variable = item.get("variable")
            if isinstance(variable, list):
                variable_key = str(variable[-1] or "").strip()
            else:
                variable_key = str(variable or item.get("key") or "").strip()
            value = item.get("value")
            if variable_key in workflow_spec.internal_variable_keys or variable_key in workflow_spec.public_variable_keys:
                if value not in (None, "", [], {}):
                    yield f"{list_source}[{index}].value", value

    for source, value in (
        ("root.answerText", response_json.get("answerText")),
        ("root.responseData.answerText", (response_json.get("responseData") or {}).get("answerText")),
        ("root.responseData.responseText", (response_json.get("responseData") or {}).get("responseText")),
    ):
        if value not in (None, "", [], {}):
            yield source, value

    for index, choice in enumerate(response_json.get("choices") or []):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") or {}
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if content not in (None, "", [], {}):
            yield f"choices[{index}].message.content", content


def _coerce_candidate_to_stage_output(
    definition: FrameworkPlannerStageDefinition,
    candidate: Any,
    output_aliases: dict[str, tuple[str, ...]],
) -> dict[str, Any] | None:
    parsed = _parse_candidate_value(candidate)
    if parsed is None:
        return None

    if len(definition.output_fields) == 1:
        field = definition.output_fields[0]
        if isinstance(parsed, dict):
            direct = _find_value_by_aliases(parsed, output_aliases.get(field, (field,)))
            if direct is not None:
                return {field: direct}
            if "data" in parsed and isinstance(parsed["data"], dict):
                nested = _find_value_by_aliases(parsed["data"], output_aliases.get(field, (field,)))
                if nested is not None:
                    return {field: nested}
            if field in parsed:
                return {field: parsed[field]}
            return {field: parsed}
        return {field: parsed}

    if definition.stage == "04" and isinstance(parsed, list):
        return {
            "beat_checkpoint_timeline": parsed,
            "checkpoint_explanation": {},
        }

    if not isinstance(parsed, dict):
        return None

    data_source = parsed.get("data") if isinstance(parsed.get("data"), dict) else None
    mapped: dict[str, Any] = {}
    for field in definition.output_fields:
        aliases = output_aliases.get(field, (field,))
        value = _find_value_by_aliases(parsed, aliases)
        if value is None and data_source is not None:
            value = _find_value_by_aliases(data_source, aliases)
        if value is None and field == "framework_plan_package":
            value = parsed
        if value is None and field == "validation_report" and "validation" in parsed:
            value = parsed.get("validation")
        if value is not None:
            mapped[field] = value
    if mapped:
        return mapped
    return None


def _parse_candidate_value(candidate: Any) -> Any:
    if isinstance(candidate, (dict, list)):
        return candidate
    text = str(candidate or "").strip()
    if not text:
        return None
    try:
        return parse_json(text)
    except Exception:
        return strip_code_fence(text)


def _normalize_stage_output(stage: str, data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    if stage == "01":
        normalized["source_brief"] = _normalize_object_like(normalized.get("source_brief"), key_name="content")
        return normalized
    if stage == "02":
        normalized["worldview_plan"] = _normalize_object_like(normalized.get("worldview_plan"), key_name="content")
        return normalized
    if stage == "03":
        normalized["character_plan"] = _normalize_object_like(normalized.get("character_plan"), key_name="content")
        return normalized
    if stage == "04":
        normalized["beat_checkpoint_timeline"] = _normalize_beat_timeline(
            normalized.get("beat_checkpoint_timeline")
        )
        normalized["checkpoint_explanation"] = _normalize_checkpoint_explanation(
            normalized.get("checkpoint_explanation"),
            normalized["beat_checkpoint_timeline"],
        )
        return normalized
    if stage == "05":
        normalized["character_storylines"] = _normalize_character_storylines(
            normalized.get("character_storylines")
        )
        return normalized
    if stage == "06":
        normalized["adaptation_guide"] = _normalize_adaptation_guide(
            normalized.get("adaptation_guide")
        )
        return normalized
    if stage == "07":
        normalized["framework_plan_package"] = _normalize_object_like(
            normalized.get("framework_plan_package"),
            key_name="content",
        )
        normalized["validation_report"] = _normalize_validation_report(
            normalized.get("validation_report")
        )
        return normalized
    return normalized


def _extract_display_text(response_json: dict[str, Any], data: dict[str, Any]) -> str:
    for key in ("display_text", "displayText"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for value in (
        response_json.get("answerText"),
        (response_json.get("responseData") or {}).get("answerText"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(data, ensure_ascii=False, indent=2)


def _normalize_object_like(value: Any, *, key_name: str = "content") -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {key_name: value}
    text = str(value or "").strip()
    return {key_name: text} if text else {}


def _normalize_beat_timeline(value: Any) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else []
    ranges = _split_episode_ranges(_episodes_per_season_from_basic_config(None))
    normalized: list[dict[str, Any]] = []
    for index in range(15):
        raw = items[index] if index < len(items) and isinstance(items[index], dict) else {}
        beat_no = index + 1
        normalized.append(
            {
                "beat_no": raw.get("beat_no") or beat_no,
                "beat_name": str(raw.get("beat_name") or FIFTEEN_BEAT_NAMES[index]),
                "act": str(raw.get("act") or _act_for_beat(beat_no)),
                "episode_range": str(raw.get("episode_range") or ranges[index]),
                "checkpoint_title": str(raw.get("checkpoint_title") or f"{FIFTEEN_BEAT_NAMES[index]}卡点"),
                "narrative_function": str(raw.get("narrative_function") or raw.get("function") or ""),
                "plot_content": str(raw.get("plot_content") or raw.get("content") or ""),
                "character_change": str(raw.get("character_change") or ""),
                "conflict_upgrade": str(raw.get("conflict_upgrade") or ""),
                "hook_or_reversal": str(raw.get("hook_or_reversal") or raw.get("hook") or ""),
                "linked_storylines": _normalize_string_list(raw.get("linked_storylines")),
            }
        )
    return normalized


def _normalize_checkpoint_explanation(value: Any, timeline: list[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(value, dict):
        overview = str(value.get("overview") or value.get("summary") or "").strip()
        beat_notes = value.get("beat_notes")
        if not isinstance(beat_notes, list):
            beat_notes = []
        if beat_notes:
            return {
                "overview": overview,
                "beat_notes": beat_notes,
            }
    elif isinstance(value, str) and value.strip():
        return {
            "overview": value.strip(),
            "beat_notes": [
                {"beat_no": item["beat_no"], "explanation": item["plot_content"]}
                for item in timeline
            ],
        }
    return {
        "overview": "该卡点说明与同一条十五节拍时间轴一一对应，用于解释各节拍的叙事功能与阶段作用。",
        "beat_notes": [
            {
                "beat_no": item["beat_no"],
                "explanation": f"{item['beat_name']}：{item['narrative_function'] or item['plot_content']}",
            }
            for item in timeline
        ],
    }


def _normalize_character_storylines(value: Any) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else []
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            continue
        normalized.append(
            {
                "id": str(raw.get("id") or f"storyline_{index}"),
                "title": str(raw.get("title") or f"故事线 {index}"),
                "summary": str(raw.get("summary") or raw.get("content") or ""),
                "detailed_storyline": str(raw.get("detailed_storyline") or raw.get("detail") or raw.get("summary") or ""),
                "linked_beats": _normalize_int_list(raw.get("linked_beats") or raw.get("linked_storylines")),
                "episode_distribution": _normalize_episode_distribution(raw.get("episode_distribution")),
                "edit_notes": str(raw.get("edit_notes") or raw.get("detailNote") or ""),
                "decision": _normalize_storyline_decision(raw.get("decision")),
            }
        )
    return normalized


def _normalize_adaptation_guide(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        if {
            "core_setting_adjustments",
            "structure_and_rhythm",
            "visualization_strategy",
            "character_emotion_strategy",
        }.intersection(value.keys()):
            return {
                "core_setting_adjustments": str(value.get("core_setting_adjustments") or ""),
                "structure_and_rhythm": str(value.get("structure_and_rhythm") or ""),
                "visualization_strategy": str(value.get("visualization_strategy") or ""),
                "character_emotion_strategy": str(value.get("character_emotion_strategy") or ""),
            }
        return {
            "core_setting_adjustments": json.dumps(value, ensure_ascii=False, indent=2),
            "structure_and_rhythm": "",
            "visualization_strategy": "",
            "character_emotion_strategy": "",
        }
    if isinstance(value, list):
        items = [item for item in value if isinstance(item, dict)]
        texts = [str(item.get("content") or item.get("summary") or "") for item in items]
        while len(texts) < 4:
            texts.append("")
        return {
            "core_setting_adjustments": texts[0],
            "structure_and_rhythm": texts[1],
            "visualization_strategy": texts[2],
            "character_emotion_strategy": texts[3],
        }
    text = str(value or "").strip()
    return {
        "core_setting_adjustments": text,
        "structure_and_rhythm": "",
        "visualization_strategy": "",
        "character_emotion_strategy": "",
    }


def _normalize_validation_report(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    return {"summary": text} if text else {}


def _normalize_storyline_decision(value: Any) -> str:
    decision = str(value or "keep").strip().lower()
    if decision not in {"keep", "simplify", "delete"}:
        return "keep"
    return decision


def _normalize_episode_distribution(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(
                {
                    "episode_range": str(item.get("episode_range") or item.get("range") or ""),
                    "focus": str(item.get("focus") or item.get("title") or item.get("content") or ""),
                }
            )
        else:
            text = str(item or "").strip()
            if text:
                normalized.append({"episode_range": "", "focus": text})
    return normalized


def _normalize_int_list(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    result: list[int] = []
    for item in items:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        result.append(number)
    return result


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _first_present_value(payload: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        if alias in payload and not _is_blank(payload.get(alias)):
            return payload.get(alias)
    return None


def _find_value_by_aliases(data: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        if alias in data and data.get(alias) not in (None, "", [], {}):
            return data.get(alias)
    return None


def _wire_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return value


def _safe_response_text(response: requests.Response) -> str:
    try:
        return response.text
    except Exception:
        return ""


def _write_debug_artifact(
    *,
    stage: str,
    workflow_spec: FrameworkPlannerWorkflowSpec,
    request_variables: dict[str, Any],
    payload: dict[str, Any],
    response_raw: Any,
    parse_error: str,
) -> dict[str, Any]:
    debug_dir = get_runtime_data_dir(Path(__file__).resolve().parents[2]) / "debug_dumps" / "framework_planner"
    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = debug_dir / f"framework_planner_stage_{stage}_{timestamp}_{uuid.uuid4().hex[:8]}.json"
    artifact = {
        "stage": stage,
        "workflow_json_path": str(workflow_spec.path),
        "payload_keys": sorted(payload.keys()),
        "request_variables": request_variables,
        "response_raw": response_raw,
        "parse_error": parse_error,
    }
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "debug_artifact_path": str(path),
        "workflow_json_path": str(workflow_spec.path),
        "payload_keys": sorted(payload.keys()),
        "parse_error": parse_error,
    }


def _build_mock_stage_output(stage: str, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if stage == "01":
        source_title = str(payload.get("source_title") or "未命名原作")
        target_format = str(payload.get("target_format") or "短剧")
        source_text = str(payload.get("source_text") or "").strip()
        source_brief = {
            "source_title": source_title,
            "target_format": target_format,
            "season_plan": {
                "season_count": int(payload.get("season_count") or 1),
                "episodes_per_season": int(payload.get("episodes_per_season") or 60),
                "minutes_per_episode": int(payload.get("minutes_per_episode") or 2),
            },
            "core_premise": source_text[:180] or "当前为 mock 提取结果，请在接入真实原文后替换。",
            "main_conflict": "主角被旧秩序压制，被迫进入更高风险的规则体系中完成自我翻盘。",
            "tone_keywords": ["强钩子", "强反转", "强情绪"],
            "adaptation_direction": str(payload.get("adaptation_direction") or ""),
            "user_constraints": str(payload.get("user_constraints") or ""),
            "user_requirements": str(payload.get("user_requirements") or ""),
        }
        return {"source_brief": source_brief}, json.dumps(source_brief, ensure_ascii=False, indent=2)

    if stage == "02":
        worldview_plan = {
            "world_type": "近未来高压都市短剧世界",
            "core_rules": [
                "资源被平台、资本与隐秘组织共同垄断。",
                "主角每跨过一个等级门槛，都会暴露更大的代价与真相。",
                "公开羞辱、限时任务、身份揭露与资源争夺是主要戏剧化手段。",
            ],
            "power_structure": [
                "平台方负责制定准入规则。",
                "地方财团负责操盘资源流向。",
                "地下信息网络负责掌握灰色真相。",
            ],
            "main_conflict": "主角必须在看似公开公平、实则被操控的规则体系中撕开上升通道。",
            "visual_style": "高压、节奏快、场面外化、冲突可拍摄。",
        }
        return {"worldview_plan": worldview_plan}, json.dumps(worldview_plan, ensure_ascii=False, indent=2)

    if stage == "03":
        character_plan = {
            "protagonist": {
                "name": "林渡",
                "identity": "被排挤的底层执行者",
                "goal": "查清旧案真相并反向夺回资源入口",
                "flaw": "过度逞强，不愿信任他人",
                "growth_arc": "从单点反击走向主动承担与联手破局",
            },
            "antagonist": {
                "name": "周砺",
                "identity": "掌握规则解释权的既得利益代表",
                "goal": "维持既得秩序并清除不稳定因素",
                "methods": ["身份压制", "信息差操控", "公开羞辱", "资源封锁"],
            },
            "b_story_role": {
                "name": "沈念",
                "identity": "与主角相互试探的关键同伴",
                "function": "承担情感与价值观回流，让主角完成内在转向",
            },
            "supporting_roles": [
                {"name": "顾行舟", "function": "提供关键线索并制造阶段性误解"},
                {"name": "梁澈", "function": "提供资源通道，同时制造背叛风险"},
            ],
            "relationship_map": [
                "主角 vs 反派：规则体系的正面对抗",
                "主角 vs B 故事人物：从互相利用到建立信任",
                "主角 vs 配角群：阶段性联盟、背叛与回收",
            ],
        }
        return {"character_plan": character_plan}, json.dumps(character_plan, ensure_ascii=False, indent=2)

    if stage == "04":
        total = _episodes_per_season_from_basic_config(payload.get("basic_config"))
        ranges = _split_episode_ranges(total)
        linked_storylines = [
            ["主角成长线", "反派压迫线"],
            ["主角成长线", "B故事情感线"],
            ["秘密揭露线"],
            ["主角成长线", "反派压迫线"],
            ["主角成长线", "B故事情感线"],
            ["主角成长线", "秘密揭露线"],
            ["B故事情感线"],
            ["主角成长线", "反派压迫线"],
            ["秘密揭露线", "主角成长线"],
            ["反派压迫线", "B故事情感线"],
            ["反派压迫线", "秘密揭露线"],
            ["主角成长线", "B故事情感线"],
            ["主角成长线", "秘密揭露线"],
            ["主角成长线", "反派压迫线", "秘密揭露线"],
            ["主角成长线", "B故事情感线"],
        ]
        timeline: list[dict[str, Any]] = []
        for index, beat_name in enumerate(FIFTEEN_BEAT_NAMES, start=1):
            timeline.append(
                {
                    "beat_no": index,
                    "beat_name": beat_name,
                    "act": _act_for_beat(index),
                    "episode_range": ranges[index - 1],
                    "checkpoint_title": f"{beat_name}卡点",
                    "narrative_function": f"承接{beat_name}对应的核心叙事功能，并为下一个节拍蓄压。",
                    "plot_content": f"第 {index} 节拍围绕 {beat_name} 展开，推动主角与规则体系的冲突继续升级。",
                    "character_change": "主角逐渐从被动应对转向主动破局。",
                    "conflict_upgrade": "旧秩序的压制手段升级，迫使人物关系和资源分配重新洗牌。",
                    "hook_or_reversal": f"{beat_name}结尾抛出下一阶段必须立即处理的钩子或反转。",
                    "linked_storylines": linked_storylines[index - 1],
                }
            )
        explanation = {
            "overview": "该 checkpoint_explanation 仅用于解释同一条十五节拍时间轴，不再额外复制一套 checkpointPlan 结构。",
            "beat_notes": [
                {
                    "beat_no": item["beat_no"],
                    "explanation": f"{item['beat_name']}主要承担 {item['narrative_function']}",
                }
                for item in timeline
            ],
        }
        return {
            "beat_checkpoint_timeline": timeline,
            "checkpoint_explanation": explanation,
        }, json.dumps(
            {"beat_checkpoint_timeline": timeline, "checkpoint_explanation": explanation},
            ensure_ascii=False,
            indent=2,
        )

    if stage == "05":
        storylines = [
            {
                "id": "protagonist_growth",
                "title": "主角成长线",
                "summary": "主角从被规则压制到主动掌控反击节奏，是全季主引擎。",
                "detailed_storyline": "前半段承担处境、缺陷与被迫入局，后半段承担崩盘、转向与反攻闭环。",
                "linked_beats": [1, 2, 4, 6, 9, 11, 12, 13, 14, 15],
                "episode_distribution": [
                    {"episode_range": "前 10 集", "focus": "低位处境与被迫入局"},
                    {"episode_range": "中段", "focus": "阶段胜利后的认知反转"},
                    {"episode_range": "后段", "focus": "崩盘、转向与最终反攻"},
                ],
                "edit_notes": "重点保留，后续剧本必须持续体现成长递进。",
                "decision": "keep",
            },
            {
                "id": "antagonist_pressure",
                "title": "反派压迫线",
                "summary": "反派以规则解释权、资源封锁和公开羞辱推动冲突升级。",
                "detailed_storyline": "用于持续制造门槛、围剿和阶段性失败，是主线爽点与危机感的重要来源。",
                "linked_beats": [1, 3, 4, 8, 10, 11, 14],
                "episode_distribution": [
                    {"episode_range": "前段", "focus": "压迫与规则展示"},
                    {"episode_range": "中段", "focus": "围剿升级与局部压制"},
                    {"episode_range": "后段", "focus": "反制与秩序崩塌"},
                ],
                "edit_notes": "必须与主角成长线同步升级。",
                "decision": "keep",
            },
            {
                "id": "b_story_relationship",
                "title": "B故事情感线",
                "summary": "承担信任修复与主题回流，但不应压过主线节奏。",
                "detailed_storyline": "建议保留关键节点，弱化独立展开，确保它服务于主角在最低谷后的转向。",
                "linked_beats": [3, 7, 10, 12, 15],
                "episode_distribution": [
                    {"episode_range": "前中段", "focus": "建立误解与合作试探"},
                    {"episode_range": "后中段", "focus": "价值观碰撞与支撑"},
                    {"episode_range": "结尾", "focus": "情感闭环"},
                ],
                "edit_notes": "适合精简保留。",
                "decision": "simplify",
            },
            {
                "id": "secret_reveal",
                "title": "秘密揭露线",
                "summary": "围绕旧案、身份与资源真相埋伏笔，并在中点与第三幕前集中回收。",
                "detailed_storyline": "该线主要服务于悬念和反转，是主线升级的重要燃料。",
                "linked_beats": [2, 3, 9, 11, 13, 14],
                "episode_distribution": [
                    {"episode_range": "前段", "focus": "埋伏笔与异常点"},
                    {"episode_range": "中点", "focus": "揭露第一层真相"},
                    {"episode_range": "后段", "focus": "真相代价与最终回收"},
                ],
                "edit_notes": "保留，以支撑反转密度。",
                "decision": "keep",
            },
        ]
        return {"character_storylines": storylines}, json.dumps(storylines, ensure_ascii=False, indent=2)

    if stage == "06":
        guide = {
            "core_setting_adjustments": "保留资源垄断与规则对抗的大骨架，改动时不得削弱主角与规则体系的硬碰撞。",
            "structure_and_rhythm": "按强开局、高频小高潮、中点反转、低谷转向、终局反攻的节奏执行。",
            "visualization_strategy": "把心理冲突尽量外化成公开对峙、限时任务、证据展示、排名变化与身份揭露。",
            "character_emotion_strategy": "主角情绪从屈辱、不甘、逞强，推进到清醒、承担与主动反攻。",
        }
        return {"adaptation_guide": guide}, json.dumps(guide, ensure_ascii=False, indent=2)

    if stage == "07":
        storylines = _normalize_character_storylines(payload.get("character_storylines"))
        decisions = _normalize_storyline_decisions(payload.get("storyline_decisions"), storylines)
        selected_storylines = [
            {
                **item,
                "decision": decisions.get(item["id"], item.get("decision", "keep")),
            }
            for item in storylines
            if decisions.get(item["id"], item.get("decision", "keep")) != "delete"
        ]
        package = {
            "basic_config": payload.get("basic_config") or {},
            "source_brief": payload.get("source_brief") or {},
            "worldview_plan": payload.get("worldview_plan") or {},
            "character_plan": payload.get("character_plan") or {},
            "beat_checkpoint_timeline": payload.get("beat_checkpoint_timeline") or [],
            "checkpoint_explanation": payload.get("checkpoint_explanation") or {},
            "character_storylines": selected_storylines,
            "storyline_decisions": payload.get("storyline_decisions") or [],
            "adaptation_guide": payload.get("adaptation_guide") or {},
            "user_edit_history": payload.get("user_edit_history") or [],
            "handoff_notes": "该策划包已按框架工作台输出，可直接交给正式剧本生成链路。",
            "storage_key": FRAMEWORK_PLANNER_STORAGE_KEY,
        }
        validation = {
            "passed": True,
            "warnings": [],
            "checks": {
                "beat_count": len(package["beat_checkpoint_timeline"]),
                "storyline_count": len(selected_storylines),
                "has_adaptation_guide": bool(package["adaptation_guide"]),
            },
            "summary": "框架策划包结构完整，可交付后续正式剧本生成链路。",
        }
        return {
            "framework_plan_package": package,
            "validation_report": validation,
        }, json.dumps(
            {"framework_plan_package": package, "validation_report": validation},
            ensure_ascii=False,
            indent=2,
        )

    raise FrameworkPlannerStageError("未知阶段", stage=stage, status_code=404)


def _normalize_storyline_decisions(
    value: Any,
    storylines: list[dict[str, Any]],
) -> dict[str, str]:
    if isinstance(value, list):
        decisions: dict[str, str] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            identifier = str(item.get("storyline_id") or item.get("id") or "").strip()
            if not identifier:
                continue
            decisions[identifier] = _normalize_storyline_decision(item.get("decision"))
        return decisions
    decisions = {
        item["id"]: _normalize_storyline_decision(item.get("decision"))
        for item in storylines
    }
    return decisions


def _episodes_per_season_from_basic_config(value: Any) -> int:
    config = value if isinstance(value, dict) else {}
    try:
        episodes = int(
            config.get("episodes_per_season")
            or config.get("episodesPerSeason")
            or 60
        )
    except (TypeError, ValueError, AttributeError):
        episodes = 60
    return max(15, episodes)


def _split_episode_ranges(total_episodes: int) -> list[str]:
    weights = [3, 4, 4, 4, 4, 5, 5, 7, 5, 5, 4, 4, 3, 2, 1]
    weight_sum = sum(weights)
    start = 1
    ranges: list[str] = []
    for index, weight in enumerate(weights, start=1):
        remaining = 15 - index
        if index == 15:
            length = total_episodes - start + 1
        else:
            length = max(1, round(total_episodes * weight / weight_sum))
            if start + length + remaining - 1 > total_episodes:
                length = max(1, total_episodes - start - remaining + 1)
        end = min(total_episodes, start + length - 1)
        if start == end:
            ranges.append(f"第{start}集")
        else:
            ranges.append(f"第{start}-{end}集")
        start = end + 1
    return ranges


def _act_for_beat(beat_no: int) -> str:
    if beat_no <= 6:
        return "第一幕"
    if beat_no <= 12:
        return "第二幕"
    return "第三幕"


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def _env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_with_name(*names: str) -> tuple[str, str]:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return name, str(value).strip()
    return "", ""


def _normalize_fastgpt_url(raw_url: str) -> str:
    url = str(raw_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("FastGPT 接口地址不能为空")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"FastGPT 接口地址必须以 http:// 或 https:// 开头：{url}")
    if url.endswith("/api/v1"):
        return f"{url}/chat/completions"
    if url.endswith("/api/v1/chat/completions"):
        return url
    if url.endswith("/api/v1/chat/completions/"):
        return url.rstrip("/")
    if url.endswith("/api/v1"):
        return f"{url}/chat/completions"
    return url


def _truncate_text(value: str, *, limit: int = 800) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."
