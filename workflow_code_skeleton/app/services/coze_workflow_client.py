from __future__ import annotations

import json
import os
import re
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from ..config import settings
from ..utils.logger import get_logger
from .workflow_output_normalizer import normalize_stage_output

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "coze_workflows.yaml"
logger = get_logger("coze_workflow_client")


class CozeWorkflowError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage_key: str = "",
        workflow_id: str = "",
        error: Any = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.stage_key = stage_key
        self.workflow_id = workflow_id
        self.error = error
        self.detail = detail or {}


@dataclass(frozen=True, slots=True)
class CozeStageConfig:
    key: str
    name: str
    workflow_id: str
    workflow_id_env: str
    yaml_path: str
    input_mapping: dict[str, str]
    output_mapping: dict[str, str]
    output_fallbacks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CozeCredential:
    name: str
    auth_type: str
    token: str
    token_env: str
    token_expires_at: str
    token_expires_env: str
    base_url: str
    base_url_source: str
    base_url_env: str
    token_detail: dict[str, Any]


STAGE_KEY_ALIASES: dict[str, str] = {
    "basic": "stage_01",
    "source": "stage_01",
    "source_brief": "stage_01",
    "worldview": "stage_02",
    "character": "stage_03",
    "characters": "stage_03",
    "beat": "stage_04",
    "storyline": "stage_05",
    "storylines": "stage_05",
    "guide": "stage_06",
    "adaptation": "stage_06",
    "package": "stage_07",
    "framework": "stage_07",
    "scene": "stage_08",
    "appearance": "stage_09",
    "alias": "stage_09",
    "episode": "stage_10",
    "enriched": "stage_10",
    "conflict": "stage_11_write",
    "script": "stage_12_write",
    "script_text": "stage_12_write",
}


def normalize_coze_stage_key(stage_key: Any) -> str:
    raw = str(stage_key or "").strip()
    lowered = raw.lower().replace("-", "_")
    if lowered in STAGE_KEY_ALIASES:
        return STAGE_KEY_ALIASES[lowered]
    substage_match = re.fullmatch(r"stage_?(1[12])_?(write|review|rewrite|memory)", lowered)
    if substage_match:
        return f"stage_{substage_match.group(1)}_{substage_match.group(2)}"
    number_match = re.fullmatch(r"(?:stage_?)?(\d{1,2})", lowered)
    if number_match:
        return f"stage_{int(number_match.group(1)):02d}"
    return lowered


def _cozepy_version() -> str:
    try:
        return metadata.version("cozepy")
    except Exception:
        return "unknown"


def _env_status(name: str) -> str:
    return "SET" if os.getenv(name) else "EMPTY"


def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default) or default).strip().lower() in {"1", "true", "yes", "on"}


def _base_url_region(base_url: str) -> str:
    lowered = str(base_url or "").lower()
    if "api.coze.cn" in lowered:
        return "cn"
    if "api.coze.com" in lowered:
        return "global"
    return "custom" if lowered else ""


def _normalized_token_value(raw_token: str | None) -> tuple[str, dict[str, Any]]:
    raw = "" if raw_token is None else str(raw_token)
    stripped = raw.strip()
    bearer_prefixed = stripped.lower().startswith("bearer ")
    normalized = stripped[7:].strip() if bearer_prefixed else stripped
    return normalized, {
        "token_status": "SET" if normalized else "EMPTY",
        "token_format_status": "BEARER_PREFIX_STRIPPED" if bearer_prefixed else ("SET" if normalized else "EMPTY"),
        "token_had_bearer_prefix": bearer_prefixed,
        "token_had_leading_or_trailing_space": raw != stripped,
        "token_contains_newline": "\n" in raw or "\r" in raw,
        "token_too_short": bool(normalized) and len(normalized) < 20,
    }


def _coze_error_hint(error_code: str, workflow_id: str = "") -> str:
    if error_code == "4101":
        return (
            f"当前 token 有效，但没有权限访问 workflow_id={workflow_id}。请检查该 token 是否授权了 workflow "
            "所在工作空间，并勾选 Workflow.run 权限；也请确认 workflow_id 是否属于当前 token 可访问空间。"
        )
    if error_code == "4100":
        return "当前 token 鉴权失败，可能过期、复制错误、区域不匹配、带了 Bearer 前缀，或 token 被截断。"
    if error_code == "4200":
        return "Coze workflow 未发布或不可运行，请先发布 workflow 后重试。"
    if error_code == "4000":
        return "Coze 请求参数错误，请检查 workflow 入参名称、必填字段和参数格式。"
    return ""


def _safe_token_prefix(token: str) -> str:
    text = str(token or "")
    if not text:
        return ""
    return text[:8]


def _days_left(expires_at: str) -> int | None:
    text = str(expires_at or "").strip()
    if not text:
        return None
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError:
        return None
    return (parsed - datetime.now(timezone.utc).date()).days


def _safe_credential_detail(credential: CozeCredential) -> dict[str, Any]:
    days_left = _days_left(credential.token_expires_at)
    detail = {
        "credential_name": credential.name,
        "auth_type": credential.auth_type,
        "token_env": credential.token_env,
        "token_status": "SET" if credential.token else "EMPTY",
        "token_redacted": True,
        "token_prefix": _safe_token_prefix(credential.token),
        "token_len": len(credential.token),
        "token_too_short": bool(credential.token) and len(credential.token) < 20,
        "token_expires_at": credential.token_expires_at,
        "token_days_left": days_left,
        "base_url": credential.base_url,
        "base_url_source": credential.base_url_source,
        "base_url_env": credential.base_url_env,
        "base_url_region": _base_url_region(credential.base_url),
    }
    detail.update(credential.token_detail)
    return detail


