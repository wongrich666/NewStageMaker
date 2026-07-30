from __future__ import annotations

from types import SimpleNamespace


class _FakeAuth:
    @staticmethod
    def get_user(user_id):
        if int(user_id) == 7:
            return SimpleNamespace(id=7, username="writer")
        return None

    @staticmethod
    def get_user_by_token(token):
        if token == "writer-token":
            return SimpleNamespace(id=7, username="writer")
        return None


def _install_fakes(
    monkeypatch,
    *,
    refresh_fails: bool = False,
    refresh_replaces_build: bool = False,
    refresh_result_pending: bool = False,
):
    from workflow_code_skeleton.app import server

    state = {"job": None, "stage_calls": [], "full_calls": 0, "fallback_calls": []}

    class FakeStore:
        def __init__(self, _config):
            pass

        def create(self, *, user_id, request_payload):
            job = {
                "job_id": "npc-orchestration-test",
                "user_id": user_id,
                "status": "created",
                "status_text": "",
                "progress": 0,
                "request": dict(request_payload),
                "execution_mode": request_payload.get("execution_mode") or "step",
                "execution_target": "remote_cnb",
                "remote_kind": "",
                "remote_stage": "",
                "remote_retry_count": 0,
                "remote_retry_limit": 0,
                "active_stage": "",
                "build": {},
                "recovered_files": {},
                "stage_outputs": {},
                "stage_versions": {},
                "final_script": "",
                "error": "",
            }
            return self.save(job)

        def save(self, job):
            state["job"] = dict(job)
            return state["job"]

        def load(self, job_id, *, user_id):
            job = state["job"]
            if job and job_id == job["job_id"] and user_id == job["user_id"]:
                return dict(job)
            return None

        def latest(self, *, user_id):
            return self.load("npc-orchestration-test", user_id=user_id)

        def list(self, *, user_id):
            job = self.latest(user_id=user_id)
            return [job] if job else []

    class FakeClient:
        def __init__(self, _config):
            pass

        def trigger(self, _job):
            state["full_calls"] += 1
            raise AssertionError("new auto jobs must not use the monolithic build")

        def trigger_stage(self, _job, *, stage, feedback, continue_after):
            state["stage_calls"].append(
                {
                    "stage": stage,
                    "feedback": feedback,
                    "continue_after": continue_after,
                }
            )
            return {"sn": f"build-{len(state['stage_calls'])}"}

        def refresh(self, job):
            updated = dict(job)
            if refresh_result_pending:
                updated["status"] = "result_pending"
            if refresh_replaces_build:
                newer = dict(state["job"])
                newer["build"] = {"sn": "build-newer"}
                newer["status"] = "running"
                newer["remote_stage"] = "story_architect"
                state["job"] = newer
                updated["status"] = "result_pending"
            if refresh_fails:
                updated["status"] = "failed"
                updated["error"] = "remote stage failed"
            return updated

    class FakeRunner:
        def __init__(self, _store):
            pass

        @staticmethod
        def is_running(_job_id):
            return False

        def start(self, *, job_id, user_id, stage, continue_after):
            state["fallback_calls"].append(
                {
                    "job_id": job_id,
                    "user_id": user_id,
                    "stage": stage,
                    "continue_after": continue_after,
                }
            )
            updated = dict(state["job"])
            updated["status"] = "running"
            updated["execution_target"] = "local_fallback"
            updated["active_stage"] = stage
            state["job"] = updated
            return updated

    monkeypatch.setattr(server, "auth_store", _FakeAuth())
    monkeypatch.setattr(server, "CodeBuddyNpcJobStore", FakeStore)
    monkeypatch.setattr(server, "CodeBuddyNpcClient", FakeClient)
    monkeypatch.setattr(server, "CodeBuddyNpcStageRunner", FakeRunner)
    return server, state


