from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtime_paths import get_runtime_data_dir


STAGE_PROMPT_KEYS = ("basic", "worldview", "character", "beat", "storylines", "guide", "package")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _slug(value: str) -> str:
    text = re.sub(r"\s+", "-", str(value or "").strip().lower())
    text = re.sub(r"[^a-z0-9\-\u4e00-\u9fff]+", "", text)
    return text.strip("-") or uuid.uuid4().hex[:10]


def _stage_prompt(base: str, stage: str) -> str:
    stage_focus = {
        "basic": "01 基础信息提取：提炼题材定位、主角处境、核心冲突和必须保留的用户偏好，不提前扩写成完整剧情。",
        "worldview": "02 世界观：把偏好落到规则、空间、资源、阶层或关系网络上，保证设定可解释且能持续制造冲突。",
        "character": "03 人设：围绕主角欲望、缺陷、反派压力、关系拉扯和成长代价设计人物，不让角色只服务设定。",
        "beat": "04 十五节拍：按短剧节奏安排钩子、危机、反转和阶段性回报，每个节拍都要可拍、可验证。",
        "storylines": "05 人物故事线：让主要人物线各自有目标和变化，并与关键节拍交叉，不生成游离支线。",
        "guide": "06 改编指引：输出可执行的删改、视觉化、节奏和人物情绪策略，说明保留与调整理由。",
        "package": "07 最终策划包：校验结构完整、字段为对象/数组、偏好已落实，避免把 JSON 字符串当成结构化结果。",
    }[stage]
    return f"{base}\n{stage_focus}"


def _builtin(name: str, category: str, base: str) -> dict[str, Any]:
    return {
        "name": name,
        "category": category,
        "description": base,
        "prompt_text": base,
        "stage_prompts": {key: _stage_prompt(base, key) for key in STAGE_PROMPT_KEYS},
    }


BUILTIN_TAG_DEFINITIONS: tuple[dict[str, Any], ...] = (
    _builtin("规则怪谈", "题材", "建立清晰禁忌规则、违背规则的代价和层层升级的异常感。"),
    _builtin("都市情感", "题材", "强化现实情感冲突、亲密关系误会和可共情的都市生活压力。"),
    _builtin("霸总甜宠", "题材", "突出高势能男主、甜宠拉扯、身份差和高密度情绪回报。"),
    _builtin("复仇爽剧", "题材", "围绕压迫、隐忍、反击和阶段性打脸设计强爽点。"),
    _builtin("逆袭成长", "题材", "让主角从低位困境出发，通过选择、代价和能力成长完成逆袭。"),
    _builtin("悬疑推理", "题材", "设计线索、误导、嫌疑人和阶段性真相揭示，保持推理闭环。"),
    _builtin("古装权谋", "题材", "强化阵营博弈、身份伪装、朝堂利益和多方制衡。"),
    _builtin("仙侠玄幻", "题材", "突出修行体系、宿命牵引、法宝门派和奇观式世界观。"),
    _builtin("科幻末世", "题材", "建立灾变规则、生存资源压力、科技设定和人性抉择。"),
    _builtin("家庭伦理", "题材", "聚焦家庭责任、代际冲突、婚姻矛盾和亲情反转。"),
    _builtin("校园青春", "题材", "强化少年成长、友情爱情、校园事件和青春遗憾或热血。"),
    _builtin("职场商战", "题材", "突出职场竞争、商业谈判、资源争夺和职业成长线。"),
    _builtin("强反转", "结构", "每个关键阶段保留信息差，结尾用合理伏笔完成反转。"),
    _builtin("强钩子", "结构", "每集开头和结尾都设置明确悬念、危机或情绪爆点。"),
    _builtin("高爽短剧", "风格", "节奏快、冲突密、反馈强，避免长铺垫和低效支线。"),
    _builtin("低成本可拍", "制作", "优先使用少场景、少群演、强对白冲突和可落地动作。"),
    _builtin("群像叙事", "结构", "多角色拥有独立目标与交叉冲突，主线保持清晰推进。"),
    _builtin("单主角强线", "结构", "聚焦单一主角目标、欲望和成长，不让支线稀释主线。"),
)


