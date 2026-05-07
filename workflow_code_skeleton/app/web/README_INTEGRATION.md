# 框架策划工作台 v2 集成说明

这是一个前端 Mock 版本，用于先跑通“基础配置 → 世界观 → 人设 → 三幕十五节拍卡点 → 人物故事线 → 改编指引 → JSON 输出”的页面流程。

## 设计调整

v2 已经把“三幕十五节拍”和“卡点时间轴”合并为一个模块：`threeActFifteenBeatCheckpointTimeline`。

原因：卡点并不是独立于十五节拍之外的另一套结构，而是十五节拍落到集数后的时间轴表达。因此本版本不再保留单独的 `checkpointPlan`，避免冗余。

## 推荐放置位置

如果当前项目使用 Flask 模板结构，可先放在：

```text
workflow_code_skeleton/app/web/templates/framework_planner.html
workflow_code_skeleton/app/web/static/framework_planner.css
workflow_code_skeleton/app/web/static/framework_planner.js
```

然后新增路由：

```text
/framework-planner
```

如果暂时不接 Flask，也可以直接打开 `framework_planner_standalone.html` 预览。

## 当前状态逻辑

- 基础配置确认后锁定，才允许进入世界观。
- 世界观确认后锁定，才允许进入人设。
- 人设确认后锁定，才允许进入三幕十五节拍卡点规划。
- 三幕十五节拍卡点确认后锁定，才允许进入人物故事线。
- 人物故事线确认后锁定，才允许进入整体改编指引。
- 改编指引确认后锁定，才允许输出最终 JSON。

上游确认并进入下游后，不允许继续修改上游。这样可以避免后续内容和上游设定不一致。

## 后端接入点

后续真实接后端时，优先替换 `framework_planner.js` 中的 `planningApi`：

```js
planningApi.generateWorldview()
planningApi.generateCharacters()
planningApi.generateBeatPlan()
planningApi.generateStorylines()
planningApi.generateGuide()
```

建议接口返回结构与 `buildPayload()` 保持一致。

## 输出 JSON 核心字段

```json
{
  "frameworkPlan": {
    "worldviewPlan": "...",
    "characterPlan": "...",
    "threeActFifteenBeatCheckpointTimeline": [],
    "threeActFifteenBeatCheckpointExplanation": "...",
    "characterStorylines": [],
    "adaptationGuide": []
  },
  "userDecisions": {
    "storylineActions": []
  }
}
```
