# Idea to Scripts · 腾讯工作流版

这是一个本地剧本生产工作台。当前远程生成链路只调用腾讯云智能体开发平台上的 18 个工作流，每个阶段使用独立 AppKey。

## 首次配置

1. 在腾讯平台分别将 01～12_04 发布为“单工作流应用”。
2. 复制 `workflow_code_skeleton/.env.example` 为 `workflow_code_skeleton/.env`。
3. 把每个应用发布页中的 AppKey 填入对应的 `TENCENT_WORKFLOW_*_API_KEY`。
4. 在腾讯远端完成变量、提示词和结束节点修复后重新发布；本地导出 JSON 仅作为腾讯下载快照，不要手工修改。

本届省赛使用独立部署环境，调用地址是：

```text
http://101.42.184.216/adp/v2/chat
```

省赛独立部署与腾讯公有云使用不同的 AppKey 命名空间，二者不能混用。省赛 v2 请求把开始节点参数放在顶层 `WorkflowInput`，因此 `.env` 同时配置：

```text
TENCENT_WORKFLOW_V2_INPUT_MODE=workflow_input
```

如果以后切回腾讯公有云，可把地址改为 `https://wss.lke.cloud.tencent.com/adp/v2/chat`，并把输入模式改为 `custom_variables`。

如果控制台为某阶段提供独立调用地址，可在 `.env` 增加该阶段的 `TENCENT_WORKFLOW_<阶段>_API_URL`；未设置时统一使用 `TENCENT_ADP_API_URL`。

## Windows 启动

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1
```

默认访问地址：`http://127.0.0.1:5001`

## 关键契约

- 01～07 使用腾讯工作流导出的开始节点变量名，并从各自的 `Output.<字段>` 取业务结果。
- 08～12_04 通过本地编排串接场景字典、服饰映射、分集计划、冲突钩子和剧本正文。
- `episodeWordCount` 直接映射为工作流入参 `character_count`。该值就是“每集目标字数”，没有分钟数或时长换算层。
- 响应解析器支持腾讯响应信封、结束节点 `Output` 对象、阶段外层字段、JSON 字符串和二次 JSON 字符串的递归解包。
- 未配置当前阶段 AppKey 时会明确报出缺少的环境变量，不会回退到其他接口。

完整阶段表见 [腾讯工作流契约](workflow_code_skeleton/TENCENT_WORKFLOW_CONTRACTS.md)。

## 审计与测试

只审计 18 个导出工作流：

```powershell
.\.venv\Scripts\python.exe scripts\normalize_tencent_workflow_exports.py
```

写入标准化修复：

```powershell
.\.venv\Scripts\python.exe scripts\normalize_tencent_workflow_exports.py --fix
```

运行契约测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s workflow_code_skeleton\tests -v
```

测试会逐个核对注册表与本地导出的工作流 ID、开始节点输入名、结束节点外层字段，并验证字数直传、SSE 解析和嵌套 JSON 解包。
