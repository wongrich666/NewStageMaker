from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

from ..utils.logger import get_logger
# The contract/extraction layer still lives in fastgpt_client, but HTTP runtime
# for this client is Coze-only.
from .fastgpt_client import FastGPTClient, FastGPTStageFormatError
from .fastgpt_contracts import (
    ALL_ENRICHED_EPISODE_PLAN,
    APPEARANCE_MAPPING,
    BATCH_CAUSAL_CONFLICT_PLAN,
    BATCH_CAUSAL_CONFLICT_REVIEW,
    BATCH_ENRICHED_EPISODE_PLAN,
    BATCH_SCRIPT_REVIEW,
    BATCH_SCRIPT_TEXT,
    BEAT_CHECKPOINT_TIMELINE,
    BLOCKING_ISSUES,
    CHARACTER_PLAN,
    CHARACTER_STORYLINES,
    CONFLICT_MEMORY,
    CONFLICT_START_EPISODE,
    EPISODE_WORD_COUNT,
    FRAMEWORK_PLAN_PACKAGE,
    REVIEW_PASSED,
    REWRITE_REQUIRED,
    SCENE_DICTIONARY,
    SCRIPT_MEMORY,
    SCRIPT_START_EPISODE,
    SCRIPT_WORLD_RULES_DIGEST,
    STAGE_FRAMEWORK_APPEARANCE_MAPPING,
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_MEMORY,
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_REVIEW,
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_REWRITE,
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE,
    STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN,
    STAGE_FRAMEWORK_SCENE_DICTIONARY,
    STAGE_FRAMEWORK_SCRIPT_MEMORY,
    STAGE_FRAMEWORK_SCRIPT_REVIEW,
    STAGE_FRAMEWORK_SCRIPT_REWRITE,
    STAGE_FRAMEWORK_SCRIPT_WRITE,
    TOTAL_EPISODES,
    WORLDVIEW_PLAN,
    FastGPTStageContract,
    contract_for,
    to_jsonable_value,
)
from .workflow_output_parser import (
    parse_workflow_output,
    safe_truncated_preview,
    wrap_payload_for_expected_output,
)

logger = get_logger("coze_client")

DEFAULT_COZE_WORKFLOW_URL = "https://api.coze.cn/v1/workflow/run"
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}

PREFERENCE_SOURCE_KEYS = (
    "user_feedback",
    "stagePreference",
    "stage_preference",
    "stage_preference_prompt",
    "user_stage_preference_prompt",
    "user_preference_prompt",
    "user_preferences",
    "userPreferences",
    "userRequirements",
    "user_requirements",
    "user_constraints",
)


@dataclass(frozen=True, slots=True)
class CozeEndpoint:
    url: str
    url_source: str
    token: str
    token_source: str
    workflow_id: str
    workflow_id_source: str
    timeout: int


COZE_STAGE_WORKFLOW_ID_ENVS: dict[str, tuple[str, ...]] = {
    STAGE_FRAMEWORK_SCENE_DICTIONARY: ("COZE_WORKFLOW_STAGE_08_ID",),
    STAGE_FRAMEWORK_APPEARANCE_MAPPING: ("COZE_WORKFLOW_STAGE_09_ID",),
    STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN: ("COZE_WORKFLOW_STAGE_10_ID",),
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE: ("COZE_WORKFLOW_STAGE_11_WRITE_ID",),
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_REVIEW: ("COZE_WORKFLOW_STAGE_11_REVIEW_ID",),
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_REWRITE: ("COZE_WORKFLOW_STAGE_11_REWRITE_ID",),
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_MEMORY: ("COZE_WORKFLOW_STAGE_11_MEMORY_ID",),
    STAGE_FRAMEWORK_SCRIPT_WRITE: ("COZE_WORKFLOW_STAGE_12_WRITE_ID",),
    STAGE_FRAMEWORK_SCRIPT_REVIEW: ("COZE_WORKFLOW_STAGE_12_REVIEW_ID",),
    STAGE_FRAMEWORK_SCRIPT_REWRITE: ("COZE_WORKFLOW_STAGE_12_REWRITE_ID",),
    STAGE_FRAMEWORK_SCRIPT_MEMORY: ("COZE_WORKFLOW_STAGE_12_MEMORY_ID",),
}

