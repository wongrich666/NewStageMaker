from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models.inputs import derive_script_title_content
from .agent_conversation_store import agent_conversation_store
from .codebuddy_npc import (
    ACTIVE_STATUSES,
    STAGE_ARTIFACTS,
    STAGE_NAMES,
    STAGE_ORDER,
    CodeBuddyNpcClient,
    CodeBuddyNpcConfig,
    CodeBuddyNpcError,
    CodeBuddyNpcJobStore,
)
from .codebuddy_npc_stage_runner import CodeBuddyNpcStageRunner
from .deepseek_agent import DeepSeekAgentError, deepseek_agent_client, deepseek_agent_status
from .user_knowledge_store import user_knowledge_store
from .workbuddy_doctor import (
    DOCTOR_SKILLS,
    build_doctor_prompt,
    doctor_timeout_seconds,
    list_doctor_skills,
    resolve_doctor_skill,
    save_workbuddy_history,
)


AGENT_SYSTEM_PROMPT = """你是“IDEA TO SCRIPT 剧本平台”的总控“剧本 Agent”。
你的职责是通过对话理解用户意图、补齐缺失字段，并调用白名单工具操作现有剧本平台。

理解用户的方式：
1. 先判断用户真正想达成的结果，再决定是否调用工具。不要依赖固定关键词，也不要要求用户使用平台术语。
2. 用户可以用口语、省略句、错别字、代词或承接上文来表达。例如“把刚才那个接着做”“照这个来”“看看为什么卡住了”“先把故事骨架弄好”，都要结合最近对话、当前项目、待确认动作和任务状态理解。
3. 区分“讨论/咨询”和“执行操作”。用户在询问方案、原因或能力时先直接回答；用户明确要求平台执行时才调用工具。
4. 用户纠正某个条件时，只更新被纠正的条件，保留此前已经明确的题材、受众、集数、角色、风格和限制。
5. 能可靠推断的信息直接采用，并在执行摘要中让用户确认；只有会改变执行范围或成品结果的关键信息无法判断时才追问。
6. 需要追问时调用 ask_choice 生成一个选择卡，一次只问一个最关键问题；选项不能覆盖用户的真实表达时允许用户自定义回答。
7. 不要因为用户没说“生成剧本”“查询状态”等标准词就拒绝理解。把自然表达映射到最接近的工具能力；现有工具确实做不到时，再说明限制并使用 open_feature。

工作原则：
1. 不要假装已经操作平台；凡涉及项目、任务、导出、审查或状态，必须调用工具。
2. 用户要生成剧本时，至少收集：创作要求、总集数、主要角色数量。标题可根据需求自动推断，单集字数默认600。
3. 信息缺失时用自然、简短的问题补齐，一次最多追问3项；能从用户原话可靠推断的字段不要重复询问。
4. 收集齐后先调用 prepare_script_generation，展示执行摘要；只有用户明确回复“确认/开始/执行”后，才能调用 confirm_script_generation。
5. 查询、暂停、继续、普通重试可以直接执行；终止任务必须得到用户明确确认。
6. 用户提到“这个项目、刚才的剧本、继续它”时，优先使用当前会话上下文里的剧本团队任务编号。
7. 不输出API Key、服务器路径或内部异常堆栈。
8. 最终回复使用简洁中文，先说结果，再说下一步。不要暴露工具名和JSON参数。
9. 剧本生成固定走“专业剧本团队”链路：总编剧→故事架构师→人物情感编剧→分集连续性编剧→正文对白编剧→状态记录器→终审与钩子编辑。用户只要求分析框架时，同一团队运行到“分集连续性编剧”即停止；要求完整成品时运行全部七个节点。
10. 剧本医生可直接调用 run_project_doctor，既支持平台中已完成且存在正文的项目，也支持用户本轮独立上传的完整剧本附件。附件存在时优先审查附件，不要求先创建项目或先做框架分析。
11. 用户选择的智慧库标签是本轮新剧本的创作约束，准备生成方案时必须保留，并写入专业剧本团队的创作要求。
12. 用户上传附件仅表示该文件可供本次对话使用，上传本身绝不等同于开始分析、审查、改编、重构或生成，也不得自动调用任何工具。先根据用户本轮明确指令判断用途：只有用户明确要求“分析框架/拆解重构/改编生成/续写”时，才可以把附件作为剧本源材料；只有用户明确要求“审查/质检/剧本医生/优化”时，才可以调用剧本医生。
13. 有附件且用户明确要求框架分析或改编时，仍需收集总集数和主要角色数量；收集齐后调用 prepare_script_generation。该工具只会生成确认卡，用户明确确认后才可启动专业剧本团队。不要把附件全文复述到普通对话中；附件会由后端工作流在确认后读取。
"""


_SCRIPT_TEAM_CONFIG = CodeBuddyNpcConfig.from_env()
_SCRIPT_TEAM_JOBS = CodeBuddyNpcJobStore(_SCRIPT_TEAM_CONFIG)
_SCRIPT_TEAM_CLIENT = CodeBuddyNpcClient(_SCRIPT_TEAM_CONFIG)
_SCRIPT_TEAM_RUNNER = CodeBuddyNpcStageRunner(_SCRIPT_TEAM_JOBS)


def _script_team_status(job: dict[str, Any]) -> str:
    raw = str(job.get("status") or "").strip().lower().replace("-", "_")
    if raw in {"completed", "completed_scope", "completed_with_warnings", "complete", "success", "succeeded"}:
        return "completed"
    if raw in {"failed", "error", "failure"}:
        return "failed"
    if raw in {"stage_paused", "paused", "cancelled", "canceled", "stopped"}:
        return "paused"
    if raw in ACTIVE_STATUSES or raw in {"created", "stage_running", "stage_ready"}:
        return "running" if raw != "stage_ready" else "paused"
    return raw or "pending"


