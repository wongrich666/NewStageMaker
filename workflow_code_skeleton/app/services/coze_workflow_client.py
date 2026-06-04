from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "coze_workflows.yaml"


class CozeWorkflowError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage_key: str = "",
        workflow_id: str = "",
        error: Any = None,
    ) -> None:
        super().__init__(message)
        self.stage_key = stage_key
        self.workflow_id = workflow_id
        self.error = error


@dataclass(frozen=True, slots=True)
class CozeStageConfig:
    key: str
    name: str
    workflow_id: str
    workflow_id_env: str
    yaml_path: str
    input_mapping: dict[str, str]
    output_mapping: dict[str, str]
    output_fallbacks: tuple[str, ...]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_config_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except Exception as exc:  # pragma: no cover - only hit without JSON config
            raise CozeWorkflowError(
                f"Coze workflow config must be JSON-compatible YAML or PyYAML must be installed: {path}"
            ) from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise CozeWorkflowError(f"Coze workflow config must be an object: {path}")
    return data


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def _try_json_loads(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        return value


def _deep_find_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for nested in value.values():
            found = _deep_find_key(nested, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _deep_find_key(item, key)
            if found is not None:
                return found
    return None


def _first_text(value: Any, keys: tuple[str, ...]) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in keys:
            candidate = _deep_find_key(value, key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
            if isinstance(candidate, (dict, list)):
                return json.dumps(candidate, ensure_ascii=False)
    return ""


class CozeWorkflowClient:
    def __init__(self, config_path: str | os.PathLike[str] | None = None) -> None:
        env_config = os.getenv("COZE_WORKFLOW_CONFIG")
        self.config_path = Path(config_path or env_config or DEFAULT_CONFIG_PATH).resolve()
        self.config = _load_config_file(self.config_path)
        self.token_env = str(self.config.get("token_env") or "COZE_API_TOKEN")
        self.base_url_env = str(self.config.get("base_url_env") or "COZE_API_BASE")
        self.timeout_seconds = int(
            os.getenv(str(self.config.get("timeout_env") or "COZE_TIMEOUT_SECONDS"), "600") or "600"
        )
        self.dry_run = str(
            os.getenv(str(self.config.get("dry_run_env") or "COZE_DRY_RUN"), "0")
        ).strip() in {"1", "true", "TRUE", "yes", "on"}
        self._coze: Any = None

    def run_stage(
        self,
        stage_key: str,
        project_state: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
        stream: bool = True,
    ) -> dict[str, Any]:
        stage = self.stage_config(stage_key)
        built = self.build_parameters(stage.key, project_state or {}, parameters)
        return self.run_workflow_by_id(
            self.workflow_id_for_stage(stage.key),
            parameters=built,
            stream=stream,
            stage_key=stage.key,
        )

    def run_workflow_by_id(
        self,
        workflow_id: str,
        parameters: dict[str, Any] | None = None,
        stream: bool = True,
        stage_key: str = "",
    ) -> dict[str, Any]:
        safe_parameters = _jsonable(parameters or {})
        workflow_id = str(workflow_id or "").strip()
        if not workflow_id:
            raise CozeWorkflowError("Coze workflow_id is empty", stage_key=stage_key)
        if self.dry_run:
            raw = {
                "dry_run": True,
                "stage_key": stage_key,
                "workflow_id": workflow_id,
                "parameter_keys": sorted(safe_parameters.keys()),
            }
            return self.normalize_response(stage_key, workflow_id, raw)
        token = os.getenv(self.token_env)
        if not token:
            raise CozeWorkflowError(
                f"Missing {self.token_env}; set COZE_API_TOKEN or enable COZE_DRY_RUN=1",
                stage_key=stage_key,
                workflow_id=workflow_id,
            )

        coze = self._client()
        try:
            if stream:
                raw_events: list[Any] = []
                messages: list[str] = []
                from cozepy import WorkflowEventType

                for event in coze.workflows.runs.stream(
                    workflow_id=workflow_id,
                    parameters=safe_parameters,
                ):
                    raw_events.append(event)
                    event_type = getattr(event, "event", None) or getattr(event, "type", None)
                    data = getattr(event, "message", None) or getattr(event, "data", None) or event
                    if event_type == WorkflowEventType.MESSAGE:
                        text = _first_text(_event_to_jsonable(data), ("content", "answer", "message", "data"))
                        if text:
                            messages.append(text)
                    elif event_type == WorkflowEventType.ERROR:
                        raise CozeWorkflowError(
                            "Coze workflow returned ERROR event",
                            stage_key=stage_key,
                            workflow_id=workflow_id,
                            error=_event_to_jsonable(data),
                        )
                    elif event_type == WorkflowEventType.INTERRUPT:
                        raise CozeWorkflowError(
                            "Coze workflow returned INTERRUPT; resume strategy is not configured",
                            stage_key=stage_key,
                            workflow_id=workflow_id,
                            error=_event_to_jsonable(data),
                        )
                raw: Any = {"events": [_event_to_jsonable(item) for item in raw_events], "content": "".join(messages)}
            else:
                raw = coze.workflows.runs.create(workflow_id=workflow_id, parameters=safe_parameters)
        except CozeWorkflowError:
            raise
        except Exception as exc:
            raise CozeWorkflowError(
                f"Coze workflow request failed: {type(exc).__name__}: {exc}",
                stage_key=stage_key,
                workflow_id=workflow_id,
                error=str(exc),
            ) from exc
        return self.normalize_response(stage_key, workflow_id, raw)

    def build_parameters(
        self,
        stage_key: str,
        project_state: dict[str, Any],
        extra_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stage = self.stage_config(stage_key)
        parameters: dict[str, Any] = {}
        for source_key, target_key in stage.input_mapping.items():
            if source_key in project_state:
                parameters[target_key] = project_state[source_key]
        if extra_parameters:
            for key, value in extra_parameters.items():
                parameters[str(key)] = value
        return parameters

    def normalize_response(self, stage_key: str, workflow_id: str, raw_response: Any) -> dict[str, Any]:
        raw_jsonable = _event_to_jsonable(raw_response)
        content = _first_text(raw_jsonable, ("content", "answerText", "textOutput", "message", "data", "output", "result"))
        parsed = _try_json_loads(content) if content else _try_json_loads(raw_jsonable)
        stage = self.stage_config(stage_key) if stage_key else None
        normalized: dict[str, Any] = {
            "stage_key": stage_key,
            "workflow_id": workflow_id,
            "ok": True,
            "content": content,
            "parsed": parsed,
            "raw_response": raw_jsonable,
            "error": None,
        }
        if isinstance(parsed, dict):
            normalized.update(parsed)
        elif isinstance(raw_jsonable, dict):
            normalized.update(raw_jsonable)

        if stage:
            self._apply_output_mapping(normalized, parsed, raw_jsonable, stage)
        return normalized

    def stage_config(self, stage_key: str) -> CozeStageConfig:
        stages = self.config.get("stages")
        if not isinstance(stages, dict):
            raise CozeWorkflowError("Coze workflow config missing stages")
        if stage_key not in stages:
            raise CozeWorkflowError(f"Unknown Coze stage_key: {stage_key}", stage_key=stage_key)
        raw = stages[stage_key]
        if not isinstance(raw, dict):
            raise CozeWorkflowError(f"Invalid Coze stage config: {stage_key}", stage_key=stage_key)
        fallbacks = raw.get("output_fallbacks") or self.config.get("output_fallbacks") or []
        return CozeStageConfig(
            key=stage_key,
            name=str(raw.get("name") or stage_key),
            workflow_id=str(raw.get("workflow_id") or ""),
            workflow_id_env=str(raw.get("workflow_id_env") or ""),
            yaml_path=str(raw.get("yaml_path") or ""),
            input_mapping=dict(raw.get("input_mapping") or {}),
            output_mapping=dict(raw.get("output_mapping") or {}),
            output_fallbacks=tuple(str(item) for item in fallbacks),
        )

    def workflow_id_for_stage(self, stage_key: str) -> str:
        stage = self.stage_config(stage_key)
        if stage.workflow_id_env:
            env_value = os.getenv(stage.workflow_id_env)
            if env_value:
                return env_value.strip()
        return stage.workflow_id

    def _apply_output_mapping(
        self,
        normalized: dict[str, Any],
        parsed: Any,
        raw_jsonable: Any,
        stage: CozeStageConfig,
    ) -> None:
        for source_key, target_key in stage.output_mapping.items():
            value = None
            if isinstance(parsed, dict):
                value = _deep_find_key(parsed, source_key)
            if value is None and isinstance(raw_jsonable, dict):
                value = _deep_find_key(raw_jsonable, source_key)
            if value is None and source_key in {"output", "data", "content"}:
                value = parsed if parsed not in (None, "", {}, []) else normalized.get("content")
            if value is None:
                continue
            value = _try_json_loads(value)
            normalized[target_key] = value
            if isinstance(value, dict):
                normalized.update(value)

        if len(stage.output_mapping) == 1:
            target_key = next(iter(stage.output_mapping.values()))
            if target_key not in normalized and parsed not in (None, "", {}, []):
                normalized[target_key] = parsed

    def _client(self) -> Any:
        if self._coze is not None:
            return self._coze
        from cozepy import COZE_CN_BASE_URL, Coze, TokenAuth

        token = os.getenv(self.token_env)
        base_url = os.getenv(self.base_url_env) or COZE_CN_BASE_URL
        self._coze = Coze(auth=TokenAuth(token=token), base_url=base_url)
        return self._coze


def _event_to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _event_to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_event_to_jsonable(v) for v in value]
    for attr in ("model_dump", "dict", "to_dict"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                return _event_to_jsonable(method())
            except Exception:
                pass
    if hasattr(value, "__dict__"):
        return {
            str(k): _event_to_jsonable(v)
            for k, v in vars(value).items()
            if not str(k).startswith("_")
        }
    return str(value)


coze_workflow_client = CozeWorkflowClient()
