from __future__ import annotations

import json

from workflow_code_skeleton.app.services.workflow_output_parser import (
    parse_workflow_output,
    safe_truncated_preview,
    wrap_payload_for_expected_output,
)


def test_parse_direct_json_object():
    raw = '{"worldview_plan": {"a": 1}}'
    assert parse_workflow_output(raw)["worldview_plan"]["a"] == 1


def test_parse_direct_json_array():
    raw = '[{"episode": 1, "title": "xxx"}]'
    assert parse_workflow_output(raw)[0]["episode"] == 1


def test_parse_markdown_json_fence():
    raw = '```json\n{"worldview_plan": {"a": 1}}\n```'
    assert parse_workflow_output(raw)["worldview_plan"]["a"] == 1


def test_parse_triple_quote_json_fence():
    raw = "'''json\n{\"worldview_plan\": {\"a\": 1}}\n'''"
    assert parse_workflow_output(raw)["worldview_plan"]["a"] == 1


def test_parse_blank_markdown_fence():
    raw = '```\n{"worldview_plan": {"a": 1}}\n```'
    assert parse_workflow_output(raw)["worldview_plan"]["a"] == 1


def test_parse_multiple_fences_uses_first_json_payload():
    raw = "```text\nnot json\n```\n```JSON\n{\"worldview_plan\": {\"a\": 1}}\n```"
    assert parse_workflow_output(raw)["worldview_plan"]["a"] == 1


def test_parse_json_inside_prose():
    raw = '下面是结果：\n{"worldview_plan": {"a": 1}}\n请确认。'
    assert parse_workflow_output(raw)["worldview_plan"]["a"] == 1


def test_parse_double_encoded_json():
    raw = '"{\\"worldview_plan\\": {\\"a\\": 1}}"'
    assert parse_workflow_output(raw)["worldview_plan"]["a"] == 1


def test_parse_nested_output_json_string():
    raw = {"data": {"output": "{\"worldview_plan\": {\"a\": 1}}"}}
    assert parse_workflow_output(raw)["worldview_plan"]["a"] == 1


def test_parse_variables_first():
    raw = {
        "data": {
            "variables": {
                "worldview_plan": {"a": 1},
            },
            "output": "这段不是主结果",
        }
    }
    assert parse_workflow_output(raw)["worldview_plan"]["a"] == 1


def test_parse_output_field_json_string():
    raw = {
        "output": "{\"batchScriptText\": [{\"episode\": 1}]}",
    }
    assert parse_workflow_output(raw)["batchScriptText"][0]["episode"] == 1


def test_wrap_unique_dict_output_when_business_object():
    parsed = {"background": "x", "rules": [1]}
    wrapped = wrap_payload_for_expected_output(
        parsed,
        output_names=("worldview_plan",),
        output_aliases={"worldview_plan": ("worldview",)},
        output_types={"worldview_plan": "object"},
        stage_name="02",
    )
    assert wrapped == {"worldview_plan": parsed}


def test_wrap_unique_list_for_conflict_plan():
    parsed = [{"episode": 1, "conflict": "A"}]
    wrapped = wrap_payload_for_expected_output(
        parsed,
        output_names=("batchCausalConflictPlan",),
        output_aliases={"batchCausalConflictPlan": ("conflicts",)},
        output_types={"batchCausalConflictPlan": "object"},
        stage_name="framework_causal_conflict_write",
    )
    assert wrapped["batchCausalConflictPlan"]["episodes"][0]["episode"] == 1


def test_wrap_unique_list_for_script_text_as_json_string():
    parsed = [{"episode": 1, "script": "正文"}]
    wrapped = wrap_payload_for_expected_output(
        parsed,
        output_names=("batchScriptText",),
        output_aliases={"batchScriptText": ("script",)},
        output_types={"batchScriptText": "string"},
        stage_name="framework_script_write",
    )
    assert json.loads(wrapped["batchScriptText"])[0]["episode"] == 1


def test_safe_preview_redacts_secrets_and_truncates():
    raw = {"Authorization": "Bearer abcdefghijklmnopqrstuvwxyz", "text": "x" * 5000}
    preview = safe_truncated_preview(raw, limit=200)
    assert "abcdefghijklmnopqrstuvwxyz" not in preview
    assert "<redacted>" in preview
    assert "<truncated" in preview
