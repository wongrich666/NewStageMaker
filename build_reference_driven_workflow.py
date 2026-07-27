from __future__ import annotations

import copy
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


SOURCE = Path(
    r"C:\Users\Administrator\Desktop\工作流json\工作流优化"
    r"\当前工作流_全题材保真强钩子直出_20260723_161247"
)
OUTPUT_ROOT = Path(r"C:\Users\Administrator\Desktop\工作流json\工作流优化")


COMMON = """

【全链路硬约束】
1. 只输出当前节点既有 JSON Schema 或既有纯文本格式。字段名、层级、类型、顶层输出变量全部不变，不新增字段。
2. 先锁定核心主角模式：男主、女主、双主角或群像。除明确交棒外，每集由核心主角的决定或行动推动状态变化。
3. 每集必须形成“承接上集状态 -> 主角即时目标 -> 阻力升级 -> 选择与代价 -> 状态改变 -> 下集待回应动作”的因果闭环。
4. 默认每集 1-2 个场景；高潮确有必要时可到 3 个。换场必须说明谁为何现在离开、如何到达、带着什么目标和未解决状态。
5. 新人物必须持有入场凭证：前置提及或关系依据、到场原因、到场方式、即时目标、对主角造成的压力/机会、离场或留场状态。缺一项不得突然出现。
6. 支线只有在本集改变主角的资源、关系、信息、代价或选择时才能出现；否则删除或延后。支线必须回撞主线。
7. 道具必须有来源、持有人、出现原因、剧情功能和去向。不得用无依据的U盘、监控、手机、文件、录音、照片、新闻或系统提示代替人物行动。
8. 开头第一句有效对白或动作必须是短钩子，直接制造压力、错位、损失、危险或未答问题。钩子必须来自本集既定人物关系和事件，不照搬后文高潮。
9. 回忆只有在当下触发且内部具备目标、阻力、选择、代价、未偿旧账时才能使用；回到当下后必须改变判断或行动。
10. 少用形容词、副词和摄影说明。对白以试探、遮掩、逼迫、拒绝、交换、误导、求助或关系变化为功能，禁止互相讲解已知信息和整齐的AI金句。
11. 事实优先级：用户明确要求 > 已确认上游字段 > 当前阶段推导。不得改人物生死、秘密顺序、关系结果、关键选择或既定结局。
12. 信息不足时在既有风险/说明字段中如实标记，不得用新人物、新设定或万能道具填空。
""".strip()


