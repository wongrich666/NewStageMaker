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
    "state_recorder": ("showrunner", "character_emotion", "episode_continuity", "script_writer"),
    "final_editor": (
        "showrunner",
        "character_emotion",
        "episode_continuity",
        "script_writer",
        "state_recorder",
    ),
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
MAINLINE_RE = re.compile(r"MAINLINE_LOCK_JSON\s*:\s*(\{[^\r\n]+\})")
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
BATCH_SIZE = 5
STATE_BATCH_SIZE = 5
STATE_AUDIT_BATCH_SIZE = 10
STAGE_BATCH_SIZES = {
    "episode_continuity": 5,
    "script_writer": 5,
    "final_editor": 5,
}
BATCHED_EPISODE_STAGES = {
    "episode_continuity",
    "script_writer",
    "state_recorder",
    "final_editor",
}
EPISODE_CARD_FIELDS = (
    "承接事实", "开场钩子", "最短因果锚", "主角目标", "主角主动动作",
    "阻力", "选择与代价", "本集主线推进", "结尾状态", "下一集第一有效动作",
)
EPISODE_CARD_JSON_FIELDS = {
    "carryover_fact": "承接事实",
    "opening_hook": "开场钩子",
    "causal_anchor": "最短因果锚",
    "protagonist_goal": "主角目标",
    "protagonist_action": "主角主动动作",
    "obstacle": "阻力",
    "choice_and_cost": "选择与代价",
    "mainline_advance": "本集主线推进",
    "ending_state": "结尾状态",
    "next_opening_action": "下一集第一有效动作",
}

