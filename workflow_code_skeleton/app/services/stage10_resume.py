from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def stage10_input_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_stage10_resume(
    path: Path,
    *,
    fingerprint: str,
    asset_id: str,
    total_episodes: int,
    batch_size: int,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("status") not in {"partial", "failed"}:
        return None
    if str(payload.get("fingerprint") or "") != str(fingerprint or ""):
        return None
    if str(payload.get("asset_id") or "") != str(asset_id or ""):
        return None
    if int(payload.get("total_episodes") or 0) != int(total_episodes or 0):
        return None
    if int(payload.get("batch_size") or 0) != int(batch_size or 0):
        return None

    episodes: dict[int, dict[str, Any]] = {}
    for item in payload.get("episodes") or []:
        if not isinstance(item, dict):
            continue
        try:
            episode_no = int(item.get("episode") or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= episode_no <= total_episodes:
            episodes[episode_no] = item
    text_by_batch = {
        str(key): str(value)
        for key, value in (payload.get("text_by_batch") or {}).items()
        if str(value or "").strip()
    }
    return {"episodes": episodes, "text_by_batch": text_by_batch}


def save_stage10_resume(
    path: Path,
    *,
    status: str,
    fingerprint: str,
    asset_id: str,
    total_episodes: int,
    batch_size: int,
    episodes: dict[int, dict[str, Any]],
    text_by_batch: dict[str, str],
    updated_at: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": str(status or "partial"),
        "fingerprint": str(fingerprint or ""),
        "asset_id": str(asset_id or ""),
        "total_episodes": int(total_episodes or 0),
        "batch_size": int(batch_size or 0),
        "completed_episodes": sorted(int(key) for key in episodes),
        "episodes": [episodes[key] for key in sorted(episodes)],
        "text_by_batch": dict(text_by_batch),
        "updated_at": str(updated_at or ""),
    }
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary_path.replace(path)
