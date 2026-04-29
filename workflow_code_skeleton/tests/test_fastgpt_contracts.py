from __future__ import annotations

from pathlib import Path
import json
import unittest

from workflow_code_skeleton.app.services.fastgpt_contracts import (
    CHARACTER_SEARCH_INTENT,
    STAGE_APPEARANCE_ALIAS_REVIEW,
    STAGE_APPEARANCE_ALIAS_REWRITE,
    STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
    STAGE_APPEARANCE_ALIAS_WRITING,
    STAGE_APPEARANCE_PRE_STRATEGY,
    STAGE_CHARACTERS,
    STAGE_CONSISTENCY,
    STAGE_DIALOGUES_REVIEW,
    STAGE_DIALOGUES_REWRITE,
    STAGE_DIALOGUES_WRITING,
    STAGE_EPISODE_PLAN_NORMALIZE,
    STAGE_FINAL,
    STAGE_FRAMEWORK,
    STAGE_FRAMEWORK_NATURALIZE,
    STAGE_HOOKS_REVIEW,
    STAGE_HOOKS_REWRITE,
    STAGE_HOOKS_WRITING,
    STAGE_SCENES,
    STAGE_SCRIPT_MEMORY,
    STAGE_SCRIPT_REVIEW,
    STAGE_SCRIPT_REWRITE,
    STAGE_SCRIPT_WRITING,
    STAGE_WORLDVIEW,
    STAGE_WORLDVIEW_NATURALIZE,
    LEGACY_INPUT_ALIASES,
    STAGE_CONTRACTS,
    contract_for,
)


class FastGPTContractsTestCase(unittest.TestCase):
    def test_direct_fastgpt_stages_declare_workflow_json_name(self) -> None:
        direct_stages = (
            STAGE_FRAMEWORK,
            STAGE_FRAMEWORK_NATURALIZE,
            STAGE_APPEARANCE_PRE_STRATEGY,
            STAGE_CONSISTENCY,
            STAGE_EPISODE_PLAN_NORMALIZE,
            STAGE_WORLDVIEW,
            STAGE_WORLDVIEW_NATURALIZE,
            STAGE_CHARACTERS,
            STAGE_SCENES,
            STAGE_APPEARANCE_ALIAS_WRITING,
            STAGE_APPEARANCE_ALIAS_REVIEW,
            STAGE_APPEARANCE_ALIAS_REWRITE,
            STAGE_APPEARANCE_ALIAS_UNSTRUCTURED,
            STAGE_HOOKS_WRITING,
            STAGE_HOOKS_REVIEW,
            STAGE_HOOKS_REWRITE,
            STAGE_DIALOGUES_WRITING,
            STAGE_DIALOGUES_REVIEW,
            STAGE_DIALOGUES_REWRITE,
            STAGE_SCRIPT_WRITING,
            STAGE_SCRIPT_REVIEW,
            STAGE_SCRIPT_REWRITE,
            STAGE_SCRIPT_MEMORY,
            STAGE_FINAL,
        )
        for stage_name in direct_stages:
            contract = contract_for(stage_name)
            self.assertTrue(
                str(contract.workflow_json_name or "").strip(),
                msg=f"{stage_name} should declare workflow_json_name",
            )

    def test_env_example_documents_current_stage_keys(self) -> None:
        env_text = Path("workflow_code_skeleton/.env.example").read_text(encoding="utf-8")
        self.assertIn("FASTGPT_STAGE_FORMAT_RETRY_LIMIT=3", env_text)
        self.assertIn("FASTGPT_STAGE_REVIEW_REVISE_MAX_LOOPS=10", env_text)
        self.assertIn("FASTGPT_APPEARANCE_ALIAS_WRITING_API_KEY=fastgpt-", env_text)
        self.assertIn("FASTGPT_APPEARANCE_ALIAS_REVIEW_API_KEY=fastgpt-", env_text)
        self.assertIn("FASTGPT_APPEARANCE_ALIAS_REWRITE_API_KEY=fastgpt-", env_text)
        self.assertIn("FASTGPT_APPEARANCE_ALIAS_UNSTRUCTURED_API_KEY=fastgpt-", env_text)
        self.assertIn("FASTGPT_SCRIPT_MEMORY_API_KEY=fastgpt-", env_text)
        self.assertNotIn("FASTGPT_SCRIPT_MEMORY_API_KEY==", env_text)

    def test_characters_stage_accepts_optional_search_intent_input(self) -> None:
        contract = contract_for(STAGE_CHARACTERS)

        self.assertIn(CHARACTER_SEARCH_INTENT, contract.input_names)
        payload = contract.build_input_payload({
            "user_characters": "人物小传",
            "worldview": "世界观",
            "story_outline": "故事大纲",
        })

        self.assertEqual(payload[CHARACTER_SEARCH_INTENT], "")

    def test_main_workflow_public_inputs_are_covered_by_contract_aliases(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        for stage_name, contract in STAGE_CONTRACTS.items():
            workflow_json_name = str(contract.workflow_json_name or "").strip()
            if not workflow_json_name:
                continue
            workflow_path = next(repo_root.rglob(workflow_json_name), None)
            self.assertIsNotNone(workflow_path, msg=f"missing workflow json: {workflow_json_name}")
            data = json.loads(workflow_path.read_text(encoding="utf-8-sig"))
            public_input_keys = [
                item.get("key")
                for item in data.get("chatConfig", {}).get("variables", [])
                if item.get("type") in {"input", "numberInput"} and item.get("key")
            ]
            covered_keys: set[str] = set()
            for alias in LEGACY_INPUT_ALIASES.get(stage_name, {}).values():
                if isinstance(alias, tuple):
                    covered_keys.update(str(item) for item in alias)
                else:
                    covered_keys.add(str(alias))
            missing = [key for key in public_input_keys if key not in covered_keys]
            self.assertEqual(
                missing,
                [],
                msg=f"{stage_name} public inputs not covered by contract aliases: {missing}",
            )


if __name__ == "__main__":
    unittest.main()
