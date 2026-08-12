from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from workflow_code_skeleton.app.server import create_app
from workflow_code_skeleton.app.services.character_image_prompt_service import (
    SCHEMA_VERSION,
    build_character_image_prompt_inputs,
    extract_character_catalog,
    generate_character_image_prompt,
    normalize_character_image_prompt,
)
from workflow_code_skeleton.app.services.tencent_workflow_registry import (
    TENCENT_WORKFLOWS,
    build_workflow_inputs,
)


def sample_asset() -> dict:
    return {
        "asset_id": "22",
        "title": "测试项目",
        "framework_plan_package": {
            "worldview_plan": {
                "world_type": "架空古代",
                "tone": "克制写实",
                "visual_style": "低饱和国风",
            },
            "character_plan": {
                "characters": [
                    {
                        "id": "hero",
                        "name": "苏砚",
                        "role": "protagonist",
                        "identity": "26岁的现代策划，意外穿越到古代",
                        "external_goal": "生存并寻找归途",
                        "internal_need": "重新学会信任",
                        "growth_arc": "从防备到主动承担",
                        "forbidden_write": ["不能拥有无来源的超能力"],
                    }
                ]
            },
        },
        "scriptStages": {
            "stage08": {
                "sceneDictionary": {
                    "core_scenes": [
                        {
                            "scene_id": "scene_A",
                            "name": "古代市井",
                            "visual_anchor": "青石路、木质摊位、自然暖光",
                            "common_characters": ["苏砚"],
                            "key_props": ["磨损的布包", "铜钱"],
                        }
                    ]
                }
            },
            "stage09": {
                "appearanceMapping": {
                    "characters": [
                        {
                            "character_id": "hero",
                            "name": "苏砚",
                            "identity": "26岁现代策划",
                            "personality": "理性克制，略显疲惫",
                            "appearance_anchor": "黑色短发，清瘦，目光警觉",
                            "outfit_variants": [
                                {
                                    "version_id": "A",
                                    "version_name": "市井日常",
                                    "episode_range": "第1-10集",
                                    "clothing": "米白内衫与墨绿旧外袍",
                                    "visual_anchor": "低饱和、轻微磨损",
                                    "scene_refs": ["scene_A"],
                                }
                            ],
                        }
                    ]
                }
            },
            "stage10": {
                "allEnrichedEpisodePlan": [
                    {
                        "episode": 1,
                        "title": "初入市井",
                        "characters": ["苏砚(A)"],
                        "scene_refs": ["scene_A"],
                        "scenes": ["古代市井"],
                        "specific_plot": "苏砚背着布包寻找落脚点。",
                    }
                ]
            },
            "stage12": {
                "batches": {
                    "1": {
                        "batchScriptText": (
                            "第1集：初入市井\n角色：苏砚(A)\n场景：古代市井\n"
                            "道具：磨损的布包、三枚铜钱\n苏砚观察四周。"
                        )
                    }
                }
            },
        },
    }


def workflow_result() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "character_id": "hero",
        "character_name": "苏砚",
        "outfit_id": "A",
        "design_summary": "克制疲惫的现代女性落入古代市井。",
        "positive_prompt": "单人全身角色设定图，26岁清瘦女性，黑色短发，墨绿旧外袍。",
        "negative_prompt": "多人，现代拉链，华丽宫装，多余手指。",
        "continuity_lock": {
            "immutable_features": ["黑色短发", "清瘦身形"],
            "outfit_features": ["米白内衫", "墨绿旧外袍"],
            "forbidden_drift": ["不能变成长发", "不能出现现代鞋服"],
        },
        "recommended_views": [
            {"view_type": "正面全身", "prompt_suffix": "正面自然站姿，完整展示服装层次"}
        ],
        "design_notes": [],
        "source_trace": {"used_props": ["磨损的布包"]},
    }


class FakeClient:
    def __init__(self) -> None:
        self.stage = ""
        self.variables = {}

    def run_raw(self, stage_name: str, variables: dict) -> dict:
        self.stage = stage_name
        self.variables = dict(variables)
        return {"Output": {"character_image_prompt": json.dumps(workflow_result(), ensure_ascii=False)}}


