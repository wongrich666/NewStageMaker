from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import settings
from .fastgpt_contracts import (
    BATCH_DIALOGUES,
    BATCH_HOOKS,
    BATCH_SCRIPT,
    BLOCKING_ISSUES,
    HOOK_MEMORY,
    LAST_SUMMARY,
    REVIEW_PASSED,
    REWRITE_REQUIRED,
)
from .json_utils import parse_json, strip_code_fence


WORKFLOW_PROMPT_VAR_PATTERN = re.compile(r"\{\{\$VARIABLE_NODE_ID\.([A-Za-z0-9_]+)\$\}\}")


@dataclass(frozen=True, slots=True)
class WorkflowOutputContractSpec:
    stage_name: str
    expected_output_kind: str
    workflow_json_name: str | None
    response_format: str | None
    json_schema: str | None
    variable_update_targets: tuple[str, ...]
    prompt_variable_refs: tuple[str, ...]
    workflow_warnings: tuple[str, ...] = ()


class WorkflowOutputValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        issues: list[str] | None = None,
        normalized_output: dict[str, Any] | None = None,
        fallback_used: bool = False,
        matched_aliases: list[str] | None = None,
        raw_output_source: str = "stage_output",
        candidate_sources: list[str] | None = None,
        matched_fields: list[str] | None = None,
        missing_fields: list[str] | None = None,
        probable_truncated_json: bool = False,
        answer_text_preview: str = "",
        response_preview: str = "",
    ) -> None:
        self.issues = list(issues or [])
        self.normalized_output = dict(normalized_output or {})
        self.fallback_used = bool(fallback_used)
        self.matched_aliases = list(matched_aliases or [])
        self.raw_output_source = raw_output_source
        self.candidate_sources = list(candidate_sources or [])
        self.matched_fields = list(matched_fields or [])
        self.missing_fields = list(missing_fields or [])
        self.probable_truncated_json = bool(probable_truncated_json)
        self.answer_text_preview = str(answer_text_preview or "")
        self.response_preview = str(response_preview or "")
        super().__init__(message)


def load_workflow_output_contract(
    *,
    stage_name: str,
    expected_output_kind: str,
    workflow_json_name: str | None,
) -> WorkflowOutputContractSpec:
    if not workflow_json_name:
        return WorkflowOutputContractSpec(
            stage_name=stage_name,
            expected_output_kind=expected_output_kind,
            workflow_json_name=None,
            response_format=None,
            json_schema=None,
            variable_update_targets=(),
            prompt_variable_refs=(),
            workflow_warnings=(),
        )

    workflow_path = _workflow_json_path(workflow_json_name)
    if not workflow_path.exists():
        return WorkflowOutputContractSpec(
            stage_name=stage_name,
            expected_output_kind=expected_output_kind,
            workflow_json_name=workflow_json_name,
            response_format=None,
            json_schema=None,
            variable_update_targets=(),
            prompt_variable_refs=(),
            workflow_warnings=(f"workflow JSON not found: {workflow_json_name}",),
        )

    try:
        raw_text = workflow_path.read_text(encoding="utf-8-sig")
        workflow_json = json.loads(raw_text)
    except Exception as exc:
        return WorkflowOutputContractSpec(
            stage_name=stage_name,
            expected_output_kind=expected_output_kind,
            workflow_json_name=workflow_json_name,
            response_format=None,
            json_schema=None,
            variable_update_targets=(),
            prompt_variable_refs=(),
            workflow_warnings=(f"workflow JSON load failed: {type(exc).__name__}",),
        )

    response_format, json_schema = _extract_chatnode_output_contract(workflow_json)
    variable_update_targets = tuple(_extract_variable_update_targets(workflow_json))
    prompt_variable_refs = tuple(sorted(set(WORKFLOW_PROMPT_VAR_PATTERN.findall(raw_text))))
    warnings = _workflow_warnings_from_json(
        workflow_json,
        prompt_variable_refs,
        raw_text=raw_text,
    )
    return WorkflowOutputContractSpec(
        stage_name=stage_name,
        expected_output_kind=expected_output_kind,
        workflow_json_name=workflow_json_name,
        response_format=response_format,
        json_schema=json_schema,
        variable_update_targets=variable_update_targets,
        prompt_variable_refs=prompt_variable_refs,
        workflow_warnings=tuple(warnings),
    )


