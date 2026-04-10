from __future__ import annotations

from pathlib import Path

from ..config import ModelOption, settings
from ..models.inputs import WorkflowInput
from ..models.state import WorkflowState
from .fastgpt_hybrid_workflow import run_fastgpt_hybrid_workflow
from .workflow import run_full_workflow


def run_configured_workflow(
    payload: WorkflowInput,
    *,
    workflow_spec_path: str | Path,
    runtime=None,
    model_option: ModelOption | None = None,
) -> WorkflowState:
    backend = settings.workflow_backend
    if backend in {"fastgpt", "hybrid", "fastgpt_hybrid"}:
        return run_fastgpt_hybrid_workflow(
            payload,
            workflow_spec_path=workflow_spec_path,
            runtime=runtime,
            model_option=model_option,
        )
    if backend in {"local", "json", "legacy"}:
        return run_full_workflow(
            payload,
            workflow_spec_path=workflow_spec_path,
            runtime=runtime,
            model_option=model_option,
        )
    raise ValueError(
        "WORKFLOW_BACKEND 只能是 fastgpt 或 local，"
        f"当前为：{settings.workflow_backend}"
    )
