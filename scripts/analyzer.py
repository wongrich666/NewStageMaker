from __future__ import annotations

import re
from statistics import median
from typing import Any


TITLE_EPISODE_PATTERNS = (
    re.compile(r"\bSJS[_\-\s]*(\d{1,4})\b", re.IGNORECASE),
    re.compile(r"\bEP(?:ISODE)?[_\-\s]*(\d{1,4})\b", re.IGNORECASE),
    re.compile(r"第\s*(\d{1,4})\s*[集话話]"),
)

FIELD_ALIASES = {
    "title": ("title", "标题", "视频标题", "作品标题", "name", "video_title"),
    "episode_no": ("episode_no", "episode", "集数", "第几集", "集号"),
    "total_views": ("total_views", "views", "播放量", "总播放量", "曝光播放量", "vv"),
    "total_valid_views": ("total_valid_views", "valid_views", "有效播放量", "有效播放", "valid_vv"),
    "share_count": ("share_count", "shares", "分享量", "分享次数", "转发量"),
    "like_count": ("like_count", "likes", "点赞量", "点赞次数"),
    "comment_count": ("comment_count", "comments", "评论量", "评论次数"),
    "favorite_count": ("favorite_count", "favorites", "收藏量", "收藏次数"),
}


def analyze_market_feedback(raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    episodes = [_normalize_episode(row) for row in raw_rows if isinstance(row, dict)]
    episodes = [item for item in episodes if item["title"] or item["episode_no"] is not None]
    views_values = [item["total_views"] for item in episodes if item["total_views"] > 0]
    valid_rate_values = [
        item["valid_play_rate"]
        for item in episodes
        if item["valid_play_rate"] is not None
    ]
    median_views = float(median(views_values)) if views_values else 0.0
    median_valid_rate = float(median(valid_rate_values)) if valid_rate_values else 0.0
    min_sample_views = max(100.0, median_views)

    high_sample_episodes = [
        item for item in episodes if item["total_views"] >= min_sample_views
    ]

    high_interaction_episodes = sorted(
        [
            item
            for item in high_sample_episodes
            if item["interaction_rate"] is not None and item["interaction_rate"] > 0
        ],
        key=lambda item: (item["interaction_rate"], item["total_views"]),
        reverse=True,
    )[:10]

    high_share_episodes = sorted(
        [
            item
            for item in high_sample_episodes
            if item["share_rate"] is not None and item["share_rate"] > 0
        ],
        key=lambda item: (item["share_rate"], item["total_views"]),
        reverse=True,
    )[:10]

    high_exposure_low_valid_episodes = [
        {
            **_public_episode_fields(item),
            "valid_play_rate": item["valid_play_rate"],
            "reason": "播放量高于中位数，但有效播放率低于中位数",
        }
        for item in episodes
        if item["total_views"] > median_views
        and item["valid_play_rate"] is not None
        and item["valid_play_rate"] < median_valid_rate
    ]

    episode_drop_off_ranking = _build_drop_off_ranking(episodes)

    return {
        "episode_count": len(episodes),
        "sample_threshold": {
            "median_total_views": median_views,
            "min_total_views_for_high_interaction_or_share": min_sample_views,
        },
        "episodes": [_public_episode_fields(item) for item in episodes],
        "episode_drop_off_ranking": episode_drop_off_ranking,
        "high_interaction_episodes": [
            {
                **_public_episode_fields(item),
                "interaction_rate": item["interaction_rate"],
            }
            for item in high_interaction_episodes
        ],
        "high_share_episodes": [
            {
                **_public_episode_fields(item),
                "share_rate": item["share_rate"],
            }
            for item in high_share_episodes
        ],
        "high_exposure_low_valid_episodes": high_exposure_low_valid_episodes,
        "script_review_suggestions": _build_script_review_suggestions(
            has_low_valid=bool(high_exposure_low_valid_episodes),
            has_drop_off=bool(episode_drop_off_ranking),
            has_high_engagement=bool(high_interaction_episodes or high_share_episodes),
        ),
    }


def extract_episode_no(title: Any) -> int | None:
    text = str(title or "")
    for pattern in TITLE_EPISODE_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return None


def _build_drop_off_ranking(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    numbered = sorted(
        [item for item in episodes if isinstance(item.get("episode_no"), int)],
        key=lambda item: item["episode_no"],
    )
    ranking: list[dict[str, Any]] = []
    for previous, current in zip(numbered, numbered[1:]):
        previous_views = previous["total_views"]
        current_views = current["total_views"]
        previous_valid_views = previous["total_valid_views"]
        current_valid_views = current["total_valid_views"]
        views_drop_rate = _drop_rate(previous_views, current_views)
        valid_views_drop_rate = _drop_rate(previous_valid_views, current_valid_views)
        if (views_drop_rate or 0) <= 0 and (valid_views_drop_rate or 0) <= 0:
            continue
        ranking.append(
            {
                "episode_no": current["episode_no"],
                "title": current["title"],
                "previous_episode_no": previous["episode_no"],
                "previous_title": previous["title"],
                "total_views": current_views,
                "previous_total_views": previous_views,
                "views_drop_rate": views_drop_rate,
                "total_valid_views": current_valid_views,
                "previous_total_valid_views": previous_valid_views,
                "valid_views_drop_rate": valid_views_drop_rate,
            }
        )
    return sorted(
        ranking,
        key=lambda item: item["valid_views_drop_rate"] if item["valid_views_drop_rate"] is not None else -1,
        reverse=True,
    )[:10]


def _build_script_review_suggestions(
    *,
    has_low_valid: bool,
    has_drop_off: bool,
    has_high_engagement: bool,
) -> list[str]:
    suggestions: list[str] = []
    if has_low_valid:
        suggestions.append("高曝光低有效集数：复盘前30秒、标题封面预期、本集冲突推进是否一致。")
    if has_drop_off:
        suggestions.append("掉点集数：复盘上一集结尾钩子强度，以及本集开场对上一集悬念的承接。")
    if has_high_engagement:
        suggestions.append("高互动/高分享集数：提取可复用的情绪点、反转点、话题点。")
    if not suggestions:
        suggestions.append("当前未命中明显异常榜单，可优先保持现有节奏并继续观察新增样本。")
    return suggestions


def _normalize_episode(row: dict[str, Any]) -> dict[str, Any]:
    title = str(_first_value(row, "title") or "").strip()
    episode_no = _to_int(_first_value(row, "episode_no"))
    if episode_no is None:
        episode_no = extract_episode_no(title)
    total_views = _to_float(_first_value(row, "total_views")) or 0.0
    total_valid_views = _to_float(_first_value(row, "total_valid_views")) or 0.0
    share_count = _to_float(_first_value(row, "share_count")) or 0.0
    like_count = _to_float(_first_value(row, "like_count")) or 0.0
    comment_count = _to_float(_first_value(row, "comment_count")) or 0.0
    favorite_count = _to_float(_first_value(row, "favorite_count")) or 0.0
    total_interactions = like_count + comment_count + share_count + favorite_count
    return {
        "title": title,
        "episode_no": episode_no,
        "total_views": total_views,
        "total_valid_views": total_valid_views,
        "share_count": share_count,
        "like_count": like_count,
        "comment_count": comment_count,
        "favorite_count": favorite_count,
        "valid_play_rate": _safe_rate(total_valid_views, total_views),
        "share_rate": _safe_rate(share_count, total_views),
        "interaction_rate": _safe_rate(total_interactions, total_views),
    }


def _public_episode_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "episode_no": item.get("episode_no"),
        "title": item.get("title", ""),
        "total_views": item.get("total_views", 0.0),
        "total_valid_views": item.get("total_valid_views", 0.0),
        "share_count": item.get("share_count", 0.0),
        "like_count": item.get("like_count", 0.0),
        "comment_count": item.get("comment_count", 0.0),
    }


def _first_value(row: dict[str, Any], field: str) -> Any:
    for key in FIELD_ALIASES[field]:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _drop_rate(previous: float, current: float) -> float | None:
    if previous <= 0:
        return None
    return (previous - current) / previous


def _safe_rate(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    if number is None:
        return None
    return int(number)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    multiplier = 1.0
    if text.endswith("万"):
        multiplier = 10000.0
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100000000.0
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None
