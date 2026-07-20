from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtime_paths import get_runtime_data_dir


STAGE_PROMPT_KEYS = (
    "basic",
    "worldview",
    "character",
    "beat",
    "storylines",
    "guide",
    "package",
    "scene",
    "appearance",
    "episode",
    "conflict",
    "script_text",
)

DEFAULT_STYLE_GROUP = "default_style"
USER_CUSTOM_GROUP = "user_custom"
EXCELLENT_FILM_BEAT_GROUP = "excellent_film_beat"

GROUP_LABELS = {
    DEFAULT_STYLE_GROUP: "默认风格分类",
    USER_CUSTOM_GROUP: "用户自定义标签",
    EXCELLENT_FILM_BEAT_GROUP: "优秀电影节拍表标签",
}

EXCELLENT_FILM_BEAT_NAMES = (
    "40岁的老处男",
    "阿甘正传",
    "冰血暴",
    "颤栗汪洋",
    "大人物波拿巴",
    "当哈利碰见萨丽",
    "电锯惊魂",
    "断背山",
    "凡夫俗子",
    "肥佬教授",
    "愤怒的公牛",
    "富贵逼人来",
    "黑骏马",
    "黑客帝国",
    "虎胆龙威",
    "角斗士",
    "惊声尖叫",
    "惊天大阴谋",
    "克莱默夫妇",
    "辣妈辣妹",
    "律政俏佳人",
    "美丽心灵的永恒阳光",
    "魔茧",
    "男人百分百",
    "上班一条虫",
    "少棒闯天下",
    "神秘的河",
    "狮子王",
    "十全十美",
    "十一罗汉",
    "泰坦尼克号",
    "天地大冲撞",
    "秃鹰七十二小时",
    "万福玛利亚",
    "为所应为",
    "午夜凶铃",
    "训练日",
    "窈窕淑男",
    "野战医院",
    "一路顺风",
    "异形",
    "银翼杀手",
    "与敌共眠",
    "拯救大兵瑞恩",
    "蜘蛛侠2",
    "致命的吸引力",
    "致命武器",
    "撞车",
    "追凶",
    "醉酒俏佳人",
)

EXCELLENT_FILM_PROMPTS_PATH = Path(__file__).resolve().parents[1] / "data" / "excellent_film_beat_prompts.json"


def _load_excellent_film_prompt_definitions() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(EXCELLENT_FILM_PROMPTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, list):
        return {}
    return {
        str(item.get("name") or "").strip(): item
        for item in payload
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }


