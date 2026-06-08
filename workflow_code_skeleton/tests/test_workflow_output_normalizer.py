from __future__ import annotations

import pytest

from workflow_code_skeleton.app.services.workflow_output_normalizer import normalize_stage_output


def test_standard_dict_keeps_source_brief_and_display_text() -> None:
    result = normalize_stage_output(
        "stage_01",
        {"source_brief": {"title": "Project A"}, "display_text": "Readable A"},
    )

    assert result["source_brief"]["title"] == "Project A"
    assert result["display_text"] == "Readable A"


def test_data_output_and_new_variables_wrappers_are_unpacked() -> None:
    assert normalize_stage_output("stage_01", {"data": {"source_brief": {"title": "Data"}}})["source_brief"]["title"] == "Data"
    assert normalize_stage_output("stage_02", {"output": {"worldview_plan": {"world_type": "Urban"}}})["worldview_plan"]["world_type"] == "Urban"
    assert normalize_stage_output("stage_03", {"newVariables": {"character_plan": {"protagonist": {"name": "Lin"}}}})[
        "character_plan"
    ]["protagonist"]["name"] == "Lin"


def test_content_json_string_is_unpacked() -> None:
    result = normalize_stage_output(
        "stage_01",
        {"content": '{"source_brief": {"title": "Json String"}, "display_text": "Readable"}'},
    )

    assert result["source_brief"]["title"] == "Json String"
    assert result["display_text"] == "Readable"


def test_content_markdown_fenced_json_is_unpacked() -> None:
    result = normalize_stage_output(
        "stage_01",
        {"content": '```JSON\n{"source_brief": {"title": "Fenced"}, "display_text": "Readable"}\n```'},
    )

    assert result["source_brief"]["title"] == "Fenced"
    assert result["display_text"] == "Readable"


def test_business_field_content_wrapped_json_is_unpacked_without_content_pollution() -> None:
    result = normalize_stage_output(
        "stage_01",
        {
            "source_brief": {
                "content": '```json\n{"source_brief": {"title": "Nested", "core_premise": "Premise"}}\n```'
            }
        },
    )

    assert result["source_brief"]["title"] == "Nested"
    assert result["source_brief"]["core_premise"] == "Premise"
    assert "content" not in result["source_brief"]
    assert not str(result["source_brief"].get("core_premise", "")).startswith("```")


def test_json_with_surrounding_explanatory_text_is_extracted() -> None:
    result = normalize_stage_output(
        "stage_02",
        "以下是结果：\n"
        '{"worldview_plan": {"summary": "World summary"}, "display_text": "World display"}'
        "\n请查收。",
    )

    assert result["worldview_plan"]["summary"] == "World summary"
    assert result["display_text"] == "World display"


def test_light_repair_handles_smart_quotes_and_trailing_commas() -> None:
    result = normalize_stage_output(
        "stage_01",
        "{\n"
        '  "source_brief": {\n'
        "    “title”: “Smart Quote Title”,\n"
        '    "core_logline": "主角需要“利用”已知信息逆转困局",\n'
        "  },\n"
        "  “display_text”: “Smart display”,\n"
        "}\n",
    )

    assert result["source_brief"]["title"] == "Smart Quote Title"
    assert result["source_brief"]["core_logline"] == "主角需要“利用”已知信息逆转困局"
    assert result["display_text"] == "Smart display"


def test_plain_text_falls_back_to_display_text_and_minimal_structure() -> None:
    result = normalize_stage_output("stage_06", "这是纯自然语言改编说明。")

    assert result["display_text"] == "这是纯自然语言改编说明。"
    assert result["adaptation_guide"]["summary"] == "这是纯自然语言改编说明。"
    assert "model_returned_plain_text" in result["parse_warnings"]


def test_direct_list_root_maps_to_primary_list_field() -> None:
    result = normalize_stage_output("stage_05", [{"id": "main", "title": "Main Storyline"}])

    assert result["character_storylines"][0]["id"] == "main"
    assert result["display_text"]


def test_stage_06_accepts_overall_adaptation_guide_alias() -> None:
    result = normalize_stage_output("stage_06", {"overallAdaptationGuide": {"summary": "Guide alias"}})

    assert result["adaptation_guide"]["summary"] == "Guide alias"
    assert result["display_text"] == "Guide alias"


def test_display_text_is_generated_from_structure_when_missing() -> None:
    result = normalize_stage_output("stage_02", {"worldview_plan": {"summary": "Generated from structure"}})

    assert result["display_text"] == "Generated from structure"


@pytest.mark.parametrize(
    ("stage_key", "raw", "expected_key"),
    [
        ("stage_01", {"source_brief": {"title": "S1"}}, "source_brief"),
        ("stage_02", {"worldview_plan": {"summary": "S2"}}, "worldview_plan"),
        ("stage_03", {"character_plan": {"characters": []}}, "character_plan"),
        ("stage_04", {"beat_checkpoint": {"timeline": [{"beat_no": 1}], "explanation": {"overview": "ok"}}}, "beat_checkpoint_timeline"),
        ("stage_05", {"character_storylines": [{"id": "main"}]}, "character_storylines"),
        ("stage_06", {"adaptation_guide": {"summary": "S6"}}, "adaptation_guide"),
        ("stage_07", {"framework_plan_package": {"summary": "S7"}, "validation_report": {"passed": True}}, "framework_plan_package"),
        ("stage_08", {"scene_dictionary": {"locations": []}}, "sceneDictionary"),
        ("stage_09", {"alias": {"characters": []}}, "appearanceMapping"),
        ("stage_10", {"episode_plan": [{"episode": 1}]}, "allEnrichedEpisodePlan"),
        ("stage_11", {"conflicts": {"batchStartEpisode": 1}}, "batchCausalConflictPlan"),
        ("stage_12", {"script_text": "EP1 script"}, "batchScriptText"),
    ],
)
def test_stage_01_to_12_normalize_to_expected_fields(stage_key: str, raw: dict[str, object], expected_key: str) -> None:
    result = normalize_stage_output(stage_key, raw)

    assert expected_key in result
    assert result[expected_key] not in (None, "", [], {})


def test_raw_result_is_kept_in_debug_not_business_content() -> None:
    raw = {"content": '```json\n{"source_brief": {"title": "Debug Raw"}}\n```'}
    result = normalize_stage_output("stage_01", raw)

    assert result["_normalizer_debug"]["raw_result"] == raw
    assert result["_normalizer_debug"]["raw_content"] == raw["content"]
    assert "content" not in result["source_brief"]
