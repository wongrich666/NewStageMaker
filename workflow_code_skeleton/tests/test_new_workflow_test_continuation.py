from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "web"
    / "static"
    / "new_workflow_test.js"
)


def test_continuation_ui_detects_existing_range_and_only_asks_for_target_episode():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'data-choice-value="续写"' in source
    assert "function detectLastEpisode" in source
    assert "continuation_target_episode" in source
    assert "source_last_episode" in source
    assert "续写到第几集" in source
    assert "已识别写至第" in source
    assert "未识别到集号" in source


def test_continuation_duration_and_delivery_range_use_new_episode_count():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "function generationEpisodeCount" in source
    assert "function deliveryRange" in source
    assert "generationEpisodeCount()" in source
    assert "deliveryRange()" in source


def test_all_creation_modes_expose_optional_uploadable_locked_story_bible():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "story_bible_enabled: false" in source
    assert 'data-action="toggle-story-bible"' in source
    assert 'continuation_bible: ""' in source
    assert 'data-form-key="continuation_bible"' in source
    assert 'data-upload-target="continuation_bible"' in source
    assert "创作圣经（全链路锁定）" in source
    assert 'state.form.mode === "续写" ? `\n              <label class="nwt-field wide nwt-continuation-bible">' not in source


def test_ip_anthology_is_an_explicit_opt_in_button():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "ip_anthology_mode: false" in source
    assert 'data-action="toggle-ip-anthology"' in source
    assert "IP单元剧" in source
    assert "默认连续叙事" in source
