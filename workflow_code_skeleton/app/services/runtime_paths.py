from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MANIFEST_VERSION = 1
ARCHIVE_ENTRY_MARKER = "RUNTIME_ARCHIVE_ENTRY_V1"
ARCHIVE_SUBDIRECTORIES = (
    "projects",
    "exports",
    "large_docs",
    "debug_dumps",
    "logs",
)


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _normalize_base_root(base_root: Path | None = None) -> Path:
    if base_root:
        return Path(base_root).resolve()
    env_root = os.environ.get("RUNTIME_DATA_DIR")
    if env_root:
        root = Path(env_root).resolve()
        if root.name == "runtime_data":
            return root.parent
        return root
    return _default_repo_root()


def _coerce_path(path: str | Path, *, base_root: Path | None = None) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (_normalize_base_root(base_root) / candidate).resolve()


def _relative_key(path: str | Path, *, base_root: Path | None = None) -> str:
    candidate = _coerce_path(path, base_root=base_root)
    root = _normalize_base_root(base_root)
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return candidate.as_posix()


def _default_manifest() -> dict[str, Any]:
    return {
        "version": MANIFEST_VERSION,
        "updated_at": _now_iso(),
        "entries": {},
    }


def get_runtime_data_dir(repo_root: Path | None = None) -> Path:
    return _normalize_base_root(repo_root) / "runtime_data"


def get_runtime_archive_dir(repo_root: Path | None = None) -> Path:
    return _normalize_base_root(repo_root) / "runtime_archive"


def get_runtime_manifest_path(
    *,
    repo_root: Path | None = None,
    archive_dir: Path | None = None,
) -> Path:
    if archive_dir is not None:
        return Path(archive_dir).resolve() / "manifest.json"
    return get_runtime_archive_dir(repo_root) / "manifest.json"


