from __future__ import annotations

from ..models.state import WorkflowState


def sync_runtime_state(state: WorkflowState) -> None:
    runtime = state.runtime
    if runtime:
        runtime.sync_from_state(state)


def set_runtime_stage(
    state: WorkflowState,
    stage_key: str,
    message: str,
    *,
    batch_label: str | None = None,
    progress_percent: int | None = None,
    generated_episodes: int | None = None,
) -> None:
    runtime = state.runtime
    if runtime:
        runtime.set_stage(
            stage_key,
            message,
            batch_label=batch_label,
            progress_percent=progress_percent,
            generated_episodes=generated_episodes,
        )