STAGE_RULES = {
    "01": """
你是“故事事实与戏剧燃料提取器”。本阶段只建立统一事实层，不扩写剧情。

提取并压缩：题材、主角、目标、主要阻力、世界约束、不可改事实、关系旧账、可用场景、目标集数，以及可制造强钩子的压力源。区分“原文事实、用户改编要求、合理推断”；推断不得伪装成事实。

重点写入既有字段：
- core_logline/core_conflict：主角目标与代价；
- must_keep_elements：不可删除的关系、事件、规则和情感债；
- available_material_summary：已有主线、可回撞主线的支线、人物共情软肋；
- missing_information_risks：主角不清、回忆无冲突、人物入场无依据、集数不足、钩子燃料弱等风险。

不要写完整世界观、人设、节拍或正文。episodes_per_season 等用户配置必须原样继承。
""",
    "02": """
你是“世界因果系统设计师”。根据事实层建立能持续制造人物选择的世界规则，不做网络搜索，不输出搜索计划。

世界观不是背景百科。每条规则必须回答：谁受益、谁受限、违反会付出什么代价、它会迫使主角做什么。只保留会进入剧情的制度、资源、能力、职业、地理和社会关系。

世界方案必须明确：
- 主角可行动的边界与升级/失败代价；
- 主要对抗力量为何现在阻止主角；
- 题材特有的信息传播、交通、权力与生存规则；
- 场景之间移动所需的时间、条件或身份；
- 哪些规则能稳定产生主线压力，哪些只能作为支线。

禁止用“现实/类型化世界、强情绪、强节奏”之类空话代替具体规则。不得新增与 source_brief 冲突的大设定。
""",
    "03": """
你是“人物行动系统设计师”。人物不是标签集合，而是带着目标、软肋、秘密和行动权限的剧情发动机。

为每个必要人物建立：表面目标、真实需要、不可触碰点、错误信念、可付代价、与主角的利益关系、独特说话方式、首次出场依据、进入/离开场景的条件。合并功能重复人物，删除只负责解释信息的人物。

人物首次出现必须能追溯到既有关系、传闻、任务、求助、追捕、交易或事件后果。任何新人物都要立即改变主角的压力、机会、信息或选择。配角支线必须在明确节点回撞主线。

情感表达依靠具体行为：嘴硬、回避、照顾、失误、遮羞、误判、自我推翻和有代价的选择；不要直接写“善良、腹黑、深情”等结论。
""",
    "04": """
你是“三幕十五节拍因果规划师”。严格输出既有 15 个节拍及说明，不做网络搜索。

每个节拍必须包含：发生前状态、触发事件、主角选择、代价、不可逆状态变化、下一节拍为何必然发生。节拍不是主题说明，也不是并列事件清单。

规划全剧主线推进与阶段升级：开局生存/欲望问题，中段方法变化与代价累积，后段价值选择与终局兑现。支线进入节拍时必须改变主线。首次出场的重要人物至少提前以关系、消息、需求或后果埋下入场依据。

集数范围必须连续、完整、不重叠、不缺集。检查重复节拍、重复集号和缺失集号。开篇节拍必须允许第1集第一句直接进入压力，不能先交代世界。
""",
    "05": """
你是“主线与支线交织设计师”。以核心主角的连续行动为主轴，设计必要人物线。

主线记录每阶段主角想完成什么、使用什么方法、遭遇何种代价、最终状态怎样改变。每条支线都要说明：因何启动、与主线在哪些集碰撞、给主角增加或夺走什么、何时回收。不能回撞主线的支线删除。

关系变化必须由共同经历、利益交换、误判、背叛、保护或代价触发，不允许突然爱上、突然翻脸、突然忠诚。人物离开与再次出现都要有可追踪状态。
""",
    "06": """
你是“全剧执行合同编剧”。把 01-05 压缩成后续不得违背的改编指引。

在既有字段中锁定：主角行动权、核心叙事承诺、主线阶段目标、支线碰撞点、强钩子机制、回忆使用条件、人物入场规则、场景移动规则、道具来源规则、对白与动作风格、每集场景和字数策略。

优先保留具体事件、选择、关系变化与结局，删除重复口号和同义要求。指引必须能被 07-12 直接执行和检查，不写文学评论。
""",
    "07": """
你是“框架编译与阻断式质检器”。整合 01-06 为唯一框架策划包，不自由创作。

逐项校验：顶层字段齐全；总集数一致；节拍覆盖无重叠缺失；人物首次出场有依据；人物关系变化有事件；每条支线回撞主线；场景移动可解释；关键道具有来源；第1集可直接形成强钩子。

发现冲突时按事实优先级选择唯一版本，并把问题写入既有 validation_report。阻断问题未解决不得伪装为通过。不要为了“丰富”新增人物、设定或事件。
""",
    "08": """
你是“可执行场景与世界规则字典编译器”。

只收录剧情确实需要的场景。每个场景写清可进入人物、进入条件、空间限制、可用动作、可见信息、离开路径、与其他场景的移动成本，以及已发生且不可逆的状态变化。

默认每集 1-2 场。场景不是装饰性美术描述；不能影响行动、暴露信息或改变结果的细节删掉。不得临时创造万能密室、监控死角或便利出口。
""",
    "09": """
你是“人物身份、外观、称谓与入场许可编译器”。

保持姓名、alias、身份、服装状态和伤势跨集一致。称谓变化必须由关系或身份事件触发。scene_trigger_rules 与 episode_usage_plan 必须同时约束人物何时能出现、为何出现、如何到场、完成何种剧情功能、离场后处于何种状态。

禁止把未获入场许可的人物放进场景；禁止同一人物无解释换名、换身份、换伤势或知道尚未获得的信息。
""",
    "10": """
你是“逐集因果蓝图总编剧”。第10阶段是正文不可改写的逐集剧情合同。

每集必须在既有字段中落实以下内容：
1. 开场承接：上一集最后地点、人物、动作/台词、道具、伤势、已知信息和未解决压力，本集第一组戏如何立即回应。
2. 主角推动：本集具体目标、主动行动、阻力、选择、代价和不可逆状态变化。
3. 主支线碰撞：至少一条必要支线如何改变主角资源、关系、信息或选择；没有有效碰撞时宁可只写主线。
4. 人物入场账：新进场人物的前置依据、到场原因/方式、即时目标、剧情功能和离场状态。
5. 场景迁移账：换场者、离开原因、目的地、移动方式/时间、到达后的第一动作；无迁移账不得换场。
6. 道具账：来源、持有人、用途、转移与去向。
7. 结尾与下集：结尾停在必须被下一集开头回应的动作、决定、发现或代价，不写空泛预告。

开头钩子用一句短台词或一个反常动作承载具体压力；不能靠长环境描写。集数必须完整连续，逐集标题与事件不得重复。
""",
    "11_write": """
你是“当前批次因果连续性施工图编剧”。忠实把第10阶段当前批次转成可直接写正文的 batchCausalConflictPlan，不改剧情合同。

逐集将连续性写进既有字段：
- carry_in：准确记录上集最后一秒并给出本集第一反应；
- why_now/natural_transition：解释人物为何此刻行动及换场全过程；
- active_characters/scene_refs：只允许已有入场依据的人物和场景；
- scene_cause_chain：按“因为A，所以B；人物选择C，付出D，状态变为E”写因果链；
- character_motivation：区分表面目标、真实需要、压力和不能说出口的话；
- opening_action：一句短台词或动作，立刻触发压力和未答问题；
- episode_state_change：写本集结束后不可撤销的变化；
- next_episode_priority_response：指定下一集第一组戏必须回应什么。

若人物首次进入当前批次，必须在相关既有文本字段中写清入场凭证。若场景变化，必须写迁移凭证。不得凭空补人物、道具或信息。
""",
    "11_review": """
你是“因果施工图阻断式审核员”。只审核，不润色，不重写。

逐集判定 blocking：
- 未直接回应上一集最后动作/后果；
- 主角未主动推动或无状态变化；
- 人物无前置依据突然出现、消失或知道未知信息；
- 换场无离开原因、移动过程或到达目标；
- 支线与主线无影响；
- 道具无来源或代替人物完成冲突；
- 开头先铺陈，钩子无具体压力；
- 结尾无法明确驱动下一集；
- 事件、人物选择、秘密顺序或结局偏离第10阶段。

任一项存在则 passed=false、rewrite_required=true，blocking_issues按“第X集：问题；必须恢复/补足什么”写明，rewrite_start_episode取最早错误集。只输出既有 Schema。
""",
    "11_rewrite": """
你是“因果施工图定向修订编剧”。第10阶段是不可变合同；只修审核指出的阻断问题及必要联动。

优先补齐上集反应、主角行动、人物入场凭证、场景迁移凭证、状态变化和下集回应。弱钩子在同一既定事件内改成一句短台词、反常动作、即时损失或关系错位，不得另造主线。无依据人物应删除、提前埋入或改由既有人物承担，不能硬写“恰好出现”。

输出完整当前批次 JSON，字段、集数和数组契约不变。
""",
    "11_memory": """
你是“因果连续性状态压缩器”。只记录下一批必须继承的事实，不创作。

final_hook_of_this_turn必须精确到最后地点、时间、在场人物、最后动作/台词、关键道具、伤势、已公开信息和未完成压力。causal_continuity_state记录不可逆选择、关系、资源、秘密知情范围、道具位置和场景状态。motivation_continuity记录人物下一步想做什么及为什么。

next_turn_opening_guidance必须要求下一批第一组有效戏先回应最后动作/后果；不得跳时空、换任务或让新人物无依据接管。只输出既有 Schema。
""",
    "12_write": """
你是“成品剧本主编剧”。一次完成当前批次正文；不得在生成后再交给第二个模型压缩或改写。

写每集前先锁定第10、11阶段的上集状态、主角目标、允许人物、允许场景、因果链、状态变化和结尾钩子。第一句有效对白或动作必须短、具体、有压力，例如命令、拒绝、揭穿、危险动作或关系错位；钩子前不写天气、装修、外貌、醒来过程和背景说明。

下一集开头必须先演出上一集最后动作/台词的直接反应或后果。换场时用最短可演动作交代离开原因、移动目标和到达动作。新人物只有具备上游入场凭证才能出现。

对白短而有目的，允许打断、改口、答非所问、停顿和沉默；人物说符合身份的话，不说剧情摘要和主题口号。动作只写可演且改变局面的事实，少形容词副词。

按目标字数一次写准，允许约 ±10%；篇幅不足先补选择、反应和因果，不补环境。篇幅超出先删重复解释和形容词，不删事件、人物选择、连续性桥梁或钩子。严格使用既有剧本正文格式并输出纯正文。
""",
    "12_review": """
你是“成品剧本阻断式审核员”。只审核当前正文与第10、11阶段是否一致。

逐集检查：开头5秒是否有具体压力；是否立即承接上集最后一秒；主角是否主动推动；新人物是否有入场凭证；换场是否有迁移凭证；支线是否改变主线；对白是否在行动而非讲解；形容词和摄影说明是否过量；结尾是否准确停在既定钩子；字数是否在允许范围。

人物突然出现、瞬移、剧情硬事件丢失、秘密提前、结局变化、钩子平淡或正文被说明性对白拖垮均为 blocking。只输出既有 Schema，不直接改正文。
""",
    "12_rewrite": """
你是“成品剧本定向修订编剧”。依据审核结果对最小必要段落做手术式修复，输出完整批次正文。

不得自由重写已合格内容，不得新增人物、主线、万能道具或额外反转。连续性问题补直接反应、离开原因、到达动作和状态继承；人物入场问题删除无依据角色或改由已有角色承担；弱钩子在同一事件内改成短台词/动作加即时后果；AI对白改为带目的、潜台词和人物差异的短句。

控制字数时只删重复解释、形容词和无效动作，不删剧情合同。输出纯正文。
""",
    "12_memory": """
你是“正文连续性记忆压缩器”。只提取正文已经发生的事实，不评价、不创作。

记录最后一集最后一秒、人物位置/伤势/关系/目标、秘密知情范围、资源与道具位置、场景破坏、尚未回应的动作和下一集第一反应。任何新批次必须从这些状态继续，不能恢复旧状态或让人物瞬移。

去重、短句、确定性表达。只输出既有 Schema。
""",
}


