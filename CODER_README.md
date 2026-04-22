# CODER README

这份文档是给开发者自己看的排障地图，不是给最终用户看的使用说明。

目标只有一个：当你点击“开始生成”以后，知道请求会经过哪些文件、哪些函数、每一层在做什么、应该在哪里打断点。

---

## 1. 先记住主链路

从网页点击“开始生成”开始，当前 FastGPT 链路的大致顺序是：

1. 前端收集表单并发起 `/api/workflows/start`
2. Flask 路由把前端 JSON 转成后端 `payload`
3. `TaskManager.start_task()` 创建 `project_id / task_id / snapshot`
4. 后台线程进入 `TaskManager._run_task()`
5. `WorkflowInput.from_dict()` 把原始 payload 变成强类型输入对象
6. `run_configured_workflow()` 根据配置选择后端
7. 当前默认进入 `run_fastgpt_hybrid_workflow()`
8. Python 本地编排主流程，逐阶段调用 FastGPT
9. 每个阶段都会走 `FastGPTClient.run_stage()`
10. FastGPT 返回后，先解析 HTTP 响应，再过契约校验，再回写本地 `state`
11. `WorkflowRuntime.sync_from_state()` 把当前进度和成品同步到任务快照
12. 前端轮询 `/api/projects/<id>` 或 `/api/tasks/<task_id>`，刷新页面显示

一句话理解：

- 前端负责发请求和展示状态
- Flask 负责把请求转成任务
- `TaskManager` 负责线程、暂停恢复、快照缓存
- `fastgpt_hybrid_workflow.py` 负责“本地编排”
- `fastgpt_client.py` 负责“真正调用 FastGPT API”
- `fastgpt_contracts.py` 负责“这个阶段该收什么、该回什么”

---

## 2. 最常用的断点地图

如果你只想快速排查，先打这几个点：

### A. 点击开始后到底有没有成功发起任务

- `workflow_code_skeleton/app/web/static/app.js:626` `startGeneration()`
  - 中文意思：前端“开始生成”按钮的主入口
- `workflow_code_skeleton/app/web/static/app.js:490` `buildPayload()`
  - 中文意思：把页面输入拼成后端要的 JSON
- `workflow_code_skeleton/app/server.py:289` `start_workflow()`
  - 中文意思：Flask 的“开始工作流”接口入口

### B. 后端有没有真的启动线程

- `workflow_code_skeleton/app/services/task_manager.py:701` `start_task()`
  - 中文意思：创建任务记录、快照、线程
- `workflow_code_skeleton/app/services/task_manager.py:1022` `_run_task()`
  - 中文意思：后台线程真正开始执行工作流

### C. 是不是已经进入 FastGPT 主编排

- `workflow_code_skeleton/app/orchestrators/runner.py:12` `run_configured_workflow()`
  - 中文意思：根据配置选择“FastGPT 编排”还是“本地旧编排”
- `workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py:110` `run_fastgpt_hybrid_workflow()`
  - 中文意思：当前主流程总控函数

### D. 某个阶段为什么失败/没返回

- `workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py:726` `_run_fastgpt_stage()`
  - 中文意思：单个阶段的统一执行器
- `workflow_code_skeleton/app/services/fastgpt_client.py:125` `run_stage()`
  - 中文意思：真正发 FastGPT HTTP 请求
- `workflow_code_skeleton/app/services/fastgpt_client.py:320` `_extract_output_payload()`
  - 中文意思：从 FastGPT HTTP 响应体里提取阶段产物
- `workflow_code_skeleton/app/services/fastgpt_contracts.py:738` `contract_for()`
  - 中文意思：拿到该阶段的输入/输出契约

### E. 为什么页面不更新 / 中间变量明明有但前端没看到

- `workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py:902` `_sync_state_variables()`
  - 中文意思：把本地 `variables` 同步回 `WorkflowState`
- `workflow_code_skeleton/app/services/task_manager.py:326` `WorkflowRuntime.sync_from_state()`
  - 中文意思：把 `WorkflowState` 转成快照里的 artifacts/progress
- `workflow_code_skeleton/app/services/task_manager.py:507` `_public_snapshot()`
  - 中文意思：决定哪些字段允许返回给前端
