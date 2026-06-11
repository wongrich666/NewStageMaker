# CODER README

这份文档只描述当前代码真实行为，作为工程师排障与维护地图使用。

## 1. 主链路总览

从网页点击“开始生成”到最终成品，当前默认链路是：

1. 前端 `app.js` 组装 payload，POST `/api/workflows/start`
2. Flask `server.py` 接口做鉴权、参数整理、创建任务
3. `TaskManager.start_task()` 创建项目快照并启动后台线程
4. `TaskManager._run_task()` 构建 `WorkflowInput / WorkflowRuntime`
5. `run_configured_workflow()` 进入 `run_fastgpt_hybrid_workflow()`
6. Python 本地按阶段编排，逐个调用 `FastGPTClient.run_stage()`
7. 阶段输出先过本地契约、repair、workflow output validation
8. `WorkflowRuntime.sync_from_state()` 把正式结果同步进 snapshot
9. 前端轮询项目快照并按当前公开规则渲染

一句话理解：

- 前端负责交互、轮询、渲染
- `server.py` 负责 Web/API 与登录拦截
- `task_manager.py` 负责线程、快照、暂停恢复、回退、导出
- `fastgpt_hybrid_workflow.py` 负责本地编排
- `fastgpt_client.py` 负责 FastGPT HTTP 调用与输出抽取
- `fastgpt_contracts.py` 负责阶段输入/输出契约

## 2. 当前阶段模型

### 固定主顺序

当前主链路阶段顺序：

1. `framework`
2. `framework_naturalize`
3. `appearance_pre_strategy`
4. `consistency`
5. `episode_plan_normalize`
6. `worldview`
7. `worldview_naturalize`
8. `characters`
9. `scenes`
10. `appearance_alias_generation`
11. `all_hooks`
12. `all_dialogues`
13. `all_script`
14. `final`

### 批处理正文链

正文生产固定是三段式：

```text
all_hooks -> all_dialogues -> all_script
```

每批默认 5 集：

- hooks 当前批通过后才进入 dialogues
- dialogues 全批通过后才进入 script
- script 当前批通过 `script_review` 且本地正文校验通过后，会先进入用户可见的 partial script 展示，再进入 `script_memory`

### appearance 四阶段

`appearance_alias_generation` 只是逻辑阶段名，实际由 Python 编排：

1. `appearance_alias_writing`
2. `appearance_alias_review`
3. `appearance_alias_rewrite`
4. `appearance_alias_unstructured`

正式结构化结果始终是 `appearanceMapping / h2KpLm91`；自然语言说明 `c7VnQ4eX` 只用于展示，不能覆盖正式映射。

## 3. 当前用户可见层与私有层

### 普通用户前端

普通用户当前只展示：

- `framework_natural_language`
- `worldview_natural_language`
- `partial_script / script_batches_display / script_batch_preview`
- `final_script / final_output_text`

不会直接展示：

- `characters`
- `scenes`
- `appearanceMapping`
- debug_state
- FastGPT 原始响应壳字段

### 后端 public/private artifacts

`task_manager.py` 当前分层是：

- `PUBLIC_ARTIFACT_KEYS`
  - `script_title_content`
  - `framework_natural_language`
  - `worldview_natural_language`
  - `partial_script`
  - `script_batches_display`
  - `script_batch_preview`
  - `script_batch_range`
  - `partial_script_episodes`
- `PUBLIC_COMPLETED_ARTIFACT_KEYS`
  - `final_script`
  - `final_output_text`
- `COMPLETED_ARTIFACT_KEYS`
  - 包括 `story_outline`、`normalized_episode_plan`
  - 包括 `character_natural_language / character_summary`
  - 包括 `scene_natural_language / core_scene_summary`
  - 包括 `appearanceMapping / character_registry / character_alias_registry / episode_alias_plan`

要点：

- `characters / scenes / appearance` 的结构化与自然语言数据仍保存在 `variables / debug_state / private artifacts` 里供流程继续使用。
- 普通用户页面不会再把这些字段直接当阶段输出渲染。

## 4. FastGPT 输出处理真实规则

### Framework-to-script 08-12 chain