def _coze_error_code_from_detail(detail: dict[str, Any]) -> str:
    for key in ("code", "error_code", "original_error_code", "status_code"):
        value = detail.get(key)
        if value not in (None, ""):
            return str(value)
    text = str(detail.get("original_exception_message") or detail.get("msg") or detail.get("message") or "")
    match = re.search(r"(?:code|error_code)\s*[:=]\s*([A-Za-z0-9_-]+)", text)
    return match.group(1) if match else ""


def _coze_error_message_from_detail(detail: dict[str, Any]) -> str:
    for key in ("msg", "message", "error_message", "original_error_msg", "original_exception_message"):
        value = detail.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _env_value_with_source(*names: str) -> tuple[str, str]:
    for name in names:
        value = str(os.getenv(name) or "").strip()
        if value:
            return value, name
    return "", ""


def _resolve_coze_base_url(value: str | None = None) -> str:
    from cozepy import COZE_CN_BASE_URL

    raw = str(value if value is not None else os.getenv("COZE_API_BASE") or "").strip()
    if not raw:
        return COZE_CN_BASE_URL
    normalized = raw.upper()
    if normalized in {"COZE_CN_BASE_URL", "CN", "CHINA", "COZE_CN"}:
        if normalized == "COZE_CN_BASE_URL":
            logger.warning("COZE_API_BASE=COZE_CN_BASE_URL is accepted, but https://api.coze.cn is preferred.")
        return COZE_CN_BASE_URL
    if normalized in {"COZE_COM_BASE_URL", "GLOBAL", "COM", "US"}:
        if normalized == "COZE_COM_BASE_URL":
            logger.warning("COZE_API_BASE=COZE_COM_BASE_URL is accepted, but https://api.coze.com is preferred.")
        return "https://api.coze.com"
    if raw.startswith(("http://", "https://")):
        return raw.rstrip("/")
    raise CozeWorkflowError(
        f"Invalid COZE_API_BASE: {raw}. Use COZE_CN_BASE_URL, COZE_COM_BASE_URL, or a full https:// URL."
    )


def _resolve_coze_base_url_info(value: str | None = None, source: str = "") -> tuple[str, str]:
    raw = str(value if value is not None else os.getenv("COZE_API_BASE") or "").strip()
    base_url = _resolve_coze_base_url(raw)
    if raw:
        return base_url, source or "COZE_API_BASE"
    return base_url, "default:COZE_CN_BASE_URL"


def _exception_detail(exc: Exception) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "original_exception_type": type(exc).__name__,
        "original_exception_message": str(exc),
    }
    for attr in ("code", "msg", "logid", "debug_url", "status_code"):
        value = getattr(exc, attr, None)
        if value is not None:
            detail[attr] = _event_to_jsonable(value)
    if hasattr(exc, "__dict__"):
        for key, value in vars(exc).items():
            if str(key).startswith("_") or key in detail:
                continue
            detail[str(key)] = _event_to_jsonable(value)
    code = detail.get("code") or detail.get("error_code") or detail.get("status_code")
    msg = detail.get("msg") or detail.get("message") or detail.get("error_msg")
    if code not in (None, ""):
        detail["original_error_code"] = _event_to_jsonable(code)
    if msg not in (None, ""):
        detail["original_error_msg"] = _event_to_jsonable(msg)
    return detail


def _coze_error_message(exc: Exception, detail: dict[str, Any]) -> str:
    message = f"Coze workflow request failed: {type(exc).__name__}: {exc}"
    code = str(detail.get("code") or detail.get("original_error_code") or detail.get("error_code") or "")
    msg = str(detail.get("msg") or detail.get("original_exception_message") or "").lower()
    base_url = str(detail.get("base_url") or "")
    token_env = str(detail.get("token_env") or "COZE_API_TOKEN")
    workflow_id = str(detail.get("workflow_id") or "")
    if code in {"4101", "4100", "4200", "4000"}:
        return _coze_error_hint(code, workflow_id)
    if code == "4100" or "authentication is invalid" in msg:
        return (
            f"Coze authentication invalid. {token_env} is present, but Coze rejected it "
            f"for base_url={base_url or 'unknown'}. Regenerate or replace the PAT for this Coze region, "
            "then restart the server."
        )
    if code == "4101" or "permission denied" in msg or "permission" in msg:
        return (
            "Coze permission denied. The token is valid but does not have permission to run this workflow "
            f"for base_url={base_url or 'unknown'}. Check Workflow.run permission and workspace authorization."
        )
    if code == "700012006" or "access token invalid" in msg:
        hint = (
            f"Coze access token invalid. Check {token_env}, and make sure "
            "COZE_API_BASE matches the token region."
        )
        if "api.coze.com" in base_url:
            hint += " If this is a Coze CN token, set COZE_API_BASE=COZE_CN_BASE_URL or https://api.coze.cn."
        elif "api.coze.cn" in base_url:
            hint += " If this is a global Coze token, set COZE_API_BASE=COZE_COM_BASE_URL or https://api.coze.com."
        return hint
    return message


def _augment_authentication_failure_detail(detail: dict[str, Any]) -> None:
    code = str(detail.get("original_error_code") or detail.get("code") or "")
    msg = str(detail.get("original_error_msg") or detail.get("msg") or detail.get("original_exception_message") or "").lower()
    if (
        code not in {"4100", "4101", "700012006"}
        and "authentication is invalid" not in msg
        and "access token invalid" not in msg
        and "permission denied" not in msg
    ):
        return
    base_url = str(detail.get("base_url") or "")
    detail["auth_failure_suspected"] = True
    detail["auth_failure_code"] = code
    detail["base_url_region"] = _base_url_region(base_url)
    detail["token_action_required"] = "replace_or_regenerate_coze_pat"
    token_env = str(detail.get("token_env") or "COZE_API_TOKEN")
    base_url_env = str(detail.get("base_url_env") or "COZE_API_BASE")
    detail["token_action_hint"] = (
        f"{token_env} is set, but Coze rejected it. Use a valid PAT for the configured "
        f"{base_url_env} region, and restart the server after updating .env."
    )


