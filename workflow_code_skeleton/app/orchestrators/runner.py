from __future__ import annotations

from pathlib import Path

from ..config import ModelOption
from ..models.inputs import WorkflowInput
from ..models.state import WorkflowState
from .fastgpt_hybrid_workflow import run_fastgpt_hybrid_workflow


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
        from ..services.coze_client import CozeWorkflowClient

        client = CozeWorkflowClient()
    return run_fastgpt_hybrid_workflow(
        payload,
        workflow_spec_path=workflow_spec_path,
        runtime=runtime,
        model_option=model_option,
        client=client,
        resume_snapshot=resume_snapshot,
    )
