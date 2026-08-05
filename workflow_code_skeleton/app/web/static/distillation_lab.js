(function () {
  "use strict";

  const root = document.getElementById("distillation-lab-app");
  const config = window.DISTILLATION_LAB_CONFIG || {};
  const MODULE_KEYS = [
    ["skill_md", "SKILL.md"],
    ["genre_profile", "总编剧 · 题材画像"],
    ["story_architecture", "故事架构师"],
    ["hook_craft", "钩子与追剧问题"],
    ["character_emotion", "人物与情感"],
    ["continuity", "分集连续性"],
    ["dialogue_voice", "对白与人物声音"],
    ["adversity_payoff", "逆风与情绪兑现"],
    ["anti_patterns", "题材反模式"],
    ["quality_gate", "终审质量门"],
    ["verified_rules", "已验证规律"],
    ["hypotheses", "候选假设"],
    ["source_conflicts", "样本冲突"],
    ["manifest", "新工作流路由"],
    ["evidence", "证据索引"],
  ];
  const READONLY_KEYS = new Set(["verified_rules", "hypotheses", "source_conflicts", "manifest", "evidence"]);
  const STATUS = {
    draft: "草稿",
    distilling: "蒸馏中",
    candidate: "候选版本",
    published: "已发布",
    retired: "已归档",
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    pending: "等待",
    analyzed: "已分析",
    parsed: "已解析",
    uploaded: "待解析",
  };

  const state = {
    overview: { projects: [], counts: {}, model: {} },
    project: null,
    activeTab: "sources",
    activeVersionId: "",
    editorKey: "skill_md",
    pollTimer: null,
    modal: false,
  };

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function icon(name, size) {
    return `<i data-lucide="${name}"${size ? ` style="width:${size}px;height:${size}px"` : ""}></i>`;
  }

  function statusBadge(status) {
    const value = String(status || "draft");
    return `<span class="dl-badge ${escapeHtml(value)}">${escapeHtml(STATUS[value] || value)}</span>`;
  }

  function apiUrl(path) {
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${config.authToken ? `${separator}auth_token=${encodeURIComponent(config.authToken)}` : ""}`;
  }

  async function api(path, options) {
    const response = await fetch(apiUrl(path), {
      credentials: "same-origin",
      ...options,
      headers: {
        ...(options && options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(options && options.headers ? options.headers : {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || payload.message || `请求失败（${response.status}）`);
    }
    return payload;
  }

  function refreshIcons() {
    if (window.lucide) window.lucide.createIcons();
  }

  function toast(message, error) {
    document.querySelector(".dl-toast")?.remove();
    const node = document.createElement("div");
    node.className = `dl-toast${error ? " error" : ""}`;
    node.textContent = message;
    document.body.appendChild(node);
    setTimeout(() => node.remove(), 3600);
  }

  function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString("zh-CN", { hour12: false });
  }

  function formatChars(value) {
    const number = Number(value || 0);
    return number >= 10000 ? `${(number / 10000).toFixed(1)}万字` : `${number.toLocaleString()}字`;
  }

  async function loadOverview(selectFirst) {
    const data = await api("/api/distillation-lab/overview");
    state.overview = data;
    if (state.project) {
      const exists = data.projects.some((item) => item.id === state.project.id);
      if (!exists) state.project = null;
    }
    if (selectFirst && !state.project && data.projects.length) {
      await selectProject(data.projects[0].id, false);
      return;
    }
    render();
  }

  async function selectProject(projectId, renderLoading = true) {
    if (renderLoading) {
      state.project = null;
      render();
    }
    const data = await api(`/api/distillation-lab/projects/${projectId}`);
    state.project = data.project;
    const versions = state.project.versions || [];
    if (!versions.some((item) => item.id === state.activeVersionId)) {
      state.activeVersionId = versions[0]?.id || "";
    }
    render();
    schedulePolling();
  }

  function schedulePolling() {
    clearTimeout(state.pollTimer);
    const running = (state.project?.runs || []).find((item) => ["queued", "running"].includes(item.status));
    if (!running) return;
    state.pollTimer = setTimeout(async () => {
      try {
        const data = await api(`/api/distillation-lab/runs/${running.id}`);
        const index = state.project.runs.findIndex((item) => item.id === running.id);
        if (index >= 0) state.project.runs[index] = data.run;
        if (["completed", "failed"].includes(data.run.status)) {
          await loadOverview(false);
          await selectProject(state.project.id, false);
        } else {
          render();
          schedulePolling();
        }
      } catch (error) {
        toast(error.message, true);
      }
    }, 3000);
  }

  function sidebar() {
    const counts = state.overview.counts || {};
    return `
      <aside class="dl-sidebar">
        <div class="dl-sidebar-head">
          <div class="dl-counts">
            <div class="dl-stat"><strong>${counts.projects || 0}</strong><span>题材项目</span></div>
            <div class="dl-stat"><strong>${counts.sources || 0}</strong><span>样本</span></div>
            <div class="dl-stat"><strong>${counts.versions || 0}</strong><span>版本</span></div>
          </div>
          <button class="dl-btn primary" data-action="new-project">${icon("plus")} 新建蒸馏项目</button>
        </div>
        <div class="dl-project-list">
          ${(state.overview.projects || []).map((item) => `
            <button class="dl-project-item ${state.project?.id === item.id ? "active" : ""}" data-project-id="${escapeHtml(item.id)}">
              <span class="dl-project-title"><span>${escapeHtml(item.name)}</span>${statusBadge(item.status)}</span>
              <span class="dl-project-meta">${escapeHtml(item.genre || "未设置题材")} · ${item.source_count || 0}份样本 · ${item.version_count || 0}版</span>
            </button>
          `).join("") || `<div class="dl-empty" style="min-height:220px"><div>还没有蒸馏项目</div></div>`}
        </div>
      </aside>`;
  }

  function emptyWorkspace() {
    return `<section class="dl-workspace dl-empty"><div class="dl-empty-inner">
      <div class="dl-empty-icon">${icon("flask-conical", 28)}</div>
      <h2>建立你的第一个题材方法库</h2>
      <p>上传优质剧本与反面样本，提炼可追溯、可测试、可迭代的编剧 Skill。实验结果不会影响现有剧本工作流。</p>
      <button class="dl-btn primary" data-action="new-project">${icon("plus")} 新建蒸馏项目</button>
    </div></section>`;
  }

  function tabs() {
    const items = [
      ["sources", "样本素材"], ["process", "蒸馏过程"], ["skill", "Skill编辑器"],
      ["versions", "版本与测试"], ["settings", "项目设置"],
    ];
    return `<nav class="dl-tabs">${items.map(([key, label]) => `<button class="dl-tab ${state.activeTab === key ? "active" : ""}" data-tab="${key}">${label}</button>`).join("")}</nav>`;
  }

  function sourcesView() {
    const sources = state.project.sources || [];
    return `
      <section class="dl-section">
        <div class="dl-section-title"><div><h2>训练样本</h2><p>正面样本提炼有效结构，反面样本用于识别失败模式。</p></div></div>
        <form class="dl-upload" id="source-upload-form">
          <div class="dl-field"><label>剧本或文章</label><label class="dl-file-picker"><input name="files" type="file" accept=".docx,.pdf,.txt,.md" multiple required /></label></div>
          <div class="dl-field"><label>样本类型</label><select class="dl-select" name="polarity"><option value="positive">正面样本</option><option value="negative">反面样本</option></select></div>
          <div class="dl-field"><label>证据权重</label><select class="dl-select" name="weight"><option value="1">标准 1.0</option><option value="1.5">重要 1.5</option><option value="2">核心 2.0</option><option value="0.5">参考 0.5</option></select></div>
          <button class="dl-btn primary" type="submit">${icon("upload")} 上传素材</button>
        </form>
      </section>
      <section class="dl-section">
        <div class="dl-section-title"><div><h2>素材清单</h2><p>${sources.length}份素材，支持Word、PDF、TXT和Markdown。</p></div></div>
        <div class="dl-table-wrap"><table class="dl-table"><thead><tr><th>素材</th><th>属性</th><th>权重</th><th>文本量</th><th>状态</th><th></th></tr></thead><tbody>
          ${sources.map((item) => `<tr>
            <td><div class="dl-source-name">${icon("file-text")}<span title="${escapeHtml(item.original_name)}">${escapeHtml(item.original_name)}</span></div></td>
            <td>${item.polarity === "negative" ? "反面样本" : "正面样本"}</td>
            <td>${Number(item.weight || 1).toFixed(1)}</td>
            <td>${formatChars(item.char_count)}</td>
            <td>${statusBadge(item.status)}${item.error ? `<div class="dl-muted" title="${escapeHtml(item.error)}">解析异常</div>` : ""}</td>
            <td><button class="dl-btn icon danger" title="删除素材" data-delete-source="${escapeHtml(item.id)}">${icon("trash-2")}</button></td>
          </tr>`).join("") || `<tr><td colspan="6" class="dl-muted">上传至少一份素材后即可开始蒸馏。</td></tr>`}
        </tbody></table></div>
      </section>`;
  }

  function processView() {
    const run = (state.project.runs || [])[0];
    const stages = run?.stages || [
      { stage_key: "parse", stage_name: "素材解析", status: "pending" },
      { stage_key: "evidence", stage_name: "单篇证据提取", status: "pending" },
      { stage_key: "synthesis", stage_name: "跨样本证据验证", status: "pending" },
      { stage_key: "compile", stage_name: "新工作流 Skill 编译", status: "pending" },
      { stage_key: "evaluate", stage_name: "发布质量门", status: "pending" },
    ];
    const isRunning = run && ["queued", "running"].includes(run.status);
    return `
      <section class="dl-section">
        <div class="dl-section-title">
          <div><h2>蒸馏流水线</h2><p>节点完成即保存，刷新或离开页面不会丢失已完成产物。</p></div>
          <button class="dl-btn primary" data-action="start-run" ${isRunning || !(state.project.sources || []).length ? "disabled" : ""}>${icon(isRunning ? "loader-circle" : "play")} ${isRunning ? "正在蒸馏" : (run ? "生成新版本" : "开始蒸馏")}</button>
        </div>
        <div class="dl-pipeline">${stages.map((item, index) => `<article class="dl-stage ${escapeHtml(item.status)}">
          <div class="dl-stage-head"><span class="dl-stage-index">${item.status === "completed" ? icon("check", 14) : index + 1}</span>${statusBadge(item.status)}</div>
          <strong>${escapeHtml(item.stage_name)}</strong>
          <small>${item.error ? escapeHtml(item.error) : item.completed_at ? `完成于 ${formatDate(item.completed_at)}` : item.status === "running" ? "模型正在处理并保存结果" : "等待上游节点"}</small>
        </article>`).join("")}</div>
        ${run ? `<div class="dl-run-summary"><div><div class="dl-inline" style="justify-content:space-between;margin-bottom:8px"><strong>${statusBadge(run.status)} ${run.status === "failed" ? escapeHtml(run.error) : `当前进度 ${run.progress || 0}%`}</strong><span class="dl-muted">${formatDate(run.started_at || run.created_at)}</span></div><div class="dl-progress"><span style="width:${Math.max(2, Number(run.progress || 0))}%"></span></div></div><span class="dl-muted">任务 ${escapeHtml(run.id)}</span></div>` : ""}
      </section>
      <section class="dl-section"><div class="dl-section-title"><div><h2>执行原则</h2><p>新增样本只分析一次并复用证据卡；每个版本只加载新工作流需要的模块，减少重复上下文。</p></div></div>
        <div class="dl-run-summary"><div><strong>模型状态</strong><div class="dl-muted" style="margin-top:5px">${escapeHtml(state.overview.model?.model || "未配置")} · ${state.overview.model?.configured ? "已连接" : "缺少配置"}</div></div><button class="dl-btn" disabled title="首版仅预留关联能力">${icon("link")} 关联工作流（暂未开放）</button></div>
      </section>`;
  }

  function activeVersion() {
    return (state.project.versions || []).find((item) => item.id === state.activeVersionId) || state.project.versions?.[0] || null;
  }

  function editorValue(version) {
    if (!version) return "";
    if (state.editorKey === "skill_md") return version.skill_md || "";
    if (state.editorKey === "evidence") return JSON.stringify(version.evidence || [], null, 2);
    if (READONLY_KEYS.has(state.editorKey)) return JSON.stringify(version.assets?.[state.editorKey] || [], null, 2);
    return (version.modules || version.stage_prompts || {})[state.editorKey] || "";
  }

  function skillView() {
    const version = activeVersion();
    if (!version) return `<section class="dl-empty"><div class="dl-empty-inner"><div class="dl-empty-icon">${icon("wand-sparkles")}</div><h2>还没有候选Skill</h2><p>完成一次蒸馏后，可按新剧本团队模块编辑规则并查看证据来源。</p><button class="dl-btn primary" data-tab="process">前往蒸馏</button></div></section>`;
    const readonly = version.status === "published" || READONLY_KEYS.has(state.editorKey);
    return `<section class="dl-section">
      <div class="dl-section-title"><div><h2>${escapeHtml(version.version)} 新工作流 Skill编辑器</h2><p>模块按角色节点加载；未选择该Skill的任务不会占用这些规则和Token。</p></div><div class="dl-actions">${statusBadge(version.status)}<span class="dl-score">${version.score?.total || "-"}</span></div></div>
      <div class="dl-editor">
        <nav class="dl-editor-nav">${MODULE_KEYS.map(([key, label]) => `<button class="${state.editorKey === key ? "active" : ""}" data-editor-key="${key}">${escapeHtml(label)}</button>`).join("")}</nav>
        <div class="dl-editor-main">
          <textarea class="dl-codearea" id="skill-editor" ${readonly ? "readonly" : ""}>${escapeHtml(editorValue(version))}</textarea>
          <div class="dl-editor-actions">
            <a class="dl-btn" href="${apiUrl(`/api/distillation-lab/projects/${state.project.id}/versions/${version.id}/export`)}">${icon("download")} 导出Skill包</a>
            ${version.status === "published" ? `<button class="dl-btn danger" data-unpublish-version="${version.id}">${icon("circle-off")} 取消发布</button>` : ""}
            <button class="dl-btn primary" data-action="save-version" ${readonly ? "disabled" : ""}>${icon("save")} 保存当前修改</button>
          </div>
        </div>
      </div>
    </section>`;
  }

  function versionsView() {
    const versions = state.project.versions || [];
    return `<section class="dl-section"><div class="dl-section-title"><div><h2>版本与测试</h2><p>发布会归档上一个版本；旧版本及其证据始终保留。</p></div></div>
      <div class="dl-version-list">${versions.map((version) => `<article class="dl-version-row">
        <div><div class="dl-version-title"><strong>${escapeHtml(version.version)}</strong>${statusBadge(version.status)}<span class="dl-badge">${version.score?.grade || "待评测"}</span></div><div class="dl-version-meta">${formatDate(version.created_at)} · ${version.score?.source_count || 0}份证据 · 模块覆盖 ${version.score?.checks?.module_coverage ?? version.score?.checks?.stage_coverage ?? 0}%</div></div>
        <div class="dl-actions"><span class="dl-score">${version.score?.total || "-"}</span><button class="dl-btn" data-open-version="${version.id}">${icon("file-pen-line")} 查看</button>${version.status === "published" ? `<button class="dl-btn danger" data-unpublish-version="${version.id}">${icon("circle-off")} 取消发布</button>` : `<button class="dl-btn primary" data-publish-version="${version.id}" ${version.status !== "candidate" || !version.score?.ready_to_publish ? "disabled" : ""}>${icon("badge-check")} 发布</button>`}</div>
      </article>`).join("") || `<div class="dl-empty"><div>暂无版本，先运行一次蒸馏。</div></div>`}</div>
    </section>`;
  }

  function settingsView() {
    const item = state.project;
    return `<section class="dl-section"><div class="dl-section-title"><div><h2>题材边界</h2><p>这里定义蒸馏对象，不直接改变现有工作流。</p></div></div>
      <form id="project-settings-form" class="dl-form-grid">
        <div class="dl-field"><label>项目名称</label><input class="dl-input" name="name" value="${escapeHtml(item.name)}" required /></div>
        <div class="dl-field"><label>题材</label><input class="dl-input" name="genre" value="${escapeHtml(item.genre)}" placeholder="例如：狼人逆袭、都市复仇" /></div>
        <div class="dl-field"><label>目标市场</label><input class="dl-input" name="market" value="${escapeHtml(item.market)}" placeholder="例如：中国大陆、北美" /></div>
        <div class="dl-field"><label>目标受众</label><input class="dl-input" name="audience" value="${escapeHtml(item.audience)}" placeholder="年龄、偏好、观看场景" /></div>
        <div class="dl-field wide"><label>蒸馏边界与目标</label><textarea class="dl-textarea" name="description" placeholder="需要重点学习什么，以及哪些内容不能照搬">${escapeHtml(item.description)}</textarea></div>
        <div class="dl-actions wide" style="justify-content:space-between"><button class="dl-btn danger" type="button" data-action="delete-project">${icon("trash-2")} 删除项目</button><button class="dl-btn primary" type="submit">${icon("save")} 保存设置</button></div>
      </form>
    </section>`;
  }

  function projectWorkspace() {
    const p = state.project;
    const view = state.activeTab === "sources" ? sourcesView() : state.activeTab === "process" ? processView() : state.activeTab === "skill" ? skillView() : state.activeTab === "versions" ? versionsView() : settingsView();
    return `<section class="dl-workspace">
      <header class="dl-project-header"><div><div class="dl-inline" style="gap:9px"><h1>${escapeHtml(p.name)}</h1>${statusBadge(p.status)}</div><p>${escapeHtml(p.genre || "待定义题材")} · ${escapeHtml(p.market || "未指定市场")} · ${escapeHtml(p.audience || "未指定受众")}</p></div><div class="dl-actions"><button class="dl-btn" data-tab="settings">${icon("settings-2")} 项目设置</button><button class="dl-btn primary" data-tab="process">${icon("flask-conical")} ${p.versions?.length ? "蒸馏新版本" : "开始实验"}</button></div></header>
      ${tabs()}${view}
    </section>`;
  }

  function modal() {
    if (!state.modal) return "";
    return `<div class="dl-modal-backdrop"><form class="dl-modal" id="new-project-form">
      <header class="dl-modal-head"><h2>新建蒸馏项目</h2><button class="dl-btn icon" type="button" data-action="close-modal">${icon("x")}</button></header>
      <div class="dl-modal-body"><div class="dl-form-grid">
        <div class="dl-field wide"><label>项目名称</label><input class="dl-input" name="name" placeholder="例如：狼人逆袭爆款模型" required autofocus /></div>
        <div class="dl-field"><label>题材</label><input class="dl-input" name="genre" placeholder="狼人、职场、悬疑等" /></div>
        <div class="dl-field"><label>目标市场</label><input class="dl-input" name="market" placeholder="中国大陆、北美等" /></div>
        <div class="dl-field wide"><label>目标受众</label><input class="dl-input" name="audience" placeholder="例如：18-35岁女性短剧用户" /></div>
        <div class="dl-field wide"><label>蒸馏目标</label><textarea class="dl-textarea" name="description" placeholder="例如：重点提炼黄金3秒钩子、逆风压抑与反转打脸结构"></textarea></div>
      </div></div>
      <footer class="dl-modal-foot"><button class="dl-btn" type="button" data-action="close-modal">取消</button><button class="dl-btn primary" type="submit">${icon("plus")} 创建项目</button></footer>
    </form></div>`;
  }

  function render() {
    root.innerHTML = `<div class="dl-shell">
      <header class="dl-topbar"><div class="dl-brand"><span class="dl-brand-icon">${icon("flask-conical")}</span><span class="dl-brand-copy"><strong>爆款蒸馏实验室</strong><span>证据驱动的垂类编剧 Skill 研发台</span></span></div><div class="dl-actions"><a class="dl-btn" href="${escapeHtml(config.scriptStudioUrl || "/new-workflow-test")}">${icon("clapperboard")}<span>专业剧本制作台</span></a><a class="dl-btn icon" title="返回平台" href="${escapeHtml(config.workspaceUrl || "/")}">${icon("house")}</a></div></header>
      <div class="dl-layout">${sidebar()}${state.project ? projectWorkspace() : emptyWorkspace()}</div>${modal()}
    </div>`;
    bindEvents();
    refreshIcons();
  }

  function formObject(form) {
    return Object.fromEntries(new FormData(form).entries());
  }

  function bindEvents() {
    root.querySelectorAll("[data-action='new-project']").forEach((button) => button.addEventListener("click", () => { state.modal = true; render(); }));
    root.querySelectorAll("[data-action='close-modal']").forEach((button) => button.addEventListener("click", () => { state.modal = false; render(); }));
    root.querySelectorAll("[data-project-id]").forEach((button) => button.addEventListener("click", () => selectProject(button.dataset.projectId).catch((error) => toast(error.message, true))));
    root.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => { state.activeTab = button.dataset.tab; render(); }));
    root.querySelectorAll("[data-editor-key]").forEach((button) => button.addEventListener("click", () => { state.editorKey = button.dataset.editorKey; render(); }));

    root.querySelector("#new-project-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const data = await api("/api/distillation-lab/projects", { method: "POST", body: JSON.stringify(formObject(event.currentTarget)) });
        state.modal = false;
        await loadOverview(false);
        await selectProject(data.project.id, false);
        toast("蒸馏项目已创建。请上传优质样本和反面样本。");
      } catch (error) { toast(error.message, true); }
    });

    root.querySelector("#project-settings-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const data = await api(`/api/distillation-lab/projects/${state.project.id}`, { method: "PUT", body: JSON.stringify(formObject(event.currentTarget)) });
        state.project = data.project;
        await loadOverview(false);
        toast("项目设置已保存。");
      } catch (error) { toast(error.message, true); }
    });

    root.querySelector("#source-upload-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = event.currentTarget.querySelector("button[type='submit']");
      button.disabled = true;
      try {
        await api(`/api/distillation-lab/projects/${state.project.id}/sources`, { method: "POST", body: new FormData(event.currentTarget) });
        await selectProject(state.project.id, false);
        await loadOverview(false);
        toast("素材已上传，开始蒸馏时会自动解析并生成证据卡。");
      } catch (error) { toast(error.message, true); button.disabled = false; }
    });

    root.querySelectorAll("[data-delete-source]").forEach((button) => button.addEventListener("click", async () => {
      if (!window.confirm("确定删除这份素材及其证据卡吗？")) return;
      try {
        await api(`/api/distillation-lab/projects/${state.project.id}/sources/${button.dataset.deleteSource}`, { method: "DELETE" });
        await selectProject(state.project.id, false);
        await loadOverview(false);
        toast("素材已删除。");
      } catch (error) { toast(error.message, true); }
    }));

    root.querySelector("[data-action='start-run']")?.addEventListener("click", async () => {
      try {
        const data = await api(`/api/distillation-lab/projects/${state.project.id}/runs`, { method: "POST", body: "{}" });
        state.project.runs.unshift(data.run);
        render();
        schedulePolling();
        toast("蒸馏任务已启动，每个节点完成后都会立即保存。");
      } catch (error) { toast(error.message, true); }
    });

    root.querySelector("[data-action='save-version']")?.addEventListener("click", async () => {
      const version = activeVersion();
      const value = root.querySelector("#skill-editor")?.value || "";
      const payload = { skill_md: version.skill_md, modules: { ...(version.modules || version.stage_prompts || {}) } };
      if (state.editorKey === "skill_md") payload.skill_md = value;
      else payload.modules[state.editorKey] = value;
      try {
        const data = await api(`/api/distillation-lab/projects/${state.project.id}/versions/${version.id}`, { method: "PUT", body: JSON.stringify(payload) });
        const index = state.project.versions.findIndex((item) => item.id === version.id);
        state.project.versions[index] = data.version;
        render();
        toast("当前版本修改已保存。");
      } catch (error) { toast(error.message, true); }
    });

    root.querySelectorAll("[data-open-version]").forEach((button) => button.addEventListener("click", () => {
      state.activeVersionId = button.dataset.openVersion;
      state.editorKey = "skill_md";
      state.activeTab = "skill";
      render();
    }));

    root.querySelectorAll("[data-publish-version]").forEach((button) => button.addEventListener("click", async () => {
      if (!window.confirm("发布后，该版本才可供未来工作流关联。确定发布吗？")) return;
      try {
        await api(`/api/distillation-lab/projects/${state.project.id}/versions/${button.dataset.publishVersion}/publish`, { method: "POST", body: "{}" });
        await selectProject(state.project.id, false);
        await loadOverview(false);
        toast("Skill版本已发布，当前仍未自动关联任何工作流。");
      } catch (error) { toast(error.message, true); }
    }));

    root.querySelectorAll("[data-unpublish-version]").forEach((button) => button.addEventListener("click", async () => {
      if (!window.confirm("取消发布后，该 Skill 会从专业剧本制作台的可选列表中消失；已创建任务不受影响。确定取消吗？")) return;
      try {
        await api(`/api/distillation-lab/projects/${state.project.id}/versions/${button.dataset.unpublishVersion}/unpublish`, { method: "POST", body: "{}" });
        window.localStorage.setItem("distilledSkillCatalogChanged", String(Date.now()));
        await selectProject(state.project.id, false);
        await loadOverview(false);
        toast("已取消发布，制作台将不再显示该 Skill。");
      } catch (error) { toast(error.message, true); }
    }));

    root.querySelector("[data-action='delete-project']")?.addEventListener("click", async () => {
      if (!window.confirm(`确定删除“${state.project.name}”及全部素材、任务和版本吗？`)) return;
      try {
        await api(`/api/distillation-lab/projects/${state.project.id}`, { method: "DELETE" });
        state.project = null;
        await loadOverview(true);
        toast("蒸馏项目已删除。");
      } catch (error) { toast(error.message, true); }
    });
  }

  render();
  loadOverview(true).catch((error) => toast(error.message, true));
})();