COZE_STAGE_INPUT_SOURCES: dict[str, dict[str, tuple[str, ...]]] = {
    STAGE_FRAMEWORK_SCENE_DICTIONARY: {
        "framework": (FRAMEWORK_PLAN_PACKAGE,),
        "worldview": (WORLDVIEW_PLAN,),
        "beat": (BEAT_CHECKPOINT_TIMELINE,),
        "character_storyline": (CHARACTER_STORYLINES,),
        "user_feedback": PREFERENCE_SOURCE_KEYS,
        "user_requirements": ("user_requirements", "userRequirements"),
    },
    STAGE_FRAMEWORK_APPEARANCE_MAPPING: {
        "framework": (FRAMEWORK_PLAN_PACKAGE,),
        "character": (CHARACTER_PLAN,),
        "scene": (SCENE_DICTIONARY,),
        "beat": (BEAT_CHECKPOINT_TIMELINE,),
        "user_feedback": PREFERENCE_SOURCE_KEYS,
    },
    STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN: {
        "framework": (FRAMEWORK_PLAN_PACKAGE,),
        "scene": (SCENE_DICTIONARY,),
        "alias": (APPEARANCE_MAPPING,),
        "user_feedback": PREFERENCE_SOURCE_KEYS,
    },
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE: {
        "episode_num": (TOTAL_EPISODES,),
        "start_epi": (CONFLICT_START_EPISODE,),
        "enriched_epiplan": (BATCH_ENRICHED_EPISODE_PLAN,),
        "scene": (SCENE_DICTIONARY,),
        "worldview": (SCRIPT_WORLD_RULES_DIGEST, WORLDVIEW_PLAN),
        "alias": (APPEARANCE_MAPPING,),
        "memory": (CONFLICT_MEMORY,),
        "user_feedback": PREFERENCE_SOURCE_KEYS,
    },
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_REVIEW: {
        "episode_num": (TOTAL_EPISODES,),
        "start_epi": (CONFLICT_START_EPISODE,),
        "enriched_epiplan": (BATCH_ENRICHED_EPISODE_PLAN,),
        "scene": (SCENE_DICTIONARY,),
        "worldview": (SCRIPT_WORLD_RULES_DIGEST, WORLDVIEW_PLAN),
        "alias": (APPEARANCE_MAPPING,),
        "memory": (CONFLICT_MEMORY,),
        "conflict": (BATCH_CAUSAL_CONFLICT_PLAN,),
        "user_feedback": PREFERENCE_SOURCE_KEYS,
    },
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_REWRITE: {
        "episode_num": (TOTAL_EPISODES,),
        "start_epi": (CONFLICT_START_EPISODE,),
        "enriched_epiplan": (BATCH_ENRICHED_EPISODE_PLAN,),
        "scene": (SCENE_DICTIONARY,),
        "alias": (APPEARANCE_MAPPING,),
        "memory": (CONFLICT_MEMORY,),
        "conflict": (BATCH_CAUSAL_CONFLICT_PLAN,),
        "review": (BATCH_CAUSAL_CONFLICT_REVIEW,),
        "feedback": PREFERENCE_SOURCE_KEYS,
        "user_feedback": PREFERENCE_SOURCE_KEYS,
    },
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_MEMORY: {
        "conflict": (BATCH_CAUSAL_CONFLICT_PLAN,),
        "start_epi": (CONFLICT_START_EPISODE,),
    },
    STAGE_FRAMEWORK_SCRIPT_WRITE: {
        "episode_num": (TOTAL_EPISODES,),
        "start_epi": (SCRIPT_START_EPISODE,),
        "character_count": (EPISODE_WORD_COUNT,),
        "according_epiplan": (BATCH_ENRICHED_EPISODE_PLAN,),
        "according_conflict": (BATCH_CAUSAL_CONFLICT_PLAN,),
        "worldview": (SCRIPT_WORLD_RULES_DIGEST, WORLDVIEW_PLAN),
        "alias": (APPEARANCE_MAPPING,),
        "memory": (SCRIPT_MEMORY,),
        "user_feedback": PREFERENCE_SOURCE_KEYS,
    },
    STAGE_FRAMEWORK_SCRIPT_REVIEW: {
        "episode_num": (TOTAL_EPISODES,),
        "start_epi": (SCRIPT_START_EPISODE,),
        "character_count": (EPISODE_WORD_COUNT,),
        "according_epiplan": (BATCH_ENRICHED_EPISODE_PLAN,),
        "according_conflict": (BATCH_CAUSAL_CONFLICT_PLAN,),
        "memory": (SCRIPT_MEMORY,),
        "script": (BATCH_SCRIPT_TEXT,),
        "user_feedback": PREFERENCE_SOURCE_KEYS,
    },
    STAGE_FRAMEWORK_SCRIPT_REWRITE: {
        "episode_num": (TOTAL_EPISODES,),
        "start_epi": (SCRIPT_START_EPISODE,),
        "character_count": (EPISODE_WORD_COUNT,),
        "according_epiplan": (BATCH_ENRICHED_EPISODE_PLAN,),
        "according_conflict": (BATCH_CAUSAL_CONFLICT_PLAN,),
        "worldview": (SCRIPT_WORLD_RULES_DIGEST, WORLDVIEW_PLAN),
        "alias": (APPEARANCE_MAPPING,),
        "memory": (SCRIPT_MEMORY,),
        "current_script": (BATCH_SCRIPT_TEXT,),
        "current_review": (BATCH_SCRIPT_REVIEW,),
        "user_feedback": PREFERENCE_SOURCE_KEYS,
    },
    STAGE_FRAMEWORK_SCRIPT_MEMORY: {
        "script": (BATCH_SCRIPT_TEXT,),
    },
}

