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
from .fastgpt_contracts import (
    ALL_DIALOGUES,
    ALL_HOOKS,
    ALL_SCRIPT,
    CHARACTERS,
    CHARACTER_APPEARANCE_REQUIREMENTS,
    LAST_SUMMARY,
    LEGACY_INPUT_ALIASES,
    MAX_RETRIES,
    OUTFIT_SWITCH_RULES,
    SCENES,
    STAGE_SCRIPT,
    USER_CONTENT_BASELINE,
    FastGPTStageContract,
    contract_for,
    coerce_fastgpt_value,
    to_jsonable_value,
)
from .json_utils import parse_json, strip_code_fence

logger = get_logger("fastgpt_client")


TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


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
        endpoint = self._endpoint_for(stage_name)
        body = self._build_request_body(contract, payload_variables, endpoint.chat_id)
        headers = {
            "Authorization": f"Bearer {endpoint.api_key}",
            "Content-Type": "application/json",
        }
        response = self._post_with_retries(endpoint, headers, body, stage_name)
        data = response.json()
        raw_output = self._extract_output_payload(data, contract)
        return contract.validate_output_payload(raw_output)

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
    ) -> dict[str, Any]:
        expected = contract.output_names
        validated_candidates: list[ValidatedStageOutput] = []
        rejected_candidates: list[tuple[str, str, dict[str, Any] | None]] = []

        for source, candidate in _iter_named_structured_candidates(data):
            match = _payload_from_candidate(candidate, contract)
            if match is None:
                continue
            try:
                validated_payload = contract.validate_output_payload(match.payload)
            except ValueError as exc:
                rejected_candidates.append((source, str(exc), match.payload))
                continue
            validated_candidates.append(
                ValidatedStageOutput(
                    source=source,
                    payload=match.payload,
                    validated_payload=validated_payload,
                    matched_keys=match.matched_keys,
                    canonical_hits=match.canonical_hits,
                    alias_hits=match.alias_hits,
                )
            )

        if len(expected) == 1:
            single_key = expected[0]
            for source, text in _iter_named_text_candidates(data):
                if not text:
                    continue
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
    if _is_non_output_metadata(candidate):
        return None
    return _extract_contract_payload(candidate, contract)

def _extract_contract_payload(
    candidate: dict[str, Any],
    contract: FastGPTStageContract,
) -> StageOutputMatch | None:
    payload: dict[str, Any] = {}
    matched_keys: dict[str, str] = {}
    canonical_hits = 0
    alias_hits = 0
    lowered_candidate = {str(key).lower(): key for key in candidate.keys()}

    for expected_name in contract.output_names:
        actual_key = _match_contract_output_key(
            expected_name,
            candidate,
            lowered_candidate,
            contract,
        )
        if actual_key is None:
            return None
        payload[expected_name] = candidate[actual_key]
        matched_keys[expected_name] = actual_key
        if actual_key == expected_name:
            canonical_hits += 1
        else:
            alias_hits += 1

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
    best: tuple[tuple[int, int, int, int], ValidatedStageOutput] | None = None
    for candidate in candidates:
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
    if source.startswith("responseData.contract_json"):
        return 8
    if source.startswith("responseData.updateVarResult"):
        return 7
    if source.startswith("responseData.newVariables"):
        return 6
    if source.startswith("responseData.output") or source.startswith("responseData.outputs"):
        return 5
    if source.startswith("responseData.pluginOutput") or source.startswith("responseData.data"):
        return 4
    if source.startswith("choices"):
        return 3
    if source.startswith("answerText") or source.startswith("responseData.answerText"):
        return 2
    if source == "root":
        return 1
    return 0


def _format_rejected_candidate_details(
    rejected: list[tuple[str, str, dict[str, Any] | None]],
) -> str:
    if not rejected:
        return "没有发现任何可映射到阶段契约的候选输出"
    preview = []
    for source, error, payload in rejected[:4]:
        preview.append(
            f"{source}: {error}（payload={_truncate_log_text(_json_for_log(payload), limit=260)}）"
        )
    return "候选输出校验失败：" + "；".join(preview)


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
    key = contract.output_names[0]
    type_name = contract.output_types[key]
    try:
        coerce_fastgpt_value(value, type_name)
        return True
    except Exception:
        return False


def _iter_named_structured_candidates(data: Any) -> Iterable[tuple[str, Any]]:
    if not isinstance(data, dict):
        return

    response_data = data.get("responseData")
    if isinstance(response_data, dict):
        yield from _yield_named_branch_candidates("responseData", response_data)

    yield from _yield_named_branch_candidates("root", data)


def _yield_named_branch_candidates(prefix: str, data: dict[str, Any]) -> Iterable[tuple[str, Any]]:
    if not isinstance(data, dict):
        return
    priority_keys = (
        "contract_json",
        "updateVarResult",
        "newVariables",
        "output",
        "outputs",
        "pluginOutput",
        "data",
        "answerText",
        "answer",
        "response",
        "result",
        "content",
        "text",
    )
    for key in priority_keys:
        if key in data:
            yield (f"{prefix}.{key}", data[key])
    yield (prefix, data)


def _iter_named_text_candidates(data: Any) -> Iterable[tuple[str, str]]:
    if not isinstance(data, dict):
        return

    for index, content in enumerate(_iter_choice_message_contents(data)):
        yield (f"choices[{index}].message.content", strip_code_fence(content))

    response_data = data.get("responseData")
    if isinstance(response_data, dict):
        yield from _yield_named_text_fields("responseData", response_data)

    yield from _yield_named_text_fields("root", data)


def _yield_named_text_fields(prefix: str, data: dict[str, Any]) -> Iterable[tuple[str, str]]:
    if not isinstance(data, dict):
        return
    for key in ("answerText", "answer", "response", "result", "content", "text"):
        value = data.get(key)
        if isinstance(value, str):
            yield (f"{prefix}.{key}", strip_code_fence(value))


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
        return {str(candidate["key"]).strip(): candidate.get("value")}

    variable = candidate.get("variable")
    if "value" in candidate:
        if isinstance(variable, str) and variable.strip():
            return {variable.strip(): candidate.get("value")}
        if isinstance(variable, list) and variable:
            variable_key = str(variable[-1] or "").strip()
            if variable_key:
                return {variable_key: candidate.get("value")}

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
        "newVariables",
        "outputs",
        "output",
        "data",
        "responseData",
        "pluginOutput",
    )
    for key in nested_list_keys:
        value = candidate.get(key)
        if isinstance(value, (list, dict)):
            normalized = _normalize_payload_candidate(value, contract)
            if normalized is not None:
                return normalized

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
