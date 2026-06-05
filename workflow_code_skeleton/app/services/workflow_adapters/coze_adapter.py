from __future__ import annotations

import os
from typing import Any

from ..coze_workflow_client import CozeWorkflowClient, coze_workflow_client, _resolve_coze_base_url_info


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
        workflow_info: dict[str, Any] = {}
        base_url = ""
        base_url_source = ""
        try:
            base_url, base_url_source = _resolve_coze_base_url_info(
                os.getenv(self.client.base_url_env),
                self.client.base_url_env,
            )
        except Exception as exc:
            base_url = f"invalid: {exc}"
            base_url_source = self.client.base_url_env
        if stage_key:
            try:
                workflow_info = self.client.workflow_id_info_for_stage(stage_key)
                workflow_id = str(workflow_info.get("workflow_id") or "")
            except Exception:
                workflow_id = ""
        return {
            "ok": True,
            "backend": self.name,
            "stage_key": stage_key or "",
            "normalized_stage_key": workflow_info.get("normalized_stage_key") or stage_key or "",
            "workflow_id": workflow_id,
            "has_workflow_id": bool(workflow_id),
            "workflow_id_source": workflow_info.get("workflow_id_source") or "",
            "config_path": str(self.client.config_path),
            "resource_path": workflow_info.get("resource_path") or "",
            "inner_yaml_path": workflow_info.get("inner_yaml_path") or "",
            "dry_run": bool(self.client.dry_run),
            "token_env": self.client.token_env,
            "token_status": "SET" if os.getenv(self.client.token_env) else "EMPTY",
            "base_url_env": self.client.base_url_env,
            "base_url_status": "SET" if os.getenv(self.client.base_url_env) else "EMPTY",
            "base_url": base_url,
            "base_url_source": base_url_source,
            "workflow_id_status": "SET" if workflow_id else "EMPTY",
            "timeout_seconds": self.client.timeout_seconds,
        }