- `workflow_code_skeleton/app/web/static/app.js:305` `renderSnapshot()`
  - 中文意思：前端把任务快照渲染到页面

---

## 3. 从点击开始到线程启动：前端 -> Flask

### 3.1 前端按钮

文件：

- `workflow_code_skeleton/app/web/static/app.js`

关键函数：

- `startGeneration()` `app.js:626`
  - 中文意思：点击“开始生成”后的主流程
  - 做的事：
    1. 检查登录
    2. 保存草稿
    3. 调 `buildPayload()`
    4. POST 到 `/api/workflows/start`
    5. 任务创建成功后刷新项目列表并开始轮询

- `buildPayload()` `app.js:490`
  - 中文意思：构造后端输入
  - 当前页面主要提交：
    - `user_expectation`
    - `character_count`
    - `episode_word_count`
    - `total_episodes`
    - `model_selection_id`
  - 另外 `title / story_outline / core_scene_input / character_bios / episode_plan` 当前先传空，等 framework 阶段来补

- `requestJson()` `app.js:438`
  - 中文意思：统一请求封装
  - 这里会自动把当前页面自己的 `Authorization: Bearer <auth_token>` 带上

### 3.2 Flask 接口入口

文件：

- `workflow_code_skeleton/app/server.py`

关键函数：

- `start_workflow()` `server.py:289`
  - 中文意思：后端“开始工作流”接口
  - 做的事：
    1. 读取前端 JSON
    2. 生成 `payload`
    3. 如果没有标题，就先用 `derive_script_title()` 根据“用户期待”兜底
    4. 把服装相关三个字段先置空，等后续 `appearance_pre_strategy` 阶段回填
    5. 调 `task_manager.start_task(...)`

- `derive_script_title()` `workflow_code_skeleton/app/models/inputs.py:16`
  - 中文意思：本地兜底标题生成器
  - 用途：framework 阶段没出标题时，至少有个可用标题

---

## 4. 后台任务线程：TaskManager 在做什么

文件：

- `workflow_code_skeleton/app/services/task_manager.py`

### 4.1 创建任务

- `start_task()` `task_manager.py:701`
  - 中文意思：创建任务与项目记录
  - 做的事：
    1. 分配 `project_id`
    2. 生成 `task_id`
    3. 解析模型选择
    4. 创建初始 `snapshot`
    5. 把任务放进内存字典 `_tasks / _projects`
    6. 启动后台线程 `target=self._run_task`

如果你怀疑“前端点了开始但根本没开线程”，断点先打这里。

### 4.2 后台线程主入口

- `_run_task()` `task_manager.py:1022`
  - 中文意思：后台线程真正执行工作流
  - 做的事：
    1. 更新快照状态为 `running`
    2. `WorkflowInput.from_dict()`：把原始 payload 转成结构化输入
    3. 创建 `WorkflowRuntime`
    4. 调 `run_configured_workflow(...)`
    5. 根据返回结果把任务标记为：
       - `completed`
       - `failed`
       - `terminated`
    6. 完成后压缩快照，只保留成品数据

### 4.3 运行时同步器

- `WorkflowRuntime.set_stage()` `task_manager.py:243`
  - 中文意思：更新当前阶段、进度、批次标签

- `WorkflowRuntime.fastgpt_stage_started()` `task_manager.py:295`
  - 中文意思：记录某个 FastGPT 阶段开始了

- `WorkflowRuntime.fastgpt_stage_finished()` `task_manager.py:311`
  - 中文意思：记录某个 FastGPT 阶段成品已生成

- `WorkflowRuntime.sync_from_state()` `task_manager.py:326`
  - 中文意思：把 `WorkflowState` 里的变量同步成快照里的 artifacts
  - 这是“后端中间状态怎么变成前端能看到的状态”的关键位置

如果你发现：

- 后端明明生成了结果
- 但页面没显示

优先打这里。

---

## 5. 输入对象与运行态对象

### 5.1 WorkflowInput

文件：

- `workflow_code_skeleton/app/models/inputs.py`

关键函数：

- `WorkflowInput.from_dict()` `inputs.py:42`
  - 中文意思：把 Flask 收到的 payload 统一转成后端输入对象

