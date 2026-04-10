from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptFix:
    node_id: str
    input_key: str
    description: str


def normalize_prompt(node_id: str, input_key: str, value: str) -> tuple[str, list[PromptFix]]:
    if input_key != "systemPrompt" or not isinstance(value, str):
        return value, []

    text = value
    fixes: list[PromptFix] = []

    def _replace(old: str, new: str, description: str) -> None:
        nonlocal text
        if old in text:
            text = text.replace(old, new)
            fixes.append(
                PromptFix(
                    node_id=node_id,
                    input_key=input_key,
                    description=description,
                )
            )

    if node_id == "hkqS87SbnICwToox":
        _replace(
            "【当前人设JSON】{{$c8dQrGAIwG5dD32J.answerText$}}",
            "【当前人设JSON】{{$VARIABLE_NODE_ID.fFM0mroW$}}",
            "人设审核改为读取循环后的当前人设变量，避免审核旧初稿。",
        )

    if node_id == "sybkLGNSDvuRF1b0":
        _replace(
            "修订当前场景JSON ：{{$VARIABLE_NODE_ID.fFM0mroW$}}",
            "修订当前场景JSON ：{{$VARIABLE_NODE_ID.iJudZHhM$}}",
            "场景修订改为读取当前场景变量，避免误把人物摘要当场景 JSON。",
        )

    if node_id == "pYmIGTdscTjB34Pp":
        _replace(
            "【人设场景结果JSON】\n{{$VARIABLE_NODE_ID.fFM0mroW$}}，",
            "【人设结果摘要】\n{{$VARIABLE_NODE_ID.fFM0mroW$}}\n【场景结果JSON】\n{{$VARIABLE_NODE_ID.iJudZHhM$}}",
            "钩子生成补入场景结果，消除“人设场景结果”只有人设没有场景的歧义。",
        )
        _replace(
            "一次只性写五集",
            "一次只写五集",
            "修正钩子生成提示词中的笔误。",
        )

    if node_id == "rUZ4xLNv2Zw5WoGW":
        _replace(
            "一次只性写五集",
            "一次只写五集",
            "修正角色对话生成提示词中的笔误。",
        )

    if node_id == "uq4CUgDXJK0iPnnn":
        _replace(
            "7. 当前集数减去5之后大于{{$VARIABLE_NODE_ID.blkSS7dY$}}，存在扩写，或一次写的数量超过五集，直接打回\n8. 如果有重复的集、集数不连贯直接打回",
            "7. 如果输出超出当前应写批次、超过总集数、或一次写的数量超过五集，直接打回\n8. 如果有重复的集、集数不连贯，也直接打回",
            "钩子审核改写为直接检查批次越界与集数错误，消除算式表达的歧义。",
        )

    if node_id == "mCJVQGweeCJChKI9":
        _replace(
            "9. 当前集数减去5之后大于{{$VARIABLE_NODE_ID.blkSS7dY$}}，存在扩写，或一次写的数量超过五集，直接打回\n10. 如果有重复的集、集数不连贯直接打回",
            "9. 如果输出超出当前应写批次、超过总集数、或一次写的数量超过五集，直接打回\n10. 如果有重复的集、集数不连贯，也直接打回",
            "角色对话审核改写为直接检查批次越界与集数错误，消除算式表达的歧义。",
        )

    if node_id == "riKJtX6mPgdMak9I":
        _replace(
            "【世界观JSON】\n{{$VARIABLE_NODE_ID.yuozoGpo$}}\n【开头冲突钩子JSON】",
            "【世界观JSON】\n{{$VARIABLE_NODE_ID.yuozoGpo$}}\n【人设结果摘要】\n{{$VARIABLE_NODE_ID.fFM0mroW$}}\n【场景结果JSON】\n{{$VARIABLE_NODE_ID.iJudZHhM$}}\n【开头冲突钩子JSON】",
            "正文生成补入人设与场景结果，和提示词开头声明保持一致。",
        )
        _replace(
            "【任务目标】\n让人物动机从人物内部自然生长出来，使角色行为具有必然性、可共情性和说服力；同时让每一场都真正推动剧情，而不是停留在解释、铺垫和空转上。",
            "【补充推进目标】\n让人物动机从人物内部自然生长出来，使角色行为具有必然性、可共情性和说服力；同时让每一场都真正推动剧情，而不是停留在解释、铺垫和空转上。",
            "正文生成将重复的任务目标改为补充目标，保留原意同时减少歧义。",
        )
        _replace(
            "每集控制在 2-3 场，场景使用“场景1-1”的格式开头，场次头必须清晰标示",
            "每集控制在 2-3 场，场次头使用“6-1 / 6-2 / 6-3”这一类格式开头，并且必须清晰标示",
            "正文生成统一场次编号格式，避免与审核提示词冲突。",
        )
        _replace(
            "不要输出 JSON、Markdown、解释、总结、审核意见数据剧本格式的文段。",
            "不要输出 JSON、Markdown、解释、总结或审核意见等非剧本文段。",
            "正文生成修正输出规则中的语病，保持禁止项含义不变。",
        )

    if node_id == "qsa5jqscPavJr68p":
        _replace(
            "当前集数为“{{$VARIABLE_NODE_ID.d4sfifeZ$}}”减去5的值，若这个值大于{{$VARIABLE_NODE_ID.blkSS7dY$}}，认定为存在扩写，或一次写的数量超过五集，直接打回",
            "如果输出超出当前应写批次、超过总集数、或一次写的数量超过五集，直接打回",
            "正文审核改写为直接检查批次越界与集数错误，消除算式表达的歧义。",
        )
        _replace(
            "8. 当前集数减去5之后大于{{$VARIABLE_NODE_ID.blkSS7dY$}}，存在扩写，或一次写的数量超过五集，直接打回",
            "8. 如果输出超出当前应写批次、超过总集数、或一次写的数量超过五集，直接打回",
            "正文审核重点条目同步改成直接约束表达。",
        )
        _replace(
            "11. 是否存在以下常见问题：\n- \n  - 动机断裂\n  - 人物突然转变但没有触发过程\n  - 结尾钩子无效\n  - 下一集开头没有承接上一集结尾\n  - 倒叙使用生硬且没有明确切回\n  - 擅自新增核心设定、关键规则、关键任务、关键组织、关键真相、关键道具\n  - 扩写到当前批次之外的集数\n  - 每集字数严格把控在{{$VARIABLE_NODE_ID.eBEWC07Q$}}浮动10%以内，如果有超过需要立即打回",
            "11. 是否存在以下常见问题：\n- 动机断裂\n- 人物突然转变但没有触发过程\n- 结尾钩子无效\n- 下一集开头没有承接上一集结尾\n- 倒叙使用生硬且没有明确切回\n- 擅自新增核心设定、关键规则、关键任务、关键组织、关键真相、关键道具\n- 扩写到当前批次之外的集数\n- 每集字数严格把控在{{$VARIABLE_NODE_ID.eBEWC07Q$}}浮动10%以内，如果有超过需要立即打回",
            "正文审核整理了嵌套错乱的条目，保留原有检查项。",
        )

    return text, fixes
