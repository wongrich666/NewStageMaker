from __future__ import annotations

import copy
import json
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any

from .agent_conversation_store import agent_conversation_store
from .framework_planner_service import run_framework_planner_stage
from .task_manager import task_manager


STAGE_KEYS = {
    "01": "basic",
    "02": "worldview",
    "03": "character",
    "04": "beat",
    "05": "storylines",
    "06": "guide",
    "07": "package",
}

STAGE_LABELS = {
    "01": "原文信息提取",
    "02": "世界观方案",
    "03": "人物设定",
    "04": "三幕十五节拍",
    "05": "人物故事线",
    "06": "整体改编指引",
    "07": "框架策划包校验",
}

SCRIPT_STAGE_LABELS = {
    "08": "提炼核心场景",
    "09": "确定角色外观",
    "10": "优化分集计划",
    "11": "规划因果冲突",
    "12": "生成剧本正文",
}

AGENT_CHARACTER_NAMING_FEEDBACK = (
    "这是全自动原创任务。用户未指定姓名时，必须由你自主为每个主要角色生成符合题材、时代和性别的自然中文姓名，"
    "并在 name、人物关系和后续内容中统一使用。不得输出‘未明确’‘待确认’‘暂定名’、char_01 等编号，"
    "也不得仅用主角、队长、副队长、生物学家、技术员等身份或职务代替姓名。"
)

UNRESOLVED_CHARACTER_NAMES = {
    "主角",
    "男主",
    "女主",
    "队长",
    "副队长",
    "生物学家",
    "技术员",
    "技术人员",
    "反派",
    "配角",
}


