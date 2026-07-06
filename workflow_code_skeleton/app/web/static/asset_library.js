(() => {
  const config = window.assetLibraryConfig || {};
  const mode = String(config.mode || "framework");
  const authToken = config.authToken || new URLSearchParams(window.location.search).get("auth_token") || "";
  const grid = document.getElementById("assetLibraryGrid");
  const statusEl = document.getElementById("assetLibraryStatus");
  const refreshBtn = document.getElementById("assetRefreshBtn");
  const searchInput = document.getElementById("assetSearchInput");
  const countValue = document.getElementById("assetCountValue");
  let allAssets = [];

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function headers() {
    return authToken ? { Authorization: `Bearer ${authToken}` } : {};
  }

  function asObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function hotReviewAssetTitle(item) {
    const artifacts = asObject(item.artifacts);
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
    const artifacts = asObject(item.artifacts);
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

  function hasFrameworkToScriptState(item) {
    const artifacts = asObject(item.artifacts);
    const state = artifacts.framework_to_script_state || item.framework_to_script_state;
    if (!state || typeof state !== "object") return false;
    const stages = state.scriptStages && typeof state.scriptStages === "object" ? state.scriptStages : {};
    const outputs = state.stageOutputs && typeof state.stageOutputs === "object" ? state.stageOutputs : {};
    return Object.keys(stages).length > 0 || Object.keys(outputs).length > 0 || Boolean(state.runningStage);
  }

  function assetCategory(item) {
    if (isHotReviewAsset(item)) return "hot_review";
    const explicit = String(item.asset_type || item.type || "").trim();
    if (["framework", "new_script", "character_reskin", "waibao"].includes(explicit)) return explicit;
    const input = asObject(item.input_payload);
    const assetKind = String(item.asset_kind || "").trim();
    const scriptMode = String(item.script_format_mode || input.script_format_mode || "").trim();
    if (assetKind === "framework_to_script" || scriptMode === "framework_to_script" || input.framework_to_script === true || hasFrameworkToScriptState(item)) {
      return "new_script";
    }
    if (assetKind === "framework_planner") return "framework";
    return "";
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

  function assetTitle(item) {
    if (isHotReviewAsset(item)) return hotReviewAssetTitle(item);
    return String(item.title || item.project_title || item.source_title || "未命名框架资产").trim();
  }

  function assetSummary(item) {
    const artifacts = asObject(item.artifacts);
    const result = item.result || item.tool_result || artifacts.tool_result || artifacts.result || {};
    const audit = item.audit || result.audit || artifacts.audit || {};
    const view = item.view || result.view || artifacts.view || {};
    if (isHotReviewAsset(item)) {
      return String(
        audit?.overall?.core_judgement
        || view?.summary
        || result.summary
        || item.summary
        || "已保存的爆款文审核结果，可打开查看评分、心电图和修改建议。"
      ).trim();
    }
    return String(item.summary || item.description || "已保存的框架策划资产，可继续进入框架到剧本链路。").trim();
  }

  function projectId(item) {
    return String(item && (item.project_id || item.asset_id || item.id) || "").trim();
  }

  function withAuth(url) {
    const parsed = new URL(url, window.location.origin);
    if (authToken) parsed.searchParams.set("auth_token", authToken);
    return parsed.pathname + parsed.search;
  }

  function frameworkOpenUrl(item) {
    const id = projectId(item);
    const url = new URL(config.frameworkPlannerUrl || "/framework-planner", window.location.origin);
    if (authToken) url.searchParams.set("auth_token", authToken);
    if (id) url.searchParams.set("project_id", id);
    return url.pathname + url.search;
  }

  function frameworkToScriptUrl(item) {
    const id = projectId(item);
    const url = new URL(config.frameworkToScriptUrl || "/framework-to-script", window.location.origin);
    if (authToken) url.searchParams.set("auth_token", authToken);
    if (id) {
      url.searchParams.set("framework_asset_id", id);
      url.searchParams.set("project_id", id);
      url.searchParams.set("source_framework_project_id", id);
    }
    return url.pathname + url.search;
  }

  function hotReviewOpenUrl(item) {
    const id = projectId(item);
    const url = new URL(config.workspaceUrl || "/workspace", window.location.origin);
    if (authToken) url.searchParams.set("auth_token", authToken);
    url.searchParams.set("section", "tools");
    url.searchParams.set("tool", "hot_review");
    if (id) url.searchParams.set("project_id", id);
    return url.pathname + url.search;
  }

  function filteredAssets() {
    const keyword = String(searchInput?.value || "").trim().toLowerCase();
    return allAssets
      .filter((item) => assetCategory(item) === mode)
      .filter((item) => {
        if (!keyword) return true;
        return [
          assetTitle(item),
          assetSummary(item),
          statusLabel(item.status),
          item.current_stage_label,
          item.updated_at,
        ].some((value) => String(value || "").toLowerCase().includes(keyword));
      });
  }

  function renderStatus(text, tone = "") {
    if (!statusEl) return;
    statusEl.textContent = text || "";
    statusEl.className = `asset-library-status${tone ? ` ${tone}` : ""}`;
    statusEl.hidden = !text;
  }

  function render() {
    const items = filteredAssets();
    if (countValue) countValue.textContent = String(items.length);
    if (!grid) return;
    if (!items.length) {
      grid.innerHTML = `
        <article class="asset-empty-panel">
          <span class="asset-empty-icon">${mode === "framework" ? "▣" : "◇"}</span>
          <h2>${mode === "framework" ? "还没有框架资产" : "还没有爆款文审核资产"}</h2>
          <p>${mode === "framework" ? "完成 01-07 框架策划后，资产会自动出现在这里。" : "运行爆款文审核并保存后，评分结果会集中展示在这里。"}</p>
          <a class="asset-primary-action" href="${escapeHtml(mode === "framework" ? withAuth("/framework-planner?new=1") : withAuth("/workspace?section=tools&tool=hot_review"))}">
            <span>${mode === "framework" ? "✦" : "◇"}</span>
            ${mode === "framework" ? "新建框架" : "运行审核"}
          </a>
        </article>
      `;
      return;
    }
    grid.innerHTML = items.map(renderCard).join("");
  }

  function renderCard(item) {
    const id = projectId(item);
    const hot = mode === "hot_review";
    const status = statusLabel(item.status);
    const updated = String(item.updated_at || item.created_at || "").replace("T", " ").slice(0, 16);
    const title = assetTitle(item);
    const summary = assetSummary(item);
    const score = hot ? extractHotScore(item) : null;
    return `
      <article class="asset-library-card ${hot ? "hot-review-card" : "framework-card"}">
        <div class="asset-card-icon">${hot ? "◇" : "▣"}</div>
        ${hot ? renderScoreBadge(score) : ""}
        <div class="asset-card-body">
          <div class="asset-card-topline">
            <span>${hot ? "爆款文审核" : "框架策划"}</span>
            <small>${escapeHtml(status)}</small>
          </div>
          <h2>${escapeHtml(title)}</h2>
          <p>${escapeHtml(summary)}</p>
          <div class="asset-card-meta">
            ${score ? `<span>评分 ${escapeHtml(score.label)}</span>` : ""}
            <span>ID ${escapeHtml(id || "-")}</span>
            <span>${escapeHtml(updated || "暂无更新时间")}</span>
          </div>
          <div class="asset-card-actions">
            ${hot
              ? `<a class="asset-card-btn primary" href="${escapeHtml(hotReviewOpenUrl(item))}"><span>↗</span>打开审核</a>`
              : `<a class="asset-card-btn primary" href="${escapeHtml(frameworkOpenUrl(item))}"><span>↗</span>打开框架</a>
                 <a class="asset-card-btn" href="${escapeHtml(frameworkToScriptUrl(item))}"><span>▶</span>生成剧本</a>`
            }
            ${hot ? `<button class="asset-card-btn danger" type="button" data-action="delete-asset" data-project-id="${escapeHtml(id)}"><span>×</span>删除</button>` : ""}
          </div>
        </div>
      </article>
    `;
  }

  function renderScoreBadge(score) {
    if (!score) {
      return `
        <div class="asset-score-badge empty">
          <strong>--</strong>
          <span>未评分</span>
        </div>
      `;
    }
    return `
      <div class="asset-score-badge ${escapeHtml(score.tone)}">
        <strong>${escapeHtml(score.value)}</strong>
        <span>/100</span>
      </div>
    `;
  }

  function extractHotScore(item) {
    const artifacts = asObject(item.artifacts);
    const result = item.result || item.tool_result || artifacts.tool_result || artifacts.result || {};
    const audit = item.audit || result.audit || artifacts.audit || {};
    const view = item.view || result.view || artifacts.view || {};
    const score = audit?.overall?.total_score
      ?? audit?.overall?.score
      ?? audit?.total_score
      ?? audit?.score
      ?? view?.score
      ?? view?.total_score
      ?? result.score
      ?? result.total_score
      ?? item.score
      ?? item.total_score
      ?? "";
    if (score === "" || score === null || score === undefined) return "";
    const numeric = Number(score);
    const value = Number.isFinite(numeric) ? String(Math.round(numeric)) : String(score);
    const tone = Number.isFinite(numeric)
      ? (numeric >= 80 ? "high" : numeric >= 70 ? "mid" : "low")
      : "mid";
    return { value, label: `${value}/100`, tone };
  }

  async function loadAssets() {
    if (refreshBtn) refreshBtn.disabled = true;
    renderStatus("正在读取资产...");
    try {
      const response = await fetch(config.projectsUrl || "/api/projects", { headers: headers() });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.success === false || data.ok === false) {
        throw new Error(data.message || data.error || "资产列表加载失败");
      }
      allAssets = Array.isArray(data.projects) ? data.projects : [];
      if (mode === "hot_review") {
        renderStatus("正在读取审核分数...");
        await hydrateHotReviewDetails();
      }
      renderStatus("");
      render();
    } catch (error) {
      renderStatus(error && error.message ? error.message : "资产列表加载失败", "error");
      if (grid) grid.innerHTML = "";
    } finally {
      if (refreshBtn) refreshBtn.disabled = false;
    }
  }

  async function hydrateHotReviewDetails() {
    const hotItems = allAssets.filter((item) => assetCategory(item) === "hot_review" && projectId(item));
    await Promise.all(hotItems.map(async (item) => {
      try {
        const response = await fetch(`/api/projects/${encodeURIComponent(projectId(item))}`, { headers: headers() });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.success === false || data.ok === false || !data.project) return;
        Object.assign(item, data.project);
      } catch {
        // Keep the list item usable even when a detail request fails.
      }
    }));
  }

  async function deleteAsset(id, button) {
    if (!id) return;
    if (!window.confirm("确认删除这个爆款文审核资产吗？此操作不可恢复。")) return;
    const previous = button.textContent;
    button.disabled = true;
    button.textContent = "删除中...";
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(id)}`, {
        method: "DELETE",
        headers: headers(),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.success === false || data.ok === false) {
        throw new Error(data.message || data.error || "删除失败");
      }
      allAssets = allAssets.filter((item) => projectId(item) !== String(id));
      render();
    } catch (error) {
      window.alert(error && error.message ? error.message : "删除失败，请稍后重试。");
      button.disabled = false;
      button.textContent = previous;
    }
  }

  refreshBtn?.addEventListener("click", loadAssets);
  searchInput?.addEventListener("input", render);
  document.addEventListener("click", (event) => {
    const button = event.target?.closest?.('[data-action="delete-asset"]');
    if (!button) return;
    event.preventDefault();
    deleteAsset(String(button.dataset.projectId || ""), button);
  });

  loadAssets();
})();
