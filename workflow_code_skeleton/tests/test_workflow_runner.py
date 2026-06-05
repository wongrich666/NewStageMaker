from __future__ import annotations

import json

import pytest

from workflow_code_skeleton.app.services import workflow_runner


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


def test_workflow_runner_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("WORKFLOW_BACKEND", "unknown")

    with pytest.raises(workflow_runner.WorkflowRunnerError) as exc:
        workflow_runner.run_stage("stage_01", {})

    assert exc.value.backend == "unknown"
    assert "fastgpt" in exc.value.detail["supported_backends"]


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