def _stage_data(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("框架阶段没有返回可用数据。")
    return data


def _safe_error(exc: Exception) -> str:
    text = " ".join(str(exc or "").split())
    return (text[:240] or "框架生成失败，请稍后重试。")


def _unresolved_character_names(character_plan: Any) -> list[str]:
    if not isinstance(character_plan, dict):
        return ["人物方案缺失"]
    characters = character_plan.get("characters")
    if not isinstance(characters, list) or not characters:
        return ["主要角色列表缺失"]
    unresolved: list[str] = []
    for index, item in enumerate(characters, start=1):
        if not isinstance(item, dict):
            unresolved.append(f"第{index}个角色")
            continue
        name = str(item.get("name") or "").strip()
        compact = "".join(name.split()).lower()
        if (
            not compact
            or compact in UNRESOLVED_CHARACTER_NAMES
            or compact.startswith("char_")
            or compact.startswith("character_")
            or any(marker in compact for marker in ("未明确", "待确认", "暂定名", "未命名", "后续确认"))
        ):
            unresolved.append(name or f"第{index}个角色")
    return unresolved


class AgentFrameworkPipeline:
    def start(
        self,
        *,
        user_id: int,
        conversation_id: str,
        payload: dict[str, Any],
        internal_api_base_url: str,
        internal_auth_token: str,
    ) -> dict[str, Any]:
        title = str(payload.get("title") or "未命名剧本").strip() or "未命名剧本"
        total_episodes = max(1, int(payload.get("total_episodes") or 1))
        expectation = str(payload.get("user_expectation") or "").strip()
        snapshot = task_manager.create_framework_planner_asset(
            user_id=user_id,
            title=title,
            season_count=1,
            episodes_per_season=total_episodes,
            target_format="短剧",
            style=expectation,
            description=expectation,
        )
        project_id = int(snapshot.get("project_id") or 0)
        state = {
            "generation_chain": "agent_framework_01_12",
            "pipeline_phase": "framework_01_07",
            "pipeline_stage": "01",
            "framework_project_id": project_id,
        }
        agent_conversation_store.update(
            user_id,
            conversation_id,
            project_id=project_id,
            task_id=str(snapshot.get("task_id") or ""),
            state=state,
        )
        thread = threading.Thread(
            target=self._run,
            kwargs={
                "user_id": user_id,
                "conversation_id": conversation_id,
                "framework_project_id": project_id,
                "payload": copy.deepcopy(payload),
                "internal_api_base_url": internal_api_base_url,
                "internal_auth_token": internal_auth_token,
            },
            daemon=False,
            name=f"agent-framework-{project_id}",
        )
        thread.start()
        return task_manager.get_project_snapshot(project_id, user_id=user_id) or snapshot

    @staticmethod
    def _post_script_stage(
        *,
        stage_no: str,
        payload: dict[str, Any],
        base_url: str,
        auth_token: str,
    ) -> dict[str, Any]:
        if not base_url or not auth_token:
            raise RuntimeError("当前登录凭证不可用，无法启动人工模式剧本阶段。")
        url = f"{base_url.rstrip('/')}/api/framework-to-script/stage/{stage_no}"
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=1800) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
            except Exception:
                error_payload = {}
            message = str(error_payload.get("message") or error_payload.get("error") or exc.reason).strip()
            raise RuntimeError(message or f"{stage_no} 阶段请求失败。") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{stage_no} 阶段请求失败：{exc}") from exc
        if not isinstance(result, dict) or result.get("success") is False:
            message = str((result or {}).get("message") or (result or {}).get("error") or "").strip()
            raise RuntimeError(message or f"{stage_no} 阶段没有返回有效结果。")
        return result

    @staticmethod
    def _episode_plan(stage10: dict[str, Any]) -> list[dict[str, Any]]:
        plan = (
            stage10.get("allEnrichedEpisodePlan")
            or stage10.get("enrichedEpisodePlan")
            or stage10.get("batchEnrichedEpisodePlan")
            or []
        )
        if not isinstance(plan, list) or not plan:
            raise RuntimeError("10 阶段未返回结构化分集计划。")
        return [item for item in plan if isinstance(item, dict)]

    @staticmethod
    def _batch_starts(plan: list[dict[str, Any]]) -> list[int]:
        starts: set[int] = set()
        for index, item in enumerate(plan):
            try:
                episode = int(
                    item.get("episode")
                    or item.get("episodeNumber")
                    or item.get("episode_number")
                    or item.get("ep")
                    or index + 1
                )
            except (TypeError, ValueError):
                episode = index + 1
            starts.add(((max(1, episode) - 1) // 5) * 5 + 1)
        return sorted(starts)

    def _conversation_state(self, user_id: int, conversation_id: str) -> dict[str, Any]:
        conversation = agent_conversation_store.get(user_id, conversation_id) or {}
        return dict(conversation.get("state") or {})

    def _set_pipeline_state(
        self,
        *,
        user_id: int,
        conversation_id: str,
        **changes: Any,
    ) -> None:
        state = self._conversation_state(user_id, conversation_id)
        state.update(changes)
        agent_conversation_store.update(user_id, conversation_id, state=state)

    def _save_framework_state(
        self,
        *,
        user_id: int,
        framework_project_id: int,
        framework_state: dict[str, Any],
        stage_no: str,
        status: str,
    ) -> dict[str, Any]:
        stage_key = STAGE_KEYS[stage_no]
        asset_state = dict(framework_state.get("asset_state") or {})
        asset_state.update(
            {
                "project_id": framework_project_id,
                "asset_id": framework_project_id,
                "asset_kind": "framework_planner",
                "asset_type": "framework",
                "status": status,
                "current_stage": stage_key,
                "agent_pipeline": True,
            }
        )
        framework_state["asset_state"] = asset_state
        return task_manager.save_framework_planner_asset(
            user_id=user_id,
            payload={
                **copy.deepcopy(framework_state),
                "project_id": framework_project_id,
                "project_title": framework_state["basic_config"]["project_title"],
                "title": framework_state["basic_config"]["project_title"],
                "asset_state": asset_state,
                "current_view": stage_key,
            },
        )

    def _run(
        self,
        *,
        user_id: int,
        conversation_id: str,
        framework_project_id: int,
        payload: dict[str, Any],
        internal_api_base_url: str,
        internal_auth_token: str,
    ) -> None:
        title = str(payload.get("title") or "未命名剧本").strip() or "未命名剧本"
        expectation = str(payload.get("user_expectation") or "").strip()
        conversation_material = str(payload.get("conversation_material") or "").strip()
        source_text = expectation
        if conversation_material and conversation_material != expectation:
            source_text = (
                f"【Agent整理后的创作要求】\n{expectation}\n\n"
                f"【用户原始对话材料】\n{conversation_material}"
            )
        total_episodes = max(1, int(payload.get("total_episodes") or 1))
        episode_word_count = max(50, int(payload.get("episode_word_count") or 600))
        basic_config = {
            "project_title": title,
            "title": title,
            "mode": "创作",
            "source_title": title,
            "source_text": source_text,
            "target_format": "短剧",
            "season_count": 1,
            "episodes_per_season": total_episodes,
            "total_episodes": total_episodes,
            "episode_word_count": episode_word_count,
            "adaptation_direction": expectation,
            "user_constraints": "",
            "user_requirements": "",
        }
        framework_state: dict[str, Any] = {
            "project_id": framework_project_id,
            "project_title": title,
            "mode": "创作",
            "basic_config": basic_config,
            "source_brief": {},
            "worldview_plan": {},
            "character_plan": {},
            "beat_checkpoint_timeline": [],
            "checkpoint_explanation": {},
            "character_storylines": [],
            "storyline_decisions": [],
            "adaptation_guide": {},
            "framework_plan_package": {},
            "validation_report": {},
            "display_texts": {},
            "stage_state": {},
            "asset_state": {},
            "selected_preference_tag_ids": copy.deepcopy(payload.get("selected_preference_tag_ids") or []),
            "selected_preference_tags": copy.deepcopy(payload.get("selected_preference_tags") or []),
            "user_knowledge_tag_prompt": str(payload.get("user_knowledge_tag_prompt") or ""),
            "user_knowledge_stage_prompts": copy.deepcopy(payload.get("user_knowledge_stage_prompts") or {}),
            "prompt_preferences": copy.deepcopy(payload.get("prompt_preferences") or {}),
        }
        current_stage = "01"
        try:
            for stage_no in STAGE_KEYS:
                current_stage = stage_no
                stage_key = STAGE_KEYS[stage_no]
                self._set_pipeline_state(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    pipeline_phase="framework_01_07",
                    pipeline_stage=stage_no,
                    pipeline_message=f"正在执行 {stage_no} {STAGE_LABELS[stage_no]}",
                )
                framework_state["stage_state"][stage_key] = {
                    "status": "running",
                    "confirmed": False,
                    "locked": False,
                }
                self._save_framework_state(
                    user_id=user_id,
                    framework_project_id=framework_project_id,
                    framework_state=framework_state,
                    stage_no=stage_no,
                    status="in_progress",
                )
                request_payload = {
                    **copy.deepcopy(framework_state),
                    **copy.deepcopy(basic_config),
                    "locked_basic_config": copy.deepcopy(basic_config),
                    "project_id": framework_project_id,
                    "project_title": title,
                    "title": title,
                    "mode": "创作",
                    "user_requirements": "",
                    "adaptation_direction": expectation,
                    "user_feedback": AGENT_CHARACTER_NAMING_FEEDBACK if stage_no == "03" else "",
                    "previous_worldview_plan": {},
                    "previous_character_plan": {},
                    "previous_beat_checkpoint_timeline": [],
                    "previous_character_storylines": [],
                    "previous_adaptation_guide": {},
                    "previous_framework_plan_package": {},
                    "current_storyline_decisions": framework_state["storyline_decisions"],
                }
                response = run_framework_planner_stage(stage_no, request_payload)
                data = _stage_data(response)
                if stage_no == "03":
                    for _ in range(2):
                        unresolved_names = _unresolved_character_names(data.get("character_plan"))
                        if not unresolved_names:
                            break
                        retry_payload = {
                            **copy.deepcopy(request_payload),
                            "mode": "改写",
                            "previous_character_plan": copy.deepcopy(data.get("character_plan") or {}),
                            "user_feedback": (
                                f"{AGENT_CHARACTER_NAMING_FEEDBACK}\n"
                                f"上一版仍有未完成姓名：{'、'.join(unresolved_names)}。请完整重写人物方案并消除全部代称。"
                            ),
                        }
                        response = run_framework_planner_stage(stage_no, retry_payload)
                        data = _stage_data(response)
                    unresolved_names = _unresolved_character_names(data.get("character_plan"))
                    if unresolved_names:
                        raise RuntimeError(
                            "03 人物设定未生成可用姓名：" + "、".join(unresolved_names)
                        )
                for key, value in data.items():
                    if key in framework_state:
                        framework_state[key] = copy.deepcopy(value)
                display_text = str(response.get("display_text") or data.get("display_text") or "").strip()
                if display_text:
                    framework_state["display_texts"][stage_no] = display_text
                if stage_no == "05":
                    framework_state["storyline_decisions"] = [
                        {
                            "storyline_id": item.get("id") or item.get("storyline_id") or "",
                            "title": item.get("title") or "",
                            "linked_beats": item.get("linked_beats") or [],
                            "decision": item.get("decision") or "keep",
                        }
                        for item in framework_state["character_storylines"]
                        if isinstance(item, dict)
                    ]
                framework_state["stage_state"][stage_key] = {
                    "status": "confirmed",
                    "confirmed": True,
                    "locked": True,
                }
                self._save_framework_state(
                    user_id=user_id,
                    framework_project_id=framework_project_id,
                    framework_state=framework_state,
                    stage_no=stage_no,
                    status="completed" if stage_no == "07" else "in_progress",
                )

            request_base = {
                "framework_asset_id": framework_project_id,
                "source_framework_project_id": framework_project_id,
                "framework_plan_package": copy.deepcopy(framework_state["framework_plan_package"]),
                "selected_preference_tag_ids": copy.deepcopy(framework_state["selected_preference_tag_ids"]),
                "selected_preference_tags": copy.deepcopy(framework_state["selected_preference_tags"]),
                "user_knowledge_tag_prompt": framework_state["user_knowledge_tag_prompt"],
                "user_knowledge_stage_prompts": copy.deepcopy(framework_state["user_knowledge_stage_prompts"]),
                "prompt_preferences": copy.deepcopy(framework_state["prompt_preferences"]),
            }
            outputs: dict[str, dict[str, Any]] = {}
            for stage_no in ("08", "09", "10"):
                current_stage = stage_no
                task_manager.update_framework_script_pipeline_status(
                    framework_project_id,
                    user_id=user_id,
                    status="running",
                    current_stage=f"framework_to_script_{stage_no}",
                    current_stage_label=f"{stage_no} {SCRIPT_STAGE_LABELS[stage_no]}",
                    message=f"正在执行 {stage_no} {SCRIPT_STAGE_LABELS[stage_no]}",
                    progress_percent={"08": 72, "09": 76, "10": 82}[stage_no],
                )
                self._set_pipeline_state(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    pipeline_phase="script_08_12",
                    pipeline_stage=stage_no,
                    pipeline_message=f"正在执行 {stage_no} {SCRIPT_STAGE_LABELS[stage_no]}",
                )
                stage_payload = copy.deepcopy(request_base)
                if stage_no in {"09", "10"}:
                    stage_payload.update(outputs["08"])
                if stage_no == "10":
                    stage_payload.update(outputs["09"])
                outputs[stage_no] = self._post_script_stage(
                    stage_no=stage_no,
                    payload=stage_payload,
                    base_url=internal_api_base_url,
                    auth_token=internal_auth_token,
                )

            episode_plan = self._episode_plan(outputs["10"])
            batch_starts = self._batch_starts(episode_plan)
            stage11: dict[str, Any] = {"batches": {}}
            for batch_index, batch_start in enumerate(batch_starts):
                current_stage = "11"
                task_manager.update_framework_script_pipeline_status(
                    framework_project_id,
                    user_id=user_id,
                    status="running",
                    current_stage="framework_to_script_11",
                    current_stage_label="11 规划因果冲突",
                    message=f"正在执行 11 {SCRIPT_STAGE_LABELS['11']}（第 {batch_start} 集起）",
                    progress_percent=84 + int(6 * batch_index / max(1, len(batch_starts))),
                )
                self._set_pipeline_state(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    pipeline_phase="script_08_12",
                    pipeline_stage="11",
                    pipeline_message=f"正在执行 11 {SCRIPT_STAGE_LABELS['11']}（第 {batch_start} 集起）",
                )
                stage11 = self._post_script_stage(
                    stage_no="11",
                    payload={
                        **copy.deepcopy(request_base),
                        **copy.deepcopy(outputs["08"]),
                        **copy.deepcopy(outputs["09"]),
                        "allEnrichedEpisodePlan": copy.deepcopy(episode_plan),
                        "batchStartEpisode": batch_start,
                        "batch_start_episode": batch_start,
                        "conflictMemory": str(stage11.get("conflictMemory") or ""),
                    },
                    base_url=internal_api_base_url,
                    auth_token=internal_auth_token,
                )

            stage12: dict[str, Any] = {"batches": {}}
            for batch_index, batch_start in enumerate(batch_starts):
                current_stage = "12"
                task_manager.update_framework_script_pipeline_status(
                    framework_project_id,
                    user_id=user_id,
                    status="running",
                    current_stage="framework_to_script_12",
                    current_stage_label="12 生成剧本正文",
                    message=f"正在执行 12 {SCRIPT_STAGE_LABELS['12']}（第 {batch_start} 集起）",
                    progress_percent=90 + int(9 * batch_index / max(1, len(batch_starts))),
                )
                self._set_pipeline_state(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    pipeline_phase="script_08_12",
                    pipeline_stage="12",
                    pipeline_message=f"正在执行 12 {SCRIPT_STAGE_LABELS['12']}（第 {batch_start} 集起）",
                )
                stage12 = self._post_script_stage(
                    stage_no="12",
                    payload={
                        **copy.deepcopy(request_base),
                        "stage08": copy.deepcopy(outputs["08"]),
                        "stage09": copy.deepcopy(outputs["09"]),
                        "stage11": copy.deepcopy(stage11),
                        "stage12": copy.deepcopy(stage12),
                        "batchStartEpisode": batch_start,
                        "batch_start_episode": batch_start,
                    },
                    base_url=internal_api_base_url,
                    auth_token=internal_auth_token,
                )

            task_manager.update_framework_script_pipeline_status(
                framework_project_id,
                user_id=user_id,
                status="completed",
                current_stage="framework_to_script_12",
                current_stage_label="剧本创作流程完成",
                message="剧本创作流程完成。",
                progress_percent=100,
            )
            state = self._conversation_state(user_id, conversation_id)
            state.update(
                {
                    "generation_chain": "agent_framework_01_12",
                    "pipeline_phase": "completed",
                    "pipeline_stage": "12",
                    "pipeline_message": "剧本创作流程完成",
                    "framework_project_id": framework_project_id,
                    "script_project_id": framework_project_id,
                }
            )
            agent_conversation_store.update(
                user_id,
                conversation_id,
                project_id=framework_project_id,
                state=state,
            )
            agent_conversation_store.add_message(
                user_id,
                conversation_id,
                role="assistant",
                content="剧本创作流程完成，剧本已保存到新剧本资产。",
                metadata={"pipeline_completed": True, "project_id": framework_project_id},
            )
        except Exception as exc:
            message = _safe_error(exc)
            stage_label = STAGE_LABELS.get(current_stage) or SCRIPT_STAGE_LABELS.get(current_stage) or ""
            if current_stage in STAGE_KEYS:
                framework_state["validation_report"] = {
                    "agent_pipeline_error": message,
                    "failed_stage": current_stage,
                }
                try:
                    self._save_framework_state(
                        user_id=user_id,
                        framework_project_id=framework_project_id,
                        framework_state=framework_state,
                        stage_no=current_stage,
                        status="failed",
                    )
                except Exception:
                    pass
            else:
                try:
                    task_manager.update_framework_script_pipeline_status(
                        framework_project_id,
                        user_id=user_id,
                        status="failed",
                        current_stage=f"framework_to_script_{current_stage}",
                        current_stage_label=f"{current_stage} {SCRIPT_STAGE_LABELS.get(current_stage, '')}".strip(),
                        message=f"{current_stage} 阶段执行失败：{message}",
                        progress_percent={"08": 72, "09": 76, "10": 82, "11": 88, "12": 94}.get(current_stage, 70),
                    )
                except Exception:
                    pass
            self._set_pipeline_state(
                user_id=user_id,
                conversation_id=conversation_id,
                pipeline_phase="failed",
                pipeline_stage=current_stage,
                pipeline_message=f"{current_stage} {stage_label}执行失败",
                pipeline_error=message,
            )
            agent_conversation_store.add_message(
                user_id,
                conversation_id,
                role="assistant",
                content=f"自动生成停在 {current_stage} {stage_label}：{message}",
                metadata={"pipeline_failed": True, "stage": current_stage},
            )


agent_framework_pipeline = AgentFrameworkPipeline()
