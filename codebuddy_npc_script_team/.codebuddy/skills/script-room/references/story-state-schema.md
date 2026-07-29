# story_state.json 契约

状态记录器只提取事实，不改写剧本。输出必须是单个合法 JSON 对象，不得使用 Markdown
代码围栏或附加解释。

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

数组没有事实时使用空数组。未知事实用明确字符串“未明确”，不得猜测。
`continuity_bridge` 仅第一集允许为 `null`；其他集必须填写上一集动作和本集承接动作。
当创作合同将 `adversity_payoff` 设为 `off` 时，`narrative_pressure` 的三个数组使用空数组；
设为 `core` 或 `support` 时，只记录上游和正文已经存在的压力、情绪债和翻盘资产。