框架生成与框架转剧本是两个独立但可衔接的工作区。01-07 完成并确认 07 后，框架生成页必须保存“框架资产”；用户可以一键进入 `/framework-to-script?framework_asset_id=...`，也可以直接打开框架转剧本页并从已有框架资产导入。08+ 接口支持 `framework_asset_id`，后端会读取资产并注入 `framework_plan_package` 与 01-07 阶段输出，前端不要求用户复制 JSON。

框架资产的前端可见字段至少包括 `asset_id / project_id / title / source_title / framework_plan_package / stage_outputs / target_format / episodes_per_season / minutes_per_episode / season_count / created_at / updated_at / summary`。普通 UI 统一叫“框架资产”“版本历史”“保存当前版本”“恢复到此版本”，不要出现 JSON/raw/cache/logs/debug，也不要透出 `responseData / choices / reasoningText / historyPreview / newVariables / updateVarResult / raw_stage_responses`。

- 08 `framework_scene_dictionary` 产出 `sceneDictionary / scriptWorldRulesDigest`。
- 09 `framework_appearanceMapping` 产出 `appearanceMapping`，兼容 `appearance_mapping`。
- 10 `framework_enriched_episode_plan` 产出 `allEnrichedEpisodePlan`。
- 11 `framework_causal_conflict_write/review/memory` 串行生成因果冲突计划。
- 12 `framework_script_write/review/memory` 串行生成正文，最终导出字段固定为 `final_script / final_output_text`。
- 运行时串行执行，代码上一次性串联；`.env`、`cache/`、`debug/`、`logs/` 不应提交。

### Framework planner stage preferences

- 智慧库偏好按阶段生效：`01=basic`、`02=worldview`、`03=character`、`04=beat`、`05=storylines`、`06=guide`、`07=package`。
- 默认标签允许用户编辑运行时标签实例，不修改 `BUILTIN_TAG_DEFINITIONS` 种子；删除默认标签等价于隐藏/禁用。
- 阶段调用优先读取 `user_knowledge_stage_prompts[stage_key]`，其次 `prompt_preferences.stage_prompts[stage_key]`，最后才用全局兼容字段。
- 前端应用标签会写入各阶段 `stage_prompts`；当前阶段文本框只修改当前阶段。
- 普通界面展示折叠树状业务结构和“版本历史”，不展示 JSON、FastGPT 原始壳字段、`cache/logs/debug` 工程词。

### 输出抽取顺序

当前 `FastGPTClient.run_stage()` 会按这个顺序抽取候选：

1. `newVariables`
2. `updateVarResult`
3. `responseData.variableUpdate`
4. `textOutput`
5. `answerText`
6. `choices[0].message.content`
7. answerNode 最终回复包装

支持：

- markdown code fence
- JSON string
- 二次嵌套 JSON string
- content array 中的 `type=text`
- “解释文本 + JSON” 时取最后一个合法 JSON object

`reasoningText / reasoning / 思考过程` 只进 debug，不算正式输出。

### 统一格式重试

当前所有 FastGPT stage 都适用统一格式重试：

- 配置项：`FASTGPT_STAGE_FORMAT_RETRY_LIMIT`
- 默认：`3`

含义：

- HTTP 成功，但输出不可消费时，当前 stage 最多重新调用 3 次
- HTTP/timeout 仍走独立的 transient retry，不消耗格式重试次数

会触发格式重试的情况包括：

- 缺契约字段
- answerNode / choices / answerText 没被正确解析
- JSON 截断
- 输出是自然语言解释而不是正式对象
- 本地结构校验失败
- workflow output validation 失败

失败 attempt 只写 debug artifact，不会污染正式 `variables/artifacts`。

### review / rewrite 循环

审核修订循环当前由 Python 控制，最大轮次：

- 配置项：`FASTGPT_STAGE_REVIEW_REVISE_MAX_LOOPS`
- 默认：`10`

适用阶段：

- appearance review / rewrite
- hooks review / rewrite
- dialogues review / rewrite
- script review / rewrite

规则：

- 每次 `review -> rewrite -> review` 后轮次 +1
- 审核 JSON 解析失败也计入一次失败轮次
- 达到上限后抛可恢复失败，不能死循环
- 审核通过后不得继续修订

## 5. scenes / characters / appearance 当前兼容事实

### characters

- 正式结构化输出：`fFM0mroW`
- 自然语言人物小传：`dT7mQ2Nz`
- 代码会同步 `dT7mQ2Nz -> character_natural_language / character_summary`
- 普通用户前端当前默认不展示人物阶段，但完成态 private artifacts 会保留这些字段

