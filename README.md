# AI 剧本生成平台

这是一个“Python 本地编排 + FastGPT 工作流 API”的剧本生产工作台。

它不是一次性吐一段文本，而是把“用户需求 -> 剧本框架 -> 世界观 -> 三段式批处理正文 -> 最终成品 -> 导出”的整条链路做成可登录、可暂停、可恢复、可回退、可导出的网页平台。

## 当前真实能力

- 注册、登录、个人中心、资产管理
- 多用户并发、多任务并发、后台线程继续运行
- 失败后保留进度并继续生成
- 阶段回退重写与完成确认
- 主链路按 FastGPT workflow 逐阶段执行
- 框架转剧本工作台已支持 10/11/12：分集细化、开头冲突钩子、正文及对话。FastGPT JSON 型输出优先从 `answerText/textOutput` 里的 JSON 解析，`newVariables` 仅作为候选之一；正文纯文本阶段读取最终 AI 文本输出。
- 辅助工具动态接入：`/api/tools`、`/api/tools/<tool_id>/run`
- 稳定导出：`txt + docx`

说明：

- 当前实现不把 `zip/json` 作为稳定导出能力对外承诺。
- 普通用户前端当前只展示：
  - `framework_natural_language`
  - `worldview_natural_language`
  - 已通过审核的分批正文 / 最终正文
- `characters / scenes / appearance` 的结构化与自然语言结果仍保留在后端状态里给后续流程使用，但不会作为普通用户阶段卡片直接展示。

## 项目结构

```text
new_scriptmaker/
├─ main.py
├─ README.md
├─ CODER_README.md
├─ workflow_code_skeleton/
│  ├─ .env.example
│  ├─ FASTGPT_CONTRACTS.md
│  ├─ requirements.txt
│  ├─ runtime_data/
│  └─ app/
│     ├─ server.py
│     ├─ config.py
│     ├─ models/
│     ├─ orchestrators/
│     ├─ services/
│     ├─ utils/
│     └─ web/
└─ workflow_jsons/（仓库里保留历史目录名）
```

运行时数据主要保存在：

- 项目快照：`workflow_code_skeleton/runtime_data/projects/`
- 导出文件：`workflow_code_skeleton/runtime_data/exports/`
- 用户与登录数据：`workflow_code_skeleton/runtime_data/`

## 启动方式

安装依赖：

```bash
pip install -r workflow_code_skeleton/requirements.txt
```

复制环境变量模板：

```bash
copy workflow_code_skeleton\.env.example workflow_code_skeleton\.env
```

启动服务：

```bash
python main.py
```

默认访问地址：

```text
http://127.0.0.1:5000
```

## 网页端当前怎么用

### 智慧库标签阶段偏好

智慧库标签现在也是“阶段偏好包”。标签仍保存在现有智慧库数据里，不单独建立另一套偏好系统：

- 标签通用偏好继续保存在 `prompt_text`，用于兼容旧数据。
- 标签阶段偏好保存在同一个标签对象的 `stage_prompts` 字段，覆盖 01-07 框架阶段，并预留 08-12 框架转剧本阶段。
- 01-07 键名沿用 `basic / worldview / character / beat / storylines / guide / package`。
- 08-12 键名为 `scene / appearance / episode / conflict / script_text`。

在框架策划工作台的“智慧库 / 阶段偏好”里，每个标签旁边有 `✍️` 按钮。点击后可以编辑该标签下的阶段提示词，至少包括 01 原文提取、02 世界观、03 人设、04 节拍规划、05 人物故事线、06 改编指引、07 框架校验，同时保留 08 场景字典、09 角色外观映射、10 分集细化、11 开头冲突钩子、12 正文写作的输入结构。

新建标签仍使用原有智慧库新建入口；创建后会自动选中，之后点击标签旁的 `✍️` 即可补充 01-07 / 08-12 阶段偏好。已有旧标签没有 `stage_prompts` 时不会报错，阶段偏好显示为空，旧的一段式 `prompt_text` 会继续保留。

阶段运行时只注入当前阶段对应的标签偏好：例如运行 02 只读取选中标签的 `worldview`，运行 12 只读取 `script_text`。后端会把当前阶段偏好写入 FastGPT variables 的 `stagePreference / stage_preference / stage_preference_prompt / user_stage_preference_prompt`，并兼容追加到 `user_preferences / userPreferences / userRequirements / user_constraints`。日志会输出 `preference_source=智慧库标签`、`preference_stage_key`、`selected_tag_count`、`has_stage_preference`、`preference_length` 等字段，但不会打印完整偏好正文。

