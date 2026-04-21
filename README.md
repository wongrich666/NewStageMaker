# AI 剧本生成工作台

这是一个“本地编排逻辑 + FastGPT 工作流 API”的混合式剧本生成系统。

它提供两种使用方式：

- 网页工作台：注册登录后，通过可视化页面创建、运行、暂停、继续、终止和保存剧本任务
- CLI：直接读取输入 JSON，执行一次完整工作流，便于联调和排障

当前主流程已经改成：

- 用户只需要输入 `用户期待`、`角色数量`、`总集数`
- 系统先调用 FastGPT 的“剧本框架撰写”工作流，生成：
  - 故事大纲
  - 人物小传
  - 核心场景
  - 分集计划
- 后续所有主流程阶段继续基于这些中间产物运行

## 主要能力

- 用户注册、登录、修改用户名、修改密码
- 同一用户可同时开启多个任务
- 多个用户可并发使用，项目彼此隔离
- 离开网页但不退出登录时，后台任务继续运行
- 失败后保留阶段、进度和中间产物，可继续生成
- 支持暂停、继续、终止
- 最终导出 `txt + docx + zip`
- 支持社区公开作品展示
- 支持若干单次 FastGPT 辅助工具：
  - 爆款文审核
  - 换皮
  - 增加爽感
  - 只换人设

## 仓库结构

```text
new_scriptmaker/
├─ main.py
├─ README.md
└─ workflow_code_skeleton/
   ├─ .env.example
   ├─ requirements.txt
   ├─ runtime_data/
   ├─ app/
   │  ├─ main.py
   │  ├─ server.py
   │  ├─ config.py
   │  ├─ models/
   │  ├─ orchestrators/
   │  ├─ services/
   │  ├─ utils/
   │  └─ web/
   └─ output/
```

说明：

- 根目录 `main.py` 是统一入口
- 主要业务代码在 `workflow_code_skeleton/app/`
- 运行时项目快照、用户数据、导出文件都保存在 `workflow_code_skeleton/runtime_data/`

## 快速开始

### 1. 安装依赖

```bash
pip install -r workflow_code_skeleton/requirements.txt
```

### 2. 准备环境变量

复制示例配置：

```bash
copy workflow_code_skeleton\.env.example workflow_code_skeleton\.env
```

至少需要检查这些配置：

```env
WORKFLOW_BACKEND=fastgpt
FASTGPT_CHAT_COMPLETIONS_URL=http://your-fastgpt-host/api/v1/chat/completions

FASTGPT_FRAMEWORK_API_KEY=
FASTGPT_CONSISTENCY_API_KEY=
FASTGPT_EPISODE_PLAN_NORMALIZE_API_KEY=
FASTGPT_WORLDVIEW_API_KEY=
FASTGPT_CHARACTERS_API_KEY=
FASTGPT_SCENES_API_KEY=
FASTGPT_HOOKS_API_KEY=
FASTGPT_DIALOGUES_API_KEY=
FASTGPT_SCRIPT_API_KEY=
FASTGPT_MEMORY_API_KEY=
FASTGPT_FINAL_API_KEY=
```

说明：

- `FASTGPT_CHAT_COMPLETIONS_URL` 必须填写完整地址，代码不会自动拼接 `/api/v1/chat/completions`
- 如果所有阶段共用一个 FastGPT 应用 Key，也可以只填 `FASTGPT_API_KEY`
- 如果每个阶段是不同的 FastGPT 工作流，就分别填写各阶段的 API Key
- 新增的“剧本框架撰写”阶段 API Key 变量名是：

```env
FASTGPT_FRAMEWORK_API_KEY=
```

辅助工具如果要启用，也可以填写：

```env
FASTGPT_HOT_REVIEW_API_KEY=
FASTGPT_RESKIN_API_KEY=
FASTGPT_PUNCHUP_API_KEY=
FASTGPT_CHARACTER_RESKIN_API_KEY=
```

### 3. 启动网页服务

直接运行：

```bash
python main.py
```

默认会启动网页服务。

也可以显式指定：

```bash
python main.py serve --host 0.0.0.0 --port 5000
```

本机访问：

```text
http://127.0.0.1:5000
```

如果要让同一局域网其他设备访问，请使用启动日志里显示的内网 IP，例如：