def input_lines(prompt: str) -> str:
    lines = []
    for line in prompt.splitlines():
        if "{{$" in line and line.strip() not in lines:
            lines.append(line.strip())
    return "\n".join(lines)


def get_input(node: dict, key: str) -> dict | None:
    for item in node.get("inputs", []):
        if item.get("key") == key:
            return item
    return None


def classify(path: Path) -> str:
    rel = str(path.relative_to(SOURCE))
    if rel.startswith("11阶段"):
        if "01编写" in rel:
            return "11_write"
        if "02审核" in rel:
            return "11_review"
        if "03修订" in rel:
            return "11_rewrite"
        return "11_memory"
    if rel.startswith("12阶段"):
        if "01编写" in rel:
            return "12_write"
        if "02审核" in rel:
            return "12_review"
        if "03修订" in rel:
            return "12_rewrite"
        return "12_memory"
    return path.name[:2]


def node_id(data: dict, flow_type: str) -> str | None:
    for node in data["nodes"]:
        if node.get("flowNodeType") == flow_type:
            return node.get("nodeId")
    return None


def simplify_dispatch(data: dict) -> None:
    start = node_id(data, "workflowStart")
    var = node_id(data, "variableUpdate")
    answer = node_id(data, "answerNode")
    chats = [n for n in data["nodes"] if n.get("flowNodeType") == "chatNode"]
    creator = next(
        (n for n in chats if "调度" not in n.get("name", "") and "判断" not in n.get("name", "")),
        chats[-1],
    )
    keep_ids = {start, creator["nodeId"], var, answer}
    data["nodes"] = [
        n
        for n in data["nodes"]
        if n.get("nodeId") in keep_ids
        or n.get("flowNodeType") not in {"tools", "tool", "toolParams"}
    ]
    update = next(n for n in data["nodes"] if n.get("nodeId") == var)
    update_list = get_input(update, "updateList")
    if update_list:
        for item in update_list.get("value", []):
            item["value"] = [creator["nodeId"], "answerText"]
    data["edges"] = [
        {
            "source": start,
            "target": creator["nodeId"],
            "sourceHandle": f"{start}-source-right",
            "targetHandle": f"{creator['nodeId']}-target-left",
        },
        {
            "source": creator["nodeId"],
            "target": var,
            "sourceHandle": f"{creator['nodeId']}-source-right",
            "targetHandle": f"{var}-target-left",
        },
        {
            "source": var,
            "target": answer,
            "sourceHandle": f"{var}-source-right",
            "targetHandle": f"{answer}-target-left",
        },
    ]


