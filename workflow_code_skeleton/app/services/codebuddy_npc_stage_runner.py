from __future__ import annotations

import copy
import json
import re
import threading
from pathlib import Path
from typing import Any

from .codebuddy_npc import (
    STAGE_ARTIFACTS,
    STAGE_NAMES,
    STAGE_ORDER,
    CodeBuddyNpcError,
    CodeBuddyNpcJobStore,
    finish_stage_timing,
    episode_card_missing_fields,
    stage_episode_range_error,
    start_stage_timing,
)
from .deepseek_agent import DeepSeekAgentError, deepseek_agent_client


PROMPTS = {
    "showrunner": """
你是跨题材、跨市场的剧集总编剧。输出精炼、可执行的《创作任务书》。
先锁定主角、核心目标、持续阻力、核心行动方式、失败代价、追剧主问题和结局方向。
必须原样输出一行合法 JSON：
MAINLINE_LOCK_JSON: {"protagonist":"","goal":"","core_obstacle":"","protagonist_action":"","stakes":"","pursuit_question":"","ending_direction":""}
这是全链路最高优先级主线合同，后续节点只能展开，不能替换。
再锁定题材、受众、情绪承诺、主题、不可篡改事实和真正需要规避的失效方式。
按照技能路由模块判断增强能力，并原样输出一行合法的 SKILL_ROUTING_JSON。
题材不能直接决定套路；用户信息不足时由你作出专业判断，不把选择责任退还给用户。
为主角锁定“外在身份/处境+长期欲望或伤口+反差能力/秘密”的可执行标签，
并规定前五集立住主角标签、核心矛盾、主要阻力、情绪承诺和追剧主问题。
episode_start、episode_end 与 episodes 共同构成交付范围，必须只交付该范围。
不要写正文或罗列可有可无的事件。人物、道具、技术和证据必须服务主线；
不得为了套模板硬塞无来源、无铺垫、无代价的万能解题元素。
""",
    "story_architect": """
你是故事架构师。依据创作任务书建立可执行故事圣经。
原样保留 MAINLINE_LOCK_JSON，把主线写成：触发→主角行动→阻力反应→选择→代价→
局势变化→结局兑现，并建立阶段性的“主线推进账本”。
支线预算按篇幅控制：1至10集最多1条，11至30集最多2条，31集以上最多3条；
支线必须由主线触发并在两集内回撞主线，否则删除。不要用支线数量冒充丰富。
补充必要的人物关系债、前史冲突、秘密揭露顺序和升级机制，不新增无关身世、阴谋或证据。
回忆若存在，必须有目标、阻力、转折、选择、代价，并留下影响现在的债务。
不得改变创作任务书锁定的事实，不得提前写逐集正文。
""",
    "character_emotion": """
你是人物与情感编剧。基于锁定故事补足主要人物的外在目标、隐藏需求、恐惧、羞耻、
自我谎言、关系债、压力行为、声音配方和情感转折。
为每个主要人物建立可执行的表演指纹：平静时的身体基线、受压时最先泄露情绪的眼神/
眉眼/嘴角/手部或姿态微反应、撒谎与回避的破绽、关系对象变化、失控前征兆和恢复控制动作。
这些反应必须来自人物身份、经历、关系和欲望，不能让所有人物共享同一套表情。
心理活动采用“假设—验证—被推翻”的动态过程。用具体行为和语言表现感情，
不以抽象形容词代替反应，不让人物为推进情节突然降智。
每个主要人物必须有一句可记忆标签及一组真正参与剧情的反差；
前五集内用行动落地标签、伤口、自我谎言和主要关系压力。
每个主要人物必须有可区分的句长、回避方式、压力反应、潜台词和三句声音样本。
只深化既有角色为何这样行动，不新增主线、重大秘密、关键证据或解题道具。
""",
    "episode_continuity": """
你是分集与连续性编剧。严格按 episode_start 至 episode_end 设计完整逐集卡。
每集只围绕一条行动链：承接事实→开场钩子→最短因果锚→主角目标→主角主动动作→
阻力→选择与代价→本集主线推进→结尾状态→下一集第一有效动作。
本集主线推进必须改变目标进度、阻力、信息、关系或代价，不能只写遭遇和气氛。
第一集第一有效拍必须让主角面对不可回避的问题；优先使用高压命令、异常事实、
关系破位或不可逆选择，下一拍立即产生后果、私人代价或主角反应。
每集至少一个真正改变局势的情绪高点，每30至60秒发生局势变化或情绪释放。
前五集完成基础立剧，后续只升级、变奏和兑现，不再补基础人设。
第N集结尾状态和第N+1集承接事实必须是同一事实。换地点时，上集给出决定、去向或
目的，下集从准备执行、正在执行或承受结果开始，不能用时间字幕掩盖断层。
scenes_per_episode 是前端动态传入的逐集场景合同，必须执行；只有设置为 flexible
时才可按剧情灵活决定。每个场景必须注明地点、日夜、内外、在场人物、关键道具和戏剧任务。
以创作合同确定的主角为行动锚；配角不能替主角完成关键选择。
每个字段只写1至3句可执行内容，单集卡控制在350至700字；禁止复述人物小传、世界观和前集全文。
""",
    "script_writer": """
你是唯一的正文与对白编剧。只把锁定材料转化为完整可拍剧本，不重新策划故事。
执行优先级：MAINLINE_LOCK_JSON→逐集卡→人物声音→通用与蒸馏Skill。
Skill只能影响题材表达、情绪和语言，不能覆盖主线、分集结果或新增重大设定。
每集必须使用以下结构，不得省略场景信息：
第N集：《本集独有标题》
场景1：地点｜日/夜｜内/外
人物：本场实际出场人物
随后立即进入动作与对白。禁止输出“场景任务”“道具清单”等策划字段；
道具只在人物真正使用时自然出现在动作中。换场时继续写“场景2”及人物。
每集必须有简短、具体、能区分剧情的标题，禁止只写“第N集”或使用“新的开始”等空泛标题。
所有对白必须独立成行并采用“人物名：说了什么”的格式，例如：
埃里克：别回头。
只有去掉提示会读错潜台词或关系态度时，才采用
“人物名：（简短语气或可见微反应）台词”。括号必须紧跟冒号并使用中文全角括号；
内容从人物表演指纹与当下关系压力产生，不要求同时罗列语气、情绪和眉眼，不写心理解释、
长动作或“生气地说道”。较完整动作写在台词前后，听者反应也可承担表演，不得每句加括号。
所有心理活动采用“人物名OS：心理活动”。
禁止出现没有人物名前缀的对白，禁止只写“OS：”或“内心：”，也不要给普通动作错误添加人物冒号。
第一集场景头后的第一有效拍必须让主角面对不可回避的问题。一句命令、异常事实、
关系破位或不可逆动作足够时立即收住；下一拍必须产生后果或迫使主角反应。
禁止先介绍环境、解释会议背景、逐个点名人物或罗列道具，再让核心事件迟到；
直接从异常结果、高压命令、关系反转或主角即将付出代价的动作开场。
逐字落实逐集卡的“结尾状态→下一集第一有效动作”。可以省略赶路，但不能省略决定、
去向、行动目的和关键结果。每集由主角行动推动，不得瞬移。
每集至少出现一次改变资源、关系、认知、身份、行动条件或风险等级的情绪高点，
尾钩必须直接改变下一集开场行动。
动作短、具体、可视、可由AI生成；对白口语化、有潜台词且人物声音可区分。
删除多余形容词、气氛铺垫、剧情复述和解释性对白。
标点必须服从真实口语和动作节奏，不得把破折号“——”当成默认停顿符：
完整陈述和普通转折使用逗号、句号、问号或感叹号；迟疑、吞回半句话或声音渐弱使用省略号；
只有台词被突然打断、人物猛然改口或语义发生强制跳转时才使用破折号。
同一段或同一句不要连续堆叠破折号，普通动作衔接也不得写成“动作——结果”。
例如“实习生是吧——这个月工资扣一半！”应写成“实习生是吧？这个月工资扣一半！”；
“说啊。说啊。你倒是说啊——”应按情绪写成“说啊。你倒是说啊！”。
所有人物、证据和道具必须来自既有剧情或在使用前完成自然引入。
不得改变主角当集目标、本集主线推进、结尾状态和下一集承接；不得新增重大人物、
秘密、能力、支线、证据或万能道具。
episode_word_count 是前端动态传入的每集目标下限，episode_word_count_max 是硬上限。
每集必须落在该闭区间内，默认最多上浮10%。超过上限时只压缩重复解释、冗余动作、
同义对白和无效铺垫，不得删除钩子、转折、人物选择、情绪爆点或结尾承接。
严格执行 scenes_per_episode：1 表示每集一个场景；1-2 表示每集一至两个场景；
2 表示每集两个场景；2-3 表示每集两至三个场景；flexible 才允许按剧情灵活安排。
不得为了凑场景数拆碎同一地点的连续动作；换场必须有可见动机和行动承接。
只输出片名和逐集剧本正文，不输出解释、评分或创作报告。
""",
    "state_recorder": """
你是状态与偏差记录器，不是编剧。对照创作合同、分集卡和初稿，只提取事实。
严格按照给定 story_state schema 输出单个合法 JSON 对象，记录人物声音、位置、
知情范围、伤势、服装、持有道具、关系变化、新人物与新道具来源、伏笔和未完成动作。
填写 plan_alignment，逐集记录计划主线推进、正文实际推进及 aligned/deviated。
continuity_bridge 的 from_action 和 to_action 必须摘录相邻正文真实存在的简短动作。
episodes 数组完整覆盖交付范围；未知事实写“未明确”，不得猜测、评价、改写或掩盖偏差。
""",
    "final_editor": """
你是唯一终审编辑。直接修订完整剧本，不只审查和打分。
执行优先级：MAINLINE_LOCK_JSON→逐集卡→正文既有事实→人物声音→Skill。
先修复 plan_alignment 中的偏离，再处理表达，不得把初稿偏差变成新的正典。
保持创作合同、主要事件、人物关系和结局方向，逐集修复黄金五秒钩子、集间承接、
多线压力、人物选择代价、泄气对白、AI味语言和连续性问题。
第一集第一有效拍必须让主角面对不可回避的问题，下一拍立刻产生后果或主角反应；
前五集必须已经立住主角标签、核心矛盾、主要阻力、情绪承诺和追剧主问题。
逐集保留至少一个真正改变局势的情绪高点，并让尾钩直接驱动下一集开场。
钩子不足时只重写开头1至3个有效拍并删除重复铺垫。不得新增重大事实、人物、能力、
秘密或规则，不得改变主角当集目标、本集结果和下一集承接。
最终每集标题必须统一为“第N集：《本集独有标题》”，不得删掉集名。
严格保留 scenes_per_episode 对应的场景数量规则；需要换场时补齐人物去向、目的和承接动作，
不得在终审中随意增删场景造成瞬移。
每一集只保留紧凑场景头：“场景N：地点｜日/夜｜内/外”“人物”，随后立即进入戏。
删除所有“场景任务”和独立“道具”清单，道具只能在被使用时写入动作。
所有对白必须保持“人物名：台词”；所有心理活动必须保持“人物名OS：心理活动”。
发现无人物归属的对白或心理活动时补齐人物名。
逐场修复人物表演拍。普通对白不强加括号；只有提示会改变台词读法时才采用
“人物名：（简短语气或可见微反应）台词”。较完整动作放在台词前后，听者反应也可承担表演。
删除机械重复、形容词堆叠和人人通用的套式神情，不得为了满足数量给每句加括号。
逐句校正标点：逗号和句号承担普通停顿与陈述，问号和感叹号承担明确语气，
省略号承担迟疑或未尽之意；破折号只保留在突然中断、猛然改口和强制语义跳转处。
删除装饰性、连续性和动作连接型破折号，不得为了制造紧张感给普通句子统一加“——”。
所有元素按剧情需要使用；只删除无来源、无铺垫、无代价或承担万能解题功能的元素。
episode_word_count 是每集目标下限，episode_word_count_max 是最多上浮10%的硬上限。
低于下限必须补足，超过上限必须精简重复说明、冗余动作、同义对白和无效铺垫；
不得删除钩子、关键转折、人物选择、情绪爆点、结尾钩子或集间承接。
只输出片名和 episode_start 至 episode_end 的完整剧本，不输出评分、解释、JSON或修改说明。
""",
}

