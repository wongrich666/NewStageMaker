from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

import pytest
import requests

from workflow_code_skeleton.app.services.codebuddy_npc import (
    CodeBuddyNpcClient,
    CodeBuddyNpcConfig,
    CodeBuddyNpcError,
    CodeBuddyNpcJobStore,
    finish_stage_timing,
    public_job,
    stage_episode_range_error,
    start_stage_timing,
)
from workflow_code_skeleton.app.services.codebuddy_npc_stage_runner import (
    CodeBuddyNpcStageRunner,
    _compact_story_state,
    _continuation_instruction,
    _merge_episode_outputs,
    _missing_episode_ranges,
    _episode_slice,
)


class _Response:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


class _DnsRetrySession(_Session):
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _config(tmp_path: Path, **overrides) -> CodeBuddyNpcConfig:
    values = {
        "api_base": "https://api.cnb.cool",
        "repository": "demo/script-team",
        "access_token": "token",
        "event": "api_trigger_script_team_custom_api",
        "model": "deepseek-v4-pro",
        "context_window": "1m",
        "branch": "main",
        "timeout": 10,
        "callback_token": "",
        "job_dir": tmp_path,
    }
    values.update(overrides)
    return CodeBuddyNpcConfig(**values)


def test_job_store_preserves_request_and_user_boundary(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))
    job = store.create(
        user_id=7,
        request_payload={
            "project_title": "测试剧",
            "production_type": "AI真人剧",
            "episodes": 5,
            "episode_word_count": 800,
            "episode_duration_seconds": 75,
            "source_text": "一个不能被忘记的约定。",
        },
    )

    assert job["request"]["project_title"] == "测试剧"
    assert job["request"]["scenes_per_episode"] == "1"
    assert job["request"]["episode_duration_seconds"] == 75
    assert job["request"]["total_duration_seconds"] == 375
    assert job["request"]["episode_word_count_max"] == 880
    assert job["request"]["episode_word_count_tolerance_percent"] == 10
    assert store.load(job["job_id"], user_id=7)["user_id"] == 7
    assert store.load(job["job_id"], user_id=8) is None


def test_remote_stage_result_rejects_missing_episode_range() -> None:
    result = "\n\n".join(
        f"第{episode}集：《测试》\n场景1：工作室｜夜｜内"
        for episode in range(1, 6)
    )

    assert stage_episode_range_error(
        "episode_continuity",
        result,
        {"episode_start": 1, "episode_end": 10, "episodes": 10},
    ) == "分集连续性编剧集数不完整：要求第1-10集，实际集号为[1, 2, 3, 4, 5]"


def test_remote_stage_result_rejects_placeholder_episode_card() -> None:
    content = "\n\n".join(
        [
            "第1集：《有效》\n承接事实：旧动作\n开场钩子：异变\n最短因果锚：旧债\n"
            "主角目标：脱困\n主角主动动作：反击\n阻力：封锁\n选择与代价：受伤\n"
            "本集主线推进：获得线索\n结尾状态：门被锁死\n下一集第一有效动作：砸门"
        ]
        + [f"第{episode}集：《占位》\n承接事实：" for episode in range(2, 6)]
    )

    error = stage_episode_range_error(
        "episode_continuity",
        content,
        {"episode_start": 1, "episode_end": 5, "episodes": 5},
    )

    assert error.startswith("第2集逐集卡为空或字段不完整")


def test_episode_batches_merge_valid_parts_and_only_report_missing_ranges() -> None:
    current = "\n\n".join(
        f"第{episode}集：《旧{episode}》\n场景1：工作室｜夜｜内"
        for episode in (1, 2, 4)
    )
    incoming = "\n\n".join(
        f"第{episode}集：《新{episode}》\n场景1：工作室｜夜｜内"
        for episode in (3, 4, 5, 12)
    )

    merged = _merge_episode_outputs(
        current,
        incoming,
        episode_start=1,
        episode_end=10,
    )

    assert "第4集：《旧4》" in merged
    assert "第4集：《新4》" not in merged
    assert "第12集" not in merged
    assert _missing_episode_ranges(
        merged,
        episode_start=1,
        episode_end=10,
    ) == [(6, 10)]


def test_cancel_stale_job_pauses_immediately_and_keeps_checkpoint(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))
    job = store.create(
        user_id=7,
        request_payload={
            "project_title": "断点任务",
            "episodes": 10,
            "source_text": "测试断点恢复。",
        },
    )
    job.update(
        {
            "status": "stage_running",
            "active_stage": "episode_continuity",
            "stage_resume_text": "第1集\n保留内容",
            "batch_progress": {
                "stage": "episode_continuity",
                "completed_episodes": [1],
            },
        }
    )
    store.save(job)

    paused = CodeBuddyNpcStageRunner(store).request_cancel(
        job_id=job["job_id"],
        user_id=7,
    )

    assert paused["status"] == "stage_paused"
    assert paused["active_stage"] == ""
    assert paused["stage_resume_text"] == "第1集\n保留内容"
    assert paused["batch_progress"]["completed_episodes"] == [1]


