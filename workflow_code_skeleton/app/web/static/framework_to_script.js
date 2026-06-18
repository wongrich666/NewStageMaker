(() => {
  const app = document.getElementById("framework-to-script-app");
  if (!app) return;

  const config = window.FRAMEWORK_TO_SCRIPT_CONFIG || {};
  const params = new URLSearchParams(window.location.search);
  const authToken = params.get("auth_token") || "";
  const urlAssetId = params.get("framework_asset_id") || params.get("asset_id") || "";
  const LEGACY_STORAGE_KEY = "frameworkToScriptWorkspace.v1";
  const STORAGE_KEY = urlAssetId ? `${LEGACY_STORAGE_KEY}.${urlAssetId}` : LEGACY_STORAGE_KEY;
  const RAW_KEYS = new Set(["responseData", "choices", "reasoningText", "historyPreview", "newVariables", "updateVarResult", "raw_stage_responses", "raw_output", "raw", "answerText", "debug", "logs", "cache"]);
  const RESILIENT_STAGE_RETRY_DELAY_MS = 60 * 1000;
  const RESILIENT_STAGE_REQUEST_TIMEOUT_MS = 45 * 60 * 1000;
  const RESILIENT_STAGE_MAX_RETRY_ATTEMPTS = 30;
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
    appearanceMapping: "确定角色外观",
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
    assetPanelOpen: false,
    isLoadingAsset: false,
    isRunning: false,
    runningStage: "",
    runningStartedAt: "",
    runningProgress: null,
    runningProgressTimer: null,
    runningRetryMessage: "",
    runningRetryCountdown: 0,
    lastFailedStage: "",
    error: null,
    importStatus: "",
    frameworkSource: "",
  }, loadWorkspace());

  const directFromPlanner = Boolean(urlAssetId && (params.has("source_framework_project_id") || params.has("project_id")));
  if (urlAssetId && String(urlAssetId) !== String(state.frameworkAssetId || "")) {
    window.localStorage.removeItem(STORAGE_KEY);
    state.frameworkAssetId = urlAssetId;
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
  } else if (!urlAssetId) {
    window.localStorage.removeItem(STORAGE_KEY);
    state.frameworkAssetId = null;
    state.projectId = null;
    state.importedFrameworkAsset = null;
    state.frameworkPlanPackage = null;
    state.stageOutputs = {};
    state.stages = {};
    state.completedStages = [];
    state.scriptStages = {};
    state.preferenceSnapshot = {};
    state.preferenceSource = "none";
    state.assetPanelOpen = true;
    state.frameworkSource = "";
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
      const debugPath = detail.debug_path ? `debug: ${detail.debug_path}` : "";
      const error = new Error(
        [data.message || data.error || "请求失败，请稍后重试。", failedSubStage, detailMessage, debugPath]
          .filter(Boolean)
          .join(" ")
      );
      error.detail = detail;
      error.status = response.status;
      error.payload = data;
      error.failedSubStage = detail.failed_sub_stage || "";
      error.reviewRound = detail.review_round || detail.review_attempt || detail.loop_round || "";
      throw error;
    }
    return stripRaw(data);
  }

  async function requestJsonWithTimeout(path, options, timeoutMs) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), Math.max(1, Number(timeoutMs) || RESILIENT_STAGE_REQUEST_TIMEOUT_MS));
    try {
      return await requestJson(path, Object.assign({}, options || {}, { signal: controller.signal }));
    } catch (error) {
      if (error && error.name === "AbortError") {
        throw new Error("请求长时间无响应，可能是后端中断或网络异常。");
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function requestStageJsonWithRetry(stage, path, buildOptions, maxAttempts = 3) {
    let lastError = null;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      try {
        return await requestJson(path, typeof buildOptions === "function" ? buildOptions(attempt, lastError) : buildOptions);
      } catch (error) {
        lastError = error;
        if (Number(error?.status || 0) === 409) break;
        if (attempt >= maxAttempts) break;
        state.error = `${stage} 阶段请求失败，正在第 ${attempt + 1}/${maxAttempts} 次重试：${formatRetryError(error)}`;
        render();
        await delay(2200);
      }
    }
    throw lastError || new Error(`${stage} 阶段请求失败`);
  }

  function markStageFailure(stage, error, fallback) {
    state.lastFailedStage = String(stage || "");
    state.error = (error && error.message) || fallback || `${stage || "当前"} 阶段失败`;
    saveWorkspace();
    persistRunningStage("", state.lastFailedStage);
  }

  function clearStageFailure(stage) {
    if (!stage || String(state.lastFailedStage || "") === String(stage || "")) {
      state.lastFailedStage = "";
    }
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
      const raw = window.localStorage.getItem(STORAGE_KEY)
        || (STORAGE_KEY !== LEGACY_STORAGE_KEY ? window.localStorage.getItem(LEGACY_STORAGE_KEY) : "");
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
        stages: state.stages,
        completedStages: state.completedStages,
        settings: state.settings,
        scriptStages: state.scriptStages,
        frameworkSource: state.frameworkSource,
        preferenceSnapshot: state.preferenceSnapshot,
        preferenceSource: state.preferenceSource,
        lastFailedStage: state.lastFailedStage,
      })));
    } catch (error) {}
  }

  async function persistRunningStage(stage, failedStage = undefined) {
    if (!state.frameworkAssetId) return;
    try {
      const payload = {
        framework_asset_id: state.frameworkAssetId,
        running_stage: stage ? String(stage) : "",
      };
      if (failedStage !== undefined) {
        payload.last_failed_stage = failedStage ? String(failedStage) : "";
      }
      await requestJson("/api/framework-to-script/running-stage", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    } catch (error) {
      console.warn("persist framework-to-script running stage failed", error);
    }
  }

  async function saveWorkspaceToAsset() {
    saveWorkspace();
    if (!state.frameworkAssetId) {
      throw new Error("当前剧本进度还没有关联框架资产，无法保存到资产。");
    }
    const data = await requestJson("/api/framework-to-script/save-progress", {
      method: "POST",
      body: JSON.stringify(stripRaw({
        framework_asset_id: state.frameworkAssetId,
        scriptStages: state.scriptStages,
        stageOutputs: state.stageOutputs,
        completedStages: state.completedStages,
        stages: state.stages,
        settings: state.settings,
        runningStage: state.runningStage,
        lastFailedStage: state.lastFailedStage,
      })),
    });
    if (data.framework_asset) {
      state.importedFrameworkAsset = data.framework_asset;
      state.frameworkPlanPackage = data.framework_asset.framework_plan_package || state.frameworkPlanPackage;
      state.frameworkAssetId = data.framework_asset.asset_id || state.frameworkAssetId;
    }
    const savedState = data.framework_to_script_state || {};
    if (savedState && typeof savedState === "object") {
      state.scriptStages = savedState.scriptStages || state.scriptStages;
      state.stageOutputs = savedState.stageOutputs || state.stageOutputs;
      state.completedStages = Array.isArray(savedState.completedStages) ? savedState.completedStages : state.completedStages;
      state.stages = savedState.stages || state.stages;
      state.settings = savedState.settings || state.settings;
    }
    saveWorkspace();
    return data;
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
    saveWorkspace();
  }

  function detailsStateStorageKey(id) {
    return [state.frameworkAssetId || "no-asset", id].join(":");
  }

  function isPersistentDetailsOpen(id, defaultOpen) {
    if (!id) return Boolean(defaultOpen);
    const map = (state.settings && state.settings.persistedDetailsOpen) || {};
    const key = detailsStateStorageKey(id);
    if (Object.prototype.hasOwnProperty.call(map, key)) return Boolean(map[key]);
    return Boolean(defaultOpen);
  }

  function persistentDetailsAttrs(id, defaultOpen) {
    const safeId = String(id || "").trim();
    if (!safeId) return defaultOpen ? " open" : "";
    return `data-persist-details-id="${escapeHtml(safeId)}"${isPersistentDetailsOpen(safeId, defaultOpen) ? " open" : ""}`;
  }

  function setPersistentDetailsOpen(id, isOpen) {
    const safeId = String(id || "").trim();
    if (!safeId) return;
    if (!state.settings || typeof state.settings !== "object") {
      state.settings = {};
    }
    const map = state.settings.persistedDetailsOpen && typeof state.settings.persistedDetailsOpen === "object"
      ? state.settings.persistedDetailsOpen
      : {};
    map[detailsStateStorageKey(safeId)] = Boolean(isOpen);
    state.settings.persistedDetailsOpen = map;
    saveWorkspace();
  }

  const RUNNING_STAGE_STORAGE_PREFIX = "frameworkToScriptRunningStage.v1";
  const RUNNING_STAGE_TIMEOUT_MS = 12 * 60 * 60 * 1000;

  function runningStageStorageKey(assetId = state.frameworkAssetId) {
    const scopedId = String(assetId || urlAssetId || "temporary").trim() || "temporary";
    return `${RUNNING_STAGE_STORAGE_PREFIX}.${scopedId}`;
  }

  function saveRunningStage(stage) {
    const payload = {
      runningStage: String(stage || ""),
      startedAt: new Date().toISOString(),
      frameworkAssetId: state.frameworkAssetId || "",
    };

    state.runningStage = payload.runningStage;
    state.runningStartedAt = payload.startedAt;
    state.isRunning = Boolean(payload.runningStage);
    persistRunningStage(stage);

    try {
      window.localStorage.setItem(runningStageStorageKey(payload.frameworkAssetId), JSON.stringify(payload));
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
    persistRunningStage("", state.lastFailedStage || "");

    try {
      window.localStorage.removeItem(runningStageStorageKey());
    } catch (error) {
      console.warn("clear running stage failed", error);
    }
  }

  function scheduleInterruptedStageResume(stage, attempt = 0) {
    const stageValue = String(stage || "");
    if (!["11", "12"].includes(stageValue)) return;
    window.setTimeout(() => {
      if (stageHasCompleted(stageValue)) {
        state.error = null;
        render();
        return;
      }
      if (!currentAssetReady()) {
        if (attempt < 20) {
          scheduleInterruptedStageResume(stageValue, attempt + 1);
        } else {
          state.error = `检测到 ${stageValue} 阶段中断，但框架资产尚未就绪。请重新导入框架资产后继续。`;
          render();
        }
        return;
      }
      state.error = null;
      if (stageValue === "11") {
        runStage11({ skipConfirm: true });
      } else {
        runStage12({ skipConfirm: true });
      }
    }, attempt ? 3000 : 1000);
  }

  function restoreRunningStage() {
    try {
      const key = runningStageStorageKey();
      const legacyKey = RUNNING_STAGE_STORAGE_PREFIX;
      const raw = window.localStorage.getItem(key)
        || (key !== legacyKey ? window.localStorage.getItem(legacyKey) : "");
      if (!raw) return;

      const payload = JSON.parse(raw);
      if (!payload || !payload.runningStage || !payload.startedAt) {
        window.localStorage.removeItem(key);
        window.localStorage.removeItem(legacyKey);
        return;
      }

      const startedAt = new Date(payload.startedAt).getTime();
      if (!Number.isFinite(startedAt) || Date.now() - startedAt > RUNNING_STAGE_TIMEOUT_MS) {
        window.localStorage.removeItem(key);
        window.localStorage.removeItem(legacyKey);
        return;
      }

      if (
        payload.frameworkAssetId &&
        state.frameworkAssetId &&
        String(payload.frameworkAssetId) !== String(state.frameworkAssetId)
      ) {
        return;
      }

      window.localStorage.removeItem(key);
      window.localStorage.removeItem(legacyKey);
      state.runningStage = "";
      state.runningStartedAt = "";
      state.isRunning = false;
      if (["11", "12"].includes(String(payload.runningStage))) {
        state.error = `检测到上次 ${payload.runningStage} 阶段可能中断，正在自动从已完成批次断点续跑。`;
        scheduleInterruptedStageResume(payload.runningStage);
      } else {
        state.error = `已清除上次遗留的 ${payload.runningStage} 阶段运行锁，可重新点击运行。`;
      }
    } catch (error) {
      console.warn("restore running stage failed", error);
      try {
        window.localStorage.removeItem(runningStageStorageKey());
        window.localStorage.removeItem(RUNNING_STAGE_STORAGE_PREFIX);
      } catch (_) {}
    }
  }

  function hasStage12ScriptText() {
    const stage12 = (state.scriptStages || {}).stage12 || {};
    const batches = stage12.batches || {};
    if (Object.keys(batches).some((key) => hasContent((batches[key] || {}).batchScriptText || (batches[key] || {}).batch_script_text))) {
      return true;
    }
    return hasContent(stage12.batchScriptText || stage12.batch_script_text);
  }

  function numericKeys(value) {
    return Object.keys(value || {})
      .filter((key) => /^\d+$/.test(String(key)))
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

  function stage11Completion() {
    const expected = expectedStage11Starts();
    const done = numericKeys(((state.scriptStages || {}).stage11 || {}).batches);
    return { expected, done, complete: Boolean(expected.length && done.length >= expected.length) };
  }

  function stage12Completion() {
    const stage11 = ((state.scriptStages || {}).stage11 || {});
    const expected = numericKeys(stage11.batches);
    const done = numericKeys(((state.scriptStages || {}).stage12 || {}).batches);
    return { expected, done, complete: Boolean(expected.length && done.length >= expected.length) };
  }

  function missingBatchStarts(expected, done) {
    const completed = new Set((done || []).map((key) => String(key)));
    return (expected || []).filter((key) => !completed.has(String(key)));
  }

  function batchRangeForStart(startEpisode) {
    const start = Number(startEpisode) || 0;
    if (!start) return "";
    const plan = stage10Plan((state.scriptStages || {}).stage10 || {});
    const total = inferTotalEpisodes(plan, state.importedFrameworkAsset);
    const end = total ? Math.min(total, start + 4) : start + 4;
    return `${start}-${end}集`;
  }

  function runningProgressText(stage) {
    const progress = state.runningProgress || {};
    if (String(progress.stage || "") !== String(stage || "")) return "";
    if (state.runningRetryMessage) return state.runningRetryMessage;
    const range = progress.range || batchRangeForStart(progress.startEpisode);
    const subStage = progress.backendSubStage ? backendSubStageLabel(stage, progress.backendSubStage) : "";
    const round = progress.backendReviewRound ? `第${progress.backendReviewRound}轮` : "";
    if (subStage) return `${range || "当前批次"}后端${round}${subStage}中...`;
    return `${range || "当前批次"}请求中，等待后端返回实际处理阶段...`;
  }

  function stopRunningProgress() {
    if (state.runningProgressTimer) {
      window.clearInterval(state.runningProgressTimer);
    }
    state.runningProgressTimer = null;
    state.runningProgress = null;
    state.runningRetryMessage = "";
    state.runningRetryCountdown = 0;
  }

  function startRunningProgress(stage, startEpisode, metadata = {}) {
    if (state.runningProgressTimer) {
      window.clearInterval(state.runningProgressTimer);
    }
    state.runningProgress = {
      stage: String(stage || ""),
      startEpisode: Number(startEpisode) || 0,
      range: batchRangeForStart(startEpisode),
      backendSubStage: metadata.backendSubStage || "",
      backendReviewRound: metadata.backendReviewRound || "",
      requestAttempt: metadata.requestAttempt || 1,
    };
    state.runningProgressTimer = window.setInterval(() => {
      const progress = state.runningProgress;
      if (!progress || String(progress.stage || "") !== String(stage || "")) return;
      render();
    }, 1800);
  }

  function resilientStageLabel(stage) {
    return String(stage || "") === "12" ? "12 正文及对话" : "11 开头冲突钩子";
  }

  function formatRetryError(error) {
    return String((error && error.message) || error || "请求失败").replace(/\s+/g, " ").trim();
  }

  function backendSubStageLabel(stage, subStage) {
    const key = String(subStage || "");
    const common = {
      memory: "保存记忆",
    };
    const stage11 = {
      causal_conflict_write: "撰写开头冲突钩子",
      causal_conflict_review: "审核开头冲突钩子",
      causal_conflict_rewrite: "修改开头冲突钩子",
      causal_conflict_memory: "保存记忆",
    };
    const stage12 = {
      script_write: "撰写正文",
      script_review: "审核正文",
      script_rewrite: "修改正文",
      script_memory: "保存记忆",
    };
    return (String(stage || "") === "12" ? stage12[key] : stage11[key]) || common[key] || key;
  }

  function backendStageTextFromError(stage, error) {
    const subStage = error && error.failedSubStage;
    if (!subStage) return "";
    const round = error && error.reviewRound ? `第${error.reviewRound}轮` : "";
    return `${round}${backendSubStageLabel(stage, subStage)}`;
  }

  function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, Math.max(0, Number(ms) || 0)));
  }

  async function waitBeforeStageRetry(stage, startEpisode, attempt, error) {
    const range = batchRangeForStart(startEpisode) || "当前批次";
    const reason = formatRetryError(error);
    const backendStageText = backendStageTextFromError(stage, error);
    const backendPrefix = backendStageText ? `后端${backendStageText}异常` : "后端请求异常";
    const totalSeconds = Math.max(1, Math.ceil(RESILIENT_STAGE_RETRY_DELAY_MS / 1000));
    state.runningRetryCountdown = totalSeconds;
    for (let seconds = totalSeconds; seconds > 0; seconds -= 1) {
      state.runningRetryCountdown = seconds;
      state.runningRetryMessage = `${range}${backendPrefix}，第${attempt}次自动重试准备中，${seconds}秒后继续...（${reason}）`;
      render();
      await delay(1000);
    }
    state.runningRetryCountdown = 0;
    state.runningRetryMessage = "";
    startRunningProgress(stage, startEpisode, {
      backendSubStage: error && error.failedSubStage,
      backendReviewRound: error && error.reviewRound,
      requestAttempt: attempt,
    });
    render();
  }

  async function runResilientStageBatch(stage, startEpisode, operation) {
    let attempt = 1;
    while (attempt <= RESILIENT_STAGE_MAX_RETRY_ATTEMPTS) {
      try {
        startRunningProgress(stage, startEpisode, { requestAttempt: attempt });
        render();
        return await operation(attempt);
      } catch (error) {
        if (attempt >= RESILIENT_STAGE_MAX_RETRY_ATTEMPTS) {
          throw new Error(`${resilientStageLabel(stage)}自动重试 ${attempt} 次后仍未完成：${formatRetryError(error)}。已保留已完成批次，可重新点击继续。`);
        }
        await waitBeforeStageRetry(stage, startEpisode, attempt + 1, error);
        attempt += 1;
      }
    }
    throw new Error(`${resilientStageLabel(stage)}自动重试未完成。`);
  }

  function renderRunningProgress(stage) {
    const text = runningProgressText(stage);
    if (!text) return "";
    return `
      <div class="wts-running-detail" role="status" aria-live="polite">
        <span class="wts-running-dot" aria-hidden="true"></span>
        <span>${escapeHtml(text)}</span>
      </div>
    `;
  }

  function renderErrorPanel() {
    if (!state.error) return `<section class="wts-error hidden" id="frameworkToScriptError"></section>`;
    const failedStage = String(state.lastFailedStage || "").trim();
    const canRetry = failedStage && currentAssetReady() && !state.runningStage && !state.isRunning;
    return `
      <section class="wts-error" id="frameworkToScriptError">
        <div class="wts-error-text">${escapeHtml(state.error)}</div>
        ${canRetry ? `
          <div class="wts-error-actions">
            <button type="button" class="wts-btn ghost" data-action="retry-failed-stage">重试 ${escapeHtml(failedStage)} 阶段</button>
            <button type="button" class="wts-btn" data-action="continue-from-failure">从断点继续</button>
          </div>
        ` : ""}
      </section>
    `;
  }

  function retryStage(stage, options = {}) {
    const key = String(stage || state.lastFailedStage || "").padStart(2, "0");
    if (key === "08") return runStage08();
    if (key === "09") return runStage09();
    if (key === "10") return runStage10();
    if (key === "11") return runStage11(options.reset ? { resetStage11: true } : {});
    if (key === "12") return runStage12(options.reset ? { resetStage12: true } : {});
    return generateFullScript();
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

  function mergeStage11(data) {
    const current = (state.scriptStages || {}).stage11 || {};
    const currentBatches = current.batches && typeof current.batches === "object" && !Array.isArray(current.batches)
      ? current.batches
      : {};
    const incomingBatches = data && data.batches && typeof data.batches === "object" && !Array.isArray(data.batches)
      ? data.batches
      : {};
    const mergedBatches = Object.assign({}, currentBatches, incomingBatches);
    const startEpisode = data.batchStartEpisode || data.batch_start_episode || data.startEpisode || data.start_episode;
    const endEpisode = data.batchEndEpisode || data.batch_end_episode || data.endEpisode || data.end_episode;
    const conflictPlan = data.batchCausalConflictPlan || data.batch_causal_conflict_plan;
    const conflictReview = data.batchCausalConflictReview || data.batch_causal_conflict_review;
    const conflictMemory = data.conflictMemory || data.conflict_memory;
    const batchKey = startEpisode ? String(startEpisode) : "";

    if (batchKey && hasContent(conflictPlan)) {
      mergedBatches[batchKey] = Object.assign(
        {},
        currentBatches[batchKey] || {},
        incomingBatches[batchKey] || {},
        {
          batchStartEpisode: startEpisode,
          batchEndEpisode: endEpisode,
          batchEnrichedEpisodePlan: data.batchEnrichedEpisodePlan || data.batch_enriched_episode_plan || (incomingBatches[batchKey] || {}).batchEnrichedEpisodePlan || (currentBatches[batchKey] || {}).batchEnrichedEpisodePlan,
          batchCausalConflictPlan: conflictPlan,
          batch_causal_conflict_plan: conflictPlan,
          batchCausalConflictReview: conflictReview || (incomingBatches[batchKey] || {}).batchCausalConflictReview || (currentBatches[batchKey] || {}).batchCausalConflictReview,
          conflictMemory: conflictMemory || (incomingBatches[batchKey] || {}).conflictMemory || (currentBatches[batchKey] || {}).conflictMemory
        }
      );
    }

    state.scriptStages.stage11 = {
      batchStartEpisode: startEpisode || current.batchStartEpisode,
      batchEndEpisode: endEpisode || current.batchEndEpisode,
      batchEnrichedEpisodePlan: data.batchEnrichedEpisodePlan || data.batch_enriched_episode_plan || current.batchEnrichedEpisodePlan,
      batchCausalConflictPlan: conflictPlan || current.batchCausalConflictPlan,
      batchCausalConflictReview: conflictReview || current.batchCausalConflictReview,
      conflictMemory: conflictMemory || current.conflictMemory,
      batches: mergedBatches,
      updated_at: new Date().toISOString(),
    };
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
          scriptMemory: data.scriptMemory || data.script_memory || (incomingBatches[batchKey] || {}).scriptMemory || (currentBatches[batchKey] || {}).scriptMemory
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
      batches: mergedBatches,
      updated_at: new Date().toISOString(),
    };
  }

  function clearDownstreamStages(stage) {
    const order = ["stage08", "stage09", "stage10", "stage11", "stage12"];
    const index = order.indexOf(stage);
    if (index < 0) return;
    order.slice(index + 1).forEach((key) => {
      delete state.scriptStages[key];
    });
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
    if (window.fieldLabelsCn && typeof window.fieldLabelsCn.labelFor === "function") {
      return window.fieldLabelsCn.labelFor(key);
    }
    if (FIELD_LABELS[key]) return FIELD_LABELS[key];
    return String(key || "")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replaceAll("_", " ")
      .trim() || "内容";
  }

  function truncate(text, maxLength) {
    const value = String(text || "").trim();
    const limit = Math.max(1, Number(maxLength) || 120);
    return value.length > limit ? `${value.slice(0, limit)}...` : value;
  }

  function readableValue(value) {
    if (window.fieldLabelsCn && typeof window.fieldLabelsCn.readableText === "function") {
      return window.fieldLabelsCn.readableText(value);
    }
    if (Array.isArray(value)) {
      return value.map((item, index) => `${index + 1}. ${readableValue(item)}`).join("\n");
    }
    if (value && typeof value === "object") {
      return Object.keys(value)
        .filter((key) => !RAW_KEYS.has(key) && hasContent(value[key]))
        .map((key) => `${labelFor(key)}：${readableValue(value[key])}`)
        .join("\n");
    }
    return String(value ?? "");
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

  function exportScriptFilename(extension) {
    const asset = state.importedFrameworkAsset || {};
    const title = String(asset.title || asset.source_title || state.frameworkPlanPackage?.title || state.frameworkPlanPackage?.project_title || "完整剧本")
      .replace(/[\\/:*?"<>|]+/g, "_")
      .slice(0, 80) || "完整剧本";
    const totalEpisodes = inferTotalEpisodes(stage10Plan((state.scriptStages || {}).stage10 || {}), asset)
      || Number(asset.episodes_per_season || asset.total_episodes || 0)
      || "";
    const episodeText = totalEpisodes ? `${totalEpisodes}集` : "";
    return `${title}${episodeText}完整剧本.${extension}`;
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

  function renderStage11Batches(stage11) {
    const batches = stage11.batches || {};
    const keys = numericKeys(batches);
    if (!keys.length && hasContent(stage11.batchCausalConflictPlan)) {
      return `
        <details class="wts-output" ${outputDetailsAttrs(`stage11:${stage11.batchStartEpisode || "single"}:conflict`)}>
          <summary>第 ${escapeHtml(stage11.batchStartEpisode || "")}-${escapeHtml(stage11.batchEndEpisode || "")} 集因果冲突</summary>
          ${renderConflictSummary(stage11)}
        </details>
      `;
    }
    return keys.map((key) => {
      const batch = batches[key] || {};
      return `
        <details class="wts-output" ${outputDetailsAttrs(`stage11:${key}:conflict`)}>
          <summary>第 ${escapeHtml(batch.batchStartEpisode || key)}-${escapeHtml(batch.batchEndEpisode || "")} 集因果冲突</summary>
          ${renderConflictSummary(batch.batchCausalConflictPlan || batch.batch_causal_conflict_plan)}
        </details>
      `;
    }).join("");
  }

  function renderStage12Batches(stage12) {
    const batches = stage12.batches || {};
    const keys = numericKeys(batches);
    if (!keys.length && hasContent(stage12.batchScriptText || stage12.batch_script_text)) {
      return `
        <details class="wts-output" ${outputDetailsAttrs(`stage12:${stage12.batchStartEpisode || "single"}:script`)}>
          <summary>第 ${escapeHtml(stage12.batchStartEpisode || "")}-${escapeHtml(stage12.batchEndEpisode || "")} 集正文</summary>
          ${renderTree(stage12.batchScriptText || stage12.batch_script_text, "batchScriptText", 0, `stage12:${stage12.batchStartEpisode || "single"}:script`)}
        </details>
      `;
    }
    return keys.map((key) => {
      const batch = batches[key] || {};
      return `
        <details class="wts-output" ${outputDetailsAttrs(`stage12:${key}:script`)}>
          <summary>第 ${escapeHtml(batch.batchStartEpisode || key)}-${escapeHtml(batch.batchEndEpisode || "")} 集正文</summary>
          ${renderTree(batch.batchScriptText || batch.batch_script_text || "暂无", "batchScriptText", 0, `stage12:${key}:script`)}
        </details>
      `;
    }).join("");
  }

  function currentAssetReady() {
    return Boolean(hasObject(state.frameworkPlanPackage) || hasObject(state.stageOutputs));
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
      const workspaceState = asset.framework_to_script_state || {};
      state.stageOutputs = { ...(asset.stage_outputs || {}), ...(workspaceState.stageOutputs || {}) };
      state.stages = workspaceState.stages || {};
      state.completedStages = Array.isArray(workspaceState.completedStages) ? workspaceState.completedStages : [];
      state.scriptStages = asset.scriptStages || workspaceState.scriptStages || {};
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

  function normalizeImportedFrameworkJson(source) {
    const data = source && typeof source === "object" ? source : {};
    const workspaceState = data.framework_to_script_state || data.frameworkToScriptState || data.workspace_state || {};
    const scriptStages = data.scriptStages || data.script_stages || workspaceState.scriptStages || {};
    const stageOutputs = data.stageOutputs || data.stage_outputs || workspaceState.stageOutputs || {};
    const stage10Source = scriptStages.stage10 || data.stage10 || stageOutputs.stage10 || {};
    let frameworkPlanPackage =
      data.frameworkPlanPackage ||
      data.framework_plan_package ||
      stageOutputs.framework_plan_package ||
      data.framework_plan ||
      {};
    if (!hasObject(frameworkPlanPackage) && !hasObject(stageOutputs) && !hasObject(scriptStages)) {
      throw new Error("导入失败：缺少 frameworkPlanPackage、stageOutputs 或 scriptStages，无法进入框架到剧本阶段。");
    }
    if (!hasObject(frameworkPlanPackage) && (hasObject(stageOutputs) || hasObject(scriptStages))) {
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
    const allEnrichedEpisodePlan = data.allEnrichedEpisodePlan
      || data.all_enriched_episode_plan
      || stage10Source.allEnrichedEpisodePlan
      || stage10Source.enrichedEpisodePlan
      || stage10Source.batchEnrichedEpisodePlan
      || stageOutputs.allEnrichedEpisodePlan
      || stageOutputs.all_enriched_episode_plan
      || stageOutputs.batchEnrichedEpisodePlan
      || stageOutputs.batch_enriched_episode_plan
      || (stageOutputs.framework_enriched_episode_plan || {}).allEnrichedEpisodePlan
      || (stageOutputs.framework_enriched_episode_plan || {}).enrichedEpisodePlan
      || (stageOutputs.framework_enriched_episode_plan || {}).batchEnrichedEpisodePlan
      || frameworkPlanPackage.allEnrichedEpisodePlan
      || frameworkPlanPackage.all_enriched_episode_plan
      || frameworkPlanPackage.enrichedEpisodePlan
      || frameworkPlanPackage.enriched_episode_plan
      || [];
    const allEnrichedEpisodePlanText = data.allEnrichedEpisodePlanText
      || data.all_enriched_episode_plan_text
      || stage10Source.allEnrichedEpisodePlanText
      || stage10Source.enrichedEpisodePlanText
      || stageOutputs.allEnrichedEpisodePlanText
      || stageOutputs.all_enriched_episode_plan_text
      || (stageOutputs.framework_enriched_episode_plan || {}).allEnrichedEpisodePlanText
      || (stageOutputs.framework_enriched_episode_plan || {}).enrichedEpisodePlanText
      || frameworkPlanPackage.allEnrichedEpisodePlanText
      || frameworkPlanPackage.all_enriched_episode_plan_text
      || frameworkPlanPackage.enrichedEpisodePlanText
      || frameworkPlanPackage.enriched_episode_plan_text
      || "";
    const normalizedEpisodePlan = normalizeEpisodePlanItems(allEnrichedEpisodePlan);
    const title = data.project_title || data.source_title || data.title || basic.project_title || basic.source_title || frameworkPlanPackage.project_title || "导入的框架 JSON";
    const inferredFromPlan = inferTotalEpisodes(normalizedEpisodePlan, data);
    const inferredFromText = episodeNumbersFromText(allEnrichedEpisodePlanText);
    const episodes = Number(data.episodes_per_season || data.total_episodes || basic.episodes_per_season || basic.total_episodes || frameworkPlanPackage.episodes_per_season || inferredFromPlan || (inferredFromText.length ? Math.max(...inferredFromText) : 0));
    if (!String(title || "").trim()) {
      throw new Error("导入失败：无法确定项目标题。");
    }
    if (!hasObject(frameworkPlanPackage)) {
      throw new Error("导入失败：无法确定框架核心内容。");
    }
    if (normalizedEpisodePlan.length && episodes) {
      const validation = validateStage10Completeness(normalizedEpisodePlan, allEnrichedEpisodePlanText, episodes);
      if (!validation.ok) {
        console.warn("[framework_to_script] imported stage10 validation warnings", validation.issues);
      }
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
      minutes_per_episode: data.minutes_per_episode || basic.minutes_per_episode || "",
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
      scriptStages: Object.assign({}, scriptStages, normalizedEpisodePlan.length || allEnrichedEpisodePlanText ? {
        stage10: {
          ...(scriptStages.stage10 || {}),
          allEnrichedEpisodePlan: normalizedEpisodePlan,
          enrichedEpisodePlan: normalizedEpisodePlan,
          batchEnrichedEpisodePlan: normalizedEpisodePlan,
          allEnrichedEpisodePlanText,
          enrichedEpisodePlanText: allEnrichedEpisodePlanText,
          episodeValidation: { ok: true, issues: [] },
        },
      } : {}),
    };
  }

  async function importStructuredFrameworkFile(file) {
    if (!file) return;
    state.error = null;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const asset = normalizeImportedFrameworkJson(parsed);
      try {
        window.localStorage.removeItem(STORAGE_KEY);
        if (STORAGE_KEY !== LEGACY_STORAGE_KEY) window.localStorage.removeItem(LEGACY_STORAGE_KEY);
        window.localStorage.removeItem("frameworkToScriptSource");
      } catch (error) {}
      state.frameworkAssetId = "";
      state.projectId = "";
      state.importedFrameworkAsset = asset;
      state.frameworkPlanPackage = asset.framework_plan_package || {};
      state.stageOutputs = asset.stage_outputs || {};
      state.scriptStages = asset.scriptStages || {};
      const importedHasStage10 = hasContent(stage10Plan(state.scriptStages.stage10 || {})) || hasContent(stage10Text(state.scriptStages.stage10 || {}));
      state.stages = importedHasStage10 ? { 10: { status: "completed", stage_key: "stage10", updated_at: new Date().toISOString() } } : {};
      state.completedStages = importedHasStage10 ? ["10"] : [];
      setPreferenceSnapshot(asset.preference_snapshot || {}, "imported_json");
      state.frameworkSource = "导入 JSON";
      state.assetPanelOpen = false;
      state.importStatus = `导入成功：${asset.title || "未命名框架"} · ${asset.episodes_per_season || "未知"} 集 · ${asset.minutes_per_episode || "未知"} 分钟/集`;
      saveWorkspace();
    } catch (error) {
      state.error = error.message || "导入失败：JSON 格式不正确。";
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
    clearStageFailure("08");
    render();
    render();
    try {
      const data = await requestStageJsonWithRetry("08", "/api/framework-to-script/stage/08", () => ({
        method: "POST",
        body: JSON.stringify(attachKnowledgePayload({
          ...frameworkRequestBase(),
        }, "08")),
      }));
      state.scriptStages.stage08 = {
        sceneDictionary: data.sceneDictionary,
        scriptWorldRulesDigest: data.scriptWorldRulesDigest,
        updated_at: new Date().toISOString(),
      };
      clearDownstreamStages("stage08");
      clearStageFailure("08");
      saveWorkspace();
    } catch (error) {
      markStageFailure("08", error, "08 提炼核心场景失败");
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
      state.error = "请先完成 08 提炼核心场景。";
      render();
      return;
    }
    if (hasObject((state.scriptStages.stage09 || {}).appearanceMapping) && !window.confirm("重新运行 09 会覆盖 09 输出，并清空后续 10-12 已生成结果。继续吗？")) return;
    saveRunningStage("09");
    state.error = null;
    clearStageFailure("09");
    render();
    try {
      const data = await requestStageJsonWithRetry("09", "/api/framework-to-script/stage/09", () => ({
        method: "POST",
        body: JSON.stringify(attachKnowledgePayload({
          ...frameworkRequestBase(),
          sceneDictionary: stage08.sceneDictionary,
        }, "09")),
      }));
      state.scriptStages.stage09 = {
        appearanceMapping: data.appearanceMapping,
        updated_at: new Date().toISOString(),
      };
      clearDownstreamStages("stage09");
      clearStageFailure("09");
      saveWorkspace();
    } catch (error) {
      markStageFailure("09", error, "09 确定角色外观失败");
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
      state.error = "请先完成 08 提炼核心场景。";
      render();
      return;
    }

    if (!hasObject(stage09.appearanceMapping)) {
      state.error = "请先完成 09 确定角色外观。";
      render();
      return;
    }
    if (hasContent(stage10Plan(state.scriptStages.stage10 || {})) && !window.confirm("重新运行 10 会覆盖分集细化结果，并清空后续 11-12 已生成结果。继续吗？")) return;

    saveRunningStage("10");
    state.error = null;
    clearStageFailure("10");
    render();

    try {
      let data = null;
      let validation = null;
      let lastIssues = [];
      for (let attempt = 1; attempt <= 2; attempt += 1) {
        data = await requestStageJsonWithRetry("10", "/api/framework-to-script/stage/10", () => ({
          method: "POST",
          body: JSON.stringify(attachKnowledgePayload({
            ...frameworkRequestBase(),
            sceneDictionary: stage08.sceneDictionary,
            scriptWorldRulesDigest: stage08.scriptWorldRulesDigest,
            appearanceMapping: stage09.appearanceMapping,
            retry_reason: lastIssues.join("；"),
          }, "10")),
        }));

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
      state.stages = {
        ...(state.stages || {}),
        10: { status: "completed", stage_key: "stage10", updated_at: state.scriptStages.stage10.updated_at },
        11: { status: "pending", stage_key: "stage11", updated_at: state.scriptStages.stage10.updated_at },
        12: { status: "pending", stage_key: "stage12", updated_at: state.scriptStages.stage10.updated_at },
      };
      state.completedStages = Array.from(new Set([...(state.completedStages || []).map((item) => String(item)), "10"]))
        .filter((item) => item !== "11" && item !== "12");
      clearDownstreamStages("stage10");
      clearStageFailure("10");

      saveWorkspace();
    } catch (error) {
      markStageFailure("10", error, "10 优化分集计划失败");
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
    const rewriteExistingScript = stage12Completion().complete || hasStage12ScriptText();
    if (
      rewriteExistingScript &&
      !window.confirm("当前框架资产已经生成过剧本。一键生成将保留 08-10 框架资产，重新生成 11 因果冲突和 12 正文，相当于重写全剧。继续吗？")
    ) {
      return;
    }
    if (!hasObject((state.scriptStages.stage08 || {}).sceneDictionary)) {
      await runStage08();
      if (state.error) return;
    }
    if (!hasObject((state.scriptStages.stage09 || {}).appearanceMapping)) {
      await runStage09();
      if (state.error) return;
    }
    if (!hasContent(stage10Plan(state.scriptStages.stage10 || {}))) {
      await runStage10();
      if (state.error) return;
    }
    if (rewriteExistingScript) {
      await runStage11({ resetStage11: true, skipConfirm: true });
      if (state.error) return;
      await runStage12({ resetStage12: true, skipConfirm: true });
      return;
    }
    if (!stage11Completion().complete) {
      await runStage11();
      if (state.error) return;
    }
    if (!stage12Completion().complete) {
      await runStage12();
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
      state.error = "请先完成 08 提炼核心场景。";
      render();
      return;
    }
    if (!hasObject(stage09.appearanceMapping)) {
      state.error = "请先完成 09 确定角色外观。";
      render();
      return;
    }
    const resetStage11 = Boolean(options.resetStage11);
    if (resetStage11 && !options.skipConfirm && !window.confirm("重新运行 11 会覆盖开头冲突钩子，并清空 12 正文批次。继续吗？")) return;
    const expectedStarts = expectedBatchStartsFromPlan(allEnrichedEpisodePlan);
    if (resetStage11) {
      state.scriptStages.stage11 = {};
    }
    state.scriptStages.stage12 = {};
    saveRunningStage("11");
    state.error = null;
    clearStageFailure("11");
    render();
    try {
      let firstRequest = true;
      let guard = 0;
      while (guard < 200) {
        guard += 1;
        const currentStage11 = state.scriptStages.stage11 || {};
        const beforeCount = numericKeys(currentStage11.batches).length;
        const beforeMissing = missingBatchStarts(expectedStarts, numericKeys(currentStage11.batches));
        if (expectedStarts.length && !beforeMissing.length) break;
        const batchStart = beforeMissing[0] || expectedStarts[beforeCount] || expectedStarts[0];
        await runResilientStageBatch("11", batchStart, async () => {
          const latestStage11 = state.scriptStages.stage11 || {};
          const latestBeforeCount = numericKeys(latestStage11.batches).length;
          const data = await requestJsonWithTimeout("/api/framework-to-script/stage/11", {
            method: "POST",
            body: JSON.stringify(attachKnowledgePayload({
              ...frameworkRequestBase(),
              allEnrichedEpisodePlan,
              sceneDictionary: stage08.sceneDictionary,
              scriptWorldRulesDigest: stage08.scriptWorldRulesDigest,
              appearanceMapping: stage09.appearanceMapping,
              batchStartEpisode: batchStart,
              batch_start_episode: batchStart,
              reset_stage11: resetStage11 && firstRequest,
              conflictMemory: resetStage11 && firstRequest ? "" : (latestStage11.conflictMemory || ""),
            }, "11")),
          }, RESILIENT_STAGE_REQUEST_TIMEOUT_MS);
          mergeStage11(data);
          saveWorkspace();
          render();
          const latestAfterCount = numericKeys((state.scriptStages.stage11 || {}).batches).length;
          const latestAfterMissing = missingBatchStarts(expectedStarts, numericKeys((state.scriptStages.stage11 || {}).batches));
          if (latestAfterMissing.length && latestAfterCount <= latestBeforeCount) {
            throw new Error(`后端返回后未新增批次，仍缺少第 ${latestAfterMissing[0]} 集起。`);
          }
        });
        firstRequest = false;
      }
      const finalMissing = missingBatchStarts(expectedStarts, numericKeys((state.scriptStages.stage11 || {}).batches));
      if (finalMissing.length) {
        throw new Error(`11 未完成全部批次，剩余第 ${finalMissing.join("、")} 集起。`);
      }
      saveWorkspace();
      clearStageFailure("11");
    } catch (error) {
      markStageFailure("11", error, "11 开头冲突钩子失败");
    } finally {
      stopRunningProgress();
      clearRunningStage("11");
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
    }
    const resetStage12 = Boolean(options.resetStage12);
    if (resetStage12 && !options.skipConfirm && !window.confirm("重新运行 12 会覆盖已生成的正文批次。继续吗？")) return;
    if (resetStage12) {
      state.scriptStages.stage12 = {};
    }
    saveRunningStage("12");
    state.error = null;
    clearStageFailure("12");
    render();
    try {
      let firstRequest = true;
      let guard = 0;
      while (guard < 200) {
        guard += 1;
        const currentStage11 = state.scriptStages.stage11 || {};
        const currentStage12 = state.scriptStages.stage12 || {};
        const stage11Keys = numericKeys(currentStage11.batches);
        const expectedCount = stage11Keys.length || (hasContent(currentStage11.batchCausalConflictPlan) ? 1 : 0);
        const beforeCount = numericKeys(currentStage12.batches).length;
        const beforeMissing = missingBatchStarts(stage11Keys, numericKeys(currentStage12.batches));
        if (expectedCount && !beforeMissing.length) break;
        const batchStart = beforeMissing[0] || stage11Keys[beforeCount] || stage11Keys[0];
        await runResilientStageBatch("12", batchStart, async () => {
          const latestStage11 = state.scriptStages.stage11 || {};
          const latestStage12 = state.scriptStages.stage12 || {};
          const latestStage11Keys = numericKeys(latestStage11.batches);
          const latestBeforeCount = numericKeys(latestStage12.batches).length;
          const data = await requestJsonWithTimeout("/api/framework-to-script/stage/12", {
            method: "POST",
            body: JSON.stringify(attachKnowledgePayload({
              ...frameworkRequestBase(),
              stage08: state.scriptStages.stage08 || {},
              stage09: state.scriptStages.stage09 || {},
              stage11: latestStage11,
              stage12: latestStage12,
              batchStartEpisode: batchStart,
              batch_start_episode: batchStart,
              reset_stage12: resetStage12 && firstRequest,
            }, "12")),
          }, RESILIENT_STAGE_REQUEST_TIMEOUT_MS);
          mergeStage12(data);
          saveWorkspace();
          render();
          const latestAfterCount = numericKeys((state.scriptStages.stage12 || {}).batches).length;
          const latestAfterMissing = missingBatchStarts(latestStage11Keys, numericKeys((state.scriptStages.stage12 || {}).batches));
          if (latestAfterMissing.length && latestAfterCount <= latestBeforeCount) {
            throw new Error(`后端返回后未新增正文批次，仍缺少第 ${latestAfterMissing[0]} 集起。`);
          }
        });
        firstRequest = false;
      }
      const finalStage11Keys = numericKeys((state.scriptStages.stage11 || {}).batches);
      const finalMissing = missingBatchStarts(finalStage11Keys, numericKeys((state.scriptStages.stage12 || {}).batches));
      if (finalMissing.length) {
        throw new Error(`12 未完成全部正文批次，剩余第 ${finalMissing.join("、")} 集起。`);
      }
      saveWorkspace();
      clearStageFailure("12");
    } catch (error) {
      markStageFailure("12", error, "12 正文及对话失败");
    } finally {
      stopRunningProgress();
      if (!options.autoFromStage11) {
        clearRunningStage("12");
      } else {
        state.runningStage = "";
        state.runningStartedAt = "";
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
      const filename = exportScriptFilename("txt");
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
      const filename = exportScriptFilename("docx");
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


  function renderTree(value, keyName = "root", depth = 0, detailsPath = "") {
    let clean = null;
    try {
      clean = stripRaw(value);
    } catch (error) {
      console.warn("[framework_to_script] renderTree strip failed", error);
      return `<div class="wts-tree-text">${renderTreeText(value)}</div>`;
    }
    if (clean === null || clean === undefined || clean === "") {
      return `<div class="wts-empty-inline">暂无内容</div>`;
    }
    if (Array.isArray(clean)) {
      if (!clean.length) return `<div class="wts-empty-inline">暂无条目</div>`;
      return `<div class="wts-tree-list">${clean.map((item, index) => `
        <details class="wts-tree-node" ${persistentDetailsAttrs(`${detailsPath || keyName}:item:${index}`, depth < 1)}>
          <summary><span class="wts-tree-arrow"></span>${escapeHtml(labelFor(keyName))} ${index + 1}</summary>
          <div>${safeRenderTree(item, keyName, depth + 1, `${detailsPath || keyName}:item:${index}`)}</div>
        </details>
      `).join("")}</div>`;
    }
    if (typeof clean === "object") {
      const entries = Object.entries(clean).filter(([key]) => !RAW_KEYS.has(key) && !(window.fieldLabelsCn && window.fieldLabelsCn.isHiddenKey && window.fieldLabelsCn.isHiddenKey(key)));
      if (!entries.length) return `<div class="wts-empty-inline">暂无内容</div>`;
      return `<div class="wts-tree-list">${entries.map(([key, item]) => {
        const complex = item && typeof item === "object";
        return complex ? `
          <details class="wts-tree-node" ${persistentDetailsAttrs(`${detailsPath || keyName}:field:${key}`, depth < 1)}>
            <summary><span class="wts-tree-arrow"></span>${escapeHtml(labelFor(key))}</summary>
            <div>${safeRenderTree(item, key, depth + 1, `${detailsPath || keyName}:field:${key}`)}</div>
          </details>
        ` : `
          <div class="wts-tree-leaf">
            <b>${escapeHtml(labelFor(key))}</b>
            ${renderTreeText(item, `${detailsPath || keyName}:field:${key}:text`)}
          </div>
        `;
      }).join("")}</div>`;
    }
    return `<div class="wts-tree-text">${renderTreeText(clean, `${detailsPath || keyName}:text`)}</div>`;
  }

  function safeRenderTree(value, keyName = "root", depth = 0, detailsPath = "") {
    try {
      return renderTree(value, keyName, depth, detailsPath);
    } catch (error) {
      console.warn("[framework_to_script] render tree failed", error);
      return `<div class="wts-error-inline">该内容暂时无法展开渲染，已保留原始摘要：${escapeHtml(truncate(readableValue(value), 360))}</div>`;
    }
  }

  function renderStage10Output(stage10) {
    const text = stage10Text(stage10);
    if (String(text || "").trim()) {
      return safeRenderTree(text, "enrichedEpisodePlanText", 0, "stage10:enrichedEpisodePlanText");
    }
    const plan = normalizeEpisodePlanItems(stage10Plan(stage10));
    if (plan.length) {
      return `
        <div class="wts-tree-list">
          ${plan.map((item, index) => `
            <details class="wts-tree-node" ${persistentDetailsAttrs(`stage10:episode:${item.episode || index + 1}`, index < 3)}>
              <summary><span class="wts-tree-arrow"></span>第 ${escapeHtml(item.episode || index + 1)} 集 ${escapeHtml(item.title || "")}</summary>
              <div>${safeRenderTree(item, "episode", 1, `stage10:episode:${item.episode || index + 1}`)}</div>
            </details>
          `).join("")}
        </div>
      `;
    }
    return safeRenderTree("已生成结构化优化分集计划，供 11/12 阶段继续使用；本次未返回分集细化文本。", "enrichedEpisodePlanText", 0, "stage10:empty");
  }

  function renderTreeText(value, detailsPath = "") {
    const text = String(value ?? "");
    if (text.length <= 420) return `<span>${escapeHtml(text)}</span>`;
    return `
      <details class="wts-tree-more" ${persistentDetailsAttrs(`${detailsPath || "text"}:more`, false)}>
        <summary>
          <span class="wts-tree-preview">${escapeHtml(text.slice(0, 420))}...</span>
          <span class="wts-tree-expand-label">展开全文</span>
          <span class="wts-tree-collapse-label">收起</span>
        </summary>
        <div>${escapeHtml(text)}</div>
      </details>
    `;
  }

  function renderFrameworkPackageField(label, value, key, index) {
    if (!hasContent(value)) return "";
    const text = typeof value === "string" ? value : readableValue(value);
    const count = Array.isArray(value)
      ? `${value.filter(hasContent).length} 条`
      : (value && typeof value === "object" ? `${Object.keys(value).filter((itemKey) => !RAW_KEYS.has(itemKey) && hasContent(value[itemKey])).length} 项` : "");
    return `
      <details class="wts-package-field" data-framework-package-field="${escapeHtml(key || String(index))}">
        <summary>
          <span class="wts-package-arrow" aria-hidden="true"></span>
          <strong>${escapeHtml(label)}</strong>
          <small>${escapeHtml(count || truncate(text, 96) || "点击展开查看")}</small>
        </summary>
        <div class="wts-package-field-body">${renderTreeText(text || "暂无")}</div>
      </details>
    `;
  }

  function firstContentValue(...values) {
    return values.find((value) => hasContent(value));
  }

  function renderFrameworkPackageStack(packageValue) {
    const source = packageValue && typeof packageValue === "object" && !Array.isArray(packageValue) ? packageValue : {};
    const outputs = state.stageOutputs || {};
    const fields = [
      {
        key: "beat_checkpoint_timeline",
        label: "三幕十五节拍",
        value: firstContentValue(source.beat_checkpoint_timeline, source.beatCheckpointTimeline, outputs.beat_checkpoint_timeline, outputs.beatCheckpointTimeline),
      },
      {
        key: "worldview_plan",
        label: "世界观方案",
        value: firstContentValue(source.worldview_plan, source.worldviewPlan, source.worldview, outputs.worldview_plan, outputs.worldviewPlan, outputs.worldview),
      },
    ].filter((item) => hasContent(item.value));
    return `
      <div class="wts-package-stack">
        ${fields.map((item, index) => renderFrameworkPackageField(item.label, item.value, item.key, index)).join("") || `<div class="wts-empty-inline">暂无最终策划包内容</div>`}
      </div>
    `;
  }

  function renderAssetPanel() {
    if (!state.assetPanelOpen) return "";
    const scriptAssets = state.assets.filter((asset) => hasFrameworkToScriptProgress(asset));
    const frameworkAssets = state.assets.filter((asset) => !hasFrameworkToScriptProgress(asset));
    return `
      <section class="wts-card wts-asset-panel" id="frameworkAssetPanel">
        <div class="wts-card-head">
          <div>
            <h2>剧本阶段资产</h2>
            <p>优先从已保存的 08-12 进度恢复；没有进度时再选择框架资产重新开始。</p>
          </div>
          <button type="button" class="wts-btn ghost" data-action="close-asset-panel">收起</button>
        </div>
        ${state.isLoadingAsset ? `<div class="wts-loading">正在读取框架资产...</div>` : ""}
        <div class="wts-import-json" data-import-json-drop-zone>
          <label class="wts-btn">
            导入结构化框架 JSON
            <input type="file" accept="application/json,.json" data-import-framework-json hidden />
          </label>
          <span>${escapeHtml(state.importStatus || "支持拖拽/点击上传 07 导出的结构化框架 JSON，也支持包含 08-12 scriptStages/stageOutputs 的工作区 JSON。")}</span>
        </div>
        <div class="wts-asset-list">
          <h3>已有剧本阶段进度</h3>
          ${scriptAssets.length ? scriptAssets.map((asset) => renderAssetItem(asset, { restoreScript: true })).join("") : `<div class="wts-empty">当前没有已保存的 08-12 剧本阶段资产。</div>`}
        </div>
        <div class="wts-asset-list">
          <h3>可用框架资产</h3>
          ${frameworkAssets.length ? frameworkAssets.map((asset) => renderAssetItem(asset)).join("") : `<div class="wts-empty">暂无可导入框架资产。请先在框架生成页面完成 01-07 并保存。</div>`}
        </div>
      </section>
    `;
  }

  function hasFrameworkToScriptProgress(asset) {
    const progress = asset && typeof asset.framework_to_script_progress === "object" ? asset.framework_to_script_progress : {};
    return Boolean(asset?.has_framework_to_script_state || progress.has_state || progress.latest_stage || Number(progress.stage_count || 0) > 0);
  }

  function frameworkToScriptProgressText(asset) {
    const progress = asset && typeof asset.framework_to_script_progress === "object" ? asset.framework_to_script_progress : {};
    const completed = Array.isArray(progress.completed_stages) ? progress.completed_stages : [];
    const running = String(progress.running_stage || "").trim();
    if (running) return `运行中：${running}`;
    if (completed.length) return `已保存到：${completed.map((item) => String(item).padStart(2, "0")).join("、")}`;
    return "已保存剧本阶段进度";
  }

  function renderAssetItem(asset, options = {}) {
    const restoreScript = Boolean(options.restoreScript);
    const canImport = restoreScript || asset.can_import !== false;
    const disabled = canImport ? "" : "disabled";
    const meta = [
      asset.target_format || "未填写类型",
      asset.episodes_per_season ? `${asset.episodes_per_season} 集` : "",
      asset.episode_word_count ? `${asset.episode_word_count} 字/集` : "",
      `更新时间：${formatDate(asset.updated_at || asset.created_at)}`,
    ].filter(Boolean);
    const importStatus = asset.import_readiness || (canImport ? "可导入：已找到最终策划包。" : asset.import_disabled_reason || "不可导入：缺少最终策划包。");
    const packageSource = asset.framework_package_source === "synthesized_stage_outputs"
      ? "阶段输出合成"
      : (asset.framework_package_source === "framework_plan_package" ? "07 最终策划包" : "");
    const progressText = hasFrameworkToScriptProgress(asset) ? frameworkToScriptProgressText(asset) : "";
    return `
      <article class="wts-asset-item">
        <div>
          <h3>${escapeHtml(asset.title || "未命名框架资产")}</h3>
          <div class="wts-meta">
            <span>原文：${escapeHtml(asset.source_title || "未填写")}</span>
            ${meta.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
            <span>${escapeHtml(canImport ? `可导入${packageSource ? `（${packageSource}）` : ""}` : "不可导入")}</span>
          </div>
          <p>${escapeHtml(asset.summary || "暂无摘要")}</p>
          ${progressText ? `<p class="wts-hint">${escapeHtml(progressText)}</p>` : ""}
          <p class="${canImport ? "wts-hint" : "wts-error-inline"}">${escapeHtml(restoreScript ? "点击恢复该资产已保存的 08-12 剧本阶段进度。" : importStatus)}</p>
        </div>
        <button type="button" class="wts-btn" data-action="import-asset" data-asset-id="${escapeHtml(asset.asset_id)}" ${disabled}>${restoreScript ? "恢复进度" : "导入"}</button>
      </article>
    `;
  }

  function renderImportedSummary() {
    if (!currentAssetReady()) {
      return `
        <section class="wts-card wts-empty-state">
          <h2>当前流程：从框架写剧本</h2>
          <p>请先选择已有框架资产，或导入结构化框架 JSON。导入后会从 08 场景字典开始继续生成正文。</p>
        </section>
      `;
    }
    const asset = state.importedFrameworkAsset || {};
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
            <span>保存时间：${escapeHtml(formatDate(asset.updated_at || asset.created_at))}</span>
            <button type="button" class="wts-btn ghost" data-action="save-workspace">保存当前剧本进度</button>
          </div>
        </div>
        <div class="wts-framework-package-only">
          <h3>最终策划包</h3>
          ${renderFrameworkPackageStack(state.frameworkPlanPackage)}
        </div>
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
    const stage11Progress = stage11Completion();
    const stage12Progress = stage12Completion();
    const has11 = hasContent(stage11.batchCausalConflictPlan) || stage11Progress.done.length > 0;
    const has12 = hasContent(stage12.batchScriptText) || stage12Progress.done.length > 0;
    const has11Complete = stage11Progress.complete;
    const has12Complete = stage12Progress.complete;
    const stage11Status = state.runningStage === "11"
      ? (runningProgressText("11") || `运行中 ${stage11Progress.done.length}/${stage11Progress.expected.length || "?"}`)
      : has11Complete
        ? "已完成"
        : has11
          ? `部分完成 ${stage11Progress.done.length}/${stage11Progress.expected.length || "?"}`
          : has10Output
            ? "待运行"
            : "等待 10";
    const stage12Status = state.runningStage === "12"
      ? (runningProgressText("12") || `运行中 ${stage12Progress.done.length}/${stage12Progress.expected.length || "?"}`)
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
    const stage12ButtonText = has12Complete ? "重新运行 12" : "生成全部正文";
    const stage12Action = has12Complete ? "rerun-stage-12" : "run-stage-12";
    const fullButtonText = has12Complete ? "重写全剧剧本" : has12 ? "继续一键生成剧本" : "一键生成剧本";
    return `
      <section class="wts-card" id="scriptStageArea">
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
            "提炼核心场景",
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
            "确定角色外观",
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
            "优化分集计划",
            state.runningStage === "10" ? "运行中" : has10 ? "已完成" : has09 ? "待运行" : "等待 09",
            has10 ? "重新运行 10" : "运行 10",
            "run-stage-10",
            locked || !has09,
            has10 ? `
              <details class="wts-output" ${outputDetailsAttrs("stage10:enrichedEpisodePlanText")}>
                <summary><span class="wts-output-arrow" aria-hidden="true"></span><span>分集细化文本</span></summary>
                ${renderStage10Output(stage10)}
              </details>
              ${stage10Valid ? `<p class="wts-hint">第 10 阶段已完成，可继续运行 11。</p>` : `<p class="wts-error-inline">集数完整性校验失败：${escapeHtml((stage10Validation.issues || []).join("；"))}</p>`}
            ` : `<p class="wts-hint">将沿用当前导入的框架资产和已完成的 08/09 输出。</p>`,
            { secondary: has10 }
          )}
          ${renderStageCard(
            "11",
            "开头冲突钩子",
            stage11Status,
            has11Complete ? "重新运行 11" : "运行全部 11 开头冲突钩子",
            has11Complete ? "rerun-stage-11" : "run-stage-11",
            locked || !stage10Valid,
            `${renderRunningProgress("11")}${has11 ? renderStage11Batches(stage11) : `<p class="wts-hint">${state.runningStage ? `当前 ${escapeHtml(state.runningStage)} 阶段运行态锁定，完成或任务中断后才能点击按钮。` : ""}</p>`}`,
            { secondary: has11Complete }
          )}
          ${renderStageCard(
            "12",
            "正文及对话",
            stage12Status,
            stage12ButtonText,
            stage12Action,
            locked || !has11Complete,
            `${renderRunningProgress("12")}${has12 ? renderStage12Batches(stage12) : `<p class="wts-hint"></p>`}`,
            { secondary: has12Complete }
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
        ${renderErrorPanel()}
        ${renderAssetPanel()}
        ${renderImportedSummary()}
        ${renderStages()}
      </main>
    `;
  }

  app.addEventListener("click", async (event) => {
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
      target.disabled = true;
      const previousText = target.textContent;
      target.textContent = "保存中...";
      try {
        await saveWorkspaceToAsset();
        state.error = null;
        state.importStatus = "剧本进度已保存到当前框架资产。";
      } catch (error) {
        state.error = error?.message || "保存剧本进度失败，请稍后重试。";
      } finally {
        target.disabled = false;
        target.textContent = previousText || "保存当前剧本进度";
        render();
      }
    } else if (action === "retry-failed-stage") {
      retryStage(state.lastFailedStage);
    } else if (action === "continue-from-failure") {
      if (["08", "09", "10", "11", "12"].includes(String(state.lastFailedStage || "").padStart(2, "0"))) {
        retryStage(state.lastFailedStage);
      } else {
        generateFullScript();
      }
    } else if (action === "collapse-tree-node") {
      const detail = target.closest("details.wts-tree-node");
      if (detail) detail.open = false;
    }
  });

  app.addEventListener("toggle", (event) => {
    const target = event.target;
    if (!target || !target.matches) return;
    if (target.matches("details[data-output-details-id]")) {
      setOutputDetailsOpen(target.dataset.outputDetailsId, target.open);
    }
    if (target.matches("details[data-persist-details-id]")) {
      setPersistentDetailsOpen(target.dataset.persistDetailsId, target.open);
    }
  }, true);

  app.addEventListener("change", (event) => {
    const target = event.target;
    if (!target || !target.matches || !target.matches("[data-import-framework-json]")) return;
    const file = target.files && target.files[0];
    importStructuredFrameworkFile(file);
    target.value = "";
  });

  app.addEventListener("dragover", (event) => {
    const zone = event.target && event.target.closest ? event.target.closest("[data-import-json-drop-zone]") : null;
    if (!zone) return;
    event.preventDefault();
    zone.classList.add("drag-over");
  });

  app.addEventListener("dragleave", (event) => {
    const zone = event.target && event.target.closest ? event.target.closest("[data-import-json-drop-zone]") : null;
    if (!zone || zone.contains(event.relatedTarget)) return;
    zone.classList.remove("drag-over");
  });

  app.addEventListener("drop", (event) => {
    const zone = event.target && event.target.closest ? event.target.closest("[data-import-json-drop-zone]") : null;
    if (!zone) return;
    event.preventDefault();
    zone.classList.remove("drag-over");
    const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    importStructuredFrameworkFile(file);
  });

  restoreRunningStage();
  reconcileRunningStageResult();
  render();

  if (state.frameworkAssetId && (directFromPlanner || state.runningStage || !currentAssetReady())) {
    importAsset(state.frameworkAssetId, { skipConfirm: true });
  } else if (!state.frameworkAssetId && !currentAssetReady()) {
    loadAssets();
  }
})();
