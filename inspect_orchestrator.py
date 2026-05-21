from pathlib import Path
import re

root = Path.cwd()
target = root / "workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py"

print("=" * 100)
print("FILE:", target)
print("EXISTS:", target.exists())
print("=" * 100)

text = target.read_text(encoding="utf-8", errors="replace")

print("\n[1] fastgpt_hybrid_workflow.py 函数列表")
for i, line in enumerate(text.splitlines(), 1):
    m = re.match(r"^(\s*)def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
    if m:
        name = m.group(2)
        if any(k in name.lower() for k in [
            "run", "stage", "framework", "script", "hook", "dialogue",
            "conflict", "batch", "episode", "fastgpt", "workflow"
        ]):
            print(f"L{i}: {line}")

print("\n[2] 新链路关键词上下文")
patterns = [
    "framework_scene_dictionary",
    "framework_appearance_mapping",
    "framework_enriched_episode_plan",
    "framework_causal_conflict_write",
    "framework_script_write",
    "allEnrichedEpisodePlan",
    "batchEnrichedEpisodePlan",
    "batchCausalConflictPlan",
    "batchScriptText",
    "STAGE_FRAMEWORK",
    "slice_by_episode",
    "parse_json_object_or_raise",
]

lines = text.splitlines()
for p in patterns:
    print("\n" + "-" * 100)
    print("PATTERN:", p)
    found = False
    for idx, line in enumerate(lines, 1):
        if p in line:
            found = True
            start = max(1, idx - 5)
            end = min(len(lines), idx + 8)
            print(f"\n--- around L{idx} ---")
            for j in range(start, end + 1):
                print(f"{j}: {lines[j-1]}")
    if not found:
        print("NOT FOUND")

print("\n[3] 旧链路关键词上下文，用来确认现在是否还走 all_hooks/all_dialogues/all_script")
old_patterns = [
    "STAGE_HOOK",
    "all_hooks",
    "all_dialogues",
    "dialogue",
    "STAGE_SCRIPT",
    "run_batched",
]
for p in old_patterns:
    print("\n" + "-" * 100)
    print("OLD PATTERN:", p)
    count = 0
    for idx, line in enumerate(lines, 1):
        if p in line:
            count += 1
            if count <= 12:
                print(f"L{idx}: {line}")
    print("COUNT:", count)
