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


@dataclass(slots=True)
class WorkflowInput:
    title: str
    episode_word_count: int
    total_episodes: int
    story_outline: str
    core_scene_input: str
    character_bios: str
    episode_plan: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowInput":
        return cls(
            title=str(
                _pick(data, "title", "script_title", "剧本标题", default="")
            ).strip(),
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
        if not self.story_outline:
            raise ValueError("story_outline / 故事大纲 不能为空")
        if not self.character_bios:
            raise ValueError("character_bios / 人物小传 不能为空")
        if not self.episode_plan:
            raise ValueError("episode_plan / 分集计划 不能为空")