- `WorkflowInput.validate()` `inputs.py:131`
  - 中文意思：输入合法性校验
  - 当前最重要的校验：
    - 总集数 > 0
    - 每集字数 > 0
    - 要么有完整梗概/人设/分集计划
    - 要么至少有 `user_expectation + character_count`

### 5.2 WorkflowState

文件：

- `workflow_code_skeleton/app/models/state.py`

关键函数：

- `WorkflowState.from_defaults()` `state.py:43`
  - 中文意思：创建运行态对象，并把最初输入写入基础变量

- `set_var()` `state.py:72`
  - 中文意思：往运行态变量表里写值

- `set_output()` `state.py:90`
  - 中文意思：给某个节点记录输出

- `as_debug_dict()` `state.py:93`
  - 中文意思：导出完整调试态
  - 注意：现在这个完整调试态主要保留在后端，不再原样返回前端

---

## 6. 主流程总控：run_fastgpt_hybrid_workflow

文件：

- `workflow_code_skeleton/app/orchestrators/runner.py`
- `workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py`

### 6.1 先选后端

- `run_configured_workflow()` `runner.py:12`
  - 中文意思：决定走哪套工作流后端
  - 当前配置只要 `settings.workflow_backend` 是：
    - `fastgpt`
    - `hybrid`
    - `fastgpt_hybrid`
  - 就会进入 `run_fastgpt_hybrid_workflow()`

### 6.2 主流程顺序

- `run_fastgpt_hybrid_workflow()` `fastgpt_hybrid_workflow.py:110`
  - 中文意思：FastGPT 混合编排主流程

当前阶段顺序是：

1. `framework` 剧本框架撰写
2. `appearance_pre_strategy` 服装前置策略生成器
3. `consistency` 集数一致性检查
4. `episode_plan_normalize` 分集计划规范化
5. `worldview` 世界观生成与审核
6. `characters` 人物设定生成与审核
7. `scenes` 核心场景生成与审核
8. `appearance_alias_generation` 人物服装版本映射
9. `hooks` 开头冲突钩子批处理
10. `dialogues` 角色对白批处理
11. `script` 剧本正文批处理
12. `memory` 当前批次正文摘要
13. `final` 最终完整剧本拼接

### 6.3 进入主流程后的初始化

关键函数：

- `_initial_fastgpt_variables()` `fastgpt_hybrid_workflow.py:355`
  - 中文意思：初始化全局变量字典

- `_restore_resume_state()` `fastgpt_hybrid_workflow.py:990`
  - 中文意思：从失败/暂停快照里恢复运行状态

- `_apply_framework_outputs_to_variables()` `fastgpt_hybrid_workflow.py:1088`
  - 中文意思：把 framework 阶段产物应用回统一变量

- `_apply_normalized_episode_plan_to_variables()` `fastgpt_hybrid_workflow.py:1055`
  - 中文意思：把结构化分集计划转换成后续阶段统一输入

- `_apply_appearance_outputs_to_variables()` `fastgpt_hybrid_workflow.py:1123`
  - 中文意思：把服装映射结果拆成：
    - `character_registry`
    - `character_alias_registry`
    - `episode_alias_plan`
    - `appearance_continuity_memory`

### 6.4 单个阶段是怎么跑的

- `_run_fastgpt_stage()` `fastgpt_hybrid_workflow.py:726`
  - 中文意思：统一阶段执行器
  - 每个阶段都会在这里做：
    1. 先更新当前阶段和进度
    2. 记日志“第几次尝试”
    3. `runner.run_stage(...)` 发请求
    4. 对输出再次做契约校验
    5. `_sync_state_variables(...)` 回写到本地状态
    6. 如果网络错误则自动重试
    7. 如果格式错误则按阶段重试策略重试

如果你怀疑“某个阶段没发出去”或“某个阶段结果没进 state”，先断在这里。

---

## 7. 真正的 FastGPT 调用链：FastGPTClient

文件：

- `workflow_code_skeleton/app/services/fastgpt_client.py`
- `workflow_code_skeleton/app/services/fastgpt_contracts.py`

### 7.1 总入口