def test_prepare_remote_keeps_same_stage_episode_checkpoint(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))
    job = store.create(
        user_id=7,
        request_payload={
            "project_title": "断点重跑",
            "episodes": 10,
            "source_text": "测试断点恢复。",
        },
    )
    partial = "第1集：《保留》\n场景1：办公室｜日｜内\n人物：主角\n主角：继续。"
    job.update(
        {
            "status": "stage_paused",
            "remote_stage": "episode_continuity",
            "stage_resume_text": partial,
            "batch_progress": {
                "stage": "episode_continuity",
                "batch_size": 5,
                "completed_episodes": [1],
                "completed_ranges": [],
                "current_start": 1,
                "current_end": 5,
            },
            "recovered_files": {
                "contract": "创作合同",
                "story": "故事架构",
                "characters": "人物设定",
            },
        }
    )
    store.save(job)

    prepared = CodeBuddyNpcStageRunner(store).prepare_remote(
        job_id=job["job_id"],
        user_id=7,
        stage="episode_continuity",
    )

    assert prepared["stage_resume_text"] == partial
    assert prepared["batch_progress"]["stage"] == "episode_continuity"


def test_stage_timing_is_live_then_persists_completed_duration() -> None:
    job = {"stage_timings": {}, "active_stage": "story_architect"}

    start_stage_timing(
        job,
        "story_architect",
        reset=True,
        execution_target="remote_cnb",
    )
    live = public_job(job)

    assert live["stage_timings"]["story_architect"]["status"] == "running"
    assert live["stage_timings"]["story_architect"]["execution_target"] == "remote_cnb"
    assert live["active_stage_elapsed_ms"] >= 0

    finish_stage_timing(job, "story_architect", status="success")
    finished = public_job(job)

    assert finished["stage_timings"]["story_architect"]["status"] == "success"
    assert finished["stage_timings"]["story_architect"]["completed_at"]
    assert finished["stage_timings"]["story_architect"]["duration_ms"] >= 0


def test_job_store_preserves_dynamic_scene_contract(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))
    job = store.create(
        user_id=7,
        request_payload={
            "project_title": "双场景测试",
            "source_text": "一集需要两个连续场景。",
            "scenes_per_episode": "2",
        },
    )

    assert job["request"]["scenes_per_episode"] == "2"


def test_job_store_migrates_existing_job_to_ten_percent_word_limit(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))
    job = store.create(
        user_id=7,
        request_payload={
            "project_title": "旧任务",
            "source_text": "旧任务断点继续。",
            "episode_word_count": 1200,
        },
    )
    job["request"].pop("episode_word_count_max")
    job["request"].pop("episode_word_count_tolerance_percent")

    saved = store.save(job)

    assert saved["request"]["episode_word_count"] == 1200
    assert saved["request"]["episode_word_count_max"] == 1320
    assert saved["request"]["episode_word_count_tolerance_percent"] == 10


def test_job_store_builds_continuation_episode_range(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))
    job = store.create(
        user_id=7,
        request_payload={
            "project_title": "未完的王座",
            "mode": "续写",
            "source_text": "\n\n".join(
                [
                    f"第{episode}集：《旧事{episode}》\n场景1：王宫｜夜｜内\n林烬：继续。"
                    for episode in range(1, 6)
                ]
            ),
            "continuation_target_episode": 10,
            "episode_duration_seconds": 75,
            "continuation_policy": "strict",
            "continuation_bible": "林烬怕火；第8集必须揭开王室血契。",
        },
    )

    assert job["request"]["mode"] == "续写"
    assert job["request"]["source_last_episode"] == 5
    assert job["request"]["episode_start"] == 6
    assert job["request"]["episode_end"] == 10
    assert job["request"]["episodes"] == 5
    assert job["request"]["series_total_episodes"] == 10
    assert job["request"]["total_duration_seconds"] == 375
    assert job["request"]["continuation_policy"] == "strict"
    assert job["request"]["continuation_bible"] == "林烬怕火；第8集必须揭开王室血契。"
    assert "第6集至第10集" in job["request"]["episode_contract"]
    assert "不得重写第1集至第5集" in job["request"]["episode_contract"]

    instruction = _continuation_instruction(job["request"])
    assert "续写创作圣经" in instruction
    assert "已有正文明确事实 > 续写创作圣经" in instruction
    assert "第8集必须揭开王室血契" in instruction


def test_continuation_requires_existing_script_material(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))

    with pytest.raises(CodeBuddyNpcError, match="已有剧本"):
        store.create(
            user_id=7,
            request_payload={
                "project_title": "未完的王座",
                "mode": "续写",
                "adaptation_direction": "承接上一集继续调查。",
                "continuation_target_episode": 10,
            },
        )


