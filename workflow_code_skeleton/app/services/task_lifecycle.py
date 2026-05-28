
from __future__ import annotations

"""Extracted TaskManager mixin for TaskLifecycleMixin."""

from . import task_manager_common as _task_manager_common
from .task_manager_common import *
globals().update(
    {name: getattr(_task_manager_common, name) for name in dir(_task_manager_common) if name.startswith("_")}
)
from .task_state import TaskControl, TaskRecord, TaskTerminated, WorkflowRuntime

from .task_manager_common import (
    _batch_end_episode,
    _completion_confirmed,
    _join_script_episode_map,
    _join_script_parts,
    _normalize_batch_object_map,
    _normalize_batch_text_map,
    _normalize_episode_script_map,
    _normalize_rollback_stage_key,
    _partial_script_artifacts_from_variables,
    _rollback_stage_requires_episode_range,
    _safe_int,
    _slice_episode_object_before,
    _string_keyed_batch_map,
)

class TaskLifecycleMixin:
    def start_task(
        self,
        *,
        user_id: int,
        input_payload: dict[str, Any],
        workflow_spec_path: str,
        model_selection_id: str | None,
    ) -> dict[str, Any]:
        project_id = self._next_project_id()
        self._remember_latest_project(user_id, project_id)
        task_id = uuid.uuid4().hex[:12]
        model_option = settings.resolve_model_selection(model_selection_id)
        spec = None if use_fastgpt_backend() else WorkflowSpec(workflow_spec_path)

        snapshot = {
            "user_id": int(user_id),
            "project_id": project_id,
            "task_id": task_id,
            "status": "pending",
            "title": str(input_payload.get("title", "")).strip(),
            "message": "任务已创建，准备开始生成。",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "workflow_spec_path": workflow_spec_path,
            "visibility": "private",
            "asset_type": "new_script" if (
                str(input_payload.get("script_format_mode") or "").strip() == "framework_to_script"
                or str(input_payload.get("workflow_mode") or "").strip() == "framework_to_script"
                or bool(input_payload.get("framework_to_script"))
            ) else "old_script",
            "model_option": {
                "id": model_option.id,
                "label": self._model_alias(model_option.provider),
                "provider": model_option.provider,
                "model": model_option.model,
            }
            if model_option
            else None,
            "input_payload": input_payload,
            "artifacts": {},
            "logs": [],
            "prompt_fixes": spec.get_prompt_fixes() if spec else [],
            "progress_percent": 0,
            "generated_episodes": 0,
            "total_episodes": int(input_payload.get("total_episodes", 0) or 0),
            "current_stage": "validation",
            "current_stage_label": STAGE_LABELS["validation"],
            "current_node_id": None,
            "current_node_name": None,
            "current_batch": None,
            "completion_confirmed": False,
            "awaiting_user_confirmation": False,
            "cache_retained": True,
            "debug_state": {},
            "wait_elapsed_ms": 0,
            "wait_started_at": now_iso(),
        }

        record = TaskRecord(
            user_id=int(user_id),
            project_id=project_id,
            task_id=task_id,
            workflow_spec_path=workflow_spec_path,
            input_payload=input_payload,
            model_option=model_option,
            snapshot=snapshot,
        )
        self._tasks[task_id] = record
        self._projects[project_id] = record
        self._append_log(
            record,
            title="任务创建",
            message="任务已创建，准备开始生成。",
        )
        self._save_resume_checkpoint(record)
        self._persist_snapshot(record)

        thread = threading.Thread(
            target=self._run_task,
            args=(record,),
            daemon=True,
            name=f"workflow-task-{task_id}",
        )
        record.thread = thread
        thread.start()
        return self._public_snapshot(record.clone_snapshot())

    def _render_auxiliary_asset_text(self, value: Any) -> str:
        if isinstance(value, str):
            return clean_multiline_user_visible_text(value)
        if isinstance(value, (dict, list)):
            try:
                return clean_multiline_user_visible_text(
                    json.dumps(value, ensure_ascii=False, indent=2)
                )
            except Exception:
                return clean_multiline_user_visible_text(str(value))
        return clean_multiline_user_visible_text(value)

    def _auxiliary_asset_title(
        self,
        *,
        tool_label: str,
        request_payload: dict[str, Any],
        result: dict[str, Any],
    ) -> str:
        suffix = ""
        filename = str(result.get("filename") or "").strip()
        if filename:
            stem = Path(filename).stem.strip()
            prefix = f"{tool_label}_"
            if stem.startswith(prefix):
                suffix = stem[len(prefix):].strip()
            elif stem and stem != tool_label:
                suffix = stem
        if not suffix:
            output = result.get("output")
            if isinstance(output, dict):
                for key in ("script_title_content", "title", "script_title"):
                    value = clean_user_visible_text(output.get(key)).strip()
                    if value:
                        suffix = value
                        break
        if not suffix:
            suffix = clean_user_visible_text(
                request_payload.get("project_title") or request_payload.get("title") or ""
            ).strip()
        return f"{tool_label}｜{suffix}" if suffix else tool_label

    def _auxiliary_asset_story_outline(
        self,
        *,
        request_payload: dict[str, Any],
        final_text: str,
    ) -> str:
        for key in (
            "story_outline",
            "story",
            "user_expectation",
            "source_outline",
            "target_style",
            "characters",
            "source_characters",
            "text",
        ):
            text = clean_user_visible_text(request_payload.get(key)).strip()
            if text:
                return text
        return clean_multiline_user_visible_text(final_text)

    def save_auxiliary_asset(
        self,
        *,
        user_id: int,
        tool_key: str,
        request_payload: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        tool_label = clean_user_visible_text(result.get("title") or tool_key).strip() or "辅助工具"
        final_text = self._render_auxiliary_asset_text(result.get("text") or result.get("output") or "")
        if not final_text:
            raise ValueError("辅助工具结果为空，暂时无法保存到用户资产。")

        project_id = self._next_project_id()
        timestamp = now_iso()
        story_outline = self._auxiliary_asset_story_outline(
            request_payload=request_payload,
            final_text=final_text,
        )
        title = self._auxiliary_asset_title(
            tool_label=tool_label,
            request_payload=request_payload,
            result=result,
        )
        total_episodes = _safe_int(request_payload.get("total_episodes"), 0)
        snapshot = {
            "user_id": int(user_id),
            "project_id": project_id,
            "task_id": f"tool-{tool_key}-{uuid.uuid4().hex[:10]}",
            "status": "completed",
            "title": title,
            "message": "辅助工具结果已保存到用户资产。",
            "created_at": timestamp,
            "updated_at": timestamp,
            "finished_at": timestamp,
            "workflow_spec_path": "",
            "visibility": "private",
            "model_option": None,
            "asset_kind": AUXILIARY_TOOL_ASSET_KIND,
            "asset_type": "old_script",
            "tool_key": str(tool_key or "").strip(),
            "tool_label": tool_label,
            "tool_request_payload": copy.deepcopy(request_payload or {}),
            "tool_output_type": str(result.get("output_type") or "").strip(),
            "tool_output_source": str((result.get("debug") or {}).get("chosen_output_source") or "").strip(),
            "input_payload": {
                "title": title,
                "story_outline": story_outline,
                "total_episodes": max(0, int(total_episodes or 0)),
            },
            "artifacts": {
                "story_outline": story_outline,
                "final_script": final_text,
                "final_output_text": final_text,
                "tool_filename": clean_user_visible_text(result.get("filename")).strip(),
                "tool_output_type": str(result.get("output_type") or "").strip(),
            },
            "logs": [],
            "progress_percent": 100,
            "generated_episodes": 0,
            "total_episodes": max(0, int(total_episodes or 0)),
            "current_stage": str(tool_key or "").strip(),
            "current_stage_label": tool_label,
            "current_node_id": None,
            "current_node_name": None,
            "current_batch": None,
            "completion_confirmed": True,
            "awaiting_user_confirmation": False,
            "cache_retained": False,
            "debug_state": {},
            "wait_elapsed_ms": 0,
            "wait_started_at": None,
        }
        compacted = self._compact_completed_snapshot(snapshot)
        self._project_path(project_id).write_text(
            json.dumps(compacted, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self._public_snapshot(compacted)

    def create_framework_planner_asset(
        self,
        *,
        user_id: int,
        title: str,
        season_count: int = 1,
        episodes_per_season: int = 60,
        target_format: str = "短剧",
        style: str = "",
        description: str = "",
    ) -> dict[str, Any]:
        clean_title = clean_user_visible_text(title).strip() or "未命名剧本"
        clean_description = clean_multiline_user_visible_text(description).strip()
        clean_format = clean_user_visible_text(target_format).strip() or "短剧"
        clean_style = clean_user_visible_text(style).strip()
        project_id = self._next_project_id()
        timestamp = now_iso()
        input_payload = {
            "title": clean_title,
            "project_title": clean_title,
            "story_outline": clean_description,
            "target_format": clean_format,
            "style": clean_style,
            "season_count": max(1, int(season_count or 1)),
            "episodes_per_season": max(1, int(episodes_per_season or 1)),
            "total_episodes": max(1, int(season_count or 1)) * max(1, int(episodes_per_season or 1)),
        }
        snapshot = {
            "user_id": int(user_id),
            "project_id": project_id,
            "task_id": f"framework-planner-{uuid.uuid4().hex[:10]}",
            "status": "draft",
            "title": clean_title,
            "message": "框架策划资产已创建，可从第一阶段开始填写。",
            "created_at": timestamp,
            "updated_at": timestamp,
            "finished_at": None,
            "workflow_spec_path": "",
            "visibility": "private",
            "model_option": None,
            "asset_kind": "framework_planner",
            "asset_type": "framework",
            "input_payload": input_payload,
            "artifacts": {
                "story_outline": clean_description,
                "target_format": clean_format,
                "style": clean_style,
            },
            "logs": [],
            "progress_percent": 0,
            "generated_episodes": 0,
            "total_episodes": input_payload["total_episodes"],
            "current_stage": "framework_planner",
            "current_stage_label": "剧本框架策划",
            "current_node_id": None,
            "current_node_name": None,
            "current_batch": None,
            "completion_confirmed": False,
            "awaiting_user_confirmation": False,
            "cache_retained": False,
            "debug_state": {"variables": {}},
            "wait_elapsed_ms": 0,
            "wait_started_at": None,
        }
        self._project_path(project_id).write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._remember_latest_project(int(user_id), project_id)
        return self._public_snapshot(snapshot)

    def save_framework_planner_asset(
        self,
        *,
        user_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("保存内容格式不正确")
        basic_config = payload.get("basic_config") if isinstance(payload.get("basic_config"), dict) else {}
        asset_state = payload.get("asset_state") if isinstance(payload.get("asset_state"), dict) else {}
        raw_project_id = (
            payload.get("project_id")
            or asset_state.get("project_id")
            or asset_state.get("asset_id")
        )
        project_id = _safe_int(raw_project_id, 0)
        title = clean_user_visible_text(
            payload.get("project_title")
            or payload.get("title")
            or basic_config.get("project_title")
            or basic_config.get("source_title")
            or ""
        ).strip() or "未命名框架策划"
        now = now_iso()

        if project_id > 0:
            snapshot = self.get_project_snapshot(project_id, user_id=user_id, public_view=False)
            if not snapshot or not self._snapshot_belongs_to_user(snapshot, user_id):
                raise ValueError("project_id 缺失或无权保存该框架资产")
            if str(snapshot.get("asset_kind") or "").strip() != "framework_planner":
                raise ValueError("该项目不是 framework_planner 资产，不能用框架策划保存接口覆盖")
            created_at = snapshot.get("created_at") or now
            task_id = snapshot.get("task_id") or f"framework-planner-{uuid.uuid4().hex[:10]}"
        else:
            project_id = self._next_project_id()
            created_at = now
            task_id = f"framework-planner-{uuid.uuid4().hex[:10]}"

        framework_plan_package = payload.get("framework_plan_package") if isinstance(payload.get("framework_plan_package"), dict) else {}
        stage_state = payload.get("stage_state") if isinstance(payload.get("stage_state"), dict) else {}
        current_stage = str((asset_state or {}).get("current_stage") or "framework_planner").strip() or "framework_planner"
        confirmed_package = bool((stage_state.get("package") or {}).get("confirmed")) if isinstance(stage_state.get("package"), dict) else False
        status = str((asset_state or {}).get("status") or "").strip()
        if status not in {"draft", "in_progress", "completed", "running", "failed", "terminated"}:
            status = "completed" if framework_plan_package and confirmed_package else "in_progress"
        if status == "running":
            status = "in_progress"

        total_episodes = _safe_int(
            payload.get("total_episodes")
            or basic_config.get("total_episodes")
            or basic_config.get("episodes_per_season"),
            0,
        )
        if total_episodes <= 0:
            total_episodes = max(1, _safe_int(basic_config.get("season_count"), 1)) * max(
                1,
                _safe_int(basic_config.get("episodes_per_season"), 60),
            )

        framework_state = {
            "project_id": project_id,
            "project_title": title,
            "basic_config": copy.deepcopy(basic_config),
            "source_brief": copy.deepcopy(payload.get("source_brief") if isinstance(payload.get("source_brief"), dict) else {}),
            "worldview_plan": copy.deepcopy(payload.get("worldview_plan") if isinstance(payload.get("worldview_plan"), dict) else {}),
            "character_plan": copy.deepcopy(payload.get("character_plan") if isinstance(payload.get("character_plan"), dict) else {}),
            "beat_checkpoint_timeline": copy.deepcopy(payload.get("beat_checkpoint_timeline") if isinstance(payload.get("beat_checkpoint_timeline"), list) else []),
            "checkpoint_explanation": copy.deepcopy(payload.get("checkpoint_explanation") if isinstance(payload.get("checkpoint_explanation"), dict) else {}),
            "character_storylines": copy.deepcopy(payload.get("character_storylines") if isinstance(payload.get("character_storylines"), list) else []),
            "storyline_decisions": copy.deepcopy(payload.get("storyline_decisions") if isinstance(payload.get("storyline_decisions"), list) else []),
            "adaptation_guide": copy.deepcopy(payload.get("adaptation_guide") if isinstance(payload.get("adaptation_guide"), dict) else {}),
            "framework_plan_package": copy.deepcopy(framework_plan_package),
            "validation_report": copy.deepcopy(payload.get("validation_report") if isinstance(payload.get("validation_report"), dict) else {}),
            "display_texts": copy.deepcopy(payload.get("display_texts") if isinstance(payload.get("display_texts"), dict) else {}),
            "prompt_preferences": copy.deepcopy(payload.get("prompt_preferences") if isinstance(payload.get("prompt_preferences"), dict) else {}),
            "preference_snapshot": copy.deepcopy(payload.get("preference_snapshot") if isinstance(payload.get("preference_snapshot"), dict) else {}),
            "selected_preference_tag_ids": copy.deepcopy(payload.get("selected_preference_tag_ids") if isinstance(payload.get("selected_preference_tag_ids"), list) else []),
            "selected_preference_tags": copy.deepcopy(payload.get("selected_preference_tags") if isinstance(payload.get("selected_preference_tags"), list) else []),
            "asset_state": copy.deepcopy(asset_state),
            "stage_state": copy.deepcopy(stage_state),
            "current_view": str(payload.get("current_view") or "package" if framework_plan_package else "basic"),
            "created_at": created_at,
            "updated_at": now,
        }
        framework_state["asset_state"]["asset_kind"] = "framework_planner"
        framework_state["asset_state"]["asset_type"] = "framework"
        framework_state["asset_state"]["asset_id"] = project_id
        framework_state["asset_state"]["project_id"] = project_id
        framework_state["asset_state"]["status"] = status
        framework_state["asset_state"]["updated_at"] = now

        input_payload = copy.deepcopy(framework_state)
        input_payload.update(
            {
                "title": title,
                "project_title": title,
                "source_title": str(basic_config.get("source_title") or title),
                "target_format": str(basic_config.get("target_format") or payload.get("target_format") or "短剧"),
                "season_count": _safe_int(basic_config.get("season_count") or payload.get("season_count"), 1),
                "episodes_per_season": _safe_int(basic_config.get("episodes_per_season") or payload.get("episodes_per_season"), total_episodes),
                "total_episodes": total_episodes,
                "story_outline": clean_multiline_user_visible_text(
                    basic_config.get("source_text")
                    or payload.get("user_expectation")
                    or payload.get("adaptation_direction")
                    or ""
                ).strip(),
                "asset_kind": "framework_planner",
                "asset_type": "framework",
                "framework_planner_state": copy.deepcopy(framework_state),
                "preference_snapshot": copy.deepcopy(framework_state["preference_snapshot"]),
            }
        )

        snapshot = {
            "user_id": int(user_id),
            "project_id": project_id,
            "task_id": task_id,
            "status": status,
            "title": title,
            "message": "框架策划资产已保存。",
            "created_at": created_at,
            "updated_at": now,
            "finished_at": now if status == "completed" else None,
            "workflow_spec_path": "",
            "visibility": "private",
            "model_option": None,
            "asset_kind": "framework_planner",
            "asset_type": "framework",
            "input_payload": input_payload,
            "artifacts": {
                "story_outline": input_payload.get("story_outline") or "",
                "framework_planner_state": copy.deepcopy(framework_state),
                "framework_plan_package": copy.deepcopy(framework_plan_package),
                "validation_report": copy.deepcopy(framework_state["validation_report"]),
                "preference_snapshot": copy.deepcopy(framework_state["preference_snapshot"]),
            },
            "metadata": {
                "preference_snapshot": copy.deepcopy(framework_state["preference_snapshot"]),
            },
            "logs": [],
            "progress_percent": 100 if status == "completed" else 0,
            "generated_episodes": 0,
            "total_episodes": total_episodes,
            "current_stage": current_stage,
            "current_stage_label": "三幕十五节拍框架策划",
            "current_node_id": None,
            "current_node_name": None,
            "current_batch": None,
            "completion_confirmed": status == "completed",
            "awaiting_user_confirmation": False,
            "cache_retained": False,
            "debug_state": {"variables": {"framework_planner_state": copy.deepcopy(framework_state)}},
            "wait_elapsed_ms": 0,
            "wait_started_at": None,
        }
        self._project_path(project_id).write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._remember_latest_project(int(user_id), project_id)
        return self._public_snapshot(snapshot)

    def update_project_asset(
        self,
        project_id: int,
        *,
        user_id: int,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        record = self._projects.get(project_id)
        if record:
            snapshot = record.clone_snapshot()
        else:
            snapshot = self.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot or not self._snapshot_belongs_to_user(snapshot, user_id):
            raise ValueError("项目不存在或无权操作")
        is_tool_asset = self._is_auxiliary_tool_asset(snapshot)
        if (not is_tool_asset) and _completion_confirmed(snapshot) and any(
            key in changes for key in ("title", "story_outline", "final_script")
        ):
            raise ValueError("该剧本已确认满意完成，正文内容已锁定；如需调整请重新生成。公开/私有仍可随时切换。")

        title = str(changes.get("title") or "").strip()
        story_outline = str(changes.get("story_outline") or "").strip()
        final_script = changes.get("final_script")
        visibility = str(changes.get("visibility") or snapshot.get("visibility") or "private").strip()
        if visibility not in {"public", "private"}:
            raise ValueError("隐私设置只能是 public 或 private")

        if title:
            snapshot["title"] = title
            snapshot.setdefault("input_payload", {})["title"] = title
        if story_outline:
            snapshot.setdefault("input_payload", {})["story_outline"] = story_outline
            artifacts = dict(snapshot.get("artifacts") or {})
            artifacts["story_outline"] = story_outline
            artifacts.pop(STORY_TEASER_ARTIFACT, None)
            artifacts.pop(STORY_TEASER_SOURCE_ARTIFACT, None)
            snapshot["artifacts"] = artifacts
        if final_script is not None:
            text = clean_multiline_user_visible_text(final_script) if is_tool_asset else clean_user_visible_text(final_script).strip()
            artifacts = dict(snapshot.get("artifacts") or {})
            artifacts["final_script"] = text
            artifacts["final_output_text"] = text
            snapshot["artifacts"] = artifacts
        snapshot["visibility"] = visibility
        snapshot["updated_at"] = now_iso()

        if record:
            with record.lock:
                record.snapshot = snapshot
            self._persist_snapshot(record)
        else:
            self._project_path(project_id).write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return self._public_snapshot(snapshot)

    def confirm_project_completion(
        self,
        project_id: int,
        *,
        user_id: int,
    ) -> dict[str, Any]:
        snapshot = self.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot or not self._snapshot_belongs_to_user(snapshot, user_id):
            raise ValueError("项目不存在或无权操作")
        if str(snapshot.get("status") or "") != "completed":
            raise ValueError("只有已完成的剧本才能确认满意完成")
        if _completion_confirmed(snapshot):
            return self._public_snapshot(snapshot)

        record = self._projects.get(project_id)
        if record:
            self._update_snapshot(
                record,
                completion_confirmed=True,
                awaiting_user_confirmation=False,
                cache_retained=False,
                message=COMPLETION_CONFIRMED_MESSAGE,
                finished_at=snapshot.get("finished_at") or now_iso(),
            )
            self._compact_record_after_completion(record)
            return self._public_snapshot(record.clone_snapshot())

        snapshot.update(
            {
                "completion_confirmed": True,
                "awaiting_user_confirmation": False,
                "cache_retained": False,
                "message": COMPLETION_CONFIRMED_MESSAGE,
                "finished_at": snapshot.get("finished_at") or now_iso(),
            }
        )
        compacted = self._compact_completed_snapshot(snapshot)
        self._project_path(project_id).write_text(
            json.dumps(compacted, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self._public_snapshot(compacted)

    def rollback_project_to_stage(
        self,
        project_id: int,
        *,
        user_id: int,
        stage_key: str,
        start_episode: int | None = None,
    ) -> dict[str, Any]:
        rollback_stage = _normalize_rollback_stage_key(stage_key)
        if rollback_stage not in ROLLBACK_STAGE_LABELS:
            raise ValueError("请选择有效的回退阶段")

        snapshot = self.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot or not self._snapshot_belongs_to_user(snapshot, user_id):
            raise ValueError("项目不存在或无权操作")
        status = str(snapshot.get("status") or "")
        if status in {"pending", "running"}:
            raise ValueError("任务仍在执行中，不能回退重写")
        if status not in {"completed", "paused", "pausing", "terminated", "failed"}:
            raise ValueError("当前状态不支持阶段回退重写")
        if _completion_confirmed(snapshot):
            raise ValueError("该剧本已确认满意完成并清理缓存，如需调整请重新生成。")

        debug_state = snapshot.get("debug_state")
        if not isinstance(debug_state, dict) or not isinstance(debug_state.get("variables"), dict):
            raise ValueError("当前项目缺少可回退的执行缓存，无法按阶段重写。")

        _, default_start_episode = self._rollback_defaults(snapshot)
        rollback_start_episode: int | None = None
        if _rollback_stage_requires_episode_range(rollback_stage):
            rollback_start_episode = _safe_int(start_episode, 0) or None
            if rollback_start_episode is None and default_start_episode:
                rollback_start_episode = int(default_start_episode)
            rollback_options = self._batched_stage_rollback_start_options(snapshot, rollback_stage)
            valid_start_episodes = {int(option["value"]) for option in rollback_options if _safe_int(option.get("value"), 0) > 0}
            if rollback_start_episode is None:
                raise ValueError(f"请选择{ROLLBACK_STAGE_LABELS[rollback_stage]}开始重写的集数范围")
            batch_size = max(1, int(settings.batch_size or 5))
            try:
                rollback_start_episode = validate_rewrite_start_episode(
                    rollback_start_episode,
                    int(snapshot.get("total_episodes") or 0),
                    batch_size=batch_size,
                )
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
            if rollback_start_episode not in valid_start_episodes:
                raise ValueError(rewrite_start_validation_message(batch_size))

        old_task_id = str(snapshot.get("task_id") or "").strip()
        old_record = self._projects.get(project_id)
        if old_record and status in {"paused", "pausing", "terminated"}:
            self._prepare_record_for_replacement(old_record)

        task_id = old_task_id or uuid.uuid4().hex[:12]
        rollback_snapshot = self._build_stage_rollback_snapshot(
            snapshot,
            rollback_stage,
            start_episode=rollback_start_episode,
        )
        model_option = settings.resolve_model_selection(
            (snapshot.get("model_option") or {}).get("id")
        )
        stage_label = ROLLBACK_STAGE_LABELS[rollback_stage]
        if _rollback_stage_requires_episode_range(rollback_stage) and rollback_start_episode:
            batch_size = max(1, int(settings.batch_size or 5))
            end_episode = min(int(snapshot.get("total_episodes") or 0), rollback_start_episode + batch_size - 1)
            if end_episode < int(snapshot.get("total_episodes") or 0):
                stage_label = (
                    f"{stage_label}（从第 {rollback_start_episode} 集开始，"
                    f"将按批次重写第 {rollback_start_episode}-{end_episode} 集，并继续重写后续批次）"
                )
            else:
                stage_label = f"{stage_label}（从第 {rollback_start_episode} 集开始，将重写第 {rollback_start_episode}-{end_episode} 集）"
        new_snapshot = copy.deepcopy(rollback_snapshot)
        new_snapshot.update(
            {
                "task_id": task_id,
                "status": "pending",
                "message": f"已回退到“{stage_label}”，准备在当前资产上继续生成。",
                "error": None,
                "rollback_of_task_id": None,
                "rollback_stage": rollback_stage,
                "rollback_start_episode": rollback_start_episode,
                "updated_at": now_iso(),
                "finished_at": None,
                "completion_confirmed": False,
                "awaiting_user_confirmation": False,
                "cache_retained": True,
                "wait_elapsed_ms": 0,
                "wait_started_at": now_iso(),
            }
        )

        if old_record is not None:
            record = old_record
            record.user_id = int(snapshot.get("user_id") or user_id or 0)
            record.project_id = int(project_id)
            record.task_id = task_id
            record.workflow_spec_path = str(snapshot.get("workflow_spec_path", ""))
            record.input_payload = copy.deepcopy(snapshot.get("input_payload") or {})
            record.model_option = model_option
            record.snapshot = new_snapshot
            record.control = TaskControl()
            record.thread = None
            record.resume_snapshot = rollback_snapshot
        else:
            record = TaskRecord(
                user_id=int(snapshot.get("user_id") or user_id or 0),
                project_id=int(project_id),
                task_id=task_id,
                workflow_spec_path=str(snapshot.get("workflow_spec_path", "")),
                input_payload=copy.deepcopy(snapshot.get("input_payload") or {}),
                model_option=model_option,
                snapshot=new_snapshot,
                resume_snapshot=rollback_snapshot,
            )
        with self._lock:
            if old_task_id and old_task_id != task_id:
                self._tasks.pop(old_task_id, None)
            self._tasks[task_id] = record
            self._projects[int(project_id)] = record
            self._remember_latest_project(int(user_id), int(project_id))
        self._append_log(
            record,
            title="控制动作：阶段回退重写",
            message=f"已保留前序阶段结果，并在当前资产上从“{stage_label}”开始重新生成。",
        )
        self._save_resume_checkpoint(record)
        self._persist_snapshot(record)

        thread = threading.Thread(
            target=self._run_task,
            args=(record,),
            daemon=True,
            name=f"workflow-task-{task_id}",
        )
        record.thread = thread
        thread.start()
        return self._public_snapshot(record.clone_snapshot())

    def _prepare_record_for_replacement(self, record: TaskRecord) -> None:
        thread = record.thread
        if thread is None or not thread.is_alive():
            return
        record.control.request_terminate()
        thread.join(timeout=3.0)
        if thread.is_alive():
            raise ValueError("当前任务仍在收尾，暂时无法回退重写，请稍后再试。")

    def _build_stage_rollback_snapshot(
        self,
        snapshot: dict[str, Any],
        stage_key: str,
        *,
        start_episode: int | None = None,
    ) -> dict[str, Any]:
        """构造阶段回退后的新快照，只保留当前阶段之前仍然可信的缓存。"""
        effective_start_episode = (
            int(start_episode)
            if _safe_int(start_episode, 0) > 0
            else self._interrupted_batch_start_episode(snapshot)
            if stage_key in {"hooks", "dialogues", "script"}
            else None
        )
        rollback = copy.deepcopy(snapshot)
        rollback["artifacts"] = self._rolled_back_artifacts(snapshot, stage_key)
        rollback["debug_state"] = self._rolled_back_debug_state(
            snapshot,
            stage_key,
            start_episode=effective_start_episode,
        )
        rollback["artifacts"].update(
            _partial_script_artifacts_from_variables(
                total_episodes=_safe_int(rollback.get("total_episodes"), 0),
                variables=(rollback.get("debug_state") or {}).get("variables"),
            )
        )
        rollback["prompt_fixes"] = []
        rollback["current_node_id"] = None
        rollback["current_node_name"] = None
        rollback["current_batch"] = (
            f"{effective_start_episode}-{_batch_end_episode(int(snapshot.get('total_episodes') or 0), effective_start_episode)}"
            if stage_key in {"hooks", "dialogues", "script"} and effective_start_episode
            else None
        )
        rollback["generated_episodes"] = (
            max(0, int(effective_start_episode or 0) - 1)
            if stage_key in {"hooks", "dialogues", "script"} and effective_start_episode
            else 0
        )
        rollback["current_stage"] = stage_key
        rollback["current_stage_label"] = ROLLBACK_STAGE_LABELS.get(stage_key, stage_key)
        rollback["progress_percent"] = self._rollback_progress_percent(rollback)
        rollback["message"] = f"已回退到“{ROLLBACK_STAGE_LABELS.get(stage_key, stage_key)}”，等待重新生成。"
        rollback["error"] = None
        rollback["finished_at"] = None
        rollback["cache_retained"] = True
        rollback["awaiting_user_confirmation"] = False
        rollback["completion_confirmed"] = False
        rollback["rollback_start_episode"] = effective_start_episode
        return rollback

    def _rolled_back_artifacts(
        self,
        snapshot: dict[str, Any],
        stage_key: str,
    ) -> dict[str, Any]:
        artifacts = copy.deepcopy(snapshot.get("artifacts") or {})
        for key in ROLLBACK_ARTIFACT_CLEAR_RULES.get(stage_key, ()):
            artifacts.pop(key, None)
        artifacts.pop(STORY_TEASER_ARTIFACT, None)
        artifacts.pop(STORY_TEASER_SOURCE_ARTIFACT, None)
        artifacts.pop(EPISODE_PLAN_DISPLAY_ARTIFACT, None)
        artifacts.pop(EPISODE_PLAN_DISPLAY_SOURCE_HASH_ARTIFACT, None)
        return artifacts

    def _rolled_back_debug_state(
        self,
        snapshot: dict[str, Any],
        stage_key: str,
        *,
        start_episode: int | None = None,
    ) -> dict[str, Any]:
        debug_state = copy.deepcopy(snapshot.get("debug_state") or {})
        variables = debug_state.get("variables")
        if not isinstance(variables, dict):
            variables = {}

        # 回退不是简单清空全部缓存，而是“只删除当前阶段之后不再可信的部分”。
        # 这样前序稳定产物还能继续复用，减少重跑成本。
        clear_keys = set(ROLLBACK_DEBUG_CLEAR_RULES.get(stage_key, ()))
        for key in list(clear_keys):
            clear_keys.update(DEBUG_VARIABLE_MIRRORS.get(key, ()))
        for key in clear_keys:
            variables.pop(key, None)

        if stage_key in {"dialogues", "script", "final"}:
            variables[LOCAL_REWRITE_FROM_STAGE] = (
                "dialogue" if stage_key == "dialogues"
                else "script" if stage_key == "script"
                else "final"
            )

        if stage_key in {"hooks", "dialogues"} and start_episode:
            self._apply_batched_stage_rollback(
                snapshot,
                variables,
                stage_key=stage_key,
                start_episode=start_episode,
            )
        if stage_key == "script" and start_episode:
            self._apply_script_partial_rollback(
                snapshot,
                variables,
                start_episode=start_episode,
            )

        debug_state["variables"] = variables
        debug_state["node_outputs"] = {}
        debug_state["halted_message"] = None
        debug_state["final_output_text"] = ""
        return debug_state

    def _apply_batched_stage_rollback(
        self,
        snapshot: dict[str, Any],
        variables: dict[str, Any],
        *,
        stage_key: str,
        start_episode: int,
    ) -> None:
        """按批次回退 hooks/dialogues，保留前序结果，只清掉需要重做的窗口。"""
        debug_state = snapshot.get("debug_state") or {}
        original_variables = debug_state.get("variables") if isinstance(debug_state, dict) else {}
        if not isinstance(original_variables, dict):
            original_variables = {}

        total_episodes = int(snapshot.get("total_episodes") or 0)
        batch_size = max(1, int(settings.batch_size or 5))
        batch_end_episode = _batch_end_episode(total_episodes, start_episode)
        completed_batches = len(
            [batch for batch in iter_episode_batches(total_episodes, batch_size=batch_size) if batch.start_episode < start_episode]
        )

        original_hooks = copy.deepcopy(original_variables.get(ALL_HOOKS) or {})
        original_dialogues = copy.deepcopy(original_variables.get(ALL_DIALOGUES) or {})
        summary_by_batch = _normalize_batch_text_map(original_variables.get(LOCAL_SUMMARY_BY_BATCH))
        appearance_memory_by_batch = _normalize_batch_object_map(
            original_variables.get(LOCAL_APPEARANCE_MEMORY_BY_BATCH)
        )

        if stage_key == "hooks":
            preserved_hooks = _slice_episode_object_before(original_hooks, start_episode)
            if preserved_hooks:
                variables[ALL_HOOKS] = preserved_hooks
            else:
                variables.pop(ALL_HOOKS, None)
        elif stage_key == "dialogues":
            preserved_hooks = copy.deepcopy(original_hooks)
            if preserved_hooks:
                variables[ALL_HOOKS] = preserved_hooks
            else:
                variables.pop(ALL_HOOKS, None)
            preserved_dialogues = _slice_episode_object_before(original_dialogues, start_episode)
            if preserved_dialogues:
                variables[ALL_DIALOGUES] = preserved_dialogues
            else:
                variables.pop(ALL_DIALOGUES, None)

        previous_batch_candidates = [
            episode
            for episode in sorted(summary_by_batch)
            if episode + batch_size - 1 < start_episode
        ]
        previous_batch_start = previous_batch_candidates[-1] if previous_batch_candidates else None
        preserved_summary_batches = {
            episode: text for episode, text in summary_by_batch.items() if episode < start_episode
        }
        preserved_appearance_batches = {
            episode: value for episode, value in appearance_memory_by_batch.items() if episode < start_episode
        }

        if previous_batch_start and preserved_summary_batches.get(previous_batch_start):
            variables[LAST_SUMMARY] = preserved_summary_batches[previous_batch_start]
        else:
            variables.pop(LAST_SUMMARY, None)

        preserved_appearance_memory = (
            copy.deepcopy(preserved_appearance_batches.get(previous_batch_start))
            if previous_batch_start in preserved_appearance_batches
            else {}
        )
        if preserved_appearance_memory:
            variables[APPEARANCE_CONTINUITY_MEMORY] = preserved_appearance_memory
        else:
            variables.pop(APPEARANCE_CONTINUITY_MEMORY, None)

        variables[LOCAL_SUMMARY_BY_BATCH] = _string_keyed_batch_map(preserved_summary_batches)
        variables[LOCAL_APPEARANCE_MEMORY_BY_BATCH] = _string_keyed_batch_map(preserved_appearance_batches)
        variables[LOCAL_COMPLETED_BATCHES] = completed_batches
        variables[LOCAL_CURRENT_BATCH_INDEX] = completed_batches
        variables[LOCAL_CURRENT_BATCH_STAGE] = "hook" if stage_key == "hooks" else "dialogue"
        variables[BATCH_START_EPISODE] = int(start_episode)
        variables.pop(BATCH_HOOKS, None)
        variables.pop(BATCH_DIALOGUES, None)
        variables.pop(BATCH_SCRIPT, None)
        variables.pop(LOCAL_HOOK_CHECKPOINT_START, None)
        variables.pop(LOCAL_DIALOGUE_CHECKPOINT_START, None)
        variables.pop(LOCAL_SCRIPT_CHECKPOINT_START, None)

    def _apply_script_partial_rollback(
        self,
        snapshot: dict[str, Any],
        variables: dict[str, Any],
        *,
        start_episode: int,
    ) -> None:
        """按正文缓存切掉 start_episode 之后的内容，确保 script 从真实断点续写。"""
        debug_state = snapshot.get("debug_state") or {}
        original_variables = debug_state.get("variables") if isinstance(debug_state, dict) else {}
        if not isinstance(original_variables, dict):
            original_variables = {}

        script_batches = _normalize_batch_text_map(original_variables.get(LOCAL_SCRIPT_BATCHES))
        script_episodes = _normalize_episode_script_map(original_variables.get(LOCAL_SCRIPT_EPISODES))
        summary_by_batch = _normalize_batch_text_map(original_variables.get(LOCAL_SUMMARY_BY_BATCH))
        appearance_memory_by_batch = _normalize_batch_object_map(
            original_variables.get(LOCAL_APPEARANCE_MEMORY_BY_BATCH)
        )

        preserved_script_episodes = {
            episode: text for episode, text in script_episodes.items() if episode < start_episode
        }
        batch_size = max(1, int(settings.batch_size or 5))
        preserved_script_batches = {
            episode: text
            for episode, text in script_batches.items()
            if (
                episode < start_episode
                and (
                    not preserved_script_episodes
                    or episode + batch_size - 1 < start_episode
                )
            )
        }
        preserved_summary_batches = {
            episode: text for episode, text in summary_by_batch.items() if episode < start_episode
        }
        preserved_appearance_batches = {
            episode: value for episode, value in appearance_memory_by_batch.items() if episode < start_episode
        }

        preserved_starts = sorted(preserved_script_batches)
        preserved_script = (
            _join_script_episode_map(preserved_script_episodes)
            if preserved_script_episodes
            else _join_script_parts(*(preserved_script_batches[episode] for episode in preserved_starts))
        )
        previous_batch_candidates = [
            episode
            for episode in sorted(summary_by_batch)
            if episode + batch_size - 1 < start_episode
        ]
        previous_batch_start = previous_batch_candidates[-1] if previous_batch_candidates else None

        if preserved_script:
            variables[ALL_SCRIPT] = preserved_script
            variables[LOCAL_COMMITTED_SCRIPT] = preserved_script
        else:
            variables.pop(ALL_SCRIPT, None)
            variables.pop(LOCAL_COMMITTED_SCRIPT, None)

        if previous_batch_start and preserved_summary_batches.get(previous_batch_start):
            variables[LAST_SUMMARY] = preserved_summary_batches[previous_batch_start]
        else:
            variables.pop(LAST_SUMMARY, None)

        preserved_appearance_memory = (
            copy.deepcopy(preserved_appearance_batches.get(previous_batch_start))
            if previous_batch_start in preserved_appearance_batches
            else {}
        )
        if preserved_appearance_memory:
            variables[APPEARANCE_CONTINUITY_MEMORY] = preserved_appearance_memory
        else:
            variables.pop(APPEARANCE_CONTINUITY_MEMORY, None)

        variables[LOCAL_SCRIPT_BATCHES] = _string_keyed_batch_map(preserved_script_batches)
        variables[LOCAL_SCRIPT_EPISODES] = _string_keyed_batch_map(preserved_script_episodes)
        variables[LOCAL_SUMMARY_BY_BATCH] = _string_keyed_batch_map(preserved_summary_batches)
        variables[LOCAL_APPEARANCE_MEMORY_BY_BATCH] = _string_keyed_batch_map(preserved_appearance_batches)
        total_episodes = int(snapshot.get("total_episodes") or 0)
        completed_batches = len(
            [
                batch
                for batch in iter_episode_batches(total_episodes, batch_size=batch_size)
                if batch.start_episode < start_episode
            ]
        )
        variables[LOCAL_COMPLETED_BATCHES] = completed_batches
        variables[LOCAL_CURRENT_BATCH_INDEX] = completed_batches
        variables[LOCAL_CURRENT_BATCH_STAGE] = "script"
        variables[BATCH_START_EPISODE] = int(start_episode)
        variables.pop(BATCH_SCRIPT, None)
        variables.pop(LOCAL_HOOK_CHECKPOINT_START, None)
        variables.pop(LOCAL_DIALOGUE_CHECKPOINT_START, None)
        variables.pop(LOCAL_SCRIPT_CHECKPOINT_START, None)

    def _rollback_progress_percent(self, snapshot: dict[str, Any]) -> int:
        return self._snapshot_progress_metrics(snapshot)["progress_percent"]

    def _run_task(self, record: TaskRecord) -> None:
        self._update_snapshot(record, status="running", message="开始执行工作流。")
        self._append_log(
            record,
            title="任务启动",
            message="开始执行工作流。",
        )
        runtime: WorkflowRuntime | None = None
        try:
            from .fastgpt_client import FastGPTClient

            workflow_input = WorkflowInput.from_dict(record.input_payload)
            spec = None if use_fastgpt_backend() else WorkflowSpec(record.workflow_spec_path)
            runtime = WorkflowRuntime(manager=self, record=record, spec=spec)
            script_format_mode = str(record.input_payload.get("script_format_mode") or "").strip().lower()
            if script_format_mode:
                logger.info(
                    "任务 %s 启用 script_format_mode=%s；正文编写/修订将优先使用对应的专用 FastGPT API key。",
                    record.task_id,
                    script_format_mode,
                )
            runner = FastGPTClient(script_api_profile=script_format_mode)

            state = run_configured_workflow(
                workflow_input,
                workflow_spec_path=record.workflow_spec_path,
                runtime=runtime,
                model_option=record.model_option,
                client=runner,
                resume_snapshot=record.resume_snapshot,
            )

            if state.halted_message:
                runtime.sync_from_state(state)
                self._update_snapshot(
                    record,
                    status="failed",
                    current_stage="validation",
                    current_stage_label=STAGE_LABELS["validation"],
                    message=state.halted_message,
                    error=state.halted_message,
                    progress_percent=0,
                )
                return

            runtime.set_stage("finalize", "正在整理最终输出。", progress_percent=100)
            runtime.sync_from_state(state)
            self._update_snapshot(
                record,
                status="completed",
                current_stage="finished",
                current_stage_label=STAGE_LABELS["finished"],
                message=COMPLETION_PENDING_MESSAGE,
                finished_at=now_iso(),
                progress_percent=100,
                generated_episodes=record.snapshot.get("total_episodes", 0),
                prompt_fixes=state.prompt_fixes,
                completion_confirmed=False,
                awaiting_user_confirmation=True,
                cache_retained=True,
            )
        except TaskTerminated as exc:
            if runtime is not None:
                self._append_log(
                    record,
                    title="任务已终止",
                    message="已保留终止前的阶段、进度和中间产物。",
                )
            self._update_snapshot(
                record,
                status="terminated",
                message=TERMINATED_PUBLIC_MESSAGE,
                error=str(exc),
                finished_at=now_iso(),
            )

        except Exception as exc:
            logger.exception("任务执行失败: %s", record.task_id)

            # 失败时先退回最近一次稳定 checkpoint，再对外标记 failed。
            # 这样 retry/继续生成看到的是“上一个成功步骤”的缓存，而不是半写入状态。
            self._restore_from_resume_checkpoint(record)

            self._update_snapshot(
                record,
                status="failed",
                message=FAILED_PUBLIC_MESSAGE,
                error=str(exc),
                finished_at=now_iso(),
            )

            self._append_log(
                record,
                title="任务失败",
                message=f"已回退到上一个成功步骤并保留可继续生成的缓存。错误：{type(exc).__name__}: {exc}",
                level="error",
            )

    def _get_task_record_for_user(self, task_id: str, user_id: int | None) -> TaskRecord:
        record = self._tasks.get(task_id)
        if not record:
            raise ValueError("任务不存在")
        if user_id is not None and int(record.user_id) != int(user_id):
            raise ValueError("您没有权限操作该任务")
        return record

    def pause_task(self, task_id: str, user_id: int | None = None) -> dict[str, Any]:
        record = self._get_task_record_for_user(task_id, user_id)
        snapshot = record.clone_snapshot()
        status = snapshot.get("status")
        if status in {"paused", "pausing"}:
            return self._public_snapshot(snapshot)
        if status not in {"pending", "running"}:
            raise ValueError("只有进行中的任务才能暂停")
        record.control.request_pause()
        self._append_log(
            record,
            title="控制动作：暂停请求",
            message="暂停指令已发出，当前节点完成后会暂停。",
        )
        self._update_snapshot(
            record,
            status="pausing",
            message="暂停指令已发出，当前节点完成后会暂停。",
        )
        return self._public_snapshot(record.clone_snapshot())

    def resume_task(self, task_id: str, user_id: int | None = None) -> dict[str, Any]:
        record = self._get_task_record_for_user(task_id, user_id)
        snapshot = record.clone_snapshot()
        status = snapshot.get("status")
        if status == "running" and not record.control.is_pause_requested():
            return self._public_snapshot(snapshot)
        if status not in {"paused", "pausing", "running"}:
            raise ValueError("只有已暂停或正在暂停的任务才能继续")
        record.control.request_resume()
        self._append_log(
            record,
            title="控制动作：继续请求",
            message="继续指令已发出，任务恢复执行。",
        )
        self._update_snapshot(
            record,
            status="running",
            message="继续指令已发出，任务恢复执行。",
        )
        return self._public_snapshot(record.clone_snapshot())

    def retry_task(self, task_id: str, user_id: int | None = None) -> dict[str, Any]:
        snapshot = self.get_task_snapshot(task_id, user_id=user_id, public_view=False)
        if not snapshot:
            raise ValueError("任务不存在")
        status = snapshot.get("status")
        if status in PROJECT_RUNNING_STATUSES:
            raise ValueError("任务仍在执行中，不能重复重试")
        if status == "completed":
            raise ValueError("任务已完成，无需继续生成")

        project_id = int(snapshot.get("project_id") or 0)
        if project_id <= 0:
            raise ValueError("项目记录缺少 project_id，无法继续")

        old_task_id = str(snapshot.get("task_id") or task_id)
        new_task_id = uuid.uuid4().hex[:12]
        resume_base = snapshot.get("_resume_checkpoint")
        if not isinstance(resume_base, dict):
            resume_base = snapshot
        resume_snapshot = copy.deepcopy(resume_base)
        model_option = settings.resolve_model_selection(
            (snapshot.get("model_option") or {}).get("id")
        )
        new_snapshot = copy.deepcopy(resume_base)
        new_snapshot.update(
            {
                "task_id": new_task_id,
                "status": "pending",
                "message": "已回退到上一个成功步骤，等待继续生成。",
                "error": None,
                "retry_of_task_id": old_task_id,
                "updated_at": now_iso(),
                "finished_at": None,
                "completion_confirmed": False,
                "awaiting_user_confirmation": False,
                "cache_retained": True,
                "wait_elapsed_ms": 0,
                "wait_started_at": now_iso(),
            }
        )

        record = TaskRecord(
            user_id=int(snapshot.get("user_id") or user_id or 0),
            project_id=project_id,
            task_id=new_task_id,
            workflow_spec_path=str(snapshot.get("workflow_spec_path", "")),
            input_payload=snapshot.get("input_payload", {}),
            model_option=model_option,
            snapshot=new_snapshot,
            resume_snapshot=resume_snapshot,
        )
        with self._lock:
            self._tasks.pop(old_task_id, None)
            self._tasks[new_task_id] = record
            self._projects[project_id] = record
            self._remember_latest_project(record.user_id, project_id)
        self._append_log(
            record,
            title="控制动作：继续失败任务",
            message="将从上一个成功步骤继续执行；已完成步骤会跳过，失败步骤会重新尝试。",
        )
        self._save_resume_checkpoint(record)
        self._persist_snapshot(record)

        thread = threading.Thread(
            target=self._run_task,
            args=(record,),
            daemon=True,
            name=f"workflow-task-{new_task_id}",
        )
        record.thread = thread
        thread.start()
        return self._public_snapshot(record.clone_snapshot())

    def restart_project(
        self,
        project_id: int,
        *,
        user_id: int,
        input_payload: dict[str, Any],
        workflow_spec_path: str,
        model_selection_id: str | None,
    ) -> dict[str, Any]:
        snapshot = self.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot:
            raise ValueError("项目不存在或无权操作")

        status = str(snapshot.get("status") or "")
        if status in PROJECT_RUNNING_STATUSES:
            raise ValueError("任务仍在执行中，不能重新开始")

        old_task_id = str(snapshot.get("task_id") or "").strip()
        new_task_id = uuid.uuid4().hex[:12]
        model_option = settings.resolve_model_selection(model_selection_id)

        new_snapshot = {
            "user_id": int(user_id),
            "project_id": int(project_id),
            "task_id": new_task_id,
            "status": "pending",
            "title": str(input_payload.get("title", "")).strip() or str(snapshot.get("title") or "").strip(),
            "message": "正在同一资产下重新开始生成。",
            "created_at": snapshot.get("created_at") or now_iso(),
            "updated_at": now_iso(),
            "workflow_spec_path": workflow_spec_path,
            "visibility": str(snapshot.get("visibility") or "private"),
            "model_option": {
                "id": model_option.id,
                "label": self._model_alias(model_option.provider),
                "provider": model_option.provider,
                "model": model_option.model,
            }
            if model_option
            else None,
            "input_payload": copy.deepcopy(input_payload),
            "artifacts": {},
            "logs": [],
            "prompt_fixes": [],
            "progress_percent": 0,
            "generated_episodes": 0,
            "total_episodes": int(input_payload.get("total_episodes", 0) or 0),
            "current_stage": "validation",
            "current_stage_label": STAGE_LABELS["validation"],
            "current_node_id": None,
            "current_node_name": None,
            "current_batch": None,
            "completion_confirmed": False,
            "awaiting_user_confirmation": False,
            "cache_retained": True,
            "debug_state": {},
            "restart_of_task_id": old_task_id or None,
            "finished_at": None,
            "error": None,
            "wait_elapsed_ms": 0,
            "wait_started_at": now_iso(),
        }

        record = TaskRecord(
            user_id=int(user_id),
            project_id=int(project_id),
            task_id=new_task_id,
            workflow_spec_path=workflow_spec_path,
            input_payload=copy.deepcopy(input_payload),
            model_option=model_option,
            snapshot=new_snapshot,
            resume_snapshot=None,
        )

        with self._lock:
            if old_task_id:
                self._tasks.pop(old_task_id, None)
            self._tasks[new_task_id] = record
            self._projects[int(project_id)] = record
            self._remember_latest_project(int(user_id), int(project_id))

        self._save_resume_checkpoint(record)
        self._persist_snapshot(record)

        thread = threading.Thread(
            target=self._run_task,
            args=(record,),
            daemon=True,
            name=f"workflow-task-{new_task_id}",
        )
        record.thread = thread
        thread.start()
        return self._public_snapshot(record.clone_snapshot())

    def terminate_task(self, task_id: str, user_id: int | None = None) -> dict[str, Any]:
        record = self._get_task_record_for_user(task_id, user_id)
        snapshot = record.clone_snapshot()
        if snapshot.get("status") in {"completed", "terminated"}:
            return self._public_snapshot(snapshot)
        if snapshot.get("status") == "failed":
            self._append_log(
                record,
                title="控制动作：终止失败任务",
                message="失败任务已标记为终止，失败前的阶段和中间产物已保留。",
            )
            self._update_snapshot(
                record,
                status="terminated",
                message="任务已终止，失败前的阶段和中间产物已保留，可直接重新开始。",
                finished_at=now_iso(),
            )
            return self._public_snapshot(record.clone_snapshot())
        record.control.request_terminate()
        self._append_log(
            record,
            title="控制动作：终止请求",
            message="终止指令已发出，当前节点结束后会停止。",
        )
        self._update_snapshot(
            record,
            status="terminated",
            message=TERMINATED_PUBLIC_MESSAGE,
            finished_at=now_iso(),
        )
        return self._public_snapshot(record.clone_snapshot())

    def delete_task(self, task_id: str, user_id: int | None = None) -> None:
        snapshot = self.get_task_snapshot(task_id, user_id=user_id, public_view=False)
        if not snapshot:
            raise ValueError("任务不存在")
        project_id = int(snapshot.get("project_id") or 0)
        if project_id <= 0:
            raise ValueError("任务缺少关联资产，无法删除")
        self.clear_project(project_id, user_id=user_id)

    def clear_project(self, project_id: int, user_id: int | None = None) -> None:
        record = self._projects.get(project_id)
        owner_user_id: int | None = None
        if record:
            if user_id is not None and int(record.user_id) != int(user_id):
                raise ValueError("您没有权限清空该项目")
            snapshot = record.clone_snapshot()
            owner_user_id = int(snapshot.get("user_id") or record.user_id or 0)
            record.control.request_terminate()
            with record.lock:
                record.snapshot["_deleted"] = True
            self._tasks.pop(record.task_id, None)
            self._projects.pop(project_id, None)

        path = self._project_path(project_id)
        if path.exists():
            if user_id is not None:
                try:
                    snapshot = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    snapshot = {}
                if not self._snapshot_belongs_to_user(snapshot, user_id):
                    raise ValueError("您没有权限清空该项目")
                owner_user_id = int(snapshot.get("user_id") or owner_user_id or 0)
            path.unlink()
        else:
            archived_path = resolve_project_snapshot_path(
                project_id,
                projects_dir=self.projects_dir,
                base_root=self.runtime_root,
                manifest_path=self.runtime_manifest_path,
                archive_dir=self.runtime_archive_dir,
            )
            if archived_path and archived_path.exists():
                if user_id is not None:
                    try:
                        snapshot = json.loads(archived_path.read_text(encoding="utf-8"))
                    except Exception:
                        snapshot = {}
                    if not self._snapshot_belongs_to_user(snapshot, user_id):
                        raise ValueError("您没有权限清空该项目")
                    owner_user_id = int(snapshot.get("user_id") or owner_user_id or 0)
                archived_path.unlink()

        update_runtime_manifest(
            removals=(self._runtime_relpath(self._project_path(project_id)),),
            manifest_path=self.runtime_manifest_path,
            archive_dir=self.runtime_archive_dir,
            repo_root=self.runtime_root,
        )

        latest_by_user = dict(self._index.get("latest_project_by_user", {}))
        if owner_user_id is not None and latest_by_user.get(str(owner_user_id)) == project_id:
            latest_by_user.pop(str(owner_user_id), None)
            self._index["latest_project_by_user"] = latest_by_user
        if self._index.get("latest_project_id") == project_id:
            self._index["latest_project_id"] = None
        self._save_index()

