from __future__ import annotations

import json

from workflow_code_skeleton.app.orchestrators import fastgpt_hybrid_workflow as flow
from workflow_code_skeleton.app.services.fastgpt_contracts import (
    ALL_ENRICHED_EPISODE_PLAN,
    ALL_SCRIPT,
    APPEARANCE_MAPPING,
    BATCH_CAUSAL_CONFLICT_PLAN,
    BATCH_SCRIPT_TEXT,
    CONFLICT_MEMORY,
    FINAL_SCRIPT,
    SCENE_DICTIONARY,
    SCRIPT_MEMORY,
    SCRIPT_WORLD_RULES_DIGEST,
)
from workflow_code_skeleton.app.services.task_manager import TaskManager, TaskRecord, WorkflowRuntime
from workflow_code_skeleton.app.models.inputs import WorkflowInput
from workflow_code_skeleton.app.models.state import WorkflowState
from workflow_code_skeleton.app.utils.episode import BatchWindow


def _valid_scene_dictionary() -> dict[str, object]:
    return {
        "scene_count": 2,
        "core_scenes": [
            {"scene_id": "S1", "name": "旧港实验楼"},
            {"scene_id": "S2", "name": "发布会现场"},
        ],
    }


def _valid_rules_digest() -> dict[str, object]:
    return {
        "world_type": "近未来商战",
        "core_rules": ["审批窗口期决定节奏"],
        "action_limits": ["不能跳过资金约束"],
        "danger_sources": ["资金断裂", "资料泄露"],
        "do_not_break_rules": ["关键发布前必须二次确认"],
    }


def _valid_appearanceMapping() -> dict[str, object]:
    return {
        "mapping_version": "v1",
        "characters": [
            {
                "name": "林夏",
                "default_name": "林夏",
                "role_type": "主角",
                "identity": "产品负责人",
                "core_desire": "重启项目",
                "deep_motivation": "弥补离开的遗憾",
                "appearance_anchor": "深色外套",
                "outfit_versions": [{"alias": "林夏_工作装"}],
                "alias_rules": {"default": "林夏"},
            }
        ],
    }


def _valid_enriched_plan(total: int = 10) -> list[dict[str, object]]:
    return [
        {
            "episode": episode,
            "title": f"第{episode}集",
            "characters": ["林夏"],
            "scene_refs": ["S1"],
            "scenes": [{"scene_id": "S1", "purpose": "推进主线"}],
            "specific_plot": f"第{episode}集主线推进",
            "pressure_sources": ["资金压力"],
            "ending_hook": "对手放出新证据",
            "text_view": f"第{episode}集文本视图",
        }
        for episode in range(1, total + 1)
    ]


def _valid_causal_plan(batch: BatchWindow) -> dict[str, object]:
    return {
        "batch_meta": {"start_episode": batch.start_episode, "end_episode": batch.end_episode},
        "global_conflict_engine": {"driver": "资源争夺"},
        "episodes": [
            {
                "episode": episode,
                "episode_title": f"第{episode}集",
                "active_characters": ["林夏"],
                "scene_refs": ["S1"],
                "carry_in": "上一集压力延续",
                "why_now": "审批窗口临近",
                "character_motivation": "守住团队",
                "emotional_precondition": "焦虑但克制",
                "scene_cause_chain": ["资料丢失", "团队追查"],
                "non_conflict_moment": "短暂互相信任",
                "natural_transition": "线索指向发布会",
                "opening_image": "雨夜旧港",
                "opening_action": "林夏检查设备",
                "current_goal": "找回资料",
                "core_obstacle": "对手封锁信息",
                "episode_state_change": "团队从被动转主动",
                "ending_hook": "发现内鬼线索",
                "dialogue_strategy": "短句压迫",
            }
            for episode in range(batch.start_episode, batch.end_episode + 1)
        ],
    }


def test_scene_dictionary_answer_text_wrapper_is_normalized() -> None:
    variables = {
        "answerText": json.dumps(
            {
                SCENE_DICTIONARY: _valid_scene_dictionary(),
                SCRIPT_WORLD_RULES_DIGEST: _valid_rules_digest(),
            },
            ensure_ascii=False,
        )
    }

    flow._normalize_framework_to_script_asset_variables(variables)

    assert variables[SCENE_DICTIONARY]["scene_count"] == 2
    assert variables[SCRIPT_WORLD_RULES_DIGEST]["world_type"] == "近未来商战"
    assert flow._validate_framework_scene_dictionary_assets(variables) == []