COZE_OUTPUT_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    STAGE_FRAMEWORK_SCENE_DICTIONARY: {
        SCENE_DICTIONARY: ("output", "sceneDictionary"),
        SCRIPT_WORLD_RULES_DIGEST: ("output", "scriptWorldRulesDigest"),
    },
    STAGE_FRAMEWORK_APPEARANCE_MAPPING: {
        APPEARANCE_MAPPING: ("alias", "appearanceMapping"),
    },
    STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN: {
        # Coze 的结束节点会返回 {"episodeplan": "...json string..."}。
        # episodeplan 是外壳变量名，不是 allEnrichedEpisodePlan 本身。
        # 因此这里不再把 episodeplan 注册为字段别名，避免把整个业务 JSON 当成单集/数组字段。
        ALL_ENRICHED_EPISODE_PLAN: (
            "allEnrichedEpisodePlan",
            "enrichedEpisodePlan",
            "all_enriched_episode_plan",
            "enriched_episode_plan",
        ),
        "allEnrichedEpisodePlanText": (
            "allEnrichedEpisodePlanText",
            "enrichedEpisodePlanText",
            "all_enriched_episode_plan_text",
            "enriched_episode_plan_text",
        ),
    },
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_WRITE: {
        BATCH_CAUSAL_CONFLICT_PLAN: ("conflicts", "batchCausalConflictPlan"),
    },
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_REVIEW: {
        REVIEW_PASSED: ("conflictreview", "passed", "approved"),
        REWRITE_REQUIRED: ("conflictreview", "rewrite_required"),
        BLOCKING_ISSUES: ("conflictreview", "blocking_issues"),
    },
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_REWRITE: {
        BATCH_CAUSAL_CONFLICT_PLAN: ("rewrite", "batchCausalConflictPlan"),
    },
    STAGE_FRAMEWORK_CAUSAL_CONFLICT_MEMORY: {
        CONFLICT_MEMORY: ("memory",),
    },
    STAGE_FRAMEWORK_SCRIPT_WRITE: {
        BATCH_SCRIPT_TEXT: ("script",),
    },
    STAGE_FRAMEWORK_SCRIPT_REVIEW: {
        REVIEW_PASSED: ("scriptreview", "passed", "approved"),
        REWRITE_REQUIRED: ("scriptreview", "rewrite_required"),
        BLOCKING_ISSUES: ("scriptreview", "blocking_issues"),
    },
    STAGE_FRAMEWORK_SCRIPT_REWRITE: {
        BATCH_SCRIPT_TEXT: ("script",),
    },
    STAGE_FRAMEWORK_SCRIPT_MEMORY: {
        SCRIPT_MEMORY: ("script",),
    },
}


