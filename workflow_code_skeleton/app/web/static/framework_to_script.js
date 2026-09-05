(() => {
  const app = document.getElementById("framework-to-script-app");
  if (!app) return;

  const config = window.FRAMEWORK_TO_SCRIPT_CONFIG || {};
  const params = new URLSearchParams(window.location.search);
  const authToken = params.get("auth_token") || "";
  const STORAGE_KEY = "frameworkToScriptWorkspace.v1";
  const LAST_ASSET_STORAGE_KEY = "frameworkToScriptLastAsset.v1";
  const READING_STATE_STORAGE_KEY = "frameworkToScriptReadingState.v1";
  const RUNNING_STAGE_STORAGE_KEY = "frameworkToScriptRunningStage.v1";
  const ASSET_SYNC_STORAGE_KEY = "ideaToScripts.assetSync.v2";
  const ASSET_SYNC_CHANNEL_NAME = "idea-to-scripts-assets-v2";
  const ASSET_SYNC_SOURCE = `framework-to-script-${Date.now()}-${Math.random().toString(36).slice(2)}`;
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
    appearanceMapping: "角色外观匹配场景",
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
    stages: {},
    completedStages: [],
    settings: {},
    scriptStages: {},
    preferenceSnapshot: {},
    preferenceSource: "none",
    assets: [],
    assetsLastRefreshedAt: "",
    assetPanelOpen: false,
    isLoadingAsset: false,
    isRunning: false,
    runningStage: "",
    runningStartedAt: "",
    stageRuns: [],
    activeRun: null,
    runPollTimer: null,
    autoGenerateScript: false,
    autoGenerateInFlight: false,
    lastRunBatchRefreshKey: "",
    lastRunPartialRenderKey: "",
    scriptLocked: false,
    scriptLockedAt: "",
    lockStatus: "",
    error: null,
    importStatus: "",
    frameworkSource: "",
  }, loadWorkspace());
  state.settings = Object.assign({}, state.settings || {}, loadReadingSettings());
  state.runPollTimer = null;
  state.lastRunPartialRenderKey = "";
  let localStageRecoveryTimer = null;
  let localStageRecoveryInFlight = false;
  let runPollInFlight = false;
  let resultSyncInFlight = false;
  let lastResultSyncAt = 0;

  const urlAssetId = params.get("framework_asset_id") || params.get("asset_id") || "";
  const directFromPlanner = Boolean(urlAssetId && (params.has("source_framework_project_id") || params.has("project_id")));
  if (urlAssetId && (directFromPlanner || String(urlAssetId) !== String(state.frameworkAssetId || ""))) {
    window.localStorage.removeItem(STORAGE_KEY);
    window.localStorage.removeItem(RUNNING_STAGE_STORAGE_KEY);
    state.frameworkAssetId = urlAssetId;
    saveLastAssetId(urlAssetId);
    state.frameworkSource = "刚刚完成的框架";
    state.projectId = null;
    state.importedFrameworkAsset = null;
    state.frameworkPlanPackage = null;
    state.stageOutputs = {};
    state.stages = {};
    state.completedStages = [];
    state.scriptStages = {};
    state.preferenceSnapshot = {};
    state.preferenceSource = "none";
    state.autoGenerateScript = false;
    state.autoGenerateInFlight = false;
    state.lastRunBatchRefreshKey = "";
    state.lastRunPartialRenderKey = "";
    state.scriptLocked = false;
    state.scriptLockedAt = "";
    state.lockStatus = "";
    state.runningStage = "";
    state.runningStartedAt = "";
    state.isRunning = false;
  } else if (!urlAssetId && !state.frameworkAssetId) {
    const lastAssetId = loadLastAssetId();
    if (lastAssetId) {
      // 页面刷新不应清空当前任务。这里只恢复轻量资产指针，完整内容随后从后端加载。
      state.frameworkAssetId = lastAssetId;
      state.projectId = lastAssetId;
      state.assetPanelOpen = false;
      state.isLoadingAsset = true;
      state.frameworkSource = "上次打开的框架资产";
    } else {
      state.assetPanelOpen = true;
    }
  }
  if (state.frameworkAssetId && !urlAssetId) syncAssetIdInUrl(state.frameworkAssetId);

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

  function syncAssetIdInUrl(assetId) {
    try {
      const url = new URL(window.location.href);
      const value = String(assetId || "").trim();
      if (value) url.searchParams.set("framework_asset_id", value);
      else url.searchParams.delete("framework_asset_id");
      window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
    } catch (_) {}
  }

  async function requestJson(path, options) {
    const response = await fetch(apiUrl(path), Object.assign({ headers: headers(), cache: "no-store" }, options || {}));
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false || data.ok === false) {
      const detail = data.detail && typeof data.detail === "object" ? data.detail : {};
      const detailMessage = detail.error_message || detail.message || "";
      const failedSubStage = detail.failed_sub_stage ? `（${detail.failed_sub_stage}）` : "";
      const debugPath = detail.debug_path ? `debug: ${detail.debug_path}` : "";
      const requestError = new Error(
        [data.message || data.error || "请求失败，请稍后重试。", failedSubStage, detailMessage, debugPath]
          .filter(Boolean)
          .join(" ")
      );
      requestError.status = response.status;
      requestError.payload = data;
      throw requestError;
    }
    return stripRaw(data);
  }

  let assetSyncChannel = null;
  let assetRefreshTimer = null;
  let assetRefreshInFlight = null;

  function announceAssetChange(reason, detail = {}) {
    const payload = {
      source: ASSET_SYNC_SOURCE,
      reason: String(reason || "asset-updated"),
      detail,
      at: Date.now(),
    };
    try {
      window.localStorage.setItem(ASSET_SYNC_STORAGE_KEY, JSON.stringify(payload));
    } catch (_) {}
    try {
      assetSyncChannel?.postMessage(payload);
    } catch (_) {}
  }

  async function refreshAssetsFromBackend() {
    const beforeSignature = visibleWorkspaceSignature();
    await loadAssets({ openPanel: false, silent: true });
    const currentId = String(state.frameworkAssetId || "");
    const currentExists = !currentId || state.assets.some((asset) => String(asset.asset_id || asset.project_id || "") === currentId);
    if (!currentExists) {
      stopRunPolling();
      state.frameworkAssetId = null;
      syncAssetIdInUrl("");
      state.projectId = null;
      state.importedFrameworkAsset = null;
      state.frameworkPlanPackage = null;
      state.stageOutputs = {};
      state.stages = {};
      state.completedStages = [];
      state.scriptStages = {};
      state.scriptLocked = false;
      state.scriptLockedAt = "";
      state.assetPanelOpen = true;
      state.error = "当前框架资产已被删除，请重新选择资产。";
      saveWorkspace();
      render();
      return;
    }
    if (state.frameworkAssetId && !anyStageRunning()) {
      await importAsset(state.frameworkAssetId, {
        quiet: true,
        skipConfirm: true,
        skipRunRefresh: true,
        preservePanel: true,
      });
    } else if (state.frameworkAssetId) {
      await fetchStageRuns();
    }
    const afterSignature = visibleWorkspaceSignature();
    if (state.assetPanelOpen || beforeSignature !== afterSignature) {
      render();
      return;
    }
    const activeRun = state.activeRun && isRunActive(state.activeRun) ? state.activeRun : null;
    if (activeRun) updateActiveRunDom(activeRun);
    const brandStatus = app.querySelector("[data-brand-motion-status]");
    if (brandStatus) brandStatus.textContent = brandMotionStatusText();
  }

  function scheduleAssetRefresh() {
    window.clearTimeout(assetRefreshTimer);
    assetRefreshTimer = window.setTimeout(() => {
      if (assetRefreshInFlight) return;
      assetRefreshInFlight = refreshAssetsFromBackend()
        .catch(() => {})
        .finally(() => {
          assetRefreshInFlight = null;
        });
    }, 180);
  }

  function bindAssetRefreshEvents() {
    if (typeof window.BroadcastChannel === "function") {
      assetSyncChannel = new window.BroadcastChannel(ASSET_SYNC_CHANNEL_NAME);
      assetSyncChannel.addEventListener("message", (event) => {
        if (event.data?.source !== ASSET_SYNC_SOURCE) scheduleAssetRefresh();
      });
    }
    window.addEventListener("storage", (event) => {
      if (event.key === ASSET_SYNC_STORAGE_KEY) scheduleAssetRefresh();
    });
    window.addEventListener("focus", scheduleAssetRefresh);
    window.addEventListener("pageshow", scheduleAssetRefresh);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") scheduleAssetRefresh();
    });
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

  function loadLastAssetId() {
    try {
      return String(window.localStorage.getItem(LAST_ASSET_STORAGE_KEY) || "").trim();
    } catch (_) {
      return "";
    }
  }

  function loadReadingSettings() {
    try {
      const raw = window.localStorage.getItem(READING_STATE_STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function saveReadingSettings() {
    try {
      window.localStorage.setItem(READING_STATE_STORAGE_KEY, JSON.stringify({
        outputDetailsOpen: (state.settings || {}).outputDetailsOpen || {},
        readingDetailsOpen: (state.settings || {}).readingDetailsOpen || {},
      }));
    } catch (_) {}
  }

  function saveLastAssetId(assetId) {
    try {
      const value = String(assetId || "").trim();
      if (value) window.localStorage.setItem(LAST_ASSET_STORAGE_KEY, value);
      else window.localStorage.removeItem(LAST_ASSET_STORAGE_KEY);
    } catch (_) {}
  }

  function saveWorkspace() {
    saveLastAssetId(state.frameworkAssetId);
    saveReadingSettings();
    const snapshot = stripRaw({
      frameworkAssetId: state.frameworkAssetId,
      projectId: state.projectId,
      importedFrameworkAsset: state.importedFrameworkAsset,
      frameworkPlanPackage: state.frameworkPlanPackage,
      stageOutputs: state.stageOutputs,
      stages: state.stages,
      completedStages: state.completedStages,
      settings: state.settings,
      scriptStages: state.scriptStages,
      frameworkSource: state.frameworkSource,
      preferenceSnapshot: state.preferenceSnapshot,
      preferenceSource: state.preferenceSource,
      autoGenerateScript: state.autoGenerateScript,
      scriptLocked: state.scriptLocked,
      scriptLockedAt: state.scriptLockedAt,
    });
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
    } catch (error) {
      // 全剧正文可能超过浏览器 localStorage 配额。退化为轻量恢复信息，正文以后端资产为准。
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
          frameworkAssetId: state.frameworkAssetId,
          projectId: state.projectId,
          settings: state.settings,
          frameworkSource: state.frameworkSource,
          autoGenerateScript: state.autoGenerateScript,
          scriptLocked: state.scriptLocked,
          scriptLockedAt: state.scriptLockedAt,
        }));
      } catch (_) {}
    }
  }

  function attachKnowledgePayload(payload, stageNo) {
    const next = Object.assign({}, payload || {});
    const snapshot = state.preferenceSnapshot && typeof state.preferenceSnapshot === "object" ? state.preferenceSnapshot : {};
    const stagePreferences = snapshot.stage_preferences && typeof snapshot.stage_preferences === "object" ? snapshot.stage_preferences : {};
    const paddedStage = String(stageNo || "").padStart(2, "0");
    const stageKeyMap = { "08": "scene", "09": "appearance", "10": "episode", "11": "conflict", "12": "script_text" };
    const preference = String(stagePreferences[paddedStage] || stagePreferences[stageKeyMap[paddedStage]] || "");
    next.preference_snapshot = snapshot;
    next.preference_source = state.preferenceSource || (hasObject(snapshot) ? "framework_asset_snapshot" : "none");
    next.stage_preference_prompt = preference;
    next.user_stage_preference_prompt = preference;
    return next;
  }

  function normalizePreferenceSnapshot(value) {
    const snapshot = value && typeof value === "object" && !Array.isArray(value) ? value : {};
    const stagePreferences = snapshot.stage_preferences && typeof snapshot.stage_preferences === "object" ? snapshot.stage_preferences : {};
    return {
      selected_knowledge_tag_ids: Array.isArray(snapshot.selected_knowledge_tag_ids) ? snapshot.selected_knowledge_tag_ids.map(String) : [],
      selected_knowledge_tag_names: Array.isArray(snapshot.selected_knowledge_tag_names) ? snapshot.selected_knowledge_tag_names.map(String) : [],
      stage_preferences: Object.assign({}, stagePreferences),
      captured_at: String(snapshot.captured_at || ""),
      source: String(snapshot.source || (hasObject(stagePreferences) ? "knowledge_library" : "")),
    };
  }

  function setPreferenceSnapshot(snapshot, source) {
    const normalized = normalizePreferenceSnapshot(snapshot);
    state.preferenceSnapshot = normalized;
    state.preferenceSource = hasObject(normalized.stage_preferences) ? source : "none";
  }

  function preferenceStatusText() {
    if (state.preferenceSource === "framework_asset_snapshot") return "当前框架偏好：已继承自框架资产";
    if (state.preferenceSource === "imported_json") return "当前框架偏好：导入 JSON 中已包含";
    return "当前框架偏好：未记录，将使用默认策略";
  }

  function outputDetailsStorageKey(id) {
    return [state.frameworkAssetId || "no-asset", id].join(":");
  }

  function isOutputDetailsOpen(id) {
    const map = (state.settings && state.settings.outputDetailsOpen) || {};
    return Boolean(map[outputDetailsStorageKey(id)]);
  }

  function outputDetailsAttrs(id) {
    return `data-output-details-id="${escapeHtml(id)}"${isOutputDetailsOpen(id) ? " open" : ""}`;
  }

  function outputContentAttrs(id, value) {
    return `${outputDetailsAttrs(id)} data-output-content-signature="${escapeHtml(contentFingerprint(value))}"`;
  }

  function contentFingerprint(value) {
    let text = "";
    try {
      text = typeof value === "string" ? value : JSON.stringify(value);
    } catch (_) {
      text = String(value ?? "");
    }
    let hash = 2166136261;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return `${text.length}:${(hash >>> 0).toString(36)}`;
  }

  function setOutputDetailsOpen(id, isOpen) {
    if (!state.settings || typeof state.settings !== "object") {
      state.settings = {};
    }
    const map = state.settings.outputDetailsOpen && typeof state.settings.outputDetailsOpen === "object"
      ? state.settings.outputDetailsOpen
      : {};
    const key = outputDetailsStorageKey(id);
    if (isOpen) {
      map[key] = true;
    } else {
      delete map[key];
    }
    state.settings.outputDetailsOpen = map;
    saveReadingSettings();
  }

  function persistedReadingDetailsKey(runtimeKey) {
    return [state.frameworkAssetId || "no-asset", runtimeKey].join(":");
  }

  function persistedReadingDetailsOpen(runtimeKey) {
    const map = (state.settings && state.settings.readingDetailsOpen) || {};
    const key = persistedReadingDetailsKey(runtimeKey);
    return Object.prototype.hasOwnProperty.call(map, key) ? Boolean(map[key]) : null;
  }

  function setPersistedReadingDetailsOpen(runtimeKey, isOpen) {
    if (!runtimeKey) return;
    if (!state.settings || typeof state.settings !== "object") state.settings = {};
    const map = state.settings.readingDetailsOpen && typeof state.settings.readingDetailsOpen === "object"
      ? state.settings.readingDetailsOpen
      : {};
    map[persistedReadingDetailsKey(runtimeKey)] = Boolean(isOpen);
    state.settings.readingDetailsOpen = map;
    saveReadingSettings();
  }

  const RUNNING_STAGE_TIMEOUT_MS = 1000 * 60 * 60 * 12;
  const RUN_POLL_INTERVAL_MS = 2000;
  const RESULT_SYNC_INTERVAL_MS = 4000;
  const RUNNING_STATUSES = new Set(["pending", "running"]);
  const LOCAL_RECOVERY_STAGES = new Set(["08", "09", "10"]);
  const BACKGROUND_RUN_STAGES = new Set(["11", "12"]);
  const STAGE_RUN_ACTIONS = new Set([
    "run-stage-08",
    "rerun-stage-08",
    "run-stage-09",
    "rerun-stage-09",
    "run-stage-10",
    "rerun-stage-10",
    "run-stage-11",
    "rerun-stage-11",
    "run-stage-12",
    "rerun-stage-12",
    "generate-full-script",
  ]);

  function anyStageRunning() {
    return Boolean(
      state.runningStage ||
      state.isRunning ||
      (state.activeRun && isRunActive(state.activeRun)) ||
      (state.stageRuns || []).some((run) => isRunActive(run))
    );
  }

  function saveRunningStage(stage, startedAt) {
    const stageText = String(stage || "");
    const startedText = String(
      startedAt ||
      (state.runningStage === stageText ? state.runningStartedAt : "") ||
      new Date().toISOString()
    );
    const payload = {
      runningStage: stageText,
      startedAt: startedText,
      frameworkAssetId: state.frameworkAssetId || "",
    };

    state.runningStage = payload.runningStage;
    state.runningStartedAt = payload.startedAt;
    state.isRunning = Boolean(payload.runningStage);
    if (LOCAL_RECOVERY_STAGES.has(payload.runningStage)) {
      startLocalStageRecoveryPolling();
    }

    try {
      window.localStorage.setItem(RUNNING_STAGE_STORAGE_KEY, JSON.stringify(payload));
    } catch (error) {
      console.warn("save running stage failed", error);
    }
  }

  function clearRunningStage(stage) {
    const stageText = String(stage || state.runningStage || "");
    if (stage && state.runningStage && String(stage) !== String(state.runningStage)) {
      return;
    }

    if (stageText) {
      state.stageRuns = (state.stageRuns || []).filter((run) => (
        String((run || {}).stage || "") !== stageText || !isRunActive(run)
      ));
      if (state.activeRun && String(state.activeRun.stage || "") === stageText) {
        state.activeRun = null;
      }
    }
    state.runningStage = "";
    state.runningStartedAt = "";
    state.isRunning = false;
    stopLocalStageRecoveryPollingIfIdle();

    try {
      window.localStorage.removeItem(RUNNING_STAGE_STORAGE_KEY);
    } catch (error) {
      console.warn("clear running stage failed", error);
    }
  }

  function setAutoGenerateScript(enabled) {
    state.autoGenerateScript = Boolean(enabled);
    saveWorkspace();
  }

  function stopLocalStageRecoveryPollingIfIdle() {
    if (LOCAL_RECOVERY_STAGES.has(String(state.runningStage || ""))) return;
    if (localStageRecoveryTimer) {
      window.clearInterval(localStageRecoveryTimer);
      localStageRecoveryTimer = null;
    }
  }

  function startLocalStageRecoveryPolling() {
    if (localStageRecoveryTimer) return;
    localStageRecoveryTimer = window.setInterval(async () => {
      const runningStage = String(state.runningStage || "");
      if (!LOCAL_RECOVERY_STAGES.has(runningStage) || !state.frameworkAssetId) {
        stopLocalStageRecoveryPollingIfIdle();
        return;
      }
      if (localStageRecoveryInFlight) return;
      localStageRecoveryInFlight = true;
      try {
        await importAsset(state.frameworkAssetId, {
          skipConfirm: true,
          skipRunRefresh: true,
          quiet: true,
        });
        const runs = await fetchStageRuns();
        const activeForStage = (runs || []).find((run) => (
          isRunActive(run) && String(run.stage || "") === runningStage
        ));
        if (!state.runningStage || stageResultBelongsToCurrentRun(runningStage)) {
          clearRunningStage(runningStage);
          state.error = null;
          render();
          if (state.autoGenerateScript && !(state.activeRun && isRunActive(state.activeRun))) {
            continueAutoGenerate().catch((error) => {
              state.error = error.message || "自动续跑失败";
              render();
            });
          }
        } else if (activeForStage) {
          const brandStatus = app.querySelector("[data-brand-motion-status]");
          if (brandStatus) brandStatus.textContent = brandMotionStatusText();
        } else {
          const startedAt = new Date(state.runningStartedAt || "").getTime();
          if (Number.isFinite(startedAt) && Date.now() - startedAt >= 15000) {
            const keptPrevious = stageHasCompleted(runningStage);
            clearRunningStage(runningStage);
            state.error = keptPrevious
              ? `${runningStage} 本次重新运行未生成新结果，已保留上一次成功结果，后续阶段仍可继续。`
              : `${runningStage} 运行已中断且未生成结果，请重新运行。`;
            render();
          }
        }
      } catch (error) {
        console.warn("local stage recovery refresh failed", error);
      } finally {
        localStageRecoveryInFlight = false;
      }
    }, 5000);
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

      state.runningStage = String(payload.runningStage || "");
      state.runningStartedAt = payload.startedAt;
      state.isRunning = Boolean(state.runningStage);
      if (LOCAL_RECOVERY_STAGES.has(state.runningStage)) {
        startLocalStageRecoveryPolling();
      }
    } catch (error) {
      console.warn("restore running stage failed", error);
      try {
        window.localStorage.removeItem(RUNNING_STAGE_STORAGE_KEY);
      } catch (_) {}
    }
  }

  function isRunActive(run) {
    return Boolean(run && RUNNING_STATUSES.has(String(run.status || "")));
  }

  function runDebugSummary(run) {
    return "";
  }

  function runErrorMessage(run) {
    const debugText = runDebugSummary(run);
    return [
      run && (run.latest_error || run.progress_text) ? (run.latest_error || run.progress_text) : "阶段运行失败",
      debugText,
    ].filter(Boolean).join(" ");
  }

  function applyRunState(run) {
    if (!run || typeof run !== "object" || !run.run_id) {
      state.activeRun = null;
      state.stageRuns = Array.isArray(state.stageRuns) ? state.stageRuns : [];
      return;
    }
    state.activeRun = run;
    state.stageRuns = [run].concat((state.stageRuns || []).filter((item) => item && item.run_id !== run.run_id));
    if (isRunActive(run)) {
      state.runningStage = String(run.stage || "");
      state.runningStartedAt = run.started_at || state.runningStartedAt || "";
      state.isRunning = Boolean(state.runningStage);
      state.error = null;
      saveRunningStage(state.runningStage, state.runningStartedAt || run.started_at || "");
      return;
    }
    if (run.status === "failed") {
      state.error = runErrorMessage(run);
      setAutoGenerateScript(false);
      clearRunningStage(run.stage);
      return;
    }
    if (run.status === "succeeded" && state.runningStage === String(run.stage || "")) {
      clearRunningStage(run.stage);
      state.error = null;
    }
  }

  async function fetchStageRuns() {
    if (!state.frameworkAssetId) return [];
    const data = await requestJson(`/api/framework-to-script/runs?framework_asset_id=${encodeURIComponent(state.frameworkAssetId)}`);
    const runs = Array.isArray(data.runs) ? data.runs : [];
    state.stageRuns = runs;
    const active = runs.find((run) => isRunActive(run));
    if (active) {
      applyRunState(active);
      if (BACKGROUND_RUN_STAGES.has(String(active.stage || ""))) {
        startRunPolling(active);
      } else {
        startLocalStageRecoveryPolling();
      }
    } else if (state.runningStage && BACKGROUND_RUN_STAGES.has(String(state.runningStage || ""))) {
      stopRunPolling();
      clearRunningStage(state.runningStage);
    } else if (state.activeRun && LOCAL_RECOVERY_STAGES.has(String(state.activeRun.stage || ""))) {
      state.activeRun = null;
    }
    return runs;
  }

  function stopRunPolling() {
    if (state.runPollTimer) {
      window.clearInterval(state.runPollTimer);
      state.runPollTimer = null;
    }
  }

  async function refreshAssetAfterRunUpdate() {
    if (!state.frameworkAssetId) return;
    await importAsset(state.frameworkAssetId, {
      quiet: true,
      skipConfirm: true,
      skipRunRefresh: true,
      preservePanel: true,
    });
    await loadAssets({ openPanel: false, silent: true }).catch(() => {});
    announceAssetChange("script-stage-updated", { framework_asset_id: state.frameworkAssetId });
  }

  async function syncGeneratedResultsFromBackend(options = {}) {
    if (!state.frameworkAssetId || resultSyncInFlight) return false;
    const force = Boolean(options.force);
    const now = Date.now();
    if (!force && now - lastResultSyncAt < RESULT_SYNC_INTERVAL_MS) return false;
    resultSyncInFlight = true;
    lastResultSyncAt = now;
    const beforeSignature = visibleWorkspaceSignature();
    try {
      const knownStage11 = numericKeys(stage11BatchMap({ completeOnly: true }));
      const knownStage12 = numericKeys(stage12BatchMap({ completeOnly: true }));
      const params = new URLSearchParams({
        framework_asset_id: String(state.frameworkAssetId),
        known_stage11: knownStage11.join(","),
        known_stage12: knownStage12.join(","),
      });
      const data = await requestJson(`/api/framework-to-script/results-sync?${params.toString()}`);
      if (data.stage11 && hasObject(data.stage11.batches)) mergeStage11(data.stage11);
      if (data.stage12 && hasObject(data.stage12.batches)) mergeStage12(data.stage12);
      if (data.script_locked) state.scriptLocked = true;
      synchronizeStageTrackingFromResults();
      saveLastAssetId(state.frameworkAssetId);
      return visibleWorkspaceSignature() !== beforeSignature;
    } catch (error) {
      console.warn("generated result background sync failed", error);
      return false;
    } finally {
      resultSyncInFlight = false;
    }
  }

  function partialValueSignature(value) {
    let text = "";
    try {
      text = typeof value === "string" ? value : JSON.stringify(value);
    } catch (_) {
      text = String(value ?? "");
    }
    return `${text.length}:${text.slice(0, 80)}:${text.slice(-80)}`;
  }

  function visibleWorkspaceSignature() {
    const scriptStages = state.scriptStages || {};
    const asset = state.importedFrameworkAsset || {};
    return [
      String(state.frameworkAssetId || ""),
      String(asset.asset_id || asset.project_id || ""),
      String(state.scriptLocked || ""),
      (state.completedStages || []).map(String).sort().join(","),
      contentFingerprint(scriptStages.stage08 || {}),
      contentFingerprint(scriptStages.stage09 || {}),
      contentFingerprint(scriptStages.stage10 || {}),
      contentFingerprint(scriptStages.stage11 || {}),
      contentFingerprint(scriptStages.stage12 || {}),
    ].join("|");
  }

  function mergeRunPartialResult(run) {
    const stage = String((run || {}).stage || "");
    const partial = run && run.latest_partial_result && typeof run.latest_partial_result === "object"
      ? run.latest_partial_result
      : {};
    const startEpisode = partial.start_episode || partial.batchStartEpisode || partial.batch_start_episode || partial.selected_batch_start || "";
    const endEpisode = partial.end_episode || partial.batchEndEpisode || partial.batch_end_episode || "";

    if (stage === "11") {
      const conflictPlan =
        partial.batchCausalConflictPlan
        || partial.batch_causal_conflict_plan
        || partial.batchCausalConflict
        || partial.batch_causal_conflict;
      if (!hasContent(conflictPlan)) return false;
      const savedBatch = stage11BatchMap({ completeOnly: true })[String(startEpisode || "")];
      // 后端已经完整保存的批次不可再被较旧的轮询临时态降级为 running，
      // 否则“（生成中）”会在保存完成后被重新挂回去。
      if (savedBatch && isStage11BatchComplete(savedBatch)) return false;
      const partialKey = [
        run.run_id,
        stage,
        startEpisode,
        endEpisode,
        partial.sub_stage || "",
        partial.review_round || "",
        partial.rewrite_round || "",
        partialValueSignature(conflictPlan),
      ].join("|");
      if (state.lastRunPartialRenderKey === partialKey) return false;
      mergeStage11({
        batchStartEpisode: startEpisode,
        batchEndEpisode: endEpisode,
        batchCausalConflictPlan: conflictPlan,
        batchCausalConflictReview: partial.batchCausalConflictReview || partial.batch_causal_conflict_review,
        conflictMemory: partial.conflictMemory || partial.conflict_memory,
        // 轮询中的 write/review/rewrite/memory 都只是可预览的临时态。
        // 明确标为 running，不能继承上一批的 complete 状态并提前放行后续阶段。
        batchPipelineStatus: partial.batchPipelineStatus || partial.batch_pipeline_status || "running",
        completedSubStages: partial.completedSubStages || partial.completed_sub_stages || [],
      });
      state.lastRunPartialRenderKey = partialKey;
      saveWorkspace();
      return true;
    }

    if (stage === "12") {
      // 12 的 write/review/rewrite/memory 都是临时态。只展示已完整保存到资产的批次，
      // 避免把工作流包装 JSON 或未审核正文短暂渲染给用户。
      const pipelineStatus = String(partial.batchPipelineStatus || partial.batch_pipeline_status || "").toLowerCase();
      const completedSubStages = partial.completedSubStages || partial.completed_sub_stages || [];
      const fullySaved = pipelineStatus === "complete"
        && Array.isArray(completedSubStages)
        && completedSubStages.includes("script_memory");
      if (!fullySaved) return false;
      const batchScriptText = partial.batchScriptText || partial.batch_script_text;
      if (!hasContent(batchScriptText)) return false;
      const partialKey = [
        run.run_id,
        stage,
        startEpisode,
        endEpisode,
        partial.sub_stage || "",
        partial.review_round || "",
        partial.rewrite_round || "",
        partialValueSignature(batchScriptText),
      ].join("|");
      if (state.lastRunPartialRenderKey === partialKey) return false;
      mergeStage12({
        batchStartEpisode: startEpisode,
        batchEndEpisode: endEpisode,
        batchCausalConflictPlan: partial.batchCausalConflictPlan || partial.batch_causal_conflict_plan,
        batchScriptText,
        batchScriptReview: partial.batchScriptReview || partial.batch_script_review,
        scriptMemory: partial.scriptMemory || partial.script_memory,
        batchPipelineStatus: partial.batchPipelineStatus || partial.batch_pipeline_status,
        completedSubStages: partial.completedSubStages || partial.completed_sub_stages,
      });
      state.lastRunPartialRenderKey = partialKey;
      saveWorkspace();
      return true;
    }

    return false;
  }

  function renderStagesQuietly() {
    const node = app.querySelector("[data-script-stage-area]");
    if (!node) {
      render();
      return;
    }
    const interactionSnapshot = captureInteractionSnapshot(app);
    const template = document.createElement("template");
    template.innerHTML = renderStages().trim();
    const nextNode = template.content.firstElementChild;
    if (!nextNode) return;
    reuseStableOutputNodes(node, nextNode);
    node.replaceWith(nextNode);
    const brandStatus = app.querySelector("[data-brand-motion-status]");
    if (brandStatus) brandStatus.textContent = brandMotionStatusText();
    restoreInteractionSnapshot(interactionSnapshot, app);
  }

  async function pollRun(runId) {
    const id = String(runId || (state.activeRun || {}).run_id || "");
    if (!id || runPollInFlight) return;
    runPollInFlight = true;
    try {
      const data = await requestJson(`/api/framework-to-script/runs/${encodeURIComponent(id)}`);
      const run = data.run || {};
      applyRunState(run);
      const partialMerged = mergeRunPartialResult(run);
      if (isRunActive(run)) {
        const partial = run.latest_partial_result && typeof run.latest_partial_result === "object" ? run.latest_partial_result : {};
        const latestDone = partial.latest_batch_done || "";
        const refreshKey = latestDone ? `${run.run_id}:${latestDone}` : "";
        let savedBatchAdvanced = false;
        let assetChanged = await syncGeneratedResultsFromBackend();
        if (refreshKey && refreshKey !== state.lastRunBatchRefreshKey) {
          state.lastRunBatchRefreshKey = refreshKey;
          savedBatchAdvanced = true;
          assetChanged = assetChanged || await syncGeneratedResultsFromBackend({ force: true });
        }
        if (assetChanged || savedBatchAdvanced) {
          // 即使资产内容本身没有变化，completed_batch_starts 已推进时也要立刻重绘，
          // 让对应批次的“（生成中）”无需刷新页面即可自动消失。
          renderStagesQuietly();
        } else if (partialMerged) {
          renderStagesQuietly();
        } else {
          updateActiveRunDom(run);
        }
        return;
      }
      stopRunPolling();
      if (run.status === "succeeded") {
        await refreshAssetAfterRunUpdate();
        clearRunningStage(run.stage);
        state.error = null;
        if (state.autoGenerateScript) {
          await continueAutoGenerate();
          return;
        }
      } else if (run.status === "failed") {
        state.error = runErrorMessage(run);
        setAutoGenerateScript(false);
        clearRunningStage(run.stage);
      }
      render();
    } catch (error) {
      if (Number(error && error.status) === 404) {
        const staleRun = state.activeRun && String(state.activeRun.run_id || "") === id
          ? state.activeRun
          : (state.stageRuns || []).find((run) => String((run || {}).run_id || "") === id);
        const staleStage = String((staleRun || {}).stage || state.runningStage || "");
        stopRunPolling();
        state.stageRuns = (state.stageRuns || []).filter((run) => String((run || {}).run_id || "") !== id);
        if (state.activeRun && String(state.activeRun.run_id || "") === id) state.activeRun = null;
        if (!staleStage || String(state.runningStage || "") === staleStage) clearRunningStage(staleStage);
        setAutoGenerateScript(false);
        state.error = null;
        state.importStatus = "上次后台运行已结束，已恢复到最近保存进度。";
        await refreshAssetAfterRunUpdate().catch((refreshError) => {
          console.warn("stale run recovery asset refresh failed", refreshError);
        });
        render();
        return;
      }
      state.error = error.message || "运行状态刷新失败";
      render();
    } finally {
      runPollInFlight = false;
    }
  }

  function startRunPolling(run) {
    if (!run || !run.run_id) return;
    applyRunState(run);
    stopRunPolling();
    state.runPollTimer = window.setInterval(() => {
      pollRun(run.run_id);
    }, RUN_POLL_INTERVAL_MS);
    pollRun(run.run_id);
  }

  function hasStage12ScriptText() {
    const batches = stage12BatchMap();
    if (Object.keys(batches).some((key) => hasContent((batches[key] || {}).batchScriptText || (batches[key] || {}).batch_script_text))) {
      return true;
    }
    const stage12 = (state.scriptStages || {}).stage12 || {};
    if (!isStage12BatchComplete(stage12)) return false;
    return hasContent(stage12.batchScriptText || stage12.batch_script_text);
  }

  function numericKeys(value) {
  return Object.keys(value || {})
    .map((key) => String(key))
    .filter((key) => /^\d+$/.test(key))
    .sort((a, b) => Number(a) - Number(b));
}

  function expectedBatchStartsFromPlan(plan) {
    const starts = new Set();
    (Array.isArray(plan) ? plan : []).forEach((item, index) => {
      const episode = Number(
        (item && (item.episode || item.episodeNumber || item.episode_number || item.ep))
        || index + 1
      );
      if (Number.isFinite(episode) && episode > 0) {
        starts.add(String(Math.floor((episode - 1) / 5) * 5 + 1));
      }
    });
    return Array.from(starts).sort((a, b) => Number(a) - Number(b));
  }

  function expectedStage11Starts() {
    const stage10 = (state.scriptStages || {}).stage10 || {};
    return expectedBatchStartsFromPlan(stage10Plan(stage10));
  }

  function stage11PlanFromBatch(batch) {
  if (!batch || typeof batch !== "object") return null;
  return batch.batchCausalConflictPlan
    || batch.batch_causal_conflict_plan
    || batch.batchCausalConflict
    || batch.batch_causal_conflict
    || null;
}

