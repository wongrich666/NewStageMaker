from __future__ import annotations

import pytest

from app.services.framework_stage10_fallback import generate_stage10_plan


class FakeClient:
    def __init__(self, episodes):
        self.episodes = episodes
        self.prompt = ""

    def complete_json(self, prompt, **kwargs):
        self.prompt = prompt
        return {
            "structured_output": {"episodes": self.episodes},
            "model": "test-model",
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }


def _episode(number: int) -> dict:
    return {
        "episode": number,
        "title": f"第{number}集",
        "characters": ["打工鱼(A)"],
        "scene_refs": ["scene_A"],
        "scenes": ["办公室"],
        "specific_plot": f"承接前集后，打工鱼完成第{number}集的选择并付出代价。",
        "pressure_sources": ["老板的截止时间", "同事关系压力"],
        "ending_hook": f"第{number}集未完成动作启动。",
        "beat_refs": ["Beat 1"],
        "character_storyline_refs": ["打工鱼主线", "团队关系线"],
        "alias_notes": "打工鱼(A)来自默认服装版本。",
    }


def test_generates_display_text_locally_without_asking_model_to_duplicate_it():
    client = FakeClient([_episode(1), _episode(2)])
    plan, text = generate_stage10_plan(
        framework_plan_package={
            "basic_config": {"episodes_per_season": 2},
            "beat_checkpoint_timeline": [{"beat_no": 1}],
        },
        scene_dictionary={"core_scenes": [{"scene_id": "scene_A"}]},
        appearance_mapping={"characters": [{"name": "打工鱼"}]},
        client=client,
    )

    assert [item["episode"] for item in plan] == [1, 2]
    assert plan[0]["text_view"].startswith("第1集")
    assert "第2集" in text
    assert "不要输出 text_view" in client.prompt


def test_rejects_missing_episode_in_complete_plan():
    client = FakeClient([_episode(1), _episode(3)])

    with pytest.raises(ValueError, match="缺集|无效"):
        generate_stage10_plan(
            framework_plan_package={"basic_config": {"episodes_per_season": 3}},
            scene_dictionary={"core_scenes": [{"scene_id": "scene_A"}]},
            appearance_mapping={"characters": [{"name": "打工鱼"}]},
            client=client,
        )
