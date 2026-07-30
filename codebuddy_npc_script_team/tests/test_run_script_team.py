from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_script_team.py"
SPEC = importlib.util.spec_from_file_location("run_script_team", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_single_scene_contract_means_one_scene_per_whole_episode() -> None:
    instruction = MODULE.scene_contract_instruction({"scenes_per_episode": "1"})

    assert "每一大集必须且只能有1个场景" in instruction
    assert "不是集内的小阶段" in instruction


def test_single_scene_contract_rejects_three_scene_headers() -> None:
    script = """
第1集：《第98次死亡》
场景1：暗巷｜夜｜外
人物：林烬
林烬：我活了。
场景2：巷口｜夜｜外
人物：秦墨
秦墨：找到你了。
场景3：暗巷深处｜夜｜外
人物：林烬、秦墨
林烬：带路。
"""

    assert MODULE.scene_contract_violations(
        script,
        {"scenes_per_episode": "1"},
    ) == ["第1集要求1个场景，实际检测到3个"]


def test_flexible_scene_contract_accepts_three_scene_headers() -> None:
    script = """
第1集：《第98次死亡》
场景1：暗巷｜夜｜外
场景2：巷口｜夜｜外
场景3：暗巷深处｜夜｜外
"""

    assert MODULE.scene_contract_violations(
        script,
        {"scenes_per_episode": "flexible"},
    ) == []
