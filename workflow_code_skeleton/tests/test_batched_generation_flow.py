from __future__ import annotations

import json
import unittest

from workflow_code_skeleton.app.config import settings
from workflow_code_skeleton.app.models.inputs import WorkflowInput
from workflow_code_skeleton.app.models.state import WorkflowState
from workflow_code_skeleton.app.orchestrators import fastgpt_hybrid_workflow as flow
from workflow_code_skeleton.app.services.fastgpt_contracts import (
    ALL_DIALOGUES,
    ALL_HOOKS,
    ALL_SCRIPT,
    APPEARANCE_MAPPING,
    BATCH_DIALOGUES,
    BATCH_HOOKS,
    BATCH_SCRIPT,
    BATCH_START_EPISODE,
    CHARACTER_ALIAS_NAMING_RULES,
    CHARACTERS,
    EPISODE_PLAN,
    EPISODE_WORD_COUNT,
    LAST_SUMMARY,
    MAX_RETRIES,
    NORMALIZED_EPISODE_PLAN,
    SCENES,
    STORY_OUTLINE,
    TOTAL_EPISODES,
    WORLDVIEW,
    STAGE_DIALOGUES,
    STAGE_DIALOGUE_MEMORY,
    STAGE_DIALOGUE_REVIEW,
    STAGE_DIALOGUES_REVIEW,
    STAGE_DIALOGUES_REWRITE,
    STAGE_DIALOGUES_WRITING,
    STAGE_HOOKS,
    STAGE_HOOK_MEMORY,
    STAGE_HOOK_REVIEW,
    STAGE_HOOKS_REVIEW,
    STAGE_HOOKS_REWRITE,
    STAGE_HOOKS_WRITING,
    STAGE_SCRIPT,
    STAGE_SCRIPT_MEMORY,
    STAGE_SCRIPT_REVIEW,
    STAGE_SCRIPT_REWRITE,
    STAGE_SCRIPT_WRITING,
)
from workflow_code_skeleton.app.utils.episode import BatchWindow, iter_episode_batches
from workflow_code_skeleton.app.workflow_ids import (
    DIALOGUE_CURRENT_WORKFLOW_VAR,
    DIALOGUE_CURRENT_WRITE_VAR,
    DIALOGUE_MEMORY_OUTPUT_VAR,
    DIALOGUE_REVIEW_LEGACY_VAR,
    DIALOGUE_REVIEW_WORKFLOW_VAR,
    HOOK_CURRENT_VAR,
    HOOK_CURRENT_WRITE_VAR,
    HOOK_MEMORY_OUTPUT_VAR,
    HOOK_REVIEW_OUTPUT_VAR,
    MEMORY_VAR,
    SCRIPT_CURRENT_VAR,
    SCRIPT_CURRENT_WRITE_VAR,
    SCRIPT_MEMORY_OUTPUT_VAR,
    SCRIPT_REVIEW_OUTPUT_VAR,
    SCRIPT_REVIEW_WRITE_VAR,
)


def _workflow_input(total_episodes: int) -> WorkflowInput:
    return WorkflowInput(
        title="测试剧本",
        episode_word_count=1200,
        total_episodes=total_episodes,
        user_expectation="测试三段式批处理",
        character_count=3,
        character_appearance_requirements="",
        character_alias_naming_rules="统一使用正式中文名",
        outfit_switch_rules="",
        story_outline="测试大纲",
        core_scene_input="测试核心场景",
        character_bios="测试人物小传",
        episode_plan="",
    )


def _normalized_plan(total_episodes: int) -> dict[str, object]:
    return {
        "parsed_episode_count": total_episodes,
        "appearance_alias_planning": {},
        "episodes": [
            {
                "episode": episode,
                "title": f"第{episode}集",
                "content": f"第{episode}集主线推进",
                "main_character_aliases": [],
                "appearance_events": [],
                "long_term_stage_flags": [],
                "scene_based_alias_hints": [],
            }
            for episode in range(1, total_episodes + 1)
        ],
    }


def _hook_batch(episodes: list[int]) -> dict[str, object]:
    return {
        "batch_meta": {
            "start_episode": episodes[0],
            "end_episode": episodes[-1],
        },
        "global_hook_engine": {
            "batch_label": f"{episodes[0]}-{episodes[-1]}",
        },
        "episodes": [
            {
                "episode": episode,
                "hook": f"第{episode}集钩子",
            }
            for episode in episodes
        ],
    }


def _dialogue_batch(episodes: list[int]) -> dict[str, object]:
    return {
        "batch_meta": {
            "start_episode": episodes[0],
            "end_episode": episodes[-1],
        },
        "character_voice_bibles": [
            {
                "character_name": "林夏",
                "voice": "克制锋利",
            }
        ],
        "episode_dialogue_blocks": [
            {
                "episode": episode,
                "dialogue_block": f"第{episode}集对白块",
            }
            for episode in episodes
        ],
    }


def _script_batch_text(episodes: list[int]) -> str:
    return "\n\n".join(
        f"第{episode}集：\n场景一：第{episode}集正文"
        for episode in episodes
    )