- `FastGPTClient.run_stage()` `fastgpt_client.py:125`
  - 中文意思：执行一个 FastGPT 阶段
  - 调用顺序：
    1. `contract_for(stage_name)`
    2. `contract.build_input_payload(variables)`
    3. `_build_wire_variables(...)`
    4. `_endpoint_for(stage_name)`
    5. `_build_request_body(...)`
    6. `_post_with_retries(...)`
    7. `response.json()`
    8. `_extract_output_payload(...)`
    9. `contract.validate_output_payload(...)`

### 7.2 契约层

文件：

- `workflow_code_skeleton/app/services/fastgpt_contracts.py`

关键位置：

- `STAGE_FRAMEWORK` 等阶段常量：`fastgpt_contracts.py:102-114`
- `LEGACY_INPUT_ALIASES`：`fastgpt_contracts.py:378`
  - 中文意思：代码里的标准变量名，映射到 FastGPT workflow 里的旧变量 ID / internal 变量名
- `LEGACY_OUTPUT_ALIASES`：`fastgpt_contracts.py:500`
  - 中文意思：FastGPT 返回的 internal 变量名，映射回代码里的标准输出名
- `STAGE_CONTRACTS`：`fastgpt_contracts.py:536`
  - 中文意思：每个阶段到底该收什么、该回什么
- `contract_for()`：`fastgpt_contracts.py:738`
  - 中文意思：按阶段名取契约

如果你要排查“为什么这个阶段变量名对不上”，优先看这里。

### 7.3 请求参数是怎么拼的

- `_build_wire_variables()` `fastgpt_client.py:214`
  - 中文意思：把代码里的变量字典转成 FastGPT 工作流实际吃的字段名
  - 这里会用 `LEGACY_INPUT_ALIASES`

- `_endpoint_for()` `fastgpt_client.py:256`
  - 中文意思：按阶段选择 URL / API key / chat_id
  - 这里是查环境变量最重要的地方

- `_build_request_body()` `fastgpt_client.py:293`
  - 中文意思：构造最终 POST body
  - 当前 body 重点字段有：
    - `chatId`
    - `stream: false`
    - `detail: true`
    - `variables`
    - `messages`

- `_post_with_retries()` `fastgpt_client.py:140`
  - 中文意思：真正发 HTTP 请求，并处理 502/503/504 等临时错误

### 7.4 FastGPT 返回结果是怎么被提取的

- `_extract_output_payload()` `fastgpt_client.py:320`
  - 中文意思：从 FastGPT HTTP 响应中提取阶段结果
  - 当前优先级很重要：
    1. 先读 `responseData / outputs / variables / updateVarResult`
    2. 再看 `choices[0].message.content`
    3. 再做其它文本兜底
  - 这就是 framework 阶段最近修过的关键点

- `_payload_from_candidate()` `fastgpt_client.py:466`
  - 中文意思：尝试把某个候选对象解释成契约输出

- `_normalize_payload_candidate()` `fastgpt_client.py:822`
  - 中文意思：把包装结构解开，比如：
    - `key/value`
    - `variable/value`
    - `updateVarResult`
    - `outputs`
    - `contract_json`

- `_iter_response_data_candidates()` `fastgpt_client.py:911`
  - 中文意思：优先递归遍历 FastGPT 结构化返回区

如果你再次遇到：

- `FastGPT 输出 string 不能为空`
- `某个 internal 变量明明写进了 workflow，但 Python 还是拿不到`

断点优先顺序：

1. `fastgpt_client.py:320`
2. `fastgpt_client.py:466`
3. `fastgpt_client.py:822`
4. `fastgpt_contracts.py:500`

---

## 8. 批处理逻辑：hooks / dialogues / script 到底怎么切批

文件：

- `workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py`

关键函数：

- `_run_batched_generation()` `fastgpt_hybrid_workflow.py:473`
  - 中文意思：本地批处理总控
  - 这里控制：
    - 按 `batch_size` 切批
    - 每批先跑 hooks
    - 再跑 dialogues
    - 再跑 script
    - 再更新 memory

- `get_episode_batch_payload()` `fastgpt_hybrid_workflow.py:1702`
  - 中文意思：取当前批次的分集计划切片