PROMPTS = {
    "showrunner": """
你是专业剧集总编剧。根据用户任务输出精炼的《创作任务书》。
先锁定主角、核心目标、持续阻力、主角的核心行动方式、失败代价、追剧主问题和结局方向。
必须原样输出一行合法 JSON：
MAINLINE_LOCK_JSON: {"protagonist":"","goal":"","core_obstacle":"","protagonist_action":"","stakes":"","pursuit_question":"","ending_direction":""}
这行是全链路最高优先级主线合同，后续节点只能展开，不能替换。
再锁定题材与观众、情绪承诺、主题、不可篡改事实和真正需要规避的失效方式。
按照 skill-routing 模块判断增强能力，并原样输出一行合法的 SKILL_ROUTING_JSON。
题材不能直接决定套路；用户信息不足时由你作出专业判断，不把选择责任退还给用户。
为主角锁定“外在身份/处境+长期欲望或伤口+反差能力/秘密”的可执行标签，
并规定前五集必须立住主角标签、核心矛盾、主要阻力、情绪承诺和追剧主问题。
episode_start、episode_end 与 episodes 共同定义本次唯一交付范围，必须原样锁定，
忽略补充方向中与数值集数冲突的单集试写或只交付某一集要求。
不要写正文，不要罗列可有可无的事件。人物、道具、证据与技术按因果需要决定；
任何新增元素必须服务主线，不能成为无来源、无铺垫、无代价的万能解题工具。
""",
    "story_architect": """
你是故事架构师。读取创作任务书，建立可执行的故事圣经。
原样保留 MAINLINE_LOCK_JSON，并把主线写成可追踪的因果链：
触发事件→主角行动→阻力反应→主角选择→代价→局势变化→结局兑现。
建立“主线推进账本”，说明每个阶段推进了目标、阻力、信息、关系或代价中的哪一项。
支线预算按篇幅控制：1至10集最多1条，11至30集最多2条，31集以上最多3条；
支线必须由主线触发，并在两集内回撞主线，否则删除。不要用支线数量冒充丰富。
补充必要的人物关系债、前史未偿还冲突、秘密揭露顺序、升级机制和结局兑现。
每个解决必须产生代价，但不得添加与主线无关的身世、阴谋、证据或功能人物。
回忆若存在，必须拥有目标、阻力、转折、选择、代价，并留下影响现在的债务。
""",
    "character_emotion": """
你是人物与情感编剧。基于已锁定的故事，不改变主要事件，补足人物内在动力。
为主要人物写：外在目标、隐藏需求、恐惧、羞耻、自我谎言、关系债、压力行为、
声音配方和情感转折。再为每个主要人物建立可执行的“表演指纹”：平静时的身体基线、
受压时最先泄露情绪的眼神/眉眼/嘴角/手部或姿态微反应、撒谎与回避的破绽、
面对不同关系对象时的变化、失控前征兆和重新夺回控制的动作。表演指纹必须来自人物
身份、经历、关系和当下欲望，不得给所有人物套用同一组表情。
心理活动采用假设、验证、被推翻的动态过程。
每个主要人物必须有一句可被观众记住的标签及一组真正参与剧情的反差；
前五集内用行动落地标签、伤口、自我谎言和主要关系压力。
不得用抽象形容词代替具体反应，不得让人物为推动剧情突然降智。
本节点只深化既有角色为何这样行动，不新增主线、重大秘密、关键证据或解题道具。
""",
    "episode_continuity": """
你是分集与连续性编剧。严格按用户要求的集号范围、每集字数规模和画面时长设计逐集卡。
必须依次设计 episode_start 至 episode_end，不得缺集、越界或只设计试写集。
每集只围绕一条行动链设计：承接事实→开场钩子→最短因果锚→主角当集目标→
主角主动动作→阻力→选择与代价→本集主线推进→结尾状态→下一集第一有效动作。
“本集主线推进”必须明确改变目标进度、阻力、信息、关系或代价，不能只写气氛和遭遇。
主线不能只存在于后台摘要。每集必须设计一个“观众可见的主线载体”：通过主角的
明确决定、进度变化、关系站队、对手反制、可见结果或持续事物的状态变化，让观众
明白主角长期在做什么、现在到了哪一步、为什么还要继续。载体必须从本剧因果中生长，
不固定为证据、文档、道具或倒计时。前1至3集内用行动或自然对白立住长期目标与行动方法，
不用旁白概述主线。
不得只用“记录、发现、关系加深、积累证据”宣称主线已推进；必须同时写明谁因此
采取了新动作，局势或下一步方法如何改变。连续两集不得只积累而无处境变化；每3至5集
必须出现一次阶段性兑现、失败、暴露、对手反制或主角策略改变，不得把所有兑现拖到结局。
第N集“结尾状态”与第N+1集“承接事实”必须是同一事实；换地点时，上集先给出
决定、去向或行动目的，下集从准备执行、正在执行或承受结果开始。禁止用时间字幕掩盖断层。
第一集及新冲突首次出现时规划开场因果锚：强钩子先发生，随后1至3拍只交代观众
理解眼前处境所需的最小原因，不泄露完整前史。
scenes_per_episode 是逐集场景数量硬合同。1表示每一大集只能有一个场景，
1-2表示每集一至两个，2表示每集必须两个，2-3表示每集两至三个，
只有 flexible 才允许按剧情灵活安排。不得把一个场景内的小节拍拆成新场景。
第一集第一有效拍必须让主角立刻面对不可回避的问题，并产生具体追问；优先使用
高压命令、异常事实、关系破位或不可逆选择，随后立即出现后果、私人代价或主角选择。
每集至少一个真正改变局势的情绪高点，每30至60秒出现一次局势变化或情绪释放。
前五集必须完成基础立剧，后续只升级、变奏和兑现，不得再补基础人设。
以创作合同确定的主角为行动锚，不按男女频机械判断；配角不能替主角完成关键选择。
每个字段只写1至3句可执行内容，单集卡控制在350至700字；禁止复述人物小传、世界观和前集全文。
""",
    "script_writer": """
你是唯一的正文与对白编剧。只把锁定材料转化为完整可拍剧本，不重新策划故事。
执行优先级固定为：MAINLINE_LOCK_JSON→逐集卡→人物声音→通用与蒸馏Skill。
Skill只能影响题材表达、情绪和语言，不能覆盖主线、分集结果或新增重大设定。
必须完整写出 episode_start 至 episode_end 且不多不少，每集标题统一使用
“第N集：《本集独有标题》”；标题必须简短、具体并能区分本集剧情。
数值集数优先于补充方向中的单集试写文字。
episode_word_count 是前端动态传入的每集目标下限，episode_word_count_max 是硬上限。
每集必须落在该闭区间内；默认最多上浮10%。超上限时只压缩重复解释、冗余动作、
同义对白和无效铺垫，不得删除钩子、关键转折、人物选择、情绪爆点或结尾承接。
episode_duration_seconds 是每集目标画面时长。按对白实际说完、自然停顿、人物反应、
动作完成、信息揭示和必要转场所占时间组织内容，不得把字数机械换算成秒数。
第一集场景头后的第一有效拍必须让主角立刻面对不可回避的问题。一句命令、异常事实、
关系破位或不可逆动作足够时立即收住；下一拍必须产生后果或迫使主角反应。
禁止先铺陈环境、解释背景、逐个介绍人物或罗列道具，再让核心事件迟到。
强钩子后的1至3个有效拍内补足“开场因果锚”，只让观众理解眼前处境为何发生：
优先使用本来就在场且有信息来源的人物反应、对手指控、主角反问、公开通知、可见痕迹
或规则反馈。不得固定使用路人解释；第三方开口必须同时在劝阻、站队、起哄、施压、
自保或受到波及，不能像作者一样概述背景。钩子本身已经包含清楚原因时不得重复解释。
逐字落实逐集卡的“结尾状态→下一集第一有效动作”。允许省略无戏剧价值的赶路，
但不能省略决定、去向、行动目的和关键结果。每集由主角行动推动，不得瞬移。
严格执行 scenes_per_episode。场景数按每一大集内出现的“场景N”标题计数；
一个动作段、冲突阶段或人物进入不能自行升级为新场景。
每集至少出现一次改变资源、关系、认知、身份、行动条件或风险等级的情绪高点，
并用尾钩直接改变下一集开场行动，禁止集间冷却或另起无关事件。
每集只写紧凑场景头“场景N：地点｜日/夜｜内/外”和“人物”，然后立刻进入戏。
场景头和人物行使用纯文本，不添加 Markdown 加粗符号或标题符号。
禁止输出“场景任务”和独立“道具”清单；道具只在人物真正使用时自然写入动作。
每次换场重新写场景头和人物即可。
不得改变主角当集目标、本集主线推进、结尾状态和下一集承接；不得新增重大人物、
秘密、能力、支线、证据或万能道具。需要补细节时只能从既有关系、规则和行动中生长。
所有对白必须独立成行，采用“人物名：台词”；所有心理活动必须采用
“人物名OS：心理活动”。不得输出无人物名前缀的对白或单独的“OS：”。
对白表演按戏剧需要选择：普通台词直接写；只有去掉提示会读错潜台词、真实意图或关系态度时，才采用
“人物名：（发声方式＋当下可见的眉眼、视线或嘴角反应）台词”。例如
“人物名：（压低声音，视线越过对方肩头）台词。”示例只说明组合格式，不得照抄具体反应。
括号必须紧跟冒号并使用中文全角括号。
括号内不写“生气、严肃、无奈”等抽象结论，不写心理解释或长动作；语气、视线和表情必须来自人物表演指纹、说话目的和当下关系压力。
同一场内同一人物不得连续复制同一表情；不得批量使用“指节发白、瞳孔骤缩、呼吸一滞、攥紧拳头、嘴角勾起、眼底闪过”等人人通用的套式反应。
较完整动作写在台词前后，听者反应也可承担表演，不得每句加括号。动作短、具体、可视、可由AI生成；对白口语化、有潜台词，人物声音和表演反应均可区分。
删除多余形容词、气氛铺垫、剧情复述和解释性对白。
标点服从真实口语与动作节奏，禁止把破折号“——”当成默认停顿符。
完整陈述和普通转折使用逗号、句号、问号或感叹号；迟疑、吞回半句话或声音渐弱使用省略号；
只有台词被突然打断、人物猛然改口或语义发生强制跳转时才使用破折号。
同一段或同一句不得连续堆叠破折号，普通动作衔接不得写成“动作——结果”。
例如“实习生是吧——这个月工资扣一半！”应写成“实习生是吧？这个月工资扣一半！”；
“说啊。说啊。你倒是说啊——”应按情绪写成“说啊。你倒是说啊！”。
""",
    "state_recorder": """
你是状态与偏差记录器，不是编剧。对照分集卡和初稿，只提取本批事实，不改写正文。
只输出 episodes、plan_alignment，以及本批确实发生变化的 open_threads、narrative_pressure。
project、mainline_lock、characters、props 等全局字段由代码从上游合同和人物圣经补齐，
不要重复生成。除人物位置、知情范围、伤势、服装、道具、关系、伏笔和未完成动作外，
还要填写 plan_alignment：记录计划主线推进、正文实际推进以及 aligned/deviated。
continuity_bridge 的 from_action 和 to_action 必须摘录相邻正文中真实存在的简短动作，
不得用概括句伪造承接。未知事实写“未明确”，不得猜测或替正文掩盖偏差。
""",
    "final_editor": """
你是唯一终审编辑，合并钩子编辑和终审导演职责。必须直接修稿，不只审查和打分。
最终稿必须完整包含 episode_start 至 episode_end 且不多不少。执行优先级固定为：
MAINLINE_LOCK_JSON→逐集卡→正文既有事实→人物声音→Skill。先依据 plan_alignment
修复正文偏离，再处理表达；不得把初稿偏差当成新的正典。
1. 第一集第一有效拍必须让主角面对不可回避的问题。优先用最短的高压命令、异常事实、
   关系破位或不可逆选择，并让下一拍立刻产生后果或主角反应；
1.1 若缺少开场因果锚、观众仍不明白眼前处境为何发生，在强钩子后1至3个有效拍内补足：
    使用有来源的人物反应、指控、可见结果或规则反馈交代最小原因；不得在钩子前铺垫，
    不得新增只负责讲解的路人，也不得把完整前史一次说完；
2. 其他集开头必须处理上集结尾状态；换场时保留决定、去向、目的或结果；
3. 增强同场多线压力、人物选择代价和每集至少一个真正改变局势的情绪高点；
4. 改写泄气、解释性、AI味对白；
5. 删掉不影响动作、信息和情绪的形容词。
episode_word_count 是每集目标下限，episode_word_count_max 是最多上浮10%的硬上限。
低于下限必须补足，超过上限必须精简重复说明、冗余动作、同义对白和无效铺垫；
不得删除钩子、关键转折、人物选择、情绪爆点、结尾钩子与集间承接。
逐集修正 deterministic_gate 中的时长偏差，使对白、停顿、动作与镜头节拍合计
接近 episode_duration_seconds；优先删重复解释或补有效反应与因果动作，不得注水。
钩子不足时只允许重写开头1至3个有效拍，并同步删除重复铺垫。不得新增重大事实、
人物、能力、秘密或世界规则，不得改变主角当集目标、本集结果和下一集承接。
最终每集必须保留“第N集：《本集独有标题》”，不得在终审时删掉集名。
每集只保留“场景N：地点｜日/夜｜内/外”和“人物”两项紧凑场景信息；
删除“场景任务”和独立“道具”清单，道具只在真正使用时进入动作。
所有对白保持“人物名：台词”；所有心理活动保持“人物名OS：心理活动”。
发现无人物归属的对白或心理活动时补齐人物名。
逐场修复人物表演拍。普通对白不强加括号；只有提示会改变台词读法时才使用
“人物名：（简短语气或可见微反应）台词”。较完整动作放在台词前后，也允许由听者反应
完成情绪回声。所有表演必须来自人物表演指纹与当下关系压力，删除机械重复、形容词堆叠
和人人通用的套式神情，不得为了满足数量给每句加括号。
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
    bible = str(request_payload.get("continuation_bible") or "").strip()
    policy_text = (
        "允许修复不改变既有事件结果的轻微连续性问题"
        if policy == "light"
        else "严格保留既有事实、人物声音、关系温度、伤势、位置、道具与未完成动作"
    )
    bible_contract = ""
    if bible:
        bible_contract = (
            "\n《续写创作圣经》是所有后续节点共同遵守的长期正典：\n"
            f"{bible}\n"
            "执行优先级固定为：已有正文明确事实 > 续写创作圣经 > 本次临时续写方向 > "
            "模型自由发挥。圣经不得反向改写已发生事件；其人物设定、关系、世界规则、"
            "主支线走向、未来节点与风格偏好必须落实到新集，不得无故遗忘、替换或弱化。"
        )
    return (
        f"续写硬合同：已有剧本写至第{source_last}集，已有第{source_last}集结尾是"
        f"第{episode_start}集唯一开场起点；本次只输出第{episode_start}集至第{episode_end}集。"
        f"{policy_text}。先从已有全文提取续写基线，再规划新剧情；"
        "不得重写、摘要代替或重新解释已有各集，不得让人物失忆、瞬移、伤势复原，"
        "不得让旧道具和旧关系无因变化。第一集新稿必须直接处理旧稿最后的动作、决定或后果。"
        + bible_contract
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


def blocking_scene_contract_message(
    stage: str,
    script: str,
    request_payload: dict,
) -> str:
    """Keep draft scene drift recoverable; enforce the contract on final delivery."""
    violations = scene_contract_violations(script, request_payload)
    if not violations or stage == "script_writer":
        return ""
    return "逐集场景合同未满足：" + "；".join(violations[:20])


def episode_numbers(text: str) -> list[int]:
    return [
        int(match.group("zh") or match.group("en"))
        for match in EPISODE_HEADER_RE.finditer(str(text or ""))
    ]


def episode_range_violations(text: str, request_payload: dict) -> list[str]:
    episode_start = max(1, int(request_payload.get("episode_start") or 1))
    total = max(1, int(request_payload.get("episodes") or 1))
    episode_end = max(
        episode_start,
        int(request_payload.get("episode_end") or (episode_start + total - 1)),
    )
    expected = list(range(episode_start, episode_end + 1))
    actual = episode_numbers(text)
    if actual == expected:
        return []
    return [
        f"要求完整交付第{episode_start}-{episode_end}集，实际集号为{actual}"
    ]


def _episode_slice(text: str, episode_start: int, episode_end: int) -> str:
    value = str(text or "")
    matches = list(EPISODE_HEADER_RE.finditer(value))
    selected: list[str] = []
    for index, match in enumerate(matches):
        episode = int(match.group("zh") or match.group("en"))
        if episode_start <= episode <= episode_end:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
            selected.append(value[match.start() : end].strip())
    return "\n\n".join(selected)


def _state_episode_numbers(text: str) -> list[int]:
    try:
        payload = json.loads(str(text or ""))
    except (TypeError, json.JSONDecodeError):
        return []
    items = payload.get("episodes") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    numbers: list[int] = []
    for item in items:
        if isinstance(item, dict):
            try:
                numbers.append(int(item.get("episode")))
            except (TypeError, ValueError):
                continue
    return numbers


def _state_slice(text: str, episode_start: int, episode_end: int) -> str:
    try:
        payload = json.loads(str(text or ""))
    except (TypeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    sliced = dict(payload)
    sliced["episodes"] = [
        item
        for item in payload.get("episodes") or []
        if isinstance(item, dict)
        and episode_start <= int(item.get("episode") or 0) <= episode_end
    ]
    sliced["plan_alignment"] = [
        item
        for item in payload.get("plan_alignment") or []
        if isinstance(item, dict)
        and episode_start <= int(item.get("episode") or 0) <= episode_end
    ]
    return json.dumps(sliced, ensure_ascii=False, indent=2)


def _missing_state_ranges(
    text: str,
    *,
    episode_start: int,
    episode_end: int,
    batch_size: int = STATE_BATCH_SIZE,
) -> list[tuple[int, int]]:
    present = set(_state_episode_numbers(text))
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


def _merge_state_outputs(current: str, incoming: str, *, episode_start: int, episode_end: int) -> str:
    base = parse_json_result(current) if str(current or "").strip() else {}
    batch = parse_json_result(incoming)
    items = batch.get("episodes")
    if not isinstance(items, list):
        raise ValueError("状态批次 episodes 必须是数组")
    expected = list(range(episode_start, episode_end + 1))
    actual = [int(item.get("episode")) for item in items if isinstance(item, dict)]
    if actual != expected:
        raise ValueError(f"状态批次要求集号{expected}，实际集号{actual}")

    merged = dict(base)
    for key, value in batch.items():
        if key in {"episodes", "plan_alignment"}:
            continue
        if key == "narrative_pressure" and isinstance(value, dict):
            target = merged.setdefault("narrative_pressure", {})
            if not isinstance(target, dict):
                target = {}
                merged["narrative_pressure"] = target
            for nested_key, nested_value in value.items():
                if isinstance(nested_value, list):
                    existing = target.setdefault(nested_key, [])
                    if not isinstance(existing, list):
                        existing = []
                        target[nested_key] = existing
                    for item in nested_value:
                        if item not in existing:
                            existing.append(item)
                elif not target.get(nested_key):
                    target[nested_key] = nested_value
        elif isinstance(value, list):
            existing = merged.setdefault(key, [])
            if not isinstance(existing, list):
                existing = []
                merged[key] = existing
            for item in value:
                if item not in existing:
                    existing.append(item)
        elif not merged.get(key):
            merged[key] = value
    episode_map = {
        int(item.get("episode")): item
        for item in (merged.get("episodes") or [])
        if isinstance(item, dict) and str(item.get("episode") or "").isdigit()
    }
    episode_map.update({int(item["episode"]): item for item in items})
    merged["episodes"] = [episode_map[number] for number in sorted(episode_map)]
    alignment_map = {
        int(item.get("episode")): item
        for item in (merged.get("plan_alignment") or [])
        if isinstance(item, dict) and str(item.get("episode") or "").isdigit()
    }
    for item in batch.get("plan_alignment") or []:
        if isinstance(item, dict) and str(item.get("episode") or "").isdigit():
            alignment_map[int(item["episode"])] = item
    merged["plan_alignment"] = [alignment_map[number] for number in sorted(alignment_map)]
    return json.dumps(merged, ensure_ascii=False, indent=2)


def _append_episode_batch(prefix: str, batch: str) -> str:
    value = str(batch or "").strip()
    if str(prefix or "").strip():
        match = EPISODE_HEADER_RE.search(value)
        if match:
            value = value[match.start() :].strip()
    return "\n\n".join(
        item for item in (str(prefix or "").strip(), value) if item
    )


def _episode_parts(text: str) -> tuple[str, dict[int, str]]:
    value = str(text or "").strip()
    matches = list(EPISODE_HEADER_RE.finditer(value))
    if not matches:
        return value, {}
    prefix = value[: matches[0].start()].strip()
    parts: dict[int, str] = {}
    for index, match in enumerate(matches):
        episode = int(match.group("zh") or match.group("en"))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        parts.setdefault(episode, value[match.start() : end].strip())
    return prefix, parts


def _valid_episode_parts(stage: str, text: str) -> dict[int, str]:
    _prefix, parts = _episode_parts(text)
    if stage != "episode_continuity":
        return {
            episode: content
            for episode, content in parts.items()
            if len(content) >= 120 and SCENE_HEADER_RE.search(content)
        }
    return {
        episode: content
        for episode, content in parts.items()
        if all(
            re.search(rf"(?:\*\*)?{re.escape(field)}(?:\*\*)?\s*[:：]\s*\S", content)
            for field in EPISODE_CARD_FIELDS
        )
    }


def _episode_card_json_contract(start: int, end: int) -> str:
    return f"""
本节点禁止输出 Markdown。只输出一个合法 JSON 对象，不得使用代码围栏或附加解释：
{{"episodes":[{{
  "episode": {start},
  "title": "本集独有短标题",
  "carryover_fact": "与上一集结尾完全一致的事实",
  "opening_hook": "本集第一有效拍",
  "causal_anchor": "观众理解钩子所需的最短原因",
  "protagonist_goal": "主角本集可执行目标",
  "protagonist_action": "主角主动采取的动作",
  "obstacle": "直接阻碍动作的人或局势",
  "choice_and_cost": "主角选择及立刻付出的代价",
  "mainline_advance": "本集对主线造成的不可撤销变化",
  "ending_state": "本集最后一个已发生状态",
  "next_opening_action": "下一集承接该状态的第一动作",
  "scenes": [{{
    "location": "地点",
    "time": "日或夜",
    "interior_exterior": "内或外",
    "characters": ["在场人物"],
    "props": ["实际使用的关键道具"],
    "dramatic_task": "本场必须完成的戏剧任务"
  }}]
}}]}}
episodes 数组必须按顺序且只能包含第{start}集至第{end}集。所有字符串字段必须有具体内容；
不得用“待定”“同上”“承接前文”或空字符串占位。
""".strip()


def _json_object_from_text(text: str) -> dict:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, count=1, flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value, count=1)
    candidates = [value]
    if "{" in value and "}" in value:
        candidates.append(value[value.find("{") : value.rfind("}") + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                start = candidate.find("{")
                if start < 0:
                    continue
                payload, _end = json.JSONDecoder().raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("没有返回合法 JSON 对象")


def render_episode_card_json(
    text: str,
    *,
    episode_start: int,
    episode_end: int,
    allow_partial: bool = False,
) -> str:
    payload = _json_object_from_text(text)
    items = payload.get("episodes")
    if not isinstance(items, list):
        raise ValueError("episodes 必须是数组")
    expected = list(range(episode_start, episode_end + 1))
    actual: list[int] = []
    rendered: dict[int, str] = {}
    errors: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            if allow_partial:
                errors.append("episodes 中存在非对象内容")
                continue
            raise ValueError("episodes 中存在非对象内容")
        try:
            episode = int(item.get("episode"))
        except (TypeError, ValueError) as exc:
            if allow_partial:
                errors.append("episode 必须是数字")
                continue
            raise ValueError("episode 必须是数字") from exc
        title = str(item.get("title") or "").strip()
        missing = [key for key in EPISODE_CARD_JSON_FIELDS if not str(item.get(key) or "").strip()]
        scenes = item.get("scenes")
        if not title:
            missing.append("title")
        if not isinstance(scenes, list) or not scenes:
            missing.append("scenes")
        if missing:
            if allow_partial:
                errors.append(f"第{episode}集缺少字段：{','.join(missing)}")
                continue
            raise ValueError(f"第{episode}集缺少字段：{','.join(missing)}")
        lines = [f"第{episode}集：《{title}》"]
        lines.extend(
            f"{label}：{str(item[key]).strip()}"
            for key, label in EPISODE_CARD_JSON_FIELDS.items()
        )
        scene_error = ""
        for scene_index, scene in enumerate(scenes, start=1):
            if not isinstance(scene, dict):
                scene_error = f"第{episode}集场景{scene_index}不是对象"
                break
            location = str(scene.get("location") or "").strip()
            time_value = str(scene.get("time") or "").strip()
            interior = str(scene.get("interior_exterior") or "").strip()
            task = str(scene.get("dramatic_task") or "").strip()
            if not all((location, time_value, interior, task)):
                scene_error = f"第{episode}集场景{scene_index}信息不完整"
                break
            characters = "、".join(str(value).strip() for value in scene.get("characters") or [] if str(value).strip())
            props = "、".join(str(value).strip() for value in scene.get("props") or [] if str(value).strip()) or "无"
            lines.append(
                f"场景{scene_index}：{location}｜{time_value}｜{interior}；"
                f"人物：{characters or '未明确'}；关键道具：{props}；戏剧任务：{task}"
            )
        if scene_error:
            if allow_partial:
                errors.append(scene_error)
                continue
            raise ValueError(scene_error)
        actual.append(episode)
        rendered.setdefault(episode, "\n".join(lines))
    if allow_partial:
        if not rendered:
            raise ValueError(errors[0] if errors else "没有可保留的合法分集卡")
        return "\n\n".join(rendered[number] for number in sorted(rendered))
    if actual != expected:
        raise ValueError(f"要求集号{expected}，实际集号{actual}")
    return "\n\n".join(rendered[number] for number in expected)


def generate_episode_card_batch(
    request_payload: dict,
    user_prompt: str,
    *,
    stage_label: str,
) -> str:
    start = max(1, int(request_payload.get("episode_start") or 1))
    end = max(start, int(request_payload.get("episode_end") or start))
    raw = call_model(
        PROMPTS["episode_continuity"] + "\n\n" + _episode_card_json_contract(start, end),
        user_prompt,
        stage=stage_label,
    )
    try:
        return render_episode_card_json(
            raw,
            episode_start=start,
            episode_end=end,
            allow_partial=True,
        )
    except ValueError as exc:
        print(
            f"__SCRIPT_TEAM_CARD_REPAIR__ stage={stage_label} error={exc}",
            flush=True,
        )
        # A model may return the requested card labels as Markdown instead of JSON.
        # The outer batch loop validates and preserves any usable episode sections.
        return raw


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
    present = set(episode_numbers(text))
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


def read_bundle_text(direct_names: tuple[str, ...], file_names: tuple[str, ...]) -> str:
    for name in direct_names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    for name in file_names:
        path_text = (os.getenv(name) or "").strip()
        if not path_text:
            continue
        try:
            return Path(path_text).read_text(encoding="ascii").strip()
        except OSError as exc:
            raise SystemExit(f"无法读取远程上下文文件 {path_text}：{exc}") from exc
    return ""


def read_request() -> dict:
    encoded = read_bundle_text(
        ("scriptRequestBundle", "SCRIPT_REQUEST_BUNDLE"),
        ("scriptRequestBundleFile", "SCRIPT_REQUEST_BUNDLE_FILE"),
    )
    if encoded:
        try:
            raw = gzip.decompress(base64.b64decode(encoded)).decode("utf-8")
        except (ValueError, OSError) as exc:
            raise SystemExit(f"scriptRequest 压缩包解析失败：{exc}") from exc
    else:
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
    encoded = read_bundle_text(
        ("scriptStateBundle", "SCRIPT_STATE_BUNDLE"),
        ("scriptStateBundleFile", "SCRIPT_STATE_BUNDLE_FILE"),
    )
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
    resume_stage = str(payload.get("resume_stage") or "") if isinstance(payload, dict) else ""
    resume_text = str(payload.get("stage_resume_text") or "") if isinstance(payload, dict) else ""
    if resume_stage in BATCHED_EPISODE_STAGES and resume_text.strip():
        (ROOT / "stage_resume.json").write_text(
            json.dumps({"stage": resume_stage, "content": resume_text}, ensure_ascii=False),
            encoding="utf-8",
        )


def emit_stage_checkpoint(stage: str, result: str) -> None:
    payload = f"{stage}\n{result}".encode("utf-8")
    encoded = base64.b64encode(gzip.compress(payload, compresslevel=6)).decode("ascii")
    print("__SCRIPT_TEAM_STAGE_GZIP_BEGIN__", flush=True)
    for index in range(0, len(encoded), 160):
        print(encoded[index : index + 160], flush=True)
    print("__SCRIPT_TEAM_STAGE_GZIP_END__", flush=True)


def previous_context(
    stage: str,
    episode_start: int | None = None,
    episode_end: int | None = None,
) -> str:
    chunks: list[str] = []
    for previous in CONTEXT_FILES.get(stage, ()):
        path = ROOT / ROLE_FILES[previous]
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            if (
                episode_start is not None
                and episode_end is not None
                and previous in {"episode_continuity", "script_writer", "state_recorder"}
            ):
                content = (
                    _state_slice(content, episode_start, episode_end)
                    if previous == "state_recorder"
                    else _episode_slice(content, episode_start, episode_end)
                )
            chunks.append(f"\n\n===== {previous} =====\n{content}")
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


def _stage_user_prompt(
    stage: str,
    request_payload: dict,
    modules: str,
    *,
    episode_start: int | None = None,
    episode_end: int | None = None,
    previous_tail: str = "",
) -> str:
    context = previous_context(stage, episode_start, episode_end)
    tail = (
        "\n\n===== 上一批结尾，仅用于连续承接 =====\n" + previous_tail
        if previous_tail
        else ""
    )
    return (
        "用户创作任务：\n"
        f"{json.dumps(request_payload, ensure_ascii=False, indent=2)}"
        f"{context}\n\n"
        f"{modules}"
        f"{tail}\n\n"
        "episode_start、episode_end 与 episodes 是本次交付范围硬合同；"
        "episode_word_count 是每集目标下限，episode_word_count_max 是最多上浮10%的"
        "硬上限；每集必须处于闭区间内，补充要求不得与该字数合同冲突。\n"
        f"{continuation_contract_instruction(request_payload)}\n"
        f"{scene_contract_instruction(request_payload)}\n"
        f"{duration_contract_instruction(request_payload)}"
    )


def _state_batch_contract(start: int, end: int) -> str:
    return f"""
状态记录器采用分批协议。本次只处理第{start}集至第{end}集，不能输出其他集。
只输出一个合法 JSON 对象，不要 Markdown 围栏、解释或校验报告。顶层至少包含 episodes
和 plan_alignment，可选填写本批确实变化的 open_threads、narrative_pressure。
episodes 和 plan_alignment 只填写本批集数；每个 episode 必须有完整 schema 字段。
project、mainline_lock、characters、props 等全局字段不要重复生成，由代码补齐。
JSON 必须在写入前自行保证可解析，字符串中的 ASCII 双引号必须转义。
""".strip()


def _ensure_state_globals(text: str, request_payload: dict) -> str:
    payload = parse_json_result(text)
    contract_path = ROOT / ROLE_FILES["showrunner"]
    contract = contract_path.read_text(encoding="utf-8") if contract_path.is_file() else ""
    lock = _mainline_lock_from_text(contract)
    if not lock:
        lock = {
            "protagonist": str(request_payload.get("protagonist") or "未明确"),
            "goal": "未明确",
            "core_obstacle": "未明确",
            "protagonist_action": "未明确",
            "stakes": "未明确",
            "pursuit_question": "未明确",
            "ending_direction": "未明确",
        }
    payload.setdefault("schema_version", "1.0")
    payload.setdefault("project", {
        "title": str(request_payload.get("title") or request_payload.get("project_name") or "未命名项目"),
        "protagonist": str(lock.get("protagonist") or "未明确"),
        "episode_count": int(request_payload.get("series_episode_count") or request_payload.get("episodes") or 1),
        "target_words_per_episode": int(request_payload.get("episode_word_count") or 0),
        "immutable_facts": [],
    })
    payload["project"]["episode_count"] = int(
        request_payload.get("series_episode_count") or request_payload.get("episodes") or 1
    )
    payload["mainline_lock"] = lock
    payload.setdefault("characters", [])
    payload.setdefault("props", [])
    payload.setdefault("open_threads", [])
    payload.setdefault("narrative_pressure", {
        "adversity_payoff_level": "off",
        "pressure_lines": [],
        "emotional_debts": [],
        "reversal_assets": [],
    })
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _state_text_action(text: str, *, first: bool) -> str:
    lines = []
    for line in str(text or "").splitlines():
        value = line.strip()
        if not value or EPISODE_HEADER_RE.match(value) or SCENE_HEADER_RE.match(value):
            continue
        if value.startswith(("人物", "场景", "承接事实", "开场钩子", "最短因果锚")):
            continue
        lines.append(value)
    if not lines:
        return "未明确"
    return lines[0] if first else lines[-1]


def _fallback_state_batch(
    request_payload: dict,
    *,
    episode_start: int,
    episode_end: int,
    reason: str,
) -> str:
    """Build a publishable minimum state without another model request."""
    contract_path = ROOT / ROLE_FILES["showrunner"]
    contract = contract_path.read_text(encoding="utf-8") if contract_path.is_file() else ""
    mainline_lock = _mainline_lock_from_text(contract)
    if not mainline_lock:
        mainline_lock = {
            "protagonist": str(request_payload.get("protagonist") or "未明确"),
            "goal": "未明确",
            "core_obstacle": "未明确",
            "protagonist_action": "未明确",
            "stakes": "未明确",
            "pursuit_question": "未明确",
            "ending_direction": "未明确",
        }
    episode_file = ROOT / ROLE_FILES["episode_continuity"]
    draft_file = ROOT / ROLE_FILES["script_writer"]
    episode_text = episode_file.read_text(encoding="utf-8") if episode_file.is_file() else ""
    draft_text = draft_file.read_text(encoding="utf-8") if draft_file.is_file() else ""
    episodes = []
    alignment = []
    for number in range(episode_start, episode_end + 1):
        card = _episode_slice(episode_text, number, number)
        draft = _episode_slice(draft_text, number, number)
        opening = _state_text_action(draft or card, first=True)
        closing = _state_text_action(draft or card, first=False)
        previous = episodes[-1]["closing_action"] if episodes else "未明确"
        episodes.append(
            {
                "episode": number,
                "opening_action": opening,
                "closing_action": closing,
                "core_scenes": [
                    match.group(0).strip()
                    for match in SCENE_HEADER_RE.finditer(draft)
                ][:3] or ["未明确"],
                "scene_exception_reason": "",
                "continuity_bridge": (
                    None
                    if number == episode_start and episode_start == 1
                    else {
                        "previous_episode": number - 1,
                        "from_action": previous,
                        "to_action": opening,
                        "reason": "代码兜底提取，待补充核验",
                    }
                ),
                "character_states": [],
                "introduced_characters": [],
                "introduced_props": [],
                "information_changes": [],
                "open_loops": [],
                "resolved_loops": [],
            }
        )
        alignment.append(
            {
                "episode": number,
                "planned_mainline_advance": "未由模型核验",
                "actual_mainline_advance": closing,
                "status": "unverified",
                "issue": reason[:500],
            }
        )
    payload = {
        "schema_version": "1.0",
        "state_status": "degraded",
        "state_warnings": [reason[:500]],
        "project": {
            "title": str(request_payload.get("title") or request_payload.get("project_name") or "未命名项目"),
            "protagonist": str(mainline_lock.get("protagonist") or "未明确"),
            "episode_count": int(request_payload.get("series_episode_count") or request_payload.get("episodes") or 1),
            "target_words_per_episode": int(request_payload.get("episode_word_count") or 0),
            "immutable_facts": [],
        },
        "mainline_lock": mainline_lock,
        "characters": [],
        "props": [],
        "episodes": episodes,
        "open_threads": [],
        "plan_alignment": alignment,
        "narrative_pressure": {
            "adversity_payoff_level": "off",
            "pressure_lines": [],
            "emotional_debts": [],
            "reversal_assets": [],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _state_audit_reasons(request_payload: dict) -> list[str]:
    policy = str(request_payload.get("state_audit_policy") or "auto").strip().lower()
    if policy == "never":
        return []
    if policy == "always":
        return ["用户或平台要求连续性模型抽查"]
    reasons: list[str] = []
    total = max(1, int(request_payload.get("episodes") or 1))
    if total >= 40:
        reasons.append("长篇任务达到40集")
    return reasons


def _state_audit_ranges(episode_start: int, episode_end: int) -> list[tuple[int, int]]:
    return [
        (start, min(episode_end, start + STATE_AUDIT_BATCH_SIZE - 1))
        for start in range(episode_start, episode_end + 1, STATE_AUDIT_BATCH_SIZE)
    ]


def _audit_deterministic_state(
    deterministic: str,
    request_payload: dict,
    *,
    modules: str,
    reasons: list[str],
) -> str:
    result = deterministic
    episode_start = max(1, int(request_payload.get("episode_start") or 1))
    episode_end = max(
        episode_start,
        int(request_payload.get("episode_end") or episode_start),
    )
    warnings: list[str] = []
    successful = 0
    for batch_start, batch_end in _state_audit_ranges(episode_start, episode_end):
        batch_request = dict(request_payload)
        batch_request.update(
            {
                "episodes": batch_end - batch_start + 1,
                "episode_start": batch_start,
                "episode_end": batch_end,
                "series_episode_start": episode_start,
                "series_episode_end": episode_end,
                "series_episode_count": int(request_payload.get("episodes") or 1),
            }
        )
        prompt = _stage_user_prompt(
            "state_recorder",
            batch_request,
            modules,
            episode_start=batch_start,
            episode_end=batch_end,
        )
        try:
            raw = call_model(
                PROMPTS["state_recorder"] + "\n\n" + _state_batch_contract(batch_start, batch_end),
                prompt,
                stage=f"state_audit:{batch_start}-{batch_end}",
            )
            audited = _merge_state_outputs(
                "",
                raw,
                episode_start=batch_start,
                episode_end=batch_end,
            )
            result = _merge_state_outputs(
                result,
                audited,
                episode_start=batch_start,
                episode_end=batch_end,
            )
            successful += 1
        except (SystemExit, OSError, TypeError, ValueError) as exc:
            warnings.append(f"第{batch_start}-{batch_end}集模型抽查失败：{exc}")
            print(
                f"__SCRIPT_TEAM_STATE_AUDIT_WARNING__ range={batch_start}-{batch_end}",
                flush=True,
            )
        result = _ensure_state_globals(result, request_payload)
        emit_stage_checkpoint("state_recorder", result)
    payload = parse_json_result(_ensure_state_globals(result, request_payload))
    payload["state_status"] = "audited" if not warnings else "audit_partial"
    payload["state_audit"] = {
        "reasons": reasons,
        "batch_count": len(_state_audit_ranges(episode_start, episode_end)),
        "successful_batches": successful,
        "warnings": warnings,
    }
    payload["state_warnings"] = list(payload.get("state_warnings") or []) + warnings
    return json.dumps(payload, ensure_ascii=False, indent=2)


def generate_state_result(
    request_payload: dict,
    *,
    modules: str,
) -> str:
    episode_start = max(1, int(request_payload.get("episode_start") or 1))
    total = max(1, int(request_payload.get("episodes") or 1))
    episode_end = max(
        episode_start,
        int(request_payload.get("episode_end") or (episode_start + total - 1)),
    )
    state_model_forced = os.getenv("SCRIPT_TEAM_STATE_MODEL", "").strip().lower()
    if state_model_forced in {"0", "false", "no"}:
        audit_reasons: list[str] = []
    elif state_model_forced in {"1", "true", "yes"}:
        audit_reasons = ["环境变量要求连续性模型抽查"]
    else:
        audit_reasons = _state_audit_reasons(request_payload)
    deterministic_payload = parse_json_result(_ensure_state_globals(
        _fallback_state_batch(
            request_payload,
            episode_start=episode_start,
            episode_end=episode_end,
            reason="默认使用代码状态提取，未调用状态模型",
        ),
        request_payload,
    ))
    deterministic_payload["state_status"] = "deterministic"
    deterministic_payload["state_warnings"] = []
    deterministic = json.dumps(deterministic_payload, ensure_ascii=False, indent=2)
    if not audit_reasons:
        return deterministic
    return _audit_deterministic_state(
        deterministic,
        request_payload,
        modules=modules,
        reasons=audit_reasons,
    )


def generate_stage_result(stage: str, request_payload: dict, *, modules: str) -> str:
    episode_start = max(1, int(request_payload.get("episode_start") or 1))
    total = max(1, int(request_payload.get("episodes") or 1))
    episode_end = max(
        episode_start,
        int(request_payload.get("episode_end") or (episode_start + total - 1)),
    )
    if stage == "state_recorder":
        return generate_state_result(request_payload, modules=modules)
    stage_batch_size = STAGE_BATCH_SIZES.get(stage, BATCH_SIZE)
    if stage not in BATCHED_EPISODE_STAGES:
        user_prompt = _stage_user_prompt(stage, request_payload, modules)
        if stage == "episode_continuity":
            result = generate_episode_card_batch(
                request_payload,
                user_prompt,
                stage_label=stage,
            )
        else:
            result = call_model(PROMPTS[stage], user_prompt, stage=stage)
        if stage in BATCHED_EPISODE_STAGES:
            result = _merge_episode_outputs(
                "",
                result,
                episode_start=episode_start,
                episode_end=episode_end,
                stage=stage,
            )
            violations = episode_range_violations(result, request_payload)
            if violations:
                raise SystemExit(f"{stage}集数合同未满足：" + "；".join(violations))
        return result

    result = ""
    resume_path = ROOT / "stage_resume.json"
    if resume_path.is_file():
        try:
            resume_payload = json.loads(resume_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            resume_payload = {}
        if str(resume_payload.get("stage") or "") == stage:
            result = _merge_episode_outputs(
                "",
                str(resume_payload.get("content") or ""),
                episode_start=episode_start,
                episode_end=episode_end,
                stage=stage,
            )
    no_progress_attempts: dict[tuple[int, int], int] = {}
    while True:
        missing_ranges = _missing_episode_ranges(
            result,
            episode_start=episode_start,
            episode_end=episode_end,
            batch_size=stage_batch_size,
        )
        if not missing_ranges:
            break
        batch_start, batch_end = missing_ranges[0]
        batch_request = dict(request_payload)
        batch_request.update(
            {
                "episodes": batch_end - batch_start + 1,
                "episode_start": batch_start,
                "episode_end": batch_end,
                "series_episode_start": episode_start,
                "series_episode_end": episode_end,
                "series_episode_count": total,
                "episode_contract": (
                    f"当前为缺失集定向补齐，必须且只能交付第{batch_start}集至第{batch_end}集；"
                    f"全剧范围为第{episode_start}集至第{episode_end}集。"
                ),
            }
        )
        batch_user_prompt = _stage_user_prompt(
            stage,
            batch_request,
            modules,
            episode_start=batch_start,
            episode_end=batch_end,
            previous_tail=result[-1800:],
        )
        if stage == "episode_continuity":
            batch = generate_episode_card_batch(
                batch_request,
                batch_user_prompt,
                stage_label=f"{stage}:{batch_start}-{batch_end}",
            )
        else:
            batch = call_model(
                PROMPTS[stage],
                batch_user_prompt,
                stage=f"{stage}:{batch_start}-{batch_end}",
            )
        before = set(episode_numbers(result))
        result = _merge_episode_outputs(
            result,
            batch,
            episode_start=episode_start,
            episode_end=episode_end,
            stage=stage,
        )
        expected = set(range(batch_start, batch_end + 1))
        added = set(episode_numbers(result)) - before
        if not added.intersection(expected):
            key = (batch_start, batch_end)
            no_progress_attempts[key] = no_progress_attempts.get(key, 0) + 1
        else:
            no_progress_attempts.pop((batch_start, batch_end), None)
        if no_progress_attempts.get((batch_start, batch_end), 0) >= 3:
            raise SystemExit(
                f"{stage}连续3次未能补齐第{batch_start}-{batch_end}集；"
                f"已生成集号为{episode_numbers(result)}"
            )
        emit_stage_checkpoint(stage, result)

    violations = episode_range_violations(result, request_payload)
    if violations:
        raise SystemExit(f"{stage}合并集数合同未满足：" + "；".join(violations))
    return result


def distilled_skill_modules(stage: str, request_payload: dict) -> str:
    """Load only the selected distilled modules routed to this team role."""
    skill = request_payload.get("distilled_skill")
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
        "以下内容只用于增强题材节奏、情绪与表达。示例是方法，不是必须照搬的事件、人物或道具；"
        "不得覆盖 MAINLINE_LOCK_JSON、逐集卡、用户事实、节点职责和输出格式。"
        "执行前先把每条规则还原为叙事功能、触发条件、变量槽位、节拍关系和失败边界。"
        "不得迁移Skill样本中的人物身份、关系套路、职业、场景、道具、证据手段、疾病或具体事件；"
        "这些内容只有在用户材料或当前上游合同独立提出时才能出现。Skill不得主动提议其同义替代品。\n"
        + "".join(chunks)
    )


def parse_json_result(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, count=1)
        value = re.sub(r"\s*```$", "", value, count=1)
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        if start < 0:
            raise SystemExit("状态记录器未返回 JSON 对象")
        try:
            payload, _end = json.JSONDecoder().raw_decode(value[start:])
        except json.JSONDecodeError as exc:
            raise SystemExit(f"story_state.json 解析失败：{exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("story_state.json 顶层必须是对象")
    return payload


def _mainline_lock_from_text(text: str) -> dict:
    match = MAINLINE_RE.search(str(text or ""))
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def inter_stage_contract_errors(stage: str, result: str) -> list[str]:
    """Check only invariants that can be proven without asking the model to grade itself."""
    errors: list[str] = []
    if stage == "showrunner":
        if not _mainline_lock_from_text(result):
            errors.append("创作任务书缺少合法 MAINLINE_LOCK_JSON")
        if not ROUTING_RE.search(result):
            errors.append("创作任务书缺少合法 SKILL_ROUTING_JSON")
        return errors
    contract_path = ROOT / ROLE_FILES["showrunner"]
    contract = contract_path.read_text(encoding="utf-8") if contract_path.is_file() else ""
    locked = _mainline_lock_from_text(contract)
    if not locked:
        if not contract.strip():
            errors.append("上游创作任务书缺失")
        return errors
    if stage == "state_recorder":
        try:
            state = parse_json_result(result)
        except SystemExit as exc:
            return [str(exc)]
        state_lock = state.get("mainline_lock")
        if not isinstance(state_lock, dict) or state_lock != locked:
            errors.append("状态记录器的 mainline_lock 与创作任务书不一致")
        return errors
    output_lock = _mainline_lock_from_text(result)
    if output_lock and output_lock != locked:
        errors.append(f"{stage} 改写了 MAINLINE_LOCK_JSON")
    return errors


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
    stage_name = stage.split(":", 1)[0]
    max_tokens = {
        "showrunner": 8_000,
        "story_architect": 12_000,
        "character_emotion": 12_000,
        "episode_continuity": 12_000,
        "script_writer": 16_000,
        "state_recorder": 10_000,
        "final_editor": 16_000,
    }.get(stage_name, 16_000)
    temperature = 0.45 if stage_name in {"script_writer", "final_editor"} else 0.25
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
    response = None
    try:
        for attempt in range(1, 3):
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
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "stream": False,
                    },
                    timeout=timeout_seconds,
                )
            except requests.RequestException as exc:
                if attempt == 2:
                    raise SystemExit(f"DeepSeek 请求失败：{exc}") from exc
                print(f"__SCRIPT_TEAM_MODEL_RETRY__ stage={stage} attempt={attempt + 1}", flush=True)
                time.sleep(2)
                continue
            if response.status_code not in {408, 429, 500, 502, 503, 504} or attempt == 2:
                break
            print(
                f"__SCRIPT_TEAM_MODEL_RETRY__ stage={stage} attempt={attempt + 1} "
                f"http_status={response.status_code}",
                flush=True,
            )
            time.sleep(2)
    finally:
        stop_event.set()
        heartbeat.join(timeout=1)
        print(
            f"__SCRIPT_TEAM_MODEL_END__ stage={stage} "
            f"elapsed_seconds={max(0, int(time.monotonic() - started_at))}",
            flush=True,
        )
    if response is None:
        raise SystemExit("DeepSeek 未返回 HTTP 响应")
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
    modules = skill_modules(stage) + distilled_skill_modules(stage, request_payload)
    result = generate_stage_result(stage, request_payload, modules=modules)
    contract_errors = inter_stage_contract_errors(stage, result)
    if contract_errors:
        raise SystemExit(f"{stage}上游承接合同未满足：" + "；".join(contract_errors))
    if stage in {"script_writer", "final_editor"}:
        violations = scene_contract_violations(result, request_payload)
        if violations:
            blocking_message = blocking_scene_contract_message(
                stage,
                result,
                request_payload,
            )
            if blocking_message:
                raise SystemExit(blocking_message)
            print(
                "__SCRIPT_TEAM_NONBLOCKING_AUDIT__ "
                f"stage={stage} issue=scene_contract detail="
                + "；".join(violations[:20]),
                flush=True,
            )
    output_path = ROOT / ROLE_FILES[stage]
    if stage == "state_recorder":
        output_path.write_text(
            json.dumps(parse_json_result(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        output_path.write_text(result, encoding="utf-8")
    emit_stage_checkpoint(stage, output_path.read_text(encoding="utf-8"))
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
