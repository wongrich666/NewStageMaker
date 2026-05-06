
from __future__ import annotations

"""Runtime task state objects extracted from the TaskManager facade."""

from . import task_manager_common as _task_manager_common
from .task_manager_common import *
globals().update(
    {name: getattr(_task_manager_common, name) for name in dir(_task_manager_common) if name.startswith("_")}
)

class TaskTerminated(RuntimeError):
    pass


@dataclass(slots=True)
class TaskControl:
    pause_requested: bool = False
    terminate_requested: bool = False
    condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock())
    )

    def request_pause(self) -> None:
        with self.condition:
            self.pause_requested = True
            self.condition.notify_all()

    def request_resume(self) -> None:
        with self.condition:
            self.pause_requested = False
            self.condition.notify_all()

    def request_terminate(self) -> None:
        with self.condition:
            self.terminate_requested = True
            self.pause_requested = False
            self.condition.notify_all()

    def is_pause_requested(self) -> bool:
        with self.condition:
            return self.pause_requested

    def checkpoint(self, *, on_paused: Callable[[], None] | None = None) -> None:
        with self.condition:
            while self.pause_requested and not self.terminate_requested:
                if on_paused is not None:
                    on_paused()
                self.condition.wait(timeout=0.5)
            if self.terminate_requested:
                raise TaskTerminated("任务已终止")


@dataclass(slots=True)
class TaskRecord:
    user_id: int
    project_id: int
    task_id: str
    workflow_spec_path: str
    input_payload: dict[str, Any]
    model_option: ModelOption | None
    snapshot: dict[str, Any]
    control: TaskControl = field(default_factory=TaskControl)
    thread: threading.Thread | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)
    resume_snapshot: dict[str, Any] | None = None

    def clone_snapshot(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self.snapshot)