EXCELLENT_FILM_PROMPT_DEFINITIONS = _load_excellent_film_prompt_definitions()


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
        "scene": "08 场景字典：提炼可复用、可拍摄的场景空间和世界观规则摘要，避免场景命名混乱。",
        "appearance": "09 确定角色外观：固定角色外观、服装、身份识别点和别名映射，保证后续正文一致。",
        "episode": "10 分集细化：按集拆解剧情推进、情绪回报和可拍动作，避免空泛梗概。",
        "conflict": "11 开头冲突钩子：强化每批次开头冲突、因果推进和结尾牵引。",
        "script_text": "12 正文写作：控制正文对白、动作、节奏、可视化表达和角色语气一致性。",
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
        raw_tags = self._read_json(self.tags_path, [])
        tags = self._read_json(self.tags_path, [])
        if not isinstance(tags, list):
            tags = []
        tags = [self._normalize_tag(item) for item in tags if isinstance(item, dict)]
        by_id = {str(item.get("id") or ""): item for item in tags}
        changed = (not self.tags_path.exists()) or (tags != raw_tags)
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
                        "group": DEFAULT_STYLE_GROUP,
                        "group_label": GROUP_LABELS[DEFAULT_STYLE_GROUP],
                        "source": "builtin_default_style",
                        "type": "stage_preference_template",
                        "is_default": True,
                        "is_user_editable": True,
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
        for index, name in enumerate(EXCELLENT_FILM_BEAT_NAMES, start=1):
            tag_id = f"excellent_film_beat_{index:03d}"
            definition = EXCELLENT_FILM_PROMPT_DEFINITIONS.get(name) or {}
            if tag_id in by_id:
                changed = self._ensure_excellent_film_beat_fields(by_id[tag_id], name, definition) or changed
                continue
            now = _now_iso()
            tag = self._normalize_tag(
                {
                    "id": tag_id,
                    "name": name,
                    "category": GROUP_LABELS[EXCELLENT_FILM_BEAT_GROUP],
                    "builtin": True,
                    "group": EXCELLENT_FILM_BEAT_GROUP,
                    "group_label": GROUP_LABELS[EXCELLENT_FILM_BEAT_GROUP],
                    "source": "save_the_cat_film_beat",
                    "type": "stage_preference_template",
                    "is_default": True,
                    "is_user_editable": True,
                    "description": str(definition.get("description") or "优秀电影节拍参考。"),
                    "prompt_text": str(definition.get("prompt_text") or ""),
                    "stage_prompts": definition.get("stage_prompts") or {key: "" for key in STAGE_PROMPT_KEYS},
                    "created_at": now,
                    "updated_at": now,
                    "enabled": True,
                    "pinned": False,
                }
            )
            tags.append(tag)
            by_id[tag_id] = tag
            changed = True
        if changed:
            self._write_json(self.tags_path, tags)
        if not self.preferences_path.exists():
            self._write_json(self.preferences_path, {})

    def list_tags(self, *, enabled_only: bool = True, user_id: int | str | None = None) -> list[dict[str, Any]]:
        owner_id = str(user_id or "").strip()
        tags = [self._normalize_tag(item) for item in self._read_tags()]
        if owner_id:
            tags = [
                item
                for item in tags
                if item.get("builtin") or str(item.get("owner_user_id") or "").strip() == owner_id
            ]
        else:
            tags = [item for item in tags if item.get("builtin") or not str(item.get("owner_user_id") or "").strip()]
        if enabled_only:
            tags = [item for item in tags if item.get("enabled") is not False]
        group_order = {DEFAULT_STYLE_GROUP: 0, USER_CUSTOM_GROUP: 1, EXCELLENT_FILM_BEAT_GROUP: 2}
        return sorted(tags, key=lambda item: (group_order.get(str(item.get("group") or ""), 9), not bool(item.get("pinned")), item.get("created_at", "")))

    def create_tag(self, payload: dict[str, Any], *, user_id: int | str | None = None) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("标签名称不能为空")
        owner_id = str(user_id or "").strip()
        now = _now_iso()
        tag = self._normalize_tag(
            {
                "id": f"custom-{uuid.uuid4().hex[:12]}",
                "owner_user_id": owner_id,
                "name": name,
                "category": str(payload.get("category") or "自定义").strip() or "自定义",
                "builtin": False,
                "group": USER_CUSTOM_GROUP,
                "group_label": GROUP_LABELS[USER_CUSTOM_GROUP],
                "source": "user_created",
                "type": "stage_preference_template",
                "is_default": False,
                "is_user_editable": True,
                "description": str(payload.get("description") or "").strip(),
                "prompt_text": _coerce_prompt_text(payload.get("prompt_text")),
                "stage_prompts": _normalize_stage_prompts(payload.get("stage_prompts")),
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

    def update_tag(self, tag_id: str, changes: dict[str, Any], *, user_id: int | str | None = None) -> dict[str, Any]:
        owner_id = str(user_id or "").strip()
        tags = self._read_tags()
        for index, tag in enumerate(tags):
            if str(tag.get("id") or "") != str(tag_id):
                continue
            if tag.get("builtin") and owner_id:
                copy_payload = deepcopy(tag)
                copy_payload.update(changes or {})
                copy_payload["id"] = f"custom-{uuid.uuid4().hex[:12]}"
                copy_payload["owner_user_id"] = owner_id
                copy_payload["builtin"] = False
                copy_payload["group"] = USER_CUSTOM_GROUP
                copy_payload["group_label"] = GROUP_LABELS[USER_CUSTOM_GROUP]
                copy_payload["source"] = f"user_override:{tag.get('id')}"
                copy_payload["is_default"] = False
                copy_payload["created_at"] = _now_iso()
                copy_payload["updated_at"] = _now_iso()
                copy_payload["enabled"] = True
                copy_payload["pinned"] = False
                tags.append(self._normalize_tag(copy_payload))
                self._write_json(self.tags_path, tags)
                return deepcopy(tags[-1])
            tag_owner = str(tag.get("owner_user_id") or "").strip()
            if owner_id and tag_owner and tag_owner != owner_id:
                raise ValueError("不能编辑其他用户的智慧库标签")
            if owner_id and not tag_owner:
                raise ValueError("不能编辑未归属当前用户的历史标签，请新建自己的标签")
            for key in ("name", "category", "description", "prompt_text", "enabled", "pinned"):
                if key not in changes:
                    continue
                if key in ("enabled", "pinned"):
                    tag[key] = bool(changes[key])
                else:
                    tag[key] = _coerce_prompt_text(changes[key]) if key == "prompt_text" else str(changes[key] or "").strip()
            if "stage_prompts" in changes:
                tag["stage_prompts"] = _normalize_stage_prompts(changes.get("stage_prompts"))
            if not str(tag.get("name") or "").strip():
                raise ValueError("标签名称不能为空")
            tag["updated_at"] = _now_iso()
            tags[index] = self._normalize_tag(tag)
            self._write_json(self.tags_path, tags)
            return deepcopy(tags[index])
        raise ValueError("标签不存在")

    def delete_tag(self, tag_id: str, *, user_id: int | str | None = None) -> dict[str, Any]:
        owner_id = str(user_id or "").strip()
        tags = self._read_tags()
        for index, tag in enumerate(tags):
            if str(tag.get("id") or "") != str(tag_id):
                continue
            if tag.get("builtin"):
                raise ValueError("默认标签不能删除，请取消选择或新建个人标签")
            tag_owner = str(tag.get("owner_user_id") or "").strip()
            if owner_id and tag_owner and tag_owner != owner_id:
                raise ValueError("不能删除其他用户的智慧库标签")
            if owner_id and not tag_owner:
                raise ValueError("不能删除未归属当前用户的历史标签")
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
        record["stage_prompts"] = _normalize_stage_prompts(record.get("stage_prompts"))
        return record

    def save_preferences(self, user_id: int | str, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._read_preferences()
        record = {
            "user_preference_prompt": _coerce_prompt_text(payload.get("user_preference_prompt")),
            "selected_preference_tag_ids": _coerce_string_list(payload.get("selected_preference_tag_ids")),
            "stage_prompts": _normalize_stage_prompts(payload.get("stage_prompts")),
            "updated_at": _now_iso(),
        }
        data[str(user_id)] = record
        self._write_json(self.preferences_path, data)
        return deepcopy(record)

    def apply_tags(self, selected_tag_ids: Any, *, existing_user_preference: Any = "", user_id: int | str | None = None) -> dict[str, Any]:
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
        tags_by_id = {tag["id"]: tag for tag in self.list_tags(enabled_only=True, user_id=user_id)}
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
        merged = existing
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
    def _ensure_excellent_film_beat_fields(
        tag: dict[str, Any],
        default_name: str,
        definition: dict[str, Any] | None = None,
    ) -> bool:
        changed = False
        definition = definition if isinstance(definition, dict) else {}
        defaults = {
            "category": GROUP_LABELS[EXCELLENT_FILM_BEAT_GROUP],
            "builtin": True,
            "group": EXCELLENT_FILM_BEAT_GROUP,
            "group_label": GROUP_LABELS[EXCELLENT_FILM_BEAT_GROUP],
            "source": "save_the_cat_film_beat",
            "type": "stage_preference_template",
            "is_default": True,
            "is_user_editable": True,
            "enabled": True,
            "pinned": False,
        }
        if not str(tag.get("name") or "").strip():
            tag["name"] = default_name
            changed = True
        description = str(tag.get("description") or "").strip()
        if not description or "空标签" in description:
            tag["description"] = str(definition.get("description") or "优秀电影节拍参考。")
            changed = True
        if not str(tag.get("prompt_text") or "").strip() and str(definition.get("prompt_text") or "").strip():
            tag["prompt_text"] = str(definition.get("prompt_text") or "").strip()
            changed = True
        for key, value in defaults.items():
            if key not in tag or tag.get(key) in (None, ""):
                tag[key] = value
                changed = True
        prompts = tag.get("stage_prompts") if isinstance(tag.get("stage_prompts"), dict) else {}
        definition_prompts = definition.get("stage_prompts") if isinstance(definition.get("stage_prompts"), dict) else {}
        for stage_key in STAGE_PROMPT_KEYS:
            if not str(prompts.get(stage_key) or "").strip():
                prompts[stage_key] = str(definition_prompts.get(stage_key) or "").strip()
                changed = True
        tag["stage_prompts"] = prompts
        return changed

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
        tag_id = str(tag.get("id") or f"custom-{uuid.uuid4().hex[:12]}")
        source = str(tag.get("source") or "").strip()
        group = str(tag.get("group") or "").strip()
        builtin = bool(tag.get("builtin"))
        if not group:
            if tag_id.startswith("excellent_film_beat_") or source == "save_the_cat_film_beat":
                group = EXCELLENT_FILM_BEAT_GROUP
                builtin = True
            elif builtin:
                group = DEFAULT_STYLE_GROUP
            else:
                group = USER_CUSTOM_GROUP
        group_label = str(tag.get("group_label") or GROUP_LABELS.get(group, "")).strip()
        if not source:
            source = "save_the_cat_film_beat" if group == EXCELLENT_FILM_BEAT_GROUP else ("builtin_default_style" if group == DEFAULT_STYLE_GROUP else "user_created")
        return {
            "id": tag_id,
            "name": str(tag.get("name") or "").strip(),
            "category": str(tag.get("category") or "自定义").strip() or "自定义",
            "builtin": builtin,
            "group": group,
            "group_label": group_label,
            "source": source,
            "owner_user_id": str(tag.get("owner_user_id") or "").strip(),
            "type": str(tag.get("type") or "stage_preference_template").strip() or "stage_preference_template",
            "is_default": bool(tag.get("is_default")) if "is_default" in tag else bool(builtin),
            "is_user_editable": tag.get("is_user_editable") is not False,
            "description": str(tag.get("description") or "").strip(),
            "prompt_text": prompt_text,
            "stage_prompts": _normalize_stage_prompts(tag.get("stage_prompts")),
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
    label = {
        "basic": "01 原文提取偏好",
        "worldview": "02 世界观偏好",
        "character": "03 人设偏好",
        "beat": "04 节拍规划偏好",
        "storylines": "05 人物故事线偏好",
        "guide": "06 改编指引偏好",
        "package": "07 框架校验偏好",
        "scene": "08 场景字典偏好",
        "appearance": "09 确定角色外观偏好",
        "episode": "10 分集细化偏好",
        "conflict": "11 开头冲突钩子偏好",
        "script_text": "12 正文写作偏好",
    }.get(stage_key, stage_key)
    return f"【智慧库标签偏好：{tag.get('name') or tag.get('id')} / {label}】\n{str(stage_prompts.get(stage_key) or '').strip()}"


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