def remove_word_count_rewriter(data: dict) -> None:
    chats = [n for n in data["nodes"] if n.get("flowNodeType") == "chatNode"]
    controllers = [
        n for n in chats if "字数" in n.get("name", "") or "控制编剧" in n.get("name", "")
    ]
    if not controllers:
        return
    controller_ids = {n["nodeId"] for n in controllers}
    main = next(n for n in chats if n["nodeId"] not in controller_ids)
    data["nodes"] = [n for n in data["nodes"] if n.get("nodeId") not in controller_ids]
    for node in data["nodes"]:
        if node.get("flowNodeType") == "variableUpdate":
            update_list = get_input(node, "updateList")
            if update_list:
                for item in update_list.get("value", []):
                    if isinstance(item.get("value"), list) and item["value"][0] in controller_ids:
                        item["value"] = [main["nodeId"], "answerText"]
    new_edges = []
    for edge in data.get("edges", []):
        if edge.get("source") in controller_ids or edge.get("target") in controller_ids:
            continue
        new_edges.append(edge)
    var = node_id(data, "variableUpdate")
    if var and not any(e.get("source") == main["nodeId"] and e.get("target") == var for e in new_edges):
        new_edges.append(
            {
                "source": main["nodeId"],
                "target": var,
                "sourceHandle": f"{main['nodeId']}-source-right",
                "targetHandle": f"{var}-target-left",
            }
        )
    data["edges"] = new_edges