class WorkflowRuntime:
    def __init__(
        self,
        *,
        manager: "TaskManager",
        record: TaskRecord,
        spec: WorkflowSpec | None,
    ) -> None:
        self.manager = manager
        self.record = record
        self.spec = spec

    def checkpoint(self) -> None:
        def _mark_paused() -> None:
            snapshot = self.record.clone_snapshot()
            if snapshot.get("status") != "paused":
                self.manager._update_snapshot(
                    self.record,
                    status="paused",
                    message="已暂停，等待继续。",
                )

        if self.record.control.is_pause_requested():
            _mark_paused()
        self.record.control.checkpoint(on_paused=_mark_paused)
        if self.record.clone_snapshot().get("status") in {"paused", "pausing"}:
            self.manager._update_snapshot(
                self.record,
                status="running",
                message="已继续执行。",
            )

    def set_stage(
        self,
        stage_key: str,
        message: str,
        *,
        batch_label: str | None = None,
        progress_percent: int | None = None,
        generated_episodes: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "current_stage": stage_key,
            "current_stage_label": STAGE_LABELS.get(stage_key, stage_key),
            "message": message,
            "current_batch": str(batch_label).strip() if batch_label else None,
        }
        if progress_percent is not None:
            payload["progress_percent"] = max(0, min(100, int(progress_percent)))
        if generated_episodes is not None:
            payload["generated_episodes"] = max(0, int(generated_episodes))
        self.manager._update_snapshot(self.record, **payload)

    def before_node(self, node_id: str, state: WorkflowState) -> None:
        self.checkpoint()
        node_name = self.spec.get_node_name(node_id) if self.spec else node_id
        self.manager._append_log(
            self.record,
            title=f"开始节点：{node_name}",
            message=f"{node_id} 正在执行。",
            node_id=node_id,
        )
        self.manager._update_snapshot(
            self.record,
            status="running",
            current_node_id=node_id,
            current_node_name=node_name,
            message=f"正在执行：{node_name}",
        )
        self.sync_from_state(state)

    def after_node(self, node_id: str, state: WorkflowState, output_text: str) -> None:
        node_name = self.spec.get_node_name(node_id) if self.spec else node_id
        preview = str(output_text or "").strip().replace("\n", " ")[:180]
        self.manager._append_log(
            self.record,
            title=f"完成节点：{node_name}",
            message=preview or "节点已完成。",
            node_id=node_id,
        )
        self.sync_from_state(state)
        self.checkpoint()

    def fastgpt_stage_started(
        self,
        stage_label: str,
        *,
        batch_label: str | None = None,
        attempt: int = 1,
    ) -> None:
        self.checkpoint()
        batch_text = f" {batch_label} 集" if batch_label else ""
        self.manager._append_log(
            self.record,
            title=f"{stage_label}{batch_text}",
            message=f"第 {attempt} 次尝试",
            node_id=f"fastgpt:{stage_label}",
        )

    def fastgpt_stage_finished(
        self,
        stage_label: str,
        *,
        batch_label: str | None = None,
        output: dict[str, Any],
    ) -> None:
        batch_text = f" {batch_label} 集" if batch_label else ""
        self.manager._append_log(
            self.record,
            title=f"{stage_label}{batch_text} 已完成",
            message=_summarize_fastgpt_output(output),
            node_id=f"fastgpt:{stage_label}",
        )

    def sync_from_state(self, state: WorkflowState) -> None:
        script_title_content = export_safe_text(state.get_var(TITLE_VAR, "")).strip()
        final_script_text = _resolve_best_script_text(
            total_episodes=_safe_int(getattr(state.user_input, "total_episodes", 0), 0),
            artifacts={},
            variables=state.variables,
            final_output_text=state.final_output_text,
        )
        if not final_script_text:
            final_script_text = clean_user_visible_text(
                state.final_output_text
                or state.get_var(FINAL_SCRIPT, "")
                or state.get_var(SCRIPT_FINAL_VAR, "")
                or ""
            ).strip()
        raw_character_natural_language = str(
            state.get_var(CHARACTER_NATURAL_LANGUAGE_VAR, "") or ""
        ).strip()
        structured_characters = state.get_var(CHARACTER_VAR, "")
        character_natural_language, character_natural_language_issues = _select_character_display_text(
            raw_character_natural_language,
            structured_characters,
        )
        if raw_character_natural_language and character_natural_language_issues:
            _log_warning_once(
                "character_natural_language_rejected",
                character_natural_language_issues,
                _truncate_log_text(raw_character_natural_language, max_chars=240),
            )
        structured_scenes = state.get_var(SCENE_VAR, "")
        framework_natural_language = build_user_visible_section(
            "剧本框架",
            {
                "故事梗概": state.get_var(STORY_OUTLINE_VAR, ""),
                "人物小传": state.get_var(CHARACTER_BIOS_VAR, ""),
                "核心场景": state.get_var(CORE_SCENE_INPUT_VAR, ""),
                "分集计划": state.get_var(EPISODE_PLAN_VAR, ""),
            },
            state.get_var(FRAMEWORK_NATURAL_LANGUAGE, ""),
        )
        worldview_natural_language = build_user_visible_section(
            "世界观设定",
            state.get_var(WORLDVIEW_VAR, ""),
            state.get_var(WORLDVIEW_NATURAL_LANGUAGE, ""),
        )
        appearance_natural_language = build_user_visible_section(
            "人物服饰说明",
            state.get_var(APPEARANCE_MAPPING, ""),
            state.get_var(APPEARANCE_NATURAL_LANGUAGE_VAR, ""),
        )
        scene_natural_language = build_user_visible_section(
            "核心场景",
            structured_scenes,
            state.get_var(SCENE_NATURAL_LANGUAGE_VAR, ""),
        )
        partial_script_artifacts = _partial_script_artifacts_from_variables(
            total_episodes=_safe_int(getattr(state.user_input, "total_episodes", 0), 0),
            variables=state.variables,
        )
        artifacts = {
            "script_title_content": script_title_content,
            "framework_natural_language": framework_natural_language,
            "story_outline": state.get_var(STORY_OUTLINE_VAR, ""),
            "character_bios": state.get_var(CHARACTER_BIOS_VAR, ""),
            "episode_plan": state.get_var(EPISODE_PLAN_VAR, ""),
            "normalized_episode_plan": state.get_var(NORMALIZED_EPISODE_PLAN, ""),
            "worldview": state.get_var(WORLDVIEW_VAR, ""),
            "worldview_natural_language": worldview_natural_language,
            "characters": structured_characters,
            "character_natural_language": character_natural_language,
            "character_summary": character_natural_language,
            "scene_json": structured_scenes,
            "scene_natural_language": scene_natural_language,
            "core_scene_input": state.get_var(
                SCENE_NATURAL_LANGUAGE_VAR,
                state.get_var(CORE_SCENE_INPUT_VAR, ""),
            ),
            "core_scene_summary": scene_natural_language,
            "character_appearance_requirements": state.get_var(CHARACTER_APPEARANCE_REQUIREMENTS, ""),
            "character_alias_naming_rules": state.get_var(CHARACTER_ALIAS_NAMING_RULES, ""),
            "outfit_switch_rules": state.get_var(OUTFIT_SWITCH_RULES, ""),
            "appearance_mapping": state.get_var(APPEARANCE_MAPPING, ""),
            APPEARANCE_NATURAL_LANGUAGE_ARTIFACT: appearance_natural_language,
            "character_registry": state.get_var(CHARACTER_REGISTRY, ""),
            "character_alias_registry": state.get_var(CHARACTER_ALIAS_REGISTRY, ""),
            "episode_alias_plan": state.get_var(EPISODE_ALIAS_PLAN, ""),
            "appearance_continuity_memory": state.get_var(APPEARANCE_CONTINUITY_MEMORY, ""),
            "hook_plan": state.get_var(HOOK_FINAL_VAR, ""),
            "dialogue_plan": state.get_var(DIALOGUE_FINAL_VAR, ""),
            "script_batch": state.get_var(SCRIPT_CURRENT_VAR, ""),
            "final_script": final_script_text,
            "continuity_memory": state.get_var(MEMORY_VAR, ""),
            "halted_message": state.halted_message or "",
            "final_output_text": final_script_text,
        }
        artifacts.update(partial_script_artifacts)
        # artifacts 面向前端展示与导出，debug_state 面向恢复/回退。
        # 两份都要同步：前者保证用户能立刻看到正式成品，后者保证失败后能从真实执行状态继续。
        self.manager._update_snapshot(
            self.record,
            title=script_title_content or self.record.snapshot.get("title") or "未命名剧本",
            artifacts=artifacts,
            debug_state=state.as_debug_dict(),
            prompt_fixes=state.prompt_fixes,
        )
        self.manager._save_resume_checkpoint(self.record)