def test_appearanceMapping_answer_text_wrapper_is_normalized() -> None:
    variables = {
        "answerText": json.dumps(
            {APPEARANCE_MAPPING: _valid_appearanceMapping()},
            ensure_ascii=False,
        )
    }

    flow._normalize_framework_to_script_asset_variables(variables)

    assert variables[APPEARANCE_MAPPING]["characters"][0]["name"] == "林夏"
    assert flow._validate_framework_appearanceMapping_assets(variables) == []


def test_appearanceMapping_without_mapping_version_is_allowed() -> None:
    variables = {
        APPEARANCE_MAPPING: {
            "mapping_principle": "优先使用角色默认名和服装锚点。",
            "global_naming_style": "短名、稳定、避免泛称。",
            "characters": [
                {
                    "character_id": "char_001",
                    "canonical_name": "林夏",
                    "story_role": "主角",
                    "same_person_anchor": {"default": "林夏"},
                    "default_name": "林夏",
                    "forbidden_generic_names": ["女人"],
                    "outfit_variants": [{"alias_name": "林夏工作装"}],
                }
            ],
        }
    }

    assert flow._validate_framework_appearanceMapping_assets(variables) == []


def test_appearanceMapping_snake_case_is_normalized() -> None:
    variables = {
        "appearance_mapping": {
            "mapping_principle": "snake case 来源。",
            "characters": [{"character_id": "char_001", "canonical_name": "林夏"}],
        }
    }

    flow._normalize_framework_to_script_asset_variables(variables)

    assert variables[APPEARANCE_MAPPING]["mapping_principle"] == "snake case 来源。"
    assert variables["appearanceMapping"] == variables[APPEARANCE_MAPPING]
    assert variables["appearance_mapping"] == variables[APPEARANCE_MAPPING]


def test_answer_text_concatenated_json_extracts_target_objects() -> None:
    appearance = {
        "appearanceMapping": {
            "mapping_principle": "第二个对象才是外观映射。",
            "characters": [{"character_id": "char_001", "canonical_name": "林夏"}],
        }
    }
    variables = {
        "answerText": json.dumps({"note": "ignore"}, ensure_ascii=False)
        + json.dumps(appearance, ensure_ascii=False)
    }

    flow._normalize_framework_to_script_asset_variables(variables)

    assert variables[APPEARANCE_MAPPING]["mapping_principle"] == "第二个对象才是外观映射。"


def test_enriched_episode_plan_result_wrapper_is_normalized() -> None:
    variables = {
        "enrichedEpisodePlanResult": json.dumps(
            {
                ALL_ENRICHED_EPISODE_PLAN: _valid_enriched_plan(2),
                "allEnrichedEpisodePlanText": "第1-2集丰富分集计划",
            },
            ensure_ascii=False,
        )
    }

    flow._normalize_framework_to_script_asset_variables(variables)

    assert len(variables[ALL_ENRICHED_EPISODE_PLAN]) == 2
    assert flow._validate_framework_enriched_episode_plan_assets(variables, total_episodes=2) == []


def test_enriched_episode_plan_sources_are_normalized() -> None:
    for source_key in ("enrichedEpisodePlanResult", ALL_ENRICHED_EPISODE_PLAN, "answerText"):
        variables = {
            source_key: json.dumps(
                {ALL_ENRICHED_EPISODE_PLAN: _valid_enriched_plan(2)},
                ensure_ascii=False,
            )
            if source_key != ALL_ENRICHED_EPISODE_PLAN
            else _valid_enriched_plan(2)
        }

        flow._normalize_framework_to_script_asset_variables(variables)

        assert [item["episode"] for item in variables[ALL_ENRICHED_EPISODE_PLAN]] == [1, 2]


def test_answer_text_concatenated_json_extracts_enriched_plan() -> None:
    variables = {
        "answerText": json.dumps({"appearanceMapping": {"characters": [{"canonical_name": "林夏"}]}}, ensure_ascii=False)
        + json.dumps({ALL_ENRICHED_EPISODE_PLAN: _valid_enriched_plan(2)}, ensure_ascii=False)
    }

    flow._normalize_framework_to_script_asset_variables(variables)

    assert [item["episode"] for item in variables[ALL_ENRICHED_EPISODE_PLAN]] == [1, 2]


def test_enriched_episode_plan_can_be_sliced_by_batches() -> None:
    variables = {
        ALL_ENRICHED_EPISODE_PLAN: _valid_enriched_plan(10),
        "allEnrichedEpisodePlanText": "第1-10集丰富分集计划",
    }

    first_batch = flow._framework_enriched_plan_for_batch(variables, BatchWindow(1, 5))
    second_batch = flow._framework_enriched_plan_for_batch(variables, BatchWindow(6, 10))

    assert [item["episode"] for item in json.loads(first_batch)] == [1, 2, 3, 4, 5]
    assert [item["episode"] for item in json.loads(second_batch)] == [6, 7, 8, 9, 10]