def test_continuation_can_fall_back_to_manual_last_episode(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))
    job = store.create(
        user_id=7,
        request_payload={
            "project_title": "无集号旧稿",
            "mode": "续写",
            "source_text": "旧稿没有规范集号，但人物已经进入王宫。",
            "source_last_episode": 17,
            "continuation_target_episode": 30,
        },
    )

    assert job["request"]["episode_start"] == 18
    assert job["request"]["episode_end"] == 30
    assert job["request"]["episodes"] == 13


def test_job_store_returns_latest_job_for_user(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))
    first = store.create(
        user_id=7,
        request_payload={"project_title": "first", "source_text": "first source"},
    )
    second = store.create(
        user_id=7,
        request_payload={"project_title": "second", "source_text": "second source"},
    )
    store.create(
        user_id=8,
        request_payload={"project_title": "other", "source_text": "other source"},
    )
    first["updated_at"] = "2026-01-01T00:00:00+00:00"
    store.save(first)
    second["updated_at"] = "2026-01-02T00:00:00+00:00"
    store.save(second)

    assert store.latest(user_id=7)["job_id"] == second["job_id"]
    assert store.latest(user_id=9) is None


def test_client_stops_remote_build_with_official_endpoint(tmp_path: Path) -> None:
    session = _Session([_Response({"success": True})])
    client = CodeBuddyNpcClient(_config(tmp_path), session=session)

    result = client.stop_build("cnb-demo-123")

    assert result == {"success": True}
    method, url, _kwargs = session.calls[0]
    assert method == "POST"
    assert url == "https://api.cnb.cool/demo/script-team/-/build/stop/cnb-demo-123"


def test_job_store_lists_and_deletes_history(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))
    job = store.create(
        user_id=7,
        request_payload={"project_title": "历史剧本", "source_text": "历史内容"},
    )
    job["final_script"] = "第1集\n场景1：家｜夜｜内\n人物：林深\n场景任务：回家\n道具：钥匙"
    store.save(job)

    assert [item["job_id"] for item in store.list(user_id=7)] == [job["job_id"]]
    assert store.delete(job["job_id"], user_id=8) is False
    assert store.delete(job["job_id"], user_id=7) is True
    assert store.list(user_id=7) == []


def test_editing_upstream_artifact_invalidates_downstream(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))
    job = store.create(
        user_id=7,
        request_payload={"project_title": "节点修改", "source_text": "父子诀别"},
    )
    job["recovered_files"] = {
        "contract": "旧合同",
        "story": "旧架构",
        "characters": "旧人物",
        "episodes": "旧分集",
        "draft": "旧初稿",
        "story_state": '{"schema_version":"1.0"}',
    }
    job["final_script"] = "旧终稿"
    store.save(job)

    updated = CodeBuddyNpcStageRunner(store).edit_artifact(
        job_id=job["job_id"],
        user_id=7,
        artifact_key="story",
        content="新架构",
    )

    assert updated["recovered_files"]["contract"] == "旧合同"
    assert updated["recovered_files"]["story"] == "新架构"
    assert "characters" not in updated["recovered_files"]
    assert updated["final_script"] == ""
    assert updated["stage_versions"]["story"][-1]["content"] == "旧架构"


def test_edited_artifact_is_sent_to_the_next_remote_stage(tmp_path: Path) -> None:
    session = _Session([_Response({"success": True, "sn": "stage-build"})])
    config = _config(tmp_path)
    store = CodeBuddyNpcJobStore(config)
    job = store.create(
        user_id=7,
        request_payload={"project_title": "修改应用", "source_text": "父子诀别"},
    )
    job["recovered_files"] = {
        "contract": "创作合同",
        "story": "旧故事架构",
        "characters": "旧人物",
    }
    store.save(job)
    edited = CodeBuddyNpcStageRunner(store).edit_artifact(
        job_id=job["job_id"],
        user_id=7,
        artifact_key="story",
        content="人工修改后的故事架构",
    )

    CodeBuddyNpcClient(config, session=session).trigger_stage(
        edited,
        stage="character_emotion",
    )

    payload = session.calls[0][2]["json"]
    checkpoint = json.loads(
        gzip.decompress(
            base64.b64decode(payload["env"]["scriptStateBundle"])
        ).decode("utf-8")
    )
    assert checkpoint["recovered_files"] == {
        "contract": "创作合同",
        "story": "人工修改后的故事架构",
    }
    assert "characters" not in edited["recovered_files"]


