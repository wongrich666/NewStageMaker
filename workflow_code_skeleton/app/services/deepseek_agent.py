from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests


class DeepSeekAgentError(RuntimeError):
    pass


def _env(*keys: str, default: str = "") -> str:
    for key in keys:
        value = str(os.getenv(key) or "").strip()
        if value:
            return value
    return default


@dataclass(frozen=True, slots=True)
class DeepSeekAgentConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


def get_deepseek_agent_config() -> DeepSeekAgentConfig:
    base_url = _env(
        "AGENT_DEEPSEEK_BASE_URL",
        "WORKBUDDY_DEEPSEEK_BASE_URL",
        "DEEPSEEK_HOST",
        default="https://api.deepseek.com",
    ).rstrip("/")
    try:
        timeout_seconds = max(
            30,
            int(_env("AGENT_DEEPSEEK_TIMEOUT", "DEEPSEEK_TIMEOUT", default="600")),
        )
    except ValueError:
        timeout_seconds = 600
    return DeepSeekAgentConfig(
        api_key=_env(
            "AGENT_DEEPSEEK_API_KEY",
            "WORKBUDDY_DEEPSEEK_API_KEY",
            "DEEPSEEK_API_KEY",
        ),
        base_url=base_url,
        model=_env(
            "AGENT_DEEPSEEK_MODEL",
            "WORKBUDDY_DEEPSEEK_MODEL",
            "DEEPSEEK_MODEL",
            default="deepseek-v4-pro",
        ),
        timeout_seconds=timeout_seconds,
    )


def deepseek_agent_status() -> dict[str, Any]:
    config = get_deepseek_agent_config()
    missing: list[str] = []
    if not config.api_key:
        missing.append("AGENT_DEEPSEEK_API_KEY")
    if not config.base_url:
        missing.append("AGENT_DEEPSEEK_BASE_URL")
    if not config.model:
        missing.append("AGENT_DEEPSEEK_MODEL")
    return {
        "provider": "deepseek",
        "configured": not missing,
        "model": config.model,
        "timeout_seconds": config.timeout_seconds,
        "missing": missing,
    }


def _chat_completions_url(base_url: str) -> str:
    base = str(base_url or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _safe_upstream_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("code") or "").strip()
            if message:
                return message[:500]
        message = str(payload.get("message") or payload.get("code") or "").strip()
        if message:
            return message[:500]
    return f"上游返回 HTTP {response.status_code}"


class DeepSeekAgentClient:
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 8192,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        config = get_deepseek_agent_config()
        if not config.configured:
            raise DeepSeekAgentError(
                "DeepSeek智能体尚未配置完成：" + ", ".join(deepseek_agent_status()["missing"])
            )

        payload: dict[str, Any] = {
            "model": str(model or config.model),
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if response_format:
            payload["response_format"] = response_format

        try:
            response = requests.post(
                _chat_completions_url(config.base_url),
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=max(30, int(timeout_seconds or config.timeout_seconds)),
            )
        except requests.Timeout as exc:
            raise DeepSeekAgentError("DeepSeek V4 Pro请求超时，请稍后重试。") from exc
        except requests.RequestException as exc:
            raise DeepSeekAgentError(f"DeepSeek V4 Pro连接失败：{exc}") from exc

        if not response.ok:
            raise DeepSeekAgentError(_safe_upstream_error(response))

        try:
            data = response.json()
            message = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise DeepSeekAgentError("DeepSeek V4 Pro返回格式异常。") from exc

        return {
            "message": message if isinstance(message, dict) else {},
            "usage": data.get("usage") if isinstance(data, dict) else None,
            "model": str(data.get("model") or model or config.model),
            "request_id": str(data.get("id") or ""),
        }

    def complete_json(
        self,
        prompt: str,
        *,
        system_prompt: str = "你必须只输出一个合法JSON对象。",
        model: str | None = None,
        max_tokens: int = 32768,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        result = self.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            model=model,
            temperature=0.1,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        content = str((result.get("message") or {}).get("content") or "").strip()
        if not content:
            raise DeepSeekAgentError("DeepSeek V4 Pro没有返回内容。")
        try:
            structured = json.loads(content)
        except json.JSONDecodeError as exc:
            raise DeepSeekAgentError("DeepSeek V4 Pro没有返回合法JSON。") from exc
        if not isinstance(structured, dict):
            raise DeepSeekAgentError("DeepSeek V4 Pro返回的JSON不是对象。")
        return {
            "content": content,
            "structured_output": structured,
            "usage": result.get("usage"),
            "model": result.get("model"),
            "session_id": result.get("request_id"),
        }


deepseek_agent_client = DeepSeekAgentClient()
