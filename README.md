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

- `script_title_content`
- `story_outline`
- `user_characters`
- `user_scenes`
- `episode_plan`

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
- `xxx.zip`

如果当前项目包含服装映射相关结构化数据，还会一起导出：

- `character_registry.json`
- `character_alias_registry.json`
- `episode_alias_plan.json`
- `appearance_mapping.json`
- `appearance_continuity_memory.json`
- `normalized_episode_plan.json`

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
  "script_title_content": "string",
  "story_outline": "string",
  "user_characters": "string",
  "user_scenes": "string",
  "episode_plan": "string"
}
```

如果 FastGPT 工作流最后返回的是这个 JSON 字符串，当前解析层可以直接识别。

---

当前仓库只保留这一份 README 作为有效说明文档。
