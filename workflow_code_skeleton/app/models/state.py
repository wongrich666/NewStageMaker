from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .inputs import WorkflowInput
from ..workflow_ids import (
    CHARACTER_BIOS_VAR,
    CORE_SCENE_INPUT_VAR,
    EPISODE_PLAN_VAR,
    EPISODE_WORD_COUNT_VAR,
    STORY_OUTLINE_VAR,
    TITLE_VAR,
    TOTAL_EPISODES_VAR,
)


@dataclass(slots=True)
class ReviewResult:
    approved: bool
    rewrite_required: bool = False
    summary: str = ""
    suggestions: list[str] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)
    non_blocking_issues: list[str] = field(default_factory=list)
    rewrite_start_episode: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowState:
    user_input: WorkflowInput
    variables: dict[str, Any] = field(default_factory=dict)
    node_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    halted_message: str | None = None
    final_output_text: str = ""
    preferred_provider: str | None = None
    preferred_model: str | None = None
    runtime: Any = None
    prompt_fixes: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_defaults(
        cls,
        *,
        user_input: WorkflowInput,
        default_variables: dict[str, Any],
    ) -> "WorkflowState":
        state = cls(user_input=user_input, variables=dict(default_variables))
        state.variables.update(
            {
                TITLE_VAR: user_input.title,
                EPISODE_WORD_COUNT_VAR: user_input.episode_word_count,
                TOTAL_EPISODES_VAR: user_input.total_episodes,
                STORY_OUTLINE_VAR: user_input.story_outline,
                CORE_SCENE_INPUT_VAR: user_input.core_scene_input,
                CHARACTER_BIOS_VAR: user_input.character_bios,
                EPISODE_PLAN_VAR: user_input.episode_plan,
            }
        )
        return state

    def get_var(self, key: str, default: Any = "") -> Any:
        return self.variables.get(key, default)

    def get_int_var(self, key: str, default: int = 0) -> int:
        value = self.variables.get(key, default)
        if value in (None, ""):
            return default
        return int(value)

    def set_var(self, key: str, value: Any) -> None:
        self.variables[key] = value

    def append_text_var(self, key: str, text: str) -> str:
        current = str(self.get_var(key, "") or "").strip()
        incoming = str(text or "").strip()
        if not current:
            combined = incoming
        elif not incoming:
            combined = current
        else:
            combined = f"{current}\n\n{incoming}"
        self.set_var(key, combined)
        return combined

    def get_output(self, node_id: str, key: str, default: Any = "") -> Any:
        return self.node_outputs.get(node_id, {}).get(key, default)

    def set_output(self, node_id: str, key: str, value: Any) -> None:
        self.node_outputs.setdefault(node_id, {})[key] = value

    def as_debug_dict(self) -> dict[str, Any]:
        return {
            "user_input": {
                "title": self.user_input.title,
                "episode_word_count": self.user_input.episode_word_count,
                "total_episodes": self.user_input.total_episodes,
                "story_outline": self.user_input.story_outline,
                "core_scene_input": self.user_input.core_scene_input,
                "character_bios": self.user_input.character_bios,
                "episode_plan": self.user_input.episode_plan,
            },
            "halted_message": self.halted_message,
            "final_output_text": self.final_output_text,
            "preferred_provider": self.preferred_provider,
            "preferred_model": self.preferred_model,
            "prompt_fixes": self.prompt_fixes,
            "variables": self.variables,
            "node_outputs": self.node_outputs,
        }
