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
    LAST_SUMMARY,
    LEGACY_INPUT_ALIASES,
    LEGACY_OUTPUT_ALIASES,
    MAX_RETRIES,
    USER_CONTENT_BASELINE,
    FastGPTStageContract,
    contract_for,
    coerce_fastgpt_value,
    to_jsonable_value,
)
from .json_utils import parse_json, strip_code_fence

logger = get_logger("fastgpt_client")


TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
OUTPUT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "is_consistent": (
        "is_consistent",
        "passed",
        "approved",
        "consistent",
    ),
}


@dataclass(frozen=True, slots=True)
class FastGPTEndpoint:
    url: str
    url_source: str
    api_key: str
    api_key_source: str
    chat_id: str
    timeout: int


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

        logger.info(
            "调用 FastGPT 阶段 %s，URL：%s，URL来源：%s，Key来源：%s，headers摘要：%s，变量：%s，payload摘要：%s",
            stage_name,
            endpoint.url,
            endpoint.url_source,
            endpoint.api_key_source,
            _summarize_headers(headers),
            ", ".join(payload_variables.keys()),
            _summarize_payload(body),
        )
        response = self._post_with_retries(endpoint, headers, body, stage_name)
        data = response.json()
        logger.info(
            "FastGPT 阶段 %s 原始响应 data：%s",
            stage_name,
            _json_for_log(data),
        )
        raw_output = self._extract_output_payload(data, contract)
        logger.info(
            "FastGPT 阶段 %s 解析得到的原始输出：%s",
            stage_name,
            _json_for_log(raw_output),
        )
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
                    timeout=endpoint.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "FastGPT 阶段 %s 网络请求失败，URL：%s，headers摘要：%s，payload摘要：%s，错误：%s",
                    stage_name,
                    endpoint.url,
                    _summarize_headers(headers),
                    _summarize_payload(body),
                    exc,
                )
                if attempt >= attempts:
                    raise RuntimeError(
                        f"FastGPT 阶段 {stage_name} 网络请求失败：{exc}"
                    ) from exc
                _sleep_before_retry(delay, attempt)
                continue

            if response.status_code >= 400:
                logger.warning(
                    "FastGPT 阶段 %s 请求失败，URL：%s，HTTP %s %s，response.text：%s，headers摘要：%s，payload摘要：%s",
                    stage_name,
                    endpoint.url,
                    response.status_code,
                    response.reason or "",
                    _safe_response_text(response),
                    _summarize_headers(headers),
                    _summarize_payload(body),
                )

            if response.status_code in TRANSIENT_STATUS_CODES and attempt < attempts:
                logger.warning(
                    "FastGPT 阶段 %s 返回 HTTP %s，准备第 %s 次重试。",
                    stage_name,
                    response.status_code,
                    attempt + 1,
                )
                _sleep_before_retry(delay, attempt)
                continue

            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise RuntimeError(
                    _format_http_error(stage_name, endpoint.url, response)
                ) from exc
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
                        "请严格读取 variables 中的输入变量，"
                        "并只返回约定的 JSON 输出字段。"
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
        logger.info(
            "FastGPT 阶段 %s 开始解析输出，期望字段：%s",
            contract.stage_name,
            list(expected),
        )

        choice_contents = list(_iter_choice_message_contents(data))
        for index, content in enumerate(choice_contents):
            logger.info(
                "FastGPT 阶段 %s choices[%s].message.content：%s",
                contract.stage_name,
                index,
                content,
            )
            parsed_content = _try_parse_json(content)
            if parsed_content is not None:
                logger.info(
                    "FastGPT 阶段 %s choices[%s].message.content JSON解析结果：%s",
                    contract.stage_name,
                    index,
                    _json_for_log(parsed_content),
                )
                candidate_payload = _payload_from_candidate(parsed_content, contract)
                if candidate_payload is not None:
                    logger.info(
                        "FastGPT 阶段 %s 使用 choices[%s].message.content JSON解析结果作为输出：%s",
                        contract.stage_name,
                        index,
                        _json_for_log(candidate_payload),
                    )
                    return candidate_payload

            if len(expected) == 1 and _can_coerce_single_output(content, contract):
                key = expected[0]
                payload = {key: content}
                logger.info(
                    "FastGPT 阶段 %s 使用 choices[%s].message.content 文本作为字段 %s：%s",
                    contract.stage_name,
                    index,
                    key,
                    content,
                )
                return payload

        for candidate in _iter_structured_output_candidates(data):
            logger.info(
                "FastGPT 阶段 %s 结构化解析候选：%s",
                contract.stage_name,
                _json_for_log(candidate),
            )
            candidate_payload = _payload_from_candidate(candidate, contract)
            if candidate_payload is not None:
                logger.info(
                    "FastGPT 阶段 %s 使用结构化候选作为输出：%s",
                    contract.stage_name,
                    _json_for_log(candidate_payload),
                )
                return candidate_payload

        if len(expected) == 1:
            key = expected[0]
            for candidate in _iter_answer_text_candidates(data):
                text = strip_code_fence(candidate)
                logger.info(
                    "FastGPT 阶段 %s 文本解析候选：%s",
                    contract.stage_name,
                    text,
                )
                parsed_text = _try_parse_json(text)
                if parsed_text is not None:
                    logger.info(
                        "FastGPT 阶段 %s 文本候选 JSON解析结果：%s",
                        contract.stage_name,
                        _json_for_log(parsed_text),
                    )
                    candidate_payload = _payload_from_candidate(parsed_text, contract)
                    if candidate_payload is not None:
                        logger.info(
                            "FastGPT 阶段 %s 使用文本候选 JSON解析结果作为输出：%s",
                            contract.stage_name,
                            _json_for_log(candidate_payload),
                        )
                        return candidate_payload
                if text and _can_coerce_single_output(text, contract):
                    logger.info(
                        "FastGPT 阶段 %s 使用文本候选作为字段 %s：%s",
                        contract.stage_name,
                        key,
                        text,
                    )
                    return {key: text}

            if contract.output_types[key] == "object":
                for candidate in _iter_structured_output_candidates(data):
                    if isinstance(candidate, dict) and _looks_like_payload_dict(candidate):
                        return {key: candidate}

        message = (
            f"FastGPT 阶段 {contract.stage_name} 未返回契约字段：{', '.join(expected)}；"
            f"实际返回内容：{_json_for_log(data)}"
        )
        logger.error(message)
        raise ValueError(message)


