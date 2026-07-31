from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import requests


ROOT = Path(os.getenv("SCRIPT_TEAM_STATE_DIR", "/tmp/script-team"))
ROOT.mkdir(parents=True, exist_ok=True)

ROLE_ORDER = [
    "showrunner",
    "story_architect",
    "character_emotion",
    "episode_continuity",
    "script_writer",
    "state_recorder",
    "final_editor",
]

ROLE_FILES = {
    "showrunner": "01_showrunner.txt",
    "story_architect": "02_story_architect.txt",
    "character_emotion": "03_character_emotion.txt",
    "episode_continuity": "04_episode_continuity.txt",
    "script_writer": "05_script_writer.txt",
    "state_recorder": "story_state.json",
    "final_editor": "07_final_script.txt",
}

ARTIFACT_ROLE_MAP = {
    "contract": "showrunner",
    "story": "story_architect",
    "characters": "character_emotion",
    "episodes": "episode_continuity",
    "draft": "script_writer",
    "story_state": "state_recorder",
    "final_script": "final_editor",
}

CONTEXT_FILES = {
    "story_architect": ("showrunner",),
    "character_emotion": ("showrunner", "story_architect"),
    "episode_continuity": ("showrunner", "story_architect", "character_emotion"),
    "script_writer": ("showrunner", "story_architect", "character_emotion", "episode_continuity"),
    "state_recorder": ("character_emotion", "episode_continuity", "script_writer"),
    "final_editor": ("script_writer", "state_recorder"),
}

SKILL_ROOT = Path(
    os.getenv("SCRIPT_ROOM_SKILL_DIR", "/root/.codebuddy/skills/script-room")
)
MODULE_FILES = {
    "routing": "skill-routing.md",
    "hook": "hook-craft.md",
    "voice": "character-voice.md",
    "continuity": "continuity.md",
    "continuation": "continuation.md",
    "state": "story-state-schema.md",
    "adversity_payoff": "adversity-payoff.md",
}
STAGE_MODULES = {
    "showrunner": ("routing", "continuation"),
    "character_emotion": ("voice",),
    "episode_continuity": ("hook", "continuity", "continuation"),
    "script_writer": ("hook", "voice", "continuity", "continuation"),
    "state_recorder": ("continuity", "continuation", "state"),
    "final_editor": ("hook", "voice", "continuity", "continuation"),
}
DYNAMIC_STAGE_MODULES = {
    "story_architect": ("adversity_payoff",),
    "character_emotion": ("adversity_payoff",),
    "episode_continuity": ("adversity_payoff",),
    "script_writer": ("adversity_payoff",),
    "state_recorder": ("adversity_payoff",),
    "final_editor": ("adversity_payoff",),
}
ROUTING_RE = re.compile(r"SKILL_ROUTING_JSON\s*:\s*(\{[^\r\n]+\})")
EPISODE_HEADER_RE = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*|__)?\s*"
    r"(?:(?:第\s*(?P<zh>\d{1,3})\s*集)|(?:Episode\s*(?P<en>\d{1,3})))"
    r"(?:\s*[-—:：].*)?(?:\*\*|__)?\s*$"
)
SCENE_HEADER_RE = re.compile(
    r"(?im)^\s*(?:#{1,6}\s+)?(?:[-+*]\s+)?(?:\*\*|__)?\s*"
    r"(?:场景\s*(?:\d+|[一二三四五六七八九十百零〇两]+)?\s*(?=[：:])"
    r"|\d{1,3}\s*[-－—]\s*\d{1,2}(?=\s|[：:])"
    r"|(?:内|外|内外)\s*[·.．]|(?:INT|EXT)\s*[.．])"
)
SCENE_CONTRACTS = {
    "1": (1, 1, "每一大集必须且只能有1个场景"),
    "1-2": (1, 2, "每一大集允许1至2个场景"),
    "2": (2, 2, "每一大集必须且只能有2个场景"),
    "2-3": (2, 3, "每一大集允许2至3个场景"),
    "flexible": (1, None, "每一大集按剧情灵活安排，但至少有1个明确场景"),
}

