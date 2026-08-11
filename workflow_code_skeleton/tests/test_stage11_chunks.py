from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from workflow_code_skeleton.app.services.stage11_chunks import (
    compact_appearance_mapping,
    compact_conflict_plan_for_review,
    compact_enriched_episode_plan,
    compact_scene_dictionary,
    merge_causal_conflict_plans,
    load_stage11_write_resume,
    save_stage11_write_resume,
    split_episode_plan,
    stage11_input_fingerprint,
)


class Stage11ChunkTests(unittest.TestCase):
    def test_split_and_merge_single_episode_plans(self) -> None:
        source = [{"episode": number, "title": f"第{number}集"} for number in range(1, 6)]
        self.assertEqual([1, 1, 1, 1, 1], [len(chunk) for chunk in split_episode_plan(source, 1)])
        plans = [
            {
                "batch_meta": {"start_episode": number, "end_episode": number},
                "global_conflict_engine": {"primary_pressure_source": "生存压力"},
                "episodes": [{"episode": number, "why_now": f"原因{number}"}],
            }
            for number in range(1, 6)
        ]

        merged = merge_causal_conflict_plans(plans, start_episode=1, end_episode=5)

        self.assertEqual([1, 2, 3, 4, 5], [item["episode"] for item in merged["episodes"]])
        self.assertEqual(1, merged["batch_meta"]["start_episode"])
        self.assertEqual(5, merged["batch_meta"]["end_episode"])

    def test_merge_rejects_missing_episode(self) -> None:
        plans = [{"batch_meta": {}, "global_conflict_engine": {}, "episodes": [{"episode": 1}]}]
        self.assertEqual({}, merge_causal_conflict_plans(plans, start_episode=1, end_episode=2))

    def test_write_resume_round_trip_and_fingerprint_guard(self) -> None:
        source = [{"episode": number, "title": f"第{number}集"} for number in range(1, 6)]
        fingerprint = stage11_input_fingerprint(source)
        plans = {
            1: {
                "batch_meta": {"start_episode": 1, "end_episode": 1},
                "global_conflict_engine": {"primary_pressure_source": "生存压力"},
                "episodes": [{"episode": 1, "why_now": "现在发生"}],
            }
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "resume.json"
            save_stage11_write_resume(
                path,
                status="partial",
                fingerprint=fingerprint,
                asset_id="22",
                start_episode=1,
                end_episode=5,
                plans=plans,
                updated_at="now",
            )
            loaded = load_stage11_write_resume(
                path,
                fingerprint=fingerprint,
                asset_id="22",
                start_episode=1,
                end_episode=5,
            )
            self.assertEqual([1], sorted(loaded))
            self.assertEqual(
                {},
                load_stage11_write_resume(
                    path,
                    fingerprint="different",
                    asset_id="22",
                    start_episode=1,
                    end_episode=5,
                ),
            )

    def test_review_context_compaction_removes_duplicate_and_biography_fields(self) -> None:
        plan = [{"episode": 1, "specific_plot": "情节", "text_view": "重复展示文本"}]
        aliases = {
            "naming_principle": "使用显示名",
            "characters": [{
                "character_id": "hero",
                "default_name": "主角",
                "personality": "很长的人物传记",
                "alias_rules": [{"alias": "主角(A)"}],
            }],
        }
        scenes = {
            "core_scenes": [{
                "scene_id": "scene_A",
                "allowed_actions": ["交谈"],
                "conflict_soil": "审核阶段不需要的长篇扩写",
            }]
        }

        self.assertNotIn("text_view", compact_enriched_episode_plan(plan)[0])
        self.assertNotIn("personality", compact_appearance_mapping(aliases)["characters"][0])
        self.assertEqual(
            [],
            compact_appearance_mapping(aliases, relevant_names=["另一个角色"])["characters"],
        )
        self.assertNotIn("conflict_soil", compact_scene_dictionary(scenes)["core_scenes"][0])

    def test_review_conflict_view_keeps_contract_fields_and_drops_optional_explanations(self) -> None:
        plan = {
            "batch_meta": {"start_episode": 1},
            "global_conflict_engine": {"primary_pressure_source": "危机"},
            "episodes": [{
                "episode": 1,
                "episode_title": "开场",
                "opening_alias_plan": [{"character_name": "主角(A)"}],
                "ending_hook": "钩子",
                "audience_must_understand": "重复解释",
            }],
        }
        compact = compact_conflict_plan_for_review(plan)
        self.assertEqual("钩子", compact["episodes"][0]["ending_hook"])
        self.assertIn("opening_alias_plan", compact["episodes"][0])
        self.assertNotIn("audience_must_understand", compact["episodes"][0])


if __name__ == "__main__":
    unittest.main()
