from __future__ import annotations

from pathlib import Path
import unittest


JAVASCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "web"
    / "static"
    / "framework_to_script.js"
)


class FrameworkToScriptStage10RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.javascript = JAVASCRIPT_PATH.read_text(encoding="utf-8")

    def test_old_success_is_not_mistaken_for_current_rerun(self) -> None:
        self.assertIn("function stageResultBelongsToCurrentRun(stage)", self.javascript)
        self.assertIn(
            "updatedAt >= startedAt - 2000",
            self.javascript,
        )
        self.assertNotIn(
            "if (state.runningStage && stageHasCompleted(state.runningStage))",
            self.javascript,
        )

    def test_clearing_stage_also_removes_stale_active_run(self) -> None:
        self.assertIn(
            "state.stageRuns = (state.stageRuns || []).filter",
            self.javascript,
        )
        self.assertIn(
            "state.activeRun = null;",
            self.javascript,
        )

    def test_failed_rerun_restores_previous_success(self) -> None:
        self.assertIn(
            "已保留上一次成功的第 10 阶段结果",
            self.javascript,
        )


if __name__ == "__main__":
    unittest.main()
