from __future__ import annotations

from pathlib import Path
import re
import unittest


STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "web" / "static"


class FrameworkAssetImportPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.javascript = (STATIC_DIR / "framework_planner.js").read_text(encoding="utf-8")
        match = re.search(
            r"async function openAsset\(projectId\) \{(?P<body>.*?)"
            r"\n  \}\n\n  async function controlAssetTask",
            cls.javascript,
            flags=re.DOTALL,
        )
        if match is None:
            raise AssertionError("openAsset function was not found")
        cls.open_asset_body = match.group("body")

    def test_import_does_not_wait_for_stage_history(self):
        self.assertNotIn("loadStageHistory(", self.open_asset_body)

    def test_successful_import_persists_state_only_once(self):
        self.assertEqual(self.open_asset_body.count("saveState();"), 1)
        self.assertIn("render({ skipSync: true, skipPersist: true });", self.open_asset_body)

    def test_large_package_details_are_deferred(self):
        self.assertIn("ui.packageDetailsExpanded = false;", self.javascript)
        self.assertIn('data-action="toggle-package-details"', self.javascript)
        self.assertIn("详细字段改为按需渲染", self.javascript)

    def test_success_toast_does_not_trigger_another_full_render(self):
        self.assertIn('showToast("资产导入成功", { render: false });', self.open_asset_body)


if __name__ == "__main__":
    unittest.main()
