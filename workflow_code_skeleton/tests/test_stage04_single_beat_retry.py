from __future__ import annotations

import unittest
from unittest.mock import patch

from workflow_code_skeleton.app.services.framework_planner_service import (
    FIFTEEN_BEAT_NAMES,
    FrameworkPlannerStageError,
    run_framework_planner_stage,
)


def _beat(beat_no: int) -> dict:
    start = (beat_no - 1) * 3 + 1
    end = 48 if beat_no == 15 else beat_no * 3
    return {
        "beat_no": beat_no,
        "act": "第一幕" if beat_no <= 6 else ("第二幕" if beat_no <= 12 else "第三幕"),
        "beat_name": FIFTEEN_BEAT_NAMES[beat_no - 1],
        "episode_range": f"第{start}-{end}集",
        "checkpoint_title": f"节拍{beat_no}",
        "narrative_function": "承担明确结构功能并推动下一阶段。",
        "plot_content": "通过具体事件、选择和结果推进剧情。",
        "character_change": "人物认知、关系或行动策略发生变化。",
        "conflict_upgrade": "外部压力与内部矛盾同步升级。",
        "hook_or_reversal": "结尾形成可由下一阶段承接的悬念。",
        "linked_storylines": ["主角主线"],
    }


def _complete_response() -> dict:
    return {
        "beat_checkpoint_timeline": [_beat(index) for index in range(1, 16)],
        "checkpoint_explanation": "三幕结构与十五节拍一一对应。",
        "display_text": "完整十五节拍已经生成。",
    }


def _payload() -> dict:
    return {
        "mode": "创作",
        "source_brief": {"core_logline": "测试故事"},
        "basic_config": {
            "season_count": 1,
            "episodes_per_season": 48,
            "total_episodes": 48,
        },
        "season_count": 1,
        "episodes_per_season": 48,
        "total_episodes": 48,
        "episode_count_guard": {
            "season_count": 1,
            "episodes_per_season": 48,
            "total_episodes": 48,
        },
        "worldview_plan": {"core_setting": "测试世界"},
        "character_plan": {"characters": [{"name": "测试主角"}]},
        "previous_beat_checkpoint_timeline": [],
        "user_feedback": "",
        "framework_score_report": "",
        "adaptation_direction": "保持因果完整",
        "user_requirements": "输出完整十五节拍",
    }


class Stage04SingleBeatRetryTests(unittest.TestCase):
    @patch(
        "workflow_code_skeleton.app.services.tencent_workflow_client."
        "tencent_workflow_client.run_raw"
    )
    def test_single_beat_triggers_one_corrective_retry(self, run_raw) -> None:
        run_raw.side_effect = [_beat(1), _complete_response()]

        result = run_framework_planner_stage("04", _payload())

        self.assertEqual(2, run_raw.call_count)
        self.assertEqual(15, len(result["data"]["beat_checkpoint_timeline"]))
        retry_variables = run_raw.call_args_list[1].args[1]
        self.assertIn("上一轮错误地只返回了一个 beat 对象", retry_variables["user_feedback"])
        self.assertIn("必须且只能包含 15 个节拍对象", retry_variables["framework_score_report"])

    @patch(
        "workflow_code_skeleton.app.services.tencent_workflow_client."
        "tencent_workflow_client.run_raw"
    )
    def test_two_single_beat_responses_raise_precise_error(self, run_raw) -> None:
        run_raw.side_effect = [_beat(1), _beat(1)]

        with self.assertRaises(FrameworkPlannerStageError) as context:
            run_framework_planner_stage("04", _payload())

        self.assertEqual(2, run_raw.call_count)
        self.assertEqual(422, context.exception.status_code)
        self.assertEqual(
            "tencent_stage04_returned_single_beat_object",
            context.exception.detail["reason"],
        )
        self.assertIn("连续两次仅返回单个节拍", str(context.exception))


if __name__ == "__main__":
    unittest.main()
