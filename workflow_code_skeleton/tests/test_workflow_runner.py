from __future__ import annotations

import json

import pytest

from workflow_code_skeleton.app.services.coze_workflow_client import (
    CozeWorkflowError,
    coze_workflow_client,
    normalize_coze_stage_key,
    use_coze_workflow_backend,
)
from workflow_code_skeleton.app.services import workflow_runner


def _clear_coze_credential_env(monkeypatch):
    for name in (
        "COZE_CREDENTIALS_ORDER",
        "COZE_PRIMARY_API_TOKEN",
        "COZE_SECONDARY_API_TOKEN",
        "COZE_PRIMARY_API_BASE",
        "COZE_SECONDARY_API_BASE",
        "COZE_PRIMARY_AUTH_TYPE",
        "COZE_SECONDARY_AUTH_TYPE",
        "COZE_PRIMARY_TOKEN_EXPIRES_AT",
        "COZE_SECONDARY_TOKEN_EXPIRES_AT",
    ):
        monkeypatch.delenv(name, raising=False)


def _stage01_required_params():
    return {
        "adaptation_direction": "",
        "episodes_per_season": 20,
        "minutes_per_episode": 2,
        "mode": "create",
        "season_count": 1,
        "source_text": "x",
        "source_title": "test",
        "target_format": "short",
        "user_constraints": "",
        "user_requirements": "",
    }


def test_workflow_runner_selects_fastgpt_adapter(monkeypatch):
    captured = {}

    def fake_run_stage(self, stage_key, variables=None, extra_parameters=None):
        captured["stage_key"] = stage_key
        captured["variables"] = dict(variables or {})
        captured["extra_parameters"] = dict(extra_parameters or {})
        return {"ok": True, "value": "fastgpt"}

    monkeypatch.setenv("WORKFLOW_BACKEND", "fastgpt")
    monkeypatch.delenv("WORKFLOW_CONFIG", raising=False)
    monkeypatch.setattr(
        "workflow_code_skeleton.app.services.workflow_adapters.fastgpt_adapter.FastGPTWorkflowAdapter.run_stage",
        fake_run_stage,
    )

    result = workflow_runner.run_stage("framework_scene_dictionary", {"source": "x"}, {"extra": "y"})

    assert result["backend"] == "fastgpt"
    assert result["stage_key"] == "framework_scene_dictionary"
    assert result["backend_stage_key"] == "framework_scene_dictionary"
    assert result["value"] == "fastgpt"
    assert captured["variables"] == {"source": "x"}
    assert captured["extra_parameters"] == {"extra": "y"}


def test_workflow_runner_selects_coze_backend_stage_key(monkeypatch):
    captured = {}

    def fake_run_stage(self, stage_key, variables=None, extra_parameters=None):
        captured["stage_key"] = stage_key
        return {"ok": True, "workflow_id": "wf-coze"}

    monkeypatch.setenv("WORKFLOW_BACKEND", "coze")
    monkeypatch.delenv("WORKFLOW_CONFIG", raising=False)
    monkeypatch.setattr(
        "workflow_code_skeleton.app.services.workflow_adapters.coze_adapter.CozeWorkflowAdapter.run_stage",
        fake_run_stage,
    )

    result = workflow_runner.run_stage("framework_script_rewrite", {"a": 1})

    assert captured["stage_key"] == "stage_12_rewrite"
    assert result["backend"] == "coze"
    assert result["backend_stage_key"] == "stage_12_rewrite"


def test_workflow_runner_normalizes_adapter_output(monkeypatch):
    def fake_run_stage(self, stage_key, variables=None, extra_parameters=None):
        return {
            "ok": True,
            "content": '```json\n{"source_brief": {"title": "Runner Normalized"}, "display_text": "Readable"}\n```',
        }

    monkeypatch.setenv("WORKFLOW_BACKEND", "coze")
    monkeypatch.delenv("WORKFLOW_CONFIG", raising=False)
    monkeypatch.setattr(
        "workflow_code_skeleton.app.services.workflow_adapters.coze_adapter.CozeWorkflowAdapter.run_stage",
        fake_run_stage,
    )

    result = workflow_runner.run_stage("stage_01", {"source_text": "x"})

    assert result["source_brief"]["title"] == "Runner Normalized"
    assert result["display_text"] == "Readable"
    assert result["_normalizer_debug"]["raw_result"]["content"].startswith("```json")