### scenes

- 正式结构化输出最终仍保存到 Python `variables["scenes"]`，类型是 string
- 当前兼容：
  - `{"scenes":{"scene_setting":{...}}}`
  - `{"scene_setting":{...}}`
  - `{"scenes":"<json string>"}`
  - `{"iJudZHhM":"<json string>"}`
- scenes 正式输出必须满足：`parsed["scenes"]["scene_setting"]["scenes"]` 或兼容等价结构最终是 list
- `n8PqLs4V` 只会同步到 `scene_natural_language / core_scene_summary`，不能覆盖正式结构化场景

### appearance

- `appearance_alias_generation` 已经切成 4 个独立 workflow
- 正式结构化输出是 `h2KpLm91 / appearanceMapping`
- 自然语言说明是 `c7VnQ4eX`
- `c7VnQ4eX` 只做展示，不得覆盖正式结构化结果

## 6. 工具链真实入口

### 后端

- `GET /api/tools`
- `POST /api/tools/<tool_id>/run`

代码位置：

- `workflow_code_skeleton/app/services/simple_fastgpt_tools.py`
- `workflow_code_skeleton/app/server.py`

已接入工具：

- `hot_review`
- `reskin`
- `punchup`
- `character_reskin`

工具 schema 来自 workflow JSON：

- `chatConfig.variables` 的 `type=input / numberInput` 作为用户输入字段
- `answerNode` / `choices.message.content` / `answerText` / updated variables 共同决定最终可见输出
- 未登录时接口直接返回登录错误，前端会跳登录或提示需要登录

## 7. 导出链路真实情况

导出入口：

- `POST /api/projects/<id>/save`
- `GET /api/projects/<id>/download`

关键代码：

- `task_manager.save_final_script()`
- `utils/txt_to_docx.py`

当前稳定能力：

- `txt`
- `docx`

不应再把 `zip/json` 当成当前稳定导出能力。

DOCX 导出器已兼容旧项目脏数据：

- `char` 可以是 `dict / str / None / 其他`
- `personality / traits / appearance / relationships / speech_profile / dramatic_value` 等字段都做了防御式归一化
- 正文可以是 `str / dict / list`
- 某个字段异常不会阻断整份文档导出

## 8. 维护时最常看的入口

### Web / API

- `workflow_code_skeleton/app/server.py`
- `workflow_code_skeleton/app/web/static/app.js`

### 主编排

- `workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py`

重点看：

- framework / worldview / characters / scenes / appearance 调度
- `_run_all_hook_batches`
- `_run_all_dialogue_batches`
- `_run_all_script_batches`
- `run_stage_with_contract_guard`
- partial script 更新点

### 阶段契约与 FastGPT 适配

- `workflow_code_skeleton/app/services/fastgpt_contracts.py`
- `workflow_code_skeleton/app/services/fastgpt_client.py`
- `workflow_code_skeleton/app/services/stage_output_repair.py`
- `workflow_code_skeleton/app/services/workflow_output_validation.py`

### 快照 / 恢复 / 回退 / 导出

- `workflow_code_skeleton/app/services/task_manager.py`
- `workflow_code_skeleton/app/utils/txt_to_docx.py`

## 9. 当前最有用的排障顺序

### 点击开始后没跑起来

1. 前端 `buildPayload()` 是否发出请求
2. `/api/workflows/start` 是否返回 `task_id / project_id`
3. `TaskManager.start_task()` 是否创建线程
4. `TaskManager._run_task()` 是否把状态切到 `running`

### 某个 stage 没结果

1. 看 `FastGPTClient.run_stage()` 的 debug info
2. 看 contract 是否命中正确字段
3. 看 `workflow_json_name` 对应的 output validation
4. 看是否触发了格式重试 / review-rewrite 上限 / payload hard limit

### 前端没显示结果

1. 看 `WorkflowRuntime.sync_from_state()` 是否已写 artifact
2. 看 `task_manager._public_snapshot()` 是否公开了该字段
3. 看 `app.js` 的 `visibleStageMessages()` 是否允许当前阶段展示

### 已有项目下载 DOCX 失败

1. 先看 `save_final_script()` 是否拿到最终正文
2. 再看 `txt_to_docx.py` 是否被旧结构字段卡住
3. 旧项目不需要重生成，导出器应该兜底兼容
