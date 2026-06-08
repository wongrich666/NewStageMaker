from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKELETON_ROOT = SCRIPT_DIR.parent
if str(SKELETON_ROOT) not in sys.path:
    sys.path.insert(0, str(SKELETON_ROOT))

from dotenv import load_dotenv  # noqa: E402


load_dotenv(SKELETON_ROOT / ".env", override=False)
load_dotenv(SKELETON_ROOT.parent / ".env", override=False)

from app.services.coze_workflow_client import coze_workflow_client  # noqa: E402


def _status(name: str) -> str:
    return "SET" if str(os.getenv(name) or "").strip() else "EMPTY"


def _workflow_info(stage_key: str) -> dict[str, Any]:
    try:
        return coze_workflow_client.workflow_id_info_for_stage(stage_key)
    except Exception as exc:
        return {"workflow_id": "", "workflow_id_error": str(exc)}


def main() -> int:
    stage_key = sys.argv[1] if len(sys.argv) > 1 else "stage_01"
    workflow_info = _workflow_info(stage_key)
    credentials = coze_workflow_client.credentials_diagnostics()
    token_statuses = {
        "COZE_PRIMARY_API_TOKEN": _status("COZE_PRIMARY_API_TOKEN"),
        "COZE_SECONDARY_API_TOKEN": _status("COZE_SECONDARY_API_TOKEN"),
        "COZE_API_TOKEN": _status("COZE_API_TOKEN"),
    }
    configured_token_envs = [
        item.get("token_env")
        for item in credentials
        if item.get("token_status") == "SET" and item.get("token_env")
    ]
    result = {
        "ok": bool(configured_token_envs),
        "note": "This script only verifies local credential discovery; it does not call Coze.",
        "workflow_backend": os.getenv("WORKFLOW_BACKEND") or "coze",
        "env_paths": [str(SKELETON_ROOT / ".env"), str(SKELETON_ROOT.parent / ".env")],
        "stage_key": stage_key,
        "normalized_stage_key": workflow_info.get("normalized_stage_key") or stage_key,
        "workflow_id_status": "SET" if workflow_info.get("workflow_id") else "EMPTY",
        "workflow_id_source": workflow_info.get("workflow_id_source") or "",
        "resource_path": workflow_info.get("resource_path") or "",
        "inner_yaml_path": workflow_info.get("inner_yaml_path") or "",
        "coze_credentials_order": os.getenv("COZE_CREDENTIALS_ORDER") or "primary,secondary",
        "credential_attempt_order": [item.get("credential_name") for item in credentials],
        "configured_token_envs": configured_token_envs,
        "token_statuses": token_statuses,
        "credentials": credentials,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