def ensure_runtime_archive_layout(
    *,
    repo_root: Path | None = None,
    archive_dir: Path | None = None,
    manifest_path: Path | None = None,
) -> Path:
    archive_root = Path(archive_dir).resolve() if archive_dir else get_runtime_archive_dir(repo_root)
    archive_root.mkdir(parents=True, exist_ok=True)
    for name in ARCHIVE_SUBDIRECTORIES:
        (archive_root / name).mkdir(parents=True, exist_ok=True)
    manifest_file = Path(manifest_path).resolve() if manifest_path else get_runtime_manifest_path(
        repo_root=repo_root,
        archive_dir=archive_root,
    )
    if not manifest_file.exists():
        manifest_file.write_text(
            json.dumps(_default_manifest(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return archive_root


def load_runtime_manifest(
    *,
    manifest_path: Path | None = None,
    archive_dir: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path).resolve() if manifest_path else get_runtime_manifest_path(
        repo_root=repo_root,
        archive_dir=archive_dir,
    )
    if not manifest_file.exists():
        return _default_manifest()
    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception:
        return _default_manifest()
    entries = data.get("entries")
    if not isinstance(entries, dict):
        data["entries"] = {}
    data.setdefault("version", MANIFEST_VERSION)
    data.setdefault("updated_at", _now_iso())
    return data


def update_runtime_manifest(
    updates: dict[str, dict[str, Any]] | None = None,
    *,
    removals: Iterable[str] = (),
    manifest_path: Path | None = None,
    archive_dir: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    archive_root = ensure_runtime_archive_layout(
        repo_root=repo_root,
        archive_dir=archive_dir,
        manifest_path=manifest_path,
    )
    manifest_file = Path(manifest_path).resolve() if manifest_path else get_runtime_manifest_path(
        archive_dir=archive_root
    )
    manifest = load_runtime_manifest(manifest_path=manifest_file)
    entries = manifest.setdefault("entries", {})
    for key in removals:
        entries.pop(str(key), None)
    for key, value in (updates or {}).items():
        payload = dict(value)
        payload["original_path"] = str(payload.get("original_path") or key)
        entries[str(key)] = payload
    manifest["version"] = MANIFEST_VERSION
    manifest["updated_at"] = _now_iso()
    manifest_file.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def _manifest_entry_target(
    entry: dict[str, Any],
    *,
    base_root: Path | None = None,
) -> Path | None:
    archived_path = str(entry.get("archived_path") or "").strip()
    if not archived_path:
        return None
    return _coerce_path(archived_path, base_root=base_root)


def parse_runtime_entry(path: str | Path) -> dict[str, str] | None:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return None
    try:
        text = candidate.read_text(encoding="utf-8")
    except Exception:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != ARCHIVE_ENTRY_MARKER:
        return None
    payload: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        payload[key.strip().lower().replace("-", "_")] = value.strip()
    return payload or None


def is_runtime_entry_file(path: str | Path) -> bool:
    return parse_runtime_entry(path) is not None


def render_runtime_entry_text(
    *,
    original_path: str,
    archived_path: str,
    category: str,
    note: str | None = None,
) -> str:
    lines = [
        ARCHIVE_ENTRY_MARKER,
        f"Original-Path: {original_path}",
        f"Archived-Target: {archived_path}",
        f"Category: {category}",
        f"Archived-At: {_now_iso()}",
    ]
    if note:
        lines.append(f"Note: {note}")
    return "\n".join(lines) + "\n"


def _finalize_resolved_path(path: Path) -> Path:
    if path.is_dir():
        index_file = path / "index.md"
        if index_file.exists():
            return index_file
    return path


def resolve_runtime_file(
    path: str | Path,
    *,
    base_root: Path | None = None,
    manifest_path: Path | None = None,
    archive_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Path:
    base = base_root or repo_root
    candidate = _coerce_path(path, base_root=base)
    if candidate.exists():
        entry = parse_runtime_entry(candidate)
        if entry:
            target = entry.get("archived_target", "")
            if target:
                return resolve_runtime_file(
                    target,
                    base_root=base,
                    manifest_path=manifest_path,
                    archive_dir=archive_dir,
                    repo_root=repo_root,
                )
        return _finalize_resolved_path(candidate)

    manifest = load_runtime_manifest(
        manifest_path=manifest_path,
        archive_dir=archive_dir,
        repo_root=repo_root,
    )
    key = _relative_key(candidate, base_root=base)
    entry = manifest.get("entries", {}).get(key)
    if not isinstance(entry, dict):
        raise FileNotFoundError(f"未找到运行时文件：{candidate}")
    target = _manifest_entry_target(entry, base_root=base)
    if target is None or not target.exists():
        raise FileNotFoundError(f"运行时文件已登记归档，但目标不存在：{key}")
    return _finalize_resolved_path(target)


def resolve_project_snapshot_path(
    project_id: int,
    *,
    projects_dir: Path | None = None,
    base_root: Path | None = None,
    manifest_path: Path | None = None,
    archive_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Path | None:
    active_dir = Path(projects_dir).resolve() if projects_dir else get_runtime_data_dir(base_root or repo_root) / "projects"
    active_path = active_dir / f"{int(project_id)}.json"
    if active_path.exists():
        return active_path

    manifest = load_runtime_manifest(
        manifest_path=manifest_path,
        archive_dir=archive_dir,
        repo_root=repo_root,
    )
    active_key = _relative_key(active_path, base_root=base_root or repo_root)
    entry = manifest.get("entries", {}).get(active_key)
    if isinstance(entry, dict):
        target = _manifest_entry_target(entry, base_root=base_root or repo_root)
        if target and target.exists():
            return target

    for item in manifest.get("entries", {}).values():
        if not isinstance(item, dict):
            continue
        if str(item.get("category") or "") != "projects":
            continue
        if int(item.get("project_id") or 0) != int(project_id):
            continue
        target = _manifest_entry_target(item, base_root=base_root or repo_root)
        if target and target.exists():
            return target
    return None


def _export_candidate_priority(path: Path, *, preferred_suffix: str | None = None) -> tuple[int, str]:
    normalized_suffix = str(preferred_suffix or "").lower()
    priorities = [normalized_suffix] if normalized_suffix else []
    priorities.extend([".docx", ".txt", ".zip", ".json", ".md"])
    try:
        rank = priorities.index(path.suffix.lower())
    except ValueError:
        rank = len(priorities)
    return rank, path.name


def resolve_export_path(
    filename_or_project_id: str | int,
    *,
    exports_dir: Path | None = None,
    base_root: Path | None = None,
    manifest_path: Path | None = None,
    archive_dir: Path | None = None,
    preferred_suffix: str | None = None,
    repo_root: Path | None = None,
) -> Path | None:
    active_dir = Path(exports_dir).resolve() if exports_dir else get_runtime_data_dir(base_root or repo_root) / "exports"

    if isinstance(filename_or_project_id, int) or str(filename_or_project_id).isdigit():
        project_id = int(filename_or_project_id)
        candidates: list[Path] = []
        if active_dir.exists():
            for path in active_dir.iterdir():
                if not path.is_file():
                    continue
                if path.stem.endswith(f"_{project_id}") or f"_{project_id}_" in path.stem:
                    candidates.append(resolve_runtime_file(
                        path,
                        base_root=base_root or repo_root,
                        manifest_path=manifest_path,
                        archive_dir=archive_dir,
                        repo_root=repo_root,
                    ))
        manifest = load_runtime_manifest(
            manifest_path=manifest_path,
            archive_dir=archive_dir,
            repo_root=repo_root,
        )
        for item in manifest.get("entries", {}).values():
            if not isinstance(item, dict):
                continue
            if str(item.get("category") or "") != "exports":
                continue
            if int(item.get("project_id") or 0) != project_id:
                continue
            target = _manifest_entry_target(item, base_root=base_root or repo_root)
            if target and target.exists():
                candidates.append(_finalize_resolved_path(target))
        if not candidates:
            return None
        candidates = sorted(set(candidates), key=lambda path: _export_candidate_priority(path, preferred_suffix=preferred_suffix))
        return candidates[0]

    filename = str(filename_or_project_id or "").strip()
    if not filename:
        return None
    candidate = Path(filename)
    if not candidate.is_absolute():
        candidate = active_dir / candidate.name
    try:
        return resolve_runtime_file(
            candidate,
            base_root=base_root or repo_root,
            manifest_path=manifest_path,
            archive_dir=archive_dir,
            repo_root=repo_root,
        )
    except FileNotFoundError:
        return None


def _choose_archive_target(target: Path) -> Path:
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    counter = 1
    while True:
        candidate = target.with_name(f"{stem}__archived_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def archive_runtime_file(
    path: str | Path,
    category: str,
    *,
    base_root: Path | None = None,
    archive_dir: Path | None = None,
    manifest_path: Path | None = None,
    keep_entry: bool = False,
    archived_only: bool = False,
    metadata: dict[str, Any] | None = None,
) -> Path:
    source = _coerce_path(path, base_root=base_root)
    if not source.exists():
        raise FileNotFoundError(f"待归档文件不存在：{source}")
    if not source.is_file():
        raise ValueError(f"当前只支持归档文件：{source}")

    archive_root = ensure_runtime_archive_layout(
        archive_dir=archive_dir,
        repo_root=base_root,
        manifest_path=manifest_path,
    )
    target_dir = archive_root / category
    target_dir.mkdir(parents=True, exist_ok=True)
    target = _choose_archive_target(target_dir / source.name)

    original_key = _relative_key(source, base_root=base_root)
    shutil.move(str(source), str(target))

    archived_key = _relative_key(target, base_root=base_root)
    entry_note = str((metadata or {}).get("entry_note") or "").strip()
    if keep_entry:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            render_runtime_entry_text(
                original_path=original_key,
                archived_path=archived_key,
                category=category,
                note=entry_note or None,
            ),
            encoding="utf-8",
        )

    payload: dict[str, Any] = {
        "original_path": original_key,
        "archived_path": archived_key,
        "category": category,
        "file_name": source.name,
        "suffix": source.suffix.lower(),
        "size": target.stat().st_size,
        "archived_at": _now_iso(),
        "archived_only": bool(archived_only),
        "entry_path": original_key if keep_entry else None,
    }
    if metadata:
        payload.update({key: value for key, value in metadata.items() if key != "entry_note"})

    update_runtime_manifest(
        {original_key: payload},
        manifest_path=manifest_path,
        archive_dir=archive_root,
        repo_root=base_root,
    )
    return target
