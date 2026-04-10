# FastGPT 混合工作流契约

本项目当前采用“本地逻辑 + FastGPT 工作流 API”的混合架构：

- 本地负责：暂停/继续/终止、批次划分、分集计划裁剪、批次 +5、JSON 拼接、正文拼接、`last_summary` 覆盖、用户缓存与保存。
- FastGPT 负责：当前阶段/当前批次内部的内容生成、内容审核、修订整理，并只把成品输出给 Python。
- 代码内部统一使用本文列出的英文变量名；当 `FASTGPT_VARIABLE_MODE=legacy` 时，会在请求前映射为你最新 FastGPT JSON 中的变量 ID。

## 配置位置

真实 Key 不要写进代码。复制 `workflow_code_skeleton/.env.example` 为 `workflow_code_skeleton/.env` 后填写：

- `FASTGPT_CHAT_COMPLETIONS_URL`：完整 FastGPT 接口地址，例如 `http://47.93.31.133:18080/api/v1/chat/completions`。代码不会再自动拼接 `/api/v1/chat/completions`。
- `FASTGPT_API_KEY`：所有阶段共用的 FastGPT 应用 Key。
- `FASTGPT_CONSISTENCY_API_KEY`：集数一致性检查阶段独立 Key，可选。
- `FASTGPT_WORLDVIEW_API_KEY`：世界观阶段独立 Key，可选。
- `FASTGPT_CHARACTERS_API_KEY`：人设阶段独立 Key，可选。
- `FASTGPT_SCENES_API_KEY`：核心场景阶段独立 Key，可选。
- `FASTGPT_HOOKS_API_KEY`：开头冲突钩子阶段独立 Key，可选。
- `FASTGPT_DIALOGUES_API_KEY`：角色对话阶段独立 Key，可选。
- `FASTGPT_SCRIPT_API_KEY`：剧本正文阶段独立 Key，可选。
- `FASTGPT_MEMORY_API_KEY`：正文记忆整理阶段独立 Key，可选。
- `FASTGPT_FINAL_API_KEY`：最终剧本拼接阶段独立 Key，可选。

如某个阶段未配置独立 Key，代码会回退使用 `FASTGPT_API_KEY`。缺少 Key 时，后端只提示缺少哪个变量，不会打印任何密钥内容。请求失败时日志会打印最终请求 URL、状态码、`response.text` 和脱敏后的 payload 摘要，用于判断 URL、Key、请求体或远端上游模型问题。

当前你保留的 9 个 JSON 使用的是 FastGPT 变量 ID，例如 `blkSS7dY`、`pxtQY7p2`、`yuozoGpo`。代码内部仍统一使用英文变量名，并通过 `FASTGPT_VARIABLE_MODE=legacy` 自动映射到这些 ID。如果你后续把 FastGPT 工作流变量也改成英文名，可以设置 `FASTGPT_VARIABLE_MODE=canonical`。

当前推荐配置为 `FASTGPT_BATCH_MODE=local`。`05/06/07` 应保持为“只处理当前 `episode_plan` 片段的一批智能体”：FastGPT 内部可以继续保留生成-审核-修订闭环，但不要再做总集数循环、开始集数 +5 或全量拼接。

## 全局变量

| 变量名 | 类型 | 说明 | 来源 |
| --- | --- | --- | --- |
| `script_title` | string | 剧本标题 | 用户输入 |
| `total_episodes` | number | 总集数 | 用户输入 |
| `episode_plan` | string | 分集计划。非批处理阶段传全文，批处理阶段传当前 5 集片段 | 用户输入/本地裁剪 |
| `story_outline` | string | 故事大纲 | 用户输入 |
| `user_scenes` | string | 核心场景 | 用户输入 |
| `user_characters` | string | 人物小传 | 用户输入 |
| `worldview` | string | 世界观内容 | FastGPT 输出 |
| `characters` | string | 人设内容 | FastGPT 输出 |
| `scenes` | string | 核心场景内容 | FastGPT 输出 |
| `batch_hooks` | object | 当前批次 5 集开头冲突钩子 JSON | FastGPT 输出 |
| `all_hooks` | object | 完整开头冲突钩子 JSON | 本地拼接 |
| `batch_dialogues` | object | 当前批次 5 集角色对话 JSON | FastGPT 输出 |
| `all_dialogues` | object | 完整角色对话 JSON | 本地拼接 |
| `batch_script` | string | 当前批次 5 集剧本正文 | FastGPT 输出 |
| `all_script` | string | 完整剧本正文 | 本地拼接 |
| `last_summary` | string | 最近一次剧本摘要，只保留最新 | FastGPT 输出/本地覆盖 |
| `final_script` | string | 最终完整剧本 | FastGPT 输出 |
| `batch_start_episode` | number | 当前批次起始集数，仅 legacy 变量映射时传给批处理智能体 | 本地批次控制 |

