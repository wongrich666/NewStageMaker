from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "web"
    / "static"
    / "new_workflow_test.js"
)


def _function_source(source: str, name: str, next_name: str) -> str:
    start = source.index(f"  async function {name}(")
    end = source.index(f"  async function {next_name}(", start)
    return source[start:end]


def test_job_polling_does_not_rebuild_the_page_for_telemetry_only_updates():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    polling = _function_source(source, "pollJob", "recoverJob")

    assert "renderSignature" in polling
    assert "patchLiveTelemetry" in polling
    assert "if (previousSignature !== renderSignature(state.job))" in polling


def test_job_polling_rerenders_when_checkpoint_or_status_changes():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "status_text: value.status_text" in source
    assert "remote_checkpoint: value.remote_checkpoint" in source
    assert "remote_retry_count: value.remote_retry_count" in source
    assert 'stage_resume_text_length: String(value.stage_resume_text || "").length' in source


def test_silent_history_polling_only_replaces_sidebar_when_items_changed():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    history = _function_source(source, "loadHistory", "openHistory")

    assert "historyRenderSignature" in history
    assert "if (previousSignature !== historyRenderSignature(state.history))" in history


def test_recovered_stage_output_is_rendered_as_completed():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'if (memberHasOutput(member, job)) return "success";' in source
    assert "const status = memberVisualStatus(member, job);" in source
    assert 'class="nwt-flow-step ${klass}' in source