PROMPTS = {
    "showrunner": """
你是专业剧集总编剧。根据用户任务输出精炼的《创作任务书》。
必须锁定：题材与目标观众、主角、核心欲望、核心阻力、情绪承诺、主题、结局方向、
不可篡改事实、禁用套路。识别AI漫剧或AI真人剧及目标市场。
按照 skill-routing 模块判断增强能力，并原样输出一行合法的 SKILL_ROUTING_JSON。
题材不能直接决定套路；用户信息不足时由你作出专业判断，不把选择责任退还给用户。
为主角锁定“外在身份/处境+长期欲望或伤口+反差能力/秘密”的可执行标签，
并规定前五集必须立住主角标签、核心矛盾、主要阻力、情绪承诺和追剧主问题。
episode_start、episode_end 与 episodes 共同定义本次唯一交付范围，必须原样锁定，
忽略补充方向中与数值集数冲突的单集试写或只交付某一集要求。
不要写正文，不要堆砌事件。人物、道具、证据与技术根据剧情需要决定；
禁止的是无来源、无铺垫、无代价的万能解题元素。
""",
    "story_architect": """
你是故事架构师。读取创作任务书，建立可执行的故事圣经。
输出主线、最多三条有效支线、人物关系债、前史未偿还冲突、因果链、秘密揭露顺序、
升级机制和结局兑现。每条支线必须回撞主线，每个解决必须产生代价。
回忆若存在，必须拥有目标、阻力、转折、选择、代价，并留下影响现在的债务。
""",
    "character_emotion": """
你是人物与情感编剧。基于已锁定的故事，不改变主要事件，补足人物内在动力。
为主要人物写：外在目标、隐藏需求、恐惧、羞耻、自我谎言、关系债、压力行为、
声音配方和情感转折。心理活动采用假设、验证、被推翻的动态过程。
每个主要人物必须有一句可被观众记住的标签及一组真正参与剧情的反差；
前五集内用行动落地标签、伤口、自我谎言和主要关系压力。
不得用抽象形容词代替具体反应，不得让人物为推动剧情突然降智。
""",
    "episode_continuity": """
你是分集与连续性编剧。严格按用户要求的集号范围、每集字数规模和画面时长设计逐集卡。
必须依次设计 episode_start 至 episode_end，不得缺集、越界或只设计试写集。
每集写清：承接点、前五秒短钩子、主角目标、A线与至少一条叠加压力线、场景、
行动、阻力、选择、代价、转折、结尾钩子、下一集开场承接动作，以及各段预计秒数。
第一集及新冲突首次出现时必须规划“开场因果锚”：钩子本身已包含原因则标记“已内嵌”；
否则指定在钩子后由哪个在场人物、哪项可见结果或哪条正在生效的规则，用最短一拍让
观众理解为什么此刻发生、为什么落到这个人物身上，不得泄露完整前史。
scenes_per_episode 是逐集场景数量硬合同。1表示每一大集只能有一个场景，
1-2表示每集一至两个，2表示每集必须两个，2-3表示每集两至三个，
只有 flexible 才允许按剧情灵活安排。不得把一个场景内的小节拍拆成新场景。
第一集第一有效拍必须达到黄金三秒门槛：至少同时形成冲突、悬念、反差、
危险后果中的两项。每集至少一个情绪高点，每30至60秒出现一次局势变化或情绪释放。
前五集必须完成基础立剧，后续只升级、变奏和兑现，不得再补基础人设。
男频默认男主持续推动，女频默认女主持续推动；场景转换必须说明为什么去。
""",
    "script_writer": """
你是唯一的正文与对白编剧。根据全部锁定材料写出完整分集剧本。
必须完整写出 episode_start 至 episode_end 且不多不少，每集标题统一使用
“第N集：《本集独有标题》”；标题必须简短、具体并能区分本集剧情。
数值集数优先于补充方向中的单集试写文字。
episode_word_count 是前端动态传入的每集最低字数，不是固定值，也不是上限。
每集不得少于该值；允许根据剧情需要自然超出，禁止因超过该值而删戏、压缩或返工。
episode_duration_seconds 是每集目标画面时长。按对白实际说完、自然停顿、人物反应、
动作完成、信息揭示和必要转场所占时间组织内容，不得把字数机械换算成秒数。
第一集场景头之后的第一句台词或第一个动作必须构成短而强的黄金三秒钩子，
至少同时形成冲突、悬念、反差、危险后果中的两项；一句话足够时立即收住。
禁止先铺陈环境、解释背景、逐个介绍人物或罗列道具，再让核心事件迟到。
强钩子后的1至3个有效拍内补足“开场因果锚”，只让观众理解眼前处境为何发生：
优先使用本来就在场且有信息来源的人物反应、对手指控、主角反问、公开通知、可见痕迹
或规则反馈。不得固定使用路人解释；第三方开口必须同时在劝阻、站队、起哄、施压、
自保或受到波及，不能像作者一样概述背景。钩子本身已经包含清楚原因时不得重复解释。
每集开头承接上一集结尾动作，每集由主角行动推动，不得瞬移。
严格执行 scenes_per_episode。场景数按每一大集内出现的“场景N”标题计数；
一个动作段、冲突阶段或人物进入不能自行升级为新场景。
每集至少出现一次改变资源、关系、认知、身份、行动条件或风险等级的情绪高点，
并用尾钩直接改变下一集开场行动，禁止集间冷却或另起无关事件。
每集只写紧凑场景头“场景N：地点｜日/夜｜内/外”和“人物”，然后立刻进入戏。
场景头和人物行使用纯文本，不添加 Markdown 加粗符号或标题符号。
禁止输出“场景任务”和独立“道具”清单；道具只在人物真正使用时自然写入动作。
每次换场重新写场景头和人物即可。
所有对白必须独立成行，采用“人物名：台词”；所有心理活动必须采用
“人物名OS：心理活动”。不得输出无人物名前缀的对白或单独的“OS：”。
关键对白涉及当下表演时，采用“人物名：（语气/情绪，眉眼神情）台词”，例如：
“打工鱼：（无奈，眉心微蹙）呃，我……”。括号必须紧跟冒号并使用中文全角括号；
内容要短、可演、镜头可见，不能写心理解释、长动作或“生气地说道”。
每集关键情绪转折对白至少使用一次，但不得每句都加或连续复用同一神情。
动作短、可视、可由AI生成；对白口语化、有潜台词，人物声音可区分。
删除多余形容词、气氛铺垫、剧情复述和解释性对白。
标点服从真实口语与动作节奏，禁止把破折号“——”当成默认停顿符。
完整陈述和普通转折使用逗号、句号、问号或感叹号；迟疑、吞回半句话或声音渐弱使用省略号；
只有台词被突然打断、人物猛然改口或语义发生强制跳转时才使用破折号。
同一段或同一句不得连续堆叠破折号，普通动作衔接不得写成“动作——结果”。
例如“实习生是吧——这个月工资扣一半！”应写成“实习生是吧？这个月工资扣一半！”；
“说啊。说啊。你倒是说啊——”应按情绪写成“说啊。你倒是说啊！”。
""",
    "state_recorder": """
你是状态记录器，不是编剧。只从用户任务、人物设计、分集卡和初稿提取事实，
不得评价、润色、修复或改写正文。严格按照 story-state-schema.md 输出单个合法
JSON 对象，记录人物声音、位置、知情范围、伤势、服装、持有道具、关系变化、
新人物和新道具来源、伏笔与未完成动作。未知事实写“未明确”，不得猜测。
""",
    "final_editor": """
你是唯一终审编辑，合并钩子编辑和终审导演职责。必须直接修稿，不只审查和打分。
最终稿必须完整包含 episode_start 至 episode_end 且不多不少。保持主要事件、
人物关系和结局不变，逐集修复：
1. 第一集黄金三秒必须是一句命令、双关、禁忌信息、危险动作或关系反转形成的爆点，
   至少同时形成冲突、悬念、反差、危险后果中的两项；
1.1 若缺少开场因果锚、观众仍不明白眼前处境为何发生，在强钩子后1至3个有效拍内补足：
    使用有来源的人物反应、指控、可见结果或规则反馈交代最小原因；不得在钩子前铺垫，
    不得新增只负责讲解的路人，也不得把完整前史一次说完；
2. 其他集开头必须承接上集结尾；
3. 增强同场多线压力、人物选择代价和每集至少一个真正改变局势的情绪高点；
4. 改写泄气、解释性、AI味对白；
5. 删掉不影响动作、信息和情绪的形容词。
episode_word_count 是前端动态传入的每集最低字数，不是上限。只能补足低于
最低字数的集数，不得因超过该值而压缩、删戏或反复返工。
逐集修正 deterministic_gate 中的时长偏差，使对白、停顿、动作与镜头节拍合计
接近 episode_duration_seconds；优先删重复解释或补有效反应与因果动作，不得注水。
钩子不足时可以依据上下文新增，不得只是把后文冲突搬到前面。
最终每集必须保留“第N集：《本集独有标题》”，不得在终审时删掉集名。
每集只保留“场景N：地点｜日/夜｜内/外”和“人物”两项紧凑场景信息；
删除“场景任务”和独立“道具”清单，道具只在真正使用时进入动作。
所有对白保持“人物名：台词”，所有心理活动保持“人物名OS：心理活动”。
逐集为关键情绪对白补充“人物名：（语气/情绪，眉眼神情）台词”格式，
括号必须简短、可演并符合当下压力；不得滥用、不得机械重复同一表情。
逐句校正标点：普通停顿与陈述使用逗号、句号，明确语气使用问号、感叹号，
迟疑或未尽之意使用省略号；破折号只保留在突然中断、猛然改口和强制语义跳转处。
删除装饰性、连续性和动作连接型破折号，不得用破折号给普通句子强行制造紧张感。
同时修复人物、服装、伤势、道具、时间、场景和AI生成可执行性问题。
严格保留 scenes_per_episode 的逐集场景数量，不得为了增强节奏擅自增加场景。
只输出最终完整剧本，不输出评分、解释、JSON、修改说明或复核过程。
""",
}


