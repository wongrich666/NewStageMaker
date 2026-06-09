from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKELETON_ROOT = SCRIPT_DIR.parent
if str(SKELETON_ROOT) not in sys.path:
    sys.path.insert(0, str(SKELETON_ROOT))

from dotenv import load_dotenv  # noqa: E402


load_dotenv(SKELETON_ROOT / ".env", override=True)
load_dotenv(SKELETON_ROOT.parent / ".env", override=False)

from app.services.coze_workflow_client import coze_workflow_client  # noqa: E402


def _status(name: str) -> str:
    return "SET" if os.getenv(name) else "EMPTY"


def _safe_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def main() -> int:
    stage_key = "stage_01"
    workflow_info = coze_workflow_client.workflow_id_info_for_stage(stage_key)
    workflow_id = str(workflow_info.get("workflow_id") or "")
    credentials = coze_workflow_client.credentials_diagnostics()
    first_credential = credentials[0] if credentials else {}
    print(f"workflow_backend = {os.getenv('WORKFLOW_BACKEND') or 'coze'}")
    print(f"env_path = {SKELETON_ROOT / '.env'}")
    print(f"parent_env_path = {SKELETON_ROOT.parent / '.env'}")
    print(f"coze_credentials_order = {os.getenv('COZE_CREDENTIALS_ORDER') or 'primary,secondary'}")
    print(f"credential_chain = {[item.get('credential_name') for item in credentials]}")
    print(f"credential_attempt_order = {[item.get('credential_name') for item in credentials]}")
    print(f"base_url = {first_credential.get('base_url') or ''}")
    print(f"base_url_source = {first_credential.get('base_url_source') or ''}")
    print(f"token_status = {first_credential.get('token_status') or 'EMPTY'}")
    print(f"legacy_token_status = {_status('COZE_API_TOKEN')}")
    print(f"primary_token_status = {_status('COZE_PRIMARY_API_TOKEN')}")
    print(f"secondary_token_status = {_status('COZE_SECONDARY_API_TOKEN')}")
    print("credentials =")
    print(_safe_dump(credentials))
    print(f"workflow_id_status = {'SET' if workflow_id else 'EMPTY'}")
    print(f"workflow_id = {workflow_id}")
    print(f"stage_key = {stage_key}")
    print(f"workflow_id_source = {workflow_info.get('workflow_id_source') or ''}")
    print(f"workflow_id_env = {workflow_info.get('workflow_id_env') or ''}")
    print(f"resource_path = {workflow_info.get('resource_path') or ''}")
    print(f"inner_yaml_path = {workflow_info.get('inner_yaml_path') or ''}")
    if not any(item.get("token_status") == "SET" for item in credentials):
        print("At least one Coze credential token is required for smoke test")
        return 2
    if not workflow_id:
        print("COZE_WORKFLOW_STAGE_01_ID or stage_01 workflow id is required for smoke test")
        return 2

    try:
        result = coze_workflow_client.run_stage(
            stage_key,
            {
                "mode": "创作",
                "source_text": "测试短剧设定",
                "source_title": "测试",
                "target_format": "短剧",
                "season_count": 1,
                "episodes_per_season": 20,
                "minutes_per_episode": 2,
                "adaptation_direction": "",
                "user_constraints": "",
                "user_requirements": "",
            },
        )
    except Exception as exc:
        print(f"original_exception_type = {type(exc).__name__}")
        print(f"original_exception_message = {exc}")
        detail = getattr(exc, "detail", None)
        if detail:
            print(f"original_error_code = {detail.get('original_error_code') or detail.get('code') or ''}")
            print(f"original_error_msg = {detail.get('original_error_msg') or detail.get('msg') or detail.get('message') or ''}")
            print("credential_attempts =")
            print(_safe_dump(detail.get("credential_attempts") or []))
            print("detail =")
            print(_safe_dump(detail))
        print("traceback =")
        print(traceback.format_exc(limit=8))
        return 1

    print("ok = True")
    print(f"result_keys = {sorted(result.keys())}")
    print(f"credential_name = {result.get('credential_name') or result.get('coze_credential_name') or ''}")
    print("credential_attempts =")
    print(_safe_dump(result.get("credential_attempts") or []))
    print(f"content_length = {len(str(result.get('content') or ''))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