class CharacterImagePromptTests(unittest.TestCase):
    def test_catalog_merges_character_and_appearance_sources(self) -> None:
        catalog = extract_character_catalog(sample_asset())

        self.assertEqual("测试项目", catalog["project_title"])
        self.assertEqual(1, len(catalog["characters"]))
        character = catalog["characters"][0]
        self.assertEqual("hero", character["character_id"])
        self.assertEqual("苏砚", character["character_name"])
        self.assertEqual("A", character["outfits"][0]["outfit_id"])
        self.assertTrue(catalog["source_status"]["has_script_text"])

    def test_workflow_inputs_are_character_scoped_and_include_props(self) -> None:
        variables, summary = build_character_image_prompt_inputs(
            sample_asset(),
            character_id="hero",
            selected_outfit_id="A",
            user_visual_requirements="避免网红脸",
        )

        self.assertEqual("苏砚", variables["character_name"])
        self.assertEqual("A", variables["selected_outfit_id"])
        self.assertIn("避免网红脸", variables["user_visual_requirements"])
        self.assertIn("磨损的布包", variables["scene_prop_context"])
        self.assertIn("墨绿旧外袍", variables["appearance_mapping"])
        self.assertEqual(1, summary["related_episode_count"])
        self.assertGreater(summary["prop_count"], 0)

    def test_nested_tencent_output_is_normalized(self) -> None:
        raw = {"Output": {"character_image_prompt": json.dumps(workflow_result(), ensure_ascii=False)}}
        result = normalize_character_image_prompt(
            raw,
            expected_character={"character_id": "hero", "character_name": "苏砚", "outfit_id": "A"},
        )

        self.assertEqual(SCHEMA_VERSION, result["schema_version"])
        self.assertIn("黑色短发", result["positive_prompt"])
        self.assertEqual("米白内衫", result["continuity_lock"]["outfit_features"][0])

    def test_generator_calls_the_new_workflow_with_exact_inputs(self) -> None:
        client = FakeClient()
        result, summary = generate_character_image_prompt(
            sample_asset(), character_id="hero", selected_outfit_id="A",
            user_visual_requirements="国风写实", client=client,
        )

        self.assertEqual("character_image_prompt", client.stage)
        self.assertEqual(set(TENCENT_WORKFLOWS["character_image_prompt"].input_names), set(client.variables))
        self.assertEqual("国风写实", client.variables["user_visual_requirements"])
        self.assertEqual("苏砚", result["character_name"])
        self.assertEqual("A", summary["selected_outfit"]["outfit_id"])

    def test_registry_matches_documented_remote_contract(self) -> None:
        spec = TENCENT_WORKFLOWS["character_image_prompt"]
        self.assertEqual(
            (
                "project_title", "character_name", "user_visual_requirements", "character_source_profile",
                "appearance_mapping", "scene_prop_context", "selected_outfit_id",
            ),
            spec.input_names,
        )
        self.assertEqual(("character_image_prompt",), spec.response_fields)
        self.assertEqual("TENCENT_WORKFLOW_CHARACTER_IMAGE_PROMPT_API_KEY", spec.api_key_env)
        values = build_workflow_inputs("character_image_prompt", {
            "project_title": "测试", "character_name": "苏砚", "user_visual_requirements": "写实",
            "character_source_profile": "{}", "appearance_mapping": "{}", "scene_prop_context": "{}",
            "selected_outfit_id": "A",
        })
        self.assertTrue(all(isinstance(value, str) for value in values.values()))

    def test_missing_positive_prompt_is_rejected(self) -> None:
        value = workflow_result()
        value["positive_prompt"] = ""
        with self.assertRaisesRegex(ValueError, "positive_prompt"):
            normalize_character_image_prompt(value, expected_character={})

    def test_wrong_schema_or_wrong_character_is_rejected(self) -> None:
        wrong_schema = workflow_result()
        wrong_schema["schema_version"] = "unknown"
        with self.assertRaisesRegex(ValueError, "schema_version"):
            normalize_character_image_prompt(wrong_schema, expected_character={"character_name": "苏砚"})

        wrong_character = workflow_result()
        wrong_character["character_name"] = "另一个角色"
        with self.assertRaisesRegex(ValueError, "错误角色"):
            normalize_character_image_prompt(wrong_character, expected_character={"character_name": "苏砚"})

    @patch("workflow_code_skeleton.app.server.auth_store.get_user_by_token")
    def test_authenticated_page_renders(self, get_user_by_token) -> None:
        get_user_by_token.return_value = SimpleNamespace(id=7, username="tester")
        app = create_app()
        app.config.update(TESTING=True)

        response = app.test_client().get(
            "/character-image-prompts",
            headers={"Authorization": "Bearer test-token"},
        )

        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("character_image_prompts.js", html)
        self.assertIn("20260812-audit-cip-contrast-v9", html)


if __name__ == "__main__":
    unittest.main()
