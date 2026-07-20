from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from ..models.inputs import derive_script_title_content
from .agent_conversation_store import agent_conversation_store
from .agent_framework_pipeline import agent_framework_pipeline
from .deepseek_agent import DeepSeekAgentError, deepseek_agent_client, deepseek_agent_status
from .task_manager import task_manager
from .user_knowledge_store import user_knowledge_store
from .workbuddy_doctor import (
    DOCTOR_SKILLS,
    build_doctor_prompt,
    doctor_timeout_seconds,
    list_doctor_skills,
    save_workbuddy_history,
)


AGENT_SYSTEM_PROMPT = """你是“IDEA TO SCRIPT 剧本平台”的总控创作智能体，模型为 DeepSeek V4 Pro。
你的职责是通过对话理解用户意图、补齐缺失字段，并调用白名单工具操作现有剧本平台。

工作原则：
1. 不要假装已经操作平台；凡涉及项目、任务、导出、审查或状态，必须调用工具。
2. 用户要生成剧本时，至少收集：创作要求、总集数、主要角色数量。标题可根据需求自动推断，单集字数默认600。
3. 信息缺失时用自然、简短的问题补齐，一次最多追问3项；能从用户原话可靠推断的字段不要重复询问。
4. 收集齐后先调用 prepare_script_generation，展示执行摘要；只有用户明确回复“确认/开始/执行”后，才能调用 confirm_script_generation。
5. 查询、暂停、继续、普通重试可以直接执行；终止任务必须得到用户明确确认。
6. 用户提到“这个项目、刚才的剧本、继续它”时，优先使用当前会话上下文里的 project_id/task_id。
7. 不输出API Key、服务器路径、内部异常堆栈或FastGPT密钥。
8. 最终回复使用简洁中文，先说结果，再说下一步。不要暴露工具名和JSON参数。
9. 新剧本生成固定走“01-07 框架策划 → 08-12 框架转剧本”链路，不得调用或宣称使用旧剧本生成链路。当前工具未覆盖的精细阶段操作，使用 open_feature 打开对应现有工作台，并明确说明仍保留原功能；不要编造已执行。
10. 剧本医生可直接调用 run_project_doctor，对已完成且存在正文的项目运行指定Skill。
11. 用户选择的智慧库标签是本轮新剧本的创作约束，准备生成方案时必须保留，并由 01-12 阶段分别使用对应提示词。
"""


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_projects",
            "description": "列出当前用户最近的剧本和框架项目。用户问有哪些项目、最近项目时调用。",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "返回数量，默认10"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "select_project",
            "description": "把某个项目设为当前对话操作对象。",
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "integer"}},
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_project_status",
            "description": "查询指定项目或当前项目的任务状态、阶段和进度。",
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_script_generation",
            "description": "在字段齐全后准备一项剧本生成任务，只生成确认卡，不真正启动。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "剧本标题，可根据需求拟定"},
                    "user_expectation": {"type": "string", "description": "完整创作要求，包含题材、受众、风格、核心故事与限制"},
                    "total_episodes": {"type": "integer", "description": "总集数"},
                    "character_count": {"type": "integer", "description": "主要角色数量"},
                    "episode_word_count": {"type": "integer", "description": "单集目标字数，默认600"},
                    "script_format_mode": {"type": "string", "description": "standard或waibao，默认standard"},
                },
                "required": ["title", "user_expectation", "total_episodes", "character_count"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_script_generation",
            "description": "用户明确确认后，启动上一项已经准备好的剧本生成任务。",
            "parameters": {
                "type": "object",
                "properties": {"confirmed": {"type": "boolean"}},
                "required": ["confirmed"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pause_task",
            "description": "暂停当前或指定任务。",
            "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resume_task",
            "description": "继续当前或指定任务。",
            "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retry_task",
            "description": "重试失败的当前或指定任务。",
            "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminate_task",
            "description": "终止当前或指定任务，必须得到用户明确确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "confirmed": {"type": "boolean"},
                },
                "required": ["confirmed"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_project",
            "description": "为已生成完成的项目准备下载文件。",
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_project_doctor",
            "description": "对已生成完成的当前或指定项目运行一个AI剧本医生Skill。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer"},
                    "skill": {
                        "type": "string",
                        "enum": [
                            "overall_dispatcher",
                            "character_continuity",
                            "hook_rhythm",
                            "logic_holes",
                            "character_humanity",
                            "character_resonance",
                        ],
                    },
                    "user_goal": {"type": "string"},
                },
                "required": ["skill"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_feature",
            "description": "打开现有人工工作台功能，适用于精细框架01-07、框架到剧本08-12、剧本医生、资产库或传统工作台。",
            "parameters": {
                "type": "object",
                "properties": {
                    "feature": {
                        "type": "string",
                        "enum": ["workspace", "framework_planner", "framework_to_script", "script_doctor", "assets"],
                    },
                    "project_id": {"type": "integer"},
                },
                "required": ["feature"],
            },
        },
    },
]