### framework-planner 01-07 手动阶段流

01-07 不再自动连跑。每个阶段运行前都会先显示“运行前确认区”：即将生成的阶段、已应用上游、当前阶段智慧库偏好状态，以及“编辑阶段偏好 ✍️ / 生成本阶段”按钮。偏好为空可以运行，但界面会明确显示“未设置该阶段偏好，将使用默认策略”。

阶段输出生成后只代表草稿。用户编辑主展示字段后，阶段会标记 `stageDraftDirty=true`，下一阶段生成、保存框架、进入剧本阶段都会被拦截，并提示先点击“应用修改”。点击“应用修改”后才会校验并写回真实阶段状态、`localStorage`、后端框架资产；此时 `stageCommitted=true`，下游 payload 才会读取这份已应用结果。

主展示不再默认展示完整复杂 JSON。01-07 使用中文白名单视图：

- 01：故事核心、关键人物、关键场景、关键事件、重要道具、核心冲突、改编风险。
- 02：世界观概述、核心规则、禁忌与代价、冲突压力、视觉与氛围、下游写作要求。
- 03：人物卡片，展示姓名 / 合法称呼、身份定位、人物目标、核心欲望、弱点 / 恐惧、人物关系、人物变化线、说话风格、下游注意事项。
- 04：节拍时间轴 / 表格化字段，包括节拍名、集数范围、剧情功能、关键事件、反转 / 钩子、下游分集约束。
- 05：按人物线展示起点状态、阶段目标、关键转折、关系变化、失败 / 代价、终点状态、与主线关系。
- 06：改编方向、原文保留内容、本次重点改变、风格要求、风险提醒、给后续写作的硬要求。
- 07：框架完成状态、核心框架摘要、缺失项检查、下游生成准备、进入下一阶段建议。

完整原始数据仍保留在“调试原始数据”折叠区；`id / nodeId / moduleName / moduleType / moduleLogo / runningTime / totalPoints / model / inputTokens / outputTokens / query / maxToken / reasoningText / historyPreview / contextTotalLen / finishReason / llmRequestIds / updateVarResult / responseData / raw / debug / metadata / schema_version / mapping_version / contract_version / validation_status / source_path / source_ref / payload_keys` 等内部字段不进入主展示。

取消自动连跑的原因是避免“02 刚完成就自动跑 03，用户还没确认 03 偏好或应用 02 修改”的竞态。现在 02 完成后只展示 02 结果；用户应用修改后，03 页面先显示 03 人设偏好状态，只有用户点击“生成 03 人设方案”才请求 `/api/framework-planner/stage/03`。

### 框架导出与框架转剧本输入

07 完成页提供两个框架导出按钮：

- `下载可读框架`：导出 `.txt`，将 01-07 的结构化结果整理成分段中文说明，字段缺失显示“暂无”，不直接暴露原始 JSON key。
- `下载结构化框架`：导出 `.json`，用于导入框架到剧本工作台。内容包含 `frameworkPlanPackage / framework_plan_package`、`stageOutputs`、标题、集数、分钟数、目标形式、改编方向，以及 `export_version / exported_at` 等元数据；调试 raw、token、nodeId 等字段会被清理。

框架到剧本工作台支持三种输入方式：

- 从 01-07 框架阶段完成后直接跳转，URL 携带 `framework_asset_id`。
- 在 08-12 页面选择一个已保存框架资产。
- 在 08-12 页面导入“结构化框架 JSON”。导入会校验 `frameworkPlanPackage` 或 `stageOutputs`，失败时给出明确提示，不静默沿用旧缓存。

05 阶段 UI 已收口为一个“人物故事线”入口，不再暴露旧的拆分步骤。旧缓存中的详情或处理字段仍按同一份 `character_storylines / storyline_decisions` 兼容读取；人物线卡片里可展开查看对应集数、节拍和剧情节点。

06 “整体改编指引”支持字段化编辑：改编方向、原文保留内容、本次重点改变、风格要求、风险提醒、后续写作硬要求。修改后必须点击“应用修改”，否则 07 生成和保存会被拦截。