def test_coze_stage_key_aliases_resolve_stage_01():
    assert normalize_coze_stage_key("basic") == "stage_01"
    assert normalize_coze_stage_key("01") == "stage_01"
    assert normalize_coze_stage_key("stage01") == "stage_01"
    info = coze_workflow_client.workflow_id_info_for_stage("basic")
    assert info["normalized_stage_key"] == "stage_01"
    assert info["workflow_id"]
    assert info["resource_path"].endswith(".zip")
    assert info["inner_yaml_path"].endswith(".yaml")


def test_use_coze_workflow_backend_defaults_to_settings(monkeypatch):
    monkeypatch.delenv("WORKFLOW_BACKEND", raising=False)
    assert use_coze_workflow_backend() is True


def test_coze_access_token_invalid_error_has_region_hint(monkeypatch):
    _clear_coze_credential_env(monkeypatch)

    class FakeRuns:
        def stream(self, **kwargs):
            raise FakeCozeApiError()

    class FakeWorkflows:
        runs = FakeRuns()

    class FakeCoze:
        workflows = FakeWorkflows()

    class FakeCozeApiError(Exception):
        code = 700012006
        msg = "access token invalid"
        logid = "test-logid"
        debug_url = None

        def __str__(self) -> str:
            return "code: 700012006, msg: access token invalid, logid: test-logid"

    monkeypatch.setenv("COZE_API_TOKEN", "fake-token")
    monkeypatch.setenv("COZE_API_BASE", "https://api.coze.com")
    monkeypatch.setattr(coze_workflow_client, "_coze", FakeCoze())
    monkeypatch.setattr(coze_workflow_client, "_coze_signature", None)

    with pytest.raises(CozeWorkflowError) as exc:
        coze_workflow_client.run_workflow_by_id(
            "workflow-id",
            parameters={
                "adaptation_direction": "",
                "episodes_per_season": 20,
                "minutes_per_episode": 2,
                "mode": "创作",
                "season_count": 1,
                "source_text": "x",
                "source_title": "测试",
                "target_format": "短剧",
                "user_constraints": "",
                "user_requirements": "",
            },
            stage_key="stage_01",
        )

    assert "Coze access token invalid" in str(exc.value)
    assert "COZE_API_BASE=COZE_CN_BASE_URL" in str(exc.value)
    assert exc.value.detail["code"] == 700012006
    assert exc.value.detail["msg"] == "access token invalid"
    assert exc.value.detail["region_mismatch_suspected"] is True
    assert exc.value.detail["suggested_base_url"] == "https://api.coze.cn"
    assert exc.value.detail["suggested_base_url_env"] == "COZE_API_BASE=https://api.coze.cn"
    assert exc.value.detail["auth_failure_suspected"] is True
    assert exc.value.detail["token_action_required"] == "replace_or_regenerate_coze_pat"


def test_coze_authentication_invalid_error_has_token_hint(monkeypatch):
    _clear_coze_credential_env(monkeypatch)

    class FakeRuns:
        def stream(self, **kwargs):
            raise FakeCozeApiError()

    class FakeWorkflows:
        runs = FakeRuns()

    class FakeCoze:
        workflows = FakeWorkflows()

    class FakeCozeApiError(Exception):
        code = 4100
        msg = "authentication is invalid"
        logid = "test-logid"
        debug_url = None

        def __str__(self) -> str:
            return "code: 4100, msg: authentication is invalid, logid: test-logid"

    monkeypatch.setenv("COZE_API_TOKEN", "fake-token")
    monkeypatch.setenv("COZE_API_BASE", "https://api.coze.cn")
    monkeypatch.setattr(coze_workflow_client, "_coze", FakeCoze())
    monkeypatch.setattr(coze_workflow_client, "_coze_signature", None)

    with pytest.raises(CozeWorkflowError) as exc:
        coze_workflow_client.run_workflow_by_id(
            "workflow-id",
            parameters={
                "adaptation_direction": "",
                "episodes_per_season": 20,
                "minutes_per_episode": 2,
                "mode": "创作",
                "season_count": 1,
                "source_text": "x",
                "source_title": "测试",
                "target_format": "短剧",
                "user_constraints": "",
                "user_requirements": "",
            },
            stage_key="stage_01",
        )

    assert "Coze authentication invalid" in str(exc.value)
    assert "base_url=https://api.coze.cn" in str(exc.value)
    assert exc.value.detail["code"] == 4100
    assert exc.value.detail["msg"] == "authentication is invalid"
    assert exc.value.detail["auth_failure_suspected"] is True
    assert exc.value.detail["auth_failure_code"] == "4100"
    assert exc.value.detail["base_url_region"] == "cn"
    assert exc.value.detail["token_action_required"] == "replace_or_regenerate_coze_pat"
    assert exc.value.detail["token_status"] == "SET"


