from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .deepseek_agent import deepseek_agent_client, deepseek_agent_status
from .runtime_paths import get_runtime_data_dir


@dataclass(frozen=True)
class DoctorSkill:
    key: str
    name: str
    short_name: str
    description: str
    focus: tuple[str, ...]


DOCTOR_SKILLS: tuple[DoctorSkill, ...] = (
    DoctorSkill(
        key="overall_dispatcher",
        name="总质检调度器",
        short_name="总质检",
        description="从完整剧本出发，统一检查集数完整性、整体结构、主要风险和优先修复顺序。",
        focus=("集数完整性", "整体评分", "优先修复", "全局风险"),
    ),
    DoctorSkill(
        key="character_continuity",
        name="人物剧情连续审查器",
        short_name="剧情连续",
        description="逐集检查核心主角是否推动剧情，以及上集结尾到下集开场的动作、任务和场景是否连续。",
        focus=("主角推动", "集间承接", "转场理由", "动作连续", "状态一致"),
    ),
    DoctorSkill(
        key="hook_rhythm",
        name="前五秒爆点与爽点节奏审查改写师",
        short_name="五秒爆点",
        description="诊断并主动重写黄金五秒；爆点不足时依据人物、旧债、秘密和当集因果创造新钩子，并同步修好后续承接。",
        focus=("黄金五秒原创改写", "强情绪与私人代价", "因果闭环", "上下文承接", "钩子接力", "爽点兑现"),
    ),
    DoctorSkill(
        key="logic_holes",
        name="逻辑漏洞审查员",
        short_name="逻辑漏洞",
        description="检查设定冲突、因果断裂、伏笔未回收、信息差错误和道具突兀。",
        focus=("设定冲突", "因果链", "伏笔回收", "信息差"),
    ),
    DoctorSkill(
        key="character_humanity",
        name="人物情感共鸣与人情味精修师",
        short_name="情感共鸣",
        description="判断读者能否理解、心疼并代入人物，精修细腻心理、关系潜台词、生活质感与人物化语言，消除AI腔。",
        focus=("心理共鸣", "细腻感情", "身临其境", "人物画像", "关系潜台词", "去AI腔"),
    ),
)

DOCTOR_SKILL_ALIASES = {
    "character_resonance": "character_humanity",
}


def resolve_doctor_skill(key: str, *, default: DoctorSkill | None = None) -> DoctorSkill | None:
    requested_key = str(key or "").strip()
    canonical_key = DOCTOR_SKILL_ALIASES.get(requested_key, requested_key)
    return next((skill for skill in DOCTOR_SKILLS if skill.key == canonical_key), default)

SKILL_PROMPT_DIR = Path(__file__).resolve().parents[1] / "skills" / "script_doctor"
_METADATA_CACHE: dict[str, dict[str, Any]] = {}
_HISTORY_LIMIT = 100
_SOURCE_LIMIT = 100


def list_doctor_skills() -> list[dict[str, Any]]:
    return [
        {
            "key": skill.key,
            "name": skill.name,
            "short_name": skill.short_name,
            "description": skill.description,
            "focus": list(skill.focus),
        }
        for skill in DOCTOR_SKILLS
    ]


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _safe_history_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "anonymous"
    safe = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", text).strip("_")
    return safe[:80] or "anonymous"