- `slice_normalized_episode_plan_for_batch()` `fastgpt_hybrid_workflow.py:1719`
  - 中文意思：从结构化分集计划里切出当前批次

- `slice_episode_alias_plan_for_batch()` `fastgpt_hybrid_workflow.py:1531`
  - 中文意思：从逐集服装别名计划里切出当前批次

- `_update_appearance_continuity_memory()` `fastgpt_hybrid_workflow.py:1645`
  - 中文意思：更新跨批次服装连续性记忆

如果你怀疑：

- 第 6-10 集吃到了第 1-5 集的计划
- 服装版本在跨批次时突然回退
- 批次拼接错乱

直接在这几个函数里打断点最有效。

---

## 9. 状态同步：为什么后端有值但前端不显示

### 9.1 先从 variables 写回 WorkflowState

- `_sync_state_variables()` `fastgpt_hybrid_workflow.py:902`
  - 中文意思：把标准变量写回 `WorkflowState`
  - 这里还负责把标准变量同步到 legacy 变量位，比如：
    - `TITLE_VAR`
    - `STORY_OUTLINE_VAR`
    - `EPISODE_PLAN_NORMALIZED_VAR`
    - `APPEARANCE_MAPPING_VAR`

### 9.2 再从 WorkflowState 写回 snapshot

- `WorkflowRuntime.sync_from_state()` `task_manager.py:326`
  - 中文意思：把 `WorkflowState` 压缩成快照里的 `artifacts`
  - 页面显示的大部分内容都来自这里同步出来的 `artifacts`

### 9.3 再从 snapshot 过滤成前端可见版本

- `_public_snapshot()` `task_manager.py:507`
  - 中文意思：决定前端最终能看到哪些字段
  - 这里很重要，因为：
    - 中途 debug 变量不应该原样泄漏给前端
    - 失败任务和完成任务的可见字段也不一样

### 9.4 前端渲染

- `renderSnapshot()` `app.js:305`
  - 中文意思：把 `/api/projects/<id>` 返回的数据画到页面上

- `loadProjects()` `app.js:589`
  - 中文意思：加载项目列表并决定当前选中哪个项目

- `loadProjectDetail()` `app.js:571`
  - 中文意思：读取某个项目的完整快照

- `pollWorkspace()` `app.js:966`
  - 中文意思：轮询刷新工作台

---

## 10. 暂停 / 恢复 / 失败重试 / 终止

### 前端入口

- `pauseTask()` `app.js:641`
- `resumeTask()` `app.js:650`
- `terminateTask()` `app.js:662`

### 后端入口

- `pause_task()` `server.py:328` -> `task_manager.pause_task()` `task_manager.py:1102`
- `resume_task()` `server.py:337` -> `task_manager.resume_task()` `task_manager.py:1123`
- `retry_task()` `server.py:346` -> `task_manager.retry_task()` `task_manager.py:1144`
- `terminate_task()` `server.py:355` -> `task_manager.terminate_task()` `task_manager.py:1209`

### 暂停恢复核心机制

- `TaskControl.checkpoint()` `task_manager.py:182`
  - 中文意思：安全暂停点
- `WorkflowRuntime.checkpoint()` `task_manager.py:223`
  - 中文意思：在阶段切换或等待期间检查是否需要暂停/终止
- `_checkpoint()` `fastgpt_hybrid_workflow.py:881`
  - 中文意思：主编排里统一触发检查点

如果你发现“点了暂停但还继续跑很久”，通常不是暂停坏了，而是当前正在等待：

- FastGPT HTTP 请求返回
- 或当前阶段执行到下一个 checkpoint

---

## 11. 导出完整剧本

文件：

- `workflow_code_skeleton/app/services/task_manager.py`
- `workflow_code_skeleton/app/utils/txt_to_docx.py`

关键函数：

- `saveFinalScript()` `app.js:682`
  - 中文意思：前端下载按钮入口

- `download_project()` `server.py:382`
  - 中文意思：下载接口

- `save_final_script()` `task_manager.py:1270`
  - 中文意思：后端导出逻辑
  - 当前会：
    1. 生成 `.txt`
    2. 转 `.docx`
    3. 打包成 `.zip`

---

## 12. 现在最值得记住的 5 个文件

