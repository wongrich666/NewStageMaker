from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from workflow_code_skeleton.app.server import create_app
from workflow_code_skeleton.app.services.auth_store import auth_store


class FrameworkToScriptRunRecoveryTests(unittest.TestCase):
    def test_missing_in_memory_run_returns_recoverable_terminal_state(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        user = SimpleNamespace(id=139, username="test-user")

        with patch.object(auth_store, "get_user_by_token", return_value=user):
            response = app.test_client().get(
                "/api/framework-to-script/runs/missing-after-restart",
                headers={"Authorization": "Bearer local-test"},
            )

        self.assertEqual(200, response.status_code)
        run = response.get_json()["run"]
        self.assertEqual("failed", run["status"])
        self.assertTrue(run["recoverable"])
        self.assertTrue(run["missing_run_record"])
        self.assertEqual("", run["asset_id"])


if __name__ == "__main__":
    unittest.main()