def test_coze_stage_01_missing_variables_fail_before_request(monkeypatch):
    _clear_coze_credential_env(monkeypatch)

    class FakeRuns:
        def stream(self, **kwargs):
            raise AssertionError("Coze request should not be sent with missing variables")

    class FakeWorkflows:
        runs = FakeRuns()

    class FakeCoze:
        workflows = FakeWorkflows()

    monkeypatch.setenv("COZE_API_TOKEN", "fake-token")
    monkeypatch.setattr(coze_workflow_client, "_coze", FakeCoze())

    with pytest.raises(CozeWorkflowError) as exc:
        coze_workflow_client.run_workflow_by_id(
            "workflow-id",
            parameters={"source_text": "x"},
            stage_key="stage_01",
        )

    assert "Coze workflow input variables missing" in str(exc.value)
    assert "source_title" in exc.value.detail["missing_input_variables"]
    assert exc.value.detail["request_parameters_keys"] == ["source_text"]


def test_coze_credentials_use_primary_secondary_order(monkeypatch):
    _clear_coze_credential_env(monkeypatch)
    monkeypatch.delenv("COZE_API_TOKEN", raising=False)
    monkeypatch.setenv("COZE_CREDENTIALS_ORDER", "primary,secondary")
    monkeypatch.setenv("COZE_SECONDARY_API_TOKEN", "secondary-token-secret")
    monkeypatch.setenv("COZE_API_BASE", "https://api.coze.cn")

    credentials = coze_workflow_client.credentials()
    diagnostics = coze_workflow_client.credentials_diagnostics()
    serialized = json.dumps(diagnostics, ensure_ascii=False)

    assert [credential.name for credential in credentials] == ["primary", "secondary"]
    assert credentials[0].token_env == "COZE_PRIMARY_API_TOKEN"
    assert credentials[0].token == ""
    assert credentials[1].token_env == "COZE_SECONDARY_API_TOKEN"
    assert credentials[1].token == "secondary-token-secret"
    assert [item["credential_name"] for item in diagnostics] == ["primary", "secondary"]
    assert diagnostics[0]["token_status"] == "EMPTY"
    assert diagnostics[1]["token_status"] == "SET"
    assert diagnostics[1]["token_redacted"] is True
    assert "secondary-token-secret" not in serialized


def test_coze_primary_4100_falls_back_to_secondary(monkeypatch):
    _clear_coze_credential_env(monkeypatch)
    monkeypatch.delenv("COZE_API_TOKEN", raising=False)
    monkeypatch.setenv("COZE_CREDENTIALS_ORDER", "primary,secondary")
    monkeypatch.setenv("COZE_PRIMARY_API_TOKEN", "primary-token-secret")
    monkeypatch.setenv("COZE_SECONDARY_API_TOKEN", "secondary-token-secret")
    monkeypatch.setenv("COZE_API_BASE", "https://api.coze.cn")
    calls = []

    def fake_run_once(workflow_id, *, parameters, stream, stage_key, workflow_info, credential):
        calls.append(credential.name)
        if credential.name == "primary":
            raise CozeWorkflowError(
                "primary failed",
                stage_key=stage_key,
                workflow_id=workflow_id,
                detail={
                    "code": 4100,
                    "original_error_code": 4100,
                    "msg": "authentication is invalid",
                    "original_error_msg": "authentication is invalid",
                    "workflow_id_status": "SET",
                    "workflow_id_exists": True,
                    "token_env": credential.token_env,
                    "base_url": credential.base_url,
                    "base_url_env": credential.base_url_env,
                },
            )
        return {"ok": True, "content": "secondary ok"}

    monkeypatch.setattr(coze_workflow_client, "_run_workflow_by_id_once", fake_run_once)

    result = coze_workflow_client.run_workflow_by_id(
        "workflow-id",
        parameters=_stage01_required_params(),
        stage_key="stage_01",
    )
    attempts = result["credential_attempts"]
    serialized = json.dumps(attempts, ensure_ascii=False)

    assert calls == ["primary", "secondary"]
    assert [item["credential_name"] for item in attempts] == ["primary", "secondary"]
    assert attempts[0]["success"] is False
    assert attempts[0]["error_code"] == "4100"
    assert attempts[0]["fallback_allowed"] is True
    assert attempts[1]["success"] is True
    assert result["credential_name"] == "secondary"
    assert "primary-token-secret" not in serialized
    assert "secondary-token-secret" not in serialized


