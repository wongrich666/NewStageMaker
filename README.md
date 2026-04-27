# AI 剧本生成平台

这是一个“本地编排 + FastGPT 工作流 API”的混合式剧本生产系统。

它的目标不是只生成一段文本，而是把“从用户想法到完整剧本”的整条链路做成可暂停、可继续、可缓存、可导出的工作台。

当前系统支持：

- 网页端注册、登录、个人资产管理
- 同一用户同时运行多个任务
- 多用户并发使用
- 任务离开页面后继续运行
- 失败后保留中间进度并继续生成
- 最终导出 `txt + docx + zip`
- 社区公开作品展示
- 若干一次性辅助工具工作流

## 项目结构

```text
new_scriptmaker/
├─ main.py
├─ README.md
└─ workflow_code_skeleton/
   ├─ .env.example
   ├─ requirements.txt
   ├─ runtime_data/
   └─ app/
      ├─ server.py
      ├─ config.py
      ├─ workflow_ids.py
      ├─ models/
      ├─ orchestrators/
      ├─ services/
      ├─ utils/
      └─ web/
```

主要代码都在 [workflow_code_skeleton/app](C:\Users\Administrator\PycharmProjects\new_scriptmaker\workflow_code_skeleton\app)。

运行时数据保存在：

- 项目快照：`workflow_code_skeleton/runtime_data/projects/`
- 导出文件：`workflow_code_skeleton/runtime_data/exports/`
- 用户与登录数据：`workflow_code_skeleton/runtime_data/`

## 启动方式

先安装依赖：

```bash
pip install -r workflow_code_skeleton/requirements.txt
```

复制环境变量模板：

```bash
copy workflow_code_skeleton\.env.example workflow_code_skeleton\.env
```

启动网页服务：

```bash
python main.py
```

本机访问：

```text
http://127.0.0.1:5000
```

如果要给同一局域网其他人访问，请使用启动日志里显示的内网地址，例如：

```text
http://192.168.x.x:5000
```

## 网页怎么用

### 主流程输入

当前主剧本创建页只需要用户填写：

- `想要的剧本`
- `角色数量`
- `总集数`

其余这些内容不需要手填，会由前置 FastGPT 工作流自动生成：

- 剧本标题
- 故事大纲
- 人物小传
- 核心场景
- 分集计划
- 服装前置策略

### 任务控制

工作台支持：

- 开始生成
- 暂停生成
- 继续生成
- 终止生成
- 继续失败任务
- 下载最终剧本

说明：

- 暂停、终止通常会在当前阶段调用结束后生效
- 失败后会保留后端中间数据，方便继续生成
- 项目完成后会自动收缩缓存，只保留正式成品和必要导出数据

### 多任务

- 同一账号可同时开多个任务
- 同一浏览器可开多个页面
- 页面关闭后任务继续运行
- 只要不退出登录，回来后仍可继续查看和管理任务

### 个人资产

个人中心支持：

- 修改标题
- 修改故事梗概
- 修改公开 / 不公开
- 删除资产
- 查看和下载完整剧本

即使剧本尚未完全生成，也可以修改资产信息。

### 社区好剧

社区只展示：

- `status = completed`
- `visibility = public`

的作品。

社区卡片展示的是一句话摘要；详情页可以查看完整剧本正文。

## 环境变量

至少需要配置完整的 FastGPT 接口地址：

```env
FASTGPT_CHAT_COMPLETIONS_URL=http://your-fastgpt-host/api/v1/chat/completions
```

代码不会自动补 `/api/v1/chat/completions`，这里必须直接写完整 URL。

### 主流程阶段 Key

当前主流程会用到这些阶段 Key：

```env
FASTGPT_FRAMEWORK_API_KEY=
FASTGPT_APPEARANCE_PRE_STRATEGY_API_KEY=
FASTGPT_CONSISTENCY_API_KEY=
FASTGPT_EPISODE_PLAN_NORMALIZE_API_KEY=
FASTGPT_WORLDVIEW_API_KEY=
FASTGPT_CHARACTERS_API_KEY=
FASTGPT_SCENES_API_KEY=
FASTGPT_APPEARANCE_ALIAS_GENERATION_API_KEY=
FASTGPT_HOOKS_API_KEY=
FASTGPT_DIALOGUES_API_KEY=
FASTGPT_SCRIPT_API_KEY=
FASTGPT_MEMORY_API_KEY=
FASTGPT_FINAL_API_KEY=
```