def _augment_region_mismatch_detail(detail: dict[str, Any]) -> None:
    code = str(detail.get("original_error_code") or detail.get("code") or "")
    msg = str(detail.get("original_error_msg") or detail.get("msg") or detail.get("original_exception_message") or "").lower()
    if code != "700012006" and "access token invalid" not in msg:
        return
    base_url = str(detail.get("base_url") or "")
    if "api.coze.com" in base_url:
        detail["region_mismatch_suspected"] = True
        detail["suggested_base_url"] = "https://api.coze.cn"
        detail["suggested_base_url_env"] = "COZE_API_BASE=https://api.coze.cn"
    elif "api.coze.cn" in base_url:
        detail["region_mismatch_suspected"] = True
        detail["suggested_base_url"] = "https://api.coze.com"
        detail["suggested_base_url_env"] = "COZE_API_BASE=https://api.coze.com"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_config_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except Exception as exc:  # pragma: no cover - only hit without JSON config
            raise CozeWorkflowError(
                f"Coze workflow config must be JSON-compatible YAML or PyYAML must be installed: {path}"
            ) from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise CozeWorkflowError(f"Coze workflow config must be an object: {path}")
    return data


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def _try_json_loads(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        return value


def _deep_find_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for nested in value.values():
            found = _deep_find_key(nested, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _deep_find_key(item, key)
            if found is not None:
                return found
    return None


def _first_text(value: Any, keys: tuple[str, ...]) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in keys:
            candidate = _deep_find_key(value, key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
            if isinstance(candidate, (dict, list)):
                return json.dumps(candidate, ensure_ascii=False)
    return ""


class CozeWorkflowClient:
    def __init__(self, config_path: str | os.PathLike[str] | None = None) -> None:
        env_config = os.getenv("COZE_WORKFLOW_CONFIG")
        self.config_path = Path(config_path or env_config or DEFAULT_CONFIG_PATH).resolve()
        self.config = _load_config_file(self.config_path)
        self.token_env = str(self.config.get("token_env") or "COZE_API_TOKEN")
        self.base_url_env = str(self.config.get("base_url_env") or "COZE_API_BASE")
        self.timeout_seconds = int(
            os.getenv(str(self.config.get("timeout_env") or "COZE_TIMEOUT_SECONDS"), "600") or "600"
        )
        self.dry_run = str(
            os.getenv(str(self.config.get("dry_run_env") or "COZE_DRY_RUN"), "0")
        ).strip() in {"1", "true", "TRUE", "yes", "on"}
        self._coze: Any = None
        self._coze_signature: tuple[str, str, str] | None = None

    def credentials(self) -> list[CozeCredential]:
        primary_token, _primary_detail = _normalized_token_value(os.getenv("COZE_PRIMARY_API_TOKEN"))
        secondary_token, _secondary_detail = _normalized_token_value(os.getenv("COZE_SECONDARY_API_TOKEN"))
        order_env = str(os.getenv("COZE_CREDENTIALS_ORDER") or "").strip()
        multi_credential_configured = bool(primary_token or secondary_token or order_env)
        if multi_credential_configured:
            names = [
                re.sub(r"[^A-Za-z0-9_]", "", item.strip()).lower()
                for item in str(order_env or "primary,secondary").split(",")
                if item.strip()
            ]
            if not names:
                names = ["primary", "secondary"]
            if primary_token:
                names = [name for name in names if name in {"primary", "secondary"}]
                if not names:
                    names = ["primary", "secondary"]
            return [self._credential_from_name(name) for name in names]
        return [self._legacy_credential()]

    def credentials_diagnostics(self) -> list[dict[str, Any]]:
        return [_safe_credential_detail(credential) for credential in self.credentials()]

    def credential_order(self) -> list[str]:
        return [credential.name for credential in self.credentials()]

    def credential_chain(self) -> tuple[list[CozeCredential], dict[str, Any]]:
        credentials = self.credentials()
        primary_token, primary_detail = _normalized_token_value(os.getenv("COZE_PRIMARY_API_TOKEN"))
        secondary_token, secondary_detail = _normalized_token_value(os.getenv("COZE_SECONDARY_API_TOKEN"))
        legacy_token, legacy_detail = _normalized_token_value(os.getenv(self.token_env))
        reasons: list[str] = []
        if primary_token:
            reasons.append("primary token set; legacy COZE_API_TOKEN fallback disabled")
        else:
            reasons.append("primary token empty")
            if legacy_token:
                reasons.append("legacy COZE_API_TOKEN allowed")
        return credentials, {
            "credential_chain": [item.name for item in credentials],
            "credential_attempt_order": [item.name for item in credentials],
            "coze_credentials_order": os.getenv("COZE_CREDENTIALS_ORDER") or "",
            "credential_resolution_reasons": reasons,
            "legacy_fallback_allowed": not bool(primary_token),
            "primary_token_status": primary_detail.get("token_status", "EMPTY"),
            "secondary_token_status": secondary_detail.get("token_status", "EMPTY"),
            "legacy_token_status": legacy_detail.get("token_status", "EMPTY"),
        }

    def credential_diagnostics(self) -> dict[str, Any]:
        credentials, chain_detail = self.credential_chain()
        payload = dict(chain_detail)
        all_credentials = {credential.name: credential for credential in credentials}
        for name in ("primary", "secondary", "legacy"):
            credential = all_credentials.get(name)
            if credential is None:
                credential = self._legacy_credential() if name == "legacy" else self._credential_from_name(name)
            safe = _safe_credential_detail(credential)
            payload[f"{name}_token_status"] = safe.get("token_status", "EMPTY")
            payload[f"{name}_token_prefix"] = safe.get("token_prefix", "")
            payload[f"{name}_token_len"] = safe.get("token_len", 0)
            payload[f"{name}_token_had_bearer_prefix"] = safe.get("token_had_bearer_prefix", False)
            payload[f"{name}_token_contains_newline"] = safe.get("token_contains_newline", False)
            payload[f"{name}_token_too_short"] = safe.get("token_too_short", False)
            payload[f"{name}_base_url"] = safe.get("base_url", "")
        return payload

    def _credential_from_name(self, name: str) -> CozeCredential:
        normalized = str(name or "").strip().lower() or "primary"
        if normalized == "legacy":
            return self._legacy_credential()
        prefix = f"COZE_{normalized.upper()}"
        token_env = f"{prefix}_API_TOKEN"
        expires_env = f"{prefix}_TOKEN_EXPIRES_AT"
        base_env = f"{prefix}_API_BASE"
        token, token_detail = _normalized_token_value(os.getenv(token_env))
        base_raw = os.getenv(base_env)
        base_source = base_env if str(base_raw or "").strip() else self.base_url_env
        try:
            base_url, base_url_source = _resolve_coze_base_url_info(
                base_raw if str(base_raw or "").strip() else os.getenv(self.base_url_env),
                base_source,
            )
        except Exception as exc:
            base_url, base_url_source = "", base_source
            token_detail["base_url_error"] = str(exc)
        return CozeCredential(
            name=normalized,
            auth_type=str(os.getenv(f"{prefix}_AUTH_TYPE") or os.getenv("COZE_AUTH_TYPE") or "pat").strip().lower() or "pat",
            token=token,
            token_env=token_env,
            token_expires_at=str(os.getenv(expires_env) or "").strip(),
            token_expires_env=expires_env,
            base_url=base_url,
            base_url_source=base_url_source,
            base_url_env=base_source,
            token_detail=token_detail,
        )

    def _legacy_credential(self) -> CozeCredential:
        token, token_detail = _normalized_token_value(os.getenv(self.token_env))
        try:
            base_url, base_url_source = _resolve_coze_base_url_info(os.getenv(self.base_url_env), self.base_url_env)
        except Exception as exc:
            base_url, base_url_source = "", self.base_url_env
            token_detail["base_url_error"] = str(exc)
        return CozeCredential(
            name="legacy",
            auth_type=str(os.getenv("COZE_AUTH_TYPE") or "pat").strip().lower() or "pat",
            token=token,
            token_env=self.token_env,
            token_expires_at=str(os.getenv("COZE_TOKEN_EXPIRES_AT") or "").strip(),
            token_expires_env="COZE_TOKEN_EXPIRES_AT",
            base_url=base_url,
            base_url_source=base_url_source,
            base_url_env=self.base_url_env,
            token_detail=token_detail,
        )

    def _bot_app_info_for_stage(self, stage_key: str) -> dict[str, Any]:
        normalized = normalize_coze_stage_key(stage_key).upper()
        compact = normalized.replace("_", "")
        bot_id, bot_source = _env_value_with_source(
            f"COZE_WORKFLOW_{normalized}_BOT_ID",
            f"COZE_WORKFLOW_{compact}_BOT_ID",
            "COZE_BOT_ID",
        )
        app_id, app_source = _env_value_with_source(
            f"COZE_WORKFLOW_{normalized}_APP_ID",
            f"COZE_WORKFLOW_{compact}_APP_ID",
            "COZE_APP_ID",
        )
        return {
            "bot_id": bot_id,
            "bot_id_source": bot_source,
            "bot_id_status": "SET" if bot_id else "EMPTY",
            "app_id": app_id,
            "app_id_source": app_source,
            "app_id_status": "SET" if app_id else "EMPTY",
        }

    def run_stage(
        self,
        stage_key: str,
        project_state: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
        stream: bool = True,
    ) -> dict[str, Any]:
        normalized_stage_key = normalize_coze_stage_key(stage_key)
        stage = self.stage_config(normalized_stage_key)
        built = self.build_parameters(stage.key, project_state or {}, parameters)
        workflow_info = self.workflow_id_info_for_stage(stage.key)
        workflow_id = str(workflow_info.get("workflow_id") or "")
        credential_detail = self.credential_diagnostics()
        logger.info(
            "Coze stage resolved input_stage_key=%s normalized_stage_key=%s workflow_id=%s workflow_id_exists=%s workflow_id_source=%s config_path=%s resource_path=%s inner_yaml_path=%s credential_chain=%s credential_attempt_order=%s primary_token_status=%s primary_token_prefix=%s primary_token_len=%s secondary_token_status=%s secondary_token_prefix=%s secondary_token_len=%s legacy_token_status=%s base_url_status=%s",
            stage_key,
            normalized_stage_key,
            workflow_id,
            bool(workflow_id),
            workflow_info.get("workflow_id_source") or "",
            self.config_path,
            workflow_info.get("resource_path") or "",
            workflow_info.get("inner_yaml_path") or "",
            credential_detail.get("credential_chain"),
            credential_detail.get("credential_attempt_order"),
            credential_detail.get("primary_token_status"),
            credential_detail.get("primary_token_prefix"),
            credential_detail.get("primary_token_len"),
            credential_detail.get("secondary_token_status"),
            credential_detail.get("secondary_token_prefix"),
            credential_detail.get("secondary_token_len"),
            credential_detail.get("legacy_token_status"),
            _env_status(self.base_url_env),
        )
        return self.run_workflow_by_id(
            workflow_id,
            parameters=built,
            stream=stream,
            stage_key=stage.key,
            workflow_info=workflow_info,
        )

    def run_workflow_by_id(
        self,
        workflow_id: str,
        parameters: dict[str, Any] | None = None,
        stream: bool = True,
        stage_key: str = "",
        workflow_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_stage_key = normalize_coze_stage_key(stage_key)
        safe_parameters = _jsonable(parameters or {})
        workflow_id = str(workflow_id or "").strip()
        workflow_info = workflow_info or self.workflow_id_info_for_stage(normalized_stage_key)
        if not workflow_id:
            raise CozeWorkflowError(
                "Coze workflow_id is empty",
                stage_key=normalized_stage_key,
                detail=self._request_debug_detail(normalized_stage_key, workflow_id, safe_parameters, workflow_info),
            )
        missing_input_variables = self._missing_input_variables(normalized_stage_key, safe_parameters)
        if missing_input_variables:
            raise CozeWorkflowError(
                "Coze workflow input variables missing",
                stage_key=normalized_stage_key,
                workflow_id=workflow_id,
                detail={
                    **self._request_debug_detail(normalized_stage_key, workflow_id, safe_parameters, workflow_info),
                    "missing_input_variables": missing_input_variables,
                },
            )
        if self.dry_run:
            raw = {
                "dry_run": True,
                "stage_key": normalized_stage_key,
                "workflow_id": workflow_id,
                "parameter_keys": sorted(safe_parameters.keys()),
            }
            return self.normalize_response(normalized_stage_key, workflow_id, raw)

        credentials = self.credentials()
        attempts: list[dict[str, Any]] = []
        last_error: CozeWorkflowError | None = None
        for index, credential in enumerate(credentials):
            try:
                result = self._run_workflow_by_id_once(
                    workflow_id,
                    parameters=safe_parameters,
                    stream=stream,
                    stage_key=normalized_stage_key,
                    workflow_info=workflow_info,
                    credential=credential,
                )
                if isinstance(result, dict):
                    result.setdefault("coze_credential_name", credential.name)
                    result.setdefault("credential_name", credential.name)
                    result.setdefault("credential_attempts", attempts + [self._credential_success_attempt(credential)])
                return result
            except CozeWorkflowError as exc:
                last_error = exc
                fallback_allowed, fallback_reason = self._fallback_allowed(exc)
                is_last = index >= len(credentials) - 1
                attempt = self._credential_failure_attempt(credential, exc, fallback_allowed, fallback_reason)
                attempts.append(attempt)
                exc.detail["credential_attempts"] = attempts
                if is_last or not fallback_allowed:
                    detail = dict(exc.detail)
                    detail["credential_attempts"] = attempts
                    error_code = _coze_error_code_from_detail(detail)
                    detail["coze_error_hint"] = _coze_error_hint(error_code, workflow_id)
                    if len(credentials) > 1:
                        raise CozeWorkflowError(
                            f"All Coze credentials failed; last credential={credential.name}: {exc}",
                            stage_key=normalized_stage_key,
                            workflow_id=workflow_id,
                            error=detail,
                            detail=detail,
                        ) from exc
                    raise
                next_credential = credentials[index + 1]
                logger.warning(
                    "Coze credential failed, trying next credential: credential=%s error_code=%s fallback_next=%s",
                    credential.name,
                    attempt.get("error_code") or "",
                    next_credential.name,
                )

        detail = {
            **self._request_debug_detail(normalized_stage_key, workflow_id, safe_parameters, workflow_info),
            "credential_attempts": attempts,
        }
        error_code = _coze_error_code_from_detail(detail)
        detail["coze_error_hint"] = _coze_error_hint(error_code, workflow_id)
        raise CozeWorkflowError(
            f"All Coze credentials failed: {last_error or 'no credential attempted'}",
            stage_key=normalized_stage_key,
            workflow_id=workflow_id,
            error=detail,
            detail=detail,
        )

    def _run_workflow_by_id_once(
        self,
        workflow_id: str,
        *,
        parameters: dict[str, Any],
        stream: bool,
        stage_key: str,
        workflow_info: dict[str, Any],
        credential: CozeCredential,
    ) -> dict[str, Any]:
        normalized_stage_key = normalize_coze_stage_key(stage_key)
        safe_parameters = _jsonable(parameters or {})
        if not credential.base_url:
            raise CozeWorkflowError(
                "Coze credential base_url is invalid",
                stage_key=normalized_stage_key,
                workflow_id=workflow_id,
                detail={
                    **self._request_debug_detail(normalized_stage_key, workflow_id, safe_parameters, workflow_info, credential),
                    "credential_config_invalid": True,
                    "credential_config_error": credential.token_detail.get("base_url_error") or "base_url_empty",
                },
            )
        if credential.token_detail.get("token_had_bearer_prefix"):
            raise CozeWorkflowError(
                "Coze credential token must not include Bearer prefix",
                stage_key=normalized_stage_key,
                workflow_id=workflow_id,
                detail={
                    **self._request_debug_detail(normalized_stage_key, workflow_id, safe_parameters, workflow_info, credential),
                    "credential_config_invalid": True,
                    "credential_config_error": "token_has_bearer_prefix",
                },
            )
        if credential.token_detail.get("token_contains_newline") or credential.token_detail.get("token_too_short"):
            raise CozeWorkflowError(
                "Coze credential token format is invalid",
                stage_key=normalized_stage_key,
                workflow_id=workflow_id,
                detail={
                    **self._request_debug_detail(normalized_stage_key, workflow_id, safe_parameters, workflow_info, credential),
                    "credential_config_invalid": True,
                    "credential_config_error": "token_format_error",
                },
            )
        if not credential.token:
            raise CozeWorkflowError(
                f"{credential.token_env} is required for Coze workflow backend",
                stage_key=normalized_stage_key,
                workflow_id=workflow_id,
                detail={
                    **self._request_debug_detail(normalized_stage_key, workflow_id, safe_parameters, workflow_info, credential),
                    "credential_config_invalid": True,
                    "credential_config_error": "token_empty",
                },
            )

        coze = self._client(credential)
        base_url = credential.base_url
        base_url_source = credential.base_url_source
        bot_app_info = self._bot_app_info_for_stage(normalized_stage_key)
        run_kwargs = {
            "workflow_id": workflow_id,
            "parameters": safe_parameters,
        }
        if bot_app_info["bot_id"]:
            run_kwargs["bot_id"] = bot_app_info["bot_id"]
        if bot_app_info["app_id"]:
            run_kwargs["app_id"] = bot_app_info["app_id"]
        logger.info(
            "Coze workflow request start backend=coze stage_key=%s workflow_id_status=%s workflow_id_source=%s credential_name=%s auth_type=%s token_status=%s token_prefix=%s token_len=%s token_expires_at=%s token_days_left=%s base_url=%s base_url_source=%s stream=%s bot_id_status=%s app_id_status=%s parameter_keys=%s",
            normalized_stage_key,
            "SET" if workflow_id else "EMPTY",
            workflow_info.get("workflow_id_source") or "",
            credential.name,
            credential.auth_type,
            "SET" if credential.token else "EMPTY",
            _safe_token_prefix(credential.token),
            len(credential.token),
            credential.token_expires_at,
            _days_left(credential.token_expires_at),
            base_url,
            base_url_source,
            stream,
            bot_app_info["bot_id_status"],
            bot_app_info["app_id_status"],
            sorted(safe_parameters.keys()),
        )
        raw_events: list[Any] = []
        messages: list[str] = []
        try:
            if stream:
                from cozepy import WorkflowEventType

                for event in coze.workflows.runs.stream(**run_kwargs):
                    raw_events.append(event)
                    event_type = getattr(event, "event", None) or getattr(event, "type", None)
                    data = getattr(event, "message", None) or getattr(event, "data", None) or event
                    if event_type == WorkflowEventType.MESSAGE:
                        text = _first_text(_event_to_jsonable(data), ("content", "answer", "message", "data"))
                        if text:
                            messages.append(text)
                    elif event_type == WorkflowEventType.ERROR:
                        error_data = getattr(event, "error", None) or data
                        error_jsonable = _event_to_jsonable(error_data)
                        error_code = _deep_find_key(error_jsonable, "code") if isinstance(error_jsonable, (dict, list)) else None
                        error_msg = (
                            _deep_find_key(error_jsonable, "msg")
                            or _deep_find_key(error_jsonable, "message")
                            if isinstance(error_jsonable, (dict, list))
                            else None
                        )
                        raise CozeWorkflowError(
                            f"Coze workflow returned ERROR event: {json.dumps(error_jsonable, ensure_ascii=False, default=str)}",
                            stage_key=normalized_stage_key,
                            workflow_id=workflow_id,
                            error=error_jsonable,
                            detail={
                                **self._request_debug_detail(normalized_stage_key, workflow_id, safe_parameters, workflow_info, credential),
                                "original_exception_type": "CozeWorkflowError",
                                "original_exception_message": "Coze workflow returned ERROR event",
                                "code": error_code or "",
                                "msg": error_msg or "",
                                "original_error_code": error_code or "",
                                "original_error_msg": error_msg or "",
                                "debug_url": _deep_find_key(error_jsonable, "debug_url") if isinstance(error_jsonable, (dict, list)) else "",
                                "coze_error_event": error_jsonable,
                                "stream_event_count": len(raw_events),
                                "stream_message_count": len(messages),
                                "received_stream_output": bool(messages),
                            },
                        )
                    elif event_type == WorkflowEventType.INTERRUPT:
                        interrupt_data = getattr(event, "interrupt", None) or data
                        raise CozeWorkflowError(
                            "Coze workflow returned INTERRUPT; resume strategy is not configured",
                            stage_key=normalized_stage_key,
                            workflow_id=workflow_id,
                            error=_event_to_jsonable(interrupt_data),
                            detail={
                                **self._request_debug_detail(normalized_stage_key, workflow_id, safe_parameters, workflow_info, credential),
                                "coze_interrupt_event": _event_to_jsonable(interrupt_data),
                                "stream_event_count": len(raw_events),
                                "stream_message_count": len(messages),
                                "received_stream_output": bool(messages),
                            },
                        )
                raw: Any = {"events": [_event_to_jsonable(item) for item in raw_events], "content": "".join(messages)}
            else:
                raw = coze.workflows.runs.create(**run_kwargs)
        except CozeWorkflowError as exc:
            _augment_authentication_failure_detail(exc.detail)
            _augment_region_mismatch_detail(exc.detail)
            raise
        except Exception as exc:
            detail = {
                **self._request_debug_detail(normalized_stage_key, workflow_id, safe_parameters, workflow_info, credential),
                **_exception_detail(exc),
                "traceback": traceback.format_exc(limit=8),
                "stream_event_count": len(raw_events),
                "stream_message_count": len(messages),
                "received_stream_output": bool(messages),
            }
            _augment_authentication_failure_detail(detail)
            _augment_region_mismatch_detail(detail)
            logger.exception(
                "Coze workflow request exception stage_key=%s workflow_id=%s credential_name=%s base_url=%s parameter_keys=%s",
                normalized_stage_key,
                workflow_id,
                credential.name,
                base_url,
                sorted(safe_parameters.keys()),
            )
            raise CozeWorkflowError(
                _coze_error_message(exc, detail),
                stage_key=normalized_stage_key,
                workflow_id=workflow_id,
                error=detail,
                detail=detail,
            ) from exc
        normalized = self.normalize_response(normalized_stage_key, workflow_id, raw)
        normalized.setdefault("coze_credential_name", credential.name)
        return normalized

    def _credential_success_attempt(self, credential: CozeCredential) -> dict[str, Any]:
        return {
            **_safe_credential_detail(credential),
            "success": True,
            "fallback_allowed": False,
            "error_code": "",
            "error_message": "",
        }

    def _credential_failure_attempt(
        self,
        credential: CozeCredential,
        exc: CozeWorkflowError,
        fallback_allowed: bool,
        fallback_reason: str,
    ) -> dict[str, Any]:
        detail = getattr(exc, "detail", {}) if isinstance(getattr(exc, "detail", None), dict) else {}
        return {
            **_safe_credential_detail(credential),
            "success": False,
            "error_code": _coze_error_code_from_detail(detail),
            "error_message": _coze_error_message_from_detail(detail) or str(exc),
            "fallback_allowed": bool(fallback_allowed),
            "fallback_reason": fallback_reason,
            "original_exception_type": detail.get("original_exception_type") or type(exc).__name__,
        }

    def _fallback_allowed(self, exc: CozeWorkflowError) -> tuple[bool, str]:
        detail = getattr(exc, "detail", {}) if isinstance(getattr(exc, "detail", None), dict) else {}
        if detail.get("received_stream_output"):
            return False, "stream_output_already_received"
        if detail.get("missing_input_variables"):
            return False, "missing_input_variables"
        if detail.get("bot_app_conflict"):
            return False, "bot_id_and_app_id_conflict"
        if detail.get("workflow_id_status") == "EMPTY" or not detail.get("workflow_id_exists", True):
            return False, "workflow_id_missing"
        if detail.get("credential_config_invalid"):
            return True, str(detail.get("credential_config_error") or "credential_config_invalid")

        code = _coze_error_code_from_detail(detail)
        msg = _coze_error_message_from_detail(detail).lower()
        if code in {"4000", "4200"}:
            return False, f"non_fallback_code_{code}"
        if code in {"4100", "4101", "700012006"}:
            return True, f"fallback_code_{code}"
        if "authentication is invalid" in msg or "access token invalid" in msg:
            return True, "authentication_invalid"
        if "permission denied" in msg or "permission" in msg and "denied" in msg:
            return True, "permission_denied"

        exc_type = str(detail.get("original_exception_type") or "")
        timeout_like = "Timeout" in exc_type or "timeout" in msg or "timed out" in msg
        if timeout_like:
            return (_env_flag("COZE_FALLBACK_ON_TIMEOUT", "0"), "timeout")
        network_like = any(marker in exc_type for marker in ("Connection", "Connect", "Proxy", "SSLError", "Network"))
        if network_like and _env_flag("COZE_FALLBACK_ON_NETWORK", "1"):
            return True, "network_error"
        return False, "not_fallback_error"

    def _missing_input_variables(self, stage_key: str, parameters: dict[str, Any]) -> list[str]:
        stage = self.stage_config(stage_key)
        required = list(dict.fromkeys(str(value) for value in stage.input_mapping.values() if str(value).strip()))
        return [key for key in required if key not in parameters]

    def build_parameters(
        self,
        stage_key: str,
        project_state: dict[str, Any],
        extra_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stage = self.stage_config(stage_key)
        parameters: dict[str, Any] = {}
        for source_key, target_key in stage.input_mapping.items():
            if source_key in project_state:
                parameters[target_key] = project_state[source_key]
        if extra_parameters:
            for key, value in extra_parameters.items():
                parameters[str(key)] = value
        return parameters

    def normalize_response(self, stage_key: str, workflow_id: str, raw_response: Any) -> dict[str, Any]:
        raw_jsonable = _event_to_jsonable(raw_response)
        content = _first_text(raw_jsonable, ("content", "answerText", "textOutput", "message", "data", "output", "result"))
        parsed = _try_json_loads(content) if content else _try_json_loads(raw_jsonable)
        stage = self.stage_config(stage_key) if stage_key else None
        normalized: dict[str, Any] = {
            "stage_key": stage_key,
            "workflow_id": workflow_id,
            "ok": True,
            "content": content,
            "parsed": parsed,
            "raw_response": raw_jsonable,
            "error": None,
        }
        if isinstance(parsed, dict):
            normalized.update(parsed)
        elif isinstance(raw_jsonable, dict):
            normalized.update(raw_jsonable)

        if stage:
            self._apply_output_mapping(normalized, parsed, raw_jsonable, stage)
        return normalize_stage_output(stage_key, normalized, backend="coze", backend_stage_key=stage_key)

    def stage_config(self, stage_key: str) -> CozeStageConfig:
        stage_key = normalize_coze_stage_key(stage_key)
        stages = self.config.get("stages")
        if not isinstance(stages, dict):
            raise CozeWorkflowError("Coze workflow config missing stages")
        if stage_key not in stages:
            raise CozeWorkflowError(f"Unknown Coze stage_key: {stage_key}", stage_key=stage_key)
        raw = stages[stage_key]
        if not isinstance(raw, dict):
            raise CozeWorkflowError(f"Invalid Coze stage config: {stage_key}", stage_key=stage_key)
        fallbacks = raw.get("output_fallbacks") or self.config.get("output_fallbacks") or []
        return CozeStageConfig(
            key=stage_key,
            name=str(raw.get("name") or stage_key),
            workflow_id=str(raw.get("workflow_id") or ""),
            workflow_id_env=str(raw.get("workflow_id_env") or ""),
            yaml_path=str(raw.get("yaml_path") or ""),
            input_mapping=dict(raw.get("input_mapping") or {}),
            output_mapping=dict(raw.get("output_mapping") or {}),
            output_fallbacks=tuple(str(item) for item in fallbacks),
        )

    def workflow_id_for_stage(self, stage_key: str) -> str:
        return str(self.workflow_id_info_for_stage(stage_key).get("workflow_id") or "")

    def workflow_id_info_for_stage(self, stage_key: str) -> dict[str, Any]:
        normalized_stage_key = normalize_coze_stage_key(stage_key)
        stage = self.stage_config(normalized_stage_key)
        resource_path, inner_yaml_path = self._stage_resource_paths(stage)
        stage = self.stage_config(stage_key)
        if stage.workflow_id_env:
            env_value = os.getenv(stage.workflow_id_env)
            if env_value and env_value.strip():
                return {
                    "input_stage_key": str(stage_key),
                    "normalized_stage_key": normalized_stage_key,
                    "workflow_id": env_value.strip(),
                    "workflow_id_source": stage.workflow_id_env,
                    "workflow_id_env": stage.workflow_id_env,
                    "config_path": str(self.config_path),
                    "resource_path": resource_path,
                    "inner_yaml_path": inner_yaml_path,
                }
        return {
            "input_stage_key": str(stage_key),
            "normalized_stage_key": normalized_stage_key,
            "workflow_id": stage.workflow_id,
            "workflow_id_source": str(self.config_path) if stage.workflow_id else "",
            "workflow_id_env": stage.workflow_id_env,
            "config_path": str(self.config_path),
            "resource_path": resource_path,
            "inner_yaml_path": inner_yaml_path,
        }

    def _stage_resource_paths(self, stage: CozeStageConfig) -> tuple[str, str]:
        yaml_path = str(stage.yaml_path or "")
        if "::" in yaml_path:
            zip_name, inner = yaml_path.split("::", 1)
            return str(_repo_root() / "BETTER_FRAMEWORK_JSONS" / zip_name), inner
        if yaml_path:
            path = Path(yaml_path)
            if not path.is_absolute():
                path = _repo_root() / "BETTER_FRAMEWORK_JSONS" / path
            return str(path), ""
        return "", ""

    def _request_debug_detail(
        self,
        stage_key: str,
        workflow_id: str,
        parameters: dict[str, Any],
        workflow_info: dict[str, Any],
        credential: CozeCredential | None = None,
    ) -> dict[str, Any]:
        if credential is None:
            try:
                credential = self.credentials()[0]
            except Exception:
                credential = None
        base_url = credential.base_url if credential else ""
        base_url_source = credential.base_url_source if credential else self.base_url_env
        credential_detail = _safe_credential_detail(credential) if credential else {}
        chain_detail = self.credential_chain()[1]
        bot_app_info = self._bot_app_info_for_stage(stage_key)
        missing_input_variables = self._missing_input_variables(stage_key, parameters)
        bot_app_conflict = bool(bot_app_info.get("bot_id") and bot_app_info.get("app_id"))
        env_name = str(workflow_info.get("workflow_id_env") or "")
        env_workflow_id = str(os.getenv(env_name) or "").strip() if env_name else ""
        workflow_id_override_mismatch = bool(env_workflow_id and workflow_id and env_workflow_id != workflow_id)
        return {
            "workflow_backend": str(os.getenv("WORKFLOW_BACKEND") or settings.workflow_backend or ""),
            "env_loaded_paths": [str(path) for path in getattr(settings, "loaded_env_paths", ())],
            "env_path": str(getattr(settings, "env_path", "")),
            "config_path": str(self.config_path),
            "stage_key": str(stage_key),
            "normalized_stage_key": normalize_coze_stage_key(stage_key),
            "backend_stage_key": normalize_coze_stage_key(stage_key),
            "workflow_id": workflow_id,
            "workflow_id_exists": bool(workflow_id),
            "workflow_id_status": "SET" if workflow_id else "EMPTY",
            "workflow_id_source": workflow_info.get("workflow_id_source") or "",
            "workflow_id_env": env_name,
            "workflow_id_env_value": env_workflow_id,
            "workflow_id_override_mismatch": workflow_id_override_mismatch,
            "workflow_id_override_warning": (
                f"检测到 workflow_id 覆盖异常：env={env_workflow_id}，resolved={workflow_id}，请检查配置优先级。"
                if workflow_id_override_mismatch
                else ""
            ),
            **credential_detail,
            **chain_detail,
            "credential_order_env": str(os.getenv("COZE_CREDENTIALS_ORDER") or ""),
            "base_url_status": _env_status(self.base_url_env),
            "base_url": base_url,
            "base_url_source": base_url_source,
            "base_url_region": _base_url_region(base_url),
            "cozepy_version": _cozepy_version(),
            "request_parameters_keys": sorted(parameters.keys()),
            "missing_input_variables": missing_input_variables,
            "resource_path": workflow_info.get("resource_path") or "",
            "inner_yaml_path": workflow_info.get("inner_yaml_path") or "",
            "sdk_optional_parameters_supported": ["bot_id", "app_id"],
            "bot_app_conflict": bot_app_conflict,
            **bot_app_info,
        }

    def _apply_output_mapping(
        self,
        normalized: dict[str, Any],
        parsed: Any,
        raw_jsonable: Any,
        stage: CozeStageConfig,
    ) -> None:
        for source_key, target_key in stage.output_mapping.items():
            value = None
            if isinstance(parsed, dict):
                value = _deep_find_key(parsed, source_key)
            if value is None and isinstance(raw_jsonable, dict):
                value = _deep_find_key(raw_jsonable, source_key)
            if value is None and source_key in {"output", "data", "content"}:
                value = parsed if parsed not in (None, "", {}, []) else normalized.get("content")
            if value is None:
                continue
            value = _try_json_loads(value)
            normalized[target_key] = value
            if isinstance(value, dict):
                normalized.update(value)

        if len(stage.output_mapping) == 1:
            target_key = next(iter(stage.output_mapping.values()))
            if target_key not in normalized and parsed not in (None, "", {}, []):
                normalized[target_key] = parsed

    def _client(self, credential: CozeCredential | None = None) -> Any:
        if credential is None:
            credential = self.credentials()[0]
        token = credential.token
        base_url = credential.base_url
        signature = (credential.name, token, base_url)
        if self._coze is not None and (self._coze_signature is None or self._coze_signature == signature):
            return self._coze
        from cozepy import Coze, TokenAuth

        self._coze = Coze(auth=TokenAuth(token=token), base_url=base_url)
        self._coze_signature = signature
        return self._coze


def _event_to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _event_to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_event_to_jsonable(v) for v in value]
    for attr in ("model_dump", "dict", "to_dict"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                return _event_to_jsonable(method())
            except Exception:
                pass
    if hasattr(value, "__dict__"):
        return {
            str(k): _event_to_jsonable(v)
            for k, v in vars(value).items()
            if not str(k).startswith("_")
        }
    return str(value)


coze_workflow_client = CozeWorkflowClient()


def use_coze_workflow_backend() -> bool:
    backend = str(os.getenv("WORKFLOW_BACKEND") or getattr(settings, "workflow_backend", "") or "coze")
    return backend.strip().lower() in {"coze", "volcengine", "volcano"}
