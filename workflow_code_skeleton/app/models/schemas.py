from __future__ import annotations

from typing import Any, TypedDict


class ApprovalReviewSchema(TypedDict, total=False):
    approved: bool
    suggestions: list[str]


class PassReviewSchema(TypedDict, total=False):
    passed: bool
    rewrite_required: bool
    summary: str
    blocking_issues: list[str]
    non_blocking_issues: list[str]
    rewrite_start_episode: int
    stage: str


JSONDict = dict[str, Any]