def validate_stage_output_with_workflow_contract(
    output: dict[str, Any],
    *,
    spec: WorkflowOutputContractSpec,
    canonical_name: str,
    aliases: tuple[str, ...],
    batch_validator: Callable[[Any], list[str]] | None = None,
    review_parser: Callable[[Any], Any] | None = None,
    memory_normalizer: Callable[..., str] | None = None,
    memory_kwargs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    matched_aliases = [
        name
        for name in (canonical_name, *aliases)
        if isinstance(output, dict) and name in output
    ]
    candidate = _candidate_from_output(output, canonical_name=canonical_name, aliases=aliases)
    meta: dict[str, Any] = {
        "matched_aliases": matched_aliases,
        "raw_output_source": "stage_output",
        "fallback_used": False,
        "workflow_warnings": [],
        "matched_fields": [],
        "missing_fields": [],
    }

    kind = spec.expected_output_kind
    if kind == "review_json":
        if review_parser is None:
            raise WorkflowOutputValidationError(
                f"{spec.stage_name} 缺少 review_parser",
                matched_aliases=matched_aliases,
            )
        review_input = output if isinstance(output, dict) else candidate
        if isinstance(candidate, (dict, str)) and not isinstance(candidate, bool):
            review_input = candidate
        decision = review_parser(review_input)
        review_contract_issues = _review_contract_issues(decision)
        if review_contract_issues:
            raise WorkflowOutputValidationError(
                f"{spec.stage_name} 审核输出未通过格式契约校验",
                issues=review_contract_issues,
                normalized_output={},
                matched_aliases=matched_aliases,
            )
        payload = decision.payload
        normalized = {
            REVIEW_PASSED: payload[REVIEW_PASSED],
            REWRITE_REQUIRED: payload[REWRITE_REQUIRED],
            BLOCKING_ISSUES: payload[BLOCKING_ISSUES],
            "summary": str(payload.get("summary") or "").strip(),
            "non_blocking_issues": list(payload.get("non_blocking_issues") or []),
        }
        if "rewrite_start_episode" in payload:
            normalized["rewrite_start_episode"] = payload["rewrite_start_episode"]
        if spec.stage_name == "script_review":
            normalized["stage"] = (
                str(payload.get("stage") or "").strip()
                or "five_episode_continuity_review"
            )
        elif "stage" in payload:
            normalized["stage"] = payload["stage"]
        if spec.stage_name == "script_review":
            review_issues, review_warnings = _script_review_contract_issues(payload)
            if review_issues:
                raise WorkflowOutputValidationError(
                    f"{spec.stage_name} 审核输出未通过格式契约校验",
                    issues=review_issues,
                    normalized_output=normalized,
                    matched_aliases=matched_aliases,
                )
            meta["workflow_warnings"] = review_warnings
        meta["normalized_preview"] = _preview(normalized)
        return normalized, meta

    if kind in {"hooks_batch_json", "dialogues_batch_json"}:
        payload = _normalize_batch_json_candidate(candidate, canonical_name=canonical_name)
        issues = list(batch_validator(payload) if callable(batch_validator) else [])
        if issues:
            raise WorkflowOutputValidationError(
                f"{spec.stage_name} 输出未通过本地批次校验",
                issues=issues,
                normalized_output={canonical_name: payload},
                matched_aliases=matched_aliases,
            )
        normalized = {canonical_name: payload}
        meta["normalized_preview"] = _preview(normalized)
        return normalized, meta

    if kind == "appearanceMapping_json":
        payload = _normalize_batch_json_candidate(candidate, canonical_name=canonical_name)
        issues = list(batch_validator(payload) if callable(batch_validator) else [])
        if issues:
            raise WorkflowOutputValidationError(
                f"{spec.stage_name} 输出未通过服装映射本地校验",
                issues=issues,
                normalized_output={canonical_name: payload},
                matched_aliases=matched_aliases,
            )
        normalized = {canonical_name: payload}
        meta["normalized_preview"] = _preview(normalized)
        return normalized, meta

    if kind == "script_text":
        if not isinstance(candidate, str):
            raise WorkflowOutputValidationError(
                f"{spec.stage_name} 输出必须是正文字符串",
                issues=[f"{spec.stage_name} 输出不是 string"],
                matched_aliases=matched_aliases,
            )
        text = str(candidate).strip()
        issues = list(batch_validator(text) if callable(batch_validator) else [])
        if issues:
            raise WorkflowOutputValidationError(
                f"{spec.stage_name} 输出未通过正文批次校验",
                issues=issues,
                normalized_output={canonical_name: text},
                matched_aliases=matched_aliases,
            )
        normalized = {canonical_name: text}
        meta["normalized_preview"] = _preview(normalized)
        return normalized, meta

    if kind in {"hook_memory_json", "dialogue_memory_json", "script_memory_json"}:
        raw_value = candidate
        if raw_value is None and isinstance(output, dict):
            raw_value = output.get("answerText")
            if raw_value is not None:
                matched_aliases = [*matched_aliases, "answerText"]
                meta["matched_aliases"] = matched_aliases
        strict_ok = _strict_memory_json_is_valid(raw_value, required_keys=_required_memory_keys(kind))
        if memory_normalizer is None:
            raise WorkflowOutputValidationError(
                f"{spec.stage_name} 缺少 memory_normalizer",
                matched_aliases=matched_aliases,
            )
        normalized_text = memory_normalizer(raw_value, **(memory_kwargs or {}))
        normalized = {canonical_name: normalized_text}
        if not strict_ok:
            raise WorkflowOutputValidationError(
                f"{spec.stage_name} memory 输出未通过格式契约校验",
                issues=[f"{spec.stage_name} memory output is not valid required json"],
                normalized_output=normalized,
                matched_aliases=matched_aliases,
            )
        meta["fallback_used"] = False
        meta["normalized_preview"] = _preview(normalized)
        return normalized, meta

    if kind == "unstructured_natural_language_text":
        if candidate is None and isinstance(output, dict):
            raw_value = output.get("answerText")
            if raw_value is not None:
                candidate = raw_value
                matched_aliases = [*matched_aliases, "answerText"]
                meta["matched_aliases"] = matched_aliases
        if not isinstance(candidate, str):
            raise WorkflowOutputValidationError(
                f"{spec.stage_name} 输出必须是自然语言字符串",
                issues=[f"{spec.stage_name} 输出不是 string"],
                matched_aliases=matched_aliases,
            )
        text = strip_code_fence(str(candidate or "")).strip()
        if not text:
            raise WorkflowOutputValidationError(
                f"{spec.stage_name} 输出不能为空",
                issues=[f"{spec.stage_name} 输出为空"],
                matched_aliases=matched_aliases,
            )
        if "```" in str(candidate):
            raise WorkflowOutputValidationError(
                f"{spec.stage_name} 输出不能包含 markdown code fence",
                issues=[f"{spec.stage_name} 输出包含 code fence"],
                matched_aliases=matched_aliases,
            )
        stripped = text.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                parsed = parse_json(stripped)
            except Exception:
                parsed = None
            if isinstance(parsed, (dict, list)):
                raise WorkflowOutputValidationError(
                    f"{spec.stage_name} 输出不能是 JSON",
                    issues=[f"{spec.stage_name} 输出仍是 JSON 结构"],
                    matched_aliases=matched_aliases,
                )
        trivial_prefixes = ("已完成", "以下是", "当然", "好的", "下面是")
        if any(text.startswith(prefix) for prefix in trivial_prefixes) and len(text) <= 24:
            raise WorkflowOutputValidationError(
                f"{spec.stage_name} 输出过于空泛",
                issues=[f"{spec.stage_name} 输出只有空泛提示语"],
                matched_aliases=matched_aliases,
            )
        normalized = {canonical_name: text}
        meta["normalized_preview"] = _preview(normalized)
        return normalized, meta

    normalized = {canonical_name: candidate}
    meta["normalized_preview"] = _preview(normalized)
    return normalized, meta


def build_debug_artifact(
    *,
    spec: WorkflowOutputContractSpec,
    batch_label: str | None,
    review_round: int | None,
    format_attempt: int,
    max_format_retries: int,
    status: str,
    validator_issues: list[str] | None = None,
    exception: Exception | None = None,
    raw_output_source: str = "stage_output",
    matched_aliases: list[str] | None = None,
    candidate_sources: list[str] | None = None,
    matched_fields: list[str] | None = None,
    missing_fields: list[str] | None = None,
    probable_truncated_json: bool = False,
    answer_text_preview: str | None = None,
    response_preview: str | None = None,
    raw_preview: str | None = None,
    normalized_preview: str | None = None,
    fallback_used: bool = False,
    last_failure_reason: str = "",
) -> dict[str, Any]:
    return {
        "stage_name": spec.stage_name,
        "workflow_json_name": spec.workflow_json_name,
        "expected_output_kind": spec.expected_output_kind,
        "batch_label": batch_label or "",
        "review_round": review_round,
        "format_attempt": format_attempt,
        "max_format_retries": max_format_retries,
        "status": status,
        "raw_output_source": raw_output_source,
        "matched_aliases": list(matched_aliases or []),
        "candidate_sources": list(candidate_sources or []),
        "matched_fields": list(matched_fields or []),
        "missing_fields": list(missing_fields or []),
        "probable_truncated_json": bool(probable_truncated_json),
        "variable_update_targets": list(spec.variable_update_targets),
        "workflow_contract_summary": {
            "response_format": spec.response_format,
            "json_schema": spec.json_schema,
            "prompt_variable_refs": list(spec.prompt_variable_refs),
        },
        "workflow_warnings": list(spec.workflow_warnings),
        "validator_issues": list(validator_issues or []),
        "exception_type": type(exception).__name__ if exception else "",
        "exception_message": str(exception) if exception else "",
        "answer_text_preview": _preview(answer_text_preview),
        "response_preview": _preview(response_preview),
        "raw_preview": _preview(raw_preview),
        "normalized_preview": _preview(normalized_preview),
        "fallback_used": bool(fallback_used),
        "last_failure_reason": str(last_failure_reason or ""),
    }


def resolve_workflow_json_path(filename: str) -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    cwd = Path.cwd()

    configured_dir = str(getattr(settings, "workflow_json_dir", "") or "").strip()
    search_roots: list[Path] = []
    if configured_dir:
        configured_path = Path(configured_dir)
        if not configured_path.is_absolute():
            search_roots.extend(
                [
                    (cwd / configured_path).resolve(),
                    (repo_root / configured_path).resolve(),
                ]
            )
        else:
            search_roots.append(configured_path)

    search_roots.extend(
        [
            repo_root / "workflow_jsons",
            cwd / "workflow_jsons",
        ]
    )

    visited: set[Path] = set()
    for root in list(search_roots):
        try:
            resolved = root.resolve()
        except Exception:
            resolved = root
        if resolved in visited:
            continue
        visited.add(resolved)
        candidate = resolved / filename
        if candidate.exists():
            return candidate

    for parent in (repo_root, cwd):
        try:
            children = list(parent.iterdir())
        except Exception:
            continue
        for candidate_dir in children:
            if not candidate_dir.is_dir() or not candidate_dir.name.endswith("workflow_jsons"):
                continue
            candidate = candidate_dir / filename
            if candidate.exists():
                return candidate

    fallback_root = search_roots[0] if search_roots else (repo_root / "workflow_jsons")
    return fallback_root / filename


def _workflow_json_path(filename: str) -> Path:
    return resolve_workflow_json_path(filename)


def _extract_chatnode_output_contract(workflow_json: dict[str, Any]) -> tuple[str | None, str | None]:
    response_format: str | None = None
    json_schema: str | None = None
    for node in workflow_json.get("nodes") or []:
        if not isinstance(node, dict) or node.get("flowNodeType") != "chatNode":
            continue
        for item in node.get("inputs") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            value = item.get("value")
            if key == "aiChatResponseFormat" and value not in (None, ""):
                response_format = str(value)
            elif key == "aiChatJsonSchema" and value not in (None, ""):
                json_schema = str(value)
    return response_format, json_schema


def _extract_variable_update_targets(workflow_json: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    for node in workflow_json.get("nodes") or []:
        if not isinstance(node, dict) or node.get("flowNodeType") != "variableUpdate":
            continue
        for item in node.get("inputs") or []:
            if not isinstance(item, dict) or str(item.get("key") or "") != "updateList":
                continue
            for update in item.get("value") or []:
                if not isinstance(update, dict):
                    continue
                variable = update.get("variable")
                if isinstance(variable, list) and len(variable) >= 2:
                    name = str(variable[-1] or "").strip()
                    if name:
                        targets.append(name)
                elif isinstance(variable, str) and variable.strip():
                    targets.append(variable.strip())
    return targets


def _workflow_warnings_from_json(
    workflow_json: dict[str, Any],
    prompt_variable_refs: tuple[str, ...],
    *,
    raw_text: str,
) -> list[str]:
    chat_variables = {
        str(item.get("key") or "").strip()
        for item in workflow_json.get("chatConfig", {}).get("variables") or []
        if isinstance(item, dict)
    }
    warnings: list[str] = []
    if "hookContent" in prompt_variable_refs and "hookContent" not in chat_variables:
        warnings.append(
            "workflow prompt 通过 VARIABLE_NODE_ID 引用了 hookContent，但 chatConfig.variables 未声明该变量。"
        )
    return warnings


def _review_contract_issues(decision: Any) -> list[str]:
    summary = str(getattr(decision, "summary", "") or "").strip()
    blocking_issues = [
        str(item).strip()
        for item in list(getattr(decision, "blocking_issues", []) or [])
        if str(item).strip()
    ]
    if summary.startswith("review output"):
        return blocking_issues or [summary]
    invalid_markers = (
        "review output",
        "review output key",
    )
    issues = [
        item
        for item in blocking_issues
        if any(item.startswith(marker) for marker in invalid_markers)
    ]
    return issues


def _candidate_from_output(
    output: dict[str, Any],
    *,
    canonical_name: str,
    aliases: tuple[str, ...],
) -> Any:
    for key in (canonical_name, *aliases):
        if key in output:
            return output[key]
    return None


def _normalize_batch_json_candidate(value: Any, *, canonical_name: str) -> dict[str, Any]:
    candidate = value
    if isinstance(candidate, str):
        candidate = parse_json(candidate)
    if not isinstance(candidate, dict):
        raise WorkflowOutputValidationError(
            f"{canonical_name} 输出必须是 JSON object",
            issues=[f"{canonical_name} 输出必须是 JSON object"],
        )
    nested_candidate = candidate.get(canonical_name)
    if isinstance(nested_candidate, str):
        try:
            nested_candidate = parse_json(nested_candidate)
        except Exception:
            nested_candidate = nested_candidate
    if isinstance(nested_candidate, dict):
        candidate = nested_candidate
        nested_inner = candidate.get(canonical_name)
        if isinstance(nested_inner, str):
            try:
                nested_inner = parse_json(nested_inner)
            except Exception:
                nested_inner = nested_inner
        if isinstance(nested_inner, dict):
            candidate = nested_inner
    if not isinstance(candidate, dict):
        raise WorkflowOutputValidationError(
            f"{canonical_name} 输出必须归一化为 object",
            issues=[f"{canonical_name} 输出必须归一化为 object"],
        )
    return candidate


def _required_memory_keys(kind: str) -> set[str]:
    if kind == "hook_memory_json":
        return {
            "final_hook_of_this_turn",
            "must_carry_into_next_turn",
            "appearance_alias_continuity_summary",
        }
    if kind == "dialogue_memory_json":
        return {
            "dialogue_voice_summary",
            "must_carry_into_next_turn",
            "alias_usage_continuity",
        }
    return {
        "final_hook_of_this_turn",
        "must_carry_into_next_turn",
        "appearance_continuity_summary",
    }


def _script_review_contract_issues(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    if "non_blocking_issues" in payload and not isinstance(payload.get("non_blocking_issues"), list):
        issues.append("script_review output key non_blocking_issues must be array")
    if "rewrite_start_episode" in payload:
        rewrite_start = payload.get("rewrite_start_episode")
        if isinstance(rewrite_start, bool) or not isinstance(rewrite_start, int):
            issues.append("script_review output key rewrite_start_episode must be int")
    if "stage" in payload:
        stage_value = str(payload.get("stage") or "").strip()
        if not stage_value:
            issues.append("script_review output key stage must be non-empty string")
        elif stage_value != "five_episode_continuity_review":
            warnings.append(
                f"script_review output stage is '{stage_value}', expected 'five_episode_continuity_review'"
            )
    return issues, warnings


def _strict_memory_json_is_valid(value: Any, *, required_keys: set[str]) -> bool:
    try:
        parsed = value if isinstance(value, dict) else parse_json(str(value or "").strip())
    except Exception:
        return False
    if not isinstance(parsed, dict):
        return False
    return required_keys.issubset(parsed.keys())


def _preview(value: Any, *, limit: int = 500) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            value = str(value)
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."