def _script_team_stage(job: dict[str, Any]) -> str:
    active = str(job.get("active_stage") or job.get("remote_stage") or "").strip()
    if active in STAGE_ORDER:
        return active
    recovered = job.get("recovered_files") if isinstance(job.get("recovered_files"), dict) else {}
    for stage in STAGE_ORDER:
        artifact = STAGE_ARTIFACTS[stage]
        value = job.get("final_script") if artifact == "final_script" else recovered.get(artifact)
        if not str(value or "").strip():
            return stage
    return "final_editor"


def _script_team_summary(job: dict[str, Any]) -> dict[str, Any]:
    request_data = job.get("request") if isinstance(job.get("request"), dict) else {}
    stage = _script_team_stage(job)
    status = _script_team_status(job)
    execution_scope = str(job.get("execution_scope") or "framework_and_script")
    return {
        "task_id": str(job.get("job_id") or ""),
        "job_id": str(job.get("job_id") or ""),
        "title": str(request_data.get("project_title") or "未命名剧本"),
        "status": status,
        "message": str(job.get("status_text") or ""),
        "current_stage": stage,
        "current_stage_label": STAGE_NAMES.get(stage, stage),
        "pipeline_stage": STAGE_ORDER.index(stage) + 1,
        "pipeline_phase": "completed" if status == "completed" else "failed" if status == "failed" else status,
        "pipeline_message": str(job.get("status_text") or STAGE_NAMES.get(stage, "")),
        "pipeline_error": str(job.get("error") or ""),
        "progress_percent": int(job.get("progress") or 0),
        "generated_episodes": len(re.findall(r"(?m)^第\s*\d+\s*集", str(job.get("final_script") or ""))),
        "total_episodes": int(request_data.get("episodes") or 0),
        "generation_chain": "script_team_v2",
        "execution_scope": execution_scope,
        "workspace_url": "/new-workflow-test",
        "download_url": (
            f"/api/new-workflow-test/npc/jobs/{job.get('job_id')}/export/docx"
            if str(job.get("final_script") or "").strip()
            else ""
        ),
        "updated_at": job.get("updated_at"),
    }


def _load_script_team_job(user_id: int, job_id: str, *, refresh: bool = True) -> dict[str, Any] | None:
    job = _SCRIPT_TEAM_JOBS.load(job_id, user_id=user_id)
    if not job:
        return None
    remote_active = (
        refresh
        and str(job.get("execution_target") or "") == "remote_cnb"
        and str(job.get("status") or "").strip().lower().replace("-", "_") in ACTIVE_STATUSES
    )
    if remote_active:
        try:
            job = _SCRIPT_TEAM_CLIENT.refresh(job)
            job = _SCRIPT_TEAM_JOBS.save(job)
        except CodeBuddyNpcError as exc:
            job["poll_warning"] = str(exc)
            job = _SCRIPT_TEAM_JOBS.save(job)
    return job


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "ask_choice",
            "description": "只有关键条件无法从用户原话和上下文可靠推断时，向用户展示一个语义化选择卡。一次只问一个问题，不要用它重复询问已知信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "description": "稳定字段名，例如 total_episodes、character_count、execution_scope、target_project",
                    },
                    "question": {"type": "string", "description": "简短自然的问题"},
                    "options": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 5,
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "prompt": {"type": "string", "description": "用户选择后作为下一条消息发送的完整语义"},
                                "description": {"type": "string"},
                            },
                            "required": ["label", "prompt"],
                        },
                    },
                    "custom_prefix": {"type": "string", "description": "用户自定义答案的可选前缀"},
                },
                "required": ["field", "question", "options"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_projects",
            "description": "列出当前用户最近的专业剧本团队任务。用户问有哪些项目、最近项目时调用。",
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
            "description": "把某个专业剧本团队任务设为当前对话操作对象。",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_project_status",
            "description": "查询指定或当前专业剧本团队任务的状态、节点和进度。",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string", "description": "专业剧本团队任务编号"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_script_generation",
            "description": "在字段齐全后准备一项专业剧本团队任务，只生成确认卡，不真正启动。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "剧本标题，可根据需求拟定"},
                    "user_expectation": {"type": "string", "description": "完整创作要求，包含题材、受众、风格、核心故事与限制"},
                    "total_episodes": {"type": "integer", "description": "总集数"},
                    "character_count": {"type": "integer", "description": "主要角色数量"},
                    "episode_word_count": {"type": "integer", "description": "单集目标字数，默认600"},
                    "script_format_mode": {"type": "string", "description": "standard或waibao，默认standard"},
                    "execution_scope": {
                        "type": "string",
                        "enum": ["framework_only", "framework_and_script"],
                        "description": "用户只要求分析/拆解框架时用framework_only；明确要求生成完整剧本时才用framework_and_script",
                    },
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
            "description": "为已完成的专业剧本团队任务准备下载文件。",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_project_doctor",
            "description": "对专业剧本团队成品或本轮独立上传的完整剧本附件运行AI剧本医生Skill。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "skill": {
                        "type": "string",
                        "enum": [
                            "overall_dispatcher",
                            "character_continuity",
                            "hook_rhythm",
                            "logic_holes",
                            "character_humanity",
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
            "description": "打开专业剧本团队、剧本医生或资产库。",
            "parameters": {
                "type": "object",
                "properties": {
                    "feature": {
                        "type": "string",
                        "enum": ["script_team", "script_doctor", "assets"],
                    },
                },
                "required": ["feature"],
            },
        },
    },
]