class UserKnowledgeStore:
    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir).resolve() if base_dir else get_runtime_data_dir() / "user_knowledge"
        self.tags_path = self.base_dir / "tags.json"
        self.preferences_path = self.base_dir / "user_preferences.json"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.ensure_initialized()

    def ensure_initialized(self) -> None:
        tags = self._read_json(self.tags_path, [])
        if not isinstance(tags, list):
            tags = []
        tags = [self._normalize_tag(item) for item in tags if isinstance(item, dict)]
        by_id = {str(item.get("id") or ""): item for item in tags}
        changed = not self.tags_path.exists()
        for definition in BUILTIN_TAG_DEFINITIONS:
            tag_id = f"builtin-{_slug(definition['name'])}"
            if tag_id in by_id:
                existing = by_id[tag_id]
                if not existing.get("stage_prompts"):
                    existing["stage_prompts"] = deepcopy(definition["stage_prompts"])
                    changed = True
                continue
            now = _now_iso()
            tags.append(
                self._normalize_tag(
                    {
                        "id": tag_id,
                        "name": definition["name"],
                        "category": definition["category"],
                        "builtin": True,
                        "description": definition["description"],
                        "prompt_text": definition["prompt_text"],
                        "stage_prompts": definition["stage_prompts"],
                        "created_at": now,
                        "updated_at": now,
                        "enabled": True,
                        "pinned": False,
                    }
                )
            )
            changed = True
        if changed:
            self._write_json(self.tags_path, tags)
        if not self.preferences_path.exists():
            self._write_json(self.preferences_path, {})

    def list_tags(self, *, enabled_only: bool = True) -> list[dict[str, Any]]:
        tags = [self._normalize_tag(item) for item in self._read_tags()]
        if enabled_only:
            tags = [item for item in tags if item.get("enabled") is not False]
        return sorted(tags, key=lambda item: (not bool(item.get("pinned")), bool(item.get("builtin")), item.get("created_at", "")))

    def create_tag(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("标签名称不能为空")
        now = _now_iso()
        tag = self._normalize_tag(
            {
                "id": f"custom-{uuid.uuid4().hex[:12]}",
                "name": name,
                "category": str(payload.get("category") or "自定义").strip() or "自定义",
                "builtin": False,
                "description": str(payload.get("description") or "").strip(),
                "prompt_text": _coerce_prompt_text(payload.get("prompt_text")),
                "stage_prompts": _normalize_stage_prompts(payload.get("stage_prompts"), _coerce_prompt_text(payload.get("prompt_text"))),
                "created_at": now,
                "updated_at": now,
                "enabled": payload.get("enabled") is not False,
                "pinned": False,
            }
        )
        tags = self._read_tags()
        tags.append(tag)
        self._write_json(self.tags_path, tags)
        return deepcopy(tag)

    def update_tag(self, tag_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        tags = self._read_tags()
        for index, tag in enumerate(tags):
            if str(tag.get("id") or "") != str(tag_id):
                continue
            if tag.get("builtin") is True:
                raise ValueError("系统预置标签不能直接编辑")
            for key in ("name", "category", "description", "prompt_text", "enabled", "pinned"):
                if key not in changes:
                    continue
                if key in ("enabled", "pinned"):
                    tag[key] = bool(changes[key])
                else:
                    tag[key] = _coerce_prompt_text(changes[key]) if key == "prompt_text" else str(changes[key] or "").strip()
            if "stage_prompts" in changes:
                tag["stage_prompts"] = _normalize_stage_prompts(changes.get("stage_prompts"), str(tag.get("prompt_text") or ""))
            if not str(tag.get("name") or "").strip():
                raise ValueError("标签名称不能为空")
            tag["updated_at"] = _now_iso()
            tags[index] = self._normalize_tag(tag)
            self._write_json(self.tags_path, tags)
            return deepcopy(tags[index])
        raise ValueError("标签不存在")

    def delete_tag(self, tag_id: str) -> dict[str, Any]:
        tags = self._read_tags()
        for index, tag in enumerate(tags):
            if str(tag.get("id") or "") != str(tag_id):
                continue
            if tag.get("builtin") is True:
                raise ValueError("系统预置标签不能删除")
            tag["enabled"] = False
            tag["updated_at"] = _now_iso()
            tags[index] = self._normalize_tag(tag)
            self._write_json(self.tags_path, tags)
            return deepcopy(tags[index])
        raise ValueError("标签不存在")

    def get_preferences(self, user_id: int | str) -> dict[str, Any]:
        data = self._read_preferences()
        record = dict(data.get(str(user_id)) or {})
        record["selected_preference_tag_ids"] = _coerce_string_list(record.get("selected_preference_tag_ids"))
        return record

    def save_preferences(self, user_id: int | str, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._read_preferences()
        record = {
            "user_preference_prompt": _coerce_prompt_text(payload.get("user_preference_prompt")),
            "selected_preference_tag_ids": _coerce_string_list(payload.get("selected_preference_tag_ids")),
            "updated_at": _now_iso(),
        }
        data[str(user_id)] = record
        self._write_json(self.preferences_path, data)
        return deepcopy(record)

    def apply_tags(self, selected_tag_ids: Any, *, existing_user_preference: Any = "") -> dict[str, Any]:
        ids = _coerce_string_list(selected_tag_ids)
        existing = _coerce_prompt_text(existing_user_preference)
        empty_stage_prompts = {key: "" for key in STAGE_PROMPT_KEYS}
        if not ids:
            return {
                "selected_tags": [],
                "selected_tag_ids": [],
                "selected_preference_tag_ids": [],
                "merged_preference_prompt": existing,
                "tag_prompt_text": "",
                "stage_prompts": empty_stage_prompts,
            }
        tags_by_id = {tag["id"]: tag for tag in self.list_tags(enabled_only=True)}
        selected_tags: list[dict[str, Any]] = []
        for tag_id in ids:
            tag = tags_by_id.get(tag_id)
            if tag and tag["id"] not in {item["id"] for item in selected_tags}:
                selected_tags.append(tag)
        tag_prompt_text = "\n\n".join(_format_tag_section(tag, "prompt_text") for tag in selected_tags if str(tag.get("prompt_text") or "").strip())
        stage_prompts = {}
        for stage_key in STAGE_PROMPT_KEYS:
            stage_prompts[stage_key] = "\n\n".join(
                _format_stage_section(tag, stage_key)
                for tag in selected_tags
                if str((tag.get("stage_prompts") or {}).get(stage_key) or "").strip()
            )
        merged = _merge_preference_prompt(existing, tag_prompt_text)
        selected_ids = [tag["id"] for tag in selected_tags]
        return {
            "selected_tags": selected_tags,
            "selected_tag_ids": selected_ids,
            "selected_preference_tag_ids": selected_ids,
            "merged_preference_prompt": merged,
            "tag_prompt_text": tag_prompt_text,
            "stage_prompts": stage_prompts,
        }

    def _read_tags(self) -> list[dict[str, Any]]:
        tags = self._read_json(self.tags_path, [])
        if not isinstance(tags, list):
            return []
        normalized = [self._normalize_tag(item) for item in tags if isinstance(item, dict)]
        if normalized != tags:
            self._write_json(self.tags_path, normalized)
        return normalized

    def _read_preferences(self) -> dict[str, Any]:
        data = self._read_json(self.preferences_path, {})
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return deepcopy(default)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return deepcopy(default)

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _normalize_tag(tag: dict[str, Any]) -> dict[str, Any]:
        now = _now_iso()
        prompt_text = _coerce_prompt_text(tag.get("prompt_text"))
        return {
            "id": str(tag.get("id") or f"custom-{uuid.uuid4().hex[:12]}"),
            "name": str(tag.get("name") or "").strip(),
            "category": str(tag.get("category") or "自定义").strip() or "自定义",
            "builtin": bool(tag.get("builtin")),
            "description": str(tag.get("description") or "").strip(),
            "prompt_text": prompt_text,
            "stage_prompts": _normalize_stage_prompts(tag.get("stage_prompts"), prompt_text),
            "created_at": str(tag.get("created_at") or now),
            "updated_at": str(tag.get("updated_at") or now),
            "enabled": tag.get("enabled") is not False,
            "pinned": bool(tag.get("pinned")),
        }


def _normalize_stage_prompts(value: Any, fallback_prompt: str = "") -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    fallback = str(fallback_prompt or "").strip()
    return {key: _coerce_prompt_text(source.get(key)) or fallback for key in STAGE_PROMPT_KEYS}


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, dict):
            item_id = str(item.get("id") or "").strip()
        else:
            item_id = str(item or "").strip()
        if item_id and item_id not in result:
            result.append(item_id)
    return result


def _coerce_prompt_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _format_tag_section(tag: dict[str, Any], key: str) -> str:
    return f"【{tag.get('name') or tag.get('id')}】\n{str(tag.get(key) or '').strip()}"


def _format_stage_section(tag: dict[str, Any], stage_key: str) -> str:
    stage_prompts = tag.get("stage_prompts") if isinstance(tag.get("stage_prompts"), dict) else {}
    return f"【{tag.get('name') or tag.get('id')}】\n{str(stage_prompts.get(stage_key) or '').strip()}"


def _merge_preference_prompt(existing: str, tag_prompt_text: str) -> str:
    base = str(existing or "").rstrip()
    tag_text = str(tag_prompt_text or "").strip()
    if not tag_text:
        return base
    section = "来自智慧库标签：\n" + tag_text
    if section in base:
        return base
    if not base:
        return section
    return f"{base}\n\n{section}"


user_knowledge_store = UserKnowledgeStore()
