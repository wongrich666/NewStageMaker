from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path.cwd()
ORCH = ROOT / "workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py"
JSON_ROOT = ROOT / "BETTER_FRAMEWORK_JSONS"

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")

def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")

def backup(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".bak_framework_chain")
    if not bak.exists():
        shutil.copy2(path, bak)

def load_json(path: Path):
    return json.loads(read_text(path))

def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

def find_json_by_predicate(predicate):
    for path in JSON_ROOT.rglob("*.json"):
        try:
            obj = load_json(path)
        except Exception:
            continue
        text = json.dumps(obj, ensure_ascii=False)
        if predicate(path, obj, text):
            return path, obj
    return None, None

def add_chat_variable(obj: dict, variable: dict) -> bool:
    chat = obj.setdefault("chatConfig", {})
    variables = chat.setdefault("variables", [])
    key = variable["key"]
    if any(isinstance(v, dict) and v.get("key") == key for v in variables):
        return False
    variables.append(variable)
    return True

def walk_nodes(obj: dict):
    for node in obj.get("nodes", []):
        yield node

def patch_orchestrator() -> None:
    backup(ORCH)
    text = read_text(ORCH)
    original = text

    helper = r'''
def _framework_to_script_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        for _ in range(2):
            try:
                parsed = json.loads(raw)
            except Exception:
                return {}
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, str):
                raw = parsed.strip()
                continue
            return {}
    return {}


def _framework_to_script_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    obj = _framework_to_script_json_object(value)
    if isinstance(obj.get(ALL_ENRICHED_EPISODE_PLAN), list):
        return list(obj.get(ALL_ENRICHED_EPISODE_PLAN) or [])
    if isinstance(obj.get("allEnrichedEpisodePlan"), list):
        return list(obj.get("allEnrichedEpisodePlan") or [])
    return []


def _normalize_framework_to_script_asset_variables(variables: dict[str, Any]) -> None:
    """Normalize 08/09/10 workflow outputs.

    FastGPT variableUpdate often stores a full answerText JSON string into an
    internal variable. The framework-to-script chain needs actual subfields:
    sceneDictionary, scriptWorldRulesDigest, appearanceMapping,
    allEnrichedEpisodePlan and allEnrichedEpisodePlanText.
    """

    # 08 sceneDictionary + scriptWorldRulesDigest
    for raw in (
        variables.get(SCENE_DICTIONARY),
        variables.get("sceneDictionaryResult"),
        variables.get("answerText"),
    ):
        obj = _framework_to_script_json_object(raw)
        if not obj:
            continue
        scene_value = obj.get(SCENE_DICTIONARY) or obj.get("sceneDictionary")
        rules_value = obj.get(SCRIPT_WORLD_RULES_DIGEST) or obj.get("scriptWorldRulesDigest")
        if _has_value(scene_value):
            variables[SCENE_DICTIONARY] = scene_value
            variables["sceneDictionary"] = scene_value
        if _has_value(rules_value):
            variables[SCRIPT_WORLD_RULES_DIGEST] = rules_value
            variables["scriptWorldRulesDigest"] = rules_value

    nested_scene = _framework_to_script_json_object(variables.get(SCENE_DICTIONARY))
    if _has_value(nested_scene.get(SCENE_DICTIONARY) or nested_scene.get("sceneDictionary")):
        variables[SCENE_DICTIONARY] = nested_scene.get(SCENE_DICTIONARY) or nested_scene.get("sceneDictionary")
        variables["sceneDictionary"] = variables[SCENE_DICTIONARY]
    if _has_value(nested_scene.get(SCRIPT_WORLD_RULES_DIGEST) or nested_scene.get("scriptWorldRulesDigest")):
        variables[SCRIPT_WORLD_RULES_DIGEST] = (
            nested_scene.get(SCRIPT_WORLD_RULES_DIGEST) or nested_scene.get("scriptWorldRulesDigest")
        )
        variables["scriptWorldRulesDigest"] = variables[SCRIPT_WORLD_RULES_DIGEST]

    # 09 appearanceMapping
    for raw in (
        variables.get(APPEARANCE_MAPPING),
        variables.get("appearanceMappingResult"),
        variables.get("answerText"),
    ):
        obj = _framework_to_script_json_object(raw)
        if not obj:
            continue
        appearance_value = obj.get(APPEARANCE_MAPPING) or obj.get("appearanceMapping")
        if _has_value(appearance_value):
            variables[APPEARANCE_MAPPING] = appearance_value
            variables["appearanceMapping"] = appearance_value

    nested_appearance = _framework_to_script_json_object(variables.get(APPEARANCE_MAPPING))
    if _has_value(nested_appearance.get(APPEARANCE_MAPPING) or nested_appearance.get("appearanceMapping")):
        variables[APPEARANCE_MAPPING] = nested_appearance.get(APPEARANCE_MAPPING) or nested_appearance.get("appearanceMapping")
        variables["appearanceMapping"] = variables[APPEARANCE_MAPPING]

    # 10 allEnrichedEpisodePlan + allEnrichedEpisodePlanText
    for raw in (
        variables.get("enrichedEpisodePlanResult"),
        variables.get(ALL_ENRICHED_EPISODE_PLAN),
        variables.get("allEnrichedEpisodePlan"),
        variables.get("answerText"),
    ):
        obj = _framework_to_script_json_object(raw)
        if not obj:
            continue
        plan_value = obj.get(ALL_ENRICHED_EPISODE_PLAN) or obj.get("allEnrichedEpisodePlan")
        text_value = obj.get("allEnrichedEpisodePlanText")
        if isinstance(plan_value, list) and plan_value:
            variables[ALL_ENRICHED_EPISODE_PLAN] = plan_value
            variables["allEnrichedEpisodePlan"] = plan_value
        if _has_value(text_value):
            variables["allEnrichedEpisodePlanText"] = text_value

    plan_items = _framework_to_script_json_list(variables.get(ALL_ENRICHED_EPISODE_PLAN))
    if plan_items:
        variables[ALL_ENRICHED_EPISODE_PLAN] = plan_items
        variables["allEnrichedEpisodePlan"] = plan_items
'''

    if "_normalize_framework_to_script_asset_variables" not in text:
        marker = "def _run_framework_to_script_workflow("
        if marker not in text:
            raise RuntimeError("找不到 _run_framework_to_script_workflow，无法插入 helper。")
        text = text.replace(marker, helper + "\n\n" + marker, 1)

    # ensure normalize call after seed
    old = "    _ensure_framework_to_script_seed_variables(payload, variables)\n    _sync_state_variables(state, variables)\n"
    new = "    _ensure_framework_to_script_seed_variables(payload, variables)\n    _normalize_framework_to_script_asset_variables(variables)\n    _sync_state_variables(state, variables)\n"
    if old in text and new not in text:
        text = text.replace(old, new, 1)

    # normalize after variables.update(output) in framework asset stages
    old = "        variables.update(output)\n        _sync_state_variables(state, variables)\n"
    new = "        variables.update(output)\n        _normalize_framework_to_script_asset_variables(variables)\n        _sync_state_variables(state, variables)\n"
    if old in text:
        # only replace first three occurrences inside 08/09/10 area
        count = 0
        parts = []
        start = 0
        while True:
            idx = text.find(old, start)
            if idx < 0 or count >= 3:
                parts.append(text[start:])
                break
            parts.append(text[start:idx])
            parts.append(new)
            start = idx + len(old)
            count += 1
        text = "".join(parts)

    # Replace _framework_enriched_plan_for_batch with robust version
    pattern = re.compile(
        r"def _framework_enriched_plan_for_batch\(\n"
        r".*?\n"
        r"def _validate_framework_batch_object\(",
        re.S,
    )
    replacement = r'''def _framework_enriched_plan_for_batch(
    variables: dict[str, Any],
    batch: BatchWindow,
) -> Any:
    _normalize_framework_to_script_asset_variables(variables)

    plan_items = _framework_to_script_json_list(variables.get(ALL_ENRICHED_EPISODE_PLAN))
    if plan_items:
        batch_items: list[Any] = []
        for item in plan_items:
            if not isinstance(item, dict):
                continue
            episode_no = _safe_int(item.get("episode"), 0)
            if batch.start_episode <= episode_no <= batch.end_episode:
                batch_items.append(item)
        if batch_items:
            return json.dumps(batch_items, ensure_ascii=False)

    cached = slice_object_episodes_for_batch(variables.get(ALL_ENRICHED_EPISODE_PLAN), batch)
    if _has_value(cached):
        return cached

    fallback = variables.get(BATCH_ENRICHED_EPISODE_PLAN)
    fallback_items = _framework_to_script_json_list(fallback)
    if fallback_items:
        return json.dumps(fallback_items, ensure_ascii=False)
    return fallback


def _validate_framework_batch_object('''
    if pattern.search(text):
        text = pattern.sub(replacement, text, count=1)
    else:
        raise RuntimeError("未能替换 _framework_enriched_plan_for_batch。")

    # Explicitly pass variables even if contract input_names misses them.
    replacements = [
        (
            "                CONFLICT_START_EPISODE: batch.start_episode,\n                CONFLICT_MEMORY: conflict_memory,\n",
            "                CONFLICT_START_EPISODE: batch.start_episode,\n                CONFLICT_MEMORY: conflict_memory,\n                BATCH_ENRICHED_EPISODE_PLAN: batch_enriched,\n                SCENE_DICTIONARY: variables.get(SCENE_DICTIONARY),\n                SCRIPT_WORLD_RULES_DIGEST: variables.get(SCRIPT_WORLD_RULES_DIGEST),\n                APPEARANCE_MAPPING: variables.get(APPEARANCE_MAPPING),\n",
        ),
        (
            "                BATCH_CAUSAL_CONFLICT_PLAN: current,\n            },\n            rewrite_context_builder=lambda current, review: {\n",
            "                BATCH_CAUSAL_CONFLICT_PLAN: current,\n                BATCH_ENRICHED_EPISODE_PLAN: batch_enriched,\n                APPEARANCE_MAPPING: variables.get(APPEARANCE_MAPPING),\n            },\n            rewrite_context_builder=lambda current, review: {\n",
        ),
        (
            "                CONFLICT_MEMORY: conflict_memory,\n            },\n            progress_percent=min(78",
            "                CONFLICT_MEMORY: conflict_memory,\n                BATCH_ENRICHED_EPISODE_PLAN: batch_enriched,\n                APPEARANCE_MAPPING: variables.get(APPEARANCE_MAPPING),\n            },\n            progress_percent=min(78",
        ),
        (
            "                SCRIPT_START_EPISODE: batch.start_episode,\n                SCRIPT_MEMORY: script_memory,\n                BATCH_CAUSAL_CONFLICT_PLAN: conflict_plan,\n",
            "                SCRIPT_START_EPISODE: batch.start_episode,\n                SCRIPT_MEMORY: script_memory,\n                BATCH_CAUSAL_CONFLICT_PLAN: conflict_plan,\n                BATCH_ENRICHED_EPISODE_PLAN: batch_enriched,\n                SCRIPT_WORLD_RULES_DIGEST: variables.get(SCRIPT_WORLD_RULES_DIGEST),\n                APPEARANCE_MAPPING: variables.get(APPEARANCE_MAPPING),\n",
        ),
        (
            "                BATCH_CAUSAL_CONFLICT_PLAN: conflict_plan,\n                BATCH_SCRIPT_TEXT: current,\n            },\n            rewrite_context_builder=lambda current, review: {\n",
            "                BATCH_CAUSAL_CONFLICT_PLAN: conflict_plan,\n                BATCH_ENRICHED_EPISODE_PLAN: batch_enriched,\n                APPEARANCE_MAPPING: variables.get(APPEARANCE_MAPPING),\n                BATCH_SCRIPT_TEXT: current,\n            },\n            rewrite_context_builder=lambda current, review: {\n",
        ),
        (
            "                BATCH_CAUSAL_CONFLICT_PLAN: conflict_plan,\n                BATCH_SCRIPT_TEXT: current,\n                BATCH_SCRIPT_REVIEW: json.dumps(review, ensure_ascii=False),\n",
            "                BATCH_CAUSAL_CONFLICT_PLAN: conflict_plan,\n                BATCH_ENRICHED_EPISODE_PLAN: batch_enriched,\n                SCRIPT_WORLD_RULES_DIGEST: variables.get(SCRIPT_WORLD_RULES_DIGEST),\n                APPEARANCE_MAPPING: variables.get(APPEARANCE_MAPPING),\n                BATCH_SCRIPT_TEXT: current,\n                BATCH_SCRIPT_REVIEW: json.dumps(review, ensure_ascii=False),\n",
        ),
    ]
    for old, new in replacements:
        if old in text and new not in text:
            text = text.replace(old, new, 1)

    if text != original:
        write_text(ORCH, text)
        print("[PATCHED]", ORCH)
    else:
        print("[NO CHANGE]", ORCH)