```text
http://192.168.x.x:5000
```

## 网页使用说明

### 登录与创建

1. 先注册或登录
2. 点击“新建剧本”
3. 填写：
   - 用户期待
   - 角色数量
   - 总集数
4. 选择模型入口
5. 点击“开始生成”

说明：

- 当前主流程在 FastGPT 模式下，网页里的模型选择主要是工作台层面的配置入口
- 真正每个 FastGPT 工作流节点使用什么模型，通常仍由 FastGPT 后台工作流本身决定

### 多任务使用方式

- 同一账号可以同时开启多个任务
- 点击“新建剧本”会打开新的工作页
- 旧页面里的任务会继续在后台运行
- 页面之间互不抢占当前项目
- 只要后端服务进程还在，离开页面也不会中断任务

### 任务控制

支持以下操作：

- 开始生成
- 暂停生成
- 继续生成
- 终止生成
- 继续失败任务
- 保存最终剧本
- 删除项目

说明：

- 暂停和终止通常会在“当前阶段调用结束后”生效，不会强行中断已经发出的单次 FastGPT 请求
- 如果因为网络或远端 FastGPT 故障导致失败，系统会保留失败前阶段、进度和中间产物

### 最终导出

点击“保存最终剧本”后，系统会：

1. 生成 `.txt`
2. 转换为 `.docx`
3. 打包为 `.zip`

导出目录：

```text
workflow_code_skeleton/runtime_data/exports/
```

## CLI 用法

如果你想绕过网页直接执行一次工作流，可以使用 CLI：

```bash
python main.py run ^
  --input workflow_code_skeleton/app/examples/sample_input.json ^
  --output result.txt ^
  --debug-state debug_state.json
```

也兼容直接传裸参数的老写法，`main.py` 会自动判断是 `run` 还是 `serve`。

### CLI 输入示例

现在推荐的最小输入：

```json
{
  "user_expectation": "我想要一个60集的古风复仇成长短剧，前期被压制，中期逆袭，后期身份反转。",
  "character_count": 6,
  "total_episodes": 60
}
```

系统也兼容旧输入模式，如果你已经有这些完整材料，也可以直接传：

- `story_outline`
- `character_bios`
- `core_scene_input`
- `episode_plan`

## 后端原理概览

### 总体架构

这个系统不是“所有逻辑都写在 Python 里”，也不是“所有控制都丢给 FastGPT”。

它采用分工式架构：

- FastGPT 负责内容生成型工作
- Python 本地负责流程控制型工作

### FastGPT 负责什么

FastGPT 负责每个业务阶段的内容产出，包括：

- 剧本框架撰写
- 集数一致性检查
- 分集计划规范化
- 世界观生成
- 人物设定生成
- 核心场景生成
- 开头冲突钩子生成
- 角色对话生成
- 剧本正文生成
- 批次记忆整理
- 最终完整剧本拼接

其中“审核 / 修订 / 重写”这类业务循环，当前约定都放在 FastGPT 工作流内部完成。
也就是说，Python 调用一个阶段时，期望拿到的是该阶段的成品，而不是半成品。

### Python 本地负责什么

Python 本地主要负责：

- 用户登录与权限隔离
- 项目与任务管理
- 多任务并发执行
- 暂停、继续、终止
- 阶段进度更新
- 中间产物缓存
- 失败恢复
- 批次循环
- 当前批次分集计划切片
- 钩子 / 对话 / 正文的全量拼接
- 批次记忆覆盖
- 最终文件导出

### 主流程顺序

当前 FastGPT 混合工作流主干是：

1. `framework`
   - 输入：用户期待、角色数量、总集数
   - 输出：故事大纲、人物小传、核心场景、分集计划
2. `consistency`
   - 检查分集计划与总集数是否一致
3. `episode_plan_normalize`
   - 把分集计划整理成结构化 JSON
4. `worldview`
   - 生成故事规则 / 世界观
5. `characters`
   - 生成人物设定
6. `scenes`
   - 生成核心场景
7. `hooks`
   - 按批次生成开头冲突钩子
8. `dialogues`
   - 按批次生成角色对话
9. `script`
   - 按批次生成剧本正文
10. `memory`
    - 只整理“刚刚生成的这一批”记忆