def _hook_batch(episodes: list[int]) -> dict[str, object]:
    return {
        "batch_meta": {
            "start_episode": episodes[0],
            "end_episode": episodes[-1],
        },
        "global_hook_engine": {
            "batch_label": f"{episodes[0]}-{episodes[-1]}",
        },
        "episodes": [
            {
                "episode": episode,
                "hook": f"hook-{episode}",
                "opening_alias_plan": {"primary_alias": "A"},
                "opening_action": f"open-{episode}",
                "current_goal": f"goal-{episode}",
                "core_obstacle": f"obstacle-{episode}",
                "ending_hook": f"ending-{episode}",
                "next_episode_priority_response": f"next-{episode}",
            }
            for episode in episodes
        ],
    }


def _dialogue_batch(episodes: list[int]) -> dict[str, object]:
    return {
        "batch_meta": {
            "start_episode": episodes[0],
            "end_episode": episodes[-1],
        },
        "character_voice_bibles": [
            {
                "character_name": "A",
                "voice": "direct",
            }
        ],
        "episode_dialogue_blocks": [
            {
                "episode": episode,
                "participants": ["A", "B"],
                "speaker": "A",
                "dialogue_block": f"dialogue-{episode}",
            }
            for episode in episodes
        ],
    }


def _script_batch_text(episodes: list[int]) -> str:
    return "\n\n".join(
        f"第{episode}集\n{episode}-1\n正文内容 {episode}"
        for episode in episodes
    )


def _episode_numbers_from_plan(plan_value: object) -> list[int]:
    candidate = plan_value
    if isinstance(candidate, str):
        candidate = json.loads(candidate)
    if not isinstance(candidate, dict):
        return []
    episodes = candidate.get("episodes")
    if not isinstance(episodes, list):
        return []
    return [
        int(item["episode"])
        for item in episodes
        if isinstance(item, dict) and int(item.get("episode", 0)) > 0
    ]


def _episode_numbers_from_object(value: object) -> list[int]:
    if not isinstance(value, dict):
        return []
    if isinstance(value.get("episodes"), list):
        source = value["episodes"]
    elif isinstance(value.get("episode_dialogue_blocks"), list):
        source = value["episode_dialogue_blocks"]
    else:
        return []
    return [
        int(item["episode"])
        for item in source
        if isinstance(item, dict) and int(item.get("episode", 0)) > 0
    ]


