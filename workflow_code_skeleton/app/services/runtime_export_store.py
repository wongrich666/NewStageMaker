from __future__ import annotations

"""Extracted TaskManager mixin for RuntimeExportStoreMixin."""

from . import task_manager_common as _task_manager_common
from .task_manager_common import *
globals().update(
    {name: getattr(_task_manager_common, name) for name in dir(_task_manager_common) if name.startswith("_")}
)
from .task_state import TaskRecord
from .fastgpt_contracts import (
    STAGE_CHARACTERS,
    STAGE_CHARACTERS_NATURALIZE,
)
from .unstructured_naturalize import (
    build_character_unstructured_source,
    build_unstructured_stage_variables,
    extract_unstructured_stage_output_text,
)
class RuntimeExportStoreMixin:
    def _best_final_script_text(self, snapshot: dict[str, Any]) -> str:
        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        if str(snapshot.get("asset_kind") or "").strip() == AUXILIARY_TOOL_ASSET_KIND:
            return clean_multiline_user_visible_text(
                artifacts.get("final_output_text")
                or artifacts.get("final_script")
                or ""
            )
        debug_state = snapshot.get("debug_state") if isinstance(snapshot.get("debug_state"), dict) else {}
        variables = debug_state.get("variables") if isinstance(debug_state.get("variables"), dict) else {}
        input_payload = snapshot.get("input_payload") if isinstance(snapshot.get("input_payload"), dict) else {}
        total_episodes = _safe_int(
            snapshot.get("total_episodes")
            or input_payload.get("total_episodes")
            or variables.get(TOTAL_EPISODES),
            0,
        )
        return _resolve_best_script_text(
            total_episodes=total_episodes,
            artifacts=artifacts,
            variables=variables,
            final_output_text=debug_state.get("final_output_text"),
        )

    def _snapshot_artifacts_dict(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        artifacts = snapshot.get("artifacts")
        return artifacts if isinstance(artifacts, dict) else {}

    def _snapshot_debug_variables(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        debug_state = snapshot.get("debug_state")
        if not isinstance(debug_state, dict):
            return {}
        variables = debug_state.get("variables")
        return variables if isinstance(variables, dict) else {}

    def _snapshot_input_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        input_payload = snapshot.get("input_payload")
        return input_payload if isinstance(input_payload, dict) else {}

    def _snapshot_export_value(
        self,
        snapshot: dict[str, Any],
        *,
        artifact_keys: tuple[str, ...] = (),
        variable_keys: tuple[str, ...] = (),
        input_keys: tuple[str, ...] = (),
        require_meaningful: bool = False,
    ) -> Any:
        artifacts = self._snapshot_artifacts_dict(snapshot)
        for key in artifact_keys:
            value = artifacts.get(key)
            if value not in (None, "", {}, []):
                if require_meaningful and not has_meaningful_content(value):
                    continue
                return value
        variables = self._snapshot_debug_variables(snapshot)
        for key in variable_keys:
            value = variables.get(key)
            if value not in (None, "", {}, []):
                if require_meaningful and not has_meaningful_content(value):
                    continue
                return value
        input_payload = self._snapshot_input_payload(snapshot)
        for key in input_keys:
            value = input_payload.get(key)
            if value not in (None, "", {}, []):
                if require_meaningful and not has_meaningful_content(value):
                    continue
                return value
        return None

    def _sanitize_export_section_text(
        self,
        value: Any,
        *,
        banned_prefixes: tuple[str, ...] = (),
    ) -> str:
        readable = clean_export_readable_text(value)
        return clean_user_visible_text(readable, banned_prefixes=banned_prefixes)

    def _validated_export_natural_text(
        self,
        value: Any,
        *,
        banned_prefixes: tuple[str, ...] = (),
    ) -> str:
        if is_machine_structured_content(value):
            return ""
        text = _meaningful_stage_output_text(
            self._sanitize_export_section_text(value, banned_prefixes=banned_prefixes)
        )
        if not text:
            return ""
        if _export_text_has_placeholder_leaks(text):
            return ""
        return text

    def _sentence_fragment(self, value: Any) -> str:
        return export_safe_text(value).strip().strip("，。；： ")

    def _snapshot_record_for_update(
        self,
        project_id: int,
        snapshot: dict[str, Any],
    ) -> TaskRecord:
        existing = self._projects.get(project_id)
        if existing is not None:
            return existing
        return TaskRecord(
            user_id=int(snapshot.get("user_id") or 0),
            project_id=project_id,
            task_id=str(snapshot.get("task_id", "")),
            workflow_spec_path=str(snapshot.get("workflow_spec_path", "")),
            input_payload=snapshot.get("input_payload", {}),
            model_option=settings.resolve_model_selection(
                (snapshot.get("model_option") or {}).get("id")
            ),
            snapshot=copy.deepcopy(snapshot),
        )

    def _apply_snapshot_variable_artifact_updates(
        self,
        project_id: int,
        snapshot: dict[str, Any],
        *,
        artifact_updates: dict[str, Any],
        variable_updates: dict[str, Any],
    ) -> None:
        if artifact_updates:
            artifacts = snapshot.setdefault("artifacts", {})
            if isinstance(artifacts, dict):
                artifacts.update(artifact_updates)
        debug_state = snapshot.setdefault("debug_state", {})
        if not isinstance(debug_state, dict):
            debug_state = {}
            snapshot["debug_state"] = debug_state
        debug_variables = debug_state.setdefault("variables", {})
        if not isinstance(debug_variables, dict):
            debug_variables = {}
            debug_state["variables"] = debug_variables
        debug_variables.update(variable_updates)

        record = self._snapshot_record_for_update(project_id, snapshot)
        record_debug_state = copy.deepcopy(
            record.snapshot.get("debug_state") if isinstance(record.snapshot.get("debug_state"), dict) else {}
        )
        if not isinstance(record_debug_state, dict):
            record_debug_state = {}
        record_debug_variables = record_debug_state.setdefault("variables", {})
        if not isinstance(record_debug_variables, dict):
            record_debug_variables = {}
            record_debug_state["variables"] = record_debug_variables
        record_debug_variables.update(variable_updates)
        self._update_snapshot(
            record,
            artifacts=artifact_updates,
            debug_state=record_debug_state,
        )

    def _build_export_character_naturalize_stage_variables(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        debug_variables = self._snapshot_debug_variables(snapshot)
        input_payload = self._snapshot_input_payload(snapshot)
        source_text = build_character_unstructured_source(
            {
                CHARACTERS: self._snapshot_export_value(
                    snapshot,
                    artifact_keys=("characters", "character_bios"),
                    variable_keys=(CHARACTERS, CHARACTER_VAR),
                ),
                USER_CHARACTERS: self._snapshot_export_value(
                    snapshot,
                    variable_keys=(USER_CHARACTERS, CHARACTER_BIOS_VAR),
                    input_keys=("character_bios",),
                ),
                CHARACTER_NATURAL_LANGUAGE_VAR: debug_variables.get(CHARACTER_NATURAL_LANGUAGE_VAR),
                CHARACTER_BIOS_VAR: input_payload.get("character_bios"),
            }
        )
        return build_unstructured_stage_variables(
            source_text,
            stage_name=STAGE_CHARACTERS_NATURALIZE,
            source_stage=STAGE_CHARACTERS,
        )

    def _persist_export_character_natural_language(
        self,
        snapshot: dict[str, Any],
        *,
        project_id: int,
        natural_text: str,
    ) -> str:
        natural = _meaningful_stage_output_text(self._sanitize_export_section_text(natural_text))
        if not natural:
            return ""
        self._apply_snapshot_variable_artifact_updates(
            project_id,
            snapshot,
            artifact_updates={
                "character_natural_language": natural,
                "character_summary": natural,
            },
            variable_updates={CHARACTER_NATURAL_LANGUAGE_VAR: natural},
        )
        return natural

    def _character_structured_fallback_text(self, structured: Any) -> str:
        characters = _character_items_from_value(structured)
        if not characters:
            return ""

        sections: list[str] = []
        for item in characters:
            name = _character_name_from_item(item)
            role = _meaningful_character_fragment(
                item.get("story_role") or item.get("role_type") or item.get("identity")
            )
            personality = _meaningful_character_fragment(
                item.get("personality") or item.get("speech_profile")
            )
            desire = _meaningful_character_fragment(
                item.get("core_desire") or item.get("core_motivation") or item.get("deep_motivation")
            )
            relationship = _meaningful_character_fragment(
                item.get("relationship_to_protagonist")
                or item.get("relationships_with_others")
                or item.get("relationships")
            )
            growth = _meaningful_character_fragment(item.get("growth_arc") or item.get("plot_function"))
            appearance = _meaningful_character_fragment(
                item.get("appearance_anchor")
                or item.get("appearance")
                or item.get("appearance_description")
            )

            fragments: list[str] = []
            if role:
                fragments.append(f"是故事中的{role}")
            if personality:
                fragments.append(f"性格上{personality}")
            if desire:
                fragments.append(f"内在驱动力集中在{desire}")
            if relationship:
                fragments.append(f"与其他角色的关系重点在于{relationship}")
            if growth:
                fragments.append(f"人物成长会落在{growth}")
            if appearance:
                fragments.append(f"视觉辨识点则是{appearance}")

            if not name:
                continue
            if fragments:
                sections.append(f"{name}：" + "，".join(fragments).strip("，") + "。")
            else:
                sections.append(name)

        return "\n".join(section for section in sections if section).strip()

    def _ensure_export_character_natural_language(
        self,
        snapshot: dict[str, Any],
        *,
        project_id: int,
    ) -> str:
        structured = self._snapshot_export_value(
            snapshot,
            artifact_keys=("characters", "character_bios"),
            variable_keys=(CHARACTERS, CHARACTER_VAR),
            input_keys=("character_bios",),
        )
        fallback_text = self._character_structured_fallback_text(structured)
        if not fallback_text:
            fallback_text = self._sanitize_export_section_text(
                self._snapshot_export_value(
                    snapshot,
                    variable_keys=(USER_CHARACTERS, CHARACTER_BIOS_VAR),
                    input_keys=("character_bios",),
                )
            )
        existing = self._snapshot_export_value(
            snapshot,
            artifact_keys=("character_natural_language",),
            variable_keys=(CHARACTER_NATURAL_LANGUAGE_VAR,),
            require_meaningful=True,
        ) or self._snapshot_export_value(
            snapshot,
            artifact_keys=("character_summary",),
            require_meaningful=True,
        )
        preferred, issues = _select_character_display_text(existing, structured)
        existing_text = _meaningful_stage_output_text(self._sanitize_export_section_text(existing))
        if existing_text and not issues:
            logger.info("character_natural_language_export status=reuse_existing project_id=%s", project_id)
            return preferred
        if existing_text and issues:
            logger.warning(
                "character_natural_language_export status=reject_existing project_id=%s issues=%s preview=%s",
                project_id,
                ",".join(issues),
                _truncate_log_text(existing_text, max_chars=240),
            )

        if not has_meaningful_content(structured):
            logger.info("character_natural_language_export status=skip_missing_characters project_id=%s", project_id)
            return ""
        if not use_fastgpt_backend():
            logger.info("character_natural_language_export status=skip_non_fastgpt_backend project_id=%s", project_id)
            return self._persist_export_character_natural_language(
                snapshot,
                project_id=project_id,
                natural_text=fallback_text,
            )

        stage_variables = self._build_export_character_naturalize_stage_variables(snapshot)
        source_text = str(stage_variables.get(UNSTRUCTURED_SOURCE) or "").strip()
        if not source_text:
            logger.warning(
                "character_natural_language_export status=skip_invalid_source project_id=%s",
                project_id,
            )
            return self._persist_export_character_natural_language(
                snapshot,
                project_id=project_id,
                natural_text=fallback_text,
            )

        try:
            workflow_input = WorkflowInput.from_dict(self._snapshot_input_payload(snapshot))
            from ..orchestrators.fastgpt_hybrid_workflow import run_stage_with_contract_guard
            from .fastgpt_client import FastGPTClient
            from .fastgpt_contracts import STAGE_CHARACTERS_NATURALIZE

            state = WorkflowState(user_input=workflow_input, variables=dict(stage_variables))
            runner = FastGPTClient()
            output = run_stage_with_contract_guard(
                state,
                runner,
                STAGE_CHARACTERS_NATURALIZE,
                stage_variables,
                stage_key="character",
                message="正在整理人物小传自然语言说明。",
                output_field=CHARACTER_NATURAL_LANGUAGE_VAR,
                sync_output_to_state=False,
            )
            natural = extract_unstructured_stage_output_text(
                output,
                output_field=CHARACTER_NATURAL_LANGUAGE_VAR,
            )
            natural = _meaningful_stage_output_text(self._sanitize_export_section_text(natural))
            issues = _character_natural_text_quality_issues(natural, structured) if natural else []
            if not natural or issues:
                logger.warning(
                    "character_natural_language_export status=empty_or_rejected_after_stage project_id=%s issues=%s preview=%s",
                    project_id,
                    ",".join(issues),
                    _truncate_log_text(natural, max_chars=240),
                )
                return self._persist_export_character_natural_language(
                    snapshot,
                    project_id=project_id,
                    natural_text=fallback_text,
                )
            self._persist_export_character_natural_language(
                snapshot,
                project_id=project_id,
                natural_text=natural,
            )
            logger.info(
                "character_natural_language_export status=generated_and_persisted project_id=%s",
                project_id,
            )
            return natural
        except Exception as exc:
            logger.warning(
                "character_natural_language_export status=fallback_after_failure project_id=%s preview=%s",
                project_id,
                _truncate_log_text(str(exc), max_chars=320),
            )
            return self._persist_export_character_natural_language(
                snapshot,
                project_id=project_id,
                natural_text=fallback_text,
            )

    def _build_export_appearance_stage_variables(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        artifacts = self._snapshot_artifacts_dict(snapshot)
        input_payload = self._snapshot_input_payload(snapshot)
        variables = copy.deepcopy(self._snapshot_debug_variables(snapshot))
        if not isinstance(variables, dict):
            variables = {}

        def fill(key: str, *candidates: Any) -> None:
            if variables.get(key) not in (None, "", {}, []):
                return
            for candidate in candidates:
                if candidate not in (None, "", {}, []):
                    variables[key] = candidate
                    return

        fill(WORLDVIEW, artifacts.get("worldview"), input_payload.get("worldview"))
        fill(STORY_OUTLINE, artifacts.get("story_outline"), input_payload.get("story_outline"))
        fill(
            EPISODE_PLAN,
            artifacts.get("normalized_episode_plan"),
            artifacts.get("episode_plan"),
            input_payload.get("episode_plan"),
        )
        fill(USER_CHARACTERS, artifacts.get("character_bios"), input_payload.get("character_bios"))
        fill(CHARACTERS, artifacts.get("characters"), artifacts.get("character_bios"))
        fill(SCENES, artifacts.get("scene_json"), artifacts.get("core_scene_input"))
        fill(
            CHARACTER_ALIAS_NAMING_RULES,
            artifacts.get("character_alias_naming_rules"),
            input_payload.get("character_alias_naming_rules"),
            input_payload.get("alias_naming_rules"),
        )
        fill(APPEARANCE_MAPPING, artifacts.get("appearance_mapping"))
        return variables

    def _ensure_export_appearance_natural_language(
        self,
        snapshot: dict[str, Any],
        *,
        project_id: int,
    ) -> str:
        existing = _meaningful_stage_output_text(
            self._sanitize_export_section_text(
                self._snapshot_export_value(
                    snapshot,
                    artifact_keys=(APPEARANCE_NATURAL_LANGUAGE_ARTIFACT,),
                    variable_keys=(APPEARANCE_NATURAL_LANGUAGE_VAR, "c7VnQ4eX"),
                )
            )
        )
        if existing:
            logger.info("appearance_natural_language_export status=reuse_existing project_id=%s", project_id)
            return existing

        structured = self._snapshot_export_value(
            snapshot,
            artifact_keys=("appearance_mapping",),
            variable_keys=(APPEARANCE_MAPPING, APPEARANCE_MAPPING_VAR),
        )
        if not has_meaningful_content(structured):
            logger.info("appearance_natural_language_export status=skip_missing_mapping project_id=%s", project_id)
            return ""
        if not use_fastgpt_backend():
            logger.info("appearance_natural_language_export status=skip_non_fastgpt_backend project_id=%s", project_id)
            return ""

        try:
            workflow_input = WorkflowInput.from_dict(self._snapshot_input_payload(snapshot))
            stage_variables = self._build_export_appearance_stage_variables(snapshot)
            from ..orchestrators.fastgpt_hybrid_workflow import run_stage_with_contract_guard
            from .fastgpt_client import FastGPTClient
            from .fastgpt_contracts import STAGE_APPEARANCE_ALIAS_UNSTRUCTURED

            state = WorkflowState(user_input=workflow_input, variables=dict(stage_variables))
            runner = FastGPTClient()
            output = run_stage_with_contract_guard(
                state,
                runner,
                STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
                stage_variables,
                stage_key="appearance",
                message="正在整理服装版本自然语言说明。",
                output_field=APPEARANCE_NATURAL_LANGUAGE_VAR,
                sync_output_to_state=False,
            )
            natural = str(output.get(APPEARANCE_NATURAL_LANGUAGE_VAR) or "").strip()
            natural = _meaningful_stage_output_text(self._sanitize_export_section_text(natural))
            if not natural:
                logger.warning(
                    "appearance_natural_language_export status=empty_after_stage project_id=%s",
                    project_id,
                )
                return ""
            self._apply_snapshot_variable_artifact_updates(
                project_id,
                snapshot,
                artifact_updates={APPEARANCE_NATURAL_LANGUAGE_ARTIFACT: natural},
                variable_updates={APPEARANCE_NATURAL_LANGUAGE_VAR: natural},
            )
            logger.info(
                "appearance_natural_language_export status=generated_and_persisted project_id=%s",
                project_id,
            )
            return natural
        except Exception as exc:
            logger.warning(
                "appearance_natural_language_export status=fallback_after_failure project_id=%s preview=%s",
                project_id,
                _truncate_log_text(str(exc), max_chars=320),
            )
            return ""

    def _extract_labeled_export_segment(
        self,
        value: Any,
        *,
        start_labels: tuple[str, ...],
        stop_labels: tuple[str, ...] = (),
    ) -> str:
        raw_text = _strip_export_code_fences(str(value or "")).replace("\r", "")
        parsed = _jsonish_value(raw_text)
        text = clean_export_readable_text(parsed) if parsed is not None else raw_text.strip()
        if not text:
            return ""
        lines = [str(line or "").strip() for line in text.replace("\r", "").split("\n")]
        capturing = False
        captured: list[str] = []
        for line in lines:
            if not line:
                if capturing and captured and captured[-1] != "":
                    captured.append("")
                continue
            matched_start = next((label for label in start_labels if line.startswith(label)), "")
            if matched_start:
                capturing = True
                remainder = line[len(matched_start):].lstrip("：: ")
                if remainder:
                    captured.append(remainder)
                continue
            if capturing and any(line.startswith(label) for label in stop_labels):
                break
            if capturing:
                captured.append(line)
        if not captured:
            return text
        while captured and captured[0] == "":
            captured.pop(0)
        while captured and captured[-1] == "":
            captured.pop()
        return "\n".join(captured).strip()

    def _story_outline_fallback_text(self, value: Any) -> str:
        parsed = _jsonish_value(value)
        if isinstance(parsed, dict):
            segments: list[str] = []
            opening = self._sentence_fragment(parsed.get("opening"))
            inciting = self._sentence_fragment(parsed.get("inciting_incident"))
            early_goal = self._sentence_fragment(parsed.get("early_goal"))
            middle = self._sentence_fragment(parsed.get("middle_escalation"))
            relationship = self._sentence_fragment(parsed.get("relationship_changes"))
            crisis = self._sentence_fragment(parsed.get("larger_crisis_or_truth"))
            climax = self._sentence_fragment(parsed.get("final_climax"))
            ending = self._sentence_fragment(parsed.get("ending_resolution"))
            theme = self._sentence_fragment(parsed.get("theme"))
            if opening:
                segments.append(f"故事从{opening}展开。")
            if inciting:
                segments.append(f"主角因为{inciting}卷入冲突。")
            if early_goal:
                segments.append(f"前期的明确目标是{early_goal}。")
            if middle:
                segments.append(f"随着剧情推进，{middle}。")
            if relationship:
                segments.append(f"人物关系也在这个过程中逐渐变化，{relationship}。")
            if crisis:
                segments.append(f"更大的危机与真相随后浮出水面：{crisis}。")
            if climax:
                segments.append(f"最终故事在{climax}中迎来高潮。")
            if ending:
                segments.append(f"结局落在{ending}。")
            if theme:
                segments.append(f"整部作品最终指向的主题是{theme}。")
            if segments:
                return "\n".join(segments).strip()
        return self._sanitize_export_section_text(value)

    def _story_outline_export_text(self, snapshot: dict[str, Any]) -> str:
        natural = self._snapshot_export_value(
            snapshot,
            artifact_keys=("framework_natural_language",),
            variable_keys=(FRAMEWORK_NATURAL_LANGUAGE,),
            require_meaningful=True,
        )
        natural_excerpt = self._extract_labeled_export_segment(
            natural,
            start_labels=("故事梗概", "故事简介"),
            stop_labels=("主要人物小传", "人物小传", "核心场景说明", "核心场景", "分集计划说明", "分集计划"),
        )
        text = self._validated_export_natural_text(natural_excerpt)
        if text:
            return text
        source = self._snapshot_export_value(
            snapshot,
            artifact_keys=("story_outline",),
            variable_keys=(STORY_OUTLINE,),
            input_keys=("story_outline",),
        )
        return self._story_outline_fallback_text(source)

    def _worldview_fallback_text(self, value: Any) -> str:
        parsed = _jsonish_value(value)
        if isinstance(parsed, dict):
            parts: list[str] = []
            summary = self._sentence_fragment(
                parsed.get("worldview_summary")
                or parsed.get("world_building_core")
                or parsed.get("worldview")
            )
            rules = clean_export_readable_text(parsed.get("social_rules") or parsed.get("rules"))
            atmosphere = self._sentence_fragment(parsed.get("atmosphere") or parsed.get("tone"))
            if summary:
                parts.append(summary if summary.endswith("。") else f"{summary}。")
            if rules:
                parts.append(f"这个世界的运行规则主要体现在：{rules}。")
            if atmosphere:
                parts.append(f"整体气质则偏向{atmosphere}。")
            if parts:
                return "\n".join(parts).strip()
        return self._sanitize_export_section_text(value)

    def _worldview_export_text(self, snapshot: dict[str, Any]) -> str:
        text = self._validated_export_natural_text(
            self._snapshot_export_value(
                snapshot,
                artifact_keys=("worldview_natural_language",),
                variable_keys=(WORLDVIEW_NATURAL_LANGUAGE,),
                require_meaningful=True,
            ),
        )
        if text:
            return text
        source = self._snapshot_export_value(
            snapshot,
            artifact_keys=("worldview",),
            variable_keys=(WORLDVIEW,),
        )
        return self._worldview_fallback_text(source)

    def _character_export_text(self, snapshot: dict[str, Any]) -> str:
        banned = (
            "角色设计原则",
            "角色视觉风格命名策略",
            "角色角色设计原则",
            "character_design_principle",
            "character_visual_styling_naming_strategy",
            "character_role_design_principle",
            "character_registry",
            "character_alias_registry",
        )
        structured = self._snapshot_export_value(
            snapshot,
            artifact_keys=("characters", "character_bios"),
            variable_keys=(CHARACTERS, CHARACTER_VAR),
            input_keys=("character_bios",),
        )
        for candidate in (
            self._snapshot_export_value(snapshot, artifact_keys=("character_natural_language",)),
            self._snapshot_export_value(snapshot, variable_keys=(CHARACTER_NATURAL_LANGUAGE_VAR,)),
            self._snapshot_export_value(snapshot, artifact_keys=("character_summary",)),
        ):
            raw_text = clean_export_readable_text(candidate).strip()
            sanitized = self._sanitize_export_section_text(raw_text, banned_prefixes=banned)
            text = _meaningful_stage_output_text(sanitized)
            issues = _character_natural_text_quality_issues(raw_text, structured) if raw_text else []
            if text and not issues:
                return text
            if raw_text and (issues or (not text and is_placeholder_text(raw_text))):
                _log_warning_once(
                    "character_export_text_rejected",
                    issues or ["placeholder_heavy_natural_language"],
                    _truncate_log_text(raw_text, max_chars=240),
                )
        return self._character_structured_fallback_text(structured)

    def _appearance_export_text(self, snapshot: dict[str, Any]) -> str:
        for candidate in (
            self._snapshot_export_value(snapshot, artifact_keys=(APPEARANCE_NATURAL_LANGUAGE_ARTIFACT,)),
            self._snapshot_export_value(snapshot, variable_keys=(APPEARANCE_NATURAL_LANGUAGE_VAR, "c7VnQ4eX")),
            self._snapshot_export_value(snapshot, artifact_keys=(APPEARANCE_NATURAL_LANGUAGE_ARTIFACT,)),
        ):
            text = _meaningful_stage_output_text(self._sanitize_export_section_text(candidate))
            if text:
                return text

        structured = self._snapshot_export_value(
            snapshot,
            artifact_keys=("appearance_mapping",),
            variable_keys=(APPEARANCE_MAPPING, APPEARANCE_MAPPING_VAR),
        )
        characters = _appearance_character_items_from_value(structured)
        if not characters:
            return ""
        blocks: list[str] = []
        for item in characters:
            role_name = self._sentence_fragment(
                item.get("default_name")
                or item.get("canonical_name")
                or item.get("character_name")
                or item.get("character_id")
            ) or "未命名角色"
            default_name = self._sentence_fragment(item.get("default_name") or item.get("canonical_name"))
            same_person_anchor = self._sentence_fragment(item.get("same_person_anchor"))
            forbidden = clean_export_readable_text(item.get("forbidden_generic_names"))
            variants = item.get("outfit_variants") if isinstance(item.get("outfit_variants"), list) else []
            variant_lines: list[str] = []
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                alias_name = self._sentence_fragment(variant.get("alias_name") or variant.get("default_name"))
                usage_rule = self._sentence_fragment(variant.get("usage_rule"))
                episode_hint = self._sentence_fragment(variant.get("episode_range_hint"))
                trigger_rule = self._sentence_fragment(
                    variant.get("scene_trigger_rules")
                    or variant.get("scene_names")
                    or variant.get("scene_types")
                    or variant.get("status_conditions")
                )
                detail_bits = [bit for bit in (usage_rule, episode_hint, trigger_rule) if bit]
                if alias_name:
                    if detail_bits:
                        variant_lines.append(f"{alias_name}：{'；'.join(detail_bits)}")
                    else:
                        variant_lines.append(alias_name)
            block_parts = [f"【角色】{role_name}"]
            if default_name:
                block_parts.append(f"默认称呼：{default_name}")
            if same_person_anchor:
                block_parts.append(f"固定识别锚点：{same_person_anchor}")
            if variant_lines:
                block_parts.append("服装版本与使用条件：" + "；".join(variant_lines))
            if forbidden:
                block_parts.append(f"禁止退回泛称：{forbidden}")
            blocks.append("\n".join(block_parts).strip())
        return "\n\n".join(block for block in blocks if block).strip()

    def _scene_export_text(self, snapshot: dict[str, Any]) -> str:
        for candidate in (
            self._snapshot_export_value(snapshot, artifact_keys=("scene_natural_language", "core_scene_summary")),
            self._snapshot_export_value(snapshot, variable_keys=(SCENE_NATURAL_LANGUAGE_VAR,)),
        ):
            if is_machine_structured_content(candidate):
                continue
            text = _meaningful_stage_output_text(self._sanitize_export_section_text(candidate))
            if text and _export_text_has_placeholder_leaks(text):
                continue
            if text:
                return text

        structured = self._snapshot_export_value(
            snapshot,
            artifact_keys=("scene_json", "core_scene_input"),
            variable_keys=(SCENES, SCENE_VAR),
            input_keys=("core_scene_input",),
        )
        scenes = _scene_items_from_value(structured)
        if not scenes:
            return ""
        blocks: list[str] = []
        for item in scenes:
            if not isinstance(item, dict):
                continue
            name = self._sentence_fragment(item.get("scene_name") or item.get("name")) or "核心场景"
            scene_type = self._sentence_fragment(item.get("scene_type"))
            story_function = self._sentence_fragment(item.get("story_function"))
            environment = self._sentence_fragment(item.get("environment_description"))
            atmosphere = self._sentence_fragment(item.get("atmosphere_description"))
            interaction = self._sentence_fragment(item.get("character_interaction_effect"))
            fragments = [bit for bit in (scene_type, story_function, environment, atmosphere, interaction) if bit]
            if not fragments:
                fragments.append("承载关键剧情推进。")
            blocks.append(f"{name}：{'，'.join(fragments).strip('，')}。")
        return "\n".join(block for block in blocks if block).strip()

    def _episode_plan_export_text(self, snapshot: dict[str, Any]) -> str:
        artifacts = self._snapshot_artifacts_dict(snapshot)
        display_text = self._snapshot_export_value(
            snapshot,
            artifact_keys=(EPISODE_PLAN_DISPLAY_ARTIFACT,),
        )
        if display_text:
            text = self._sanitize_export_section_text(display_text)
            if text:
                return text
        text = self._episode_plan_display_text(snapshot, artifacts)
        return self._sanitize_export_section_text(text)

    def _build_docx_export_source_text(self, snapshot: dict[str, Any]) -> str:
        """把正式产物组装成自然语言前置信息 + 正文，供 DOCX 导出使用。"""
        artifacts = self._snapshot_artifacts_dict(snapshot)
        input_payload = self._snapshot_input_payload(snapshot)
        title = str(
            artifacts.get("script_title_content")
            or snapshot.get("title")
            or input_payload.get("title")
            or f"project_{snapshot.get('project_id')}"
        ).strip()
        final_script = self._best_final_script_text(snapshot)
        if not final_script:
            return ""

        parts: list[str] = [title or f"project_{snapshot.get('project_id')}"]
        for heading, section_text in (
            ("故事梗概", self._story_outline_export_text(snapshot)),
            ("世界观设定", self._worldview_export_text(snapshot)),
            ("人物小传", self._character_export_text(snapshot)),
            ("人物服饰说明", self._appearance_export_text(snapshot)),
            ("核心场景", self._scene_export_text(snapshot)),
        ):
            cleaned = self._sanitize_export_section_text(section_text)
            if cleaned:
                parts.append(f"{heading}\n{cleaned}")

        script_section = (
            final_script
            if final_script.lstrip().startswith("剧本正文")
            else f"剧本正文\n{final_script}"
        )
        parts.append(script_section)
        return "\n\n".join(part.strip() for part in parts if str(part).strip()).strip() + "\n"

    def _build_character_setting_export_block(self, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        source_candidates = (
            artifacts.get("character_summary"),
            artifacts.get("character_bios"),
            artifacts.get("characters"),
            artifacts.get("user_characters"),
        )
        for candidate in source_candidates:
            normalized = self._coerce_existing_export_block(candidate, block_key="character_setting")
            if normalized:
                return normalized

        source_text = next((str(item).strip() for item in source_candidates if str(item or "").strip()), "")
        if not source_text:
            return None
        characters = self._parse_character_entries(source_text)
        if not characters:
            return None
        return {
            "character_setting": {
                "character_design_principle": self._summarize_export_text(source_text, limit=140),
                "characters": characters,
            }
        }

    def _build_scene_setting_export_block(self, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
        source_candidates = (
            artifacts.get("core_scene_summary"),
            artifacts.get("scene_json"),
            artifacts.get("core_scene_input"),
            artifacts.get("user_scenes"),
        )
        for candidate in source_candidates:
            normalized = self._coerce_existing_export_block(candidate, block_key="scene_setting")
            if normalized:
                return normalized

        source_text = next((str(item).strip() for item in source_candidates if str(item or "").strip()), "")
        if not source_text:
            return None
        scenes = self._parse_scene_entries(source_text)
        if not scenes:
            return None
        return {
            "scene_setting": {
                "scene_design_principle": self._summarize_export_text(source_text, limit=180),
                "scenes": scenes,
            }
        }

    def _coerce_existing_export_block(
        self,
        candidate: Any,
        *,
        block_key: str,
    ) -> dict[str, Any] | None:
        value = self._coerce_jsonish_value(candidate)
        if value is None:
            return None
        if isinstance(value, dict) and isinstance(value.get(block_key), dict):
            return {block_key: value[block_key]}
        if block_key == "character_setting":
            if isinstance(value, dict) and isinstance(value.get("characters"), list):
                return {
                    "character_setting": {
                        "character_design_principle": self._summarize_export_text(candidate, limit=140),
                        "characters": [item for item in value.get("characters") or [] if isinstance(item, dict)],
                    }
                }
            if isinstance(value, list):
                items = [item for item in value if isinstance(item, dict)]
                if items:
                    return {
                        "character_setting": {
                            "character_design_principle": self._summarize_export_text(candidate, limit=140),
                            "characters": items,
                        }
                    }
        if block_key == "scene_setting":
            if isinstance(value, dict) and isinstance(value.get("scenes"), dict) and isinstance(
                value["scenes"].get("scene_setting"),
                dict,
            ):
                return {"scene_setting": value["scenes"]["scene_setting"]}
            if isinstance(value, dict) and isinstance(value.get("scenes"), list):
                return {
                    "scene_setting": {
                        "scene_design_principle": self._summarize_export_text(candidate, limit=180),
                        "scenes": [item for item in value.get("scenes") or [] if isinstance(item, dict)],
                    }
                }
            if isinstance(value, list):
                items = [item for item in value if isinstance(item, dict)]
                if items:
                    return {
                        "scene_setting": {
                            "scene_design_principle": self._summarize_export_text(candidate, limit=180),
                            "scenes": items,
                        }
                    }
        return None

    def _coerce_jsonish_value(self, value: Any) -> Any | None:
        if isinstance(value, (dict, list)):
            return value
        text = str(value or "").strip()
        if not text or text[0] not in "[{":
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        if isinstance(parsed, (dict, list)):
            return parsed
        return None

    def _parse_character_entries(self, text: str) -> list[dict[str, Any]]:
        blocks = self._split_character_blocks(text)
        if not blocks:
            return []
        entries: list[dict[str, Any]] = []
        for block in blocks:
            heading = str(block.get("heading") or "").strip()
            lines = block.get("lines") if isinstance(block.get("lines"), list) else []
            name, role_hint = self._parse_character_heading(heading)
            fields = self._parse_inline_fields(lines)
            story_role = self._pick_first_non_empty(
                fields,
                "人物定位",
                "身份定位",
                "故事角色",
            ) or role_hint
            core_motivation = self._pick_first_non_empty(
                fields,
                "核心欲望",
                "核心动机",
                "深层动机",
                "行为习惯与核心动机",
            )
            dramatic_value = self._pick_first_non_empty(
                fields,
                "主线作用",
                "戏剧价值",
                "人物小传",
                "关系特点",
            )
            personality_text = self._pick_first_non_empty(fields, "性格特点", "性格特质")
            appearance_anchor = self._pick_first_non_empty(fields, "稳定外貌识别锚点", "稳定识别锚点")
            entry = {
                "character_name": name or "未命名角色",
                "story_role": story_role or "角色设定",
                "core_motivation": core_motivation or "待补充",
                "dramatic_value": dramatic_value or story_role or "待补充",
            }
            personality = self._compact_dict(
                {
                    "traits": self._split_brief_items(personality_text),
                    "surface_impression": self._pick_first_non_empty(fields, "外貌特征", "外貌描述"),
                    "inner_contradiction": self._pick_first_non_empty(fields, "角色弱点", "深层动机"),
                }
            )
            family = self._compact_dict(
                {
                    "family_background": self._pick_first_non_empty(fields, "家庭背景", "家世"),
                    "upbringing": self._pick_first_non_empty(fields, "成长线", "成长经历"),
                    "key_family_influence": self._pick_first_non_empty(fields, "与主角关系", "与其他主要角色关系", "关系特点"),
                }
            )
            appearance = self._compact_dict(
                {
                    "overall_look": self._pick_first_non_empty(fields, "外貌特征", "外貌描述"),
                    "recognizable_features": self._split_brief_items(appearance_anchor, max_items=6),
                    "external_impression_effect": self._pick_first_non_empty(fields, "出场记忆点", "人物小传"),
                }
            )
            behavior = self._compact_dict(
                {
                    "emotional_response_pattern": self._pick_first_non_empty(fields, "行为习惯与核心动机", "角色弱点"),
                    "social_interaction_style": self._pick_first_non_empty(fields, "常见活动状态", "关系特点"),
                }
            )
            if personality:
                entry["personality"] = personality
            if family:
                entry["family"] = family
            if appearance:
                entry["appearance"] = appearance
            if behavior:
                entry["behavior"] = behavior
            entries.append(entry)
        return entries

    def _split_character_blocks(self, text: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        current_heading = ""
        current_lines: list[str] = []
        for raw_line in str(text or "").replace("\r", "").split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if self._looks_like_character_heading(line):
                if current_heading:
                    blocks.append({"heading": current_heading, "lines": current_lines[:]})
                current_heading = line
                current_lines = []
                continue
            if current_heading:
                current_lines.append(line)
        if current_heading:
            blocks.append({"heading": current_heading, "lines": current_lines[:]})
        return blocks

    def _looks_like_character_heading(self, line: str) -> bool:
        text = str(line or "").strip()
        if not text:
            return False
        if re.match(r"^\d+\.\s*[^\s]", text):
            return True
        if text.startswith("【") and "】" in text and "人物小传" not in text and "主要角色设定" not in text:
            suffix = text.split("】", 1)[1].strip()
            return bool(suffix)
        return False

    def _parse_character_heading(self, heading: str) -> tuple[str, str]:
        text = str(heading or "").strip()
        if not text:
            return "", ""
        if re.match(r"^\d+\.", text):
            body = re.sub(r"^\d+\.\s*", "", text)
            name = re.split(r"[（(]", body, maxsplit=1)[0].strip()
            role_hint = body[len(name):].strip("（）() ")
            return name, role_hint
        match = re.match(r"^【(?P<label>[^】]+)】\s*(?P<name>.+)$", text)
        if match:
            name = re.split(r"[（(]", match.group("name"), maxsplit=1)[0].strip()
            return name, match.group("label").strip()
        return text, ""

    def _parse_inline_fields(self, lines: list[str]) -> dict[str, str]:
        fields: dict[str, str] = {}
        current_key = ""
        for line in lines:
            text = str(line or "").strip()
            if not text:
                continue
            match = re.match(r"^(?P<key>[^：:]{1,24})[:：]\s*(?P<value>.*)$", text)
            if match:
                current_key = match.group("key").strip()
                value = match.group("value").strip()
                if current_key:
                    fields[current_key] = value
                continue
            if current_key and text:
                fields[current_key] = f"{fields.get(current_key, '')}\n{text}".strip()
        return fields

    def _parse_scene_entries(self, text: str) -> list[dict[str, Any]]:
        sections = self._parse_multiline_sections(text)
        area_items = self._parse_numbered_items(
            sections.get("核心场景区域")
            or sections.get("核心场景")
            or ""
        )
        conflict_items = self._parse_numbered_items(
            sections.get("冲突土壤")
            or sections.get("危险来源")
            or ""
        )
        visual_items = self._parse_numbered_items(
            sections.get("高频触发服装切换的场景类型")
            or ""
        )
        worldview_support = "\n".join(
            part for part in (
                sections.get("时代背景与世界观"),
                sections.get("时代背景"),
                sections.get("世界状态"),
            ) if part
        ).strip()
        interaction_effect = "\n".join(
            part for part in (
                sections.get("社会环境"),
                sections.get("生存规则与行动规则"),
                sections.get("社会身份要求"),
            ) if part
        ).strip()
        atmosphere = sections.get("整体氛围") or ""
        environment_suffix = "\n".join(
            part for part in (
                sections.get("环境条件与时间条件"),
                sections.get("环境条件触发"),
                sections.get("时间条件触发"),
            ) if part
        ).strip()

        if not area_items:
            merged_environment = self._summarize_export_text(
                "\n".join(part for part in (sections.get("核心场景区域"), environment_suffix) if part),
                limit=280,
            )
            return [self._compact_dict(
                {
                    "scene_name": "核心场景设定",
                    "scene_type": "故事舞台",
                    "story_function": self._summarize_export_text(text, limit=160),
                    "environment_description": merged_environment or self._summarize_export_text(text, limit=240),
                    "atmosphere_description": atmosphere or self._summarize_export_text(text, limit=120),
                    "character_interaction_effect": interaction_effect or None,
                    "worldview_support": worldview_support or None,
                    "visual_elements": visual_items[:6] if visual_items else None,
                    "conflict_potential": conflict_items[:6] if conflict_items else None,
                }
            )]

        scenes: list[dict[str, Any]] = []
        for item in area_items:
            name, description = self._split_list_item_name_value(item)
            environment_description = description
            if environment_suffix:
                environment_description = "\n".join(part for part in (description, environment_suffix) if part).strip()
            scene = self._compact_dict(
                {
                    "scene_name": name or "核心场景",
                    "scene_type": "故事关键区域",
                    "story_function": description or atmosphere or "承载关键剧情推进。",
                    "environment_description": environment_description or worldview_support or "见核心场景说明。",
                    "atmosphere_description": atmosphere or None,
                    "character_interaction_effect": interaction_effect or None,
                    "worldview_support": worldview_support or None,
                    "visual_elements": visual_items[:6] if visual_items else None,
                    "conflict_potential": conflict_items[:6] if conflict_items else None,
                }
            )
            scenes.append(scene)
        return scenes

    def _parse_multiline_sections(self, text: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        current_key = ""
        buffer: list[str] = []
        for raw_line in str(text or "").replace("\r", "").split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            match = re.match(r"^(?P<key>[^：:\n]{2,28})[:：]\s*(?P<value>.*)$", line)
            if match and not re.match(r"^\d+\.\s*", line):
                if current_key:
                    sections[current_key] = "\n".join(buffer).strip()
                current_key = match.group("key").strip()
                buffer = [match.group("value").strip()] if match.group("value").strip() else []
                continue
            if current_key:
                buffer.append(line)
        if current_key:
            sections[current_key] = "\n".join(buffer).strip()
        return sections

    def _parse_numbered_items(self, text: str) -> list[str]:
        items: list[str] = []
        for raw_line in str(text or "").replace("\r", "").split("\n"):
            line = raw_line.strip(" -\t")
            if not line:
                continue
            match = re.match(r"^\d+\.\s*(.+)$", line)
            if match:
                items.append(match.group(1).strip())
                continue
            if not items:
                items.append(line)
            else:
                items[-1] = f"{items[-1]} {line}".strip()
        return items

    def _split_list_item_name_value(self, item: str) -> tuple[str, str]:
        text = str(item or "").strip()
        if not text:
            return "", ""
        if "：" in text:
            name, value = text.split("：", 1)
            return name.strip(), value.strip()
        if ":" in text:
            name, value = text.split(":", 1)
            return name.strip(), value.strip()
        return text, ""

    def _pick_first_non_empty(self, fields: dict[str, str], *keys: str) -> str:
        for key in keys:
            value = str(fields.get(key) or "").strip()
            if value:
                return value
        return ""

    def _split_brief_items(self, value: str, *, max_items: int = 5) -> list[str]:
        text = str(value or "").replace("\n", " ").strip()
        if not text:
            return []
        parts = [
            part.strip("；;，,。 ")
            for part in re.split(r"[；;、]", text)
            if part.strip("；;，,。 ")
        ]
        if len(parts) <= 1:
            parts = [
                part.strip("；;，,。 ")
                for part in re.split(r"[，,]", text)
                if part.strip("；;，,。 ")
            ]
        return parts[:max_items] if parts else [text[:80]]

    def _summarize_export_text(self, value: Any, *, limit: int) -> str:
        condensed = " ".join(str(value or "").replace("\r", "\n").split())
        return condensed[:limit] if condensed else ""

    def _compact_dict(self, payload: dict[str, Any]) -> dict[str, Any]:
        compacted: dict[str, Any] = {}
        for key, value in payload.items():
            if value in (None, "", [], {}):
                continue
            compacted[key] = value
        return compacted

    def save_final_script(self, project_id: int, user_id: int | None = None) -> Path:
        snapshot = self.get_project_snapshot(project_id, user_id=user_id, public_view=False)
        if not snapshot:
            raise ValueError("项目不存在")
        artifacts = snapshot.get("artifacts", {})
        final_script = self._best_final_script_text(snapshot)
        total_episodes = _safe_int(
            snapshot.get("total_episodes")
            or (snapshot.get("input_payload") or {}).get("total_episodes"),
            0,
        )
        if final_script and total_episodes > 0:
            available_episodes = _script_episode_numbers(
                final_script,
                total_episodes=total_episodes,
            )
            expected = list(range(1, total_episodes + 1))
            if available_episodes != expected:
                available_set = set(available_episodes)
                missing = [episode for episode in expected if episode not in available_set]
                raise ValueError(
                    f"当前剧本正文只覆盖 {len(available_episodes)}/{total_episodes} 集，"
                    f"缺少：{_format_episode_ranges(missing)}。"
                    "请先继续生成缺失批次，再下载成品。"
                )
        self._ensure_export_character_natural_language(snapshot, project_id=project_id)
        self._ensure_export_appearance_natural_language(snapshot, project_id=project_id)
        content = self._build_docx_export_source_text(snapshot)
        if not content:
            raise ValueError("当前项目还没有可保存的最终剧本")
        title = str(snapshot.get("title") or f"project_{project_id}").strip() or f"project_{project_id}"
        safe_title = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in title)[:80]
        base_name = f"{safe_title}_{project_id}"
        txt_path = self.exports_dir / f"{base_name}.txt"
        docx_path = self.exports_dir / f"{base_name}.docx"
        # TODO: README 历史上提到 zip/json 一起导出，但当前实现只稳定产出 txt/docx。
        # 如果后续要恢复压缩包导出，需要在这里补齐真实打包和快照写回逻辑。
        zip_path = self.exports_dir / f"{base_name}.zip"
        notice_path = self.exports_dir / f"{base_name}_导出说明.txt"
        legacy_json_paths = [
            self.exports_dir / f"{base_name}_character_registry.json",
            self.exports_dir / f"{base_name}_character_alias_registry.json",
            self.exports_dir / f"{base_name}_episode_alias_plan.json",
            self.exports_dir / f"{base_name}_appearance_mapping.json",
            self.exports_dir / f"{base_name}_appearance_continuity_memory.json",
            self.exports_dir / f"{base_name}_normalized_episode_plan.json",
        ]

        txt_path.write_text(content, encoding="utf-8")
        try:
            from ..utils.txt_to_docx import convert as convert_txt_to_docx
            convert_txt_to_docx(str(txt_path), str(docx_path))
        except ModuleNotFoundError as exc:
            if exc.name == "docx":
                raise ValueError("当前环境缺少 python-docx，暂时无法导出剧本正文 DOCX。") from exc
            else:
                raise ValueError(f"导出剧本正文 DOCX 失败：{exc}") from exc
        except Exception as exc:
            logger.exception("导出 Word 失败: %s", project_id)
            raise ValueError(f"导出剧本正文 DOCX 失败：{exc}") from exc

        for stale_path in (zip_path, notice_path, *legacy_json_paths):
            if stale_path.exists():
                stale_path.unlink()

        self._update_snapshot(
            self._projects.get(project_id) or TaskRecord(
                user_id=int(snapshot.get("user_id") or 0),
                project_id=project_id,
                task_id=str(snapshot.get("task_id", "")),
                workflow_spec_path=str(snapshot.get("workflow_spec_path", "")),
                input_payload=snapshot.get("input_payload", {}),
                model_option=settings.resolve_model_selection(
                    (snapshot.get("model_option") or {}).get("id")
                ),
                snapshot=snapshot,
            ),
            saved_file=str(docx_path),
            saved_txt_file="",
            saved_docx_file=str(docx_path),
            saved_zip_file="",
            export_notice="",
            saved_json_files={},
        )
        return docx_path

