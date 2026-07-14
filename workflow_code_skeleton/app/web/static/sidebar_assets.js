(() => {
  const config = window.sidebarAssetsConfig || {};
  if (!config.projectsUrl) return;

  const authToken = config.authToken || new URLSearchParams(window.location.search).get("auth_token") || "";
  const lists = {
    framework: document.getElementById("completedProjectList"),
    new_script: document.getElementById("newScriptProjectList"),
    hot_review: document.getElementById("hotReviewProjectList"),
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function hotReviewAssetTitle(item) {
    const artifacts = item && typeof item.artifacts === "object" ? item.artifacts : {};
    const result = item.result || item.tool_result || artifacts.tool_result || artifacts.result || {};
    const audit = item.audit || result.audit || artifacts.audit || {};
    const view = item.view || result.view || artifacts.view || {};
    return String(
      audit?.meta?.script_title
      || view?.meta?.script_title
      || item.script_title
      || result.script_title
      || item.title
      || "未命名爆款文审核"
    ).trim();
  }

  function isHotReviewAsset(item) {
    const artifacts = item && typeof item.artifacts === "object" ? item.artifacts : {};
    const result = item.result || item.tool_result || artifacts.tool_result || artifacts.result || {};
    const values = [
      item.tool_key,
      item.tool_id,
      item.tool_label,
      item.asset_type,
      item.category,
      item.workflow_type,
      item.result_type,
      item.resultType,
      item.tool_output_type,
      result.tool_key,
      result.result_type,
      result.resultType,
      artifacts.result_type,
      artifacts.tool_result && artifacts.tool_result.result_type,
    ].map((value) => String(value || "").trim());
    return values.some((value) =>
      value === "hot_review"
      || value === "script_audit_ecg"
      || value.includes("hot_review")
      || value.includes("script_audit")
      || value.includes("爆款文审核")
    ) || Boolean(item.audit || result.audit || artifacts.audit);
  }

  function ensureHotReviewList() {
    if (lists.hot_review) return lists.hot_review;
    const anchor = lists.framework?.closest("details") || lists.new_script?.closest("details");
    const parent = anchor?.parentElement;
    if (!parent) return null;
    const details = document.createElement("details");
    details.className = "workspace-folder hot-review-workspace-folder";
    details.innerHTML = `
      <summary><span>爆款文审核资产</span></summary>
      <div id="hotReviewProjectList" class="workspace-compact-list"></div>
    `;
    if (anchor) anchor.insertAdjacentElement("afterend", details);
    else parent.appendChild(details);
    lists.hot_review = details.querySelector("#hotReviewProjectList");
    return lists.hot_review;
  }

  function setHotReviewCount(count) {
    const countEl = document.getElementById("hotReviewProjectCount");
    if (countEl) countEl.textContent = String(Math.max(0, Number(count) || 0));
  }

  function setFrameworkCount(count) {
    const countEl = document.getElementById("completedProjectCount");
    if (countEl) countEl.textContent = String(Math.max(0, Number(count) || 0));
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
    if (isHotReviewAsset(item)) return "hot_review";
    const explicit = String(item.asset_type || item.type || "").trim();
    if (explicit === "legacy_script") return "";
    if (["old_script", "framework", "new_script", "character_reskin", "waibao"].includes(explicit)) return explicit;
    const input = item.input_payload && typeof item.input_payload === "object" ? item.input_payload : {};
    const assetKind = String(item.asset_kind || "").trim();
    const scriptMode = String(item.script_format_mode || input.script_format_mode || "").trim();
    if (assetKind === "framework_to_script" || scriptMode === "framework_to_script" || input.framework_to_script === true || hasFrameworkToScriptState(item)) return "new_script";
    if (assetKind === "framework_planner") return "framework";
    return "";
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
    if (isHotReviewAsset(item)) return hotReviewAssetTitle(item);
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
    if (isHotReviewAsset(item)) {
      url.searchParams.set("section", "tools");
      url.searchParams.set("tool", "hot_review");
    }
    return url.pathname + url.search;
  }

  function projectId(item) {
    return String(item && (item.project_id || item.asset_id || item.id) || "").trim();
  }

  function renderList(container, items, emptyText) {
    if (!container) return;
    if (!items.length) {
      container.innerHTML = `<div class="workspace-empty">${escapeHtml(emptyText)}</div>`;
      return;
    }
    container.innerHTML = items.map((item) => {
      const hotReview = isHotReviewAsset(item);
      return `
        <div class="workspace-pick-row${hotReview ? " hot-review-workspace-pick-row" : ""}">
          <a class="workspace-pick" href="${escapeHtml(projectUrl(item))}">
            <span class="workspace-pick-main">
              <span class="workspace-pick-title">${escapeHtml(projectTitle(item))}</span>
              <span class="workspace-pick-meta">${escapeHtml(`${Number(item.progress_percent || 0)}% · ${item.current_stage_label || statusLabel(item.status)}`)}</span>
            </span>
            <span class="workspace-pick-state">${escapeHtml(statusLabel(item.status))}</span>
          </a>
          ${hotReview ? `<button class="btn btn-danger workspace-pick-delete" type="button" data-action="delete-hot-review-asset" data-project-id="${escapeHtml(projectId(item))}">删除</button>` : ""}
        </div>
      `;
    }).join("");
  }

  async function loadSidebarAssets() {
    const headers = {};
    if (authToken) headers.Authorization = `Bearer ${authToken}`;
    const response = await fetch(config.projectsUrl, { headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false || data.ok === false) throw new Error(data.message || data.error || "资产列表加载失败");
    const projects = Array.isArray(data.projects) ? data.projects : [];
    const hotReviews = projects.filter((item) => assetCategory(item) === "hot_review");
    const frameworks = projects.filter((item) => assetCategory(item) === "framework");
    renderList(lists.framework, frameworks, "当前还没有框架资产。");
    setFrameworkCount(frameworks.length);
    renderList(ensureHotReviewList(), hotReviews, "当前还没有爆款文审核资产。");
    setHotReviewCount(hotReviews.length);
    renderList(lists.new_script, projects.filter((item) => assetCategory(item) === "new_script"), "当前还没有新剧本平台资产。");
  }

  document.querySelectorAll("[data-sidebar-refresh]").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.preventDefault();
      loadSidebarAssets().catch(() => {});
    });
  });

  document.addEventListener("click", async (event) => {
    const button = event.target?.closest?.('[data-action="delete-hot-review-asset"]');
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    const id = String(button.dataset.projectId || "").trim();
    if (!id) return;
    if (!window.confirm("确认删除这个爆款文审核资产吗？此操作不可恢复。")) return;
    button.disabled = true;
    const previousText = button.textContent;
    button.textContent = "删除中...";
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(id)}`, {
        method: "DELETE",
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.success === false || data.ok === false) {
        throw new Error(data.message || data.error || "删除失败");
      }
      await loadSidebarAssets();
    } catch (error) {
      button.disabled = false;
      button.textContent = previousText;
      window.alert(error && error.message ? error.message : "删除失败，请稍后重试。");
    }
  });

  loadSidebarAssets().catch(() => {});
})();