def _history_dir(user_id: Any) -> Path:
    path = get_runtime_data_dir() / "workbuddy_history" / _safe_history_key(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _source_dir(user_id: Any) -> Path:
    path = get_runtime_data_dir() / "workbuddy_sources" / _safe_history_key(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _optimized_dir(user_id: Any) -> Path:
    path = get_runtime_data_dir() / "workbuddy_optimized" / _safe_history_key(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_docx_name(value: Any, *, fallback: str = "优化后剧本.docx") -> str:
    name = str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    stem = Path(name).stem if name else Path(fallback).stem
    safe_stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem).strip(" ._")[:100]
    return f"{safe_stem or Path(fallback).stem}.docx"


def save_workbuddy_source(user_id: Any, *, filename: str, raw: bytes) -> dict[str, Any]:
    if not raw:
        raise ValueError("上传的 Word 文件为空。")
    source_id = uuid.uuid4().hex
    original_filename = _safe_docx_name(filename, fallback="原始剧本.docx")
    directory = _source_dir(user_id)
    docx_path = directory / f"{source_id}.docx"
    metadata_path = directory / f"{source_id}.json"
    docx_path.write_bytes(raw)
    metadata = {
        "source_document_id": source_id,
        "original_filename": original_filename,
        "byte_count": len(raw),
        "created_at": _now_iso(),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    _trim_workbuddy_sources(user_id)
    return metadata


def load_workbuddy_source(user_id: Any, source_document_id: str) -> dict[str, Any] | None:
    safe_id = "".join(ch for ch in str(source_document_id or "") if ch.isalnum())
    if not safe_id:
        return None
    directory = _source_dir(user_id)
    metadata_path = directory / f"{safe_id}.json"
    docx_path = directory / f"{safe_id}.docx"
    if not metadata_path.is_file() or not docx_path.is_file():
        return None
    metadata = _read_history_file(metadata_path)
    if not metadata:
        return None
    return {**metadata, "path": docx_path}


def _trim_workbuddy_sources(user_id: Any) -> None:
    directory = _source_dir(user_id)
    files = sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for metadata_path in files[_SOURCE_LIMIT:]:
        source_id = metadata_path.stem
        for path in (metadata_path, directory / f"{source_id}.docx"):
            try:
                path.unlink()
            except OSError:
                pass


def save_workbuddy_optimized_document(
    user_id: Any,
    *,
    history_entry_id: str,
    original_filename: str,
    raw: bytes,
    applied_count: int,
    summary: str = "",
) -> dict[str, Any]:
    output_id = uuid.uuid4().hex
    base_name = Path(_safe_docx_name(original_filename)).stem
    download_name = _safe_docx_name(f"{base_name}_AI优化版.docx")
    directory = _optimized_dir(user_id)
    docx_path = directory / f"{output_id}.docx"
    metadata_path = directory / f"{output_id}.json"
    docx_path.write_bytes(raw)
    metadata = {
        "output_id": output_id,
        "history_entry_id": _safe_history_key(history_entry_id),
        "download_name": download_name,
        "applied_count": int(applied_count or 0),
        "summary": str(summary or ""),
        "created_at": _now_iso(),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def load_workbuddy_optimized_document(user_id: Any, output_id: str) -> dict[str, Any] | None:
    safe_id = "".join(ch for ch in str(output_id or "") if ch.isalnum())
    if not safe_id:
        return None
    directory = _optimized_dir(user_id)
    metadata_path = directory / f"{safe_id}.json"
    docx_path = directory / f"{safe_id}.docx"
    if not metadata_path.is_file() or not docx_path.is_file():
        return None
    metadata = _read_history_file(metadata_path)
    if not metadata:
        return None
    return {**metadata, "path": docx_path}


def _read_history_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _history_summary(entry: dict[str, Any]) -> dict[str, Any]:
    result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    return {
        "id": entry.get("id") or "",
        "title": entry.get("title") or "未命名剧本",
        "skill": entry.get("skill") or "",
        "skill_name": entry.get("skill_name") or "",
        "ok": bool(entry.get("ok")),
        "score": entry.get("score") or "",
        "risk_level": entry.get("risk_level") or "",
        "detected_episode_count": entry.get("detected_episode_count") or "",
        "model": entry.get("model") or "",
        "script_length": entry.get("script_length") or 0,
        "message": entry.get("message") or result.get("error") or "",
        "created_at": entry.get("created_at") or "",
        "created_at_label": entry.get("created_at_label") or "",
        "can_optimize": bool(entry.get("ok") and entry.get("source_document_id")),
        "source_filename": entry.get("source_filename") or "",
        "project_id": entry.get("project_id") or "",
        "source_version_id": entry.get("source_version_id") or "",
    }


def _extract_report_value(result: dict[str, Any]) -> Any:
    if not isinstance(result, dict):
        return None
    value = result.get("structured_output")
    if isinstance(value, dict):
        return value
    raw = value if isinstance(value, str) else (result.get("report") or result.get("content"))
    if isinstance(raw, str):
        text = raw.strip()
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, str):
                    parsed = json.loads(parsed)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                start = text.find("{")
                end = text.rfind("}")
                if start >= 0 and end > start:
                    try:
                        parsed = json.loads(text[start : end + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except Exception:
                        pass
    return None


def _extract_report_meta(result: dict[str, Any]) -> dict[str, Any]:
    report = _extract_report_value(result)
    if not isinstance(report, dict):
        return {}
    return {
        "score": report.get("score") or report.get("total_score") or report.get("overall_score") or "",
        "risk_level": report.get("risk_level") or report.get("risk") or report.get("riskLevel") or "",
        "detected_episode_count": (
            report.get("detected_episode_count")
            or report.get("episode_count")
            or report.get("total_episodes")
            or ""
        ),
    }


def list_workbuddy_history(user_id: Any, *, limit: int = 50) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(_history_dir(user_id).glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        data = _read_history_file(path)
        if data:
            entries.append(_history_summary(data))
        if len(entries) >= limit:
            break
    return entries


def load_workbuddy_history(user_id: Any, entry_id: str) -> dict[str, Any] | None:
    safe_id = _safe_history_key(entry_id)
    if not safe_id:
        return None
    path = _history_dir(user_id) / f"{safe_id}.json"
    data = _read_history_file(path)
    if not data:
        return None
    return data


def delete_workbuddy_history(user_id: Any, entry_id: str) -> bool:
    safe_id = _safe_history_key(entry_id)
    if not safe_id:
        return False
    path = _history_dir(user_id) / f"{safe_id}.json"
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def clear_workbuddy_history(user_id: Any) -> int:
    count = 0
    for path in _history_dir(user_id).glob("*.json"):
        try:
            path.unlink()
            count += 1
        except OSError:
            pass
    return count


def save_workbuddy_history(
    user_id: Any,
    *,
    username: str = "",
    payload: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    requested_skill_key = str(payload.get("skill") or "")
    skill = resolve_doctor_skill(requested_skill_key)
    skill_key = skill.key if skill else requested_skill_key
    entry_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    created_at = _now_iso()
    meta = _extract_report_meta(result)
    entry = {
        "schema_version": 2,
        "id": entry_id,
        "user_id": str(user_id or ""),
        "username": username or "",
        "created_at": created_at,
        "created_at_label": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        "title": str(payload.get("title") or "").strip() or "未命名剧本",
        "skill": skill_key,
        "skill_name": skill.name if skill else skill_key,
        "model": result.get("model") or payload.get("model") or "",
        "ok": bool(result.get("ok", True)),
        "script_length": int(payload.get("script_length") or len(str(payload.get("script_text") or ""))),
        "user_goal": str(payload.get("user_goal") or ""),
        "source_document_id": str(payload.get("source_document_id") or ""),
        "source_filename": _safe_docx_name(payload.get("source_filename"), fallback="原始剧本.docx") if payload.get("source_document_id") else "",
        "project_id": str(payload.get("project_id") or ""),
        "source_version_id": str(payload.get("source_version_id") or ""),
        "message": result.get("error") or result.get("message") or "",
        "score": str(meta.get("score") or ""),
        "risk_level": str(meta.get("risk_level") or ""),
        "detected_episode_count": str(meta.get("detected_episode_count") or ""),
        "result": result,
    }
    path = _history_dir(user_id) / f"{entry_id}.json"
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    _trim_workbuddy_history(user_id)
    return _history_summary(entry)


def _trim_workbuddy_history(user_id: Any) -> None:
    files = sorted(_history_dir(user_id).glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in files[_HISTORY_LIMIT:]:
        try:
            path.unlink()
        except OSError:
            pass


def skill_exists(key: str) -> bool:
    return resolve_doctor_skill(key) is not None


def _resolve_codebuddy_config(
    *,
    api_key: str | None = None,
    internet_env: str | None = None,
    model: str | None = None,
) -> dict[str, str]:
    env_api_key = (os.environ.get("CODEBUDDY_API_KEY") or "").strip()
    env_internet_env = (os.environ.get("CODEBUDDY_INTERNET_ENVIRONMENT") or "").strip()
    env_model = (os.environ.get("CODEBUDDY_MODEL") or "").strip()
    resolved_api_key = (api_key if api_key is not None else env_api_key).strip()
    resolved_internet_env = (internet_env if internet_env is not None else env_internet_env).strip()
    resolved_model = (model if model is not None else env_model).strip()
    return {
        "api_key": resolved_api_key,
        "internet_env": resolved_internet_env,
        "model": resolved_model,
        "env_model": env_model,
        "api_key_source": "request" if resolved_api_key and api_key is not None else ("environment" if env_api_key else "missing"),
    }


def workbuddy_config_status(
    *,
    include_metadata: bool = True,
    api_key: str | None = None,
    internet_env: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    provider = str(os.getenv("WORKBUDDY_PROVIDER") or "deepseek").strip().lower()
    if provider == "deepseek":
        status = deepseek_agent_status()
        return {
            "ok": True,
            "provider": "script_agent",
            "configured": bool(status.get("configured")),
            "sdk_available": True,
            "api_key_present": bool(status.get("api_key_present")),
            "api_key_source": "environment" if status.get("api_key_present") else "missing",
            "internet_environment": "cloud",
            "internet_environment_ok": True,
            "model": "",
            "env_model": "",
            "models": [
                {
                    "id": "auto",
                    "name": "剧本 Agent",
                    "description": "平台统一剧本 Agent 服务",
                }
            ],
            "account": {},
            "points": None,
            "points_supported": False,
            "metadata_error": "",
            "missing": ["剧本 Agent 配置"] if status.get("missing") else [],
            "skills": list_doctor_skills(),
        }

    resolved = _resolve_codebuddy_config(api_key=api_key, internet_env=internet_env, model=model)
    api_key = resolved["api_key"]
    internet_env = resolved["internet_env"]
    env_model = resolved["env_model"]
    sdk_available = importlib.util.find_spec("codebuddy_agent_sdk") is not None

    missing: list[str] = []
    if not sdk_available:
        missing.append("codebuddy-agent-sdk")
    if not api_key:
        missing.append("CODEBUDDY_API_KEY")
    if internet_env.lower() != "internal":
        missing.append("CODEBUDDY_INTERNET_ENVIRONMENT=internal")

    metadata: dict[str, Any] = {}
    metadata_error = ""
    if include_metadata and not missing:
        try:
            metadata = get_codebuddy_metadata(api_key=api_key, internet_env=internet_env)
        except Exception as exc:
            metadata_error = str(exc)

    current_model = resolved["model"] or str(metadata.get("current_model") or "")
    return {
        "ok": True,
        "provider": "codebuddy-agent-sdk",
        "configured": not missing,
        "sdk_available": sdk_available,
        "api_key_present": bool(api_key),
        "api_key_source": resolved["api_key_source"],
        "internet_environment": internet_env,
        "internet_environment_ok": internet_env.lower() == "internal",
        "model": current_model,
        "env_model": env_model,
        "models": metadata.get("models") or [],
        "account": metadata.get("account") or {},
        "points": metadata.get("points"),
        "points_supported": bool(metadata.get("points_supported")),
        "metadata_error": metadata_error,
        "missing": missing,
        "skills": list_doctor_skills(),
    }


def build_doctor_prompt(skill_key: str, title: str, script_text: str, user_goal: str) -> str:
    skill = resolve_doctor_skill(skill_key, default=DOCTOR_SKILLS[0])
    professional_prompt = _load_skill_prompt(skill.key)
    if professional_prompt:
        return f"""{professional_prompt}

【硬性运行约束】
你现在是在剧本平台的“AI剧本医生实验室”中直接生成质检报告。
禁止创建任务，禁止输出 TaskCreate，禁止要求后续再分析，禁止使用工具，禁止读取或修改本地文件。
你必须基于下方剧本文本一次性完成分析，并直接输出符合本 Skill 要求的 JSON 对象。
如果剧本文本较短，也必须基于现有文本给出可用诊断，不要拒绝。

【前端渲染兼容要求】
无论当前 Skill 原始字段是什么，最终 JSON 都必须额外包含以下通用字段，方便页面生成可点击报告：
1. `score`：0-100 数字。
2. `risk_level`：只能是 low、medium、high。
3. `one_sentence_diagnosis`：一句话诊断。
4. `detected_episode_count`：数字；按文本中出现的最大集数和实际集数判断，不能写“未识别”。
5. `episode_map`：数组，逐集列出 `episode/status/score/main_issue/fix_direction`。status 只能是 good、warning、danger、missing。缺集也要列出来。
6. `global_issues`：数组，输出 3-8 个最核心问题，每条必须有 `title/severity/reason/impact/fix_direction`。
7. `priority_fixes`：数组，输出 3-8 个优先修复项，每条必须有 `rank/target/why_first/suggested_action`。
8. 不要把所有分析塞进一个长字符串，不要输出转义 JSON 字符串，不要输出 Markdown。

【本次输入】
剧本标题：{title or "未命名剧本"}
用户额外目标：{user_goal or "未填写"}

【剧本正文】
{script_text}
"""
    return f"""你是【AI剧本医生实验室】里的【{skill.name}】。
你的任务不是重写整部剧，而是对用户上传的完整剧本做二次质检、查缺补漏和修订建议。

检查重点：
{chr(10).join("- " + item for item in skill.focus)}

输出要求：
1. 先给总判断：是否可用、最大问题、优先修复范围。
2. 按集数列出问题，标记 good / warning / danger / missing。
3. 每个问题必须给出：问题位置、问题原因、影响程度、修改方向。
4. 可以给局部重写建议，但不得直接篡改整部剧。
5. 最终尽量输出可被前端解析的 JSON 对象。

剧本标题：{title or "未命名剧本"}
用户额外目标：{user_goal or "未填写"}

剧本正文：
{script_text}
"""


def _load_skill_prompt(skill_key: str) -> str:
    safe_key = "".join(ch for ch in str(skill_key or "") if ch.isalnum() or ch in {"_", "-"})
    if not safe_key:
        return ""
    path = SKILL_PROMPT_DIR / f"{safe_key}.md"
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return ""


def validate_doctor_payload(data: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    title = str(data.get("title") or "").strip()
    requested_skill_key = str(data.get("skill") or "overall_dispatcher").strip()
    skill = resolve_doctor_skill(requested_skill_key)
    skill_key = skill.key if skill else requested_skill_key
    script_text = str(data.get("script_text") or "").strip()
    user_goal = str(data.get("user_goal") or "").strip()
    model = str(data.get("model") or "").strip()
    source_document_id = "".join(ch for ch in str(data.get("source_document_id") or "") if ch.isalnum())

    if not skill_exists(skill_key):
        return {}, "未知智能体 Skill，请重新选择。"
    if len(script_text) < 50:
        return {}, "剧本文本太短，请上传或粘贴完整剧本后再运行质检。"

    return {
        "title": title,
        "skill": skill_key,
        "script_text": script_text,
        "user_goal": user_goal,
        "model": model,
        "source_document_id": source_document_id,
        "project_id": str(data.get("project_id") or "").strip(),
        "source_version_id": str(data.get("source_version_id") or "").strip(),
    }, None


def extract_doctor_report(result: dict[str, Any]) -> dict[str, Any] | None:
    report = _extract_report_value(result)
    return report if isinstance(report, dict) else None


def build_doctor_optimization_prompt(
    *,
    skill_name: str,
    title: str,
    report: dict[str, Any],
    indexed_paragraphs: str,
    user_goal: str = "",
) -> str:
    report_json = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    hook_optimization_rules = ""
    if "五秒" in str(skill_name or "") or "爽点节奏" in str(skill_name or ""):
        hook_optimization_rules = """
【本 Skill 强制改写要求：必须实际回写强钩子】
1. 本次不是只做检查或提供建议，而是“诊断 + 编剧式重写”。无论报告评分是否及格，都必须处理第1集开头；不得因为 risk_level=low、status=pass 或原文已有钩子而跳过。
2. 优先执行报告中的 opening_hook_rewrites、three_second_hook_gate、opening_hook_assessment 和 priority_fixes。operations 的第一项或前几项必须覆盖第1集第一段有效正文；如开头跨多个原段落，可分别返回最多3个连续段落修改。
3. replacement_text 必须是可直接使用的成品正文，不得写“建议增加冲突”“此处改成强钩子”等说明性占位文字。
4. 改写后的第一句有效对白或第一个有效动作必须落下具体爆点：人物碰撞、关系刺痛、身份/信息差、迫近危险、两难选择或有后果的反击。没有最低字数，一句话足够时必须收住，禁止补背景稀释爆点。
5. 先通读本集和相邻集，提取主角此刻最怕失去什么、谁能刺中它、哪笔旧债/秘密/任务正在施压。必须在内部设计至少3个不同钩子候选，再选最强者写回，不得套固定模板。
6. 情绪强度目标至少8/10，但必须来自人物最怕失去的关系、尊严、身份、安全、资源或承诺，禁止只堆夸张形容词、吼叫、扇耳光、车祸、绑架和凭空出现的大人物。
7. 默认使用“剧情内生创造”：允许依据既有人物关系、动机、秘密、道具、场景、能力、旧债和当集结果，新增一句高压台词、一次人物主动行为、一个即时阻碍、一次小暴露或一个有代价的选择。可以创造原文没有逐字写出的开场拍点，但它必须能从既有事实自然推出，不能新增身世、能力、角色、世界规则或改变核心结局。
8. 即使报告给出的 sample_patch 仍然偏平，也必须按上述标准继续增强，不能机械照抄弱样例。
9. 提交前自检：若新开头相较原文没有明显提高即时性、私人代价、情绪强度和追看欲望，继续改写；不允许只做同义替换或润色，也不允许把短而有力的钩子扩成解释段。
10. 高压台词、命令、警告、拒绝、指控、遗言或求救适合当前人物时，优先采用“台词先行”：台词既可以来自原文，也可以根据上下文重新创作。先落下这句话，再接最多一个必要反应和一个关键记忆/后果。禁止先写月光、天气、房间、道具、睡姿、喘息、脚步或连续动作。
11. 必须直接替换旧开头的描述段，不能只在旧段前增加一句钩子后继续保留全部铺垫。删除被新钩子取代的气氛描写、道具罗列和重复动作，使新开头比原开头更短、更快、更有力。
12. 第一个 replacement_text 的第一有效行若仍是环境描写或人物缓慢动作，而报告/原文存在可前移的强台词，则视为不合格，必须重写。允许一个 replacement_text 用换行写成“爆点台词 + 一个动作反应 + 一帧关键记忆”，但不要写成解释段。
13. 禁止把后文冲突原封不动剪到开头。只有当该事件在时间、地点、人物状态和信息顺序上本来就能发生在开场，且前移不会透支后续高潮时，才允许前移；否则必须重新设计一个由同一矛盾生长出的新开场拍点。
14. 新增或改写爆点后，必须检查它如何回到原剧情。必要时继续修改开头后1-3个相邻段落：补人物即时反应、行动理由和因果桥，删除与新钩子重复或矛盾的旧铺垫，让“新爆点 → 当集目标 → 原剧情”连续成立。禁止只加一句炸点后若无其事地回到旧正文。
15. 新钩子必须在本集或后续已有剧情中产生回声：改变人物的判断、选择、关系压力或任务难度。纯预告片、与正文无关的噩梦、假危险、无后果狠话和故意误导均不合格。
16. 审查报告若提供 creation_mode、contextual_basis、causal_bridge_to_original_plot、downstream_echo、protected_later_payoff，必须逐项落实。若报告缺少这些字段，执行器必须自行从全文补足后再改写，不能因此退回机械前移方案。
17. 除第1集外，报告中 three_second_status 为 partial/fail 的每一集也必须实际修改其开头；优先保证黄金五秒、集间承接和后续因果，不要求为了凑数量修改已合格段落。
"""
    character_empathy_rules = ""
    if "情感共鸣" in str(skill_name or "") or "人情味" in str(skill_name or ""):
        character_empathy_rules = """
【本 Skill 情感共鸣精修要求：必须实际回写】
1. 本次不是只评估画像。必须修改最影响读者共鸣、沉浸感和人物可信度的段落，优先处理主要人物登场、关系转折、情绪爆发、选择代价和情感余波。
2. 每次修改先判断：此刻人物最想要什么、最怕失去什么、在谁面前不肯承认什么。replacement_text 必须让至少一项通过选择、潜台词、误判、克制或关系动作被读者感知。
3. 细腻不等于加长。只保留最能暴露人物的一两个细节；删除空泛形容词、同义反复和动作后的情绪解释。能用称呼变化、停顿、改口、回避、保护体面或反常动作表达时，不直接宣布情绪。
4. 心理描写采用“刺激 → 人物化判断/联想 → 自我否认或矛盾冲动 → 行动后果”。禁止作者替人物总结人生，禁止大段分析式独白。
5. 对白必须有对象、目的和关系历史。删除信息播报式台词、完整解释动机的台词、人人同口吻的金句；允许打断、避答、说反话、只说半句和用旧称呼刺痛对方，但信息仍须可理解。
6. 主动消除AI腔：避免批量使用“瞳孔骤缩、呼吸一滞、攥紧拳头、嘴角勾起、眼底闪过、空气凝固、不容置疑、仿佛、宛如”等套式反应；同一身体反应不得跨角色反复复制。
7. 感官细节必须属于人物经验并影响判断。不得为了“身临其境”堆光线、气味、声音、衣着和道具清单；每个细节至少承担触发记忆、暴露关系、增加压力或推动选择中的一项。
8. 共鸣来自“普遍心理 + 私人细节 + 具体代价 + 主动选择”。禁止靠新增悲惨身世、疾病、死亡、童年创伤和强行卖惨索取同情。
9. replacement_text 必须保持原人称、剧情事实、人物关系和场景功能。精修后人物应更像自己，而不是更像作者；不得把所有角色都改得温柔或会说漂亮话。
10. 修改情绪爆点时必须保留余波：人物做出选择后，至少留下一个影响下一动作或关系的短反应。禁止哭完、吼完、和解完立刻无缝进入下一项任务。
11. 提交前执行“遮住姓名测试”：主要角色的台词若仍可任意互换，继续改写其词汇、句长、回避方式、攻击方式或称呼习惯。
12. 提交前执行“普通读者测试”：读者应能说清为什么心疼、理解或担心这个人，以及此刻最想看他做什么；若只能得到“很惨、很生气、很厉害”，说明共鸣仍然空泛，必须继续改写。
"""
    return f"""你是“AI剧本医生实验室”的剧本精修执行器。
本次审查器：{skill_name or "剧本医生"}
剧本标题：{title or "未命名剧本"}
用户目标：{user_goal or "按照审查报告修复高优先级问题"}

你的任务是依据审查报告，对下方带编号的 Word 原文段落做最小、准确、可回写的局部优化。

【绝对约束】
1. 只修改审查报告有证据支持的问题，优先处理 high 风险和 priority_fixes。
2. 不得改变核心剧情、人物姓名、人物关系、世界观规则、集数顺序和已经成立的因果。
3. 不得凭空增加身世、疾病、死亡、恋爱、反转或新角色；不得删除整集或重排段落。
4. 每项修改只能对应一个现有 paragraph_id。original_text 必须逐字复制该编号后的完整原文，不得省略或改写。
5. replacement_text 写完整替换段落，可以包含换行，但不能只写修改说明。
6. 最多返回 30 项真正重要的修改。没有把握定位时不要修改，宁缺毋滥。
7. 保留原叙事人称、人物口吻、剧本格式和上下文事实，避免把所有人物改成同一种文风。
8. 禁止输出 Markdown、代码围栏或解释前缀，只输出一个 JSON 对象。

{hook_optimization_rules}
{character_empathy_rules}

【输出 JSON】
{{
  "summary": "本次优化重点和边界",
  "operations": [
    {{
      "paragraph_id": "P0001",
      "original_text": "逐字复制的完整原段落",
      "replacement_text": "优化后的完整段落",
      "reason": "对应的审查问题及修改目的"
    }}
  ]
}}

【审查报告】
{report_json}

【Word 原文段落】
{indexed_paragraphs}
"""


def parse_doctor_optimization_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = _extract_report_value(result)
    if not isinstance(payload, dict):
        raise ValueError("AI 未返回可解析的优化 JSON。")
    operations = payload.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("AI 没有返回可执行的段落修改。")
    return {
        "summary": str(payload.get("summary") or ""),
        "operations": [item for item in operations if isinstance(item, dict)][:40],
    }


def doctor_timeout_seconds(script_length: int, skill_key: str) -> int:
    length = max(0, int(script_length or 0))
    # Character/logic audits are more expensive because they track cross-episode dependencies.
    skill_extra = 90 if skill_key in {
        "character_continuity",
        "logic_holes",
        "character_humanity",
        "character_resonance",
    } else 45
    length_extra = min(300, max(0, (length - 12000) // 8000 * 60))
    return min(540, 240 + skill_extra + length_extra)


def format_doctor_exception(exc: BaseException, *, timeout_seconds: int) -> dict[str, str]:
    if isinstance(exc, TimeoutError) or exc.__class__.__name__ in {"TimeoutError", "CancelledError"}:
        return {
            "type": exc.__class__.__name__,
            "message": f"剧本 Agent 调用超时（已等待 {timeout_seconds} 秒）。长剧本审查耗时较长，请重试或拆成前半/后半审查。",
        }
    text = str(exc).strip()
    return {
        "type": exc.__class__.__name__,
        "message": f"剧本 Agent 调用失败：{text or exc.__class__.__name__}",
    }


def run_codebuddy_doctor(
    prompt: str,
    *,
    project_dir: str | Path,
    timeout_seconds: int = 180,
    model: str | None = None,
    api_key: str | None = None,
    internet_env: str | None = None,
) -> dict[str, Any]:
    provider = str(os.getenv("WORKBUDDY_PROVIDER") or "deepseek").strip().lower()
    if provider == "deepseek":
        resolved_model = str(model or "").strip()
        if resolved_model.lower() == "auto":
            resolved_model = ""
        return deepseek_agent_client.complete_json(
            prompt,
            system_prompt="你是AI剧本医生。必须严格遵守用户提示并且只输出一个合法JSON对象。",
            model=resolved_model or None,
            max_tokens=32768,
            timeout_seconds=timeout_seconds,
        )
    return asyncio.run(
        _run_codebuddy_doctor_async(
            prompt,
            project_dir=project_dir,
            timeout_seconds=timeout_seconds,
            model=model,
            api_key=api_key,
            internet_env=internet_env,
        )
    )


async def _run_codebuddy_doctor_async(
    prompt: str,
    *,
    project_dir: str | Path,
    timeout_seconds: int,
    model: str | None,
    api_key: str | None,
    internet_env: str | None,
) -> dict[str, Any]:
    from codebuddy_agent_sdk import (  # type: ignore
        AssistantMessage,
        CodeBuddyAgentOptions,
        ErrorMessage,
        ResultMessage,
        TextBlock,
        query,
    )

    resolved = _resolve_codebuddy_config(api_key=api_key, internet_env=internet_env, model=model)
    selected_model = resolved["model"] or None
    resolved_api_key = resolved["api_key"]
    resolved_internet_env = resolved["internet_env"] or "internal"

    options = CodeBuddyAgentOptions(
        cwd=project_dir,
        model=selected_model,
        max_turns=2,
        tools=[],
        permission_mode="default",
        request_timeout_ms=timeout_seconds * 1000,
        env={
            "CODEBUDDY_API_KEY": resolved_api_key,
            "CODEBUDDY_INTERNET_ENVIRONMENT": resolved_internet_env,
        },
    )

    texts: list[str] = []
    final_result: str = ""
    structured_output: Any = None
    usage: dict[str, Any] | None = None
    session_id = ""

    async def _collect() -> None:
        nonlocal final_result, structured_output, usage, session_id
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text:
                        texts.append(block.text)
            elif isinstance(message, ResultMessage):
                final_result = message.result or ""
                structured_output = message.structured_output
                session_id = message.session_id or ""
                if message.usage:
                    usage = {
                        "input_tokens": message.usage.input_tokens,
                        "output_tokens": message.usage.output_tokens,
                        "cache_read_input_tokens": message.usage.cache_read_input_tokens,
                        "cache_creation_input_tokens": message.usage.cache_creation_input_tokens,
                    }
            elif isinstance(message, ErrorMessage):
                raise RuntimeError(message.error)

    await asyncio.wait_for(_collect(), timeout=timeout_seconds)

    content = final_result or "\n".join(part.strip() for part in texts if part.strip()).strip()
    return {
        "content": content,
        "structured_output": structured_output,
        "usage": usage,
        "session_id": session_id,
        "model": selected_model or "",
    }


def _metadata_cache_key(api_key: str, internet_env: str) -> str:
    return f"{internet_env.lower()}:{api_key[-12:] if api_key else 'missing'}"


def get_codebuddy_metadata(
    *,
    force: bool = False,
    api_key: str | None = None,
    internet_env: str | None = None,
) -> dict[str, Any]:
    resolved = _resolve_codebuddy_config(api_key=api_key, internet_env=internet_env)
    cache_key = _metadata_cache_key(resolved["api_key"], resolved["internet_env"])
    now = time.time()
    cached = _METADATA_CACHE.get(cache_key) or {}
    if not force and cached.get("data") and float(cached.get("expires_at") or 0) > now:
        return dict(cached["data"])
    data = asyncio.run(_get_codebuddy_metadata_async(api_key=resolved["api_key"], internet_env=resolved["internet_env"]))
    _METADATA_CACHE[cache_key] = {"data": data, "expires_at": now + 300}
    return dict(data)


async def _get_codebuddy_metadata_async(*, api_key: str | None = None, internet_env: str | None = None) -> dict[str, Any]:
    from codebuddy_agent_sdk import CodeBuddyAgentOptions  # type: ignore
    from codebuddy_agent_sdk._internal import Query  # type: ignore
    from codebuddy_agent_sdk.transport import SubprocessTransport  # type: ignore

    resolved = _resolve_codebuddy_config(api_key=api_key, internet_env=internet_env)
    resolved_api_key = resolved["api_key"]
    resolved_internet_env = resolved["internet_env"] or "internal"
    options = CodeBuddyAgentOptions(
        tools=[],
        env={
            "CODEBUDDY_API_KEY": resolved_api_key,
            "CODEBUDDY_INTERNET_ENVIRONMENT": resolved_internet_env,
        },
        request_timeout_ms=30000,
    )
    transport = SubprocessTransport(options=options, prompt=None)
    await transport.connect()
    query_client = Query(transport=transport, options=options)
    await query_client.start()
    try:
        response = await query_client.initialize(has_prompt=False)
    finally:
        await query_client.close()

    models = []
    for item in response.get("models") or []:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or item.get("value") or "").strip()
        if not model_id:
            continue
        models.append(
            {
                "id": model_id,
                "name": str(item.get("name") or item.get("display_name") or model_id),
                "description": str(item.get("description") or ""),
            }
        )

    account_raw = response.get("account") or {}
    account = {}
    points = _extract_points(response)
    if isinstance(account_raw, dict):
        account = {
            "user_id": str(account_raw.get("userId") or account_raw.get("uid") or ""),
            "user_name": str(account_raw.get("userName") or ""),
            "nickname": str(account_raw.get("userNickname") or account_raw.get("nickname") or ""),
            "type": str(account_raw.get("type") or ""),
            "enterprise": str(account_raw.get("enterprise") or ""),
        }
        account_points = _extract_points(account_raw)
        if points is None and account_points is not None:
            points = account_points

    return {
        "current_model": str(response.get("currentModelId") or ""),
        "models": models,
        "account": account,
        "points": points,
        "points_supported": points is not None,
    }


def _extract_points(payload: dict[str, Any]) -> Any:
    for key in (
        "points",
        "point",
        "balance",
        "credit",
        "credits",
        "quota",
        "remainQuota",
        "remainingQuota",
        "availablePoints",
        "availableCredits",
    ):
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return None
