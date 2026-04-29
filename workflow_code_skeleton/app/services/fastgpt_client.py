from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

import requests

from ..config import settings
from ..utils.logger import get_logger
from ..workflow_ids import (
    APPEARANCE_MAPPING_VAR,
    APPEARANCE_NATURAL_LANGUAGE_VAR,
    CHARACTER_NATURAL_LANGUAGE_VAR,
    CORE_SCENE_FINAL_VAR,
    SCENE_NATURAL_LANGUAGE_VAR,
    SCENE_VAR,
)
from .fastgpt_contracts import (
    ALL_DIALOGUES,
    ALL_HOOKS,
    ALL_SCRIPT,
    APPEARANCE_MAPPING,
    BATCH_DIALOGUES,
    BATCH_HOOKS,
    CHARACTERS,
    CHARACTER_ALIAS_NAMING_RULES,
    CHARACTER_APPEARANCE_REQUIREMENTS,
    DIALOGUE_MEMORY,
    HOOK_MEMORY,
    LAST_SUMMARY,
    LEGACY_INPUT_ALIASES,
    MAX_RETRIES,
    NORMALIZED_EPISODE_PLAN,
    OUTFIT_SWITCH_RULES,
    STAGE_APPEARANCE_ALIAS_GENERATION,
    STAGE_APPEARANCE_ALIAS_REVIEW,
    STAGE_APPEARANCE_ALIAS_REWRITE,
    STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
    STAGE_APPEARANCE_ALIAS_WRITING,
    STAGE_APPEARANCE_PRE_STRATEGY,
    STAGE_DIALOGUES,
    STAGE_DIALOGUE_MEMORY,
    STAGE_DIALOGUE_REVIEW,
    STAGE_DIALOGUE_REVISE,
    STAGE_DIALOGUE_WRITE,
    STAGE_DIALOGUES_REVIEW,
    STAGE_DIALOGUES_REWRITE,
    STAGE_DIALOGUES_WRITING,
    STAGE_EPISODE_PLAN_NORMALIZE,
    STAGE_FRAMEWORK,
    STAGE_FRAMEWORK_NATURALIZE,
    STAGE_CHARACTERS,
    STAGE_HOOK_MEMORY,
    STAGE_HOOK_REVIEW,
    STAGE_HOOK_REVISE,
    STAGE_HOOK_WRITE,
    STAGE_HOOKS_REVIEW,
    SCENES,
    STAGE_SCENES,
    STAGE_SCRIPT,
    STAGE_SCRIPT_REVIEW,
    STAGE_SCRIPT_REVISE,
    STAGE_SCRIPT_REWRITE,
    STAGE_SCRIPT_WRITE,
    STAGE_SCRIPT_WRITING,
    STAGE_SCRIPT_MEMORY,
    SCRIPT_MEMORY,
    STAGE_WORLDVIEW,
    STAGE_WORLDVIEW_NATURALIZE,
    USER_CONTENT_BASELINE,
    FastGPTStageContract,
    contract_for,
    coerce_fastgpt_value,
    to_jsonable_value,
)
from .json_utils import parse_json, strip_code_fence
from .stage_output_repair import (
    StageRepairOutcome,
    is_repairable_stage_output,
    normalize_appearance_mapping_candidate,
    repair_stage_output_candidate,
    validate_scenes_output,
)

logger = get_logger("fastgpt_client")


TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
STAGE_AUXILIARY_OUTPUT_KEYS: dict[str, dict[str, tuple[str, ...]]] = {
    "characters": {
        CHARACTER_NATURAL_LANGUAGE_VAR: (
            CHARACTER_NATURAL_LANGUAGE_VAR,
            "character_natural_language",
            "character_summary",
        ),
    },
    "scenes": {
        SCENE_NATURAL_LANGUAGE_VAR: (
            SCENE_NATURAL_LANGUAGE_VAR,
            "scene_natural_language",
            "core_scene_summary",
        ),
    },
    "appearance_alias_generation": {
        APPEARANCE_NATURAL_LANGUAGE_VAR: (APPEARANCE_NATURAL_LANGUAGE_VAR,),
    },
}
STAGE_API_KEY_ENV_ALIASES: dict[str, tuple[str, ...]] = {
    STAGE_FRAMEWORK_NATURALIZE: ("FASTGPT_UNSTRUCTURED_API_KEY",),
    STAGE_WORLDVIEW_NATURALIZE: ("FASTGPT_UNSTRUCTURED_API_KEY",),
    STAGE_APPEARANCE_ALIAS_WRITING: (
        "FASTGPT_APPEARANCE_ALIAS_WRITING_API_KEY",
    ),
    STAGE_APPEARANCE_ALIAS_REVIEW: (
        "FASTGPT_APPEARANCE_ALIAS_REVIEW_API_KEY",
    ),
    STAGE_APPEARANCE_ALIAS_REWRITE: (
        "FASTGPT_APPEARANCE_ALIAS_REWRITE_API_KEY",
    ),
    STAGE_APPEARANCE_ALIAS_UNSTRUCTURED: (
        "FASTGPT_APPEARANCE_ALIAS_UNSTRUCTURED_API_KEY",
    ),
    STAGE_SCRIPT_WRITING: (
        "FASTGPT_SCRIPT_WRITING_API_KEY",
        "FASTGPT_SCRIPT_WRITE_API_KEY",
        "FASTGPT_SCRIPT_API_KEY",
    ),
    STAGE_SCRIPT_WRITE: (
        "FASTGPT_SCRIPT_WRITING_API_KEY",
        "FASTGPT_SCRIPT_WRITE_API_KEY",
        "FASTGPT_SCRIPT_API_KEY",
    ),
    STAGE_SCRIPT_REVIEW: ("FASTGPT_SCRIPT_REVIEW_API_KEY", "FASTGPT_SCRIPT_API_KEY"),
    STAGE_SCRIPT_REWRITE: (
        "FASTGPT_SCRIPT_REWRITE_API_KEY",
        "FASTGPT_SCRIPT_REVISE_API_KEY",
        "FASTGPT_SCRIPT_API_KEY",
    ),
    STAGE_SCRIPT_REVISE: (
        "FASTGPT_SCRIPT_REWRITE_API_KEY",
        "FASTGPT_SCRIPT_REVISE_API_KEY",
        "FASTGPT_SCRIPT_API_KEY",
    ),
    STAGE_SCRIPT_MEMORY: ("FASTGPT_SCRIPT_MEMORY_API_KEY", "FASTGPT_MEMORY_API_KEY"),
    STAGE_HOOK_WRITE: ("FASTGPT_HOOK_WRITE_API_KEY", "FASTGPT_HOOKS_WRITING_API_KEY", "FASTGPT_HOOKS_API_KEY"),
    STAGE_HOOK_REVIEW: ("FASTGPT_HOOK_REVIEW_API_KEY", "FASTGPT_HOOKS_REVIEW_API_KEY", "FASTGPT_HOOKS_API_KEY"),
    STAGE_HOOK_REVISE: ("FASTGPT_HOOK_REVISE_API_KEY", "FASTGPT_HOOKS_REWRITE_API_KEY", "FASTGPT_HOOKS_API_KEY"),
    STAGE_HOOK_MEMORY: ("FASTGPT_HOOK_MEMORY_API_KEY", "FASTGPT_HOOKS_MEMORY_API_KEY", "FASTGPT_HOOKS_API_KEY"),
    STAGE_DIALOGUE_WRITE: ("FASTGPT_DIALOGUE_WRITE_API_KEY", "FASTGPT_DIALOGUES_WRITING_API_KEY", "FASTGPT_DIALOGUE_API_KEY"),
    STAGE_DIALOGUE_REVIEW: ("FASTGPT_DIALOGUE_REVIEW_API_KEY", "FASTGPT_DIALOGUES_REVIEW_API_KEY", "FASTGPT_DIALOGUE_API_KEY"),
    STAGE_DIALOGUE_REVISE: ("FASTGPT_DIALOGUE_REVISE_API_KEY", "FASTGPT_DIALOGUES_REWRITE_API_KEY", "FASTGPT_DIALOGUE_API_KEY"),
    STAGE_DIALOGUE_MEMORY: ("FASTGPT_DIALOGUE_MEMORY_API_KEY", "FASTGPT_DIALOGUES_MEMORY_API_KEY", "FASTGPT_MEMORY_API_KEY", "FASTGPT_DIALOGUE_API_KEY"),
}
TEXT_FIRST_MULTI_FIELD_STAGES = {
    STAGE_FRAMEWORK,
    STAGE_APPEARANCE_PRE_STRATEGY,
    STAGE_APPEARANCE_ALIAS_REVIEW,
    STAGE_HOOKS_REVIEW,
    STAGE_HOOK_REVIEW,
    STAGE_DIALOGUES_REVIEW,
    STAGE_DIALOGUE_REVIEW,
    STAGE_SCRIPT_REVIEW,
}
PARTIAL_MATCH_MISSING_ERROR_STAGES = {
    STAGE_FRAMEWORK,
    STAGE_APPEARANCE_PRE_STRATEGY,
    STAGE_APPEARANCE_ALIAS_REVIEW,
    STAGE_HOOKS_REVIEW,
    STAGE_HOOK_REVIEW,
    STAGE_DIALOGUES_REVIEW,
    STAGE_DIALOGUE_REVIEW,
    STAGE_SCRIPT_REVIEW,
}
STRICT_JSON_STRING_STAGES = {
    STAGE_WORLDVIEW,
    STAGE_CHARACTERS,
    STAGE_SCENES,
}
APPEARANCE_MAPPING_OUTPUT_STAGES = {
    STAGE_APPEARANCE_ALIAS_GENERATION,
    STAGE_APPEARANCE_ALIAS_WRITING,
    STAGE_APPEARANCE_ALIAS_REWRITE,
}
APPEARANCE_DETAIL_STAGES = {
    STAGE_APPEARANCE_ALIAS_GENERATION,
    STAGE_APPEARANCE_ALIAS_WRITING,
    STAGE_APPEARANCE_ALIAS_REVIEW,
    STAGE_APPEARANCE_ALIAS_REWRITE,
    STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
}
PASS_REVIEW_OUTPUT_STAGES = {
    STAGE_APPEARANCE_ALIAS_REVIEW,
    STAGE_HOOKS_REVIEW,
    STAGE_HOOK_REVIEW,
    STAGE_DIALOGUES_REVIEW,
    STAGE_DIALOGUE_REVIEW,
    STAGE_SCRIPT_REVIEW,
}


class FastGPTTransientError(RuntimeError):
    """A retryable FastGPT HTTP/upstream error after local retries are exhausted."""

    def __init__(
        self,
        message: str,
        *,
        stage_name: str,
        status_code: int | None = None,
        url: str = "",
        response_text: str = "",
    ) -> None:
        super().__init__(message)
        self.stage_name = stage_name
        self.status_code = status_code
        self.url = url
        self.response_text = response_text


class FastGPTStageFormatError(ValueError):
    """HTTP 成功但阶段输出仍不可消费时，交给编排层统一格式重试。"""

    def __init__(
        self,
        *,
        stage_name: str,
        expected_fields: Iterable[str],
        failure_reason: str,
        candidate_sources: Iterable[str] | None = None,
        matched_fields: Iterable[str] | None = None,
        missing_fields: Iterable[str] | None = None,
        probable_truncated_json: bool = False,
        answer_text_preview: str = "",
        response_preview: str = "",
        raw_output_source: str = "none",
    ) -> None:
        self.stage_name = stage_name
        self.expected_fields = tuple(str(field) for field in expected_fields)
        self.failure_reason = str(failure_reason or "").strip()
        self.candidate_sources = tuple(
            str(item) for item in list(candidate_sources or []) if str(item or "").strip()
        )
        self.matched_fields = tuple(
            str(item) for item in list(matched_fields or []) if str(item or "").strip()
        )
        self.missing_fields = tuple(
            str(item) for item in list(missing_fields or []) if str(item or "").strip()
        )
        self.probable_truncated_json = bool(probable_truncated_json)
        self.answer_text_preview = str(answer_text_preview or "")
        self.response_preview = str(response_preview or "")
        self.raw_output_source = str(raw_output_source or "none")
        preview = _truncate_log_text(self.response_preview, limit=500)
        message = (
            f"FastGPT 阶段 {stage_name} 未识别到可消费的契约输出，"
            f"期望字段：{', '.join(self.expected_fields)}；"
            f"{self.failure_reason or '没有发现任何可映射到阶段契约的候选输出'}；"
            f"实际返回内容：{preview}"
        )
        super().__init__(message)


class FastGPTPayloadTooLargeError(RuntimeError):
    """阻止把明显超大的请求体直接发给 FastGPT。"""

    def __init__(
        self,
        *,
        stage_name: str,
        body_chars: int,
        hard_limit: int,
        largest_variables: list[dict[str, Any]],
    ) -> None:
        self.stage_name = stage_name
        self.body_chars = int(body_chars)
        self.hard_limit = int(hard_limit)
        self.largest_variables = list(largest_variables)
        largest_desc = "、".join(
            f"{item.get('name')}={item.get('chars')}"
            for item in self.largest_variables[:3]
            if item.get("name")
        ) or "未知"
        super().__init__(
            f"FastGPT 阶段 {stage_name} 请求体过大：{body_chars} chars，"
            f"超过硬限制 {hard_limit} chars；最大变量：{largest_desc}。"
            "当前阶段已优先使用 compact context，如仍超限，请进一步缩小输入。"
        )


@dataclass(frozen=True, slots=True)
class FastGPTEndpoint:
    url: str
    url_source: str
    api_key: str
    api_key_source: str
    chat_id: str
    timeout: int


@dataclass(frozen=True, slots=True)
class StageOutputMatch:
    """记录单个候选来源是如何映射到阶段契约字段的。"""

    payload: dict[str, Any]
    matched_keys: dict[str, str]
    canonical_hits: int
    alias_hits: int
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidatedStageOutput:
    """记录通过契约校验后的候选输出，供多来源候选之间做稳定排序。"""

    source: str
    payload: dict[str, Any]
    validated_payload: dict[str, Any]
    matched_keys: dict[str, str]
    canonical_hits: int
    alias_hits: int