def test_local_runner_can_stop_after_framework_team_stage(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))
    job = store.create(
        user_id=7,
        request_payload={"project_title": "框架任务", "source_text": "父子诀别"},
    )
    runner = CodeBuddyNpcStageRunner(store)
    executed: list[str] = []

    def fake_execute(current_job, stage, feedback):
        executed.append(stage)
        artifact = {
            "showrunner": "contract",
            "story_architect": "story",
            "character_emotion": "characters",
            "episode_continuity": "episodes",
        }[stage]
        fresh = store.load(job["job_id"], user_id=7)
        recovered = dict(fresh.get("recovered_files") or {})
        recovered[artifact] = f"{stage} output"
        fresh["recovered_files"] = recovered
        store.save(fresh)

    runner._execute_stage = fake_execute
    runner._run(
        job_id=job["job_id"],
        user_id=7,
        start_stage="showrunner",
        feedback="",
        continue_after=True,
        stop_after_stage="episode_continuity",
    )

    finished = store.load(job["job_id"], user_id=7)
    assert executed == [
        "showrunner",
        "story_architect",
        "character_emotion",
        "episode_continuity",
    ]
    assert finished["status"] == "completed_scope"
    assert finished["progress"] == 100
    assert "episodes" in finished["recovered_files"]
    assert "draft" not in finished["recovered_files"]


def test_job_store_materializes_recovered_stage_files(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))
    job = store.create(
        user_id=7,
        request_payload={"project_title": "恢复测试", "source_text": "中断任务"},
    )
    job["recovered_files"] = {
        "contract": "创作合同正文",
        "draft": "第1集\n初稿正文",
        "story_state": '{"schema_version":"1.0"}',
    }
    job["final_script"] = "第1集\n最终正文"
    job["quality_gate"] = {"ok": True, "errors": [], "warnings": []}

    saved = store.save(job)
    artifact_dir = tmp_path / job["job_id"]

    assert (artifact_dir / "01_contract.md").read_text(encoding="utf-8") == "创作合同正文"
    assert (artifact_dir / "05_draft.txt").read_text(encoding="utf-8").startswith("第1集")
    assert (artifact_dir / "final_script.txt").read_text(encoding="utf-8") == "第1集\n最终正文"
    assert json.loads((artifact_dir / "gate_final.json").read_text(encoding="utf-8"))["ok"] is True
    assert {item["key"] for item in saved["artifact_files"]} == {
        "contract",
        "draft",
        "story_state",
        "final_script",
        "quality_gate",
    }


def test_job_store_uses_numeric_episode_count_as_hard_contract(tmp_path: Path) -> None:
    store = CodeBuddyNpcJobStore(_config(tmp_path))

    job = store.create(
        user_id=7,
        request_payload={
            "project_title": "狼人复仇",
            "episodes": 5,
            "source_text": "狼人复仇计划",
            "adaptation_direction": (
                "第一句形成五秒钩子；只用一个核心场景；"
                "最终文件只能是第1集剧本正文。"
            ),
        },
    )

    assert job["request"]["episodes"] == 5
    assert "第1集至第5集" in job["request"]["episode_contract"]
    assert "只用一个核心场景" in job["request"]["adaptation_direction"]
    assert "最终文件只能是第1集" not in job["request"]["adaptation_direction"]
    assert "总集数 5 集" in job["request_warnings"][0]


@pytest.mark.parametrize("episodes", [1, 3, 12, 120])
def test_job_store_builds_dynamic_episode_contract(tmp_path: Path, episodes: int) -> None:
    job = CodeBuddyNpcJobStore(_config(tmp_path)).create(
        user_id=7,
        request_payload={
            "project_title": f"{episodes}集项目",
            "episodes": episodes,
            "source_text": "动态集数测试",
        },
    )

    assert job["request"]["episodes"] == episodes
    assert f"共{episodes}集" in job["request"]["episode_contract"]


def test_trigger_uses_one_async_cnb_build(tmp_path: Path) -> None:
    session = _Session(
        [_Response({"success": True, "sn": "build-1", "buildLogUrl": "https://log"})]
    )
    config = _config(tmp_path)
    client = CodeBuddyNpcClient(config, session=session)
    job = CodeBuddyNpcJobStore(config).create(
        user_id=1,
        request_payload={"project_title": "钩子测试", "source_text": "父亲让我快跑。"},
    )

    result = client.trigger(job)

    assert result["sn"] == "build-1"
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/demo/script-team/-/build/start")
    assert kwargs["headers"]["Authorization"] == "Bearer token"
    assert kwargs["json"]["event"] == "api_trigger_script_team_custom_api"
    assert kwargs["json"]["sync"] == "false"
    assert json.loads(kwargs["json"]["env"]["scriptRequest"])["project_title"] == "钩子测试"


def test_trigger_stage_uses_remote_event_and_compressed_checkpoint(tmp_path: Path) -> None:
    session = _Session([_Response({"success": True, "sn": "stage-build"})])
    config = _config(tmp_path)
    client = CodeBuddyNpcClient(config, session=session)
    job = CodeBuddyNpcJobStore(config).create(
        user_id=1,
        request_payload={"project_title": "远程分步", "source_text": "父子诀别。"},
    )
    job["recovered_files"] = {"contract": "创作合同"}
    job["stage_resume_text"] = "第1集\n已完成断点"

    result = client.trigger_stage(job, stage="story_architect", feedback="保留结局")

    assert result["remote_stage"] == "story_architect"
    payload = session.calls[0][2]["json"]
    assert payload["event"] == "api_trigger_script_team_stage_custom_api"
    assert payload["env"]["scriptStage"] == "story_architect"
    checkpoint = json.loads(
        gzip.decompress(base64.b64decode(payload["env"]["scriptStateBundle"])).decode("utf-8")
    )
    assert checkpoint["recovered_files"]["contract"] == "创作合同"
    assert checkpoint["resume_stage"] == "story_architect"
    assert checkpoint["stage_resume_text"] == "第1集\n已完成断点"
    request_payload = json.loads(
        gzip.decompress(base64.b64decode(payload["env"]["scriptRequestBundle"])).decode("utf-8")
    )
    assert request_payload["stage_feedback"] == "保留结局"