## 阶段契约

| 阶段 | FastGPT 输入 | FastGPT 输出 | 本地职责 |
| --- | --- | --- | --- |
| `consistency` 集数一致性检查 | `total_episodes`, `episode_plan` | `{ "is_consistent": boolean }` | 根据结果继续或停止 |
| `worldview` 世界观循环 | `story_outline`, `user_scenes`, `user_characters`, `episode_plan` | `{ "worldview": string }` | 控制重试，校验输出字段 |
| `characters` 人设循环 | `user_characters`, `worldview` | `{ "characters": string }` | 控制重试，校验输出字段 |
| `scenes` 核心场景循环 | `user_scenes`, `worldview` | `{ "scenes": string }` | 控制重试，校验输出字段 |
| `hooks` 开头冲突钩子批处理 | `worldview`, `characters`, `episode_plan`, `total_episodes`, `last_summary`, `batch_start_episode` | `{ "batch_hooks": object }` | 按 5 集划分，拼接 `all_hooks` |
| `dialogues` 角色对话批处理 | `characters`, `episode_plan`, `total_episodes`, `last_summary`, `batch_start_episode` | `{ "batch_dialogues": object }` | 按 5 集划分，拼接 `all_dialogues` |
| `script` 剧本正文批处理 | `worldview`, `all_hooks`, `all_dialogues`, `episode_plan`, `total_episodes`, `last_summary`, `batch_start_episode` | `{ "batch_script": string }` | 按 5 集划分，拼接 `all_script` |
| `memory` 正文记忆整理 | `batch_script` | `{ "last_summary": string }` | 用新摘要覆盖旧摘要 |
| `final` 最终剧本拼接 | `script_title`, `total_episodes`, `story_outline`, `characters`, `scenes`, `all_script` | `{ "final_script": string }` | 接收并保存最终文本 |

## 批次说明

FastGPT 不接收 `batch_index`、`end_episode` 等本地计数器。为了让 FastGPT 知道当前要处理哪 5 集，本地会把用户的 `episode_plan` 按“第 N 集 / Episode N / 1.”等标记裁剪成当前批次片段，再以同名变量 `episode_plan` 发送。

你这版 legacy 智能体仍在提示词里引用了当前批次起始集数，因此代码会额外发送 `batch_start_episode`，并映射为 `iJkq6iGe`、`sKq9Iyza`、`d4sfifeZ`。代码不会发送批次索引或结束集数，结束边界仍由当前 `episode_plan` 片段和 `total_episodes` 约束。

第 5-8 步在本地按批次串联执行：当前批次钩子 -> 当前批次对白 -> 当前批次正文 -> 当前批次记忆。记忆工作流只根据刚生成的 5 集输出新记忆；代码用新 `last_summary` 覆盖旧值。这样下一批次正文智能体只能看到最新一次 `last_summary`，不会看到历史摘要列表。

最终拼接阶段在 legacy 模式下会把 `characters` 发送到 `iDnZYjwW`，把 `scenes` 发送到 `ibpp7JZ8`，把完整正文 `all_script` 发送到 `vI8t3a31`，对应你当前最终拼接模板：

```text
《{{$VARIABLE_NODE_ID.n5ZHYrj8$}}》{{$VARIABLE_NODE_ID.blkSS7dY$}}完整剧本

故事梗概
{{$VARIABLE_NODE_ID.ayxWwSpE$}}

人物小传
{{$VARIABLE_NODE_ID.iDnZYjwW$}}

核心场景
{{$VARIABLE_NODE_ID.ibpp7JZ8$}}

剧本正文
{{$VARIABLE_NODE_ID.vI8t3a31$}}
```

默认 `FASTGPT_STAGE_RETRIES=0`，表示 Python 不做业务层反复调用；如果 FastGPT 返回格式错误或网络失败，HTTP 层仍会按 `FASTGPT_HTTP_RETRIES` 做短暂技术重试。旧的全量内部循环工作流只应作为临时兼容方案显式设置 `FASTGPT_BATCH_MODE=fastgpt_full` 使用。