08-12 当前不使用智慧库偏好。框架到剧本阶段只使用 01-07 框架资产、08-12 上游阶段结果和页面显式参数；UI 不显示智慧库偏好，后端也不对 08-12 注入智慧库阶段偏好。

### 新建剧本输入

当前网页端新建剧本只要求用户输入：

- `想要的剧本`
- `角色数量`
- `总集数`

前端实际还会携带一个内部固定字段：

- `episode_word_count = 600`

其余内容由主链路自动生成：

- 剧本标题
- 故事大纲
- 原始人物设定
- 原始核心场景
- 规范化分集计划
- 世界观
- 服装前置策略与服装映射

### 运行中前端展示

普通用户前端当前按真实完成进度逐步展示：

1. `framework` 完成后显示 `framework_natural_language`
2. `worldview` 完成后显示 `worldview_natural_language`
3. `script` 批处理阶段只要某个 5 集批次通过 `script_review` 且本地正文校验通过，就显示该批正文
4. `completed` 后优先展示 `final_script / final_output_text`

未完成阶段不会提前渲染空壳、默认值、旧缓存或 `[object Object]`。

### 任务控制

工作台支持：

- 开始生成
- 暂停生成
- 继续生成
- 终止生成
- 继续失败任务
- 阶段回退重写
- 确认完成后清理缓存
- 下载 `txt / docx`

说明：

- 暂停、终止通常在当前阶段调用结束后生效。
- `running / pending / pausing` 时前端统一显示当前 `runtime_state.message`。
- 失败后会保留后端进度，可继续生成。
- 某个 script 批次一旦审核通过，会在 `script_memory` 之前先进入用户可见的阶段性正文展示。

## 当前主链路

当前 FastGPT 主链路顺序是：

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

其中：

- `appearance_alias_generation` 是 Python 逻辑阶段，内部由 4 个独立 FastGPT workflow 编排：
  - `appearance_alias_writing`
  - `appearance_alias_review`
  - `appearance_alias_rewrite`
  - `appearance_alias_unstructured`
- 正文链路固定是三段式批处理：
  - `all_hooks -> all_dialogues -> all_script`
- 每批默认 5 集，批次大小来自 `BATCH_SIZE`。

### 三幕十五节拍框架转剧本专用链路

平台主入口现在区分三条路径：

- 写剧本框架：进入 `/framework-planner?new=1`，创建全新的 01-07 框架策划上下文。
- 从已有框架写剧本：进入 `/framework-to-script` 后必须先选择已保存框架资产，不自动读取旧 localStorage 缓存。
- 继续编辑已有项目：进入框架策划工作台，打开已保存项目并恢复上次状态。

框架生成和框架转剧本是两个独立但可衔接的工作区。框架生成页负责完成 01-07；07 最终策划包生成后显示“框架已完成，可以进入剧本正文阶段”，用户点击“保存框架并进入剧本正文阶段”会先调用现有保存接口，再跳转到 `/framework-to-script?framework_asset_id=<asset_id>&source_framework_project_id=<project_id>&project_id=<project_id>`，并保留 `auth_token`。

框架资产接口只给前端业务字段：`asset_id`、`project_id`、`title`、`source_title`、`framework_plan_package`、`stage_outputs`、`target_format`、`episodes_per_season`、`minutes_per_episode`、`season_count`、`created_at`、`updated_at`、`summary`。01-07 主界面默认展示中文标题、段落和卡片；工程字段、原始 JSON、版本记录和回滚记录放入默认折叠的高级/调试区域，不在主要创作结果区展示。

框架策划工作台先完成 01-07 的策划资产，然后由用户在 07 后点击“用当前框架生成剧本”，进入主工作台的下游自动任务：

```text
01 原文信息提取 / 基础配置
02 世界观方案
03 人设方案
04 三幕十五节拍卡点规划
05 人物故事线
06 整体改编指引
07 最终策划包输出
点击“保存框架并进入剧本正文阶段”
08 场景字典提炼
09 人设服装 alias 映射
10 丰富分集计划
因果冲突推进计划
正文对白融合
最终输出剧本正文
```

其中 08、09、10 是框架转剧本内部阶段，也可以称为下游资产化阶段；它们不是框架策划工作台里需要用户手动点击的阶段。用户只需要确认 07 最终策划包，保存框架资产，然后点击“保存框架并进入剧本正文阶段”。

