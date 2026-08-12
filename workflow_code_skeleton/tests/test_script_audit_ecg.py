from __future__ import annotations

import json
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from workflow_code_skeleton.app.server import create_app
from workflow_code_skeleton.app.services.tencent_workflow_client import _build_request_body
from workflow_code_skeleton.app.services.script_audit_ecg_parser import (
    SCHEMA_VERSION,
    build_script_audit_view_model,
    parse_script_audit_workflow_output,
)
from workflow_code_skeleton.app.services.tencent_workflow_registry import (
    TENCENT_WORKFLOWS,
    build_workflow_inputs,
)


def dimensions(scores: tuple[int, int, int, int, int] = (12, 18, 20, 15, 10)) -> list[dict]:
    definitions = (
        ("opening_hook", "开场吸引力", 15),
        ("conflict_pacing", "冲突与节奏", 25),
        ("satisfying_payoff", "爽点兑现", 25),
        ("character_dialogue_filming", "人物对白与可拍性", 20),
        ("market_compliance", "市场适配与平台合规", 15),
    )
    return [
        {
            "dimension_key": key,
            "dimension_name": name,
            "max_score": maximum,
            "score": score,
            "summary": f"{name}审核",
            "deduction_reason": "",
            "fix_direction": "",
            "evidence_segment_ids": ["seg_e01_001"],
        }
        for (key, name, maximum), score in zip(definitions, scores)
    ]


def payload() -> dict:
    point = {
        "point_id": "ecg_e01_001",
        "segment_id": "seg_e01_001",
        "episode_no": 1,
        "scene_no": 1,
        "segment_index_global": 1,
        "segment_index_in_episode": 1,
        "x_label": "第1集·危机",
        "ecg_value": 3,
        "short_label": "危机",
        "audit_reason": "开场迅速建立危险。",
        "commercial_effect": "提高首集留存。",
        "problem_if_any": "",
        "fix_suggestion": "",
        "event_type": "钩子",
        "original_text_excerpt": "门外传来追兵的脚步声。",
        "tags": ["强钩子"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "script_title": "测试剧本",
            "text_type": "短剧剧本",
            "total_episode_count": 1,
            "total_segment_count": 1,
            "is_partial_review": False,
            "episode_detection": {
                "has_explicit_episode_titles": True,
                "detected_episode_numbers": [1],
                "missing_episode_numbers": [],
                "duplicate_episode_numbers": [],
                "episode_order_is_valid": True,
                "detection_evidence": "识别到第1集标题。",
            },
        },
        "overall": {
            "total_score": 75,
            "level": "B",
            "modification_cost": "中",
            "core_judgement": "具备开发价值。",
            "largest_problem": "中段略慢。",
            "best_retained_part": "开场危机。",
            "final_judgement": "可修改后测试。",
            "priority_fix": "压缩解释。",
        },
        "dimension_scores": dimensions(),
        "segments": [
            {
                "segment_id": "seg_e01_001",
                "episode_no": 1,
                "scene_no": 1,
                "segment_index_global": 1,
                "segment_index_in_episode": 1,
                "segment_type": "开场钩子",
                "summary": "主角遭追杀。",
                "original_text_excerpt": "门外传来追兵的脚步声。",
            }
        ],
        "global_review": {
            "main_genre": "穿越",
            "main_emotional_contract": "逆袭",
            "main_conflict_chain": "追杀升级",
            "protagonist_arc": "被动到主动",
            "payoff_chain": "识破并反击",
            "global_retention_problem": "中段解释偏长",
            "global_revision_priority": "先压缩解释",
            "global_score_explanation": "五项合计75分",
            "global_strength_summary": "钩子清楚",
            "global_weakness_summary": "节奏不均",
            "global_ecg_points": [point],
            "global_satisfying_points": [],
            "global_key_issues": [],
            "global_risk_scan": [],
            "global_rewrite_plan": [],
        },
        "episode_reviews": [
            {
                "episode_no": 1,
                "episode_title": "追杀",
                "episode_scope": "建立危机",
                "episode_score": 75,
                "episode_score_explanation": "开场有效",
                "level": "B",
                "core_judgement": "钩子成立",
                "main_hook": "追兵逼近",
                "main_conflict": "逃亡",
                "main_payoff": "识破埋伏",
                "largest_retention_loss": "解释略多",
                "best_retained_part": "开场",
                "next_episode_pull": "幕后人现身",
                "priority_fix": "缩短解释",
                "episode_structure": {"opening": "危机", "development": "逃亡", "climax": "识破", "ending": "悬念"},
                "dimension_scores": dimensions(),
                "ecg_points": [point],
                "ending_hook": {"hook_type": "悬念", "strength": "强", "description": "幕后人现身"},
                "satisfying_points": [],
                "key_issues": [],
                "risk_scan": [],
                "rewrite_plan": [],
            }
        ],
        "cross_episode_analysis": {"retention_curve_summary": "首集稳定"},
    }