def scene_contract_instruction(request_payload: dict) -> str:
    policy = str(request_payload.get("scenes_per_episode") or "1").strip().lower()
    if policy not in SCENE_CONTRACTS:
        policy = "1"
    _minimum, _maximum, description = SCENE_CONTRACTS[policy]
    return (
        f"逐集场景硬合同：scenes_per_episode={policy}，{description}。"
        "这里的“每集”指第N集这一整集，不是集内的小阶段；"
        "场景数只按该集中的“场景N：地点｜日/夜｜内/外”标题计算。"
    )


def duration_contract_instruction(request_payload: dict) -> str:
    episodes = max(1, int(request_payload.get("episodes") or 1))
    seconds = max(15, int(request_payload.get("episode_duration_seconds") or 90))
    return (
        f"逐集画面时长合同：每集目标约{seconds}秒，全剧约{episodes * seconds}秒，"
        "允许单集在目标上下约15%内自然浮动。按可见画面实际计时："
        "短促眼神、眨眼、吸气或反应约1至2秒，明确手势或单步动作约1至3秒，"
        "移动、操作或关系动作约3至8秒；中文对白通常按每秒约4个汉字并叠加"
        "情绪停顿估算。动作可并行时不得重复累计，禁止靠空镜、慢动作或重复台词凑时长。"
    )


