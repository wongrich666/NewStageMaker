import json
import os
import re
from pathlib import Path

ROOT = Path.cwd()
print("=" * 100)
print("[CHECK] 当前目录:", ROOT)
print("=" * 100)

def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception as exc:
        return f"__READ_ERROR__ {exc}"

def load_json(path: Path):
    try:
        return json.loads(read_text(path))
    except Exception as exc:
        return None, str(exc)

def print_header(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)

# 1. 基础文件存在性
print_header("1. 关键文件存在性")

paths = {
    "fastgpt_hybrid_workflow": ROOT / "workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py",
    "fastgpt_contracts": ROOT / "workflow_code_skeleton/app/services/fastgpt_contracts.py",
    "workflow_ids": ROOT / "workflow_code_skeleton/app/workflow_ids.py",
    "fastgpt_client": ROOT / "workflow_code_skeleton/app/services/fastgpt_client.py",
    "task_manager_common": ROOT / "workflow_code_skeleton/app/services/task_manager_common.py",
    "env_example": ROOT / "workflow_code_skeleton/.env.example",
    "env": ROOT / ".env",
    "framework_json_dir": ROOT / "BETTER_FRAMEWORK_JSONS",
}
for name, path in paths.items():
    print(f"{name:28} {'OK' if path.exists() else 'MISSING'}  {path}")

# 2. Python 代码里是否有新链路调用痕迹
print_header("2. Python 代码搜索：新链路是否只有常量，还是已有真实编排")

py_files = list((ROOT / "workflow_code_skeleton/app").rglob("*.py"))
patterns = [
    "framework_scene_dictionary",
    "framework_appearance_mapping",
    "framework_enriched_episode_plan",
    "framework_causal_conflict_write",
    "framework_causal_conflict_review",
    "framework_causal_conflict_rewrite",
    "framework_causal_conflict_memory",
    "framework_script_write",
    "framework_script_review",
    "framework_script_rewrite",
    "framework_script_memory",
    "allEnrichedEpisodePlan",
    "batchEnrichedEpisodePlan",
    "batchCausalConflictPlan",
    "batchCausalConflictReview",
    "batchScriptText",
    "batchScriptReview",
    "run_framework",
    "framework_to_script",
    "slice_by_episode",
    "parse_json_object_or_raise",
]
hits = {p: [] for p in patterns}
for f in py_files:
    text = read_text(f)
    for p in patterns:
        if p in text:
            # 打印最多前 8 个匹配行
            lines = []
            for i, line in enumerate(text.splitlines(), start=1):
                if p in line:
                    lines.append((i, line.strip()))
                    if len(lines) >= 8:
                        break
            hits[p].append((f.relative_to(ROOT), lines))

for p in patterns:
    print(f"\n--- PATTERN: {p} ---")
    if not hits[p]:
        print("NOT FOUND")
    else:
        for f, lines in hits[p][:8]:
            print(f"[{f}]")
            for ln, line in lines:
                print(f"  L{ln}: {line}")
        if len(hits[p]) > 8:
            print(f"  ... more files: {len(hits[p]) - 8}")

# 3. fastgpt_hybrid_workflow.py 函数名提取
print_header("3. fastgpt_hybrid_workflow.py 函数清单中是否有 framework 新链路函数")

fhw = paths["fastgpt_hybrid_workflow"]
if fhw.exists():
    text = read_text(fhw)
    funcs = re.findall(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text, flags=re.M)
    for fn in funcs:
        if "framework" in fn.lower() or "script" in fn.lower() or "conflict" in fn.lower() or "enriched" in fn.lower():
            print(fn)
else:
    print("fastgpt_hybrid_workflow.py missing")

# 4. 检查 .env.example 和 .env 的新 API key
print_header("4. 新链路 API KEY 是否声明/配置")