@dataclass
class FrameworkScoredCandidate:
    source: str
    candidate: dict[str, Any]
    preview: str
    score: tuple[int, int, int, int, int, int, int]


@dataclass
class FrameworkSelectionResult:
    selected: ValidatedStageOutput | None
    candidate_summaries: list[dict[str, Any]]
    selected_source: str | None = None
    selected_preview: str | None = None


@dataclass
class AppearanceSelectionResult:
    selected: ValidatedStageOutput | None
    candidate_summaries: list[dict[str, Any]]
    selected_source: str | None = None
    selected_preview: str | None = None
    empty_alias_seen: bool = False


class FastGPTClient:
    """OpenAI-compatible FastGPT workflow client.

    FastGPT applications expose workflow calls through /api/v1/chat/completions.
    Each stage can use its own API key, or all stages can share FASTGPT_API_KEY.
    """

    def __init__(self) -> None:
        self._last_stage_debug_info: dict[str, dict[str, Any]] = {}

    def get_last_stage_debug_info(self, stage_name: str) -> dict[str, Any]:
        cache = getattr(self, "_last_stage_debug_info", None)
        if not isinstance(cache, dict):
            return {}
        return dict(cache.get(stage_name, {}))

    def _remember_stage_debug_info(self, stage_name: str, **info: Any) -> None:
        cache = getattr(self, "_last_stage_debug_info", None)
        if not isinstance(cache, dict):
            cache = {}
            self._last_stage_debug_info = cache
        existing = cache.get(stage_name, {})
        if not isinstance(existing, dict):
            existing = {}
        merged = dict(existing)
        merged.update(dict(info))
        cache[stage_name] = merged

    def run_stage(self, stage_name: str, variables: dict[str, Any]) -> dict[str, Any]:
        contract = contract_for(stage_name)
        contract.build_input_payload(variables)
        payload_variables = self._build_wire_variables(stage_name, variables, contract)
        self._remember_stage_debug_info(stage_name, status="started", matched_aliases=[], raw_output_source="")
        endpoint = self._endpoint_for(stage_name)
        body = self._build_request_body(contract, payload_variables, endpoint.chat_id)
        headers = {
            "Authorization": f"Bearer {endpoint.api_key}",
            "Content-Type": "application/json",
        }
        response = self._post_with_retries(endpoint, headers, body, stage_name)
        try:
            data = response.json()
        except ValueError as exc:
            response_preview = _truncate_log_text(_safe_response_text(response), limit=1000)
            self._remember_stage_debug_info(
                stage_name,
                status="invalid_json_response",
                raw_output_source="response.json",
                matched_aliases=[],
                matched_fields=[],
                missing_fields=list(contract.output_names),
                candidate_sources=[],
                probable_truncated_json=False,
                answer_text_preview="",
                response_preview=response_preview,
                output_keys=[],
                raw_response={"response_text": response_preview},
                conversation_log_available=False,
                last_failure_reason="response.json invalid",
            )
            raise FastGPTTransientError(
                f"FastGPT 阶段 {stage_name} 返回了无法解析的 JSON 响应。"
                "当前项目进度已保存，可稍后点击继续生成重试。",
                stage_name=stage_name,
                url=endpoint.url,
                response_text=response_preview,
            ) from exc

        raw_output = self._extract_output_payload(
            data,
            contract,
            variables,
            allow_fallback=False,
        )
        try:
            validated_output = contract.validate_output_payload(raw_output)
        except ValueError as exc:
            debug_info = self.get_last_stage_debug_info(stage_name)
            failure = FastGPTStageFormatError(
                stage_name=stage_name,
                expected_fields=contract.output_names,
                failure_reason=str(exc),
                candidate_sources=debug_info.get("candidate_sources", []),
                matched_fields=debug_info.get("matched_fields", []),
                missing_fields=debug_info.get("missing_fields", list(contract.output_names)),
                probable_truncated_json=bool(debug_info.get("probable_truncated_json")),
                answer_text_preview=str(debug_info.get("answer_text_preview") or ""),
                response_preview=str(debug_info.get("response_preview") or ""),
                raw_output_source=str(debug_info.get("raw_output_source") or "none"),
            )
            self._remember_stage_debug_info(
                stage_name,
                status="contract_validation_failed",
                last_failure_reason=str(exc),
            )
            raise failure from exc

        auxiliary_output = _extract_stage_auxiliary_outputs(data, stage_name)
        if auxiliary_output:
            logger.info(
                "FastGPT 阶段 %s 捕获到辅助输出：%s",
                stage_name,
                auxiliary_output.keys(),
            )
        debug_info = self.get_last_stage_debug_info(stage_name)
        debug_info.update(
            {
                "status": "validated",
                "answer_text_preview": _truncate_log_text(
                    _first_text_candidate(data),
                    limit=300,
                ),
                "response_preview": _response_log_summary(data, answer_limit=1000),
                "output_keys": _candidate_output_keys(data),
                "raw_response": data,
                "conversation_log_available": False,
                "last_failure_reason": "",
            }
        )
        self._remember_stage_debug_info(stage_name, **debug_info)
        return {
            **auxiliary_output,
            **validated_output,
        }

    def _post_with_retries(
        self,
        endpoint: FastGPTEndpoint,
        headers: dict[str, str],
        body: dict[str, Any],
        stage_name: str,
    ) -> requests.Response:
        attempts = max(1, int(getattr(settings, "fastgpt_http_retries", 2)) + 1)
        delay = max(0.0, float(getattr(settings, "fastgpt_http_retry_delay", 1.5)))
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            timeout_seconds = max(
                1,
                int(
                    getattr(endpoint, "timeout", 0)
                    or getattr(settings, "fastgpt_timeout", 300)
                    or 300
                ),
            )
            try:
                response = requests.post(
                    endpoint.url,
                    headers=headers,
                    json=body,
                    timeout=timeout_seconds,
                )
            except requests.Timeout as exc:
                last_error = exc
                logger.warning(
                    "FastGPT 阶段 %s 请求超时，URL：%s，timeout=%ss，attempt=%s/%s",
                    stage_name,
                    endpoint.url,
                    timeout_seconds,
                    attempt,
                    attempts,
                )
                if attempt >= attempts:
                    raise FastGPTTransientError(
                        f"FastGPT 阶段 {stage_name} 请求超时（{timeout_seconds}s）。"
                        "当前项目进度已保存，可稍后点击继续生成重试。",
                        stage_name=stage_name,
                        url=endpoint.url,
                    ) from exc
                _sleep_before_retry(delay, attempt)
                continue
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "FastGPT 阶段 %s 网络请求失败，URL：%s，错误：%s",
                    stage_name,
                    endpoint.url,
                    exc,
                )
                if attempt >= attempts:
                    raise FastGPTTransientError(
                        f"FastGPT 阶段 {stage_name} 网络请求失败：{exc}。当前项目进度已保存，将自动继续重试。",
                        stage_name=stage_name,
                        url=endpoint.url,
                    ) from exc
                _sleep_before_retry(delay, attempt)
                continue

            if response.status_code >= 400:
                logger.warning(
                    "FastGPT 阶段 %s 请求失败，URL：%s，HTTP %s %s，response.text：%s",
                    stage_name,
                    endpoint.url,
                    response.status_code,
                    response.reason or "",
                    _safe_response_text(response),
                )

            if response.status_code in TRANSIENT_STATUS_CODES and attempt < attempts:
                logger.warning(
                    "FastGPT 阶段 %s 返回 HTTP %s，准备第 %s/%s 次重试。",
                    stage_name,
                    response.status_code,
                    attempt + 1,
                    attempts,
                )
                _sleep_before_retry(delay, attempt)
                continue

            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                message = _format_http_error(stage_name, endpoint.url, response)
                if response.status_code in TRANSIENT_STATUS_CODES:
                    raise FastGPTTransientError(
                        message,
                        stage_name=stage_name,
                        status_code=response.status_code,
                        url=endpoint.url,
                        response_text=_safe_response_text(response),
                    ) from exc
                raise RuntimeError(message) from exc
            return response

        raise RuntimeError(f"FastGPT 阶段 {stage_name} 请求失败：{last_error}")

    def _build_wire_variables(
        self,
        stage_name: str,
        variables: dict[str, Any],
        contract: FastGPTStageContract,
    ) -> dict[str, Any]:
        if settings.fastgpt_variable_mode in {"canonical", "english"}:
            return contract.build_input_payload(variables)

        if settings.fastgpt_variable_mode not in {"legacy", "legacy_ids"}:
            raise ValueError(
                "FASTGPT_VARIABLE_MODE 只能是 legacy 或 canonical，"
                f"当前为：{settings.fastgpt_variable_mode}"
            )

        aliases = LEGACY_INPUT_ALIASES.get(stage_name)
        if not aliases:
            return contract.build_input_payload(variables)

        wire: dict[str, Any] = {}
        for canonical_name, wire_name in aliases.items():
            wire_names = _as_wire_names(wire_name)
            if canonical_name == ALL_HOOKS and BATCH_HOOKS in variables:
                _set_wire_values(wire, wire_names, variables[BATCH_HOOKS])
                continue
            if canonical_name == ALL_DIALOGUES and BATCH_DIALOGUES in variables:
                _set_wire_values(wire, wire_names, variables[BATCH_DIALOGUES])
                continue
            if canonical_name in variables:
                if _is_script_family_stage(stage_name) and canonical_name == CHARACTERS:
                    _set_wire_values(
                        wire,
                        wire_names,
                        _build_script_character_scene_bundle(
                            variables.get(CHARACTERS),
                            variables.get(SCENES),
                        ),
                    )
                    continue
                if _is_script_family_stage(stage_name) and canonical_name == SCENES:
                    continue
                if canonical_name == CHARACTER_APPEARANCE_REQUIREMENTS:
                    _set_wire_values(
                        wire,
                        wire_names,
                        _merge_optional_text(
                            variables.get(CHARACTER_APPEARANCE_REQUIREMENTS),
                            variables.get(OUTFIT_SWITCH_RULES),
                        ),
                    )
                    continue
                _set_wire_values(wire, wire_names, variables[canonical_name])
                continue
            if canonical_name in {LAST_SUMMARY, HOOK_MEMORY, DIALOGUE_MEMORY, SCRIPT_MEMORY}:
                _set_wire_values(wire, wire_names, "")
            elif canonical_name in {ALL_HOOKS, ALL_DIALOGUES, ALL_SCRIPT}:
                _set_wire_values(wire, wire_names, "")
            elif canonical_name == USER_CONTENT_BASELINE:
                _set_wire_values(wire, wire_names, "{}")
            elif canonical_name == MAX_RETRIES:
                _set_wire_values(wire, wire_names, settings.max_retries_default)
        return wire

    def _endpoint_for(self, stage_name: str) -> FastGPTEndpoint:
        env_prefix = f"FASTGPT_{stage_name.upper()}"
        api_key_source, api_key = _env_with_name(
            f"{env_prefix}_API_KEY",
            *STAGE_API_KEY_ENV_ALIASES.get(stage_name, ()),
            "FASTGPT_API_KEY",
        )
        if not api_key:
            raise ValueError(
                f"缺少 FastGPT API Key：请在 workflow_code_skeleton/.env 中配置 "
                f"{env_prefix}_API_KEY 或 FASTGPT_API_KEY"
            )

        url_source, raw_url = _env_with_name(
            f"{env_prefix}_CHAT_COMPLETIONS_URL",
            "FASTGPT_CHAT_COMPLETIONS_URL",
            f"{env_prefix}_BASE_URL",
            "FASTGPT_BASE_URL",
        )
        url = _normalize_fastgpt_url(
            raw_url or "https://api.fastgpt.in/api/v1/chat/completions"
        )
        url_source = url_source or "default"
        timeout = int(
            _env(f"{env_prefix}_TIMEOUT", "FASTGPT_TIMEOUT")
            or getattr(settings, "fastgpt_timeout", 300)
        )
        prefix = _env("FASTGPT_CHAT_ID_PREFIX") or "scriptmaker"
        chat_id = (
            _env(f"{env_prefix}_CHAT_ID")
            or f"{prefix}-{stage_name}-{uuid.uuid4().hex[:8]}"
        )
        return FastGPTEndpoint(
            url=url,
            url_source=url_source,
            api_key=api_key,
            api_key_source=api_key_source or "unknown",
            chat_id=chat_id,
            timeout=timeout,
        )

    def _build_request_body(
        self,
        contract: FastGPTStageContract,
        variables: dict[str, Any],
        chat_id: str,
    ) -> dict[str, Any]:
        safe_variables = {
            key: to_jsonable_value(value)
            for key, value in variables.items()
        }
        detail = _detail_enabled_for_stage(contract.stage_name)
        body = {
            "chatId": chat_id,
            "stream": False,
            "detail": detail,
            "variables": safe_variables,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"执行阶段：{contract.label}。"
                        "读取输入，"
                        "并只返回约定的输出字段。"
                    ),
                }
            ],
        }
        payload_stats = _build_request_payload_stats(
            contract.stage_name,
            safe_variables,
            body,
        )
        self._remember_stage_debug_info(
            contract.stage_name,
            payload_stats=payload_stats,
            request_detail=detail,
        )
        warn_limit = max(
            0,
            int(getattr(settings, "fastgpt_stage_payload_warn_chars", 120000)),
        )
        hard_limit = max(
            warn_limit,
            int(getattr(settings, "fastgpt_stage_payload_hard_chars", 240000)),
        )
        if payload_stats["body_chars"] > warn_limit:
            logger.warning(
                "FastGPT 阶段 %s payload 过大：body=%s，warn=%s，detail=%s，变量=%s，最大字段=%s",
                contract.stage_name,
                payload_stats["body_chars"],
                warn_limit,
                detail,
                payload_stats["variable_keys"],
                _format_largest_payload_fields(payload_stats["largest_variables"]),
            )
        if payload_stats["body_chars"] > hard_limit:
            raise FastGPTPayloadTooLargeError(
                stage_name=contract.stage_name,
                body_chars=int(payload_stats["body_chars"]),
                hard_limit=hard_limit,
                largest_variables=list(payload_stats["largest_variables"]),
            )
        return body

    def _extract_output_payload(
        self,
        data: dict[str, Any],
        contract: FastGPTStageContract,
        variables: dict[str, Any],
        *,
        allow_fallback: bool = True,
    ) -> dict[str, Any]:
        expected = contract.output_names
        validated_candidates: list[ValidatedStageOutput] = []
        rejected_candidates: list[tuple[str, str, dict[str, Any] | None]] = []
        partial_matches: list[tuple[str, StageOutputMatch]] = []

        if contract.stage_name == STAGE_FRAMEWORK:
            framework_output = _extract_framework_stage_output(
                data,
                contract,
                rejected_candidates,
            )
            if framework_output.selected is not None:
                self._remember_stage_debug_info(
                    contract.stage_name,
                    raw_output_source=framework_output.selected.source,
                    matched_aliases=sorted(
                        set(framework_output.selected.matched_keys.values())
                    ),
                    normalized_preview=_truncate_log_text(
                        _json_for_log(framework_output.selected.validated_payload),
                        limit=800,
                    ),
                    framework_candidate_sources=[
                        item.get("source")
                        for item in framework_output.candidate_summaries
                    ],
                    framework_candidate_scores=framework_output.candidate_summaries,
                    framework_selected_candidate_source=framework_output.selected_source,
                    framework_selected_candidate_preview=framework_output.selected_preview,
                )
                logger.info(
                    "FastGPT 阶段 %s 选中 framework 候选，来源=%s，匹配字段=%s，候选摘要=%s，payload=%s",
                    contract.stage_name,
                    framework_output.selected.source,
                    framework_output.selected.matched_keys,
                    [
                        {
                            "source": item.get("source"),
                            "score": item.get("score"),
                        }
                        for item in framework_output.candidate_summaries[:3]
                    ],
                    _truncate_log_text(
                        _json_for_log(framework_output.selected.validated_payload),
                        limit=500,
                    ),
                )
                return framework_output.selected.validated_payload

        if contract.stage_name in APPEARANCE_MAPPING_OUTPUT_STAGES:
            appearance_output = _extract_appearance_stage_output(
                data,
                contract,
                variables,
                rejected_candidates,
            )
            existing_debug = self.get_last_stage_debug_info(contract.stage_name)
            previous_empty_alias = bool(existing_debug.get("appearance_h2KpLm91_empty"))
            previous_sources = list(existing_debug.get("appearance_candidate_sources") or [])
            previous_summaries = list(existing_debug.get("appearance_candidate_summaries") or [])
            combined_summaries = previous_summaries + list(appearance_output.candidate_summaries)
            combined_sources = previous_sources + [
                item.get("source") for item in appearance_output.candidate_summaries
            ]
            self._remember_stage_debug_info(
                contract.stage_name,
                appearance_candidate_sources=[
                    source for source in combined_sources if str(source or "").strip()
                ],
                appearance_candidate_summaries=combined_summaries,
                appearance_h2KpLm91_empty=previous_empty_alias
                or appearance_output.empty_alias_seen,
            )
            if appearance_output.selected is not None:
                self._remember_stage_debug_info(
                    contract.stage_name,
                    raw_output_source=appearance_output.selected.source,
                    matched_aliases=sorted(
                        set(appearance_output.selected.matched_keys.values())
                    ),
                    normalized_preview=_truncate_log_text(
                        _json_for_log(appearance_output.selected.validated_payload),
                        limit=800,
                    ),
                    appearance_selected_candidate_source=appearance_output.selected_source,
                    appearance_selected_candidate_preview=appearance_output.selected_preview,
                )
                logger.info(
                    "FastGPT 阶段 %s 选中 appearance 候选，来源=%s，匹配字段=%s，候选摘要=%s，payload=%s",
                    contract.stage_name,
                    appearance_output.selected.source,
                    appearance_output.selected.matched_keys,
                    [
                        {
                            "source": item.get("source"),
                            "status": item.get("status"),
                            "reason": item.get("reason"),
                        }
                        for item in appearance_output.candidate_summaries[:4]
                    ],
                    _truncate_log_text(
                        _json_for_log(appearance_output.selected.validated_payload),
                        limit=500,
                    ),
                )
                return appearance_output.selected.validated_payload

        if contract.stage_name in TEXT_FIRST_MULTI_FIELD_STAGES:
            preferred_text_output = _extract_preferred_text_stage_output(
                data,
                contract,
                rejected_candidates,
            )
            if preferred_text_output is not None:
                self._remember_stage_debug_info(
                    contract.stage_name,
                    raw_output_source=preferred_text_output.source,
                    matched_aliases=sorted(set(preferred_text_output.matched_keys.values())),
                    normalized_preview=_truncate_log_text(
                        _json_for_log(preferred_text_output.validated_payload),
                        limit=800,
                    ),
                )
                logger.info(
                    "FastGPT 阶段 %s 选中最终回复 JSON，来源=%s，匹配字段=%s，payload=%s",
                    contract.stage_name,
                    preferred_text_output.source,
                    preferred_text_output.matched_keys,
                    _truncate_log_text(
                        _json_for_log(preferred_text_output.validated_payload),
                        limit=800,
                    ),
                )
                return preferred_text_output.validated_payload

        if contract.stage_name not in APPEARANCE_MAPPING_OUTPUT_STAGES:
            # 先扫结构化槽位。FastGPT 在不同工作流/节点组合下，正式输出可能落在
            # responseData.updateVarResult、output、pluginOutput、toolDetail 等不同位置，
            # 这里统一把它们当作“候选正式产物”来做契约校验。
            for source, candidate in _iter_named_structured_candidates(data):
                variants = list(
                    _iter_repaired_candidate_variants(
                        contract=contract,
                        variables=variables,
                        source=source,
                        candidate=candidate,
                        allow_textual_relaxation=allow_fallback,
                    )
                ) or [(source, candidate)]
                for variant_source, variant_candidate in variants:
                    match = _payload_from_candidate(variant_candidate, contract)
                    if match is None:
                        continue
                    partial_matches.append((variant_source, match))
                    stage_issue = _stage_specific_candidate_issue(
                        contract=contract,
                        source=variant_source,
                        payload=match.payload,
                        candidate=variant_candidate,
                    )
                    if stage_issue is not None:
                        rejected_candidates.append((variant_source, stage_issue, match.payload))
                        continue
                    try:
                        validated_payload = contract.validate_output_payload(match.payload)
                    except ValueError as exc:
                        rejected_candidates.append((variant_source, str(exc), match.payload))
                        continue
                    validated_payload = _merge_review_auxiliary_fields(
                        validated_payload,
                        match.payload,
                        contract=contract,
                    )
                    validated_candidates.append(
                        ValidatedStageOutput(
                            source=variant_source,
                            payload=match.payload,
                            validated_payload=validated_payload,
                            matched_keys=match.matched_keys,
                            canonical_hits=match.canonical_hits,
                            alias_hits=match.alias_hits,
                        )
                    )

        if len(expected) == 1 and contract.stage_name not in APPEARANCE_MAPPING_OUTPUT_STAGES:
            single_key = expected[0]
            # 单字段阶段再额外走一遍“文本兜底”。
            # 这样即使 FastGPT 最后只回了一段 JSON 字符串或纯文本，也仍有机会
            # 被解析成合法阶段成品，而不是直接判定失败。
            for source, text in _iter_named_text_candidates(data):
                if not text:
                    continue
                text_variants = list(
                    _iter_repaired_candidate_variants(
                        contract=contract,
                        variables=variables,
                        source=source,
                        candidate=text,
                        allow_textual_relaxation=allow_fallback,
                    )
                )
                for variant_source, variant_candidate in text_variants:
                    match = _payload_from_candidate(variant_candidate, contract)
                    if match is None:
                        continue
                    partial_matches.append((variant_source, match))
                    stage_issue = _stage_specific_candidate_issue(
                        contract=contract,
                        source=variant_source,
                        payload=match.payload,
                        candidate=variant_candidate,
                    )
                    if stage_issue is not None:
                        rejected_candidates.append((variant_source, stage_issue, match.payload))
                        continue
                    try:
                        validated_payload = contract.validate_output_payload(match.payload)
                    except ValueError as exc:
                        rejected_candidates.append((variant_source, str(exc), match.payload))
                    else:
                        validated_candidates.append(
                            ValidatedStageOutput(
                                source=variant_source,
                                payload=match.payload,
                                validated_payload=validated_payload,
                                matched_keys=match.matched_keys,
                                canonical_hits=match.canonical_hits,
                                alias_hits=match.alias_hits,
                            )
                        )
                parsed_text = _try_parse_json(text)
                if parsed_text is not None:
                    match = _payload_from_candidate(parsed_text, contract)
                    if match is not None:
                        partial_matches.append((f"{source}(json)", match))
                        stage_issue = _stage_specific_candidate_issue(
                            contract=contract,
                            source=f"{source}(json)",
                            payload=match.payload,
                            candidate=parsed_text,
                        )
                        if stage_issue is not None:
                            rejected_candidates.append((f"{source}(json)", stage_issue, match.payload))
                            continue
                        try:
                            validated_payload = contract.validate_output_payload(match.payload)
                        except ValueError as exc:
                            rejected_candidates.append((f"{source}(json)", str(exc), match.payload))
                        else:
                            validated_candidates.append(
                                ValidatedStageOutput(
                                    source=f"{source}(json)",
                                    payload=match.payload,
                                    validated_payload=validated_payload,
                                    matched_keys=match.matched_keys,
                                    canonical_hits=match.canonical_hits,
                                    alias_hits=match.alias_hits,
                                )
                            )
                if _can_coerce_single_output(text, contract):
                    raw_payload = {single_key: text}
                    stage_issue = _stage_specific_candidate_issue(
                        contract=contract,
                        source=f"{source}(text)",
                        payload=raw_payload,
                        candidate=text,
                    )
                    if stage_issue is not None:
                        rejected_candidates.append((f"{source}(text)", stage_issue, raw_payload))
                        continue
                    try:
                        validated_payload = contract.validate_output_payload(raw_payload)
                    except ValueError as exc:
                        rejected_candidates.append((f"{source}(text)", str(exc), raw_payload))
                    else:
                        validated_candidates.append(
                            ValidatedStageOutput(
                                source=f"{source}(text)",
                                payload=raw_payload,
                                validated_payload=validated_payload,
                                matched_keys={single_key: single_key},
                                canonical_hits=1,
                                alias_hits=0,
                            )
                        )

        selected = _select_best_validated_output(validated_candidates)
        if selected is not None:
            self._remember_stage_debug_info(
                contract.stage_name,
                candidate_sources=_collect_candidate_sources(data),
                raw_output_source=selected.source,
                matched_aliases=sorted(set(selected.matched_keys.values())),
                matched_fields=list(selected.payload.keys()),
                missing_fields=[],
                probable_truncated_json=False,
                normalized_preview=_truncate_log_text(
                    _json_for_log(selected.validated_payload),
                    limit=800,
                ),
            )
            logger.info(
                "FastGPT 阶段 %s 选中输出来源=%s，匹配字段=%s，alias_hits=%s，payload=%s",
                contract.stage_name,
                selected.source,
                selected.matched_keys,
                selected.alias_hits,
                _truncate_log_text(_json_for_log(selected.validated_payload), limit=800),
            )
            return selected.validated_payload

        details = _format_rejected_candidate_details(rejected_candidates)
        response_summary = _response_log_summary(data, answer_limit=1000)
        answer_preview = _truncate_log_text(_first_text_candidate(data), limit=1000)
        candidate_sources = _collect_candidate_sources(data)
        probable_truncated_json, truncated_source = _probable_truncated_json_details(
            data,
            contract,
        )
        matched_source, matched_fields, missing_fields = _best_partial_match_info(
            partial_matches,
            expected,
        )
        raw_output_source = truncated_source or matched_source
        failure_reason = details
        if probable_truncated_json:
            failure_reason = (
                "输出疑似被截断；"
                f"{details}"
            )

        message = (
            f"FastGPT 阶段 {contract.stage_name} 未返回契约字段：{', '.join(expected)}；"
            f"未找到通过校验的候选输出。{failure_reason}；"
            f"候选字段：{', '.join(_candidate_output_keys(data)[:24]) or '无'}；"
            f"answerText 预览：{answer_preview or '空'}"
        )
        self._remember_stage_debug_info(
            contract.stage_name,
            status="no_valid_candidate",
            raw_output_source=raw_output_source,
            matched_aliases=[],
            matched_fields=matched_fields,
            missing_fields=missing_fields,
            candidate_sources=candidate_sources,
            probable_truncated_json=probable_truncated_json,
            answer_text_preview=answer_preview,
            response_preview=response_summary,
            output_keys=_candidate_output_keys(data),
            raw_response=data,
            conversation_log_available=False,
            normalized_preview="",
            last_failure_reason=failure_reason,
        )
        logger.error(message)
        raise FastGPTStageFormatError(
            stage_name=contract.stage_name,
            expected_fields=expected,
            failure_reason=failure_reason,
            candidate_sources=candidate_sources,
            matched_fields=matched_fields,
            missing_fields=missing_fields,
            probable_truncated_json=probable_truncated_json,
            answer_text_preview=answer_preview,
            response_preview=response_summary,
            raw_output_source=raw_output_source,
        )