def rewrite_file(src: Path, dst: Path) -> dict:
    data = json.loads(src.read_text(encoding="utf-8-sig"))
    stage = classify(src)
    if stage in {"02", "03", "04"}:
        simplify_dispatch(data)
    if stage in {"12_write", "12_rewrite"}:
        remove_word_count_rewriter(data)

    chat_nodes = [n for n in data["nodes"] if n.get("flowNodeType") == "chatNode"]
    if len(chat_nodes) != 1:
        raise RuntimeError(f"{src.name}: expected one content chat node, got {len(chat_nodes)}")
    node = chat_nodes[0]
    model = get_input(node, "model")
    if model:
        model["value"] = "deepseek-v4-pro"
    system_prompt = get_input(node, "systemPrompt")
    if not system_prompt:
        raise RuntimeError(f"{src.name}: missing systemPrompt")
    inherited_inputs = input_lines(str(system_prompt.get("value", "")))
    schema_note = (
        "\n\n【本节点可用输入】\n" + inherited_inputs
        if inherited_inputs
        else ""
    )
    system_prompt["value"] = (
        STAGE_RULES[stage].strip()
        + schema_note
        + "\n\n"
        + COMMON
        + "\n\n最终严格遵守本节点既有输出 Schema；不得输出 Markdown 代码块或解释前缀。"
    )

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "file": str(dst.relative_to(dst.parents[1])),
        "stage": stage,
        "nodes": len(data["nodes"]),
        "edges": len(data.get("edges", [])),
        "model": model.get("value") if model else None,
        "prompt_chars": len(system_prompt["value"]),
    }


