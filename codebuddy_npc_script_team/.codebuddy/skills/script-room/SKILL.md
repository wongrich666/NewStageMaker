---
name: script-room
description: 生成、修订和验收AI漫剧或AI真人剧；用于创作合同、人物声音、分集连续、强钩子、结构化故事状态和剧本质量门禁。
---

# 专业剧本团队

## 单一事实源

所有角色必须读取 `.script-team` 中已存在的上游文件，不得用聊天回复替代文件交付。
不得擅自改变人物姓名、关系、目标、世界规则、关键秘密、结局方向和禁改事实。

文件顺序：

1. `01_contract.md`：创作合同。
2. `02_story.md`：故事架构。
3. `03_characters.md`：人物、关系和声音配方。
4. `04_episodes.md`：逐集场景卡。
5. `05_draft.txt`：唯一初稿。
6. `story_state.json`：结构化事实状态。
7. `gate_pre.json`：初稿确定性检查。
8. `final_script.txt`：终审与钩子编辑后的纯剧本。
9. `gate_final.json`：发布前严格门禁。

## 执行顺序

创作合同 → 架构 → 人物声音 → 分集卡 → 正文 → 状态提取 → 软门禁 →
终审与钩子修订 → 严格门禁 → 发布。

正文对白编剧是唯一初稿作者。其他角色只能在既有故事内补充事实、直接修稿或验收，
不得重新发明主线。

用户任务中的数值字段 `episodes=N` 是总集数唯一权威。所有剧本文件必须完整包含
第1集至第N集；补充方向中的单集试写或只交付某一集文字不得覆盖该数值。

## 按需读取

- 总编剧先读取
  [references/skill-routing.md](references/skill-routing.md)，在创作合同中输出机器可识别的
  `SKILL_ROUTING_JSON`。基础模块按节点职责常驻，增强模块只在合同启用后读取。
- 设计或修订开头、尾钩和局势变化时读取
  [references/hook-craft.md](references/hook-craft.md)。
- 建立人物、声音配方或改写对白时读取
  [references/character-voice.md](references/character-voice.md)。
- 设计分集、换场、集间动作和事实状态时读取
  [references/continuity.md](references/continuity.md)。
- 写入或读取 `story_state.json` 时严格遵守
  [references/story-state-schema.md](references/story-state-schema.md)。
- 创作合同将 `adversity_payoff` 路由为 `core` 或 `support` 时，故事架构、分集、
  正文、状态和终审读取
  [references/adversity-payoff.md](references/adversity-payoff.md)；路由为 `off` 时不得套用。

## 发布条件

- 集数、正文、状态 schema 和集间桥通过代码门禁。
- 默认每集一至两个核心场景；超出时必须记录必要性。
- `final_script.txt` 只能包含片名和逐集可拍正文。
- 审核报告、评分表、修改说明或“质量达标”结论不得作为最终剧本。
- 严格门禁失败时禁止打印最终结果标记。
