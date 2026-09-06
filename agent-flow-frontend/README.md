# Idea to Scripts 代码驱动架构图

这是与现有 Flask WebUI 隔离的 React + Vite 展示子项目。页面读取仓库扫描生成的架构 manifest，使用三条纵向泳道展示：Level 1 系统模块 → Level 2 工作流/本地模块 → Level 3 腾讯工作流内部 START / LLM / END 节点。

## 启动

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\run_architecture_graph.ps1"
```

访问：<http://127.0.0.1:5173/>

也可以手动启动：

```powershell
python .\scripts\generate_architecture_manifest.py
cd .\agent-flow-frontend
npm install
npm run dev
```

## 页面交互

- 默认显示 Level 1 系统模块；
- 点击一级节点显示它的 Level 2 本地模块或工作流；
- 点击 Level 2 Workflow 显示真实 Level 3 腾讯内部节点；
- 点击节点打开输入、输出、调用关系、保存状态、模型参数和代码证据；
- 支持画布平移、滚轮缩放、MiniMap 和动态数据边；
- 节点可以自由拖动以避让线路；不能新建、重连或删除节点和边；
- 每个节点右上角的眼睛按钮可隔离当前数据流：保留节点分支、直接上下游和父级上下文，隐藏其他节点；再次点击或使用 `SHOW ALL` 恢复总览；
- 展开或收起 Level 2/3 时保留当前缩放比例和画布位置，不自动执行适应视图；
- 创作、编排、审核、记忆、持久化和平台内部数据流使用不同的低饱和深色；
- 箭头和层级虚线使用加粗的非缩放描边；聚焦模式下相关数据流进一步加粗并显示传输标签；
- 连线根据节点相对位置自动选择上下或左右端口；向上回流从侧面绕行，并使用不同偏移轨道避免 180° 共线；
- `RESET POS` 恢复纵向泳道默认位置；
- `LEVEL 1` 按钮恢复总览，`HIDE DETAIL` 可为录屏腾出画布空间。

架构数据源：`src/data/architecture_manifest.generated.json`。该文件由 `scripts/generate_architecture_manifest.py` 生成，不应手动维护。

## 构建验证

```powershell
npm run build
```

构建产物会生成在 `dist/`，该目录不会提交到 Git。