function stage11BatchStartFromPlan(plan, fallback = "") {
  if (!plan || typeof plan !== "object") return String(fallback || "");
  const meta = plan.batch_meta || plan.batchMeta || {};
  return String(
    meta.start_episode
    || meta.startEpisode
    || plan.start_episode
    || plan.startEpisode
    || fallback
    || ""
  ).trim();
}

function completedSubStages(batch) {
  const stages = batch && (batch.completedSubStages || batch.completed_sub_stages);
  return Array.isArray(stages) ? stages.map((item) => String(item || "").trim()).filter(Boolean) : [];
}

function hasCompletedSubStages(batch, required) {
  const completed = new Set(completedSubStages(batch));
  return required.every((item) => completed.has(item));
}

function stage11ReviewFromBatch(batch) {
  return batch && (
    batch.batchCausalConflictReview
    || batch.batch_causal_conflict_review
    || batch.causalConflictReview
    || batch.causal_conflict_review
  );
}

function stage11MemoryFromBatch(batch) {
  return batch && (batch.conflictMemory || batch.conflict_memory);
}

function isStage11BatchComplete(batch) {
  if (!batch || typeof batch !== "object") return false;
  const hasCore = hasContent(stage11PlanFromBatch(batch))
    && hasContent(stage11ReviewFromBatch(batch))
    && hasContent(stage11MemoryFromBatch(batch));
  const pipelineStatus = String(batch.batchPipelineStatus || batch.batch_pipeline_status || "").toLowerCase();
  if (pipelineStatus) return pipelineStatus === "complete" && hasCore;
  // 兼容尚未写入 batchPipelineStatus 的旧资产；新运行一律有明确状态。
  return hasCore;
}