def _env(*names: str) -> str | None:
    return _env_with_name(*names)[1]


def _merge_optional_text(*parts: Any) -> str:
    merged: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = str(part or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return "\n".join(merged).strip()


def _detail_enabled_for_stage(stage_name: str) -> bool:
    if stage_name == STAGE_CHARACTERS:
        return bool(getattr(settings, "fastgpt_characters_detail", False))
    if stage_name == STAGE_SCENES:
        return bool(getattr(settings, "fastgpt_scenes_detail", False))
    if stage_name in APPEARANCE_DETAIL_STAGES:
        return bool(getattr(settings, "fastgpt_appearance_alias_generation_detail", False))
    return True


def _build_request_payload_stats(
    stage_name: str,
    variables: dict[str, Any],
    body: dict[str, Any],
) -> dict[str, Any]:
    variable_lengths = {
        str(key): _payload_chars(value)
        for key, value in variables.items()
    }
    largest_variables = [
        {
            "name": name,
            "chars": size,
            "preview": _payload_preview(variables.get(name)),
        }
        for name, size in sorted(
            variable_lengths.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:5]
    ]
    return {
        "stage_name": stage_name,
        "variable_keys": list(variables.keys()),
        "variable_char_lengths": variable_lengths,
        "largest_variables": largest_variables,
        "body_chars": _payload_chars(body),
    }


def _format_largest_payload_fields(items: list[dict[str, Any]]) -> str:
    if not items:
        return "无"
    return "；".join(
        f"{item.get('name')}={item.get('chars')} preview={item.get('preview')}"
        for item in items
        if item.get("name")
    )


def _payload_chars(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    )


def _payload_preview(value: Any, *, limit: int = 120) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    return _truncate_log_text(text, limit=limit)


def _build_script_character_scene_bundle(characters: Any, scenes: Any) -> str:
    character_text = str(characters or "").strip()
    scene_text = str(scenes or "").strip()
    if character_text and scene_text:
        return (
            "【人设结果JSON】\n"
            f"{character_text}\n\n"
            "【场景结果JSON】\n"
            f"{scene_text}"
        ).strip()
    return character_text or scene_text


def _is_script_family_stage(stage_name: str) -> bool:
    return stage_name in {
        STAGE_SCRIPT,
        STAGE_SCRIPT_WRITING,
        STAGE_SCRIPT_WRITE,
        STAGE_SCRIPT_REVIEW,
        STAGE_SCRIPT_REWRITE,
        STAGE_SCRIPT_REVISE,
    }


def _is_dialogue_payload_stage(stage_name: str) -> bool:
    return stage_name in {
        STAGE_DIALOGUES,
        STAGE_DIALOGUES_WRITING,
        STAGE_DIALOGUE_WRITE,
        STAGE_DIALOGUES_REWRITE,
        STAGE_DIALOGUE_REVISE,
    }


def _env_with_name(*names: str) -> tuple[str | None, str | None]:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            normalized = str(value).strip()
            if "API_KEY" in name and normalized.startswith("="):
                normalized = normalized.lstrip("=").strip()
            return name, normalized
    return None, None


def _normalize_fastgpt_url(raw_url: str) -> str:
    url = raw_url.strip().rstrip("/")
    if not url:
        raise ValueError("FastGPT 接口地址不能为空")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"FastGPT 接口地址必须以 http:// 或 https:// 开头：{url}")
    if not url.endswith("/chat/completions"):
        logger.warning(
            "FastGPT 接口地址看起来不是完整 chat/completions URL，将按原样请求：%s",
            url,
        )
    return url


