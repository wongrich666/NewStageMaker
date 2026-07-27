from __future__ import annotations

import unittest

import workflow_code_skeleton.app.services.platform_agent as platform_agent_module
from workflow_code_skeleton.app.services.platform_agent import (
    AGENT_SYSTEM_PROMPT,
    TOOL_DEFINITIONS,
    PlatformConversationAgent,
    _has_explicit_confirmation,
    _normalize_choice_answer,
    _safe_tool_calls,
    _script_team_summary,
)


class PlatformAgentSemanticTests(unittest.TestCase):
    def test_prompt_requires_semantic_understanding_instead_of_keywords(self) -> None:
        self.assertIn("不要依赖固定关键词", AGENT_SYSTEM_PROMPT)
        self.assertIn("口语、省略句、错别字、代词或承接上文", AGENT_SYSTEM_PROMPT)
        self.assertIn("讨论/咨询", AGENT_SYSTEM_PROMPT)

    def test_new_generation_uses_script_team_instead_of_fastgpt_pipeline(self) -> None:
        self.assertIn("专业剧本团队", AGENT_SYSTEM_PROMPT)
        self.assertNotIn("FastGPT", AGENT_SYSTEM_PROMPT)
        self.assertNotIn("01-12", AGENT_SYSTEM_PROMPT)

    def test_script_team_job_maps_to_agent_progress_shape(self) -> None:
        summary = _script_team_summary(
            {
                "job_id": "npc-demo",
                "status": "stage_running",
                "status_text": "人物情感编剧正在运行",
                "progress": 29,
                "active_stage": "character_emotion",
                "execution_scope": "framework_and_script",
                "request": {"project_title": "测试剧", "episodes": 5},
            }
        )

        self.assertEqual(summary["generation_chain"], "script_team_v2")
        self.assertEqual(summary["task_id"], "npc-demo")
        self.assertEqual(summary["pipeline_stage"], 3)
        self.assertEqual(summary["current_stage_label"], "人物情感编剧")
        self.assertEqual(summary["workspace_url"], "/new-workflow-test")

    def test_natural_start_confirmations_are_accepted(self) -> None:
        for value in (
            "就这么办",
            "按这个来",
            "就按这个方案开始吧",
            "照刚才的方案做",
            "可以开始了",
        ):
            with self.subTest(value=value):
                self.assertTrue(_has_explicit_confirmation(value, action="start"))

    def test_negative_confirmation_still_blocks_execution(self) -> None:
        for value in ("先不要开始", "取消，别执行", "暂不确认"):
            with self.subTest(value=value):
                self.assertFalse(_has_explicit_confirmation(value, action="start"))

    def test_model_can_request_a_semantic_choice_card(self) -> None:
        tool_names = [item["function"]["name"] for item in TOOL_DEFINITIONS]
        self.assertIn("ask_choice", tool_names)

        result = PlatformConversationAgent()._execute_tool(
            user_id=1,
            username="tester",
            conversation={"id": "conversation-1"},
            name="ask_choice",
            arguments={
                "field": "execution_scope",
                "question": "你想先整理故事骨架，还是直接产出完整剧本？",
                "options": [
                    {
                        "label": "先做故事骨架",
                        "prompt": "先完成 01-07 框架策划，不生成正文。",
                        "description": "先确认人物、节拍和故事线",
                    },
                    {
                        "label": "直接完成剧本",
                        "prompt": "运行专业剧本团队全部节点，生成完整剧本。",
                        "description": "框架与正文一起完成",
                    },
                ],
            },
            user_content="",
            attached_document=None,
            selected_knowledge={},
            internal_api_base_url="",
            internal_auth_token="",
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["awaiting_user_input"])
        self.assertEqual(result["ui"]["kind"], "choice")
        self.assertEqual(len(result["options"]), 2)

    def test_choice_card_cannot_share_a_turn_with_an_operation(self) -> None:
        operation = {"function": {"name": "prepare_script_generation"}}
        choice = {"function": {"name": "ask_choice"}}
        self.assertEqual(_safe_tool_calls([operation, choice]), [choice])
        self.assertEqual(_safe_tool_calls([operation]), [operation])

    def test_short_choice_followup_keeps_its_semantic_field(self) -> None:
        messages = [
            {
                "role": "assistant",
                "metadata": {
                    "events": [
                        {
                            "tool": "ask_choice",
                            "result": {
                                "field": "episode_count",
                                "ui": {"kind": "choice"},
                            },
                        }
                    ]
                },
            },
            {"role": "user", "content": "60"},
        ]
        self.assertEqual(_normalize_choice_answer("60", messages), "总集数：60 集")