如果你以后又忘了，只先看这 5 个文件就够了：

1. `workflow_code_skeleton/app/web/static/app.js`
   - 前端按钮、发请求、轮询、渲染
2. `workflow_code_skeleton/app/server.py`
   - Flask 路由层
3. `workflow_code_skeleton/app/services/task_manager.py`
   - 任务线程、快照、暂停恢复、导出
4. `workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py`
   - 真正的本地主流程编排
5. `workflow_code_skeleton/app/services/fastgpt_client.py`
   - 真正的 FastGPT HTTP 调用和返回解析

---

## 13. 常见问题 -> 最快断点建议

### 13.1 点击开始没反应

先看：

- `app.js:626` `startGeneration()`
- `server.py:289` `start_workflow()`
- `task_manager.py:701` `start_task()`

### 13.2 任务创建了，但线程没继续跑

先看：

- `task_manager.py:1022` `_run_task()`
- `runner.py:12` `run_configured_workflow()`

### 13.3 framework 阶段又报“输出为空 / string 不能为空”

先看：

- `fastgpt_hybrid_workflow.py:726` `_run_fastgpt_stage()`
- `fastgpt_client.py:125` `run_stage()`
- `fastgpt_client.py:320` `_extract_output_payload()`
- `fastgpt_contracts.py:536` `STAGE_CONTRACTS`
- `fastgpt_contracts.py:500` `LEGACY_OUTPUT_ALIASES`

### 13.4 FastGPT 明明回了值，但 Python 没拿到

先看：

- `fastgpt_client.py:320` `_extract_output_payload()`
- `fastgpt_client.py:466` `_payload_from_candidate()`
- `fastgpt_client.py:822` `_normalize_payload_candidate()`

### 13.5 某阶段输入变量不对

先看：

- `fastgpt_client.py:214` `_build_wire_variables()`
- `fastgpt_contracts.py:378` `LEGACY_INPUT_ALIASES`
- `workflow_code_skeleton/app/workflow_ids.py`

### 13.6 页面显示不对，但后端好像已经成功了

先看：

- `fastgpt_hybrid_workflow.py:902` `_sync_state_variables()`
- `task_manager.py:326` `WorkflowRuntime.sync_from_state()`
- `task_manager.py:507` `_public_snapshot()`
- `app.js:305` `renderSnapshot()`

### 13.7 批次乱了 / 集数切片错了

先看：

- `fastgpt_hybrid_workflow.py:473` `_run_batched_generation()`
- `fastgpt_hybrid_workflow.py:1702` `get_episode_batch_payload()`
- `fastgpt_hybrid_workflow.py:1719` `slice_normalized_episode_plan_for_batch()`
- `fastgpt_hybrid_workflow.py:1531` `slice_episode_alias_plan_for_batch()`

---

## 14. 一个实用排障顺序

以后如果你只想“最快定位”，推荐固定按这个顺序看：

1. 前端是否真的发了 `/api/workflows/start`
2. Flask 的 `start_workflow()` 有没有拿到正确 payload
3. `TaskManager.start_task()` 是否创建了线程
4. `_run_task()` 是否进入 `run_configured_workflow()`
5. `run_fastgpt_hybrid_workflow()` 是否走到了目标阶段
6. `_run_fastgpt_stage()` 是否真的调用了 `runner.run_stage()`
7. `FastGPTClient.run_stage()` 是否拿到了 HTTP 响应
8. `_extract_output_payload()` 是否正确解析
9. `contract.validate_output_payload()` 是否通过
10. `_sync_state_variables()` 和 `sync_from_state()` 是否把结果写回快照
11. `/api/projects/<id>` 返回的快照里是否有目标字段
12. `renderSnapshot()` 是否正确渲染

这 12 步，基本能覆盖 90% 的问题。

---

## 15. 最后一句

如果你以后只记一件事，请记住：

**主流程排障最核心的三层是：**

1. `fastgpt_hybrid_workflow.py`：决定“应该跑什么阶段”
2. `fastgpt_client.py`：决定“FastGPT 的响应到底有没有被正确读出来”
3. `task_manager.py`：决定“读出来的结果有没有真正同步到页面能看到的快照”

这三层打通了，大部分问题都会很好定位。