def _sleep_before_retry(delay: float, attempt: int) -> None:
    if delay > 0:
        time.sleep(delay * attempt)


def _format_http_error(
    stage_name: str,
    url: str,
    response: requests.Response,
) -> str:
    body = _safe_response_text(response)
    message = (
        f"FastGPT 阶段 {stage_name} HTTP {response.status_code} "
        f"{response.reason or ''}，URL：{url}"
    )
    if body:
        message += f"，响应片段：{body}"
    else:
        message += "，响应体为空"
    if response.status_code in TRANSIENT_STATUS_CODES:
        message += "。这是远端 FastGPT 或其上游模型服务的临时/网关错误；当前项目进度已保存，可稍后点击继续生成重试。"
    return message


def _safe_response_text(response: requests.Response) -> str:
    try:
        text = response.text or ""
    except Exception:
        return ""
    cleaned = " ".join(text.strip().split())
    return _truncate_log_text(cleaned, limit=1000)


def _json_for_log(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _truncate_log_text(text: str, *, limit: int = 500) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def _candidate_output_keys(data: Any, *, limit: int = 40) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    try:
        candidates = _iter_named_structured_candidates(data)
    except Exception:
        candidates = ()
    for _, candidate in candidates:
        normalized = candidate
        if isinstance(normalized, list):
            normalized = _dict_from_variable_items(normalized) or normalized
        if not isinstance(normalized, dict):
            continue
        for key in normalized.keys():
            name = str(key or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            keys.append(name)
            if len(keys) >= limit:
                return keys
    return keys


def _response_log_summary(data: Any, *, answer_limit: int = 1000) -> str:
    if not isinstance(data, dict):
        return _truncate_log_text(_json_for_log(data), limit=max(300, answer_limit))
    summary = {
        "root_keys": sorted(str(key) for key in data.keys())[:24],
        "candidate_keys": _candidate_output_keys(data, limit=40),
        "answer_text_preview": _truncate_log_text(
            _first_text_candidate(data),
            limit=answer_limit,
        ),
    }
    return _truncate_log_text(_json_for_log(summary), limit=max(600, answer_limit + 200))


def _collect_candidate_sources(data: Any, *, limit: int = 80) -> list[str]:
    sources: list[str] = []
    seen: set[str] = set()
    for source, _ in _iter_named_structured_candidates(data):
        if source in seen:
            continue
        seen.add(source)
        sources.append(source)
        if len(sources) >= limit:
            return sources
    for source, _ in _iter_named_text_candidates(data):
        if source in seen:
            continue
        seen.add(source)
        sources.append(source)
        if len(sources) >= limit:
            return sources
    return sources


def _best_partial_match_info(
    matches: list[tuple[str, StageOutputMatch]],
    expected_fields: tuple[str, ...],
) -> tuple[str, list[str], list[str]]:
    if not matches:
        return "none", [], list(expected_fields)
    best = max(
        matches,
        key=lambda item: (
            item[1].canonical_hits,
            -item[1].alias_hits,
            -len(item[1].missing_fields),
            _payload_source_priority(item[0]),
        ),
    )
    source, match = best
    matched = list(match.payload.keys())
    missing = list(match.missing_fields) or [
        field for field in expected_fields if field not in set(matched)
    ]
    return source, matched, missing


def _probable_truncated_json_details(
    data: Any,
    contract: FastGPTStageContract,
) -> tuple[bool, str]:
    for source, text in _iter_named_text_candidates(data):
        if _looks_like_probably_truncated_json(text, contract):
            return True, source
    return False, ""


def _iter_choice_message_contents(data: Any) -> Iterable[str]:
    if not isinstance(data, dict):
        return
    choices = data.get("choices")
    if not isinstance(choices, list):
        return
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict):
            yield from _iter_text_from_content(message.get("content"))


def _first_text_candidate(data: Any) -> str:
    for text in _iter_named_text_candidates(data):
        candidate = text[1] if isinstance(text, tuple) and len(text) == 2 else ""
        if candidate:
            return str(candidate)
    return ""


def _payload_from_candidate(
    candidate: Any,
    contract: FastGPTStageContract,
) -> StageOutputMatch | None:
    candidate = _normalize_payload_candidate(candidate, contract)
    if isinstance(candidate, list):
        candidate = _dict_from_variable_items(candidate)
    if not isinstance(candidate, dict):
        return None
    candidate = _normalize_stage_specific_output_candidate(candidate, contract)
    if not isinstance(candidate, dict):
        return None
    if _is_non_output_metadata(candidate):
        return None
    return _extract_contract_payload(candidate, contract)


def _scene_formal_source_blocked(source: str) -> bool:
    lowered = str(source or "").strip().lower()
    if not lowered:
        return False
    if lowered.startswith("choices["):
        return True
    if "toolcall" in lowered:
        return True
    return ".content" in lowered


def _scene_candidate_uses_blocked_text_wrapper(candidate: Any, *, depth: int = 0) -> bool:
    if depth > 5:
        return False
    if isinstance(candidate, dict):
        lowered_keys = {str(key).strip().lower() for key in candidate.keys()}
        if "toolcall" in lowered_keys or "message" in lowered_keys:
            return True
        return any(
            _scene_candidate_uses_blocked_text_wrapper(value, depth=depth + 1)
            for value in candidate.values()
        )
    if isinstance(candidate, list):
        return any(
            _scene_candidate_uses_blocked_text_wrapper(item, depth=depth + 1)
            for item in candidate
        )
    return False


def _stage_specific_candidate_issue(
    *,
    contract: FastGPTStageContract,
    source: str,
    payload: dict[str, Any],
    candidate: Any | None = None,
) -> str | None:
    if contract.stage_name != STAGE_SCENES:
        return None
    if _scene_formal_source_blocked(source):
        return "scenes 正式输出不能来自 message.content 或 toolCall 文本"
    lowered_source = str(source or "").strip().lower()
    if "(local_repair:" in lowered_source:
        allowed_repair_sources = (
            "newvariables",
            "updatevarresult",
            "variableupdate",
            "responsedata",
            "root",
            "answertext",
            ".output",
            "scene_setting",
            SCENE_VAR.lower(),
        )
        if not any(marker in lowered_source for marker in allowed_repair_sources):
            return "scenes 正式输出来源不是正式结构化场景槽位"
    if candidate is not None and _scene_candidate_uses_blocked_text_wrapper(candidate):
        return "scenes 正式输出不能来自 message/content 或 toolCall 包装"
    issues = validate_scenes_output(payload.get(SCENES))
    return issues[0] if issues else None

def _extract_contract_payload(
    candidate: dict[str, Any],
    contract: FastGPTStageContract,
) -> StageOutputMatch | None:
    """只按当前阶段契约字段和本阶段登记过的别名提取输出，拒绝通用相似字段猜测。"""
    payload: dict[str, Any] = {}
    matched_keys: dict[str, str] = {}
    canonical_hits = 0
    alias_hits = 0
    lowered_candidate = {str(key).lower(): key for key in candidate.keys()}
    missing_fields: list[str] = []

    for expected_name in contract.output_names:
        actual_key, value = extract_stage_output_with_aliases(
            candidate,
            expected_name,
            contract.aliases_for_output(expected_name),
            lowered_candidate=lowered_candidate,
        )
        if actual_key is None:
            missing_fields.append(expected_name)
            continue
        payload[expected_name] = value
        matched_keys[expected_name] = actual_key
        if actual_key == expected_name:
            canonical_hits += 1
        else:
            alias_hits += 1

    if missing_fields:
        if contract.stage_name not in PARTIAL_MATCH_MISSING_ERROR_STAGES or not payload:
            return None

    if contract.stage_name in PASS_REVIEW_OUTPUT_STAGES:
        for key in ("summary", "non_blocking_issues", "rewrite_start_episode", "stage"):
            if key in candidate and key not in payload:
                payload[key] = candidate[key]

    return StageOutputMatch(
        payload=payload,
        matched_keys=matched_keys,
        canonical_hits=canonical_hits,
        alias_hits=alias_hits,
        missing_fields=tuple(missing_fields),
    )


def extract_stage_output_with_aliases(
    candidate: dict[str, Any],
    canonical_name: str,
    aliases: tuple[str, ...] | list[str],
    *,
    lowered_candidate: dict[str, str] | None = None,
) -> tuple[str | None, Any]:
    lowered = lowered_candidate or {str(key).lower(): key for key in candidate.keys()}
    actual_key = _match_contract_output_key(
        canonical_name,
        candidate,
        lowered,
        contract=None,
        aliases=tuple(str(alias) for alias in aliases if str(alias).strip()),
    )
    if actual_key is None:
        return None, None
    return actual_key, candidate[actual_key]


def _match_contract_output_key(
    expected_name: str,
    candidate: dict[str, Any],
    lowered_candidate: dict[str, Any],
    contract: FastGPTStageContract | None = None,
    aliases: tuple[str, ...] | list[str] = (),
) -> str | None:
    """按“契约字段本名 -> 同名大小写变体 -> 阶段专属别名”的顺序寻找真实输出键。"""
    if expected_name in candidate:
        return expected_name

    exact_name = lowered_candidate.get(expected_name.lower())
    if exact_name is not None:
        return str(exact_name)

    alias_names = tuple(aliases) if aliases else contract.aliases_for_output(expected_name) if contract else ()
    for alias in alias_names:
        alias_key = lowered_candidate.get(str(alias).lower())
        if alias_key is not None:
            return str(alias_key)
    return None


def _select_best_validated_output(
    candidates: list[ValidatedStageOutput],
) -> ValidatedStageOutput | None:
    """在已通过契约校验的候选里，优先选择契约本名命中更多、alias 更少的来源。"""
    best: tuple[tuple[int, int, int, int], ValidatedStageOutput] | None = None
    for candidate in candidates:
        # 同时命中多个候选时，本地更相信“字段名更接近契约原名”的结果，
        # 因为 alias 常常来自旧工作流或中间节点，语义漂移风险更高。
        score = (
            candidate.canonical_hits,
            -candidate.alias_hits,
            _payload_source_priority(candidate.source),
            -len(candidate.source),
        )
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best is not None else None


def _payload_source_priority(source: str) -> int:
    lowered = source.lower()
    if lowered.startswith("root.newvariables"):
        return 90
    if lowered.startswith("root.updatevarresult"):
        return 80
    if lowered.startswith("responsedata.variableupdate"):
        return 70
    if "textoutput" in lowered:
        return 60
    if "answertext" in lowered:
        return 50
    if lowered.startswith("choices"):
        return 40
    if ".output" in lowered or ".outputs" in lowered or lowered.endswith("output") or lowered.endswith("outputs"):
        return 30
    if "contract_json" in lowered or "frameworkcontractjson" in lowered:
        return 20
    if "pluginoutput" in lowered or ".data" in lowered or lowered.endswith("data"):
        return 10
    if source == "root":
        return 1
    return 0


def _format_rejected_candidate_details(
    rejected: list[tuple[str, str, dict[str, Any] | None]],
) -> str:
    """把若干失败候选压成一条错误摘要，方便排查到底是哪类输出不合契约。"""
    if not rejected:
        return "没有发现任何可映射到阶段契约的候选输出"
    preview = []
    for source, error, payload in rejected[:4]:
        preview.append(
            f"{source}: {error}（payload={_truncate_log_text(_json_for_log(payload), limit=260)}）"
        )
    return "候选输出校验失败：" + "；".join(preview)


def _iter_repaired_candidate_variants(
    *,
    contract: FastGPTStageContract,
    variables: dict[str, Any],
    source: str,
    candidate: Any,
    allow_textual_relaxation: bool,
) -> Iterable[tuple[str, Any]]:
    if not is_repairable_stage_output(contract.stage_name):
        return ()
    if (
        contract.stage_name == STAGE_SCENES
        and str(source or "").strip() in {"root", "responseData"}
        and _scene_candidate_uses_blocked_text_wrapper(candidate)
    ):
        return ()

    attempts = 1 + max(0, int(getattr(settings, "fastgpt_output_repair_retries", 1)))
    repaired: list[tuple[str, Any]] = []
    for attempt_index in range(attempts):
        outcome = repair_stage_output_candidate(
            contract.stage_name,
            candidate,
            source=source,
            input_variables=variables,
            attempt_index=attempt_index,
            allow_textual_relaxation=allow_textual_relaxation,
        )
        if outcome is None:
            continue
        variant_source = f"{source}({outcome.mode}:{attempt_index + 1})"
        _log_stage_output_repair(contract.stage_name, variant_source, outcome)
        repaired.append((variant_source, outcome.payload))
        break
    return repaired


def _log_stage_output_repair(
    stage_name: str,
    source: str,
    outcome: StageRepairOutcome,
) -> None:
    if (
        not outcome.warnings
        and not outcome.alias_hits
        and not outcome.missing_fields
        and not outcome.used_fallback
        and not outcome.requires_local_restart
    ):
        return
    logger.warning(
        "FastGPT 阶段 %s 输出已修复，来源=%s，used_fallback=%s，requires_local_restart=%s，missing_fields=%s，alias_hits=%s，warnings=%s，payload=%s",
        stage_name,
        source,
        outcome.used_fallback,
        outcome.requires_local_restart,
        outcome.missing_fields[:12],
        outcome.alias_hits,
        outcome.warnings[:6],
        _truncate_log_text(_json_for_log(outcome.payload), limit=500),
    )


def _extract_preferred_text_stage_output(
    data: dict[str, Any],
    contract: FastGPTStageContract,
    rejected_candidates: list[tuple[str, str, dict[str, Any] | None]],
) -> ValidatedStageOutput | None:
    # framework / appearance_pre_strategy 这类新版纯 AI 节点，
    # 正式产物优先看最终回复文本里的整段 JSON，而不是更容易漂移的中间变量写回。
    for source, text in _iter_named_text_candidates(data):
        if not text:
            continue
        if contract.stage_name in PASS_REVIEW_OUTPUT_STAGES:
            json_candidates = extract_json_object_candidates(text)
            for candidate_index, parsed_text in reversed(list(enumerate(json_candidates))):
                match = _payload_from_candidate(parsed_text, contract)
                if match is None:
                    continue
                try:
                    validated_payload = contract.validate_output_payload(match.payload)
                except ValueError as exc:
                    rejected_candidates.append(
                        (f"{source}[json_object:{candidate_index}]", str(exc), match.payload)
                    )
                    continue
                validated_payload = _merge_review_auxiliary_fields(
                    validated_payload,
                    match.payload,
                    contract=contract,
                )
                return ValidatedStageOutput(
                    source=f"{source}[json_object:{candidate_index}]",
                    payload=match.payload,
                    validated_payload=validated_payload,
                    matched_keys=match.matched_keys,
                    canonical_hits=match.canonical_hits,
                    alias_hits=match.alias_hits,
                )
            continue

        parsed_text = _try_parse_json(text)
        if parsed_text is None:
            continue
        match = _payload_from_candidate(parsed_text, contract)
        if match is None:
            continue
        try:
            validated_payload = contract.validate_output_payload(match.payload)
        except ValueError as exc:
            rejected_candidates.append((f"{source}(json)", str(exc), match.payload))
            continue
        return ValidatedStageOutput(
            source=f"{source}(json)",
            payload=match.payload,
            validated_payload=validated_payload,
            matched_keys=match.matched_keys,
            canonical_hits=match.canonical_hits,
            alias_hits=match.alias_hits,
        )
    return None


def _extract_framework_stage_output(
    data: dict[str, Any],
    contract: FastGPTStageContract,
    rejected_candidates: list[tuple[str, str, dict[str, Any] | None]],
) -> FrameworkSelectionResult:
    scored_candidates = sorted(
        _iter_framework_scored_candidates(data, contract),
        key=lambda item: item.score,
        reverse=True,
    )
    candidate_summaries = [
        {
            "source": item.source,
            "score": item.score,
            "preview": item.preview,
        }
        for item in scored_candidates[:8]
    ]

    for item in scored_candidates:
        match = _payload_from_candidate(item.candidate, contract)
        if match is None:
            continue
        try:
            validated_payload = contract.validate_output_payload(match.payload)
        except ValueError as exc:
            rejected_candidates.append(
                (f"{item.source}(framework)", str(exc), match.payload)
            )
            continue
        return FrameworkSelectionResult(
            selected=ValidatedStageOutput(
                source=f"{item.source}(framework)",
                payload=match.payload,
                validated_payload=validated_payload,
                matched_keys=match.matched_keys,
                canonical_hits=match.canonical_hits,
                alias_hits=match.alias_hits,
            ),
            candidate_summaries=candidate_summaries,
            selected_source=item.source,
            selected_preview=item.preview,
        )

    return FrameworkSelectionResult(
        selected=None,
        candidate_summaries=candidate_summaries,
    )


def _extract_appearance_stage_output(
    data: dict[str, Any],
    contract: FastGPTStageContract,
    variables: dict[str, Any],
    rejected_candidates: list[tuple[str, str, dict[str, Any] | None]],
) -> AppearanceSelectionResult:
    candidate_summaries: list[dict[str, Any]] = []
    empty_alias_seen = False

    for source, candidate in _iter_appearance_output_candidates(data, contract):
        preview = _truncate_log_text(_json_for_log(candidate), limit=260)
        normalized_candidate, rejection_reason, alias_empty = _coerce_appearance_candidate(
            candidate
        )
        empty_alias_seen = empty_alias_seen or alias_empty
        if normalized_candidate is None:
            candidate_summaries.append(
                {
                    "source": source,
                    "status": "rejected",
                    "reason": rejection_reason,
                    "preview": preview,
                }
            )
            rejected_candidates.append((source, rejection_reason, None))
            continue

        variants = list(
            _iter_repaired_candidate_variants(
                contract=contract,
                variables=variables,
                source=source,
                candidate=normalized_candidate,
                allow_textual_relaxation=False,
            )
        ) or [(source, normalized_candidate)]

        last_reason = "候选未能映射到 appearance_mapping 契约"
        for variant_source, variant_candidate in variants:
            match = _payload_from_candidate(variant_candidate, contract)
            if match is None:
                last_reason = "候选未能映射到 appearance_mapping 契约"
                rejected_candidates.append((variant_source, last_reason, None))
                continue
            try:
                validated_payload = contract.validate_output_payload(match.payload)
            except ValueError as exc:
                last_reason = str(exc)
                rejected_candidates.append((variant_source, last_reason, match.payload))
                continue
            candidate_summaries.append(
                {
                    "source": variant_source,
                    "status": "selected",
                    "reason": "",
                    "preview": preview,
                }
            )
            return AppearanceSelectionResult(
                selected=ValidatedStageOutput(
                    source=f"{variant_source}(appearance)",
                    payload=match.payload,
                    validated_payload=validated_payload,
                    matched_keys=match.matched_keys,
                    canonical_hits=match.canonical_hits,
                    alias_hits=match.alias_hits,
                ),
                candidate_summaries=candidate_summaries,
                selected_source=variant_source,
                selected_preview=preview,
                empty_alias_seen=empty_alias_seen,
            )

        candidate_summaries.append(
            {
                "source": source,
                "status": "rejected",
                "reason": last_reason,
                "preview": preview,
            }
        )

    return AppearanceSelectionResult(
        selected=None,
        candidate_summaries=candidate_summaries,
        empty_alias_seen=empty_alias_seen,
    )


def _iter_framework_scored_candidates(
    data: dict[str, Any],
    contract: FastGPTStageContract,
) -> Iterable[FrameworkScoredCandidate]:
    seen: set[str] = set()
    for source, candidate in _iter_framework_output_candidates(data):
        if not isinstance(candidate, dict):
            continue
        serialized = _stable_candidate_fingerprint(candidate)
        cache_key = f"{source}:{serialized}"
        if cache_key in seen:
            continue
        seen.add(cache_key)
        preview = _truncate_log_text(_json_for_log(candidate), limit=500)
        yield FrameworkScoredCandidate(
            source=source,
            candidate=candidate,
            preview=preview,
            score=_score_framework_candidate(candidate, source, contract),
        )


def _iter_framework_output_candidates(
    data: dict[str, Any],
) -> Iterable[tuple[str, dict[str, Any]]]:
    for source, candidate in _iter_framework_structured_candidates(data):
        normalized = _coerce_framework_candidate_object(candidate)
        if isinstance(normalized, dict):
            yield (source, normalized)

    for source, text in _iter_framework_named_text_candidates(data):
        if not text:
            continue
        for index, candidate in enumerate(extract_json_object_candidates(text)):
            yield (f"{source}[json_object:{index}]", candidate)


def _iter_framework_structured_candidates(
    data: Any,
) -> Iterable[tuple[str, Any]]:
    for source, candidate in _iter_named_structured_candidates(data):
        yield from _iter_framework_wrapped_candidates(source, candidate)


def _iter_framework_named_text_candidates(data: Any) -> Iterable[tuple[str, str]]:
    if not isinstance(data, dict):
        return

    choices = data.get("choices")
    if isinstance(choices, list):
        for index, choice in enumerate(choices):
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str):
                text = strip_code_fence(content)
                if text:
                    yield (f"choices[{index}].message.content", text)
            elif isinstance(content, list):
                for text_index, text in enumerate(
                    _iter_framework_text_blocks_from_content_list(content)
                ):
                    cleaned = strip_code_fence(text)
                    if cleaned:
                        yield (
                            f"choices[{index}].message.content[{text_index}]",
                            cleaned,
                        )

    response_data = data.get("responseData")
    if isinstance(response_data, dict):
        yield from _yield_named_text_fields("responseData", response_data)
    elif isinstance(response_data, list):
        yield from _yield_named_text_list_fields("responseData", response_data)

    yield from _yield_named_text_fields("root", data)