class CozeWorkflowClient(FastGPTClient):
    """Coze workflow runner with the same public interface as FastGPTClient."""

    def run_stage(self, stage_name: str, variables: dict[str, Any]) -> dict[str, Any]:
        base_contract = contract_for(stage_name)
        base_contract.build_input_payload(variables)
        contract = _coze_contract_for(stage_name, base_contract)
        endpoint = self._endpoint_for_coze(stage_name)
        parameters = self._build_coze_parameters(stage_name, variables)
        body = {
            "workflow_id": endpoint.workflow_id,
            "parameters": parameters,
        }

        if stage_name == "framework_script_write":
            expected_params = {
                "episode_num",
                "start_epi",
                "character_count",
                "according_conflict",
                "according_epiplan",
                "worldview",
                "alias",
                "memory",
                "user_feedback",
            }
            actual_params = set(parameters.keys()) if isinstance(parameters, dict) else set()
            missing_params = sorted(expected_params - actual_params)
            empty_params = sorted([
                key for key, value in (parameters or {}).items()
                if value is None or value == "" or value == [] or value == {}
            ])

            logger.warning(
                "[COZE REQUEST DEBUG] stage=%s workflow_id=%r param_keys=%s missing_expected=%s empty_params=%s param_types=%s param_preview=%s",
                stage_name,
                endpoint.workflow_id,
                sorted(actual_params),
                missing_params,
                empty_params,
                {key: type(value).__name__ for key, value in (parameters or {}).items()},
                safe_truncated_preview(parameters, limit=3000),
            )

        headers = {
            "Authorization": f"Bearer {endpoint.token}",
            "Content-Type": "application/json",
        }
        response = self._post_with_retries(endpoint, headers, body, stage_name)
        try:
            response_json = response.json()
        except ValueError:
            response_json = str(getattr(response, "text", "") or "")
            if not response_json.strip():
                raise RuntimeError(f"Coze stage {stage_name} returned empty non-JSON response")

        _raise_for_coze_error(stage_name, response_json)

        # Keep the raw Coze response before parsing.
        # Stage10 may raise during strict episodeplan parsing; the server still needs
        # execute_id/debug_url/raw response for diagnosis.
        self._remember_stage_debug_info(
            stage_name,
            status="coze_response_received",
            raw_response=response_json,
            response_preview=safe_truncated_preview(response_json, limit=2000),
            conversation_log_available=False,
        )

        extraction_payload = _coze_response_as_fastgpt_payload(response_json, contract)
        raw_output = self._extract_output_payload(
            extraction_payload,
            contract,
            variables,
            allow_fallback=False,
        )
        try:
            validated_output = contract.validate_output_payload(raw_output)
        except ValueError as exc:
            debug_info = self.get_last_stage_debug_info(stage_name)
            logger.warning(
                "Coze stage output validation failed: stage=%s expected=%s reason=%s response_preview=%s",
                stage_name,
                list(contract.output_names),
                exc,
                safe_truncated_preview(response_json, limit=1000),
            )
            raise FastGPTStageFormatError(
                stage_name=stage_name,
                expected_fields=contract.output_names,
                failure_reason=str(exc),
                candidate_sources=debug_info.get("candidate_sources", []),
                matched_fields=debug_info.get("matched_fields", []),
                missing_fields=debug_info.get("missing_fields", list(contract.output_names)),
                answer_text_preview=str(debug_info.get("answer_text_preview") or ""),
                response_preview=safe_truncated_preview(response_json, limit=1000),
                raw_output_source=str(debug_info.get("raw_output_source") or "coze"),
            ) from exc

        if stage_name == STAGE_FRAMEWORK_APPEARANCE_MAPPING and isinstance(raw_output, dict):
            validated_output = raw_output

        self._remember_stage_debug_info(
            stage_name,
            status="validated",
            raw_response=response_json,
            output_keys=sorted(validated_output.keys()),
            response_preview=safe_truncated_preview(response_json, limit=1000),
            conversation_log_available=False,
            last_failure_reason="",
        )
        return validated_output

    def _build_coze_parameters(self, stage_name: str, variables: dict[str, Any]) -> dict[str, Any]:
        mapping = COZE_STAGE_INPUT_SOURCES.get(stage_name)
        if not mapping:
            raise ValueError(f"Coze workflow stage is not mapped: {stage_name}")
        payload: dict[str, Any] = {}
        for wire_name, source_keys in mapping.items():
            value = _first_present_value(variables, source_keys)
            if value in (None, "", [], {}):
                if wire_name in {"memory", "feedback", "user_feedback", "user_requirements"}:
                    value = ""
                else:
                    continue
            payload[wire_name] = _format_coze_value(value)
        return payload

    def _endpoint_for_coze(self, stage_name: str) -> CozeEndpoint:
        token_source, token = _coze_token_with_name()
        if not token:
            raise ValueError("Missing Coze API token. Configure COZE_*_API_TOKEN in workflow_code_skeleton/.env")
        workflow_source, workflow_id = _env_with_name(*COZE_STAGE_WORKFLOW_ID_ENVS.get(stage_name, ()))
        if not workflow_id:
            expected = ", ".join(COZE_STAGE_WORKFLOW_ID_ENVS.get(stage_name, ()))
            raise ValueError(f"Missing Coze workflow id for {stage_name}. Expected env: {expected}")
        url_source, raw_url = _coze_api_base_with_name(token_source)
        return CozeEndpoint(
            url=_normalize_coze_workflow_url(raw_url or DEFAULT_COZE_WORKFLOW_URL),
            url_source=url_source or "default",
            token=token,
            token_source=token_source,
            workflow_id=workflow_id,
            workflow_id_source=workflow_source,
            timeout=int(_env("COZE_TIMEOUT_SECONDS") or 600),
        )

    def _post_with_retries(
        self,
        endpoint: CozeEndpoint,
        headers: dict[str, str],
        body: dict[str, Any],
        stage_name: str,
    ) -> requests.Response:
        attempts = max(1, int(_env("COZE_HTTP_RETRIES") or 2) + 1)
        delay = max(0.0, float(_env("COZE_HTTP_RETRY_DELAY") or 1.5))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = requests.post(endpoint.url, headers=headers, json=body, timeout=endpoint.timeout)
                if response.status_code in RETRYABLE_HTTP_STATUSES and attempt < attempts:
                    time.sleep(delay * attempt)
                    continue
                if response.status_code >= 400:
                    preview = safe_truncated_preview(getattr(response, "text", "") or "", limit=1000)
                    raise RuntimeError(
                        f"Coze stage {stage_name} returned HTTP {response.status_code}: {preview}"
                    )
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= attempts:
                    raise RuntimeError(f"Coze stage {stage_name} request failed: {exc}") from exc
                time.sleep(delay * attempt)
        raise RuntimeError(f"Coze stage {stage_name} request failed: {last_error}")


