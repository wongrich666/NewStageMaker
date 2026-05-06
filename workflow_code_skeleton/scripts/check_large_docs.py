from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from workflow_code_skeleton.app.services.runtime_paths import load_runtime_manifest

PLACEHOLDER_PATTERN = re.compile(
    r"(待补全|待完善|未提供|暂无|待填写|待定|TBD|TODO|\[object Object\]|None|null)",
    re.IGNORECASE,
)
HEADING_PATTERN = re.compile(
    r"^(#{1,6}\s+.+|故事梗概|世界观设定|人物小传|人物服饰说明|核心场景|分集计划|剧本正文|第\d+集[:：].+)$"
)
JSONISH_LINE_PATTERN = re.compile(r'^\s*"[^"\n]+"\s*:\s*')


def iter_doc_files(root: Path, *, ignored_roots: tuple[Path, ...] = ()) -> list[Path]:
    extensions = {".md", ".txt", ".json", ".jsonc"}
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(ignored == path or ignored in path.parents for ignored in ignored_roots):
            continue
        if path.suffix.lower() not in extensions:
            continue
        candidates.append(path)
    return sorted(candidates)


def duplicate_headings(lines: list[str]) -> list[str]:
    headings = [line.strip() for line in lines if HEADING_PATTERN.match(line.strip())]
    counts = Counter(headings)
    return [heading for heading, count in counts.items() if count > 1]


def json_dump_suspected(lines: list[str]) -> bool:
    jsonish_lines = sum(1 for line in lines if JSONISH_LINE_PATTERN.match(line))
    fenced_json = sum(1 for line in lines if line.strip().startswith("```json"))
    return jsonish_lines >= 20 or fenced_json >= 1


def inspect_file(path: Path, size_limit: int, line_limit: int) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except FileNotFoundError:
            return []
    lines = text.splitlines()
    findings: list[str] = []
    try:
        file_size = path.stat().st_size
    except FileNotFoundError:
        return []
    if file_size > size_limit:
        findings.append(f"oversized_bytes={file_size}")
    if len(lines) > line_limit:
        findings.append(f"oversized_lines={len(lines)}")
    if PLACEHOLDER_PATTERN.search(text):
        findings.append("placeholder_tokens")
    if json_dump_suspected(lines):
        findings.append("json_dump_suspected")
    duplicates = duplicate_headings(lines)
    if duplicates:
        findings.append("duplicate_headings=" + " | ".join(duplicates[:8]))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Check large or polluted documentation-like files.")
    parser.add_argument(
        "root",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root to scan.",
    )
    parser.add_argument("--size-limit", type=int, default=200_000, help="Maximum recommended file size in bytes.")
    parser.add_argument("--line-limit", type=int, default=3_000, help="Maximum recommended line count.")
    parser.add_argument(
        "--include-archive",
        action="store_true",
        help="Include runtime_archive in the active scan.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    ignored_roots: tuple[Path, ...] = ()
    runtime_archive_dir = root / "runtime_archive"
    if runtime_archive_dir.exists() and not args.include_archive:
        ignored_roots = (runtime_archive_dir,)
    problems: dict[str, list[str]] = {}
    for path in iter_doc_files(root, ignored_roots=ignored_roots):
        findings = inspect_file(path, args.size_limit, args.line_limit)
        if findings:
            problems[str(path.relative_to(root))] = findings

    manifest = load_runtime_manifest(repo_root=root)
    archived_entries = [
        {
            "original_path": key,
            "archived_path": value.get("archived_path"),
            "category": value.get("category"),
            "kind": value.get("kind"),
            "size": value.get("size"),
        }
        for key, value in sorted((manifest.get("entries") or {}).items())
        if isinstance(value, dict)
    ]

    if not problems and not archived_entries:
        print("No large-doc issues found.")
        return 0

    payload: dict[str, object] = {"active_issues": problems}
    if ignored_roots:
        payload["ignored_roots"] = [str(path.relative_to(root)) for path in ignored_roots]
    if archived_entries:
        payload["archived_entries"] = archived_entries
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