def _env(*names: str) -> str | None:
    return _env_with_name(*names)[1]


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
    return message


def _safe_response_text(response: requests.Response) -> str:
    try:
        text = response.text or ""
    except Exception:
        return ""
    cleaned = " ".join(text.strip().split())
    return cleaned


def _summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    variables = payload.get("variables")
    if isinstance(variables, dict):
        variable_summary = {
            key: "***" if _is_sensitive_name(key) else _summarize_value(value)
            for key, value in variables.items()
        }
    else:
        variable_summary = {}

    messages = payload.get("messages")
    message_summary: list[dict[str, Any]] = []
    if isinstance(messages, list):
        for item in messages[:3]:
            if not isinstance(item, dict):
                continue
            message_summary.append(
                {
                    "role": item.get("role"),
                    "content": _summarize_value(item.get("content")),
                }
            )

    return {
        "chatId": payload.get("chatId"),
        "stream": payload.get("stream"),
        "detail": payload.get("detail"),
        "variables": variable_summary,
        "messages": message_summary,
    }


def _summarize_headers(headers: dict[str, str]) -> dict[str, Any]:
    authorization = headers.get("Authorization", "")
    return {
        "Content-Type": headers.get("Content-Type"),
        "Authorization": "Bearer ***" if authorization.startswith("Bearer ") else "<missing>",
    }


def _is_sensitive_name(name: str) -> bool:
    lowered = str(name).lower()
    return any(
        token in lowered
        for token in ("key", "token", "secret", "password", "authorization")
    )


def _summarize_value(value: Any) -> Any:
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(str(text).split())
    if len(text) <= 240:
        return text
    return f"{text[:240]}...<len={len(text)}>"


def _json_for_log(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


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
) -> dict[str, Any] | None:
    expected = contract.output_names
    if not isinstance(candidate, dict):
        return None
    if _is_non_output_metadata(candidate):
        return None

    if all(name in candidate for name in expected):
        return {name: candidate[name] for name in expected}

    alias_payload = _extract_generic_alias_payload(candidate, contract)
    if alias_payload is not None:
        logger.warning(
            "FastGPT 阶段 %s 返回字段与契约不完全一致，已按别名映射：期望=%s，实际字段=%s，映射结果=%s",
            contract.stage_name,
            list(expected),
            list(candidate.keys()),
            _json_for_log(alias_payload),
        )
        return alias_payload

    legacy_payload = _extract_legacy_alias_payload(candidate, contract)
    if legacy_payload is not None:
        logger.warning(
            "FastGPT 阶段 %s 返回 legacy 字段，已映射到契约字段：期望=%s，实际字段=%s，映射结果=%s",
            contract.stage_name,
            list(expected),
            list(candidate.keys()),
            _json_for_log(legacy_payload),
        )
        return legacy_payload

    _warn_similar_fields(candidate, contract)
    return None


def _extract_generic_alias_payload(
    candidate: dict[str, Any],
    contract: FastGPTStageContract,
) -> dict[str, Any] | None:
    if _is_non_output_metadata(candidate):
        return None
    payload: dict[str, Any] = {}
    lowered_candidate = {key.lower(): key for key in candidate.keys()}
    for expected_name in contract.output_names:
        if expected_name in candidate:
            payload[expected_name] = candidate[expected_name]
            continue
        matched = False
        for alias in OUTPUT_FIELD_ALIASES.get(expected_name, ()):
            actual_key = lowered_candidate.get(alias.lower())
            if actual_key is not None:
                payload[expected_name] = candidate[actual_key]
                matched = True
                break
        if not matched:
            return None
    return payload


