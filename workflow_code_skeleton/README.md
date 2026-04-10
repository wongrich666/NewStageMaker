# Script Workflow Runner

这个项目把 `剧本生成_0401_loops.json` 里的工作流，落成了可执行的 Python 编排器。

## 已对齐的流程

1. 集数一致性检查
2. 世界观提取 -> 生成 -> 审核 -> 修订循环
3. 人设生成 -> 审核 -> 修订循环 -> 人物小传整理
4. 核心场景提炼/复用 -> 场景生成 -> 审核 -> 修订循环 -> 核心场景整理
5. 当前 5 集开头冲突钩子批处理
6. 当前 5 集角色对话批处理
7. 当前 5 集剧本正文批处理
8. 当前 5 集正文记忆整理
9. 最终完整剧本拼接

## 运行方式

安装依赖：

```bash
pip install -r workflow_code_skeleton/requirements.txt
```

准备 `.env`：

```bash
copy workflow_code_skeleton\\.env.example workflow_code_skeleton\\.env
```

### CLI

运行一次完整工作流：

```bash
python main.py run ^
  --input workflow_code_skeleton/app/examples/sample_input.json ^
  --workflow-spec C:\\Users\\Administrator\\Downloads\\剧本生成_0401_loops.json ^
  --output output.txt ^
  --debug-state debug_state.json
```

为了兼容旧调用，直接写 `python main.py --input ...` 也仍然会默认走 `run`。

### Web

启动网页服务：

```bash
python main.py
```

也可以显式指定服务参数：

```bash
python main.py serve ^
  --workflow-spec C:\\Users\\Administrator\\Downloads\\剧本生成_0401_loops.json ^
  --host 127.0.0.1 ^
  --port 5000
```

浏览器打开：

```text
http://127.0.0.1:5000
```

网页支持：

- 用户注册、登录、退出
- 模型选择
- 开始生成、暂停生成、继续生成、终止生成
- 清空全部
- 保存最终剧本
- 按用户账号缓存表单草稿和最近项目快照

说明：

- 用户数据保存在 `workflow_code_skeleton/runtime_data/users.db`，密码会加密保存。
- 每个用户只能读取和操作自己账户下创建的生成项目。
- 模型选择在页面上只显示别名，例如 DeepSeek 显示为 `XKD`，Gemini 显示为 `XKG`。
- 暂停会在“当前节点完成后”生效，不会强制中断正在执行的单次模型调用。
- 服务端运行快照会保存到 `workflow_code_skeleton/runtime_data/projects/`。
- 导出的最终剧本会保存到 `workflow_code_skeleton/runtime_data/exports/`。

## 输入字段

输入 JSON 支持中英文键名，核心字段如下：

- `title` / `剧本标题`
- `episode_word_count` / `每集正文字数`
- `total_episodes` / `总集数`
- `story_outline` / `故事大纲`
- `core_scene_input` / `核心场景`
- `character_bios` / `人物小传`
- `episode_plan` / `分集计划`

## 说明

- FastGPT 智能体内部负责生成、审核、修订，并向 Python 返回当前阶段成品。
- Python 本地负责批次 +5、当前批次起始集数传递、分集计划裁剪、全量钩子/对白/正文拼接、记忆覆盖、暂停恢复和异常缓存。
- 正文记忆是覆盖式：每批正文生成后，记忆工作流只输出刚刚 5 集的记忆；代码把它保存为下一批正文的 `last_summary`。