这条链路专用于“三幕十五节拍框架输出后的剧本生成”。它不会复用旧的 `all_hooks / all_dialogues / all_script` 三段式批处理，也不会调用 `dialogue_write / dialogue_review / dialogue_rewrite / dialogue_memory`。正文和对白已经在 `framework_script_write/review/rewrite/memory` 中融合生成，角色对话工作流不再用于 `framework_to_script` 链路。普通新建剧本仍走原有主链路。

#### Framework-to-script 08-12 chain

- 08 `framework_scene_dictionary` 生成 `sceneDictionary / scriptWorldRulesDigest`。
- 09 `framework_appearanceMapping` 生成 `appearanceMapping`，兼容 `appearance_mapping`。
- 10 `framework_enriched_episode_plan` 生成 `allEnrichedEpisodePlan`。
- 11 `framework_causal_conflict_write/review/memory` 串行生成因果冲突计划。
- 12 `framework_script_write/review/memory` 串行生成正文；最终导出字段是 `final_script / final_output_text`。
- 运行时按批次串行执行，代码上由同一条 `framework_to_script` 链路一次性串联；`.env`、`cache/`、`debug/`、`logs/` 不应提交。

#### Framework planner stage preferences

- 智慧库现在按 01-07 阶段保存偏好：`01=basic`、`02=worldview`、`03=character`、`04=beat`、`05=storylines`、`06=guide`、`07=package`。
- 默认标签和自定义标签都可编辑；应用标签后会写入各阶段 `stage_prompts`，当前阶段文本框仍可二次修改。
- 阶段请求优先使用当前阶段的 `stage_preference_prompt / user_stage_preference_prompt`，全局 `user_preference_prompt` 只作兼容兜底。
- 普通用户界面只展示用户友好的折叠结构，不直接展示 JSON 或 FastGPT 原始壳字段。
- 阶段历史在界面中称为“版本历史”，不对普通用户展示 `cache/logs/debug` 等工程词。

框架转剧本任务识别条件是输入中出现以下任一标记：

- `workflow_mode = "framework_to_script"`
- `generation_chain = "framework_to_script"`
- `framework_to_script = true`
- `framework_planner_source = true`

手动验收流程：

1. 启动服务：`python main.py`
2. 进入框架策划工作台。
3. 创建一个 5 集短项目。
4. 依次完成 01-07。
5. 确认 07 最终策划包输出。
6. 点击“保存框架”。
7. 点击“用当前框架生成剧本”。
8. 跳转到主工作台。
9. 检查运行阶段依次出现：
   - 框架转剧本：场景字典提炼
   - 框架转剧本：人设服装 alias 映射
   - 框架转剧本：丰富分集计划
   - 框架转剧本：因果冲突推进计划
   - 框架转剧本：正文对白融合
10. 最终生成 `final_script / final_output_text`。
11. 导出 `txt/docx`。

## 辅助工具

当前工具列表由后端动态读取并暴露为：

- `GET /api/tools`
- `POST /api/tools/<tool_id>/run`

已接入工具：

- `hot_review` -> `爆款文审核.json`
- `reskin` -> `换皮.json`
- `punchup` -> `增加爽感.json`
- `character_reskin` -> 后端多阶段 FastGPT 编排链路

工具输入字段以 workflow JSON 的 `chatConfig.variables` 为准；如果 workflow 没有公开输入变量，代码会做最小兜底。`character_reskin` 固定兼容现有“只换人设”表单字段和别名。

工具输出展示优先顺序：

1. `choices[0].message.content`
2. answerNode 对应文本
3. `answerText / textOutput`
4. `updateVarResult / newVariables / variableUpdate` 中的可见输出

普通用户只会看到最终可见结果，不会看到 FastGPT 原始壳字段、reasoning 或内部变量。

腾讯视频平台数据反馈模块使用说明：[docs/tencent_video_data.md](docs/tencent_video_data.md)

## FastGPT 环境变量

至少需要配置：

```env
FASTGPT_CHAT_COMPLETIONS_URL=http://your-fastgpt-host/api/v1/chat/completions
FASTGPT_API_KEY=fastgpt-xxxx
```

代码不会自动拼接 `/api/v1/chat/completions`，这里必须写完整 URL。

### 全局控制项

常用全局配置：

