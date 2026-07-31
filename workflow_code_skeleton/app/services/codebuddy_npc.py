from __future__ import annotations

import copy
import base64
import binascii
import gzip
import json
import os
import re
import socket
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.parse import urlsplit

import requests

from .script_delivery import build_delivery_script


RESULT_BEGIN = "__SCRIPT_TEAM_RESULT_BEGIN__"
RESULT_END = "__SCRIPT_TEAM_RESULT_END__"
STAGE_RESULT_BEGIN = "__SCRIPT_TEAM_STAGE_BEGIN__"
STAGE_RESULT_END = "__SCRIPT_TEAM_STAGE_END__"
STAGE_RESULT_GZIP_BEGIN = "__SCRIPT_TEAM_STAGE_GZIP_BEGIN__"
STAGE_RESULT_GZIP_END = "__SCRIPT_TEAM_STAGE_GZIP_END__"
GATE_BEGIN = "__SCRIPT_TEAM_GATE_BEGIN__"
GATE_END = "__SCRIPT_TEAM_GATE_END__"
TERMINAL_SUCCESS = {"success", "succeeded", "completed", "complete"}
TERMINAL_FAILURE = {"error", "failed", "failure", "cancel", "canceled", "cancelled", "stopped"}
ACTIVE_STATUSES = {"pending", "queued", "waiting", "start", "running", "in_progress"}
_DNS_FALLBACK_LOCK = threading.Lock()
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
_ARTIFACT_FILENAMES = {
    "contract": "01_contract.md",
    "story": "02_story.md",
    "characters": "03_characters.md",
    "episodes": "04_episodes.md",
    "draft": "05_draft.txt",
    "story_state": "story_state.json",
}
STAGE_ORDER = (
    "showrunner",
    "story_architect",
    "character_emotion",
    "episode_continuity",
    "script_writer",
    "state_recorder",
    "final_editor",
)
STAGE_ARTIFACTS = {
    "showrunner": "contract",
    "story_architect": "story",
    "character_emotion": "characters",
    "episode_continuity": "episodes",
    "script_writer": "draft",
    "state_recorder": "story_state",
    "final_editor": "final_script",
}
STAGE_REQUIRED_ARTIFACTS = {
    "showrunner": (),
    "story_architect": ("contract",),
    "character_emotion": ("contract", "story"),
    "episode_continuity": ("contract", "story", "characters"),
    "script_writer": ("contract", "story", "characters", "episodes"),
    "state_recorder": ("contract", "characters", "episodes", "draft"),
    "final_editor": ("contract", "draft", "story_state"),
}
STAGE_NAMES = {
    "showrunner": "总编剧",
    "story_architect": "故事架构师",
    "character_emotion": "人物情感编剧",
    "episode_continuity": "分集连续性编剧",
    "script_writer": "正文对白编剧",
    "state_recorder": "状态记录器",
    "final_editor": "终审与钩子编辑",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _elapsed_ms(started_at: str, ended_at: str = "") -> int:
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        end = (
            datetime.fromisoformat(str(ended_at).replace("Z", "+00:00"))
            if ended_at
            else datetime.now(timezone.utc)
        )
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 0
    return max(0, int((end - start).total_seconds() * 1000))


def start_stage_timing(
    job: dict[str, Any],
    stage: str,
    *,
    reset: bool,
    execution_target: str,
) -> None:
    timings = copy.deepcopy(job.get("stage_timings") or {})
    current = timings.get(stage) if isinstance(timings.get(stage), dict) else {}
    if reset or not str(current.get("started_at") or ""):
        current = {
            "started_at": _now_iso(),
            "completed_at": "",
            "duration_ms": 0,
        }
    current["status"] = "running"
    current["execution_target"] = execution_target
    current["attempt"] = max(1, int(current.get("attempt") or 0) + (1 if reset else 0))
    timings[stage] = current
    job["stage_timings"] = timings
    job["active_stage_started_at"] = str(current.get("started_at") or "")


def finish_stage_timing(job: dict[str, Any], stage: str, *, status: str) -> None:
    timings = copy.deepcopy(job.get("stage_timings") or {})
    current = timings.get(stage) if isinstance(timings.get(stage), dict) else {}
    completed_at = _now_iso()
    started_at = str(current.get("started_at") or completed_at)
    current.update(
        {
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": _elapsed_ms(started_at, completed_at),
            "status": status,
        }
    )
    timings[stage] = current
    job["stage_timings"] = timings
    if str(job.get("active_stage") or "") == stage:
        job.pop("active_stage_started_at", None)


def _clean_text(value: Any, *, limit: int = 200_000) -> str:
    return str(value or "").strip()[:limit]


_EXCLUSIVE_EPISODE = re.compile(r"(?:只能|只(?:需|要)?|仅(?:需|要)?)")
_EPISODE_REFERENCE = re.compile(r"第\s*(\d{1,3})\s*集")
_DELIVERY_REFERENCE = re.compile(r"(?:最终|文件|正文|剧本|成品|交付|输出|生成|编写|写出|只写)")
_SOURCE_EPISODE_HEADER = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:《[^》\r\n]+》\s*[·\-—]?\s*)?"
    r"(?:第\s*(\d{1,3})\s*集|Episode\s*(\d{1,3})\b)"
)
_CREATION_MODES = {"原创", "改编", "续写"}
_CONTINUATION_POLICIES = {"strict", "light"}