def _coze_contract_for(stage_name: str, contract: FastGPTStageContract) -> FastGPTStageContract:
    extra_aliases = COZE_OUTPUT_ALIASES.get(stage_name, {})
    output_aliases: dict[str, tuple[str, ...]] = {}
    for field_name in contract.output_names:
        merged = (
            *contract.aliases_for_output(field_name),
            *extra_aliases.get(field_name, ()),
        )
        output_aliases[field_name] = tuple(dict.fromkeys(str(item) for item in merged if str(item).strip()))
    return FastGPTStageContract(
        stage_name=contract.stage_name,
        label=contract.label,
        input_names=contract.input_names,
        output_types=contract.output_types,
        fastgpt_responsibility=contract.fastgpt_responsibility,
        local_responsibility=contract.local_responsibility,
        output_aliases=output_aliases,
        expected_output_kind=contract.expected_output_kind,
        workflow_json_name=contract.workflow_json_name,
    )


def _coze_response_as_fastgpt_payload(response_json: Any, contract: FastGPTStageContract) -> dict[str, Any]:
    # Stage10 的 Coze 结束节点形态是：
    # {"episodeplan": "{\"allEnrichedEpisodePlan\":[...],\"allEnrichedEpisodePlanText\":\"...\"}"}
    # episodeplan 是变量外壳；真正业务字段在字符串内部。
    # 必须先拆 episodeplan，再交给 FastGPTClient 的契约校验层。
    if contract.stage_name == STAGE_FRAMEWORK_ENRICHED_EPISODE_PLAN:
        stage10_payload = _extract_stage10_episodeplan_payload_from_coze_response(response_json)
        if isinstance(stage10_payload, dict) and stage10_payload.get(ALL_ENRICHED_EPISODE_PLAN):
            answer_text = json.dumps(stage10_payload, ensure_ascii=False, default=str)
            return {
                "answerText": answer_text,
                "textOutput": answer_text,
                "newVariables": dict(stage10_payload),
                "responseData": {
                    "answerText": answer_text,
                    "textOutput": answer_text,
                    "variables": dict(stage10_payload),
                },
                **stage10_payload,
            }

    parsed = parse_workflow_output(response_json)
    returned = wrap_payload_for_expected_output(
        parsed,
        output_names=contract.output_names,
        output_aliases=contract.output_aliases,
        output_types=contract.output_types,
        stage_name=contract.stage_name,
    )
    flattened = _flatten_return_variables(returned, output_types=contract.output_types)
    answer_text = _coze_answer_text(flattened, returned)
    return {
        "answerText": answer_text,
        "textOutput": answer_text,
        "newVariables": flattened,
        "responseData": {
            "answerText": answer_text,
            "textOutput": answer_text,
            "variables": flattened,
        },
        **flattened,
    }


