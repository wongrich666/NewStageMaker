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
  } else if (!urlAssetId) {
    state.frameworkAssetId = null;
    state.projectId = null;
    state.importedFrameworkAsset = null;
    state.frameworkPlanPackage = null;
    state.stageOutputs = {};
    state.scriptStages = {};
    state.assetPanelOpen = true;
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
      clearDownstreamStages("stage10");

      saveWorkspace();
    } catch (error) {
      state.error = error.message || "10 分集细化方案失败";
    } finally {
      clearRunningStage("10");
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
          body: JSON.stringify({
            framework_asset_id: state.frameworkAssetId,
            allEnrichedEpisodePlan,
            sceneDictionary: stage08.sceneDictionary,
            scriptWorldRulesDigest: stage08.scriptWorldRulesDigest,
            appearanceMapping: stage09.appearanceMapping,
            reset_stage11: resetStage11 && firstRequest,
            conflictMemory: resetStage11 && firstRequest ? "" : (currentStage11.conflictMemory || ""),
          }),
        });
        mergeStage11(data);
        saveWorkspace();
        render();
        const afterCount = numericKeys((state.scriptStages.stage11 || {}).batches).length;
        if (afterCount <= beforeCount) break;
        firstRequest = false;
      }
      saveWorkspace();
      await runStage12({ resetStage12: resetStage11, autoFromStage11: true });
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
    if (resetStage12) {
      state.scriptStages.stage12 = {};
    }
    state.runningStage = "12";
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
          body: JSON.stringify({
            framework_asset_id: state.frameworkAssetId,
            reset_stage12: resetStage12 && firstRequest,
          }),
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
          <div>${renderTree(item, keyName, depth + 1)}<button type="button" class="wts-btn ghost wts-collapse-local" data-action="collapse-tree-node">收起本层</button></div>
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
            <summary><span class="wts-tree-arrow"></span>${escapeHtml(labelFor(key))}</summary>
            <div>${renderTree(item, key, depth + 1)}<button type="button" class="wts-btn ghost wts-collapse-local" data-action="collapse-tree-node">收起本层</button></div>
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
            <p>从已有框架写剧本必须先选择已保存框架资产；本页不会自动使用旧缓存。</p>
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

  function renderStageCard(id, title, status, buttonText, action, disabled, body, extraActions = "") {
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
            ${extraActions}
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
    const reset08Button = `<button type="button" data-action="rerun-stage-08" ${locked ? "disabled" : ""}>重新运行08阶段</button>`;
    const reset09Button = `<button type="button" data-action="rerun-stage-09" ${locked || !has08 ? "disabled" : ""}>重新运行09阶段</button>`;
    const reset10Button = `<button type="button" data-action="rerun-stage-10" ${locked || !has09 ? "disabled" : ""}>重新运行10阶段</button>`;
    const reset11Button = `<button type="button" data-action="rerun-stage-11" ${locked || !has10Output ? "disabled" : ""}>重新运行11阶段</button>`;
    const reset12Button = `<button type="button" data-action="rerun-stage-12" ${locked || !has11Complete ? "disabled" : ""}>重新运行12阶段</button>`;
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
              : `<p class="wts-hint">运行完成前不展示输出；结果会自动缓存并供后续阶段使用。</p>`,
            reset08Button
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
            reset09Button
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
            ` : `<p class="wts-hint">将沿用当前导入的框架资产和已完成的 08/09 输出。</p>`,
            reset10Button
          )}
          ${renderStageCard(
            "11",
            "开头冲突钩子",
            stage11Status,
            has11Complete ? "重新补跑 11→12" : has11 ? "继续运行" : "运行 11",
            "run-stage-11",
            locked || !has10Output,
            has11 ? renderStage11Batches(stage11) : `<p class="wts-hint">${state.runningStage ? `当前 ${escapeHtml(state.runningStage)} 阶段运行态锁定，完成或超时后可继续。` : ""}</p>`,
            reset11Button
          )}
          ${renderStageCard(
            "12",
            "正文及对话",
            stage12Status,
            has12Complete ? "重新补跑 12" : has12 ? "继续运行 12" : "运行 12",
            "run-stage-12",
            locked || !has11Complete,
            has12 ? renderStage12Batches(stage12) : `<p class="wts-hint"></p>`,
            reset12Button
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
            <p>从已有框架写剧本。请先选择已保存框架资产，再执行 08-12 正文链路。</p>
          </div>
          <div class="wts-actions">
            <button type="button" class="wts-btn" data-action="open-asset-panel">导入框架资产</button>
            <button type="button" class="wts-btn ghost" data-action="download-txt">下载 TXT</button>
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
    } else if (action === "save-workspace") {
      saveWorkspace();
      state.error = null;
      render();
    } else if (action === "show-version-history") {
      state.assetPanelOpen = true;
      loadAssets();
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

  restoreRunningStage();
  reconcileRunningStageResult();
  render();

  if (state.frameworkAssetId && (state.runningStage || !currentAssetReady())) {
    importAsset(state.frameworkAssetId, { skipConfirm: true });
  } else if (!state.frameworkAssetId) {
    loadAssets();
  }
})();
