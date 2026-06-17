# FastGPT 混合工作流契约

这份文档只描述当前代码中的真实 FastGPT 契约与编排规则，来源以：

- `workflow_code_skeleton/app/services/fastgpt_contracts.py`
- `workflow_code_skeleton/app/services/fastgpt_client.py`
- `workflow_code_skeleton/app/services/workflow_output_validation.py`
- `workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py`

为准。

## 1. 架构边界

当前架构是“Python 本地编排 + FastGPT 阶段 workflow”：

- **Python 本地负责**
  - 输入准备
  - stage 顺序控制
  - hooks/dialogues/script 三段式批处理
  - review/rewrite 循环控制
  - 输出契约校验
  - 格式重试
  - 失败恢复 / 回退重写 / 快照同步
  - partial script 展示
  - 最终导出

- **FastGPT 负责**
  - 当前阶段或当前批次的内容生成
  - 审核
  - 修订
  - 自然语言整理
  - answerNode / 变量更新输出

## 2. 当前主阶段与 workflow 映射

### 直接对应 FastGPT workflow 的阶段

| stage | workflow JSON | 正式输出 |
| --- | --- | --- |
| `framework` | `剧本框架撰写.json` | `script_title_content`, `story_outline`, `user_characters`, `user_scenes`, `episode_plan` |
| `framework_naturalize` | `自然语言化.json` | `framework_natural_language` |
| `appearance_pre_strategy` | `服装前置策略生成器.json` | `character_appearance_requirements`, `character_alias_naming_rules`, `outfit_switch_rules` |
| `consistency` | `集数一致性检查.json` | `is_consistent` |
| `episode_plan_normalize` | `分集计划规范化.json` | `normalized_episode_plan` |
| `worldview` | `世界观生成.json` | `worldview` |
| `worldview_naturalize` | `自然语言化.json` | `worldview_natural_language` |
| `characters_naturalize` | `自然语言化.json` | `dT7mQ2Nz` / `character_natural_language` |
| `characters` | `人设生成.json` | `characters` |
| `scenes` | `场景生成.json` | `scenes` |
| `appearance_alias_writing` | `服装版本映射编写.json` | `appearanceMapping` |
| `appearance_alias_review` | `服装版本映射审核.json` | `passed`, `rewrite_required`, `blocking_issues` |
| `appearance_alias_rewrite` | `服装版本映射修订.json` | `appearanceMapping` |
| `appearance_alias_unstructured` | `自然语言服装版本映射.json` | `c7VnQ4eX` |
| `framework_scene_dictionary` | `08_提炼核心场景.json` | `sceneDictionary`, `scriptWorldRulesDigest` |
| `framework_appearanceMapping` | `09_人设服装alias映射.json` | `appearanceMapping` |
| `framework_enriched_episode_plan` | `10_丰富分集计划.json` | `enrichedEpisodePlanResult`; 后端解析 `allEnrichedEpisodePlan`, `allEnrichedEpisodePlanText` |
| `framework_causal_conflict_write` | `框架转剧本因果冲突推进计划编写.json` | `batchCausalConflictPlan` |
| `framework_causal_conflict_review` | `框架转剧本因果冲突推进计划审核.json` | `passed`, `rewrite_required`, `blocking_issues` |
| `framework_causal_conflict_rewrite` | `框架转剧本因果冲突推进计划修订.json` | `batchCausalConflictPlan` |
| `framework_causal_conflict_memory` | `框架转剧本因果冲突记忆存储.json` | `conflictMemory` |
| `framework_script_write` | `框架转剧本正文对白融合编写.json` | `batchScriptText` |
| `framework_script_review` | `框架转剧本正文对白融合审核.json` | `passed`, `rewrite_required`, `blocking_issues` |
| `framework_script_rewrite` | `框架转剧本正文对白融合修订.json` | `batchScriptText` |
| `framework_script_memory` | `框架转剧本正文记忆存储.json` | `scriptMemory` |
| `hooks_writing` / `hook_write` | `开头冲突钩子编写.json` | `batch_hooks` |
| `hooks_review` / `hook_review` | `开头冲突钩子审核.json` | `passed`, `rewrite_required`, `blocking_issues` |
| `hooks_rewrite` / `hook_revise` | `开头冲突钩子修订.json` | `batch_hooks` |
| `hook_memory` | `开头冲突钩子记忆存储.json` | `hook_memory` |
| `dialogues_writing` / `dialogue_write` | `角色对话编写.json` | `batch_dialogues` |
| `dialogues_review` / `dialogue_review` | `角色对话审核.json` | `passed`, `rewrite_required`, `blocking_issues` |
| `dialogues_rewrite` / `dialogue_revise` | `角色对话修订.json` | `batch_dialogues` |
| `dialogue_memory` | `角色对话记忆存储.json` | `dialogue_memory` |
| `script_writing` / `script_write` | `剧本正文编写.json` | `batch_script` |
| `script_review` | `剧本正文审核.json` | `passed`, `rewrite_required`, `blocking_issues` |
| `script_rewrite` / `script_revise` | `剧本正文修订.json` | `batch_script` |
| `script_memory` | `当前五集剧本正文摘要.json` | `last_summary` |
| `memory` | `当前五集剧本正文摘要.json` | `last_summary` |
| `final` | `完整剧本拼接.json` | `final_script` |