def test_trigger_stage_compresses_large_request_below_linux_single_argument_limit(
    tmp_path: Path,
) -> None:
    session = _Session([_Response({"success": True, "sn": "stage-build"})])
    config = _config(tmp_path)
    client = CodeBuddyNpcClient(config, session=session)
    job = CodeBuddyNpcJobStore(config).create(
        user_id=1,
        request_payload={"project_title": "长材料", "source_text": "人物冲突与选择。" * 30_000},
    )

    client.trigger_stage(job, stage="showrunner")

    env = session.calls[0][2]["json"]["env"]
    assert "scriptRequest" not in env
    assert len(env["scriptRequestBundle"].encode("ascii")) < 128 * 1024
    request_payload = json.loads(
        gzip.decompress(base64.b64decode(env["scriptRequestBundle"])).decode("utf-8")
    )
    assert request_payload["source_text"] == job["request"]["source_text"]


def test_trigger_final_editor_sends_only_required_checkpoint_artifacts(tmp_path: Path) -> None:
    session = _Session([_Response({"success": True, "sn": "stage-build"})])
    config = _config(tmp_path)
    client = CodeBuddyNpcClient(config, session=session)
    job = CodeBuddyNpcJobStore(config).create(
        user_id=1,
        request_payload={"project_title": "终审精简", "source_text": "父子诀别。"},
    )
    job["recovered_files"] = {
        "contract": "创作合同",
        "story": "不应发送的故事圣经" * 10_000,
        "characters": "终审需要的人物方案" * 10_000,
        "episodes": "终审需要的分集卡" * 10_000,
        "draft": "完整正文",
        "story_state": '{"continuity":"状态"}',
    }
    job["final_script"] = "旧终稿也不应发送"

    client.trigger_stage(job, stage="final_editor")

    payload = session.calls[0][2]["json"]
    encoded = payload["env"]["scriptStateBundle"]
    checkpoint = json.loads(
        gzip.decompress(base64.b64decode(encoded)).decode("utf-8")
    )
    assert checkpoint == {
        "recovered_files": {
            "contract": "创作合同",
            "characters": "终审需要的人物方案" * 10_000,
            "episodes": "终审需要的分集卡" * 10_000,
            "draft": "完整正文",
            "story_state": '{"continuity":"状态"}',
        },
        "resume_stage": "final_editor",
        "stage_resume_text": "",
    }
    assert len(encoded) < 4_000


def test_trigger_final_editor_allows_missing_optional_story_state(tmp_path: Path) -> None:
    session = _Session([_Response({"success": True, "sn": "stage-build"})])
    config = _config(tmp_path)
    client = CodeBuddyNpcClient(config, session=session)
    job = CodeBuddyNpcJobStore(config).create(
        user_id=1,
        request_payload={
            "project_title": "状态降级终审",
            "adaptation_direction": "保留人物关系并完成终审",
        },
    )
    job["recovered_files"] = {
        "contract": "创作合同",
        "characters": "人物声音圣经",
        "episodes": "完整分集卡",
        "draft": "完整正文",
    }

    result = client.trigger_stage(job, stage="final_editor")

    assert result["remote_stage"] == "final_editor"
    payload = session.calls[0][2]["json"]
    checkpoint = json.loads(
        gzip.decompress(
            base64.b64decode(payload["env"]["scriptStateBundle"])
        ).decode("utf-8")
    )
    assert "story_state" not in checkpoint["recovered_files"]


def test_refresh_remote_stage_recovers_artifact(tmp_path: Path) -> None:
    status = {
        "status": "success",
        "pipelinesStatus": {
            "pipeline-1": {
                "id": "pipeline-1",
                "stages": [{"id": "stage-1", "name": "远程单节点编剧", "status": "success"}],
            }
        },
    }
    log = {
        "content": [
            "__SCRIPT_TEAM_STAGE_BEGIN__",
            "story_architect",
            "主线：父亲失踪留下未偿还债务。",
            "__SCRIPT_TEAM_STAGE_END__",
        ]
    }
    session = _Session([_Response(status), _Response(log)])
    config = _config(tmp_path)
    job = CodeBuddyNpcJobStore(config).create(
        user_id=1,
        request_payload={"project_title": "远程恢复", "source_text": "父亲失踪。"},
    )
    job.update(
        {
            "build": {"sn": "stage-build"},
            "remote_kind": "stage",
            "remote_stage": "story_architect",
            "status": "running",
        }
    )

    refreshed = CodeBuddyNpcClient(config, session=session).refresh(job)

    assert refreshed["status"] == "stage_ready"
    assert refreshed["recovered_files"]["story"].startswith("主线")