def test_missing_enriched_episode_plan_returns_clear_error() -> None:
    issues = flow._validate_framework_enriched_episode_plan_assets(
        {"allEnrichedEpisodePlanText": "只有文本"},
        total_episodes=10,
    )

    assert issues == [flow.FRAMEWORK_ENRICHED_PLAN_ERROR]


def test_empty_batch_enriched_plan_returns_clear_error() -> None:
    variables = {
        ALL_ENRICHED_EPISODE_PLAN: _valid_enriched_plan(5),
        "allEnrichedEpisodePlanText": "第1-5集丰富分集计划",
    }
    missing_batch = flow._framework_enriched_plan_for_batch(variables, BatchWindow(6, 10))

    assert missing_batch == ""
    assert flow._validate_framework_batch_enriched_plan(missing_batch, batch=BatchWindow(6, 10)) == [
        flow.FRAMEWORK_BATCH_ENRICHED_PLAN_ERROR
    ]


def test_memory_answer_text_fallback_does_not_block() -> None:
    conflict_memory = flow._extract_framework_memory_text(
        {"answerText": json.dumps({CONFLICT_MEMORY: "上一批因果记忆"}, ensure_ascii=False)},
        field_name=CONFLICT_MEMORY,
    )
    script_memory = flow._extract_framework_memory_text(
        {"answerText": json.dumps({SCRIPT_MEMORY: "上一批正文记忆"}, ensure_ascii=False)},
        field_name=SCRIPT_MEMORY,
    )
    missing_memory = flow._extract_framework_memory_text({}, field_name=SCRIPT_MEMORY)

    assert conflict_memory == "上一批因果记忆"
    assert script_memory == "上一批正文记忆"
    assert missing_memory == ""


def test_causal_conflict_missing_key_fields_returns_rewrite_issues() -> None:
    batch = BatchWindow(1, 5)
    invalid_plan = {
        BATCH_CAUSAL_CONFLICT_PLAN: {
            "batch_meta": {},
            "global_conflict_engine": {},
            "episodes": [{"episode": 1}],
        }
    }

    issues = flow._validate_framework_causal_conflict_plan(invalid_plan, batch=batch)

    assert any("缺少字段" in issue for issue in issues)
    assert any("缺少集数" in issue for issue in issues)


def test_valid_causal_conflict_plan_and_empty_script_text_validation() -> None:
    batch = BatchWindow(1, 2)

    assert flow._validate_framework_causal_conflict_plan(_valid_causal_plan(batch), batch=batch) == []
    assert flow._validate_framework_script_batch_text("", batch=batch) == [
        "batchScriptText 第 1-2 集必须是非空字符串"
    ]


def test_framework_to_script_final_sync_exposes_export_artifacts(tmp_path) -> None:
    manager = TaskManager()
    manager.set_storage_root(
        tmp_path / "runtime_data",
        runtime_archive_dir=tmp_path / "runtime_archive",
    )
    record = TaskRecord(
        user_id=1,
        project_id=1,
        task_id="task-framework-final",
        workflow_spec_path="spec.json",
        input_payload={"title": "测试项目", "framework_to_script": True},
        model_option=None,
        snapshot={
            "status": "running",
            "title": "测试项目",
            "artifacts": {},
            "debug_state": {},
            "prompt_fixes": [],
            "input_payload": {"framework_to_script": True},
        },
    )
    runtime = WorkflowRuntime(manager=manager, record=record, spec=None)
    state = WorkflowState(
        WorkflowInput(
            title="测试项目",
            episode_word_count=1200,
            total_episodes=2,
            user_expectation="需求",
            character_count=2,
            character_appearance_requirements="",
            character_alias_naming_rules="",
            outfit_switch_rules="",
            story_outline="",
            core_scene_input="",
            character_bios="",
            episode_plan="",
        )
    )
    final_text = "第1集\n林夏：开始。\n\n第2集\n林夏：完成。"
    state.set_var(ALL_SCRIPT, final_text)
    state.set_var(FINAL_SCRIPT, final_text)
    state.final_output_text = final_text

    runtime.sync_from_state(state)
    artifacts = record.clone_snapshot()["artifacts"]

    assert artifacts["final_script"]
    assert artifacts["final_output_text"] == artifacts["final_script"]
    assert "林夏：开始。" in artifacts["final_script"]
