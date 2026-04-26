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
    APPEARANCE_NATURAL_LANGUAGE_VAR,
    CHARACTER_NATURAL_LANGUAGE_VAR,
    SCENE_NATURAL_LANGUAGE_VAR,
)
from .fastgpt_contracts import (
    ALL_DIALOGUES,
    ALL_HOOKS,
    ALL_SCRIPT,
    APPEARANCE_MAPPING,
    BATCH_DIALOGUES,
    CHARACTERS,
    CHARACTER_ALIAS_NAMING_RULES,
    CHARACTER_APPEARANCE_REQUIREMENTS,
    LAST_SUMMARY,
    LEGACY_INPUT_ALIASES,
    MAX_RETRIES,
    NORMALIZED_EPISODE_PLAN,
    OUTFIT_SWITCH_RULES,
    STAGE_APPEARANCE_ALIAS_GENERATION,
    STAGE_APPEARANCE_PRE_STRATEGY,
    STAGE_DIALOGUES,
    STAGE_EPISODE_PLAN_NORMALIZE,
    STAGE_FRAMEWORK,
    STAGE_CHARACTERS,
    SCENES,
    STAGE_SCRIPT,
    STAGE_WORLDVIEW,
    USER_CONTENT_BASELINE,
    FastGPTStageContract,
    contract_for,
    coerce_fastgpt_value,
    to_jsonable_value,
)
from .json_utils import parse_json, strip_code_fence
from .stage_output_repair import (
    StageRepairOutcome,
    build_stage_output_fallback,
    is_repairable_stage_output,
    repair_stage_output_candidate,
)

logger = get_logger("fastgpt_client")


TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
STAGE_AUXILIARY_OUTPUT_KEYS: dict[str, tuple[str, ...]] = {
    "characters": (CHARACTER_NATURAL_LANGUAGE_VAR,),
    "scenes": (SCENE_NATURAL_LANGUAGE_VAR,),
    "appearance_alias_generation": (APPEARANCE_NATURAL_LANGUAGE_VAR,),
}
TEXT_FIRST_MULTI_FIELD_STAGES = {
    STAGE_FRAMEWORK,
    STAGE_APPEARANCE_PRE_STRATEGY,
}
PARTIAL_MATCH_MISSING_ERROR_STAGES = {
    STAGE_FRAMEWORK,
    STAGE_APPEARANCE_PRE_STRATEGY,
}
STRICT_JSON_STRING_STAGES = {
    STAGE_WORLDVIEW,
    STAGE_CHARACTERS,
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


class FastGPTStageOutputRetryRequest(ValueError):
    """Worldview/characters 未形成可消费契约输出时，要求本阶段重新调用一次。"""

    def __init__(
        self,
        *,
        stage_name: str,
        expected_fields: Iterable[str],
        details: str,
        response_preview: str,
    ) -> None:
        self.stage_name = stage_name
        self.expected_fields = tuple(str(field) for field in expected_fields)
        self.details = str(details or "").strip()
        self.response_preview = str(response_preview or "")
        preview = _truncate_log_text(self.response_preview, limit=500)
        message = (
            f"FastGPT 阶段 {stage_name} 未识别到可消费的契约输出，"
            f"期望字段：{', '.join(self.expected_fields)}；"
            f"{self.details or '没有发现任何可映射到阶段契约的候选输出'}；"
            f"实际返回内容：{preview}"
        )
        super().__init__(message)


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


@dataclass(frozen=True, slots=True)
class ValidatedStageOutput:
    """记录通过契约校验后的候选输出，供多来源候选之间做稳定排序。"""

    source: str
    payload: dict[str, Any]
    validated_payload: dict[str, Any]
    matched_keys: dict[str, str]
    canonical_hits: int
    alias_hits: int


class FastGPTClient:
    """OpenAI-compatible FastGPT workflow client.

    FastGPT applications expose workflow calls through /api/v1/chat/completions.
    Each stage can use its own API key, or all stages can share FASTGPT_API_KEY.
    """

    def run_stage(self, stage_name: str, variables: dict[str, Any]) -> dict[str, Any]:
        contract = contract_for(stage_name)
        contract.build_input_payload(variables)
        payload_variables = self._build_wire_variables(stage_name, variables, contract)
        output_reruns = 0
        if is_repairable_stage_output(stage_name):
            output_reruns = max(
                0,
                int(
                    getattr(
                        settings,
                        "fastgpt_stage_local_restart_retries",
                        getattr(settings, "fastgpt_stage_output_rerun_retries", 1),
                    )
                ),
            )

        total_attempts = 1 + output_reruns
        last_retry_request: FastGPTStageOutputRetryRequest | None = None
        for output_attempt in range(1, total_attempts + 1):
            # 结构化输出识别失败时重新创建 chat_id 再跑一次，
            # 避免同一个失败回复在同一会话上下文里被模型不断延续。
            endpoint = self._endpoint_for(stage_name)
            body = self._build_request_body(contract, payload_variables, endpoint.chat_id)
            headers = {
                "Authorization": f"Bearer {endpoint.api_key}",
                "Content-Type": "application/json",
            }
            response = self._post_with_retries(endpoint, headers, body, stage_name)
            data = response.json()
            try:
                raw_output = self._extract_output_payload(
                    data,
                    contract,
                    variables,
                    allow_fallback=output_attempt >= total_attempts,
                )
            except FastGPTStageOutputRetryRequest as exc:
                last_retry_request = exc
                logger.warning(
                    "FastGPT 阶段 %s 第 %s/%s 次输出未形成可消费契约结果，"
                    "将从当前阶段开头重新请求一次：%s",
                    stage_name,
                    output_attempt,
                    total_attempts,
                    exc,
                )
                continue

            validated_output = contract.validate_output_payload(raw_output)
            auxiliary_output = _extract_stage_auxiliary_outputs(data, stage_name)
            if auxiliary_output:
                logger.info(
                    "FastGPT 阶段 %s 捕获到辅助输出：%s",
                    stage_name,
                    auxiliary_output.keys(),
                )
            return {
                **auxiliary_output,
                **validated_output,
            }

        if last_retry_request is not None:
            raise last_retry_request
        raise RuntimeError(f"FastGPT 阶段 {stage_name} 未能产出合法输出。")

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
            try:
                response = requests.post(
                    endpoint.url,
                    headers=headers,
                    json=body,
                    timeout=36000,
                )
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
            if canonical_name in variables:
                if stage_name == STAGE_SCRIPT and canonical_name == CHARACTERS:
                    wire[wire_name] = _format_wire_value(
                        _build_script_character_scene_bundle(
                            variables.get(CHARACTERS),
                            variables.get(SCENES),
                        )
                    )
                    continue
                if stage_name == STAGE_SCRIPT and canonical_name == SCENES:
                    continue
                if canonical_name == CHARACTER_APPEARANCE_REQUIREMENTS:
                    wire[wire_name] = _format_wire_value(
                        _merge_optional_text(
                            variables.get(CHARACTER_APPEARANCE_REQUIREMENTS),
                            variables.get(OUTFIT_SWITCH_RULES),
                        )
                    )
                    continue
                wire[wire_name] = _format_wire_value(variables[canonical_name])
                continue
            if canonical_name == LAST_SUMMARY:
                wire[wire_name] = ""
            elif canonical_name in {ALL_HOOKS, ALL_DIALOGUES, ALL_SCRIPT}:
                wire[wire_name] = ""
            elif canonical_name == USER_CONTENT_BASELINE:
                wire[wire_name] = "{}"
            elif canonical_name == MAX_RETRIES:
                wire[wire_name] = settings.max_retries_default
        return wire

    def _endpoint_for(self, stage_name: str) -> FastGPTEndpoint:
        env_prefix = f"FASTGPT_{stage_name.upper()}"
        api_key_source, api_key = _env_with_name(f"{env_prefix}_API_KEY", "FASTGPT_API_KEY")
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
        return {
            "chatId": chat_id,
            "stream": False,
            "detail": True,
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

        if contract.stage_name in TEXT_FIRST_MULTI_FIELD_STAGES:
            preferred_text_output = _extract_preferred_text_stage_output(
                data,
                contract,
                rejected_candidates,
            )
            if preferred_text_output is not None:
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
                try:
                    validated_payload = contract.validate_output_payload(match.payload)
                except ValueError as exc:
                    rejected_candidates.append((variant_source, str(exc), match.payload))
                    continue
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

        if len(expected) == 1:
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
        if is_repairable_stage_output(contract.stage_name) and not allow_fallback:
            raise FastGPTStageOutputRetryRequest(
                stage_name=contract.stage_name,
                expected_fields=expected,
                details=details,
                response_preview=_json_for_log(data),
            )

        fallback = build_stage_output_fallback(
            contract.stage_name,
            source="local",
            input_variables=variables,
            failure_reason=details,
        )
        if fallback is not None:
            try:
                validated_fallback = contract.validate_output_payload(fallback.payload)
            except ValueError:
                logger.exception(
                    "FastGPT 阶段 %s fallback 生成后仍未通过契约校验，payload=%s",
                    contract.stage_name,
                    _truncate_log_text(_json_for_log(fallback.payload), limit=800),
                )
            else:
                _log_stage_output_repair(
                    contract.stage_name,
                    "fallback",
                    fallback,
                )
                return validated_fallback

        message = (
            f"FastGPT 阶段 {contract.stage_name} 未返回契约字段：{', '.join(expected)}；"
            f"未找到通过校验的候选输出。{details}；实际返回内容：{_json_for_log(data)}"
        )
        logger.error(message)
        raise ValueError(message)


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


def _env_with_name(*names: str) -> tuple[str | None, str | None]:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return name, str(value).strip()
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
    return cleaned


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
        actual_key = _match_contract_output_key(
            expected_name,
            candidate,
            lowered_candidate,
            contract,
        )
        if actual_key is None:
            missing_fields.append(expected_name)
            continue
        payload[expected_name] = candidate[actual_key]
        matched_keys[expected_name] = actual_key
        if actual_key == expected_name:
            canonical_hits += 1
        else:
            alias_hits += 1

    if missing_fields:
        if contract.stage_name not in PARTIAL_MATCH_MISSING_ERROR_STAGES or not payload:
            return None

    return StageOutputMatch(
        payload=payload,
        matched_keys=matched_keys,
        canonical_hits=canonical_hits,
        alias_hits=alias_hits,
    )


def _match_contract_output_key(
    expected_name: str,
    candidate: dict[str, Any],
    lowered_candidate: dict[str, Any],
    contract: FastGPTStageContract,
) -> str | None:
    """按“契约字段本名 -> 同名大小写变体 -> 阶段专属别名”的顺序寻找真实输出键。"""
    if expected_name in candidate:
        return expected_name

    exact_name = lowered_candidate.get(expected_name.lower())
    if exact_name is not None:
        return str(exact_name)

    for alias in contract.aliases_for_output(expected_name):
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
    if "contract_json" in lowered:
        return 8
    if "updatevarresult" in lowered:
        return 7
    if "newvariables" in lowered:
        return 6
    if ".output" in lowered or ".outputs" in lowered or lowered.endswith("output") or lowered.endswith("outputs"):
        return 5
    if "pluginoutput" in lowered or ".data" in lowered or lowered.endswith("data"):
        return 4
    if lowered.startswith("choices"):
        return 3
    if "answertext" in lowered or lowered.startswith("answertext"):
        return 2
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


def _normalize_stage_specific_output_candidate(
    candidate: dict[str, Any],
    contract: FastGPTStageContract,
) -> dict[str, Any]:
    # 通用字段匹配只解决“键名叫什么”的问题；
    # 某些阶段还需要先把 body 从 wrapper/list/camelCase 归一化成稳定母型，
    # 否则后续契约校验会把本来可用的结果误判为不合格。
    if contract.stage_name == STAGE_APPEARANCE_PRE_STRATEGY:
        return _normalize_appearance_pre_strategy_output_candidate(candidate, contract)
    if contract.stage_name == STAGE_APPEARANCE_ALIAS_GENERATION:
        return _normalize_appearance_mapping_output_candidate(candidate, contract)
    if contract.stage_name == STAGE_EPISODE_PLAN_NORMALIZE:
        return _normalize_episode_plan_normalize_output_candidate(candidate, contract)
    if contract.stage_name == STAGE_DIALOGUES:
        return _normalize_dialogues_output_candidate(candidate, contract)
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


def _normalize_appearance_mapping_output_candidate(
    candidate: dict[str, Any],
    contract: FastGPTStageContract,
) -> dict[str, Any]:
    wrapper_keys = (
        APPEARANCE_MAPPING,
        *contract.aliases_for_output(APPEARANCE_MAPPING),
        "appearanceMapping",
    )
    for key in wrapper_keys:
        if key not in candidate:
            continue
        wrapped = _normalize_appearance_mapping_body(candidate.get(key))
        if isinstance(wrapped, dict):
            return {APPEARANCE_MAPPING: wrapped}

    wrapped_candidate = _normalize_appearance_mapping_body(candidate)
    if isinstance(wrapped_candidate, dict):
        return {APPEARANCE_MAPPING: wrapped_candidate}
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

    response_data = data.get("responseData")
    if isinstance(response_data, dict):
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
        "contract_json",
        "variableUpdate",
        "updateVarResult",
        "newVariables",
        "toolCall",
        "output",
        "outputs",
        "pluginOutput",
        "data",
        "toolDetail",
        "answerText",
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
    """只读取 choices/answerText 等真实文本输出槽位，避免递归扫到中间元数据。"""
    if not isinstance(data, dict):
        return

    for index, content in enumerate(_iter_choice_message_contents(data)):
        yield (f"choices[{index}].message.content", strip_code_fence(content))

    response_data = data.get("responseData")
    if isinstance(response_data, dict):
        yield from _yield_named_text_fields("responseData", response_data)
    elif isinstance(response_data, list):
        yield from _yield_named_text_list_fields("responseData", response_data)

    yield from _yield_named_text_fields("root", data)


def _yield_named_text_fields(prefix: str, data: dict[str, Any]) -> Iterable[tuple[str, str]]:
    """枚举某个响应分支里的文本字段，供单字段阶段做 JSON/纯文本双路解析。"""
    if not isinstance(data, dict):
        return
    for key in ("answerText", "answer", "response", "result", "content", "text"):
        value = data.get(key)
        if isinstance(value, str):
            yield (f"{prefix}.{key}", strip_code_fence(value))
    for key in ("contract_json", "variableUpdate", "updateVarResult", "newVariables", "toolCall", "output", "outputs", "pluginOutput", "data", "toolDetail"):
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
    wanted_keys = STAGE_AUXILIARY_OUTPUT_KEYS.get(stage_name, ())
    if not wanted_keys:
        return {}

    found: dict[str, Any] = {}
    for _, candidate in _iter_named_structured_candidates(data):
        normalized = _normalize_payload_candidate(candidate, contract_for(stage_name))
        if isinstance(normalized, list):
            normalized = _dict_from_variable_items(normalized)
        if not isinstance(normalized, dict):
            continue
        for key in wanted_keys:
            if key in found:
                continue
            value = normalized.get(key)
            if isinstance(value, str):
                value = value.strip()
            if value not in (None, "", [], {}):
                found[key] = value
    return found


def _try_parse_json(text: str) -> Any | None:
    cleaned = strip_code_fence(text)
    if not cleaned:
        return None
    try:
        return parse_json(cleaned)
    except Exception:
        pass
    try:
        return json.loads(cleaned)
    except Exception:
        return None


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
