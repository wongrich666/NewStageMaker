from __future__ import annotations

import json

from app.services.script_audit_ecg_parser import (
    COMPACT_SCHEMA_VERSION,
    SCHEMA_VERSION,
    SCHEMA_VERSION_V3,
    build_audit_visualization_payload,
    build_script_audit_view_model,
    fallback_audit_from_text,
    normalize_compact_audit_payload,
    normalize_script_audit_ecg,
    parse_compact_audit_json,
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


def test_fallback_audit_from_unparseable_text_still_builds_view():
    audit, warnings = normalize_script_audit_ecg(
        fallback_audit_from_text("《坏格式剧本》\n{ this is not valid json", warnings=["bad json"]),
        raw_answer_text="{ this is not valid json",
    )
    view = build_script_audit_view_model(audit)
    assert audit["schema_version"] == SCHEMA_VERSION_V3
    assert audit["meta"]["script_title"] == "坏格式剧本"
    assert audit["parse_fallback"]["enabled"] is True
    assert view["summary_cards"]
    assert view["global_review"]["key_issues"][0]["title"] == "模型输出未能完整解析"


def compact_payload():
    return {
        "schema_version": COMPACT_SCHEMA_VERSION,
        "meta": {"script_title": "紧凑测试", "text_type": "短剧"},
        "overall": {"level": "B", "core_judgement": "开场有效，中段需要加压。"},
        "dimension_scores": [
            {"dimension_key": "opening_hook", "score": 12, "summary": "开场清楚"},
            {"dimension_key": "conflict_pacing", "score": 18, "summary": "中段略松"},
            {"dimension_key": "satisfying_payoff", "score": 17},
            {"dimension_key": "character_dialogue_filming", "score": 15},
            {"dimension_key": "market_compliance", "score": 12},
        ],
        "segments": [
            {"segment_id": "s1", "episode_no": 1, "segment_index_global": 1, "original_text_excerpt": "医生冲进病房。"},
            {"segment_id": "s2", "episode_no": 1, "segment_index_global": 2, "original_text_excerpt": "主角犹豫解释。"},
        ],
        "global_review": {
            "main_genre": "都市逆袭",
            "global_retention_problem": "解释段偏长",
            "global_ecg_points": [
                {"point_id": "p1", "segment_id": "s1", "episode_no": 1, "ecg_value": 4, "short_label": "强开场", "audit_reason": "目标明确"},
                {"point_id": "p2", "segment_id": "s2", "episode_no": 1, "ecg_value": -2, "short_label": "解释拖慢", "fix_suggestion": "压缩对白"},
            ],
            "global_key_issues": [{"title": "解释偏多", "risk_level": "建议修改"}],
            "global_rewrite_plan": [{"task_id": "r1", "specific_action": "前置冲突"}],
        },
        "episode_reviews": [
            {
                "episode_no": 1,
                "episode_title": "第一集",
                "level": "B",
                "core_judgement": "钩子成立",
                "largest_retention_loss": "解释拖慢",
                "priority_fix": "加选择代价",
                "dimension_scores": [
                    {"dimension_key": "opening_hook", "score": 12},
                    {"dimension_key": "conflict_pacing", "score": 18},
                    {"dimension_key": "satisfying_payoff", "score": 17},
                    {"dimension_key": "character_dialogue_filming", "score": 15},
                    {"dimension_key": "market_compliance", "score": 12},
                ],
                "ecg_points": [{"segment_id": "s1", "episode_no": 1, "ecg_value": 4, "label": "集内高点"}],
            }
        ],
        "cross_episode_analysis": {"retention_curve_summary": "第一集开场较强。"},
    }


def compact_result_from(raw):
    data = parse_compact_audit_json(raw)
    audit, warnings = normalize_compact_audit_payload(data)
    visualization = build_audit_visualization_payload(audit)
    return {"audit": audit, "visualization": visualization, "warnings": warnings}


def test_compact_parse_valid_raw_json():
    result = compact_result_from(json.dumps(compact_payload(), ensure_ascii=False))
    assert result["audit"]["schema_version"] == COMPACT_SCHEMA_VERSION
    assert result["audit"]["overall"]["total_score"] == 74
    assert result["visualization"]["ecg_chart"]["global"]["points"][0]["hover_title"] == "强开场"
    assert result["visualization"]["episode_score_map"][0]["episode_score"] == 74


def test_compact_parse_fenced_bom_and_surrounding_text():
    raw = "\ufeff下面是审核结果：```json\n" + json.dumps(compact_payload(), ensure_ascii=False) + "\n```谢谢"
    result = compact_result_from(raw)
    assert result["audit"]["meta"]["script_title"] == "紧凑测试"
    assert result["visualization"]["ecg_chart"]["global"]["peak_points"][0]["point_id"] == "p1"
    assert result["visualization"]["ecg_chart"]["global"]["valley_points"][0]["point_id"] == "p2"


def test_compact_alias_payload_normalizes_to_canonical():
    alias_payload = {
        "schema_version": COMPACT_SCHEMA_VERSION,
        "meta": {"script_title": "短字段测试"},
        "overall": {"level": "C"},
        "global_dimensions": [
            {"key": "opening_hook", "score": 10, "main_deduction": "开头不够锐"},
            {"key": "conflict_pacing", "score": 16},
            {"key": "satisfying_payoff", "score": 15},
            {"key": "character_dialogue_filming", "score": 14},
            {"key": "market_compliance", "score": 12},
        ],
        "global_review": {
            "global_ecg_points": [
                {"segment_id": "sx", "episode_no": 1, "value": 3, "label": "小高潮", "reason": "反击清楚", "fix": "补后果"}
            ]
        },
        "episodes": [
            {
                "episode_no": 1,
                "dimensions": [
                    {"key": "opening_hook", "score": 10, "deduction": "开头慢"},
                    {"key": "conflict_pacing", "score": 16},
                    {"key": "satisfying_payoff", "score": 15},
                    {"key": "character_dialogue_filming", "score": 14},
                    {"key": "market_compliance", "score": 12},
                ],
                "rewrite_tasks": [{"specific_action": "减少解释"}],
                "ecg_points": [{"value": 3, "label": "集内点", "reason": "有效"}],
            }
        ],
    }
    wrapped = {"answerText": json.dumps(alias_payload, ensure_ascii=False)}
    result = compact_result_from(json.dumps(wrapped, ensure_ascii=False))
    assert result["audit"]["dimension_scores"][0]["dimension_key"] == "opening_hook"
    assert result["audit"]["dimension_scores"][0]["deduction_reason"] == "开头不够锐"
    assert result["audit"]["episode_reviews"][0]["rewrite_plan"][0]["specific_action"] == "减少解释"
    assert result["visualization"]["ecg_chart"]["global"]["points"][0]["ecg_value"] == 3
    assert result["warnings"]


def test_compact_global_chart_includes_episode_points_for_each_episode():
    payload = compact_payload()
    payload["episode_reviews"].append({
        "episode_no": 2,
        "episode_title": "第二集",
        "level": "C",
        "core_judgement": "本集压力不足",
        "largest_retention_loss": "缺少新阻力",
        "priority_fix": "补一个新选择",
        "dimension_scores": [
            {"dimension_key": "opening_hook", "score": 8},
            {"dimension_key": "conflict_pacing", "score": 12},
            {"dimension_key": "satisfying_payoff", "score": 13},
            {"dimension_key": "character_dialogue_filming", "score": 12},
            {"dimension_key": "market_compliance", "score": 12},
        ],
        "ecg_points": [
            {"episode_no": 2, "value": -2, "label": "第二集低点", "reason": "解释偏多"}
        ],
    })
    result = compact_result_from(json.dumps(payload, ensure_ascii=False))
    episodes = {
        point["episode_no"]
        for point in result["visualization"]["ecg_chart"]["global"]["points"]
    }
    assert episodes == {1, 2}
    assert len(result["visualization"]["episode_score_map"]) == 2
    assert len(result["audit"]["episode_reviews"]) == 2


def test_compact_episode_mapping_and_fallback_point_for_missing_ecg():
    payload = compact_payload()
    payload["global_review"]["global_ecg_points"] = []
    payload["episode_reviews"] = {
        "1": payload["episode_reviews"][0],
        "2": {
            "episode_no": 2,
            "episode_title": "第二集",
            "core_judgement": "没有返回心电点",
            "largest_retention_loss": "节奏平",
            "priority_fix": "增加段尾钩子",
            "dimension_scores": [
                {"dimension_key": "opening_hook", "score": 7},
                {"dimension_key": "conflict_pacing", "score": 10},
                {"dimension_key": "satisfying_payoff", "score": 11},
                {"dimension_key": "character_dialogue_filming", "score": 10},
                {"dimension_key": "market_compliance", "score": 12},
            ],
        },
    }
    result = compact_result_from(json.dumps(payload, ensure_ascii=False))
    assert [item["episode_no"] for item in result["audit"]["episode_reviews"]] == [1, 2]
    global_points = result["visualization"]["ecg_chart"]["global"]["points"]
    assert {point["episode_no"] for point in global_points} == {1, 2}
    assert any(point.get("derived_from_episode_score") for point in global_points)


def enhanced_compact_payload():
    payload = compact_payload()
    payload["segments"].append({
        "segment_id": "s3",
        "episode_no": 2,
        "scene_no": 1,
        "segment_index_global": 3,
        "original_text_excerpt": "第二集出现新证据。",
    })
    payload["global_review"].update({
        "global_score_explanation": "五大维度合计后，全剧商业可看性中上。",
        "global_strength_summary": "开场和主线目标明确。",
        "global_weakness_summary": "第二集钩子连续性偏弱。",
        "global_satisfying_points": [{
            "point_id": "sp1",
            "episode_no": 1,
            "segment_ids": ["s1"],
            "content": "主角强反击",
            "pressure_exists": True,
            "counterattack_exists": True,
            "payoff_exists": True,
            "consequence_exists": True,
            "closed_loop": True,
            "strength": "强",
            "global_value": "建立爽感承诺",
            "problem": "",
            "enhancement_suggestion": "保留",
        }],
        "global_key_issues": [{
            "issue_id": "gi1",
            "priority": 1,
            "issue_type": "钩子",
            "risk_level": "建议修改",
            "title": "第二集拉力弱",
            "description": "新危险不够具体",
            "evidence": "第二集结尾信息不足",
            "affected_episode_numbers": [2],
            "affected_segment_ids": ["s3"],
            "commercial_impact": "降低追更",
            "fix_strategy": "加新证据",
            "expected_improvement": "提升集尾拉力",
        }],
        "global_risk_scan": [{
            "risk_id": "gr1",
            "risk_type": "节奏",
            "risk_level": "建议修改",
            "evidence": "解释段偏多",
            "affected_episode_numbers": [2],
            "affected_segment_ids": ["s3"],
            "impact": "掉点",
            "avoidance_suggestion": "压缩解释",
        }],
        "global_rewrite_plan": [{
            "task_id": "gt1",
            "priority": 1,
            "target": "集尾钩子",
            "problem": "第二集缺拉力",
            "specific_action": "补一个强选择",
            "affected_episode_numbers": [2],
            "affected_segment_ids": ["s3"],
            "expected_result": "提高追更",
        }],
    })
    payload["episode_reviews"] = [
        {
            "episode_no": 1,
            "episode_title": "第一集",
            "episode_scope": {
                "segment_ids": ["s1", "s2"],
                "scene_count": 2,
                "segment_count": 2,
                "is_complete_episode": True,
                "is_partial_episode": False,
                "integrity_evidence": "第一集完整",
            },
            "episode_score_explanation": "开场强但解释略多。",
            "best_retained_part": "主角反击",
            "episode_structure": {
                "episode_goal": "证明自己",
                "main_obstacle": "医生阻拦",
                "forced_choice": "公开证据",
                "conflict_result": "暂时获胜",
                "situation_change": "关系反转",
                "protagonist_agency": "强",
                "retention_engine": "新证据",
                "structure_problem": "解释偏多",
                "evidence_segment_ids": ["s1"],
            },
            "dimension_scores": [
                {"dimension_key": "opening_hook", "score": 12, "evidence_segment_ids": ["s1"]},
            ],
            "ending_hook": {"exists": True, "content": "新证据出现", "evidence_segment_ids": ["s2"]},
            "key_issues": [{
                "title": "解释偏多",
                "affected_segment_ids": ["s2"],
                "commercial_impact": "拖慢节奏",
                "expected_improvement": "更快进入冲突",
            }],
            "rewrite_plan": [{"specific_action": "删减对白", "affected_segment_ids": ["s2"]}],
            "ecg_points": [{"segment_id": "s1", "episode_no": 1, "ecg_value": 4, "label": "反击"}],
        },
        {
            "episode_no": 2,
            "episode_title": "第二集",
            "episode_scope": {"segment_ids": ["s3"], "scene_count": 1, "segment_count": 1},
            "episode_structure": {"episode_goal": "找出幕后人", "evidence_segment_ids": ["s3"]},
            "dimension_scores": [
                {"dimension_key": "opening_hook", "score": 8},
                {"dimension_key": "conflict_pacing", "score": 12},
                {"dimension_key": "satisfying_payoff", "score": 13},
                {"dimension_key": "character_dialogue_filming", "score": 12},
                {"dimension_key": "market_compliance", "score": 12},
            ],
            "ecg_points": [{"segment_id": "s3", "episode_no": 2, "ecg_value": -1, "label": "解释"}],
        },
    ]
    payload["cross_episode_analysis"].update({
        "episode_score_trend": "第一集高，第二集回落",
        "best_episode_no": 1,
        "best_episode_reason": "开场强",
        "weakest_episode_no": 2,
        "weakest_episode_reason": "集尾弱",
        "score_gap_analysis": "两集差距来自钩子强度",
        "global_dropoff_pattern": "第二集解释造成掉点",
    })
    return payload


def test_compact_enhanced_payload_normalizes_deep_fields_and_visual_cards():
    result = compact_result_from(json.dumps(enhanced_compact_payload(), ensure_ascii=False))
    audit = result["audit"]
    visualization = result["visualization"]
    assert audit["meta"]["total_episode_count"] == 2
    assert audit["meta"]["total_segment_count"] == 3
    assert audit["global_review"]["global_score_explanation"].startswith("五大维度")
    assert audit["global_review"]["global_satisfying_points"][0]["closed_loop"] is True
    assert audit["episode_reviews"][0]["episode_scope"]["scene_count"] == 2
    assert audit["episode_reviews"][0]["episode_structure"]["episode_goal"] == "证明自己"
    assert audit["episode_reviews"][0]["ending_hook"]["evidence_segment_ids"] == ["s2"]
    assert len(audit["episode_reviews"][0]["dimension_scores"]) == 5
    assert audit["episode_reviews"][0]["episode_score"] == 12
    assert audit["cross_episode_analysis"]["best_episode_no"] == 1
    assert visualization["episode_score_map"][0]["best_retained_part"] == "主角反击"
    assert any(card.get("scope") == "episode" for card in visualization["dimension_cards"])
    assert any(card.get("scope") == "episode" for card in visualization["issue_cards"])
    assert any(card.get("scope") == "episode" for card in visualization["rewrite_cards"])


def test_compact_enhanced_wrapped_json_and_missing_segment_refs_warn():
    payload = enhanced_compact_payload()
    payload["global_review"]["global_ecg_points"].append({
        "segment_id": "missing_seg",
        "episode_no": 2,
        "ecg_value": -4,
        "label": "坏引用",
    })
    payload["episode_reviews"][0]["episode_scope"]["segment_ids"].append("missing_scope")
    raw = {"data": "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"}
    result = compact_result_from(json.dumps(raw, ensure_ascii=False))
    assert result["audit"]["schema_version"] == COMPACT_SCHEMA_VERSION
    assert any("missing_seg" in warning for warning in result["warnings"])
    assert any("missing_scope" in warning for warning in result["warnings"])
