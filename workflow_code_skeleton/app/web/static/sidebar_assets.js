(() => {
  const config = window.sidebarAssetsConfig || {};
  if (!config.projectsUrl) return;

  const authToken = config.authToken || new URLSearchParams(window.location.search).get("auth_token") || "";
  const lists = {
    old_script: document.getElementById("activeProjectList"),
    framework: document.getElementById("completedProjectList"),
    new_script: document.getElementById("newScriptProjectList"),
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function hasFrameworkToScriptState(item) {
    const artifacts = item && typeof item.artifacts === "object" ? item.artifacts : {};
    const state = artifacts.framework_to_script_state || item.framework_to_script_state;
    if (!state || typeof state !== "object") return false;
    const stages = state.scriptStages && typeof state.scriptStages === "object" ? state.scriptStages : {};
    const outputs = state.stageOutputs && typeof state.stageOutputs === "object" ? state.stageOutputs : {};
    return Object.keys(stages).length > 0 || Object.keys(outputs).length > 0 || Boolean(state.runningStage);
  }

  function assetCategory(item) {
    const explicit = String(item.asset_type || item.type || "").trim();
    if (explicit === "legacy_script") return "old_script";
    if (["old_script", "framework", "new_script"].includes(explicit)) return explicit;
    const input = item.input_payload && typeof item.input_payload === "object" ? item.input_payload : {};
    const assetKind = String(item.asset_kind || "").trim();
    const scriptMode = String(item.script_format_mode || input.script_format_mode || "").trim();
    if (assetKind === "framework_to_script" || scriptMode === "framework_to_script" || input.framework_to_script === true || hasFrameworkToScriptState(item)) return "new_script";
    if (assetKind === "framework_planner") return "framework";
    return "old_script";
  }

  function isFrameworkToScriptAsset(item) {
    const input = item && item.input_payload && typeof item.input_payload === "object" ? item.input_payload : {};
    const assetKind = String((item && item.asset_kind) || "").trim();
    const scriptMode = String((item && item.script_format_mode) || input.script_format_mode || "").trim();
    return assetKind === "framework_to_script" || scriptMode === "framework_to_script" || input.framework_to_script === true || hasFrameworkToScriptState(item);
  }

  function statusLabel(status) {
    const labels = {
      pending: "排队中",
      running: "生成中",
      pausing: "暂停中",
      paused: "已暂停",
      failed: "失败",
      completed: "已完成",
      terminated: "已终止",
    };
    return labels[String(status || "")] || "已保存";
  }

  function projectTitle(item) {
    return String(item.title || item.project_title || item.source_title || "未命名资产").trim();
  }

  function projectUrl(item) {
    const id = encodeURIComponent(String(item.project_id || item.asset_id || ""));
    if (isFrameworkToScriptAsset(item)) {
      const url = new URL(config.frameworkToScriptUrl || "/framework-to-script", window.location.origin);
      if (authToken) url.searchParams.set("auth_token", authToken);
      url.searchParams.set("framework_asset_id", id);
      url.searchParams.set("project_id", id);
      url.searchParams.set("source_framework_project_id", id);
      return url.pathname + url.search;
    }
    const url = new URL(config.workspaceUrl || "/workspace", window.location.origin);
    if (authToken) url.searchParams.set("auth_token", authToken);
    url.searchParams.set("project_id", id);
    return url.pathname + url.search;
  }

  function renderList(container, items, emptyText) {
    if (!container) return;
    if (!items.length) {
      container.innerHTML = `<div class="workspace-empty">${escapeHtml(emptyText)}</div>`;
      return;
    }
    container.innerHTML = items.map((item) => `
      <a class="workspace-pick" href="${escapeHtml(projectUrl(item))}">
        <span class="workspace-pick-main">
          <span class="workspace-pick-title">${escapeHtml(projectTitle(item))}</span>
          <span class="workspace-pick-meta">${escapeHtml(`${Number(item.progress_percent || 0)}% · ${item.current_stage_label || statusLabel(item.status)}`)}</span>
        </span>
        <span class="workspace-pick-state">${escapeHtml(statusLabel(item.status))}</span>
      </a>
    `).join("");
  }

  async function loadSidebarAssets() {
    const headers = {};
    if (authToken) headers.Authorization = `Bearer ${authToken}`;
    const response = await fetch(config.projectsUrl, { headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false || data.ok === false) throw new Error(data.message || data.error || "资产列表加载失败");
    const projects = Array.isArray(data.projects) ? data.projects : [];
    renderList(lists.old_script, projects.filter((item) => assetCategory(item) === "old_script"), "当前没有老剧本平台资产。");
    renderList(lists.framework, projects.filter((item) => assetCategory(item) === "framework"), "当前还没有框架资产。");
    renderList(lists.new_script, projects.filter((item) => assetCategory(item) === "new_script"), "当前还没有新剧本平台资产。");
  }

  document.querySelectorAll("[data-sidebar-refresh]").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.preventDefault();
      loadSidebarAssets().catch(() => {});
    });
  });

  loadSidebarAssets().catch(() => {});
})();