class ScriptAuditEcgTests(unittest.TestCase):
    def test_tencent_end_node_text_is_unwrapped_and_normalized(self) -> None:
        raw = {"Output": {"audit": json.dumps(payload(), ensure_ascii=False)}}
        audit, warnings = parse_script_audit_workflow_output(raw)

        self.assertEqual([], warnings)
        self.assertEqual(SCHEMA_VERSION, audit["schema_version"])
        self.assertEqual(75, audit["overall"]["total_score"])
        self.assertEqual("测试剧本", audit["meta"]["script_title"])
        self.assertEqual("建立危机", audit["episode_reviews"][0]["episode_scope"])
        self.assertEqual(3, audit["global_review"]["global_ecg_points"][0]["ecg_value"])

        view = build_script_audit_view_model(audit)
        self.assertEqual(1, len(view["ecg_chart"]["points"]))
        self.assertIn("总评分：75/100", view["export_text"])

    def test_episode_points_are_global_fallback(self) -> None:
        value = payload()
        value["global_review"]["global_ecg_points"] = []
        audit, _ = parse_script_audit_workflow_output({"audit": json.dumps(value, ensure_ascii=False)})
        self.assertEqual("ecg_e01_001", audit["global_review"]["global_ecg_points"][0]["point_id"])

    def test_missing_all_ecg_points_is_rejected(self) -> None:
        value = payload()
        value["global_review"]["global_ecg_points"] = []
        value["episode_reviews"][0]["ecg_points"] = []
        with self.assertRaisesRegex(ValueError, "ecg_points"):
            parse_script_audit_workflow_output(value)

    def test_detected_episode_without_review_is_rejected(self) -> None:
        value = payload()
        value["meta"]["episode_detection"]["detected_episode_numbers"] = [1, 2]
        with self.assertRaisesRegex(ValueError, "第2集"):
            parse_script_audit_workflow_output(value)

    def test_hot_review_registry_matches_remote_start_and_end_names(self) -> None:
        spec = TENCENT_WORKFLOWS["hot_review"]
        self.assertEqual(
            (
                "script_title", "total_episodes", "batch_start_episode", "batch_end_episode",
                "previous_audit_memory", "batch_script_text", "is_final_batch",
            ),
            spec.input_names,
        )
        self.assertEqual(("audit_batch",), spec.response_fields)
        self.assertEqual("TENCENT_WORKFLOW_HOT_REVIEW_API_KEY", spec.api_key_env)
        self.assertEqual(
            {
                "script_title": "标题", "total_episodes": "6", "batch_start_episode": "1",
                "batch_end_episode": "5", "previous_audit_memory": "{}",
                "batch_script_text": "第1集 正文内容", "is_final_batch": "false",
            },
            build_workflow_inputs("hot_review", {
                "title": "标题", "total_episodes": 6, "batch_start_episode": 1,
                "batch_end_episode": 5, "previous_audit_memory": "{}",
                "text": "第1集 正文内容", "is_final_batch": False,
            }),
        )

    def test_hot_review_node_types_are_transported_as_required_strings(self) -> None:
        workflow_inputs = build_workflow_inputs("hot_review", {
            "script_title": "标题", "total_episodes": 11,
            "batch_start_episode": 6, "batch_end_episode": 10,
            "previous_audit_memory": "{}", "batch_script_text": "第6集\n正文",
            "is_final_batch": False,
        })
        body = _build_request_body(
            url="http://101.42.184.216/adp/v2/chat",
            spec=TENCENT_WORKFLOWS["hot_review"], api_key="test-key",
            workflow_inputs=workflow_inputs, request_id="typed-input-test",
        )
        sent_variables = body.get("WorkflowInput") or next(
            item["CustomVariables"]
            for item in body["Contents"]
            if item.get("Type") == "custom_variables"
        )
        self.assertEqual("11", sent_variables["total_episodes"])
        self.assertEqual("6", sent_variables["batch_start_episode"])
        self.assertEqual("10", sent_variables["batch_end_episode"])
        self.assertEqual("false", sent_variables["is_final_batch"])
        self.assertTrue(all(isinstance(value, str) for value in sent_variables.values()))

    @patch("workflow_code_skeleton.app.server.auth_store.get_user_by_token")
    @patch("workflow_code_skeleton.app.server.script_audit_batch_service.start_run")
    def test_authenticated_api_starts_background_batch_run(self, start_run, get_user_by_token) -> None:
        get_user_by_token.return_value = SimpleNamespace(id=7, username="tester")
        start_run.return_value = {
            "run_id": "a" * 32, "status": "pending", "total_episodes": 1,
            "total_batches": 1, "completed_batches": 0, "completed_episode_numbers": [],
            "progress_percent": 0,
        }
        app = create_app()
        app.config.update(TESTING=True)

        response = app.test_client().post(
            "/api/script-audit/run",
            json={"script_title": "测试剧本", "script_text": "第1集\n" + "有效剧本内容" * 20},
            headers={"Authorization": "Bearer test-token"},
        )

        self.assertEqual(202, response.status_code)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual("pending", data["status"])
        self.assertEqual("a" * 32, data["run_id"])
        start_run.assert_called_once()

    @patch("workflow_code_skeleton.app.server.auth_store.get_user_by_token")
    def test_authenticated_page_renders_dedicated_audit_ui(self, get_user_by_token) -> None:
        get_user_by_token.return_value = SimpleNamespace(id=7, username="tester")
        app = create_app()
        app.config.update(TESTING=True)

        response = app.test_client().get(
            "/script-audit",
            headers={"Authorization": "Bearer test-token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("script_audit.js", response.get_data(as_text=True))

    @patch("workflow_code_skeleton.app.server.auth_store.get_user_by_token")
    def test_authenticated_txt_upload_extracts_script_without_starting_a_run(self, get_user_by_token) -> None:
        get_user_by_token.return_value = SimpleNamespace(id=7, username="tester")
        app = create_app()
        app.config.update(TESTING=True)

        response = app.test_client().post(
            "/api/script-audit/extract-file",
            data={"file": (BytesIO("第1集\n有效正文".encode("utf-8")), "测试剧本.txt")},
            content_type="multipart/form-data",
            headers={"Authorization": "Bearer test-token"},
        )

        self.assertEqual(200, response.status_code)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual("测试剧本", data["script_title"])
        self.assertIn("第1集", data["script_text"])

    @patch("workflow_code_skeleton.app.server.auth_store.get_user_by_token")
    @patch("workflow_code_skeleton.app.server.script_audit_batch_service.get_debug")
    def test_authenticated_debug_endpoint_returns_sanitized_events(self, get_debug, get_user_by_token) -> None:
        get_user_by_token.return_value = SimpleNamespace(id=7, username="tester")
        get_debug.return_value = {
            "run_id": "a" * 32,
            "debug_file": "runtime_data/script_audits/run.debug.json",
            "events": [{"event": "workflow_attempt_failed", "details": {"http_status": 400}}],
        }
        app = create_app()
        app.config.update(TESTING=True)

        response = app.test_client().get(
            f"/api/script-audit/runs/{'a' * 32}/debug",
            headers={"Authorization": "Bearer test-token"},
        )

        self.assertEqual(200, response.status_code)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(400, data["debug"]["events"][0]["details"]["http_status"])
        get_debug.assert_called_once_with("a" * 32, user_id=7)


if __name__ == "__main__":
    unittest.main()
