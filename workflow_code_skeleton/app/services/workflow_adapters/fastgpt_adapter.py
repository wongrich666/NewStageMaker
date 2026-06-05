from __future__ import annotations

import os
from typing import Any

from ..fastgpt_client import fastgpt_client


class FastGPTWorkflowAdapter:
    name = "fastgpt"

    def run_stage(
        self,
        stage_key: str,
        variables: dict[str, Any] | None = None,
        extra_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(variables or {})
        if extra_parameters:
            payload.update(extra_parameters)
        return fastgpt_client.run_stage(stage_key, payload)

    def backend_ready(self, stage_key: str | None = None) -> bool:
        if os.getenv("FASTGPT_API_KEY"):
            return True
        if not stage_key:
            return any(key.startswith("FASTGPT_") and key.endswith("_API_KEY") and value for key, value in os.environ.items())
        normalized = str(stage_key or "").strip().upper().replace("-", "_")
        candidates = (
            f"FASTGPT_{normalized}_API_KEY",
            f"{normalized}_API_KEY",
            "FASTGPT_API_KEY",
        )
        return any(os.getenv(name) for name in candidates)

    def diagnostics(self, stage_key: str | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "backend": self.name,
            "stage_key": stage_key or "",
            "has_api_key": self.backend_ready(stage_key),
        }