def _compact_text(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _task_record_identity(record: dict[str, Any]) -> str:
    kind = str(record.get("kind") or "")
    if kind == "script_team":
        return f"script_team:{record.get('job_id') or ''}"
    return f"operation:{record.get('request_id') or ''}"


def _remember_task_record(state: dict[str, Any], record: dict[str, Any]) -> None:
    identity = _task_record_identity(record)
    if identity in {"script_team:", "operation:"}:
        return
    history = [
        dict(item)
        for item in state.get("task_history") or []
        if isinstance(item, dict) and _task_record_identity(item) != identity
    ]
    history.append(dict(record))
    state["task_history"] = history[-16:]


def _positive_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 500) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _agent_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    """Read bounded cost-control settings without making deployment config mandatory."""
    try:
        value = int(str(os.getenv(name) or default).strip())
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _has_explicit_confirmation(value: Any, *, action: str) -> bool:
    text = re.sub(r"[\s，。！？、,.!?：:；;\"'“”‘’]+", "", str(value or "").lower())
    if not text or any(word in text for word in ("不要", "别", "取消", "不确认", "先不", "暂不")):
        return False
    if action == "terminate":
        return any(word in text for word in ("确认终止", "立即终止", "终止任务", "停止并终止"))
    return text in {
        "确认", "开始", "执行", "可以", "好的", "好", "确认开始",
        "就这么办", "按这个来", "照这个来", "按这个方案来", "照这个方案做",
        "没问题开始吧", "可以开始了", "直接开始", "开始吧", "开干",
    } or any(
        text.startswith(word)
        for word in (
            "确认开始", "开始执行", "确认执行", "立即开始", "可以开始",
            "好的开始", "好开始", "就按这个", "就照这个", "按刚才的方案",
            "照刚才的方案", "按上面的方案", "照上面的方案",
        )
    )