def _iter_framework_text_blocks_from_content_list(content: list[Any]) -> Iterable[str]:
    for item in content:
        if isinstance(item, dict):
            item_type = str(item.get("type") or "").strip().lower()
            if item_type and item_type != "text":
                continue
            text = item.get("text")
            if isinstance(text, str):
                yield text
                continue
            if isinstance(text, dict) and isinstance(text.get("content"), str):
                yield text["content"]
                continue
            if isinstance(item.get("content"), str):
                yield item["content"]


def _iter_appearance_output_candidates(
    data: dict[str, Any],
    contract: FastGPTStageContract,
) -> Iterable[tuple[str, Any]]:
    output_alias = next(iter(contract.aliases_for_output(APPEARANCE_MAPPING)), "h2KpLm91")
    yielded: set[str] = set()

    def emit(source: str, value: Any) -> Iterable[tuple[str, Any]]:
        if source in yielded:
            return ()
        yielded.add(source)
        return ((source, value),)

    for source, candidate in _iter_appearance_named_alias_candidates(
        data,
        output_alias,
        "newVariables",
    ):
        yield from emit(source, candidate)

    for source, candidate in _iter_appearance_named_alias_candidates(
        data,
        output_alias,
        "updateVarResult",
    ):
        yield from emit(source, candidate)

    response_data = data.get("responseData")
    for source, container in _iter_response_like_branches(response_data, "responseData"):
        if not isinstance(container, dict) or "variableUpdate" not in container:
            continue
        source_name = f"{source}.variableUpdate.{output_alias}"
        yield from emit(source_name, _extract_named_value(container.get("variableUpdate"), output_alias))

    for source, candidate in _iter_appearance_answer_node_candidates(data, output_alias):
        yield from emit(source, candidate)

    for source, candidate in _iter_appearance_choice_json_candidates(data):
        yield from emit(source, candidate)


def _iter_appearance_named_alias_candidates(
    data: dict[str, Any],
    output_alias: str,
    container_key: str,
) -> Iterable[tuple[str, Any]]:
    for source, container in _iter_response_like_branches(data, "root"):
        if not isinstance(container, dict) or container_key not in container:
            continue
        candidate_source = f"{source}.{container_key}.{output_alias}"
        yield (candidate_source, _extract_named_value(container.get(container_key), output_alias))


def _iter_appearance_answer_node_candidates(
    data: dict[str, Any],
    output_alias: str,
) -> Iterable[tuple[str, Any]]:
    emitted: set[str] = set()
    for source, candidate in _iter_response_like_branches(data, "root"):
        if source in emitted or not _is_appearance_answer_node_source(source):
            continue
        if not isinstance(candidate, dict):
            continue
        if any(
            key in candidate
            for key in (
                output_alias,
                APPEARANCE_MAPPING,
                "scene_setting",
                APPEARANCE_NATURAL_LANGUAGE_VAR,
                CORE_SCENE_FINAL_VAR,
            )
        ):
            emitted.add(source)
            yield (source, candidate)


