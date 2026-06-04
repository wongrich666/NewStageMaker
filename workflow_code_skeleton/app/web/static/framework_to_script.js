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
    preferenceSnapshot: {},
    preferenceSource: "none",
    assets: [],
    assetPanelOpen: false,
    isLoadingAsset: false,
    isRunning: false,
    runningStage: "",
    runningStartedAt: "",
    error: null,
    importStatus: "",
    frameworkSource: "",
  }, loadWorkspace());

  const urlAssetId = params.get("framework_asset_id") || params.get("asset_id") || "";
  const directFromPlanner = Boolean(urlAssetId && (params.has("source_framework_project_id") || params.has("project_id")));
  if (urlAssetId && (directFromPlanner || String(urlAssetId) !== String(state.frameworkAssetId || ""))) {
    window.localStorage.removeItem(STORAGE_KEY);
    state.frameworkAssetId = urlAssetId;
    state.frameworkSource = "刚刚完成的框架";
    state.projectId = null;
    state.importedFrameworkAsset = null;
    state.frameworkPlanPackage = null;
    state.stageOutputs = {};
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
        frameworkSource: state.frameworkSource,
        preferenceSnapshot: state.preferenceSnapshot,
        preferenceSource: state.preferenceSource,
      })));
    } catch (error) {}
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

  function stageHasCompleted(stage) {
    const stages = state.scriptStages || {};
    const stage08 = stages.stage08 || {};
    const stage09 = stages.stage09 || {};
    const stage10 = stages.stage10 || {};

    if (stage === "08") return hasObject(stage08.sceneDictionary);
    if (stage === "09") return hasObject(stage09.appearanceMapping);
    if (stage === "10") return hasContent(stage10.allEnrichedEpisodePlan) || hasContent(stage10.enrichedEpisodePlan);
    if (stage === "11") return stage11Completion().complete;
    if (stage === "12") return stage12Completion().complete;
    return false;
  }

  function mergeStage11(data) {
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
  }

  function mergeStage12(data) {
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
          ${renderTree(stage12.batchScriptText || stage12.batch_script_text, "batchScriptText")}
        </details>
      `;
    }
    return keys.map((key) => {
      const batch = batches[key] || {};
      return `
        <details class="wts-output" ${outputDetailsAttrs(`stage12:${key}:script`)}>
          <summary>第 ${escapeHtml(batch.batchStartEpisode || key)}-${escapeHtml(batch.batchEndEpisode || "")} 集正文</summary>
          ${renderTree(batch.batchScriptText || batch.batch_script_text || "暂无", "batchScriptText")}
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
      state.stageOutputs = asset.stage_outputs || {};
      state.scriptStages = asset.scriptStages || (asset.framework_to_script_state || {}).scriptStages || {};
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
      throw new Error("导入失败：无法确定项目标题。");
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
      },
      scriptStages: normalizedEpisodePlan.length ? {
        stage10: {
          allEnrichedEpisodePlan: normalizedEpisodePlan,
          enrichedEpisodePlan: normalizedEpisodePlan,
          allEnrichedEpisodePlanText,
          episodeValidation: { ok: true, issues: [] },
        },
      } : {},
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
        window.localStorage.removeItem("frameworkToScriptSource");
      } catch (error) {}
      state.frameworkAssetId = "";
      state.projectId = "";
      state.importedFrameworkAsset = asset;
      state.frameworkPlanPackage = asset.framework_plan_package || {};
      state.stageOutputs = asset.stage_outputs || {};
      state.scriptStages = asset.scriptStages || {};
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
    render();
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
      clearDownstreamStages("stage08");
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
      state.scriptStages.stage09 = {
        appearanceMapping: data.appearanceMapping,
        updated_at: new Date().toISOString(),
      };
      clearDownstreamStages("stage09");
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
          body: JSON.stringify({
            ...frameworkRequestBase(),
            sceneDictionary: stage08.sceneDictionary,
            scriptWorldRulesDigest: stage08.scriptWorldRulesDigest,
            appearanceMapping: stage09.appearanceMapping,
            retry_reason: lastIssues.join("；"),
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
        const totalEpisodes = inferTotalEpisodes(enrichedEpisodePlan, state.importedFrameworkAsset);
        validation = validateStage10Completeness(enrichedEpisodePlan, enrichedEpisodePlanText, totalEpisodes);
        if (validation.ok) break;
        lastIssues = validation.issues;
      }

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
      if (!validation || !validation.ok) {
        throw new Error(`10 分集细化校验失败：${(validation && validation.issues || []).join("；")}`);
      }

      state.scriptStages.stage10 = {
        enrichedEpisodePlan: validation.normalizedPlan,
        enrichedEpisodePlanText,
        allEnrichedEpisodePlan: validation.normalizedPlan,
        allEnrichedEpisodePlanText: data.allEnrichedEpisodePlanText || enrichedEpisodePlanText,
        episodeValidation: validation,
        updated_at: new Date().toISOString(),
      };
      clearDownstreamStages("stage10");

      saveWorkspace();
    } catch (error) {
      state.error = error.message || "10 分集细化方案失败";
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
    const validation = validateStage10Completeness(allEnrichedEpisodePlan, stage10Text(stage10), inferTotalEpisodes(allEnrichedEpisodePlan, state.importedFrameworkAsset));
    if (!validation.ok) {
      state.error = `10 分集细化校验未通过，不能进入 11：${validation.issues.join("；")}`;
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
    const resetStage11 = Boolean(options.resetStage11);
    if (resetStage11 && !options.skipConfirm && !window.confirm("重新运行 11 会覆盖开头冲突钩子，并清空 12 正文批次。继续吗？")) return;
    const expectedStarts = expectedBatchStartsFromPlan(allEnrichedEpisodePlan);
    if (resetStage11) {
      state.scriptStages.stage11 = {};
    }
    state.scriptStages.stage12 = {};
    saveRunningStage("11");
    state.error = null;
    render();
    try {
      let firstRequest = true;
      let guard = 0;
      while (guard < 200) {
        guard += 1;
        const currentStage11 = state.scriptStages.stage11 || {};
        const beforeCount = numericKeys(currentStage11.batches).length;
        if (expectedStarts.length && beforeCount >= expectedStarts.length) break;
        const data = await requestJson("/api/framework-to-script/stage/11", {
          method: "POST",
          body: JSON.stringify(attachKnowledgePayload({
            ...frameworkRequestBase(),
            allEnrichedEpisodePlan,
            sceneDictionary: stage08.sceneDictionary,
            scriptWorldRulesDigest: stage08.scriptWorldRulesDigest,
            appearanceMapping: stage09.appearanceMapping,
            reset_stage11: resetStage11 && firstRequest,
            conflictMemory: resetStage11 && firstRequest ? "" : (currentStage11.conflictMemory || ""),
          }, "11")),
        });
        mergeStage11(data);
        saveWorkspace();
        render();
        const afterCount = numericKeys((state.scriptStages.stage11 || {}).batches).length;
        if (afterCount <= beforeCount) break;
        firstRequest = false;
      }
      saveWorkspace();
    } catch (error) {
      state.error = error.message || "11 开头冲突钩子失败";
    } finally {
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
    const hasStage11Batches = stage11.batches && Object.keys(stage11.batches).length > 0;
    if (!hasContent(stage11.batchCausalConflictPlan) && !hasStage11Batches) {
      state.error = "请先完成 11 当前批次开头冲突钩子。";
      render();
      return;
    }
    const resetStage12 = Boolean(options.resetStage12);
    if (resetStage12 && !options.skipConfirm && !window.confirm("重新运行 12 会覆盖已生成的正文批次。继续吗？")) return;
    if (resetStage12) {
      state.scriptStages.stage12 = {};
    }
    saveRunningStage("12");
    state.error = null;
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
        if (expectedCount && beforeCount >= expectedCount) break;
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
        mergeStage12(data);
        saveWorkspace();
        render();
        const afterCount = numericKeys((state.scriptStages.stage12 || {}).batches).length;
        if (afterCount <= beforeCount) break;
        firstRequest = false;
      }
      saveWorkspace();
    } catch (error) {
      state.error = error.message || "12 正文及对话失败";
    } finally {
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
            ${renderTreeText(item)}
          </div>
        `;
      }).join("")}</div>`;
    }
    return `<div class="wts-tree-text">${renderTreeText(clean)}</div>`;
  }

  function renderTreeText(value) {
    const text = String(value ?? "");
    if (text.length <= 420) return `<span>${escapeHtml(text)}</span>`;
    return `
      <details class="wts-tree-more">
        <summary>${escapeHtml(text.slice(0, 420))}... <span>展开全文</span></summary>
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
            <p>当前流程：从框架写剧本。请选择已保存框架资产，或导入结构化框架 JSON。</p>
          </div>
          <button type="button" class="wts-btn ghost" data-action="close-asset-panel">收起</button>
        </div>
        ${state.isLoadingAsset ? `<div class="wts-loading">正在读取框架资产...</div>` : ""}
        <div class="wts-import-json">
          <label class="wts-btn">
            导入结构化框架 JSON
            <input type="file" accept="application/json,.json" data-import-framework-json hidden />
          </label>
          <span>${escapeHtml(state.importStatus || "支持 07 页下载的结构化框架 JSON。")}</span>
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
            <button type="button" class="wts-btn ghost" data-action="save-workspace">保存当前版本</button>
          </div>
        </div>
        <div class="wts-summary-grid">
          <div class="wts-asset-current">
            <strong>当前使用的框架资产</strong>
            <span>名称：${escapeHtml(asset.title || "未命名框架资产")}</span>
            <span>ID：${escapeHtml(state.frameworkAssetId || "未记录")}</span>
          </div>
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
      ? `运行中 ${stage11Progress.done.length}/${stage11Progress.expected.length || "?"}`
      : has11Complete
        ? "已完成"
        : has11
          ? `部分完成 ${stage11Progress.done.length}/${stage11Progress.expected.length || "?"}`
          : has10Output
            ? "待运行"
            : "等待 10";
    const stage12Status = state.runningStage === "12"
      ? `运行中 ${stage12Progress.done.length}/${stage12Progress.expected.length || "?"}`
      : has12Complete
        ? "已完成"
        : has12
          ? `部分完成 ${stage12Progress.done.length}/${stage12Progress.expected.length || "?"}`
          : has11Complete
            ? "待运行"
            : "等待 11";
    const stage10Validation = stage10.episodeValidation || validateStage10Completeness(stage10Plan(stage10), stage10Text(stage10), inferTotalEpisodes(stage10Plan(stage10), state.importedFrameworkAsset));
    const stage10Valid = has10 && stage10Validation.ok;
    const stage12ButtonText = has12Complete ? "重新运行 12" : has12 ? "生成下一批正文" : "生成当前批正文";
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
            "场景字典提炼",
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
            "角色外观映射",
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
              <details class="wts-output" ${outputDetailsAttrs("stage10:enrichedEpisodePlanText")}>
                <summary>分集细化文本</summary>
                ${renderTree(
                  stage10.enrichedEpisodePlanText ||
                  stage10.allEnrichedEpisodePlanText ||
                  "已生成结构化分集细化方案，供 11/12 阶段继续使用；本次未返回分集细化文本。",
                  "enrichedEpisodePlanText"
                )}
              </details>
              ${stage10Validation.ok ? `<p class="wts-hint">集数完整性校验通过。</p>` : `<p class="wts-error-inline">集数完整性校验失败：${escapeHtml(stage10Validation.issues.join("；"))}</p>`}
            ` : `<p class="wts-hint">将沿用当前导入的框架资产和已完成的 08/09 输出。</p>`,
            { secondary: has10 }
          )}
          ${renderStageCard(
            "11",
            "开头冲突钩子",
            stage11Status,
            has11Complete ? "重新运行 11" : has11 ? "继续运行 11" : "运行 11 开头冲突钩子",
            has11Complete ? "rerun-stage-11" : "run-stage-11",
            locked || !stage10Valid,
            has11 ? renderStage11Batches(stage11) : `<p class="wts-hint">${state.runningStage ? `当前 ${escapeHtml(state.runningStage)} 阶段运行态锁定，完成或超时后可继续。` : ""}</p>`,
            { secondary: has11Complete }
          )}
          ${renderStageCard(
            "12",
            "正文及对话",
            stage12Status,
            stage12ButtonText,
            stage12Action,
            locked || !has11Complete,
            has12 ? renderStage12Batches(stage12) : `<p class="wts-hint"></p>`,
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
    } else if (action === "collapse-tree-node") {
      const detail = target.closest("details.wts-tree-node");
      if (detail) detail.open = false;
    }
  });

  app.addEventListener("toggle", (event) => {
    const target = event.target;
    if (!target || !target.matches || !target.matches("details[data-output-details-id]")) return;
    setOutputDetailsOpen(target.dataset.outputDetailsId, target.open);
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
  render();

  if (state.frameworkAssetId && (directFromPlanner || state.runningStage || !currentAssetReady())) {
    importAsset(state.frameworkAssetId, { skipConfirm: true });
  } else if (!state.frameworkAssetId && !currentAssetReady()) {
    loadAssets();
  }
})();
