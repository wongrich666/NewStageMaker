from __future__ import annotations

import json

from app.services.script_audit_ecg_parser import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_V3,
    build_script_audit_view_model,
    normalize_script_audit_ecg,
    parse_model_json_loose,
)


def sample_payload():
    return {
        "schema_version": SCHEMA_VERSION,
        "overall": {"level": "中低适配"},
        "dimension_scores": [
            {
                "dimension_key": "opening_hook",
                "dimension_name": "开篇钩子与人设锚定",
                "max_score": 25,
                "sub_items": [
                    {
                        "sub_key": "opening_speed",
                        "sub_name": "进入事件速度",
                        "raw_score": 4,
                        "weight": 5,
                    }
                ],
            }
        ],
        "segments": [
            {"segment_id": "seg_1", "segment_index": 1, "start_offset": 0, "end_offset": 10},
            {"segment_id": "seg_2", "segment_index": 2, "start_offset": 10, "end_offset": 20},
            {"segment_id": "seg_3", "segment_index": 3, "start_offset": 20, "end_offset": 30},
        ],
        "ecg": {
            "main_series": {
                "points": [
                    {"segment_id": "seg_1", "ecg_value": 6, "audit_reason": "强开篇"},
                    {"segment_id": "seg_2", "ecg_value": -3, "audit_reason": "空转"},
                    {"segment_id": "seg_3", "ecg_value": -4, "audit_reason": "继续空转"},
                ]
            }
        },
    }


def test_parse_pure_json():
    parsed, warnings = parse_model_json_loose(json.dumps(sample_payload(), ensure_ascii=False))
    assert parsed["schema_version"] == SCHEMA_VERSION


def test_parse_fenced_json():
    raw = "```json\n" + json.dumps(sample_payload(), ensure_ascii=False) + "\n```"
    parsed, warnings = parse_model_json_loose(raw)
    assert parsed["schema_version"] == SCHEMA_VERSION


def test_parse_json_with_surrounding_text():
    raw = "下面是结果：" + json.dumps(sample_payload(), ensure_ascii=False) + "结束"
    parsed, warnings = parse_model_json_loose(raw)
    assert parsed["schema_version"] == SCHEMA_VERSION


def test_parse_nested_string_json():
    raw = json.dumps(json.dumps(sample_payload(), ensure_ascii=False), ensure_ascii=False)
    parsed, warnings = parse_model_json_loose(raw)
    assert parsed["schema_version"] == SCHEMA_VERSION


def test_parse_fastgpt_answer_text():
    raw = {"answerText": "```json\n" + json.dumps(sample_payload(), ensure_ascii=False) + "\n```"}
    parsed, warnings = parse_model_json_loose(raw)
    assert parsed["schema_version"] == SCHEMA_VERSION


def test_normalize_clamps_and_fills_hover_and_total_score():
    audit, warnings = normalize_script_audit_ecg(sample_payload())
    points = audit["ecg"]["main_series"]["points"]
    assert points[0]["ecg_value"] == 5
    assert points[0]["value_type"] == "positive"
    assert points[0]["hover_card"]["score_text"] == "+5"
    assert audit["overall"]["total_score"] == 4
    assert audit["dimension_scores"][0]["sub_items"][0]["weighted_score"] == 4


def test_negative_zones_are_generated():
    audit, warnings = normalize_script_audit_ecg(sample_payload())
    assert audit["ecg"]["negative_zones"]
    assert audit["ecg"]["negative_zones"][0]["risk_type"] == "连续低留存区间"


def test_build_view_model():
    audit, warnings = normalize_script_audit_ecg(sample_payload())
    view = build_script_audit_view_model(audit)
    assert view["ecg_chart"]["points"]
    assert view["summary_cards"][0]["key"] == "total_score"


def test_non_schema_dict_can_fall_back_without_crashing():
    parsed, warnings = parse_model_json_loose({"text": "普通文本"})
    assert isinstance(parsed, dict)


def sample_v3_payload():
    return {
        "schema_version": SCHEMA_VERSION_V3,
        "meta": {"script_title": "测试短剧", "total_episode_count": 2},
        "overall": {"total_score": 72, "level": "可改", "core_judgement": "有钩子但中段松。"},
        "dimension_scores": [
            {"dimension_key": "hook", "dimension_name": "钩子", "max_score": 20, "score": 14}
        ],
        "segments": [
            {"segment_id": "s1", "episode_no": 1, "segment_index_global": 1, "start_offset": 0, "end_offset": 10},
            {"segment_id": "s2", "episode_no": 2, "segment_index_global": 2, "start_offset": 10, "end_offset": 20},
        ],
        "global_review": {
            "global_structure_judgement": {
                "main_genre": "都市反转",
                "global_retention_problem": "第二集压力不足",
            },
            "ecg": {
                "title": "全剧总心电图",
                "main_series": {
                    "points": [
                        {"point_id": "p1", "segment_id": "s1", "episode_no": 1, "segment_index_global": 1, "ecg_value": 4, "audit_reason": "开场强"},
                        {"point_id": "p2", "segment_id": "s2", "episode_no": 2, "segment_index_global": 2, "ecg_value": -2, "audit_reason": "解释偏多"},
                    ]
                },
            },
            "episode_score_map": [
                {"episode_no": 1, "episode_score": 78, "main_problem": "钩子可更强"},
                {"episode_no": 2, "episode_score": 63, "main_problem": "压力不足"},
            ],
            "global_key_issues": [{"title": "中段松", "fix_strategy": "压缩解释"}],
        },
        "episode_reviews": [
            {
                "episode_no": 1,
                "episode_title": "第一集",
                "episode_overall": {"episode_score": 78, "core_judgement": "开场有效", "priority_fix": "加代价"},
                "key_issues": [{"title": "代价不足"}],
            }
        ],
        "cross_episode_analysis": {"retention_curve_summary": "第二集掉点"},
    }


def test_parse_and_normalize_v3_episode_global():
    audit, warnings = normalize_script_audit_ecg(sample_v3_payload())
    view = build_script_audit_view_model(audit)
    assert audit["schema_version"] == SCHEMA_VERSION_V3
    assert audit["global_review"]["ecg"]["main_series"]["points"][0]["episode_no"] == 1
    assert view["ecg_chart"]["episode_markers"][1]["episode_no"] == 2
    assert view["episode_cards"][0]["episode_overall"]["episode_score"] == 78
    assert "第二集掉点" in view["export_text"]


def test_parse_v3_from_nested_answer_text():
    raw = {"answerText": "```json\n" + json.dumps(sample_v3_payload(), ensure_ascii=False) + "\n```"}
    parsed, warnings = parse_model_json_loose(raw)
    assert parsed["schema_version"] == SCHEMA_VERSION_V3
