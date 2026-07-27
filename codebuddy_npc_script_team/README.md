# CodeBuddy NPC 专业剧本团队

这个目录是一套可推送到私有 CNB 仓库的测试包。它只服务于
`/new-workflow-test`，不会替换生产 FastGPT 工作流。

## 两种运行方式

### 1. CNB 平台模型

事件名：

```text
api_trigger_script_team
```

流水线使用 `npc:go` 运行七个创作角色，并在正文后生成
`story_state.json`。初稿经过软门禁后由终审与钩子编辑一次修复，最终稿通过
严格代码门禁才允许发布。

### 2. 自有 DeepSeek V4 Pro API

事件名：

```text
api_trigger_script_team_custom_api
```

该模式仍由 CodeBuddy NPC/CNB 负责云端触发、沙箱、进度和角色流水线，
模型请求由自定义运行镜像直接调用你的 OpenAI 兼容 API。

逐节点确认使用独立事件：

```text
api_trigger_script_team_stage_custom_api
```

5002 会把已确认的上游产物压缩后传给该远程节点。自动跑到底与逐节点确认
都在 CNB 执行；只有远程失败后点击“本地兜底继续”才会调用5002本地节点。

需要在 CNB 私有仓库配置三个密钥/环境变量：

```text
DEEPSEEK_BASE_URL=https://你的接口地址/v1/chat/completions
DEEPSEEK_API_KEY=你的API Key
DEEPSEEK_MODEL=deepseek-v4-pro
```

不要把真实 API Key 写入 `.cnb.yml`、Git 仓库或5002前端。

## 部署

1. 在 CNB 创建一个私有仓库。
2. 把本目录内容放到仓库根目录并推送。
3. 等待 `main.push` 构建自定义运行镜像。
4. 创建至少具备触发构建和读取构建状态权限的 CNB 访问令牌。
5. 在5002的 `.env` 配置：

```text
CODEBUDDY_NPC_REPOSITORY=你的组织/仓库
CODEBUDDY_NPC_ACCESS_TOKEN=你的CNB访问令牌
CODEBUDDY_NPC_EVENT=api_trigger_script_team_custom_api
CODEBUDDY_NPC_STAGE_EVENT=api_trigger_script_team_stage_custom_api
CODEBUDDY_NPC_MODEL=deepseek-v4-pro
CODEBUDDY_NPC_CONTEXT_WINDOW=1m
```

6. 重启5002，打开 `/new-workflow-test`。

## 重要约束

- 用户填写的总集数是硬合同，流程动态生成第1集至第N集。
- 所有角色读取同一任务与上游产物。
- 正文对白编剧是唯一初稿作者。
- 状态记录器只提取事实，不参与改写。
- 默认每集一至两个核心场景，超出时必须记录必要性。
- 人物声音、集间连续和钩子规则由 `script-room/references` 统一提供。
- 终审与钩子编辑只做一次受控修订，不重新发明故事。
- 最终结果通过日志标记返回给5002：
  `__SCRIPT_TEAM_RESULT_BEGIN__` / `__SCRIPT_TEAM_RESULT_END__`。

## 产物与中断恢复

CNB 构建容器中的 `.script-team/` 和 `/tmp/script-team/` 是临时目录。流水线会把
最终门禁报告与终审稿写入发布阶段日志，5002 再将任务书、故事架构、人物方案、
分集卡、初稿、故事状态、终审稿和门禁报告实体化到：

```text
debug/codebuddy_npc_jobs/<job_id>/
```

严格门禁发现问题时仍会发布并保留终审稿，但会把门禁错误或警告返回 5002，
不会把“有待修项”伪装成质量通过。

对于旧构建或发布阶段被跳过的构建，5002 可从成功 NPC 阶段的文件写入日志恢复
已有产物。若终审稿已经生成，只需恢复并重新运行代码门禁，不需要重新调用前面的
NPC；若正文阶段本身没有成功生成完整文件，则必须从该创作阶段重新生成。
