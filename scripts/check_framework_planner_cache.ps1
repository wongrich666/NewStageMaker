param(
  [string]$ProjectName = "Cache 链路/测试:网页?",
  [string]$ProjectId = "cache-debug-test"
)

$ErrorActionPreference = "Stop"
$env:FRAMEWORK_PLANNER_USE_MOCK = "true"
$env:PYTHONIOENCODING = "utf-8"
$probeConfigJson = @{ project_name = $ProjectName; project_id = $ProjectId } | ConvertTo-Json -Compress
$env:FRAMEWORK_CACHE_PROBE_CONFIG_B64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($probeConfigJson))

@"
import base64
import json
import os
import re
import uuid
from pathlib import Path

from workflow_code_skeleton.app.server import create_app
from workflow_code_skeleton.app.services.auth_store import auth_store

config = json.loads(base64.b64decode(os.environ["FRAMEWORK_CACHE_PROBE_CONFIG_B64"]).decode("utf-8"))
project_name = config["project_name"]
project_id = config["project_id"]
repo = Path.cwd()

def safe_project_history_name(value):
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
    text = re.sub(r"\s+", "_", text).strip("._ ")
    return text[:80] or "未命名项目"

project_cache_name = safe_project_history_name(project_name)
cache_dir = repo / "cache" / project_cache_name
logs_dir = repo / "logs" / project_cache_name
debug_dir = repo / "debug" / project_cache_name

app = create_app()
client = app.test_client()
user = auth_store.register_user(f"cache_probe_{uuid.uuid4().hex[:8]}", "password123")
token = auth_store.create_session_token(user.id)
headers = {"Authorization": f"Bearer {token}"}

basic_config = {
    "project_title": project_name,
    "title": project_name,
    "source_title": project_name,
    "mode": "create",
    "source_text": "A lawyer returns to his hometown to investigate his father's death and a local consortium.",
    "target_format": "short drama",
    "season_count": 1,
    "episodes_per_season": 60,
    "minutes_per_episode": 2,
    "adaptation_direction": "strong reversals",
    "user_constraints": "",
    "user_requirements": "tight pacing",
}

common = {
    "project_id": project_id,
    "project_title": project_name,
    "title": project_name,
    "source_title": project_name,
}

state = {}

def post_stage(stage, payload):
    merged = {**common, **payload}
    response = client.post(f"/api/framework-planner/stage/{stage}", headers=headers, json=merged)
    data = response.get_json() or {}
    print(f"stage {stage} status={response.status_code} ok={data.get('ok')} history={data.get('history')}")
    if response.status_code >= 400 or not data.get("ok"):
        print(json.dumps(data, ensure_ascii=False, indent=2))
        raise SystemExit(f"stage {stage} failed")
    state.update(data.get("data") or {})
    return data

post_stage("01", {**basic_config})
post_stage("02", {
    "mode": "create",
    "basic_config": basic_config,
    "locked_basic_config": basic_config,
    "source_brief": state["source_brief"],
})
post_stage("03", {
    "mode": "create",
    "basic_config": basic_config,
    "locked_basic_config": basic_config,
    "source_brief": state["source_brief"],
    "worldview_plan": state["worldview_plan"],
})
post_stage("04", {
    "mode": "create",
    "basic_config": basic_config,
    "source_brief": state["source_brief"],
    "worldview_plan": state["worldview_plan"],
    "character_plan": state["character_plan"],
})
post_stage("05", {
    "mode": "create",
    "basic_config": basic_config,
    "source_brief": state["source_brief"],
    "worldview_plan": state["worldview_plan"],
    "character_plan": state["character_plan"],
    "beat_checkpoint_timeline": state["beat_checkpoint_timeline"],
})
post_stage("06", {
    "mode": "create",
    "basic_config": basic_config,
    "source_brief": state["source_brief"],
    "worldview_plan": state["worldview_plan"],
    "character_plan": state["character_plan"],
    "beat_checkpoint_timeline": state["beat_checkpoint_timeline"],
    "character_storylines": state["character_storylines"],
    "storyline_decisions": state.get("storyline_decisions", []),
})
post_stage("07", {
    "mode": "create",
    "basic_config": basic_config,
    "source_brief": state["source_brief"],
    "worldview_plan": state["worldview_plan"],
    "character_plan": state["character_plan"],
    "beat_checkpoint_timeline": state["beat_checkpoint_timeline"],
    "checkpoint_explanation": state.get("checkpoint_explanation", {}),
    "character_storylines": state["character_storylines"],
    "storyline_decisions": state.get("storyline_decisions", []),
    "adaptation_guide": state["adaptation_guide"],
    "user_edit_history": [],
})

failure = client.post(
    "/api/framework-planner/stage/99",
    headers=headers,
    json={"project_id": project_id, "basic_config": {"project_title": project_name}},
)
failure_data = failure.get_json() or {}
print(f"failure probe stage 99 status={failure.status_code} ok={failure_data.get('ok')}")
if failure.status_code < 400:
    print(json.dumps(failure_data, ensure_ascii=False, indent=2))
    raise SystemExit("failure probe unexpectedly succeeded")

required_cache = [
    cache_dir / "latest_stage01.json",
    cache_dir / "latest_stage02.json",
    cache_dir / "latest_stage03.json",
    cache_dir / "latest_stage04.json",
    cache_dir / "latest_stage05.json",
    cache_dir / "latest_stage06.json",
    cache_dir / "latest_stage07.json",
    cache_dir / "stage01_debug.txt",
    cache_dir / "stage07_debug.txt",
]
missing = [str(path) for path in required_cache if not path.exists()]
if missing:
    print("missing cache files:")
    print("\n".join(missing))
    raise SystemExit(2)
if not logs_dir.exists() or not list(logs_dir.glob("*.json")):
    raise SystemExit(f"missing failure log json under {logs_dir}")

history_response = client.get(
    f"/api/framework-planner/history?project_id={project_cache_name}&stage=07",
    headers=headers,
)
history_data = history_response.get_json() or {}
history_entries = history_data.get("entries") or []
print(f"history list status={history_response.status_code} entries={len(history_entries)}")
if history_response.status_code != 200 or not history_entries:
    print(json.dumps(history_data, ensure_ascii=False, indent=2))
    raise SystemExit("history list probe failed")

history_file = history_entries[0]["filename"]
load_response = client.get(
    f"/api/framework-planner/history/{project_cache_name}/{history_file}",
    headers=headers,
)
load_data = load_response.get_json() or {}
print(f"history load status={load_response.status_code} filename={history_file}")
if load_response.status_code != 200 or not load_data.get("record"):
    print(json.dumps(load_data, ensure_ascii=False, indent=2))
    raise SystemExit("history load probe failed")

print("\nCACHE DIR:", cache_dir)
for path in sorted(cache_dir.glob("*")):
    print("  ", path.name)
print("\nLOGS DIR:", logs_dir)
for path in sorted(logs_dir.glob("*")):
    print("  ", path.name)
print("\nDEBUG DIR:", debug_dir)
for path in sorted(debug_dir.glob("*")):
    print("  ", path.name)
print("\nOK: cache/debug/logs are visible for", project_name, "=>", project_cache_name)
"@ | python -

if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