function stage11BatchHasDisplayableContent(batch) {
  if (!batch || typeof batch !== "object") return false;
  return hasContent(stage11PlanFromBatch(batch))
    || hasContent(stage11ReviewFromBatch(batch))
    || hasContent(stage11MemoryFromBatch(batch));
}

function addStage11BatchToMap(map, key, batch, options = {}) {
  if (!batch || typeof batch !== "object") return;
  if (options.completeOnly && !isStage11BatchComplete(batch)) return;
  if (!options.completeOnly && !stage11BatchHasDisplayableContent(batch)) return;

  const plan = stage11PlanFromBatch(batch) || batch;

  const start = String(
    batch.batchStartEpisode
    || batch.batch_start_episode
    || batch.startEpisode
    || batch.start_episode
    || stage11BatchStartFromPlan(plan, key)
    || key
    || ""
  ).trim();

  if (!start) return;

  const normalizedKey = /^\d+$/.test(start) ? start : String(key || start);
  map[normalizedKey] = Object.assign({}, map[normalizedKey] || {}, batch);
}

function stage11BatchMap(options = {}) {
  const stages = state.scriptStages || {};
  const outputs = state.stageOutputs || {};
  const stage11 = stages.stage11 || {};
  const map = {};
  const mapOptions = { completeOnly: Boolean(options.completeOnly) };

  [
    stage11.batches,
    stage11.batchCausalConflictBatches,
    stage11.batch_causal_conflict_batches,
    (outputs.stage11 || {}).batches,
    (outputs.framework_causal_conflict || {}).batches,
    (outputs.frameworkCausalConflict || {}).batches
  ].forEach((source) => {
    if (!source || typeof source !== "object" || Array.isArray(source)) return;
    Object.entries(source).forEach(([key, batch]) => addStage11BatchToMap(map, key, batch, mapOptions));
  });

  const topPlan =
    stage11.batchCausalConflictPlan
    || stage11.batch_causal_conflict_plan
    || (outputs.stage11 || {}).batchCausalConflictPlan
    || (outputs.stage11 || {}).batch_causal_conflict_plan;

  if (hasContent(topPlan)) {
    const start = String(
      stage11.batchStartEpisode
      || stage11.batch_start_episode
      || stage11BatchStartFromPlan(topPlan, "1")
      || "1"
    );
    addStage11BatchToMap(map, start, Object.assign({}, stage11, {
      batchCausalConflictPlan: topPlan
    }), mapOptions);
  }

  return map;
}

function isStage12BatchComplete(batch) {
  if (!batch || typeof batch !== "object") return false;
  const hasCore = hasContent(batch.batchScriptText || batch.batch_script_text)
    && hasContent(batch.batchScriptReview || batch.batch_script_review)
    && hasContent(batch.scriptMemory || batch.script_memory);
  const pipelineStatus = String(batch.batchPipelineStatus || batch.batch_pipeline_status || "").toLowerCase();
  if (pipelineStatus) return pipelineStatus === "complete" && hasCore;
  // 兼容尚未写入 batchPipelineStatus 的旧资产；新运行一律有明确状态。
  return hasCore;
}

function stage12BatchHasDisplayableContent(batch) {
  return Boolean(batch && typeof batch === "object" && hasContent(batch.batchScriptText || batch.batch_script_text));
}

function stage12BatchMap(options = {}) {
  const stage12 = ((state.scriptStages || {}).stage12 || {});
  const source = stage12.batches && typeof stage12.batches === "object" && !Array.isArray(stage12.batches)
    ? stage12.batches
    : {};
  const map = {};
  Object.entries(source).forEach(([key, batch]) => {
    const canUse = isStage12BatchComplete(batch);
    if (canUse) map[String(key)] = batch;
  });
  const canUseTopLevel = isStage12BatchComplete(stage12);
  if (!Object.keys(map).length && canUseTopLevel) {
    const start = String(stage12.batchStartEpisode || stage12.batch_start_episode || "1");
    map[start] = stage12;
  }
  return map;
}

  function ensureStage11BatchesOnState() {
  const normalizedBatches = stage11BatchMap();
  const current = (state.scriptStages || {}).stage11 || {};

  if (!Object.keys(normalizedBatches).length) {
    return current;
  }

  const currentBatches =
    current.batches && typeof current.batches === "object" && !Array.isArray(current.batches)
      ? current.batches
      : {};

  state.scriptStages.stage11 = {
    ...current,
    batches: Object.assign({}, currentBatches, normalizedBatches),
    updated_at: current.updated_at || new Date().toISOString()
  };

  return state.scriptStages.stage11;
}

  function stage11Completion() {
  const expected = expectedStage11Starts();
  const batches = stage11BatchMap({ completeOnly: true });
  const done = numericKeys(batches);

  const expectedForCheck = expected.length ? expected : done;
  const missing = missingBatchStarts(expectedForCheck, done);
  const completeByBatches = Boolean(expectedForCheck.length && missing.length === 0);

  return {
    expected: expectedForCheck,
    done,
    missing,
    complete: completeByBatches
  };
}