def _compact_text(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _snapshot_summary(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    return {
        "project_id": snapshot.get("project_id"),
        "task_id": snapshot.get("task_id"),
        "title": snapshot.get("title") or "未命名项目",
        "status": snapshot.get("status") or "unknown",
        "message": _compact_text(snapshot.get("message"), 320),
        "current_stage": snapshot.get("current_stage"),
        "current_stage_label": snapshot.get("current_stage_label"),
        "progress_percent": snapshot.get("progress_percent") or 0,
        "generated_episodes": snapshot.get("generated_episodes") or 0,
        "total_episodes": snapshot.get("total_episodes") or 0,
        "asset_type": snapshot.get("asset_type"),
        "asset_kind": snapshot.get("asset_kind"),
        "updated_at": snapshot.get("updated_at"),
        "error": _compact_text(snapshot.get("error"), 320),
    }


def _positive_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 500) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _has_explicit_confirmation(value: Any, *, action: str) -> bool:
    text = re.sub(r"[\s，。！？、,.!?：:；;\"'“”‘’]+", "", str(value or "").lower())
    if not text or any(word in text for word in ("不要", "别", "取消", "不确认", "先不", "暂不")):
        return False
    if action == "terminate":
        return any(word in text for word in ("确认终止", "立即终止", "终止任务", "停止并终止"))
    return text in {"确认", "开始", "执行", "可以", "好的", "好", "确认开始"} or any(
        text.startswith(word)
        for word in ("确认开始", "开始执行", "确认执行", "立即开始", "可以开始", "好的开始", "好开始")
    )


class PlatformConversationAgent:
    def status(self) -> dict[str, Any]:
        status = deepseek_agent_status()
        status["tools"] = [item["function"]["name"] for item in TOOL_DEFINITIONS]
        status["doctor_skills"] = list_doctor_skills()
        status["capabilities"] = [
            "对话补齐创作字段",
            "启动剧本生成",
            "项目查询与选择",
            "暂停、继续、重试和终止",
            "剧本医生Skill",
            "智慧库创作风格注入",
            "成品导出",
            "跳转现有精细工作台",
        ]
        return status

    def _conversation_context(self, conversation: dict[str, Any], user_id: int) -> dict[str, Any]:
        context = dict(conversation.get("state") or {})
        project_id = conversation.get("project_id")
        if project_id:
            snapshot = task_manager.get_project_snapshot(int(project_id), user_id=user_id)
            if snapshot:
                context["current_project"] = _snapshot_summary(snapshot)
                context["current_project"]["generation_chain"] = context.get("generation_chain") or ""
                context["current_project"]["pipeline_phase"] = context.get("pipeline_phase") or ""
                context["current_project"]["pipeline_stage"] = context.get("pipeline_stage") or ""
                context["current_project"]["pipeline_message"] = context.get("pipeline_message") or ""
                context["current_project"]["pipeline_error"] = context.get("pipeline_error") or ""
        context["project_id"] = conversation.get("project_id")
        context["task_id"] = conversation.get("task_id")
        return context

    def _resolve_project_id(self, conversation: dict[str, Any], arguments: dict[str, Any]) -> int:
        project_id = arguments.get("project_id") or conversation.get("project_id")
        try:
            return int(project_id)
        except (TypeError, ValueError):
            return 0

    def _resolve_task_id(self, conversation: dict[str, Any], arguments: dict[str, Any]) -> str:
        task_id = str(arguments.get("task_id") or conversation.get("task_id") or "").strip()
        if task_id:
            return task_id
        project_id = self._resolve_project_id(conversation, arguments)
        if project_id:
            snapshot = task_manager.get_project_snapshot(project_id, user_id=int(conversation["user_id"]))
            return str((snapshot or {}).get("task_id") or "")
        return ""

    def _execute_tool(
        self,
        *,
        user_id: int,
        username: str,
        conversation: dict[str, Any],
        name: str,
        arguments: dict[str, Any],
        user_content: str,
        attached_document: dict[str, Any] | None,
        selected_knowledge: dict[str, Any],
        internal_api_base_url: str,
        internal_auth_token: str,
    ) -> dict[str, Any]:
        if name == "list_projects":
            limit = _positive_int(arguments.get("limit"), 10, maximum=30)
            projects = task_manager.list_user_projects(user_id)[:limit]
            return {
                "ok": True,
                "projects": [_snapshot_summary(item) for item in projects],
                "count": len(projects),
                "ui": {"kind": "project_list"},
            }

        if name == "select_project":
            project_id = self._resolve_project_id(conversation, arguments)
            snapshot = task_manager.get_project_snapshot(project_id, user_id=user_id)
            if not snapshot:
                return {"ok": False, "error": "项目不存在或无权访问。"}
            updated = agent_conversation_store.update(
                user_id,
                conversation["id"],
                project_id=project_id,
                task_id=str(snapshot.get("task_id") or ""),
            )
            conversation.update(updated or {})
            return {"ok": True, "project": _snapshot_summary(snapshot), "ui": {"kind": "project"}}

        if name == "get_project_status":
            project_id = self._resolve_project_id(conversation, arguments)
            snapshot = task_manager.get_project_snapshot(project_id, user_id=user_id) if project_id else task_manager.latest_project_snapshot(user_id=user_id)
            if not snapshot:
                return {"ok": False, "error": "还没有找到可查询的项目。"}
            updated = agent_conversation_store.update(
                user_id,
                conversation["id"],
                project_id=int(snapshot.get("project_id") or 0) or None,
                task_id=str(snapshot.get("task_id") or ""),
            )
            conversation.update(updated or {})
            return {"ok": True, "project": _snapshot_summary(snapshot), "ui": {"kind": "progress"}}

        if name == "prepare_script_generation":
            expectation = str(arguments.get("user_expectation") or "").strip()
            total_episodes = _positive_int(arguments.get("total_episodes"), 0, minimum=0, maximum=300)
            character_count = _positive_int(arguments.get("character_count"), 0, minimum=0, maximum=50)
            if len(expectation) < 10:
                return {"ok": False, "missing_fields": ["完整创作要求"], "error": "创作要求还不够完整。"}
            if total_episodes <= 0 or character_count <= 0:
                missing = []
                if total_episodes <= 0:
                    missing.append("总集数")
                if character_count <= 0:
                    missing.append("主要角色数量")
                return {"ok": False, "missing_fields": missing, "error": "仍有必要字段未填写。"}
            title = str(arguments.get("title") or "").strip() or derive_script_title_content(expectation)
            user_material_parts = []
            for message in agent_conversation_store.messages(user_id, conversation["id"], limit=36):
                if message.get("role") != "user":
                    continue
                text = str(message.get("content") or "").strip()
                if text and not _has_explicit_confirmation(text, action="start"):
                    user_material_parts.append(text)
            conversation_material = "\n\n".join(user_material_parts).strip()
            if len(conversation_material) > 10000:
                conversation_material = conversation_material[-10000:]
            payload = {
                "title": title,
                "user_expectation": expectation,
                "conversation_material": conversation_material,
                "total_episodes": total_episodes,
                "character_count": character_count,
                "episode_word_count": _positive_int(arguments.get("episode_word_count"), 600, maximum=5000),
                "script_format_mode": str(arguments.get("script_format_mode") or "standard").strip() or "standard",
                "selected_preference_tag_ids": list(selected_knowledge.get("selected_preference_tag_ids") or []),
                "selected_preference_tags": list(selected_knowledge.get("selected_tags") or []),
                "user_knowledge_tag_prompt": str(selected_knowledge.get("tag_prompt_text") or ""),
                "user_knowledge_stage_prompts": dict(selected_knowledge.get("stage_prompts") or {}),
                "prompt_preferences": {"stage_prompts": dict(selected_knowledge.get("stage_prompts") or {})},
            }
            state = dict(conversation.get("state") or {})
            state["pending_action"] = {
                "type": "start_script_generation",
                "payload": payload,
                "confirmation_required": True,
            }
            updated = agent_conversation_store.update(user_id, conversation["id"], title=title, state=state)
            conversation.update(updated or {})
            return {
                "ok": True,
                "prepared": True,
                "confirmation_required": True,
                "summary": payload,
                "ui": {"kind": "confirmation", "confirm_text": "确认开始", "cancel_text": "取消"},
            }

        if name == "confirm_script_generation":
            if arguments.get("confirmed") is not True:
                state = dict(conversation.get("state") or {})
                state.pop("pending_action", None)
                updated = agent_conversation_store.update(user_id, conversation["id"], state=state)
                conversation.update(updated or {})
                return {"ok": False, "cancelled": True, "message": "用户尚未确认，任务没有启动。"}
            if not _has_explicit_confirmation(user_content, action="start"):
                return {
                    "ok": False,
                    "confirmation_required": True,
                    "error": "当前这句话不是明确的开始确认，任务没有启动。",
                }
            state = dict(conversation.get("state") or {})
            pending = state.get("pending_action")
            if not isinstance(pending, dict) or pending.get("type") != "start_script_generation":
                return {"ok": False, "error": "当前没有等待确认的生成任务，请先描述创作需求。"}
            payload = dict(pending.get("payload") or {})
            snapshot = agent_framework_pipeline.start(
                user_id=user_id,
                conversation_id=conversation["id"],
                payload=payload,
                internal_api_base_url=internal_api_base_url,
                internal_auth_token=internal_auth_token,
            )
            state.pop("pending_action", None)
            state["generation_chain"] = "agent_framework_01_12"
            state["pipeline_phase"] = "framework_01_07"
            state["pipeline_stage"] = "01"
            state["pipeline_message"] = "正在执行 01 原文信息提取"
            state["framework_project_id"] = snapshot.get("project_id")
            state["last_started_project_id"] = snapshot.get("project_id")
            updated = agent_conversation_store.update(
                user_id,
                conversation["id"],
                project_id=int(snapshot.get("project_id") or 0) or None,
                task_id=str(snapshot.get("task_id") or ""),
                state=state,
            )
            conversation.update(updated or {})
            return {
                "ok": True,
                "started": True,
                "project": _snapshot_summary(snapshot),
                "ui": {"kind": "task_started", "url": "/workspace"},
            }

        if name in {"pause_task", "resume_task", "retry_task", "terminate_task"}:
            task_id = self._resolve_task_id(conversation, arguments)
            if not task_id:
                return {"ok": False, "error": "当前对话还没有关联任务，请先选择项目。"}
            if name == "terminate_task" and (
                arguments.get("confirmed") is not True
                or not _has_explicit_confirmation(user_content, action="terminate")
            ):
                return {"ok": False, "confirmation_required": True, "error": "终止任务前需要用户明确说“确认终止”。"}
            operation = {
                "pause_task": task_manager.pause_task,
                "resume_task": task_manager.resume_task,
                "retry_task": task_manager.retry_task,
                "terminate_task": task_manager.terminate_task,
            }[name]
            try:
                snapshot = operation(task_id, user_id=user_id)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "project": _snapshot_summary(snapshot), "ui": {"kind": "progress"}}

        if name == "export_project":
            project_id = self._resolve_project_id(conversation, arguments)
            if not project_id:
                return {"ok": False, "error": "请先选择要导出的项目。"}
            try:
                path = task_manager.save_final_script(project_id, user_id=user_id)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            return {
                "ok": True,
                "project_id": project_id,
                "filename": Path(path).name,
                "download_url": f"/api/projects/{project_id}/download",
                "ui": {"kind": "download"},
            }

        if name == "run_project_doctor":
            attachment = attached_document if isinstance(attached_document, dict) else None
            project_id = self._resolve_project_id(conversation, arguments)
            snapshot = task_manager.get_project_snapshot(project_id, user_id=user_id, public_view=False) if project_id and not attachment else None
            if not snapshot and not attachment:
                return {"ok": False, "error": "请先选择一个存在正文的项目，或上传完整剧本附件。"}
            script_text = str(
                (attachment or {}).get("script_text")
                or (task_manager._best_final_script_text(snapshot) if snapshot else "")
                or ""
            ).strip()
            if len(script_text) < 50:
                return {"ok": False, "error": "这个项目还没有可审查的完整剧本正文。"}
            skill_key = str(arguments.get("skill") or "overall_dispatcher")
            skill = next((item for item in DOCTOR_SKILLS if item.key == skill_key), DOCTOR_SKILLS[0])
            user_goal = str(arguments.get("user_goal") or "").strip()
            title = (
                Path(str((attachment or {}).get("filename") or "")).stem
                if attachment
                else str((snapshot or {}).get("title") or "")
            ) or "未命名剧本"
            prompt = build_doctor_prompt(skill.key, title, script_text, user_goal)
            timeout = doctor_timeout_seconds(len(script_text), skill.key)
            result = deepseek_agent_client.complete_json(
                prompt,
                system_prompt="你是AI剧本医生。必须严格按照提示词只输出一个合法JSON对象。",
                max_tokens=32768,
                timeout_seconds=timeout,
            )
            response_payload = {
                "ok": True,
                "provider": "deepseek",
                "title": title,
                "skill": skill.key,
                "script_length": len(script_text),
                "timeout_seconds": timeout,
                "model": result.get("model"),
                "session_id": result.get("session_id"),
                "usage": result.get("usage"),
                "report": result.get("content") or "",
                "structured_output": result.get("structured_output"),
            }
            history = save_workbuddy_history(
                user_id,
                username=username,
                payload={
                    "title": response_payload["title"],
                    "skill": skill.key,
                    "script_text": script_text,
                    "script_length": len(script_text),
                    "user_goal": user_goal,
                    "source_document_id": str((attachment or {}).get("source_document_id") or ""),
                    "source_filename": str((attachment or {}).get("filename") or ""),
                },
                result=response_payload,
            )
            report = result.get("structured_output") if isinstance(result.get("structured_output"), dict) else {}
            return {
                "ok": True,
                "skill": skill.name,
                "score": report.get("score"),
                "risk_level": report.get("risk_level"),
                "diagnosis": report.get("one_sentence_diagnosis"),
                "history_entry_id": history.get("id") if isinstance(history, dict) else None,
                "can_optimize": bool(attachment and (attachment or {}).get("source_document_id")),
                "source_filename": str((attachment or {}).get("filename") or ""),
                "ui": {"kind": "doctor_report", "url": "/workbuddy-studio"},
            }

        if name == "open_feature":
            feature = str(arguments.get("feature") or "workspace")
            project_id = self._resolve_project_id(conversation, arguments)
            urls = {
                "workspace": "/workspace",
                "framework_planner": "/framework-planner",
                "framework_to_script": "/framework-to-script",
                "script_doctor": "/workbuddy-studio",
                "assets": "/assets/framework",
            }
            url = urls.get(feature, "/workspace")
            if project_id and feature == "framework_planner":
                url += f"?project_id={project_id}"
            elif project_id and feature == "framework_to_script":
                url += f"?framework_asset_id={project_id}"
            return {"ok": True, "feature": feature, "url": url, "ui": {"kind": "navigation"}}

        return {"ok": False, "error": "未知平台操作。"}

    def handle_message(
        self,
        *,
        user_id: int,
        username: str,
        conversation_id: str,
        content: str,
        request_id: str,
        selected_skill: str = "",
        selected_knowledge_tag_ids: list[Any] | None = None,
        attachment_id: str = "",
        internal_api_base_url: str = "",
        internal_auth_token: str = "",
    ) -> dict[str, Any]:
        conversation = agent_conversation_store.get(user_id, conversation_id)
        if not conversation:
            raise ValueError("对话不存在或无权访问。")

        cached_request = agent_conversation_store.begin_request(user_id, conversation_id, request_id)
        if cached_request:
            if cached_request.get("status") == "completed" and isinstance(cached_request.get("response"), dict):
                return cached_request["response"]
            raise ValueError("这条消息正在处理中，请稍候。")

        attached_document = agent_conversation_store.get_attachment(
            user_id,
            conversation_id,
            attachment_id,
        ) if attachment_id else None
        if attachment_id and not attached_document:
            raise ValueError("附件不存在或无权使用，请重新上传。")
        if attached_document and not selected_skill:
            selected_skill = "overall_dispatcher"
        selected_doctor_skill = next(
            (skill for skill in DOCTOR_SKILLS if skill.key == str(selected_skill or "").strip()),
            None,
        )
        selected_knowledge = user_knowledge_store.apply_tags(
            selected_knowledge_tag_ids or [],
            user_id=user_id,
        )
        selected_knowledge_names = [
            str(item.get("name") or item.get("id") or "")
            for item in selected_knowledge.get("selected_tags") or []
            if isinstance(item, dict)
        ]
        message_metadata: dict[str, Any] = {}
        if selected_doctor_skill:
            message_metadata.update(
                {
                    "selected_skill": selected_doctor_skill.key,
                    "selected_skill_name": selected_doctor_skill.name,
                }
            )
        if selected_knowledge_names:
            message_metadata.update(
                {
                    "selected_knowledge_tag_ids": list(selected_knowledge.get("selected_preference_tag_ids") or []),
                    "selected_knowledge_tag_names": selected_knowledge_names,
                }
            )
        if attached_document:
            message_metadata.update(
                {
                    "attachment_id": attached_document.get("id"),
                    "attachment_name": attached_document.get("filename"),
                    "attachment_extension": attached_document.get("extension"),
                }
            )
        user_message = agent_conversation_store.add_message(
            user_id,
            conversation_id,
            role="user",
            content=str(content).strip(),
            metadata=message_metadata,
        )
        if conversation.get("title") == "新的创作对话":
            updated = agent_conversation_store.update(
                user_id,
                conversation_id,
                title=_compact_text(content, 28) or "新的创作对话",
            )
            conversation.update(updated or {})

        history = agent_conversation_store.messages(user_id, conversation_id, limit=36)
        context = self._conversation_context(conversation, user_id)
        model_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": AGENT_SYSTEM_PROMPT
                + "\n\n【当前会话上下文】\n"
                + json.dumps(context, ensure_ascii=False, default=str),
            }
        ]
        for item in history:
            if item.get("role") in {"user", "assistant"}:
                message_content = str(item.get("content") or "")
                if selected_doctor_skill and item.get("id") == user_message.get("id"):
                    message_content += (
                        f"\n\n【已附加剧本医生 Skill】{selected_doctor_skill.name}"
                        f"（skill={selected_doctor_skill.key}）。"
                        "本轮若是审查、诊断或优化请求，必须调用 run_project_doctor 并使用该 skill；"
                        "不要改用其他 Skill。"
                    )
                    if attached_document:
                        message_content += (
                            f"\n【已附加完整剧本文件】{attached_document.get('filename')}，"
                            f"共 {len(str(attached_document.get('script_text') or ''))} 字。"
                            "必须审查这个附件内容，不要改为审查当前项目。"
                        )
                if selected_knowledge_names and item.get("id") == user_message.get("id"):
                    message_content += (
                        "\n\n【已选择智慧库创作偏好】"
                        + "、".join(selected_knowledge_names)
                        + "。准备新剧本生成方案时必须保留这些偏好，确认后由 01-12 各阶段自动注入。"
                    )
                model_messages.append({"role": item["role"], "content": message_content})

        events: list[dict[str, Any]] = []
        usage: dict[str, Any] | None = None
        model = ""
        assistant_content = ""
        try:
            for _ in range(6):
                completion = deepseek_agent_client.complete(
                    model_messages,
                    tools=TOOL_DEFINITIONS,
                    temperature=0.15,
                    max_tokens=4096,
                    timeout_seconds=180,
                )
                usage = completion.get("usage") if isinstance(completion.get("usage"), dict) else usage
                model = str(completion.get("model") or model)
                message = completion.get("message") if isinstance(completion.get("message"), dict) else {}
                tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
                if not tool_calls:
                    assistant_content = str(message.get("content") or "").strip()
                    break

                model_messages.append(message)
                for call in tool_calls:
                    function = call.get("function") if isinstance(call, dict) else {}
                    tool_name = str((function or {}).get("name") or "")
                    raw_arguments = str((function or {}).get("arguments") or "{}")
                    try:
                        arguments = json.loads(raw_arguments)
                        if not isinstance(arguments, dict):
                            arguments = {}
                    except json.JSONDecodeError:
                        arguments = {}
                    action_id = str(call.get("id") or uuid.uuid4().hex)
                    cached_action = agent_conversation_store.cached_action(user_id, action_id)
                    if cached_action is None:
                        try:
                            result = self._execute_tool(
                                user_id=user_id,
                                username=username,
                                conversation=conversation,
                                name=tool_name,
                                arguments=arguments,
                                user_content=content,
                                attached_document=attached_document,
                                selected_knowledge=selected_knowledge,
                                internal_api_base_url=internal_api_base_url,
                                internal_auth_token=internal_auth_token,
                            )
                        except DeepSeekAgentError as exc:
                            result = {"ok": False, "error": str(exc)}
                        except Exception as exc:
                            result = {"ok": False, "error": f"平台操作失败：{exc}"}
                        agent_conversation_store.save_action(
                            user_id,
                            conversation_id,
                            action_id,
                            tool_name,
                            arguments,
                            result,
                        )
                    else:
                        result = cached_action
                    events.append({"tool": tool_name, "result": result})
                    model_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": action_id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        }
                    )
            if not assistant_content:
                assistant_content = "操作已处理。你可以继续告诉我下一步要做什么。"

            assistant_message = agent_conversation_store.add_message(
                user_id,
                conversation_id,
                role="assistant",
                content=assistant_content,
                metadata={"events": events, "model": model, "usage": usage or {}},
            )
            conversation = agent_conversation_store.get(user_id, conversation_id) or conversation
            response = {
                "success": True,
                "conversation": conversation,
                "user_message": user_message,
                "assistant_message": assistant_message,
                "events": events,
                "context": self._conversation_context(conversation, user_id),
                "model": model,
                "usage": usage,
            }
            agent_conversation_store.finish_request(user_id, request_id, response)
            return response
        except Exception as exc:
            response = {
                "success": False,
                "message": str(exc) if isinstance(exc, (ValueError, DeepSeekAgentError)) else "智能体暂时无法完成请求，请稍后重试。",
                "conversation": agent_conversation_store.get(user_id, conversation_id) or conversation,
            }
            agent_conversation_store.finish_request(user_id, request_id, response, status="failed")
            return response


platform_conversation_agent = PlatformConversationAgent()