def test_refresh_remote_stage_recovers_compressed_artifact_after_log_truncation(
    tmp_path: Path,
) -> None:
    result = (
        "第1集：囚笼裂缝\n承接事实：旧锁链断裂\n开场钩子：牢门自动打开\n"
        "最短因果锚：守卫撤离\n主角目标：逃出囚笼\n主角主动动作：拆下锁链\n"
        "阻力：出口封死\n选择与代价：以伤换路\n本集主线推进：取得钥匙\n"
        "结尾状态：警报响起\n下一集第一有效动作：冲向暗门\n"
        + ("主角承担代价并推动下一步。\n" * 4_000)
    )
    encoded = base64.b64encode(
        gzip.compress(f"episode_continuity\n{result}".encode("utf-8"))
    ).decode("ascii")
    status = {
        "status": "success",
        "pipelinesStatus": {
            "pipeline-1": {
                "id": "pipeline-1",
                "stages": [{"id": "stage-1", "name": "远程单节点编剧", "status": "success"}],
            }
        },
    }
    log = {
        "content": [
            "The log is truncated because the original stage output was too long.",
            "__SCRIPT_TEAM_STAGE_GZIP_BEGIN__",
            *[encoded[index : index + 160] for index in range(0, len(encoded), 160)],
            "__SCRIPT_TEAM_STAGE_GZIP_END__",
        ]
    }
    session = _Session([_Response(status), _Response(log)])
    config = _config(tmp_path)
    job = CodeBuddyNpcJobStore(config).create(
        user_id=1,
        request_payload={
            "project_title": "长分集卡",
            "source_text": "百年囚笼。",
            "episodes": 1,
        },
    )
    job.update(
        {
            "build": {"sn": "compressed-stage-build"},
            "remote_kind": "stage",
            "remote_stage": "episode_continuity",
            "status": "running",
        }
    )

    refreshed = CodeBuddyNpcClient(config, session=session).refresh(job)

    assert refreshed["status"] == "stage_ready"
    assert refreshed["recovered_files"]["episodes"] == result.strip()


def test_failed_remote_stage_preserves_partial_episode_checkpoint(tmp_path: Path) -> None:
    fields = (
        "承接事实", "开场钩子", "最短因果锚", "主角目标", "主角主动动作",
        "阻力", "选择与代价", "本集主线推进", "结尾状态", "下一集第一有效动作",
    )
    partial = "\n\n".join(
        f"第{episode}集：《断点{episode}》\n"
        + "\n".join(f"{field}：第{episode}集有效内容" for field in fields)
        for episode in range(1, 6)
    )
    encoded = base64.b64encode(
        gzip.compress(f"episode_continuity\n{partial}".encode("utf-8"))
    ).decode("ascii")
    status = {
        "status": "error",
        "pipelinesStatus": {
            "pipeline-1": {
                "id": "pipeline-1",
                "stages": [{"id": "stage-1", "name": "远程单节点编剧", "status": "failed"}],
            }
        },
    }
    log = {
        "content": [
            "__SCRIPT_TEAM_STAGE_GZIP_BEGIN__",
            *[encoded[index : index + 160] for index in range(0, len(encoded), 160)],
            "__SCRIPT_TEAM_STAGE_GZIP_END__",
        ]
    }
    session = _Session([_Response(status), _Response(log)])
    config = _config(tmp_path)
    job = CodeBuddyNpcJobStore(config).create(
        user_id=1,
        request_payload={"project_title": "30集断点", "source_text": "测试", "episodes": 30},
    )
    job.update(
        {
            "build": {"sn": "failed-stage-build"},
            "remote_kind": "stage",
            "remote_stage": "episode_continuity",
            "status": "running",
        }
    )

    refreshed = CodeBuddyNpcClient(config, session=session).refresh(job)

    assert refreshed["status"] == "failed"
    assert refreshed["stage_resume_text"] == partial
    assert refreshed["remote_checkpoint"]["completed_episodes"] == [1, 2, 3, 4, 5]
    assert refreshed["batch_progress"]["completed_ranges"] == [[1, 5]]
    assert refreshed["batch_progress"]["current_start"] == 6
    assert refreshed["batch_progress"]["current_end"] == 10
    assert "可从云端断点补齐" in refreshed["error"]