def write_reports(out: Path, manifest: list[dict]) -> None:
    analysis = """# 双样本结构分析

## 样本概况

- 《末世兽潮》：60 集，约 6.7 万字，显式场次约 118 个，主体保持每集 1-2 场。
- 《别让我守身如玉啊这系统它针对单身狗》：50 集，约 5 万字，多次使用“开场接上/场景接上”明确锁定连续动作。

## 两部剧本共同有效的机制

1. **每集改变状态**：主角不是听完信息就结束，而是作出选择，导致身份、资源、关系、伤势、知情范围或任务发生不可逆变化。
2. **结尾就是下一集任务**：上一集最后的命令、危险、来访、发现或决定，直接成为下一集第一组戏的处理对象。
3. **核心主角持续拥有行动权**：《末世兽潮》围绕逃生、囤积、升级、防守和联盟推进；“系统单身狗”围绕存活、破解规则、优化修炼和扩大方法论推进。
4. **支线服务主线**：感情、家族、宗门、商业、同盟等支线，都在改变主角的方法、成本、资源或选择，没有脱离主角单独空转。
5. **人物凭功能入场**：新人物通常作为追捕者、求助者、客户、考验者、盟友或竞争者出现，且出现原因来自上游事件或主角声望。
6. **场景由目标切换**：人物先产生“为什么要去”，再进入新场景；场景不是随机换景。
7. **升级保持同一故事引擎**：规模会从个人生存升级到组织、世界危机，但主角解决问题的核心方法不变。

## 需要吸收而不是照抄的部分

- 吸收“动作承接、状态变化、人物入场凭证、主支线碰撞”的结构。
- 不固定复制末世、系统、宗门、打脸、监控或电子证据等题材元素。
- 样本中少量重复标题、说明性对白和偏多镜头描述不应进入新流程。

## 对新工作流的直接结论

- 每集必须有开场承接账、人物入场账、场景迁移账、状态变化账和下集回应指令。
- 第10阶段成为不可变逐集合同；第11阶段只施工；第12阶段只落正文。
- 正文生成后不再经过第二模型做字数重写，避免剧情和钩子被洗掉。
"""
    design = """# 新工作流设计说明

## 兼容策略

继续使用平台现有 01-12 阶段和全部顶层输出字段，因此可直接导入现有 FastGPT/平台链路。内部提示词已经整体重写，适配男频、女频、双主角、群像以及现实、情感、悬疑、喜剧、古装、玄幻、科幻等题材。

## 阶段职责

| 阶段 | 唯一职责 |
|---|---|
| 01 | 提取事实、限制和戏剧燃料 |
| 02 | 把世界观变成可制造选择与代价的规则 |
| 03 | 建立人物行动系统与首次入场许可 |
| 04 | 生成带因果和不可逆变化的十五节拍 |
| 05 | 设计主线及会回撞主线的支线 |
| 06 | 压缩为后续统一执行合同 |
| 07 | 编译并阻断字段、集数、入场、转场错误 |
| 08 | 建立可执行场景与移动规则 |
| 09 | 锁定身份、称谓、外观和人物使用条件 |
| 10 | 生成逐集不可变剧情合同 |
| 11 | 生成/审核/修订/记忆当前批次因果施工图 |
| 12 | 一次生成/审核/定向修订/记忆成品正文 |

## 关键改造

1. 阶段 02、04 移除网络搜索调度与工具节点，直接生成结构化结果，减少返回搜索计划、字段空缺和前端不显示。
2. 阶段 12 的编写与修订移除二次“字数控制编剧”。字数在主编剧节点一次完成，防止二次改写洗掉钩子、因果和人物声音。
3. 所有模型统一为 `deepseek-v4-pro`。
4. 所有 JSON Schema、顶层变量名和前端依赖字段保持不变。
5. 全链路写入人物入场凭证、场景迁移凭证、主角行动权、支线回撞和状态继承规则。

## 使用顺序

先替换并发布 01-10，再完整重跑项目；随后替换 11、12 四件套。旧项目缓存了上游状态时，不建议只重跑 12，否则旧的分集合同仍会继续影响正文。
"""
    contract = """# 字段衔接与质检门槛

## 不变的顶层字段

`source_brief` -> `worldview_plan` -> `character_plan` -> `beat_checkpoint_timeline` -> `character_storylines` -> `adaptation_guide` -> `framework_plan_package` -> `sceneDictionary` -> `appearanceMapping` -> `allEnrichedEpisodePlan` -> `batchCausalConflictPlan` -> `batchScriptText`

记忆字段继续使用原流程中的 `conflictMemory` 与 `scriptMemory`，审核/修订字段保持原 Schema。

## 阻断门槛

- 上一集最后动作没有在下一集开头得到回应。
- 核心主角本集没有主动行动或状态变化。
- 新人物没有前置依据、到场原因、即时目标和离场状态。
- 换场没有离开原因、移动目标和到达动作。
- 支线没有改变主角资源、关系、信息、代价或选择。
- 道具没有来源、持有人、功能和去向。
- 开头先铺陈环境，前五秒没有具体压力或未答问题。
- 第10阶段的事件、选择、秘密顺序、关系结果或结局被第11/12阶段改写。

任一项存在，11/12 审核必须返回失败并指定最早修订集。
"""
    (out / "00_双样本结构分析.md").write_text(analysis, encoding="utf-8")
    (out / "00_新工作流设计说明.md").write_text(design, encoding="utf-8")
    (out / "00_字段衔接与质检门槛.md").write_text(contract, encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source_template": str(SOURCE),
                "workflow_files": manifest,
                "top_level_contract_preserved": True,
                "model": "deepseek-v4-pro",
                "structural_changes": [
                    "stage 02/04 search dispatch removed",
                    "stage 12 secondary word-count rewrite removed",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Source template not found: {SOURCE}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUTPUT_ROOT / f"全新工作流_双样本因果连续性全题材_{stamp}"
    out.mkdir(parents=True)
    manifest = []
    for src in sorted(SOURCE.rglob("*.json")):
        dst = out / src.relative_to(SOURCE)
        manifest.append(rewrite_file(src, dst))
    write_reports(out, manifest)
    print(out)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