def test_auto_job_starts_remote_stage_chain_instead_of_full_build(monkeypatch):
    server, state = _install_fakes(monkeypatch)
    app = server.create_app()
    app.config.update(TESTING=True)

    response = app.test_client().post(
        "/api/new-workflow-test/npc/jobs",
        headers={"Authorization": "Bearer writer-token"},
        json={
            "project_title": "逐节点保存测试",
            "source_text": "创作一个连续短剧。",
            "execution_mode": "auto",
        },
    )

    assert response.status_code == 200
    assert state["full_calls"] == 0
    assert state["stage_calls"] == [
        {"stage": "showrunner", "feedback": "", "continue_after": True}
    ]
    assert state["job"]["remote_kind"] == "stage"
    assert state["job"]["remote_retry_count"] == 0


def test_failed_remote_stage_retries_twice_then_uses_local_checkpoint(monkeypatch):
    monkeypatch.setenv("CODEBUDDY_NPC_REMOTE_STAGE_RETRIES", "2")
    server, state = _install_fakes(monkeypatch, refresh_fails=True)
    app = server.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    headers = {"Authorization": "Bearer writer-token"}

    created = client.post(
        "/api/new-workflow-test/npc/jobs",
        headers=headers,
        json={
            "project_title": "远程重试测试",
            "source_text": "从断点继续。",
            "execution_mode": "auto",
        },
    )
    assert created.status_code == 200

    for expected_retry in (1, 2):
        response = client.get(
            "/api/new-workflow-test/npc/jobs/npc-orchestration-test",
            headers=headers,
        )
        assert response.status_code == 200
        assert state["job"]["remote_retry_count"] == expected_retry
        assert state["fallback_calls"] == []

    response = client.get(
        "/api/new-workflow-test/npc/jobs/npc-orchestration-test",
        headers=headers,
    )
    assert response.status_code == 200
    assert len(state["stage_calls"]) == 3
    assert state["fallback_calls"] == [
        {
            "job_id": "npc-orchestration-test",
            "user_id": 7,
            "stage": "showrunner",
            "continue_after": True,
        }
    ]
    assert state["job"]["execution_target"] == "local_fallback"


def test_stale_poll_cannot_overwrite_a_newer_remote_build(monkeypatch):
    server, state = _install_fakes(monkeypatch, refresh_replaces_build=True)
    app = server.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    headers = {"Authorization": "Bearer writer-token"}

    created = client.post(
        "/api/new-workflow-test/npc/jobs",
        headers=headers,
        json={
            "project_title": "并发轮询保护",
            "source_text": "旧轮询不能覆盖新节点。",
            "execution_mode": "auto",
        },
    )
    assert created.status_code == 200
    assert state["job"]["build"]["sn"] == "build-1"

    response = client.get(
        "/api/new-workflow-test/npc/jobs/npc-orchestration-test",
        headers=headers,
    )

    assert response.status_code == 200
    assert state["job"]["build"]["sn"] == "build-newer"
    assert state["job"]["remote_stage"] == "story_architect"
    assert state["job"]["status"] == "running"


def test_completed_cloud_stage_cannot_remain_result_pending_forever(monkeypatch):
    monkeypatch.setenv("CODEBUDDY_NPC_REMOTE_STAGE_RETRIES", "2")
    server, state = _install_fakes(monkeypatch, refresh_result_pending=True)
    app = server.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    headers = {"Authorization": "Bearer writer-token"}

    created = client.post(
        "/api/new-workflow-test/npc/jobs",
        headers=headers,
        json={
            "project_title": "云端成功产物恢复",
            "source_text": "云端结束后必须恢复产物。",
            "execution_mode": "auto",
        },
    )
    assert created.status_code == 200
    state["job"]["result_pending_since"] = "2000-01-01T00:00:00+00:00"

    response = client.get(
        "/api/new-workflow-test/npc/jobs/npc-orchestration-test",
        headers=headers,
    )

    assert response.status_code == 200
    assert state["job"]["remote_retry_count"] == 1
    assert state["job"]["status"] == "running"
    assert state["job"]["last_remote_error"].startswith(
        "CNB 构建已成功，但平台未能"
    )
