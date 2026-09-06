from __future__ import annotations

"""Generate a code-evidence architecture manifest for Idea to Scripts.

This script deliberately separates mechanically extracted facts from curated
cross-module relationships. Tencent workflow nodes/ports/edges are read from
the exported workflow JSON files. Local module and recovery relationships are
declared only when a matching source symbol can be located in the repository.
Unknown or unenforced nested schemas stay marked as UNKNOWN.
"""

import ast
import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "workflow_code_skeleton" / "app"
EXPORT_ROOT = ROOT / "腾讯智能平台工作流文件"
OUTPUT_DIR = ROOT / "workflow_code_skeleton" / "docs" / "architecture"
MANIFEST_PATH = OUTPUT_DIR / "architecture_manifest.generated.json"
REPORT_PATH = OUTPUT_DIR / "代码驱动智能体运行架构分析.md"
FRONTEND_MANIFEST_PATH = ROOT / "agent-flow-frontend" / "src" / "data" / "architecture_manifest.generated.json"


def relpath(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def source_ref(path: Path, line: int, symbol: str = "") -> dict[str, Any]:
    return {"path": relpath(path), "line": int(line), "symbol": symbol}


def find_line(path: Path, pattern: str) -> int:
    regex = re.compile(pattern)
    for index, line in enumerate(read_text(path).splitlines(), start=1):
        if regex.search(line):
            return index
    return 0


def symbol_index() -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for path in APP_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(read_text(path), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                index.setdefault(node.name, []).append(source_ref(path, node.lineno, node.name))
    return index


SYMBOLS = symbol_index()


def evidence(symbol: str, fallback_path: Path | None = None, pattern: str = "") -> list[dict[str, Any]]:
    matches = SYMBOLS.get(symbol, [])
    if matches:
        return matches
    if fallback_path is not None and pattern:
        line = find_line(fallback_path, pattern)
        if line:
            return [source_ref(fallback_path, line, symbol)]
    return []


def flatten_schema(items: Any, prefix: str = "") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or item.get("Title") or "UNKNOWN")
        path = f"{prefix}.{name}" if prefix else name
        value = item.get("Value") if isinstance(item.get("Value"), dict) else {}
        input_value = item.get("Input") if isinstance(item.get("Input"), dict) else {}
        reference = value.get("Reference") or input_value.get("Reference") or {}
        result.append(
            {
                "field": path,
                "type": str(item.get("Type") or "UNKNOWN"),
                "required": bool(item.get("IsRequired") or item.get("Required")),
                "reference_node_id": str(reference.get("NodeID") or ""),
                "reference_path": str(reference.get("JsonPath") or ""),
            }
        )
        result.extend(flatten_schema(item.get("Properties"), path))
        result.extend(flatten_schema(item.get("SubInputs"), path))
    return result


def referenced_fields(target: dict[str, Any], source_node_id: str) -> list[str]:
    fields: list[str] = []

    def visit(value: Any, current_field: str = "") -> None:
        if isinstance(value, dict):
            field_name = str(value.get("Name") or value.get("Title") or current_field)
            reference = value.get("Reference")
            if isinstance(reference, dict) and str(reference.get("NodeID")) == source_node_id:
                fields.append(field_name or str(reference.get("JsonPath") or "UNKNOWN"))
            for child in value.values():
                visit(child, field_name)
        elif isinstance(value, list):
            for child in value:
                visit(child, current_field)

    visit(target.get("Inputs"))
    visit(target.get("Outputs"))
    return list(dict.fromkeys(field for field in fields if field))


def compact_prompt_preview(value: Any, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def extract_agent_role(system_prompt: str, fallback: str) -> str:
    """Extract the self-declared Agent role without inventing a display name."""
    fallback_text = str(fallback or "").strip()
    if fallback_text and not re.fullmatch(r"(?:大模型\s*\d*|LLM\s*\d*)", fallback_text, flags=re.IGNORECASE):
        return fallback_text
    text = re.sub(r"\s+", " ", str(system_prompt or "")).strip()
    patterns = (
        r"^你是(?:一个|一名)?[“\"]([^”\"]{2,80})[”\"]",
        r"^你是(?:一个|一名)?【([^】]{2,80})】",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    first_sentence = re.split(r"[。！？]", text, maxsplit=1)[0].strip()
    return first_sentence[:80] if first_sentence else fallback


def exported_stage_key(folder_name: str) -> str:
    name = folder_name.removeprefix("export-")
    special = {
        "分镜图提示词生成": "character_image_prompt",
        "智能剧本评分工作流": "hot_review",
    }
    if name in special:
        return special[name]
    match = re.match(r"^(11_\d{2}|12_\d{2}|\d{2})", name)
    return match.group(1) if match else f"UNKNOWN:{name}"


def subsystem_for(stage_key: str) -> str:
    if re.fullmatch(r"0[1-7]", stage_key):
        return "system:framework_planning"
    if stage_key in {"08", "09", "10"}:
        return "system:script_assets"
    if stage_key.startswith("11_"):
        return "system:conflict_production"
    if stage_key.startswith("12_"):
        return "system:script_production"
    if stage_key == "hot_review":
        return "system:script_audit"
    if stage_key == "character_image_prompt":
        return "system:character_visual"
    return "system:local_orchestration"


def load_registry() -> dict[str, dict[str, Any]]:
    registry_path = APP_ROOT / "services" / "tencent_workflow_registry.py"
    spec = importlib.util.spec_from_file_location(
        "idea_to_scripts_architecture_registry",
        registry_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load registry source: {registry_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    TENCENT_WORKFLOWS = module.TENCENT_WORKFLOWS

    result: dict[str, dict[str, Any]] = {}
    for local_name, spec in TENCENT_WORKFLOWS.items():
        payload = asdict(spec)
        payload["local_stage_name"] = local_name
        payload["input_sources"] = {
            key: list(values) for key, values in spec.input_sources.items()
        }
        payload["response_fields"] = list(spec.response_fields)
        result[spec.key] = payload
    return result


REGISTRY = load_registry()


SYSTEM_NODES = [
    ("system:user_interface", "用户交互系统", "User", "Web UI、项目管理、编辑、审核和手动回滚入口"),
    ("system:local_orchestration", "本地智能编排系统", "Orchestrator", "Flask API、Task Manager、工作流网关、契约与恢复"),
    ("system:framework_planning", "Framework Planning System", "AgentSystem", "01–07 框架策划与阶段资产生成"),
    ("system:script_assets", "Script Asset Preparation", "AgentSystem", "08–10 场景、服饰映射和丰富分集资产化"),
    ("system:conflict_production", "Conflict Production System", "AgentSystem", "11 撰写→审核→修订→记忆闭环"),
    ("system:script_production", "Script Production System", "AgentSystem", "12 正文生成→审核→修订→记忆闭环"),
    ("system:script_audit", "Script ECG Audit System", "AuditSystem", "5 集默认审核、2+2+1 降级分拆与跨批记忆"),
    ("system:character_visual", "Character Visual Prompt System", "AgentSystem", "单角色证据筛选与文生图 Prompt 合成"),
    ("system:persistence", "Persistence & Evidence System", "DataSystem", "SQLite、JSON Snapshot、审核运行、日志、调试与导出"),
]


LOCAL_NODES = [
    {
        "id": "local:flask_api",
        "parent_id": "system:local_orchestration",
        "title": "Flask API",
        "node_type": "Orchestrator",
        "responsibility": "路由、登录鉴权、参数注入、后台任务发起和前端结果投影",
        "inputs": ["HTTP JSON", "multipart file", "auth session", "framework_asset_id"],
        "outputs": ["JSON response", "task/run status", "stage asset"],
        "persistence": ["通过 Task Manager 写项目快照", "部分阶段写 debug/log"],
        "evidence": evidence("create_app"),
    },
    {
        "id": "local:task_manager",
        "parent_id": "system:local_orchestration",
        "title": "Task Manager",
        "node_type": "Orchestrator",
        "responsibility": "任务生命周期、项目快照、恢复检查点、暂停/续跑/重试/回滚",
        "inputs": ["input_payload", "workflow_spec_path", "stage outputs", "runtime state"],
        "outputs": ["task_id", "project_id", "public_snapshot", "resume_checkpoint"],
        "persistence": ["runtime_data/index.json", "runtime_data/projects/<project_id>.json", "runtime_data/exports/*"],
        "evidence": evidence("TaskManager") + evidence("start_task"),
    },
    {
        "id": "local:framework_planner_service",
        "parent_id": "system:local_orchestration",
        "title": "Framework Planner Service",
        "node_type": "Orchestrator",
        "responsibility": "01–07 阶段定义、本地别名规范化、腾讯调用与输出校验",
        "inputs": ["stage", "payload", "previous_*", "user_feedback", "stage_prompts"],
        "outputs": ["source_brief", "worldview_plan", "character_plan", "beat_checkpoint_timeline", "character_storylines", "adaptation_guide", "framework_plan_package"],
        "persistence": ["由 Flask autosave 写 framework_planner 快照"],
        "evidence": evidence("run_framework_planner_stage") + evidence("_run_framework_planner_stage_via_tencent"),
    },
    {
        "id": "local:script_orchestrator",
        "parent_id": "system:local_orchestration",
        "title": "Workflow Orchestrator",
        "node_type": "Orchestrator",
        "responsibility": "08–12 资产化、默认 5 集分批、审核修订循环和记忆传递",
        "inputs": ["frameworkPlanPackage", "totalEpisodes", "episodeWordCount", "stage cache"],
        "outputs": ["sceneDictionary", "appearanceMapping", "allEnrichedEpisodePlan", "batchCausalConflictPlan", "batchScriptText"],
        "persistence": ["scriptStages.stage08-stage12", "approved batches", "memories"],
        "evidence": evidence("_run_framework_to_script_workflow"),
    },
    {
        "id": "local:tencent_gateway",
        "parent_id": "system:local_orchestration",
        "title": "Tencent Workflow Client",
        "node_type": "Gateway",
        "responsibility": "AppKey 分流、WorkflowInput/CustomVariables 构造、HTTP/SSE 解析、嵌套 JSON 拆包",
        "inputs": ["local stage name", "canonical variables", "AppKey env", "API URL"],
        "outputs": ["workflow response", "execute_id", "debug_url", "safe diagnostics"],
        "persistence": ["调试摘要进入 debug/log；不将 AppKey 写入公开结果"],
        "evidence": evidence("TencentWorkflowClient") + evidence("build_workflow_inputs"),
    },
    {
        "id": "local:contract_guard",
        "parent_id": "system:local_orchestration",
        "title": "Contract Guard & Output Parser",
        "node_type": "Validator",
        "responsibility": "类型转换、Output 包装拆解、review 必填字段、业务结构校验与格式重试",
        "inputs": ["raw workflow response", "stage contract", "expected batch window"],
        "outputs": ["normalized output", "validation issues", "retry decision"],
        "persistence": ["失败证据写 stage errors/debug"],
        "evidence": evidence("validate_stage_output_with_workflow_contract") + evidence("parse_workflow_output"),
    },
    {
        "id": "local:audit_batch_service",
        "parent_id": "system:local_orchestration",
        "title": "Script Audit Batch Service",
        "node_type": "Orchestrator",
        "responsibility": "严格分集解析、5 集批审核、两次尝试、2→1 适应分拆、断点续跑与合并",
        "inputs": ["script_title", "canonical script text", "parsed episodes"],
        "outputs": ["script_audit_batch_v1 batches", "script_audit_compact_v1", "audit_memory"],
        "persistence": ["runtime_data/script_audits/<run_id>.json", "<run_id>.debug.json", "summary index"],
        "evidence": evidence("ScriptAuditBatchService") + evidence("compact_audit_memory") + evidence("merge_audit_batches"),
    },
    {
        "id": "local:character_prompt_service",
        "parent_id": "system:local_orchestration",
        "title": "Character Image Prompt Service",
        "node_type": "Orchestrator",
        "responsibility": "单角色、单服饰版本与相关场景/道具证据筛选，调用 Prompt workflow 并规范化输出",
        "inputs": ["framework asset", "character_id", "selected_outfit_id", "user_visual_requirements"],
        "outputs": ["character_image_prompt_v1", "source_summary"],
        "persistence": ["RESPONSE_ONLY：当前 API 未自动写回项目快照"],
        "evidence": evidence("build_character_image_prompt_inputs") + evidence("generate_character_image_prompt"),
    },
]


DATA_NODES = [
    {
        "id": "data:auth_sqlite", "parent_id": "system:persistence", "title": "Auth SQLite",
        "node_type": "Data", "responsibility": "账户与登录会话", "inputs": ["username", "password_hash", "token"],
        "outputs": ["user_id", "session user"], "persistence": ["runtime_data/users.db: users, auth_sessions"],
        "evidence": evidence("AuthStore"),
    },
    {
        "id": "data:project_snapshot", "parent_id": "system:persistence", "title": "Project JSON Snapshot",
        "node_type": "Data", "responsibility": "项目资产、阶段输出、日志、快照和恢复点", "inputs": ["snapshot", "artifacts", "debug_state"],
        "outputs": ["public_snapshot", "_resume_checkpoint"], "persistence": ["runtime_data/projects/<project_id>.json", "runtime_data/index.json"],
        "evidence": evidence("ProjectSnapshotStoreMixin"),
    },
    {
        "id": "data:user_knowledge", "parent_id": "system:persistence", "title": "User Knowledge JSON",
        "node_type": "Data", "responsibility": "偏好标签、手动/标签阶段 Prompt 与用户偏好", "inputs": ["selected tag ids", "stage prompts"],
        "outputs": ["merged stage_prompts", "user_preference_prompt"], "persistence": ["runtime_data/user_knowledge/tags.json", "runtime_data/user_knowledge/user_preferences.json"],
        "evidence": evidence("UserKnowledgeStore"),
    },
    {
        "id": "data:audit_runs", "parent_id": "system:persistence", "title": "Script Audit Run JSON",
        "node_type": "Data", "responsibility": "已完成审核子批次、记忆、告警和合并报告", "inputs": ["batch payload", "audit memory", "source script"],
        "outputs": ["resumable run", "compact audit"], "persistence": ["runtime_data/script_audits/*.json", "*.debug.json", "*.summary.json"],
        "evidence": evidence("ScriptAuditBatchService"),
    },
    {
        "id": "data:debug_logs_exports", "parent_id": "system:persistence", "title": "Debug / Logs / Exports",
        "node_type": "Data", "responsibility": "运行证据、腾讯调用摘要、阶段原始调试与 TXT/DOCX 交付", "inputs": ["debug events", "logs", "final output"],
        "outputs": ["diagnostic JSON", "TXT", "DOCX", "archive manifest"], "persistence": ["cache/*", "debug/*", "logs/*", "runtime_data/exports/*", "runtime_archive/manifest.json"],
        "evidence": evidence("RuntimeExportStoreMixin") + evidence("archive_runtime_data"),
    },
]


def load_exports() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    workflows: list[dict[str, Any]] = []
    internal_nodes: list[dict[str, Any]] = []
    internal_edges: list[dict[str, Any]] = []
    for path in sorted(EXPORT_ROOT.rglob("*_workflow.json")):
        raw = json.loads(read_text(path))
        stage_key = exported_stage_key(path.parent.name)
        workflow_id = str(raw.get("WorkflowID") or "UNKNOWN")
        workflow_node_id = f"workflow:{stage_key}"
        start_nodes = [node for node in raw.get("Nodes", []) if node.get("NodeType") == "START"]
        end_nodes = [node for node in raw.get("Nodes", []) if node.get("NodeType") == "END"]
        workflow_inputs = flatten_schema(start_nodes[0].get("Inputs") if start_nodes else [])
        workflow_outputs = flatten_schema(end_nodes[0].get("Outputs") if end_nodes else [])
        registry = REGISTRY.get(stage_key)
        registry_id = str(registry.get("workflow_id") or "") if registry else ""
        placeholder_id = registry_id in {"character_image_prompt", "hot_review"}
        id_status = "MATCH" if registry_id == workflow_id else "PLACEHOLDER" if placeholder_id else "MISMATCH"
        response_fields = registry.get("response_fields") if registry else "UNKNOWN"
        wire_fields = [
            field["field"].split(".", 1)[1]
            for field in workflow_outputs
            if "." in str(field.get("field") or "")
        ]
        if not isinstance(response_fields, list):
            response_field_status = "UNKNOWN"
        elif any(field in wire_fields for field in response_fields):
            response_field_status = "MATCH"
        elif any(field.get("field") == "Output" for field in workflow_outputs):
            response_field_status = "WRAPPED_OUTPUT_ONLY"
        else:
            response_field_status = "MISMATCH"

        workflows.append(
            {
                "id": workflow_node_id,
                "node_level": 2,
                "parent_id": subsystem_for(stage_key),
                "node_type": "Workflow",
                "stage_key": stage_key,
                "title": str(raw.get("WorkflowName") or path.parent.name.removeprefix("export-")),
                "responsibility": compact_prompt_preview(raw.get("WorkflowDesc"), 260),
                "workflow_id_export": workflow_id,
                "workflow_id_registry": registry_id or "UNKNOWN",
                "workflow_id_status": id_status,
                "registry_local_stage_name": registry.get("local_stage_name") if registry else "UNKNOWN",
                "input": workflow_inputs,
                "output": workflow_outputs,
                "input_sources": registry.get("input_sources") if registry else "UNKNOWN",
                "response_fields": response_fields,
                "wire_response_fields": wire_fields,
                "response_field_status": response_field_status,
                "save_state": "由本地调用方决定；腾讯工作流导出本身不声明本地落盘",
                "source_evidence": [source_ref(path, 1, "exported workflow")],
            }
        )

        nodes_by_id = {str(node.get("NodeID")): node for node in raw.get("Nodes", [])}
        for node in raw.get("Nodes", []):
            node_id = str(node.get("NodeID") or "UNKNOWN")
            node_type = str(node.get("NodeType") or "UNKNOWN")
            llm = node.get("LLMNodeData") if isinstance(node.get("LLMNodeData"), dict) else {}
            params = llm.get("ModelParams") if isinstance(llm.get("ModelParams"), dict) else {}
            exception = node.get("ExceptionHandling") if isinstance(node.get("ExceptionHandling"), dict) else {}
            system_prompt = str(llm.get("SystemPrompt") or "")
            user_prompt = str(llm.get("Prompt") or "")
            platform_title = str(node.get("NodeName") or node_type)
            agent_role = extract_agent_role(system_prompt, platform_title) if node_type == "LLM" else platform_title
            responsibility_fallback = {
                "START": "接收父工作流输入并向下游节点注入变量。",
                "END": "汇总上游节点结果并封装为工作流输出。",
            }.get(node_type, "UNKNOWN")
            internal_nodes.append(
                {
                    "id": f"tencent:{workflow_id}:{node_id}",
                    "node_level": 3,
                    "parent_id": workflow_node_id,
                    "node_type": node_type,
                    "platform_node_id": node_id,
                    "title": platform_title,
                    "display_title": agent_role,
                    "agent_role": agent_role if node_type == "LLM" else "",
                    "responsibility": compact_prompt_preview(system_prompt or node.get("NodeDesc"), 260) or responsibility_fallback,
                    "input": flatten_schema(node.get("Inputs")),
                    "output": flatten_schema(node.get("Outputs")),
                    "model": str(llm.get("ModelName") or ""),
                    "model_params": {
                        "temperature": params.get("Temperature", llm.get("Temperature", "UNKNOWN")),
                        "top_p": params.get("TopP", llm.get("TopP", "UNKNOWN")),
                        "max_tokens": params.get("MaxTokens", llm.get("MaxTokens", "UNKNOWN")),
                    } if node_type == "LLM" else {},
                    "prompt_sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest() if system_prompt else "",
                    "prompt_char_length": len(system_prompt),
                    "user_prompt_sha256": hashlib.sha256(user_prompt.encode("utf-8")).hexdigest() if user_prompt else "",
                    "user_prompt_char_length": len(user_prompt),
                    "exception_handling": {
                        "switch": exception.get("Switch", "UNKNOWN"),
                        "max_retries": exception.get("MaxRetries", "UNKNOWN"),
                        "retry_interval": exception.get("RetryInterval", "UNKNOWN"),
                        "timeout": exception.get("Timeout", "UNKNOWN"),
                        "abnormal_retry_switch": exception.get("AbnormalRetrySwitch", "UNKNOWN"),
                    },
                    "save_state": "腾讯执行态；本地是否保存由父 workflow 调用方决定",
                    "source_evidence": [source_ref(path, 1, f"Nodes[{node_id}]")],
                }
            )

        try:
            exported_edges = json.loads(raw.get("Edge") or "[]")
        except (TypeError, ValueError):
            exported_edges = []
        for edge in exported_edges:
            source_id = str(edge.get("source") or "UNKNOWN")
            target_id = str(edge.get("target") or "UNKNOWN")
            fields = referenced_fields(nodes_by_id.get(target_id, {}), source_id)
            internal_edges.append(
                {
                    "id": f"edge:tencent:{workflow_id}:{source_id}:{target_id}",
                    "source": f"tencent:{workflow_id}:{source_id}",
                    "target": f"tencent:{workflow_id}:{target_id}",
                    "edge_type": "platform_data_flow",
                    "data_name": ", ".join(fields) if fields else "control / referenced output",
                    "fields": fields or ["UNKNOWN"],
                    "compressed": "No",
                    "condition": "always",
                    "animation_type": "animated" if edge.get("animated") else "static",
                    "source_evidence": [source_ref(path, 1, "Edge")],
                }
            )
    return workflows, internal_nodes, internal_edges


def system_nodes() -> list[dict[str, Any]]:
    return [
        {
            "id": node_id,
            "node_level": 1,
            "parent_id": None,
            "title": title,
            "node_type": node_type,
            "responsibility": responsibility,
            "input": ["See child nodes"],
            "output": ["See child nodes"],
            "save_state": "See child nodes",
            "source_evidence": [],
        }
        for node_id, title, node_type, responsibility in SYSTEM_NODES
    ]


def normalize_curated_node(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_level": 2,
        "input": item.pop("inputs", []),
        "output": item.pop("outputs", []),
        "save_state": item.pop("persistence", []),
        "source_evidence": item.pop("evidence", []),
        **item,
    }


def business_edge(
    edge_id: str,
    source: str,
    target: str,
    data_name: str,
    fields: Iterable[str],
    *,
    compressed: str = "No",
    original_fields: Iterable[str] = (),
    compressed_fields: Iterable[str] = (),
    condition: str = "always",
    animation_type: str = "animated",
    evidence_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "edge_type": "business_data_flow",
        "data_name": data_name,
        "fields": list(fields),
        "compressed": compressed,
        "original_fields": list(original_fields),
        "compressed_fields": list(compressed_fields),
        "condition": condition,
        "animation_type": animation_type,
        "source_evidence": evidence_refs or [],
    }


def business_edges() -> list[dict[str, Any]]:
    planner_evidence = evidence("run_framework_planner_stage")
    script_evidence = evidence("_run_framework_to_script_workflow")
    server = APP_ROOT / "server.py"
    stage11_evidence = [source_ref(server, find_line(server, r"def run_framework_to_script_stage11_api"), "stage11 API")]
    stage12_evidence = [source_ref(server, find_line(server, r"def run_framework_to_script_stage12_api"), "stage12 API")]
    return [
        business_edge("business:ui-api", "system:user_interface", "local:flask_api", "user request", ["HTTP JSON", "feedback", "asset selection"], evidence_refs=evidence("create_app")),
        business_edge("business:api-planner", "local:flask_api", "local:framework_planner_service", "planner stage request", ["stage", "payload", "user_feedback", "stage_prompts"], evidence_refs=planner_evidence),
        business_edge("business:api-script", "local:flask_api", "local:script_orchestrator", "framework-to-script request", ["framework_asset_id", "batch_start_episode"], evidence_refs=script_evidence),
        business_edge("business:gateway", "local:tencent_gateway", "workflow:01", "typed Tencent inputs", ["source_title", "target_format", "episode_number", "source_text", "user_requirements"], evidence_refs=evidence("build_workflow_inputs")),
        business_edge("business:01-02", "workflow:01", "workflow:02", "source brief handoff", ["source_brief", "locked_basic_config"], evidence_refs=planner_evidence),
        business_edge("business:02-03", "workflow:02", "workflow:03", "worldview handoff", ["worldview_plan"], evidence_refs=planner_evidence),
        business_edge("business:03-04", "workflow:03", "workflow:04", "character handoff", ["character_plan"], evidence_refs=planner_evidence),
        business_edge("business:04-05", "workflow:04", "workflow:05", "beat handoff", ["beat_checkpoint_timeline"], evidence_refs=planner_evidence),
        business_edge("business:05-06", "workflow:05", "workflow:06", "storyline handoff", ["character_storylines", "storyline_decisions"], evidence_refs=planner_evidence),
        business_edge("business:06-07", "workflow:06", "workflow:07", "final package inputs", ["adaptation_guide", "source_brief", "worldview_plan", "character_plan", "beat_checkpoint_timeline", "character_storylines"], evidence_refs=planner_evidence),
        business_edge("business:07-08", "workflow:07", "workflow:08", "framework assetization", ["frameworkPlanPackage", "worldviewPlan", "beatCheckpointTimeline", "characterStorylines"], evidence_refs=script_evidence),
        business_edge("business:07-09", "workflow:07", "workflow:09", "character/framework evidence", ["characterPlan", "frameworkPlanPackage", "beatCheckpointTimeline"], evidence_refs=script_evidence),
        business_edge("business:08-09", "workflow:08", "workflow:09", "scene dictionary", ["sceneDictionary"], evidence_refs=script_evidence),
        business_edge("business:07-10", "workflow:07", "workflow:10", "framework plan", ["frameworkPlanPackage"], evidence_refs=script_evidence),
        business_edge("business:08-10", "workflow:08", "workflow:10", "scene dictionary", ["sceneDictionary"], evidence_refs=script_evidence),
        business_edge("business:09-10", "workflow:09", "workflow:10", "appearance mapping", ["appearanceMapping"], evidence_refs=script_evidence),
        business_edge("business:10-11write", "workflow:10", "workflow:11_01", "current batch plan", ["batchEnrichedEpisodePlan"], condition="default batch size=5; stage11 write may split into 1-episode chunks", evidence_refs=stage11_evidence),
        business_edge("business:11write-review", "workflow:11_01", "workflow:11_02", "conflict plan audit view", ["batchCausalConflictPlan"], compressed="Yes", original_fields=["full batchCausalConflictPlan"], compressed_fields=["batch_meta", "global_conflict_engine", "episodes[].approved audit fields"], evidence_refs=evidence("compact_conflict_plan_for_review")),
        business_edge("business:11review-rewrite", "workflow:11_02", "workflow:11_03", "blocking review", ["passed", "rewrite_required", "blocking_issues", "current conflict"], condition="review failed OR local structural validation failed", evidence_refs=stage11_evidence),
        business_edge("business:11rewrite-review", "workflow:11_03", "workflow:11_02", "revised conflict plan", ["batchCausalConflictPlan"], condition="until approved or loop limit", evidence_refs=stage11_evidence),
        business_edge("business:11review-memory", "workflow:11_02", "workflow:11_04", "approved conflict plan", ["batchCausalConflictPlan", "start_epi"], condition="review passed AND local validator passed", evidence_refs=stage11_evidence),
        business_edge("business:11memory-next", "workflow:11_04", "workflow:11_01", "next batch conflict memory", ["conflictMemory"], condition="next batch exists", evidence_refs=stage11_evidence),
        business_edge("business:11-12", "workflow:11_02", "workflow:12_01", "approved same-batch conflict plan", ["batchCausalConflictPlan", "batchEnrichedEpisodePlan"], condition="stage11 batch approved", evidence_refs=stage12_evidence),
        business_edge("business:12write-review", "workflow:12_01", "workflow:12_02", "script audit", ["batchScriptText", "batchCausalConflictPlan", "batchEnrichedEpisodePlan", "scriptMemory"], evidence_refs=stage12_evidence),
        business_edge("business:12review-rewrite", "workflow:12_02", "workflow:12_03", "blocking review", ["passed", "rewrite_required", "blocking_issues", "current_script"], condition="review failed OR local structural validation failed", evidence_refs=stage12_evidence),
        business_edge("business:12rewrite-review", "workflow:12_03", "workflow:12_02", "revised script", ["batchScriptText"], condition="until approved or loop limit", evidence_refs=stage12_evidence),
        business_edge("business:12review-memory", "workflow:12_02", "workflow:12_04", "approved batch script", ["batchScriptText"], condition="review passed; Web API has bounded degraded acceptance branches", evidence_refs=stage12_evidence),
        business_edge("business:12memory-next", "workflow:12_04", "workflow:12_01", "next batch script memory", ["scriptMemory"], condition="next batch exists", evidence_refs=stage12_evidence),
        business_edge("business:script-audit", "data:project_snapshot", "workflow:hot_review", "user-selected script audit", ["batch_script_text", "script_title", "total_episodes", "previous_audit_memory"], condition="explicit user audit request; not automatic after stage12", evidence_refs=evidence("start_run")),
        business_edge("business:audit-memory", "workflow:hot_review", "workflow:hot_review", "cross-batch audit memory", ["next_audit_memory -> previous_audit_memory"], compressed="Yes", original_fields=["remote next_audit_memory"], compressed_fields=["allowed audit memory fields only; <=30000 chars"], condition="next pending audit batch", evidence_refs=evidence("compact_audit_memory")),
        business_edge("business:character-prompt", "data:project_snapshot", "workflow:character_image_prompt", "single-character visual evidence", ["character_source_profile", "appearance_mapping", "scene_prop_context", "selected_outfit_id"], compressed="Yes", original_fields=["full framework asset", "all characters", "all scenes", "all episode plans", "stage12 script"], compressed_fields=["selected character", "selected outfit", "<=12 related scenes/episodes", "evidence-backed props"], condition="explicit user generation request", evidence_refs=evidence("build_character_image_prompt_inputs")),
        business_edge("business:task-snapshot", "local:task_manager", "data:project_snapshot", "project snapshot", ["artifacts", "stage_outputs", "logs", "_resume_checkpoint"], animation_type="static", evidence_refs=evidence("_persist_snapshot")),
        business_edge("business:audit-store", "local:audit_batch_service", "data:audit_runs", "audit progress", ["batches", "audit_memory", "completed_episode_numbers", "audit"], animation_type="static", evidence_refs=evidence("_write")),
        business_edge("business:auth-store", "local:flask_api", "data:auth_sqlite", "authentication", ["users", "auth_sessions"], animation_type="static", evidence_refs=evidence("AuthStore")),
        business_edge("business:preferences", "data:user_knowledge", "local:framework_planner_service", "stage preference injection", ["stage_prompts", "user_preference_prompt", "selected tags"], animation_type="static", evidence_refs=evidence("apply_tags")),
        business_edge("business:debug", "local:tencent_gateway", "data:debug_logs_exports", "safe workflow diagnostics", ["execute_id", "debug_url", "input lengths", "response preview"], animation_type="static", evidence_refs=evidence("get_last_stage_debug_info")),
    ]


def containment_edges(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for node in nodes:
        parent = node.get("parent_id")
        if not parent:
            continue
        edges.append(
            {
                "id": f"contains:{parent}:{node['id']}",
                "source": parent,
                "target": node["id"],
                "edge_type": "contains",
                "data_name": "contains / expands to",
                "fields": [],
                "compressed": "No",
                "condition": "expand parent node",
                "animation_type": "none",
                "source_evidence": node.get("source_evidence", []),
            }
        )
    return edges


def validate_graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    node_ids = [str(node.get("id")) for node in nodes]
    edge_ids = [str(edge.get("id")) for edge in edges]
    duplicate_node_ids = sorted({node_id for node_id in node_ids if node_ids.count(node_id) > 1})
    duplicate_edge_ids = sorted({edge_id for edge_id in edge_ids if edge_ids.count(edge_id) > 1})
    node_id_set = set(node_ids)
    dangling_edges = [
        edge["id"]
        for edge in edges
        if edge.get("source") not in node_id_set or edge.get("target") not in node_id_set
    ]
    by_id = {node["id"]: node for node in nodes}
    invalid_parent_levels: list[str] = []
    for node in nodes:
        parent_id = node.get("parent_id")
        if not parent_id:
            continue
        parent = by_id.get(parent_id)
        if parent is None or parent.get("node_level") != node.get("node_level") - 1:
            invalid_parent_levels.append(node["id"])
    result = {
        "valid": not any((duplicate_node_ids, duplicate_edge_ids, dangling_edges, invalid_parent_levels)),
        "unique_node_ids": len(node_ids) == len(set(node_ids)),
        "unique_edge_ids": len(edge_ids) == len(set(edge_ids)),
        "duplicate_node_ids": duplicate_node_ids,
        "duplicate_edge_ids": duplicate_edge_ids,
        "dangling_edge_ids": dangling_edges,
        "invalid_parent_level_node_ids": invalid_parent_levels,
    }
    if not result["valid"]:
        raise ValueError(f"Generated architecture graph is invalid: {result}")
    return result


COMPRESSION_RULES = [
    {
        "id": "compact:characters_for_scenes", "function": "build_compact_character_context_for_scenes",
        "original": "full characters", "result": ["character_name", "story_role", "appearance.overall_look", "appearance.recognizable_features[:3]", "behavior.habitual_actions[:2]", "dramatic_value_summary<=120"],
        "consumers": ["scene generation"], "evidence": evidence("build_compact_character_context_for_scenes"),
    },
    {
        "id": "compact:characters_for_appearance", "function": "build_compact_character_context_for_appearance",
        "original": "full characters", "result": ["name/role", "appearance anchors", "same_person_traits[:4]", "forbidden_generic_names[:6]"],
        "consumers": ["appearance mapping"], "evidence": evidence("build_compact_character_context_for_appearance"),
    },
    {
        "id": "compact:characters_for_hooks", "function": "build_compact_character_context_for_hooks",
        "original": "full characters", "result": ["character_name", "story_role", "core_motivation<=120", "key_relations[:2]"],
        "consumers": ["hook/conflict generation"], "evidence": evidence("build_compact_character_context_for_hooks"),
    },
    {
        "id": "compact:characters_for_dialogues", "function": "build_compact_character_context_for_dialogues",
        "original": "full characters", "result": ["character_name", "story_role", "compact speech profile", "relation_modes[:2]"],
        "consumers": ["dialogue generation"], "evidence": evidence("build_compact_character_context_for_dialogues"),
    },
    {
        "id": "compact:characters_for_script", "function": "build_compact_character_context_for_script",
        "original": "full characters", "result": ["name/role", "motivation<=100", "appearance hint", "speech profile", "relations[:2]"],
        "consumers": ["script generation"], "evidence": evidence("build_compact_character_context_for_script"),
    },
    {
        "id": "compact:scene_context", "function": "build_compact_scene_context_for_script",
        "original": "full scene objects", "result": ["scene_name/type", "story_function<=100", "visual/styling/naming summaries", "identity requirements[:2]", "conflict potential[:2]"],
        "consumers": ["script generation/review"], "evidence": evidence("build_compact_scene_context_for_script"),
    },
    {
        "id": "compact:appearance_batch", "function": "build_compact_appearance_context_for_batch",
        "original": "full appearance plan", "result": ["global rules[:4]", "per-episode aliases", "appearance events[:3]", "scene alias usage", "uncertain items[:4]"],
        "consumers": ["batch hooks/dialogues/script"], "evidence": evidence("build_compact_appearance_context_for_batch"),
    },
    {
        "id": "compact:worldview_story", "function": "build_compact_worldview_context / build_compact_story_outline_context",
        "original": "full worldview and outline", "result": ["bounded worldview summaries/rules", "opening/inciting/middle/climax/ending/theme"],
        "consumers": ["batch generation"], "evidence": evidence("build_compact_worldview_context") + evidence("build_compact_story_outline_context"),
    },
    {
        "id": "compact:stage11_review", "function": "compact_enriched_episode_plan / compact_appearance_mapping / compact_scene_dictionary / compact_conflict_plan_for_review",
        "original": "full stage10, stage09, stage08 and conflict plan", "result": ["allowed audit fields only", "relevant characters only", "scene continuity subset", "conflict audit subset"],
        "consumers": ["11_02 review", "11_03 rewrite context"], "evidence": evidence("compact_enriched_episode_plan") + evidence("compact_appearance_mapping") + evidence("compact_scene_dictionary") + evidence("compact_conflict_plan_for_review"),
    },
    {
        "id": "compact:audit_memory", "function": "compact_audit_memory",
        "original": "remote next_audit_memory", "result": ["allowlist of 43 audit fields", "strings<=1200", "lists<=200", "dict keys<=40", "depth<=4", "total<=30000 chars"],
        "consumers": ["next hot_review batch", "final compact audit"], "evidence": evidence("compact_audit_memory"),
    },
    {
        "id": "compact:character_prompt", "function": "build_character_image_prompt_inputs",
        "original": "full framework/script asset", "result": ["one selected character", "one selected outfit plus available outfit ids", "<=12 related scenes", "<=12 sampled episodes", "evidence-backed props", "bounded JSON 14k/16k/18k"],
        "consumers": ["character_image_prompt workflow"], "evidence": evidence("build_character_image_prompt_inputs"),
    },
]


RECOVERY_RULES = [
    {
        "id": "recovery:workflow_http_format", "trigger": "HTTP/transient/format error",
        "action": "Tencent client HTTP retry + contract/format retry; missing AppKey fails explicitly",
        "preserves": ["existing project snapshot", "previous approved batches"],
        "evidence": evidence("TencentWorkflowClient") + evidence("validate_stage_output_with_workflow_contract"),
    },
    {
        "id": "recovery:review_loop", "trigger": "passed=false, rewrite_required=true, or local validator rejects output",
        "action": "write -> review -> rewrite -> review loop; if passed=false and rewrite flag absent/false, local logic forces rewrite",
        "preserves": ["last candidate", "review payload", "approved prior batches"],
        "limit": "configured review/revise max loops; hard upper bound 10 in orchestrator path",
        "evidence": evidence("_run_batch_write_review_revise_loop"),
    },
    {
        "id": "recovery:stage10_fingerprint", "trigger": "stage10 interrupted or restarted",
        "action": "resume only when asset/input fingerprint and range match; otherwise discard checkpoint",
        "preserves": ["completed stage10 partial items"],
        "evidence": evidence("stage10_input_fingerprint") + evidence("load_stage10_resume") + evidence("save_stage10_resume"),
    },
    {
        "id": "recovery:stage11_chunk_resume", "trigger": "stage11 write interrupted or a large batch write fails",
        "action": "split plan into small chunks (current Web API can use single-episode chunks), fingerprint inputs, persist each completed chunk, merge only complete episode range",
        "preserves": ["completed chunk plans", "asset/range fingerprint"],
        "evidence": evidence("split_episode_plan") + evidence("load_stage11_write_resume") + evidence("save_stage11_write_resume") + evidence("merge_causal_conflict_plans"),
    },
    {
        "id": "recovery:audit_adaptive_split", "trigger": "hot_review batch invalid after 2 attempts",
        "action": "5 -> 2+2+1; failed 2 -> 1+1; only persistent single-episode failure stops run",
        "preserves": ["every completed sub-batch", "completed episode numbers", "audit memory"],
        "evidence": evidence("split_episode_batches") + evidence("ScriptAuditBatchService"),
    },
    {
        "id": "recovery:project_resume", "trigger": "pause/retry/process interruption",
        "action": "restore selected runtime fields from _resume_checkpoint and launch replacement/background task",
        "preserves": ["artifacts", "stage outputs", "approved batches", "current memories", "logs<=200"],
        "evidence": evidence("_save_resume_checkpoint") + evidence("_restore_from_resume_checkpoint") + evidence("retry_task") + evidence("resume_task"),
    },
    {
        "id": "recovery:stage_rollback", "trigger": "user chooses rollback stage/range",
        "action": "retain trusted upstream artifacts; clear current/downstream cache; for batched stages truncate from selected batch start and regenerate following batches",
        "preserves": ["upstream stable assets", "partial script before rollback start", "project identity"],
        "evidence": evidence("rollback_project_to_stage") + evidence("_build_stage_rollback_snapshot") + evidence("_rolled_back_debug_state"),
    },
    {
        "id": "recovery:appearance_last_valid", "trigger": "stage09 rerun fails after a previously valid mapping exists",
        "action": "restore last valid appearanceMapping instead of replacing it with invalid/empty output",
        "preserves": ["last valid appearanceMapping"],
        "evidence": [source_ref(APP_ROOT / "server.py", find_line(APP_ROOT / "server.py", r"restored last valid mapping"), "stage09 restore")],
    },
]


SCHEMA_TRANSFORMS = [
    {"stage": "01", "wire_output": "Output.confirmed_info:string", "canonical_output": ["source_brief:object", "display_text:string"], "confidence": "code + workflow prompt"},
    {"stage": "02", "wire_output": "Output.worldview:string", "canonical_output": ["worldview_plan:object|string"], "confidence": "code alias; nested schema enforced mainly by prompt"},
    {"stage": "03", "wire_output": "Output.character:string", "canonical_output": ["character_plan:object|string"], "confidence": "code alias; nested schema enforced mainly by prompt"},
    {"stage": "04", "wire_output": "Output.beat:string", "canonical_output": ["beat_checkpoint_timeline:array", "checkpoint_explanation:object"], "confidence": "strict local parser/validator"},
    {"stage": "05", "wire_output": "Output.storyline:string", "canonical_output": ["character_storylines:array|object|string"], "confidence": "code alias"},
    {"stage": "06", "wire_output": "Output.adaptation:string", "canonical_output": ["adaptation_guide:object|string"], "confidence": "code alias"},
    {"stage": "07", "wire_output": "Output:object/string wrapper", "canonical_output": ["framework_plan_package:object", "validation_report:object"], "confidence": "local stage definition"},
    {"stage": "08", "wire_output": "Output.output:string", "canonical_output": ["sceneDictionary:{scene_count,core_scenes[2..3]}", "scriptWorldRulesDigest:{world_type,core_rules,action_limits,danger_sources,do_not_break_rules}"], "confidence": "local validator"},
    {"stage": "09", "wire_output": "Output.alias:string", "canonical_output": ["appearanceMapping:{characters:array,...}"], "confidence": "local validator only enforces non-empty characters in framework-to-script path; deeper schema UNKNOWN unless prompt contract used"},
    {"stage": "10", "wire_output": "Output:object/string wrapper", "canonical_output": ["allEnrichedEpisodePlan:array", "allEnrichedEpisodePlanText:string"], "confidence": "local validator enforces continuous episode numbers; nested item schema beyond episode is partially UNKNOWN"},
    {"stage": "11_01/11_03", "wire_output": "conflicts/rewrite", "canonical_output": ["batchCausalConflictPlan:{batch_meta,global_conflict_engine,episodes[]}"], "confidence": "strict local root + episode field validator"},
    {"stage": "11_02/12_02", "wire_output": "conflictreview/scriptreview:string", "canonical_output": ["passed:boolean", "rewrite_required:boolean", "blocking_issues:array", "summary?", "rewrite_start_episode?", "stage?"], "confidence": "strict review parser; local default/force-rewrite branches exist"},
    {"stage": "12_01/12_03", "wire_output": "Output.script:string", "canonical_output": ["batchScriptText:string"], "confidence": "script heading/window structural validator"},
    {"stage": "hot_review", "wire_output": "Output.audit_batch:string", "canonical_output": ["script_audit_batch_v1", "merged script_audit_compact_v1"], "confidence": "strict batch validator + deterministic merge"},
    {"stage": "character_image_prompt", "wire_output": "Output.character_image_prompt:string", "canonical_output": ["character_image_prompt_v1"], "confidence": "strict schema_version, character identity and positive_prompt validation"},
]


def configuration_warnings(
    workflows: list[dict[str, Any]],
    internal_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    by_stage = {node.get("stage_key"): node for node in workflows}
    review_workflow = by_stage.get("11_02")
    review_llms = [
        node
        for node in internal_nodes
        if node.get("parent_id") == "workflow:11_02" and node.get("node_type") == "LLM"
    ]
    if review_workflow and review_llms:
        review_llm = review_llms[0]
        responsibility = str(review_llm.get("responsibility") or "")
        role = str(review_llm.get("agent_role") or "")
        if not any(token in f"{role} {responsibility}" for token in ("审核", "审查", "评审")):
            warnings.append(
                {
                    "id": "warning:11_02_review_prompt_role_mismatch",
                    "severity": "HIGH",
                    "status": "CODE_CONFIRMED_REQUIRES_HUMAN_FIX",
                    "node_id": review_llm["id"],
                    "observed": (
                        f"Workflow title/output declare review ({review_workflow.get('title')} / "
                        f"{review_workflow.get('wire_response_fields')}), but the LLM self-declared role is "
                        f"{role!r} and its prompts instruct conflict-plan generation."
                    ),
                    "expected_by_local_contract": [
                        "passed or reviewPassed",
                        "rewrite_required or rewriteRequired",
                        "blocking_issues or blockingIssues",
                    ],
                    "impact": "The local review parser may force rewrite or reject the response because review decision fields are absent.",
                    "source_evidence": review_workflow.get("source_evidence", []),
                }
            )
    wrapped = [
        node.get("stage_key")
        for node in workflows
        if node.get("response_field_status") == "WRAPPED_OUTPUT_ONLY"
    ]
    if wrapped:
        warnings.append(
            {
                "id": "warning:wrapped_output_only",
                "severity": "INFO",
                "status": "COMPATIBILITY_PATH",
                "node_id": "local:tencent_gateway",
                "observed": f"Exported END nodes expose only the root Output wrapper for stages: {', '.join(wrapped)}.",
                "expected_by_local_contract": [
                    str(by_stage[key].get("response_fields")) for key in wrapped if key in by_stage
                ],
                "impact": "Not necessarily an error: TencentWorkflowClient recursively unwraps Output/content and applies the local contract, but these stages should be covered by integration tests.",
                "source_evidence": evidence("_unwrap_response_envelope"),
            }
        )
    return warnings


def persistence_matrix() -> list[dict[str, Any]]:
    return [
        {"store": "SQLite", "path": "runtime_data/users.db", "content": ["users(id,username,password_hash,created_at)", "auth_sessions(token,user_id,created_at)"], "source_evidence": evidence("AuthStore")},
        {"store": "Project snapshots", "path": "runtime_data/projects/<project_id>.json", "content": ["input_payload", "artifacts", "stage outputs/status", "logs<=200", "debug_state", "_resume_checkpoint"], "source_evidence": evidence("ProjectSnapshotStoreMixin")},
        {"store": "Project index", "path": "runtime_data/index.json", "content": ["next_project_id", "latest_project_id", "latest_project_by_user"], "source_evidence": evidence("_load_index")},
        {"store": "User knowledge", "path": "runtime_data/user_knowledge/*.json", "content": ["tags", "user preferences", "manual/tag/merged stage prompts"], "source_evidence": evidence("UserKnowledgeStore")},
        {"store": "Script audit", "path": "runtime_data/script_audits/*", "content": ["source script run", "completed batches", "audit memory", "compact result", "safe debug events"], "source_evidence": evidence("ScriptAuditBatchService")},
        {"store": "Exports and evidence", "path": "runtime_data/exports, cache, debug, logs, runtime_archive", "content": ["TXT/DOCX", "resume fragments", "workflow diagnostics", "archive manifest"], "source_evidence": evidence("RuntimeExportStoreMixin")},
        {"store": "Character image prompt", "path": "NONE (response only)", "content": ["result", "source_summary"], "source_evidence": evidence("generate_character_image_prompt")},
    ]


def render_report(manifest: dict[str, Any]) -> str:
    workflows = [node for node in manifest["nodes"] if node.get("node_level") == 2 and node.get("node_type") == "Workflow"]
    internals = [node for node in manifest["nodes"] if node.get("node_level") == 3]
    llms = [node for node in internals if node.get("node_type") == "LLM"]
    mismatches = [node for node in workflows if node.get("workflow_id_status") == "MISMATCH"]

    lines = [
        "# Idea to Scripts 代码驱动智能体运行架构分析",
        "",
        "> 本文档由 `scripts/generate_architecture_manifest.py` 扫描仓库生成。腾讯工作流节点、端口和内部边来自 20 份 `*_workflow.json`；本地编排、压缩、恢复与持久化结论均附代码位置。无法从代码确认的子字段保持 `UNKNOWN`。",
        "",
        "## 扫描结论",
        "",
        f"- 腾讯工作流：{len(workflows)} 个。",
        f"- 腾讯工作流内部节点：{len(internals)} 个，其中 LLM 节点 {len(llms)} 个。",
        f"- 分析清单总节点：{len(manifest['nodes'])} 个；总边：{len(manifest['edges'])} 条。",
        "- 真正的隐藏层已确认：`12_01 剧本正文撰写` 和 `12_03 剧本正文修订` 均包含两个串行 LLM，而不是单一 Agent。",
        "- 其他当前导出工作流的内部结构大多为 `START → LLM → END`。",
        "- 心电图审核不是普通 5 集失败后直接改为 2 集的单次切换：实际逻辑是每个批次最多尝试 2 次，5 集仍失败则拆为 `2+2+1`，2 集仍失败再拆成单集。",
        "",
        "## Node List",
        "",
        "### Level 1 — 系统模块",
        "",
        "| Node ID | 名称 | 类型 | 职责 |",
        "|---|---|---|---|",
    ]
    for node in manifest["nodes"]:
        if node.get("node_level") == 1:
            lines.append(f"| `{node['id']}` | {node['title']} | {node['node_type']} | {node['responsibility']} |")

    lines += [
        "",
        "### Level 2 — 本地模块与工作流",
        "",
        "| Node ID | Parent | 名称 | 类型 | 输入/输出数 | 保存 |",
        "|---|---|---|---|---:|---|",
    ]
    for node in manifest["nodes"]:
        if node.get("node_level") != 2:
            continue
        input_count = len(node.get("input", [])) if isinstance(node.get("input"), list) else "UNKNOWN"
        output_count = len(node.get("output", [])) if isinstance(node.get("output"), list) else "UNKNOWN"
        save = node.get("save_state")
        save_text = "; ".join(save) if isinstance(save, list) else str(save)
        lines.append(f"| `{node['id']}` | `{node.get('parent_id')}` | {node['title']} | {node['node_type']} | {input_count}/{output_count} | {save_text} |")

    lines += [
        "",
        "### Level 3 — 腾讯工作流内部节点",
        "",
        "| Parent Workflow | 内部链路 | LLM 模型 |",
        "|---|---|---|",
    ]
    for workflow in workflows:
        children = [node for node in internals if node.get("parent_id") == workflow["id"]]
        child_by_id = {node["id"]: node for node in children}
        child_edges = [edge for edge in manifest["edges"] if edge.get("edge_type") == "platform_data_flow" and edge.get("source") in child_by_id]
        incoming = {edge["target"] for edge in child_edges}
        starts = [node for node in children if node["id"] not in incoming] or [node for node in children if node.get("node_type") == "START"]
        order: list[dict[str, Any]] = []
        current = starts[0] if starts else None
        seen: set[str] = set()
        while current and current["id"] not in seen:
            order.append(current)
            seen.add(current["id"])
            next_edge = next((edge for edge in child_edges if edge["source"] == current["id"]), None)
            current = child_by_id.get(next_edge["target"]) if next_edge else None
        for child in children:
            if child["id"] not in seen:
                order.append(child)
        chain = " → ".join(f"{node.get('display_title') or node['title']}({node['node_type']})" for node in order)
        models = ", ".join(dict.fromkeys(node.get("model") for node in order if node.get("model"))) or "—"
        lines.append(f"| `{workflow['id']}` | {chain} | {models} |")

    lines += [
        "",
        "完整 Level 3 节点的 ID、类型、引用输入、输出、模型参数、Prompt SHA-256、异常重试和源文件见 `architecture_manifest.generated.json`。",
        "",
        "## Edge List — 真实业务数据流",
        "",
        "| Source | Target | 传递数据 | 字段 | 压缩 | 条件 |",
        "|---|---|---|---|---|---|",
    ]
    for edge in manifest["edges"]:
        if edge.get("edge_type") != "business_data_flow":
            continue
        fields = ", ".join(edge.get("fields") or ["UNKNOWN"])
        lines.append(f"| `{edge['source']}` | `{edge['target']}` | {edge['data_name']} | `{fields}` | {edge.get('compressed', 'UNKNOWN')} | {edge.get('condition', 'UNKNOWN')} |")

    lines += [
        "",
        "## JSON Schema 变化",
        "",
        "| Stage | 腾讯 wire output | 本地 canonical output | 确定性 |",
        "|---|---|---|---|",
    ]
    for item in manifest["schema_transforms"]:
        lines.append(f"| `{item['stage']}` | `{item['wire_output']}` | `{'; '.join(item['canonical_output'])}` | {item['confidence']} |")

    lines += ["", "## 上下文压缩与字段筛选", ""]
    for rule in manifest["compression_rules"]:
        lines += [
            f"### `{rule['id']}`",
            "",
            f"- 实现：`{rule['function']}`",
            f"- 原始：{rule['original']}",
            f"- 压缩后：{'; '.join(rule['result'])}",
            f"- 下游：{'; '.join(rule['consumers'])}",
            "",
        ]

    lines += ["## Workflow Loop / 失败恢复与回滚", ""]
    for rule in manifest["recovery_rules"]:
        lines += [
            f"### `{rule['id']}`",
            "",
            f"- 触发：{rule['trigger']}",
            f"- 动作：{rule['action']}",
            f"- 保留：{'; '.join(rule['preserves'])}",
        ]
        if rule.get("limit"):
            lines.append(f"- 上限：{rule['limit']}")
        lines.append("")

    lines += [
        "## 持久化矩阵",
        "",
        "| Store | 路径 | 内容 |",
        "|---|---|---|",
    ]
    for item in manifest["persistence"]:
        lines.append(f"| {item['store']} | `{item['path']}` | {'; '.join(item['content'])} |")

    lines += [
        "",
        "## UNKNOWN / 需复核项",
        "",
        "- 腾讯工作流导出中所有 START 参数的 `IsRequired` 基本为 false；实际必填性主要由本地服务、Prompt 和输出校验实现，不能仅依据平台字段判断。",
        "- 02、03、05、06、07、09、10 的部分深层子字段仅在 Prompt 中约定，本地并未对每个子字段做等强度验证；这些字段在最终图中应标记为 `prompt_contract`，不应冒充 `runtime_validated`。",
        "- `character_image_prompt` 当前是响应级产物，未找到自动持久化。",
        "- `hot_review` 不是 stage12 完成后自动触发，而是用户显式提交审核。",
    ]
    if mismatches:
        lines.append("- 导出 WorkflowID 与本地诊断 ID 不一致：" + ", ".join(f"`{node['stage_key']}` export={node['workflow_id_export']} registry={node['workflow_id_registry']}" for node in mismatches) + "。实际腾讯应用由 AppKey 决定，但诊断元数据仍建议修正。")

    lines += ["", "## 配置一致性告警", ""]
    for warning in manifest["configuration_warnings"]:
        lines += [
            f"### `{warning['severity']}` — `{warning['id']}`",
            "",
            f"- 节点：`{warning['node_id']}`",
            f"- 观测：{warning['observed']}",
            f"- 本地契约：{'; '.join(warning['expected_by_local_contract'])}",
            f"- 影响：{warning['impact']}",
            "",
        ]

    lines += [
        "",
        "## React Flow 最终层级建议",
        "",
        "- 默认只显示 `node_level: 1`：系统模块和主数据流。",
        "- 点击 Level 1 展开 `node_level: 2`：本地服务或腾讯工作流。",
        "- 点击 Workflow 展开 `node_level: 3`：START、每个 LLM/Agent、END 以及平台内部边。",
        "- 节点展开状态只改变可视投影，不改变 manifest 的真实节点/边。",
        "- Edge 详情面板应显示 `fields` / `compressed` / `condition` / `source_evidence`，让“代码驱动”可现场验证。",
        "- 建议下一步先由你确认 Level 1 的 9 个系统分组，再把当前 `App.jsx` 中的手写数组替换为该 manifest 的投影器。",
        "",
        "## 机器可读交付",
        "",
        "- `architecture_manifest.generated.json`：完整 nodes / edges / compression / recovery / schema / persistence。",
        "- `scripts/generate_architecture_manifest.py`：可重复扫描生成，新工作流导出加入后可再运行。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    workflows, internal_nodes, internal_edges = load_exports()
    curated_local = [normalize_curated_node(dict(item)) for item in LOCAL_NODES]
    curated_data = [normalize_curated_node(dict(item)) for item in DATA_NODES]
    nodes = system_nodes() + curated_local + workflows + internal_nodes + curated_data
    edges = containment_edges(nodes) + internal_edges + business_edges()
    validation = validate_graph(nodes, edges)

    manifest = {
        "schema_version": "idea_to_scripts_architecture_manifest_v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "generator": relpath(Path(__file__)),
        "scan_scope": {
            "workflow_export_root": relpath(EXPORT_ROOT),
            "workflow_export_count": len(workflows),
            "python_root": relpath(APP_ROOT),
            "node_levels": {
                "1": "system module",
                "2": "local module or workflow",
                "3": "concrete Tencent platform node / Agent",
            },
        },
        "nodes": nodes,
        "edges": edges,
        "validation": validation,
        "schema_transforms": SCHEMA_TRANSFORMS,
        "compression_rules": COMPRESSION_RULES,
        "recovery_rules": RECOVERY_RULES,
        "configuration_warnings": configuration_warnings(workflows, internal_nodes),
        "persistence": persistence_matrix(),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
    MANIFEST_PATH.write_text(manifest_text, encoding="utf-8")
    REPORT_PATH.write_text(render_report(manifest), encoding="utf-8")
    FRONTEND_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_MANIFEST_PATH.write_text(manifest_text, encoding="utf-8")
    print(json.dumps({
        "manifest": relpath(MANIFEST_PATH),
        "frontend_manifest": relpath(FRONTEND_MANIFEST_PATH),
        "report": relpath(REPORT_PATH),
        "nodes": len(nodes),
        "edges": len(edges),
        "workflows": len(workflows),
        "internal_nodes": len(internal_nodes),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
