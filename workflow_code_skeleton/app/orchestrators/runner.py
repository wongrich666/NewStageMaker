from __future__ import annotations

from pathlib import Path

from ..config import ModelOption
from ..models.inputs import WorkflowInput
from ..models.state import WorkflowState
from .workflow_orchestrator import run_workflow_orchestrator


def run_configured_workflow(
    payload: WorkflowInput,
    *,
    workflow_spec_path: str | Path,
    runtime=None,
    model_option: ModelOption | None = None,
    resume_snapshot: dict | None = None,
    client=None,
) -> WorkflowState:
    if client is None:
        from ..services.tencent_workflow_client import TencentWorkflowClient

        client = TencentWorkflowClient()
    return run_workflow_orchestrator(
        payload,
        workflow_spec_path=workflow_spec_path,
        runtime=runtime,
        model_option=model_option,
        client=client,
        resume_snapshot=resume_snapshot,
    )
