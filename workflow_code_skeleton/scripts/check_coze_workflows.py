from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "workflow_code_skeleton" / "config" / "coze_workflows.yaml"


def _load_local_env() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(ROOT / "workflow_code_skeleton" / ".env", override=True)


def _load_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except Exception as exc:
            raise RuntimeError(f"{path} is not JSON-compatible YAML and PyYAML is unavailable") from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} must contain an object")
    return data


def _workflow_id(stage: dict[str, Any]) -> tuple[str, str]:
    env_name = str(stage.get("workflow_id_env") or "").strip()
    env_value = os.getenv(env_name) if env_name else ""
    if env_value:
        return env_value.strip(), f"env:{env_name}"
    return str(stage.get("workflow_id") or "").strip(), "config"


def _yaml_base(config: dict[str, Any]) -> Path:
    env_name = str(config.get("yaml_base_dir_env") or "BETTER_FRAMEWORK_JSONS_DIR")
    env_value = os.getenv(env_name)
    raw = env_value or str(config.get("default_yaml_base_dir") or "../BETTER_FRAMEWORK_JSONS")
    path = Path(raw)
    if not path.is_absolute():
        path = (DEFAULT_CONFIG.parent / path).resolve()
    return path


def _yaml_path_exists(base_dir: Path, yaml_path: str) -> bool:
    if "::" in yaml_path:
        zip_name, entry_name = yaml_path.split("::", 1)
        zip_path = base_dir / zip_name
        if not zip_path.exists():
            return False
        try:
            with zipfile.ZipFile(zip_path) as archive:
                return entry_name in archive.namelist()
        except zipfile.BadZipFile:
            return False
    path = Path(yaml_path)
    if not path.is_absolute():
        path = base_dir / path
    return path.exists()


def main() -> int:
    _load_local_env()
    config_path = Path(os.getenv("COZE_WORKFLOW_CONFIG") or DEFAULT_CONFIG).resolve()
    errors: list[str] = []
    if not config_path.exists():
        print(f"ERROR config not found: {config_path}")
        return 2
    try:
        config = _load_config(config_path)
    except Exception as exc:
        print(f"ERROR failed to read config: {type(exc).__name__}: {exc}")
        return 2

    stages = config.get("stages")
    if not isinstance(stages, dict):
        print("ERROR config.stages must be a dict")
        return 2

    base_dir = _yaml_base(config)
    print(f"config: {config_path}")
    print(f"yaml_base_dir: {base_dir}")
    for stage_key in sorted(stages):
        stage = stages[stage_key]
        if not isinstance(stage, dict):
            errors.append(f"{stage_key}: stage config must be dict")
            continue
        workflow_id, source = _workflow_id(stage)
        name = str(stage.get("name") or stage_key)
        yaml_path = str(stage.get("yaml_path") or "")
        input_mapping = stage.get("input_mapping")
        output_mapping = stage.get("output_mapping")
        print(f"{stage_key}: {name} workflow_id={workflow_id or '<missing>'} source={source} yaml={yaml_path}")
        if not workflow_id and not str(stage.get("workflow_id_env") or "").strip():
            errors.append(f"{stage_key}: missing workflow_id and workflow_id_env")
        if not yaml_path:
            errors.append(f"{stage_key}: missing yaml_path")
        elif not _yaml_path_exists(base_dir, yaml_path):
            errors.append(f"{stage_key}: yaml_path not found: {yaml_path}")
        if not isinstance(input_mapping, dict):
            errors.append(f"{stage_key}: input_mapping must be dict")
        if not isinstance(output_mapping, dict):
            errors.append(f"{stage_key}: output_mapping must be dict")

    if errors:
        print("\nFAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