_STAGE10_EPISODEPLAN_CONTAINER_KEYS = (
    "episodeplan",
    "episodePlan",
    "episode_plan",
)
_STAGE10_PLAN_KEYS = (
    ALL_ENRICHED_EPISODE_PLAN,
    "enrichedEpisodePlan",
    "all_enriched_episode_plan",
    "enriched_episode_plan",
    BATCH_ENRICHED_EPISODE_PLAN,
    "batch_enriched_episode_plan",
)
_STAGE10_TEXT_KEYS = (
    "allEnrichedEpisodePlanText",
    "enrichedEpisodePlanText",
    "all_enriched_episode_plan_text",
    "enriched_episode_plan_text",
)
_STAGE10_SEARCH_KEYS = (
    "data",
    "result",
    "output",
    "outputs",
    "response",
    "responseData",
    "newVariables",
    "variables",
    "answerText",
    "textOutput",
    "text",
    "content",
)


def _extract_stage10_episodeplan_payload_from_coze_response(response_json: Any) -> dict[str, Any] | None:
    """Extract Stage10 business payload from Coze's episodeplan wrapper.

    Coze may return:
      {"episodeplan": "{\"allEnrichedEpisodePlan\":[...], ...}"}

    The wrapper name episodeplan is not the business field itself.
    """
    saw_stage10_business_text = False

    for candidate in _iter_stage10_candidate_values(response_json):
        if isinstance(candidate, str) and (
            "allEnrichedEpisodePlan" in candidate
            or "all_enriched_episode_plan" in candidate
            or "enrichedEpisodePlan" in candidate
        ):
            saw_stage10_business_text = True

        normalized = _normalize_stage10_episodeplan_payload(candidate)
        if isinstance(normalized, dict) and normalized.get(ALL_ENRICHED_EPISODE_PLAN):
            plan = normalized.get(ALL_ENRICHED_EPISODE_PLAN)
            if isinstance(plan, list) and len(plan) == 1:
                # 如果原始文本明显包含多集迹象，但最后只解析出 1 集，说明很可能是截断 JSON 被抢救成单集。
                raw_text = json.dumps(response_json, ensure_ascii=False, default=str)
                if '"episode": 2' in raw_text or '\\"episode\\": 2' in raw_text or '"episode":2' in raw_text or '\\"episode\\":2' in raw_text:
                    raise ValueError(
                        "Stage10 Coze episodeplan 原始响应包含第2集迹象，但后端只解析出1集。"
                        "这通常表示 episodeplan JSON 字符串被截断或被宽松解析器错误抢救。"
                        "请检查 Coze 原始输出是否是完整合法 JSON，并提高输出上限或改为分批生成。"
                    )
            return normalized

    if saw_stage10_business_text:
        raise ValueError(
            "Stage10 Coze episodeplan 包含 allEnrichedEpisodePlan 文本，但不是完整合法 JSON，"
            "后端拒绝把截断 JSON 抢救成单集。请检查 Coze 原始输出是否被截断。"
        )

    return None


def _iter_stage10_candidate_values(value: Any, *, _depth: int = 0):
    if _depth > 8:
        return

    parsed = _parse_stage10_json_like(value)

    if isinstance(parsed, dict):
        # 最高优先级：先拆 Coze 结束节点的 episodeplan 外壳。
        for key in _STAGE10_EPISODEPLAN_CONTAINER_KEYS:
            actual_key = _stage10_find_key(parsed, key)
            if actual_key is not None and parsed.get(actual_key) not in (None, "", [], {}):
                yield parsed.get(actual_key)

        # 其次再尝试当前 dict 本身。它可能已经是业务 JSON。
        yield parsed

        # 最后遍历常见包装层。
        for key in _STAGE10_SEARCH_KEYS:
            actual_key = _stage10_find_key(parsed, key)
            if actual_key is None:
                continue
            nested_value = parsed.get(actual_key)
            if nested_value in (None, "", [], {}):
                continue
            yield from _iter_stage10_candidate_values(nested_value, _depth=_depth + 1)

    elif isinstance(parsed, list):
        yield parsed
        for item in parsed:
            yield from _iter_stage10_candidate_values(item, _depth=_depth + 1)


