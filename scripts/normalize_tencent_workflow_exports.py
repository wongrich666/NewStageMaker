from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


EXPORT_ROOT = Path(__file__).resolve().parents[1] / "腾讯智能平台工作流文件"
EXPECTED_END_FIELDS = {
    "export-01提取故事梗概": "confirmed_info",
    "export-02世界观": "worldview",
    "export-03人设方案撰写": "character",
    "export-04三幕十五节拍生成": "beat",
    "export-05人物故事线整理": "storyline",
    "export-06整体改编指引": "adaptation",
    "export-07最终框架策划包": "framework",
    "export-08场景字典提炼": "output",
    "export-09人物服饰映射": "alias",
    "export-10丰富分集计划": "episodeplan",
    "export-11_01开头冲突钩子撰写": "conflicts",
    "export-11_02开头冲突钩子审核": "conflictreview",
    "export-11_03开头冲突钩子修订": "rewrite",
    "export-11_04开头冲突钩子记忆": "memory",
    "export-12_01剧本正文撰写": "script",
    "export-12_02剧本正文审核": "scriptreview",
    "export-12_03剧本正文修订": "script",
    "export-12_04剧本正文记忆": "memory",
    "export-智能剧本评分工作流": "audit_batch",
}

SCRIPT_AUDIT_PROMPT_DOC = (
    Path(__file__).resolve().parents[1]
    / "workflow_code_skeleton"
    / "docs"
    / "TENCENT_SCRIPT_AUDIT_WORKFLOW_PROMPT.md"
)

CONFLICT_REVIEW_USER_PROMPT = (
    "执行阶段：开头冲突钩子审核。读取当前批次冲突计划及其上游材料，"
    "只返回约定的审核 JSON。"
)

CONFLICT_REVIEW_SYSTEM_PROMPT = """你是“短剧开头冲突钩子审核编辑”。

你的任务是审核当前批次的因果冲突推进计划是否能够直接交给剧本正文阶段使用。
你只负责审核，不得重写冲突计划，不得输出新的 batchCausalConflictPlan。

# 输入材料

【总集数】
{{episode_num}}

【当前批次起始集】
{{start_epi}}

【当前批次丰富分集计划】
{{enriched_epiplan}}

【场景字典】
{{scene}}

【世界观/规则摘要】
{{worldview}}

【人设服装 alias 映射】
{{alias}}

【上一批冲突记忆】
{{memory}}

【用户偏好提示词】
{{user_feedback}}

【待审核的当前批次冲突计划】
{{conflict}}

# 审核重点

1. 批次是否从 start_epi 开始、集数连续、最多五集且不超过 episode_num。
2. 是否承接上一批记忆和丰富分集计划，没有跳过必须落地的事件。
3. 每集是否存在清楚的 why_now、人物动机、触发点、目标、阻碍、状态变化和具体结尾钩子。
4. 冲突是否来自人物目标、信息差、规则、资源、身份或关系压力，而不是强行争吵、角色降智或突然改变态度。
5. active_characters、opening_alias_plan 和 character_motivation 中的人物显示名是否沿用上游“人物名(outfit_id)”；不得退回裸名或自造 outfit_id。
6. scene_refs 是否来自场景字典，计划是否违反世界规则或人物设定。
7. 相邻集之间是否能自然承接，是否重复同一种冲突、误会或结尾钩子。
8. 是否落实用户偏好，同时不破坏上游事实和连续性。

只有会阻断正文写作、造成集数错误、因果断裂、人设违规、规则冲突、alias 错绑或关键承接缺失的问题，才能放入 blocking_issues。
一般性的增强建议放入 non_blocking_issues，不得为了显得严格而强行判失败。
blocking_issues 必须指出具体集数、具体字段或具体问题，并给出可执行的修订方向。

# 输出规则

只输出一个可被 JSON.parse 直接解析的 JSON object。
禁止 Markdown、代码块、解释性前缀、结尾总结。
顶层必须且只能包含以下字段：

{
  "passed": false,
  "rewrite_required": true,
  "summary": "一句话说明是否可进入正文阶段及最关键原因。",
  "blocking_issues": ["第X集或具体字段：阻断问题；应如何修订。"],
  "non_blocking_issues": ["不影响通过但建议优化的问题。"],
  "rewrite_start_episode": 1,
  "stage": "causal_conflict_review"
}

字段纪律：
- passed、rewrite_required 必须是 boolean。
- blocking_issues、non_blocking_issues 必须是数组。
- blocking_issues 为空时，passed 必须为 true，rewrite_required 必须为 false。
- blocking_issues 非空时，passed 必须为 false，rewrite_required 必须为 true。
- rewrite_start_episode 应填写最早需要修订的实际集数；通过时填写 start_epi。
- stage 固定为 "causal_conflict_review"。
"""