如果多个阶段共用同一个 FastGPT 应用，也可以只配置：

```env
FASTGPT_API_KEY=
```

### 辅助工具 Key

如果你要启用一次性辅助工具，还可以配置：

```env
FASTGPT_HOT_REVIEW_API_KEY=
FASTGPT_RESKIN_API_KEY=
FASTGPT_PUNCHUP_API_KEY=
FASTGPT_CHARACTER_RESKIN_API_KEY=
```

## 混合工作流架构

这一套主流程不是“Python 里把所有内容一步生成完”，而是一个明确分层的混合架构：

```text
浏览器 / API
  -> server.py
  -> TaskManager.start_task()
  -> 后台线程 TaskManager._run_task()
  -> runner.run_configured_workflow()
  -> orchestrators/fastgpt_hybrid_workflow.py
  -> services/fastgpt_client.py
  -> FastGPT /api/v1/chat/completions
```

### 1. 入口和任务编排层

- `server.py` 只负责 Web/API 入口、鉴权和把请求交给任务管理器。
- `task_manager.py` 负责创建项目快照、启动后台线程、保存运行中快照、暂停/继续/失败重试/阶段回退/导出。
- `runner.py` 根据 `WORKFLOW_BACKEND` 选择走本地旧流程还是当前 `FastGPT Hybrid Workflow`。
- `fastgpt_hybrid_workflow.py` 是主编排层，负责决定“下一步该跑哪个阶段”、何时复用缓存、何时按批次推进、何时阻止不完整结果进入 `final`。

### 2. FastGPTClient 调用 API 的流程

`FastGPTClient.run_stage()` 的职责是“把某个阶段安全地调用出去，再把响应安全地收回来”：

1. 从 `fastgpt_contracts.py` 读取该阶段契约。
2. 根据契约和 `FASTGPT_VARIABLE_MODE` 构造要发给 FastGPT 的变量。
3. 解析该阶段自己的 URL / API Key / chatId。
4. 调用 `/api/v1/chat/completions`。
5. 从 `responseData / output / updateVarResult / answerText / choices` 等常见槽位里抽取候选输出。
6. 先做阶段专属归一化，再按契约字段名 / 别名匹配。
7. 用契约做类型校验和结构校验。
8. 返回“本阶段正式成品”，交回编排层缓存。

这里的关键点是：本地代码不会盲信 FastGPT 的任意返回文本，而是会尽量把响应折叠成“满足契约的那一个候选结果”。

### 3. 阶段契约层

`fastgpt_contracts.py` 统一定义了三件事：

- 每个阶段需要哪些输入字段；
- 每个阶段必须返回哪些输出字段；
- 这些字段的类型、结构、别名以及“FastGPT 负责什么 / 本地负责什么”。

因此，契约层既是 API 适配层，也是工作流边界说明：

- FastGPT 负责阶段内容生成、审核、修订、整理成最终阶段成品；
- Python 本地负责输入准备、输出校验、缓存复用、批次切片、失败恢复和最终导出。

### 4. JSON 解析层

`json_utils.py` 和 `fastgpt_client.py` 共同承担“把模型输出变成稳定 JSON”的工作：

- `json_utils.py` 先去掉代码块 fence，再尝试从文本里抽出 JSON 片段；
- `fastgpt_client.py` 再结合阶段上下文做候选遍历、字段别名匹配和阶段专属格式归一化；
- `fastgpt_hybrid_workflow.py` 会继续把 `normalized_episode_plan`、`appearance_mapping` 这类结构整理成更稳定的本地对象，供后续批处理切片使用。

### 5. 批次生成、缓存、恢复、导出

- 批次生成：
  `fastgpt_hybrid_workflow.py` 会把 `hooks -> dialogues -> script` 固定成“同一批串行推进”，避免三个阶段各自跳批。