def continuation_contract_instruction(request_payload: dict) -> str:
    if str(request_payload.get("mode") or "").strip() != "续写":
        return ""
    source_last = max(1, int(request_payload.get("source_last_episode") or 1))
    episode_start = max(source_last + 1, int(request_payload.get("episode_start") or source_last + 1))
    episode_end = max(episode_start, int(request_payload.get("episode_end") or episode_start))
    policy = str(request_payload.get("continuation_policy") or "strict").strip()
    policy_text = (
        "允许修复不改变既有事件结果的轻微连续性问题"
        if policy == "light"
        else "严格保留既有事实、人物声音、关系温度、伤势、位置、道具与未完成动作"
    )
    return (
        f"续写硬合同：已有剧本写至第{source_last}集，已有第{source_last}集结尾是"
        f"第{episode_start}集唯一开场起点；本次只输出第{episode_start}集至第{episode_end}集。"
        f"{policy_text}。先从已有全文提取续写基线，再规划新剧情；"
        "不得重写、摘要代替或重新解释已有各集，不得让人物失忆、瞬移、伤势复原，"
        "不得让旧道具和旧关系无因变化。第一集新稿必须直接处理旧稿最后的动作、决定或后果。"
    )


def scene_contract_violations(script: str, request_payload: dict) -> list[str]:
    policy = str(request_payload.get("scenes_per_episode") or "1").strip().lower()
    if policy not in SCENE_CONTRACTS:
        policy = "1"
    minimum, maximum, _description = SCENE_CONTRACTS[policy]
    matches = list(EPISODE_HEADER_RE.finditer(script))
    violations: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(script)
        episode = int(match.group("zh") or match.group("en"))
        scene_count = len(SCENE_HEADER_RE.findall(script[match.end() : end]))
        if scene_count < minimum or (maximum is not None and scene_count > maximum):
            expected = str(minimum) if minimum == maximum else (
                f"{minimum}至{maximum}" if maximum is not None else f"至少{minimum}"
            )
            violations.append(
                f"第{episode}集要求{expected}个场景，实际检测到{scene_count}个"
            )
    return violations