def test_successful_stage_without_marker_uses_complete_saved_checkpoint(tmp_path: Path) -> None:
    complete = "\n\n".join(
        f"第{episode}集：《断点{episode}》\n场景1：办公室｜日｜内\n人物：主角\n"
        "主角：继续。\n主角把文件放到桌上。"
        for episode in range(1, 6)
    )
    status = {
        "status": "success",
        "pipelinesStatus": {
            "pipeline-1": {
                "id": "pipeline-1",
                "stages": [{"id": "stage-1", "name": "远程单节点编剧", "status": "success"}],
            }
        },
    }
    session = _Session([_Response(status), _Response({"content": ["Finished, code: 0"]})])
    config = _config(tmp_path)
    job = CodeBuddyNpcJobStore(config).create(
        user_id=1,
        request_payload={"project_title": "断点恢复", "source_text": "测试", "episodes": 5},
    )
    job.update(
        {
            "build": {"sn": "completed-without-marker"},
            "remote_kind": "stage",
            "remote_stage": "script_writer",
            "stage_resume_text": complete,
            "status": "running",
        }
    )

    refreshed = CodeBuddyNpcClient(config, session=session).refresh(job)

    assert refreshed["status"] == "stage_ready"
    assert refreshed["recovered_files"]["draft"] == complete
    assert refreshed["stage_resume_text"] == ""


def test_successful_stage_without_marker_pauses_on_partial_checkpoint(tmp_path: Path) -> None:
    partial = "\n\n".join(
        f"第{episode}集：《断点{episode}》\n场景1：办公室｜日｜内\n人物：主角\n"
        "主角：继续。\n主角把文件放到桌上。"
        for episode in range(1, 21)
    )
    status = {
        "status": "success",
        "pipelinesStatus": {
            "pipeline-1": {
                "id": "pipeline-1",
                "stages": [{"id": "stage-1", "name": "远程单节点编剧", "status": "success"}],
            }
        },
    }
    session = _Session([_Response(status), _Response({"content": ["Finished, code: 0"]})])
    config = _config(tmp_path)
    job = CodeBuddyNpcJobStore(config).create(
        user_id=1,
        request_payload={"project_title": "断点恢复", "source_text": "测试", "episodes": 30},
    )
    job.update(
        {
            "build": {"sn": "partial-without-marker"},
            "remote_kind": "stage",
            "remote_stage": "episode_continuity",
            "stage_resume_text": partial,
            "status": "running",
        }
    )

    refreshed = CodeBuddyNpcClient(config, session=session).refresh(job)

    assert refreshed["status"] == "stage_paused"
    assert refreshed["active_stage"] == ""
    assert refreshed["remote_checkpoint"]["completed_episodes"] == list(range(1, 21))
    assert refreshed["batch_progress"]["completed_ranges"] == [
        [1, 5],
        [6, 10],
        [11, 15],
        [16, 20],
    ]
    assert refreshed["batch_progress"]["current_start"] == 21
    assert refreshed["batch_progress"]["current_end"] == 25
    assert "继续补齐" in refreshed["error"]


def test_authorization_header_preserves_existing_bearer_prefix(tmp_path: Path) -> None:
    config = _config(tmp_path, access_token="Bearer token")
    client = CodeBuddyNpcClient(config, session=_Session([]))

    assert client._headers()["Authorization"] == "Bearer token"


def test_client_retries_dns_failure_with_configured_fallback(tmp_path: Path) -> None:
    session = _DnsRetrySession(
        [
            requests.ConnectionError("getaddrinfo failed"),
            _Response({"status": "running"}),
        ]
    )
    config = _config(tmp_path, fallback_ip="159.75.173.90")

    result = CodeBuddyNpcClient(config, session=session).build_status("build-1")

    assert result["status"] == "running"
    assert len(session.calls) == 2


def test_refresh_reads_final_script_from_completed_stage_log(tmp_path: Path) -> None:
    status = {
        "status": "success",
        "pipelinesStatus": {
            "pipeline-1": {
                "id": "pipeline-1",
                "stages": [
                    {"id": "stage-1", "name": "终审导演", "status": "success"}
                ],
            }
        },
    }
    log = {
        "content": [
            "终审开始",
            "__SCRIPT_TEAM_RESULT_BEGIN__",
            "第1集\n“跑！别回头！”\n埃里克猛地睁开眼。",
            "__SCRIPT_TEAM_RESULT_END__",
        ]
    }
    session = _Session([_Response(status), _Response(log)])
    config = _config(tmp_path)
    client = CodeBuddyNpcClient(config, session=session)
    job = CodeBuddyNpcJobStore(config).create(
        user_id=1,
        request_payload={"project_title": "连续剧", "source_text": "父子诀别。"},
    )
    job["build"] = {"sn": "build-1"}
    job["status"] = "running"
    job["poll_warning"] = "temporary network error"

    refreshed = client.refresh(job)

    assert refreshed["status"] == "completed"
    assert refreshed["progress"] == 100
    assert "poll_warning" not in refreshed
    assert refreshed["final_script"].startswith("第1集")
    assert "跑！别回头！" in refreshed["final_script"]


