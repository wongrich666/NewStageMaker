from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from workflow_code_skeleton.app.services.stage10_resume import (
    load_stage10_resume,
    save_stage10_resume,
    stage10_input_fingerprint,
)


class Stage10ResumeTests(unittest.TestCase):
    def test_stage10_resume_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "stage10_resume.json"
            fingerprint = stage10_input_fingerprint({"asset": 22, "input": {"title": "测试"}})
            episodes = {
                1: {"episode": 1, "title": "第一集"},
                2: {"episode": 2, "title": "第二集"},
            }
            save_stage10_resume(
                path,
                status="partial",
                fingerprint=fingerprint,
                asset_id="22",
                total_episodes=48,
                batch_size=8,
                episodes=episodes,
                text_by_batch={"1": "第一至八集"},
                updated_at="2026-08-05T18:00:00+08:00",
            )

            restored = load_stage10_resume(
                path,
                fingerprint=fingerprint,
                asset_id="22",
                total_episodes=48,
                batch_size=8,
            )

            self.assertIsNotNone(restored)
            self.assertEqual(sorted(restored["episodes"]), [1, 2])
            self.assertEqual(restored["text_by_batch"], {"1": "第一至八集"})

    def test_stage10_resume_rejects_completed_or_changed_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "stage10_resume.json"
            fingerprint = stage10_input_fingerprint({"asset": 22})
            save_stage10_resume(
                path,
                status="completed",
                fingerprint=fingerprint,
                asset_id="22",
                total_episodes=48,
                batch_size=8,
                episodes={1: {"episode": 1}},
                text_by_batch={},
                updated_at="2026-08-05T18:00:00+08:00",
            )

            self.assertIsNone(load_stage10_resume(
                path,
                fingerprint=fingerprint,
                asset_id="22",
                total_episodes=48,
                batch_size=8,
            ))
            self.assertIsNone(load_stage10_resume(
                path,
                fingerprint="different",
                asset_id="22",
                total_episodes=48,
                batch_size=8,
            ))


if __name__ == "__main__":
    unittest.main()