def prepare_final_editor_gate(request_payload: dict) -> None:
    draft_path = ROOT / ROLE_FILES["script_writer"]
    state_path = ROOT / ROLE_FILES["state_recorder"]
    if not draft_path.is_file() or not state_path.is_file():
        return
    try:
        from validate_script_team import validate

        state = json.loads(state_path.read_text(encoding="utf-8"))
        report = validate(
            draft_path.read_text(encoding="utf-8"),
            state,
            request_payload,
            mode="soft",
        )
        (ROOT / "gate_pre.json").write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (ImportError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"终审前连续性门禁生成失败：{exc}") from exc


def read_request() -> dict:
    raw = os.getenv("scriptRequest") or os.getenv("SCRIPT_REQUEST") or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"scriptRequest 不是有效 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("scriptRequest 必须是 JSON 对象")
    try:
        episodes = max(1, min(120, int(payload.get("episodes") or 1)))
    except (TypeError, ValueError) as exc:
        raise SystemExit("episodes 必须是整数") from exc
    payload["episodes"] = episodes
    episode_start = max(1, int(payload.get("episode_start") or 1))
    episode_end = episode_start + episodes - 1
    payload["episode_start"] = episode_start
    payload["episode_end"] = episode_end
    source_last = max(0, int(payload.get("source_last_episode") or 0))
    payload["source_last_episode"] = source_last
    payload["episode_contract"] = (
        (
            f"续写范围硬合同：已有剧本写至第{source_last}集；必须且只能交付"
            f"第{episode_start}集至第{episode_end}集，共{episodes}集；"
            f"不得重写第1集至第{source_last}集。"
        )
        if str(payload.get("mode") or "").strip() == "续写"
        else (
            "总集数硬合同：必须交付且只能交付第1集，共1集。"
            if episodes == 1
            else (
                f"总集数硬合同：必须完整交付第1集至第{episodes}集，共{episodes}集；"
                "任何单集试写或只交付某一集要求均不得覆盖该数值。"
            )
        )
    )
    return payload


