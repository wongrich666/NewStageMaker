请在当前 test-5001 分支中接入一个“剧本框架策划工作台”前端页面。不要破坏现有主工作流，不要立刻接真实后端，先以 Mock 页面形式跑通流程。

我提供了 3 个核心文件：

- framework_planner.html
- framework_planner.css
- framework_planner.js

目标：新增一个可访问页面 `/framework-planner`，用于后续接入剧本框架生成链路。

页面流程必须保持如下顺序：

1. 基础配置
2. 世界观方案生成、编辑、更新、确认
3. 人设方案生成、编辑、更新、确认
4. 三幕十五节拍卡点规划时间轴
5. 三幕十五节拍卡点说明
6. 不同人物故事线生成、编辑、更新、确认；每条线可选择保留 / 精简 / 删除
7. 查看详细不同人物故事线
8. 整体改编意见
9. 最终 JSON 策划包输出

注意：

- 三幕十五节拍和卡点时间轴不是两个独立模块，要合并为一个模块。
- 卡点说明是对同一条十五节拍时间轴的详细解释，不要再另建一个重复的卡点规划数据结构。
- 上游模块必须确认后才能进入下游。
- 上游确认并进入下游后，不允许继续修改上游。
- 所有编辑都必须先“更新”，再“确认”，确认后才解锁下游。
- 当前页面使用 localStorage 保存本地状态。
- 后端未接入前，请保留 planningApi 的 Mock 实现。

建议集成方式：

- 如果项目使用 Flask templates/static，把 HTML 放到 templates，CSS/JS 放到 static。
- 修正 HTML 中 CSS/JS 的引用路径，使其适配当前项目。
- 新增路由 `/framework-planner` 返回该页面。
- 不要重构已有工作流代码。
- 不要改动现有剧本生成接口。
- 先保证页面能正常打开、按钮状态正常、JSON 能输出。

后续真实接后端时，替换 `framework_planner.js` 里的 `planningApi`：

- generateWorldview
- generateCharacters
- generateBeatPlan
- generateStorylines
- generateGuide

最终 JSON 结构以 `buildPayload()` 为准。
