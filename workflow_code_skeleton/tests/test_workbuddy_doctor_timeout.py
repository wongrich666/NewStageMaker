from workflow_code_skeleton.app.services.workbuddy_doctor import doctor_timeout_seconds


def test_doctor_timeout_scales_for_long_hook_review(monkeypatch):
    monkeypatch.delenv("SCRIPT_DOCTOR_TIMEOUT_BASE", raising=False)
    monkeypatch.delenv("SCRIPT_DOCTOR_TIMEOUT_MAX", raising=False)
    monkeypatch.delenv("SCRIPT_DOCTOR_TIMEOUT_PER_8K", raising=False)

    assert doctor_timeout_seconds(25_179, "hook_rhythm") == 720


def test_doctor_timeout_allows_env_override_and_caps(monkeypatch):
    monkeypatch.setenv("SCRIPT_DOCTOR_TIMEOUT_BASE", "300")
    monkeypatch.setenv("SCRIPT_DOCTOR_TIMEOUT_MAX", "500")
    monkeypatch.setenv("SCRIPT_DOCTOR_TIMEOUT_PER_8K", "120")

    assert doctor_timeout_seconds(100_000, "character_continuity") == 500


def test_cross_episode_doctor_gets_more_time(monkeypatch):
    monkeypatch.delenv("SCRIPT_DOCTOR_TIMEOUT_BASE", raising=False)
    monkeypatch.delenv("SCRIPT_DOCTOR_TIMEOUT_MAX", raising=False)
    monkeypatch.delenv("SCRIPT_DOCTOR_TIMEOUT_PER_8K", raising=False)

    assert doctor_timeout_seconds(8_000, "character_continuity") == 600
    assert doctor_timeout_seconds(8_000, "hook_rhythm") == 540