def hydrate_remote_state() -> None:
    encoded = (os.getenv("scriptStateBundle") or os.getenv("SCRIPT_STATE_BUNDLE") or "").strip()
    if not encoded:
        return
    try:
        payload = json.loads(gzip.decompress(base64.b64decode(encoded)).decode("utf-8"))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"远程节点上下文包解析失败：{exc}") from exc
    recovered = payload.get("recovered_files") if isinstance(payload, dict) else {}
    if not isinstance(recovered, dict):
        recovered = {}
    final_script = str(payload.get("final_script") or "") if isinstance(payload, dict) else ""
    if final_script:
        recovered["final_script"] = final_script
    for artifact, content in recovered.items():
        role = ARTIFACT_ROLE_MAP.get(str(artifact))
        if role and str(content or "").strip():
            (ROOT / ROLE_FILES[role]).write_text(str(content), encoding="utf-8")


def previous_context(stage: str) -> str:
    chunks: list[str] = []
    for previous in CONTEXT_FILES.get(stage, ()):
        path = ROOT / ROLE_FILES[previous]
        if path.is_file():
            chunks.append(f"\n\n===== {previous} =====\n{path.read_text(encoding='utf-8')}")
    if stage == "final_editor":
        gate_path = ROOT / "gate_pre.json"
        if gate_path.is_file():
            chunks.append(f"\n\n===== deterministic_gate =====\n{gate_path.read_text(encoding='utf-8')}")
    return "".join(chunks)


def skill_modules(stage: str) -> str:
    chunks: list[str] = []
    modules = list(STAGE_MODULES.get(stage, ()))
    if stage in DYNAMIC_STAGE_MODULES:
        contract_path = ROOT / ROLE_FILES["showrunner"]
        contract = contract_path.read_text(encoding="utf-8") if contract_path.is_file() else ""
        match = ROUTING_RE.search(contract)
        routing: dict[str, str] = {}
        if match:
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict):
                    routing = {str(key): str(value) for key, value in parsed.items()}
            except json.JSONDecodeError:
                routing = {}
        for module in DYNAMIC_STAGE_MODULES[stage]:
            if routing.get(module, "").lower() in {"core", "support"}:
                modules.append(module)
    for module in modules:
        path = SKILL_ROOT / "references" / MODULE_FILES[module]
        if path.is_file():
            chunks.append(f"\n\n===== skill:{module} =====\n{path.read_text(encoding='utf-8')}")
    return "".join(chunks)