REQUIRED_PROMPT_BLOCKS = {
    "export-04三幕十五节拍生成": (
        "{{keyword}}",
        "\n\n【关键词补充】\n{{keyword}}",
    ),
    "export-09人物服饰映射": (
        "{{framework}}",
        "\n\n【最终框架策划包（用于核对人物与阶段状态）】\n{{framework}}",
    ),
    "export-11_03开头冲突钩子修订": (
        "{{feedback}}",
        "\n\n【补充修订反馈】\n{{feedback}}",
    ),
    "export-12_02剧本正文审核": (
        "{{user_feedback}}",
        "\n\n【用户偏好提示词】\n{{user_feedback}}",
    ),
}


def _workflow_path(directory: Path) -> Path:
    files = sorted(directory.glob("*_workflow.json"))
    if len(files) != 1:
        raise RuntimeError(f"{directory} 应当且只能包含一个 *_workflow.json，实际为 {len(files)}")
    return files[0]


def _replace_node_ui_name(node: dict[str, Any], old: str, new: str) -> None:
    raw = node.get("NodeUI")
    if not isinstance(raw, str) or not raw.strip():
        return
    try:
        ui = json.loads(raw)
    except json.JSONDecodeError:
        node["NodeUI"] = raw.replace(f'"{old}"', f'"{new}"')
        return
    content = ui.get("data", {}).get("content", {})
    inputs = content.get("inputs")
    if isinstance(inputs, list):
        content["inputs"] = [new if value == old else value for value in inputs]
    node["NodeUI"] = json.dumps(ui, ensure_ascii=False, separators=(",", ":"))


def _rename_start_input(workflow: dict[str, Any], old: str, new: str) -> bool:
    changed = False
    start = next(node for node in workflow["Nodes"] if node.get("NodeType") == "START")
    for item in start.get("Inputs") or []:
        if item.get("Name") == old:
            item["Name"] = new
            changed = True
    if changed:
        _replace_node_ui_name(start, old, new)
    return changed


def _replace_prompt_reference(workflow: dict[str, Any], old: str, new: str) -> bool:
    changed = False
    for node in workflow.get("Nodes") or []:
        llm = node.get("LLMNodeData")
        if not isinstance(llm, dict):
            continue
        for key in ("Prompt", "SystemPrompt"):
            text = llm.get(key)
            if not isinstance(text, str) or old not in text:
                continue
            llm[key] = text.replace(old, new)
            changed = True
    return changed


def _ensure_conflict_review_prompt(workflow: dict[str, Any]) -> bool:
    llm_nodes = [node for node in workflow.get("Nodes") or [] if node.get("NodeType") == "LLM"]
    if len(llm_nodes) != 1:
        raise RuntimeError("11_02 应当且只能包含一个大模型节点")
    llm = llm_nodes[0].get("LLMNodeData")
    if not isinstance(llm, dict):
        raise RuntimeError("11_02 大模型节点缺少 LLMNodeData")
    changed = False
    if llm.get("Prompt") != CONFLICT_REVIEW_USER_PROMPT:
        llm["Prompt"] = CONFLICT_REVIEW_USER_PROMPT
        changed = True
    if llm.get("SystemPrompt") != CONFLICT_REVIEW_SYSTEM_PROMPT:
        llm["SystemPrompt"] = CONFLICT_REVIEW_SYSTEM_PROMPT
        changed = True
    return changed


def _script_audit_prompts() -> tuple[str, str]:
    text = SCRIPT_AUDIT_PROMPT_DOC.read_text(encoding="utf-8")

    def fenced_text(section: str) -> str:
        match = re.search(
            rf"(?s)## {re.escape(section)}.*?```text\s*\n(.*?)\n```",
            text,
        )
        if not match:
            raise RuntimeError(f"文脉检测提示词文档缺少章节：{section}")
        return match.group(1).strip()

    return fenced_text("二、大模型节点用户消息"), fenced_text("四、大模型系统提示词")


def _ensure_script_audit_prompt(workflow: dict[str, Any]) -> bool:
    llm_nodes = [node for node in workflow.get("Nodes") or [] if node.get("NodeType") == "LLM"]
    if len(llm_nodes) != 1:
        raise RuntimeError("文脉检测工作流应当且只能包含一个大模型节点")
    llm = llm_nodes[0].get("LLMNodeData")
    if not isinstance(llm, dict):
        raise RuntimeError("文脉检测大模型节点缺少 LLMNodeData")
    user_prompt, system_prompt = _script_audit_prompts()
    changed = False
    if llm.get("Prompt") != user_prompt:
        llm["Prompt"] = user_prompt
        changed = True
    if llm.get("SystemPrompt") != system_prompt:
        llm["SystemPrompt"] = system_prompt
        changed = True
    return changed


