
from __future__ import annotations

"""Extracted TaskManager mixin for StageCacheMixin."""

from . import task_manager_common as _task_manager_common
from .task_manager_common import *
globals().update(
    {name: getattr(_task_manager_common, name) for name in dir(_task_manager_common) if name.startswith("_")}
)
from .task_state import TaskRecord


class StageCacheMixin:
    def _snapshot_belongs_to_user(
        self,
        snapshot: dict[str, Any] | None,
        user_id: int | None,
    ) -> bool:
        if snapshot is None:
            return False
        if user_id is None:
            return True
        return int(snapshot.get("user_id") or 0) == int(user_id)

    def _public_input_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return _select_non_empty_fields(
            snapshot.get("input_payload") or {},
            PUBLIC_INPUT_PAYLOAD_KEYS,
        )

    def _public_artifacts(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """只把前端允许展示的正式产物挑出来，避免中间变量泄露。"""
        allowed_keys = list(PUBLIC_ARTIFACT_KEYS)
        if str(snapshot.get("status") or "") == "completed":
            allowed_keys.extend(PUBLIC_COMPLETED_ARTIFACT_KEYS)
        raw_artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        artifacts = _select_non_empty_fields(
            raw_artifacts,
            tuple(allowed_keys),
        )
        debug_variables = (
            (snapshot.get("debug_state") or {}).get("variables")
            if isinstance(snapshot.get("debug_state"), dict)
            else {}
        )
        if not isinstance(debug_variables, dict):
            debug_variables = {}
        for key in (
            "framework_natural_language",
            "worldview_natural_language",
            "final_output_text",
            "final_script",
            PARTIAL_SCRIPT_ARTIFACT,
        ):
            text = _meaningful_stage_output_text(artifacts.get(key))
            if text:
                artifacts[key] = text
            else:
                artifacts.pop(key, None)
        episode_plan_display = self._episode_plan_display_text(snapshot, snapshot.get("artifacts") or {})
        if episode_plan_display:
            artifacts[EPISODE_PLAN_DISPLAY_ARTIFACT] = episode_plan_display
        if str(snapshot.get("status") or "") != "completed":
            artifacts.update(
                _partial_script_artifacts_from_variables(
                    total_episodes=_safe_int(snapshot.get("total_episodes"), 0),
                    variables=debug_variables,
                )
            )
        return artifacts

    def _episode_plan_display_text(
        self,
        snapshot: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> str:
        raw_episode_plan = artifacts.get("episode_plan")
        if raw_episode_plan in (None, "", {}, []):
            return ""
        parsed = self._parse_episode_plan_display_json(raw_episode_plan)
        if parsed is None:
            return clean_user_visible_text(raw_episode_plan)

        display_text = self._fallback_episode_plan_display(parsed)
        return (
            clean_user_visible_text(display_text)
            or clean_user_visible_text(self._episode_plan_display_json_text(parsed))
            or clean_user_visible_text(raw_episode_plan)
        )

    def _parse_episode_plan_display_json(self, raw_episode_plan: Any) -> Any | None:
        if isinstance(raw_episode_plan, (dict, list)):
            return copy.deepcopy(raw_episode_plan)
        text = str(raw_episode_plan or "").strip()
        if not text or text[0] not in "[{":
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        if isinstance(parsed, (dict, list)):
            return parsed
        return None

    def _episode_plan_display_json_text(self, parsed: Any) -> str:
        if isinstance(parsed, dict):
            nested_episode_plan = parsed.get("episode_plan")
            if isinstance(nested_episode_plan, str):
                nested_parsed = self._parse_episode_plan_display_json(nested_episode_plan)
                if nested_parsed is not None:
                    return self._episode_plan_display_json_text(nested_parsed)
        try:
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            return ""

    def _episode_plan_display_source_text(self, parsed: Any) -> str:
        if isinstance(parsed, dict):
            nested_episode_plan = parsed.get("episode_plan")
            if isinstance(nested_episode_plan, str):
                nested_parsed = self._parse_episode_plan_display_json(nested_episode_plan)
                if nested_parsed is not None:
                    return self._episode_plan_display_source_text(nested_parsed)
            if isinstance(parsed.get("episodes"), list):
                parts: list[str] = []
                for item in parsed.get("episodes") or []:
                    if not isinstance(item, dict):
                        continue
                    episode_no = _safe_int(item.get("episode"), 0)
                    if episode_no <= 0:
                        continue
                    title = str(item.get("title") or "").strip()
                    content = str(item.get("content") or "").strip()
                    section = f"第{episode_no}集"
                    if title:
                        section += f"《{title}》"
                    if content:
                        section += f"\n{content}"
                    parts.append(section)
                if parts:
                    return "\n\n".join(parts)
        if isinstance(parsed, list):
            parts = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                episode_no = _safe_int(
                    item.get("episode")
                    or item.get("episode_no")
                    or item.get("episodeNumber"),
                    0,
                )
                title = str(item.get("title") or "").strip()
                content = str(item.get("content") or item.get("summary") or "").strip()
                if episode_no <= 0 and not content:
                    continue
                section = f"第{episode_no}集" if episode_no > 0 else "分集内容"
                if title:
                    section += f"《{title}》"
                if content:
                    section += f"\n{content}"
                parts.append(section)
            if parts:
                return "\n\n".join(parts)
        return ""

    def _generate_episode_plan_display(self, source_text: str) -> str:
        """不再额外调用模型润色分集计划展示，统一走本地回退整理。"""
        return ""

    def _fallback_episode_plan_display(self, parsed: Any) -> str:
        text = self._episode_plan_display_source_text(parsed)
        if not text:
            return ""
        return text

    def _cache_episode_plan_display(
        self,
        snapshot: dict[str, Any],
        display_text: str,
        text_hash: str,
    ) -> None:
        project_id = int(snapshot.get("project_id") or 0)
        if project_id <= 0 or not display_text:
            return
        artifacts_update = {
            EPISODE_PLAN_DISPLAY_ARTIFACT: display_text,
            EPISODE_PLAN_DISPLAY_SOURCE_HASH_ARTIFACT: text_hash,
        }
        record = self._projects.get(project_id)
        if record is not None:
            self._update_snapshot(record, artifacts=artifacts_update)
            snapshot.setdefault("artifacts", {}).update(artifacts_update)
            return

        persisted = copy.deepcopy(snapshot)
        persisted.setdefault("artifacts", {}).update(artifacts_update)
        self._project_path(project_id).write_text(
            json.dumps(persisted, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        snapshot.setdefault("artifacts", {}).update(artifacts_update)

    def _available_rollback_stage_options(self, snapshot: dict[str, Any]) -> list[tuple[str, str]]:
        """只返回当前项目已经走到的阶段，避免前端展示未来还没执行的回退选项。"""
        max_index = self._max_reached_rollback_stage_index(snapshot)
        if max_index < 0:
            return []
        return list(ROLLBACK_STAGE_OPTIONS[: max_index + 1])

    def _max_reached_rollback_stage_index(self, snapshot: dict[str, Any]) -> int:
        """根据正式产物、缓存变量和当前阶段，推断用户真正已经到达的最深阶段。"""
        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        debug_state = snapshot.get("debug_state") if isinstance(snapshot.get("debug_state"), dict) else {}
        variables = debug_state.get("variables") if isinstance(debug_state.get("variables"), dict) else {}

        reached: set[str] = set()
        if any(str(artifacts.get(key) or "").strip() for key in ("script_title_content", "story_outline", "character_bios", "core_scene_input", "episode_plan")):
            reached.add("framework")
        if any(str(variables.get(key) or "").strip() for key in (
            USER_CONTENT_BASELINE,
            CHARACTER_APPEARANCE_REQUIREMENTS,
            CHARACTER_ALIAS_NAMING_RULES,
            OUTFIT_SWITCH_RULES,
        )):
            reached.add("appearance_strategy")
        if variables.get(IS_CONSISTENT) is not None:
            reached.add("consistency")
        if variables.get(NORMALIZED_EPISODE_PLAN):
            reached.add("episode_plan_normalize")
        if str(artifacts.get("worldview") or "").strip():
            reached.add("worldview")
        if any(
            str(artifacts.get(key) or "").strip()
            for key in ("character_natural_language", "character_summary")
        ) or any(
            str(variables.get(key) or "").strip()
            for key in (CHARACTERS, CHARACTER_NATURAL_LANGUAGE_VAR)
        ):
            reached.add("characters")
        if any(
            str(artifacts.get(key) or "").strip()
            for key in ("scene_natural_language", "core_scene_summary", "scene_json")
        ) or any(
            str(variables.get(key) or "").strip()
            for key in (SCENES, SCENE_NATURAL_LANGUAGE_VAR)
        ):
            reached.add("scenes")
        if variables.get(APPEARANCE_MAPPING):
            reached.add("appearance")
        if variables.get(ALL_HOOKS) or variables.get(BATCH_HOOKS):
            reached.add("hooks")
        if variables.get(ALL_DIALOGUES) or variables.get(BATCH_DIALOGUES):
            reached.add("dialogues")
        if variables.get(ALL_SCRIPT) or variables.get(BATCH_SCRIPT):
            reached.add("script")
        if any(str(artifacts.get(key) or "").strip() for key in ("final_output_text", "final_script")):
            reached.add("final")

        current_stage = self._snapshot_stage_to_rollback_stage(snapshot, variables)
        if current_stage:
            reached.add(current_stage)

        indexes = [index for index, (key, _) in enumerate(ROLLBACK_STAGE_OPTIONS) if key in reached]
        current_stage_index = _rollback_stage_index(current_stage)
        if current_stage_index >= 0:
            indexes = [index for index in indexes if index <= current_stage_index]
        return max(indexes) if indexes else -1

    def _snapshot_stage_to_rollback_stage(
        self,
        snapshot: dict[str, Any],
        variables: dict[str, Any],
    ) -> str:
        """把运行时阶段名映射成回退阶段名，保证前后端对阶段理解一致。"""
        batch_stage = _normalize_rollback_stage_key(variables.get(LOCAL_CURRENT_BATCH_STAGE))
        rewrite_stage = _normalize_rollback_stage_key(variables.get(LOCAL_REWRITE_FROM_STAGE))
        for candidate in (batch_stage, rewrite_stage):
            if candidate in {"hooks", "dialogues", "script"}:
                return candidate

        current_stage = str(snapshot.get("current_stage") or "").strip().lower()
        if current_stage == "validation":
            return "episode_plan_normalize" if variables.get(NORMALIZED_EPISODE_PLAN) else "consistency"
        mapping = {
            "framework": "framework",
            "framework_naturalize": "framework",
            "appearance_strategy": "appearance_strategy",
            "appearance_pre_strategy": "appearance_strategy",
            "consistency": "consistency",
            "episode_plan_normalize": "episode_plan_normalize",
            "worldview": "worldview",
            "worldview_naturalize": "worldview",
            "character": "characters",
            "characters": "characters",
            "scene": "scenes",
            "scenes": "scenes",
            "appearance": "appearance",
            "appearance_alias_generation": "appearance",
            "appearance_alias_writing": "appearance",
            "appearance_alias_review": "appearance",
            "appearance_alias_rewrite": "appearance",
            "appearance_alias_unstructured": "appearance",
            "hook": "hooks",
            "hooks": "hooks",
            "hooks_writing": "hooks",
            "hook_write": "hooks",
            "hooks_review": "hooks",
            "hook_review": "hooks",
            "hooks_rewrite": "hooks",
            "hook_revise": "hooks",
            "hook_memory": "hooks",
            "dialogue": "dialogues",
            "dialogues": "dialogues",
            "dialogues_writing": "dialogues",
            "dialogue_write": "dialogues",
            "dialogues_review": "dialogues",
            "dialogue_review": "dialogues",
            "dialogues_rewrite": "dialogues",
            "dialogue_revise": "dialogues",
            "dialogue_memory": "dialogues",
            "script": "script",
            "script_writing": "script",
            "script_write": "script",
            "script_review": "script",
            "script_rewrite": "script",
            "script_revise": "script",
            "script_memory": "script",
            "memory": "script",
            "finalize": "final",
            "final": "final",
            "finished": "final",
        }
        mapped_stage = mapping.get(current_stage, "")
        if rewrite_stage in ROLLBACK_STAGE_LABELS:
            rewrite_index = _rollback_stage_index(rewrite_stage)
            mapped_index = _rollback_stage_index(mapped_stage)
            if rewrite_index >= 0 and (mapped_index < 0 or rewrite_index < mapped_index):
                return rewrite_stage
        return mapped_stage or rewrite_stage or batch_stage or ""

    def _current_stage_display_payload(
        self,
        snapshot: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> dict[str, str]:
        """只挑用户需要看的正式阶段内容，并补一段自然语言版摘要减轻等待焦虑。"""
        raw_artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        partial_script_output = clean_user_visible_text(
            artifacts.get(PARTIAL_SCRIPT_ARTIFACT)
            or raw_artifacts.get(PARTIAL_SCRIPT_ARTIFACT)
        )
        final_stage_output = pick_best_user_visible_value(
            artifacts.get("final_output_text")
            or artifacts.get("final_script")
            or raw_artifacts.get("final_output_text")
            or raw_artifacts.get("final_script")
            or partial_script_output
        )
        stage_order = ("framework", "worldview", "final")
        stage_title_map = {
            "framework": "剧本框架",
            "worldview": "世界观",
            "final": (
                "已生成正文"
                if str(snapshot.get("status") or "") != "completed" and partial_script_output
                else "最终剧本"
            ),
        }
        stage_outputs = {
            "framework": self._framework_stage_output_text(raw_artifacts),
            "worldview": self._worldview_stage_output_text(raw_artifacts),
            "final": final_stage_output,
        }

        current_stage = self._snapshot_stage_to_rollback_stage(
            snapshot,
            (snapshot.get("debug_state") or {}).get("variables") if isinstance(snapshot.get("debug_state"), dict) else {},
        )
        stage_ceiling_map = {
            "framework": "framework",
            "appearance_strategy": "framework",
            "consistency": "framework",
            "episode_plan_normalize": "framework",
            "worldview": "worldview",
            "characters": "worldview",
            "scenes": "worldview",
            "appearance": "worldview",
            "hooks": "worldview",
            "dialogues": "worldview",
            "script": "final",
            "final": "final",
        }
        ceiling_stage = stage_ceiling_map.get(current_stage, "framework")
        ceiling_index = stage_order.index(ceiling_stage)

        chosen_stage = ""
        for stage_key in reversed(stage_order[: ceiling_index + 1]):
            if stage_outputs.get(stage_key):
                chosen_stage = stage_key
                break
        if not chosen_stage and not current_stage:
            for stage_key in stage_order:
                if stage_outputs.get(stage_key):
                    chosen_stage = stage_key
                    break
        if not chosen_stage:
            return {
                "stage_key": "",
                "stage_title": "当前阶段输出",
                "output": "",
                "natural_output": "",
            }

        raw_output = stage_outputs[chosen_stage]
        natural_output = self._stage_preview_text(
            snapshot,
            stage_key=chosen_stage,
            stage_title=stage_title_map[chosen_stage],
            raw_output=raw_output,
        )
        return {
            "stage_key": chosen_stage,
            "stage_title": stage_title_map[chosen_stage],
            "output": raw_output,
            "natural_output": natural_output,
        }

    def _framework_stage_output_text(self, artifacts: dict[str, Any]) -> str:
        return pick_best_user_visible_value(artifacts.get("framework_natural_language"))

    def _worldview_stage_output_text(self, artifacts: dict[str, Any]) -> str:
        return pick_best_user_visible_value(artifacts.get("worldview_natural_language"))

    def _character_stage_output_text(
        self,
        snapshot: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> str:
        raw_artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        natural = pick_best_user_visible_value(
            artifacts.get("character_natural_language")
            or artifacts.get("character_summary")
            or raw_artifacts.get("character_natural_language")
            or raw_artifacts.get("character_summary")
        )
        return natural

    def _scene_stage_output_text(
        self,
        snapshot: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> str:
        raw_artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        natural = pick_best_user_visible_value(
            artifacts.get("scene_natural_language")
            or artifacts.get("core_scene_summary")
            or raw_artifacts.get("scene_natural_language")
            or raw_artifacts.get("core_scene_summary")
        )
        return natural

    def _stage_preview_text(
        self,
        snapshot: dict[str, Any],
        *,
        stage_key: str,
        stage_title: str,
        raw_output: str,
    ) -> str:
        """阶段展示只走本地格式化，不再额外触发展示摘要调用。"""
        text = clean_user_visible_text(raw_output).strip()
        if not text:
            return ""
        return self._fallback_stage_preview(stage_title, text)

    def _hash_text(self, value: str) -> str:
        """用内容哈希判断阶段产物是否变化，避免重复生成摘要。"""
        return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()

    def _generate_stage_preview(self, stage_title: str, raw_output: str) -> str:
        """保留接口位置，但不再额外调用模型生成阶段摘要。"""
        return ""

    def _preview_source_text(self, raw_output: str) -> str:
        """把阶段原文裁成适合摘要模型理解的长度，避免长正文拖慢详情接口。"""
        text = str(raw_output or "").strip()
        if len(text) <= 6000:
            return text
        head = text[:3600].strip()
        tail = text[-1800:].strip()
        if not tail:
            return head
        return f"{head}\n\n【后段摘要参考】\n{tail}"

    def _fallback_stage_preview(self, stage_title: str, raw_output: str) -> str:
        """模型不可用时，给用户一段稳定的本地说明，避免输出区域空白。"""
        condensed = " ".join(str(raw_output or "").replace("\r", "\n").split())
        if not condensed:
            return ""
        return f"当前展示的是{stage_title}阶段"

    def _cache_stage_preview(
        self,
        snapshot: dict[str, Any],
        *,
        stage_key: str,
        text_hash: str,
        preview: str,
    ) -> None:
        """把阶段摘要写回项目快照，减少轮询时的重复计算。"""
        project_id = int(snapshot.get("project_id") or 0)
        if project_id <= 0 or not preview:
            return
        artifacts_update = {
            STAGE_PREVIEW_TEXT_ARTIFACT: preview,
            STAGE_PREVIEW_STAGE_ARTIFACT: stage_key,
            STAGE_PREVIEW_SOURCE_HASH_ARTIFACT: text_hash,
        }
        record = self._projects.get(project_id)
        if record is not None:
            self._update_snapshot(record, artifacts=artifacts_update)
            snapshot.setdefault("artifacts", {}).update(artifacts_update)
            return
        persisted = copy.deepcopy(snapshot)
        persisted.setdefault("artifacts", {}).update(artifacts_update)
        self._project_path(project_id).write_text(
            json.dumps(persisted, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        snapshot.setdefault("artifacts", {}).update(artifacts_update)

    def _public_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """把内部任务快照裁成安全、简洁、适合前端直接消费的公开视图。"""
        artifacts = self._public_artifacts(snapshot)
        completion_confirmed = _completion_confirmed(snapshot)
        awaiting_confirmation = _awaiting_completion_confirmation(snapshot)
        can_stage_rollback = _can_stage_rollback(snapshot)
        display_payload = self._current_stage_display_payload(snapshot, artifacts)
        progress_metrics = self._snapshot_progress_metrics(snapshot)
        rollback_stage_default, rollback_start_episode_default = self._rollback_defaults(snapshot)
        rollback_stage_start_options = (
            self._rollback_stage_start_options(snapshot) if can_stage_rollback else {}
        )
        rollback_script_start_options = rollback_stage_start_options.get("script", [])
        rollback_stage_options = self._available_rollback_stage_options(snapshot) if can_stage_rollback else []
        payload: dict[str, Any] = {
            "project_id": snapshot.get("project_id"),
            "task_id": snapshot.get("task_id"),
            "status": snapshot.get("status"),
            "title": snapshot.get("title") or artifacts.get("script_title_content") or "未命名剧本",
            "message": _public_status_message(snapshot),
            "created_at": snapshot.get("created_at"),
            "updated_at": snapshot.get("updated_at"),
            "finished_at": snapshot.get("finished_at"),
            "wait_elapsed_ms": _safe_int(snapshot.get("wait_elapsed_ms"), 0),
            "wait_started_at": snapshot.get("wait_started_at"),
            "visibility": snapshot.get("visibility") or "private",
            "input_payload": self._public_input_payload(snapshot),
            "artifacts": artifacts,
            "progress_percent": progress_metrics["progress_percent"],
            "generated_episodes": progress_metrics["generated_episodes"],
            "total_episodes": int(snapshot.get("total_episodes") or 0),
            "current_stage": snapshot.get("current_stage"),
            "current_stage_label": snapshot.get("current_stage_label") or "待开始",
            "current_batch": snapshot.get("current_batch"),
            "completion_confirmed": completion_confirmed,
            "awaiting_user_confirmation": awaiting_confirmation,
            "cache_retained": bool(snapshot.get("cache_retained", False) or awaiting_confirmation),
            "cache_notice": _cache_notice(snapshot),
            "can_confirm_completion": awaiting_confirmation,
            "can_stage_rollback": can_stage_rollback,
            "rollback_stage_options": [
                {"key": key, "label": label} for key, label in rollback_stage_options
            ] if can_stage_rollback else [],
            "rollback_stage_default": rollback_stage_default if can_stage_rollback else "",
            "rollback_stage_start_options": rollback_stage_start_options if can_stage_rollback else {},
            "rollback_script_start_options": rollback_script_start_options,
            "rollback_start_episode_default": rollback_start_episode_default if can_stage_rollback else None,
            "rollback_stage_dependencies": {
                stage_key: list(dependencies)
                for stage_key, dependencies in ROLLBACK_STAGE_DEPENDENCIES.items()
            } if can_stage_rollback else {},
            "display_stage_key": display_payload["stage_key"],
            "display_stage_title": display_payload["stage_title"],
            "display_stage_output": display_payload["output"],
            "display_stage_output_natural": display_payload["natural_output"],
            "has_final": bool(
                str(artifacts.get("final_output_text") or artifacts.get("final_script") or "").strip()
            ),
        }
        # 有意不把 debug_state / logs / 内部控制位直接暴露给前端。
        # 前端只看正式字段，避免中间变量、节点回显和恢复指针泄漏到公开接口。
        return payload

    def _rollback_stage_start_options(
        self,
        snapshot: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            stage_key: self._batched_stage_rollback_start_options(snapshot, stage_key)
            for stage_key in ("hooks", "dialogues", "script")
        }

    def _batched_stage_rollback_start_options(
        self,
        snapshot: dict[str, Any],
        stage_key: str,
    ) -> list[dict[str, Any]]:
        normalized_stage = _normalize_rollback_stage_key(stage_key)
        if normalized_stage == "script":
            return self._script_rollback_start_options(snapshot)
        if normalized_stage not in {"hooks", "dialogues"}:
            return []

        debug_state = snapshot.get("debug_state") or {}
        variables = debug_state.get("variables") if isinstance(debug_state, dict) else {}
        if not isinstance(variables, dict):
            variables = {}

        total_episodes = int(snapshot.get("total_episodes") or 0)
        batch_size = max(1, int(settings.batch_size or 5))
        if total_episodes <= 0:
            return []

        batches = list(iter_episode_batches(total_episodes, batch_size=batch_size))
        valid_batch_starts = {batch.start_episode for batch in batches}
        interrupted_start = self._interrupted_batch_start_episode(snapshot)
        next_unfinished = (
            self._next_unfinished_object_batch_start(variables.get(ALL_HOOKS), batches)
            if normalized_stage == "hooks"
            else self._next_unfinished_object_batch_start(variables.get(ALL_DIALOGUES), batches)
        )

        candidate_starts = [batch.start_episode for batch in batches if batch.start_episode < next_unfinished]
        if next_unfinished in valid_batch_starts:
            candidate_starts.append(next_unfinished)
        if interrupted_start in valid_batch_starts:
            candidate_starts.append(interrupted_start)
        if not candidate_starts and batches:
            candidate_starts = [batches[0].start_episode]

        return [
            self._build_rollback_start_option(
                normalized_stage,
                total_episodes=total_episodes,
                start_episode=start_episode,
            )
            for start_episode in sorted(set(candidate_starts))
        ]

    def _build_rollback_start_option(
        self,
        stage_key: str,
        *,
        total_episodes: int,
        start_episode: int,
        allow_script_episode_labels: bool = False,
    ) -> dict[str, Any]:
        batch_size = max(1, int(settings.batch_size or 5))
        end_episode = min(total_episodes, start_episode + batch_size - 1)
        dependencies = list(_rollback_stage_dependency_keys(stage_key))
        del allow_script_episode_labels

        stage_label = {
            "hooks": "开头冲突钩子",
            "dialogues": "角色对话",
            "script": "剧本正文",
        }.get(stage_key, ROLLBACK_STAGE_LABELS.get(stage_key, stage_key))
        if end_episode < total_episodes:
            label = (
                f"从第 {start_episode} 集开始重写{stage_label}"
                f"（将按批次重写第 {start_episode}-{end_episode} 集，并继续重写后续批次）"
            )
        else:
            label = f"从第 {start_episode} 集开始重写{stage_label}（将重写第 {start_episode}-{end_episode} 集）"

        return {
            "value": start_episode,
            "label": label,
            "start_episode": start_episode,
            "end_episode": end_episode,
            "stage_key": stage_key,
            "affected_stages": dependencies,
        }

    def _script_rollback_start_options(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        debug_state = snapshot.get("debug_state") or {}
        variables = debug_state.get("variables") if isinstance(debug_state, dict) else {}
        if not isinstance(variables, dict):
            variables = {}

        batch_size = max(1, int(settings.batch_size or 5))
        total_episodes = int(snapshot.get("total_episodes") or 0)
        if total_episodes <= 0:
            return []

        batch_starts = [
            int(batch["start"])
            for batch in build_episode_batches(total_episodes, batch_size=batch_size)
        ]
        script_batches = _normalize_batch_text_map(variables.get(LOCAL_SCRIPT_BATCHES))
        script_episodes = _normalize_episode_script_map(variables.get(LOCAL_SCRIPT_EPISODES))
        interrupted_start = self._interrupted_batch_start_episode(snapshot)
        if script_episodes:
            candidate_starts = batch_starts
        elif script_batches:
            candidate_starts = batch_starts
        else:
            candidate_starts = [interrupted_start] if interrupted_start in batch_starts else batch_starts[:1]

        if interrupted_start in batch_starts and interrupted_start not in candidate_starts:
            candidate_starts = sorted({*candidate_starts, interrupted_start})

        options: list[dict[str, Any]] = []
        for start_episode in candidate_starts:
            options.append(
                self._build_rollback_start_option(
                    "script",
                    total_episodes=total_episodes,
                    start_episode=start_episode,
                    allow_script_episode_labels=bool(script_episodes),
                )
            )
        return options

    def _rollback_defaults(self, snapshot: dict[str, Any]) -> tuple[str, int | None]:
        debug_state = snapshot.get("debug_state") or {}
        variables = debug_state.get("variables") if isinstance(debug_state, dict) else {}
        if not isinstance(variables, dict):
            variables = {}

        current_stage = _normalize_rollback_stage_key(snapshot.get("current_stage"))
        rewrite_stage = _normalize_rollback_stage_key(variables.get(LOCAL_REWRITE_FROM_STAGE))
        batch_stage = _normalize_rollback_stage_key(variables.get(LOCAL_CURRENT_BATCH_STAGE))
        interrupted_start = self._interrupted_batch_start_episode(snapshot)

        for candidate in (batch_stage, rewrite_stage, current_stage):
            if candidate in {"hooks", "dialogues", "script"}:
                valid_options = self._batched_stage_rollback_start_options(snapshot, candidate)
                valid_starts = [int(option["value"]) for option in valid_options if _safe_int(option.get("value"), 0) > 0]
                if interrupted_start in valid_starts:
                    return candidate, interrupted_start
                return candidate, valid_starts[-1] if valid_starts else None

        for candidate in (batch_stage, rewrite_stage, current_stage):
            if candidate in ROLLBACK_STAGE_LABELS:
                return candidate, None
        return "", None

    def _interrupted_batch_start_episode(self, snapshot: dict[str, Any]) -> int | None:
        """优先按真实缓存覆盖度推断中断批次，避免旧的 start_episode 把回退点带偏。"""
        debug_state = snapshot.get("debug_state") or {}
        variables = debug_state.get("variables") if isinstance(debug_state, dict) else {}
        if not isinstance(variables, dict):
            variables = {}

        total_episodes = int(snapshot.get("total_episodes") or 0)
        batch_size = max(1, int(settings.batch_size or 5))
        batches = list(iter_episode_batches(total_episodes, batch_size=batch_size)) if total_episodes > 0 else []
        if batches:
            batch_stage = _normalize_rollback_stage_key(variables.get(LOCAL_CURRENT_BATCH_STAGE))
            rewrite_stage = _normalize_rollback_stage_key(variables.get(LOCAL_REWRITE_FROM_STAGE))
            current_stage = self._snapshot_stage_to_rollback_stage(snapshot, variables)
            saved_start = _safe_int(
                variables.get(BATCH_START_EPISODE)
                or variables.get(HOOK_START_VAR)
                or variables.get(DIALOGUE_START_VAR)
                or variables.get(SCRIPT_START_VAR),
                0,
            )
            derived_start = self._derived_batch_start_from_cache(
                variables,
                batches=batches,
                batch_stage=batch_stage,
                rewrite_stage=rewrite_stage,
                current_stage=current_stage,
            )
            if derived_start is not None:
                return derived_start
            if saved_start > 0:
                return saved_start

        current_batch = str(snapshot.get("current_batch") or "").strip()
        if current_batch:
            prefix = current_batch.split("-", 1)[0].strip()
            parsed = _safe_int(prefix, 0)
            if parsed > 0:
                return parsed
        return None

    def _derived_batch_start_from_cache(
        self,
        variables: dict[str, Any],
        *,
        batches: list[BatchWindow],
        batch_stage: str,
        rewrite_stage: str,
        current_stage: str,
    ) -> int | None:
        """根据 hooks/dialogues/script 的真实缓存，反推出当前应该从哪一批继续。"""
        if not batches:
            return None

        hooks_start = self._next_unfinished_object_batch_start(variables.get(ALL_HOOKS), batches)
        dialogues_start = self._next_unfinished_object_batch_start(variables.get(ALL_DIALOGUES), batches)
        script_start = self._next_unfinished_script_batch_start(variables, batches)

        anchor_stage = ""
        for candidate in (batch_stage, rewrite_stage, current_stage):
            if candidate in {"hooks", "dialogues", "script", "final"}:
                anchor_stage = candidate
                break

        if anchor_stage == "hooks":
            return hooks_start
        if anchor_stage == "dialogues":
            return dialogues_start
        if anchor_stage in {"script", "final"}:
            return script_start
        return min(hooks_start, dialogues_start, script_start)

    def _next_unfinished_object_batch_start(
        self,
        value: Any,
        batches: list[BatchWindow],
    ) -> int:
        payload = copy.deepcopy(value) if isinstance(value, dict) else {}
        for batch in batches:
            if not self._episode_object_covers_batch(payload, batch):
                return batch.start_episode
        return batches[-1].end_episode + 1

    def _episode_object_covers_batch(self, value: Any, batch: BatchWindow) -> bool:
        payload = copy.deepcopy(value) if isinstance(value, dict) else {}
        episodes = payload.get("episodes")
        if not isinstance(episodes, list):
            return False
        episode_numbers = sorted(
            {
                _safe_int(item.get("episode"), 0)
                for item in episodes
                if isinstance(item, dict)
                and batch.start_episode <= _safe_int(item.get("episode"), 0) <= batch.end_episode
            }
        )
        expected = list(range(batch.start_episode, batch.end_episode + 1))
        return episode_numbers == expected

    def _next_unfinished_script_batch_start(
        self,
        variables: dict[str, Any],
        batches: list[BatchWindow],
    ) -> int:
        script_batches = _normalize_batch_text_map(variables.get(LOCAL_SCRIPT_BATCHES))
        script_episodes = _normalize_episode_script_map(variables.get(LOCAL_SCRIPT_EPISODES))
        summary_by_batch = _normalize_batch_text_map(variables.get(LOCAL_SUMMARY_BY_BATCH))
        for batch in batches:
            batch_text = str(script_batches.get(batch.start_episode) or "").strip()
            if not batch_text:
                expected = range(batch.start_episode, batch.end_episode + 1)
                if all(str(script_episodes.get(episode) or "").strip() for episode in expected):
                    batch_text = "\n".join(
                        str(script_episodes.get(episode) or "").strip()
                        for episode in expected
                    ).strip()
            batch_summary = str(summary_by_batch.get(batch.start_episode) or "").strip()
            if not batch_text or not batch_summary:
                return batch.start_episode
        return batches[-1].end_episode + 1

    def _episode_stage_completed_count(self, total_episodes: int, *values: Any) -> int:
        if total_episodes <= 0:
            return 0

        covered: set[int] = set()
        for value in values:
            payloads: list[dict[str, Any]] = []
            if isinstance(value, dict) and isinstance(value.get("episodes"), list):
                payloads.append(value)
            elif isinstance(value, dict):
                payloads.extend(_normalize_batch_object_map(value).values())

            for payload in payloads:
                episodes = payload.get("episodes")
                if not isinstance(episodes, list):
                    continue
                for item in episodes:
                    if not isinstance(item, dict):
                        continue
                    episode_no = _safe_int(item.get("episode"), 0)
                    if 1 <= episode_no <= total_episodes:
                        covered.add(episode_no)
        return len(covered)

    def _script_completed_episode_count(
        self,
        snapshot: dict[str, Any],
        variables: dict[str, Any],
        total_episodes: int,
    ) -> int:
        if total_episodes <= 0:
            return 0

        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        if (
            str(snapshot.get("status") or "").strip().lower() == "completed"
            or any(str(artifacts.get(key) or "").strip() for key in ("final_output_text", "final_script"))
        ):
            return total_episodes

        completed: set[int] = set()
        script_episodes = _normalize_episode_script_map(variables.get(LOCAL_SCRIPT_EPISODES))
        for episode_no in script_episodes:
            if 1 <= episode_no <= total_episodes:
                completed.add(episode_no)

        script_batches = _normalize_batch_text_map(variables.get(LOCAL_SCRIPT_BATCHES))
        if script_batches:
            batch_size = max(1, int(settings.batch_size or 5))
            for batch in iter_episode_batches(total_episodes, batch_size=batch_size):
                if str(script_batches.get(batch.start_episode) or "").strip():
                    completed.update(range(batch.start_episode, batch.end_episode + 1))

        return len(completed)

    def _progress_value_present(self, value: Any) -> bool:
        return has_meaningful_content(value)

    def _progress_stage_key(self, snapshot: dict[str, Any], variables: dict[str, Any]) -> str:
        batch_stage = str(variables.get(LOCAL_CURRENT_BATCH_STAGE) or "").strip().lower()
        if batch_stage in {"hook", "dialogue", "script"}:
            return batch_stage
        return str(snapshot.get("current_stage") or "").strip().lower()

    def _progress_batch_start_episode(
        self,
        snapshot: dict[str, Any],
        variables: dict[str, Any],
        total_episodes: int,
    ) -> int:
        upper_bound = max(1, int(total_episodes or 0) + 1)
        start_episode = _safe_int(variables.get(BATCH_START_EPISODE), 0)
        if 1 <= start_episode <= upper_bound:
            return start_episode

        current_batch = str(snapshot.get("current_batch") or "").strip()
        match = re.match(r"^\s*(\d+)", current_batch)
        if match:
            parsed = _safe_int(match.group(1), 0)
            if 1 <= parsed <= upper_bound:
                return parsed
        return 0

    def _max_fixed_stage_index(self, snapshot: dict[str, Any], progress_stage: str) -> int:
        status = str(snapshot.get("status") or "").strip().lower()
        if status == "completed" or progress_stage in {"finished", "hook", "dialogue", "script", "finalize"}:
            return 8
        stage_limits = {
            "framework": 0,
            "appearance_strategy": 1,
            "validation": 4,
            "worldview": 4,
            "character": 5,
            "scene": 6,
            "appearance": 7,
        }
        return int(stage_limits.get(progress_stage, 0))

    def _fixed_stage_completion_flags(
        self,
        snapshot: dict[str, Any],
        variables: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> list[bool]:
        del snapshot
        framework_done = all(
            self._progress_value_present(artifacts.get(key))
            for key in (
                "script_title_content",
                "story_outline",
                "character_bios",
                "core_scene_input",
                "episode_plan",
            )
        )
        pre_strategy_done = all(
            self._progress_value_present(variables.get(key) or artifacts.get(artifact_key))
            for key, artifact_key in (
                (CHARACTER_APPEARANCE_REQUIREMENTS, "character_appearance_requirements"),
                (CHARACTER_ALIAS_NAMING_RULES, "character_alias_naming_rules"),
                (OUTFIT_SWITCH_RULES, "outfit_switch_rules"),
            )
        )
        consistency_done = variables.get(IS_CONSISTENT) is not None
        normalize_done = self._progress_value_present(
            variables.get(NORMALIZED_EPISODE_PLAN) or artifacts.get("normalized_episode_plan")
        )
        worldview_done = self._progress_value_present(artifacts.get("worldview"))
        character_done = self._progress_value_present(
            artifacts.get("character_natural_language")
            or artifacts.get("character_summary")
            or variables.get(CHARACTERS)
            or variables.get(CHARACTER_NATURAL_LANGUAGE_VAR)
        )
        scene_done = self._progress_value_present(
            artifacts.get("scene_natural_language")
            or artifacts.get("core_scene_summary")
            or artifacts.get("scene_json")
            or variables.get(SCENES)
            or variables.get(SCENE_NATURAL_LANGUAGE_VAR)
        )
        appearance_done = self._progress_value_present(
            variables.get(APPEARANCE_MAPPING) or artifacts.get("appearance_mapping")
        )
        return [
            framework_done,
            pre_strategy_done,
            consistency_done,
            normalize_done,
            worldview_done,
            character_done,
            scene_done,
            appearance_done,
        ]

    def _count_contiguous_completed_stages(
        self,
        flags: list[bool],
        *,
        allowed_count: int,
    ) -> int:
        completed = 0
        for index, done in enumerate(flags, start=1):
            if index > allowed_count or not done:
                break
            completed += 1
        return completed

    def _snapshot_progress_metrics(self, snapshot: dict[str, Any]) -> dict[str, int]:
        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        debug_state = snapshot.get("debug_state") if isinstance(snapshot.get("debug_state"), dict) else {}
        variables = debug_state.get("variables") if isinstance(debug_state.get("variables"), dict) else {}
        total_episodes = max(0, _safe_int(snapshot.get("total_episodes"), 0))
        fixed_stage_total = 8
        progress_stage = self._progress_stage_key(snapshot, variables)
        batch_stage = str(variables.get(LOCAL_CURRENT_BATCH_STAGE) or "").strip().lower()
        batch_start_episode = self._progress_batch_start_episode(snapshot, variables, total_episodes)
        completed_before_current_batch = (
            min(total_episodes, max(0, batch_start_episode - 1))
            if batch_start_episode > 0
            else 0
        )

        fixed_flags = self._fixed_stage_completion_flags(snapshot, variables, artifacts)
        fixed_completed = self._count_contiguous_completed_stages(
            fixed_flags,
            allowed_count=self._max_fixed_stage_index(snapshot, progress_stage),
        )

        final_completed = (
            str(snapshot.get("status") or "").strip().lower() == "completed"
            or progress_stage == "finished"
        )

        hooks_actual = self._episode_stage_completed_count(total_episodes, variables.get(ALL_HOOKS))
        dialogues_actual = self._episode_stage_completed_count(total_episodes, variables.get(ALL_DIALOGUES))
        script_actual = self._script_completed_episode_count(snapshot, variables, total_episodes)

        hooks_completed = 0
        dialogues_completed = 0
        script_completed = 0

        if final_completed:
            fixed_completed = fixed_stage_total
            hooks_completed = total_episodes
            dialogues_completed = total_episodes
            script_completed = total_episodes
        elif progress_stage == "hook":
            hooks_completed = (
                completed_before_current_batch
                if batch_stage == "hook" and batch_start_episode > 0
                else hooks_actual
            )
        elif progress_stage == "dialogue":
            hooks_completed = hooks_actual
            dialogues_completed = (
                completed_before_current_batch
                if batch_stage == "dialogue" and batch_start_episode > 0
                else dialogues_actual
            )
        elif progress_stage == "script":
            hooks_completed = hooks_actual
            dialogues_completed = dialogues_actual
            script_completed = (
                max(script_actual, completed_before_current_batch)
                if batch_stage == "script" and batch_start_episode > 0
                else script_actual
            )
        elif progress_stage == "finalize":
            hooks_completed = hooks_actual
            dialogues_completed = max(dialogues_actual, script_actual)
            if self._progress_value_present(artifacts.get("final_output_text") or artifacts.get("final_script")):
                script_completed = total_episodes
            else:
                script_completed = script_actual

        hooks_completed = min(total_episodes, max(0, hooks_completed))
        dialogues_completed = min(total_episodes, max(dialogues_completed, script_completed))
        hooks_completed = min(total_episodes, max(hooks_completed, dialogues_completed))
        dialogues_completed = min(dialogues_completed, hooks_completed)
        script_completed = min(script_completed, dialogues_completed)

        total_units = fixed_stage_total + (total_episodes * 3) + 1
        completed_units = fixed_completed + hooks_completed + dialogues_completed + script_completed + (1 if final_completed else 0)
        completed_units = max(0, min(total_units, completed_units))
        generated_episodes = total_episodes if final_completed else script_completed

        if final_completed:
            progress_percent = 100
        else:
            progress_percent = int(round((completed_units / total_units) * 100)) if total_units > 0 else 0

        return {
            "progress_percent": max(0, min(100, progress_percent)),
            "generated_episodes": max(0, generated_episodes),
        }

    def _completed_input_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        input_payload = _select_non_empty_fields(
            snapshot.get("input_payload") or {},
            COMPLETED_INPUT_PAYLOAD_KEYS,
        )
        artifacts = snapshot.get("artifacts") or {}
        title = clean_user_visible_text(
            artifacts.get("script_title_content")
            or snapshot.get("title")
            or input_payload.get("title")
            or ""
        ).strip()
        story_outline = clean_user_visible_text(
            artifacts.get("story_outline")
            or input_payload.get("story_outline")
            or ""
        ).strip()
        total_episodes = snapshot.get("total_episodes") or input_payload.get("total_episodes")
        if title:
            input_payload["title"] = title
        if story_outline:
            input_payload["story_outline"] = story_outline
        if total_episodes:
            input_payload["total_episodes"] = int(total_episodes)
        return input_payload

    def _compact_completed_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        compacted = copy.deepcopy(snapshot)
        compacted["artifacts"] = _select_non_empty_fields(
            compacted.get("artifacts") or {},
            COMPLETED_ARTIFACT_KEYS,
        )
        artifacts = compacted.get("artifacts") if isinstance(compacted.get("artifacts"), dict) else {}
        if isinstance(artifacts, dict):
            for key in (
                "script_title_content",
                "framework_natural_language",
                "story_outline",
                "character_natural_language",
                "character_summary",
                "scene_natural_language",
                "core_scene_summary",
                "worldview_natural_language",
                APPEARANCE_NATURAL_LANGUAGE_ARTIFACT,
                "final_script",
                "final_output_text",
            ):
                text = clean_user_visible_text(artifacts.get(key))
                if text:
                    artifacts[key] = text
                else:
                    artifacts.pop(key, None)
            if is_meaningful_text(artifacts.get(APPEARANCE_NATURAL_LANGUAGE_ARTIFACT)):
                for key in (
                    "appearance_mapping",
                    "character_registry",
                    "character_alias_registry",
                    "episode_alias_plan",
                ):
                    artifacts.pop(key, None)
        compacted["input_payload"] = self._completed_input_payload(compacted)
        compacted["current_node_id"] = None
        compacted["current_node_name"] = None
        compacted["current_batch"] = None
        # 用户确认“满意完成”后，不再保留可回退执行缓存。
        # 这样既减小快照体积，也避免前端误以为还能继续从中间阶段接着改。
        compacted.pop("debug_state", None)
        compacted.pop("logs", None)
        compacted.pop("error", None)
        compacted.pop("prompt_fixes", None)
        compacted["completion_confirmed"] = True
        compacted["awaiting_user_confirmation"] = False
        compacted["cache_retained"] = False
        compacted["message"] = COMPLETION_CONFIRMED_MESSAGE
        return compacted

    def _compact_record_after_completion(self, record: TaskRecord) -> None:
        compacted = self._compact_completed_snapshot(record.clone_snapshot())
        with record.lock:
            record.snapshot = compacted
        self._persist_snapshot(record)

    def _asset_summary(
        self,
        snapshot: dict[str, Any],
        *,
        include_private: bool,
        use_teaser: bool,
    ) -> dict[str, Any]:
        input_payload = snapshot.get("input_payload") or {}
        artifacts = snapshot.get("artifacts") or {}
        progress_metrics = self._snapshot_progress_metrics(snapshot)
        story_outline = str(
            input_payload.get("story_outline")
            or artifacts.get("story_outline")
            or ""
        ).strip()
        final_script = self._best_final_script_text(snapshot)
        summary = self._fallback_story_teaser(story_outline) if use_teaser else ""
        if not summary:
            summary = story_outline or "这个作品还没有填写故事梗概。"
        payload = {
            "project_id": snapshot.get("project_id"),
            "task_id": snapshot.get("task_id"),
            "title": artifacts.get("script_title_content") or snapshot.get("title") or input_payload.get("title") or "未命名剧本",
            "summary": summary[:360],
            "status": snapshot.get("status"),
            "visibility": snapshot.get("visibility") or "private",
            "updated_at": snapshot.get("updated_at"),
            "created_at": snapshot.get("created_at"),
            "has_final": bool(final_script),
            "message": _public_status_message(snapshot),
            "current_stage": snapshot.get("current_stage"),
            "current_stage_label": snapshot.get("current_stage_label") or "待开始",
            "current_batch": snapshot.get("current_batch"),
            "progress_percent": progress_metrics["progress_percent"],
            "generated_episodes": progress_metrics["generated_episodes"],
            "total_episodes": int(snapshot.get("total_episodes") or 0),
            "model_label": ((snapshot.get("model_option") or {}).get("label") or ""),
            "completion_confirmed": _completion_confirmed(snapshot),
            "awaiting_user_confirmation": _awaiting_completion_confirmation(snapshot),
            "cache_notice": _cache_notice(snapshot),
        }
        if include_private:
            payload["final_preview"] = final_script[:500]
        return payload

    def _story_teaser_for_snapshot(self, snapshot: dict[str, Any]) -> str:
        input_payload = snapshot.get("input_payload") or {}
        artifacts = snapshot.get("artifacts") or {}
        story_outline = str(
            artifacts.get("story_outline")
            or input_payload.get("story_outline")
            or ""
        ).strip()
        if not story_outline:
            return ""

        has_final = bool(self._best_final_script_text(snapshot))
        if str(snapshot.get("status") or "") != "completed" or not has_final:
            return self._fallback_story_teaser(story_outline)

        cached_teaser = str(artifacts.get(STORY_TEASER_ARTIFACT) or "").strip()
        cached_source = str(artifacts.get(STORY_TEASER_SOURCE_ARTIFACT) or "").strip()
        if cached_teaser and cached_source == story_outline:
            return cached_teaser

        teaser = self._generate_story_teaser(story_outline) or self._fallback_story_teaser(story_outline)
        self._cache_story_teaser(snapshot, teaser, story_outline)
        return teaser

    def _fallback_story_teaser(self, story_outline: str) -> str:
        condensed = " ".join(str(story_outline or "").replace("\r", "\n").split())
        return condensed[:88] if condensed else "这个作品还没有填写故事梗概。"

    def _generate_story_teaser(self, story_outline: str) -> str:
        """社区/资产摘要不再额外调用模型生成，统一走本地梗概截断。"""
        return ""

    def _cache_story_teaser(
        self,
        snapshot: dict[str, Any],
        teaser: str,
        story_outline: str,
    ) -> None:
        project_id = int(snapshot.get("project_id") or 0)
        if project_id <= 0 or not teaser:
            return
        artifacts_update = {
            STORY_TEASER_ARTIFACT: teaser,
            STORY_TEASER_SOURCE_ARTIFACT: story_outline,
        }
        record = self._projects.get(project_id)
        if record is not None:
            self._update_snapshot(record, artifacts=artifacts_update)
            snapshot.setdefault("artifacts", {}).update(artifacts_update)
            return

        persisted = copy.deepcopy(snapshot)
        persisted.setdefault("artifacts", {}).update(artifacts_update)
        self._project_path(project_id).write_text(
            json.dumps(persisted, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        snapshot.setdefault("artifacts", {}).update(artifacts_update)