def _iter_appearance_choice_json_candidates(
    data: dict[str, Any],
) -> Iterable[tuple[str, Any]]:
    for index, content in enumerate(_iter_choice_message_contents(data)):
        cleaned = strip_code_fence(content).strip()
        if not cleaned:
            continue
        for candidate_index, candidate in enumerate(extract_json_object_candidates(cleaned)):
            if not isinstance(candidate, dict):
                continue
            if any(
                key in candidate
                for key in (
                    APPEARANCE_MAPPING,
                    "scene_setting",
                    APPEARANCE_NATURAL_LANGUAGE_VAR,
                    CORE_SCENE_FINAL_VAR,
                )
            ):
                yield (f"choices[{index}].message.content[json_object:{candidate_index}]", candidate)


def _is_appearance_answer_node_source(source: str) -> bool:
    for segment in str(source or "").lower().replace("[", ".[").split("."):
        normalized = segment.split("[", 1)[0]
        if normalized in {"answernode", "output", "outputs"}:
            return True
    return False


def _iter_response_like_branches(
    value: Any,
    prefix: str,
) -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        yield (prefix, value)
        for key, nested in value.items():
            if isinstance(nested, dict):
                yield from _iter_response_like_branches(nested, f"{prefix}.{key}")
            elif isinstance(nested, list):
                for index, item in enumerate(nested):
                    if isinstance(item, dict):
                        yield from _iter_response_like_branches(item, f"{prefix}.{key}[{index}]")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, dict):
                yield from _iter_response_like_branches(item, f"{prefix}[{index}]")


def _extract_named_value(container: Any, key: str) -> Any:
    if isinstance(container, dict):
        return container.get(key)
    if isinstance(container, list):
        mapped = _dict_from_variable_items(container)
        if isinstance(mapped, dict):
            return mapped.get(key)
    return None


def _iter_appearance_text_candidates(data: Any) -> Iterable[tuple[str, str]]:
    if not isinstance(data, dict):
        return

    yielded: set[str] = set()

    def emit(source: str, value: Any) -> Iterable[tuple[str, str]]:
        if not isinstance(value, str):
            return ()
        cleaned = strip_code_fence(value).strip()
        if not cleaned or source in yielded:
            return ()
        yielded.add(source)
        return ((source, cleaned),)

    response_data = data.get("responseData")
    for source, branch in _iter_response_like_branches(response_data, "responseData"):
        if not isinstance(branch, dict):
            continue
        yield from emit(f"{source}.answerText", branch.get("answerText"))
        yield from emit(f"{source}.textOutput", branch.get("textOutput"))
        outputs = branch.get("outputs")
        if isinstance(outputs, dict):
            yield from emit(f"{source}.outputs.answerText", outputs.get("answerText"))
            yield from emit(f"{source}.outputs.textOutput", outputs.get("textOutput"))

    yield from emit("root.answerText", data.get("answerText"))
    yield from emit("root.textOutput", data.get("textOutput"))

    for index, content in enumerate(_iter_choice_message_contents(data)):
        yield from emit(f"choices[{index}].message.content", content)


def _coerce_appearance_candidate(
    candidate: Any,
) -> tuple[dict[str, Any] | None, str, bool]:
    alias_empty = False
    current = candidate

    if isinstance(current, list):
        current = _dict_from_variable_items(current) or current

    if isinstance(current, str):
        text = strip_code_fence(current).strip()
        if not text:
            return None, "appearance_mapping 候选为空字符串", True
        if _looks_like_core_scene_text(text):
            return None, "候选是核心场景提炼文本，不是 appearance_mapping JSON", False
        parsed = _try_parse_json(text)
        if not isinstance(parsed, dict):
            return None, "appearance_mapping 候选不是可解析的 JSON object", False
        current = parsed

    if not isinstance(current, dict):
        return None, "appearance_mapping 候选不是 object", alias_empty

    if "scene_setting" in current:
        return None, "候选是 scene_setting，不是 appearance_mapping", alias_empty
    if APPEARANCE_NATURAL_LANGUAGE_VAR in current:
        return None, f"候选是 {APPEARANCE_NATURAL_LANGUAGE_VAR}，不是 appearance_mapping", alias_empty
    if CORE_SCENE_FINAL_VAR in current:
        return None, f"候选是 {CORE_SCENE_FINAL_VAR}，不是 appearance_mapping", alias_empty

    for key in (APPEARANCE_MAPPING_VAR, APPEARANCE_MAPPING):
        if key not in current:
            continue
        wrapped = current.get(key)
        if isinstance(wrapped, str):
            text = strip_code_fence(wrapped).strip()
            if not text:
                alias_empty = alias_empty or key == APPEARANCE_MAPPING_VAR
                return None, f"{key} 为空字符串", alias_empty
            if _looks_like_core_scene_text(text):
                return None, f"{key} 是核心场景提炼文本，不是 appearance_mapping JSON", alias_empty
            parsed = _try_parse_json(text)
            if parsed is None:
                return None, f"{key} 是纯文本，不是 JSON object", alias_empty
        elif wrapped in (None, ""):
            alias_empty = alias_empty or key == APPEARANCE_MAPPING_VAR
            return None, f"{key} 为空字符串", alias_empty

    normalized = normalize_appearance_mapping_candidate(current)
    if isinstance(normalized, dict):
        return normalized, "", alias_empty

    return None, "候选不是可归一化的 appearance_mapping object", alias_empty


def _looks_like_core_scene_text(text: str) -> bool:
    cleaned = " ".join(strip_code_fence(str(text or "")).split())
    if not cleaned:
        return False
    if cleaned.startswith("核心场景：") or cleaned.startswith("核心场景:"):
        return True
    if "核心场景包括" in cleaned:
        return True
    if "场景名：场景类型 / 建筑或空间属性" in cleaned:
        return True
    if "核心场景" in cleaned and "场景类型" in cleaned and "建筑或空间属性" in cleaned:
        return True
    return False


def extract_json_object_candidates(text: str) -> list[dict[str, Any]]:
    cleaned = strip_code_fence(text)
    if not cleaned:
        return []

    direct = _try_parse_json(cleaned)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(direct, dict):
        fingerprint = _stable_candidate_fingerprint(direct)
        seen.add(fingerprint)
        candidates.append(direct)

    in_string = False
    escaping = False
    depth = 0
    start_index: int | None = None
    for index, char in enumerate(cleaned):
        if depth > 0:
            if escaping:
                escaping = False
                continue
            if char == "\\":
                escaping = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
                continue
            if char == "}":
                depth -= 1
                if depth == 0 and start_index is not None:
                    snippet = cleaned[start_index : index + 1]
                    parsed = _try_parse_json(snippet)
                    if isinstance(parsed, dict):
                        fingerprint = _stable_candidate_fingerprint(parsed)
                        if fingerprint not in seen:
                            seen.add(fingerprint)
                            candidates.append(parsed)
                    start_index = None
                continue
        else:
            if char == "{":
                start_index = index
                depth = 1
                in_string = False
                escaping = False
    return candidates


def _coerce_framework_candidate_object(candidate: Any) -> dict[str, Any] | None:
    if isinstance(candidate, str):
        parsed = _try_parse_json(candidate)
        if isinstance(parsed, dict):
            return parsed
        candidates = extract_json_object_candidates(candidate)
        return candidates[0] if candidates else None
    if isinstance(candidate, list):
        candidate = _dict_from_variable_items(candidate) or candidate
    if not isinstance(candidate, dict):
        return None
    return candidate


def _iter_framework_wrapped_candidates(
    source: str,
    candidate: Any,
    *,
    depth: int = 0,
) -> Iterable[tuple[str, Any]]:
    if depth > 5:
        return

    if isinstance(candidate, str):
        parsed = _try_parse_json(candidate)
        if isinstance(parsed, dict):
            yield (source, parsed)
            return
        for index, parsed_candidate in enumerate(extract_json_object_candidates(candidate)):
            yield (f"{source}[json_object:{index}]", parsed_candidate)
        return

    if isinstance(candidate, list):
        normalized_list = _dict_from_variable_items(candidate)
        if isinstance(normalized_list, dict):
            yield from _iter_framework_wrapped_candidates(
                source,
                normalized_list,
                depth=depth + 1,
            )
        return

    if not isinstance(candidate, dict):
        return

    lowered = {str(key).lower(): key for key in candidate.keys()}
    if _looks_like_framework_candidate_dict(candidate):
        yield (source, candidate)

    for key in ("frameworkcontractjson", "contract_json", "textoutput", "answertext"):
        actual_key = lowered.get(key)
        if actual_key is None:
            continue
        yield from _iter_framework_wrapped_candidates(
            f"{source}.{actual_key}",
            candidate.get(actual_key),
            depth=depth + 1,
        )

    for key in (
        "updatevarresult",
        "newvariables",
        "variableupdate",
        "responsedata",
        "outputs",
        "output",
        "data",
    ):
        actual_key = lowered.get(key)
        if actual_key is None:
            continue
        yield from _iter_framework_wrapped_candidates(
            f"{source}.{actual_key}",
            candidate.get(actual_key),
            depth=depth + 1,
        )


def _score_framework_candidate(
    candidate: dict[str, Any],
    source: str,
    contract: FastGPTStageContract,
) -> tuple[int, int, int, int, int, int, int]:
    lowered = {str(key).lower(): key for key in candidate.keys()}
    logical_hits = 0
    canonical_hits = 0
    type_hits = 0
    alias_hits = 0
    all_framework_keys: set[str] = set()

    for field_name in contract.output_names:
        aliases = (field_name, *contract.aliases_for_output(field_name))
        all_framework_keys.update(str(alias).lower() for alias in aliases)
        actual_key = _match_contract_output_key(
            field_name,
            candidate,
            lowered,
            contract,
        )
        if actual_key is None:
            continue
        logical_hits += 1
        if actual_key == field_name:
            canonical_hits += 1
        else:
            alias_hits += 1
        if _framework_value_matches_expected_type(
            candidate.get(actual_key),
            contract.output_types[field_name],
        ):
            type_hits += 1

    metadata_penalty = 0
    lowered_keys = set(lowered.keys())
    if lowered_keys & {"historypreview", "reasoningtext", "responsedata", "choices"}:
        metadata_penalty += 4
    if lowered_keys & {"passed", "rewrite_required", "blocking_issues"}:
        metadata_penalty += 3
    if lowered_keys & {
        "final_hook_of_this_turn",
        "must_carry_into_next_turn",
        "appearance_continuity_summary",
        "appearance_alias_continuity_summary",
        "dialogue_voice_summary",
        "alias_usage_continuity",
    }:
        metadata_penalty += 3

    unrelated_keys = [
        key for key in lowered_keys if key not in all_framework_keys and key != "frameworkcontractjson"
    ]
    extraneous_penalty = max(0, len(unrelated_keys) - 2)

    return (
        logical_hits,
        canonical_hits,
        type_hits,
        _framework_source_priority(source),
        -metadata_penalty,
        -extraneous_penalty,
        -alias_hits,
    )


def _framework_source_priority(source: str) -> int:
    lowered = source.lower()
    if "frameworkcontractjson" in lowered:
        return 9
    return _payload_source_priority(source)


def _framework_value_matches_expected_type(value: Any, type_name: str) -> bool:
    if type_name == "string":
        return isinstance(value, str) and bool(value.strip())
    if type_name == "object":
        return isinstance(value, dict) and bool(value)
    if type_name == "array":
        return isinstance(value, list) and bool(value)
    try:
        coerce_fastgpt_value(value, type_name)
        return True
    except Exception:
        return False


def _looks_like_framework_candidate_dict(candidate: dict[str, Any]) -> bool:
    lowered_keys = {str(key).lower() for key in candidate.keys()}
    framework_markers = {
        "script_title_content",
        "script_title",
        "title",
        "story_outline",
        "story_outline_content",
        "user_characters",
        "character_bios_content",
        "user_scenes",
        "core_scene_content",
        "episode_plan",
        "episode_plan_content",
        "frameworkcontractjson",
    }
    return bool(lowered_keys & framework_markers)