### Python 逻辑阶段

这些 stage 主要是本地编排概念，不是单个 workflow：

| stage | 说明 |
| --- | --- |
| `appearance_alias_generation` | 逻辑阶段名，由 Python 串联 `writing -> review -> rewrite -> unstructured` |
| `hooks` | 当前批 hooks 逻辑阶段名，实际落到 `hooks_writing/review/rewrite` |
| `dialogues` | 当前批 dialogues 逻辑阶段名，实际落到 `dialogues_writing/review/rewrite` |
| `script` | 当前批 script 逻辑阶段名，实际落到 `script_writing/review/rewrite/script_memory` |

### 三幕十五节拍框架转剧本专用链路

`script_format_mode` 为 `framework_to_script` 或 `better_framework_script` 时，Python 会进入独立的新链路：

`07 framework_plan_package -> 08 sceneDictionary -> 09 appearanceMapping -> 10 enrichedEpisodePlan -> 因果冲突推进计划 -> 正文对白融合生成 -> final`

这条链路只服务“三幕十五节拍框架输出后的框架到剧本生成”，不会进入旧的 `all_hooks -> all_dialogues -> all_script` 三段式，也不会调用 `dialogue_write / dialogue_review / dialogue_rewrite / dialogue_memory`。旧普通新建剧本链路仍保留 `all_hooks / all_dialogues / all_script`。

08、09、10 是框架转剧本内部阶段 / 下游资产化阶段，不是框架策划工作台的手动阶段。用户在 07 最终策划包确认后点击“用当前框架生成剧本”，后端自动执行 08、09、10、因果冲突推进计划和正文对白融合。正文和对白已经在新链路中融合生成，角色对话工作流不再用于 `framework_to_script`。

#### framework_to_script 变量契约

| 环节 | 输入变量 | 输出变量 |
| --- | --- | --- |
| 08 提炼核心场景 | `frameworkPlanPackage`, `worldviewPlan`, `beatCheckpointTimeline`, `characterStorylines` | `sceneDictionary`, `scriptWorldRulesDigest` |
| 09 人设服装 alias 映射 | `frameworkPlanPackage`, `characterPlan`, `sceneDictionary`, `beatCheckpointTimeline` | `appearanceMapping` |
| 10 丰富分集计划 | `frameworkPlanPackage`, `beatCheckpointTimeline`, `characterStorylines`, `sceneDictionary`, `appearanceMapping` | `enrichedEpisodePlanResult` |
| 10 后端解析 | `enrichedEpisodePlanResult` | `allEnrichedEpisodePlan`, `allEnrichedEpisodePlanText` |
| 因果冲突推进计划 | `totalEpisodes`, `conflictStartEpisode`, `batchEnrichedEpisodePlan`, `sceneDictionary`, `scriptWorldRulesDigest`, `appearanceMapping`, `conflictMemory` | `batchCausalConflictPlan`, `batchCausalConflictReview`, `conflictMemory` |
| 正文对白融合 | `totalEpisodes`, `scriptStartEpisode`, `episodeWordCount`, `batchCausalConflictPlan`, `batchEnrichedEpisodePlan`, `scriptWorldRulesDigest`, `appearanceMapping`, `scriptMemory` | `batchScriptText`, `batchScriptReview`, `scriptMemory` |

注意：

- `batchEnrichedEpisodePlan` 由后端从 `allEnrichedEpisodePlan` 按当前批次切片得到，因果冲突阶段只消费当前批次，不消费完整 `frameworkPlanPackage`。
- `framework_to_script` 不允许回退到旧 `all_hooks / all_dialogues / all_script`，也不允许缺少新链路专用 key 时回退到全局 `FASTGPT_API_KEY`。
- 10 阶段工作流可以把完整 JSON 包在 `enrichedEpisodePlanResult` 或 `answerText` 中；后端会解析顶层 `allEnrichedEpisodePlan` 与 `allEnrichedEpisodePlanText`。