def test_refresh_recovers_final_script_when_strict_gate_failed(tmp_path: Path) -> None:
    status = {
        "status": "error",
        "pipelinesStatus": {
            "pipeline-1": {
                "id": "pipeline-1",
                "stages": [
                    {"id": "stage-7", "name": "终审与钩子编辑", "status": "success"},
                    {"id": "stage-8", "name": "最终连续性门禁", "status": "error"},
                ],
            }
        },
    }
    final_log = {
        "content": [
            "Runner $ printf '%s' 'THE LAST HOWL",
            "第1集：The Return",
            "Kael opened the door. Joran stopped breathing.",
            "' > '.script-team/final_script.txt'",
        ]
    }
    gate_report = {
        "schema_version": "1.0",
        "mode": "strict",
        "ok": False,
        "errors": [
            {
                "code": "state.voice.samples",
                "message": "Joran必须提供三句声音样本",
            }
        ],
        "warnings": [],
        "metrics": {},
    }
    gate_log = {
        "content": [
            "validator start",
            json.dumps(gate_report, ensure_ascii=False),
        ]
    }
    session = _Session(
        [
            _Response(status),
            _Response(final_log),
            _Response(gate_log),
        ]
    )
    config = _config(tmp_path)
    client = CodeBuddyNpcClient(config, session=session)
    job = CodeBuddyNpcJobStore(config).create(
        user_id=1,
        request_payload={"project_title": "狼人剧", "source_text": "狼人归来。"},
    )
    job["build"] = {"sn": "build-1"}
    job["status"] = "running"

    refreshed = client.refresh(job)

    assert refreshed["status"] == "completed_with_warnings"
    assert refreshed["progress"] == 100
    assert refreshed["final_script"].startswith("THE LAST HOWL")
    assert "Kael opened the door" in refreshed["final_script"]
    assert refreshed["quality_gate"]["ok"] is False
    assert "Joran必须提供三句声音样本" in refreshed["error"]


def test_trigger_reports_missing_connection_settings(tmp_path: Path) -> None:
    config = _config(tmp_path, repository="", access_token="")
    client = CodeBuddyNpcClient(config, session=_Session([]))

    with pytest.raises(CodeBuddyNpcError, match="尚未配置"):
        client.trigger({"job_id": "npc-1", "request": {"project_title": "测试"}})


@pytest.mark.parametrize("episode_count", [3, 12, 40])
def test_compact_story_state_follows_dynamic_episode_count(episode_count: int) -> None:
    draft = "\n\n".join(
        f"第{episode}集\n场景1：办公室｜日｜内\n主角：第{episode}集开始。\n主角：第{episode}集结束。"
        for episode in range(1, episode_count + 1)
    )
    payload = json.loads(
        _compact_story_state(
            {
                "request": {
                    "project_title": "动态剧",
                    "episodes": episode_count,
                    "episode_word_count": 600,
                },
                "recovered_files": {"draft": draft, "episodes": draft},
            }
        )
    )

    assert payload["project"]["episode_count"] == episode_count
    assert len(payload["episodes"]) == episode_count
    assert payload["episodes"][-1]["episode"] == episode_count
    assert payload["cost_control"]["model_call_used"] is False


def test_compact_story_state_preserves_continuation_episode_numbers() -> None:
    draft = "\n\n".join(
        f"第{episode}集\n场景1：办公室｜日｜内\n主角：第{episode}集开始。\n主角：第{episode}集结束。"
        for episode in range(18, 31)
    )

    payload = json.loads(
        _compact_story_state(
            {
                "request": {
                    "project_title": "续写剧",
                    "mode": "续写",
                    "episodes": 13,
                    "source_last_episode": 17,
                    "episode_start": 18,
                    "episode_end": 30,
                    "episode_word_count": 600,
                },
                "recovered_files": {"draft": draft, "episodes": draft},
            }
        )
    )

    assert payload["project"]["episode_count"] == 13
    assert [item["episode"] for item in payload["episodes"]] == list(range(18, 31))
    assert payload["episodes"][0]["continuity_bridge"]["previous_episode"] == 17
    assert "已有第17集结尾" in payload["episodes"][0]["continuity_bridge"]["from_action"]


def test_episode_slice_selects_requested_dynamic_range() -> None:
    text = "\n".join(f"## 第{episode}集\n内容{episode}" for episode in range(1, 13))

    selected = _episode_slice(text, 6, 10)

    assert "第6集" in selected
    assert "第10集" in selected
    assert "第5集" not in selected
    assert "第11集" not in selected


def test_public_job_hides_large_internal_resume_and_stage_logs() -> None:
    payload = public_job(
        {
            "job_id": "npc-test",
            "user_id": 1,
            "stage_resume_text": "正文" * 100,
            "stage_outputs": {"总编剧": "日志"},
        }
    )

    assert "stage_resume_text" not in payload
    assert "stage_outputs" not in payload
    assert payload["stage_checkpoint_chars"] == 200
    assert payload["stage_output_keys"] == ["总编剧"]