def patch_json_files() -> None:
    # Convert every JSON under BETTER_FRAMEWORK_JSONS to UTF-8 without BOM if loadable.
    for path in JSON_ROOT.rglob("*.json"):
        try:
            obj = load_json(path)
        except Exception as exc:
            print("[JSON SKIP]", path, exc)
            continue
        backup(path)
        write_json(path, obj)

    # Patch 10 enriched workflow.
    p10, obj10 = find_json_by_predicate(
        lambda p, obj, text: "ai10EnrichedEpisodePlan" in text or "allEnrichedEpisodePlanText" in text
    )
    if p10 and obj10:
        changed = False
        backup(p10)

        changed |= add_chat_variable(obj10, {
            "type": "internal",
            "key": "enrichedEpisodePlanResult",
            "label": "10阶段完整丰富分集计划结果",
            "valueType": "string",
            "description": "10 阶段完整 JSON 字符串，顶层包含 allEnrichedEpisodePlan 和 allEnrichedEpisodePlanText。",
            "required": False,
            "defaultValue": "",
            "icon": "core/workflow/inputType/internal"
        })

        for node in walk_nodes(obj10):
            if node.get("flowNodeType") == "variableUpdate":
                for inp in node.get("inputs", []):
                    if inp.get("key") != "updateList":
                        continue
                    for item in inp.get("value", []):
                        if item.get("variable") == ["VARIABLE_NODE_ID", "allEnrichedEpisodePlan"] and item.get("value") == ["ai10EnrichedEpisodePlan", "answerText"]:
                            item["variable"] = ["VARIABLE_NODE_ID", "enrichedEpisodePlanResult"]
                            changed = True

            if node.get("flowNodeType") == "answerNode":
                for inp in node.get("inputs", []):
                    if inp.get("value") == ["VARIABLE_NODE_ID", "allEnrichedEpisodePlan"]:
                        inp["value"] = ["VARIABLE_NODE_ID", "enrichedEpisodePlanResult"]
                        changed = True

        if changed:
            write_json(p10, obj10)
            print("[PATCHED JSON 10]", p10)
        else:
            print("[JSON 10 NO CHANGE]", p10)
    else:
        print("[WARN] 未找到 10 丰富分集计划 JSON。")

    # Patch script review 02: add appearanceMapping variable and prompt input.
    p02, obj02 = find_json_by_predicate(
        lambda p, obj, text: ("batchScriptReview" in text and "batchScriptText" in text and "batchCausalConflictPlan" in text)
    )
    if p02 and obj02:
        backup(p02)
        changed = False
        changed |= add_chat_variable(obj02, {
            "type": "input",
            "key": "appearanceMapping",
            "label": "人设服装alias映射",
            "valueType": "string",
            "description": "用于审核正文 alias、服装状态、身份称呼是否符合 09 阶段映射。",
            "required": False,
            "defaultValue": "",
            "icon": "core/workflow/inputType/input"
        })

        for node in walk_nodes(obj02):
            if node.get("flowNodeType") not in ("chatNode", "tools"):
                continue
            for inp in node.get("inputs", []):
                if inp.get("key") != "systemPrompt":
                    continue
                prompt = inp.get("value") or ""
                if "{{$VARIABLE_NODE_ID.appearanceMapping$}}" not in prompt:
                    marker = "【当前批次剧本正文】"
                    insert = "【人设服装alias映射】\n{{$VARIABLE_NODE_ID.appearanceMapping$}}\n\n"
                    if marker in prompt:
                        prompt = prompt.replace(marker, insert + marker, 1)
                    else:
                        prompt += "\n\n" + insert
                    inp["value"] = prompt
                    changed = True

        if changed:
            write_json(p02, obj02)
            print("[PATCHED SCRIPT REVIEW JSON]", p02)
        else:
            print("[SCRIPT REVIEW JSON NO CHANGE]", p02)
    else:
        print("[WARN] 未找到正文审核 02 JSON。")

patch_orchestrator()
patch_json_files()
print("DONE")
