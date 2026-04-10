from __future__ import annotations

from dataclasses import dataclass


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


def iter_episode_batches(total_episodes: int, batch_size: int = 5):
    start = 1
    while start <= total_episodes:
        yield BatchWindow.from_start(start, total_episodes, batch_size=batch_size)
        start += batch_size
