from __future__ import annotations

import os
from typing import Any

from ..coze_workflow_client import CozeWorkflowClient, coze_workflow_client, _resolve_coze_base_url_info
from ..workflow_output_normalizer import OUTPUT_FORMAT_INSTRUCTION, normalize_stage_output


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
        parameters = dict(extra_parameters or {})
        parameters.setdefault("workflow_output_format_instruction", OUTPUT_FORMAT_INSTRUCTION)
        raw_result = self.client.run_stage(stage_key, variables or {}, parameters)
        return normalize_stage_output(stage_key, raw_result, payload=variables or {}, backend=self.name, backend_stage_key=stage_key)

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
        credentials = self.client.credentials_diagnostics()
        first_credential = credentials[0] if credentials else {}
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
            "token_env": first_credential.get("token_env") or self.client.token_env,
            "legacy_token_env": self.client.token_env,
            "token_status": first_credential.get("token_status") or ("SET" if os.getenv(self.client.token_env) else "EMPTY"),
            "token_prefix": first_credential.get("token_prefix") or "",
            "token_len": first_credential.get("token_len") or 0,
            "token_expires_at": first_credential.get("token_expires_at") or "",
            "token_days_left": first_credential.get("token_days_left"),
            "credential_name": first_credential.get("credential_name") or "",
            "credential_attempt_order": [item.get("credential_name") for item in credentials],
            "credential_order_env": os.getenv("COZE_CREDENTIALS_ORDER") or "",
            "credentials": credentials,
            "base_url_env": first_credential.get("base_url_env") or self.client.base_url_env,
            "legacy_base_url_env": self.client.base_url_env,
            "base_url_status": "SET" if first_credential.get("base_url") else "EMPTY",
            "base_url": first_credential.get("base_url") or base_url,
            "base_url_source": first_credential.get("base_url_source") or base_url_source,
            "workflow_id_status": "SET" if workflow_id else "EMPTY",
            "timeout_seconds": self.client.timeout_seconds,
        }

