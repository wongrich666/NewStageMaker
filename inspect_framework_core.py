import json
import re
from pathlib import Path

ROOT = Path.cwd()
ORCH = ROOT / "workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py"
JSON_ROOT = ROOT / "BETTER_FRAMEWORK_JSONS"

def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

def header(title: str):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)

def extract_func(text: str, func_name: str) -> str:
    pattern = re.compile(rf"^def {re.escape(func_name)}\(", re.M)
    m = pattern.search(text)
    if not m:
        pattern = re.compile(rf"^\s*def {re.escape(func_name)}\(", re.M)
        m = pattern.search(text)
    if not m:
        return ""
    start = m.start()
    next_m = re.search(r"^\s*def [A-Za-z_][A-Za-z0-9_]*\(", text[m.end():], re.M)
    end = m.end() + next_m.start() if next_m else len(text)
    return text[start:end]

def print_func(func_name: str, max_lines: int = 260):
    text = read(ORCH)
    chunk = extract_func(text, func_name)
    header(f"FUNCTION: {func_name}")
    if not chunk:
        print("NOT FOUND")
        return
    lines = chunk.splitlines()
    for i, line in enumerate(lines[:max_lines], 1):
        print(f"{i:04d}: {line}")
    if len(lines) > max_lines:
        print(f"... TRUNCATED, total lines={len(lines)}")

def load_json(path: Path):
    try:
        return json.loads(read(path))
    except Exception as exc:
        print("JSON LOAD ERROR:", path, exc)
        return None

def find_file(part: str):
    matches = list(JSON_ROOT.rglob(f"*{part}*.json"))
    return matches[0] if matches else None

def get_vars(obj):
    return [v.get("key") for v in obj.get("chatConfig", {}).get("variables", []) if isinstance(v, dict)]

def get_updates(obj):
    out = []
    for node in obj.get("nodes", []):
        if node.get("flowNodeType") != "variableUpdate":
            continue
        for inp in node.get("inputs", []):
            if inp.get("key") != "updateList":
                continue
            for item in inp.get("value", []):
                out.append({
                    "nodeId": node.get("nodeId"),
                    "variable": item.get("variable"),
                    "value": item.get("value"),
                    "valueType": item.get("valueType"),
                })
    return out

def get_answer_refs(obj):
    refs = []
    for node in obj.get("nodes", []):
        if node.get("flowNodeType") != "answerNode":
            continue
        refs.append(node)
    return refs

def inspect_json(label, path):
    header(f"JSON: {label}")
    print("PATH:", path)
    if not path or not path.exists():
        print("MISSING")
        return
    obj = load_json(path)
    if obj is None:
        return
    print("chatConfig._id:", obj.get("chatConfig", {}).get("_id"))
    print("variables:", get_vars(obj))
    print("variableUpdate:")
    for u in get_updates(obj):
        print(" ", u)
    print("answer nodes:", len(get_answer_refs(obj)))
    # 只打印 answer node 的输入，避免太长
    for node in get_answer_refs(obj):
        print(" answerNode:", node.get("nodeId"), node.get("name"))
        for inp in node.get("inputs", []):
            print("   ", inp.get("key"), "=", inp.get("value"))

header("ENV 文件位置检查")
for p in [ROOT / ".env", ROOT / "workflow_code_skeleton/.env", ROOT / "workflow_code_skeleton/.env.example"]:
    print(p, "EXISTS" if p.exists() else "MISSING")

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
    d = {}
    if not path.exists():
        return d
    for line in read(path).splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        d[k.strip()] = v.strip()
    return d

for env_path in [ROOT / ".env", ROOT / "workflow_code_skeleton/.env"]:
    header(f"ENV KEY CHECK: {env_path}")
    data = parse_env(env_path)
    if not data:
        print("NO ENV DATA")
        continue
    for k in required_keys:
        v = data.get(k, "")
        if not v:
            status = "MISSING/EMPTY"
        elif v == "fastgpt-" or len(v) < 12:
            status = "RISK: looks incomplete"
        else:
            status = "SET"
        print(f"{k:58} {status}")

print_func("_run_framework_to_script_workflow", 360)
print_func("_ensure_framework_to_script_seed_variables", 220)
print_func("_framework_enriched_plan_for_batch", 220)
print_func("_validate_framework_batch_object", 180)
print_func("_run_batch_write_review_revise_loop", 300)
print_func("_stage_input_context", 180)
print_func("_normalize_stage_output_aliases", 220)

inspect_json("08 场景字典", find_file("08_场景字典"))
inspect_json("09 人设服装", find_file("09_人设服装"))
inspect_json("10 丰富分集", find_file("10_丰富分集"))
inspect_json("正文审核 02", (JSON_ROOT / "【新】正文及对话" / "02审核.json"))
inspect_json("冲突记忆 04", (JSON_ROOT / "【新】开头冲突钩子" / "04记忆.json"))
inspect_json("正文记忆 04", (JSON_ROOT / "【新】正文及对话" / "04记忆.json"))

header("自动判断")
text = read(ORCH)
checks = {
    "_run_framework_to_script_workflow exists": "_run_framework_to_script_workflow" in text,
    "scene stage constant used": "STAGE_FRAMEWORK_SCENE_DICTIONARY" in text,
    "appearance stage constant used": "STAGE_FRAMEWORK_APPEARANCE_MAPPING" in text,
    "enriched stage constant used": "STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN" in text,
    "causal write used": "STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE" in text,
    "script write used": "STAGE_FRAMEWORK_SCRIPT_WRITE" in text,
    "batch plan var used": "BATCH_ENRICHED_EPISODE_PLAN" in text,
    "all enriched var used": "ALL_ENRICHED_EPISODE_PLAN" in text,
    "conflict memory fallback maybe direct get only": "memory_output.get(CONFLICT_MEMORY)" in text,
    "script memory fallback maybe direct get only": "script_memory_output.get(SCRIPT_MEMORY)" in text,
}
for k, v in checks.items():
    print(f"{k:55} {'YES' if v else 'NO'}")

print("\nDONE")
