from __future__ import annotations

import os
import re
from contextvars import ContextVar, Token
from functools import lru_cache
from pathlib import Path


PRODUCTION_WORKFLOW_LINE = "production"
TEST_WORKFLOW_LINE = "new-workflow-test"
WORKFLOW_LINE_HEADER = "X-Workflow-Line"

_current_workflow_line: ContextVar[str] = ContextVar(
    "current_workflow_line",
    default=PRODUCTION_WORKFLOW_LINE,
)

TEST_STAGE_ORDER = (
    "01",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
    "framework_scene_dictionary",
    "framework_appearanceMapping",
    "framework_enriched_episode_plan",
    "framework_causal_conflict_write",
    "framework_causal_conflict_review",
    "framework_causal_conflict_rewrite",
    "framework_causal_conflict_memory",
    "framework_script_write",
    "framework_script_review",
    "framework_script_rewrite",
    "framework_script_memory",
)


def normalize_workflow_line(value: object) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    if text in {"test", "new-workflow-test", "new-workflow", "workflow-test"}:
        return TEST_WORKFLOW_LINE
    return PRODUCTION_WORKFLOW_LINE


def set_workflow_line(value: object) -> Token[str]:
    return _current_workflow_line.set(normalize_workflow_line(value))


def reset_workflow_line(token: Token[str]) -> None:
    _current_workflow_line.reset(token)


def current_workflow_line() -> str:
    return _current_workflow_line.get()


def is_test_workflow_line() -> bool:
    return current_workflow_line() == TEST_WORKFLOW_LINE


def test_workflow_api_file() -> Path:
    configured = os.getenv("FASTGPT_TEST_WORKFLOW_API_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Desktop" / "新工作流api.txt"


def test_workflow_json_dir() -> Path:
    configured = os.getenv("FASTGPT_TEST_WORKFLOW_JSON_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return (
        Path.home()
        / "Desktop"
        / "工作流json"
        / "工作流优化"
        / "全新工作流_双样本因果连续性全题材_20260723_173732"
    )


def test_workflow_chat_completions_url() -> str:
    root = os.getenv(
        "FASTGPT_TEST_WORKFLOW_BASE_URL",
        "http://47.93.31.133:9999/api",
    ).strip().rstrip("/")
    if root.endswith("/v1/chat/completions"):
        return root
    if root.endswith("/v1"):
        return f"{root}/chat/completions"
    return f"{root}/v1/chat/completions"


@lru_cache(maxsize=4)
def _load_test_stage_keys(api_file: str, modified_ns: int) -> dict[str, str]:
    del modified_ns
    text = Path(api_file).read_text(encoding="utf-8-sig")
    keys = re.findall(r"fastgpt-[A-Za-z0-9_-]+", text)
    if len(keys) != len(TEST_STAGE_ORDER):
        raise ValueError(
            "新工作流 API 清单数量不正确："
            f"应为 {len(TEST_STAGE_ORDER)} 个，实际读取到 {len(keys)} 个。"
        )
    if len(set(keys)) != len(keys):
        raise ValueError("新工作流 API 清单中存在重复密钥，请检查编号。")
    return dict(zip(TEST_STAGE_ORDER, keys, strict=True))


def test_stage_api_key(stage_name: str) -> str:
    path = test_workflow_api_file()
    if not path.is_file():
        raise ValueError(f"新工作流 API 文件不存在：{path}")
    keys = _load_test_stage_keys(str(path.resolve()), path.stat().st_mtime_ns)
    key = keys.get(str(stage_name))
    if not key:
        raise ValueError(f"新工作流测试线路未配置阶段：{stage_name}")
    return key


def test_workflow_status() -> dict[str, object]:
    path = test_workflow_api_file()
    workflow_dir = test_workflow_json_dir()
    workflow_json_count = (
        len(
            [
                item
                for item in workflow_dir.rglob("*.json")
                if item.name.lower() != "manifest.json"
            ]
        )
        if workflow_dir.is_dir()
        else 0
    )
    try:
        configured_stage_count = (
            len(_load_test_stage_keys(str(path.resolve()), path.stat().st_mtime_ns))
            if path.is_file()
            else 0
        )
        error = ""
    except (OSError, ValueError) as exc:
        configured_stage_count = 0
        error = str(exc)
    return {
        "line": TEST_WORKFLOW_LINE,
        "api_file_exists": path.is_file(),
        "workflow_dir_exists": workflow_dir.is_dir(),
        "workflow_json_count": workflow_json_count,
        "configured_stage_count": configured_stage_count,
        "expected_stage_count": len(TEST_STAGE_ORDER),
        "base_url": test_workflow_chat_completions_url(),
        "ready": (
            configured_stage_count == len(TEST_STAGE_ORDER)
            and workflow_json_count == len(TEST_STAGE_ORDER)
        ),
        "error": error,
    }
