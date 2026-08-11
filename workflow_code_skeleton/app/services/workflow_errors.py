from __future__ import annotations

from typing import Any, Iterable


class WorkflowTransientError(RuntimeError):
    """A retryable Tencent workflow HTTP or upstream failure."""

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


class WorkflowStageFormatError(ValueError):
    """The HTTP call succeeded, but no consumable stage output was found."""

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
        preview = " ".join(self.response_preview.split())
        if len(preview) > 500:
            preview = f"{preview[:500]}..."
        super().__init__(
            f"腾讯工作流阶段 {stage_name} 未识别到可消费的契约输出，"
            f"期望字段：{', '.join(self.expected_fields)}；"
            f"{self.failure_reason or '没有发现可映射到阶段契约的候选输出'}；"
            f"实际返回内容：{preview}"
        )


class WorkflowPayloadTooLargeError(RuntimeError):
    """The locally assembled workflow request exceeds its configured hard limit."""

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
            f"腾讯工作流阶段 {stage_name} 请求体过大：{body_chars} chars，"
            f"超过硬限制 {hard_limit} chars；最大变量：{largest_desc}。"
        )