## 3. 当前关键变量语义

### 正式结构化变量

| canonical 名 | 说明 |
| --- | --- |
| `story_outline` | 结构化故事大纲 object |
| `user_characters` | framework 产出的结构化原始人物设定 array |
| `user_scenes` | framework 产出的结构化原始核心场景 object |
| `episode_plan` | framework 产出的原始分集计划 array |
| `normalized_episode_plan` | 规范化后的分集计划 object |
| `worldview` | 世界观 JSON string |
| `characters` | 人设 JSON string |
| `scenes` | 场景业务 JSON string |
| `appearanceMapping` | 正式结构化服装映射 object |
| `batch_hooks` / `all_hooks` | 当前批 / 全量 hooks |
| `batch_dialogues` / `all_dialogues` | 当前批 / 全量 dialogues |
| `batch_script` / `all_script` | 当前批 / 全量 script |
| `last_summary` | 当前滚动 script memory |
| `final_script` | 最终完整剧本 |
| `framework_plan_package` | 三幕十五节拍第 07 阶段输出策划包，新链路起点 |
| `sceneDictionary` | 新链路 08 场景字典 |
| `scriptWorldRulesDigest` | 新链路正文世界规则摘要 |
| `appearanceMapping` | 新链路 09 外观映射；旧链路兼容 `appearanceMapping` |
| `allEnrichedEpisodePlan` / `batchEnrichedEpisodePlan` | 新链路 10 全量 / 当前批增强分集计划 |
| `conflictStartEpisode` | 新链路因果冲突批次起始集 |
| `batchCausalConflictPlan` / `batchCausalConflictReview` | 新链路当前批因果冲突推进计划 / 审核结果 |
| `conflictMemory` | 新链路因果冲突滚动记忆 |
| `scriptStartEpisode` | 新链路正文批次起始集 |
| `episodeWordCount` | 新链路每集正文字数 |
| `batchScriptText` / `batchScriptReview` | 新链路当前批正文对白融合稿 / 审核结果 |
| `scriptMemory` | 新链路正文滚动记忆，不复用旧 `last_summary` |

### 辅助自然语言变量

| 变量 | 说明 |
| --- | --- |
| `framework_natural_language` | 框架自然语言版 |
| `worldview_natural_language` | 世界观自然语言版 |
| `dT7mQ2Nz` | 人物小传自然语言版 |
| `n8PqLs4V` | 场景自然语言版 |
| `c7VnQ4eX` | 服装映射自然语言说明 |

### 自然语言化 workflow 固定变量

当前 `自然语言化.json` workflow 使用下面三个稳定变量：

| workflow 变量 | 说明 |
| --- | --- |
| `w2RJzalk` | 需要去结构化 / 自然语言化的输入内容 |
| `unstructuredContentKind` | 自然语言化类型，只支持 `framework` / `worldview` / `generic` |
| `zxlaPMOY` | 自然语言化后的正式输出，后端应优先从该变量读取 |

规则：

- 辅助自然语言变量只能用于展示或辅助输入。
- 不能覆盖正式结构化变量。
- 普通用户前端当前只公开 `framework_natural_language`、`worldview_natural_language` 和 script/final。

## 4. FastGPT 输出抽取顺序

当前 `FastGPTClient` 对所有 stage 的正式输出抽取顺序是：

1. `newVariables`
2. `updateVarResult`
3. `responseData.variableUpdate`
4. `textOutput`
5. `answerText`
6. `choices[0].message.content`
7. answerNode 最终回复包装

补充规则：

- 支持 markdown code fence、JSON string、二次嵌套 JSON string
- `choices.message.content` 为数组时，只提取 `type=text`
- 如果内容是“思考过程 + JSON”，会优先取最后一个合法 JSON object
- `reasoningText / reasoning / 思考过程` 不算正式输出

## 5. 当前校验与重试规则

### HTTP / timeout 重试

- 配置项：`FASTGPT_HTTP_RETRIES`
- 只处理网络异常、timeout、`429/500/502/503/504`

### 输出格式重试

- 配置项：`FASTGPT_STAGE_FORMAT_RETRY_LIMIT`
- 默认：`3`

语义：

