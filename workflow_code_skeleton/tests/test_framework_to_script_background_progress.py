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


class FrameworkToScriptBackgroundProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.javascript = JAVASCRIPT_PATH.read_text(encoding="utf-8")

    def test_visible_run_status_explains_why_button_is_locked(self) -> None:
        self.assertIn("scriptRunStatusText(run)", self.javascript)
        self.assertIn("后台生成中", self.javascript)
        self.assertIn("后台正从第", self.javascript)

    def test_progress_uses_fresher_of_run_and_saved_asset(self) -> None:
        self.assertIn(
            "const doneCount = Math.max(completed.length, fallbackDone.length);",
            self.javascript,
        )
        self.assertIn("fallbackExpected.length", self.javascript)

    def test_in_progress_preview_is_not_counted_as_saved_batch(self) -> None:
        self.assertIn(
            'batchPipelineStatus: partial.batchPipelineStatus || partial.batch_pipeline_status || "running"',
            self.javascript,
        )
        self.assertIn(
            'if (pipelineStatus) return pipelineStatus === "complete" && hasCore;',
            self.javascript,
        )

    def test_missing_background_run_releases_stale_button_lock(self) -> None:
        self.assertIn("requestError.status = response.status;", self.javascript)
        self.assertIn("Number(error && error.status) === 404", self.javascript)
        self.assertIn("stopRunPolling();", self.javascript)
        self.assertIn("clearRunningStage(staleStage);", self.javascript)
        self.assertIn("上次后台运行已结束，已恢复到最近保存进度。", self.javascript)

    def test_saved_batch_immediately_clears_generating_badge(self) -> None:
        self.assertIn(
            'const savedBatch = stage11BatchMap({ completeOnly: true })[String(startEpisode || "")];',
            self.javascript,
        )
        self.assertIn(
            "if (savedBatch && isStage11BatchComplete(savedBatch)) return false;",
            self.javascript,
        )
        self.assertIn("let savedBatchAdvanced = false;", self.javascript)
        self.assertIn("if (assetChanged || savedBatchAdvanced)", self.javascript)


if __name__ == "__main__":
    unittest.main()
