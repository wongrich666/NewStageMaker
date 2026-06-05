from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

from workflow_code_skeleton.app.server import create_app
from workflow_code_skeleton.app.orchestrators import fastgpt_hybrid_workflow as flow
from workflow_code_skeleton.app.services.auth_store import auth_store
from workflow_code_skeleton.app.services.fastgpt_contracts import (
    APPEARANCE_MAPPING,
    BEAT_CHECKPOINT_TIMELINE,
    BATCH_CAUSAL_CONFLICT_PLAN,
    BATCH_CAUSAL_CONFLICT_REVIEW,
    BATCH_ENRICHED_EPISODE_PLAN,
    BATCH_SCRIPT_REVIEW,
    BATCH_SCRIPT_TEXT,
    CHARACTER_PLAN,
    CHARACTER_STORYLINES,
    CONFLICT_MEMORY,
    EPISODE_WORD_COUNT,
    FRAMEWORK_PLAN_PACKAGE,
    SCENE_DICTIONARY,
    SCRIPT_MEMORY,
    SCRIPT_START_EPISODE,
    SCRIPT_WORLD_RULES_DIGEST,
    STAGE_FRAMEWORK_APPEARANCE_MAPPING,
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_MEMORY,
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_REWRITE,
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_REVIEW,
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE,
    STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN,
    STAGE_FRAMEWORK_SCRIPT_MEMORY,
    STAGE_FRAMEWORK_SCRIPT_REVIEW,
    STAGE_FRAMEWORK_SCRIPT_REWRITE,
    STAGE_FRAMEWORK_SCRIPT_WRITE,
    TOTAL_EPISODES,
    contract_for,
)
from workflow_code_skeleton.app.services.workflow_preference_keys import inject_stage_preference


def _auth_headers() -> dict[str, str]:
    username = f"fts_{uuid.uuid4().hex[:8]}"
    user = auth_store.register_user(username, "password123")
    token = auth_store.create_session_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def _framework_package() -> dict[str, object]:
    return {
        "basic_config": {"episodes_per_season": 5, "minutes_per_episode": 2},
        "worldview_plan": {"world_type": "都市悬疑"},
        "character_plan": {"protagonist": {"name": "林渡"}},
        "beat_checkpoint_timeline": [{"beat_no": 1, "beat_name": "开场"}],
        "character_storylines": [{"character": "林渡", "line": "查明旧案"}],
    }


def _episode_plan(total: int) -> list[dict[str, object]]:
    return [{"episode": episode, "title": f"第{episode}集"} for episode in range(1, total + 1)]


def _valid_conflict_plan(start: int, end: int) -> dict[str, object]:
    return {
        "batch_meta": {"batch_start_episode": start, "batch_end_episode": end},
        "global_conflict_engine": {"summary": "推进因果冲突"},
        "episodes": [
            {
                "episode": episode,
                "episode_title": f"第{episode}集",
                "active_characters": ["林渡"],
                "scene_refs": ["scene_A"],
                "carry_in": "承接上一集",
                "why_now": "线索到达",
                "character_motivation": "查明真相",
                "emotional_precondition": "焦灼",
                "scene_cause_chain": "发现线索并升级冲突",
                "non_conflict_moment": "短暂喘息",
                "natural_transition": "转入下一场",
                "opening_image": "夜色街口",
                "opening_action": "林渡追查",
                "current_goal": "拿到证据",
                "core_obstacle": "对手阻拦",
                "episode_state_change": "证据更近一步",
                "ending_hook": "新疑点出现",
                "dialogue_strategy": "短句压迫",
            }
            for episode in range(start, end + 1)
        ],
    }


def _stage11_request(asset_id: int, total: int = 60) -> dict[str, object]:
    return {
        "framework_asset_id": asset_id,
        "total_episodes": total,
        "allEnrichedEpisodePlan": _episode_plan(total),
        "sceneDictionary": {"core_scenes": [{"scene_id": "scene_A"}]},
        "scriptWorldRulesDigest": {"world_type": "都市悬疑"},
        "appearanceMapping": {"characters": [{"name": "林渡"}]},
    }


def _save_framework_asset(client, headers, *, total: int = 60) -> int:
    package = _framework_package()
    package["basic_config"] = {"episodes_per_season": total, "minutes_per_episode": 2}
    save_response = client.post(
        "/api/framework-planner/assets/save",
        headers=headers,
        json={
            "project_title": "夜行审判",
            "framework_plan_package": package,
            "validation_report": {"status": "pass"},
        },
    )
    assert save_response.status_code == 200
    return int(save_response.get_json()["project_id"])


