from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_code_skeleton.app.services.script_audit_batch_service import (
    BATCH_SCHEMA_VERSION,
    ScriptAuditBatchService,
    merge_audit_batches,
    parse_script_episodes,
    split_episode_batches,
    validate_batch_output,
)


DIMENSIONS = (
    ("opening_hook", "开场吸引力", 15, 12),
    ("conflict_pacing", "冲突与节奏", 25, 20),
    ("satisfying_payoff", "爽点兑现", 25, 18),
    ("character_dialogue_filming", "人物对白与可拍性", 20, 16),
    ("market_compliance", "市场适配与平台合规", 15, 12),
)


def episode_review(number: int) -> dict:
    return {
        "episode_no": number,
        "episode_title": f"第{number}集测试",
        "episode_scope": "推进主线",
        "episode_score": 78,
        "episode_score_explanation": "五维合计",
        "level": "B",
        "core_judgement": "本集有效但仍有节奏问题。",
        "main_hook": "开场危机",
        "main_conflict": "目标受阻",
        "main_payoff": "主角反击",
        "largest_retention_loss": "中段解释偏长",
        "best_retained_part": "结尾反转",
        "next_episode_pull": "新危机出现",
        "priority_fix": "压缩解释",
        "episode_structure": {"opening": "危机", "development": "受阻", "climax": "反击", "ending": "反转"},
        "emotional_review": {
            "opening_emotion": "紧张", "dominant_emotion": "压迫", "ending_emotion": "期待",
            "emotional_turning_points": ["反击"], "emotional_payoff": "完成一次释放", "emotional_curve_score": 7,
        },
        "continuity_review": {
            "handoff_smoothness_score": 8, "incoming_plot_matches": True,
            "character_state_matches": True, "time_space_transition_is_clear": True,
            "information_progression_is_valid": True, "emotion_transition_is_natural": True,
            "break_points": [], "fix_suggestion": "",
        },
        "dimension_scores": [
            {
                "dimension_key": key, "dimension_name": name, "max_score": maximum,
                "score": score, "summary": "有证据的判断", "deduction_reason": "具体扣分",
                "fix_direction": "具体修改", "evidence_segment_ids": [f"seg_e{number:02d}_001"],
            }
            for key, name, maximum, score in DIMENSIONS
        ],
        "ecg_points": [
            {
                "point_id": f"ecg_e{number:02d}_001", "segment_id": f"seg_e{number:02d}_001",
                "episode_no": number, "scene_no": 1, "segment_index_in_episode": 1,
                "x_label": f"第{number}集·危机", "ecg_value": 3, "short_label": "危机",
                "audit_reason": "建立当下危险", "commercial_effect": "提升留存", "problem_if_any": "",
                "fix_suggestion": "", "event_type": "钩子", "event_subtype": "危机开场",
                "original_text_excerpt": "门外响起脚步声", "tags": ["强钩子"], "score_impacts": ["opening_hook:+2"],
            }
        ],
        "ending_hook": {"hook_type": "悬念", "strength": "强", "description": "新危机"},
        "satisfying_points": [], "key_issues": [], "risk_scan": [], "rewrite_plan": [],
    }


