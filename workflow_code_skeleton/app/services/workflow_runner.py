from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol


DEFAULT_WORKFLOW_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "workflows.yaml"


class WorkflowRunnerError(RuntimeError):
    def __init__(self, message: str, *, backend: str = "", stage_key: str = "", detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.backend = backend
        self.stage_key = stage_key
        self.detail = detail or {}


class WorkflowBackendAdapter(Protocol):
    name: str

    def run_stage(
        self,
        stage_key: str,
        variables: dict[str, Any] | None = None,
        extra_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...

    def backend_ready(self, stage_key: str | None = None) -> bool:
        ...

    def diagnostics(self, stage_key: str | None = None) -> dict[str, Any]:
        ...


@dataclass(frozen=True, slots=True)
class WorkflowStageConfig:
    key: str
    backend_stage_keys: dict[str, str]
    input_mapping: dict[str, str]
    output_mapping: dict[str, str]


def selected_workflow_backend() -> str:
    return str(os.getenv("WORKFLOW_BACKEND") or "fastgpt").strip().lower() or "fastgpt"


def _load_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"stages": {}}
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise WorkflowRunnerError(f"Workflow config must be JSON-compatible YAML or PyYAML must be installed: {path}") from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise WorkflowRunnerError(f"Workflow config must be an object: {path}")
    return data


@lru_cache(maxsize=4)
def load_workflow_config(config_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    env_path = os.getenv("WORKFLOW_CONFIG")
    path = Path(config_path or env_path or DEFAULT_WORKFLOW_CONFIG_PATH).resolve()
    return _load_config_file(path)


def stage_config(stage_key: str) -> WorkflowStageConfig:
    key = str(stage_key or "").strip()
    stages = load_workflow_config().get("stages")
    raw = stages.get(key) if isinstance(stages, dict) else None
    if not isinstance(raw, dict):
        return WorkflowStageConfig(key=key, backend_stage_keys={}, input_mapping={}, output_mapping={})
    backend_stage_keys = raw.get("backend_stage_keys")
    if not isinstance(backend_stage_keys, dict):
        backend_stage_keys = {}
    return WorkflowStageConfig(
        key=key,
        backend_stage_keys={str(k).lower(): str(v) for k, v in backend_stage_keys.items()},
        input_mapping={str(k): str(v) for k, v in (raw.get("input_mapping") or {}).items()},
        output_mapping={str(k): str(v) for k, v in (raw.get("output_mapping") or {}).items()},
    )


def _adapter_for_backend(backend: str) -> WorkflowBackendAdapter:
    normalized = str(backend or "").strip().lower()
    if normalized == "fastgpt":
        from .workflow_adapters.fastgpt_adapter import FastGPTWorkflowAdapter

        return FastGPTWorkflowAdapter()
    if normalized in {"coze", "volcengine", "volcano"}:
        from .workflow_adapters.coze_adapter import CozeWorkflowAdapter

        return CozeWorkflowAdapter()
    raise WorkflowRunnerError(
        f"Unsupported WORKFLOW_BACKEND: {backend}",
        backend=normalized,
        detail={"supported_backends": ["fastgpt", "coze"]},
    )


def backend_stage_key(stage_key: str, backend: str | None = None) -> str:
    selected = (backend or selected_workflow_backend()).strip().lower()
    config = stage_config(stage_key)
    return config.backend_stage_keys.get(selected) or config.backend_stage_keys.get("default") or str(stage_key)


def run_stage(
    stage_key: str,
    variables: dict[str, Any] | None = None,
    extra_parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    backend = selected_workflow_backend()
    adapter = _adapter_for_backend(backend)
    resolved_stage_key = backend_stage_key(stage_key, backend)
    try:
        result = adapter.run_stage(resolved_stage_key, variables or {}, extra_parameters)
    except WorkflowRunnerError:
        raise
    except Exception as exc:
        raise WorkflowRunnerError(
            f"Workflow backend request failed: {type(exc).__name__}: {exc}",
            backend=backend,
            stage_key=stage_key,
            detail={"backend_stage_key": resolved_stage_key, "reason": str(exc)},
        ) from exc
    if isinstance(result, dict):
        result.setdefault("backend", backend)
        result.setdefault("stage_key", stage_key)
        result.setdefault("backend_stage_key", resolved_stage_key)
    return result


def backend_ready(stage_key: str | None = None) -> bool:
    backend = selected_workflow_backend()
    adapter = _adapter_for_backend(backend)
    resolved = backend_stage_key(stage_key, backend) if stage_key else None
    return adapter.backend_ready(resolved)


def diagnostics(stage_key: str | None = None) -> dict[str, Any]:
    backend = selected_workflow_backend()
    adapter = _adapter_for_backend(backend)
    resolved = backend_stage_key(stage_key, backend) if stage_key else None
    payload = adapter.diagnostics(resolved)
    payload.setdefault("ok", True)
    payload["backend"] = backend
    payload["stage_key"] = stage_key or ""
    payload["backend_stage_key"] = resolved or ""
    return payload