def _is_explicit_attachment_doctor_request(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if any(word in text for word in ("框架", "生成剧本", "完整生成", "续写", "改编")):
        return False
    return any(
        word in text
        for word in ("剧本医生", "审查", "检查", "质检", "诊断", "审核", "优化", "看看", "检测")
    )


def _latest_assistant_choice(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidate_messages = messages[:-1] if messages and messages[-1].get("role") == "user" else messages
    for item in reversed(candidate_messages):
        if item.get("role") == "user":
            return None
        if item.get("role") != "assistant":
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        for event in reversed(metadata.get("events") or []):
            result = event.get("result") if isinstance(event, dict) and isinstance(event.get("result"), dict) else {}
            ui = result.get("ui") if isinstance(result.get("ui"), dict) else {}
            if ui.get("kind") == "choice":
                return result
    return None


def _normalize_choice_answer(content: str, messages: list[dict[str, Any]]) -> str:
    """Canonicalize short custom answers using the immediately preceding choice field."""
    value = str(content or "").strip()
    explicit_episode_count = re.fullmatch(r"(?:总集数|集数)\s*[：:]?\s*(\d{1,3})\s*(?:集)?", value)
    if explicit_episode_count:
        return f"总集数：{int(explicit_episode_count.group(1))} 集"
    previous_choice = _latest_assistant_choice(messages)
    if not previous_choice:
        return value
    if previous_choice.get("field") == "episode_count":
        matched = re.fullmatch(r"(?:总集数|集数)?\s*[：:]?\s*(\d{1,3})\s*(?:集)?", value)
        if matched:
            return f"总集数：{int(matched.group(1))} 集"
    return value


def _safe_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Never combine a clarification request with an operation in one turn."""
    choice_calls = [
        call
        for call in tool_calls
        if str(((call.get("function") or {}) if isinstance(call, dict) else {}).get("name") or "")
        == "ask_choice"
    ]
    return choice_calls[:1] if choice_calls else tool_calls


class PlatformConversationAgent:
    def status(self) -> dict[str, Any]:
        status = deepseek_agent_status()
        status["provider"] = "script_agent"
        status["model"] = "剧本 Agent"
        status["missing"] = ["剧本 Agent 配置"] if status.get("missing") else []
        status["tools"] = [item["function"]["name"] for item in TOOL_DEFINITIONS]
        status["doctor_skills"] = list_doctor_skills()
        status["capabilities"] = [
            "对话补齐创作字段",
            "启动专业剧本团队新工作流",
            "七个Agent节点进度与断点续跑",
            "项目查询与选择",
            "暂停、继续、重试和终止",
            "剧本医生Skill",
            "智慧库创作风格注入",
            "成品导出",
            "打开专业剧本团队与剧本医生",
            "Word 剧本按意图执行框架分析或完整生成",
        ]
        return status

    def _conversation_context(self, conversation: dict[str, Any], user_id: int) -> dict[str, Any]:
        context = dict(conversation.get("state") or {})
        script_team_job_id = str(
            context.get("script_team_job_id")
            or (
                conversation.get("task_id")
                if str(conversation.get("task_id") or "").startswith("npc-")
                else ""
            )
            or ""
        ).strip()
        if script_team_job_id:
            script_team_job = _load_script_team_job(user_id, script_team_job_id)
            if script_team_job:
                summary = _script_team_summary(script_team_job)
                context["current_project"] = summary
                context["current_script_team"] = summary
        task_records = [
            dict(item)
            for item in context.get("task_history") or []
            if isinstance(item, dict) and item.get("kind") in {"script_team", "operation"}
        ]
        known_job_ids = {
            str(item.get("job_id") or "")
            for item in task_records
            if item.get("kind") == "script_team" and item.get("job_id")
        }
        for message in agent_conversation_store.messages(user_id, str(conversation.get("id") or ""), limit=100):
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            for event in metadata.get("events") or []:
                result = event.get("result") if isinstance(event, dict) and isinstance(event.get("result"), dict) else {}
                project = result.get("project") if isinstance(result.get("project"), dict) else {}
                historical_job_id = str(project.get("job_id") or project.get("task_id") or "")
                if historical_job_id.startswith("npc-") and historical_job_id not in known_job_ids:
                    task_records.append({"kind": "script_team", "job_id": historical_job_id})
                    known_job_ids.add(historical_job_id)
        if script_team_job_id and script_team_job_id not in known_job_ids:
            task_records.append({"kind": "script_team", "job_id": script_team_job_id})
        history_state = {"task_history": task_records}
        for operation_key in ("last_operation", "active_operation"):
            operation = context.get(operation_key) if isinstance(context.get(operation_key), dict) else {}
            if operation:
                _remember_task_record(history_state, {"kind": "operation", **operation})
        task_records = list(history_state.get("task_history") or [])
        resolved_history: list[dict[str, Any]] = []
        for record in task_records:
            if record.get("kind") == "script_team" and record.get("job_id"):
                script_job = _load_script_team_job(user_id, str(record.get("job_id") or ""))
                if script_job:
                    resolved_history.append(
                        {
                            "identity": f"script_team:{record.get('job_id')}",
                            "kind": "script_team",
                            "project": _script_team_summary(script_job),
                        }
                    )
            elif record.get("request_id"):
                operation = {key: value for key, value in record.items() if key != "kind"}
                resolved_history.append(
                    {
                        "identity": f"operation:{record.get('request_id')}",
                        "kind": "operation",
                        "operation": operation,
                    }
                )
        deduplicated: dict[str, dict[str, Any]] = {}
        for record in resolved_history:
            deduplicated[str(record.get("identity") or "")] = record
        context["task_history"] = list(deduplicated.values())[-16:]
        context["task_id"] = conversation.get("task_id")
        context["script_team_job_id"] = script_team_job_id
        return context

    def remember_operation(self, state: dict[str, Any], operation: dict[str, Any]) -> None:
        _remember_task_record(state, {"kind": "operation", **dict(operation)})

    @staticmethod
    def _resolve_script_team_job_id(
        conversation: dict[str, Any],
        arguments: dict[str, Any],
    ) -> str:
        state = conversation.get("state") if isinstance(conversation.get("state"), dict) else {}
        candidates = (
            arguments.get("job_id"),
            state.get("script_team_job_id"),
            conversation.get("task_id"),
        )
        for candidate in candidates:
            value = str(candidate or "").strip()
            if value.startswith("npc-"):
                return value
        return ""

    @staticmethod
    def _next_script_team_stage(job: dict[str, Any]) -> str:
        recovered = job.get("recovered_files") if isinstance(job.get("recovered_files"), dict) else {}
        for stage in STAGE_ORDER:
            artifact = STAGE_ARTIFACTS[stage]
            value = job.get("final_script") if artifact == "final_script" else recovered.get(artifact)
            if not str(value or "").strip():
                return stage
        return "final_editor"

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
        if name == "ask_choice":
            raw_options = arguments.get("options") if isinstance(arguments.get("options"), list) else []
            options: list[dict[str, str]] = []
            for item in raw_options[:5]:
                if not isinstance(item, dict):
                    continue
                label = _compact_text(item.get("label"), 40)
                prompt = _compact_text(item.get("prompt"), 300)
                if not label or not prompt:
                    continue
                options.append(
                    {
                        "label": label,
                        "prompt": prompt,
                        "description": _compact_text(item.get("description"), 100),
                    }
                )
            if len(options) < 2:
                return {"ok": False, "error": "追问选项不足，请改用简短自然语言询问用户。"}
            return {
                "ok": True,
                "field": _compact_text(arguments.get("field"), 60) or "clarification",
                "question": _compact_text(arguments.get("question"), 160) or "请确认一个关键选项。",
                "options": options,
                "step": 1,
                "total": 1,
                "allow_custom": True,
                "custom_prefix": _compact_text(arguments.get("custom_prefix"), 80),
                "awaiting_user_input": True,
                "ui": {"kind": "choice"},
            }

        if name == "list_projects":
            limit = _positive_int(arguments.get("limit"), 10, maximum=30)
            projects = [
                _script_team_summary(item)
                for item in _SCRIPT_TEAM_JOBS.list(user_id=user_id)[:limit]
            ]
            return {
                "ok": True,
                "projects": projects,
                "count": len(projects),
                "ui": {"kind": "project_list"},
            }

        if name == "select_project":
            script_job_id = self._resolve_script_team_job_id(conversation, arguments)
            if script_job_id:
                job = _load_script_team_job(user_id, script_job_id)
                if not job:
                    return {"ok": False, "error": "专业剧本团队任务不存在或无权访问。"}
                state = dict(conversation.get("state") or {})
                state["script_team_job_id"] = script_job_id
                state["generation_chain"] = "script_team_v2"
                _remember_task_record(state, {"kind": "script_team", "job_id": script_job_id})
                updated = agent_conversation_store.update(
                    user_id,
                    conversation["id"],
                    project_id=None,
                    task_id=script_job_id,
                    state=state,
                )
                conversation.update(updated or {})
                return {"ok": True, "project": _script_team_summary(job), "ui": {"kind": "project"}}
            return {"ok": False, "error": "请提供专业剧本团队任务编号。"}

        if name == "get_project_status":
            script_job_id = self._resolve_script_team_job_id(conversation, arguments)
            if script_job_id:
                job = _load_script_team_job(user_id, script_job_id)
                if not job:
                    return {"ok": False, "error": "还没有找到可查询的专业剧本团队任务。"}
                state = dict(conversation.get("state") or {})
                state["script_team_job_id"] = script_job_id
                state["generation_chain"] = "script_team_v2"
                _remember_task_record(state, {"kind": "script_team", "job_id": script_job_id})
                updated = agent_conversation_store.update(
                    user_id,
                    conversation["id"],
                    project_id=None,
                    task_id=script_job_id,
                    state=state,
                )
                conversation.update(updated or {})
                return {"ok": True, "project": _script_team_summary(job), "ui": {"kind": "progress"}}
            return {"ok": False, "error": "还没有找到可查询的专业剧本团队任务。"}

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
            attachment_text = str((attached_document or {}).get("script_text") or "").strip()
            attachment_name = str((attached_document or {}).get("filename") or "").strip()
            title = (
                str(arguments.get("title") or "").strip()
                or (Path(attachment_name).stem if attachment_name else "")
                or derive_script_title_content(expectation)
            )
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
                "execution_scope": (
                    "framework_and_script"
                    if str(arguments.get("execution_scope") or "").strip() == "framework_and_script"
                    else "framework_only" if attachment_text else "framework_and_script"
                ),
                "selected_preference_tag_ids": list(selected_knowledge.get("selected_preference_tag_ids") or []),
                "selected_preference_tags": list(selected_knowledge.get("selected_tags") or []),
                "user_knowledge_tag_prompt": str(selected_knowledge.get("tag_prompt_text") or ""),
            }
            framework_only = payload["execution_scope"] == "framework_only"
            estimated_batches = max(1, (total_episodes + 4) // 5)
            payload["workflow_engine"] = "script_team_v2"
            payload["cost_estimate"] = {
                "paid_call_range": (
                    "4 次"
                    if framework_only
                    else f"{5 + estimated_batches * 2}–{7 + estimated_batches * 2} 次"
                ),
                "execution_scope_label": (
                    "专业剧本团队前四节点"
                    if framework_only
                    else "专业剧本团队七节点完整生成"
                ),
                "estimated_output_chars": 0 if framework_only else total_episodes * payload["episode_word_count"],
                "notice": "失败重试或追加优化可能增加模型消耗。",
            }
            if attachment_text:
                # The full document is consumed only by the confirmed backend pipeline,
                # rather than becoming repeated paid conversation context.
                payload.update(
                    {
                        "source_attachment_id": str((attached_document or {}).get("id") or ""),
                        "source_document_id": str((attached_document or {}).get("source_document_id") or ""),
                        "source_filename": attachment_name,
                        "source_char_count": len(attachment_text),
                        "source_mode": "document_adaptation",
                    }
                )
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
            source_attachment_id = str(payload.get("source_attachment_id") or "").strip()
            if source_attachment_id:
                source_document = agent_conversation_store.get_attachment(
                    user_id,
                    conversation["id"],
                    source_attachment_id,
                )
                if not source_document:
                    return {"ok": False, "error": "原始附件已经不可用，请重新上传后再确认。"}
                payload["source_text"] = str(source_document.get("script_text") or "")
                payload["source_document_id"] = str(source_document.get("source_document_id") or "")
                payload["source_filename"] = str(source_document.get("filename") or payload.get("source_filename") or "")
            framework_only = str(payload.get("execution_scope") or "") == "framework_only"
            direction_parts = [
                str(payload.get("user_expectation") or "").strip(),
                str(payload.get("conversation_material") or "").strip(),
                str(payload.get("user_knowledge_tag_prompt") or "").strip(),
            ]
            job = _SCRIPT_TEAM_JOBS.create(
                user_id=user_id,
                request_payload={
                    "project_title": str(payload.get("title") or "未命名剧本"),
                    "mode": "改编" if source_attachment_id else "原创",
                    "production_type": "AI剧集",
                    "target_market": "按用户要求",
                    "genre": str(payload.get("user_expectation") or "")[:100],
                    "episodes": int(payload.get("total_episodes") or 1),
                    "episode_word_count": int(payload.get("episode_word_count") or 600),
                    "source_text": str(payload.get("source_text") or ""),
                    "adaptation_direction": "\n\n".join(item for item in direction_parts if item),
                    "execution_mode": "step" if framework_only else "auto",
                },
            )
            job["execution_scope"] = "framework_only" if framework_only else "framework_and_script"
            job = _SCRIPT_TEAM_JOBS.save(job)
            if framework_only:
                job = _SCRIPT_TEAM_RUNNER.start(
                    job_id=str(job["job_id"]),
                    user_id=user_id,
                    stage="showrunner",
                    continue_after=True,
                    stop_after_stage="episode_continuity",
                )
                job["status_text"] = "专业剧本团队正在生成故事框架"
                job = _SCRIPT_TEAM_JOBS.save(job)
            else:
                try:
                    trigger_result = _SCRIPT_TEAM_CLIENT.trigger(job)
                    job["build"] = {
                        "sn": trigger_result.get("sn"),
                        "build_log_url": trigger_result.get("buildLogUrl"),
                        "message": trigger_result.get("message"),
                    }
                    job["status"] = "running"
                    job["status_text"] = "专业剧本团队正在云端运行"
                    job["execution_target"] = "remote_cnb"
                    job["remote_kind"] = "full"
                    job["progress"] = 3
                    job = _SCRIPT_TEAM_JOBS.save(job)
                except CodeBuddyNpcError as remote_exc:
                    job = _SCRIPT_TEAM_RUNNER.start(
                        job_id=str(job["job_id"]),
                        user_id=user_id,
                        stage="showrunner",
                        continue_after=True,
                    )
                    job["fallback_reason"] = str(remote_exc)
                    job["status_text"] = "云端暂不可用，已切换本地剧本团队继续运行"
                    job = _SCRIPT_TEAM_JOBS.save(job)
            state.pop("pending_action", None)
            state["generation_chain"] = "script_team_v2"
            state["pipeline_phase"] = "running"
            state["pipeline_stage"] = "1"
            state["pipeline_message"] = str(job.get("status_text") or "专业剧本团队正在启动")
            state["script_team_job_id"] = str(job["job_id"])
            state["last_started_job_id"] = str(job["job_id"])
            _remember_task_record(
                state,
                {
                    "kind": "script_team",
                    "job_id": str(job["job_id"]),
                    "generation_chain": state["generation_chain"],
                    "pipeline_phase": state["pipeline_phase"],
                    "pipeline_stage": state["pipeline_stage"],
                    "pipeline_message": state["pipeline_message"],
                },
            )
            updated = agent_conversation_store.update(
                user_id,
                conversation["id"],
                project_id=None,
                task_id=str(job["job_id"]),
                state=state,
            )
            conversation.update(updated or {})
            return {
                "ok": True,
                "started": True,
                "project": _script_team_summary(job),
                "ui": {"kind": "task_started", "url": "/new-workflow-test"},
            }

        if name in {"pause_task", "resume_task", "retry_task", "terminate_task"}:
            script_job_id = self._resolve_script_team_job_id(conversation, arguments)
            if script_job_id:
                job = _load_script_team_job(user_id, script_job_id, refresh=False)
                if not job:
                    return {"ok": False, "error": "专业剧本团队任务不存在或无权访问。"}
                if name == "terminate_task" and (
                    arguments.get("confirmed") is not True
                    or not _has_explicit_confirmation(user_content, action="terminate")
                ):
                    return {"ok": False, "confirmation_required": True, "error": "终止任务前需要用户明确说“确认终止”。"}
                if name in {"pause_task", "terminate_task"}:
                    if str(job.get("execution_target") or "") == "remote_cnb":
                        build_sn = str((job.get("build") or {}).get("sn") or "")
                        try:
                            _SCRIPT_TEAM_CLIENT.stop_build(build_sn)
                        except CodeBuddyNpcError as exc:
                            return {
                                "ok": False,
                                "error": f"CNB远程任务停止失败：{exc}",
                            }
                        job["cancel_requested"] = True
                        job["remote_continue_after"] = False
                        job["active_stage"] = ""
                        job["paused_build_sn"] = build_sn
                        job["paused_at"] = datetime.now(timezone.utc).isoformat()
                        if name == "terminate_task":
                            job["status"] = "stopped"
                            job["status_text"] = "专业剧本团队任务已终止，已有中间产物保留"
                        else:
                            job["status"] = "stage_paused"
                            job["status_text"] = "远程CNB构建已暂停，已有进度与中间产物保留"
                        job = _SCRIPT_TEAM_JOBS.save(job)
                        return {
                            "ok": True,
                            "project": _script_team_summary(job),
                            "ui": {"kind": "progress"},
                        }
                    job = _SCRIPT_TEAM_RUNNER.request_cancel(job_id=script_job_id, user_id=user_id)
                    if name == "terminate_task":
                        job["status"] = "stopped"
                        job["status_text"] = "专业剧本团队任务已终止，已有中间产物保留"
                        job = _SCRIPT_TEAM_JOBS.save(job)
                    return {"ok": True, "project": _script_team_summary(job), "ui": {"kind": "progress"}}
                if _SCRIPT_TEAM_RUNNER.is_running(script_job_id):
                    return {"ok": False, "error": "当前节点仍在运行，请等待完成后再继续或重试。"}
                start_stage = self._next_script_team_stage(job)
                framework_only = str(job.get("execution_scope") or "") == "framework_only"
                if framework_only and STAGE_ORDER.index(start_stage) > STAGE_ORDER.index("episode_continuity"):
                    return {
                        "ok": True,
                        "project": _script_team_summary(job),
                        "message": "框架任务已经完成到分集连续性节点。",
                        "ui": {"kind": "progress"},
                    }
                job = _SCRIPT_TEAM_RUNNER.start(
                    job_id=script_job_id,
                    user_id=user_id,
                    stage=start_stage,
                    continue_after=True,
                    stop_after_stage="episode_continuity" if framework_only else "",
                )
                return {"ok": True, "project": _script_team_summary(job), "ui": {"kind": "progress"}}
            return {"ok": False, "error": "当前对话还没有关联专业剧本团队任务。"}

        if name == "export_project":
            script_job_id = self._resolve_script_team_job_id(conversation, arguments)
            if script_job_id:
                job = _load_script_team_job(user_id, script_job_id)
                if not job or not str(job.get("final_script") or "").strip():
                    return {"ok": False, "error": "专业剧本团队尚未生成可下载的最终剧本。"}
                return {
                    "ok": True,
                    "job_id": script_job_id,
                    "filename": f"{(job.get('request') or {}).get('project_title') or '完整剧本'}.docx",
                    "download_url": f"/api/new-workflow-test/npc/jobs/{script_job_id}/export/docx",
                    "ui": {"kind": "download"},
                }
            return {"ok": False, "error": "请先选择要导出的专业剧本团队任务。"}

        if name == "run_project_doctor":
            attachment = attached_document if isinstance(attached_document, dict) else None
            script_job_id = self._resolve_script_team_job_id(conversation, arguments)
            script_job = _load_script_team_job(user_id, script_job_id) if script_job_id and not attachment else None
            if not script_job and not attachment:
                return {"ok": False, "error": "请先选择一个已有成品的专业剧本团队任务，或上传完整剧本附件。"}
            script_text = str(
                (attachment or {}).get("script_text")
                or ((script_job or {}).get("final_script") if script_job else "")
                or ""
            ).strip()
            if len(script_text) < 50:
                return {"ok": False, "error": "这个项目还没有可审查的完整剧本正文。"}
            skill_key = str(arguments.get("skill") or "overall_dispatcher")
            skill = resolve_doctor_skill(skill_key, default=DOCTOR_SKILLS[0])
            user_goal = str(arguments.get("user_goal") or "").strip()
            title = (
                Path(str((attachment or {}).get("filename") or "")).stem
                if attachment
                else str(((script_job or {}).get("request") or {}).get("project_title") or "")
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
                "provider": "script_agent",
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
                    "job_id": script_job_id,
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
            feature = str(arguments.get("feature") or "script_team")
            urls = {
                "script_team": "/new-workflow-test",
                "script_doctor": "/workbuddy-studio",
                "assets": "/assets/framework",
            }
            url = urls.get(feature, "/new-workflow-test")
            return {"ok": True, "feature": feature, "url": url, "ui": {"kind": "navigation"}}

        return {"ok": False, "error": "未知平台操作。"}

    def _run_attachment_doctor_job(
        self,
        *,
        user_id: int,
        username: str,
        conversation_id: str,
        request_id: str,
        content: str,
        skill_key: str,
        skill_name: str,
        attached_document: dict[str, Any],
        selected_knowledge: dict[str, Any],
        internal_api_base_url: str,
        internal_auth_token: str,
    ) -> None:
        conversation = agent_conversation_store.get(user_id, conversation_id) or {}
        state = dict(conversation.get("state") or {})
        active = dict(state.get("active_operation") or {})
        if str(active.get("request_id") or "") == request_id:
            active.update(
                {
                    "status": "running",
                    "progress_percent": 45,
                    "stage": "ai_review",
                    "message": f"剧本 Agent 正在执行{skill_name}",
                }
            )
            state["active_operation"] = active
            self.remember_operation(state, active)
            agent_conversation_store.update(user_id, conversation_id, state=state)

        try:
            result = self._execute_tool(
                user_id=user_id,
                username=username,
                conversation=conversation,
                name="run_project_doctor",
                arguments={"skill": skill_key, "user_goal": content},
                user_content=content,
                attached_document=attached_document,
                selected_knowledge=selected_knowledge,
                internal_api_base_url=internal_api_base_url,
                internal_auth_token=internal_auth_token,
            )
            succeeded = bool(result.get("ok"))
            message = (
                f"{skill_name}已完成，报告已经保存。"
                if succeeded
                else str(result.get("error") or "剧本医生没有完成本次审查。")
            )
        except Exception as exc:
            succeeded = False
            result = {"ok": False, "error": str(exc) if isinstance(exc, DeepSeekAgentError) else "剧本医生运行失败，请稍后重试。"}
            message = str(result["error"])

        conversation = agent_conversation_store.get(user_id, conversation_id) or conversation
        state = dict(conversation.get("state") or {})
        current = dict(state.get("active_operation") or {})
        if str(current.get("request_id") or "") == request_id:
            state.pop("active_operation", None)
        finished_at = datetime.now(timezone.utc).astimezone().isoformat()
        state["last_operation"] = {
            **active,
            "request_id": request_id,
            "type": "script_doctor",
            "status": "completed" if succeeded else "failed",
            "progress_percent": 100 if succeeded else int(active.get("progress_percent") or 45),
            "stage": "completed" if succeeded else "failed",
            "message": message,
            "finished_at": finished_at,
            "history_entry_id": result.get("history_entry_id"),
            "can_optimize": bool(result.get("can_optimize")),
        }
        self.remember_operation(state, state["last_operation"])
        agent_conversation_store.update(user_id, conversation_id, state=state)
        event = {"tool": "run_project_doctor", "result": result}
        if succeeded:
            assistant_content = (
                f"已完成《{Path(str(attached_document.get('filename') or '上传剧本')).stem}》的"
                f"{skill_name}。完整报告已经保存"
                + ("，可以直接一键优化并下载 Word。" if result.get("can_optimize") else "。")
            )
        else:
            assistant_content = f"这次剧本医生任务没有完成：{message}"
        agent_conversation_store.add_message(
            user_id,
            conversation_id,
            role="assistant",
            content=assistant_content,
            metadata={
                "events": [event],
                "background_operation_completed": succeeded,
                "background_operation_failed": not succeeded,
                "request_id": request_id,
            },
        )

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
        selected_doctor_skill = resolve_doctor_skill(str(selected_skill or "").strip())
        selected_knowledge = user_knowledge_store.apply_tags(
            selected_knowledge_tag_ids or [],
            user_id=user_id,
        )
        selected_knowledge_names = [
            str(item.get("name") or item.get("id") or "")
            for item in selected_knowledge.get("selected_tags") or []
            if isinstance(item, dict)
        ]
        recent_messages = agent_conversation_store.messages(user_id, conversation_id, limit=6)
        content = _normalize_choice_answer(content, recent_messages)
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

        # A selected Skill plus an explicit review instruction is already a
        # complete user intent. Route it directly to the uploaded document so
        # the orchestration model cannot incorrectly demand a platform project,
        # and avoid paying for an extra intent-classification round trip.
        if (
            attached_document
            and selected_doctor_skill
            and _is_explicit_attachment_doctor_request(content)
        ):
            started_at = datetime.now(timezone.utc).astimezone().isoformat()
            state = dict(conversation.get("state") or {})
            state["active_operation"] = {
                "request_id": request_id,
                "type": "script_doctor",
                "status": "running",
                "progress_percent": 20,
                "stage": "preparing",
                "message": "正在读取 Word 并准备剧本医生审查",
                "filename": str(attached_document.get("filename") or "上传剧本"),
                "char_count": len(str(attached_document.get("script_text") or "")),
                "skill_key": selected_doctor_skill.key,
                "skill_name": selected_doctor_skill.name,
                "started_at": started_at,
            }
            self.remember_operation(state, state["active_operation"])
            updated = agent_conversation_store.update(user_id, conversation_id, state=state)
            conversation.update(updated or {})
            assistant_message = agent_conversation_store.add_message(
                user_id,
                conversation_id,
                role="assistant",
                content=(
                    f"已开始对《{Path(str(attached_document.get('filename') or '上传剧本')).stem}》运行"
                    f"{selected_doctor_skill.name}。任务已转入后台，刷新或离开页面不会中止。"
                ),
                metadata={
                    "background_operation_started": True,
                    "request_id": request_id,
                    "operation_type": "script_doctor",
                },
            )
            thread = threading.Thread(
                target=self._run_attachment_doctor_job,
                kwargs={
                    "user_id": user_id,
                    "username": username,
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "content": str(content).strip(),
                    "skill_key": selected_doctor_skill.key,
                    "skill_name": selected_doctor_skill.name,
                    "attached_document": dict(attached_document),
                    "selected_knowledge": dict(selected_knowledge),
                    "internal_api_base_url": internal_api_base_url,
                    "internal_auth_token": internal_auth_token,
                },
                daemon=False,
                name=f"agent-doctor-{request_id[:8]}",
            )
            thread.start()
            response = {
                "success": True,
                "accepted": True,
                "conversation": conversation,
                "user_message": user_message,
                "assistant_message": assistant_message,
                "events": [],
                "context": self._conversation_context(conversation, user_id),
            }
            agent_conversation_store.finish_request(user_id, request_id, response)
            return response

        # The Agent orchestrates work; bounded history prevents repeatedly paying
        # for an ever-growing transcript on every turn.
        history_limit = _agent_int_env("AGENT_CONVERSATION_HISTORY_MESSAGES", 24, minimum=6, maximum=48)
        history_char_limit = _agent_int_env("AGENT_CONVERSATION_HISTORY_CHARS", 18000, minimum=4000, maximum=50000)
        raw_history = agent_conversation_store.messages(user_id, conversation_id, limit=history_limit)
        history: list[dict[str, Any]] = []
        remaining_history_chars = history_char_limit
        for item in reversed(raw_history):
            if remaining_history_chars <= 0:
                break
            copied = dict(item)
            copied["content"] = str(item.get("content") or "")[-remaining_history_chars:]
            remaining_history_chars -= len(copied["content"])
            history.insert(0, copied)
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
                        + "。准备新剧本生成方案时必须保留这些偏好，确认后写入专业剧本团队的创作合同与后续节点。"
                    )
                if attached_document and item.get("id") == user_message.get("id") and not selected_doctor_skill:
                    message_content += (
                        f"\n\n【本轮可用附件】{attached_document.get('filename')}，"
                        f"类型 {attached_document.get('extension')}，共 "
                        f"{len(str(attached_document.get('script_text') or ''))} 字。"
                        "附件目前只已保存，尚未分析。必须根据用户本轮明确用途决定下一步；"
                        "若用途不明确，只询问希望做框架分析、完整生成、续写还是剧本医生审查，不得调用工具。"
                    )
                model_messages.append({"role": item["role"], "content": message_content})

        events: list[dict[str, Any]] = []
        usage: dict[str, Any] | None = None
        model = ""
        assistant_content = ""
        try:
            tool_rounds = _agent_int_env("AGENT_TOOL_ROUNDS", 3, minimum=1, maximum=6)
            response_max_tokens = _agent_int_env("AGENT_RESPONSE_MAX_TOKENS", 1400, minimum=400, maximum=4096)
            for _ in range(tool_rounds):
                completion = deepseek_agent_client.complete(
                    model_messages,
                    tools=TOOL_DEFINITIONS,
                    temperature=0.15,
                    max_tokens=response_max_tokens,
                    timeout_seconds=180,
                )
                usage = completion.get("usage") if isinstance(completion.get("usage"), dict) else usage
                model = str(completion.get("model") or model)
                message = completion.get("message") if isinstance(completion.get("message"), dict) else {}
                tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
                if not tool_calls:
                    assistant_content = str(message.get("content") or "").strip()
                    break

                tool_calls = _safe_tool_calls(tool_calls)

                model_messages.append(message)
                awaiting_user_input = False
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
                    if result.get("awaiting_user_input"):
                        assistant_content = str(result.get("question") or "请先确认一个关键选项。")
                        awaiting_user_input = True
                        break
                if awaiting_user_input:
                    break
            if not assistant_content:
                assistant_content = "操作已处理。你可以继续告诉我下一步要做什么。"

            assistant_message = agent_conversation_store.add_message(
                user_id,
                conversation_id,
                role="assistant",
                content=assistant_content,
                metadata={"events": events, "model": "剧本 Agent", "usage": usage or {}},
            )
            conversation = agent_conversation_store.get(user_id, conversation_id) or conversation
            response = {
                "success": True,
                "conversation": conversation,
                "user_message": user_message,
                "assistant_message": assistant_message,
                "events": events,
                "context": self._conversation_context(conversation, user_id),
                "model": "剧本 Agent",
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
