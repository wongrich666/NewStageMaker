from __future__ import annotations

from pathlib import Path
import unittest

from workflow_code_skeleton.app.services.fastgpt_contracts import (
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


if __name__ == "__main__":
    unittest.main()