def _normalize_episode_direction(
    direction: str,
    episodes: int,
    *,
    episode_start: int = 1,
) -> tuple[str, list[str]]:
    """Remove single-episode delivery clauses that contradict the numeric episode contract."""
    if not direction:
        return "", []
    kept: list[str] = []
    ignored: list[str] = []
    for match in re.finditer(r"[^；;。\n]+[；;。\n]*", direction):
        clause = match.group(0)
        episode_match = _EPISODE_REFERENCE.search(clause)
        is_single_episode_delivery = (
            episode_match
            and _EXCLUSIVE_EPISODE.search(clause)
            and _DELIVERY_REFERENCE.search(clause)
        )
        if is_single_episode_delivery:
            requested_episode = int(episode_match.group(1))
            if episodes != 1 or requested_episode != episode_start:
                ignored.append(clause.strip(" \t\r\n；;。"))
                continue
        kept.append(clause)
    normalized = "".join(kept).strip(" \t\r\n；;。")
    return normalized, ignored


def _detect_last_episode(source_text: str) -> int:
    numbers = [
        int(match.group(1) or match.group(2))
        for match in _SOURCE_EPISODE_HEADER.finditer(str(source_text or ""))
    ]
    return max(numbers, default=0)


def _episode_contract(
    episodes: int,
    *,
    episode_start: int = 1,
    source_last_episode: int = 0,
) -> str:
    episode_end = episode_start + episodes - 1
    if source_last_episode:
        return (
            f"续写范围硬合同：已有剧本写至第{source_last_episode}集；"
            f"必须且只能交付第{episode_start}集至第{episode_end}集，共{episodes}集；"
            f"不得重写第1集至第{source_last_episode}集。"
        )
    if episodes == 1:
        return "总集数硬合同：必须交付且只能交付第1集，共1集。"
    return (
        f"总集数硬合同：必须完整交付第1集至第{episodes}集，共{episodes}集；"
        "补充方向中的单集试写、只写某一集或只交付某一集要求一律无效。"
    )