11. `final`
    - 拼接最终完整剧本

### 为什么要有“分集计划规范化”

原始分集计划通常是长文本，直接整段传给后续阶段会带来两个问题：

- 上下文过长
- 每个批次都读全量文本，不稳定

所以系统会先把原始分集计划整理成结构化 JSON，例如：

```json
{
  "parsed_episode_count": 2,
  "episodes": [
    {
      "episode": 1,
      "title": "",
      "content": "第一集原始计划内容"
    },
    {
      "episode": 2,
      "title": "",
      "content": "第二集原始计划内容"
    }
  ]
}
```

之后本地代码只把“当前批次对应的那几集”切出来，传给 hooks / dialogues / script。

### 批次逻辑怎么工作

默认 `BATCH_SIZE=5`，所以正文部分通常按 5 集一批运行。

例如 12 集的剧本会被拆成：

- 1 到 5 集
- 6 到 10 集
- 11 到 12 集

每一批的处理流程大致是：

1. 取当前批次的规范化分集计划切片
2. 生成当前批次 hooks
3. 生成当前批次 dialogues
4. 生成当前批次 script
5. 调用 memory，把这一批正文整理成新的 `last_summary`
6. 用新的 `last_summary` 覆盖旧值
7. 继续下一批

这里要注意：

- `last_summary` 是覆盖式的，不保存完整历史
- 下一批只读取最近一批的记忆

## 数据保存位置

### 用户与账户

```text
workflow_code_skeleton/runtime_data/users.db
```

说明：

- 用户名不可重复
- 密码会以安全摘要形式保存，不是明文

### 项目快照

```text
workflow_code_skeleton/runtime_data/projects/
```

每个项目会保存：

- 当前状态
- 当前阶段
- 当前批次
- 进度百分比
- 输入参数
- 中间产物
- 最终结果
- 日志

### 导出文件

```text
workflow_code_skeleton/runtime_data/exports/
```

## 常见说明

### 1. 为什么关闭页面后任务还能继续

因为真正执行工作流的是 Flask 后端里的后台线程，不是浏览器页面。

只要：

- 你没有退出登录
- 后端服务还在运行

那么页面关掉后，任务仍会继续。

### 2. 失败后为什么还能继续生成

因为每个阶段执行前后，系统都会持续保存项目快照。

所以一旦网络波动、FastGPT 返回 502、或者阶段解析失败：

- 当前项目不会被清空
- 已完成阶段的中间产物会保留
- 可以从失败点重新发起继续任务

### 3. 如果后端服务重启会怎么样

当前任务执行模型是“后台线程”。

这意味着：

- 浏览器关闭不会中断任务
- 但如果 Flask 服务进程重启，正在运行的线程任务会停止

系统会把这些任务标记为已停止，方便你重新开始或继续。

## 开发提示

### 快速校验

后端代码可用：

```bash
python -m compileall workflow_code_skeleton/app
```

前端脚本可用：

```bash
node --check workflow_code_skeleton/app/web/static/app.js
```

### 重要入口文件

- 根入口：[main.py](./main.py)
- 应用入口：[workflow_code_skeleton/app/main.py](./workflow_code_skeleton/app/main.py)
- Flask 服务：[workflow_code_skeleton/app/server.py](./workflow_code_skeleton/app/server.py)
- 主流程编排：[workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py](./workflow_code_skeleton/app/orchestrators/fastgpt_hybrid_workflow.py)
- FastGPT 契约：[workflow_code_skeleton/app/services/fastgpt_contracts.py](./workflow_code_skeleton/app/services/fastgpt_contracts.py)
- 任务管理：[workflow_code_skeleton/app/services/task_manager.py](./workflow_code_skeleton/app/services/task_manager.py)

## 补充

这个仓库当前重点是“把剧本生成流程稳定跑通”，所以设计上更强调：

- 任务可恢复
- 中间产物可缓存
- 阶段职责清晰
- FastGPT 与本地代码边界明确

如果后续还要继续扩展新的 FastGPT 工作流，推荐遵循现在这套方式：

1. 在 FastGPT 中定义清晰输入输出
2. 在本地注册 stage contract
3. 让内容生成交给 FastGPT
4. 让循环、拼接、缓存、恢复交给本地代码