def test_inject_stage_preference_writes_real_short_key_and_common_keys() -> None:
    variables: dict[str, object] = {}

    inject_stage_preference(variables, "偏好文本", ["xOgb7piW"])

    assert variables["xOgb7piW"] == "偏好文本"
    assert variables["stagePreference"] == "偏好文本"
    assert variables["userPreferences"] == "偏好文本"
    assert variables["userRequirements"] == "偏好文本"


def test_full_framework_to_script_orchestrator_injects_all_stage_short_keys() -> None:
    variables = {
        "stage_prompts": {
            "scene": "08偏好",
            "appearance": "09偏好",
            "episode": "10偏好",
            "conflict": "11偏好",
            "script_text": "12偏好",
        }
    }

    expected = {
        "08": ("gsf2Zudx", "08偏好"),
        "09": ("oDaFpjKr", "09偏好"),
        "10": ("shmRs8OT", "10偏好"),
        "11_write": ("tFeUfwch", "11偏好"),
        "11_rewrite": ("sfQm5kD7", "11偏好"),
        "12_write": ("xOgb7piW", "12偏好"),
        "12_rewrite": ("ls0n1182", "12偏好"),
    }
    for workflow_stage, (short_key, text) in expected.items():
        context: dict[str, object] = {}
        flow._inject_framework_stage_preference(context, variables, workflow_stage)
        assert context[short_key] == text
        assert context["stagePreference"] == text


def test_single_stage_08_09_10_routes_send_real_short_keys_and_context() -> None:
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    headers = _auth_headers()
    captured: list[tuple[str, dict[str, object]]] = []

    def fake_run_stage(stage_name: str, variables: dict[str, object]):
        captured.append((stage_name, dict(variables)))
        if stage_name == "framework_scene_dictionary":
            return {
                "sceneDictionary": {"core_scenes": [{"scene_id": "scene_A"}]},
                "scriptWorldRulesDigest": {"world_type": "都市悬疑"},
            }
        if stage_name == "framework_appearanceMapping":
            return {
                "appearanceMapping": {
                    "mapping_version": "appearance_mapping_v1",
                    "characters": [{"name": "林渡", "default_name": "林渡"}],
                }
            }
        if stage_name == "framework_enriched_episode_plan":
            return {
                "allEnrichedEpisodePlan": [{"episode": 1, "title": "开场"}],
                "allEnrichedEpisodePlanText": "第一集",
            }
        raise AssertionError(stage_name)

    package = _framework_package()
    with patch("workflow_code_skeleton.app.services.fastgpt_client.fastgpt_client.run_stage", side_effect=fake_run_stage):
        response08 = client.post(
            "/api/framework-to-script/stage/08",
            headers=headers,
            json={
                "framework_plan_package": package,
                "stage_prompts": {"scene": "08偏好"},
            },
        )
        assert response08.status_code == 200

        response09 = client.post(
            "/api/framework-to-script/stage/09",
            headers=headers,
            json={
                "framework_plan_package": package,
                "sceneDictionary": {"core_scenes": [{"scene_id": "scene_A"}]},
                "stage_prompts": {"appearance": "09偏好"},
            },
        )
        assert response09.status_code == 200

        response10 = client.post(
            "/api/framework-to-script/stage/10",
            headers=headers,
            json={
                "framework_plan_package": package,
                "sceneDictionary": {"core_scenes": [{"scene_id": "scene_A"}]},
                "scriptWorldRulesDigest": {"world_type": "都市悬疑"},
                "appearanceMapping": {"characters": [{"name": "林渡"}]},
                "stage_prompts": {"episode": "10偏好"},
            },
        )
        assert response10.status_code == 200

    stage08_vars = captured[0][1]
    assert stage08_vars["gsf2Zudx"] == "08偏好"
    assert stage08_vars["frameworkPlanPackage"] == package
    assert stage08_vars["beatCheckpointTimeline"] == package["beat_checkpoint_timeline"]
    assert stage08_vars["characterStorylines"] == package["character_storylines"]

    stage09_vars = captured[1][1]
    assert stage09_vars["oDaFpjKr"] == "09偏好"
    assert stage09_vars["beatCheckpointTimeline"] == package["beat_checkpoint_timeline"]
    assert stage09_vars["sceneDictionary"]

    stage10_vars = captured[2][1]
    assert stage10_vars["shmRs8OT"] == "10偏好"
    assert stage10_vars["beatCheckpointTimeline"] == package["beat_checkpoint_timeline"]
    assert stage10_vars["characterStorylines"] == package["character_storylines"]


