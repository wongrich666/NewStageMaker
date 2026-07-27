from __future__ import annotations

import json
import logging
import os
from typing import Any

from .deepseek_agent import DeepSeekAgentClient, deepseek_agent_client


logger = logging.getLogger(__name__)


def _positive_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _compact_framework_context(package: dict[str, Any]) -> dict[str, Any]:
    return {
        key: package.get(key)
        for key in (
            "basic_config",
            "source_brief",
            "worldview_plan",
            "character_plan",
            "beat_checkpoint_timeline",
            "character_storylines",
            "adaptation_guide",
        )
        if package.get(key) not in (None, "", [], {})
    }


def _text_view(item: dict[str, Any]) -> str:
    episode = _positive_int(item.get("episode"), 0)
    characters = "、".join(str(value) for value in item.get("characters") or [])
    scenes = "、".join(str(value) for value in item.get("scenes") or [])
    pressure = "；".join(str(value) for value in item.get("pressure_sources") or [])
    return "\n".join(
        (
            f"第{episode}集",
            f"标题：{item.get('title') or ''}",
            f"人物：{characters}",
            f"场景：{scenes}",
            f"具体情节安排：{item.get('specific_plot') or ''}",
            f"压力来源：{pressure}",
            f"结尾钩子：{item.get('ending_hook') or ''}",
        )
    )


def _normalize_plan(raw_plan: Any, total_episodes: int) -> list[dict[str, Any]]:
    if not isinstance(raw_plan, list):
        raise ValueError("DeepSeek 兜底输出缺少 episodes 数组。")

    required_text = ("title", "specific_plot", "ending_hook", "alias_notes")
    required_lists = (
        "characters",
        "scene_refs",
        "scenes",
        "pressure_sources",
        "beat_refs",
        "character_storyline_refs",
    )
    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw_item in raw_plan:
        if not isinstance(raw_item, dict):
            raise ValueError("DeepSeek 兜底输出包含非对象分集。")
        episode = _positive_int(raw_item.get("episode"), 0)
        if episode < 1 or episode > total_episodes or episode in seen:
            raise ValueError(f"DeepSeek 兜底输出集数无效或重复：{episode}。")
        seen.add(episode)
        item = {"episode": episode}
        for key in required_text:
            value = str(raw_item.get(key) or "").strip()
            if not value:
                raise ValueError(f"DeepSeek 兜底第 {episode} 集缺少 {key}。")
            item[key] = value
        for key in required_lists:
            value = raw_item.get(key)
            if not isinstance(value, list) or not value:
                raise ValueError(f"DeepSeek 兜底第 {episode} 集缺少 {key}。")
            item[key] = [str(entry).strip() for entry in value if str(entry).strip()]
            if not item[key]:
                raise ValueError(f"DeepSeek 兜底第 {episode} 集缺少 {key}。")
        if len(item["scene_refs"]) > 2 or len(item["scenes"]) > 2:
            raise ValueError(f"DeepSeek 兜底第 {episode} 集超过两个核心场景。")
        item["text_view"] = _text_view(item)
        normalized.append(item)

    expected = set(range(1, total_episodes + 1))
    if seen != expected:
        missing = sorted(expected - seen)
        raise ValueError(f"DeepSeek 兜底输出缺集：{missing}。")
    return sorted(normalized, key=lambda item: item["episode"])


def generate_stage10_plan(
    *,
    framework_plan_package: dict[str, Any],
    scene_dictionary: dict[str, Any],
    appearance_mapping: dict[str, Any],
    preference_prompt: str = "",
    client: DeepSeekAgentClient = deepseek_agent_client,
) -> tuple[list[dict[str, Any]], str]:
    basic = framework_plan_package.get("basic_config")
    basic = basic if isinstance(basic, dict) else {}
    total_episodes = _positive_int(
        basic.get("episodes_per_season")
        or basic.get("total_episodes")
        or framework_plan_package.get("episodes_per_season")
        or framework_plan_package.get("total_episodes"),
        0,
    )
    if not total_episodes:
        raise ValueError("无法确定第 10 阶段总集数。")

    context = {
        "framework": _compact_framework_context(framework_plan_package),
        "sceneDictionary": scene_dictionary,
        "appearanceMapping": appearance_mapping,
        "preference": str(preference_prompt or "").strip(),
    }
    prompt = f"""
生成第 10 阶段完整丰富分集计划，共 {total_episodes} 集。

只返回 JSON object，顶层只能是 episodes。episodes 必须从 1 连续到 {total_episodes}，不得缺集、重复或省略。
每集只输出一次结构化数据，不要输出 text_view，不要重复生成人类可读版本。

每集字段：
- episode: 整数
- title: 标题
- characters: "人物名(outfit_id)" 数组，outfit_id 必须来自 appearanceMapping
- scene_refs: sceneDictionary 场景 ID 数组，默认 1 个，最多 2 个
- scenes: 与 scene_refs 对应的场景短名称数组
- specific_plot: 按“承接前集钩子 -> 当下目标 -> 具体阻力 -> 人物选择 -> 结果变化 -> 本集钩子”写成连续因果链
- pressure_sources: 至少包含外部压力和关系或内在压力
- ending_hook: 下一集可以直接承接的具体动作、发现、选择或危险
- beat_refs: 对应十五节拍
- character_storyline_refs: 主线及至少一条人物/关系线
- alias_notes: 逐人说明 outfit_id 来源

硬约束：
1. 不改变上游故事、人物、十五节拍顺序和总集数。
2. 除第 1 集外，每集开头必须直接承接上一集 ending_hook。
3. 默认一集一个核心场景；确有不可替代转场时最多两个，禁止第三个场景。
4. 不写剧本正文和完整对白，不使用万能证据，不新增上游不存在的关键人物。
5. 必须完整输出全部 {total_episodes} 集，禁止“其余省略”等占位内容。

输入资料：
{json.dumps(context, ensure_ascii=False, separators=(",", ":"))}
""".strip()

    try:
        max_tokens = max(
            8192,
            min(65536, int(os.getenv("FRAMEWORK_STAGE10_FALLBACK_MAX_TOKENS", "32768"))),
        )
    except ValueError:
        max_tokens = 32768
    result = client.complete_json(
        prompt,
        system_prompt="你是第10阶段丰富分集计划生成器，只输出合法 JSON 对象。",
        max_tokens=max_tokens,
        timeout_seconds=600,
    )
    structured = result.get("structured_output")
    structured = structured if isinstance(structured, dict) else {}
    plan = _normalize_plan(
        structured.get("episodes")
        or structured.get("allEnrichedEpisodePlan"),
        total_episodes,
    )
    plan_text = "\n\n".join(item["text_view"] for item in plan)
    usage = result.get("usage")
    logger.info(
        "framework stage10 direct fallback completed: episodes=%s model=%s usage=%s",
        len(plan),
        result.get("model"),
        usage if isinstance(usage, dict) else {},
    )
    return plan, plan_text