def _stable_candidate_fingerprint(candidate: dict[str, Any]) -> str:
    try:
        return json.dumps(candidate, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(candidate)


def _normalize_stage_specific_output_candidate(
    candidate: dict[str, Any],
    contract: FastGPTStageContract,
) -> dict[str, Any]:
    # 通用字段匹配只解决“键名叫什么”的问题；
    # 某些阶段还需要先把 body 从 wrapper/list/camelCase 归一化成稳定母型，
    # 否则后续契约校验会把本来可用的结果误判为不合格。
    if contract.stage_name == STAGE_APPEARANCE_PRE_STRATEGY:
        return _normalize_appearance_pre_strategy_output_candidate(candidate, contract)
    if contract.stage_name in APPEARANCE_MAPPING_OUTPUT_STAGES:
        return _normalize_appearance_mapping_output_candidate(candidate, contract)
    if contract.stage_name == STAGE_EPISODE_PLAN_NORMALIZE:
        return _normalize_episode_plan_normalize_output_candidate(candidate, contract)
    if contract.stage_name == STAGE_SCENES:
        return _normalize_scenes_output_candidate(candidate, contract)
    if _is_dialogue_payload_stage(contract.stage_name):
        return _normalize_dialogues_output_candidate(candidate, contract)
    if contract.stage_name in PASS_REVIEW_OUTPUT_STAGES:
        return _normalize_pass_review_output_candidate(candidate, contract)
    return candidate


def _normalize_appearance_pre_strategy_output_candidate(
    candidate: dict[str, Any],
    contract: FastGPTStageContract,
) -> dict[str, Any]:
    lowered_candidate = {str(key).lower(): key for key in candidate.keys()}
    normalized: dict[str, Any] = {}
    for field_name in contract.output_names:
        actual_key = _match_contract_output_key(
            field_name,
            candidate,
            lowered_candidate,
            contract,
        )
        if actual_key is None:
            continue
        normalized[field_name] = _normalize_appearance_pre_strategy_value(
            candidate.get(actual_key)
        )
    return normalized or candidate


def _normalize_appearance_pre_strategy_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        # 后续 legacy 阶段仍把这三个字段当字符串上下文消费，
        # 所以这里在客户端入口就把新版结构化 JSON 压成稳定字符串。
        return json.dumps(value, ensure_ascii=False, indent=2)
    if value is None:
        return ""
    return str(value).strip()


def _normalize_scenes_output_candidate(
    candidate: dict[str, Any],
    contract: FastGPTStageContract,
) -> dict[str, Any]:
    del contract
    current: Any = candidate
    if isinstance(current, list):
        current = _dict_from_variable_items(current) or current
    if not isinstance(current, dict):
        return candidate

    if SCENES in current:
        normalized_value = _normalize_scenes_contract_value(current.get(SCENES))
        if normalized_value is not None:
            normalized = dict(current)
            normalized[SCENES] = normalized_value
            return normalized
        return current

    normalized_value = _normalize_scenes_contract_value(current)
    if normalized_value is None:
        return candidate
    return {SCENES: normalized_value}


def _normalize_scenes_contract_value(value: Any) -> str | None:
    candidate = value
    if isinstance(candidate, str):
        parsed = _try_parse_json(candidate)
        if parsed is not None:
            candidate = parsed
        else:
            return str(candidate).strip() or None

    if isinstance(candidate, list):
        candidate = {"scene_setting": {"scenes": candidate}}

    if not isinstance(candidate, dict):
        return None

    if isinstance(candidate.get("scene_setting"), dict):
        body = {"scene_setting": candidate["scene_setting"]}
    elif isinstance(candidate.get("scenes"), dict) and isinstance(
        candidate["scenes"].get("scene_setting"),
        dict,
    ):
        body = {"scene_setting": candidate["scenes"]["scene_setting"]}
    elif isinstance(candidate.get("scenes"), list):
        body = {"scene_setting": {"scenes": candidate["scenes"]}}
    else:
        return None

    return json.dumps(body, ensure_ascii=False)


def _normalize_appearance_mapping_output_candidate(
    candidate: dict[str, Any],
    contract: FastGPTStageContract,
) -> dict[str, Any]:
    del contract
    normalized = normalize_appearance_mapping_candidate(candidate)
    if isinstance(normalized, dict):
        return normalized
    return candidate


def _normalize_appearance_mapping_body(value: Any) -> dict[str, Any] | None:
    candidate = value
    if isinstance(candidate, str):
        parsed = _try_parse_json(candidate)
        candidate = parsed if parsed is not None else candidate

    if isinstance(candidate, list):
        mapped = _dict_from_variable_items(candidate)
        candidate = mapped if mapped is not None else candidate

    if not isinstance(candidate, dict):
        return None

    for key in (APPEARANCE_MAPPING, "appearanceMapping"):
        if key not in candidate:
            continue
        wrapped = _normalize_appearance_mapping_body(candidate.get(key))
        if isinstance(wrapped, dict):
            return wrapped

    if _looks_like_appearance_mapping_body(candidate):
        return candidate
    return None


def _looks_like_appearance_mapping_body(candidate: dict[str, Any]) -> bool:
    mapping = (
        candidate.get(APPEARANCE_MAPPING)
        if isinstance(candidate.get(APPEARANCE_MAPPING), dict)
        else candidate
    )
    return isinstance(mapping.get("characters"), list)


def _normalize_episode_plan_normalize_output_candidate(
    candidate: dict[str, Any],
    contract: FastGPTStageContract,
) -> dict[str, Any]:
    wrapper_keys = (
        NORMALIZED_EPISODE_PLAN,
        *contract.aliases_for_output(NORMALIZED_EPISODE_PLAN),
    )
    for key in wrapper_keys:
        if key not in candidate:
            continue
        wrapped = _normalize_episode_plan_normalize_body(candidate.get(key))
        if isinstance(wrapped, dict):
            return {NORMALIZED_EPISODE_PLAN: wrapped}

    wrapped_candidate = _normalize_episode_plan_normalize_body(candidate)
    if isinstance(wrapped_candidate, dict):
        return {NORMALIZED_EPISODE_PLAN: wrapped_candidate}
    return candidate


def _normalize_episode_plan_normalize_body(value: Any) -> dict[str, Any] | None:
    candidate = value
    if isinstance(candidate, str):
        parsed = _try_parse_json(candidate)
        candidate = parsed if parsed is not None else candidate

    if isinstance(candidate, list):
        mapped = _dict_from_variable_items(candidate)
        if mapped is not None:
            candidate = mapped
        elif all(isinstance(item, dict) for item in candidate):
            candidate = {"episodes": candidate}
        else:
            return None

    if not isinstance(candidate, dict):
        return None

    wrapper_keys = (
        NORMALIZED_EPISODE_PLAN,
        "episode_plan_normalized",
        "normalizedEpisodePlan",
        "episodePlanNormalized",
        "normalized_plan",
        "normalizedPlan",
    )
    for key in wrapper_keys:
        if key not in candidate:
            continue
        wrapped = _normalize_episode_plan_normalize_body(candidate.get(key))
        if isinstance(wrapped, dict):
            return wrapped

    normalized = _normalize_episode_plan_body_dict(candidate)
    if not _looks_like_episode_plan_normalize_body(normalized):
        return None
    return normalized


def _normalize_episode_plan_body_dict(candidate: dict[str, Any]) -> dict[str, Any]:
    key_aliases = {
        "parsedEpisodeCount": "parsed_episode_count",
        "appearanceAliasPlanning": "appearance_alias_planning",
    }
    normalized_candidate = {
        str(key_aliases.get(str(key), str(key))): value
        for key, value in candidate.items()
    }

    episodes = normalized_candidate.get("episodes")
    if isinstance(episodes, list):
        normalized_episodes = [
            _normalize_episode_plan_episode_item(item)
            for item in episodes
            if isinstance(item, dict)
        ]
    else:
        normalized_episodes = episodes

    payload: dict[str, Any] = {
        "parsed_episode_count": len(normalized_episodes)
        if isinstance(normalized_episodes, list)
        else normalized_candidate.get("parsed_episode_count"),
        "episodes": normalized_episodes,
    }
    planning = _normalize_episode_plan_alias_planning(
        normalized_candidate.get("appearance_alias_planning")
    )
    if planning is not None:
        payload["appearance_alias_planning"] = planning
    return payload


def _normalize_episode_plan_episode_item(item: dict[str, Any]) -> dict[str, Any]:
    key_aliases = {
        "episodeNumber": "episode",
        "episodeNo": "episode",
        "mainCharacterAliases": "main_character_aliases",
        "appearanceEvents": "appearance_events",
        "longTermStageFlags": "long_term_stage_flags",
        "sceneBasedAliasHints": "scene_based_alias_hints",
    }
    return {
        str(key_aliases.get(str(key), str(key))): value
        for key, value in item.items()
    }


def _normalize_episode_plan_alias_planning(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    candidate = value
    if isinstance(candidate, str):
        parsed = _try_parse_json(candidate)
        candidate = parsed if parsed is not None else candidate
    if not isinstance(candidate, dict):
        return {}

    key_aliases = {
        "planningScope": "planning_scope",
        "globalNamingStyle": "global_naming_style",
        "charactersWithMultipleVariants": "characters_with_multiple_variants",
        "globalRules": "global_rules",
        "uncertainOrMissingItems": "uncertain_or_missing_items",
    }
    normalized = {
        str(key_aliases.get(str(key), str(key))): value
        for key, value in candidate.items()
    }

    characters = normalized.get("characters_with_multiple_variants")
    if isinstance(characters, list):
        normalized["characters_with_multiple_variants"] = [
            _normalize_episode_plan_alias_character_item(item)
            for item in characters
            if isinstance(item, dict)
        ]
    return normalized


def _normalize_episode_plan_alias_character_item(item: dict[str, Any]) -> dict[str, Any]:
    key_aliases = {
        "characterName": "character_name",
        "switchDimensions": "switch_dimensions",
        "longTermStageSwitches": "long_term_stage_switches",
        "sceneBasedSwitches": "scene_based_switches",
    }
    normalized = {
        str(key_aliases.get(str(key), str(key))): value
        for key, value in item.items()
    }
    for key in ("long_term_stage_switches", "scene_based_switches"):
        switches = normalized.get(key)
        if isinstance(switches, list):
            normalized[key] = [
                _normalize_episode_plan_alias_switch_item(entry)
                for entry in switches
                if isinstance(entry, dict)
            ]
    return normalized


def _normalize_episode_plan_alias_switch_item(item: dict[str, Any]) -> dict[str, Any]:
    key_aliases = {
        "episodeRange": "episode_range",
        "recommendedAliasName": "recommended_alias_name",
        "sceneOrCondition": "scene_or_condition",
    }
    return {
        str(key_aliases.get(str(key), str(key))): value
        for key, value in item.items()
    }


def _looks_like_episode_plan_normalize_body(candidate: dict[str, Any]) -> bool:
    episodes = candidate.get("episodes")
    return isinstance(episodes, list)


def _normalize_dialogues_output_candidate(
    candidate: dict[str, Any],
    contract: FastGPTStageContract,
) -> dict[str, Any]:
    if BATCH_DIALOGUES in candidate:
        wrapped = _normalize_dialogues_body(candidate.get(BATCH_DIALOGUES))
        if isinstance(wrapped, dict):
            if BATCH_DIALOGUES in wrapped and len(wrapped) == 1 and isinstance(wrapped.get(BATCH_DIALOGUES), dict):
                return {**candidate, BATCH_DIALOGUES: wrapped[BATCH_DIALOGUES]}
            return {**candidate, BATCH_DIALOGUES: wrapped}
        return candidate

    for alias in contract.aliases_for_output(BATCH_DIALOGUES):
        if alias not in candidate:
            continue
        wrapped = _normalize_dialogues_body(candidate.get(alias))
        if isinstance(wrapped, dict):
            if BATCH_DIALOGUES in wrapped and len(wrapped) == 1 and isinstance(wrapped.get(BATCH_DIALOGUES), dict):
                return wrapped
            return {BATCH_DIALOGUES: wrapped}

    wrapped_candidate = _normalize_dialogues_body(candidate)
    if isinstance(wrapped_candidate, dict) and _looks_like_dialogues_body(wrapped_candidate):
        return {BATCH_DIALOGUES: wrapped_candidate}
    return candidate


def _normalize_dialogues_body(value: Any) -> dict[str, Any] | None:
    candidate = value
    if isinstance(candidate, str):
        parsed = _try_parse_json(candidate)
        candidate = parsed if parsed is not None else candidate

    if isinstance(candidate, list):
        candidate = _dict_from_variable_items(candidate)

    if not isinstance(candidate, dict):
        return None

    if BATCH_DIALOGUES in candidate and isinstance(candidate.get(BATCH_DIALOGUES), dict):
        inner = _normalize_dialogues_body(candidate.get(BATCH_DIALOGUES))
        return {BATCH_DIALOGUES: inner} if isinstance(inner, dict) else candidate

    key_aliases = {
        "batchMeta": "batch_meta",
        "characterVoiceBibles": "character_voice_bibles",
        "episodeDialogueBlocks": "episode_dialogue_blocks",
    }
    normalized = {
        str(key_aliases.get(str(key), str(key))): value
        for key, value in candidate.items()
    }
    return normalized


def _normalize_pass_review_output_candidate(
    candidate: dict[str, Any],
    contract: FastGPTStageContract,
) -> dict[str, Any]:
    wrapped_candidate = _normalize_pass_review_body(candidate)
    if isinstance(wrapped_candidate, dict) and _looks_like_pass_review_body(wrapped_candidate):
        return wrapped_candidate

    wrapper_keys: list[str] = []
    for field_name in contract.output_names:
        for alias in contract.aliases_for_output(field_name):
            if alias not in wrapper_keys:
                wrapper_keys.append(alias)

    for alias in wrapper_keys:
        if alias not in candidate:
            continue
        wrapped = _normalize_pass_review_body(candidate.get(alias))
        if isinstance(wrapped, dict):
            return wrapped
    return candidate


def _normalize_pass_review_body(value: Any) -> dict[str, Any] | None:
    candidate = value
    if isinstance(candidate, str):
        parsed = _try_parse_json(candidate)
        candidate = parsed if parsed is not None else candidate

    if isinstance(candidate, list):
        candidate = _dict_from_variable_items(candidate)

    if not isinstance(candidate, dict):
        return None

    if _looks_like_pass_review_body(candidate):
        return candidate

    if len(candidate) == 1:
        only_value = next(iter(candidate.values()))
        nested = _normalize_pass_review_body(only_value)
        if isinstance(nested, dict):
            return nested

    return candidate


def _merge_review_auxiliary_fields(
    validated_payload: dict[str, Any],
    raw_payload: dict[str, Any],
    *,
    contract: FastGPTStageContract,
) -> dict[str, Any]:
    if contract.stage_name not in PASS_REVIEW_OUTPUT_STAGES:
        return validated_payload

    merged = dict(validated_payload)
    for key in ("summary", "non_blocking_issues", "rewrite_start_episode", "stage"):
        if key in raw_payload:
            merged[key] = raw_payload[key]
    return merged


def _looks_like_pass_review_body(candidate: dict[str, Any]) -> bool:
    keys = {str(key) for key in candidate.keys()}
    return "passed" in keys and (
        "rewrite_required" in keys or "blocking_issues" in keys or "summary" in keys
    )


def _looks_like_dialogues_body(candidate: dict[str, Any]) -> bool:
    keys = {str(key) for key in candidate.keys()}
    required = {"batch_meta", "character_voice_bibles", "episode_dialogue_blocks"}
    if required.issubset(keys):
        return True
    return "episode_dialogue_blocks" in keys and (
        "batch_meta" in keys or "character_voice_bibles" in keys
    )


def _is_non_output_metadata(candidate: dict[str, Any]) -> bool:
    keys = {str(key).lower() for key in candidate.keys()}
    if "historypreview" in keys:
        return True
    if "reasoningtext" in keys or "reasoning_text" in keys:
        return True
    if "system_error_text" in keys or "system_errortext" in keys:
        return True
    if "obj" in keys and "value" in keys:
        return True
    metadata_only_keys = {
        "obj",
        "value",
        "type",
        "module",
        "moduleid",
        "nodeid",
        "name",
        "avatar",
        "status",
    }
    return bool(keys) and keys.issubset(metadata_only_keys)


def _iter_text_from_content(content: Any) -> Iterable[str]:
    if isinstance(content, str):
        yield content
        return
    if isinstance(content, dict):
        content_type = str(content.get("type") or "").strip().lower()
        if content_type in {"reasoning", "reason", "thinking", "analysis"}:
            return
        text = content.get("text")
        if isinstance(text, str):
            yield text
        elif isinstance(text, dict) and isinstance(text.get("content"), str):
            yield text["content"]
        if isinstance(content.get("content"), str):
            yield content["content"]
        return
    if isinstance(content, list):
        for item in content:
            yield from _iter_text_from_content(item)


def _can_coerce_single_output(value: Any, contract: FastGPTStageContract) -> bool:
    if len(contract.output_names) != 1:
        return False
    if contract.stage_name in STRICT_JSON_STRING_STAGES:
        # worldview / characters 虽然外层契约仍是 string，
        # 但字符串内部必须是合法 schema JSON，不能再把任意自然语言直接放行。
        return False
    key = contract.output_names[0]
    type_name = contract.output_types[key]
    try:
        coerce_fastgpt_value(value, type_name)
        return True
    except Exception:
        return False


def _iter_named_structured_candidates(data: Any) -> Iterable[tuple[str, Any]]:
    """只从 FastGPT 常见结构化输出槽位取候选，避免把输入回显 variables 当正式输出。"""
    if not isinstance(data, dict):
        return

    if "newVariables" in data:
        yield ("root.newVariables", data.get("newVariables"))
        value = data.get("newVariables")
        if isinstance(value, dict):
            yield from _yield_named_branch_candidates("root.newVariables", value)
        elif isinstance(value, list):
            yield from _yield_named_list_candidates("root.newVariables", value)

    if "updateVarResult" in data:
        yield ("root.updateVarResult", data.get("updateVarResult"))
        value = data.get("updateVarResult")
        if isinstance(value, dict):
            yield from _yield_named_branch_candidates("root.updateVarResult", value)
        elif isinstance(value, list):
            yield from _yield_named_list_candidates("root.updateVarResult", value)

    response_data = data.get("responseData")
    if isinstance(response_data, dict):
        if "variableUpdate" in response_data:
            yield ("responseData.variableUpdate", response_data.get("variableUpdate"))
            variable_update = response_data.get("variableUpdate")
            if isinstance(variable_update, dict):
                yield from _yield_named_branch_candidates("responseData.variableUpdate", variable_update)
            elif isinstance(variable_update, list):
                yield from _yield_named_list_candidates("responseData.variableUpdate", variable_update)
        yield from _yield_named_branch_candidates("responseData", response_data)
    elif isinstance(response_data, list):
        yield ("responseData", response_data)
        yield from _yield_named_list_candidates("responseData", response_data)

    yield from _yield_named_branch_candidates("root", data)


def _yield_named_branch_candidates(prefix: str, data: dict[str, Any]) -> Iterable[tuple[str, Any]]:
    """按固定白名单枚举某个响应分支里的结构化候选来源。"""
    if not isinstance(data, dict):
        return
    priority_keys = (
        "newVariables",
        "updateVarResult",
        "variableUpdate",
        "textOutput",
        "answerText",
        "output",
        "outputs",
        "contract_json",
        "frameworkContractJson",
        "toolCall",
        "pluginOutput",
        "data",
        "toolDetail",
        "answer",
        "response",
        "result",
        "content",
        "text",
    )
    for key in priority_keys:
        if key in data:
            source = f"{prefix}.{key}"
            value = data[key]
            yield (source, value)
            if isinstance(value, dict):
                yield from _yield_named_branch_candidates(source, value)
            elif isinstance(value, list):
                yield from _yield_named_list_candidates(source, value)
    yield (prefix, data)


def _yield_named_list_candidates(prefix: str, values: list[Any]) -> Iterable[tuple[str, Any]]:
    for index, item in enumerate(values):
        source = f"{prefix}[{index}]"
        yield (source, item)
        if isinstance(item, dict):
            yield from _yield_named_branch_candidates(source, item)
        elif isinstance(item, list):
            yield from _yield_named_list_candidates(source, item)


def _iter_named_text_candidates(data: Any) -> Iterable[tuple[str, str]]:
    """按统一优先级读取真实文本输出槽位，避免把推理内容当正式结果。"""
    if not isinstance(data, dict):
        return

    for key in ("textOutput", "answerText"):
        value = data.get(key)
        if isinstance(value, str):
            yield (f"root.{key}", strip_code_fence(value))

    for index, content in enumerate(_iter_choice_message_contents(data)):
        yield (f"choices[{index}].message.content", strip_code_fence(content))

    response_data = data.get("responseData")
    if isinstance(response_data, dict):
        for key in ("textOutput", "answerText"):
            value = response_data.get(key)
            if isinstance(value, str):
                yield (f"responseData.{key}", strip_code_fence(value))
    if isinstance(response_data, dict):
        yield from _yield_named_text_fields("responseData", response_data)
    elif isinstance(response_data, list):
        yield from _yield_named_text_list_fields("responseData", response_data)

    yield from _yield_named_text_fields("root", data)


def _yield_named_text_fields(prefix: str, data: dict[str, Any]) -> Iterable[tuple[str, str]]:
    """枚举某个响应分支里的文本字段，供单字段阶段做 JSON/纯文本双路解析。"""
    if not isinstance(data, dict):
        return
    for key in ("textOutput", "answerText", "answer", "response", "result", "content", "text"):
        value = data.get(key)
        if isinstance(value, str):
            yield (f"{prefix}.{key}", strip_code_fence(value))
    for key in ("output", "outputs", "contract_json", "frameworkContractJson", "variableUpdate", "updateVarResult", "newVariables", "toolCall", "pluginOutput", "data", "toolDetail"):
        value = data.get(key)
        if isinstance(value, dict):
            yield from _yield_named_text_fields(f"{prefix}.{key}", value)
        elif isinstance(value, list):
            yield from _yield_named_text_list_fields(f"{prefix}.{key}", value)


def _yield_named_text_list_fields(prefix: str, values: list[Any]) -> Iterable[tuple[str, str]]:
    for index, item in enumerate(values):
        source = f"{prefix}[{index}]"
        if isinstance(item, dict):
            yield from _yield_named_text_fields(source, item)
        elif isinstance(item, list):
            yield from _yield_named_text_list_fields(source, item)


def _extract_stage_auxiliary_outputs(data: dict[str, Any], stage_name: str) -> dict[str, Any]:
    """从响应里捞回少量仅用于展示的内部变量，不影响阶段主契约字段。"""
    wanted_keys = STAGE_AUXILIARY_OUTPUT_KEYS.get(stage_name, {})
    if not wanted_keys:
        return {}

    found: dict[str, Any] = {}
    for _, candidate in _iter_named_structured_candidates(data):
        normalized = _normalize_payload_candidate(candidate, contract_for(stage_name))
        if isinstance(normalized, list):
            normalized = _dict_from_variable_items(normalized)
        if not isinstance(normalized, dict):
            continue
        lowered_candidate = {str(key).lower(): key for key in normalized.keys()}
        for canonical_name, aliases in wanted_keys.items():
            if canonical_name in found:
                continue
            _, value = extract_stage_output_with_aliases(
                normalized,
                canonical_name,
                aliases,
                lowered_candidate=lowered_candidate,
            )
            if isinstance(value, str):
                value = value.strip()
            if value not in (None, "", [], {}):
                found[canonical_name] = value
    if len(found) == len(wanted_keys):
        return found

    for _, text_candidate in _iter_named_text_candidates(data):
        parsed = _try_parse_json(text_candidate)
        if isinstance(parsed, list):
            parsed = _dict_from_variable_items(parsed)
        if not isinstance(parsed, dict):
            continue
        lowered_candidate = {str(key).lower(): key for key in parsed.keys()}
        for canonical_name, aliases in wanted_keys.items():
            if canonical_name in found:
                continue
            _, value = extract_stage_output_with_aliases(
                parsed,
                canonical_name,
                aliases,
                lowered_candidate=lowered_candidate,
            )
            if isinstance(value, str):
                value = value.strip()
            if value not in (None, "", [], {}):
                found[canonical_name] = value
    return found


def _try_parse_json(text: str) -> Any | None:
    cleaned = strip_code_fence(text)
    if not cleaned:
        return None
    candidate: Any = cleaned
    for _ in range(3):
        if not isinstance(candidate, str):
            return candidate
        stripped = strip_code_fence(candidate).strip()
        if not stripped:
            return None
        parsed: Any | None = None
        try:
            parsed = parse_json(stripped)
        except Exception:
            parsed = None
        if parsed is None:
            try:
                parsed = json.loads(stripped)
            except Exception:
                return None
        candidate = parsed
    return candidate


def _looks_like_probably_truncated_json(
    text: str,
    contract: FastGPTStageContract,
) -> bool:
    cleaned = strip_code_fence(str(text or "")).strip()
    if not cleaned or not cleaned.startswith(("{", "[")):
        return False
    lowered = cleaned.lower()
    expected_tokens = {
        str(field).lower()
        for field in contract.output_names
    }
    for field in contract.output_names:
        expected_tokens.update(
            str(alias).lower()
            for alias in contract.aliases_for_output(field)
            if str(alias).strip()
        )
    if not any(token in lowered for token in expected_tokens):
        return False
    if _try_parse_json(cleaned) is not None:
        return False
    if cleaned[-1:] not in {"}", "]"}:
        return True
    return _bracket_balance_delta(cleaned) != 0


def _bracket_balance_delta(text: str) -> int:
    in_string = False
    escaping = False
    delta = 0
    for char in text:
        if escaping:
            escaping = False
            continue
        if char == "\\":
            escaping = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "{[":
            delta += 1
        elif char in "}]":
            delta -= 1
    return delta


fastgpt_client = FastGPTClient()


def _looks_like_payload_dict(candidate: dict[str, Any]) -> bool:
    scaffold_keys = {
        "id",
        "model",
        "usage",
        "choices",
        "message",
        "content",
        "responseData",
        "data",
        "pluginOutput",
        "output",
        "outputs",
        "newVariables",
        "variables",
    }
    return bool(candidate) and not any(key in candidate for key in scaffold_keys)


def _format_wire_value(value: Any) -> Any:
    jsonable = to_jsonable_value(value)
    if (
        isinstance(jsonable, dict)
        and set(jsonable.keys()) == {"raw"}
        and isinstance(jsonable.get("raw"), str)
    ):
        return jsonable["raw"]
    if isinstance(jsonable, (dict, list)):
        return json.dumps(jsonable, ensure_ascii=False)
    return jsonable


def _as_wire_names(wire_name: Any) -> tuple[str, ...]:
    if isinstance(wire_name, (tuple, list, set)):
        return tuple(str(name) for name in wire_name if str(name).strip())
    return (str(wire_name),)


def _set_wire_values(wire: dict[str, Any], wire_names: tuple[str, ...], value: Any) -> None:
    formatted = _format_wire_value(value)
    for name in wire_names:
        wire[name] = formatted


def _normalize_payload_candidate(
    candidate: Any,
    contract: FastGPTStageContract,
) -> Any:
    if isinstance(candidate, list):
        if len(candidate) == 1:
            single = _normalize_payload_candidate(candidate[0], contract)
            if single is not None:
                return single
        return candidate

    if not isinstance(candidate, dict):
        return candidate

    if "key" in candidate and "value" in candidate and isinstance(candidate.get("key"), str):
        candidate = {str(candidate["key"]).strip(): candidate.get("value")}
    elif "name" in candidate and "value" in candidate and isinstance(candidate.get("name"), str):
        candidate = {str(candidate["name"]).strip(): candidate.get("value")}
    else:
        variable = candidate.get("variable")
        if "value" in candidate:
            if isinstance(variable, str) and variable.strip():
                candidate = {variable.strip(): candidate.get("value")}
            elif isinstance(variable, list) and variable:
                variable_key = str(variable[-1] or "").strip()
                if variable_key:
                    candidate = {variable_key: candidate.get("value")}

    nested_text_keys = (
        "contract_json",
        "answerText",
        "answer",
        "content",
        "text",
        "result",
        "response",
    )
    for key in nested_text_keys:
        value = candidate.get(key)
        if isinstance(value, str):
            parsed = _try_parse_json(value)
            if parsed is None:
                continue
            normalized = _normalize_payload_candidate(parsed, contract)
            if normalized is not None:
                return normalized

    nested_list_keys = (
        "updateVarResult",
        "variableUpdate",
        "newVariables",
        "toolCall",
        "outputs",
        "output",
        "data",
        "responseData",
        "pluginOutput",
        "toolDetail",
    )
    for key in nested_list_keys:
        value = candidate.get(key)
        if isinstance(value, (list, dict)):
            normalized = _normalize_payload_candidate(value, contract)
            if normalized is not None:
                return _normalize_payload_candidate(normalized, contract)

    return candidate


def _dict_from_variable_items(candidate: list[Any]) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    for item in candidate:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        if isinstance(key, str) and key.strip():
            payload[key.strip()] = value
            continue
        variable = item.get("variable")
        if isinstance(variable, str) and variable.strip():
            payload[variable.strip()] = value
            continue
        if isinstance(variable, list) and len(variable) >= 2:
            variable_key = str(variable[-1] or "").strip()
            if variable_key:
                payload[variable_key] = value
                continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            payload[name.strip()] = value
    return payload or None