def _ensure_prompt_block(workflow: dict[str, Any], token: str, block: str) -> bool:
    llm_nodes = [node for node in workflow.get("Nodes") or [] if node.get("NodeType") == "LLM"]
    if not llm_nodes:
        raise RuntimeError("工作流缺少大模型节点")
    llm = llm_nodes[0].get("LLMNodeData")
    if not isinstance(llm, dict):
        raise RuntimeError("大模型节点缺少 LLMNodeData")
    prompt = str(llm.get("Prompt") or "")
    system_prompt = str(llm.get("SystemPrompt") or "")
    if token in prompt or token in system_prompt:
        return False
    llm["Prompt"] = prompt.rstrip() + block
    return True


def _upstream_llm_node(workflow: dict[str, Any], end_node_id: str) -> dict[str, Any]:
    direct = [
        node
        for node in workflow.get("Nodes") or []
        if end_node_id in (node.get("NextNodeIDs") or [])
    ]
    llm_nodes = [node for node in direct if node.get("NodeType") == "LLM"]
    if len(llm_nodes) == 1:
        return llm_nodes[0]
    all_llm = [node for node in workflow.get("Nodes") or [] if node.get("NodeType") == "LLM"]
    if len(all_llm) == 1:
        return all_llm[0]
    raise RuntimeError(f"无法唯一确定结束节点 {end_node_id} 的上游大模型节点")


def _ensure_end_output(workflow: dict[str, Any], field_name: str) -> bool:
    end = next(node for node in workflow["Nodes"] if node.get("NodeType") == "END")
    outputs = end.get("Outputs") or []
    properties = outputs[0].get("Properties") if outputs else None
    if (
        isinstance(properties, list)
        and len(properties) == 1
        and properties[0].get("Title") == field_name
        and properties[0].get("Value", {}).get("Reference", {}).get("JsonPath") == "Output.Content"
    ):
        return False

    llm = _upstream_llm_node(workflow, str(end.get("NodeID") or ""))
    end["Outputs"] = [
        {
            "Title": "Output",
            "Type": "OBJECT",
            "Required": [],
            "Properties": [
                {
                    "Title": field_name,
                    "Type": "STRING",
                    "Required": [],
                    "Properties": [],
                    "Desc": "",
                    "Value": {
                        "InputType": "REFERENCE_OUTPUT",
                        "Reference": {
                            "NodeID": llm["NodeID"],
                            "JsonPath": "Output.Content",
                        },
                    },
                    "AnalysisMethod": "COVER",
                }
            ],
            "Desc": "输出内容",
            "AnalysisMethod": "COVER",
        }
    ]
    raw_ui = end.get("NodeUI")
    if isinstance(raw_ui, str) and raw_ui.strip():
        try:
            ui = json.loads(raw_ui)
            content = ui.get("data", {}).get("content", {})
            content["outputs"] = ["Output", f"Output.{field_name}"]
            end["NodeUI"] = json.dumps(ui, ensure_ascii=False, separators=(",", ":"))
        except json.JSONDecodeError:
            pass
    return True


def normalize_export(directory: Path, *, write: bool) -> dict[str, Any]:
    workflow_path = _workflow_path(directory)
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    changes: list[str] = []

    if directory.name == "export-01提取故事梗概":
        if _rename_start_input(workflow, "target_form", "target_format"):
            changes.append("start input target_form -> target_format")
    elif directory.name == "export-02世界观":
        if _replace_prompt_reference(
            workflow,
            "{{previous_worldview}}",
            "{{previous_worldview_plan}}",
        ):
            changes.append("prompt previous_worldview -> previous_worldview_plan")
    elif directory.name == "export-07最终框架策划包":
        if _rename_start_input(workflow, "adaption_direction", "adaptation_direction"):
            changes.append("start input adaption_direction -> adaptation_direction")
    elif directory.name == "export-11_02开头冲突钩子审核":
        if _ensure_conflict_review_prompt(workflow):
            changes.append("replace copied writing prompt with review contract")
    elif directory.name == "export-智能剧本评分工作流":
        if _ensure_script_audit_prompt(workflow):
            changes.append("sync three-episode compact prompt from documentation")

    prompt_block = REQUIRED_PROMPT_BLOCKS.get(directory.name)
    if prompt_block and _ensure_prompt_block(workflow, *prompt_block):
        changes.append(f"connect declared input {prompt_block[0]} to model prompt")

    expected_end_field = EXPECTED_END_FIELDS[directory.name]
    if _ensure_end_output(workflow, expected_end_field):
        changes.append(f"end output -> Output.{expected_end_field}")

    if write and changes:
        workflow_path.write_text(
            json.dumps(workflow, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    return {
        "directory": directory.name,
        "workflow_id": workflow.get("WorkflowID"),
        "changes": changes,
        "written": bool(write and changes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="核对并修复腾讯工作流导出契约")
    parser.add_argument("--fix", action="store_true", help="写入修复；默认只审计")
    args = parser.parse_args()

    results = [
        normalize_export(EXPORT_ROOT / directory_name, write=args.fix)
        for directory_name in EXPECTED_END_FIELDS
    ]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