def batch_payload(start: int, end: int, total: int) -> dict:
    reviews = [episode_review(number) for number in range(start, end + 1)]
    return {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_meta": {
            "batch_start_episode": start, "batch_end_episode": end, "total_episodes": total,
            "reviewed_episode_numbers": list(range(start, end + 1)), "is_final_batch": end == total,
        },
        "boundary_review": {
            "previous_episode_no": start - 1 if start > 1 else 0, "current_episode_no": start,
            "handoff_smoothness_score": 8, "plot_continuity": "承接成立",
            "character_state_continuity": "一致", "information_continuity": "递进",
            "emotion_continuity": "自然", "break_points": [], "fix_suggestion": "",
        },
        "segments": [], "episode_reviews": reviews, "batch_key_issues": [], "batch_rewrite_plan": [],
        "batch_satisfying_points": [], "batch_risk_scan": [],
        "next_audit_memory": {
            "reviewed_through_episode": end, "main_genre": "都市逆袭",
            "main_emotional_contract": "受压后反击", "main_conflict_chain": "压力逐级升级",
            "protagonist_arc": "被动转主动", "payoff_chain": "逐步兑现",
            "episode_score_index": [{"episode_no": number, "score": 78} for number in range(1, end + 1)],
            "weak_episode_numbers": [], "best_episode_no": 1, "best_episode_reason": "开场清楚",
            "weakest_episode_no": end, "weakest_episode_reason": "中段偏慢",
            "running_retention_judgement": "具备追更基础", "global_strength_summary": "冲突清楚",
            "global_weakness_summary": "解释偏多", "largest_problem": "中段解释拖慢节奏",
            "best_retained_part": "开场危机", "priority_fix": "压缩说明台词",
            "final_judgement": "修改后可测试", "modification_cost": "中",
            "retention_curve_summary": "整体平稳", "fix_suggestion": "先改弱集",
        },
    }


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_raw(self, stage_name: str, variables: dict) -> dict:
        self.calls.append(dict(variables))
        start = int(variables["batch_start_episode"])
        end = int(variables["batch_end_episode"])
        total = int(variables["total_episodes"])
        return {"Output": {"audit_batch": json.dumps(batch_payload(start, end, total), ensure_ascii=False)}}


class FailingClient:
    def run_raw(self, stage_name: str, variables: dict) -> dict:
        raise RuntimeError(
            "腾讯工作流阶段 hot_review 返回 HTTP 400："
            "json: cannot unmarshal number into Go struct field WorkflowInput of type string"
        )

    def get_last_stage_debug_info(self, stage_name: str) -> dict:
        return {
            "status": "http_error",
            "request_id": "request-debug-001",
            "http_status": 400,
            "input_types": {"total_episodes": "int"},
            "response_preview": "cannot unmarshal number into WorkflowInput of type string",
            "api_key_present": True,
        }


