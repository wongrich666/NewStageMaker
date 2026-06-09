from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from ..config import settings
from .workflow_output_normalizer import normalize_stage_output


DEFAULT_WORKFLOW_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "workflows.yaml"



def _workflow_stage_debug_artifact(event, local_vars=None, exc=None):
    """Write request/success/error debug artifacts for framework-to-script stages 08-12."""
    try:
        from pathlib import Path
        from datetime import datetime, timezone
        import json
        import traceback
        import re

        local_vars = dict(local_vars or {})
        stage = (
            local_vars.get("resolved_stage_key")
            or local_vars.get("stage_key")
            or local_vars.get("stage_name")
            or local_vars.get("backend_stage_key")
            or ""
        )
        stage = str(stage or "")
        stage_lower = stage.lower()

        nums = re.findall(r"\d+", stage_lower)
        should_log = False
        if nums:
            try:
                n = int(nums[0])
                should_log = 8 <= n <= 12
            except Exception:
                should_log = False
        if not should_log and not any(x in stage_lower for x in ("stage_08", "stage_09", "stage_10", "stage_11", "stage_12")):
            return

        def safe(value, depth=0):
            if depth > 5:
                return f"<max_depth type={type(value).__name__}>"
            if value is None or isinstance(value, (bool, int, float)):
                return value
            if isinstance(value, str):
                return value if len(value) <= 3000 else value[:3000] + f"...<truncated len={len(value)}>"
            if isinstance(value, (list, tuple)):
                return [safe(v, depth + 1) for v in list(value)[:60]]
            if isinstance(value, dict):
                out = {}
                for idx, (k, v) in enumerate(value.items()):
                    if idx >= 120:
                        out["<truncated>"] = f"dict_len={len(value)}"
                        break
                    ks = str(k)
                    if any(token in ks.upper() for token in ("TOKEN", "KEY", "SECRET", "AUTH", "PASSWORD")):
                        out[ks] = "<REDACTED>"
                    else:
                        out[ks] = safe(v, depth + 1)
                return out
            return repr(value)[:3000]

        keep = {
            "stage_key",
            "stage_name",
            "resolved_stage_key",
            "backend",
            "workflow_backend",
            "variables",
            "extra_parameters",
            "parameters",
            "result",
            "adapter",
        }

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "stage": stage,
            "locals": {},
        }

        for k, v in local_vars.items():
            if k in keep:
                if k == "adapter":
                    record["locals"][k] = type(v).__name__
                else:
                    record["locals"][k] = safe(v)

        if exc is not None:
            record["exception"] = {
                "type": type(exc).__name__,
                "message": str(exc),
                "repr": repr(exc),
                "traceback": traceback.format_exc(),
            }

        stage_dir_name = stage or "unknown_stage"
        stage_dir_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", stage_dir_name)
        debug_dir = Path.cwd() / "cache" / "workflow_stage_debug" / stage_dir_name
        debug_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        payload = json.dumps(record, ensure_ascii=False, indent=2)
        out = debug_dir / f"{stamp}_{event}.json"
        out.write_text(payload, encoding="utf-8")
        (debug_dir / f"latest_{event}.json").write_text(payload, encoding="utf-8")
        (debug_dir / "latest.json").write_text(payload, encoding="utf-8")
        print(f"[workflow_stage_debug] wrote {out}")
    except Exception as debug_exc:
        print(f"[workflow_stage_debug] failed: {debug_exc}")


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
    return str(os.getenv("WORKFLOW_BACKEND") or getattr(settings, "workflow_backend", "") or "coze").strip().lower() or "coze"


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
        _workflow_stage_debug_artifact("request", locals())
        result = adapter.run_stage(resolved_stage_key, variables or {}, extra_parameters)
        _workflow_stage_debug_artifact("success", locals())
    except WorkflowRunnerError:
        raise
    except Exception as exc:
        _workflow_stage_debug_artifact("error", locals(), exc)
        nested_detail = getattr(exc, "detail", None)
        detail = {
            "backend_stage_key": resolved_stage_key,
            "reason": str(exc),
            "original_exception_type": type(exc).__name__,
            "original_exception_message": str(exc),
        }
        if isinstance(nested_detail, dict):
            detail.update(nested_detail)
        raise WorkflowRunnerError(
            f"Workflow backend request failed: {type(exc).__name__}: {exc}",
            backend=backend,
            stage_key=stage_key,
            detail=detail,
        ) from exc
    normalized = normalize_stage_output(
        stage_key,
        result,
        payload=variables or {},
        backend=backend,
        backend_stage_key=resolved_stage_key,
    )
    normalized.setdefault("backend", backend)
    normalized.setdefault("stage_key", stage_key)
    normalized.setdefault("backend_stage_key", resolved_stage_key)
    return normalized


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

