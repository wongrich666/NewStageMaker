from __future__ import annotations

from pathlib import Path
import json
import unittest

from workflow_code_skeleton.app.services.fastgpt_contracts import (
    APPEARANCE_MAPPING,
    BATCH_SCRIPT,
    BATCH_START_EPISODE,
    CHARACTERS,
    EPISODE_PLAN,
    EPISODE_WORD_COUNT,
    LEGACY_WIRE_INPUT_ALIASES_OVERRIDES,
    SCRIPT_MEMORY,
    WORLDVIEW,
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
    STAGE_CHARACTERS_NATURALIZE,
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
    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[2]

    def test_direct_fastgpt_stages_declare_workflow_json_name(self) -> None:
        direct_stages = (
            STAGE_FRAMEWORK,
            STAGE_FRAMEWORK_NATURALIZE,
            STAGE_CHARACTERS_NATURALIZE,
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
        env_text = (self._repo_root() / "workflow_code_skeleton" / ".env.example").read_text(encoding="utf-8")
        self.assertIn("WORKFLOW_BACKEND=coze", env_text)
        self.assertIn("COZE_API_BASE=https://api.coze.cn", env_text)
        self.assertIn("COZE_PRIMARY_API_TOKEN=", env_text)
        self.assertIn("COZE_SECONDARY_API_TOKEN=", env_text)
        self.assertIn("BETTER_FRAMEWORK_JSONS_DIR=", env_text)
        for stage in ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10"):
            self.assertIn(f"COZE_WORKFLOW_STAGE_{stage}_ID=", env_text)
        for stage in ("11_WRITE", "11_REVIEW", "11_REWRITE", "11_MEMORY", "12_WRITE", "12_REVIEW", "12_REWRITE", "12_MEMORY"):
            self.assertIn(f"COZE_WORKFLOW_STAGE_{stage}_ID=", env_text)

    def test_contract_markdown_documents_unstructured_workflow_variables_and_character_export_priority(self) -> None:
        markdown = (self._repo_root() / "workflow_code_skeleton" / "FASTGPT_CONTRACTS.md").read_text(encoding="utf-8")

        self.assertIn("w2RJzalk", markdown)
        self.assertIn("unstructuredContentKind", markdown)
        self.assertIn("zxlaPMOY", markdown)
        self.assertIn("character_natural_language / dT7mQ2Nz 优先", markdown)
        self.assertIn("fFM0mroW / character_setting.characters 兜底", markdown)

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
        repo_root = self._repo_root()
        for stage_name, contract in STAGE_CONTRACTS.items():
            workflow_json_name = str(contract.workflow_json_name or "").strip()
            if not workflow_json_name:
                continue
            workflow_path = next(repo_root.rglob(workflow_json_name), None)
            if workflow_path is None:
                continue
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

    def test_script_review_declares_narrow_wire_override(self) -> None:
        self.assertEqual(
            LEGACY_WIRE_INPUT_ALIASES_OVERRIDES.get(STAGE_SCRIPT_REVIEW),
            {
                WORLDVIEW: "yuozoGpo",
                CHARACTERS: "fFM0mroW",
                APPEARANCE_MAPPING: "h2KpLm91",
                EPISODE_PLAN: "pxtQY7p2",
                SCRIPT_MEMORY: "dzt6kORx",
                BATCH_SCRIPT: "zS2LXibg",
                EPISODE_WORD_COUNT: "eBEWC07Q",
                BATCH_START_EPISODE: "d4sfifeZ",
            },
        )


if __name__ == "__main__":
    unittest.main()
