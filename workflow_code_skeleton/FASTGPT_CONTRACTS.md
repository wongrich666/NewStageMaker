# FastGPT 混合工作流契约

本项目当前采用“本地逻辑 + FastGPT 工作流 API”的混合架构：

- 本地负责：循环控制、暂停/继续/终止、批次划分、分集计划裁剪、JSON 拼接、正文拼接、`last_summary` 覆盖、用户缓存与保存。
- FastGPT 负责：内容生成、内容审核、修订整理、最终文本输出。
- 传给 FastGPT 的变量名只使用本文列出的英文变量名，不传本地计数器、批次索引或内部节点 ID。

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

当前你保留的 9 个 JSON 使用的是 FastGPT 旧变量 ID，例如 `blkSS7dY`、`pxtQY7p2`、`yuozoGpo`。代码内部仍统一使用英文变量名，并通过 `FASTGPT_VARIABLE_MODE=legacy` 自动映射到这些旧 ID。如果你后续把 FastGPT 工作流变量也改成英文名，可以设置 `FASTGPT_VARIABLE_MODE=canonical`。

`05/06/07` 这三个 JSON 当前是“全量内部循环版”，会在 FastGPT 内部自己循环所有集数。`FASTGPT_BATCH_MODE=auto` 在 legacy 模式下会兼容这种全量调用。如果要实现真正本地每 5 集暂停/继续，请把 FastGPT 里的 `05/06/07` 改成“只处理当前 `episode_plan` 片段的一批工作流”，然后设置 `FASTGPT_BATCH_MODE=local`。

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

## 阶段契约

| 阶段 | FastGPT 输入 | FastGPT 输出 | 本地职责 |
| --- | --- | --- | --- |
| `consistency` 集数一致性检查 | `total_episodes`, `episode_plan` | `{ "is_consistent": boolean }` | 根据结果继续或停止 |
| `worldview` 世界观循环 | `story_outline`, `user_scenes`, `user_characters`, `episode_plan` | `{ "worldview": string }` | 控制重试，校验输出字段 |
| `characters` 人设循环 | `user_characters`, `worldview` | `{ "characters": string }` | 控制重试，校验输出字段 |
| `scenes` 核心场景循环 | `user_scenes`, `worldview` | `{ "scenes": string }` | 控制重试，校验输出字段 |
| `hooks` 开头冲突钩子批处理 | `worldview`, `characters`, `episode_plan`, `total_episodes`, `last_summary` | `{ "batch_hooks": object }` | 按 5 集划分，拼接 `all_hooks` |
| `dialogues` 角色对话批处理 | `characters`, `episode_plan`, `total_episodes`, `last_summary` | `{ "batch_dialogues": object }` | 按 5 集划分，拼接 `all_dialogues` |
| `script` 剧本正文批处理 | `worldview`, `all_hooks`, `all_dialogues`, `episode_plan`, `total_episodes`, `last_summary` | `{ "batch_script": string }` | 按 5 集划分，拼接 `all_script` |
| `memory` 正文记忆整理 | `batch_script` | `{ "last_summary": string }` | 用新摘要覆盖旧摘要 |
| `final` 最终剧本拼接 | `script_title`, `total_episodes`, `story_outline`, `characters`, `scenes`, `all_script` | `{ "final_script": string }` | 接收并保存最终文本 |

## 批次说明

FastGPT 不接收 `batch_index`、`start_episode`、`end_episode` 等本地计数器。为了让 FastGPT 知道当前要处理哪 5 集，本地会把用户的 `episode_plan` 按“第 N 集 / Episode N / 1.”等标记裁剪成当前批次片段，再以同名变量 `episode_plan` 发送。

第 5-8 步在本地按批次串联执行：当前批次钩子 -> 当前批次对白 -> 当前批次正文 -> 当前批次记忆。这样下一批次的 FastGPT 调用只能看到最新一次 `last_summary`，不会看到历史摘要列表。

如果使用 `FASTGPT_BATCH_MODE=auto` 且 `FASTGPT_VARIABLE_MODE=legacy`，系统会切到兼容模式：`05` 全量钩子、`06` 全量对白、`07` 全量正文各调用一次，只能在这些大阶段之间暂停，不能在 FastGPT 内部循环中暂停。
