from __future__ import annotations

import unittest

from workflow_code_skeleton.app.utils.episode import (
    build_episode_batches,
    build_episode_batches_from_start,
    validate_rewrite_start_episode,
)


class EpisodeBatchTests(unittest.TestCase):
    def test_build_episode_batches_uses_fixed_five_episode_windows(self) -> None:
        self.assertEqual(build_episode_batches(1), [{"start": 1, "end": 1}])
        self.assertEqual(build_episode_batches(3), [{"start": 1, "end": 3}])
        self.assertEqual(build_episode_batches(5), [{"start": 1, "end": 5}])
        self.assertEqual(
            build_episode_batches(6),
            [{"start": 1, "end": 5}, {"start": 6, "end": 6}],
        )
        self.assertEqual(
            build_episode_batches(10),
            [{"start": 1, "end": 5}, {"start": 6, "end": 10}],
        )
        self.assertEqual(
            build_episode_batches(11),
            [{"start": 1, "end": 5}, {"start": 6, "end": 10}, {"start": 11, "end": 11}],
        )
        self.assertEqual(
            build_episode_batches(12),
            [{"start": 1, "end": 5}, {"start": 6, "end": 10}, {"start": 11, "end": 12}],
        )
        self.assertEqual(
            build_episode_batches(15),
            [{"start": 1, "end": 5}, {"start": 6, "end": 10}, {"start": 11, "end": 15}],
        )

    def test_validate_rewrite_start_episode_only_accepts_batch_aligned_starts(self) -> None:
        self.assertEqual(validate_rewrite_start_episode(1, 15), 1)
        self.assertEqual(validate_rewrite_start_episode(6, 15), 6)
        self.assertEqual(validate_rewrite_start_episode(11, 15), 11)

        for invalid_start in (0, -1, 2, 3, 4, 5, 7, 8, 9, 10, 16):
            with self.subTest(start_episode=invalid_start):
                with self.assertRaisesRegex(ValueError, "回退重写只能从每个五集批次的起点开始"):
                    validate_rewrite_start_episode(invalid_start, 15)

    def test_build_episode_batches_from_start_only_returns_remaining_batches(self) -> None:
        self.assertEqual(
            build_episode_batches_from_start(6, 15),
            [{"start": 6, "end": 10}, {"start": 11, "end": 15}],
        )
        self.assertEqual(
            build_episode_batches_from_start(6, 12),
            [{"start": 6, "end": 10}, {"start": 11, "end": 12}],
        )
        self.assertEqual(
            build_episode_batches_from_start(11, 12),
            [{"start": 11, "end": 12}],
        )


if __name__ == "__main__":
    unittest.main()
