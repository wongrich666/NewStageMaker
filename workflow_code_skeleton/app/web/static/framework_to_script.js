(() => {
  const app = document.getElementById("framework-to-script-app");
  if (!app) return;

  const config = window.FRAMEWORK_TO_SCRIPT_CONFIG || {};
  const params = new URLSearchParams(window.location.search);
  const authToken = params.get("auth_token") || "";
  const STORAGE_KEY = "frameworkToScriptWorkspace.v1";
  const RAW_KEYS = new Set(["responseData", "choices", "reasoningText", "historyPreview", "newVariables", "updateVarResult", "raw_stage_responses", "raw_output", "raw", "answerText", "debug", "logs", "cache"]);
  const FIELD_LABELS = {
    framework_plan_package: "最终框架策划包",
    source_brief: "原文信息",
    worldview_plan: "世界观方案",
    character_plan: "人物设定",
    beat_checkpoint_timeline: "三幕十五节拍",
    checkpoint_explanation: "节拍说明",
    character_storylines: "人物故事线",
    storyline_decisions: "故事线处理",
    adaptation_guide: "整体改编指引",
    sceneDictionary: "场景字典",
    scriptWorldRulesDigest: "世界观规则摘要",
    appearanceMapping: "角色外观映射",
    enrichedEpisodePlan: "分集细化文本",
    batchCausalConflictPlan: "因果冲突推进计划",
    batchCausalConflictReview: "因果冲突审核",
    conflictMemory: "因果冲突记忆",
    batchScriptText: "正文及对话",
    batchScriptReview: "正文审核",
    scriptMemory: "正文记忆",
  };

  const state = Object.assign({
    frameworkAssetId: null,
    projectId: null,
    importedFrameworkAsset: null,
    frameworkPlanPackage: null,
    stageOutputs: {},
    settings: {},
    scriptStages: {},
    assets: [],
    assetPanelOpen: false,
    isLoadingAsset: false,
    isRunning: false,
    runningStage: "",
    runningStartedAt: "",
    error: null,
  }, loadWorkspace());

  const urlAssetId = params.get("framework_asset_id") || params.get("asset_id") || "";
  if (urlAssetId && String(urlAssetId) !== String(state.frameworkAssetId || "")) {
    state.frameworkAssetId = urlAssetId;
  }

  function headers() {
    const value = { "Content-Type": "application/json" };
    if (authToken) value.Authorization = `Bearer ${authToken}`;
    return value;
  }

  function apiUrl(path) {
    if (!authToken) return path;
    const url = new URL(path, window.location.origin);
    url.searchParams.set("auth_token", authToken);
    return url.pathname + url.search;
  }

  async function requestJson(path, options) {
    const response = await fetch(apiUrl(path), Object.assign({ headers: headers() }, options || {}));
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false || data.ok === false) {
      const detail = data.detail && typeof data.detail === "object" ? data.detail : {};
      const detailMessage = detail.error_message || detail.message || "";
      const failedSubStage = detail.failed_sub_stage ? `（${detail.failed_sub_stage}）` : "";
      throw new Error(
        [data.message || data.error || "请求失败，请稍后重试。", failedSubStage, detailMessage]
          .filter(Boolean)
          .join(" ")
      );
    }
    return stripRaw(data);
  }

  function stripRaw(value) {
    if (Array.isArray(value)) return value.map(stripRaw);
    if (!value || typeof value !== "object") return value;
    const next = {};
    Object.keys(value).forEach((key) => {
      if (RAW_KEYS.has(key)) return;
      next[key] = stripRaw(value[key]);
    });
    return next;
  }

  function loadWorkspace() {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? stripRaw(parsed) : {};
    } catch (error) {
      return {};
    }
  }

  function saveWorkspace() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(stripRaw({
        frameworkAssetId: state.frameworkAssetId,
        projectId: state.projectId,
        importedFrameworkAsset: state.importedFrameworkAsset,
        frameworkPlanPackage: state.frameworkPlanPackage,
        stageOutputs: state.stageOutputs,
        settings: state.settings,
        scriptStages: state.scriptStages,
      })));
    } catch (error) {}
  }

    const RUNNING_STAGE_STORAGE_KEY = "frameworkToScriptRunningStage.v1";
  const RUNNING_STAGE_TIMEOUT_MS = 1000 * 60 * 60;

  function saveRunningStage(stage) {
    const payload = {
      runningStage: String(stage || ""),
      startedAt: new Date().toISOString(),
      frameworkAssetId: state.frameworkAssetId || "",
    };

    state.runningStage = payload.runningStage;
    state.runningStartedAt = payload.startedAt;
    state.isRunning = Boolean(payload.runningStage);

    try {
      window.localStorage.setItem(RUNNING_STAGE_STORAGE_KEY, JSON.stringify(payload));
    } catch (error) {
      console.warn("save running stage failed", error);
    }
  }

  function clearRunningStage(stage) {
    if (stage && state.runningStage && String(stage) !== String(state.runningStage)) {
      return;
    }

    state.runningStage = "";
    state.runningStartedAt = "";
    state.isRunning = false;

    try {
      window.localStorage.removeItem(RUNNING_STAGE_STORAGE_KEY);
    } catch (error) {
      console.warn("clear running stage failed", error);
    }
  }

  function restoreRunningStage() {
    try {
      const raw = window.localStorage.getItem(RUNNING_STAGE_STORAGE_KEY);
      if (!raw) return;

      const payload = JSON.parse(raw);
      if (!payload || !payload.runningStage || !payload.startedAt) {
        window.localStorage.removeItem(RUNNING_STAGE_STORAGE_KEY);
        return;
      }

      const startedAt = new Date(payload.startedAt).getTime();
      if (!Number.isFinite(startedAt) || Date.now() - startedAt > RUNNING_STAGE_TIMEOUT_MS) {
        window.localStorage.removeItem(RUNNING_STAGE_STORAGE_KEY);
        return;
      }

      if (
        payload.frameworkAssetId &&
        state.frameworkAssetId &&
        String(payload.frameworkAssetId) !== String(state.frameworkAssetId)
      ) {
        return;
      }

      window.localStorage.removeItem(RUNNING_STAGE_STORAGE_KEY);
      state.runningStage = "";
      state.runningStartedAt = "";
      state.isRunning = false;
      state.error = `已清除上次遗留的 ${payload.runningStage} 阶段运行锁，可重新点击运行。`;
    } catch (error) {
      console.warn("restore running stage failed", error);
      try {
        window.localStorage.removeItem(RUNNING_STAGE_STORAGE_KEY);
      } catch (_) {}
    }
  }

  function stageHasCompleted(stage) {
    const stages = state.scriptStages || {};
    const stage08 = stages.stage08 || {};
    const stage09 = stages.stage09 || {};
    const stage10 = stages.stage10 || {};
    const stage11 = stages.stage11 || {};
    const stage12 = stages.stage12 || {};

    if (stage === "08") return hasObject(stage08.sceneDictionary);
    if (stage === "09") return hasObject(stage09.appearanceMapping);
    if (stage === "10") return hasContent(stage10.allEnrichedEpisodePlan) || hasContent(stage10.enrichedEpisodePlan);
    if (stage === "11") return hasContent(stage11.batchCausalConflictPlan);
    if (stage === "12") return hasContent(stage12.batchScriptText);
    return false;
  }

  function reconcileRunningStageResult() {
    if (state.runningStage && stageHasCompleted(state.runningStage)) {
      clearRunningStage(state.runningStage);
      state.error = null;
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function formatDate(value) {
    if (!value) return "未记录";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString("zh-CN", { hour12: false });
  }

  function labelFor(key) {
    return FIELD_LABELS[key] || String(key || "").replaceAll("_", " ");
  }

  function hasObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length > 0;
  }

  function hasContent(value) {
    if (Array.isArray(value)) return value.length > 0;
    if (value && typeof value === "object") return Object.keys(value).length > 0;
    return String(value || "").trim().length > 0;
  }

  function stage10Plan(stage10) {
    const value = stage10 || {};
    return value.allEnrichedEpisodePlan || value.enrichedEpisodePlan || [];
  }

  function stage10Text(stage10) {
    const value = stage10 || {};
    return value.allEnrichedEpisodePlanText || value.enrichedEpisodePlanText || "";
  }

  function currentAssetReady() {
    return Boolean(state.frameworkAssetId && hasObject(state.frameworkPlanPackage));
  }

  function frameworkStageValue(key) {
    const packageValue = state.frameworkPlanPackage || {};
    const outputs = state.stageOutputs || {};
    return outputs[key] || packageValue[key] || {};
  }

  async function loadAssets() {
    state.isLoadingAsset = true;
    state.error = null;
    render();
    try {
      const data = await requestJson("/api/framework-assets");
      state.assets = Array.isArray(data.assets) ? data.assets : [];
      state.assetPanelOpen = true;
    } catch (error) {
      state.error = error.message || "框架资产列表加载失败";
    } finally {
      state.isLoadingAsset = false;
      render();
    }
  }

  async function importAsset(assetId, options = {}) {
    const id = String(assetId || "").trim();
    if (!id) return;
    if (
      state.frameworkAssetId &&
      String(state.frameworkAssetId) !== id &&
      !options.skipConfirm &&
      !window.confirm("切换框架资产会替换当前框架输入，但不会删除历史版本。继续切换吗？")
    ) {
      return;
    }
    state.isLoadingAsset = true;
    state.error = null;
    render();
    try {
      const data = await requestJson(`/api/framework-assets/${encodeURIComponent(id)}`);
      const asset = data.asset || {};
      state.frameworkAssetId = asset.asset_id || id;
      state.projectId = asset.project_id || asset.asset_id || id;
      state.importedFrameworkAsset = asset;
      state.frameworkPlanPackage = asset.framework_plan_package || {};
      state.stageOutputs = asset.stage_outputs || {};
      state.scriptStages = asset.scriptStages || (asset.framework_to_script_state || {}).scriptStages || {};
      const stage10 = state.scriptStages.stage10 || {};
      const allEnrichedEpisodePlan = stage10Plan(stage10);
      const allEnrichedEpisodePlanText = stage10Text(stage10);
      if (hasContent(allEnrichedEpisodePlan) || hasContent(allEnrichedEpisodePlanText)) {
        state.scriptStages.stage10 = {
          ...stage10,
          allEnrichedEpisodePlan,
          enrichedEpisodePlan: stage10.enrichedEpisodePlan || allEnrichedEpisodePlan,
          allEnrichedEpisodePlanText,
          enrichedEpisodePlanText: stage10.enrichedEpisodePlanText || allEnrichedEpisodePlanText,
        };
      }
      state.assetPanelOpen = false;
      reconcileRunningStageResult();
      saveWorkspace();
    } catch (error) {
      state.error = error.message || "框架资产导入失败";
    } finally {
      state.isLoadingAsset = false;
      render();
    }
  }

  async function runStage08() {
    if (!currentAssetReady()) {
      state.error = "请先导入框架资产，或从框架生成页面一键进入。";
      render();
      return;
    }
    saveRunningStage("08");
    state.error = null;
    render();
    render();
    try {
      const data = await requestJson("/api/framework-to-script/stage/08", {
        method: "POST",
        body: JSON.stringify({
          framework_asset_id: state.frameworkAssetId,
        }),
      });
      state.scriptStages.stage08 = {
        sceneDictionary: data.sceneDictionary,
        scriptWorldRulesDigest: data.scriptWorldRulesDigest,
        updated_at: new Date().toISOString(),
      };
      saveWorkspace();
    } catch (error) {
      state.error = error.message || "08 场景字典提炼失败";
    } finally {
      clearRunningStage("08");
      render();
    }
  }

  async function runStage09() {
    if (!currentAssetReady()) {
      state.error = "请先导入框架资产，或从框架生成页面一键进入。";
      render();
      return;
    }
    const stage08 = state.scriptStages.stage08 || {};
    if (!hasObject(stage08.sceneDictionary)) {
      state.error = "请先完成 08 场景字典提炼。";
      render();
      return;
    }
    state.runningStage = "09";
    state.isRunning = true;
    state.error = null;
    render();
    try {
      const data = await requestJson("/api/framework-to-script/stage/09", {
        method: "POST",
        body: JSON.stringify({
          framework_asset_id: state.frameworkAssetId,
          sceneDictionary: stage08.sceneDictionary,
        }),
      });
      state.scriptStages.stage09 = {
        appearanceMapping: data.appearanceMapping,
        updated_at: new Date().toISOString(),
      };
      saveWorkspace();
    } catch (error) {
      state.error = error.message || "09 角色外观映射失败";
    } finally {
      clearRunningStage("09");
      render();
    }
  }

  async function runStage10() {
    if (!currentAssetReady()) {
      state.error = "请先导入框架资产，或从框架生成页面一键进入。";
      render();
      return;
    }

    const stage08 = state.scriptStages.stage08 || {};
    const stage09 = state.scriptStages.stage09 || {};

    if (!hasObject(stage08.sceneDictionary)) {
      state.error = "请先完成 08 场景字典提炼。";
      render();
      return;
    }

    if (!hasObject(stage09.appearanceMapping)) {
      state.error = "请先完成 09 角色外观映射。";
      render();
      return;
    }

    saveRunningStage("10");
    state.error = null;
    render();

    try {
      const data = await requestJson("/api/framework-to-script/stage/10", {
        method: "POST",
        body: JSON.stringify({
          framework_asset_id: state.frameworkAssetId,
          sceneDictionary: stage08.sceneDictionary,
          scriptWorldRulesDigest: stage08.scriptWorldRulesDigest,
          appearanceMapping: stage09.appearanceMapping,
        }),
      });

      const enrichedEpisodePlan =
        data.enrichedEpisodePlan ||
        data.allEnrichedEpisodePlan ||
        data.enriched_episode_plan ||
        null;

      const enrichedEpisodePlanText =
        data.enrichedEpisodePlanText ||
        data.allEnrichedEpisodePlanText ||
        data.enriched_episode_plan_text ||
        "";

      state.scriptStages.stage10 = {
        enrichedEpisodePlan,
        enrichedEpisodePlanText,
        allEnrichedEpisodePlan: data.allEnrichedEpisodePlan || enrichedEpisodePlan,
        allEnrichedEpisodePlanText: data.allEnrichedEpisodePlanText || enrichedEpisodePlanText,
        updated_at: new Date().toISOString(),
      };

      saveWorkspace();
    } catch (error) {
      state.error = error.message || "10 分集细化方案失败";
    } finally {
      clearRunningStage("10");
      render();
    }
  }

  async function runStage11() {
    if (!currentAssetReady()) {
      state.error = "请先导入框架资产，或从框架生成页面一键进入。";
      render();
      return;
    }
    const stage10 = state.scriptStages.stage10 || {};
    const stage08 = state.scriptStages.stage08 || {};
    const stage09 = state.scriptStages.stage09 || {};
    const stage11 = state.scriptStages.stage11 || {};
    const allEnrichedEpisodePlan = stage10Plan(stage10);
    if (!hasContent(allEnrichedEpisodePlan)) {
      state.error = "缺少第10阶段结构化分集计划，请先重新运行10。";
      render();
      return;
    }
    if (!hasObject(stage08.sceneDictionary)) {
      state.error = "请先完成 08 场景字典提炼。";
      render();
      return;
    }
    if (!hasObject(stage09.appearanceMapping)) {
      state.error = "请先完成 09 角色外观映射。";
      render();
      return;
    }
    saveRunningStage("11");
    state.error = null;
    render();
    try {
      const data = await requestJson("/api/framework-to-script/stage/11", {
        method: "POST",
        body: JSON.stringify({
          framework_asset_id: state.frameworkAssetId,
          allEnrichedEpisodePlan,
          sceneDictionary: stage08.sceneDictionary,
          scriptWorldRulesDigest: stage08.scriptWorldRulesDigest,
          appearanceMapping: stage09.appearanceMapping,
          batchStartEpisode: state.settings.batchStartEpisode || null,
          conflictMemory: stage11.conflictMemory || "",
        }),
      });
      state.scriptStages.stage11 = {
        batchStartEpisode: data.batchStartEpisode,
        batchEndEpisode: data.batchEndEpisode,
        batchEnrichedEpisodePlan: data.batchEnrichedEpisodePlan,
        batchCausalConflictPlan: data.batchCausalConflictPlan,
        batchCausalConflictReview: data.batchCausalConflictReview,
        conflictMemory: data.conflictMemory,
        batches: data.batches || {},
        updated_at: new Date().toISOString(),
      };
      saveWorkspace();
    } catch (error) {
      state.error = error.message || "11 开头冲突钩子失败";
    } finally {
      clearRunningStage("11");
      render();
    }
  }

  async function runStage12() {
    if (!currentAssetReady()) {
      state.error = "请先导入框架资产，或从框架生成页面一键进入。";
      render();
      return;
    }
    const stage11 = state.scriptStages.stage11 || {};
    if (!hasContent(stage11.batchCausalConflictPlan)) {
      state.error = "请先完成 11 当前批次开头冲突钩子。";
      render();
      return;
    }
    state.runningStage = "12";
    state.error = null;
    render();
    try {
      const data = await requestJson("/api/framework-to-script/stage/12", {
        method: "POST",
        body: JSON.stringify({
          framework_asset_id: state.frameworkAssetId,
          batchStartEpisode: stage11.batchStartEpisode,
        }),
      });
      state.scriptStages.stage12 = {
        batchStartEpisode: data.batchStartEpisode,
        batchEndEpisode: data.batchEndEpisode,
        batchEnrichedEpisodePlan: data.batchEnrichedEpisodePlan,
        batchCausalConflictPlan: data.batchCausalConflictPlan,
        batchScriptText: data.batchScriptText,
        batchScriptReview: data.batchScriptReview,
        scriptMemory: data.scriptMemory,
        batches: data.batches || {},
        updated_at: new Date().toISOString(),
      };
      saveWorkspace();
    } catch (error) {
      state.error = error.message || "12 正文及对话失败";
    } finally {
      clearRunningStage("12");
      render();
    }
  }

  function renderTree(value, keyName = "root", depth = 0) {
    const clean = stripRaw(value);
    if (clean === null || clean === undefined || clean === "") {
      return `<div class="wts-empty-inline">暂无内容</div>`;
    }
    if (Array.isArray(clean)) {
      if (!clean.length) return `<div class="wts-empty-inline">暂无条目</div>`;
      return `<div class="wts-tree-list">${clean.map((item, index) => `
        <details class="wts-tree-node" ${depth < 1 ? "open" : ""}>
          <summary>${escapeHtml(labelFor(keyName))} ${index + 1}</summary>
          <div>${renderTree(item, keyName, depth + 1)}</div>
        </details>
      `).join("")}</div>`;
    }
    if (typeof clean === "object") {
      const entries = Object.entries(clean).filter(([key]) => !RAW_KEYS.has(key));
      if (!entries.length) return `<div class="wts-empty-inline">暂无内容</div>`;
      return `<div class="wts-tree-list">${entries.map(([key, item]) => {
        const complex = item && typeof item === "object";
        return complex ? `
          <details class="wts-tree-node" ${depth < 1 ? "open" : ""}>
            <summary>${escapeHtml(labelFor(key))}</summary>
            <div>${renderTree(item, key, depth + 1)}</div>
          </details>
        ` : `
          <div class="wts-tree-leaf">
            <b>${escapeHtml(labelFor(key))}</b>
            <span>${escapeHtml(item)}</span>
          </div>
        `;
      }).join("")}</div>`;
    }
    return `<div class="wts-tree-text">${escapeHtml(clean)}</div>`;
  }

  function renderAssetPanel() {
    if (!state.assetPanelOpen) return "";
    return `
      <section class="wts-card wts-asset-panel" id="frameworkAssetPanel">
        <div class="wts-card-head">
          <div>
            <h2>导入框架资产</h2>
            <p>选择已完成 07 最终策划包的框架资产，导入后即可执行 08+ 链路。</p>
          </div>
          <button type="button" class="wts-btn ghost" data-action="close-asset-panel">收起</button>
        </div>
        ${state.isLoadingAsset ? `<div class="wts-loading">正在读取框架资产...</div>` : ""}
        <div class="wts-asset-list">
          ${state.assets.length ? state.assets.map(renderAssetItem).join("") : `<div class="wts-empty">暂无可导入框架资产。请先在框架生成页面完成 01-07 并保存。</div>`}
        </div>
      </section>
    `;
  }

  function renderAssetItem(asset) {
    const disabled = asset.can_import ? "" : "disabled";
    const meta = [
      asset.target_format || "未填写类型",
      asset.episodes_per_season ? `${asset.episodes_per_season} 集` : "",
      asset.minutes_per_episode ? `${asset.minutes_per_episode} 分钟/集` : "",
      `更新时间：${formatDate(asset.updated_at || asset.created_at)}`,
    ].filter(Boolean);
    return `
      <article class="wts-asset-item">
        <div>
          <h3>${escapeHtml(asset.title || "未命名框架资产")}</h3>
          <div class="wts-meta">
            <span>原文：${escapeHtml(asset.source_title || "未填写")}</span>
            ${meta.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
            <span>${asset.can_import ? "可导入" : "不可导入"}</span>
          </div>
          <p>${escapeHtml(asset.summary || "暂无摘要")}</p>
        </div>
        <button type="button" class="wts-btn" data-action="import-asset" data-asset-id="${escapeHtml(asset.asset_id)}" ${disabled}>导入</button>
      </article>
    `;
  }

  function renderImportedSummary() {
    if (!currentAssetReady()) {
      return `
        <section class="wts-card wts-empty-state">
          <h2>请先导入框架资产，或从框架生成页面一键进入。</h2>
          <p>框架生成与框架转剧本是两个独立工作区；这里会从已保存的框架资产继续 08+。</p>
        </section>
      `;
    }
    const asset = state.importedFrameworkAsset || {};
    return `
      <section class="wts-card">
        <div class="wts-card-head">
          <div>
            <span class="wts-label">已导入框架资产</span>
            <h2>${escapeHtml(asset.title || "未命名框架资产")}</h2>
            <p>${escapeHtml(asset.summary || "已导入，可以执行 08+ 链路。")}</p>
          </div>
          <div class="wts-version">
            <span>当前框架版本：${escapeHtml(state.frameworkAssetId)}</span>
            <span>保存时间：${escapeHtml(formatDate(asset.updated_at || asset.created_at))}</span>
            <button type="button" class="wts-btn ghost" data-action="save-workspace">保存当前版本</button>
          </div>
        </div>
        <div class="wts-summary-grid">
          ${[
            ["worldview_plan", "世界观"],
            ["character_plan", "人物"],
            ["beat_checkpoint_timeline", "节拍"],
            ["character_storylines", "故事线"],
            ["adaptation_guide", "改编指引"],
            ["framework_plan_package", "最终策划包"],
          ].map(([key, title]) => `
            <details class="wts-output">
              <summary>${escapeHtml(title)}</summary>
              ${renderTree(key === "framework_plan_package" ? state.frameworkPlanPackage : frameworkStageValue(key), key)}
            </details>
          `).join("")}
        </div>
      </section>
    `;
  }

  function renderStageCard(id, title, status, buttonText, action, disabled, body) {
    return `
      <article class="wts-step ${status === "已完成" ? "done" : disabled ? "locked" : ""}">
        <b>${escapeHtml(id)}</b>
        <div>
          <div class="wts-step-head">
            <h3>${escapeHtml(title)}</h3>
            <span>${escapeHtml(status)}</span>
          </div>
          <div class="wts-step-actions">
            <button type="button" data-action="${escapeHtml(action)}" ${disabled ? "disabled" : ""}>${escapeHtml(buttonText)}</button>
          </div>
          ${body || ""}
        </div>
      </article>
    `;
  }

  function renderStages() {
    const locked = !currentAssetReady() || state.isRunning || Boolean(state.runningStage);
    const stage08 = state.scriptStages.stage08 || {};
    const stage09 = state.scriptStages.stage09 || {};
    const stage10 = state.scriptStages.stage10 || {};
    const stage11 = state.scriptStages.stage11 || {};
    const stage12 = state.scriptStages.stage12 || {};
    const has08 = hasObject(stage08.sceneDictionary);
    const has09 = hasObject(stage09.appearanceMapping);
    const has10Plan = hasContent(stage10Plan(stage10));
    const has10Output = has10Plan || hasContent(stage10Text(stage10));
    const has10 = has10Plan;
    const has11 = hasContent(stage11.batchCausalConflictPlan);
    const has12 = hasContent(stage12.batchScriptText);
    return `
      <section class="wts-card" id="scriptStageArea">
        <div class="wts-card-head">
          <div>
            <h2>框架到剧本链路</h2>
            <p>未导入框架前，阶段按钮会保持禁用。</p>
          </div>
          <button type="button" class="wts-btn ghost" data-action="show-version-history">版本历史</button>
        </div>
               <div class="wts-steps">
          ${renderStageCard(
            "08",
            "场景字典提炼",
            state.runningStage === "08" ? "运行中" : has08 ? "已完成" : "待运行",
            has08 ? "重新运行 08" : "运行 08",
            "run-stage-08",
            locked,
            has08
              ? `<p class="wts-hint">已完成</p>`
              : `<p class="wts-hint">运行完成前不展示输出；结果会自动缓存并供后续阶段使用。</p>`
          )}

          ${renderStageCard(
            "09",
            "角色外观映射",
            state.runningStage === "09" ? "运行中" : has09 ? "已完成" : has08 ? "待运行" : "等待 08",
            has09 ? "重新运行 09" : "运行 09",
            "run-stage-09",
            locked || !has08,
            has09
              ? `<p class="wts-hint">已完成</p>`
              : `<p class="wts-hint">运行完成前不展示输出；结果会自动缓存并供后续阶段使用。</p>`
          )}
          ${renderStageCard(
            "10",
            "分集细化方案",
            state.runningStage === "10" ? "运行中" : has10 ? "已完成" : has09 ? "待运行" : "等待 09",
            has10 ? "重新运行 10" : "运行 10",
            "run-stage-10",
            locked || !has09,
            has10 ? `
              <details class="wts-output" open>
                <summary>分集细化文本</summary>
                ${renderTree(
                  stage10.enrichedEpisodePlanText ||
                  stage10.allEnrichedEpisodePlanText ||
                  "已生成结构化分集细化方案，供 11/12 阶段继续使用；本次未返回分集细化文本。",
                  "enrichedEpisodePlanText"
                )}
              </details>
            ` : `<p class="wts-hint">将沿用当前导入的框架资产和已完成的 08/09 输出。</p>`
          )}
          ${renderStageCard(
            "11",
            "开头冲突钩子",
            state.runningStage === "11" ? "运行中" : has11 ? "已完成" : has10Output ? "待运行" : "等待 10",
            has11 ? "运行下一批 11" : "运行 11",
            "run-stage-11",
            locked || !has10Output,
            has11 ? `
              <details class="wts-output" open>
                <summary>第 ${escapeHtml(stage11.batchStartEpisode || "")}-${escapeHtml(stage11.batchEndEpisode || "")} 集因果冲突</summary>
                ${renderTree(stage11.batchCausalConflictPlan, "batchCausalConflictPlan")}
              </details>
              <details class="wts-output">
                <summary>因果冲突审核</summary>
                ${renderTree(stage11.batchCausalConflictReview, "batchCausalConflictReview")}
              </details>
              ${stage11.conflictMemory ? `
                <details class="wts-output">
                  <summary>因果冲突记忆</summary>
                  ${renderTree(stage11.conflictMemory, "conflictMemory")}
                </details>
              ` : ""}
            ` : `<p class="wts-hint">${state.runningStage ? `当前 ${escapeHtml(state.runningStage)} 阶段运行态锁定，完成或超时后可继续。` : ""}</p>`
          )}
          ${renderStageCard(
            "12",
            "正文及对话",
            state.runningStage === "12" ? "运行中" : has12 ? "已完成" : has11 ? "待运行" : "待运行",
            has12 ? "运行下一批 12" : "运行 12",
            "run-stage-12",
            locked || !has11,
            has12 ? `
              <details class="wts-output" open>
                <summary>第 ${escapeHtml(stage12.batchStartEpisode || "")}-${escapeHtml(stage12.batchEndEpisode || "")} 集正文</summary>
                ${renderTree(stage12.batchScriptText, "batchScriptText")}
              </details>
              <details class="wts-output">
                <summary>正文审核</summary>
                ${renderTree(stage12.batchScriptReview, "batchScriptReview")}
              </details>
              ${stage12.scriptMemory ? `
                <details class="wts-output">
                  <summary>正文记忆</summary>
                  ${renderTree(stage12.scriptMemory, "scriptMemory")}
                </details>
              ` : ""}
            ` : `<p class="wts-hint"></p>`
          )}
        </div>
      </section>
    `;
  }

  function render() {
    const plannerUrl = `${config.frameworkPlannerUrl || "/framework-planner"}${authToken ? `?auth_token=${encodeURIComponent(authToken)}` : ""}`;
    const workspaceUrl = `${config.workspaceUrl || "/workspace"}${authToken ? `?auth_token=${encodeURIComponent(authToken)}` : ""}`;
    app.innerHTML = `
      <main class="wts-shell">
        <header class="wts-header">
          <div>
            <div class="wts-eyebrow">Framework Asset to Script</div>
            <h1>框架转剧本</h1>
            <p>导入剧本框架，进行剧本创作。</p>
          </div>
          <div class="wts-actions">
            <button type="button" class="wts-btn" data-action="open-asset-panel">导入框架资产</button>
            <a class="wts-btn ghost" href="${escapeHtml(plannerUrl)}">返回框架生成</a>
            <a class="wts-btn ghost" href="${escapeHtml(workspaceUrl)}">返回主工作台</a>
          </div>
        </header>
        ${state.error ? `<section class="wts-error" id="frameworkToScriptError">${escapeHtml(state.error)}</section>` : `<section class="wts-error hidden" id="frameworkToScriptError"></section>`}
        ${renderAssetPanel()}
        ${renderImportedSummary()}
        ${renderStages()}
      </main>
    `;
  }

  app.addEventListener("click", (event) => {
    const target = event.target && event.target.closest ? event.target.closest("[data-action]") : null;
    if (!target) return;
    const action = target.dataset.action;
    if (action === "open-asset-panel") {
      state.assetPanelOpen = true;
      loadAssets();
    } else if (action === "close-asset-panel") {
      state.assetPanelOpen = false;
      render();
    } else if (action === "import-asset") {
      importAsset(target.dataset.assetId);
    } else if (action === "run-stage-08") {
      runStage08();
    } else if (action === "run-stage-09") {
      runStage09();
    } else if (action === "run-stage-10") {
      runStage10();
    } else if (action === "run-stage-11") {
      runStage11();
    } else if (action === "run-stage-12") {
      runStage12();
    } else if (action === "save-workspace") {
      saveWorkspace();
      state.error = null;
      render();
    } else if (action === "show-version-history") {
      state.assetPanelOpen = true;
      loadAssets();
    }
  });

  restoreRunningStage();
  reconcileRunningStageResult();
  render();

  if (state.frameworkAssetId && (state.runningStage || !currentAssetReady())) {
    importAsset(state.frameworkAssetId, { skipConfirm: true });
  }
})();