def _warn_similar_fields(candidate: dict[str, Any], contract: FastGPTStageContract) -> None:
    candidate_keys = {key.lower(): key for key in candidate.keys()}
    for expected_name in contract.output_names:
        if expected_name in candidate:
            continue
        found = [
            candidate_keys[alias.lower()]
            for alias in OUTPUT_FIELD_ALIASES.get(expected_name, ())
            if alias.lower() in candidate_keys
        ]
        if found:
            logger.warning(
                "FastGPT 阶段 %s 未返回契约字段 %s，但发现相似字段 %s；请考虑改 FastGPT 输出提示词或 Python 映射。",
                contract.stage_name,
                expected_name,
                found,
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
    key = contract.output_names[0]
    type_name = contract.output_types[key]
    try:
        coerce_fastgpt_value(value, type_name)
        return True
    except Exception:
        return False


def _iter_output_candidates(data: Any) -> Iterable[Any]:
    yield data

    if isinstance(data, dict):
        priority_keys = (
            "pluginOutput",
            "output",
            "outputs",
            "newVariables",
            "variables",
            "responseData",
            "data",
            "answer",
            "content",
            "choices",
            "message",
        )
        for key in priority_keys:
            if key in data:
                yield from _iter_output_candidates(data[key])
        for key, value in data.items():
            if key not in priority_keys:
                yield from _iter_output_candidates(value)

    elif isinstance(data, list):
        for item in data:
            yield from _iter_output_candidates(item)

    elif isinstance(data, str):
        parsed = _try_parse_json(data)
        if parsed is not None:
            yield parsed


def _iter_structured_output_candidates(data: Any) -> Iterable[Any]:
    yield data
    if isinstance(data, dict):
        if _is_non_output_metadata(data):
            return
        priority_keys = (
            "choices",
            "message",
            "responseData",
            "pluginOutput",
            "output",
            "outputs",
            "newVariables",
            "variables",
            "data",
            "answer",
            "content",
        )
        skip_keys = {
            "historyPreview",
            "history",
            "chatHistory",
            "reasoningText",
            "reasoning_text",
            "system_error_text",
            "systemErrorText",
            "quoteList",
            "obj",
            "value",
        }
        for key in priority_keys:
            if key in data and key not in skip_keys:
                yield from _iter_structured_output_candidates(data[key])
        for key, value in data.items():
            if key not in priority_keys and key not in skip_keys:
                yield from _iter_structured_output_candidates(value)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_structured_output_candidates(item)
    elif isinstance(data, str):
        parsed = _try_parse_json(data)
        if parsed is not None:
            yield parsed


def _iter_answer_text_candidates(data: Any) -> Iterable[str]:
    if isinstance(data, dict):
        if _is_non_output_metadata(data):
            return
        choices = data.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if isinstance(message, dict):
                    yield from _iter_text_from_content(message.get("content"))
                delta = choice.get("delta")
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    yield delta["content"]
                if isinstance(choice.get("text"), str):
                    yield choice["text"]

        text_keys = (
            "answerText",
            "system_text",
            "answer",
            "content",
            "text",
            "response",
            "result",
        )
        for key in text_keys:
            value = data.get(key)
            if isinstance(value, str):
                yield value

        skip_keys = {
            "variables",
            "newVariables",
            "inputs",
            "input",
            "request",
            "messages",
            "historyPreview",
            "history",
            "chatHistory",
            "reasoningText",
            "reasoning_text",
            "system_error_text",
            "systemErrorText",
            "quoteList",
            "obj",
            "value",
        }
        priority_keys = ("responseData", "pluginOutput", "output", "outputs", "data")
        for key in priority_keys:
            if key in data:
                yield from _iter_answer_text_candidates(data[key])
        for key, value in data.items():
            if key not in skip_keys and key not in priority_keys and key not in text_keys:
                yield from _iter_answer_text_candidates(value)

    elif isinstance(data, list):
        for item in data:
            yield from _iter_answer_text_candidates(item)


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


def _extract_legacy_alias_payload(
    candidate: Any,
    contract: FastGPTStageContract,
) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    aliases = LEGACY_OUTPUT_ALIASES.get(contract.stage_name, {})
    if not aliases:
        return None

    payload: dict[str, Any] = {}
    for expected_name in contract.output_names:
        if expected_name in candidate:
            payload[expected_name] = candidate[expected_name]
            continue
        for alias in aliases.get(expected_name, ()):
            if alias in candidate:
                payload[expected_name] = candidate[alias]
                break
        if expected_name not in payload:
            return None
    return payload
