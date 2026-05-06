from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4


_WORKSPACE_TEMP_ROOT = Path(
    os.getenv("NEWSTAGEMAKER_TEST_TMPDIR")
    or (Path(tempfile.gettempdir()) / "newstagemaker_test_workspaces")
)


def _ensure_workspace_temp_root() -> Path:
    _WORKSPACE_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    return _WORKSPACE_TEMP_ROOT


def _prune_workspace_temp_root() -> None:
    try:
        if _WORKSPACE_TEMP_ROOT.exists() and not any(_WORKSPACE_TEMP_ROOT.iterdir()):
            _WORKSPACE_TEMP_ROOT.rmdir()
    except OSError:
        pass


class WorkspaceTempDir:
    def __init__(self, prefix: str = "test-") -> None:
        root = _ensure_workspace_temp_root()
        while True:
            candidate = root / f"{prefix}{uuid4().hex[:12]}"
            try:
                candidate.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                continue
            self.name = str(candidate)
            break

    def cleanup(self) -> None:
        shutil.rmtree(self.name, ignore_errors=True)
        _prune_workspace_temp_root()

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()


@contextmanager
def workspace_tempdir(prefix: str = "test-") -> Iterator[str]:
    temp_dir = WorkspaceTempDir(prefix=prefix)
    try:
        yield temp_dir.name
    finally:
        temp_dir.cleanup()
