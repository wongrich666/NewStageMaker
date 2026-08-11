# 腾讯工作流调用契约

代码中的唯一事实源是：

- `app/services/tencent_workflow_registry.py`：18 个工作流的 ID、输入映射、输出外层字段和 AppKey 环境变量。
- `app/services/tencent_workflow_client.py`：请求、SSE/JSON 响应处理、嵌套 JSON 解包和阶段输出校验。
- `tests/test_tencent_workflow_integration.py`：注册表与本地导出文件的一致性测试。

## 阶段与独立 AppKey

| 阶段 | 工作流 | 结束节点字段 | AppKey 环境变量 |
|---|---|---|---|
| 01 | 提取故事梗概 | `Output.confirmed_info` | `TENCENT_WORKFLOW_01_API_KEY` |
| 02 | 世界观 | `Output.worldview` | `TENCENT_WORKFLOW_02_API_KEY` |
| 03 | 人设方案撰写 | `Output.character` | `TENCENT_WORKFLOW_03_API_KEY` |
| 04 | 三幕十五节拍生成 | `Output.beat` | `TENCENT_WORKFLOW_04_API_KEY` |
| 05 | 人物故事线整理 | `Output.storyline` | `TENCENT_WORKFLOW_05_API_KEY` |
| 06 | 整体改编指引 | `Output.adaptation` | `TENCENT_WORKFLOW_06_API_KEY` |
| 07 | 最终框架策划包 | `Output.framework` | `TENCENT_WORKFLOW_07_API_KEY` |
| 08 | 场景字典提炼 | `Output.output` | `TENCENT_WORKFLOW_08_API_KEY` |
| 09 | 人物服饰映射 | `Output.alias` | `TENCENT_WORKFLOW_09_API_KEY` |
| 10 | 丰富分集计划 | `Output.episodeplan` | `TENCENT_WORKFLOW_10_API_KEY` |
| 11_01 | 开头冲突钩子撰写 | `Output.conflicts` | `TENCENT_WORKFLOW_11_01_API_KEY` |
| 11_02 | 开头冲突钩子审核 | `Output.conflictreview` | `TENCENT_WORKFLOW_11_02_API_KEY` |
| 11_03 | 开头冲突钩子修订 | `Output.rewrite` | `TENCENT_WORKFLOW_11_03_API_KEY` |
| 11_04 | 开头冲突钩子记忆 | `Output.memory` | `TENCENT_WORKFLOW_11_04_API_KEY` |
| 12_01 | 剧本正文撰写 | `Output.script` | `TENCENT_WORKFLOW_12_01_API_KEY` |
| 12_02 | 剧本正文审核 | `Output.scriptreview` | `TENCENT_WORKFLOW_12_02_API_KEY` |
| 12_03 | 剧本正文修订 | `Output.script` | `TENCENT_WORKFLOW_12_03_API_KEY` |
| 12_04 | 剧本正文记忆 | `Output.memory` | `TENCENT_WORKFLOW_12_04_API_KEY` |

每个阶段还支持可选的 `TENCENT_WORKFLOW_<阶段>_API_URL`。没有单独设置时，使用 `TENCENT_ADP_API_URL`。

本届省赛使用独立部署地址 `http://101.42.184.216/adp/v2/chat`。该环境中的 AppKey 不能发送到腾讯公有云地址，否则会返回 `4505004 应用密钥无效`。

省赛环境要求把工作流开始节点参数放在顶层 `WorkflowInput`：

```json
{
  "AppKey": "当前阶段的 AppKey",
  "Contents": [
    {"Type": "text", "Text": "执行工作流"}
  ],
  "WorkflowInput": {
    "开始节点变量名": "字符串值"
  }
}
```

通过 `TENCENT_WORKFLOW_V2_INPUT_MODE=workflow_input` 启用该格式。腾讯公有云环境则使用 `custom_variables`。

如果某阶段显式配置的是腾讯旧版 URL，客户端仍会自动切换为旧版字段格式。

## 字数传递

剧本工作流 12_01、12_02、12_03 的腾讯入参名仍为 `character_count`，但语义固定为“每集目标字数”：

```text
系统 episodeWordCount
  → 腾讯入参 character_count
```

没有 `minutes_per_episode`，也没有按分钟数估算字数的中间步骤。

## 响应解包

模型的业务 JSON 可能被平台再包一层或多层。客户端按以下方向递归解包：

```text
腾讯 HTTP/SSE 响应
  → v2 message.done / response.completed 或旧版 reply
  → content/data/result 等响应信封
  → Output
  → 当前阶段外层字段
  → 模型输出的业务 JSON 或剧本纯文本
```

因此以下形态都可以被识别：

```json
{"Output":{"script":"第1集……"}}
```

```json
{"data":"{\"Output\":{\"episodeplan\":\"{\\\"allEnrichedEpisodePlan\\\":[]}\"}}"}
```

## 已修复的导出契约

- 01：开始节点 `target_form` 改为 `target_format`。
- 02：提示词变量 `previous_worldview` 改为已声明的 `previous_worldview_plan`。
- 04：把已声明但未使用的 `keyword` 接入模型提示词。
- 07：开始节点 `adaption_direction` 改为 `adaptation_direction`；补全 `Output.framework`。
- 09：把已声明但未使用的 `framework` 接入模型提示词。
- 10：补全 `Output.episodeplan`。
- 11_02：把误复制的“冲突计划编写”提示词替换为真正的审核契约，固定输出 `passed`、`rewrite_required`、`blocking_issues` 等审核字段。
- 11_03：把 `feedback` 接入修订提示词；补全 `Output.rewrite`。
- 12_02：把 `user_feedback` 接入审核提示词。

这些是本地导出文件的修改。腾讯平台里的已发布应用不会自动同步，必须重新导入/更新并发布。