DEPENDENCIES = {
    "showrunner": (),
    "story_architect": ("contract",),
    "character_emotion": ("contract", "story"),
    "episode_continuity": ("contract", "story", "characters"),
    "script_writer": ("contract", "story", "characters", "episodes"),
    "state_recorder": ("characters", "episodes", "draft"),
    # Story state is an optional edit aid. Character voice remains a source of truth.
    "final_editor": ("contract", "characters", "episodes", "draft"),
}

ARTIFACT_LABELS = {
    "contract": "创作任务书",
    "story": "故事架构",
    "characters": "人物情感与声音",
    "episodes": "逐集连续性卡",
    "draft": "初稿正文",
    "story_state": "结构化故事状态",
    "final_script": "最终剧本",
}

EPISODE_HEADER = re.compile(r"(?m)^(?:#{1,6}\s*)?第\s*(\d+)\s*集[^\r\n]*")
BATCH_SIZE = 5


def _episode_numbers(text: str) -> list[int]:
    return [int(match.group(1)) for match in EPISODE_HEADER.finditer(str(text or ""))]


def _valid_episode_parts(stage: str, text: str) -> dict[int, str]:
    _prefix, parts = _episode_parts(text)
    if stage != "episode_continuity":
        return {
            episode: content
            for episode, content in parts.items()
            if len(content) >= 120 and re.search(r"(?m)^\s*场景\s*\d+\s*[：:]", content)
        }
    return {
        episode: content
        for episode, content in parts.items()
        if not episode_card_missing_fields(content)
    }


