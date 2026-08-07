from workflow_code_skeleton.app.services.script_delivery import (
    build_delivery_script,
    build_script_overview,
)


def _job() -> dict:
    return {
        "request": {
            "project_title": "《我有99条命但没人信》",
            "production_type": "AI漫剧",
            "target_market": "中国大陆",
            "genre": "逆袭·高爽·反转",
            "episodes": 5,
        },
        "recovered_files": {
            "contract": """
## 三、核心欲望
活过夺格大典，并证明自己不是废物。
## 四、核心阻力
天阶城把无品者视为必须清除的空壳人。
## 五、情绪承诺
压抑后的公开打脸。
## 七、结局方向
主角在夺格大典完成第99次死亡并反杀。
## 九、不可篡改事实
- 天阶城命格分九品。
- 主角死一次变强一倍。
""",
            "story": """
## 一、主线
林烬必须在三天内完成第99次死亡，赶在夺格大典前获得反杀能力。
## 二、支线
叶青檀试图偿还旧债。
""",
            "characters": """
## 一、林烬——主角
### 标签（观众可记）
被全城当成废物的第98次复活者。
### 外在目标
活过夺格大典。
### 隐藏需求
承认自己仍然需要相信别人。
## 二、叶青檀——核心关系人物
### 标签（观众可记）
看似背叛，实际用另一种方式保护林烬。
### 外在目标
阻止林烬被献祭。
""",
        },
        "final_script": "第1集：《第98次死亡》\n场景1：暗巷｜夜｜外\n人物：林烬\n林烬睁开眼。",
    }


def test_build_script_overview_reuses_existing_artifacts() -> None:
    overview = build_script_overview(_job())

    assert overview.startswith("# 剧本大纲")
    assert "## 故事背景" in overview
    assert "天阶城命格分九品" in overview
    assert "## 故事梗概" in overview
    assert "三天内完成第99次死亡" in overview
    assert "## 核心主线" in overview
    assert "## 主要人物" in overview
    assert "**林烬——主角**" in overview
    assert "活过夺格大典" in overview


def test_build_delivery_script_places_overview_before_episodes() -> None:
    delivery = build_delivery_script(_job())

    assert delivery.index("# 剧本大纲") < delivery.index("# 剧本正文")
    assert delivery.index("# 剧本正文") < delivery.index("第1集")


def test_continuation_overview_shows_new_range_and_series_target() -> None:
    job = _job()
    job["request"].update(
        {
            "mode": "续写",
            "episodes": 13,
            "source_last_episode": 17,
            "episode_start": 18,
            "episode_end": 30,
            "series_total_episodes": 30,
        }
    )

    overview = build_script_overview(job)

    assert "**创作模式**：续写" in overview
    assert "**本次续写范围**：第18集至第30集（13集）" in overview
    assert "**全剧当前目标**：写至第30集" in overview


def test_overview_rejects_internal_mainline_formula_and_builds_readable_copy() -> None:
    job = _job()
    job["recovered_files"]["contract"] = """
## 创作边界
以已锁定世界观与创作合同为准。
"""
    job["recovered_files"]["story"] = """
# 故事圣经：《替身上位》
## 一、立意与主题
**核心主题**：身份可以被夺走，但人的选择无法被替代。
**不可篡改事实**：沈清辞被迫成为相府嫡女的替身。
## 二、主角锁定
**沈清辞（替身/复仇者）**
**核心欲望**：夺回姓名与人生。
## 三、主线因果链
**主线推进逻辑**：触发事件→主角行动→阻力反应→主角选择→代价→局势变化→结局兑现
### 第1集：替身的绝境
**触发事件**：沈清辞被迫代替苏锦瑶参加危险宫宴。
### 第2集：宫宴反击
**触发事件**：沈清辞借危机埋下反击伏笔。
### 第10集：成为唯一的自己
**结局兑现**：沈清辞揭穿骗局，夺回自己的姓名与人生。
"""

    overview = build_script_overview(job)

    assert "身份可以被夺走" in overview
    assert "沈清辞被迫代替苏锦瑶参加危险宫宴" in overview
    assert "夺回自己的姓名与人生" in overview
    assert "以已锁定世界观与创作合同为准" not in overview
    assert "主线推进逻辑" not in overview
    assert "触发事件→主角行动→阻力反应" not in overview


def test_explicit_reader_facing_synopsis_takes_priority() -> None:
    job = _job()
    job["recovered_files"]["story"] = """
## 主线推进逻辑
触发事件→主角行动→阻力反应→结局兑现
## 故事梗概
林烬在一次次死亡中积累力量，也逐渐发现每次复活都在牺牲重要记忆。
"""

    overview = build_script_overview(job)

    assert "逐渐发现每次复活都在牺牲重要记忆" in overview
    assert "触发事件→主角行动" not in overview