def test_framework_asset_import_restores_stage_prompts_for_stage08() -> None:
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    headers = _auth_headers()
    package = _framework_package()
    captured: list[dict[str, object]] = []

    save_response = client.post(
        "/api/framework-planner/assets/save",
        headers=headers,
        json={
            "project_title": "夜行审判",
            "framework_plan_package": package,
            "validation_report": {"status": "pass"},
            "preference_snapshot": {
                "stage_preferences": {
                    "08": "资产08偏好",
                    "scene": "资产08偏好",
                    "09": "资产09偏好",
                    "appearance": "资产09偏好",
                    "10": "资产10偏好",
                    "episode": "资产10偏好",
                    "11": "资产11偏好",
                    "conflict": "资产11偏好",
                    "12": "资产12偏好",
                    "script_text": "资产12偏好",
                }
            },
        },
    )
    assert save_response.status_code == 200
    asset_id = save_response.get_json()["project_id"]

    def fake_run_stage(stage_name: str, variables: dict[str, object]):
        captured.append(dict(variables))
        return {
            "sceneDictionary": {"core_scenes": [{"scene_id": "scene_A"}]},
            "scriptWorldRulesDigest": {"world_type": "都市悬疑"},
        }

    with patch("workflow_code_skeleton.app.services.fastgpt_client.fastgpt_client.run_stage", side_effect=fake_run_stage):
        response = client.post(
            "/api/framework-to-script/stage/08",
            headers=headers,
            json={"framework_asset_id": asset_id},
        )

    assert response.status_code == 200
    assert captured[0]["gsf2Zudx"] == "资产08偏好"


def test_framework_asset_without_package_can_import_from_stage_outputs() -> None:
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    headers = _auth_headers()

    save_response = client.post(
        "/api/framework-planner/assets/save",
        headers=headers,
        json={
            "project_title": "旧资产",
            "basic_config": {"episodes_per_season": 5, "minutes_per_episode": 2},
            "source_brief": {"premise": "雨夜旧案"},
            "worldview_plan": {"world_type": "都市悬疑"},
            "character_plan": {"protagonist": {"name": "林渡"}},
            "beat_checkpoint_timeline": [{"beat_no": 1, "beat_name": "开场"}],
            "character_storylines": [{"character": "林渡", "line": "查明旧案"}],
            "adaptation_guide": {"tone": "冷峻"},
            "asset_state": {"status": "completed", "current_stage": "package"},
        },
    )
    assert save_response.status_code == 200
    asset_id = save_response.get_json()["project_id"]

    list_response = client.get("/api/framework-assets", headers=headers)
    assert list_response.status_code == 200
    listed_asset = next(item for item in list_response.get_json()["assets"] if str(item["asset_id"]) == str(asset_id))
    assert listed_asset["can_import"] is True

    detail_response = client.get(f"/api/framework-assets/{asset_id}", headers=headers)
    assert detail_response.status_code == 200
    package = detail_response.get_json()["asset"]["framework_plan_package"]
    assert package["import_package_synthesized"] is True
    assert package["beat_checkpoint_timeline"] == [{"beat_no": 1, "beat_name": "开场"}]
    assert package["character_storylines"] == [{"character": "林渡", "line": "查明旧案"}]


