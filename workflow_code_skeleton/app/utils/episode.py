from __future__ import annotations

from dataclasses import dataclass


def _normalized_batch_size(batch_size: int = 5) -> int:
    return max(1, int(batch_size or 5))


def rewrite_start_validation_message(batch_size: int = 5) -> str:
    normalized = _normalized_batch_size(batch_size)
    prefix = "回退重写只能从每个五集批次的起点开始" if normalized == 5 else f"回退重写只能从每个 {normalized} 集批次的起点开始"
    examples = "、".join(str(1 + normalized * index) for index in range(3))
    return f"{prefix}，例如第 {examples} 集。"


@dataclass(frozen=True, slots=True)
class BatchWindow:
    start_episode: int
    end_episode: int

    @classmethod
    def from_start(
        cls, start_episode: int, total_episodes: int, batch_size: int = 5
    ) -> "BatchWindow":
        end_episode = min(start_episode + batch_size - 1, total_episodes)
        return cls(start_episode=start_episode, end_episode=end_episode)

    @property
    def label(self) -> str:
        return f"{self.start_episode}-{self.end_episode}"

    @property
    def size(self) -> int:
        return self.end_episode - self.start_episode + 1


def build_episode_batches(total_episodes: int, batch_size: int = 5) -> list[dict[str, int]]:
    total = max(0, int(total_episodes or 0))
    normalized = _normalized_batch_size(batch_size)
    if total <= 0:
        return []
    return [
        {
            "start": batch.start_episode,
            "end": batch.end_episode,
        }
        for batch in iter_episode_batches(total, batch_size=normalized)
    ]


def validate_rewrite_start_episode(
    start_episode: int,
    total_episodes: int,
    batch_size: int = 5,
) -> int:
    total = max(0, int(total_episodes or 0))
    normalized = _normalized_batch_size(batch_size)
    try:
        start = int(start_episode)
    except (TypeError, ValueError) as exc:
        raise ValueError(rewrite_start_validation_message(normalized)) from exc
    if start < 1 or start > total or (start - 1) % normalized != 0:
        raise ValueError(rewrite_start_validation_message(normalized))
    return start


def build_episode_batches_from_start(
    start_episode: int,
    total_episodes: int,
    batch_size: int = 5,
) -> list[dict[str, int]]:
    start = validate_rewrite_start_episode(
        start_episode,
        total_episodes,
        batch_size=batch_size,
    )
    return [
        batch
        for batch in build_episode_batches(total_episodes, batch_size=batch_size)
        if batch["start"] >= start
    ]


def iter_episode_batches(total_episodes: int, batch_size: int = 5):
    start = 1
    while start <= total_episodes:
        yield BatchWindow.from_start(start, total_episodes, batch_size=batch_size)
        start += batch_size


def iter_episode_batches_from(
    start_episode: int,
    total_episodes: int,
    batch_size: int = 5,
):
    for batch in build_episode_batches_from_start(
        start_episode,
        total_episodes,
        batch_size=batch_size,
    ):
        yield BatchWindow(
            start_episode=int(batch["start"]),
            end_episode=int(batch["end"]),
        )
