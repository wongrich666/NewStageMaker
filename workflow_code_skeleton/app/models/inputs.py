from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _pick(data: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def derive_script_title(*candidates: Any) -> str:
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        compact = " ".join(text.split())
        return compact[:32] or "AI原创剧本"
    return "AI原创剧本"


@dataclass(slots=True)
class WorkflowInput:
    title: str
    episode_word_count: int
    total_episodes: int
    user_expectation: str
    character_count: int
    character_appearance_requirements: str
    character_alias_naming_rules: str
    outfit_switch_rules: str
    story_outline: str
    core_scene_input: str
    character_bios: str
    episode_plan: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowInput":
        user_expectation = str(
            _pick(
                data,
                "user_expectation",
                "expectation",
                "用户期待",
                "用户想要的故事",
                default="",
            )
        ).strip()
        return cls(
            title=str(
                _pick(
                    data,
                    "title",
                    "script_title",
                    "剧本标题",
                    default=derive_script_title(user_expectation),
                )
            ).strip()
            or derive_script_title(user_expectation),
            episode_word_count=int(
                _pick(
                    data,
                    "episode_word_count",
                    "per_episode_word_count",
                    "每集正文字数",
                    default=500,
                )
            ),
            total_episodes=int(
                _pick(data, "total_episodes", "总集数", default=0)
            ),
            user_expectation=user_expectation,
            character_count=int(
                _pick(data, "character_count", "角色数量", default=0)
            ),
            character_appearance_requirements=str(
                _pick(
                    data,
                    "character_appearance_requirements",
                    "appearance_requirements",
                    "服装版本需求",
                    "人物服装要求",
                    default="",
                )
            ).strip(),
            character_alias_naming_rules=str(
                _pick(
                    data,
                    "character_alias_naming_rules",
                    "alias_naming_rules",
                    "命名偏好",
                    "人物别名命名规则",
                    default="",
                )
            ).strip(),
            outfit_switch_rules=str(
                _pick(
                    data,
                    "outfit_switch_rules",
                    "服装切换规则",
                    "换装规则",
                    default="",
                )
            ).strip(),
            story_outline=str(
                _pick(data, "story_outline", "故事大纲", default="")
            ).strip(),
            core_scene_input=str(
                _pick(data, "core_scene_input", "核心场景", default="")
            ).strip(),
            character_bios=str(
                _pick(data, "character_bios", "人物小传", default="")
            ).strip(),
            episode_plan=str(
                _pick(data, "episode_plan", "分集计划", default="")
            ).strip(),
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> "WorkflowInput":
        file_path = Path(path)
        data = json.loads(file_path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("输入文件必须是 JSON object")
        return cls.from_dict(data)

    def validate(self) -> None:
        if self.total_episodes <= 0:
            raise ValueError("total_episodes / 总集数 必须大于 0")
        if self.episode_word_count <= 0:
            raise ValueError("episode_word_count / 每集正文字数 必须大于 0")
        has_full_outline = bool(self.story_outline and self.character_bios and self.episode_plan)
        has_framework_prompt = bool(self.user_expectation and self.character_count > 0)
        if not has_full_outline and not has_framework_prompt:
            raise ValueError(
                "请提供完整的故事大纲/人物小传/分集计划，或至少提供 user_expectation / 用户期待 和 character_count / 角色数量"
            )