- 缓存保存：
  `WorkflowRuntime.sync_from_state()` 会把正式产物写入 `artifacts`，同时把完整执行状态写入 `debug_state`，供失败恢复和阶段回退使用。
- 失败恢复：
  `TaskManager` 会维护 `_resume_checkpoint`；任务失败后先回滚到最近一次稳定快照，再由 `_restore_resume_state()` 和 `_sanitize_restored_batch_progress()` 重新对齐批次位置。
- 正文修复：
  `_repair_script_outputs()` 会用 `LOCAL_SCRIPT_BATCHES + LOCAL_SCRIPT_EPISODES + ALL_SCRIPT` 交叉修复正文缓存，避免只剩局部批次文本时误判为完整正文。
- 导出：
  `save_final_script()` 先确认正文集数完整，再通过 `_build_docx_export_source_text()` 把标题、大纲、人物、场景、正文整理成 `txt_to_docx.py` 可识别的导出源文本。

## 当前主流程

现在的主流程顺序是：

1. `framework`
2. `appearance_pre_strategy`
3. `consistency`
4. `episode_plan_normalize`
5. `worldview`
6. `characters`
7. `scenes`
8. `appearance_alias_generation`
9. `hooks`
10. `dialogues`
11. `script`
12. `memory`
13. `final`

### 每一步大概在做什么

#### 1. framework

输入：

- 用户期待
- 角色数量
- 总集数

输出：

- `script_title` / 代码侧兼容映射到 `script_title_content`
- `story_outline`：结构化 object
- `user_characters`：结构化 array
- `user_scenes`：结构化 object
- `episode_plan`：结构化 array

也就是先把完整剧本框架搭出来。

#### 2. appearance_pre_strategy

基于框架结果自动生成：

- `character_appearance_requirements`
- `character_alias_naming_rules`
- `outfit_switch_rules`

这一层不再由网页手填，而是由 FastGPT 前置策略工作流自动完成。

#### 3. consistency

检查分集计划和总集数是否一致。

#### 4. episode_plan_normalize

把分集计划整理成结构化 JSON，方便后面按批次只读取当前需要的集数。

#### 5. worldview / 6. characters / 7. scenes

分别生成：

- 世界观
- 人物设定
- 核心场景

这些阶段都会读取前面已经生成的正式内容，而不是让用户重复输入。

#### 8. appearance_alias_generation

这一层负责“同一人物的服装版本 / 别名映射”。

系统会在后端维护这些结构化数据：

- `appearance_mapping`
- `character_registry`
- `character_alias_registry`
- `episode_alias_plan`
- `appearance_continuity_memory`

这样后面的对白和正文就不是让模型随机写名字，而是统一吃同一套人物映射。

#### 9. hooks / 10. dialogues / 11. script

这三步是按批次生成的。

本地代码负责：

- 批次划分
- 起始集数推进
- 当前批次分集计划切片
- 结果拼接

FastGPT 负责：

- 当前批次开头冲突钩子
- 当前批次角色对白
- 当前批次剧本正文

#### 12. memory

只整理“刚刚生成的这一批”记忆，并覆盖旧记忆。

#### 13. final

把标题、大纲、人物、场景、正文拼成最终完整剧本。

## 本地代码和 FastGPT 的职责边界

### FastGPT 负责

- 内容生成
- 审核 / 修订 / 重写
- 各阶段成品输出

当前约定是：每个阶段调用 FastGPT 后返回的就是该阶段成品，而不是半成品。

### Python 本地负责

- 用户系统
- 项目 / 任务管理
- 多任务并发
- 暂停 / 继续 / 终止
- 阶段进度
- 批次循环
- 当前批次切片
- 中间产物缓存
- 失败恢复
- 导出文件
- 前端安全白名单返回

## 快照与缓存策略

系统现在分两层存储：

- 后端原始快照：保留恢复任务所需的中间数据
- 前端公开快照：只返回页面真正需要的正式字段

也就是说：

- `debug_state`
- `variables`
- `node_outputs`
- 网络搜索等中间产物

不会原样暴露给前端。

另外：

- 未完成项目：保留后端中间数据，便于继续生成
- 已完成项目：自动压缩快照，只保留正式成品数据与导出数据

## 导出结果

保存最终剧本时会生成：