```env
WORKFLOW_BACKEND=fastgpt
FASTGPT_VARIABLE_MODE=legacy
FASTGPT_BATCH_MODE=local
BATCH_SIZE=5
MAX_RETRIES_DEFAULT=10
FASTGPT_STAGE_FORMAT_RETRY_LIMIT=3
FASTGPT_STAGE_REVIEW_REVISE_MAX_LOOPS=10
FASTGPT_STAGE_LOCAL_RESTART_RETRIES=1
FASTGPT_OUTPUT_REPAIR_RETRIES=1
FASTGPT_TIMEOUT=300
FASTGPT_HTTP_RETRIES=2
FASTGPT_HTTP_RETRY_DELAY=1.5
```

补充：

- HTTP/timeout 重试和“输出格式不可消费重试”是两套逻辑。
- `FASTGPT_STAGE_FORMAT_RETRY_LIMIT` 表示：HTTP 成功但输出仍不可消费时，当前 stage 最多重新调用几次。
- `FASTGPT_STAGE_REVIEW_REVISE_MAX_LOOPS` 控制审核/修订循环上限。

### stage 级 API key / URL / timeout

所有 stage 都支持：

- `FASTGPT_<STAGE>_API_KEY`
- `FASTGPT_<STAGE>_CHAT_COMPLETIONS_URL`
- `FASTGPT_<STAGE>_TIMEOUT`

未配置 stage 专用值时，会回退到全局：

- `FASTGPT_API_KEY`
- `FASTGPT_CHAT_COMPLETIONS_URL`
- `FASTGPT_TIMEOUT`

当前主链路常用的 stage 级 key 包括：

```env
FASTGPT_FRAMEWORK_API_KEY=
FASTGPT_UNSTRUCTURED_API_KEY=
FASTGPT_APPEARANCE_PRE_STRATEGY_API_KEY=
FASTGPT_CONSISTENCY_API_KEY=
FASTGPT_EPISODE_PLAN_NORMALIZE_API_KEY=
FASTGPT_WORLDVIEW_API_KEY=
FASTGPT_CHARACTERS_API_KEY=
FASTGPT_SCENES_API_KEY=

FASTGPT_APPEARANCE_ALIAS_WRITING_API_KEY=
FASTGPT_APPEARANCE_ALIAS_REVIEW_API_KEY=
FASTGPT_APPEARANCE_ALIAS_REWRITE_API_KEY=
FASTGPT_APPEARANCE_ALIAS_UNSTRUCTURED_API_KEY=

FASTGPT_HOOKS_WRITING_API_KEY=
FASTGPT_HOOKS_REVIEW_API_KEY=
FASTGPT_HOOKS_REWRITE_API_KEY=
FASTGPT_HOOKS_MEMORY_API_KEY=

FASTGPT_DIALOGUES_WRITING_API_KEY=
FASTGPT_DIALOGUES_REVIEW_API_KEY=
FASTGPT_DIALOGUES_REWRITE_API_KEY=
FASTGPT_DIALOGUES_MEMORY_API_KEY=

FASTGPT_SCRIPT_WRITING_API_KEY=
FASTGPT_SCRIPT_REVIEW_API_KEY=
FASTGPT_SCRIPT_REWRITE_API_KEY=
FASTGPT_SCRIPT_MEMORY_API_KEY=

FASTGPT_FINAL_API_KEY=
```

三幕十五节拍框架转剧本专用链路需要单独配置：

```env
FASTGPT_FRAMEWORK_SCENE_DICTIONARY_API_KEY=
FASTGPT_FRAMEWORK_APPEARANCE_MAPPING_API_KEY=
FASTGPT_FRAMEWORK_ENRICHED_EPISODE_PLAN_API_KEY=
FASTGPT_FRAMEWORK_CAUSAL_CONFLICT_WRITE_API_KEY=
FASTGPT_FRAMEWORK_CAUSAL_CONFLICT_REVIEW_API_KEY=
FASTGPT_FRAMEWORK_CAUSAL_CONFLICT_REWRITE_API_KEY=
FASTGPT_FRAMEWORK_CAUSAL_CONFLICT_MEMORY_API_KEY=
FASTGPT_FRAMEWORK_SCRIPT_WRITE_API_KEY=
FASTGPT_FRAMEWORK_SCRIPT_REVIEW_API_KEY=
FASTGPT_FRAMEWORK_SCRIPT_REWRITE_API_KEY=
FASTGPT_FRAMEWORK_SCRIPT_MEMORY_API_KEY=
```

