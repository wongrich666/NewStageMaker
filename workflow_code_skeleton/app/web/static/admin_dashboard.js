(() => {
  "use strict";
  const token = document.querySelector('meta[name="auth-token"]')?.content || "";
  const state = { panel: "overview", users: { page: 1, search: "" }, runs: { page: 1, search: "", status: "" }, audit: { page: 1, search: "", category: "", status: "" } };
  const panelMeta = {
    overview: ["平台数据总览", "掌握用户、调用和工作流运行情况"],
    users: ["用户管理", "查看用户注册、活跃和功能使用情况"],
    runs: ["工作流运行", "追踪用户发起的每一次AI工作流"],
    audit: ["操作审计", "还原谁在什么时间执行了什么操作"],
  };
  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[ch]);
  const fmtNum = (value) => new Intl.NumberFormat("zh-CN").format(Number(value || 0));
  const fmtDate = (value) => {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? esc(value) : date.toLocaleString("zh-CN", { hour12: false });
  };
  const fmtDuration = (value) => {
    const ms = Number(value || 0);
    if (!ms) return "—";
    return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`;
  };
  const fmtBytes = (value) => {
    const size = Number(value || 0);
    if (!size) return "0 B";
    if (size < 1024) return `${size} B`;
    if (size < 1048576) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1048576).toFixed(1)} MB`;
  };
  const statusText = (status) => ({ success: "成功", failed: "失败", running: "运行中", accepted: "已受理" }[status] || status || "未知");
  const statusPill = (status) => `<span class="status-pill ${esc(status)}">${esc(statusText(status))}</span>`;
  const auditActionDescription = (item) => {
    const action = String(item.action || "").trim();
    const path = String(item.path || "").trim();
    const method = String(item.http_method || action.split(" ", 1)[0] || "").toUpperCase();
    const exact = {
      login: "登录剧本平台",
      register: "注册平台账号",
      logout: "退出剧本平台",
      admin_password_reset: "重置管理员密码",
      "/api/framework-planner/assets/save": "保存框架资产",
      "/api/framework-planner/assets": method === "GET" ? "查看框架资产" : "更新框架资产",
      "/api/framework-planner/generate-script": "从框架生成剧本",
      "/api/workflows/start": "启动剧本工作流",
      "/api/projects": method === "GET" ? "查看剧本项目" : "新建剧本项目",
      "/api/auth/profile": "修改账号资料",
      "/api/auth/password": "修改登录密码",
    };
    if (exact[action]) return exact[action];
    if (exact[path]) return exact[path];
    const stage = path.match(/^\/api\/framework-planner\/stage\/(01|02|03|04|05|06|07)(?:\/score)?$/);
    if (stage) {
      const labels = {
        "01": "运行原文信息提取",
        "02": "生成世界观方案",
        "03": "生成人物设定方案",
        "04": path.endsWith("/score") ? "评估三幕十五节拍规划" : "生成三幕十五节拍规划",
        "05": "生成人物故事线",
        "06": "生成整体改编指引",
        "07": "检验框架策划包",
      };
      return labels[stage[1]];
    }
    const tool = path.match(/^\/api\/tools\/([^/]+)\/run$/);
    if (tool) return ({ hot_review: "运行爆款文审核", reskin: "运行剧本换皮", punchup: "运行增加爽感", character_reskin: "运行只换人设", sitcom: "生成情景剧" }[tool[1]] || "运行辅助工具");
    if (path.startsWith("/api/framework-to-script/")) return "运行框架到剧本流程";
    if (path.startsWith("/api/workbuddy") || path.startsWith("/api/doctor")) return "使用AI剧本医生";
    if (path.startsWith("/api/admin/")) return "访问管理后台数据";
    if (path.startsWith("/api/projects/")) return method === "DELETE" ? "删除剧本项目" : "更新剧本项目";
    return ({ auth: "账号操作", workflow: "运行工作流", request: "执行平台操作", security: "安全设置" }[item.category] || "平台操作");
  };
  const auditActionText = (item) => {
    const raw = String(item.action || item.path || "未知操作").trim();
    return `${raw}（${auditActionDescription(item)}）`;
  };
  const notice = (message = "") => {
    const el = document.getElementById("adminNotice");
    el.hidden = !message;
    el.textContent = message;
  };
  async function api(path) {
    const response = await fetch(path, { headers: { Accept: "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) }, cache: "no-store" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false) throw new Error(data.error || `请求失败（${response.status}）`);
    return data;
  }
  function table(headers, rows, emptyText) {
    if (!rows.length) return `<div class="empty-state">${esc(emptyText)}</div>`;
    return `<table class="admin-table"><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
  }
  function pagination(kind, payload) {
    const holder = document.querySelector(`[data-pagination="${kind}"]`);
    if (!holder) return;
    const totalPages = Math.max(1, Math.ceil(Number(payload.total || 0) / Number(payload.page_size || 30)));
    holder.innerHTML = `<span>共 ${fmtNum(payload.total)} 条 · 第 ${payload.page}/${totalPages} 页</span><button type="button" data-page-kind="${kind}" data-page="${payload.page - 1}" ${payload.page <= 1 ? "disabled" : ""}>上一页</button><button type="button" data-page-kind="${kind}" data-page="${payload.page + 1}" ${payload.page >= totalPages ? "disabled" : ""}>下一页</button>`;
  }
  async function loadOverview() {
    const [overviewData, auditData] = await Promise.all([api("/api/admin/overview"), api("/api/admin/audit-events?page_size=8")]);
    const o = overviewData.overview || {};
    const metrics = [
      ["总用户数", o.total_users, `今日新增 ${fmtNum(o.new_users_today)}`, "用"],
      ["今日活跃用户", o.active_users_today, `记录操作 ${fmtNum(o.events_today)} 次`, "活"],
      ["今日工作流", o.runs_today, `成功/受理 ${fmtNum(o.successful_runs_today)}`, "流"],
      ["异常运行", o.failed_runs_today, `当前运行中 ${fmtNum(o.running_now)}`, "异"],
    ];
    document.getElementById("metricGrid").innerHTML = metrics.map(([label, value, note, icon]) => `<article class="metric-card"><div class="metric-card-top"><span>${esc(label)}</span><span class="metric-icon">${esc(icon)}</span></div><strong>${fmtNum(value)}</strong><small>${esc(note)}</small></article>`).join("");
    const workflows = o.top_workflows || [];
    const max = Math.max(1, ...workflows.map((item) => Number(item.run_count || 0)));
    document.getElementById("topWorkflowList").innerHTML = workflows.length ? workflows.map((item) => `<div class="workflow-row"><strong title="${esc(item.workflow_label)}">${esc(item.workflow_label)}</strong><span class="workflow-bar"><i style="width:${Math.max(5, Number(item.run_count || 0) / max * 100)}%"></i></span><span>${fmtNum(item.run_count)} 次${Number(item.failed_count) ? ` · ${fmtNum(item.failed_count)} 失败` : ""}</span></div>`).join("") : '<div class="empty-state">今天还没有新的工作流运行记录</div>';
    renderAuditTable(document.getElementById("overviewAuditTable"), auditData.items || [], "暂无操作记录");
  }
  function renderAuditTable(holder, items, emptyText = "没有符合条件的操作记录") {
    const rows = items.map((item) => `<tr><td><span class="cell-primary">${esc(item.username || "未登录用户")}</span><span class="cell-secondary">ID ${esc(item.user_id || "—")}</span></td><td><span class="cell-primary">${esc(auditActionText(item))}</span><span class="cell-secondary">接口：${esc(item.path || "—")}</span></td><td>${statusPill(item.status)}</td><td>${esc(item.ip_address || "—")}</td><td>${fmtDuration(item.duration_ms)}</td><td>${fmtDate(item.created_at)}</td></tr>`);
    holder.innerHTML = table(["用户", "操作", "结果", "IP", "耗时", "时间"], rows, emptyText);
  }
  async function loadUsers() {
    const q = new URLSearchParams({ page: state.users.page, page_size: 25, search: state.users.search });
    const data = await api(`/api/admin/users?${q}`);
    const rows = (data.items || []).map((item) => `<tr><td><span class="cell-primary">#${esc(item.id)} ${esc(item.username)}</span>${Number(item.admin_active) ? `<span class="admin-badge">${esc(item.admin_role || "admin")}</span>` : ""}</td><td>${fmtDate(item.created_at)}</td><td>${fmtDate(item.last_active_at || item.last_session_at)}</td><td>${fmtNum(item.session_count)}</td><td>${fmtNum(item.event_count)}</td><td>${fmtNum(item.workflow_run_count)}</td></tr>`);
    document.getElementById("usersTable").innerHTML = table(["用户", "注册时间", "最近活跃", "会话", "操作", "工作流"], rows, "没有符合条件的用户");
    pagination("users", data);
  }
  async function loadRuns() {
    const q = new URLSearchParams({ page: state.runs.page, page_size: 30, search: state.runs.search, status: state.runs.status });
    const data = await api(`/api/admin/workflow-runs?${q}`);
    const rows = (data.items || []).map((item) => `<tr><td><span class="cell-primary">${esc(item.workflow_label || item.workflow_key)}</span><span class="cell-secondary mono">${esc(item.run_id)}</span></td><td><span class="cell-primary">${esc(item.username || "未知用户")}</span><span class="cell-secondary">ID ${esc(item.user_id || "—")}</span></td><td>${statusPill(item.status)}</td><td>${fmtDuration(item.duration_ms)}</td><td>${fmtBytes(item.request_bytes)} / ${fmtBytes(item.response_bytes)}</td><td>${esc(item.http_status || "—")}</td><td>${fmtDate(item.started_at)}</td></tr>`);
    document.getElementById("runsTable").innerHTML = table(["工作流 / 运行ID", "用户", "状态", "耗时", "请求 / 响应", "HTTP", "开始时间"], rows, "没有符合条件的工作流记录");
    pagination("runs", data);
  }
  async function loadAudit() {
    const q = new URLSearchParams({ page: state.audit.page, page_size: 30, search: state.audit.search, category: state.audit.category, status: state.audit.status });
    const data = await api(`/api/admin/audit-events?${q}`);
    renderAuditTable(document.getElementById("auditTable"), data.items || []);
    pagination("audit", data);
  }
  async function loadPanel(panel = state.panel) {
    notice();
    try {
      if (panel === "overview") await loadOverview();
      if (panel === "users") await loadUsers();
      if (panel === "runs") await loadRuns();
      if (panel === "audit") await loadAudit();
    } catch (error) { notice(error.message || "加载管理数据失败"); }
  }
  function openPanel(panel) {
    if (!panelMeta[panel]) return;
    state.panel = panel;
    document.querySelectorAll(".admin-nav-item").forEach((el) => el.classList.toggle("is-active", el.dataset.panel === panel));
    document.querySelectorAll(".admin-panel").forEach((el) => el.classList.toggle("is-active", el.dataset.panelView === panel));
    document.getElementById("panelTitle").textContent = panelMeta[panel][0];
    document.getElementById("panelSubtitle").textContent = panelMeta[panel][1];
    loadPanel(panel);
  }
  document.addEventListener("click", (event) => {
    const nav = event.target.closest("[data-panel]");
    if (nav) openPanel(nav.dataset.panel);
    const jump = event.target.closest("[data-open-panel]");
    if (jump) openPanel(jump.dataset.openPanel);
    const pageButton = event.target.closest("[data-page-kind]");
    if (pageButton && !pageButton.disabled) { const kind = pageButton.dataset.pageKind; state[kind].page = Number(pageButton.dataset.page || 1); loadPanel(kind); }
  });
  document.querySelectorAll("[data-filter-form]").forEach((form) => form.addEventListener("submit", (event) => {
    event.preventDefault();
    const kind = form.dataset.filterForm;
    const data = new FormData(form);
    state[kind].page = 1;
    for (const [key, value] of data.entries()) state[kind][key] = String(value || "").trim();
    loadPanel(kind);
  }));
  document.getElementById("refreshAdminData")?.addEventListener("click", () => loadPanel());
  loadOverview().catch((error) => notice(error.message || "管理后台初始化失败"));
})();