required_keys = [
    "FASTGPT_FRAMEWORK_SCENE_DICTIONARY_API_KEY",
    "FASTGPT_FRAMEWORK_APPEARANCE_MAPPING_API_KEY",
    "FASTGPT_FRAMEWORK_ENRICHED_EPISODE_PLAN_API_KEY",
    "FASTGPT_FRAMEWORK_CAUSAL_CONFLICT_WRITE_API_KEY",
    "FASTGPT_FRAMEWORK_CAUSAL_CONFLICT_REVIEW_API_KEY",
    "FASTGPT_FRAMEWORK_CAUSAL_CONFLICT_REWRITE_API_KEY",
    "FASTGPT_FRAMEWORK_CAUSAL_CONFLICT_MEMORY_API_KEY",
    "FASTGPT_FRAMEWORK_SCRIPT_WRITE_API_KEY",
    "FASTGPT_FRAMEWORK_SCRIPT_REVIEW_API_KEY",
    "FASTGPT_FRAMEWORK_SCRIPT_REWRITE_API_KEY",
    "FASTGPT_FRAMEWORK_SCRIPT_MEMORY_API_KEY",
]

def parse_env(path):
    data = {}
    if not path.exists():
        return data
    for line in read_text(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip()
    return data

env_example = parse_env(paths["env_example"])
env_real = parse_env(paths["env"])

for k in required_keys:
    in_example = k in env_example
    real_val = env_real.get(k, "")
    print(f"{k:55} example={'Y' if in_example else 'N'}  .env={'SET' if real_val else 'EMPTY/MISSING'}")

# 5. 工作流 JSON 变量检查
print_header("5. 工作流 JSON 检查：08 / 09 / 10 / 冲突 / 正文")

json_dir = paths["framework_json_dir"]

def find_json_by_name(name_part):
    if not json_dir.exists():
        return None
    matches = list(json_dir.rglob(f"*{name_part}*.json"))
    return matches[0] if matches else None

workflow_targets = {
    "08_scene": find_json_by_name("08_场景字典"),
    "09_appearance": find_json_by_name("09_人设服装"),
    "10_enriched": find_json_by_name("10_丰富分集"),
    "conflict_write": None,
    "conflict_review": None,
    "conflict_rewrite": None,
    "conflict_memory": None,
    "script_write": None,
    "script_review": None,
    "script_rewrite": None,
    "script_memory": None,
}

# 优先在两个新目录里找 01/02/03/04
for folder_name, prefix in [("【新】开头冲突钩子", "conflict"), ("【新】正文及对话", "script")]:
    folder = json_dir / folder_name
    if folder.exists():
        for f in folder.glob("*.json"):
            n = f.name
            if n.startswith("01"):
                workflow_targets[f"{prefix}_write"] = f
            elif n.startswith("02"):
                workflow_targets[f"{prefix}_review"] = f
            elif n.startswith("03"):
                workflow_targets[f"{prefix}_rewrite"] = f
            elif n.startswith("04"):
                workflow_targets[f"{prefix}_memory"] = f

def get_chat_vars(obj):
    try:
        return obj.get("chatConfig", {}).get("variables", [])
    except Exception:
        return []

def get_var_keys(obj):
    return [v.get("key") for v in get_chat_vars(obj) if isinstance(v, dict)]

def get_nodes(obj):
    return obj.get("nodes", []) if isinstance(obj, dict) else []

def get_update_targets(obj):
    targets = []
    for node in get_nodes(obj):
        if node.get("flowNodeType") != "variableUpdate":
            continue
        for inp in node.get("inputs", []):
            if inp.get("key") == "updateList":
                for item in inp.get("value", []):
                    targets.append({
                        "node": node.get("nodeId"),
                        "variable": item.get("variable"),
                        "value": item.get("value"),
                        "valueType": item.get("valueType"),
                    })
    return targets

def get_ai_schema_required(obj):
    for node in get_nodes(obj):
        if node.get("flowNodeType") not in ("chatNode", "tools"):
            continue
        for inp in node.get("inputs", []):
            if inp.get("key") == "aiChatJsonSchema":
                raw = inp.get("value", "")
                try:
                    schema = json.loads(raw)
                    return schema.get("required", []), schema
                except Exception as exc:
                    return [f"SCHEMA_PARSE_ERROR: {exc}"], None
    return [], None

for key, path in workflow_targets.items():
    print("\n" + "-" * 100)
    print(key, "=>", path if path else "MISSING")
    if not path or not path.exists():
        continue
    obj, err = load_json(path)
    if obj is None:
        print("JSON LOAD ERROR:", err)
        continue
    print("chatConfig._id:", obj.get("chatConfig", {}).get("_id"))
    print("chat variables:", get_var_keys(obj))
    required, _schema = get_ai_schema_required(obj)
    print("top required from aiChatJsonSchema:", required)
    print("variableUpdate targets:")
    for t in get_update_targets(obj):
        print(" ", t)

# 6. 针对 10 阶段做专项判断
print_header("6. 10 阶段专项检查")

p10 = workflow_targets["10_enriched"]
if p10 and p10.exists():
    obj, err = load_json(p10)
    if obj is None:
        print("10 JSON LOAD ERROR:", err)
    else:
        keys = get_var_keys(obj)
        updates = get_update_targets(obj)
        print("10 variables:", keys)
        print("10 updates:", updates)

        has_result = "enrichedEpisodePlanResult" in keys
        updates_all = any(t.get("variable") == ["VARIABLE_NODE_ID", "allEnrichedEpisodePlan"] for t in updates)
        updates_result = any(t.get("variable") == ["VARIABLE_NODE_ID", "enrichedEpisodePlanResult"] for t in updates)

        if updates_all and not updates_result:
            print("DIAGNOSIS: RISK - 10 当前把完整 answerText 写入 allEnrichedEpisodePlan，后端如果当数组切片会出错。建议改为 enrichedEpisodePlanResult，后端解析字段。")
        elif updates_result:
            print("DIAGNOSIS: OK - 10 已经保存完整 JSON 到 enrichedEpisodePlanResult。")
        else:
            print("DIAGNOSIS: UNKNOWN - 没看到 10 保存完整结果的 variableUpdate。")

        required, schema = get_ai_schema_required(obj)
        if "allEnrichedEpisodePlan" in required and "allEnrichedEpisodePlanText" in required:
            print("SCHEMA: OK - 顶层要求 allEnrichedEpisodePlan + allEnrichedEpisodePlanText")
        else:
            print("SCHEMA: RISK - 顶层 schema 不是预期结构")
else:
    print("10 工作流文件缺失")

# 7. 正文审核是否有 appearanceMapping
print_header("7. 正文审核 02 是否有 appearanceMapping / batchCausalConflictPlan")

psr = workflow_targets["script_review"]
if psr and psr.exists():
    obj, err = load_json(psr)
    if obj is None:
        print("script_review JSON LOAD ERROR:", err)
    else:
        keys = get_var_keys(obj)
        print("script_review variables:", keys)
        print("has batchCausalConflictPlan:", "batchCausalConflictPlan" in keys)
        print("has appearanceMapping:", "appearanceMapping" in keys)
        if "batchCausalConflictPlan" not in keys:
            print("DIAGNOSIS: ERROR - 正文审核缺 batchCausalConflictPlan")
        if "appearanceMapping" not in keys:
            print("DIAGNOSIS: RECOMMEND - 正文审核建议补 appearanceMapping，否则 alias 严审缺依据")
else:
    print("script_review 文件缺失")

# 8. 运行编译
print_header("8. 建议下一步")
print("请把以上完整输出复制给我。")
print("如果你想继续本地验证，可以先运行：")
print("python -m compileall -q workflow_code_skeleton")
print("python -m pytest -q workflow_code_skeleton/tests/test_fastgpt_client.py")
print("python -m pytest -q workflow_code_skeleton/tests/test_batched_generation_flow.py")
print("python -m pytest -q workflow_code_skeleton/tests/test_task_manager_public_snapshot.py")