def test_coze_all_credentials_failed_reports_sanitized_attempts(monkeypatch):
    _clear_coze_credential_env(monkeypatch)
    monkeypatch.delenv("COZE_API_TOKEN", raising=False)
    monkeypatch.setenv("COZE_CREDENTIALS_ORDER", "primary,secondary")
    monkeypatch.setenv("COZE_PRIMARY_API_TOKEN", "primary-token-secret")
    monkeypatch.setenv("COZE_SECONDARY_API_TOKEN", "secondary-token-secret")
    monkeypatch.setenv("COZE_API_BASE", "https://api.coze.cn")
    calls = []

    def fake_run_once(workflow_id, *, parameters, stream, stage_key, workflow_info, credential):
        calls.append(credential.name)
        raise CozeWorkflowError(
            f"{credential.name} failed",
            stage_key=stage_key,
            workflow_id=workflow_id,
            detail={
                "code": 4100,
                "original_error_code": 4100,
                "msg": "authentication is invalid",
                "original_error_msg": "authentication is invalid",
                "workflow_id_status": "SET",
                "workflow_id_exists": True,
                "token_env": credential.token_env,
                "base_url": credential.base_url,
                "base_url_env": credential.base_url_env,
            },
        )

    monkeypatch.setattr(coze_workflow_client, "_run_workflow_by_id_once", fake_run_once)

    with pytest.raises(CozeWorkflowError) as exc:
        coze_workflow_client.run_workflow_by_id(
            "workflow-id",
            parameters=_stage01_required_params(),
            stage_key="stage_01",
        )

    attempts = exc.value.detail["credential_attempts"]
    serialized = json.dumps(attempts, ensure_ascii=False)

    assert calls == ["primary", "secondary"]
    assert [item["credential_name"] for item in attempts] == ["primary", "secondary"]
    assert [item["token_env"] for item in attempts] == ["COZE_PRIMARY_API_TOKEN", "COZE_SECONDARY_API_TOKEN"]
    assert all(item["success"] is False for item in attempts)
    assert all(item["error_code"] == "4100" for item in attempts)
    assert "primary-token-secret" not in serialized
    assert "secondary-token-secret" not in serialized


def test_workflow_runner_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("WORKFLOW_BACKEND", "unknown")

    with pytest.raises(workflow_runner.WorkflowRunnerError) as exc:
        workflow_runner.run_stage("stage_01", {})

    assert exc.value.backend == "unknown"
    assert "fastgpt" in exc.value.detail["supported_backends"]


def test_workflow_runner_preserves_coze_adapter_error_detail(monkeypatch):
    class FakeCozeError(RuntimeError):
        detail = {
            "original_exception_type": "CozeAPIError",
            "original_exception_message": "access token invalid",
            "workflow_id_source": "COZE_WORKFLOW_STAGE_01_ID",
            "token_status": "SET",
            "resource_path": "Workflow-extract01.zip",
            "inner_yaml_path": "workflow/extract01.yaml",
        }

    def fake_run_stage(self, stage_key, variables=None, extra_parameters=None):
        raise FakeCozeError("coze failed")

    monkeypatch.setenv("WORKFLOW_BACKEND", "coze")
    monkeypatch.delenv("WORKFLOW_CONFIG", raising=False)
    monkeypatch.setattr(
        "workflow_code_skeleton.app.services.workflow_adapters.coze_adapter.CozeWorkflowAdapter.run_stage",
        fake_run_stage,
    )

    with pytest.raises(workflow_runner.WorkflowRunnerError) as exc:
        workflow_runner.run_stage("stage_01", {"source_text": "x"})

    assert exc.value.backend == "coze"
    assert exc.value.detail["backend_stage_key"] == "stage_01"
    assert exc.value.detail["original_exception_type"] == "CozeAPIError"
    assert exc.value.detail["workflow_id_source"] == "COZE_WORKFLOW_STAGE_01_ID"
    assert exc.value.detail["token_status"] == "SET"


def test_workflow_runner_loads_stage_mapping_from_config(monkeypatch, tmp_path):
    config_path = tmp_path / "workflows.json"
    config_path.write_text(
        json.dumps(
            {
                "stages": {
                    "custom_stage": {
                        "backend_stage_keys": {"fastgpt": "fg_stage", "coze": "coze_stage"},
                        "input_mapping": {"business": "wire"},
                        "output_mapping": {"wire_result": "business_result"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKFLOW_CONFIG", str(config_path))
    workflow_runner.load_workflow_config.cache_clear()

    try:
        config = workflow_runner.stage_config("custom_stage")
        assert config.backend_stage_keys["fastgpt"] == "fg_stage"
        assert config.backend_stage_keys["coze"] == "coze_stage"
        assert config.input_mapping == {"business": "wire"}
        assert config.output_mapping == {"wire_result": "business_result"}
    finally:
        workflow_runner.load_workflow_config.cache_clear()