def _normalize_status(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


@dataclass(frozen=True, slots=True)
class CodeBuddyNpcConfig:
    api_base: str
    repository: str
    access_token: str
    event: str
    model: str
    context_window: str
    branch: str
    timeout: int
    callback_token: str
    job_dir: Path
    fallback_ip: str = ""
    stage_event: str = "api_trigger_script_team_stage_custom_api"

    @classmethod
    def from_env(cls) -> "CodeBuddyNpcConfig":
        default_job_dir = (
            Path(__file__).resolve().parents[3]
            / "debug"
            / "codebuddy_npc_jobs"
        )
        return cls(
            api_base=os.getenv("CODEBUDDY_NPC_API_BASE", "https://api.cnb.cool").strip().rstrip("/"),
            repository=os.getenv("CODEBUDDY_NPC_REPOSITORY", "").strip().strip("/"),
            access_token=os.getenv("CODEBUDDY_NPC_ACCESS_TOKEN", "").strip(),
            event=os.getenv("CODEBUDDY_NPC_EVENT", "api_trigger_script_team").strip(),
            model=os.getenv("CODEBUDDY_NPC_MODEL", "deepseek-v4-pro").strip(),
            context_window=os.getenv("CODEBUDDY_NPC_CONTEXT_WINDOW", "1m").strip(),
            branch=os.getenv("CODEBUDDY_NPC_BRANCH", "main").strip(),
            timeout=max(5, int(os.getenv("CODEBUDDY_NPC_TIMEOUT", "30"))),
            callback_token=os.getenv("CODEBUDDY_NPC_CALLBACK_TOKEN", "").strip(),
            job_dir=Path(os.getenv("CODEBUDDY_NPC_JOB_DIR", str(default_job_dir))).expanduser(),
            fallback_ip=os.getenv("CODEBUDDY_NPC_FALLBACK_IP", "").strip(),
            stage_event=os.getenv(
                "CODEBUDDY_NPC_STAGE_EVENT",
                "api_trigger_script_team_stage_custom_api",
            ).strip(),
        )

    def missing(self) -> list[str]:
        missing: list[str] = []
        if not self.repository:
            missing.append("CODEBUDDY_NPC_REPOSITORY")
        if not self.access_token:
            missing.append("CODEBUDDY_NPC_ACCESS_TOKEN")
        if not self.event.startswith("api_trigger"):
            missing.append("CODEBUDDY_NPC_EVENT（必须以 api_trigger 开头）")
        if not self.stage_event.startswith("api_trigger"):
            missing.append("CODEBUDDY_NPC_STAGE_EVENT（必须以 api_trigger 开头）")
        return missing

    def public_status(self) -> dict[str, Any]:
        missing = self.missing()
        return {
            "provider": "CodeBuddy NPC / CNB",
            "ready": not missing,
            "missing": missing,
            "api_base": self.api_base,
            "repository": self.repository,
            "event": self.event,
            "stage_event": self.stage_event,
            "model": self.model,
            "context_window": self.context_window,
            "branch": self.branch,
            "access_token_configured": bool(self.access_token),
            "callback_token_configured": bool(self.callback_token),
            "dns_fallback_configured": bool(self.fallback_ip),
        }


class CodeBuddyNpcError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502, detail: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class CodeBuddyNpcJobStore:
    def __init__(self, config: CodeBuddyNpcConfig | None = None) -> None:
        self.config = config or CodeBuddyNpcConfig.from_env()
        self.config.job_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, job_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "", str(job_id or ""))
        if not safe:
            raise CodeBuddyNpcError("无效的 NPC 任务编号。", status_code=400)
        return self.config.job_dir / f"{safe}.json"

    def save(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = copy.deepcopy(job)
        payload["updated_at"] = _now_iso()
        path = self._path(str(payload["job_id"]))
        payload["artifact_files"] = self._persist_artifacts(payload)
        with self._lock:
            tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(path)
            finally:
                tmp.unlink(missing_ok=True)
        return payload

    def _persist_artifacts(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        job_id = str(payload.get("job_id") or "")
        safe_job_id = re.sub(r"[^A-Za-z0-9_-]", "", job_id)
        if not safe_job_id:
            return []
        artifact_dir = self.config.job_dir / safe_job_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        values = payload.get("recovered_files")
        values = values if isinstance(values, dict) else {}
        files: list[tuple[str, str, str]] = []
        for key, filename in _ARTIFACT_FILENAMES.items():
            content = str(values.get(key) or "").strip()
            if content:
                files.append((key, filename, content))
        final_script = str(payload.get("final_script") or "").strip()
        if final_script:
            files.append(("final_script", "final_script.txt", final_script))
        quality_gate = payload.get("quality_gate")
        if isinstance(quality_gate, dict) and quality_gate:
            files.append(
                (
                    "quality_gate",
                    "gate_final.json",
                    json.dumps(quality_gate, ensure_ascii=False, indent=2),
                )
            )

        manifest: list[dict[str, Any]] = []
        for key, filename, content in files:
            destination = artifact_dir / filename
            tmp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
            try:
                tmp.write_text(content, encoding="utf-8")
                tmp.replace(destination)
            finally:
                tmp.unlink(missing_ok=True)
            manifest.append(
                {
                    "key": key,
                    "filename": filename,
                    "chars": len(content),
                }
            )
        return manifest

    def load(self, job_id: str, *, user_id: int) -> dict[str, Any] | None:
        path = self._path(job_id)
        if not path.is_file():
            return None
        with self._lock:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        if int(payload.get("user_id") or 0) != int(user_id):
            return None
        return payload

    def latest(self, *, user_id: int) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        with self._lock:
            for path in self.config.job_dir.glob("npc-*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if int(payload.get("user_id") or 0) == int(user_id):
                    candidates.append(payload)
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        )

    def list(self, *, user_id: int) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        with self._lock:
            for path in self.config.job_dir.glob("npc-*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if int(payload.get("user_id") or 0) == int(user_id):
                    candidates.append(payload)
        return sorted(
            candidates,
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )

    def delete(self, job_id: str, *, user_id: int) -> bool:
        job = self.load(job_id, user_id=user_id)
        if not job:
            return False
        path = self._path(job_id)
        artifact_dir = self.config.job_dir / re.sub(r"[^A-Za-z0-9_-]", "", job_id)
        with self._lock:
            if path.is_file():
                path.unlink()
            if artifact_dir.is_dir():
                for child in artifact_dir.iterdir():
                    if child.is_file():
                        child.unlink()
                artifact_dir.rmdir()
        return True

    def create(self, *, user_id: int, request_payload: dict[str, Any]) -> dict[str, Any]:
        title = _clean_text(request_payload.get("project_title"), limit=120)
        source_text = _clean_text(request_payload.get("source_text"))
        direction = _clean_text(request_payload.get("adaptation_direction"), limit=20_000)
        mode = _clean_text(request_payload.get("mode"), limit=30) or "原创"
        if mode not in _CREATION_MODES:
            mode = "原创"
        if not title:
            raise CodeBuddyNpcError("请填写项目名称。", status_code=400)
        if mode == "续写" and not source_text:
            raise CodeBuddyNpcError("续写模式必须上传或粘贴已有剧本。", status_code=400)
        if not source_text and not direction:
            raise CodeBuddyNpcError("请填写原始材料或创作要求。", status_code=400)

        try:
            requested_episodes = min(120, max(1, int(request_payload.get("episodes") or 5)))
            episode_word_count = min(5000, max(100, int(request_payload.get("episode_word_count") or 800)))
            episode_duration_seconds = min(
                1800,
                max(15, int(request_payload.get("episode_duration_seconds") or 90)),
            )
        except (TypeError, ValueError) as exc:
            raise CodeBuddyNpcError("集数、每集字数或剧集时长格式不正确。", status_code=400) from exc
        scenes_per_episode = _clean_text(
            request_payload.get("scenes_per_episode"), limit=20
        ) or "1"
        if scenes_per_episode not in {"1", "1-2", "2", "2-3", "flexible"}:
            scenes_per_episode = "1"

        source_last_episode = 0
        episode_start = 1
        episode_end = requested_episodes
        series_total_episodes = requested_episodes
        episodes = requested_episodes
        continuation_policy = _clean_text(
            request_payload.get("continuation_policy"), limit=20
        ) or "strict"
        if continuation_policy not in _CONTINUATION_POLICIES:
            continuation_policy = "strict"
        if mode == "续写":
            detected_last_episode = _detect_last_episode(source_text)
            try:
                manual_last_episode = max(
                    0,
                    min(999, int(request_payload.get("source_last_episode") or 0)),
                )
                target_episode = max(
                    1,
                    min(
                        999,
                        int(
                            request_payload.get("continuation_target_episode")
                            or (
                                (detected_last_episode or manual_last_episode)
                                + requested_episodes
                            )
                        ),
                    ),
                )
            except (TypeError, ValueError) as exc:
                raise CodeBuddyNpcError(
                    "当前最后一集或续写目标集数格式不正确。",
                    status_code=400,
                ) from exc
            source_last_episode = detected_last_episode or manual_last_episode
            if source_last_episode < 1:
                raise CodeBuddyNpcError(
                    "未能从已有剧本识别集号，请手动填写当前最后一集。",
                    status_code=400,
                )
            if target_episode <= source_last_episode:
                raise CodeBuddyNpcError(
                    f"续写目标必须大于当前第{source_last_episode}集。",
                    status_code=400,
                )
            episodes = target_episode - source_last_episode
            if episodes > 120:
                raise CodeBuddyNpcError(
                    "单次最多续写120集，请缩小本次续写范围。",
                    status_code=400,
                )
            episode_start = source_last_episode + 1
            episode_end = target_episode
            series_total_episodes = target_episode

        direction, ignored_directions = _normalize_episode_direction(
            direction,
            episodes,
            episode_start=episode_start,
        )

        job_id = f"npc-{uuid.uuid4().hex[:16]}"
        job = {
            "job_id": job_id,
            "user_id": int(user_id),
            "status": "created",
            "status_text": "等待提交到 CodeBuddy NPC",
            "progress": 0,
            "request": {
                "project_title": title,
                "mode": mode,
                "production_type": _clean_text(request_payload.get("production_type"), limit=50) or "AI漫剧",
                "target_market": _clean_text(request_payload.get("target_market"), limit=100) or "中国大陆",
                "genre": _clean_text(request_payload.get("genre"), limit=100),
                "episodes": episodes,
                "source_last_episode": source_last_episode,
                "episode_start": episode_start,
                "episode_end": episode_end,
                "series_total_episodes": series_total_episodes,
                "continuation_target_episode": episode_end,
                "continuation_policy": continuation_policy,
                "episode_word_count": episode_word_count,
                "episode_duration_seconds": episode_duration_seconds,
                "total_duration_seconds": episodes * episode_duration_seconds,
                "scenes_per_episode": scenes_per_episode,
                "source_text": source_text,
                "adaptation_direction": direction,
                "episode_contract": _episode_contract(
                    episodes,
                    episode_start=episode_start,
                    source_last_episode=source_last_episode,
                ),
            },
            "request_warnings": [
                f"已忽略与总集数 {episodes} 集冲突的补充要求：{item}"
                for item in ignored_directions
            ],
            "provider": self.config.public_status(),
            "build": {},
            "team_stages": [],
            "stage_timings": {},
            "stage_outputs": {},
            "stage_versions": {},
            "execution_mode": _clean_text(request_payload.get("execution_mode"), limit=20) or "step",
            "execution_target": "remote_cnb",
            "remote_kind": "",
            "remote_stage": "",
            "remote_retry_count": 0,
            "remote_retry_limit": 0,
            "active_stage": "",
            "cancel_requested": False,
            "final_script": "",
            "error": "",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        return self.save(job)


class CodeBuddyNpcClient:
    def __init__(
        self,
        config: CodeBuddyNpcConfig | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config or CodeBuddyNpcConfig.from_env()
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        authorization = self.config.access_token
        if authorization and not authorization.lower().startswith("bearer "):
            authorization = f"Bearer {authorization}"
        return {
            "Authorization": authorization,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.config.api_base}{path}"
        try:
            response = self.session.request(
                method,
                url,
                headers=self._headers(),
                timeout=self.config.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            hostname = str(urlsplit(url).hostname or "")
            is_dns_error = "name resolution" in str(exc).lower() or "getaddrinfo failed" in str(exc).lower()
            if not (self.config.fallback_ip and hostname and is_dns_error):
                raise CodeBuddyNpcError(f"无法连接 CNB：{exc}") from exc
            original_getaddrinfo = socket.getaddrinfo

            def fallback_getaddrinfo(
                host: str,
                port: int,
                family: int = 0,
                type: int = 0,
                proto: int = 0,
                flags: int = 0,
            ) -> list[Any]:
                target = self.config.fallback_ip if host == hostname else host
                return original_getaddrinfo(target, port, family, type, proto, flags)

            try:
                with _DNS_FALLBACK_LOCK:
                    socket.getaddrinfo = fallback_getaddrinfo
                    try:
                        response = self.session.request(
                            method,
                            url,
                            headers=self._headers(),
                            timeout=self.config.timeout,
                            **kwargs,
                        )
                    finally:
                        socket.getaddrinfo = original_getaddrinfo
            except requests.RequestException as retry_exc:
                raise CodeBuddyNpcError(f"无法连接 CNB：{retry_exc}") from retry_exc
        try:
            payload = response.json()
        except ValueError:
            payload = {"message": response.text[:2000]}
        if response.status_code >= 400:
            message = ""
            if isinstance(payload, dict):
                message = str(payload.get("message") or payload.get("error") or "")
            raise CodeBuddyNpcError(
                f"CNB 请求失败（HTTP {response.status_code}）{f'：{message}' if message else ''}",
                status_code=502,
                detail=payload,
            )
        return payload

    def trigger(self, job: dict[str, Any]) -> dict[str, Any]:
        missing = self.config.missing()
        if missing:
            raise CodeBuddyNpcError(
                "CodeBuddy NPC 尚未配置：" + "、".join(missing),
                status_code=503,
            )
        repo = quote(self.config.repository, safe="/")
        request_json = json.dumps(job.get("request") or {}, ensure_ascii=False, separators=(",", ":"))
        payload = {
            "event": self.config.event,
            "branch": self.config.branch,
            "sync": "false",
            "title": f"剧本团队：{(job.get('request') or {}).get('project_title') or job['job_id']}",
            "npc": {"name": "CodeBuddy", "workMode": False},
            "env": {
                "jobId": str(job["job_id"]),
                "scriptRequest": request_json,
                "model": self.config.model,
                "contextWindow": self.config.context_window,
            },
        }
        result = self._request("POST", f"/{repo}/-/build/start", json=payload)
        if not isinstance(result, dict) or result.get("success") is False or not result.get("sn"):
            raise CodeBuddyNpcError("CNB 没有返回有效构建号。", detail=result)
        return result

    def trigger_stage(
        self,
        job: dict[str, Any],
        *,
        stage: str,
        feedback: str = "",
        continue_after: bool = False,
    ) -> dict[str, Any]:
        missing = self.config.missing()
        if missing:
            raise CodeBuddyNpcError(
                "CodeBuddy NPC 尚未配置：" + "、".join(missing),
                status_code=503,
            )
        if stage not in STAGE_ORDER:
            raise CodeBuddyNpcError("未知的剧本团队节点。", status_code=400)
        recovered_files = job.get("recovered_files")
        recovered_files = recovered_files if isinstance(recovered_files, dict) else {}
        required_artifacts = STAGE_REQUIRED_ARTIFACTS[stage]
        artifact_bundle = {
            "recovered_files": {
                key: recovered_files[key]
                for key in required_artifacts
                if str(recovered_files.get(key) or "").strip()
            }
        }
        compressed = gzip.compress(
            json.dumps(artifact_bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        state_bundle = base64.b64encode(compressed).decode("ascii")
        request_data = copy.deepcopy(job.get("request") or {})
        if feedback:
            request_data["stage_feedback"] = _clean_text(feedback, limit=20_000)
        payload = {
            "event": self.config.stage_event,
            "branch": self.config.branch,
            "sync": "false",
            "title": f"剧本节点：{STAGE_NAMES[stage]}",
            "npc": {"name": "CodeBuddy", "workMode": False},
            "env": {
                "jobId": str(job["job_id"]),
                "scriptRequest": json.dumps(
                    request_data,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "scriptStage": stage,
                "scriptStateBundle": state_bundle,
                "model": self.config.model,
                "contextWindow": self.config.context_window,
            },
        }
        repo = quote(self.config.repository, safe="/")
        result = self._request("POST", f"/{repo}/-/build/start", json=payload)
        if not isinstance(result, dict) or result.get("success") is False or not result.get("sn"):
            raise CodeBuddyNpcError("CNB 没有返回有效构建号。", detail=result)
        result["remote_stage"] = stage
        result["continue_after"] = bool(continue_after)
        return result

    def build_status(self, sn: str) -> dict[str, Any]:
        repo = quote(self.config.repository, safe="/")
        result = self._request("GET", f"/{repo}/-/build/status/{quote(str(sn), safe='')}")
        return result if isinstance(result, dict) else {}

    def stop_build(self, sn: str) -> dict[str, Any]:
        build_sn = str(sn or "").strip()
        if not build_sn:
            raise CodeBuddyNpcError("CNB 构建号为空，无法停止远程任务。", status_code=400)
        repo = quote(self.config.repository, safe="/")
        result = self._request(
            "POST",
            f"/{repo}/-/build/stop/{quote(build_sn, safe='')}",
        )
        return result if isinstance(result, dict) else {}

    def stage_log(self, sn: str, pipeline_id: str, stage_id: str) -> dict[str, Any]:
        repo = quote(self.config.repository, safe="/")
        return self._request(
            "GET",
            (
                f"/{repo}/-/build/logs/stage/{quote(str(sn), safe='')}/"
                f"{quote(str(pipeline_id), safe='')}/{quote(str(stage_id), safe='')}"
            ),
        )

    def refresh(self, job: dict[str, Any]) -> dict[str, Any]:
        sn = str((job.get("build") or {}).get("sn") or "")
        if not sn:
            return job
        status_payload = self.build_status(sn)
        build_status = _normalize_status(status_payload.get("status"))
        pipelines = status_payload.get("pipelinesStatus")
        if not isinstance(pipelines, dict):
            pipelines = {}

        team_stages: list[dict[str, Any]] = []
        terminal_count = 0
        total_count = 0
        for pipeline_key, pipeline in pipelines.items():
            if not isinstance(pipeline, dict):
                continue
            pipeline_id = str(pipeline.get("id") or pipeline_key)
            for stage in pipeline.get("stages") or []:
                if not isinstance(stage, dict):
                    continue
                stage_status = _normalize_status(stage.get("status"))
                total_count += 1
                if stage_status in TERMINAL_SUCCESS | TERMINAL_FAILURE:
                    terminal_count += 1
                team_stages.append(
                    {
                        "pipeline_id": pipeline_id,
                        "id": str(stage.get("id") or ""),
                        "name": str(stage.get("name") or "NPC任务"),
                        "status": stage_status or "pending",
                        "duration": stage.get("duration"),
                    }
                )

        refreshed = copy.deepcopy(job)
        refreshed.pop("poll_warning", None)
        refreshed["team_stages"] = team_stages
        refreshed["build_status"] = status_payload
        if total_count:
            refreshed["progress"] = min(95, max(5, round(terminal_count / total_count * 90)))
        elif build_status in ACTIVE_STATUSES:
            refreshed["progress"] = max(5, int(refreshed.get("progress") or 0))

        if build_status not in TERMINAL_SUCCESS:
            if build_status in TERMINAL_FAILURE:
                pass
            else:
                refreshed["status"] = "running"
                refreshed["status_text"] = "CodeBuddy NPC 团队正在创作"
                return refreshed

        final_script = ""
        remote_stage = str(job.get("remote_stage") or "")
        stage_result = ""
        final_gate: dict[str, Any] = {}
        stage_outputs: dict[str, str] = {}
        recovered_files: dict[str, str] = {}
        for stage in team_stages:
            if stage["status"] not in TERMINAL_SUCCESS | TERMINAL_FAILURE or not stage["id"]:
                continue
            try:
                log_payload = self.stage_log(sn, stage["pipeline_id"], stage["id"])
            except CodeBuddyNpcError:
                continue
            content = log_payload.get("content") if isinstance(log_payload, dict) else []
            text = _clean_stage_log(content)
            stage_outputs[stage["name"]] = text[-30_000:]
            extracted = _extract_result_marker(text)
            if extracted:
                final_script = extracted
            extracted_stage, extracted_stage_result = _extract_stage_result_marker(text)
            if extracted_stage and (not remote_stage or extracted_stage == remote_stage):
                remote_stage = extracted_stage
                stage_result = extracted_stage_result
            gate = _extract_json_marker(text, GATE_BEGIN, GATE_END)
            if not gate and "门禁" in stage["name"]:
                gate = _extract_gate_report_from_log(text)
            if gate:
                final_gate = gate

            for logical_name, path in (
                ("contract", ".script-team/01_contract.md"),
                ("story", ".script-team/02_story.md"),
                ("characters", ".script-team/03_characters.md"),
                ("episodes", ".script-team/04_episodes.md"),
                ("draft", ".script-team/05_draft.txt"),
                ("story_state", ".script-team/story_state.json"),
                ("final_script", ".script-team/final_script.txt"),
                ("draft", "/tmp/script-team/05_script_writer.txt"),
                ("story_state", "/tmp/script-team/story_state.json"),
                ("final_script", "/tmp/script-team/07_final_script.txt"),
            ):
                recovered = _extract_written_file(text, path)
                if recovered:
                    recovered_files[logical_name] = recovered

        if str(job.get("remote_kind") or "") == "stage":
            if stage_result and remote_stage in STAGE_ARTIFACTS:
                artifact_key = STAGE_ARTIFACTS[remote_stage]
                if artifact_key == "final_script":
                    refreshed["final_script"] = stage_result
                else:
                    files = copy.deepcopy(refreshed.get("recovered_files") or {})
                    files[artifact_key] = stage_result
                    refreshed["recovered_files"] = files
                outputs = copy.deepcopy(refreshed.get("stage_outputs") or {})
                outputs[STAGE_NAMES[remote_stage]] = stage_result
                refreshed["stage_outputs"] = outputs
                refreshed["status"] = (
                    "completed" if artifact_key == "final_script" else "stage_ready"
                )
                refreshed["status_text"] = (
                    "专业剧本团队已交付"
                    if artifact_key == "final_script"
                    else f"{STAGE_NAMES[remote_stage]}已完成，等待确认"
                )
                finish_stage_timing(refreshed, remote_stage, status="success")
                refreshed["active_stage"] = ""
                refreshed["progress"] = round(
                    (STAGE_ORDER.index(remote_stage) + 1) / len(STAGE_ORDER) * 100
                )
                refreshed["error"] = ""
                return refreshed
            if build_status in TERMINAL_FAILURE:
                refreshed["status"] = "failed"
                refreshed["status_text"] = f"{STAGE_NAMES.get(remote_stage, '远程节点')}运行失败"
                refreshed["error"] = f"CNB 构建状态：{build_status}"
                refreshed["active_stage"] = ""
                return refreshed
            refreshed["status"] = "result_pending"
            refreshed["status_text"] = f"{STAGE_NAMES.get(remote_stage, '远程节点')}已结束，正在读取产物"
            refreshed["progress"] = max(1, int(refreshed.get("progress") or 0))
            return refreshed

        if not final_script:
            final_script = str(recovered_files.get("final_script") or "")
        refreshed["stage_outputs"] = stage_outputs
        refreshed["recovered_files"] = {
            key: value
            for key, value in recovered_files.items()
            if key != "final_script"
        }
        if final_gate:
            refreshed["quality_gate"] = final_gate

        if final_script:
            refreshed["final_script"] = final_script
            gate_ok = final_gate.get("ok") if final_gate else None
            if gate_ok is False or build_status in TERMINAL_FAILURE:
                refreshed["status"] = "completed_with_warnings"
                refreshed["status_text"] = "最终稿已恢复，严格门禁有待修项"
                refreshed["error"] = _quality_gate_summary(final_gate)
            elif final_gate.get("warnings"):
                refreshed["status"] = "completed_with_warnings"
                refreshed["status_text"] = "专业剧本团队已交付，含非阻断提示"
                refreshed["error"] = ""
            else:
                refreshed["status"] = "completed"
                refreshed["status_text"] = "专业剧本团队已交付"
                refreshed["error"] = ""
            refreshed["progress"] = 100
            refreshed["recovered_at"] = _now_iso()
            return refreshed

        if build_status in TERMINAL_FAILURE:
            refreshed["status"] = "failed"
            refreshed["status_text"] = "CodeBuddy NPC 执行失败"
            refreshed["error"] = f"CNB 构建状态：{build_status}"
            refreshed["recovery_checked_at"] = _now_iso()
            return refreshed

        if build_status not in TERMINAL_SUCCESS:
            refreshed["status"] = "running"
            refreshed["status_text"] = "CodeBuddy NPC 团队正在创作"
            return refreshed

        refreshed["status"] = "result_pending"
        refreshed["status_text"] = "CNB 已完成，正在读取最终剧本"
        refreshed["progress"] = 98
        return refreshed


def _extract_result_marker(text: str) -> str:
    if RESULT_BEGIN not in text or RESULT_END not in text:
        return ""
    start = text.rfind(RESULT_BEGIN) + len(RESULT_BEGIN)
    end = text.find(RESULT_END, start)
    if end < start:
        return ""
    result = text[start:end].strip()
    result = re.sub(r"^\[[^\]]+\]\s*", "", result, flags=re.MULTILINE)
    return result


def _extract_stage_result_marker(text: str) -> tuple[str, str]:
    compressed = _extract_compressed_stage_result_marker(text)
    if compressed[0]:
        return compressed
    if STAGE_RESULT_BEGIN not in text or STAGE_RESULT_END not in text:
        return "", ""
    start = text.rfind(STAGE_RESULT_BEGIN) + len(STAGE_RESULT_BEGIN)
    end = text.find(STAGE_RESULT_END, start)
    if end < start:
        return "", ""
    payload = text[start:end].strip()
    payload = re.sub(r"^\[[^\]]+\]\s*", "", payload, flags=re.MULTILINE)
    stage, separator, result = payload.partition("\n")
    if not separator or stage.strip() not in STAGE_ORDER:
        return "", ""
    return stage.strip(), result.strip()


def _extract_compressed_stage_result_marker(text: str) -> tuple[str, str]:
    if STAGE_RESULT_GZIP_BEGIN not in text or STAGE_RESULT_GZIP_END not in text:
        return "", ""
    start = text.rfind(STAGE_RESULT_GZIP_BEGIN) + len(STAGE_RESULT_GZIP_BEGIN)
    end = text.find(STAGE_RESULT_GZIP_END, start)
    if end < start:
        return "", ""
    encoded = "".join(
        re.sub(r"^\[[^\]]+\]\s*", "", line.strip())
        for line in text[start:end].splitlines()
        if line.strip()
    )
    try:
        payload = gzip.decompress(base64.b64decode(encoded, validate=True)).decode("utf-8")
    except (binascii.Error, OSError, UnicodeDecodeError, ValueError):
        return "", ""
    stage, separator, result = payload.partition("\n")
    if not separator or stage.strip() not in STAGE_ORDER:
        return "", ""
    return stage.strip(), result.strip()


def _clean_stage_log(content: Any) -> str:
    items = content if isinstance(content, list) else []
    return "\n".join(
        _ANSI_ESCAPE.sub("", str(item))
        for item in items
    )


def _extract_json_marker(text: str, begin: str, end: str) -> dict[str, Any]:
    if begin not in text or end not in text:
        return {}
    start = text.rfind(begin) + len(begin)
    finish = text.find(end, start)
    if finish < start:
        return {}
    candidate = re.sub(r"^\[[^\]]+\]\s*", "", text[start:finish].strip(), flags=re.MULTILINE)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_written_file(text: str, path: str) -> str:
    pattern = re.compile(
        r"printf '%s' '(.*?)' > '" + re.escape(path) + r"'",
        re.DOTALL,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return ""
    return matches[-1].group(1).replace("'\\''", "'").strip()


def _extract_gate_report_from_log(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    reports: list[dict[str, Any]] = []
    for match in re.finditer(r'\{"schema_version"\s*:', text):
        try:
            payload, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "ok" in payload and "errors" in payload:
            reports.append(payload)
    return reports[-1] if reports else {}


def _quality_gate_summary(report: dict[str, Any]) -> str:
    errors = report.get("errors") if isinstance(report, dict) else []
    if not isinstance(errors, list) or not errors:
        return "最终稿已保留，但原 CNB 构建在发布前中断。"
    messages = [
        str(item.get("message") or "").strip()
        for item in errors
        if isinstance(item, dict) and str(item.get("message") or "").strip()
    ]
    return "严格门禁待修：" + "；".join(messages[:4])


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(job)
    payload.pop("user_id", None)
    payload.pop("build_status", None)
    resume_text = str(payload.pop("stage_resume_text", "") or "")
    if resume_text:
        payload["stage_checkpoint_chars"] = len(resume_text)
    stage_outputs = payload.pop("stage_outputs", None)
    if isinstance(stage_outputs, dict):
        payload["stage_output_keys"] = list(stage_outputs)
    versions = payload.pop("stage_versions", None)
    if isinstance(versions, dict):
        payload["stage_version_counts"] = {
            key: len(items) for key, items in versions.items() if isinstance(items, list)
        }
    provider = payload.get("provider")
    if isinstance(provider, dict):
        provider.pop("access_token", None)
    timings = payload.get("stage_timings")
    if isinstance(timings, dict):
        for timing in timings.values():
            if not isinstance(timing, dict):
                continue
            if str(timing.get("status") or "") == "running":
                timing["elapsed_ms"] = _elapsed_ms(str(timing.get("started_at") or ""))
            else:
                timing["elapsed_ms"] = max(0, int(timing.get("duration_ms") or 0))
    active_stage = str(payload.get("active_stage") or "")
    active_timing = timings.get(active_stage) if isinstance(timings, dict) else {}
    payload["active_stage_elapsed_ms"] = (
        max(0, int((active_timing or {}).get("elapsed_ms") or 0))
        if isinstance(active_timing, dict)
        else 0
    )
    payload["delivery_script"] = build_delivery_script(payload)
    return payload


def apply_callback_result(
    job: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    updated = copy.deepcopy(job)
    final_script = _clean_text(
        payload.get("final_script")
        or payload.get("finalScript")
        or payload.get("result")
    )
    if final_script:
        updated["final_script"] = final_script
        updated["status"] = "completed"
        updated["status_text"] = "专业剧本团队已交付"
        updated["progress"] = 100
        updated["error"] = ""
    if isinstance(payload.get("stage_outputs"), dict):
        updated["stage_outputs"] = copy.deepcopy(payload["stage_outputs"])
    return updated