def test_stage10_persists_completed_state_and_output_aliases_for_refresh() -> None:
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    headers = _auth_headers()
    package = _framework_package()

    save_response = client.post(
        "/api/framework-planner/assets/save",
        headers=headers,
        json={
            "project_title": "夜行审判",
            "framework_plan_package": package,
            "validation_report": {"status": "pass"},
        },
    )
    assert save_response.status_code == 200
    asset_id = save_response.get_json()["project_id"]

    def fake_run_stage(stage_name: str, variables: dict[str, object]):
        if stage_name == "framework_scene_dictionary":
            return {
                "sceneDictionary": {"core_scenes": [{"scene_id": "scene_A"}]},
                "scriptWorldRulesDigest": {"world_type": "都市悬疑"},
            }
        if stage_name == "framework_appearanceMapping":
            return {"appearanceMapping": {"characters": [{"name": "林渡", "alias": "A"}]}}
        if stage_name == "framework_enriched_episode_plan":
            return {
                "allEnrichedEpisodePlan": [{"episode": 1, "title": "开场"}],
                "allEnrichedEpisodePlanText": "第一集",
            }
        raise AssertionError(stage_name)

    with patch("workflow_code_skeleton.app.services.fastgpt_client.fastgpt_client.run_stage", side_effect=fake_run_stage):
        response08 = client.post("/api/framework-to-script/stage/08", headers=headers, json={"framework_asset_id": asset_id})
        assert response08.status_code == 200
        response09 = client.post("/api/framework-to-script/stage/09", headers=headers, json={"framework_asset_id": asset_id})
        assert response09.status_code == 200
        response10 = client.post("/api/framework-to-script/stage/10", headers=headers, json={"framework_asset_id": asset_id})
        assert response10.status_code == 200

    stage10_payload = response10.get_json()
    assert stage10_payload["framework_enriched_episode_plan"]["allEnrichedEpisodePlan"] == [{"episode": 1, "title": "开场"}]
    assert stage10_payload["batchEnrichedEpisodePlan"] == [{"episode": 1, "title": "开场"}]
    assert stage10_payload["stageOutputs"]["allEnrichedEpisodePlan"] == [{"episode": 1, "title": "开场"}]
    assert "10" in stage10_payload["completedStages"]

    detail_response = client.get(f"/api/framework-assets/{asset_id}", headers=headers)
    assert detail_response.status_code == 200
    asset = detail_response.get_json()["asset"]
    workspace_state = asset["framework_to_script_state"]
    assert workspace_state["stages"]["10"]["status"] == "completed"
    assert "10" in workspace_state["completedStages"]
    assert workspace_state["stageOutputs"]["allEnrichedEpisodePlan"] == [{"episode": 1, "title": "开场"}]
    assert workspace_state["stageOutputs"]["batchEnrichedEpisodePlan"] == [{"episode": 1, "title": "开场"}]
    assert asset["scriptStages"]["stage10"]["allEnrichedEpisodePlan"] == [{"episode": 1, "title": "开场"}]


def test_stage11_single_click_runs_all_batches_and_marks_complete() -> None:
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    headers = _auth_headers()
    asset_id = _save_framework_asset(client, headers, total=60)
    write_starts: list[int] = []

    def fake_run_stage(stage_name: str, variables: dict[str, object]):
        start = int(variables.get("conflictStartEpisode") or 1)
        end = min(start + 4, 60)
        if stage_name == STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE:
            write_starts.append(start)
            return {"batchCausalConflictPlan": _valid_conflict_plan(start, end)}
        if stage_name == STAGE_FRAMEWORK_CAUSAL_CONFLICT_REVIEW:
            return {"reviewPassed": True, "rewriteRequired": False}
        if stage_name == STAGE_FRAMEWORK_CAUSAL_CONFLICT_MEMORY:
            return {"conflictMemory": f"memory-{start}-{end}"}
        raise AssertionError(stage_name)

    with patch("workflow_code_skeleton.app.services.fastgpt_client.fastgpt_client.run_stage", side_effect=fake_run_stage):
        response = client.post("/api/framework-to-script/stage/11", headers=headers, json=_stage11_request(asset_id, 60))

    assert response.status_code == 200
    payload = response.get_json()
    assert write_starts == list(range(1, 61, 5))
    assert payload["isComplete"] is True
    assert payload["completed_batches"] == 12
    assert sorted((int(key) for key in payload["batches"].keys())) == list(range(1, 61, 5))

    detail_response = client.get(f"/api/framework-assets/{asset_id}", headers=headers)
    workspace_state = detail_response.get_json()["asset"]["framework_to_script_state"]
    assert workspace_state["stages"]["11"]["status"] == "completed"
    assert "11" in workspace_state["completedStages"]