- `xxx.txt`
- `xxx.docx`

当前代码里的稳定导出链路是：

- 先写出 `txt`
- 再转换成 `docx`
- 下载接口当前直接返回 `docx`

说明：

- 导出前会再次校验剧本正文是否覆盖全部集数，缺集时会拒绝导出
- 代码里仍保留了 `zip/json` 相关占位路径，但当前这条主导出路径还没有真正打包输出这些文件

## 辅助工具

当前网页还接了几类一次性工具工作流：

- 爆款文审核
- 换皮
- 增加爽感
- 只换人设

它们不参与主剧本批处理流程，只是独立调用一次、返回一次结果。

## 开发补充

### 关键入口文件

- 服务入口：[server.py](C:\Users\Administrator\PycharmProjects\new_scriptmaker\workflow_code_skeleton\app\server.py)
- 主编排：[fastgpt_hybrid_workflow.py](C:\Users\Administrator\PycharmProjects\new_scriptmaker\workflow_code_skeleton\app\orchestrators\fastgpt_hybrid_workflow.py)
- FastGPT 契约：[fastgpt_contracts.py](C:\Users\Administrator\PycharmProjects\new_scriptmaker\workflow_code_skeleton\app\services\fastgpt_contracts.py)
- 任务管理：[task_manager.py](C:\Users\Administrator\PycharmProjects\new_scriptmaker\workflow_code_skeleton\app\services\task_manager.py)
- 前端逻辑：[app.js](C:\Users\Administrator\PycharmProjects\new_scriptmaker\workflow_code_skeleton\app\web\static\app.js)

### 接入新 FastGPT 工作流时，至少要改的地方

1. 在 [workflow_ids.py](C:\Users\Administrator\PycharmProjects\new_scriptmaker\workflow_code_skeleton\app\workflow_ids.py) 补变量 ID
2. 在 [fastgpt_contracts.py](C:\Users\Administrator\PycharmProjects\new_scriptmaker\workflow_code_skeleton\app\services\fastgpt_contracts.py) 注册 stage 契约
3. 在 [fastgpt_hybrid_workflow.py](C:\Users\Administrator\PycharmProjects\new_scriptmaker\workflow_code_skeleton\app\orchestrators\fastgpt_hybrid_workflow.py) 接入阶段顺序和本地缓存逻辑
4. 在 `.env.example` 预留对应的 API Key 占位符

### framework 阶段当前契约

Python 侧现在要求 `framework` 阶段最终返回：

```json
{
  "script_title": "string",
  "story_outline": {
    "opening": "string",
    "inciting_incident": "string",
    "early_goal": "string",
    "middle_escalation": "string",
    "relationship_changes": "string",
    "larger_crisis_or_truth": "string",
    "late_direction": "string",
    "final_climax": "string",
    "ending_resolution": "string",
    "theme": "string"
  },
  "user_characters": [
    {
      "name": "string",
      "role_type": "string",
      "identity": "string",
      "personality": "string",
      "core_desire": "string",
      "deep_motivation": "string",
      "strengths": "string",
      "weaknesses": "string",
      "appearance_anchor": "string",
      "relationship_to_protagonist": "string",
      "relationships_with_others": "string",
      "growth_arc": "string",
      "plot_function": "string"
    }
  ],
  "user_scenes": {
    "era_background": "string",
    "world_state": "string",
    "core_locations": [
      {
        "name": "string",
        "function": "string",
        "conflict_soil": "string",
        "key_characters": ["string"]
      }
    ],
    "rules": "string",
    "danger_sources": "string",
    "resource_or_stakes": "string",
    "power_distribution": "string",
    "special_rules": "string",
    "overall_atmosphere": "string"
  },
  "episode_plan": [
    {
      "episode": 1,
      "title": "string",
      "main_plot": "string",
      "conflicts": ["string"],
      "ending_hook": "string"
    }
  ]
}
```

本地编排层会先按这个结构做严格校验，再把 `story_outline / user_characters / user_scenes / episode_plan` 序列化回字符串缓存，保证后面的 legacy 批处理、缓存恢复和导出逻辑不用跟着一起重写。

---

当前仓库只保留这一份 README 作为有效说明文档。
