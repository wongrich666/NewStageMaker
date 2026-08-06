# story_state.json 契约

状态记录器只提取事实，不改写剧本。输出必须是单个合法 JSON 对象，不得使用 Markdown
代码围栏或附加解释。

`project.episode_count` 记录本次生成集数。`episodes` 数组必须覆盖请求中的
`episode_start` 至 `episode_end`；续写模式下第一条记录的 `continuity_bridge`
连接 `source_last_episode`，不得强制从第1集开始。

```json
{
  "schema_version": "1.0",
  "project": {
    "title": "string",
    "protagonist": "string",
    "episode_count": 1,
    "target_words_per_episode": 800,
    "immutable_facts": ["string"]
  },
  "mainline_lock": {
    "protagonist": "string",
    "goal": "string",
    "core_obstacle": "string",
    "protagonist_action": "string",
    "stakes": "string",
    "pursuit_question": "string",
    "ending_direction": "string"
  },
  "characters": [
    {
      "name": "string",
      "role": "protagonist|antagonist|supporting",
      "first_appearance": 1,
      "voice_recipe": {
        "sentence_length": "string",
        "evasion_style": "string",
        "pressure_pattern": "string",
        "forbidden_phrases": ["string"],
        "samples": ["string", "string", "string"],
        "unspoken_truth": "string"
      }
    }
  ],
  "props": [
    {
      "name": "string",
      "first_appearance": 1,
      "source": "string"
    }
  ],
  "episodes": [
    {
      "episode": 1,
      "opening_action": "string",
      "closing_action": "string",
      "core_scenes": ["string"],
      "scene_exception_reason": "",
      "continuity_bridge": null,
      "character_states": [
        {
          "name": "string",
          "location": "string",
          "knowledge": ["string"],
          "injuries": ["string"],
          "clothing": ["string"],
          "held_props": ["string"],
          "relationships": {"人物名": "string"},
          "unfinished_actions": ["string"]
        }
      ],
      "introduced_characters": ["string"],
      "introduced_props": ["string"],
      "information_changes": ["string"],
      "open_loops": ["string"],
      "resolved_loops": ["string"]
    },
    {
      "episode": 2,
      "opening_action": "string",
      "closing_action": "string",
      "core_scenes": ["string"],
      "scene_exception_reason": "",
      "continuity_bridge": {
        "previous_episode": 1,
        "from_action": "string",
        "to_action": "string",
        "reason": "string"
      },
      "character_states": [],
      "introduced_characters": [],
      "introduced_props": [],
      "information_changes": [],
      "open_loops": [],
      "resolved_loops": []
    }
  ],
  "open_threads": [
    {
      "id": "string",
      "introduced_episode": 1,
      "description": "string",
      "status": "open|resolved",
      "resolved_episode": null
    }
  ],
  "plan_alignment": [
    {
      "episode": 1,
      "planned_mainline_advance": "分集卡中的本集主线推进",
      "actual_mainline_advance": "正文实际完成的推进",
      "status": "aligned|deviated|unverified",
      "issue": "无偏差时为空字符串"
    }
  ],
  "narrative_pressure": {
    "adversity_payoff_level": "core|support|off",
    "pressure_lines": [
      {
        "source": "string",
        "rational_motive": "string",
        "current_stakes": "string",
        "status": "active|resolved"
      }
    ],
    "emotional_debts": [
      {
        "event": "string",
        "owed_by": "string",
        "owed_to": "string",
        "expected_payoff": "string",
        "status": "open|partially_paid|paid"
      }
    ],
    "reversal_assets": [
      {
        "asset": "string",
        "source_episode": 1,
        "planned_use": "string",
        "status": "planted|developed|paid_off"
      }
    ]
  }
}
```

`continuity_bridge.from_action` 与 `to_action` 必须分别摘录上一集结尾和本集开头中真实存在的
简短动作或结果，不得写“承接上一集”“继续处理”等无法回查正文的概括。
`plan_alignment` 必须覆盖本次全部集数；发现正文改变主角目标、本集主线推进、结尾状态或
下一集承接时标记 `deviated`，如实写明偏差，不得替正文圆场。仅代码降级提取无法判断语义时
允许标记 `unverified`，模型状态记录器不得用它逃避比对。

数组没有事实时使用空数组。未知事实用明确字符串“未明确”，不得猜测。
`continuity_bridge` 仅第一集允许为 `null`；其他集必须填写上一集动作和本集承接动作。
当创作合同将 `adversity_payoff` 设为 `off` 时，`narrative_pressure` 的三个数组使用空数组；
设为 `core` 或 `support` 时，只记录上游和正文已经存在的压力、情绪债和翻盘资产。
