from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from workflow_code_skeleton.app.services.runtime_paths import (
    archive_runtime_file,
    ensure_runtime_archive_layout,
    get_runtime_archive_dir,
    get_runtime_data_dir,
    is_runtime_entry_file,
    load_runtime_manifest,
)


PROJECT_ACTIVE_STATUSES = {"pending", "running", "pausing", "paused"}
TEXT_LIMIT = 100_000
JSON_LIMIT = 200_000
ANY_LIMIT = 500_000


@dataclass(slots=True)
class ArchiveCandidate:
    path: str
    size: int
    category: str
    kind: str
    project_id: int | None
    status: str
    archived_only: bool
    keep_entry: bool
    reason: str
    title: str = ""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_project_id_from_name(path: Path) -> int | None:
    match = re.search(r"_(\d+)(?:_[^\\/]+)?\.[^.]+$", path.name)
    if not match:
        return None
    return int(match.group(1))


def is_large_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    size = path.stat().st_size
    if suffix in {".txt", ".md"}:
        return size > TEXT_LIMIT
    if suffix in {".json", ".jsonc"}:
        return size > JSON_LIMIT
    return size > ANY_LIMIT


def load_project_statuses(projects_dir: Path) -> dict[int, dict[str, Any]]:
    statuses: dict[int, dict[str, Any]] = {}
    for path in projects_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        project_id = int(data.get("project_id") or path.stem or 0)
        statuses[project_id] = {
            "status": str(data.get("status") or "").strip().lower(),
            "title": str(data.get("title") or "").strip(),
            "updated_at": str(data.get("updated_at") or data.get("created_at") or ""),
            "path": str(path),
        }
    return statuses


def build_candidates(root: Path) -> tuple[list[ArchiveCandidate], list[ArchiveCandidate]]:
    runtime_data_dir = root / "runtime_data"
    projects_dir = runtime_data_dir / "projects"
    exports_dir = runtime_data_dir / "exports"
    debug_dir = root / "debug"
    project_statuses = load_project_statuses(projects_dir)

    candidates: list[ArchiveCandidate] = []
    kept_active: list[ArchiveCandidate] = []

    for path in sorted(projects_dir.glob("*.json")):
        if not path.is_file() or not is_large_file(path):
            continue
        project_id = int(path.stem or 0)
        info = project_statuses.get(project_id, {})
        status = str(info.get("status") or "")
        candidate = ArchiveCandidate(
            path=str(path),
            size=path.stat().st_size,
            category="projects",
            kind="project_snapshot_json",
            project_id=project_id,
            status=status,
            archived_only=False,
            keep_entry=False,
            reason="large_project_snapshot",
            title=str(info.get("title") or ""),
        )
        if status in PROJECT_ACTIVE_STATUSES:
            kept_active.append(candidate)
        else:
            candidates.append(candidate)

    export_candidates_by_path: dict[str, ArchiveCandidate] = {}
    export_project_ids: set[int] = set()
    for path in sorted(exports_dir.iterdir()):
        if not path.is_file() or is_runtime_entry_file(path):
            continue
        if not is_large_file(path):
            continue
        project_id = parse_project_id_from_name(path)
        status = str((project_statuses.get(project_id or 0) or {}).get("status") or "")
        title = str((project_statuses.get(project_id or 0) or {}).get("title") or "")
        candidate = ArchiveCandidate(
            path=str(path),
            size=path.stat().st_size,
            category="exports",
            kind="export_artifact",
            project_id=project_id,
            status=status,
            archived_only=False,
            keep_entry=path.suffix.lower() == ".txt",
            reason="large_export_artifact",
            title=title,
        )
        if status in PROJECT_ACTIVE_STATUSES:
            kept_active.append(candidate)
            continue
        export_candidates_by_path[str(path)] = candidate
        if project_id is not None:
            export_project_ids.add(project_id)

    for path in sorted(exports_dir.iterdir()):
        if not path.is_file() or is_runtime_entry_file(path):
            continue
        if str(path) in export_candidates_by_path:
            continue
        project_id = parse_project_id_from_name(path)
        if project_id is None or project_id not in export_project_ids:
            continue
        status = str((project_statuses.get(project_id) or {}).get("status") or "")
        if status in PROJECT_ACTIVE_STATUSES:
            continue
        export_candidates_by_path[str(path)] = ArchiveCandidate(
            path=str(path),
            size=path.stat().st_size,
            category="exports",
            kind="export_sidecar_artifact",
            project_id=project_id,
            status=status,
            archived_only=False,
            keep_entry=path.suffix.lower() == ".txt",
            reason="related_export_artifact",
            title=str((project_statuses.get(project_id) or {}).get("title") or ""),
        )

    candidates.extend(sorted(export_candidates_by_path.values(), key=lambda item: item.path))

    if debug_dir.exists():
        for path in sorted(debug_dir.rglob("*")):
            if not path.is_file() or not is_large_file(path):
                continue
            candidates.append(
                ArchiveCandidate(
                    path=str(path),
                    size=path.stat().st_size,
                    category="debug_dumps",
                    kind="debug_dump",
                    project_id=None,
                    status="",
                    archived_only=True,
                    keep_entry=False,
                    reason="large_debug_dump",
                )
            )

    return candidates, kept_active