- HTTP 成功，但输出仍不可消费时，当前 stage 最多重新调用 3 次
- 不会把坏输出写入正式 `variables/artifacts`
- 坏输出只会写入 debug artifact

### review / rewrite 循环上限

- 配置项：`FASTGPT_STAGE_REVIEW_REVISE_MAX_LOOPS`
- 默认：`10`

适用：

- appearance review/rewrite
- hooks review/rewrite
- dialogues review/rewrite
- script review/rewrite

规则：

- 审核 JSON 无法解析，也计入一次失败轮次
- 审核通过后停止修订
- 达到上限后抛可恢复失败，不能死循环

## 6. payload 限制

当前 payload 限制只做统计和阻断，不会改正式变量：

- `FASTGPT_STAGE_PAYLOAD_WARN_CHARS`
- `FASTGPT_STAGE_PAYLOAD_HARD_CHARS`
- `FASTGPT_SCRIPT_PAYLOAD_SOFT_LIMIT`
- `FASTGPT_SCRIPT_PAYLOAD_HARD_LIMIT`

规则：

- warn：只打日志
- hard：抛可恢复失败
- 日志只记录长度统计和字段摘要，不打印完整大变量正文

## 7. scenes / characters / appearance 兼容规则

### characters

- 正式输出必须进入 `characters`
- 自然语言人物小传会额外同步：
  - `dT7mQ2Nz`
  - `character_natural_language`
  - `character_summary`
- `w2RJzalk` 的人物自然语言化输入优先来自 `characters / fFM0mroW`；如果结构化人设缺失，才回退到 `user_characters / yYYOuumm`
- `unstructuredContentKind` 对人物自然语言化固定传 `generic`，因为当前 workflow 只支持 `framework / worldview / generic`
- `zxlaPMOY` 为空时，契约层会再用 `answerText` 兜底
- 自然语言结果不能覆盖正式结构化 `fFM0mroW / characters`

人物小传最终导出字段优先级：

导出读取顺序要求：character_natural_language / dT7mQ2Nz 优先。
导出兜底要求：fFM0mroW / character_setting.characters 兜底。

1. `character_natural_language / dT7mQ2Nz` 优先
2. `character_summary` 兼容旧快照
3. `fFM0mroW / character_setting.characters` 兜底生成可读自然语言人物小传
4. 不允许导出 `【待补全：补充人物定位】`、原始 JSON、字面量变量名

### scenes

Python 最终仍保持：

- `variables["scenes"]` 类型是 string

当前兼容输入：

- `{"scenes":{"scene_setting":{...}}}`
- `{"scene_setting":{...}}`
- `{"scenes":"<json string>"}`
- `{"iJudZHhM":"<json string>"}`

最低业务校验：

- 解析后必须能得到 `scene_setting`
- `scene_setting["scenes"]` 必须是 list

污染防护：

- 不能把 `id/model/usage/choices/message/content/role` 响应壳字段当成业务输出
- 不能把审核说明、自然语言说明、toolCall 文本直接当成正式 `scenes`

### appearance

appearance 正式结构化来源白名单顺序：

1. `newVariables.h2KpLm91`
2. `updateVarResult.h2KpLm91`
3. `responseData.variableUpdate.h2KpLm91`
4. answerNode 输出里的 `h2KpLm91` 或顶层 `appearanceMapping`
5. `choices.message.content` 中可解析且顶层带 `appearanceMapping` 的 JSON object

仍然拒绝：

- 空 `h2KpLm91`
- 空 `appearanceMapping`
- `c7VnQ4eX`
- `fuKbtNtY`
- `scene_setting`
- `核心场景：...`
- `appearanceMapping` 为 string
- 把纯文本包装成 `{"appearanceMapping":"..."}` 的伪修复

## 8. 当前 detail 与自然语言 stage 规则

自然语言阶段：

- `framework_naturalize`
- `worldview_naturalize`
- `appearance_alias_unstructured`

它们当前主要走：

- `FASTGPT_UNSTRUCTURED_API_KEY`
- `FASTGPT_<STAGE>_TIMEOUT` 或全局 `FASTGPT_TIMEOUT`

同时代码不能依赖 `detail=true` 才拿到正式输出；即使 `detail=false`，也应优先从 `choices.message.content / answerNode` 取正式结果。

## 9. 当前 public/private 展示边界

### public

普通用户公开字段当前只包括：

- `framework_natural_language`
- `worldview_natural_language`
- `partial_script`
- `script_batches_display`
- `script_batch_preview`
- `script_batch_range`
- `partial_script_episodes`
- `final_script`
- `final_output_text`

