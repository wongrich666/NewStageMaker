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
    start_stage_timing,
)
from .deepseek_agent import DeepSeekAgentError, deepseek_agent_client


PROMPTS = {
    "showrunner": """
你是跨题材、跨市场的剧集总编剧。输出精炼、可执行的《创作任务书》。
锁定题材、受众、主角、核心欲望、核心阻力、情绪承诺、主题、结局方向和不可篡改事实。
按照技能路由模块判断增强能力，并原样输出一行合法的 SKILL_ROUTING_JSON。
题材不能直接决定套路；用户信息不足时由你作出专业判断，不把选择责任退还给用户。
为主角锁定“外在身份/处境+长期欲望或伤口+反差能力/秘密”的可执行标签，
并规定前五集立住主角标签、核心矛盾、主要阻力、情绪承诺和追剧主问题。
episode_start、episode_end 与 episodes 共同构成交付范围，必须只交付该范围。
不要写正文。所有人物、道具、技术、证据和事件都按题材与因果需要决定：
需要时可以使用，不需要时不得为了套模板硬塞；禁止的不是某类元素，而是无来源、无铺垫、
无代价、承担万能解题功能的元素。
""",
    "story_architect": """
你是故事架构师。依据创作任务书建立可执行故事圣经。
输出主线、最多三条有效支线、人物关系债、前史未偿还冲突、因果链、秘密揭露顺序、
升级机制和结局兑现。支线必须回撞主线，每个解决必须制造新的代价。
回忆若存在，必须有目标、阻力、转折、选择、代价，并留下影响现在的债务。
不得改变创作任务书锁定的事实，不得提前写逐集正文。
""",
    "character_emotion": """
你是人物与情感编剧。基于锁定故事补足主要人物的外在目标、隐藏需求、恐惧、羞耻、
自我谎言、关系债、压力行为、声音配方和情感转折。
心理活动采用“假设—验证—被推翻”的动态过程。用具体行为和语言表现感情，
不以抽象形容词代替反应，不让人物为推进情节突然降智。
每个主要人物必须有一句可记忆标签及一组真正参与剧情的反差；
前五集内用行动落地标签、伤口、自我谎言和主要关系压力。
每个主要人物必须有可区分的句长、回避方式、压力反应、潜台词和三句声音样本。
不得改写主线和主要事件。
""",
    "episode_continuity": """
你是分集与连续性编剧。严格按 episode_start 至 episode_end 设计完整逐集卡。
每集写清：承接点、前五秒短钩子、主角目标、A线与叠加压力线、核心场景、
行动、阻力、选择、代价、转折、尾钩、下一集开场承接动作。
第一集第一有效拍必须达到黄金三秒门槛：至少同时形成冲突、悬念、反差、
危险后果中的两项。每集至少一个情绪高点，每30至60秒发生局势变化或情绪释放。
前五集完成基础立剧，后续只升级、变奏和兑现，不再补基础人设。
第N集结尾与第N+1集开头必须形成：
未完成动作或结果→人物决定→去向或受阻→下一集开场动作。
scenes_per_episode 是前端动态传入的逐集场景合同，必须执行；只有设置为 flexible
时才可按剧情灵活决定。每个场景必须注明地点、日夜、内外、在场人物、关键道具和戏剧任务。
换场必须说明人物为什么去以及准备做什么，禁止人物和关键道具无来源突然出现。
""",
    "script_writer": """
你是唯一的正文与对白编剧。根据全部锁定材料写出 episode_start 至 episode_end 的完整可拍剧本。
每集必须使用以下结构，不得省略场景信息：
第N集：《本集独有标题》
场景1：地点｜日/夜｜内/外
人物：本场实际出场人物
随后立即进入动作与对白。禁止输出“场景任务”“道具清单”等策划字段；
道具只在人物真正使用时自然出现在动作中。换场时继续写“场景2”及人物。
每集必须有简短、具体、能区分剧情的标题，禁止只写“第N集”或使用“新的开始”等空泛标题。
所有对白必须独立成行并采用“人物名：说了什么”的格式，例如：
埃里克：别回头。
关键对白需要呈现当下语气或情绪与眉眼神情时，统一采用
“人物名：（语气/情绪，眉眼神情）台词”，例如：
打工鱼：（无奈，眉心微蹙）呃，我……
括号必须紧跟冒号并使用中文全角括号。括号内写简短、可表演、镜头可见的信息，
优先同时包含语气或情绪与眼神、眉头等面部反应；禁止写心理解释、长动作或“生气地说道”。
每集的关键情绪转折对白至少使用一次，但不得每句都加、不得连续复用同一神情。
所有需要呈现给观众的心理活动必须采用“人物名OS：心理活动”的格式，例如：
埃里克OS：他怎么会知道这件事？
禁止出现没有人物名前缀的对白，禁止只写“OS：”或“内心：”，也不要给普通动作错误添加人物冒号。
第一集场景头之后的第一句台词或第一个动作必须形成短而强的黄金三秒钩子，
至少同时形成冲突、悬念、反差、危险后果中的两项；一句话足够时立即收住。
禁止先介绍环境、解释会议背景、逐个点名人物或罗列道具，再让核心事件迟到；
直接从异常结果、高压命令、关系反转或主角即将付出代价的动作开场。
其他集开头必须承接上集结尾动作，由主角持续推动，不得瞬移。
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
episode_word_count 是前端动态传入的每集最低字数，不是固定值，也不是上限。
每集不得少于该值；允许根据剧情需要自然超出，禁止因超过该值而删戏、压缩或返工。
严格执行 scenes_per_episode：1 表示每集一个场景；1-2 表示每集一至两个场景；
2 表示每集两个场景；2-3 表示每集两至三个场景；flexible 才允许按剧情灵活安排。
不得为了凑场景数拆碎同一地点的连续动作；换场必须有可见动机和行动承接。
只输出片名和逐集剧本正文，不输出解释、评分或创作报告。
""",
    "state_recorder": """
你是状态记录器，不是编剧。只从人物设计、分集卡和初稿中提取事实。
严格按照给定 story_state schema 输出单个合法 JSON 对象，记录人物声音、位置、
知情范围、伤势、服装、持有道具、关系变化、新人物与新道具来源、伏笔和未完成动作。
episodes 数组必须完整覆盖 episode_start 至 episode_end。未知事实写“未明确”，不得猜测、评价或改写正文。
""",
    "final_editor": """
你是唯一终审编辑。直接修订完整剧本，不只审查和打分。
保持创作合同、主要事件、人物关系和结局方向，逐集修复黄金五秒钩子、集间承接、
多线压力、人物选择代价、泄气对白、AI味语言和连续性问题。
第一集黄金三秒至少同时形成冲突、悬念、反差、危险后果中的两项；前五集必须
已经立住主角标签、核心矛盾、主要阻力、情绪承诺和追剧主问题。
逐集保留至少一个真正改变局势的情绪高点，并让尾钩直接驱动下一集开场。
钩子不足时根据上下文新增或重写，并同步修正后文因果，不能机械搬运后文冲突。
最终每集标题必须统一为“第N集：《本集独有标题》”，不得删掉集名。
严格保留 scenes_per_episode 对应的场景数量规则；需要换场时补齐人物去向、目的和承接动作，
不得在终审中随意增删场景造成瞬移。
每一集只保留紧凑场景头：“场景N：地点｜日/夜｜内/外”“人物”，随后立即进入戏。
删除所有“场景任务”和独立“道具”清单，道具只能在被使用时写入动作。
所有对白必须保持“人物名：台词”；所有心理活动必须保持“人物名OS：心理活动”。
发现无人物归属的对白时必须补齐说话者，发现“OS/内心旁白”时必须改成对应人物名OS。
逐集检查关键情绪对白，补成“人物名：（语气/情绪，眉眼神情）台词”。
括号内容必须简短、可演、符合当下关系压力，不得每句添加或重复同一套表情。
逐句校正标点：逗号和句号承担普通停顿与陈述，问号和感叹号承担明确语气，
省略号承担迟疑或未尽之意；破折号只保留在突然中断、猛然改口和强制语义跳转处。
删除装饰性、连续性和动作连接型破折号，不得为了制造紧张感给普通句子统一加“——”。
所有元素按剧情需要使用；只删除无来源、无铺垫、无代价或承担万能解题功能的元素。
episode_word_count 是前端动态传入的每集最低字数，不是上限。终审只能补足
低于最低字数的集数，禁止因超过该值而压缩、删戏或反复返工。
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
    # story_state strengthens the edit when available, but a recovered draft can
    # still be finished after a remote interruption that lost this derived file.
    "final_editor": ("contract", "story", "characters", "episodes", "draft"),
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
        previous_closing = closing
    payload = {
        "schema_version": "1.0",
        "project": {
            "title": str(request_data.get("project_title") or "未命名剧本"),
            "protagonist": "见人物方案",
            "episode_count": total,
            "target_words_per_episode": int(request_data.get("episode_word_count") or 800),
            "immutable_facts": ["完整事实保存在创作合同、故事架构和人物方案中"],
        },
        "characters": [],
        "props": [],
        "episodes": episodes,
        "open_threads": [],
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


def _continuation_instruction(request_data: dict[str, Any]) -> str:
    if str(request_data.get("mode") or "") != "续写":
        return ""
    source_last = max(1, int(request_data.get("source_last_episode") or 1))
    episode_start = max(source_last + 1, int(request_data.get("episode_start") or (source_last + 1)))
    episode_end = max(episode_start, int(request_data.get("episode_end") or episode_start))
    policy = str(request_data.get("continuation_policy") or "strict")
    return (
        "\n\n===== 续写硬合同 =====\n"
        f"已有剧本写至第{source_last}集，本次只能输出第{episode_start}集至"
        f"第{episode_end}集，不得重写已有集数。续写策略：{policy}。\n"
        f"第{episode_start}集必须承接已有第{source_last}集最后的地点、动作、"
        "人物知情、伤势、关系、道具和未完成事件；先延续后升级，禁止重置人物、"
        "跳过过程、无解释换场或让既有后果自动消失。"
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
        if stage == "final_editor":
            current_final = str(job.get("final_script") or "").strip()
            numbers = _episode_numbers(current_final)
            request_data = job.get("request") or {}
            episode_start = max(1, int(request_data.get("episode_start") or 1))
            episode_end = max(
                episode_start,
                int(request_data.get("episode_end") or episode_start),
            )
            job["stage_resume_text"] = (
                current_final
                if numbers == list(range(episode_start, episode_start + len(numbers)))
                and numbers
                and numbers[-1] < episode_end
                else ""
            )
        self._invalidate_from(job, stage)
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
        job["status_text"] = "将在当前节点返回后停止"
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
                if failed_stage in STAGE_ORDER:
                    finish_stage_timing(job, failed_stage, status="failed")
                job["status"] = "failed"
                job["status_text"] = f"{STAGE_NAMES.get(job.get('active_stage'), '节点')}运行失败"
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
        request_data = job.get("request") or {}
        request_text = json.dumps(request_data, ensure_ascii=False, indent=2)
        revision = f"\n\n===== 用户本次修改意见 =====\n{feedback}" if feedback else ""
        user_prompt = (
            f"===== 用户创作任务 =====\n{request_text}"
            + "".join(context)
            + _module_text(stage, artifacts)
            + _continuation_instruction(request_data)
            + revision
            + "\n\n严格执行 episode_start、episode_end 与 episodes；"
            "episode_word_count 是前端动态传入的每集"
            "最低字数，只能多不能少且不设上限；scenes_per_episode 是前端动态"
            "场景合同，必须逐集执行；不得改变上游已锁定事实。"
        )
        if stage in {"script_writer", "final_editor"} and int((job.get("request") or {}).get("episodes") or 1) > BATCH_SIZE:
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
        artifacts = job.get("recovered_files") or {}
        result = str(job.get("stage_resume_text") or "").strip() if stage == "final_editor" else ""
        existing = _episode_numbers(result)
        expected_prefix = list(range(episode_start, episode_start + len(existing)))
        start_episode = (
            episode_start + len(existing)
            if existing == expected_prefix
            else episode_start
        )
        if start_episode > episode_end:
            return result

        context_limits = {"contract": 5_000, "story": 8_000, "characters": 8_000}
        fixed_context = "\n\n".join(
            f"===== {ARTIFACT_LABELS[key]}（成本优化摘要） =====\n"
            f"{_compact_context(str(artifacts[key]), context_limits[key])}"
            for key in ("contract", "story", "characters")
            if str(artifacts.get(key) or "").strip()
        )
        fixed_context += _module_text(stage, artifacts)
        fixed_context += _continuation_instruction(request_data)
        batch_total = (episode_end - start_episode + BATCH_SIZE) // BATCH_SIZE
        completed_ranges: list[list[int]] = []
        for batch_start in range(start_episode, episode_end + 1, BATCH_SIZE):
            fresh = self.store.load(str(job["job_id"]), user_id=int(job["user_id"]))
            if not fresh or fresh.get("cancel_requested"):
                raise CodeBuddyNpcError("流程已停止，已完成批次将作为断点保留。", status_code=409)
            batch_end = min(episode_end, batch_start + BATCH_SIZE - 1)
            expected = list(range(batch_start, batch_end + 1))
            fresh["batch_progress"] = {
                "stage": stage,
                "stage_name": STAGE_NAMES[stage],
                "current_start": batch_start,
                "current_end": batch_end,
                "completed_ranges": completed_ranges,
                "completed_batches": len(completed_ranges),
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
            previous_tail = result[-1800:] if result else "无，这是第一批。"
            batch_prompt = f"""
===== 用户创作任务 =====
{json.dumps(request_data, ensure_ascii=False, indent=2)}

{fixed_context}

===== 本批逐集卡：第{batch_start}-{batch_end}集 =====
{episode_cards}

===== 本批待修初稿 =====
{draft if stage == "final_editor" else "正文编剧根据逐集卡新写本批。"}

===== 上一批结尾，仅用于连续承接 =====
{previous_tail}

只输出第{batch_start}集至第{batch_end}集，共{len(expected)}集，不得输出其他集。
每集不得少于前端动态设定的最低字数 {minimum} 字，允许自然超出且不设上限。
不得因超字数压缩、删戏或返工。保持统一场景格式、人物署名对白和人物名OS。
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
            self._record_usage(
                job=job,
                stage=stage,
                usage=response.get("usage"),
                input_chars=len(batch_prompt) + len(PROMPTS[stage]),
                output_chars=len(batch),
                batch_start=batch_start,
                batch_end=batch_end,
            )
            numbers = _episode_numbers(batch)
            if numbers != expected:
                raise CodeBuddyNpcError(
                    f"{STAGE_NAMES[stage]}第{batch_start}-{batch_end}集批次集号异常：{numbers}",
                    status_code=502,
                )
            result = _append_episode_batch(result, batch)
            completed_ranges.append([batch_start, batch_end])
            checkpoint = self.store.load(str(job["job_id"]), user_id=int(job["user_id"]))
            if checkpoint:
                checkpoint["stage_resume_text"] = result
                checkpoint["batch_progress"] = {
                    "stage": stage,
                    "stage_name": STAGE_NAMES[stage],
                    "current_start": batch_start,
                    "current_end": batch_end,
                    "completed_ranges": completed_ranges,
                    "completed_batches": len(completed_ranges),
                    "total_batches": batch_total,
                    "episode_total": total,
                    "episode_start": episode_start,
                    "episode_end": episode_end,
                    "batch_size": BATCH_SIZE,
                }
                checkpoint["status_text"] = (
                    f"{STAGE_NAMES[stage]}已完成第{batch_start}-{batch_end}集，"
                    f"继续处理至第{episode_end}集"
                )
                checkpoint["progress"] = round(
                    (
                        STAGE_ORDER.index(stage)
                        + (batch_end - episode_start + 1) / total
                    )
                    / len(STAGE_ORDER)
                    * 100
                )
                self.store.save(checkpoint)
        return result
