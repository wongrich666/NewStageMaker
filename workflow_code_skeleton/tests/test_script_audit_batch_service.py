from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_code_skeleton.app.services.script_audit_batch_service import (
    BATCH_SCHEMA_VERSION,
    WORKFLOW_MEMORY_MAX_CHARS,
    ScriptAuditBatchService,
    compact_audit_memory,
    compact_workflow_audit_memory,
    merge_audit_batches,
    parse_script_episodes,
    pending_episode_batches,
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
            "previous_episode_no": number - 1 if number > 1 else 0,
            "current_episode_no": number,
            "handoff_smoothness_score": 8, "incoming_plot_matches": True,
            "character_state_matches": True, "time_space_transition_is_clear": True,
            "information_progression_is_valid": True, "emotion_transition_is_natural": True,
            "continuity_evidence": {
                "previous_ending_fact": "上一集结尾追兵逼近" if number > 1 else "首集无上一集",
                "current_opening_fact": "本集开场听见追兵脚步",
                "match_judgement": "动作、时空、人物与情绪承接成立",
            },
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
            "last_episode_handoff": {
                "episode_no": end,
                "ending_scene_summary": "结尾出现新危机",
                "ending_time_space": "仓库·当夜",
                "ending_emotion": "期待",
                "active_action_or_crisis": "追兵逼近",
                "ending_hook_promise": "下一集必须处理追兵",
                "ending_text_excerpt": "门外响起脚步声",
                "character_state_snapshot": [],
                "information_state": [],
                "prop_resource_state": [],
                "relationship_state": [],
                "unresolved_actions": ["处理追兵"],
                "continuity_watch_points": ["下一集开场是否承接脚步声"],
            },
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
    def __init__(self) -> None:
        self.calls = 0

    def run_raw(self, stage_name: str, variables: dict) -> dict:
        self.calls += 1
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


class FlakySummaryClient(FakeClient):
    def __init__(self, failures: int = 2) -> None:
        super().__init__()
        self.failures = failures

    def run_raw(self, stage_name: str, variables: dict) -> dict:
        self.calls.append(dict(variables))
        if len(self.calls) <= self.failures:
            return {"reply": {"audit_batch": {
                "batch_start_episode": int(variables["batch_start_episode"]),
                "batch_end_episode": int(variables["batch_end_episode"]),
                "total_episodes": int(variables["total_episodes"]),
                "reviewed_episode_numbers": list(range(
                    int(variables["batch_start_episode"]), int(variables["batch_end_episode"]) + 1
                )),
                "is_final_batch": False,
                "batch_core_judgement": "远端临时退化摘要",
            }}}
        start = int(variables["batch_start_episode"])
        end = int(variables["batch_end_episode"])
        total = int(variables["total_episodes"])
        return {"Output": {"audit_batch": json.dumps(batch_payload(start, end, total), ensure_ascii=False)}}


class ScriptAuditBatchServiceTests(unittest.TestCase):
    def script(self, count: int) -> str:
        return "《测试》\n\n四、剧本正文\n" + "\n\n".join(
            f"第{number}集：标题{number}\n场景{number}\n人物：本集有效剧本内容。" for number in range(1, count + 1)
        )

    def test_export_text_is_split_into_three_episode_batches_with_short_tail(self) -> None:
        episodes = parse_script_episodes(self.script(11))
        batches = split_episode_batches(episodes)
        self.assertEqual(4, len(batches))
        self.assertEqual([1, 2, 3], batches[0]["episode_numbers"])
        self.assertEqual([4, 5, 6], batches[1]["episode_numbers"])
        self.assertEqual([7, 8, 9], batches[2]["episode_numbers"])
        self.assertEqual([10, 11], batches[3]["episode_numbers"])

    def test_pending_batches_regroup_only_unfinished_suffix_after_old_single_runs(self) -> None:
        episodes = parse_script_episodes(self.script(16))
        batches = pending_episode_batches(episodes, set(range(1, 10)))

        self.assertEqual(
            [[10, 11, 12], [13, 14, 15], [16]],
            [item["episode_numbers"] for item in batches],
        )

    def test_same_user_and_script_reuses_one_persistent_asset_without_new_workflow_call(self) -> None:
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            service = ScriptAuditBatchService(Path(directory), client=client)
            first = service.start_run(
                user_id=7, script_title="第一次名称", script_text=self.script(5), launch=False,
            )
            service._run(first["run_id"])
            calls_after_first_run = len(client.calls)
            reused = service.start_run(
                user_id=7,
                script_title="相同正文的另一个名称",
                script_text=self.script(5).replace("\n", "\r\n") + "\r\n",
                launch=True,
            )
            assets = service.list_assets(user_id=7)

        self.assertEqual(first["run_id"], reused["run_id"])
        self.assertTrue(reused["asset_reused"])
        self.assertEqual("completed_result", reused["reuse_reason"])
        self.assertEqual("succeeded", reused["status"])
        self.assertEqual("相同正文的另一个名称", reused["script_title"])
        self.assertEqual("相同正文的另一个名称", reused["audit"]["meta"]["script_title"])
        self.assertEqual(2, calls_after_first_run)
        self.assertEqual(calls_after_first_run, len(client.calls))
        self.assertEqual(1, len(assets))
        self.assertEqual("相同正文的另一个名称", assets[0]["script_title"])
        self.assertNotIn("script_text", assets[0])
        self.assertNotIn("audit", assets[0])

    def test_completed_asset_can_be_deleted_with_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ScriptAuditBatchService(Path(directory), client=FakeClient())
            started = service.start_run(
                user_id=7, script_title="待删除", script_text=self.script(1), launch=False,
            )
            service._run(started["run_id"])
            debug_path = service._debug_path(started["run_id"])
            debug_path.write_text("{}", encoding="utf-8")

            deleted = service.delete_run(started["run_id"], user_id=7)

            self.assertTrue(deleted["deleted"])
            self.assertEqual("待删除", deleted["script_title"])
            self.assertFalse(service._path(started["run_id"]).exists())
            self.assertFalse(service._summary_path(started["run_id"]).exists())
            self.assertFalse(debug_path.exists())
            self.assertEqual([], service.list_assets(user_id=7))

    def test_asset_delete_checks_owner_and_rejects_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ScriptAuditBatchService(Path(directory), client=FakeClient())
            started = service.start_run(
                user_id=7, script_title="运行中", script_text=self.script(1), launch=False,
            )

            with self.assertRaisesRegex(ValueError, "不存在"):
                service.delete_run(started["run_id"], user_id=8)
            with self.assertRaisesRegex(RuntimeError, "仍在运行"):
                service.delete_run(started["run_id"], user_id=7)

            self.assertTrue(service._path(started["run_id"]).exists())

    def test_same_script_is_not_deduplicated_across_users(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ScriptAuditBatchService(Path(directory), client=FakeClient())
            first = service.start_run(user_id=7, script_title="用户甲", script_text=self.script(1), launch=False)
            second = service.start_run(user_id=8, script_title="用户乙", script_text=self.script(1), launch=False)

        self.assertNotEqual(first["run_id"], second["run_id"])

    def test_asset_detail_restores_uploaded_source_after_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ScriptAuditBatchService(Path(directory), client=FakeClient())
            started = service.start_run(user_id=7, script_title="刷新恢复", script_text=self.script(2), launch=False)
            restored = service.get_run(started["run_id"], user_id=7)

        self.assertEqual("刷新恢复", restored["script_title"])
        self.assertIn("第1集", restored["script_text"])
        self.assertEqual(started["run_id"], restored["asset_id"])

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

    def test_batch_parser_recovers_full_model_json_when_end_node_reply_is_summary(self) -> None:
        complete = batch_payload(1, 1, 1)
        raw = {
            "reply": {"audit": {
                "batch_start_episode": 1, "batch_end_episode": 1,
                "reviewed_episode_numbers": [1], "batch_core_judgement": "摘要",
            }},
            "events": [{
                "data": {"Response": {"Procedures": [{"Workflow": {"RunNodes": [{
                    "NodeName": "大模型1", "NodeType": 4,
                    "Output": {"Content": json.dumps(complete, ensure_ascii=False)},
                }]}}]}},
            }],
        }

        parsed, warnings = validate_batch_output(raw, [1])

        self.assertEqual(BATCH_SCHEMA_VERSION, parsed["schema_version"])
        self.assertEqual([], warnings)

    def test_batch_parser_reports_remote_summary_fields_and_required_end_node(self) -> None:
        raw = {"reply": {"audit": {
            "batch_start_episode": 1, "batch_end_episode": 5, "total_episodes": 5,
            "reviewed_episode_numbers": [1, 2, 3, 4, 5],
            "is_final_batch": False, "batch_core_judgement": "只有摘要",
        }}}

        with self.assertRaisesRegex(
            ValueError,
            "不完整批次摘要.*episode_reviews.*本地传入 48.*远端返回 5.*Output.audit_batch",
        ):
            validate_batch_output(raw, [1, 2, 3, 4, 5], 48)

    def test_batch_parser_reports_truncated_full_json_instead_of_end_node_summary(self) -> None:
        raw = {"audit_batch": '{"schema_version":"script_audit_batch_v1","episode_reviews":[{"episode_no":1},'}

        with self.assertRaisesRegex(ValueError, "JSON 在输出中途被截断.*不是前端解析丢失"):
            validate_batch_output(raw, [1], 48)

    def test_batch_contract_repairs_total_episode_count_replaced_by_batch_size(self) -> None:
        value = batch_payload(1, 5, 5)

        parsed, warnings = validate_batch_output(value, [1, 2, 3, 4, 5], 48)

        self.assertEqual(48, parsed["batch_meta"]["total_episodes"])
        self.assertFalse(parsed["batch_meta"]["is_final_batch"])
        self.assertTrue(any("自动校正为 48" in warning for warning in warnings))

    def test_batch_contract_rejects_missing_emotion_and_incorrect_score_sum(self) -> None:
        missing_emotion = batch_payload(1, 1, 1)
        missing_emotion["episode_reviews"][0]["emotional_review"] = {}
        with self.assertRaisesRegex(ValueError, "emotional_review"):
            validate_batch_output(missing_emotion, [1])

        incorrect_sum = batch_payload(1, 1, 1)
        incorrect_sum["episode_reviews"][0]["episode_score"] = 99
        with self.assertRaisesRegex(ValueError, "五维合计"):
            validate_batch_output(incorrect_sum, [1])

    def test_legacy_memory_gets_a_handoff_snapshot_for_the_next_episode(self) -> None:
        value = batch_payload(1, 1, 2)
        value["next_audit_memory"].pop("last_episode_handoff")

        parsed, warnings = validate_batch_output(value, [1], 2)

        handoff = parsed["next_audit_memory"]["last_episode_handoff"]
        self.assertEqual(1, handoff["episode_no"])
        self.assertEqual("期待", handoff["ending_emotion"])
        self.assertEqual("反转", handoff["ending_scene_summary"])
        self.assertTrue(any("兼容交接快照" in warning for warning in warnings))

    def test_legacy_continuity_fields_are_repaired_without_discarding_full_batch(self) -> None:
        value = batch_payload(1, 2, 2)
        for review in value["episode_reviews"]:
            review["continuity_review"].pop("previous_episode_no")
            review["continuity_review"].pop("current_episode_no")
            review["continuity_review"].pop("continuity_evidence")

        parsed, warnings = validate_batch_output(value, [1, 2], 2)

        self.assertEqual(0, parsed["episode_reviews"][0]["continuity_review"]["previous_episode_no"])
        self.assertEqual(2, parsed["episode_reviews"][1]["continuity_review"]["current_episode_no"])
        self.assertTrue(any("本地已按剧本连续集号补齐" in warning for warning in warnings))
        self.assertTrue(any("缺少逐项 continuity_evidence" in warning for warning in warnings))

    def test_compact_memory_preserves_structured_episode_handoff(self) -> None:
        memory = compact_audit_memory(batch_payload(3, 3, 6)["next_audit_memory"])

        self.assertEqual(3, memory["last_episode_handoff"]["episode_no"])
        self.assertEqual("仓库·当夜", memory["last_episode_handoff"]["ending_time_space"])

    def test_workflow_memory_is_bounded_without_losing_latest_handoff(self) -> None:
        memory = batch_payload(1, 3, 60)["next_audit_memory"]
        memory["last_episode_handoff"]["continuity_watch_points"] = ["承接点" * 30] * 20
        memory["current_character_states"] = [
            {"character": f"人物{number}", "state": "人物状态" * 30}
            for number in range(20)
        ]
        memory["global_key_issues"] = [
            {"issue_id": f"issue_{number}", "evidence": "问题证据" * 50}
            for number in range(15)
        ]
        memory["episode_score_index"] = [
            {"episode_no": number, "score": 70 + number % 10}
            for number in range(1, 61)
        ]

        compacted = compact_workflow_audit_memory(memory, retry_instruction="必须返回完整 JSON")
        encoded = json.dumps(compacted, ensure_ascii=False, separators=(",", ":"))

        self.assertLessEqual(len(encoded), WORKFLOW_MEMORY_MAX_CHARS)
        self.assertEqual(3, compacted["reviewed_through_episode"])
        self.assertEqual(3, compacted["last_episode_handoff"]["episode_no"])
        self.assertEqual("必须返回完整 JSON", compacted["_format_retry_instruction"])

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

    def test_final_merge_rebuilds_scores_and_combines_all_batch_records(self) -> None:
        first = batch_payload(1, 1, 2)
        second = batch_payload(2, 2, 2)
        first["batch_key_issues"] = [{"issue_id": "issue_e01_001", "title": "第一集问题"}]
        second["batch_key_issues"] = [{"issue_id": "issue_e02_001", "title": "第二集问题"}]
        second["next_audit_memory"]["global_key_issues"] = [
            {"issue_id": "issue_global_001", "title": "全剧问题"}
        ]
        second["next_audit_memory"]["episode_score_index"] = []

        audit, _ = merge_audit_batches("测试", 2, [first, second])

        self.assertEqual(
            ["issue_global_001", "issue_e01_001", "issue_e02_001"],
            [item["issue_id"] for item in audit["global_review"]["global_key_issues"]],
        )
        self.assertEqual(
            [{"episode_no": 1, "score": 78}, {"episode_no": 2, "score": 78}],
            audit["cross_episode_analysis"]["episode_score_trend"],
        )

    def test_runner_passes_replacement_memory_to_each_next_three_episode_batch(self) -> None:
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
        self.assertEqual(3, previous["reviewed_through_episode"])
        self.assertEqual(3, previous["last_episode_handoff"]["episode_no"])
        self.assertEqual("下一集必须处理追兵", previous["last_episode_handoff"]["ending_hook_promise"])
        self.assertEqual(4, client.calls[1]["batch_start_episode"])
        self.assertEqual(6, client.calls[1]["batch_end_episode"])
        self.assertTrue(client.calls[1]["is_final_batch"])
        self.assertEqual(4, client.calls[-1]["batch_start_episode"])
        self.assertTrue(client.calls[-1]["is_final_batch"])
        event_names = [item["event"] for item in debug["events"]]
        self.assertIn("workflow_attempt_started", event_names)
        self.assertIn("workflow_attempt_succeeded", event_names)
        started_event = next(item for item in debug["events"] if item["event"] == "workflow_attempt_started")
        self.assertTrue(all(value == "str" for value in started_event["details"]["workflow_input_types"].values()))
        self.assertNotIn("本集有效剧本内容", json.dumps(debug, ensure_ascii=False))

    @patch("workflow_code_skeleton.app.services.script_audit_batch_service.time.sleep", return_value=None)
    def test_incomplete_three_episode_summary_adaptively_splits_and_preserves_progress(self, _sleep) -> None:
        client = FlakySummaryClient(failures=2)
        with tempfile.TemporaryDirectory() as directory:
            service = ScriptAuditBatchService(Path(directory), client=client)
            started = service.start_run(user_id=7, script_title="测试", script_text=self.script(5), launch=False)
            service._run(started["run_id"])
            result = service.get_run(started["run_id"], user_id=7)
            debug = service.get_debug(started["run_id"], user_id=7)

        self.assertEqual("succeeded", result["status"])
        self.assertEqual([1, 2, 3, 4, 5], result["completed_episode_numbers"])
        self.assertEqual(5, len(client.calls))
        self.assertEqual(1, len([event for event in debug["events"] if event["event"] == "batch_retry_scheduled"]))
        splits = [event for event in debug["events"] if event["event"] == "batch_adaptive_split"]
        self.assertEqual(1, len(splits))
        self.assertEqual([[1, 2], [3, 3]], splits[0]["details"]["fallback_ranges"])

    def test_resume_of_legacy_five_episode_batch_continues_from_first_missing_episode(self) -> None:
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            service = ScriptAuditBatchService(Path(directory), client=client)
            started = service.start_run(
                user_id=7,
                script_title="测试",
                script_text=self.script(6),
                launch=False,
            )
            private = service._read(started["run_id"])
            legacy_batch = batch_payload(1, 5, 6)
            private.update(
                status="failed",
                batches=[legacy_batch],
                audit_memory=legacy_batch["next_audit_memory"],
                completed_batches=1,
                completed_episode_numbers=[1, 2, 3, 4, 5],
            )
            service._write(private)

            service._run(started["run_id"])
            result = service.get_run(started["run_id"], user_id=7)

        self.assertEqual("succeeded", result["status"])
        self.assertEqual([1, 2, 3, 4, 5, 6], result["completed_episode_numbers"])
        self.assertEqual(1, len(client.calls))
        self.assertEqual(6, client.calls[0]["batch_start_episode"])
        self.assertEqual(6, client.calls[0]["batch_end_episode"])
        self.assertTrue(client.calls[0]["is_final_batch"])
        self.assertEqual(5, json.loads(client.calls[0]["previous_audit_memory"])["reviewed_through_episode"])

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
