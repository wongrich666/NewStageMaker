from __future__ import annotations

import unittest

from workflow_code_skeleton.app.services.tencent_workflow_registry import (
    build_workflow_inputs,
    workflow_spec,
)


class Stage04TotalEpisodesMappingTests(unittest.TestCase):
    def test_registry_declares_remote_total_episodes_input(self) -> None:
        self.assertIn("total_episodes", workflow_spec("04").input_names)

    def test_total_episodes_is_sent_as_top_level_string(self) -> None:
        payload = build_workflow_inputs(
            "04",
            {
                "basic_config": {
                    "season_count": 1,
                    "episodes_per_season": 48,
                    "total_episodes": 48,
                },
                "total_episodes": 48,
            },
        )

        self.assertEqual("48", payload["total_episodes"])
        self.assertIn('"total_episodes":48', payload["basic_config"])

    def test_legacy_episodes_number_alias_is_supported(self) -> None:
        payload = build_workflow_inputs("04", {"episodes_number": 36})
        self.assertEqual("36", payload["total_episodes"])


if __name__ == "__main__":
    unittest.main()