def _normalize_stage10_episodeplan_payload(value: Any) -> dict[str, Any] | None:
    parsed = _parse_stage10_json_like(value)

    if isinstance(parsed, list):
        plan = [item for item in parsed if isinstance(item, dict)]
        if plan:
            return {
                ALL_ENRICHED_EPISODE_PLAN: plan,
                "allEnrichedEpisodePlanText": _stage10_plan_text("", plan),
            }
        return None

    if not isinstance(parsed, dict):
        return None

    # 如果当前 dict 仍然有 episodeplan 外壳，先打开外壳。
    for key in _STAGE10_EPISODEPLAN_CONTAINER_KEYS:
        actual_key = _stage10_find_key(parsed, key)
        if actual_key is not None and parsed.get(actual_key) not in (None, "", [], {}):
            nested = _normalize_stage10_episodeplan_payload(parsed.get(actual_key))
            if isinstance(nested, dict) and nested.get(ALL_ENRICHED_EPISODE_PLAN):
                return nested

    plan_value = _stage10_first_present(parsed, _STAGE10_PLAN_KEYS)
    text_value = _stage10_first_present(parsed, _STAGE10_TEXT_KEYS)

    plan = _stage10_plan_list(plan_value)
    if plan:
        return {
            ALL_ENRICHED_EPISODE_PLAN: plan,
            "allEnrichedEpisodePlanText": _stage10_plan_text(text_value, plan),
        }

    # 最后兜底：如果 episodeplan 本身就是单集对象，才包成数组。
    # 这个兜底必须放在 allEnrichedEpisodePlan 解析之后，避免把完整业务 JSON 当成单集。
    if _stage10_looks_like_episode_item(parsed):
        plan = [parsed]
        return {
            ALL_ENRICHED_EPISODE_PLAN: plan,
            "allEnrichedEpisodePlanText": _stage10_plan_text(text_value, plan),
        }

    return None


def _stage10_plan_list(value: Any) -> list[dict[str, Any]]:
    parsed = _parse_stage10_json_like(value)

    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]

    if isinstance(parsed, dict):
        nested = _normalize_stage10_episodeplan_payload(parsed)
        if isinstance(nested, dict) and isinstance(nested.get(ALL_ENRICHED_EPISODE_PLAN), list):
            return [
                item for item in nested.get(ALL_ENRICHED_EPISODE_PLAN, [])
                if isinstance(item, dict)
            ]
        if _stage10_looks_like_episode_item(parsed):
            return [parsed]

    return []


def _parse_stage10_json_like(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value

    text = _strip_stage10_json_fence(value)
    if not text:
        return value

    # Stage10 的 episodeplan 是 Coze 变量外壳里的业务 JSON 字符串。
    # 这里必须严格解析；不能用 parse_workflow_output / parse_json 去“抢救”局部 JSON。
    # 否则多集 JSON 一旦被截断，通用解析器可能只捞出第一个完整 episode，
    # 导致后端误判为只有 1 集并保存成功。
    looks_like_stage10_business_json = (
        "allEnrichedEpisodePlan" in text
        or "all_enriched_episode_plan" in text
        or "enrichedEpisodePlan" in text
        or "allEnrichedEpisodePlanText" in text
    )

    candidates = [text]
    first_obj, last_obj = text.find("{"), text.rfind("}")
    first_arr, last_arr = text.find("["), text.rfind("]")

    if first_obj != -1 and last_obj > first_obj:
        candidates.append(text[first_obj:last_obj + 1])
    if first_arr != -1 and last_arr > first_arr:
        candidates.append(text[first_arr:last_arr + 1])

    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)

        try:
            return json.loads(candidate)
        except Exception:
            continue

    if looks_like_stage10_business_json:
        # 明确返回原字符串，让上层判定为不可消费；
        # 禁止继续走 parse_workflow_output 抢救第一集。
        return value

    # 非 Stage10 业务 JSON 的普通包装文本，才允许通用解析兜底。
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            parsed = parse_workflow_output(candidate)
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            pass

    return value