### private / debug

仍保留：

- `character_natural_language`
- `scene_natural_language`
- `appearanceMapping`
- `character_registry`
- `character_alias_registry`
- `episode_alias_plan`
- rollback / batch checkpoint / committed script / summary caches

## 10. 当前 stage 级环境变量规则

所有 stage 都支持：

- `FASTGPT_<STAGE>_API_KEY`
- `FASTGPT_<STAGE>_CHAT_COMPLETIONS_URL`
- `FASTGPT_<STAGE>_TIMEOUT`

解析优先级：

1. 当前 stage 的显式变量
2. `fastgpt_client.py` 中定义的 alias 变量
3. 全局 `FASTGPT_API_KEY / FASTGPT_CHAT_COMPLETIONS_URL / FASTGPT_TIMEOUT`

常用专用 key：

- `FASTGPT_UNSTRUCTURED_API_KEY`
- `FASTGPT_APPEARANCE_ALIAS_WRITING_API_KEY`
- `FASTGPT_APPEARANCE_ALIAS_REVIEW_API_KEY`
- `FASTGPT_APPEARANCE_ALIAS_REWRITE_API_KEY`
- `FASTGPT_APPEARANCE_ALIAS_UNSTRUCTURED_API_KEY`
- `FASTGPT_HOOKS_WRITING_API_KEY`
- `FASTGPT_HOOKS_REVIEW_API_KEY`
- `FASTGPT_HOOKS_REWRITE_API_KEY`
- `FASTGPT_HOOKS_MEMORY_API_KEY`
- `FASTGPT_DIALOGUES_WRITING_API_KEY`
- `FASTGPT_DIALOGUES_REVIEW_API_KEY`
- `FASTGPT_DIALOGUES_REWRITE_API_KEY`
- `FASTGPT_DIALOGUES_MEMORY_API_KEY`
- `FASTGPT_SCRIPT_WRITING_API_KEY`
- `FASTGPT_SCRIPT_REVIEW_API_KEY`
- `FASTGPT_SCRIPT_REWRITE_API_KEY`
- `FASTGPT_SCRIPT_MEMORY_API_KEY`
- `FASTGPT_FINAL_API_KEY`

三幕十五节拍框架转剧本专用链路必须独立配置下面的 key。缺少任意一个当前阶段 key 时，代码会明确报出缺少的变量名，并拒绝回退到旧 `all_hooks / all_dialogues / dialogues / FASTGPT_API_KEY`：

- `FASTGPT_FRAMEWORK_SCENE_DICTIONARY_API_KEY`
- `FASTGPT_FRAMEWORK_APPEARANCE_MAPPING_API_KEY`
- `FASTGPT_FRAMEWORK_ENRICHED_EPISODE_PLAN_API_KEY`
- `FASTGPT_FRAMEWORK_CAUSAL_CONFLICT_WRITE_API_KEY`
- `FASTGPT_FRAMEWORK_CAUSAL_CONFLICT_REVIEW_API_KEY`
- `FASTGPT_FRAMEWORK_CAUSAL_CONFLICT_REWRITE_API_KEY`
- `FASTGPT_FRAMEWORK_CAUSAL_CONFLICT_MEMORY_API_KEY`
- `FASTGPT_FRAMEWORK_SCRIPT_WRITE_API_KEY`
- `FASTGPT_FRAMEWORK_SCRIPT_REVIEW_API_KEY`
- `FASTGPT_FRAMEWORK_SCRIPT_REWRITE_API_KEY`
- `FASTGPT_FRAMEWORK_SCRIPT_MEMORY_API_KEY`

辅助工具另用：

- `FASTGPT_HOT_REVIEW_API_KEY`
- `FASTGPT_RESKIN_API_KEY`
- `FASTGPT_PUNCHUP_API_KEY`
- `FASTGPT_CHARACTER_RESKIN_API_KEY`

## 11. 当前最重要的实现约束

- 不修改 workflow JSON 契约时，代码侧必须兼容 answerNode / choices 输出。
- `compact context` 只能用于发给下游 FastGPT 的请求，不能覆盖正式变量。
- hooks/dialogues/script 只使用当前批切片，不允许把全量变量误传成当前五集输入。
- partial script 展示必须发生在 script 当前批审核通过且本地校验通过之后、`script_memory` 之前。
- rollback 时必须同步清理 `partial_script / script_batches_display / script_batch_preview` 等展示缓存。
- DOCX 导出必须兼容旧项目结构，不要求重新生成。
