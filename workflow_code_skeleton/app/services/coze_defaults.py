from __future__ import annotations

DEFAULT_NS_API_BASE = "https://api.coze.cn"
DEFAULT_NS_WORKFLOW_URL = f"{DEFAULT_NS_API_BASE}/v1/workflow/run"
DEFAULT_NS_TIMEOUT_SECONDS = 600
DEFAULT_NS_HTTP_RETRIES = 2
DEFAULT_NS_HTTP_RETRY_DELAY_SECONDS = 1.5

FRAMEWORK_PLANNER_WORKFLOW_IDS: dict[str, str] = {
    "01": "7649223965336977414",
    "02": "7649224680113045550",
    "03": "7649224688775233599",
    "04": "7649224734810538034",
    "05": "7649224433361666099",
    "06": "7649224316324331566",
    "07": "7649224473841696795",
}

FRAMEWORK_TO_SCRIPT_WORKFLOW_IDS: dict[str, str] = {
    "scene_dictionary": "7649224585556541503",
    "appearance_mapping": "7649224607433703459",
    "enriched_episode_plan": "7649223990464888838",
    "causal_conflict_write": "7649224407571415075",
    "causal_conflict_review": "7649224344941969471",
    "causal_conflict_rewrite": "7649224129539063849",
    "causal_conflict_memory": "7649224299781423138",
    "script_write": "7649224164747067427",
    "script_review": "7649224020924481563",
    "script_rewrite": "7649224078767833088",
    "script_memory": "7649224056521195539",
}