def parse_json_result(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, count=1)
        value = re.sub(r"\s*```$", "", value, count=1)
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise SystemExit("状态记录器未返回 JSON 对象")
        try:
            payload = json.loads(value[start : end + 1])
        except json.JSONDecodeError as exc:
            raise SystemExit(f"story_state.json 解析失败：{exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("story_state.json 顶层必须是对象")
    return payload


def _positive_env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _emit_heartbeats(
    stop_event: threading.Event,
    interval_seconds: int,
    label: str,
    *,
    started_at: float | None = None,
    clock=time.monotonic,
) -> None:
    started = clock() if started_at is None else started_at
    sequence = 0
    while not stop_event.wait(interval_seconds):
        sequence += 1
        elapsed = max(0, int(clock() - started))
        print(
            f"__SCRIPT_TEAM_HEARTBEAT__ stage={label} "
            f"sequence={sequence} elapsed_seconds={elapsed}",
            flush=True,
        )


def call_model(system_prompt: str, user_prompt: str, *, stage: str = "unknown") -> str:
    url = os.getenv("DEEPSEEK_BASE_URL", "").strip()
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro").strip()
    if not url or not api_key:
        raise SystemExit("缺少 DEEPSEEK_BASE_URL 或 DEEPSEEK_API_KEY")
    normalized_url = url.rstrip("/")
    if not normalized_url.endswith("/chat/completions"):
        normalized_url = f"{normalized_url}/chat/completions"
    timeout_seconds = _positive_env_int(
        "DEEPSEEK_TIMEOUT",
        1200,
        minimum=60,
        maximum=3600,
    )
    heartbeat_seconds = _positive_env_int(
        "SCRIPT_TEAM_HEARTBEAT_SECONDS",
        30,
        minimum=10,
        maximum=120,
    )
    stop_event = threading.Event()
    heartbeat = threading.Thread(
        target=_emit_heartbeats,
        args=(stop_event, heartbeat_seconds, stage),
        daemon=True,
        name=f"script-team-heartbeat-{stage}",
    )
    print(
        f"__SCRIPT_TEAM_MODEL_BEGIN__ stage={stage} "
        f"timeout_seconds={timeout_seconds} heartbeat_seconds={heartbeat_seconds}",
        flush=True,
    )
    heartbeat.start()
    started_at = time.monotonic()
    try:
        response = requests.post(
            normalized_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt.strip()},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.55,
                "stream": False,
            },
            timeout=timeout_seconds,
        )
    finally:
        stop_event.set()
        heartbeat.join(timeout=1)
        print(
            f"__SCRIPT_TEAM_MODEL_END__ stage={stage} "
            f"elapsed_seconds={max(0, int(time.monotonic() - started_at))}",
            flush=True,
        )
    if response.status_code >= 400:
        raise SystemExit(f"DeepSeek HTTP {response.status_code}: {response.text[:1000]}")
    payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        raise SystemExit("DeepSeek 未返回 choices")
    result = str(((choices[0] or {}).get("message") or {}).get("content") or "").strip()
    if not result:
        raise SystemExit("DeepSeek 返回空文本")
    return result


def run(stage: str) -> None:
    hydrate_remote_state()
    request_payload = read_request()
    if stage == "final_editor":
        prepare_final_editor_gate(request_payload)
    request_text = json.dumps(request_payload, ensure_ascii=False, indent=2)
    context = previous_context(stage)
    modules = skill_modules(stage)
    user_prompt = (
        "用户创作任务：\n"
        f"{request_text}"
        f"{context}\n\n"
        f"{modules}\n\n"
        "episode_start、episode_end 与 episodes 是本次交付范围硬合同；"
        "episode_word_count 是前端动态传入的每集"
        "最低字数，只能多不能少且不设上限；补充要求不得与这两项冲突。\n"
        f"{continuation_contract_instruction(request_payload)}\n"
        f"{scene_contract_instruction(request_payload)}\n"
        f"{duration_contract_instruction(request_payload)}"
    )
    result = call_model(PROMPTS[stage], user_prompt, stage=stage)
    if stage in {"script_writer", "final_editor"}:
        violations = scene_contract_violations(result, request_payload)
        if violations:
            raise SystemExit("逐集场景合同未满足：" + "；".join(violations[:20]))
    output_path = ROOT / ROLE_FILES[stage]
    if stage == "state_recorder":
        output_path.write_text(
            json.dumps(parse_json_result(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        output_path.write_text(result, encoding="utf-8")
    payload = f"{stage}\n{output_path.read_text(encoding='utf-8')}".encode("utf-8")
    encoded = base64.b64encode(gzip.compress(payload, compresslevel=9)).decode("ascii")
    print("__SCRIPT_TEAM_STAGE_GZIP_BEGIN__", flush=True)
    for index in range(0, len(encoded), 160):
        print(encoded[index : index + 160], flush=True)
    print("__SCRIPT_TEAM_STAGE_GZIP_END__", flush=True)
    print(f"{stage} completed: {output_path}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=ROLE_ORDER,
        default=os.getenv("scriptStage") or os.getenv("SCRIPT_STAGE"),
        required=not bool(os.getenv("scriptStage") or os.getenv("SCRIPT_STAGE")),
    )
    args = parser.parse_args()
    run(args.stage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
