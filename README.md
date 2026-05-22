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

框架生成和框架转剧本是两个独立但可衔接的工作区。框架生成页负责完成 01-07；07 最终策划包确认后会保存为可复用的“框架资产”，并可通过“进入剧本阶段”跳转到 `/framework-to-script?framework_asset_id=...`。框架转剧本页也可以独立打开，从已有框架资产中选择导入后继续 08+。

框架资产接口只给前端业务字段：`asset_id`、`project_id`、`title`、`source_title`、`framework_plan_package`、`stage_outputs`、`target_format`、`episodes_per_season`、`minutes_per_episode`、`season_count`、`created_at`、`updated_at`、`summary`。UI 统一使用“框架资产”“版本历史”“保存当前版本”“恢复到此版本”等命名，不展示 JSON/raw/cache/logs/debug，也不展示 FastGPT 原始壳字段。

框架策划工作台先完成 01-07 的策划资产，然后由用户在 07 后点击“用当前框架生成剧本”，进入主工作台的下游自动任务：

```text
01 原文信息提取 / 基础配置
02 世界观方案
03 人设方案
04 三幕十五节拍卡点规划
05 人物故事线
06 整体改编指引
07 最终策划包输出
点击“用当前框架生成剧本”
08 场景字典提炼
09 人设服装 alias 映射
10 丰富分集计划
因果冲突推进计划
正文对白融合
最终输出剧本正文
```

其中 08、09、10 是框架转剧本内部阶段，也可以称为下游资产化阶段；它们不是框架策划工作台里需要用户手动点击的阶段。用户只需要确认 07 最终策划包，保存当前框架资产，然后点击“用当前框架生成剧本”。

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
6. 点击“保存当前框架”。
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
- `character_reskin` -> `只换人设.json`

工具输入字段以 workflow JSON 的 `chatConfig.variables` 为准；如果 workflow 没有公开输入变量，代码会做最小兜底。

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
FASTGPT_CHARACTER_RESKIN_API_KEY=
```

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