function stage12Completion() {
  const expected = numericKeys(stage11BatchMap({ completeOnly: true }));
  const done = numericKeys(stage12BatchMap({ completeOnly: true }));
  const hasCompleteScript = done.length > 0 || isStage12BatchComplete((state.scriptStages || {}).stage12 || {});
  const missing = missingBatchStarts(expected, done);

  return {
    expected,
    done,
    missing,
    complete: Boolean(
      (expected.length && missing.length === 0 && hasCompleteScript)
      || (!expected.length && hasCompleteScript)
    )
  };
}

  function missingBatchStarts(expected, done) {
    const completed = new Set((done || []).map((key) => String(key)));
    return (expected || []).filter((key) => !completed.has(String(key)));
  }

  function stageHasCompleted(stage) {
    const stages = state.scriptStages || {};
    const stage08 = stages.stage08 || {};
    const stage09 = stages.stage09 || {};
    const stage10 = stages.stage10 || {};
    const completed = new Set((state.completedStages || []).map((item) => String(item)));

    if (stage === "08") return hasObject(stage08.sceneDictionary);
    if (stage === "09") return hasObject(stage09.appearanceMapping);
    if (stage === "10") return completed.has("10") || hasContent(stage10Plan(stage10)) || hasContent(stage10Text(stage10));
    if (stage === "11") return stage11Completion().complete;
    if (stage === "12") return stage12Completion().complete;
    return false;
  }

  function stageResultUpdatedAt(stage) {
    const stageNo = String(stage || "").padStart(2, "0");
    const stageKey = `stage${stageNo}`;
    const output = (state.scriptStages || {})[stageKey] || {};
    const tracker = (state.stages || {})[stageNo] || {};
    return String(output.updated_at || tracker.updated_at || "");
  }

  function stageResultBelongsToCurrentRun(stage) {
    if (!stageHasCompleted(stage)) return false;
    const startedAt = new Date(state.runningStartedAt || "").getTime();
    if (!Number.isFinite(startedAt)) return true;
    const updatedAt = new Date(stageResultUpdatedAt(stage)).getTime();
    return Number.isFinite(updatedAt) && updatedAt >= startedAt - 2000;
  }

  function mergeStage11(data) {
  const current = (state.scriptStages || {}).stage11 || {};
  const currentBatches =
    current.batches && typeof current.batches === "object" && !Array.isArray(current.batches)
      ? current.batches
      : {};

  const incomingBatches =
    data && data.batches && typeof data.batches === "object" && !Array.isArray(data.batches)
      ? data.batches
      : {};

  const mergedBatches = Object.assign({}, currentBatches);

  Object.entries(incomingBatches).forEach(([key, batch]) => {
    addStage11BatchToMap(mergedBatches, key, batch);
  });

  const topPlan = data.batchCausalConflictPlan || data.batch_causal_conflict_plan;
  const startEpisode =
    data.batchStartEpisode
    || data.batch_start_episode
    || data.startEpisode
    || data.start_episode
    || stage11BatchStartFromPlan(topPlan, "");

  if (startEpisode && hasContent(topPlan)) {
    addStage11BatchToMap(mergedBatches, String(startEpisode), {
      batchStartEpisode: startEpisode,
      batchEndEpisode: data.batchEndEpisode || data.batch_end_episode,
      batchEnrichedEpisodePlan: data.batchEnrichedEpisodePlan || data.batch_enriched_episode_plan,
      batchCausalConflictPlan: topPlan,
      batchCausalConflictReview: data.batchCausalConflictReview || data.batch_causal_conflict_review,
      conflictMemory: data.conflictMemory || data.conflict_memory,
      batchPipelineStatus: data.batchPipelineStatus || data.batch_pipeline_status,
      completedSubStages: data.completedSubStages || data.completed_sub_stages
    });
  }

  state.scriptStages.stage11 = {
    ...current,
    batchStartEpisode: data.batchStartEpisode || data.batch_start_episode || current.batchStartEpisode,
    batchEndEpisode: data.batchEndEpisode || data.batch_end_episode || current.batchEndEpisode,
    batchEnrichedEpisodePlan: data.batchEnrichedEpisodePlan || data.batch_enriched_episode_plan || current.batchEnrichedEpisodePlan,
    batchCausalConflictPlan: topPlan || current.batchCausalConflictPlan,
    batchCausalConflictReview: data.batchCausalConflictReview || data.batch_causal_conflict_review || current.batchCausalConflictReview,
    conflictMemory: data.conflictMemory || data.conflict_memory || current.conflictMemory,
    batchPipelineStatus: data.batchPipelineStatus || data.batch_pipeline_status || current.batchPipelineStatus,
    completedSubStages: data.completedSubStages || data.completed_sub_stages || current.completedSubStages,
    batches: mergedBatches,
    updated_at: new Date().toISOString()
  };

  if (!Array.isArray(state.completedStages)) state.completedStages = [];
  const stage11Complete = stage11Completion().complete;
  state.stages["11"] = {
    status: stage11Complete ? "completed" : "running",
    stage_key: "stage11",
    updated_at: state.scriptStages.stage11.updated_at,
  };
  if (stage11Complete && !state.completedStages.map(String).includes("11")) {
    state.completedStages.push("11");
  }
}

  // FP_STAGE12_MERGE_BATCHES_PATCH_V1
  function mergeStage12(data) {
    const current = (state.scriptStages || {}).stage12 || {};
    const currentBatches = current.batches && typeof current.batches === "object" && !Array.isArray(current.batches)
      ? current.batches
      : {};
    const incomingBatches = data && data.batches && typeof data.batches === "object" && !Array.isArray(data.batches)
      ? data.batches
      : {};

    const mergedBatches = Object.assign({}, currentBatches, incomingBatches);

    const startEpisode = data.batchStartEpisode || data.batch_start_episode || data.startEpisode || data.start_episode;
    const endEpisode = data.batchEndEpisode || data.batch_end_episode || data.endEpisode || data.end_episode;
    const batchScriptText = data.batchScriptText || data.batch_script_text;
    const batchScriptReview = data.batchScriptReview || data.batch_script_review;
    const batchKey = startEpisode ? String(startEpisode) : "";

    if (batchKey && hasContent(batchScriptText)) {
      mergedBatches[batchKey] = Object.assign(
        {},
        currentBatches[batchKey] || {},
        incomingBatches[batchKey] || {},
        {
          batchStartEpisode: startEpisode,
          batchEndEpisode: endEpisode,
          batchEnrichedEpisodePlan: data.batchEnrichedEpisodePlan || data.batch_enriched_episode_plan || (incomingBatches[batchKey] || {}).batchEnrichedEpisodePlan || (currentBatches[batchKey] || {}).batchEnrichedEpisodePlan,
          batchCausalConflictPlan: data.batchCausalConflictPlan || data.batch_causal_conflict_plan || (incomingBatches[batchKey] || {}).batchCausalConflictPlan || (currentBatches[batchKey] || {}).batchCausalConflictPlan,
          batchScriptText: batchScriptText,
          batchScriptReview: batchScriptReview || (incomingBatches[batchKey] || {}).batchScriptReview || (currentBatches[batchKey] || {}).batchScriptReview,
          scriptMemory: data.scriptMemory || data.script_memory || (incomingBatches[batchKey] || {}).scriptMemory || (currentBatches[batchKey] || {}).scriptMemory,
          batchPipelineStatus: data.batchPipelineStatus || data.batch_pipeline_status || (incomingBatches[batchKey] || {}).batchPipelineStatus || (currentBatches[batchKey] || {}).batchPipelineStatus,
          completedSubStages: data.completedSubStages || data.completed_sub_stages || (incomingBatches[batchKey] || {}).completedSubStages || (currentBatches[batchKey] || {}).completedSubStages
        }
      );
    }

    state.scriptStages.stage12 = {
      batchStartEpisode: startEpisode || current.batchStartEpisode,
      batchEndEpisode: endEpisode || current.batchEndEpisode,
      batchEnrichedEpisodePlan: data.batchEnrichedEpisodePlan || data.batch_enriched_episode_plan || current.batchEnrichedEpisodePlan,
      batchCausalConflictPlan: data.batchCausalConflictPlan || data.batch_causal_conflict_plan || current.batchCausalConflictPlan,
      batchScriptText: batchScriptText || current.batchScriptText,
      batchScriptReview: batchScriptReview || current.batchScriptReview,
      scriptMemory: data.scriptMemory || data.script_memory || current.scriptMemory,
      batchPipelineStatus: data.batchPipelineStatus || data.batch_pipeline_status || current.batchPipelineStatus,
      completedSubStages: data.completedSubStages || data.completed_sub_stages || current.completedSubStages,
      batches: mergedBatches,
      updated_at: new Date().toISOString(),
    };

    if (!Array.isArray(state.completedStages)) state.completedStages = [];
    const stage12Complete = stage12Completion().complete;
    state.stages["12"] = {
      status: stage12Complete ? "completed" : "running",
      stage_key: "stage12",
      updated_at: state.scriptStages.stage12.updated_at,
    };
    if (stage12Complete && !state.completedStages.map(String).includes("12")) {
      state.completedStages.push("12");
    }
  }

  const SCRIPT_STAGE_ORDER = ["stage08", "stage09", "stage10", "stage11", "stage12"];
  const SCRIPT_STAGE_OUTPUT_KEYS = {
    stage08: ["framework_scene_dictionary", "sceneDictionary", "scriptWorldRulesDigest"],
    stage09: ["framework_appearanceMapping", "appearanceMapping"],
    stage10: ["framework_enriched_episode_plan", "allEnrichedEpisodePlan", "allEnrichedEpisodePlanText", "batchEnrichedEpisodePlan"],
    stage11: ["framework_causal_conflict_plan", "batchCausalConflictPlan", "conflictMemory"],
    stage12: ["framework_script_text", "batchScriptText", "scriptMemory"],
  };

  function clearStageResults(stageKeys, updatedAt = new Date().toISOString()) {
    if (!state.scriptStages || typeof state.scriptStages !== "object") state.scriptStages = {};
    if (!state.stageOutputs || typeof state.stageOutputs !== "object") state.stageOutputs = {};
    if (!state.stages || typeof state.stages !== "object") state.stages = {};
    const targets = new Set((stageKeys || []).map(String));
    targets.forEach((key) => {
      delete state.scriptStages[key];
      (SCRIPT_STAGE_OUTPUT_KEYS[key] || []).forEach((outputKey) => {
        delete state.stageOutputs[outputKey];
      });
      const stageNo = key.replace("stage", "");
      state.stages[stageNo] = { status: "pending", stage_key: key, updated_at: updatedAt };
    });
    state.completedStages = (state.completedStages || [])
      .map(String)
      .filter((stageNo) => !targets.has(`stage${stageNo.padStart(2, "0")}`));
  }

  function clearDownstreamStages(stage, updatedAt = new Date().toISOString()) {
    const index = SCRIPT_STAGE_ORDER.indexOf(stage);
    if (index < 0) return;
    clearStageResults(SCRIPT_STAGE_ORDER.slice(index + 1), updatedAt);
  }

  function clearStageAndDownstream(stage, updatedAt = new Date().toISOString()) {
    const index = SCRIPT_STAGE_ORDER.indexOf(stage);
    if (index < 0) return;
    clearStageResults(SCRIPT_STAGE_ORDER.slice(index), updatedAt);
  }

  function markScriptStageCompleted(stage, updatedAt = new Date().toISOString()) {
    const stageNo = String(stage || "").replace("stage", "");
    clearDownstreamStages(stage, updatedAt);
    state.stages[stageNo] = { status: "completed", stage_key: stage, updated_at: updatedAt };
    state.completedStages = Array.from(new Set([
      ...(state.completedStages || []).map(String),
      stageNo,
    ])).sort((left, right) => Number(left) - Number(right));
  }

  function synchronizeStageTrackingFromResults() {
    const stage08 = state.scriptStages.stage08 || {};
    const stage09 = state.scriptStages.stage09 || {};
    const stage10 = state.scriptStages.stage10 || {};
    const completeByStage = {
      "08": hasObject(stage08.sceneDictionary),
      "09": hasObject(stage09.appearanceMapping),
      "10": hasContent(stage10Plan(stage10)),
      "11": stage11Completion().complete,
      "12": stage12Completion().complete,
    };
    const completed = [];
    SCRIPT_STAGE_ORDER.forEach((stageKey) => {
      const stageNo = stageKey.replace("stage", "");
      const output = state.scriptStages[stageKey] || {};
      const updatedAt = output.updated_at || new Date().toISOString();
      const isComplete = Boolean(completeByStage[stageNo]);
      if (isComplete) completed.push(stageNo);
      state.stages[stageNo] = {
        status: isComplete ? "completed" : (String(state.runningStage || "") === stageNo ? "running" : "pending"),
        stage_key: stageKey,
        updated_at: updatedAt,
      };
    });
    state.completedStages = completed;
  }

  function reconcileRunningStageResult() {
    if (state.runningStage && stageResultBelongsToCurrentRun(state.runningStage)) {
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
    if (window.fieldLabelsCn && typeof window.fieldLabelsCn.labelFor === "function") {
      return window.fieldLabelsCn.labelFor(key);
    }
    if (FIELD_LABELS[key]) return FIELD_LABELS[key];
    return String(key || "")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replaceAll("_", " ")
      .trim() || "内容";
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
    const outputs = state.stageOutputs || {};
    return value.allEnrichedEpisodePlan
      || value.enrichedEpisodePlan
      || value.batchEnrichedEpisodePlan
      || outputs.allEnrichedEpisodePlan
      || outputs.all_enriched_episode_plan
      || outputs.batchEnrichedEpisodePlan
      || outputs.batch_enriched_episode_plan
      || (outputs.framework_enriched_episode_plan || {}).allEnrichedEpisodePlan
      || (outputs.framework_enriched_episode_plan || {}).enrichedEpisodePlan
      || (outputs.framework_enriched_episode_plan || {}).batchEnrichedEpisodePlan
      || [];
  }

  function stage10Text(stage10) {
    const value = stage10 || {};
    const outputs = state.stageOutputs || {};
    return value.allEnrichedEpisodePlanText
      || value.enrichedEpisodePlanText
      || outputs.allEnrichedEpisodePlanText
      || outputs.all_enriched_episode_plan_text
      || (outputs.framework_enriched_episode_plan || {}).allEnrichedEpisodePlanText
      || (outputs.framework_enriched_episode_plan || {}).enrichedEpisodePlanText
      || "";
  }

  function chineseNumberToInt(text) {
    const map = { 零: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
    const value = String(text || "").trim();
    if (/^\d+$/.test(value)) return Number(value);
    if (value === "十") return 10;
    const tenIndex = value.indexOf("十");
    if (tenIndex >= 0) {
      const left = value.slice(0, tenIndex);
      const right = value.slice(tenIndex + 1);
      return (left ? map[left] || 0 : 1) * 10 + (right ? map[right] || 0 : 0);
    }
    return map[value] || 0;
  }

  function episodeNumberFromValue(value) {
    if (Number.isFinite(Number(value)) && Number(value) > 0) return Number(value);
    const text = String(value || "");
    const match = text.match(/(?:第\s*)?([0-9]+|[一二两三四五六七八九十]{1,4})\s*(?:集|话|episode)?/i);
    return match ? chineseNumberToInt(match[1]) : 0;
  }

  function normalizeEpisodePlanItems(plan) {
    let sourcePlan = plan;
    if (sourcePlan && typeof sourcePlan === "object" && !Array.isArray(sourcePlan)) {
      sourcePlan = sourcePlan.allEnrichedEpisodePlan || sourcePlan.enrichedEpisodePlan || sourcePlan.episodes || sourcePlan.items || [];
    }
    return (Array.isArray(sourcePlan) ? sourcePlan : []).map((item, index) => {
      const source = item && typeof item === "object" ? item : { title: String(item || "") };
      const episode = episodeNumberFromValue(
        source.episode ?? source.episodeNumber ?? source.episode_number ?? source.index ?? source.title ?? index + 1
      );
      return Object.assign({}, source, { episode });
    });
  }

  function inferTotalEpisodes(plan, asset) {
    const fromAsset = Number((asset || {}).episodes_per_season || (asset || {}).total_episodes || 0);
    if (Number.isFinite(fromAsset) && fromAsset > 0) return fromAsset;
    const numbers = normalizeEpisodePlanItems(plan).map((item) => item.episode).filter(Boolean);
    return numbers.length ? Math.max(...numbers) : 0;
  }

  function findDuplicateNumbers(numbers) {
    const seen = new Set();
    const dup = new Set();
    numbers.forEach((number) => {
      if (seen.has(number)) dup.add(number);
      seen.add(number);
    });
    return Array.from(dup).sort((a, b) => a - b);
  }

  function episodeNumbersFromText(text) {
    const numbers = [];
    const pattern = /(?:第\s*)?([0-9]+|[一二两三四五六七八九十]{1,4})\s*集|episode\s*([0-9]+)|Episode\s*([0-9]+)|(?:^|[\n\r])\s*([0-9]+|[一二两三四五六七八九十]{1,4})\s*(?:[.、:：\-\)]|\s+episode\b)/g;
    String(text || "").replace(pattern, (_, cnOrNum, ep1, ep2, lineNumber) => {
      const value = cnOrNum || ep1 || ep2 || lineNumber;
      const number = episodeNumberFromValue(value);
      if (number > 0) numbers.push(number);
      return "";
    });
    return numbers;
  }

  function validateStage10Completeness(plan, text, totalEpisodes) {
    const normalizedPlan = normalizeEpisodePlanItems(plan);
    const numbers = normalizedPlan.map((item) => item.episode).filter((number) => number > 0);
    const expected = Array.from({ length: Math.max(0, Number(totalEpisodes) || 0) }, (_, index) => index + 1);
    const missing = expected.filter((number) => !numbers.includes(number));
    const duplicates = findDuplicateNumbers(numbers);
    const outOfRange = numbers.filter((number) => number < 1 || (totalEpisodes && number > totalEpisodes));
    const textNumbers = episodeNumbersFromText(text);
    const textMissing = expected.filter((number) => !textNumbers.includes(number));
    const textExtra = textNumbers.filter((number) => totalEpisodes && (number < 1 || number > totalEpisodes));
    const textDuplicates = findDuplicateNumbers(textNumbers);
    const textMissingFromPlan = numbers.filter((number) => !textNumbers.includes(number));
    const textNotInPlan = textNumbers.filter((number) => !numbers.includes(number));
    const issues = [];
    if (!normalizedPlan.length) issues.push("缺少 allEnrichedEpisodePlan");
    if (!String(text || "").trim()) issues.push("缺少 allEnrichedEpisodePlanText");
    if (expected.length && numbers[0] !== 1) issues.push("结构化计划未从第 1 集开始");
    if (missing.length) issues.push(`结构化计划缺集：${missing.join("、")}`);
    if (duplicates.length) issues.push(`结构化计划重复：${duplicates.join("、")}`);
    if (outOfRange.length) issues.push(`结构化计划越界：${Array.from(new Set(outOfRange)).join("、")}`);
    if (text && textMissing.length) issues.push(`文本计划少写：${textMissing.join("、")}`);
    if (textExtra.length) issues.push(`文本计划多写/越界：${Array.from(new Set(textExtra)).join("、")}`);
    if (textDuplicates.length) issues.push(`文本计划重复：${textDuplicates.join("、")}`);
    if (text && textMissingFromPlan.length) issues.push(`文本计划缺少结构化集数：${textMissingFromPlan.join("、")}`);
    if (text && textNotInPlan.length) issues.push(`文本计划存在结构化计划外集数：${Array.from(new Set(textNotInPlan)).join("、")}`);
    return {
      ok: issues.length === 0,
      issues,
      missing,
      duplicates,
      outOfRange,
      textMissing,
      textExtra,
      textDuplicates,
      textMissingFromPlan,
      textNotInPlan,
      normalizedPlan,
    };
  }

  function stage10ReadyForStage11(stage10) {
    const plan = stage10Plan(stage10 || {});
    if (!hasContent(plan)) return { ok: false, validation: { ok: false, issues: ["缺少 allEnrichedEpisodePlan"] } };
    const completed = new Set((state.completedStages || []).map((item) => String(item)));
    if (completed.has("10")) {
      return { ok: true, validation: (stage10 || {}).episodeValidation || { ok: true, issues: [] } };
    }
    if ((stage10 || {}).episodeValidation && (stage10 || {}).episodeValidation.ok) {
      return { ok: true, validation: (stage10 || {}).episodeValidation };
    }
    const validation = validateStage10Completeness(
      plan,
      stage10Text(stage10 || {}),
      inferTotalEpisodes(plan, state.importedFrameworkAsset)
    );
    return { ok: validation.ok, validation };
  }

  function textOrEmpty(value) {
    if (Array.isArray(value)) return value.filter(Boolean).join("、");
    if (value && typeof value === "object") {
      return Object.values(value).filter((item) => typeof item === "string" && item.trim()).join("；");
    }
    return String(value || "").trim();
  }

  function textOrNA(value) {
    return textOrEmpty(value) || "暂无";
  }

  function normalizeCausalConflictPlan(raw) {
    let value = raw;
    if (value && typeof value === "object" && value.batchCausalConflictPlan) {
      value = value.batchCausalConflictPlan;
    } else if (value && typeof value === "object" && value.batch_causal_conflict_plan) {
      value = value.batch_causal_conflict_plan;
    }
    if (typeof value === "string") {
      try {
        value = JSON.parse(value);
      } catch (error) {
        return {};
      }
    }
    if (value && typeof value === "object" && value.batchCausalConflictPlan) {
      value = value.batchCausalConflictPlan;
    } else if (value && typeof value === "object" && value.batch_causal_conflict_plan) {
      value = value.batch_causal_conflict_plan;
    }
    return value && typeof value === "object" ? value : {};
  }

  function renderProgression(episode) {
    const parts = [
      episode.why_now,
      episode.opening_action,
      episode.scene_cause_chain,
      episode.episode_state_change,
      episode.next_episode_priority_response,
    ].map(textOrEmpty).filter(Boolean);
    return parts.length ? parts.join("；") : "暂无";
  }

  function renderConflictSummary(planValue) {
    const plan = normalizeCausalConflictPlan(planValue);
    const meta = plan.batch_meta || plan.batchMeta || {};
    const engine = plan.global_conflict_engine || plan.globalConflictEngine || {};
    const episodes = Array.isArray(plan.episodes)
      ? plan.episodes.slice().sort((a, b) => Number(a.episode || a.episodeNumber || a.episode_number || 0) - Number(b.episode || b.episodeNumber || b.episode_number || 0))
      : [];
    const firstEpisode = episodes[0] || {};
    const lastEpisode = episodes[episodes.length - 1] || {};
    const focus = textOrNA(meta.batch_strategy || meta.batchStrategy || engine.five_episode_escalation || engine.fiveEpisodeEscalation);
    const audience = textOrNA(engine.first_concrete_problem || engine.firstConcreteProblem || firstEpisode.audience_must_understand || firstEpisode.audienceMustUnderstand);
    const obstacle = textOrNA(engine.primary_pressure_source || engine.primaryPressureSource || firstEpisode.core_obstacle || firstEpisode.coreObstacle);
    const carry = textOrNA(firstEpisode.carry_in || firstEpisode.carryIn || meta.must_land_immediately || meta.mustLandImmediately);
    const handoff = textOrNA(lastEpisode.next_episode_priority_response || lastEpisode.nextEpisodePriorityResponse || lastEpisode.ending_hook || lastEpisode.endingHook);

    const overall = `
      <div class="wts-readable">
        <p>本五集推进重点：${escapeHtml(focus)}</p>
        <p>观众需要理解：${escapeHtml(audience)}</p>
        <p>主要阻力：${escapeHtml(obstacle)}</p>
        <p>本批承接：${escapeHtml(carry)}</p>
        <p>结尾交给下一批的问题：${escapeHtml(handoff)}</p>
      </div>
    `;
    const episodeHtml = episodes.length
      ? episodes.map((episode, index) => {
        const number = textOrNA(episode.episode || episode.episodeNumber || episode.episode_number || index + 1);
        const title = textOrNA(episode.episode_title || episode.episodeTitle || episode.title);
        return `
          <section class="wts-readable">
            <h4>第${escapeHtml(number)}集：${escapeHtml(title)}</h4>
            <p>人物：${escapeHtml(textOrNA(episode.active_characters || episode.activeCharacters || episode.characters))}</p>
            <p>承接：${escapeHtml(textOrNA(episode.carry_in || episode.carryIn))}</p>
            <p>当前目标：${escapeHtml(textOrNA(episode.current_goal || episode.currentGoal))}</p>
            <p>核心阻力：${escapeHtml(textOrNA(episode.core_obstacle || episode.coreObstacle))}</p>
            <p>观众必须理解：${escapeHtml(textOrNA(episode.audience_must_understand || episode.audienceMustUnderstand))}</p>
            <p>对话策略：${escapeHtml(textOrNA(episode.dialogue_strategy || episode.dialogueStrategy))}</p>
            <p>结尾钩子：${escapeHtml(textOrNA(episode.ending_hook || episode.endingHook))}</p>
            <p>剧情推进：${escapeHtml(renderProgression(episode))}</p>
          </section>
        `;
      }).join("")
      : `<p class="wts-hint">暂无逐集摘要</p>`;
    return `${overall}${episodeHtml}`;
  }

  function stageBatchPendingLabel(stage, batchKey, batch, isComplete) {
    if (isComplete) return "";
    const run = activeRunForStage(stage);
    if (!run || !isRunActive(run)) return "";
    const partial = run.latest_partial_result && typeof run.latest_partial_result === "object" ? run.latest_partial_result : {};
    const keyText = String(batchKey || "").trim();
    const completed = Array.isArray(partial.completed_batch_starts)
      ? partial.completed_batch_starts.map((item) => String(item || "").trim())
      : [];
    if (keyText && completed.includes(keyText)) return "";
    const runningStart = String(
      partial.start_episode
      || partial.batchStartEpisode
      || partial.batch_start_episode
      || partial.selected_batch_start
      || ""
    ).trim();
    const batchStart = String(
      (batch || {}).batchStartEpisode
      || (batch || {}).batch_start_episode
      || keyText
      || ""
    ).trim();
    return runningStart && batchStart && runningStart === batchStart ? "（生成中）" : "";
  }

  function renderStage11Batches(stage11) {
    const batches = stage11BatchMap();
    const keys = numericKeys(batches);
    if (!keys.length && hasContent(stage11.batchCausalConflictPlan)) {
      const pendingLabel = stageBatchPendingLabel("11", stage11.batchStartEpisode || "1", stage11, isStage11BatchComplete(stage11));
      return `
        <details class="wts-output" ${outputContentAttrs(`stage11:${stage11.batchStartEpisode || "single"}:conflict`, stage11PlanFromBatch(stage11) || stage11)}>
          <summary>第 ${escapeHtml(stage11.batchStartEpisode || "")}-${escapeHtml(stage11.batchEndEpisode || "")} 集因果冲突${escapeHtml(pendingLabel)}</summary>
          ${renderConflictSummary(stage11)}
        </details>
      `;
    }
    return keys.map((key) => {
      const batch = batches[key] || {};
      const pendingLabel = stageBatchPendingLabel("11", key, batch, isStage11BatchComplete(batch));
      return `
        <details class="wts-output" ${outputContentAttrs(`stage11:${key}:conflict`, stage11PlanFromBatch(batch) || batch)}>
          <summary>第 ${escapeHtml(batch.batchStartEpisode || key)}-${escapeHtml(batch.batchEndEpisode || "")} 集因果冲突${escapeHtml(pendingLabel)}</summary>
          ${renderConflictSummary(stage11PlanFromBatch(batch) || batch)}
        </details>
      `;
    }).join("");
  }

  function renderStage12Batches(stage12) {
    const batches = stage12BatchMap();
    const keys = numericKeys(batches);
    if (!keys.length && isStage12BatchComplete(stage12)) {
      const pendingLabel = stageBatchPendingLabel("12", stage12.batchStartEpisode || "1", stage12, isStage12BatchComplete(stage12));
      return `
        <details class="wts-output" ${outputContentAttrs(`stage12:${stage12.batchStartEpisode || "single"}:script`, stage12.batchScriptText || stage12.batch_script_text)}>
          <summary>第 ${escapeHtml(stage12.batchStartEpisode || "")}-${escapeHtml(stage12.batchEndEpisode || "")} 集正文${escapeHtml(pendingLabel)}</summary>
          ${renderTree(stage12.batchScriptText || stage12.batch_script_text, "batchScriptText")}
        </details>
      `;
    }
    return keys.map((key) => {
      const batch = batches[key] || {};
      const pendingLabel = stageBatchPendingLabel("12", key, batch, isStage12BatchComplete(batch));
      return `
        <details class="wts-output" ${outputContentAttrs(`stage12:${key}:script`, batch.batchScriptText || batch.batch_script_text)}>
          <summary>第 ${escapeHtml(batch.batchStartEpisode || key)}-${escapeHtml(batch.batchEndEpisode || "")} 集正文${escapeHtml(pendingLabel)}</summary>
          ${renderTree(batch.batchScriptText || batch.batch_script_text || "暂无", "batchScriptText")}
        </details>
      `;
    }).join("");
  }

  function currentAssetReady() {
    return Boolean(hasObject(state.frameworkPlanPackage) || hasObject(state.stageOutputs));
  }

  function isScriptLocked() {
    const asset = state.importedFrameworkAsset || {};
    const workspace = asset.framework_to_script_state && typeof asset.framework_to_script_state === "object"
      ? asset.framework_to_script_state
      : {};
    return Boolean(
      state.scriptLocked
      || asset.framework_to_script_locked
      || asset.script_locked
      || asset.asset_locked
      || workspace.script_locked
      || workspace.scriptLocked
      || workspace.locked
    );
  }

  function scriptLockedAt() {
    const asset = state.importedFrameworkAsset || {};
    const workspace = asset.framework_to_script_state && typeof asset.framework_to_script_state === "object"
      ? asset.framework_to_script_state
      : {};
    return String(
      state.scriptLockedAt
      || asset.script_locked_at
      || asset.locked_at
      || workspace.script_locked_at
      || workspace.scriptLockedAt
      || workspace.locked_at
      || ""
    ).trim();
  }

  function workspaceStatePayload() {
    return {
      framework_asset_id: state.frameworkAssetId || "",
      project_id: state.projectId || state.frameworkAssetId || "",
      stageOutputs: state.stageOutputs || {},
      stages: state.stages || {},
      completedStages: state.completedStages || [],
      scriptStages: state.scriptStages || {},
      preferenceSnapshot: state.preferenceSnapshot || {},
      preferenceSource: state.preferenceSource || "none",
      script_locked: isScriptLocked(),
      scriptLocked: isScriptLocked(),
      script_locked_at: scriptLockedAt(),
      scriptLockedAt: scriptLockedAt(),
      updated_at: new Date().toISOString(),
    };
  }

  function frameworkStageValue(key) {
    const packageValue = state.frameworkPlanPackage || {};
    const outputs = state.stageOutputs || {};
    return outputs[key] || packageValue[key] || {};
  }

  function frameworkRequestBase() {
    const payload = {
      framework_plan_package: state.frameworkPlanPackage || {},
      frameworkPlanPackage: state.frameworkPlanPackage || {},
      source_framework_project_id: state.frameworkAssetId || state.projectId || "",
      preference_snapshot: state.preferenceSnapshot || {},
      preference_source: state.preferenceSource || "none",
    };
    if (state.frameworkAssetId) payload.framework_asset_id = state.frameworkAssetId;
    Object.assign(payload, state.stageOutputs || {});
    return payload;
  }

  async function loadAssets(options = {}) {
    const silent = Boolean(options.silent);
    const openPanel = options.openPanel !== false;
    if (!silent) {
      state.isLoadingAsset = true;
      state.error = null;
      render();
    }
    try {
      const data = await requestJson("/api/framework-assets");
      state.assets = Array.isArray(data.assets) ? data.assets : [];
      state.assetsLastRefreshedAt = new Date().toISOString();
      if (openPanel) state.assetPanelOpen = true;
    } catch (error) {
      if (!silent) state.error = error.message || "框架资产列表加载失败";
      throw error;
    } finally {
      if (!silent) {
        state.isLoadingAsset = false;
        render();
      } else if (state.assetPanelOpen) {
        render();
      }
    }
  }

  async function importAsset(assetId, options = {}) {
    const id = String(assetId || "").trim();
    if (!id) return;
    const quiet = Boolean(options.quiet);
    if (
      state.frameworkAssetId &&
      String(state.frameworkAssetId) !== id &&
      !options.skipConfirm &&
      !window.confirm("切换框架资产会替换当前框架输入，但不会删除历史版本。继续切换吗？")
    ) {
      return;
    }
    if (!quiet) {
      state.isLoadingAsset = true;
      state.error = null;
    }
    if (!quiet) render();
    try {
      const data = await requestJson(`/api/framework-assets/${encodeURIComponent(id)}`);
      const asset = data.asset || {};
      state.frameworkAssetId = asset.asset_id || id;
      syncAssetIdInUrl(state.frameworkAssetId);
      state.projectId = asset.project_id || asset.asset_id || id;
      state.importedFrameworkAsset = asset;
      state.frameworkPlanPackage = asset.framework_plan_package || {};
      const workspaceState = asset.framework_to_script_state || {};
      state.stageOutputs = { ...(asset.stage_outputs || {}), ...(workspaceState.stageOutputs || {}) };
      state.stages = workspaceState.stages || {};
      state.completedStages = Array.isArray(workspaceState.completedStages) ? workspaceState.completedStages : [];
      state.scriptStages =
          asset.scriptStages
          || asset.script_stages
          || workspaceState.scriptStages
          || workspaceState.script_stages
          || {};
      state.scriptLocked = Boolean(asset.framework_to_script_locked || asset.script_locked || asset.asset_locked || workspaceState.script_locked || workspaceState.scriptLocked || workspaceState.locked);
      state.scriptLockedAt = String(asset.script_locked_at || asset.locked_at || workspaceState.script_locked_at || workspaceState.scriptLockedAt || workspaceState.locked_at || "");
      state.lockStatus = state.scriptLocked ? "剧本已锁定保存。" : "";
      state.frameworkSource = state.frameworkSource === "刚刚完成的框架" ? "刚刚完成的框架" : "我的资产 / 框架资产";
      setPreferenceSnapshot(asset.preference_snapshot || {}, "framework_asset_snapshot");
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
      synchronizeStageTrackingFromResults();
      if (!options.preservePanel) state.assetPanelOpen = false;
      reconcileRunningStageResult();
      if (options.skipWorkspaceSave) saveLastAssetId(state.frameworkAssetId);
      else saveWorkspace();
      if (!options.skipRunRefresh) {
        await fetchStageRuns();
        if (state.autoGenerateScript && !(state.activeRun && isRunActive(state.activeRun))) {
          await continueAutoGenerate();
        }
      }
    } catch (error) {
      if (!options.suppressError) state.error = error.message || "框架资产导入失败";
    } finally {
      if (!quiet) {
        state.isLoadingAsset = false;
        render();
      }
    }
  }

  function normalizeImportedFrameworkJson(source) {
    const data = source && typeof source === "object" ? source : {};
    const stageOutputs = data.stageOutputs || data.stage_outputs || {};
    let frameworkPlanPackage =
      data.frameworkPlanPackage ||
      data.framework_plan_package ||
      stageOutputs.framework_plan_package ||
      data.framework_plan ||
      {};
    if (!hasObject(frameworkPlanPackage) && !hasObject(stageOutputs)) {
      throw new Error("导入失败：缺少 frameworkPlanPackage 或 stageOutputs，无法进入框架到剧本阶段。");
    }
    if (!hasObject(frameworkPlanPackage) && hasObject(stageOutputs)) {
      frameworkPlanPackage = {
        source_brief: stageOutputs.source_brief || {},
        worldview_plan: stageOutputs.worldview_plan || {},
        character_plan: stageOutputs.character_plan || {},
        beat_checkpoint_timeline: stageOutputs.beat_checkpoint_timeline || [],
        checkpoint_explanation: stageOutputs.checkpoint_explanation || {},
        character_storylines: stageOutputs.character_storylines || [],
        adaptation_guide: stageOutputs.adaptation_guide || {},
      };
    }
    const basic = data.basic_config || data.basicConfig || {};
    const title = data.project_title || data.source_title || data.title || basic.project_title || basic.source_title || frameworkPlanPackage.project_title || "";
    const episodes = Number(data.episodes_per_season || data.total_episodes || basic.episodes_per_season || basic.total_episodes || frameworkPlanPackage.episodes_per_season || 0);
    if (!String(title || "").trim()) {
      throw new Error("导入失败：无法确定作品标题。");
    }
    if (!episodes) {
      throw new Error("导入失败：无法确定总集数。");
    }
    if (!hasObject(frameworkPlanPackage)) {
      throw new Error("导入失败：无法确定框架核心内容。");
    }
    const allEnrichedEpisodePlan = data.allEnrichedEpisodePlan
      || data.all_enriched_episode_plan
      || stageOutputs.allEnrichedEpisodePlan
      || stageOutputs.all_enriched_episode_plan
      || frameworkPlanPackage.allEnrichedEpisodePlan
      || frameworkPlanPackage.all_enriched_episode_plan
      || frameworkPlanPackage.enrichedEpisodePlan
      || frameworkPlanPackage.enriched_episode_plan
      || [];
    const allEnrichedEpisodePlanText = data.allEnrichedEpisodePlanText
      || data.all_enriched_episode_plan_text
      || stageOutputs.allEnrichedEpisodePlanText
      || stageOutputs.all_enriched_episode_plan_text
      || frameworkPlanPackage.allEnrichedEpisodePlanText
      || frameworkPlanPackage.all_enriched_episode_plan_text
      || frameworkPlanPackage.enrichedEpisodePlanText
      || frameworkPlanPackage.enriched_episode_plan_text
      || "";
    const normalizedEpisodePlan = normalizeEpisodePlanItems(allEnrichedEpisodePlan);
    if (normalizedEpisodePlan.length) {
      const validation = validateStage10Completeness(normalizedEpisodePlan, allEnrichedEpisodePlanText, episodes);
      if (!validation.ok) throw new Error(`导入失败：${validation.issues.join("；")}`);
    }
    return {
      title,
      summary: "来自结构化框架 JSON，可继续运行 08-12。",
      import_source: "structured_json",
      asset_id: "",
      project_id: "",
      source_title: data.source_title || basic.source_title || title,
      target_format: data.target_format || basic.target_format || "",
      episodes_per_season: episodes || "",
      episode_word_count: data.episode_word_count || basic.episode_word_count || "",
      updated_at: data.exported_at || data.updated_at || new Date().toISOString(),
      framework_plan_package: frameworkPlanPackage,
      preference_snapshot: normalizePreferenceSnapshot(data.preference_snapshot || data.preferenceSnapshot || (data.metadata || {}).preference_snapshot || {}),
      stage_outputs: {
        source_brief: stageOutputs.source_brief || data.source_brief || {},
        worldview_plan: stageOutputs.worldview_plan || data.worldview_plan || frameworkPlanPackage.worldview_plan || {},
        character_plan: stageOutputs.character_plan || data.character_plan || frameworkPlanPackage.character_plan || {},
        beat_checkpoint_timeline: stageOutputs.beat_checkpoint_timeline || data.beat_checkpoint_timeline || frameworkPlanPackage.beat_checkpoint_timeline || [],
        checkpoint_explanation: stageOutputs.checkpoint_explanation || data.checkpoint_explanation || frameworkPlanPackage.checkpoint_explanation || {},
        character_storylines: stageOutputs.character_storylines || data.character_storylines || frameworkPlanPackage.character_storylines || [],
        storyline_decisions: stageOutputs.storyline_decisions || data.storyline_decisions || frameworkPlanPackage.storyline_decisions || [],
        adaptation_guide: stageOutputs.adaptation_guide || data.adaptation_guide || frameworkPlanPackage.adaptation_guide || {},
        framework_plan_package: frameworkPlanPackage,
        framework_enriched_episode_plan: normalizedEpisodePlan.length ? {
          allEnrichedEpisodePlan: normalizedEpisodePlan,
          enrichedEpisodePlan: normalizedEpisodePlan,
          batchEnrichedEpisodePlan: normalizedEpisodePlan,
          allEnrichedEpisodePlanText,
          enrichedEpisodePlanText: allEnrichedEpisodePlanText,
        } : (stageOutputs.framework_enriched_episode_plan || {}),
        allEnrichedEpisodePlan: normalizedEpisodePlan,
        allEnrichedEpisodePlanText,
        batchEnrichedEpisodePlan: normalizedEpisodePlan,
      },
      scriptStages: normalizedEpisodePlan.length ? {
        stage10: {
          allEnrichedEpisodePlan: normalizedEpisodePlan,
          enrichedEpisodePlan: normalizedEpisodePlan,
          batchEnrichedEpisodePlan: normalizedEpisodePlan,
          allEnrichedEpisodePlanText,
          episodeValidation: { ok: true, issues: [] },
        },
      } : {},
    };
  }

  function importedStageState(asset) {
    const scriptStages = asset.scriptStages && typeof asset.scriptStages === "object" ? asset.scriptStages : {};
    const stageOutputs = asset.stage_outputs && typeof asset.stage_outputs === "object" ? asset.stage_outputs : {};
    const hasImportedStage10 = hasContent(stage10Plan(scriptStages.stage10 || {})) || hasContent(stage10Text(scriptStages.stage10 || {}));
    const now = new Date().toISOString();
    return {
      scriptStages,
      stageOutputs,
      completedStages: hasImportedStage10 ? ["10"] : [],
      stages: hasImportedStage10
        ? { 10: { status: "completed", stage_key: "stage10", updated_at: now } }
        : {},
      framework_asset_id: "",
      project_id: "",
      updated_at: now,
    };
  }

  function importedFrameworkSavePayload(asset) {
    const totalEpisodes = Number(asset.episodes_per_season || asset.total_episodes || 0);
    const title = String(asset.title || asset.source_title || "本地导入框架").trim();
    const basicConfig = {
      project_title: title,
      source_title: String(asset.source_title || title).trim(),
      source_text: String(asset.summary || ""),
      target_format: String(asset.target_format || "短剧"),
      season_count: 1,
      episodes_per_season: totalEpisodes,
      total_episodes: totalEpisodes,
      episode_word_count: Number(asset.episode_word_count || 0) || "",
      episode_count_guard: {
        season_count: 1,
        episodes_per_season: totalEpisodes,
        total_episodes: totalEpisodes,
      },
    };
    const outputs = asset.stage_outputs && typeof asset.stage_outputs === "object" ? asset.stage_outputs : {};
    const packageValue = asset.framework_plan_package && typeof asset.framework_plan_package === "object" ? asset.framework_plan_package : {};
    return {
      project_title: title,
      title,
      basic_config: basicConfig,
      source_brief: outputs.source_brief || packageValue.source_brief || {},
      worldview_plan: outputs.worldview_plan || packageValue.worldview_plan || {},
      character_plan: outputs.character_plan || packageValue.character_plan || {},
      beat_checkpoint_timeline: outputs.beat_checkpoint_timeline || packageValue.beat_checkpoint_timeline || [],
      checkpoint_explanation: outputs.checkpoint_explanation || packageValue.checkpoint_explanation || {},
      character_storylines: outputs.character_storylines || packageValue.character_storylines || [],
      storyline_decisions: outputs.storyline_decisions || packageValue.storyline_decisions || [],
      adaptation_guide: outputs.adaptation_guide || packageValue.adaptation_guide || {},
      framework_plan_package: packageValue,
      validation_report: outputs.validation_report || packageValue.validation_report || {},
      display_texts: outputs.display_texts || packageValue.display_texts || {},
      preference_snapshot: asset.preference_snapshot || {},
      asset_state: {
        asset_kind: "framework_planner",
        asset_type: "framework",
        status: "completed",
        current_stage: "package",
        updated_at: new Date().toISOString(),
      },
      stage_state: {
        basic: { status: "completed", confirmed: true, locked: true },
        worldview: { status: "completed", confirmed: true, locked: true },
        character: { status: "completed", confirmed: true, locked: true },
        beat: { status: "completed", confirmed: true, locked: true },
        storylines: { status: "completed", confirmed: true, locked: true },
        guide: { status: "completed", confirmed: true, locked: true },
        package: { status: "completed", confirmed: true, locked: false },
      },
      current_view: "package",
      framework_to_script_state: importedStageState(asset),
    };
  }

  async function persistImportedFrameworkAsset(asset) {
    const data = await requestJson("/api/framework-planner/assets/save", {
      method: "POST",
      body: JSON.stringify(importedFrameworkSavePayload(asset)),
    });
    const saved = data.asset || data.project || {};
    const savedId = String(saved.project_id || saved.asset_id || "").trim();
    if (!savedId) {
      throw new Error("导入框架已解析，但保存到资产库失败：缺少资产 ID。");
    }
    return {
      ...asset,
      ...saved,
      title: saved.title || asset.title,
      summary: saved.summary || asset.summary,
      asset_id: String(saved.asset_id || savedId),
      project_id: saved.project_id || Number(savedId) || savedId,
      framework_plan_package: asset.framework_plan_package || saved.framework_plan_package || {},
      stage_outputs: asset.stage_outputs || saved.stage_outputs || {},
      scriptStages: asset.scriptStages || {},
      preference_snapshot: asset.preference_snapshot || saved.preference_snapshot || {},
    };
  }

  async function importStructuredFrameworkFile(file) {
    if (!file) return;
    state.error = null;
    state.isLoadingAsset = true;
    state.importStatus = "正在解析并保存本地框架资产...";
    render();
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const asset = await persistImportedFrameworkAsset(normalizeImportedFrameworkJson(parsed));
      try {
        window.localStorage.removeItem(STORAGE_KEY);
        window.localStorage.removeItem("frameworkToScriptSource");
        window.localStorage.removeItem(RUNNING_STAGE_STORAGE_KEY);
      } catch (error) {}
      state.frameworkAssetId = asset.asset_id || asset.project_id || "";
      syncAssetIdInUrl(state.frameworkAssetId);
      state.projectId = asset.project_id || asset.asset_id || "";
      state.importedFrameworkAsset = asset;
      state.frameworkPlanPackage = asset.framework_plan_package || {};
      state.stageOutputs = asset.stage_outputs || {};
      state.scriptStages = asset.scriptStages || {};
      state.stages = {};
      state.completedStages = [];
      synchronizeStageTrackingFromResults();
      setPreferenceSnapshot(asset.preference_snapshot || {}, "imported_json");
      state.frameworkSource = "导入 JSON";
      state.autoGenerateScript = false;
      state.autoGenerateInFlight = false;
      state.lastRunBatchRefreshKey = "";
      state.lastRunPartialRenderKey = "";
      state.scriptLocked = false;
      state.scriptLockedAt = "";
      state.lockStatus = "";
      state.runningStage = "";
      state.runningStartedAt = "";
      state.isRunning = false;
      state.assetPanelOpen = false;
      state.importStatus = `导入成功并已保存到资产库：${asset.title || "未命名框架"} · ${asset.episodes_per_season || "未知"} 集 · ${asset.episode_word_count || "未知"} 字/集`;
      saveWorkspace();
      await loadAssets({ openPanel: false, silent: true }).catch(() => {});
      announceAssetChange("framework-imported", { framework_asset_id: state.frameworkAssetId });
    } catch (error) {
      state.error = error.message || "导入失败：JSON 格式不正确。";
    } finally {
      state.isLoadingAsset = false;
    }
    render();
  }

  async function runStage08() {
    if (!currentAssetReady()) {
      state.error = "请先导入框架资产，或从框架生成页面一键进入。";
      render();
      return;
    }
    if (hasObject((state.scriptStages.stage08 || {}).sceneDictionary) && !window.confirm("重新运行 08 会覆盖 08 输出，并清空后续 09-12 已生成结果。继续吗？")) return;
    saveRunningStage("08");
    state.error = null;
    render();
    try {
      const data = await requestJson("/api/framework-to-script/stage/08", {
        method: "POST",
        body: JSON.stringify(attachKnowledgePayload({
          ...frameworkRequestBase(),
        }, "08")),
      });
      state.scriptStages.stage08 = {
        sceneDictionary: data.sceneDictionary,
        scriptWorldRulesDigest: data.scriptWorldRulesDigest,
        updated_at: new Date().toISOString(),
      };
      state.stageOutputs = {
        ...(state.stageOutputs || {}),
        ...(data.stageOutputs || {}),
        framework_scene_dictionary: data.framework_scene_dictionary || state.scriptStages.stage08,
        sceneDictionary: data.sceneDictionary,
        scriptWorldRulesDigest: data.scriptWorldRulesDigest,
      };
      markScriptStageCompleted("stage08", state.scriptStages.stage08.updated_at);
      saveWorkspace();
      await loadAssets({ openPanel: false, silent: true }).catch(() => {});
      announceAssetChange("script-stage-updated", { framework_asset_id: state.frameworkAssetId, stage: "08" });
    } catch (error) {
      state.error = error.message || "08 核心场景提炼失败";
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
      state.error = "请先完成 08 核心场景提炼。";
      render();
      return;
    }
    if (hasObject((state.scriptStages.stage09 || {}).appearanceMapping) && !window.confirm("重新运行 09 会覆盖 09 输出，并清空后续 10-12 已生成结果。继续吗？")) return;
    saveRunningStage("09");
    state.error = null;
    render();
    try {
      const data = await requestJson("/api/framework-to-script/stage/09", {
        method: "POST",
        body: JSON.stringify(attachKnowledgePayload({
          ...frameworkRequestBase(),
          sceneDictionary: stage08.sceneDictionary,
        }, "09")),
      });
      const stage09UpdatedAt = new Date().toISOString();
      state.scriptStages.stage09 = {
        ...(state.scriptStages.stage09 || {}),
        appearanceMapping: data.appearanceMapping,
        updated_at: stage09UpdatedAt,
      };
      if (data.fallback_used) {
        synchronizeStageTrackingFromResults();
        state.importStatus = data.warning || "09 本次重跑未形成完整结果，已恢复上一次有效人物映射。";
        saveWorkspace();
        await importAsset(state.frameworkAssetId, {
          quiet: true,
          skipConfirm: true,
          skipRunRefresh: true,
          preservePanel: true,
        }).catch(() => {});
        return;
      }
      state.stageOutputs = {
        ...(state.stageOutputs || {}),
        ...(data.stageOutputs || {}),
        framework_appearanceMapping: data.framework_appearanceMapping || state.scriptStages.stage09,
        appearanceMapping: data.appearanceMapping,
      };
      markScriptStageCompleted("stage09", stage09UpdatedAt);
      saveWorkspace();
      await loadAssets({ openPanel: false, silent: true }).catch(() => {});
      announceAssetChange("script-stage-updated", { framework_asset_id: state.frameworkAssetId, stage: "09" });
    } catch (error) {
      state.error = error.message || "09 角色外观匹配场景失败";
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
      state.error = "请先完成 08 核心场景提炼。";
      render();
      return;
    }

    if (!hasObject(stage09.appearanceMapping)) {
      state.error = "请先完成 09 角色外观匹配场景。";
      render();
      return;
    }
    if (hasContent(stage10Plan(state.scriptStages.stage10 || {})) && !window.confirm("重新运行 10 会覆盖分集细化结果，并清空后续 11-12 已生成结果。继续吗？")) return;

    saveRunningStage("10");
    state.error = null;
    render();

    try {
      let data = null;
      let validation = null;
      let lastIssues = [];
      for (let attempt = 1; attempt <= 2; attempt += 1) {
        data = await requestJson("/api/framework-to-script/stage/10", {
          method: "POST",
          body: JSON.stringify(attachKnowledgePayload({
            ...frameworkRequestBase(),
            sceneDictionary: stage08.sceneDictionary,
            scriptWorldRulesDigest: stage08.scriptWorldRulesDigest,
            appearanceMapping: stage09.appearanceMapping,
            retry_reason: lastIssues.join("；"),
          }, "10")),
        });

        const enrichedEpisodePlan =
          data.enrichedEpisodePlan ||
          data.allEnrichedEpisodePlan ||
          data.batchEnrichedEpisodePlan ||
          (data.framework_enriched_episode_plan || {}).allEnrichedEpisodePlan ||
          (data.framework_enriched_episode_plan || {}).enrichedEpisodePlan ||
          data.enriched_episode_plan ||
          null;

        const enrichedEpisodePlanText =
          data.enrichedEpisodePlanText ||
          data.allEnrichedEpisodePlanText ||
          (data.framework_enriched_episode_plan || {}).allEnrichedEpisodePlanText ||
          (data.framework_enriched_episode_plan || {}).enrichedEpisodePlanText ||
          data.enriched_episode_plan_text ||
          "";
        const totalEpisodes = inferTotalEpisodes(enrichedEpisodePlan, state.importedFrameworkAsset);
        validation = validateStage10Completeness(enrichedEpisodePlan, enrichedEpisodePlanText, totalEpisodes);
        if (validation.ok) break;
        lastIssues = validation.issues;
      }

      const enrichedEpisodePlan =
        data.enrichedEpisodePlan ||
        data.allEnrichedEpisodePlan ||
        data.batchEnrichedEpisodePlan ||
        (data.framework_enriched_episode_plan || {}).allEnrichedEpisodePlan ||
        (data.framework_enriched_episode_plan || {}).enrichedEpisodePlan ||
        data.enriched_episode_plan ||
        null;
      const enrichedEpisodePlanText =
        data.enrichedEpisodePlanText ||
        data.allEnrichedEpisodePlanText ||
        (data.framework_enriched_episode_plan || {}).allEnrichedEpisodePlanText ||
        (data.framework_enriched_episode_plan || {}).enrichedEpisodePlanText ||
        data.enriched_episode_plan_text ||
        "";
      if (!validation || !validation.ok) {
        throw new Error(`10 分集细化校验失败：${(validation && validation.issues || []).join("；")}`);
      }

      state.scriptStages.stage10 = {
        enrichedEpisodePlan: validation.normalizedPlan,
        enrichedEpisodePlanText,
        allEnrichedEpisodePlan: validation.normalizedPlan,
        allEnrichedEpisodePlanText: data.allEnrichedEpisodePlanText || enrichedEpisodePlanText,
        batchEnrichedEpisodePlan: data.batchEnrichedEpisodePlan || validation.normalizedPlan,
        episodeValidation: validation,
        updated_at: new Date().toISOString(),
      };
      state.stageOutputs = {
        ...(state.stageOutputs || {}),
        ...(data.stageOutputs || {}),
        framework_enriched_episode_plan: data.framework_enriched_episode_plan || state.scriptStages.stage10,
        allEnrichedEpisodePlan: validation.normalizedPlan,
        allEnrichedEpisodePlanText: data.allEnrichedEpisodePlanText || enrichedEpisodePlanText,
        batchEnrichedEpisodePlan: data.batchEnrichedEpisodePlan || validation.normalizedPlan,
      };
      markScriptStageCompleted("stage10", state.scriptStages.stage10.updated_at);

      saveWorkspace();
      await loadAssets({ openPanel: false, silent: true }).catch(() => {});
      announceAssetChange("script-stage-updated", { framework_asset_id: state.frameworkAssetId, stage: "10" });
    } catch (error) {
      const failureMessage = error.message || "10 分集细化方案失败";
      await importAsset(state.frameworkAssetId, {
        quiet: true,
        skipConfirm: true,
        skipRunRefresh: true,
        preservePanel: true,
      }).catch(() => {});
      const keptPrevious = hasContent(stage10Plan(state.scriptStages.stage10 || {}));
      state.error = keptPrevious
        ? `${failureMessage} 已保留上一次成功的第 10 阶段结果，可继续运行后续阶段；新的第 10 阶段运行会按批保存断点，中断后可续跑。`
        : failureMessage;
    } finally {
      clearRunningStage("10");
      render();
    }
  }

  async function generateFullScript() {
    if (!currentAssetReady()) {
      state.error = "请先选择框架资产或导入结构化框架 JSON。";
      render();
      return;
    }
    if (isScriptLocked()) {
      state.error = "剧本已锁定保存，不能回退或重新运行 08-12 阶段。";
      setAutoGenerateScript(false);
      render();
      return;
    }
    const rewriteExistingScript = stage12Completion().complete || hasStage12ScriptText();
    if (
      rewriteExistingScript &&
      !window.confirm("当前框架资产已经生成过剧本。一键生成将保留 08-10 框架资产，重新生成 11 因果冲突和 12 正文，相当于重写全剧。继续吗？")
    ) {
      return;
    }
    setAutoGenerateScript(true);
    await continueAutoGenerate({ rewriteExistingScript });
  }

  async function continueAutoGenerate(options = {}) {
    if (state.autoGenerateInFlight) return;
    if (!state.autoGenerateScript) return;
    if (isScriptLocked()) {
      setAutoGenerateScript(false);
      return;
    }
    state.autoGenerateInFlight = true;
    try {
      const rewriteExistingScript = Boolean(options.rewriteExistingScript);
    if (!hasObject((state.scriptStages.stage08 || {}).sceneDictionary)) {
      await runStage08();
      if (state.error) {
        setAutoGenerateScript(false);
        return;
      }
    }
    if (!hasObject((state.scriptStages.stage09 || {}).appearanceMapping)) {
      await runStage09();
      if (state.error) {
        setAutoGenerateScript(false);
        return;
      }
    }
    if (!hasContent(stage10Plan(state.scriptStages.stage10 || {}))) {
      await runStage10();
      if (state.error) {
        setAutoGenerateScript(false);
        return;
      }
    }
    if (rewriteExistingScript) {
      await runStage11({ resetStage11: true, skipConfirm: true });
      if (state.error) {
        setAutoGenerateScript(false);
        return;
      }
      if (state.runningStage === "11" || (state.activeRun && isRunActive(state.activeRun) && String(state.activeRun.stage || "") === "11")) return;
      await runStage12({ resetStage12: true, skipConfirm: true });
      if (state.error) setAutoGenerateScript(false);
      return;
    }
    if (!stage11Completion().complete) {
      await runStage11();
      if (state.error) {
        setAutoGenerateScript(false);
        return;
      }
      if (state.runningStage === "11" || (state.activeRun && isRunActive(state.activeRun) && String(state.activeRun.stage || "") === "11")) return;
    }
    if (!stage12Completion().complete) {
      await runStage12();
      if (state.error) {
        setAutoGenerateScript(false);
        return;
      }
      if (state.runningStage === "12" || (state.activeRun && isRunActive(state.activeRun) && String(state.activeRun.stage || "") === "12")) return;
    }
      if (stage12Completion().complete) {
        setAutoGenerateScript(false);
      }
    } finally {
      state.autoGenerateInFlight = false;
      saveWorkspace();
      render();
    }
  }

  async function runStage11(options = {}) {
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
    const stage10Gate = stage10ReadyForStage11(stage10);
    if (!stage10Gate.ok) {
      const issues = ((stage10Gate.validation || {}).issues || []).join("；");
      state.error = `10 分集细化尚未完成，不能进入 11${issues ? `：${issues}` : "。"}`;
      render();
      return;
    }
    if (!hasObject(stage08.sceneDictionary)) {
      state.error = "请先完成 08 核心场景提炼。";
      render();
      return;
    }
    if (!hasObject(stage09.appearanceMapping)) {
      state.error = "请先完成 09 角色外观匹配场景。";
      render();
      return;
    }
    const resetStage11 = Boolean(options.resetStage11);
    if (resetStage11 && !options.skipConfirm && !window.confirm("重新运行 11 会覆盖开头冲突钩子，并清空 12 正文批次。继续吗？")) return;
    const expectedStarts = expectedBatchStartsFromPlan(allEnrichedEpisodePlan);
    if (resetStage11) {
      clearStageAndDownstream("stage11");
    } else {
      clearStageAndDownstream("stage12");
    }
    saveRunningStage("11");
    state.error = null;
    render();
    let acceptedRun = false;
    try {
      const currentStage11 = state.scriptStages.stage11 || {};
      const data = await requestJson("/api/framework-to-script/stage/11", {
        method: "POST",
        body: JSON.stringify(attachKnowledgePayload({
          ...frameworkRequestBase(),
          allEnrichedEpisodePlan,
          sceneDictionary: stage08.sceneDictionary,
          scriptWorldRulesDigest: stage08.scriptWorldRulesDigest,
          appearanceMapping: stage09.appearanceMapping,
          reset_stage11: resetStage11,
          conflictMemory: resetStage11 ? "" : (currentStage11.conflictMemory || ""),
        }, "11")),
      });
      if (data.run) {
        acceptedRun = true;
        applyRunState(data.run);
        startRunPolling(data.run);
        saveWorkspace();
        render();
        return;
      }
      if (data.batchCausalConflictPlan || data.batches) {
        mergeStage11(data);
        saveWorkspace();
        await refreshAssetAfterRunUpdate();
        const finalMissing = missingBatchStarts(expectedStarts, numericKeys((state.scriptStages.stage11 || {}).batches));
        if (finalMissing.length) {
          throw new Error(`11 未完成全部批次，剩余第 ${finalMissing.join("、")} 集起。`);
        }
        return;
      }
      throw new Error("11 未返回可轮询的运行状态。");
    } catch (error) {
      state.error = error.message || "11 开头冲突钩子失败";
    } finally {
      if (!acceptedRun) {
        clearRunningStage("11");
      }
      render();
    }
  }

  async function runStage12(options = {}) {
    if (!currentAssetReady()) {
      state.error = "请先导入框架资产，或从框架生成页面一键进入。";
      render();
      return;
    }
    const stage11 = state.scriptStages.stage11 || {};
    if (!stage11Completion().complete) {
      await runStage11();
      if (state.error) return;
      if (state.runningStage === "11" || (state.activeRun && isRunActive(state.activeRun) && String(state.activeRun.stage || "") === "11")) return;
    }
    const resetStage12 = Boolean(options.resetStage12);
    if (resetStage12 && !options.skipConfirm && !window.confirm("重新运行 12 会覆盖已生成的正文批次。继续吗？")) return;
    if (resetStage12) {
      clearStageAndDownstream("stage12");
    }
    saveRunningStage("12");
    state.error = null;
    render();

    let acceptedRun = false;

    try {
      let firstRequest = true;
      let guard = 0;
      while (guard < 200) {
        guard += 1;
        const currentStage11 = ensureStage11BatchesOnState();
        const currentStage12 = state.scriptStages.stage12 || {};
        const stage11Keys = numericKeys(stage11BatchMap({ completeOnly: true }));
        const expectedCount = stage11Keys.length || (hasContent(currentStage11.batchCausalConflictPlan) ? 1 : 0);
        const beforeCount = numericKeys(stage12BatchMap({ completeOnly: true })).length;
        const beforeMissing = missingBatchStarts(stage11Keys, numericKeys(stage12BatchMap({ completeOnly: true })));
        if (expectedCount && !beforeMissing.length) break;
        const data = await requestJson("/api/framework-to-script/stage/12", {
          method: "POST",
          body: JSON.stringify(attachKnowledgePayload({
            ...frameworkRequestBase(),
            stage08: state.scriptStages.stage08 || {},
            stage09: state.scriptStages.stage09 || {},
            stage11: currentStage11,
            stage12: currentStage12,
            reset_stage12: resetStage12 && firstRequest,
          }, "12")),
        });

        if (data.run) {
          acceptedRun = true;
          applyRunState(data.run);
          startRunPolling(data.run);
          saveWorkspace();
          render();
          return;
        }

        mergeStage12(data);
        saveWorkspace();
        render();
        const afterCount = numericKeys(stage12BatchMap({ completeOnly: true })).length;
        const afterMissing = missingBatchStarts(stage11Keys, numericKeys(stage12BatchMap({ completeOnly: true })));
        if (afterMissing.length && afterCount <= beforeCount) {
          throw new Error(`12 未能继续生成剩余正文批次：第 ${afterMissing[0]} 集起。`);
        }
        firstRequest = false;
      }
      ensureStage11BatchesOnState();
      await refreshAssetAfterRunUpdate();
      const finalStage11Keys = numericKeys(stage11BatchMap({ completeOnly: true }));
      const finalMissing = missingBatchStarts(finalStage11Keys, numericKeys(stage12BatchMap({ completeOnly: true })));
      if (finalMissing.length) {
        throw new Error(`12 未完成全部正文批次，剩余第 ${finalMissing.join("、")} 集起。`);
      }
      saveWorkspace();
    } catch (error) {
      state.error = error.message || "12 正文及对话失败";
    } finally {
      if (!acceptedRun) {
        if (!options.autoFromStage11) {
          clearRunningStage("12");
        } else {
          state.runningStage = "";
          state.runningStartedAt = "";
        }
      }
      render();
    }
  }

  async function downloadTxt() {
    if (!currentAssetReady()) {
      state.error = "请先导入框架资产。";
      render();
      return;
    }
    if (!hasStage12ScriptText()) {
      state.error = "暂无正文，请先运行第12阶段";
      render();
      return;
    }
    state.error = null;
    render();
    try {
      const response = await fetch(apiUrl(`/api/framework-to-script/export/txt?framework_asset_id=${encodeURIComponent(state.frameworkAssetId)}`), {
        method: "GET",
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.message || "下载失败，请稍后重试。");
      }
      const blob = await response.blob();
      const asset = state.importedFrameworkAsset || {};
      const filename = `${String(asset.title || "framework_script").replace(/[\\/:*?"<>|]+/g, "_")}.txt`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      state.error = error.message || "下载失败，请稍后重试。";
      render();
    }
  }

  async function downloadDocx() {
    if (!currentAssetReady()) {
      state.error = "请先导入框架资产。";
      render();
      return;
    }
    if (!state.frameworkAssetId) {
      state.error = "结构化 JSON 导入的临时框架暂不支持 DOCX 导出，请先保存为框架资产。";
      render();
      return;
    }
    if (!hasStage12ScriptText()) {
      state.error = "暂无正文，请先运行第12阶段";
      render();
      return;
    }
    state.error = null;
    render();
    try {
      const response = await fetch(apiUrl(`/api/framework-to-script/export/docx?framework_asset_id=${encodeURIComponent(state.frameworkAssetId)}`), {
        method: "GET",
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.message || "DOCX 下载失败，请稍后重试。");
      }
      const blob = await response.blob();
      const asset = state.importedFrameworkAsset || {};
      const filename = `${String(asset.title || "framework_script").replace(/[\\/:*?"<>|]+/g, "_")}.docx`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      state.error = error.message || "DOCX 下载失败，请稍后重试。";
      render();
    }
  }

  async function lockAndSaveScript() {
    if (!currentAssetReady() || !state.frameworkAssetId) {
      state.error = "请先导入或保存框架资产后再锁定剧本。";
      render();
      return;
    }
    if (isScriptLocked()) {
      state.error = null;
      state.lockStatus = "剧本已锁定保存。";
      render();
      return;
    }
    if (!stage12Completion().complete) {
      state.error = "剧本阶段尚未完整生成，必须完成 12 阶段全部批次后才能锁定保存。";
      render();
      return;
    }
    if (anyStageRunning()) {
      state.error = "仍有阶段正在运行，请等待完成后再锁定保存。";
      render();
      return;
    }
    if (!window.confirm("锁定并保存后会清理当前剧本阶段调试文件，并禁止回退或重新运行 08-12 阶段。继续吗？")) {
      return;
    }
    state.error = null;
    state.lockStatus = "正在锁定并清理调试文件...";
    render();
    try {
      const data = await requestJson("/api/framework-to-script/lock", {
        method: "POST",
        body: JSON.stringify({
          framework_asset_id: state.frameworkAssetId,
          workspace_state: workspaceStatePayload(),
        }),
      });
      const lockedAt = data.locked_at || new Date().toISOString();
      state.scriptLocked = true;
      state.scriptLockedAt = lockedAt;
      state.lockStatus = "剧本已锁定保存，调试文件已清理。";
      if (data.asset && typeof data.asset === "object") {
        state.importedFrameworkAsset = data.asset;
        state.frameworkPlanPackage = data.asset.framework_plan_package || state.frameworkPlanPackage || {};
        const workspaceState = data.asset.framework_to_script_state || {};
        state.stageOutputs = { ...(data.asset.stage_outputs || {}), ...(workspaceState.stageOutputs || {}) };
        state.stages = workspaceState.stages || state.stages || {};
        state.completedStages = Array.isArray(workspaceState.completedStages) ? workspaceState.completedStages : state.completedStages;
        state.scriptStages = data.asset.scriptStages || workspaceState.scriptStages || state.scriptStages || {};
      }
      state.autoGenerateScript = false;
      stopRunPolling();
      saveWorkspace();
      await loadAssets({ openPanel: false, silent: true }).catch(() => {});
      announceAssetChange("script-locked", { framework_asset_id: state.frameworkAssetId });
    } catch (error) {
      state.error = error.message || "锁定保存失败，请稍后重试。";
      state.lockStatus = "";
    } finally {
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
          <summary><span class="wts-tree-arrow"></span>${escapeHtml(labelFor(keyName))} ${index + 1}</summary>
          <div>${renderTree(item, keyName, depth + 1)}</div>
        </details>
      `).join("")}</div>`;
    }
    if (typeof clean === "object") {
      const entries = Object.entries(clean).filter(([key]) => !RAW_KEYS.has(key) && !(window.fieldLabelsCn && window.fieldLabelsCn.isHiddenKey && window.fieldLabelsCn.isHiddenKey(key)));
      if (!entries.length) return `<div class="wts-empty-inline">暂无内容</div>`;
      return `<div class="wts-tree-list">${entries.map(([key, item]) => {
        const complex = item && typeof item === "object";
        return complex ? `
          <details class="wts-tree-node" ${depth < 1 ? "open" : ""}>
            <summary><span class="wts-tree-arrow"></span>${escapeHtml(labelFor(key))}</summary>
            <div>${renderTree(item, key, depth + 1)}</div>
          </details>
        ` : `
          <div class="wts-tree-leaf">
            <b>${escapeHtml(labelFor(key))}</b>
            ${renderTreeText(item, key)}
          </div>
        `;
      }).join("")}</div>`;
    }
    return `<div class="wts-tree-text">${renderTreeText(clean, keyName)}</div>`;
  }

  function renderTreeText(value, keyName = "text") {
    const text = String(value ?? "");
    if (text.length <= 420) return `<span>${escapeHtml(text)}</span>`;
    const previewLength = keyName === "batchScriptText" ? 260 : 320;
    return `
      <details class="wts-tree-more">
        <summary>
          <span class="wts-tree-preview">${escapeHtml(text.slice(0, previewLength))}...</span>
          <span class="wts-tree-toggle">
            <span class="wts-tree-expand-label">展开全文</span>
            <span class="wts-tree-collapse-label">收起</span>
          </span>
        </summary>
        <div>${escapeHtml(text)}</div>
      </details>
    `;
  }

  function renderAssetPanel() {
    if (!state.assetPanelOpen) return "";
    return `
      <section class="wts-card wts-asset-panel" id="frameworkAssetPanel">
        <div class="wts-card-head">
          <div>
            <h2>导入框架资产</h2>
            <p>当前流程：从框架写剧本。请选择已保存框架资产，或导入结构化框架 JSON。${state.assetsLastRefreshedAt ? `最近刷新：${escapeHtml(formatDate(state.assetsLastRefreshedAt))}` : ""}</p>
          </div>
          <button type="button" class="wts-btn ghost" data-action="close-asset-panel">收起</button>
        </div>
        ${state.isLoadingAsset ? `<div class="wts-loading">正在读取框架资产...</div>` : ""}
        <div class="wts-import-json">
          <label class="wts-btn">
            导入结构化框架 JSON
            <input type="file" accept="application/json,.json" data-import-framework-json hidden />
          </label>
          <span>${escapeHtml(state.importStatus || "支持：本系统导入 / 本地上传json")}</span>
        </div>
        <div class="wts-asset-list">
          ${state.assets.length ? state.assets.map(renderAssetItem).join("") : `<div class="wts-empty">暂无可导入框架资产。请先在框架生成页面完成 01-07 并保存。</div>`}
        </div>
      </section>
    `;
  }

  function renderAssetItem(asset) {
    const canImport = asset.can_import !== false;
    const disabled = canImport ? "" : "disabled";
    const meta = [
      asset.target_format || "未填写类型",
      asset.episodes_per_season ? `${asset.episodes_per_season} 集` : "",
      asset.episode_word_count ? `${asset.episode_word_count} 字/集` : "",
      `更新时间：${formatDate(asset.updated_at || asset.created_at)}`,
      asset.has_script_asset
        ? (asset.script_locked ? "关联剧本：已锁定" : `关联剧本：${asset.script_asset_status_label || "生成中"}`)
        : "关联剧本：未创建",
      asset.script_asset_updated_at ? `剧本更新：${formatDate(asset.script_asset_updated_at)}` : "",
    ].filter(Boolean);
    return `
      <article class="wts-asset-item">
        <div>
          <h3>${escapeHtml(asset.title || "未命名框架资产")}</h3>
          <div class="wts-meta">
            <span>原文：${escapeHtml(asset.source_title || "未填写")}</span>
            ${meta.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
            <span>${canImport ? "可导入" : "不可导入"}</span>
          </div>
          <p>${escapeHtml(asset.summary || asset.import_disabled_reason || "暂无摘要")}</p>
        </div>
        <button type="button" class="wts-btn" data-action="import-asset" data-asset-id="${escapeHtml(asset.asset_id)}" ${disabled}>导入</button>
      </article>
    `;
  }

  function renderImportedSummary() {
    if (!currentAssetReady()) {
      if (state.frameworkAssetId && state.isLoadingAsset) {
        return `
          <section class="wts-card wts-empty-state" aria-live="polite">
            <h2>正在恢复上次打开的框架资产</h2>
            <p>正在从后端同步资产 ${escapeHtml(state.frameworkAssetId)} 和生成进度，无需重新导入。</p>
          </section>
        `;
      }
      return `
        <section class="wts-card wts-empty-state">
          <h2>当前流程：从框架写剧本</h2>
          <p>请先选择已有框架资产，或导入结构化框架 JSON。导入后会从 08 场景字典开始继续生成正文。</p>
        </section>
      `;
    }
    const asset = state.importedFrameworkAsset || {};
    const locked = isScriptLocked();
    const canLock = stage12Completion().complete && !locked && !anyStageRunning() && Boolean(state.frameworkAssetId);
    return `
      <section class="wts-card">
        <div class="wts-card-head">
          <div>
            <span class="wts-label">当前流程：从框架写剧本</span>
            <h2>${escapeHtml(asset.title || "未命名框架资产")}</h2>
            <p>${escapeHtml(asset.summary || "已导入，可以执行 08-12 正文链路。结果会保存在当前浏览器工作区；已保存资产会同步到后端。")}</p>
          </div>
          <div class="wts-version">
            <span>当前框架版本：${escapeHtml(state.frameworkAssetId)}</span>
            <span>框架来源：${escapeHtml(state.frameworkSource || "未选择")}</span>
            <span>${escapeHtml(preferenceStatusText())}</span>
            <span>当前阶段：08-12</span>
            <span>剧本资产：${escapeHtml(asset.script_locked ? "已锁定" : (asset.script_asset_status_label || (asset.has_script_asset ? "生成中" : "未创建")))}</span>
            <span>保存时间：${escapeHtml(formatDate(asset.updated_at || asset.created_at))}</span>
            <button type="button" class="wts-btn ghost" data-action="save-workspace">保存当前版本</button>
            <button type="button" class="wts-btn ${locked ? "ghost" : ""}" data-action="lock-and-save" ${canLock ? "" : "disabled"}>${escapeHtml(locked ? "已锁定保存" : "锁定并保存")}</button>
            ${locked ? `<span>锁定时间：${escapeHtml(formatDate(scriptLockedAt()))}</span>` : ""}
          </div>
        </div>
        ${state.lockStatus ? `<p class="wts-hint">${escapeHtml(state.lockStatus)}</p>` : ""}
      </section>
    `;
  }

  function renderStageCard(id, title, status, buttonText, action, disabled, body, options = {}) {
    const secondary = Boolean(options.secondary);
    const hideAction = Boolean(options.hideAction);
    return `
      <article class="wts-step ${status === "已完成" ? "done" : disabled ? "locked" : ""}">
        <b>${escapeHtml(id)}</b>
        <div>
          <div class="wts-step-head">
            <h3>${escapeHtml(title)}</h3>
            <span>${escapeHtml(status)}</span>
          </div>
          ${hideAction ? "" : `<div class="wts-step-actions">
            <button class="${secondary ? "secondary" : ""}" type="button" data-action="${escapeHtml(action)}" ${disabled ? "disabled" : ""}>${escapeHtml(buttonText)}</button>
          </div>`}
          <p class="wts-hint">输入来源：已导入的框架和已完成内容</p>
          ${body || ""}
        </div>
      </article>
    `;
  }

  function activeRunForStage(stage) {
    const stageText = String(stage || "");
    if (state.activeRun && String(state.activeRun.stage || "") === stageText) return state.activeRun;
    return (state.stageRuns || []).find((run) => run && String(run.stage || "") === stageText && isRunActive(run)) || null;
  }

  function runBatchProgress(run, fallbackProgress) {
    const partial = run && run.latest_partial_result && typeof run.latest_partial_result === "object"
      ? run.latest_partial_result
      : {};
    const completed = Array.isArray(partial.completed_batch_starts)
      ? partial.completed_batch_starts.filter((item) => String(item || "").trim())
      : [];
    const expected = Array.isArray(partial.expected_batch_starts)
      ? partial.expected_batch_starts.filter((item) => String(item || "").trim())
      : [];
    const remaining = Array.isArray(partial.remaining_batch_starts)
      ? partial.remaining_batch_starts.filter((item) => String(item || "").trim())
      : [];
    const fallbackExpected = Array.isArray((fallbackProgress || {}).expected) ? fallbackProgress.expected : [];
    const fallbackDone = Array.isArray((fallbackProgress || {}).done) ? fallbackProgress.done : [];
    // 后台运行状态与资产批次通过两个请求分别刷新，短时间内可能相差一个批次。
    // 取两边的最大值，避免页面已经展示新批次，状态却仍显示旧进度。
    const doneCount = Math.max(completed.length, fallbackDone.length);
    const expectedCount = Math.max(
      expected.length,
      completed.length + remaining.length,
      fallbackExpected.length
    );
    return {
      doneCount,
      expectedCount,
      label: `${doneCount}/${expectedCount || "?"}`,
    };
  }

  function scriptRunStatusText(run) {
    if (!run || typeof run !== "object") return "后台处理中";
    const stage = String(run.stage || "");
    const partial = run.latest_partial_result && typeof run.latest_partial_result === "object" ? run.latest_partial_result : {};
    const start = partial.start_episode || partial.selected_batch_start || "";
    const end = partial.end_episode || "";
    const range = start ? `第 ${start}${end ? `-${end}` : ""} 集` : "";
    const reviewRound = partial.review_round ? `，第 ${partial.review_round} 轮` : "";
    const rewriteRound = partial.rewrite_round ? `，重写第 ${partial.rewrite_round} 轮` : "";
    const subStage = String(partial.sub_stage || run.current_sub_stage || "");
    const stage11Map = {
      stage11_prepare: "准备阶段",
      stage11_batch_auto_retry: "批次自动恢复",
      write: "撰写阶段",
      review: "审核阶段",
      rewrite: "重写阶段",
      memory: "记忆阶段",
      causal_conflict_write: "撰写阶段",
      causal_conflict_review: "审核阶段",
      causal_conflict_rewrite: "重写阶段",
      causal_conflict_memory: "记忆阶段",
      stage11_batch_saved: "批次保存完成",
    };
    const stage12Map = {
      stage12_prepare: "准备阶段",
      stage12_batch_auto_retry: "批次自动恢复",
      write: "撰写阶段",
      review: "审核阶段",
      rewrite: "重写阶段",
      memory: "记忆阶段",
      script_write: "撰写阶段",
      script_review: "审核阶段",
      script_review_format_retry: "审核响应自动恢复",
      script_rewrite: "重写阶段",
      script_memory: "记忆阶段",
      stage12_batch_saved: "批次保存完成",
    };
    const label = stage === "11"
      ? (stage11Map[subStage] || stage11Map[run.current_sub_stage] || "后台处理阶段")
      : (stage12Map[subStage] || stage12Map[run.current_sub_stage] || "后台处理阶段");
    const subject = stage === "11" ? "开头冲突钩子" : "正文及对话";
    if (range) return `正在运行${range}${subject}的${label}${reviewRound}${rewriteRound}`;
    return run.progress_text || `${subject}正在${label}`;
  }

  function brandMotionStatusText() {
    const isRunning = anyStageRunning();
    if (isRunning) {
      return `正在运行 ${state.runningStage || ""} 阶段，刷新页面不会中断。`;
    }
    if (state.error) return "处理已停止，请查看错误信息";
    return currentAssetReady() ? "从框架资产生成可执行剧本" : "导入框架后继续生成剧本";
  }

  function updateActiveRunDom(run) {
    const stage = String((run || {}).stage || "");
    const node = stage ? app.querySelector(`[data-run-status-stage="${stage}"]`) : null;
    if (!node) {
      render();
      return;
    }
    node.outerHTML = renderRunStatus(stage);
    const brandStatus = app.querySelector("[data-brand-motion-status]");
    if (brandStatus) brandStatus.textContent = brandMotionStatusText();
  }

  function renderRunStatus(stage) {
    const run = activeRunForStage(stage);
    if (!run || !isRunActive(run)) {
      if (String(state.runningStage || "") === String(stage || "")) {
        return `
          <div class="wts-run-status" data-run-status-stage="${escapeHtml(stage)}" aria-live="polite">
            <strong>正在连接后台运行状态…</strong>
            <span>生成会在后台继续，恢复状态前无需重复点击。</span>
          </div>
        `;
      }
      return "";
    }
    const fallbackProgress = String(stage || "") === "11" ? stage11Completion() : stage12Completion();
    const progress = runBatchProgress(run, fallbackProgress);
    return `
      <div class="wts-run-status" data-run-status-stage="${escapeHtml(stage)}" aria-live="polite">
        <strong>${escapeHtml(scriptRunStatusText(run))}</strong>
        <span>已完成 ${escapeHtml(progress.doneCount)}/${escapeHtml(progress.expectedCount || "?")} 个批次。</span>
        </div>
    `;
  }

  function renderStages() {
    const scriptLocked = isScriptLocked();
    const locked = !currentAssetReady() || anyStageRunning() || scriptLocked;
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
    const stage11Progress = stage11Completion();
    const stage12Progress = stage12Completion();
    const has11 = hasContent(stage11.batchCausalConflictPlan) || stage11Progress.done.length > 0;
    const has12 = hasStage12ScriptText() || stage12Progress.done.length > 0;
    const has11Complete = stage11Progress.complete;
    const has12Complete = stage12Progress.complete;
    const stage11Run = activeRunForStage("11");
    const stage12Run = activeRunForStage("12");
    const stage11IsRunning = state.runningStage === "11" || isRunActive(stage11Run);
    const stage12IsRunning = state.runningStage === "12" || isRunActive(stage12Run);
    const stage11RunProgress = runBatchProgress(stage11Run, stage11Progress);
    const stage12RunProgress = runBatchProgress(stage12Run, stage12Progress);
    const stage11Status = stage11IsRunning
      ? `运行中 ${stage11RunProgress.label}`
      : has11Complete
        ? "已完成"
        : has11
          ? `部分完成 ${stage11Progress.done.length}/${stage11Progress.expected.length || "?"}`
          : has10Output
            ? "待运行"
            : "等待 10";
    const stage12Status = stage12IsRunning
      ? `运行中 ${stage12RunProgress.label}`
      : has12Complete
        ? "已完成"
        : has12
          ? `部分完成 ${stage12Progress.done.length}/${stage12Progress.expected.length || "?"}`
          : has11Complete
            ? "待运行"
            : "等待 11";
    const stage10Gate = stage10ReadyForStage11(stage10);
    const stage10Validation = stage10Gate.validation || validateStage10Completeness(stage10Plan(stage10), stage10Text(stage10), inferTotalEpisodes(stage10Plan(stage10), state.importedFrameworkAsset));
    const stage10Valid = has10 && stage10Gate.ok;
    const stage11TotalEpisodes = inferTotalEpisodes(stage10Plan(stage10), state.importedFrameworkAsset);
    const nextStage11Start = Number((stage11Progress.missing || [])[0] || 0);
    const completedStage11Ranges = (stage11Progress.done || []).map((key) => {
      const start = Number(key || 0);
      return start > 0 ? `${start}-${Math.min(start + 4, stage11TotalEpisodes || start + 4)}` : "";
    }).filter(Boolean);
    const stage11ProgressHint = has11 && !has11Complete
      ? `<p class="wts-hint">已保存第 ${escapeHtml(completedStage11Ranges.join("、"))} 集；${
          nextStage11Start > 0
            ? stage11IsRunning
              ? `后台正从第 ${escapeHtml(nextStage11Start)} 集起连续生成剩余内容，无需再次点击。`
              : `下一批从第 ${escapeHtml(nextStage11Start)} 集开始。`
            : "仍有批次尚未生成。"
        }</p>`
      : "";
    const stage11ButtonText = stage11IsRunning
      ? `后台生成中（${stage11RunProgress.label}）`
      : has11Complete
      ? "重新运行 11"
      : has11 && nextStage11Start > 0
        ? `继续生成第 ${nextStage11Start}-${stage11TotalEpisodes || "末"} 集`
        : "运行全部 11 开头冲突钩子";
    const nextStage12Start = Number((stage12Progress.missing || [])[0] || 0);
    const completedStage12Ranges = (stage12Progress.done || []).map((key) => {
      const start = Number(key || 0);
      return start > 0 ? `${start}-${Math.min(start + 4, stage11TotalEpisodes || start + 4)}` : "";
    }).filter(Boolean);
    const stage12ProgressHint = has12 && !has12Complete
      ? `<p class="wts-hint">已保存正文第 ${escapeHtml(completedStage12Ranges.join("、"))} 集；${
          nextStage12Start > 0
            ? stage12IsRunning
              ? `后台正从第 ${escapeHtml(nextStage12Start)} 集起连续生成至全文结束，无需再次点击。`
              : `点击一次将从第 ${escapeHtml(nextStage12Start)} 集连续生成至全文结束。`
            : "后台将继续生成剩余正文。"
        } 运行中的临时 JSON 不会提前展示。</p>`
      : "";
    const stage12ButtonText = stage12IsRunning
      ? `后台生成中（${stage12RunProgress.label}）`
      : has12Complete
      ? "重新运行 12"
      : has12 && nextStage12Start > 0
        ? `继续生成第 ${nextStage12Start}-${stage11TotalEpisodes || "末"} 集全文`
        : `一键生成第 1-${stage11TotalEpisodes || "末"} 集全文`;
    const stage12Action = has12Complete ? "rerun-stage-12" : "run-stage-12";
    const fullButtonText = scriptLocked
      ? "已锁定保存"
      : stage11IsRunning || stage12IsRunning
        ? `${state.runningStage || stage11Run?.stage || stage12Run?.stage || ""} 阶段正在后台生成`
        : (has12Complete ? "重写全剧剧本" : (has11 || has12 || state.autoGenerateScript) ? "继续一键生成剧本" : "一键生成剧本");
    return `
      <section class="wts-card" id="scriptStageArea" data-script-stage-area>
        <div class="wts-card-head">
          <div>
            <h2>框架到剧本链路</h2>
            <p>未导入框架前，阶段按钮会保持禁用。08-12 只使用框架资产和上游阶段结果。</p>
          </div>
          <button type="button" class="wts-btn" data-action="generate-full-script" ${locked ? "disabled" : ""}>${escapeHtml(fullButtonText)}</button>
        </div>
               <div class="wts-steps">
          ${renderStageCard(
            "08",
            "核心场景提炼",
            state.runningStage === "08" ? "运行中" : has08 ? "已完成" : "待运行",
            has08 ? "重新运行 08" : "运行 08",
            "run-stage-08",
            locked,
            has08
              ? `<p class="wts-hint">已完成</p>`
              : `<p class="wts-hint">运行完成前不展示输出；结果会自动缓存并供后续阶段使用。</p>`,
            { secondary: has08 }
          )}

          ${renderStageCard(
            "09",
            "角色外观匹配场景",
            state.runningStage === "09" ? "运行中" : has09 ? "已完成" : has08 ? "待运行" : "等待 08",
            has09 ? "重新运行 09" : "运行 09",
            "run-stage-09",
            locked || !has08,
            has09
              ? `<p class="wts-hint">已完成</p>`
              : `<p class="wts-hint">运行完成前不展示输出；结果会自动缓存并供后续阶段使用。</p>`,
            { secondary: has09 }
          )}
          ${renderStageCard(
            "10",
            "分集细化方案",
            state.runningStage === "10" ? "运行中" : has10 ? "已完成" : has09 ? "待运行" : "等待 09",
            has10 ? "重新运行 10" : "运行 10",
            "run-stage-10",
            locked || !has09,
            has10 ? `
              <details class="wts-output" ${outputContentAttrs(
                "stage10:enrichedEpisodePlanText",
                stage10.enrichedEpisodePlanText || stage10.allEnrichedEpisodePlanText
              )}>
                <summary>分集细化文本</summary>
                ${renderTree(
                  stage10.enrichedEpisodePlanText ||
                  stage10.allEnrichedEpisodePlanText ||
                  "已生成结构化分集细化方案，供 11/12 阶段继续使用；本次未返回分集细化文本。",
                  "enrichedEpisodePlanText"
                )}
              </details>
              ${stage10Valid ? `<p class="wts-hint">第 10 阶段已完成，可继续运行 11。</p>` : `<p class="wts-error-inline">集数完整性校验失败：${escapeHtml((stage10Validation.issues || []).join("；"))}</p>`}
            ` : `<p class="wts-hint">将沿用当前导入的框架资产和已完成的 08/09 输出。</p>`,
            { secondary: has10 }
          )}
          ${renderStageCard(
            "11",
            "开头冲突钩子",
            stage11Status,
            stage11ButtonText,
            has11Complete ? "rerun-stage-11" : "run-stage-11",
            locked || !stage10Valid,
            `${renderRunStatus("11")}${stage11ProgressHint}${has11 ? renderStage11Batches(stage11) : ""}`,
            { secondary: has11Complete }
          )}
          ${renderStageCard(
            "12",
            "正文及对话",
            stage12Status,
            stage12ButtonText,
            stage12Action,
            locked || !has11Complete,
            `${renderRunStatus("12")}${stage12ProgressHint}${has12 ? renderStage12Batches(stage12) : ""}`,
            { secondary: has12Complete }
          )}
        </div>
      </section>
    `;
  }

  function renderBrandMotionPanel() {
    const isRunning = anyStageRunning();
    const statusText = brandMotionStatusText();
    return `
      <section class="brand-motion-panel wts-brand-motion ${isRunning ? "is-running" : ""}" data-brand-motion aria-live="polite">
        <img class="brand-motion-image brand-motion-id" src="/static/assets/brand/ID.gif" alt="Idea to Script" />
        <img class="brand-motion-image brand-motion-loading" src="/static/assets/brand/loading.gif" alt="生成中" />
        <div class="brand-motion-text">
          <div class="brand-motion-title">Idea to Script</div>
          <div class="brand-motion-subtitle" data-brand-motion-status>${escapeHtml(statusText)}</div>
        </div>
      </section>
    `;
  }

  function captureViewportScroll() {
    return {
      x: window.scrollX || window.pageXOffset || 0,
      y: window.scrollY || window.pageYOffset || 0,
    };
  }

  function detailRuntimeKey(detail, root = app) {
    if (!detail || !detail.matches || !detail.matches("details")) return "";
    const outputId = String(detail.dataset.outputDetailsId || "").trim();
    if (outputId) return `output:${outputId}`;
    const output = detail.closest("details[data-output-details-id]");
    const owner = output || root;
    const ownerId = output ? String(output.dataset.outputDetailsId || "") : "page";
    const nestedDetails = Array.from(owner.querySelectorAll("details")).filter((item) => item !== owner);
    const index = nestedDetails.indexOf(detail);
    return index >= 0 ? `nested:${ownerId}:${index}` : "";
  }

  function captureInteractionSnapshot(root = app) {
    const detailsOpen = {};
    root.querySelectorAll("details").forEach((detail) => {
      const key = detailRuntimeKey(detail, root);
      if (key) detailsOpen[key] = Boolean(detail.open);
    });

    const viewport = captureViewportScroll();
    const anchorCandidate = document.elementFromPoint(
      Math.max(1, Math.min(window.innerWidth / 2, 520)),
      Math.max(1, Math.min(window.innerHeight / 3, 260))
    );
    const anchorOutput = anchorCandidate && anchorCandidate.closest
      ? anchorCandidate.closest("details[data-output-details-id]")
      : null;
    const active = document.activeElement && root.contains(document.activeElement)
      ? document.activeElement
      : null;
    return {
      viewport,
      detailsOpen,
      anchorOutputId: anchorOutput ? String(anchorOutput.dataset.outputDetailsId || "") : "",
      anchorTop: anchorOutput ? anchorOutput.getBoundingClientRect().top : null,
      activeAction: active && active.dataset ? String(active.dataset.action || "") : "",
      activeAssetId: active && active.dataset ? String(active.dataset.assetId || "") : "",
    };
  }

  function restoreInteractionSnapshot(snapshot, root = app) {
    if (!snapshot || typeof snapshot !== "object") return;
    root.querySelectorAll("details").forEach((detail) => {
      const key = detailRuntimeKey(detail, root);
      if (key && Object.prototype.hasOwnProperty.call(snapshot.detailsOpen || {}, key)) {
        const shouldOpen = Boolean(snapshot.detailsOpen[key]);
        if (detail.open !== shouldOpen) detail.open = shouldOpen;
      } else if (key) {
        const persistedOpen = persistedReadingDetailsOpen(key);
        if (persistedOpen !== null && detail.open !== persistedOpen) detail.open = persistedOpen;
      }
    });

    let restoredByAnchor = false;
    if (snapshot.anchorOutputId) {
      const anchor = Array.from(root.querySelectorAll("details[data-output-details-id]")).find(
        (detail) => String(detail.dataset.outputDetailsId || "") === snapshot.anchorOutputId
      );
      if (anchor && Number.isFinite(Number(snapshot.anchorTop))) {
        const delta = anchor.getBoundingClientRect().top - Number(snapshot.anchorTop);
        if (Math.abs(delta) > 0.5) window.scrollBy(0, delta);
        restoredByAnchor = true;
      }
    }
    if (!restoredByAnchor) {
      window.scrollTo((snapshot.viewport || {}).x || 0, (snapshot.viewport || {}).y || 0);
    }

    if (snapshot.activeAction) {
      const matching = Array.from(root.querySelectorAll("[data-action]")).find((element) => (
        String(element.dataset.action || "") === snapshot.activeAction
        && (!snapshot.activeAssetId || String(element.dataset.assetId || "") === snapshot.activeAssetId)
      ));
      try { matching?.focus({ preventScroll: true }); } catch (_) {}
    }

    window.requestAnimationFrame(() => {
      if (snapshot.anchorOutputId) {
        const anchor = Array.from(root.querySelectorAll("details[data-output-details-id]")).find(
          (detail) => String(detail.dataset.outputDetailsId || "") === snapshot.anchorOutputId
        );
        if (anchor && Number.isFinite(Number(snapshot.anchorTop))) {
          const delta = anchor.getBoundingClientRect().top - Number(snapshot.anchorTop);
          if (Math.abs(delta) > 0.5) window.scrollBy(0, delta);
          return;
        }
      }
      window.scrollTo((snapshot.viewport || {}).x || 0, (snapshot.viewport || {}).y || 0);
    });
  }

  function reuseStableOutputNodes(currentRoot, nextRoot) {
    if (!currentRoot || !nextRoot) return;
    const existingById = new Map();
    currentRoot.querySelectorAll("details[data-output-details-id]").forEach((detail) => {
      existingById.set(String(detail.dataset.outputDetailsId || ""), detail);
    });
    nextRoot.querySelectorAll("details[data-output-details-id]").forEach((nextDetail) => {
      const id = String(nextDetail.dataset.outputDetailsId || "");
      const existing = existingById.get(id);
      if (!existing) return;
      const oldSignature = String(existing.dataset.outputContentSignature || "");
      const nextSignature = String(nextDetail.dataset.outputContentSignature || "");
      if (oldSignature && oldSignature === nextSignature) {
        nextDetail.replaceWith(existing);
      }
    });
  }

  function render() {
    const interactionSnapshot = captureInteractionSnapshot(app);
    const plannerUrl = `${config.frameworkPlannerUrl || "/framework-planner"}${authToken ? `?auth_token=${encodeURIComponent(authToken)}` : ""}`;
    const workspaceUrl = `${config.workspaceUrl || "/workspace"}${authToken ? `?auth_token=${encodeURIComponent(authToken)}` : ""}`;
    const markup = `
      <main class="wts-shell">
        <header class="wts-header">
          <div>
            <div class="wts-eyebrow">08-12 Framework Asset to Script</div>
            <h1>框架转剧本</h1>
            <p>当前流程：从框架写剧本。先选择已保存框架资产，或导入结构化框架 JSON；生成结果保存在当前工作区。</p>
          </div>
          <div class="wts-actions">
            <button type="button" class="wts-btn" data-action="open-asset-panel">导入框架资产</button>
            <button type="button" class="wts-btn ghost" data-action="download-txt">下载 TXT</button>
            <button type="button" class="wts-btn ghost" data-action="download-docx">下载 DOCX</button>
            <a class="wts-btn ghost" href="${escapeHtml(plannerUrl)}">返回框架生成</a>
            <a class="wts-btn ghost" href="${escapeHtml(workspaceUrl)}">返回主工作台</a>
          </div>
        </header>
        ${state.error ? `<section class="wts-error" id="frameworkToScriptError">${escapeHtml(state.error)}</section>` : `<section class="wts-error hidden" id="frameworkToScriptError"></section>`}
        ${renderBrandMotionPanel()}
        ${renderAssetPanel()}
        ${renderImportedSummary()}
        ${renderStages()}
      </main>
    `;
    const template = document.createElement("template");
    template.innerHTML = markup.trim();
    reuseStableOutputNodes(app, template.content);
    app.replaceChildren(template.content);
    restoreInteractionSnapshot(interactionSnapshot, app);
  }

  app.addEventListener("click", (event) => {
    const target = event.target && event.target.closest ? event.target.closest("[data-action]") : null;
    if (!target) return;
    const action = target.dataset.action;
    if (STAGE_RUN_ACTIONS.has(action) && anyStageRunning()) {
      state.error = `当前 ${state.runningStage || ""} 阶段仍在运行，请等待完成后再操作。`;
      render();
      return;
    }
    if (STAGE_RUN_ACTIONS.has(action) && isScriptLocked()) {
      state.error = "剧本已锁定保存，不能回退或重新运行 08-12 阶段。";
      render();
      return;
    }
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
    } else if (action === "rerun-stage-08") {
      runStage08();
    } else if (action === "run-stage-09") {
      runStage09();
    } else if (action === "rerun-stage-09") {
      runStage09();
    } else if (action === "run-stage-10") {
      runStage10();
    } else if (action === "rerun-stage-10") {
      runStage10();
    } else if (action === "generate-full-script") {
      generateFullScript();
    } else if (action === "run-stage-11") {
      runStage11();
    } else if (action === "rerun-stage-11") {
      runStage11({ resetStage11: true });
    } else if (action === "run-stage-12") {
      runStage12();
    } else if (action === "rerun-stage-12") {
      runStage12({ resetStage12: true });
    } else if (action === "download-txt") {
      downloadTxt();
    } else if (action === "download-docx") {
      downloadDocx();
    } else if (action === "save-workspace") {
      saveWorkspace();
      state.error = null;
      render();
    } else if (action === "lock-and-save") {
      lockAndSaveScript();
    } else if (action === "collapse-tree-node") {
      const detail = target.closest("details.wts-tree-node");
      if (detail) detail.open = false;
    }
  });

  app.addEventListener("toggle", (event) => {
    const target = event.target;
    if (!target || !target.matches || !target.matches("details")) return;
    const runtimeKey = detailRuntimeKey(target, app);
    if (runtimeKey) setPersistedReadingDetailsOpen(runtimeKey, target.open);
    if (target.matches("details[data-output-details-id]")) {
      setOutputDetailsOpen(target.dataset.outputDetailsId, target.open);
    }
  }, true);

  app.addEventListener("change", (event) => {
    const target = event.target;
    if (!target || !target.matches || !target.matches("[data-import-framework-json]")) return;
    const file = target.files && target.files[0];
    importStructuredFrameworkFile(file);
    target.value = "";
  });

  restoreRunningStage();
  reconcileRunningStageResult();
  bindAssetRefreshEvents();
  render();

  if (state.frameworkAssetId && (directFromPlanner || state.runningStage || !currentAssetReady())) {
    importAsset(state.frameworkAssetId, { skipConfirm: true });
  } else if (state.frameworkAssetId) {
    fetchStageRuns()
      .then(() => {
        if (state.autoGenerateScript && !(state.activeRun && isRunActive(state.activeRun))) {
          return continueAutoGenerate();
        }
        return null;
      })
      .then(() => render())
      .catch((error) => {
        state.error = error.message || "运行状态恢复失败";
        render();
      });
  } else if (!state.frameworkAssetId && !currentAssetReady()) {
    loadAssets();
  }
})();
