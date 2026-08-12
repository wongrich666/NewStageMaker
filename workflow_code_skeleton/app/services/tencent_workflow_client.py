from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Iterable

import requests

from ..utils.logger import get_logger
from .workflow_contracts import contract_for
from .workflow_errors import WorkflowStageFormatError, WorkflowTransientError
from .tencent_workflow_registry import (
    api_key_for,
    api_url_for,
    build_workflow_inputs,
    http_retries,
    retry_delay_seconds,
    timeout_seconds,
    workflow_spec,
)
from .workflow_output_parser import (
    parse_workflow_output,
    safe_truncated_preview,
    wrap_payload_for_expected_output,
)

logger = get_logger("tencent_workflow_client")

RETRYABLE_HTTP_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}
EMPTY_VALUES = (None, "", [], {})


class TencentWorkflowClient:
    """Run one published Tencent ADP application for each workflow stage."""

    def __init__(self) -> None:
        self._last_stage_debug_info: dict[str, dict[str, Any]] = {}
        self._debug_local = threading.local()

    def run_stage(self, stage_name: str, variables: dict[str, Any]) -> dict[str, Any]:
        spec = workflow_spec(stage_name)
        contract = contract_for(stage_name)
        contract.build_input_payload(variables)

        api_key_env, api_key = api_key_for(stage_name)
        if not api_key:
            raise ValueError(
                f"{spec.label} 尚未配置 API Key，请在 workflow_code_skeleton/.env "
                f"中填写 {api_key_env}。"
            )
        url_source, url = api_url_for(stage_name)
        workflow_inputs = build_workflow_inputs(stage_name, variables)
        request_id = uuid.uuid4().hex
        body = _build_request_body(
            url=url,
            spec=spec,
            api_key=api_key,
            workflow_inputs=workflow_inputs,
            request_id=request_id,
        )
        headers = {"Content-Type": "application/json"}

        self._remember_stage_debug_info(
            stage_name,
            status="requesting",
            workflow_key=spec.key,
            workflow_id=spec.workflow_id,
            api_key_env=api_key_env,
            api_key_present=True,
            api_url=url,
            api_url_source=url_source,
            input_keys=sorted(workflow_inputs),
            input_char_lengths={
                key: len(str(value))
                for key, value in workflow_inputs.items()
            },
            input_types={key: type(value).__name__ for key, value in workflow_inputs.items()},
            request_id=request_id,
        )
        response = self._post_with_retries(
            stage_name=stage_name,
            url=url,
            headers=headers,
            body=body,
        )
        try:
            raw_response = _response_payload(response)
        except Exception as exc:
            self._remember_stage_debug_info(
                stage_name,
                status="response_parse_error",
                http_status=getattr(response, "status_code", None),
                response_preview=safe_truncated_preview(_response_text(response), limit=2000),
                exception_type=type(exc).__name__,
                last_failure_reason=str(exc),
            )
            raise
        error_message = _tencent_error_message(raw_response)
        if error_message:
            self._remember_stage_debug_info(
                stage_name,
                status="error_response",
                response_preview=safe_truncated_preview(raw_response, limit=1600),
                last_failure_reason=error_message,
            )
            raise RuntimeError(f"{spec.label} 返回错误：{error_message}")

        output, candidate_sources = _extract_contract_output(
            raw_response,
            contract=contract,
            response_fields=spec.response_fields,
        )
        try:
            validated = contract.validate_output_payload(output)
        except ValueError as exc:
            matched_fields = [
                name
                for name in contract.output_names
                if isinstance(output, dict) and name in output
            ]
            missing_fields = [
                name for name in contract.output_names if name not in matched_fields
            ]
            response_preview = safe_truncated_preview(raw_response, limit=1800)
            self._remember_stage_debug_info(
                stage_name,
                status="contract_validation_failed",
                candidate_sources=candidate_sources,
                matched_fields=matched_fields,
                missing_fields=missing_fields,
                response_preview=response_preview,
                raw_response=raw_response,
                last_failure_reason=str(exc),
            )
            raise WorkflowStageFormatError(
                stage_name=stage_name,
                expected_fields=contract.output_names,
                failure_reason=str(exc),
                candidate_sources=candidate_sources,
                matched_fields=matched_fields,
                missing_fields=missing_fields,
                response_preview=response_preview,
                raw_output_source="tencent_adp",
            ) from exc

        self._remember_stage_debug_info(
            stage_name,
            status="validated",
            candidate_sources=candidate_sources,
            output_keys=sorted(validated),
            response_preview=safe_truncated_preview(raw_response, limit=1200),
            raw_response=raw_response,
            last_failure_reason="",
        )
        return validated

    def run_raw(self, stage_name: str, variables: dict[str, Any]) -> Any:
        """Run a 01-07 planning workflow and return its unwrapped business payload."""
        spec = workflow_spec(stage_name)
        api_key_env, api_key = api_key_for(stage_name)
        if not api_key:
            raise ValueError(
                f"{spec.label} 尚未配置 API Key，请在 workflow_code_skeleton/.env "
                f"中填写 {api_key_env}。"
            )
        url_source, url = api_url_for(stage_name)
        workflow_inputs = build_workflow_inputs(stage_name, variables)
        request_id = uuid.uuid4().hex
        body = _build_request_body(
            url=url,
            spec=spec,
            api_key=api_key,
            workflow_inputs=workflow_inputs,
            request_id=request_id,
        )
        self._remember_stage_debug_info(
            stage_name,
            status="requesting",
            workflow_key=spec.key,
            workflow_id=spec.workflow_id,
            api_key_env=api_key_env,
            api_key_present=True,
            api_url=url,
            api_url_source=url_source,
            input_keys=sorted(workflow_inputs),
            input_char_lengths={
                key: len(str(value))
                for key, value in workflow_inputs.items()
            },
            input_types={key: type(value).__name__ for key, value in workflow_inputs.items()},
            request_id=request_id,
        )
        response = self._post_with_retries(
            stage_name=stage_name,
            url=url,
            headers={"Content-Type": "application/json"},
            body=body,
        )
        try:
            raw_response = _response_payload(response)
        except Exception as exc:
            self._remember_stage_debug_info(
                stage_name,
                status="response_parse_error",
                http_status=getattr(response, "status_code", None),
                response_preview=safe_truncated_preview(_response_text(response), limit=2000),
                exception_type=type(exc).__name__,
                last_failure_reason=str(exc),
            )
            raise
        error_message = _tencent_error_message(raw_response)
        if error_message:
            self._remember_stage_debug_info(
                stage_name,
                status="error_response",
                response_preview=safe_truncated_preview(raw_response, limit=1600),
                raw_response=raw_response,
                last_failure_reason=error_message,
            )
            raise RuntimeError(f"{spec.label} 返回错误：{error_message}")
        selected, candidate_sources = _select_response_payload(
            raw_response,
            response_fields=spec.response_fields,
        )
        self._remember_stage_debug_info(
            stage_name,
            status="response_received",
            candidate_sources=candidate_sources,
            response_preview=safe_truncated_preview(raw_response, limit=1200),
            raw_response=raw_response,
        )
        return selected

    def get_last_stage_debug_info(self, stage_name: str) -> dict[str, Any]:
        stage = str(stage_name)
        thread_map = getattr(self._debug_local, "stages", {})
        if isinstance(thread_map, dict) and isinstance(thread_map.get(stage), dict):
            return dict(thread_map[stage])
        return dict(self._last_stage_debug_info.get(stage, {}))

    def _remember_stage_debug_info(self, stage_name: str, **updates: Any) -> None:
        stage = str(stage_name)
        thread_map = getattr(self._debug_local, "stages", None)
        if not isinstance(thread_map, dict):
            thread_map = {}
            self._debug_local.stages = thread_map
        current = (
            {}
            if updates.get("status") == "requesting"
            else dict(thread_map.get(stage) or self._last_stage_debug_info.get(stage, {}))
        )
        current.update(updates)
        thread_map[stage] = current
        self._last_stage_debug_info[stage] = current

    def _post_with_retries(
        self,
        *,
        stage_name: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> requests.Response:
        attempts = max(1, http_retries() + 1)
        delay = retry_delay_seconds()
        timeout = max(1, timeout_seconds())
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            started_at = time.monotonic()
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=timeout,
                )
            except (
                requests.Timeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                last_error = exc
                logger.warning(
                    "腾讯工作流请求失败 stage=%s attempt=%s/%s elapsed=%.3fs error=%s",
                    stage_name,
                    attempt,
                    attempts,
                    time.monotonic() - started_at,
                    exc,
                )
                self._remember_stage_debug_info(
                    stage_name,
                    status="transport_error",
                    http_attempt=attempt,
                    http_attempts=attempts,
                    elapsed_seconds=round(time.monotonic() - started_at, 3),
                    exception_type=type(exc).__name__,
                    last_failure_reason=str(exc),
                )
                if attempt >= attempts:
                    raise WorkflowTransientError(
                        f"腾讯工作流阶段 {stage_name} 请求失败：{exc}",
                        stage_name=stage_name,
                        url=url,
                    ) from exc
                time.sleep(delay * attempt)
                continue
            except requests.RequestException as exc:
                self._remember_stage_debug_info(
                    stage_name,
                    status="request_exception",
                    http_attempt=attempt,
                    http_attempts=attempts,
                    elapsed_seconds=round(time.monotonic() - started_at, 3),
                    exception_type=type(exc).__name__,
                    last_failure_reason=str(exc),
                )
                raise RuntimeError(f"腾讯工作流阶段 {stage_name} 请求异常：{exc}") from exc

            if response.status_code in RETRYABLE_HTTP_STATUSES and attempt < attempts:
                self._remember_stage_debug_info(
                    stage_name,
                    status="retryable_http_error",
                    http_status=response.status_code,
                    http_attempt=attempt,
                    http_attempts=attempts,
                    elapsed_seconds=round(time.monotonic() - started_at, 3),
                    response_preview=safe_truncated_preview(_response_text(response), limit=1600),
                    last_failure_reason=f"HTTP {response.status_code}",
                )
                time.sleep(delay * attempt)
                continue
            if response.status_code >= 400:
                preview = safe_truncated_preview(_response_text(response), limit=1600)
                self._remember_stage_debug_info(
                    stage_name,
                    status="http_error",
                    http_status=response.status_code,
                    http_attempt=attempt,
                    http_attempts=attempts,
                    elapsed_seconds=round(time.monotonic() - started_at, 3),
                    response_preview=preview,
                    last_failure_reason=f"HTTP {response.status_code}: {preview}",
                )
                if response.status_code in RETRYABLE_HTTP_STATUSES:
                    raise WorkflowTransientError(
                        f"腾讯工作流阶段 {stage_name} 返回 HTTP {response.status_code}",
                        stage_name=stage_name,
                        status_code=response.status_code,
                        url=url,
                        response_text=preview,
                    )
                raise RuntimeError(
                    f"腾讯工作流阶段 {stage_name} 返回 HTTP {response.status_code}：{preview}"
                )
            return response

        raise WorkflowTransientError(
            f"腾讯工作流阶段 {stage_name} 请求失败：{last_error}",
            stage_name=stage_name,
            url=url,
        )


def _trigger_text() -> str:
    return str(os.getenv("TENCENT_WORKFLOW_TRIGGER_TEXT") or "执行工作流").strip() or "执行工作流"


def _visitor_id() -> str:
    configured = str(os.getenv("TENCENT_WORKFLOW_VISITOR_ID") or "").strip()
    if configured:
        return configured[:64]
    return "idea-to-scripts"


def _build_request_body(
    *,
    url: str,
    spec: Any,
    api_key: str,
    workflow_inputs: dict[str, Any],
    request_id: str,
) -> dict[str, Any]:
    if "/adp/v2/chat" in str(url or "").lower():
        contents: list[dict[str, Any]] = [
            {
                "Type": "text",
                "Text": _trigger_text(),
            }
        ]
        body: dict[str, Any] = {
            "RequestId": request_id,
            "ConversationId": uuid.uuid4().hex,
            "AppKey": api_key,
            "VisitorId": _visitor_id(),
            "Contents": contents,
            "Incremental": False,
            "SearchNetwork": "disable",
            "Stream": "disable",
            "WorkflowStatus": "enable",
        }

        # 腾讯公有云把应用自定义变量放在 Contents[].CustomVariables。
        # 省赛私有部署则要求工作流开始节点参数放在顶层 WorkflowInput；
        # 如果仍使用 custom_variables，请求可以成功，但开始节点只会读取默认值。
        input_mode = str(
            os.getenv("TENCENT_WORKFLOW_V2_INPUT_MODE") or "custom_variables"
        ).strip().lower()
        if input_mode in {"workflow_input", "workflowinput", "workflow"}:
            body["WorkflowInput"] = workflow_inputs
        else:
            contents.append(
                {
                    "Type": "custom_variables",
                    "CustomVariables": workflow_inputs,
                }
            )
        return body

    # 兼容腾讯旧版地址或控制台给出的旧协议阶段 URL。
    return {
        "request_id": request_id,
        "session_id": f"wf-{spec.key.replace('_', '-')}-{request_id[:24]}",
        "bot_app_key": api_key,
        "visitor_biz_id": _visitor_id(),
        "content": _trigger_text(),
        "incremental": False,
        "custom_variables": workflow_inputs,
        "search_network": "disable",
        "stream": "disable",
    }


def _response_payload(response: requests.Response) -> Any:
    text = _response_text(response).strip()
    content_type = str(getattr(response, "headers", {}).get("Content-Type") or "").lower()
    if "text/event-stream" in content_type or _looks_like_sse(text):
        return _parse_sse(text)
    try:
        return response.json()
    except ValueError:
        parsed = parse_workflow_output(text)
        if parsed in EMPTY_VALUES:
            raise RuntimeError("腾讯工作流返回空响应。")
        return parsed


def _response_text(response: requests.Response) -> str:
    """Decode Tencent SSE/JSON as UTF-8 even when the header omits charset.

    requests defaults ``text/event-stream`` without a charset to ISO-8859-1,
    which turns messages such as “应用密钥无效” into mojibake.
    """
    content = getattr(response, "content", None)
    if isinstance(content, bytes) and content:
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError:
            encoding = str(
                getattr(response, "apparent_encoding", None)
                or getattr(response, "encoding", None)
                or "utf-8"
            )
            return content.decode(encoding, errors="replace")
    return str(getattr(response, "text", "") or "")


def _looks_like_sse(text: str) -> bool:
    stripped = str(text or "").lstrip()
    return stripped.startswith("event:") or stripped.startswith("data:")


def _parse_sse(text: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    event_name = ""
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal event_name, data_lines
        if not event_name and not data_lines:
            return
        raw_data = "\n".join(data_lines).strip()
        parsed_data = parse_workflow_output(raw_data) if raw_data else ""
        events.append({"event": event_name or "message", "data": parsed_data})
        event_name = ""
        data_lines = []

    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            flush()
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    flush()

    reply_events = [
        item
        for item in events
        if item.get("event") == "reply" and item.get("data") not in EMPTY_VALUES
    ]
    final_replies = [
        item
        for item in reply_events
        if isinstance(item.get("data"), dict) and item["data"].get("is_final") is True
    ]
    selected = final_replies or reply_events
    if selected:
        return {
            "events": events,
            "reply": selected[-1].get("data"),
        }

    v2_message_text = ""
    v2_completed_text = ""
    v2_workflow_output: Any = ""
    delta_text = ""
    replacement_text = ""
    for item in events:
        event = str(item.get("event") or "")
        data = item.get("data")
        if event == "message.done":
            v2_message_text = _v2_message_text(data) or v2_message_text
        elif event == "response.completed":
            v2_workflow_output = _v2_workflow_result(data) or v2_workflow_output
            v2_completed_text = _v2_response_text(data) or v2_completed_text
        elif event == "text.delta" and isinstance(data, dict):
            delta_text += str(data.get("Text") or data.get("text") or "")
        elif event == "text.replace" and isinstance(data, dict):
            replacement_text = str(data.get("Text") or data.get("text") or "")

    final_payload = (
        v2_workflow_output
        or v2_message_text
        or v2_completed_text
        or replacement_text
        or delta_text
    )
    if final_payload:
        return {
            "events": events,
            "reply": parse_workflow_output(final_payload),
        }

    non_done_events = [
        item
        for item in events
        if item.get("event") != "done" and item.get("data") not in ("[DONE]", None, "")
    ]
    selected = non_done_events or events
    return {
        "events": events,
        "reply": selected[-1].get("data") if selected else "",
    }


def _v2_message_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    message = data.get("Message") or data.get("message") or data
    if not isinstance(message, dict):
        return ""
    message_type = str(message.get("Type") or message.get("type") or "").lower()
    if message_type and message_type != "reply":
        return ""
    return _v2_contents_text(message.get("Contents") or message.get("contents"))


def _v2_response_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    response = data.get("Response") or data.get("response") or data
    if not isinstance(response, dict):
        return ""
    messages = response.get("Messages") or response.get("messages") or []
    for message in reversed(messages if isinstance(messages, list) else []):
        if not isinstance(message, dict):
            continue
        message_type = str(message.get("Type") or message.get("type") or "").lower()
        if message_type and message_type != "reply":
            continue
        text = _v2_contents_text(message.get("Contents") or message.get("contents"))
        if text:
            return text
    return ""


def _v2_workflow_result(data: Any) -> Any:
    """Return the final END-node output from private-deployment v2 responses."""
    if not isinstance(data, dict):
        return ""
    response = data.get("Response") or data.get("response") or data
    if not isinstance(response, dict):
        return ""
    procedures = response.get("Procedures") or response.get("procedures") or []
    if not isinstance(procedures, list):
        return ""

    for procedure in reversed(procedures):
        if not isinstance(procedure, dict):
            continue
        workflow = procedure.get("Workflow") or procedure.get("workflow")
        if not isinstance(workflow, dict):
            continue

        outputs = workflow.get("Outputs") or workflow.get("outputs") or []
        if isinstance(outputs, list):
            non_empty_outputs = [item for item in outputs if item not in EMPTY_VALUES]
            if non_empty_outputs:
                return non_empty_outputs[-1]
        elif outputs not in EMPTY_VALUES:
            return outputs

        run_nodes = workflow.get("RunNodes") or workflow.get("run_nodes") or []
        if not isinstance(run_nodes, list):
            continue
        for node in reversed(run_nodes):
            if not isinstance(node, dict):
                continue
            node_type = node.get("NodeType")
            if node_type is None:
                node_type = node.get("node_type")
            node_name = str(node.get("NodeName") or node.get("node_name") or "")
            if node_type not in (16, "16") and node_name not in {"结束", "END", "End"}:
                continue
            output = node.get("Output")
            if output is None:
                output = node.get("output")
            if output not in EMPTY_VALUES:
                return output
    return ""


def _v2_contents_text(contents: Any) -> str:
    if not isinstance(contents, list):
        return ""
    texts: list[str] = []
    for content in contents:
        if not isinstance(content, dict):
            continue
        content_type = str(content.get("Type") or content.get("type") or "").lower()
        if content_type not in {"text", "json_text", ""}:
            continue
        value = content.get("Text")
        if value is None:
            value = content.get("text")
        if value not in (None, ""):
            if isinstance(value, (dict, list)):
                texts.append(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
            else:
                texts.append(str(value))
    return "".join(texts)


def _extract_contract_output(
    raw: Any,
    *,
    contract: Any,
    response_fields: tuple[str, ...],
) -> tuple[dict[str, Any], list[str]]:
    candidate_sources: list[str] = []
    last_candidate: Any = raw

    for source, candidate in _iter_candidates(raw, response_fields=response_fields):
        candidate_sources.append(source)
        parsed = _unwrap_response_envelope(
            candidate,
            response_fields=response_fields,
        )
        last_candidate = parsed
        normalized = wrap_payload_for_expected_output(
            parsed,
            output_names=contract.output_names,
            output_aliases=contract.output_aliases,
            output_types=contract.output_types,
            stage_name=contract.stage_name,
        )
        if not isinstance(normalized, dict):
            continue
        try:
            contract.validate_output_payload(normalized)
        except ValueError:
            continue
        return normalized, candidate_sources

    fallback = wrap_payload_for_expected_output(
        last_candidate,
        output_names=contract.output_names,
        output_aliases=contract.output_aliases,
        output_types=contract.output_types,
        stage_name=contract.stage_name,
    )
    if isinstance(fallback, dict):
        return fallback, candidate_sources
    return {}, candidate_sources


def _unwrap_response_envelope(
    candidate: Any,
    *,
    response_fields: tuple[str, ...],
) -> Any:
    parsed = parse_workflow_output(candidate)
    for _ in range(8):
        if not isinstance(parsed, dict):
            return parsed
        if "Output" in parsed:
            parsed = parse_workflow_output(parsed["Output"])
            continue
        selected = False
        for field in response_fields:
            if field in parsed:
                parsed = parse_workflow_output(parsed[field])
                selected = True
                break
        if selected:
            continue
        wrapper_keys = ("reply", "content", "data", "result", "response", "message", "answer", "text")
        non_empty = [key for key in wrapper_keys if parsed.get(key) not in EMPTY_VALUES]
        if len(non_empty) == 1 and set(parsed).issubset(
            {*wrapper_keys, "event", "is_final", "request_id", "session_id"}
        ):
            parsed = parse_workflow_output(parsed[non_empty[0]])
            continue
        return parsed
    return parsed


def _select_response_payload(
    raw: Any,
    *,
    response_fields: tuple[str, ...],
) -> tuple[Any, list[str]]:
    sources: list[str] = []
    fallback: Any = parse_workflow_output(raw)
    for source, candidate in _iter_candidates(raw, response_fields=response_fields):
        sources.append(source)
        parsed = parse_workflow_output(candidate)
        if parsed not in EMPTY_VALUES:
            fallback = parsed
        if source.rsplit(".", 1)[-1] in set(response_fields):
            return parsed, sources
        if isinstance(parsed, dict) and any(
            field in parsed for field in response_fields
        ):
            for field in response_fields:
                if field in parsed:
                    return parse_workflow_output(parsed[field]), sources
    return fallback, sources


def _iter_candidates(
    raw: Any,
    *,
    response_fields: tuple[str, ...],
    max_depth: int = 10,
) -> Iterable[tuple[str, Any]]:
    seen: set[int] = set()
    preferred_keys = (
        *response_fields,
        "Output",
        "output",
        "reply",
        "content",
        "data",
        "result",
        "response",
        "message",
        "answer",
        "text",
    )

    def visit(value: Any, source: str, depth: int) -> Iterable[tuple[str, Any]]:
        if depth > max_depth:
            return
        if isinstance(value, (dict, list)):
            identity = id(value)
            if identity in seen:
                return
            seen.add(identity)
        yield source, value

        if isinstance(value, str):
            parsed = parse_workflow_output(value)
            if parsed is not value and parsed != value:
                yield from visit(parsed, f"{source}.json", depth + 1)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                yield from visit(item, f"{source}[{index}]", depth + 1)
            return
        if not isinstance(value, dict):
            return

        visited_keys: set[str] = set()
        for key in preferred_keys:
            if key in value:
                visited_keys.add(key)
                yield from visit(value[key], f"{source}.{key}", depth + 1)
        for key, nested in value.items():
            key_text = str(key)
            if key_text in visited_keys:
                continue
            yield from visit(nested, f"{source}.{key_text}", depth + 1)

    yield from visit(raw, "response", 0)


def _tencent_error_message(raw: Any) -> str:
    for source, candidate in _iter_candidates(raw, response_fields=()):
        if not isinstance(candidate, dict):
            continue
        event_name = str(candidate.get("event") or "").lower()
        if event_name == "error":
            return safe_truncated_preview(candidate.get("data") or candidate, limit=800)
        code = candidate.get("code")
        if code is None:
            code = candidate.get("Code")
        if code not in (None, 0, "0", 200, "200"):
            message = (
                candidate.get("message")
                or candidate.get("Message")
                or candidate.get("msg")
                or candidate.get("error")
                or candidate.get("Error")
                or candidate
            )
            return safe_truncated_preview(message, limit=800)
    return ""


tencent_workflow_client = TencentWorkflowClient()
