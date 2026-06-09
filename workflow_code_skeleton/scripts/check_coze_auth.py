from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKELETON_ROOT = SCRIPT_DIR.parent
ENV_PATH = SKELETON_ROOT / ".env"
if str(SKELETON_ROOT) not in sys.path:
    sys.path.insert(0, str(SKELETON_ROOT))


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(ENV_PATH, override=True)
    load_dotenv(SKELETON_ROOT.parent / ".env", override=False)


def _raw_env_lines() -> list[str]:
    if not ENV_PATH.exists():
        return []
    return ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines()


def _status(name: str) -> str:
    return "SET" if str(os.getenv(name) or "").strip() else "EMPTY"


def _token_summary(name: str) -> dict[str, Any]:
    raw = os.getenv(name) or ""
    stripped = raw.strip()
    return {
        "env": name,
        "status": _status(name),
        "prefix": stripped[:8] if stripped else "",
        "len": len(stripped),
        "has_outer_space": raw != stripped,
        "contains_newline": "\n" in raw or "\r" in raw,
        "has_bearer_prefix": stripped.lower().startswith("bearer "),
        "too_short": bool(stripped) and len(stripped) < 20,
    }


def _split_line_risks() -> list[str]:
    risks: list[str] = []
    suspicious = re.compile(r"^(?:Ayi|pat_|cztei_)[A-Za-z0-9._-]{8,}$")
    for index, line in enumerate(_raw_env_lines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" in stripped:
            continue
        if suspicious.match(stripped):
            risks.append(
                f"line {index}: 疑似 token 被拆行，请把完整 token 放到 COZE_PRIMARY_API_TOKEN= 同一行。"
            )
    return risks


def _expiry_risk(name: str) -> str:
    raw = str(os.getenv(name) or "").strip()
    if not raw or raw == "YYYY-MM-DD":
        return "EMPTY"
    try:
        expires = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return f"INVALID_DATE:{raw}"
    days = (expires - date.today()).days
    if days < 0:
        return f"EXPIRED:{raw}"
    if days <= 7:
        return f"EXPIRING_SOON:{raw}"
    return f"OK:{raw}"


def _workflow_info(stage_key: str) -> dict[str, Any]:
    from app.services.coze_workflow_client import coze_workflow_client

    try:
        return coze_workflow_client.workflow_id_info_for_stage(stage_key)
    except Exception as exc:
        return {"workflow_id": "", "workflow_id_error": str(exc)}


def main() -> int:
    _load_env()
    from app.services.coze_workflow_client import coze_workflow_client

    stage_key = sys.argv[1] if len(sys.argv) > 1 else "stage_01"
    workflow_info = _workflow_info(stage_key)
    credentials = coze_workflow_client.credentials_diagnostics()
    credential_detail = coze_workflow_client.credential_diagnostics()
    split_line_risks = _split_line_risks()
    bot_id = os.getenv("COZE_BOT_ID") or os.getenv("COZE_WORKFLOW_STAGE_01_BOT_ID") or ""
    app_id = os.getenv("COZE_APP_ID") or os.getenv("COZE_WORKFLOW_STAGE_01_APP_ID") or ""
    payload = {
        "ok": any(item.get("token_status") == "SET" for item in credentials) and not split_line_risks,
        "note": "This script verifies local Coze env discovery; it does not call Coze.",
        "env_path": str(ENV_PATH),
        "env_exists": ENV_PATH.exists(),
        "WORKFLOW_BACKEND": os.getenv("WORKFLOW_BACKEND") or "",
        "COZE_API_BASE": os.getenv("COZE_API_BASE") or "",
        "COZE_CREDENTIALS_ORDER": os.getenv("COZE_CREDENTIALS_ORDER") or "",
        "credential_chain": credential_detail.get("credential_chain", []),
        "credential_attempt_order": credential_detail.get("credential_attempt_order", []),
        "credentials": credentials,
        "tokens": {
            "primary": _token_summary("COZE_PRIMARY_API_TOKEN"),
            "secondary": _token_summary("COZE_SECONDARY_API_TOKEN"),
            "legacy": _token_summary("COZE_API_TOKEN"),
        },
        "token_expiry_risk": {
            "primary": _expiry_risk("COZE_PRIMARY_TOKEN_EXPIRES_AT"),
            "secondary": _expiry_risk("COZE_SECONDARY_TOKEN_EXPIRES_AT"),
            "legacy": _expiry_risk("COZE_TOKEN_EXPIRES_AT"),
        },
        "stage_key": stage_key,
        "normalized_stage_key": workflow_info.get("normalized_stage_key") or stage_key,
        "COZE_WORKFLOW_STAGE_01_ID": os.getenv("COZE_WORKFLOW_STAGE_01_ID") or "",
        "resolved_stage_01_workflow_id": workflow_info.get("workflow_id") or "",
        "workflow_id_source": workflow_info.get("workflow_id_source") or "",
        "workflow_id_env": workflow_info.get("workflow_id_env") or "",
        "config_path": workflow_info.get("config_path") or "",
        "resource_path": workflow_info.get("resource_path") or "",
        "inner_yaml_path": workflow_info.get("inner_yaml_path") or "",
        "token_split_line_risks": split_line_risks,
        "bearer_prefix_detected": {
            "primary": _token_summary("COZE_PRIMARY_API_TOKEN")["has_bearer_prefix"],
            "secondary": _token_summary("COZE_SECONDARY_API_TOKEN")["has_bearer_prefix"],
            "legacy": _token_summary("COZE_API_TOKEN")["has_bearer_prefix"],
        },
        "bot_id_and_app_id_both_configured": bool(bot_id and app_id),
        "bot_id_status": "SET" if bot_id else "EMPTY",
        "app_id_status": "SET" if app_id else "EMPTY",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 1 if split_line_risks else 0


if __name__ == "__main__":
    raise SystemExit(main())