class ScriptAuditBatchServiceTests(unittest.TestCase):
    def script(self, count: int) -> str:
        return "《测试》\n\n四、剧本正文\n" + "\n\n".join(
            f"第{number}集：标题{number}\n场景{number}\n人物：本集有效剧本内容。" for number in range(1, count + 1)
        )

    def test_export_text_is_split_into_five_episode_batches(self) -> None:
        episodes = parse_script_episodes(self.script(11))
        batches = split_episode_batches(episodes)
        self.assertEqual([1, 2, 3, 4, 5], batches[0]["episode_numbers"])
        self.assertEqual([6, 7, 8, 9, 10], batches[1]["episode_numbers"])
        self.assertEqual([11], batches[2]["episode_numbers"])

    def test_chinese_episode_numbers_and_missing_episode_are_handled(self) -> None:
        episodes = parse_script_episodes("第一集\n正文一\n\n第二集：继续\n正文二")
        self.assertEqual([1, 2], [item["episode_no"] for item in episodes])
        with self.assertRaisesRegex(ValueError, "缺少.*第2集"):
            parse_script_episodes("第1集\n正文一\n第3集\n正文三")

    def test_batch_contract_rejects_a_missing_episode(self) -> None:
        value = batch_payload(1, 5, 6)
        value["episode_reviews"].pop()
        with self.assertRaisesRegex(ValueError, "期望.*实际"):
            validate_batch_output(value, [1, 2, 3, 4, 5])

    def test_batch_contract_rejects_missing_emotion_and_incorrect_score_sum(self) -> None:
        missing_emotion = batch_payload(1, 1, 1)
        missing_emotion["episode_reviews"][0]["emotional_review"] = {}
        with self.assertRaisesRegex(ValueError, "emotional_review"):
            validate_batch_output(missing_emotion, [1])

        incorrect_sum = batch_payload(1, 1, 1)
        incorrect_sum["episode_reviews"][0]["episode_score"] = 99
        with self.assertRaisesRegex(ValueError, "五维合计"):
            validate_batch_output(incorrect_sum, [1])

    def test_final_merge_keeps_emotion_continuity_and_all_points(self) -> None:
        audit, warnings = merge_audit_batches("测试", 6, [batch_payload(1, 5, 6), batch_payload(6, 6, 6)])
        self.assertEqual([], warnings)
        self.assertEqual(6, len(audit["episode_reviews"]))
        self.assertEqual(6, len(audit["global_review"]["global_ecg_points"]))
        self.assertEqual("压迫", audit["episode_reviews"][0]["emotional_review"]["dominant_emotion"])
        self.assertEqual(8, audit["episode_reviews"][5]["continuity_review"]["handoff_smoothness_score"])
        self.assertEqual(2, len(audit["cross_episode_analysis"]["batch_boundaries"]))

    def test_final_merge_falls_back_to_batch_issues_when_memory_list_is_empty(self) -> None:
        value = batch_payload(1, 1, 1)
        value["batch_key_issues"] = [{"issue_id": "issue_e01_001", "title": "开场解释过长"}]
        value["next_audit_memory"]["global_key_issues"] = []

        audit, _ = merge_audit_batches("测试", 1, [value])

        self.assertEqual("issue_e01_001", audit["global_review"]["global_key_issues"][0]["issue_id"])

    def test_runner_passes_replacement_memory_to_next_tail_batch(self) -> None:
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            service = ScriptAuditBatchService(Path(directory), client=client)
            started = service.start_run(user_id=7, script_title="测试", script_text=self.script(6), launch=False)
            service._run(started["run_id"])
            result = service.get_run(started["run_id"], user_id=7)
            debug = service.get_debug(started["run_id"], user_id=7)

        self.assertEqual("succeeded", result["status"])
        self.assertEqual([1, 2, 3, 4, 5, 6], result["completed_episode_numbers"])
        self.assertEqual(2, len(client.calls))
        self.assertEqual("{}", client.calls[0]["previous_audit_memory"])
        previous = json.loads(client.calls[1]["previous_audit_memory"])
        self.assertEqual(5, previous["reviewed_through_episode"])
        self.assertEqual(6, client.calls[1]["batch_start_episode"])
        self.assertTrue(client.calls[1]["is_final_batch"])
        event_names = [item["event"] for item in debug["events"]]
        self.assertIn("workflow_attempt_started", event_names)
        self.assertIn("workflow_attempt_succeeded", event_names)
        started_event = next(item for item in debug["events"] if item["event"] == "workflow_attempt_started")
        self.assertTrue(all(value == "str" for value in started_event["details"]["workflow_input_types"].values()))
        self.assertNotIn("本集有效剧本内容", json.dumps(debug, ensure_ascii=False))

    @patch("workflow_code_skeleton.app.services.script_audit_batch_service.time.sleep", return_value=None)
    def test_failed_batch_writes_http_response_and_traceback_to_debug_file(self, _sleep) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ScriptAuditBatchService(Path(directory), client=FailingClient())
            started = service.start_run(user_id=7, script_title="测试", script_text=self.script(1), launch=False)
            service._run(started["run_id"])
            result = service.get_run(started["run_id"], user_id=7)
            debug = service.get_debug(started["run_id"], user_id=7)

        self.assertEqual("failed", result["status"])
        self.assertTrue(result["debug_file"].endswith(".debug.json"))
        failures = [item for item in debug["events"] if item["event"] == "workflow_attempt_failed"]
        self.assertEqual(2, len(failures))
        self.assertEqual(400, failures[-1]["details"]["client_debug"]["http_status"])
        self.assertIn("cannot unmarshal number", failures[-1]["details"]["client_debug"]["response_preview"])
        self.assertIn("Traceback", failures[-1]["details"]["traceback"])
        self.assertEqual("run_failed", debug["events"][-1]["event"])


if __name__ == "__main__":
    unittest.main()
