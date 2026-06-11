from __future__ import annotations

import uuid
import unittest
from unittest.mock import patch

from workflow_code_skeleton.app.server import create_app
from workflow_code_skeleton.app.services.auth_store import auth_store


def _auth_headers() -> dict[str, str]:
    username = f"rb{uuid.uuid4().hex[:8]}"
    user = auth_store.register_user(username, "password123")
    token = auth_store.create_session_token(user.id)
    return {"Authorization": f"Bearer {token}"}


class ServerRollbackApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.headers = _auth_headers()

    def test_rollback_api_surfaces_invalid_batch_start_message(self) -> None:
        with patch(
            "workflow_code_skeleton.app.server.task_manager.rollback_project_to_stage",
            side_effect=ValueError("回退重写只能从每个五集批次的起点开始，例如第 1、6、11 集。"),
        ):
            response = self.client.post(
                "/api/projects/1/rollback",
                headers=self.headers,
                json={"stage_key": "script", "start_episode": 2},
            )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertIn("五集批次的起点开始", payload["message"])


if __name__ == "__main__":
    unittest.main()
