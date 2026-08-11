from __future__ import annotations

from typing import Any


class ToolExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 410,
        debug: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.debug = dict(debug or {})


def list_simple_tools() -> list[dict[str, Any]]:
    """The legacy standalone tools were removed; only the 18 stage APIs remain."""
    return []


def run_simple_tool(tool_key: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    del payload
    raise ToolExecutionError(
        "该独立工具已移除；当前系统只调用 01～12_04 的 18 个腾讯工作流。",
        status_code=410,
        debug={"tool_key": str(tool_key or "")},
    )