if __name__ == "__main__":
    unittest.main()


def test_confirm_generation_creates_script_team_job(monkeypatch) -> None:
    saved_jobs = []

    class FakeJobs:
        def create(self, *, user_id, request_payload):
            return {
                "job_id": "npc-agent-test",
                "user_id": user_id,
                "status": "created",
                "status_text": "等待启动",
                "progress": 0,
                "request": {
                    "project_title": request_payload["project_title"],
                    "episodes": request_payload["episodes"],
                    "episode_word_count": request_payload["episode_word_count"],
                },
                "recovered_files": {},
                "final_script": "",
            }

        def save(self, job):
            saved_jobs.append(dict(job))
            return job

    class FakeClient:
        @staticmethod
        def trigger(job):
            return {"sn": "build-agent-test", "buildLogUrl": "https://example.invalid/build"}

    class FakeConversationStore:
        @staticmethod
        def update(user_id, conversation_id, **changes):
            return {"id": conversation_id, "user_id": user_id, **changes}

    monkeypatch.setattr(platform_agent_module, "_SCRIPT_TEAM_JOBS", FakeJobs())
    monkeypatch.setattr(platform_agent_module, "_SCRIPT_TEAM_CLIENT", FakeClient())
    monkeypatch.setattr(platform_agent_module, "agent_conversation_store", FakeConversationStore())
    conversation = {
        "id": "conversation-test",
        "user_id": 7,
        "project_id": None,
        "task_id": "",
        "state": {
            "pending_action": {
                "type": "start_script_generation",
                "payload": {
                    "title": "新团队测试剧",
                    "user_expectation": "一部职场喜剧，人物关系持续升级。",
                    "conversation_material": "",
                    "total_episodes": 5,
                    "character_count": 4,
                    "episode_word_count": 600,
                    "execution_scope": "framework_and_script",
                },
            }
        },
    }

    result = PlatformConversationAgent()._execute_tool(
        user_id=7,
        username="tester",
        conversation=conversation,
        name="confirm_script_generation",
        arguments={"confirmed": True},
        user_content="开始",
        attached_document=None,
        selected_knowledge={},
        internal_api_base_url="",
        internal_auth_token="",
    )

    assert result["ok"] is True
    assert result["project"]["generation_chain"] == "script_team_v2"
    assert result["project"]["job_id"] == "npc-agent-test"
    assert conversation["state"]["script_team_job_id"] == "npc-agent-test"
    assert saved_jobs[-1]["execution_target"] == "remote_cnb"


def test_agent_can_pause_remote_script_team_job(monkeypatch) -> None:
    saved_jobs = []
    stopped_builds = []
    job = {
        "job_id": "npc-running-test",
        "user_id": 7,
        "status": "running",
        "status_text": "专业剧本团队正在云端运行",
        "progress": 20,
        "execution_target": "remote_cnb",
        "active_stage": "story_architect",
        "build": {"sn": "cnb-running-test"},
        "request": {"project_title": "远程暂停测试", "episodes": 10},
    }

    class FakeJobs:
        @staticmethod
        def load(job_id, *, user_id):
            return dict(job) if job_id == job["job_id"] and user_id == 7 else None

        @staticmethod
        def save(updated):
            saved_jobs.append(dict(updated))
            return updated

    class FakeClient:
        @staticmethod
        def stop_build(sn):
            stopped_builds.append(sn)
            return {"success": True}

    monkeypatch.setattr(platform_agent_module, "_SCRIPT_TEAM_JOBS", FakeJobs())
    monkeypatch.setattr(platform_agent_module, "_SCRIPT_TEAM_CLIENT", FakeClient())

    result = PlatformConversationAgent()._execute_tool(
        user_id=7,
        username="tester",
        conversation={
            "id": "conversation-pause",
            "task_id": job["job_id"],
            "state": {"script_team_job_id": job["job_id"]},
        },
        name="pause_task",
        arguments={},
        user_content="暂停正在运行的任务",
        attached_document=None,
        selected_knowledge={},
        internal_api_base_url="",
        internal_auth_token="",
    )

    assert result["ok"] is True
    assert stopped_builds == ["cnb-running-test"]
    assert saved_jobs[-1]["status"] == "stage_paused"
    assert saved_jobs[-1]["cancel_requested"] is True
    assert saved_jobs[-1]["remote_continue_after"] is False