class _PhaseRecordingRunner:
    def __init__(
        self,
        *,
        review_sequences: dict[str, list[object]] | None = None,
        stage_outputs: dict[str, list[object]] | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.review_sequences = {
            key: list(value)
            for key, value in (review_sequences or {}).items()
        }
        self.stage_outputs = {
            key: list(value)
            for key, value in (stage_outputs or {}).items()
        }

    def run_stage(self, stage_name: str, variables: dict[str, object]) -> dict[str, object]:
        batch_start = int(variables.get(BATCH_START_EPISODE, 0) or 0)
        plan_episodes = _episode_numbers_from_plan(variables.get(EPISODE_PLAN))
        hooks_episodes = _episode_numbers_from_object(variables.get(ALL_HOOKS))
        dialogue_episodes = _episode_numbers_from_object(variables.get(ALL_DIALOGUES))
        self.calls.append(
            {
                "stage": stage_name,
                "batch_start": batch_start,
                "plan_episodes": plan_episodes,
                "hooks_episodes": hooks_episodes,
                "dialogue_episodes": dialogue_episodes,
                "hook_write_alias_episodes": _episode_numbers_from_object(
                    variables.get(HOOK_CURRENT_WRITE_VAR)
                ),
                "hook_review_alias_episodes": _episode_numbers_from_object(
                    variables.get(HOOK_CURRENT_VAR)
                ),
                "dialogue_write_alias_episodes": _episode_numbers_from_object(
                    variables.get(DIALOGUE_CURRENT_WRITE_VAR)
                ),
                "dialogue_workflow_alias_episodes": _episode_numbers_from_object(
                    variables.get(DIALOGUE_CURRENT_WORKFLOW_VAR)
                ),
                "script_write_alias_text": str(variables.get(SCRIPT_CURRENT_WRITE_VAR) or ""),
                "script_current_alias_text": str(variables.get(SCRIPT_CURRENT_VAR) or ""),
                "script_review_alias_text": str(variables.get(SCRIPT_REVIEW_WRITE_VAR) or ""),
            }
        )

        custom_output = self._custom_stage_output(stage_name)
        if custom_output is not None:
            return custom_output

        if stage_name in {STAGE_HOOKS, STAGE_HOOKS_WRITING, STAGE_HOOKS_REWRITE}:
            return {BATCH_HOOKS: _hook_batch(plan_episodes)}
        if stage_name == STAGE_HOOKS_REVIEW:
            return self._review_payload(stage_name)
        if stage_name in {STAGE_DIALOGUES, STAGE_DIALOGUES_WRITING, STAGE_DIALOGUES_REWRITE}:
            return {BATCH_DIALOGUES: _dialogue_batch(plan_episodes)}
        if stage_name == STAGE_DIALOGUES_REVIEW:
            return self._review_payload(stage_name)
        if stage_name in {STAGE_SCRIPT, STAGE_SCRIPT_WRITING, STAGE_SCRIPT_REWRITE}:
            return {BATCH_SCRIPT: _script_batch_text(plan_episodes)}
        if stage_name == STAGE_SCRIPT_REVIEW:
            return self._review_payload(stage_name)
        if stage_name == STAGE_SCRIPT_MEMORY:
            return {LAST_SUMMARY: f"summary-{len(self.memory_calls()) + 1}"}
        raise AssertionError(f"Unexpected stage call: {stage_name}")

    def stage_calls(self, stage_name: str) -> list[dict[str, object]]:
        return [call for call in self.calls if call["stage"] == stage_name]

    def memory_calls(self) -> list[dict[str, object]]:
        return self.stage_calls(STAGE_SCRIPT_MEMORY)

    def _review_payload(self, stage_name: str) -> dict[str, object]:
        sequence = self.review_sequences.get(stage_name, [])
        if sequence:
            item = sequence.pop(0)
            if isinstance(item, Exception):
                raise item
            if isinstance(item, dict):
                return dict(item)
            if item is False:
                return {
                    "passed": False,
                    "rewrite_required": True,
                    "blocking_issues": [f"{stage_name} failed"],
                    "summary": f"{stage_name} failed",
                    "non_blocking_issues": [],
                }
        return {
            "passed": True,
            "rewrite_required": False,
            "blocking_issues": [],
            "summary": f"{stage_name} passed",
            "non_blocking_issues": [],
        }

    def _custom_stage_output(self, stage_name: str) -> dict[str, object] | None:
        sequence = self.stage_outputs.get(stage_name, [])
        if not sequence:
            return None
        item = sequence.pop(0)
        if isinstance(item, dict):
            return dict(item)
        raise AssertionError(f"Custom stage output for {stage_name} must be dict")


class BatchedGenerationFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_batch_mode = settings.fastgpt_batch_mode
        self._original_batch_size = settings.batch_size
        self._original_review_loops = settings.fastgpt_stage_review_revise_max_loops
        settings.fastgpt_batch_mode = "local"
        settings.batch_size = 5
        settings.fastgpt_stage_review_revise_max_loops = 10

    def tearDown(self) -> None:
        settings.fastgpt_batch_mode = self._original_batch_mode
        settings.batch_size = self._original_batch_size
        settings.fastgpt_stage_review_revise_max_loops = self._original_review_loops

    def _base_variables(self, total_episodes: int) -> dict[str, object]:
        normalized_plan = _normalized_plan(total_episodes)
        return {
            TOTAL_EPISODES: total_episodes,
            EPISODE_WORD_COUNT: 1200,
            STORY_OUTLINE: "测试大纲",
            WORLDVIEW: json.dumps({"worldview_summary": "测试世界观"}, ensure_ascii=False),
            CHARACTERS: json.dumps({"character_setting": {"characters": []}}, ensure_ascii=False),
            SCENES: json.dumps({"scene_setting": {"scenes": []}}, ensure_ascii=False),
            APPEARANCE_MAPPING: {"appearance_mapping": {"characters": []}},
            CHARACTER_ALIAS_NAMING_RULES: "统一使用正式中文名",
            EPISODE_PLAN: json.dumps(normalized_plan, ensure_ascii=False),
            NORMALIZED_EPISODE_PLAN: normalized_plan,
            MAX_RETRIES: 10,
            ALL_SCRIPT: "",
            LAST_SUMMARY: "",
        }

    def _state_and_payload(
        self,
        total_episodes: int,
        *,
        variables: dict[str, object] | None = None,
    ) -> tuple[WorkflowState, WorkflowInput, dict[str, object]]:
        payload = _workflow_input(total_episodes)
        merged_variables = self._base_variables(total_episodes)
        if variables:
            merged_variables.update(variables)
        state = WorkflowState(user_input=payload, variables=dict(merged_variables))
        return state, payload, merged_variables

    def _script_ready_state(
        self,
        total_episodes: int,
        *,
        variables: dict[str, object] | None = None,
    ) -> tuple[WorkflowState, WorkflowInput, dict[str, object], list[BatchWindow]]:
        all_hooks: dict[str, object] = {}
        all_dialogues: dict[str, object] = {}
        for batch in iter_episode_batches(total_episodes, batch_size=5):
            episodes = list(range(batch.start_episode, batch.end_episode + 1))
            all_hooks = flow.merge_batch_object(all_hooks, _hook_batch(episodes))
            all_dialogues = flow.merge_batch_object(all_dialogues, _dialogue_batch(episodes))
        merged = {
            ALL_HOOKS: all_hooks,
            ALL_DIALOGUES: all_dialogues,
        }
        if variables:
            merged.update(variables)
        state, payload, base_variables = self._state_and_payload(total_episodes, variables=merged)
        batches = list(iter_episode_batches(total_episodes, batch_size=5))
        return state, payload, base_variables, batches

    def test_three_phase_order_runs_all_hooks_before_dialogues_and_script(self) -> None:
        state, payload, variables = self._state_and_payload(10)
        runner = _PhaseRecordingRunner()

        flow._run_batched_generation(state, runner, payload, variables)

        stages = [str(call["stage"]) for call in runner.calls]
        self.assertEqual(
            stages,
            [
                STAGE_HOOKS_WRITING,
                STAGE_HOOKS_REVIEW,
                STAGE_HOOKS_WRITING,
                STAGE_HOOKS_REVIEW,
                STAGE_DIALOGUES_WRITING,
                STAGE_DIALOGUES_REVIEW,
                STAGE_DIALOGUES_WRITING,
                STAGE_DIALOGUES_REVIEW,
                STAGE_SCRIPT_WRITING,
                STAGE_SCRIPT_REVIEW,
                STAGE_SCRIPT_MEMORY,
                STAGE_SCRIPT_WRITING,
                STAGE_SCRIPT_REVIEW,
                STAGE_SCRIPT_MEMORY,
            ],
        )
        self.assertEqual(
            [int(call["batch_start"]) for call in runner.stage_calls(STAGE_HOOKS_WRITING)],
            [1, 6],
        )
        self.assertEqual(
            [int(call["batch_start"]) for call in runner.stage_calls(STAGE_DIALOGUES_WRITING)],
            [1, 6],
        )
        self.assertTrue(
            all(
                call["hooks_episodes"] == list(range(1, 11))
                for call in runner.stage_calls(STAGE_DIALOGUES_WRITING)
            )
        )
        self.assertTrue(
            all(
                call["hooks_episodes"] == list(range(1, 11))
                for call in runner.stage_calls(STAGE_SCRIPT_WRITING)
            )
        )
        self.assertTrue(
            all(
                call["dialogue_episodes"] == list(range(1, 11))
                for call in runner.stage_calls(STAGE_SCRIPT_WRITING)
            )
        )
        self.assertEqual(len(runner.memory_calls()), 2)

    def test_dialogues_stage_requires_complete_hooks(self) -> None:
        state, payload, variables = self._state_and_payload(10)
        batches = list(iter_episode_batches(10, batch_size=5))

        with self.assertRaisesRegex(ValueError, "ALL_HOOKS"):
            flow._run_all_dialogue_batches(
                state,
                _PhaseRecordingRunner(),
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

    def test_script_stage_requires_complete_dialogues(self) -> None:
        variables = self._base_variables(10)
        variables[ALL_HOOKS] = flow.merge_batch_object(_hook_batch([1, 2, 3, 4, 5]), _hook_batch([6, 7, 8, 9, 10]))
        state, payload, variables = self._state_and_payload(10, variables=variables)
        batches = list(iter_episode_batches(10, batch_size=5))

        with self.assertRaisesRegex(ValueError, "ALL_DIALOGUES"):
            flow._run_all_script_batches(
                state,
                _PhaseRecordingRunner(),
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

    def test_resume_skips_completed_hooks_and_continues_from_dialogue_phase(self) -> None:
        complete_hooks = flow.merge_batch_object(
            _hook_batch([1, 2, 3, 4, 5]),
            _hook_batch([6, 7, 8, 9, 10]),
        )
        partial_dialogues = _dialogue_batch([1, 2, 3, 4, 5])
        state, payload, variables = self._state_and_payload(
            10,
            variables={
                ALL_HOOKS: complete_hooks,
                ALL_DIALOGUES: partial_dialogues,
                BATCH_DIALOGUES: partial_dialogues,
            },
        )
        runner = _PhaseRecordingRunner()

        flow._run_batched_generation(state, runner, payload, variables)

        stages = [str(call["stage"]) for call in runner.calls]
        self.assertEqual(
            stages,
            [
                STAGE_DIALOGUES_WRITING,
                STAGE_DIALOGUES_REVIEW,
                STAGE_SCRIPT_WRITING,
                STAGE_SCRIPT_REVIEW,
                STAGE_SCRIPT_MEMORY,
                STAGE_SCRIPT_WRITING,
                STAGE_SCRIPT_REVIEW,
                STAGE_SCRIPT_MEMORY,
            ],
        )
        self.assertEqual(
            [int(call["batch_start"]) for call in runner.stage_calls(STAGE_DIALOGUES_WRITING)],
            [6],
        )

    def test_restored_progress_prefers_dialogue_phase_after_hooks_complete(self) -> None:
        complete_hooks = flow.merge_batch_object(
            _hook_batch([1, 2, 3, 4, 5]),
            _hook_batch([6, 7, 8, 9, 10]),
        )
        partial_dialogues = _dialogue_batch([1, 2, 3, 4, 5])
        variables = self._base_variables(10)
        variables[ALL_HOOKS] = complete_hooks
        variables[ALL_DIALOGUES] = partial_dialogues
        batches = list(iter_episode_batches(10, batch_size=5))

        start_episode, completed_batches = flow._derive_restored_batch_progress(
            variables,
            batches=batches,
            current_stage="",
            rewrite_stage="",
        )

        self.assertEqual(start_episode, 6)
        self.assertEqual(completed_batches, 1)

    def test_final_guard_rejects_when_script_has_missing_episodes(self) -> None:
        variables = self._base_variables(10)
        variables[ALL_HOOKS] = flow.merge_batch_object(
            _hook_batch([1, 2, 3, 4, 5]),
            _hook_batch([6, 7, 8, 9, 10]),
        )
        variables[ALL_DIALOGUES] = flow.merge_batch_object(
            _dialogue_batch([1, 2, 3, 4, 5]),
            _dialogue_batch([6, 7, 8, 9, 10]),
        )
        variables[ALL_SCRIPT] = _script_batch_text([1, 2, 3, 4, 5])
        payload = _workflow_input(10)

        with self.assertRaisesRegex(ValueError, "剧本正文存在缺集"):
            flow._ensure_complete_batched_outputs_before_final(payload, variables)

    def test_review_failure_triggers_rewrite_but_pass_stops_extra_rewrites(self) -> None:
        state, payload, variables = self._state_and_payload(5)
        runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_HOOKS_REVIEW: [False, True],
                STAGE_DIALOGUES_REVIEW: [True],
                STAGE_SCRIPT_REVIEW: [True],
            }
        )

        flow._run_batched_generation(state, runner, payload, variables)

        self.assertEqual(len(runner.stage_calls(STAGE_HOOKS_REWRITE)), 1)
        self.assertEqual(len(runner.stage_calls(STAGE_DIALOGUES_REWRITE)), 0)
        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 0)
        self.assertEqual(len(runner.stage_calls(STAGE_HOOKS_REVIEW)), 2)

    def test_review_loop_exhaustion_raises_without_polluting_committed_outputs(self) -> None:
        state, payload, variables = self._state_and_payload(5)
        settings.fastgpt_stage_review_revise_max_loops = 3
        runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_HOOKS_REVIEW: [False, False, False],
            }
        )

        with self.assertRaisesRegex(ValueError, "开头冲突钩子 1-5 集审核未通过"):
            flow._run_batched_generation(state, runner, payload, variables)

        self.assertNotIn(ALL_HOOKS, variables)
        self.assertNotIn(ALL_DIALOGUES, variables)
        self.assertEqual(str(variables.get(ALL_SCRIPT, "") or "").strip(), "")
        self.assertEqual(len(runner.stage_calls(STAGE_HOOKS_REVIEW)), 3)
        self.assertEqual(len(runner.stage_calls(STAGE_HOOKS_REWRITE)), 2)

    def test_continue_after_failed_batch_restarts_same_phase_same_batch(self) -> None:
        state, payload, variables = self._state_and_payload(10)
        settings.fastgpt_stage_review_revise_max_loops = 1
        failing_runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_HOOKS_REVIEW: [False],
            }
        )

        with self.assertRaisesRegex(ValueError, "开头冲突钩子 1-5 集审核未通过"):
            flow._run_batched_generation(state, failing_runner, payload, variables)

        self.assertEqual(variables[BATCH_START_EPISODE], 1)
        self.assertEqual(variables.get(flow.LOCAL_CURRENT_BATCH_STAGE), "hook")
        self.assertNotIn(ALL_HOOKS, variables)

        settings.fastgpt_stage_review_revise_max_loops = 10
        resumed_runner = _PhaseRecordingRunner()
        flow._run_batched_generation(state, resumed_runner, payload, variables)

        self.assertEqual(
            [int(call["batch_start"]) for call in resumed_runner.stage_calls(STAGE_HOOKS_WRITING)],
            [1, 6],
        )

    def test_script_batch_local_validation_blocks_duplicate_episode_headings(self) -> None:
        state, payload, variables = self._state_and_payload(5)
        settings.fastgpt_stage_review_revise_max_loops = 1
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_SCRIPT_WRITING: [
                    {
                        BATCH_SCRIPT: "\n\n".join(
                            [
                                "第1集：\n场景一：第1集正文",
                                "第1集：\n场景一：重复的第1集正文",
                                "第2集：\n场景一：第2集正文",
                                "第3集：\n场景一：第3集正文",
                                "第4集：\n场景一：第4集正文",
                            ]
                        )
                    }
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "剧本正文 1-5 集审核未通过"):
            flow._run_batched_generation(state, runner, payload, variables)

        self.assertEqual(len(runner.memory_calls()), 0)
        self.assertEqual(str(variables.get(ALL_SCRIPT, "") or "").strip(), "")

    def test_final_guard_rejects_duplicate_hook_episodes(self) -> None:
        variables = self._base_variables(10)
        variables[ALL_HOOKS] = {
            "batch_meta": {"start_episode": 1, "end_episode": 10},
            "global_hook_engine": {"batch_label": "1-10"},
            "episodes": [
                {"episode": 1, "hook": "第1集钩子-A"},
                {"episode": 1, "hook": "第1集钩子-B"},
                {"episode": 2, "hook": "第2集钩子"},
                {"episode": 3, "hook": "第3集钩子"},
                {"episode": 4, "hook": "第4集钩子"},
                {"episode": 5, "hook": "第5集钩子"},
                {"episode": 6, "hook": "第6集钩子"},
                {"episode": 7, "hook": "第7集钩子"},
                {"episode": 8, "hook": "第8集钩子"},
                {"episode": 9, "hook": "第9集钩子"},
                {"episode": 10, "hook": "第10集钩子"},
            ],
        }
        variables[ALL_DIALOGUES] = flow.merge_batch_object(
            _dialogue_batch([1, 2, 3, 4, 5]),
            _dialogue_batch([6, 7, 8, 9, 10]),
        )
        variables[ALL_SCRIPT] = _script_batch_text([1, 2, 3, 4, 5]) + "\n\n" + _script_batch_text(
            [6, 7, 8, 9, 10]
        )
        payload = _workflow_input(10)

        with self.assertRaisesRegex(ValueError, "开头冲突钩子存在重复集"):
            flow._ensure_complete_batched_outputs_before_final(payload, variables)


    def test_script_write_stores_current_batch_var_and_review_var(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        runner = _PhaseRecordingRunner()

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertIn("1", str(variables.get(SCRIPT_CURRENT_VAR) or ""))
        self.assertIn("passed", str(variables.get(SCRIPT_REVIEW_OUTPUT_VAR) or ""))
        self.assertIn("1", str(variables.get(ALL_SCRIPT) or ""))

    def test_script_review_failure_runs_revise_then_reviews_again(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        runner = _PhaseRecordingRunner(
            review_sequences={STAGE_SCRIPT_REVIEW: [False, True]}
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 1)
        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REVIEW)), 2)

    def test_script_review_unparseable_counts_as_failure(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        settings.fastgpt_stage_review_revise_max_loops = 1
        runner = _PhaseRecordingRunner(
            review_sequences={STAGE_SCRIPT_REVIEW: [ValueError("not json")]}
        )

        with self.assertRaisesRegex(ValueError, "1-5"):
            flow._run_all_script_batches(
                state,
                runner,
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REVIEW)), 1)
        self.assertEqual(str(variables.get(ALL_SCRIPT, "") or "").strip(), "")

    def test_script_review_passed_with_blocking_issues_revises(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_SCRIPT_REVIEW: [
                    {
                        "passed": True,
                        "rewrite_required": False,
                        "blocking_issues": ["still broken"],
                        "non_blocking_issues": [],
                    },
                    True,
                ]
            }
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(len(runner.stage_calls(STAGE_SCRIPT_REWRITE)), 1)

    def test_script_revise_output_that_is_not_script_is_rejected(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        settings.fastgpt_stage_review_revise_max_loops = 2
        runner = _PhaseRecordingRunner(
            review_sequences={STAGE_SCRIPT_REVIEW: [False, True]},
            stage_outputs={
                STAGE_SCRIPT_REWRITE: [
                    {
                        BATCH_SCRIPT: json.dumps(
                            {"passed": True, "blocking_issues": []},
                            ensure_ascii=False,
                        )
                    }
                ]
            },
        )

        with self.assertRaisesRegex(ValueError, "1-5"):
            flow._run_all_script_batches(
                state,
                runner,
                payload,
                variables,
                batches=batches,
                normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
                episode_alias_plan=None,
                rewrite_from_stage="",
            )

        self.assertEqual(str(variables.get(ALL_SCRIPT, "") or "").strip(), "")

    def test_script_out_of_range_and_missing_episode_are_rejected(self) -> None:
        issues = flow._validate_script_batch_output(
            _script_batch_text([1, 2, 3, 4, 6]),
            batch=BatchWindow(start_episode=1, end_episode=5),
        )
        joined = "\n".join(issues)
        self.assertIn("out-of-window", joined)
        self.assertIn("missing", joined)

    def test_script_memory_updates_memory_var_and_invalid_memory_falls_back(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        runner = _PhaseRecordingRunner(
            stage_outputs={STAGE_SCRIPT_MEMORY: [{LAST_SUMMARY: "not json"}]}
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        memory = json.loads(str(variables[LAST_SUMMARY]))
        self.assertIn("final_hook_of_this_turn", memory)
        self.assertIn("must_carry_into_next_turn", memory)
        self.assertIn("appearance_continuity_summary", memory)
        self.assertEqual(state.get_var(MEMORY_VAR), variables[LAST_SUMMARY])

    def test_script_resume_does_not_rewrite_committed_batch(self) -> None:
        committed = _script_batch_text([1, 2, 3, 4, 5])
        committed_map = flow._extract_script_episode_map(
            committed,
            BatchWindow(start_episode=1, end_episode=5),
        )
        state, payload, variables, batches = self._script_ready_state(
            10,
            variables={
                flow.LOCAL_SCRIPT_BATCHES: {"1": committed},
                flow.LOCAL_SUMMARY_BY_BATCH: {
                    "1": json.dumps(
                        {
                            "final_hook_of_this_turn": "",
                            "must_carry_into_next_turn": [],
                            "appearance_continuity_summary": "",
                        }
                    )
                },
                flow.LOCAL_SCRIPT_EPISODES: flow._string_keyed_batch_map(committed_map),
            },
        )
        runner = _PhaseRecordingRunner()

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(
            [int(call["batch_start"]) for call in runner.stage_calls(STAGE_SCRIPT_WRITING)],
            [6],
        )

    def test_review_parser_accepts_alias_wrappers_and_rejects_natural_language(self) -> None:
        passed = {
            "passed": True,
            "rewrite_required": False,
            "blocking_issues": [],
            "non_blocking_issues": [],
        }
        for alias in (
            HOOK_REVIEW_OUTPUT_VAR,
            DIALOGUE_REVIEW_WORKFLOW_VAR,
            DIALOGUE_REVIEW_LEGACY_VAR,
            SCRIPT_REVIEW_WRITE_VAR,
            SCRIPT_REVIEW_OUTPUT_VAR,
        ):
            decision = flow.parse_review_result({alias: json.dumps(passed)})
            self.assertTrue(decision.passed, alias)
            self.assertFalse(decision.rewrite_required, alias)

        blocked = flow.parse_review_result(
            {
                SCRIPT_REVIEW_OUTPUT_VAR: json.dumps(
                    {
                        "passed": True,
                        "rewrite_required": False,
                        "blocking_issues": ["bad"],
                        "non_blocking_issues": [],
                    }
                )
            }
        )
        self.assertFalse(blocked.passed)
        self.assertTrue(blocked.rewrite_required)

        natural = flow.parse_review_result("looks good overall")
        self.assertFalse(natural.passed)
        self.assertTrue(natural.rewrite_required)

    def test_hook_alias_write_review_and_memory_answer_text(self) -> None:
        state, payload, variables = self._state_and_payload(5)
        batches = list(iter_episode_batches(5, batch_size=5))
        memory_json = json.dumps(
            {
                "final_hook_of_this_turn": "hook end",
                "must_carry_into_next_turn": [],
                "appearance_alias_continuity_summary": "alias ok",
            },
            ensure_ascii=False,
        )
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_HOOKS_WRITING: [{HOOK_CURRENT_WRITE_VAR: _hook_batch([1, 2, 3, 4, 5])}],
                STAGE_HOOK_MEMORY: [{"answerText": memory_json}],
            }
        )

        flow._run_all_hook_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(_episode_numbers_from_object(variables[BATCH_HOOKS]), [1, 2, 3, 4, 5])
        review_call = runner.stage_calls(STAGE_HOOKS_REVIEW)[0]
        self.assertEqual(review_call["hook_write_alias_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(review_call["hook_review_alias_episodes"], [1, 2, 3, 4, 5])
        self.assertIn("final_hook_of_this_turn", str(variables[flow.HOOK_MEMORY]))

    def test_hook_local_validation_rejects_missing_out_of_range_and_duplicate(self) -> None:
        batch = BatchWindow(start_episode=1, end_episode=5)
        bad_missing = _hook_batch([1, 2, 3, 4])
        bad_out = _hook_batch([1, 2, 3, 4, 6])
        bad_dup = _hook_batch([1, 1, 2, 3, 4])
        self.assertTrue(flow.validate_batch_hooks(bad_missing, batch))
        self.assertTrue(flow.validate_batch_hooks(bad_out, batch))
        self.assertTrue(flow.validate_batch_hooks(bad_dup, batch))

    def test_dialogue_alias_write_review_memory_and_bad_revise_contract(self) -> None:
        state, payload, variables = self._state_and_payload(
            5,
            variables={ALL_HOOKS: _hook_batch([1, 2, 3, 4, 5])},
        )
        batches = list(iter_episode_batches(5, batch_size=5))
        memory_json = json.dumps(
            {
                "dialogue_voice_summary": "voice ok",
                "must_carry_into_next_turn": [],
                "alias_usage_continuity": "alias ok",
            },
            ensure_ascii=False,
        )
        runner = _PhaseRecordingRunner(
            stage_outputs={
                STAGE_DIALOGUES_WRITING: [
                    {DIALOGUE_CURRENT_WRITE_VAR: _dialogue_batch([1, 2, 3, 4, 5])}
                ],
                STAGE_DIALOGUE_MEMORY: [{"answerText": memory_json}],
            }
        )

        flow._run_all_dialogue_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertEqual(_episode_numbers_from_object(variables[BATCH_DIALOGUES]), [1, 2, 3, 4, 5])
        review_call = runner.stage_calls(STAGE_DIALOGUES_REVIEW)[0]
        self.assertEqual(review_call["dialogue_write_alias_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(review_call["dialogue_workflow_alias_episodes"], [1, 2, 3, 4, 5])
        self.assertIn("dialogue_voice_summary", str(variables[flow.DIALOGUE_MEMORY]))

        bad_revise = {
            "dialogue_voice_summary": "memory",
            "must_carry_into_next_turn": [],
            "alias_usage_continuity": "alias",
        }
        issues = flow.validate_batch_dialogues(bad_revise, BatchWindow(start_episode=1, end_episode=5))
        self.assertIn("角色对话修订 workflow 输出契约错误", "\n".join(issues))

    def test_dialogue_bad_batch_is_rejected(self) -> None:
        batch = BatchWindow(start_episode=1, end_episode=5)
        bad_missing = _dialogue_batch([1, 2, 3, 4])
        bad_out = _dialogue_batch([1, 2, 3, 4, 6])
        bad_dup = _dialogue_batch([1, 1, 2, 3, 4])
        bad_empty = _dialogue_batch([1, 2, 3, 4, 5])
        bad_empty["episode_dialogue_blocks"][0]["participants"] = []
        self.assertTrue(flow.validate_batch_dialogues(bad_missing, batch))
        self.assertTrue(flow.validate_batch_dialogues(bad_out, batch))
        self.assertTrue(flow.validate_batch_dialogues(bad_dup, batch))
        self.assertTrue(flow.validate_batch_dialogues(bad_empty, batch))

    def test_script_alias_write_review_revise_and_memory_aliases(self) -> None:
        state, payload, variables, batches = self._script_ready_state(5)
        memory_json = json.dumps(
            {
                "final_hook_of_this_turn": "script end",
                "must_carry_into_next_turn": [],
                "appearance_continuity_summary": "appearance ok",
            },
            ensure_ascii=False,
        )
        runner = _PhaseRecordingRunner(
            review_sequences={
                STAGE_SCRIPT_REVIEW: [
                    {
                        "passed": False,
                        "rewrite_required": True,
                        "blocking_issues": ["revise"],
                        "non_blocking_issues": [],
                    },
                    {SCRIPT_REVIEW_WRITE_VAR: json.dumps({
                        "passed": True,
                        "rewrite_required": False,
                        "blocking_issues": [],
                        "non_blocking_issues": [],
                    })},
                ]
            },
            stage_outputs={
                STAGE_SCRIPT_WRITING: [{SCRIPT_CURRENT_WRITE_VAR: _script_batch_text([1, 2, 3, 4, 5])}],
                STAGE_SCRIPT_REWRITE: [{SCRIPT_CURRENT_VAR: _script_batch_text([1, 2, 3, 4, 5])}],
                STAGE_SCRIPT_MEMORY: [{SCRIPT_MEMORY_OUTPUT_VAR: memory_json}],
            },
        )

        flow._run_all_script_batches(
            state,
            runner,
            payload,
            variables,
            batches=batches,
            normalized_plan=variables[NORMALIZED_EPISODE_PLAN],
            episode_alias_plan=None,
            rewrite_from_stage="",
        )

        self.assertIn("第1集", str(variables[BATCH_SCRIPT]))
        review_call = runner.stage_calls(STAGE_SCRIPT_REVIEW)[0]
        rewrite_call = runner.stage_calls(STAGE_SCRIPT_REWRITE)[0]
        self.assertIn("第1集", review_call["script_write_alias_text"])
        self.assertIn("revise", rewrite_call["script_review_alias_text"])
        self.assertIn("appearance_continuity_summary", str(variables[flow.SCRIPT_MEMORY]))

    def test_script_local_validation_rejects_json_report_missing_out_of_range_duplicate(self) -> None:
        batch = BatchWindow(start_episode=1, end_episode=5)
        cases = [
            json.dumps({"batch_script": "no"}),
            "审核报告\npassed: true",
            _script_batch_text([1, 2, 3, 4]),
            _script_batch_text([1, 2, 3, 4, 6]),
            _script_batch_text([1, 1, 2, 3, 4]),
        ]
        for case in cases:
            self.assertTrue(flow.validate_batch_script_text(case, batch), case)

    def test_merge_and_complete_helpers(self) -> None:
        hooks = flow.merge_batch_hooks({}, _hook_batch([1, 2, 3, 4, 5]), BatchWindow(1, 5))
        hooks = flow.merge_batch_hooks(hooks, _hook_batch([6, 7, 8, 9, 10]), BatchWindow(6, 10))
        dialogues = flow.merge_batch_dialogues({}, _dialogue_batch([1, 2, 3, 4, 5]), BatchWindow(1, 5))
        dialogues = flow.merge_batch_dialogues(dialogues, _dialogue_batch([6, 7, 8, 9, 10]), BatchWindow(6, 10))
        script = flow.merge_batch_script("", _script_batch_text([1, 2, 3, 4, 5]), BatchWindow(1, 5))
        script = flow.merge_batch_script(script, _script_batch_text([6, 7, 8, 9, 10]), BatchWindow(6, 10))
        flow.assert_complete_hooks(hooks, 10)
        flow.assert_complete_dialogues(dialogues, 10)
        flow.assert_complete_script(script, 10)


if __name__ == "__main__":
    unittest.main()
