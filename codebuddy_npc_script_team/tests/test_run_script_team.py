from __future__ import annotations

import importlib.util
import json
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
    assert "剧情需要时可以增加" not in MODULE.PROMPTS["episode_continuity"]


def test_duration_contract_uses_dynamic_episode_and_total_seconds() -> None:
    instruction = MODULE.duration_contract_instruction(
        {"episodes": 30, "episode_duration_seconds": 75}
    )

    assert "每集目标约75秒" in instruction
    assert "全剧约2250秒" in instruction
    assert "眨眼" in instruction
    assert "每秒约4个汉字" in instruction


def test_opening_hook_keeps_a_short_causal_anchor_after_the_first_beat() -> None:
    episode_prompt = MODULE.PROMPTS["episode_continuity"]
    writer_prompt = MODULE.PROMPTS["script_writer"]
    editor_prompt = MODULE.PROMPTS["final_editor"]

    assert "开场因果锚" in episode_prompt
    assert "强钩子后的1至3个有效拍内" in writer_prompt
    assert "不得固定使用路人解释" in writer_prompt
    assert "缺少开场因果锚" in editor_prompt


def test_continuation_contract_uses_actual_episode_range(monkeypatch) -> None:
    monkeypatch.setenv(
        "scriptRequest",
        json.dumps(
            {
                "mode": "续写",
                "episodes": 5,
                "source_last_episode": 5,
                "episode_start": 6,
                "episode_end": 10,
                "continuation_bible": "女主不能失去左眼；第9集关系彻底决裂。",
            },
            ensure_ascii=False,
        ),
    )

    request = MODULE.read_request()
    instruction = MODULE.continuation_contract_instruction(request)

    assert request["episode_start"] == 6
    assert request["episode_end"] == 10
    assert "第6集至第10集" in request["episode_contract"]
    assert "已有第5集结尾" in instruction
    assert "只输出第6集至第10集" in instruction
    assert "续写创作圣经" in instruction
    assert "已有正文明确事实 > 续写创作圣经" in instruction
    assert "第9集关系彻底决裂" in instruction


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


def test_scene_contract_accepts_markdown_bold_scene_header() -> None:
    script = """
第1集：《第98次死亡》
**场景1：暗巷｜夜｜外**
**人物**：林烬、秦墨
林烬：带路。
"""

    assert MODULE.scene_contract_violations(
        script,
        {"scenes_per_episode": "1"},
    ) == []


def test_scene_contract_accepts_standard_scene_number_header() -> None:
    script = """
第12集：《古堡枪声》
12-1 古堡大厅｜日｜内
人物：伊莎贝拉、塞缪尔
塞缪尔：别动。
"""

    assert MODULE.scene_contract_violations(
        script,
        {"scenes_per_episode": "1"},
    ) == []


def test_model_timeout_defaults_to_twenty_minutes(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_TIMEOUT", raising=False)

    assert MODULE._positive_env_int(
        "DEEPSEEK_TIMEOUT",
        1200,
        minimum=60,
        maximum=3600,
    ) == 1200


def test_heartbeat_reports_stage_and_elapsed_time(capsys) -> None:
    class StopAfterOneHeartbeat:
        calls = 0

        def wait(self, _interval):
            self.calls += 1
            return self.calls > 1

    MODULE._emit_heartbeats(
        StopAfterOneHeartbeat(),
        30,
        "script_writer",
        started_at=100,
        clock=lambda: 130,
    )

    output = capsys.readouterr().out
    assert "stage=script_writer" in output
    assert "sequence=1" in output
    assert "elapsed_seconds=30" in output