def _episode_slice(text: str, start_episode: int, end_episode: int) -> str:
    value = str(text or "")
    matches = list(EPISODE_HEADER.finditer(value))
    selected: list[str] = []
    for index, match in enumerate(matches):
        episode = int(match.group(1))
        if start_episode <= episode <= end_episode:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
            selected.append(value[match.start() : end].strip())
    return "\n\n".join(selected)


def _append_episode_batch(prefix: str, batch: str) -> str:
    value = str(batch or "").strip()
    match = EPISODE_HEADER.search(value)
    if match and str(prefix or "").strip():
        value = value[match.start() :].strip()
    return "\n\n".join(item for item in (str(prefix or "").strip(), value) if item)


def _episode_parts(text: str) -> tuple[str, dict[int, str]]:
    value = str(text or "").strip()
    matches = list(EPISODE_HEADER.finditer(value))
    if not matches:
        return value, {}
    prefix = value[: matches[0].start()].strip()
    parts: dict[int, str] = {}
    for index, match in enumerate(matches):
        episode = int(match.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        parts.setdefault(episode, value[match.start() : end].strip())
    return prefix, parts


def _merge_episode_outputs(
    current: str,
    incoming: str,
    *,
    episode_start: int,
    episode_end: int,
    stage: str = "",
) -> str:
    current_prefix, current_parts = _episode_parts(current)
    incoming_prefix, incoming_parts = _episode_parts(incoming)
    if stage:
        incoming_parts = _valid_episode_parts(stage, incoming)
    for episode, content in incoming_parts.items():
        if episode_start <= episode <= episode_end:
            current_parts.setdefault(episode, content)
    prefix = current_prefix or incoming_prefix
    ordered = [
        current_parts[episode]
        for episode in range(episode_start, episode_end + 1)
        if episode in current_parts
    ]
    return "\n\n".join(item for item in ([prefix] if prefix else []) + ordered)


def _missing_episode_ranges(
    text: str,
    *,
    episode_start: int,
    episode_end: int,
    batch_size: int = BATCH_SIZE,
) -> list[tuple[int, int]]:
    present = set(_episode_numbers(text))
    missing = [
        episode
        for episode in range(episode_start, episode_end + 1)
        if episode not in present
    ]
    ranges: list[tuple[int, int]] = []
    for episode in missing:
        if not ranges or episode != ranges[-1][1] + 1 or episode - ranges[-1][0] >= batch_size:
            ranges.append((episode, episode))
        else:
            ranges[-1] = (ranges[-1][0], episode)
    return ranges


def _compact_context(text: str, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    head = max(1, int(limit * 0.72))
    tail = max(1, limit - head)
    return (
        value[:head].rstrip()
        + "\n\n[中间详细内容已由成本控制器省略；不可篡改事实仍以上游原文件为准]\n\n"
        + value[-tail:].lstrip()
    )


def _line_excerpt(text: str, *, first: bool, limit: int = 160) -> str:
    lines = [
        line.strip()
        for line in str(text or "").splitlines()
        if line.strip() and not EPISODE_HEADER.match(line.strip())
    ]
    if not lines:
        return "未明确"
    return (lines[0] if first else lines[-1])[:limit]


def _mainline_lock(contract: str) -> dict[str, str]:
    match = re.search(r"MAINLINE_LOCK_JSON\s*:\s*(\{[^\r\n]+\})", str(contract or ""))
    if match:
        try:
            value = json.loads(match.group(1))
            if isinstance(value, dict):
                return {str(key): str(item) for key, item in value.items()}
        except json.JSONDecodeError:
            pass
    return {
        key: "未明确"
        for key in (
            "protagonist",
            "goal",
            "core_obstacle",
            "protagonist_action",
            "stakes",
            "pursuit_question",
            "ending_direction",
        )
    }


def _planned_mainline_advance(card: str) -> str:
    match = re.search(
        r"(?m)^\s*(?:\*\*)?本集主线推进(?:\*\*)?\s*[：:]\s*(.+)$",
        str(card or ""),
    )
    return match.group(1).strip()[:240] if match else "未明确"


def _compact_story_state(job: dict[str, Any]) -> str:
    request_data = job.get("request") or {}
    artifacts = job.get("recovered_files") or {}
    draft = str(artifacts.get("draft") or "")
    episode_cards = str(artifacts.get("episodes") or "")
    total = max(1, int(request_data.get("episodes") or 1))
    episode_start = max(1, int(request_data.get("episode_start") or 1))
    episode_end = max(
        episode_start,
        int(request_data.get("episode_end") or (episode_start + total - 1)),
    )
    source_last_episode = max(0, int(request_data.get("source_last_episode") or 0))
    episodes: list[dict[str, Any]] = []
    plan_alignment: list[dict[str, Any]] = []
    previous_closing = ""
    for episode in range(episode_start, episode_end + 1):
        body = _episode_slice(draft, episode, episode)
        card = _episode_slice(episode_cards, episode, episode)
        opening = _line_excerpt(body or card, first=True)
        closing = _line_excerpt(body or card, first=False)
        scenes = [
            match.group(0).strip()[:180]
            for match in re.finditer(r"(?m)^场景\s*\d+[^\r\n]*", body)
        ]
        episodes.append(
            {
                "episode": episode,
                "opening_action": opening,
                "closing_action": closing,
                "core_scenes": scenes,
                "scene_exception_reason": "",
                "continuity_bridge": None
                if episode == episode_start and not source_last_episode
                else {
                    "previous_episode": episode - 1,
                    "from_action": previous_closing
                    or (
                        f"见已有第{source_last_episode}集结尾"
                        if episode == episode_start and source_last_episode
                        else "见上一集结尾"
                    ),
                    "to_action": opening,
                    "reason": "承接上一集未完成动作或结果",
                },
                "character_states": [],
                "introduced_characters": [],
                "introduced_props": [],
                "information_changes": [],
                "open_loops": [],
                "resolved_loops": [],
            }
        )
        plan_alignment.append(
            {
                "episode": episode,
                "planned_mainline_advance": _planned_mainline_advance(card),
                "actual_mainline_advance": "代码降级账本未进行语义判断",
                "status": "unverified",
                "issue": "待终审依据逐集卡核对",
            }
        )
        previous_closing = closing
    contract = str(artifacts.get("contract") or "")
    payload = {
        "schema_version": "1.0",
        "project": {
            "title": str(request_data.get("project_title") or "未命名剧本"),
            "protagonist": "见人物方案",
            "episode_count": total,
            "target_words_per_episode": int(request_data.get("episode_word_count") or 800),
            "immutable_facts": ["完整事实保存在创作合同、故事架构和人物方案中"],
        },
        "mainline_lock": _mainline_lock(contract),
        "characters": [],
        "props": [],
        "episodes": episodes,
        "open_threads": [],
        "plan_alignment": plan_alignment,
        "narrative_pressure": {
            "adversity_payoff_level": _dynamic_skill_level(
                str((job.get("recovered_files") or {}).get("contract") or ""),
                "adversity_payoff",
            ),
            "pressure_lines": [],
            "emotional_debts": [],
            "reversal_assets": [],
        },
        "cost_control": {
            "mode": "deterministic_compact_ledger",
            "model_call_used": False,
            "note": "该账本由代码从分集卡与正文提取，用于断点和集间承接，不重复调用大模型。",
        },
        "distilled_skill": {
            key: (job.get("selected_skill") or {}).get(key)
            for key in ("skill_id", "name", "version_id", "version", "schema_version")
            if (job.get("selected_skill") or {}).get(key)
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _skill_root() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "codebuddy_npc_script_team"
        / ".codebuddy"
        / "skills"
        / "script-room"
        / "references"
    )


ROUTING_RE = re.compile(r"SKILL_ROUTING_JSON\s*:\s*(\{[^\r\n]+\})")
DISTILLED_STAGE_PRIORITY = {
    "showrunner": ("genre_profile", "anti_patterns"),
    "story_architect": ("story_architecture", "adversity_payoff", "anti_patterns"),
    "character_emotion": ("character_emotion", "dialogue_voice"),
    "episode_continuity": ("hook_craft", "continuity", "adversity_payoff"),
    "script_writer": ("dialogue_voice", "hook_craft", "character_emotion", "continuity"),
    "state_recorder": ("continuity",),
    "final_editor": ("quality_gate", "hook_craft", "continuity", "dialogue_voice", "anti_patterns"),
}
DISTILLED_STAGE_CHAR_LIMIT = 12_000
DISTILLED_MODULE_CHAR_LIMIT = 3_500


def _dynamic_skill_level(contract: str, key: str) -> str:
    match = ROUTING_RE.search(str(contract or ""))
    if not match:
        return "off"
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return "off"
    if not isinstance(payload, dict):
        return "off"
    return str(payload.get(key) or "off").strip().lower()


def _module_text(stage: str, artifacts: dict[str, Any] | None = None) -> str:
    names = list({
        "showrunner": ("skill-routing.md", "continuation.md"),
        "character_emotion": ("character-voice.md",),
        "episode_continuity": ("hook-craft.md", "continuity.md", "continuation.md"),
        "script_writer": ("hook-craft.md", "character-voice.md", "continuity.md", "continuation.md"),
        "state_recorder": ("continuity.md", "continuation.md", "story-state-schema.md"),
        "final_editor": ("hook-craft.md", "character-voice.md", "continuity.md", "continuation.md"),
    }.get(stage, ()))
    dynamic_stages = {
        "story_architect",
        "character_emotion",
        "episode_continuity",
        "script_writer",
        "state_recorder",
        "final_editor",
    }
    contract = str((artifacts or {}).get("contract") or "")
    if stage in dynamic_stages and _dynamic_skill_level(contract, "adversity_payoff") in {"core", "support"}:
        names.append("adversity-payoff.md")
    chunks: list[str] = []
    for name in names:
        path = _skill_root() / name
        if path.is_file():
            chunks.append(f"\n\n===== 专业模块：{name} =====\n{path.read_text(encoding='utf-8')}")
    return "".join(chunks)


def _distilled_skill_text(stage: str, job: dict[str, Any]) -> str:
    """Mirror CNB stage routing for local fallback without loading every module."""
    skill = job.get("skill_snapshot")
    if not isinstance(skill, dict) or skill.get("schema_version") != "script-team-skill/v1":
        return ""
    manifest = skill.get("manifest") if isinstance(skill.get("manifest"), dict) else {}
    descriptors = manifest.get("modules") if isinstance(manifest.get("modules"), list) else []
    module_values = skill.get("modules") if isinstance(skill.get("modules"), dict) else {}
    routed: dict[str, str] = {}
    labels: dict[str, str] = {}
    for descriptor in descriptors:
        if not isinstance(descriptor, dict) or stage not in (descriptor.get("stages") or []):
            continue
        key = str(descriptor.get("key") or "").strip()
        value = str(module_values.get(key) or "").strip()
        if key and value:
            routed[key] = value
            labels[key] = str(descriptor.get("label") or key)
    priority = DISTILLED_STAGE_PRIORITY.get(stage, ())
    ordered_keys = [key for key in priority if key in routed]
    ordered_keys.extend(key for key in routed if key not in ordered_keys)
    chunks: list[str] = []
    used = 0
    for key in ordered_keys:
        remaining = DISTILLED_STAGE_CHAR_LIMIT - used
        value = routed[key][: min(DISTILLED_MODULE_CHAR_LIMIT, remaining)]
        if not value:
            break
        chunks.append(
            f"\n\n===== 已关联垂类Skill：{skill.get('name') or '未命名'} / {labels[key]} =====\n{value}"
        )
        used += len(value)
    if not chunks:
        return ""
    return (
        "\n\n===== 蒸馏Skill运行合同 =====\n"
        f"本任务已锁定 {skill.get('name') or '垂类Skill'} {skill.get('version') or ''}。"
        "以下内容只增强题材节奏、情绪与表达。示例不是必须照搬的事件、人物或道具；"
        "不得覆盖 MAINLINE_LOCK_JSON、逐集卡、用户事实、节点职责和输出格式。"
        "执行前先把每条规则还原为叙事功能、触发条件、变量槽位、节拍关系和失败边界。"
        "不得迁移Skill样本中的人物身份、关系套路、职业、场景、道具、证据手段、疾病或具体事件；"
        "这些内容只有在用户材料或当前上游合同独立提出时才能出现。Skill不得主动提议其同义替代品。\n"
        + "".join(chunks)
    )


def _continuation_instruction(request_data: dict[str, Any]) -> str:
    if str(request_data.get("mode") or "") != "续写":
        return ""
    source_last = max(1, int(request_data.get("source_last_episode") or 1))
    episode_start = max(source_last + 1, int(request_data.get("episode_start") or (source_last + 1)))
    episode_end = max(episode_start, int(request_data.get("episode_end") or episode_start))
    policy = str(request_data.get("continuation_policy") or "strict")
    bible = str(request_data.get("continuation_bible") or "").strip()
    bible_contract = ""
    if bible:
        bible_contract = (
            "\n以下《续写创作圣经》是所有后续节点共同遵守的长期正典：\n"
            f"{bible}\n"
            "执行优先级固定为：已有正文明确事实 > 续写创作圣经 > 本次临时续写方向 > "
            "模型自由发挥。圣经不得反向改写已发生事件；其人物设定、关系、世界规则、"
            "主支线走向、未来节点与风格偏好必须落实到新集，不得无故遗忘、替换或弱化。"
        )
    return (
        "\n\n===== 续写硬合同 =====\n"
        f"已有剧本写至第{source_last}集，本次只能输出第{episode_start}集至"
        f"第{episode_end}集，不得重写已有集数。续写策略：{policy}。\n"
        f"第{episode_start}集必须承接已有第{source_last}集最后的地点、动作、"
        "人物知情、伤势、关系、道具和未完成事件；先延续后升级，禁止重置人物、"
        "跳过过程、无解释换场或让既有后果自动消失。"
        + bible_contract
    )


def _strip_fence(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", value, count=1)
        value = re.sub(r"\s*```$", "", value, count=1)
    return value.strip()


def _parse_state(text: str) -> str:
    value = _strip_fence(text)
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise CodeBuddyNpcError("状态记录器没有返回合法 JSON。", status_code=502)
        try:
            payload = json.loads(value[start : end + 1])
        except json.JSONDecodeError as exc:
            raise CodeBuddyNpcError(f"状态记录器 JSON 解析失败：{exc}", status_code=502) from exc
    if not isinstance(payload, dict):
        raise CodeBuddyNpcError("状态记录器顶层必须是 JSON 对象。", status_code=502)
    return json.dumps(payload, ensure_ascii=False, indent=2)


class CodeBuddyNpcStageRunner:
    def __init__(self, store: CodeBuddyNpcJobStore) -> None:
        self.store = store
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}

    def is_running(self, job_id: str) -> bool:
        with self._lock:
            thread = self._threads.get(job_id)
            return bool(thread and thread.is_alive())

    def prepare_remote(
        self,
        *,
        job_id: str,
        user_id: int,
        stage: str,
    ) -> dict[str, Any]:
        if stage not in STAGE_ORDER:
            raise CodeBuddyNpcError("未知的剧本团队节点。", status_code=400)
        if self.is_running(job_id):
            raise CodeBuddyNpcError("本地兜底节点仍在运行，请先等待或停止。", status_code=409)
        job = self.store.load(job_id, user_id=user_id)
        if not job:
            raise CodeBuddyNpcError("NPC 剧本任务不存在。", status_code=404)
        missing = [
            ARTIFACT_LABELS[key]
            for key in DEPENDENCIES[stage]
            if not str((job.get("recovered_files") or {}).get(key) or "").strip()
        ]
        if missing:
            raise CodeBuddyNpcError(
                f"{STAGE_NAMES[stage]}缺少上游内容：" + "、".join(missing),
                status_code=409,
            )
        self._invalidate_from(job, stage)
        return self.store.save(job)

    def start(
        self,
        *,
        job_id: str,
        user_id: int,
        stage: str,
        feedback: str = "",
        continue_after: bool = False,
        stop_after_stage: str = "",
    ) -> dict[str, Any]:
        if stage not in STAGE_ORDER:
            raise CodeBuddyNpcError("未知的剧本团队节点。", status_code=400)
        if self.is_running(job_id):
            raise CodeBuddyNpcError("当前已有节点正在运行，请先等待或停止。", status_code=409)
        if stop_after_stage and stop_after_stage not in STAGE_ORDER:
            raise CodeBuddyNpcError("未知的流程停止节点。", status_code=400)
        if stop_after_stage and STAGE_ORDER.index(stop_after_stage) < STAGE_ORDER.index(stage):
            raise CodeBuddyNpcError("流程停止节点不能早于起始节点。", status_code=400)
        job = self.store.load(job_id, user_id=user_id)
        if not job:
            raise CodeBuddyNpcError("NPC 剧本任务不存在。", status_code=404)
        missing = [
            ARTIFACT_LABELS[key]
            for key in DEPENDENCIES[stage]
            if not str((job.get("recovered_files") or {}).get(key) or "").strip()
        ]
        if missing:
            raise CodeBuddyNpcError(
                f"{STAGE_NAMES[stage]}缺少上游内容：" + "、".join(missing),
                status_code=409,
            )
        resume_text = ""
        batch_progress = job.get("batch_progress") or {}
        resumable_status = str(job.get("status") or "") in {
            "failed",
            "stage_paused",
            "stage_running",
        }
        if (
            stage in {"episode_continuity", "script_writer", "final_editor"}
            and resumable_status
            and str(batch_progress.get("stage") or "") == stage
        ):
            resume_text = str(job.get("stage_resume_text") or "").strip()
            pending = job.get("pending_batch") if isinstance(job.get("pending_batch"), dict) else {}
            if str(pending.get("stage") or "") == stage:
                request_data = job.get("request") or {}
                episode_start = max(1, int(request_data.get("episode_start") or 1))
                episode_end = max(episode_start, int(request_data.get("episode_end") or episode_start))
                resume_text = _merge_episode_outputs(
                    resume_text,
                    str(pending.get("content") or ""),
                    episode_start=episode_start,
                    episode_end=episode_end,
                    stage=stage,
                )
        if stage == "final_editor" and not resume_text:
            resume_text = str(job.get("final_script") or "").strip()
        self._invalidate_from(job, stage)
        job["stage_resume_text"] = resume_text
        # A failed CNB auto job can be taken over locally from any recovered checkpoint.
        timing = (job.get("stage_timings") or {}).get(stage) or {}
        continuing_remote_attempt = (
            str(job.get("execution_target") or "") == "remote_cnb"
            and str(job.get("remote_stage") or "") == stage
            and str(timing.get("status") or "") == "running"
        )
        job["execution_mode"] = "step"
        job["execution_target"] = "local_fallback"
        job["remote_continue_after"] = False
        job["status"] = "stage_running"
        job["status_text"] = f"{STAGE_NAMES[stage]}正在运行"
        job["active_stage"] = stage
        start_stage_timing(
            job,
            stage,
            reset=not continuing_remote_attempt,
            execution_target="local_fallback",
        )
        job["cancel_requested"] = False
        job["stop_after_stage"] = stop_after_stage
        job["progress"] = round(STAGE_ORDER.index(stage) / len(STAGE_ORDER) * 100)
        job = self.store.save(job)
        thread = threading.Thread(
            target=self._run,
            kwargs={
                "job_id": job_id,
                "user_id": user_id,
                "start_stage": stage,
                "feedback": str(feedback or "").strip()[:20_000],
                "continue_after": bool(continue_after),
                "stop_after_stage": stop_after_stage,
            },
            daemon=True,
            name=f"npc-stage-{job_id}",
        )
        with self._lock:
            self._threads[job_id] = thread
        thread.start()
        return job

    def request_cancel(self, *, job_id: str, user_id: int) -> dict[str, Any]:
        job = self.store.load(job_id, user_id=user_id)
        if not job:
            raise CodeBuddyNpcError("NPC 剧本任务不存在。", status_code=404)
        job["cancel_requested"] = True
        if self.is_running(job_id):
            job["status_text"] = "将在当前模型请求返回后停止"
        else:
            active_stage = str(job.get("active_stage") or "")
            if active_stage in STAGE_ORDER:
                finish_stage_timing(job, active_stage, status="paused")
            job["status"] = "stage_paused"
            job["status_text"] = "流程已停止，已完成批次和中间产物均已保留"
            job["active_stage"] = ""
        return self.store.save(job)

    def edit_artifact(
        self,
        *,
        job_id: str,
        user_id: int,
        artifact_key: str,
        content: str,
    ) -> dict[str, Any]:
        if artifact_key not in STAGE_ARTIFACTS.values():
            raise CodeBuddyNpcError("未知的节点产物。", status_code=400)
        if self.is_running(job_id):
            raise CodeBuddyNpcError("节点正在运行，请先停止后再修改。", status_code=409)
        job = self.store.load(job_id, user_id=user_id)
        if not job:
            raise CodeBuddyNpcError("NPC 剧本任务不存在。", status_code=404)
        value = str(content or "").strip()
        if not value:
            raise CodeBuddyNpcError("修改后的内容不能为空。", status_code=400)
        stage = next(key for key, item in STAGE_ARTIFACTS.items() if item == artifact_key)
        old = (
            str(job.get("final_script") or "")
            if artifact_key == "final_script"
            else str((job.get("recovered_files") or {}).get(artifact_key) or "")
        )
        next_index = STAGE_ORDER.index(stage) + 1
        if next_index < len(STAGE_ORDER):
            self._invalidate_from(job, STAGE_ORDER[next_index])
        versions = copy.deepcopy(job.get("stage_versions") or {})
        if old and old != value:
            history = versions.setdefault(artifact_key, [])
            history.append({"content": old, "saved_at": job.get("updated_at")})
            versions[artifact_key] = history[-10:]
        recovered = copy.deepcopy(job.get("recovered_files") or {})
        if artifact_key == "final_script":
            job["final_script"] = value
        else:
            recovered[artifact_key] = value
            job["recovered_files"] = recovered
        job["stage_versions"] = versions
        job["status"] = "stage_ready" if artifact_key != "final_script" else "completed"
        job["status_text"] = f"{ARTIFACT_LABELS[artifact_key]}已人工修改并保存"
        job["active_stage"] = ""
        return self.store.save(job)

    def _invalidate_from(self, job: dict[str, Any], stage: str) -> None:
        index = STAGE_ORDER.index(stage)
        recovered = copy.deepcopy(job.get("recovered_files") or {})
        versions = copy.deepcopy(job.get("stage_versions") or {})
        for invalid_stage in STAGE_ORDER[index:]:
            key = STAGE_ARTIFACTS[invalid_stage]
            old = str(job.get("final_script") or "") if key == "final_script" else str(recovered.get(key) or "")
            if old:
                history = versions.setdefault(key, [])
                history.append({"content": old, "saved_at": job.get("updated_at")})
                versions[key] = history[-10:]
            recovered.pop(key, None)
        job["recovered_files"] = recovered
        job["stage_versions"] = versions
        job["final_script"] = ""
        job["quality_gate"] = {}
        job["error"] = ""
        outputs = copy.deepcopy(job.get("stage_outputs") or {})
        for invalid_stage in STAGE_ORDER[index:]:
            outputs.pop(STAGE_NAMES[invalid_stage], None)
        job["stage_outputs"] = outputs
        job.pop("batch_progress", None)
        job.pop("stage_resume_text", None)
        pending = job.get("pending_batch") if isinstance(job.get("pending_batch"), dict) else {}
        if str(pending.get("stage") or "") in STAGE_ORDER[index:]:
            job.pop("pending_batch", None)

    def _run(
        self,
        *,
        job_id: str,
        user_id: int,
        start_stage: str,
        feedback: str,
        continue_after: bool,
        stop_after_stage: str = "",
    ) -> None:
        stages = STAGE_ORDER[STAGE_ORDER.index(start_stage) :] if continue_after else (start_stage,)
        if stop_after_stage:
            stages = stages[: STAGE_ORDER.index(stop_after_stage) - STAGE_ORDER.index(start_stage) + 1]
        try:
            for stage in stages:
                job = self.store.load(job_id, user_id=user_id)
                if not job:
                    return
                if job.get("cancel_requested"):
                    job["status"] = "stage_paused"
                    job["status_text"] = "流程已停止，已完成结果已保留"
                    job["active_stage"] = ""
                    self.store.save(job)
                    return
                self._execute_stage(job, stage, feedback if stage == start_stage else "")
            job = self.store.load(job_id, user_id=user_id)
            if not job:
                return
            job["active_stage"] = ""
            job["cancel_requested"] = False
            job["stop_after_stage"] = ""
            if stages[-1] == "final_editor":
                job["status"] = "completed"
                job["status_text"] = "专业剧本团队已交付"
                job["progress"] = 100
                job["error"] = ""
                job.pop("stage_resume_text", None)
            elif stop_after_stage and stages[-1] == stop_after_stage:
                job["status"] = "completed_scope"
                job["status_text"] = f"专业剧本团队已完成至{STAGE_NAMES[stop_after_stage]}"
                job["progress"] = 100
                job["error"] = ""
            else:
                next_index = STAGE_ORDER.index(stages[-1]) + 1
                job["status"] = "stage_ready"
                job["status_text"] = (
                    f"{STAGE_NAMES[stages[-1]]}已完成，"
                    f"等待确认后运行{STAGE_NAMES[STAGE_ORDER[next_index]]}"
                )
                job["progress"] = round(next_index / len(STAGE_ORDER) * 100)
            self.store.save(job)
        except (CodeBuddyNpcError, DeepSeekAgentError, Exception) as exc:
            job = self.store.load(job_id, user_id=user_id)
            if job:
                failed_stage = str(job.get("active_stage") or "")
                cancelled = bool(job.get("cancel_requested"))
                if failed_stage in STAGE_ORDER:
                    finish_stage_timing(
                        job,
                        failed_stage,
                        status="paused" if cancelled else "failed",
                    )
                if cancelled:
                    job["status"] = "stage_paused"
                    job["status_text"] = "流程已停止，已完成批次和中间产物均已保留"
                    job["error"] = ""
                else:
                    job["status"] = "failed"
                    job["status_text"] = (
                        f"{STAGE_NAMES.get(job.get('active_stage'), '节点')}运行失败"
                    )
                    job["error"] = str(exc)
                job["active_stage"] = ""
                self.store.save(job)
        finally:
            with self._lock:
                self._threads.pop(job_id, None)

    def _execute_stage(self, job: dict[str, Any], stage: str, feedback: str) -> None:
        job["active_stage"] = stage
        timing = (job.get("stage_timings") or {}).get(stage) or {}
        start_stage_timing(
            job,
            stage,
            reset=str(timing.get("status") or "") != "running",
            execution_target="local_fallback",
        )
        job["status"] = "stage_running"
        job["status_text"] = f"{STAGE_NAMES[stage]}正在运行"
        job["error"] = ""
        job.pop("poll_warning", None)
        job["progress"] = round(STAGE_ORDER.index(stage) / len(STAGE_ORDER) * 100)
        self.store.save(job)

        if stage == "state_recorder":
            result = _compact_story_state(job)
            self._save_stage_result(job, stage, result)
            return

        context: list[str] = []
        artifacts = job.get("recovered_files") or {}
        for key in DEPENDENCIES[stage]:
            context.append(f"\n\n===== {ARTIFACT_LABELS[key]} =====\n{artifacts[key]}")
        if stage == "final_editor":
            for key in ("story_state",):
                value = str(artifacts.get(key) or "").strip()
                if value:
                    context.append(
                        f"\n\n===== {ARTIFACT_LABELS[key]}（终审辅助） =====\n"
                        f"{_compact_context(value, 6_000)}"
                    )
        request_data = job.get("request") or {}
        request_text = json.dumps(request_data, ensure_ascii=False, indent=2)
        revision = f"\n\n===== 用户本次修改意见 =====\n{feedback}" if feedback else ""
        user_prompt = (
            f"===== 用户创作任务 =====\n{request_text}"
            + "".join(context)
            + _module_text(stage, artifacts)
            + _distilled_skill_text(stage, job)
            + _continuation_instruction(request_data)
            + revision
            + "\n\n严格执行 episode_start、episode_end 与 episodes；"
            "episode_word_count 是每集目标下限，episode_word_count_max 是最多上浮10%的"
            "硬上限，每集必须处于闭区间内；scenes_per_episode 是前端动态"
            "场景合同，必须逐集执行；不得改变上游已锁定事实。"
        )
        if stage in {"episode_continuity", "script_writer", "final_editor"} and int((job.get("request") or {}).get("episodes") or 1) > BATCH_SIZE:
            result = self._complete_script_batches(job, stage, feedback)
        else:
            response = deepseek_agent_client.complete(
                [
                    {"role": "system", "content": PROMPTS[stage].strip()},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.45 if stage in {"script_writer", "final_editor"} else 0.25,
                max_tokens=32768,
            )
            result = _strip_fence(str((response.get("message") or {}).get("content") or ""))
            self._record_usage(
                job=job,
                stage=stage,
                usage=response.get("usage"),
                input_chars=len(user_prompt) + len(PROMPTS[stage]),
                output_chars=len(result),
            )
        if not result:
            raise CodeBuddyNpcError(f"{STAGE_NAMES[stage]}返回空内容。", status_code=502)
        range_error = stage_episode_range_error(stage, result, request_data)
        if range_error:
            raise CodeBuddyNpcError(range_error, status_code=502)
        if stage == "state_recorder":
            result = _parse_state(result)

        self._save_stage_result(job, stage, result)

    def _save_stage_result(self, job: dict[str, Any], stage: str, result: str) -> None:
        fresh = self.store.load(str(job["job_id"]), user_id=int(job["user_id"]))
        if not fresh:
            return
        key = STAGE_ARTIFACTS[stage]
        recovered = copy.deepcopy(fresh.get("recovered_files") or {})
        if key == "final_script":
            fresh["final_script"] = result
        else:
            recovered[key] = result
            fresh["recovered_files"] = recovered
        outputs = copy.deepcopy(fresh.get("stage_outputs") or {})
        outputs[STAGE_NAMES[stage]] = result
        fresh["stage_outputs"] = outputs
        finish_stage_timing(fresh, stage, status="success")
        stages = []
        for item in STAGE_ORDER:
            artifact_key = STAGE_ARTIFACTS[item]
            has_output = bool(
                fresh.get("final_script") if artifact_key == "final_script" else recovered.get(artifact_key)
            )
            stages.append(
                {
                    "id": item,
                    "name": STAGE_NAMES[item],
                    "status": "success" if has_output else ("running" if item == stage else "pending"),
                    "duration": int(
                        ((fresh.get("stage_timings") or {}).get(item) or {}).get("duration_ms")
                        or 0
                    ),
                }
            )
        fresh["team_stages"] = stages
        self.store.save(fresh)

    def _record_usage(
        self,
        *,
        job: dict[str, Any],
        stage: str,
        usage: Any,
        input_chars: int,
        output_chars: int,
        batch_start: int | None = None,
        batch_end: int | None = None,
    ) -> None:
        fresh = self.store.load(str(job["job_id"]), user_id=int(job["user_id"]))
        if not fresh:
            return
        source = usage if isinstance(usage, dict) else {}
        prompt_tokens = int(source.get("prompt_tokens") or source.get("input_tokens") or 0)
        completion_tokens = int(source.get("completion_tokens") or source.get("output_tokens") or 0)
        cached_tokens = int(
            source.get("prompt_cache_hit_tokens")
            or source.get("cached_tokens")
            or ((source.get("prompt_tokens_details") or {}).get("cached_tokens") if isinstance(source.get("prompt_tokens_details"), dict) else 0)
            or 0
        )
        metrics = copy.deepcopy(fresh.get("usage_metrics") or {})
        metrics["calls"] = int(metrics.get("calls") or 0) + 1
        metrics["prompt_tokens"] = int(metrics.get("prompt_tokens") or 0) + prompt_tokens
        metrics["completion_tokens"] = int(metrics.get("completion_tokens") or 0) + completion_tokens
        metrics["cached_tokens"] = int(metrics.get("cached_tokens") or 0) + cached_tokens
        metrics["input_chars"] = int(metrics.get("input_chars") or 0) + int(input_chars)
        metrics["output_chars"] = int(metrics.get("output_chars") or 0) + int(output_chars)
        metrics["last_stage"] = stage
        metrics["provider_reported_tokens"] = bool(prompt_tokens or completion_tokens or cached_tokens)
        history = list(metrics.get("history") or [])
        history.append(
            {
                "stage": stage,
                "batch": [batch_start, batch_end] if batch_start is not None else None,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cached_tokens": cached_tokens,
                "input_chars": int(input_chars),
                "output_chars": int(output_chars),
            }
        )
        metrics["history"] = history[-80:]
        fresh["usage_metrics"] = metrics
        self.store.save(fresh)

    def _complete_script_batches(
        self,
        job: dict[str, Any],
        stage: str,
        feedback: str,
    ) -> str:
        request_data = job.get("request") or {}
        total = int(request_data.get("episodes") or 1)
        episode_start = max(1, int(request_data.get("episode_start") or 1))
        episode_end = max(
            episode_start,
            int(request_data.get("episode_end") or (episode_start + total - 1)),
        )
        minimum = int(request_data.get("episode_word_count") or 800)
        maximum = int(
            request_data.get("episode_word_count_max")
            or ((minimum * 110 + 99) // 100)
        )
        artifacts = job.get("recovered_files") or {}
        result = str(job.get("stage_resume_text") or "").strip()
        pending_batch = job.get("pending_batch") if isinstance(job.get("pending_batch"), dict) else {}
        if str(pending_batch.get("stage") or "") == stage:
            result = _merge_episode_outputs(
                result,
                str(pending_batch.get("content") or ""),
                episode_start=episode_start,
                episode_end=episode_end,
                stage=stage,
            )
        result = _merge_episode_outputs(
            "",
            result,
            episode_start=episode_start,
            episode_end=episode_end,
            stage=stage,
        )
        if not _missing_episode_ranges(
            result,
            episode_start=episode_start,
            episode_end=episode_end,
        ):
            return result

        if stage == "final_editor":
            context_limits = {"contract": 5_000, "characters": 5_000, "story_state": 6_000}
            fixed_keys = ("contract", "characters", "story_state")
        else:
            context_limits = {"contract": 5_000, "story": 8_000, "characters": 8_000}
            fixed_keys = ("contract", "story", "characters")
        fixed_context = "\n\n".join(
            f"===== {ARTIFACT_LABELS[key]}（成本优化摘要） =====\n"
            f"{_compact_context(str(artifacts[key]), context_limits[key])}"
            for key in fixed_keys
            if str(artifacts.get(key) or "").strip()
        )
        fixed_context += _module_text(stage, artifacts)
        fixed_context += _distilled_skill_text(stage, job)
        fixed_context += _continuation_instruction(request_data)
        batch_total = (episode_end - episode_start + BATCH_SIZE) // BATCH_SIZE
        no_progress_attempts: dict[tuple[int, int], int] = {}
        while True:
            missing_ranges = _missing_episode_ranges(
                result,
                episode_start=episode_start,
                episode_end=episode_end,
            )
            if not missing_ranges:
                break
            batch_start, batch_end = missing_ranges[0]
            fresh = self.store.load(str(job["job_id"]), user_id=int(job["user_id"]))
            if not fresh or fresh.get("cancel_requested"):
                raise CodeBuddyNpcError("流程已停止，已完成批次将作为断点保留。", status_code=409)
            expected = list(range(batch_start, batch_end + 1))
            completed_episodes = sorted(
                set(_episode_numbers(result))
                & set(range(episode_start, episode_end + 1))
            )
            fresh["batch_progress"] = {
                "stage": stage,
                "stage_name": STAGE_NAMES[stage],
                "current_start": batch_start,
                "current_end": batch_end,
                "completed_episodes": completed_episodes,
                "missing_ranges": [list(item) for item in missing_ranges],
                "completed_batches": (
                    len(completed_episodes) + BATCH_SIZE - 1
                ) // BATCH_SIZE,
                "total_batches": batch_total,
                "episode_total": total,
                "episode_start": episode_start,
                "episode_end": episode_end,
                "batch_size": BATCH_SIZE,
            }
            fresh["status_text"] = (
                f"{STAGE_NAMES[stage]}正在处理第{batch_start}-{batch_end}集，"
                f"本次共{total}集"
            )
            self.store.save(fresh)
            episode_cards = _episode_slice(str(artifacts.get("episodes") or ""), batch_start, batch_end)
            draft = _episode_slice(str(artifacts.get("draft") or ""), batch_start, batch_end)
            previous_text = _episode_slice(result, batch_start - 1, batch_start - 1)
            previous_tail = previous_text[-1800:] if previous_text else "无，这是第一批。"
            if stage == "episode_continuity":
                batch_material = "本批逐集卡尚未生成。请依据锁定故事为本批新建逐集连续性卡。"
                batch_draft = "不适用。本节点只设计逐集卡，不写剧本正文。"
                length_contract = (
                    "每集卡必须完整包含承接事实、开场钩子、最短因果锚、主角目标与动作、"
                    "阻力、选择与代价、主线推进、结尾状态和下一集第一有效动作。"
                )
            else:
                batch_material = episode_cards
                batch_draft = draft if stage == "final_editor" else "正文编剧根据逐集卡新写本批。"
                length_contract = (
                    f"每集必须在 {minimum} 至 {maximum} 字之间（含边界），不得少写，也不得超过。\n"
                    "超上限时只压缩重复解释、冗余动作、同义对白和无效铺垫；不得删除钩子、关键转折、\n"
                    "人物选择、情绪爆点、结尾钩子与集间承接。"
                )
            batch_prompt = f"""
===== 用户创作任务 =====
{json.dumps(request_data, ensure_ascii=False, indent=2)}

{fixed_context}

===== 本批逐集卡：第{batch_start}-{batch_end}集 =====
{batch_material}

===== 本批待修初稿 =====
{batch_draft}

===== 上一批结尾，仅用于连续承接 =====
{previous_tail}

本次是缺失集定向补齐。只输出第{batch_start}集至第{batch_end}集，共{len(expected)}集，不得重写已完成集。
{length_contract}
保持统一集号格式；正文节点还必须保持场景格式、人物署名对白和人物名OS。
普通停顿使用逗号、句号、问号或感叹号；迟疑和未尽使用省略号。
破折号只用于突然打断、猛然改口或强制语义跳转，禁止把它当成通用节奏符号。
{("本次修改意见：" + feedback) if feedback else ""}
"""
            response = deepseek_agent_client.complete(
                [
                    {"role": "system", "content": PROMPTS[stage].strip()},
                    {"role": "user", "content": batch_prompt.strip()},
                ],
                temperature=0.45,
                max_tokens=32768,
            )
            batch = _strip_fence(str((response.get("message") or {}).get("content") or ""))
            pending = self.store.load(str(job["job_id"]), user_id=int(job["user_id"]))
            if pending:
                pending["pending_batch"] = {
                    "stage": stage,
                    "start": batch_start,
                    "end": batch_end,
                    "content": batch,
                }
                self.store.save(pending)
            self._record_usage(
                job=job,
                stage=stage,
                usage=response.get("usage"),
                input_chars=len(batch_prompt) + len(PROMPTS[stage]),
                output_chars=len(batch),
                batch_start=batch_start,
                batch_end=batch_end,
            )
            before = set(_episode_numbers(result))
            result = _merge_episode_outputs(
                result,
                batch,
                episode_start=episode_start,
                episode_end=episode_end,
                stage=stage,
            )
            added = set(_episode_numbers(result)) - before
            if not added.intersection(expected):
                key = (batch_start, batch_end)
                no_progress_attempts[key] = no_progress_attempts.get(key, 0) + 1
            else:
                no_progress_attempts.pop((batch_start, batch_end), None)
            if no_progress_attempts.get((batch_start, batch_end), 0) >= 3:
                raise CodeBuddyNpcError(
                    f"{STAGE_NAMES[stage]}连续3次未能补齐第{batch_start}-{batch_end}集，"
                    f"已保留集号{_episode_numbers(result)}作为断点。",
                    status_code=502,
                )
            checkpoint = self.store.load(str(job["job_id"]), user_id=int(job["user_id"]))
            if checkpoint:
                checkpoint["stage_resume_text"] = result
                checkpoint.pop("pending_batch", None)
                remaining = _missing_episode_ranges(
                    result,
                    episode_start=episode_start,
                    episode_end=episode_end,
                )
                completed_episodes = sorted(
                    set(_episode_numbers(result))
                    & set(range(episode_start, episode_end + 1))
                )
                checkpoint["batch_progress"] = {
                    "stage": stage,
                    "stage_name": STAGE_NAMES[stage],
                    "current_start": batch_start,
                    "current_end": batch_end,
                    "completed_episodes": completed_episodes,
                    "missing_ranges": [list(item) for item in remaining],
                    "completed_batches": (
                        len(completed_episodes) + BATCH_SIZE - 1
                    ) // BATCH_SIZE,
                    "total_batches": batch_total,
                    "episode_total": total,
                    "episode_start": episode_start,
                    "episode_end": episode_end,
                    "batch_size": BATCH_SIZE,
                }
                checkpoint["status_text"] = (
                    f"{STAGE_NAMES[stage]}已保存{len(completed_episodes)}/{total}集，"
                    + (f"正在补齐缺失集{remaining[0][0]}-{remaining[0][1]}" if remaining else "集数已齐全")
                )
                checkpoint["progress"] = round(
                    (
                        STAGE_ORDER.index(stage)
                        + len(completed_episodes) / total
                    )
                    / len(STAGE_ORDER)
                    * 100
                )
                self.store.save(checkpoint)
        return result
