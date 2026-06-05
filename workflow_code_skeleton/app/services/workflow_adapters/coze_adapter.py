from __future__ import annotations

from typing import Any

from ..coze_workflow_client import CozeWorkflowClient, coze_workflow_client


class CozeWorkflowAdapter:
    name = "coze"

    def __init__(self, client: CozeWorkflowClient | None = None) -> None:
        self.client = client or coze_workflow_client

    def run_stage(
        self,
        stage_key: str,
        variables: dict[str, Any] | None = None,
        extra_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.client.run_stage(stage_key, variables or {}, extra_parameters)

    def backend_ready(self, stage_key: str | None = None) -> bool:
        try:
            if stage_key:
                return bool(self.client.workflow_id_for_stage(stage_key))
            stages = self.client.config.get("stages")
            if not isinstance(stages, dict):
                return False
            return any(self.client.workflow_id_for_stage(str(key)) for key in stages)
        except Exception:
            return False

    def diagnostics(self, stage_key: str | None = None) -> dict[str, Any]:
        workflow_id = ""
        if stage_key:
            try:
                workflow_id = self.client.workflow_id_for_stage(stage_key)
            except Exception:
                workflow_id = ""
        return {
            "ok": True,
            "backend": self.name,
            "stage_key": stage_key or "",
            "workflow_id": workflow_id,
            "has_workflow_id": bool(workflow_id),
            "config_path": str(self.client.config_path),
            "dry_run": bool(self.client.dry_run),
            "token_env": self.client.token_env,
            "base_url_env": self.client.base_url_env,
            "timeout_seconds": self.client.timeout_seconds,
        }