def ensure_archive_readme(archive_dir: Path) -> None:
    readme = archive_dir / "README.md"
    if readme.exists():
        return
    readme.write_text(
        "\n".join(
            [
                "# Runtime Archive",
                "",
                "这个目录用于存放从 `runtime_data/` 和调试目录迁移出来的大型历史运行时文件。",
                "",
                "- `manifest.json`：记录原始路径与归档路径的映射。",
                "- `projects/`：历史项目快照 JSON。",
                "- `exports/`：历史导出正文、DOCX、ZIP 和侧车 JSON。",
                "- `large_docs/`：已经拆分或重构过的大文档目录。",
                "- `debug_dumps/`：阶段失败调试转储。",
                "- `logs/`：运行日志归档。",
                "",
                "业务代码需要通过 `app/services/runtime_paths.py` 解析这些归档文件，",
                "不要再在业务逻辑中直接硬编码 `runtime_data/...` 路径。",
                "",
            ]
        ),
        encoding="utf-8",
    )


def apply_archive(root: Path, candidates: list[ArchiveCandidate]) -> list[dict[str, Any]]:
    archive_dir = get_runtime_archive_dir(root)
    ensure_runtime_archive_layout(repo_root=root)
    ensure_archive_readme(archive_dir)
    manifest = load_runtime_manifest(repo_root=root)
    migrated: list[dict[str, Any]] = []

    for item in candidates:
        path = Path(item.path)
        if not path.exists():
            continue
        original_rel = path.relative_to(root).as_posix()
        if original_rel in manifest.get("entries", {}):
            continue
        metadata = {
            "project_id": item.project_id,
            "status": item.status,
            "title": item.title,
            "kind": item.kind,
            "reason": item.reason,
            "entry_note": "历史运行时文件已迁移到 runtime_archive，请通过 runtime_paths resolver 读取真实文件。",
        }
        archived_path = archive_runtime_file(
            path,
            item.category,
            base_root=root,
            archive_dir=archive_dir,
            keep_entry=item.keep_entry,
            archived_only=item.archived_only,
            metadata=metadata,
        )
        migrated.append(
            {
                "original_path": original_rel,
                "archived_path": archived_path.relative_to(root).as_posix(),
                "category": item.category,
                "kind": item.kind,
                "project_id": item.project_id,
                "keep_entry": item.keep_entry,
            }
        )
    return migrated


def build_report(
    *,
    root: Path,
    candidates: list[ArchiveCandidate],
    kept_active: list[ArchiveCandidate],
    migrated: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    manifest = load_runtime_manifest(repo_root=root)
    return {
        "root": str(root),
        "runtime_data_dir": str(get_runtime_data_dir(root)),
        "runtime_archive_dir": str(get_runtime_archive_dir(root)),
        "candidate_count": len(candidates),
        "kept_active_count": len(kept_active),
        "archived_entry_count": len(manifest.get("entries", {})),
        "candidates": [asdict(item) for item in candidates],
        "kept_active": [asdict(item) for item in kept_active],
        "migrated": migrated or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive large runtime artifacts out of runtime_data.")
    parser.add_argument("--apply", action="store_true", help="Move candidates into runtime_archive.")
    parser.add_argument("--dry-run", action="store_true", help="Show candidates without moving files.")
    args = parser.parse_args()

    root = repo_root()
    candidates, kept_active = build_candidates(root)
    migrated: list[dict[str, Any]] = []

    if args.apply:
        migrated = apply_archive(root, candidates)

    report = build_report(root=root, candidates=candidates, kept_active=kept_active, migrated=migrated)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