def test_stage11_resume_uses_first_missing_continuous_batch() -> None:
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    headers = _auth_headers()
    asset_id = _save_framework_asset(client, headers, total=15)
    write_starts: list[int] = []

    def fake_run_stage(stage_name: str, variables: dict[str, object]):
        start = int(variables.get("conflictStartEpisode") or 1)
        end = min(start + 4, 15)
        if stage_name == STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE:
            write_starts.append(start)
            return {"batchCausalConflictPlan": _valid_conflict_plan(start, end)}
        if stage_name == STAGE_FRAMEWORK_CAUSAL_CONFLICT_REVIEW:
            return {"reviewPassed": True, "rewriteRequired": False}
        if stage_name == STAGE_FRAMEWORK_CAUSAL_CONFLICT_MEMORY:
            return {"conflictMemory": f"memory-{start}-{end}"}
        raise AssertionError(stage_name)

    with patch("workflow_code_skeleton.app.services.fastgpt_client.fastgpt_client.run_stage", side_effect=fake_run_stage):
        request_1 = {**_stage11_request(asset_id, 15), "batchStartEpisode": 1}
        response_1 = client.post("/api/framework-to-script/stage/11", headers=headers, json=request_1)
        assert response_1.status_code == 200
        request_11 = {**_stage11_request(asset_id, 15), "batchStartEpisode": 11}
        response_11 = client.post("/api/framework-to-script/stage/11", headers=headers, json=request_11)
        assert response_11.status_code == 200
        write_starts.clear()
        response = client.post("/api/framework-to-script/stage/11", headers=headers, json=_stage11_request(asset_id, 15))

    assert response.status_code == 200
    payload = response.get_json()
    assert write_starts == [6, 11]
    assert payload["isComplete"] is True
    assert sorted((int(key) for key in payload["batches"].keys())) == [1, 6, 11]


def test_stage12_single_click_runs_all_stage11_batches_and_marks_complete() -> None:
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    headers = _auth_headers()
    asset_id = _save_framework_asset(client, headers, total=10)
    script_starts: list[int] = []

    def fake_run_stage(stage_name: str, variables: dict[str, object]):
        conflict_start = int(variables.get("conflictStartEpisode") or 1)
        script_start = int(variables.get("scriptStartEpisode") or 1)
        if stage_name == STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE:
            return {"batchCausalConflictPlan": _valid_conflict_plan(conflict_start, min(conflict_start + 4, 10))}
        if stage_name == STAGE_FRAMEWORK_CAUSAL_CONFLICT_REVIEW:
            return {"reviewPassed": True, "rewriteRequired": False}
        if stage_name == STAGE_FRAMEWORK_CAUSAL_CONFLICT_MEMORY:
            return {"conflictMemory": f"memory-{conflict_start}"}
        if stage_name == STAGE_FRAMEWORK_SCRIPT_WRITE:
            script_starts.append(script_start)
            end = min(script_start + 4, 10)
            return {"batchScriptText": "\n".join(f"第{episode}集 正文" for episode in range(script_start, end + 1))}
        if stage_name == STAGE_FRAMEWORK_SCRIPT_REVIEW:
            return {"reviewPassed": True, "rewriteRequired": False}
        if stage_name == STAGE_FRAMEWORK_SCRIPT_MEMORY:
            return {"scriptMemory": f"script-memory-{script_start}"}
        raise AssertionError(stage_name)

    with patch("workflow_code_skeleton.app.services.fastgpt_client.fastgpt_client.run_stage", side_effect=fake_run_stage):
        response11 = client.post("/api/framework-to-script/stage/11", headers=headers, json=_stage11_request(asset_id, 10))
        assert response11.status_code == 200
        response12 = client.post(
            "/api/framework-to-script/stage/12",
            headers=headers,
            json={
                "framework_asset_id": asset_id,
                "total_episodes": 10,
                "stage08": {
                    "sceneDictionary": {"core_scenes": [{"scene_id": "scene_A"}]},
                    "scriptWorldRulesDigest": {"world_type": "都市悬疑"},
                },
                "stage09": {"appearanceMapping": {"characters": [{"name": "林渡"}]}},
            },
        )

    assert response12.status_code == 200
    payload = response12.get_json()
    assert script_starts == [1, 6]
    assert payload["isComplete"] is True
    assert payload["completed_batches"] == 2
    assert sorted((int(key) for key in payload["batches"].keys())) == [1, 6]

    detail_response = client.get(f"/api/framework-assets/{asset_id}", headers=headers)
    workspace_state = detail_response.get_json()["asset"]["framework_to_script_state"]
    assert workspace_state["stages"]["12"]["status"] == "completed"
    assert "12" in workspace_state["completedStages"]


def test_framework_to_script_ui_allows_stage_rerun_and_full_script_rewrite() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "workflow_code_skeleton" / "app" / "web" / "static" / "framework_to_script.js").read_text(
        encoding="utf-8"
    )

    assert "asset.can_import !== false" in script
    assert "重写全剧剧本" in script
    assert "resetStage11: true, skipConfirm: true" in script
    assert "resetStage12: true, skipConfirm: true" in script
    assert "framework_enriched_episode_plan" in script
    assert "completedStages" in script
    assert "运行 11" in script
    assert "运行 12" in script
    assert "生成下一批正文" not in script
    assert "hideAction: true" not in script