def _strip_stage10_json_fence(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return text


def _stage10_find_key(mapping: dict[str, Any], key: str) -> str | None:
    if key in mapping:
        return key
    lowered = key.lower()
    for existing_key in mapping.keys():
        if str(existing_key).lower() == lowered:
            return str(existing_key)
    return None


def _stage10_first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        actual_key = _stage10_find_key(mapping, key)
        if actual_key is None:
            continue
        value = mapping.get(actual_key)
        if value not in (None, "", [], {}):
            return value
    return None


def _stage10_looks_like_episode_item(value: Any) -> bool:
    if not isinstance(value, dict):
        return False

    lowered = {str(key).lower() for key in value.keys()}

    # 带有这些业务容器键的对象不是单集。
    container_keys = {
        str(key).lower()
        for key in (
            *_STAGE10_EPISODEPLAN_CONTAINER_KEYS,
            *_STAGE10_PLAN_KEYS,
            *_STAGE10_TEXT_KEYS,
        )
    }
    if lowered & container_keys:
        return False

    return bool(
        lowered
        & {
            "episode",
            "episodenumber",
            "episode_number",
            "title",
            "specific_plot",
            "text_view",
            "ending_hook",
        }
    )


def _stage10_plan_text(text_value: Any, plan: list[dict[str, Any]]) -> str:
    if isinstance(text_value, str) and text_value.strip():
        return text_value.strip()

    if isinstance(text_value, (dict, list)) and text_value:
        try:
            return json.dumps(text_value, ensure_ascii=False, default=str)
        except Exception:
            return str(text_value)

    parts: list[str] = []
    for item in plan:
        if not isinstance(item, dict):
            continue
        text = str(
            item.get("text_view")
            or item.get("textView")
            or item.get("episode_text")
            or item.get("episodeText")
            or ""
        ).strip()
        if text:
            parts.append(text)

    if parts:
        return "\n\n".join(parts)

    try:
        return json.dumps(plan, ensure_ascii=False, default=str)
    except Exception:
        return str(plan)


def _coze_answer_text(flattened: dict[str, Any], returned: Any) -> str:
    for key in ("script", BATCH_SCRIPT_TEXT):
        value = flattened.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return json.dumps(flattened or returned, ensure_ascii=False, default=str)


def _flatten_return_variables(value: Any, *, output_types: dict[str, str] | None = None) -> dict[str, Any]:
    parsed = value if isinstance(value, dict) else parse_workflow_output(value)
    if not isinstance(parsed, dict):
        return {}
    flattened: dict[str, Any] = {}
    for key, raw_value in parsed.items():
        if (
            isinstance(raw_value, str)
            and str((output_types or {}).get(str(key)) or "").lower() == "string"
        ):
            parsed_value = raw_value
        else:
            parsed_value = parse_workflow_output(raw_value)
        flattened[str(key)] = parsed_value
        if isinstance(parsed_value, dict):
            for nested_key, nested_value in parsed_value.items():
                flattened.setdefault(str(nested_key), nested_value)
    return flattened


def _raise_for_coze_error(stage_name: str, response_json: Any) -> None:
    if not isinstance(response_json, dict):
        return
    code = response_json.get("code")
    if code in (None, 0, "0"):
        return
    message = response_json.get("msg") or response_json.get("message") or response_json.get("detail")
    raise RuntimeError(f"Coze stage {stage_name} failed: code={code} message={message}")


def _first_present_value(values: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in values and values.get(key) not in (None, "", [], {}):
            return values.get(key)
    return None


def _format_coze_value(value: Any) -> Any:
    jsonable = to_jsonable_value(value)
    if isinstance(jsonable, (dict, list)):
        return json.dumps(jsonable, ensure_ascii=False)
    return jsonable


def _env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _env_with_name(*names: str) -> tuple[str, str]:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return name, str(value).strip()
    return "", ""


def _coze_token_env_names() -> tuple[str, ...]:
    configured_order = _env("COZE_CREDENTIALS_ORDER")
    order = configured_order or "primary,secondary"
    profiles = [item.strip().lower() for item in order.replace(";", ",").split(",") if item.strip()]

    names: list[str] = []
    for profile in profiles:
        if profile in {"primary", "secondary"}:
            names.append(f"COZE_{profile.upper()}_API_TOKEN")
        elif profile in {"pat", "coze_pat"}:
            names.append("COZE_PAT")
        elif profile in {"api_token", "token", "legacy"}:
            names.append("COZE_API_TOKEN")

    # 关键改动：
    # 显式配置 order 后，只按 order 取，不再 fallback。
    if configured_order:
        return tuple(dict.fromkeys(names))

    names.extend([
        "COZE_PRIMARY_API_TOKEN",
        "COZE_SECONDARY_API_TOKEN",
        "COZE_API_TOKEN",
        "COZE_PAT",
    ])
    return tuple(dict.fromkeys(names))


def _coze_token_with_name() -> tuple[str, str]:
    return _env_with_name(*_coze_token_env_names())


def _coze_api_base_with_name(token_source: str = "") -> tuple[str, str]:
    profile = ""
    if token_source.startswith("COZE_PRIMARY_"):
        profile = "PRIMARY"
    elif token_source.startswith("COZE_SECONDARY_"):
        profile = "SECONDARY"
    names = []
    if profile:
        names.append(f"COZE_{profile}_API_BASE")
    names.extend(["COZE_API_BASE", "COZE_BASE_URL"])
    return _env_with_name(*names)


def _normalize_coze_workflow_url(raw_url: str) -> str:
    url = str(raw_url or "").strip().rstrip("/")
    if not url:
        return DEFAULT_COZE_WORKFLOW_URL
    if url.endswith("/v1/workflow/run") or url.endswith("/workflow/run"):
        return url
    if "/v1" in url:
        return f"{url}/workflow/run"
    return f"{url}/v1/workflow/run"


coze_client = CozeWorkflowClient()