这些 key 不会回退到旧的 hooks/dialogues/script 或全局 `FASTGPT_API_KEY`；缺少当前阶段 key 时，错误信息会直接指出缺少的环境变量名。

辅助工具 key：

```env
FASTGPT_HOT_REVIEW_API_KEY=
FASTGPT_RESKIN_API_KEY=
FASTGPT_PUNCHUP_API_KEY=
FASTGPT_NEW_FRAMEWORK_API_KEY=
```

`character_reskin / 只换人设` 现在不是单个 FastGPT workflow，而是后端维护中间态并串联多个拆分 workflow。它必须配置以下 12 个专用 key，统一使用 `FASTGPT_CHAT_COMPLETIONS_URL`，不再使用 `FASTGPT_EDIT_*` 和 `FASTGPT_SCRIPT_REWRITE_MEMORY_KEY`：

```env
FASTGPT_COUNT_ACTUAL_EPISODES_KEY=
FASTGPT_WRITE_CHARACTER_PROFILE_KEY=
FASTGPT_REVIEW_CHARACTER_PROFILE_KEY=
FASTGPT_REWRITE_CHARACTER_PROFILE_KEY=
FASTGPT_SORT_CHARACTER_PROFILE_KEY=
FASTGPT_WRITE_CHARACTER_DIALOGUE_KEY=
FASTGPT_REVIEW_CHARACTER_DIALOGUE_KEY=
FASTGPT_REWRITE_CHARACTER_DIALOGUE_KEY=
FASTGPT_WRITE_SCRIPT_BODY_KEY=
FASTGPT_REVIEW_SCRIPT_BODY_KEY=
FASTGPT_REWRITE_SCRIPT_BODY_KEY=
FASTGPT_SCRIPT_MEMORY_KEY=
```

只换人设链路顺序：统计原剧本实际集数 -> 生成人设 JSON -> 审核人设 JSON -> 必要时修订人设并复审，最多修订 5 次 -> 整理人物小传纯文本 -> 按 5 集一批生成角色对话 -> 审核/必要时修订角色对话，最多修订 5 次 -> 生成正文 -> 审核/必要时修订正文，最多修订 5 次 -> 总结本批剧本记忆 -> 拼接全部正文。

关键桥接规则：

- `target_style` 会拼入 `source_outline`，并传给 `ayxWwSpE`。
- 先把原剧本正文传给 `统计实际集数` workflow 的 `juben_zhengwen`，读取 `kpoOTOUP / answerText`；非零自然数会覆盖后续所有阶段的 `total_episodes / blkSS7dY`。
- 实际集数返回 `0` 时提示用户补充原剧本正文；返回 `X` 时提示原剧本跳集、漏集或残缺，需要补全后再运行。
- 人设审核结果由后端从 `profile_review_json` 桥接到修订变量 `va4Et1LA`。
- 角色对话审核结果由 `dialogue_review_json` 桥接到 `rZL0C6f9`。
- 角色对话通过后，后端把 `mN7Fh38L` 对应内容同步为正文阶段读取的 `pS7JzosX`。
- 正文审核结果由 `body_review_json` 桥接到 `gJT2URpY`。
- 剧本记忆由 `script_memory_json` 分别桥接到下一批正文编写/审核/修订的 `bai4xfdD / ntBQgrAm / mcUdAISf`。

API 完成后会返回 `output / final_output_text` 作为最终剧本正文，同时返回 `character_profile` 和 `character_profile_json`。常见错误包括：某阶段 key 缺失、FastGPT 返回空 `answerText`、短变量 key 与 workflow 不匹配、审核结果没有正确桥接到修订阶段。

## 导出说明

当前导出链路是：

- 项目完成后可下载 `txt`
- 项目完成后可下载 `docx`

DOCX 导出器已经兼容历史/旧项目中的非严格结构数据：

- 人物字段可以是 `dict / str / list / None`
- 场景字段可以是 `dict / str / list / None`
- 正文字段可以是 `str / dict / list`

因此旧项目不需要重新生成，重启代码后即可重新尝试下载。

## 进一步阅读

- 开发者维护地图：`CODER_README.md`
- 当前 FastGPT 契约、stage 映射与变量语义：`workflow_code_skeleton/FASTGPT_CONTRACTS.md`