def test_contracts_keep_required_context_for_late_framework_to_script_stages() -> None:
    conflict_rewrite_vars = {
        TOTAL_EPISODES: 60,
        "sfQm5kD7": "11修订偏好",
        "conflictStartEpisode": 6,
        BATCH_ENRICHED_EPISODE_PLAN: [{"episode": 6}],
        SCENE_DICTIONARY: {"core_scenes": []},
        SCRIPT_WORLD_RULES_DIGEST: {"world_type": "都市"},
        APPEARANCE_MAPPING: {"characters": []},
        BATCH_CAUSAL_CONFLICT_PLAN: {"episodes": []},
        BATCH_CAUSAL_CONFLICT_REVIEW: {"rewriteRequired": True},
        CONFLICT_MEMORY: "上一批冲突记忆",
    }
    conflict_payload = contract_for(STAGE_FRAMEWORK_CAUSAL_CONFLICT_REWRITE).build_input_payload(conflict_rewrite_vars)
    assert conflict_payload["sfQm5kD7"] == "11修订偏好"
    assert conflict_payload[SCENE_DICTIONARY]
    assert conflict_payload[APPEARANCE_MAPPING]

    script_review_vars = {
        TOTAL_EPISODES: 60,
        SCRIPT_START_EPISODE: 6,
        EPISODE_WORD_COUNT: 900,
        BATCH_ENRICHED_EPISODE_PLAN: [{"episode": 6}],
        BATCH_CAUSAL_CONFLICT_PLAN: {"episodes": []},
        SCRIPT_MEMORY: "上一批正文记忆",
        BATCH_SCRIPT_TEXT: "第六集正文",
    }
    review_payload = contract_for(STAGE_FRAMEWORK_SCRIPT_REVIEW).build_input_payload(script_review_vars)
    assert review_payload[SCRIPT_MEMORY] == "上一批正文记忆"

    script_rewrite_vars = {
        **script_review_vars,
        "ls0n1182": "12修订偏好",
        SCRIPT_WORLD_RULES_DIGEST: {"world_type": "都市"},
        APPEARANCE_MAPPING: {"characters": []},
        BATCH_SCRIPT_REVIEW: {"rewriteRequired": True},
    }
    rewrite_payload = contract_for(STAGE_FRAMEWORK_SCRIPT_REWRITE).build_input_payload(script_rewrite_vars)
    assert rewrite_payload["ls0n1182"] == "12修订偏好"
    assert rewrite_payload[SCRIPT_WORLD_RULES_DIGEST]
    assert rewrite_payload[APPEARANCE_MAPPING]
    assert rewrite_payload[SCRIPT_MEMORY] == "上一批正文记忆"


def test_09_10_workflow_prompts_reference_required_context() -> None:
    root = Path(__file__).resolve().parents[2]
    prompt09 = (root / "BETTER_FRAMEWORK_JSONS" / "09_人设服装alias映射.json").read_text(encoding="utf-8")
    prompt10 = (root / "BETTER_FRAMEWORK_JSONS" / "10_丰富分集计划.json").read_text(encoding="utf-8")

    assert "{{$VARIABLE_NODE_ID.beatCheckpointTimeline$}}" in prompt09
    assert "{{$VARIABLE_NODE_ID.beatCheckpointTimeline$}}" in prompt10
    assert "{{$VARIABLE_NODE_ID.characterStorylines$}}" in prompt10


def test_stage_09_10_contracts_keep_beat_and_storyline_inputs() -> None:
    base_vars = {
        FRAMEWORK_PLAN_PACKAGE: {},
        CHARACTER_PLAN: {},
        SCENE_DICTIONARY: {},
        APPEARANCE_MAPPING: {},
        BEAT_CHECKPOINT_TIMELINE: [{"beat_no": 1}],
        CHARACTER_STORYLINES: [{"character": "林渡"}],
    }

    appearance_payload = contract_for(STAGE_FRAMEWORK_APPEARANCE_MAPPING).build_input_payload(base_vars)
    assert appearance_payload[BEAT_CHECKPOINT_TIMELINE] == [{"beat_no": 1}]

    enriched_payload = contract_for(STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN).build_input_payload(base_vars)
    assert enriched_payload[BEAT_CHECKPOINT_TIMELINE] == [{"beat_no": 1}]
    assert enriched_payload[CHARACTER_STORYLINES] == [{"character": "林渡"}]
