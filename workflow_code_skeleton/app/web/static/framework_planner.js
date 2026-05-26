(function () {
  const config = window.frameworkPlannerConfig || {};
  const STORAGE_KEY = config.storageKey || "frameworkPlannerState.v2";
  const LEGACY_STORAGE_KEY = "new_stage_maker_framework_planner_v2";
  const PREFERENCE_STORAGE_KEY = config.preferenceStorageKey || "frameworkPlannerPromptPreferences.v1";
  const KNOWLEDGE_PANEL_STORAGE_KEY = config.knowledgePanelStorageKey || "frameworkPlannerKnowledgePanelOpen.v1";
  const API_BASE = config.apiBase || "/api/framework-planner";
  const authToken = String(config.authToken || "").trim();
  const RAW_RESPONSE_KEYS = ["responseData", "reasoningText", "historyPreview", "raw", "answerText", "choices", "usage", "updateVarResult", "newVariables"];
  const TECHNICAL_FIELD_KEYS = new Set(RAW_RESPONSE_KEYS.concat([
    "id", "nodeId", "moduleName", "moduleType", "moduleLogo",
    "runningTime", "inputTokens", "outputTokens", "totalPoints",
    "model", "query", "contextTotalLen", "finishReason", "llmRequestIds",
    "mapping_version", "schema_version", "version", "debug", "metadata",
    "cache", "logs", "_meta", "asset_state", "stage_state", "raw_stage_responses",
  ]));
  const UNSAVED_MESSAGE = "当前框架尚未保存，直接退出会丢失本次生成结果。";
  const BUSINESS_FIELD_KEYS = [
    "source_brief",
    "worldview_plan",
    "character_plan",
    "beat_checkpoint_timeline",
    "checkpoint_explanation",
    "character_storylines",
  ];
  const ARRAY_BUSINESS_FIELDS = new Set(["beat_checkpoint_timeline", "character_storylines"]);
  const DEV_LOG_ENABLED = Boolean(
    config.debug ||
    config.dev ||
    config.development ||
    config.debugMode ||
    (window.location && ["localhost", "127.0.0.1"].includes(window.location.hostname))
  );

  const VIEW_DEFS = [
    { id: "basic", label: "01. 原文信息提取 / 基础配置", stageKey: "basic" },
    { id: "worldview", label: "02. 世界观方案", stageKey: "worldview" },
    { id: "character", label: "03. 人设方案", stageKey: "character" },
    { id: "beat_timeline", label: "04. 三幕十五节拍卡点规划时间轴", stageKey: "beat" },
    { id: "beat_explanation", label: "04b. 三幕十五节拍卡点说明", stageKey: "beat" },
    { id: "storylines", label: "05. 不同人物故事线", stageKey: "storylines" },
    { id: "storyline_details", label: "05b. 查看详细不同人物故事线", stageKey: "storylines" },
    { id: "storyline_decisions", label: "05c. 故事线处理", stageKey: "storylines" },
    { id: "guide", label: "06. 整体改编指引四项", stageKey: "guide" },
    { id: "package", label: "07. 最终策划包输出", stageKey: "package" },
  ];

  const STAGE_SEQUENCE = ["basic", "worldview", "character", "beat", "storylines", "guide", "package"];
  const BEAT_NAMES = [
    "开场",
    "主体呈现",
    "铺垫",
    "推动催化剂",
    "争执",
    "第二幕衔接点",
    "B故事线",
    "游戏及斗争",
    "中点",
    "危险逼近",
    "一败涂地",
    "灵魂黑夜",
    "第三幕衔接点",
    "结局",
    "终场画面",
  ];
  const STORYLINE_DECISIONS = [
    ["keep", "保留"],
    ["simplify", "精简"],
    ["delete", "删除"],
  ];
  const DEFAULT_PROMPT_TEMPLATES = [
    {
      id: "custom",
      name: "自定义偏好",
      prompt: "",
    },
    {
      id: "short_drama_hook",
      name: "短剧强钩子",
      prompt: "请优先强化短剧节奏：前 30 秒明确冲突和爽点，每集结尾保留强钩子，中点加入明显反转，人物情绪推进要直接、可拍、可视化。",
    },
    {
      id: "character_emotion",
      name: "人物情绪线",
      prompt: "请优先保证人物动机清晰，情绪转折有铺垫；每条人物线都要能对应关键节拍，避免只写事件不写人物选择。",
    },
    {
      id: "adaptation_control",
      name: "改编约束优先",
      prompt: "请保留原作核心设定和主线关系，只调整节奏、结构和可视化表达；删除或合并支线前要说明理由，并避免破坏主角成长逻辑。",
    },
  ];
  const app = document.getElementById("frameworkPlannerApp");
  if (!app) {
    console.error("[framework_planner] root element #frameworkPlannerApp not found");
    return;
  }

  const initialState = {
    project_id: null,
    current_view: "basic",
    basic_config: {
      project_title: "",
      mode: "创作",
      source_text: "",
      source_title: "",
      target_format: "短剧",
      season_count: 1,
      episodes_per_season: 60,
      minutes_per_episode: 2,
      adaptation_direction: "请保持强钩子、强反转、强情绪推进，并优先服务后续正式剧本生成链路。",
      user_constraints: "",
      user_requirements: "",
    },
    source_brief: {},
    worldview_plan: {},
    character_plan: {},
    beat_checkpoint_timeline: [],
    checkpoint_explanation: {},
    character_storylines: [],
    storyline_decisions: [],
    adaptation_guide: {},
    user_edit_history: [],
    framework_plan_package: {},
    validation_report: {},
    framework_score_report: "",
    beat_revision_round: 0,
    display_texts: {},
    raw_stage_responses: {},
    prompt_preferences: {
      active_template_id: "custom",
      script_preference: "",
      stage_prompts: {
        basic: "",
        worldview: "",
        character: "",
        beat: "",
        storylines: "",
        guide: "",
        package: "",
      },
      basic_prompt_fields: {
        adaptation_direction: "",
        user_constraints: "",
        user_requirements: "",
      },
      templates: DEFAULT_PROMPT_TEMPLATES,
      source_context: {},
      updated_at: "",
    },
    asset_state: {
      asset_kind: "framework_planner",
      status: "draft",
      current_stage: "basic",
      confirmed_stages: [],
      locked_stages: ["worldview", "character", "beat", "storylines", "guide", "package"],
      stage_outputs: {
        beat_checkpoint_timeline_count: 0,
        checkpoint_explanation_count: 0,
        character_storylines_count: 0,
      },
      last_action: "init",
      updated_at: "",
    },
    feedback: {
      worldview: "",
      character: "",
      beat: "",
      storylines: "",
      guide: "",
      package: "",
    },
    editors: {
      worldview_plan: "",
      character_plan: "",
      beat_checkpoint_timeline: "",
      checkpoint_explanation: "",
      adaptation_guide: "",
    },
    stage_state: {
      basic: { status: "editing", confirmed: false, locked: false },
      worldview: { status: "locked", confirmed: false, locked: true },
      character: { status: "locked", confirmed: false, locked: true },
      beat: { status: "locked", confirmed: false, locked: true },
      storylines: { status: "locked", confirmed: false, locked: true },
      guide: { status: "locked", confirmed: false, locked: true },
      package: { status: "locked", confirmed: false, locked: true },
    },
  };

  const ui = {
    toast: "",
    loading: {},
    stageErrors: {},
    modalStorylineId: null,
    expandedBeats: {},
    expandedStorylines: {},
    expandedBusinessPanels: {},
    expandedRawTree: {},
    rawTreeAllOpen: false,
    rawTreeAllCollapsed: false,
    dirty: false,
    suppressBeforeUnload: false,
    unsavedPrompt: null,
    lastStagePayloadPreview: {},
    stageHistory: {},
    stageHistoryLoading: {},
    assetsOpen: false,
    showNewScriptModal: false,
    assets: [],
    assetsLoading: false,
    assetSearch: "",
    assetStatusFilter: "all",
    assetSort: "updated_desc",
    newScriptForm: {
      title: "",
      season_count: 1,
      episodes_per_season: 60,
      target_format: "短剧",
      style: "",
      description: "",
    },
    loadingStartedAt: {},
    loadingTicker: null,
    editMode: {
      worldview: false,
      character: false,
      beatTimeline: false,
      beatExplanation: false,
      guide: false,
    },
    knowledge: {
      open: readKnowledgePanelOpen(),
      loading: false,
      status: "",
      tags: [],
      selectedIds: [],
      tagPromptText: "",
      editingId: "",
      formOpen: false,
      form: emptyKnowledgeTagForm(),
    },
  };
  let state = loadState();

  const realApi = {
    async runStage(stage, payload) {
      const response = await fetch(`${API_BASE}/stage/${stage}`, {
        method: "POST",
        headers: buildHeaders(),
        body: JSON.stringify(payload || {}),
      });
      const data = await response.json().catch(() => ({
        ok: false,
        stage,
        error: `阶段 ${stage} 返回了无法解析的响应`,
      }));
      if (!response.ok || !data.ok) {
        throw toStageError(data, stage, response.status);
      }
      return data;
    },
    async runBeatScore(payload) {
      const response = await fetch(`${API_BASE}/stage/04/score`, {
        method: "POST",
        headers: buildHeaders(),
        body: JSON.stringify(payload || {}),
      });
      const data = await response.json().catch(() => ({
        ok: false,
        stage: "04",
        error: "评分接口返回了无法解析的响应",
      }));
      if (!response.ok || !data.ok) {
        throw toStageError(data, "04", response.status);
      }
      return data;
    },
    async startFrameworkScript(payload) {
      const response = await fetch(`${API_BASE}/generate-script`, {
        method: "POST",
        headers: buildHeaders(),
        body: JSON.stringify(payload || {}),
      });
      const rawText = await response.text();
      let data = {};
      try {
        data = rawText ? JSON.parse(rawText) : {};
      } catch (error) {
        const snippet = String(rawText || "").slice(0, 240).replace(/\s+/g, " ");
        throw new Error(`框架转剧本接口返回非 JSON 响应：status=${response.status} contentType=${response.headers.get("content-type") || ""} body=${snippet}`);
      }
      if (!response.ok || data.success === false || data.ok === false) {
        throw new Error(data.error || data.message || data.fallback || "框架转剧本任务创建失败");
      }
      return data;
    },
    async saveFrameworkAsset(payload) {
      const response = await fetch(`${API_BASE}/assets/save`, {
        method: "POST",
        headers: buildHeaders(),
        body: JSON.stringify(payload || {}),
      });
      const data = await response.json().catch(() => ({
        success: false,
        message: "保存接口返回了无法解析的响应",
      }));
      if (!response.ok || data.success === false || data.ok === false) {
        throw new Error(data.error || data.message || "当前框架保存失败");
      }
      return data;
    },
  };

  const mockApi = {
    async runStage(stage, payload) {
      return buildMockStageResponse(stage, payload || {});
    },
    async runBeatScore(payload) {
      return buildMockScoreResponse(payload || {});
    },
  };

  const planningApi = {
    async runStage(stage, payload) {
      try {
        return await realApi.runStage(stage, payload);
      } catch (error) {
        if (!config.backendReady) {
          return mockApi.runStage(stage, payload);
        }
        throw error;
      }
    },
    async runBeatScore(payload) {
      try {
        return await realApi.runBeatScore(payload);
      } catch (error) {
        if (!config.backendReady) {
          return mockApi.runBeatScore(payload);
        }
        throw error;
      }
    },
    async startFrameworkScript(payload) {
      return realApi.startFrameworkScript(payload);
    },
    async saveFrameworkAsset(payload) {
      return realApi.saveFrameworkAsset(payload);
    },
  };

  async function requestJson(url, options) {
    const response = await fetch(url, Object.assign({
      headers: buildHeaders(),
    }, options || {}));
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false || data.ok === false) {
      throw new Error(data.error || data.message || "请求失败，请稍后重试。");
    }
    return data;
  }

  function buildHeaders() {
    const headers = { "Content-Type": "application/json" };
    if (authToken) headers.Authorization = `Bearer ${authToken}`;
    return headers;
  }

  function currentProjectId() {
    const stateProjectId = state ? state.project_id : null;
    const stateNumeric = Number(stateProjectId || 0);
    if (stateNumeric > 0) return stateNumeric;
    const projectId = state && state.asset_state ? state.asset_state.project_id : null;
    const projectNumeric = Number(projectId || 0);
    if (projectNumeric > 0) return projectNumeric;
    const assetId = state && state.asset_state ? state.asset_state.asset_id : null;
    const numeric = Number(assetId || 0);
    return numeric > 0 ? numeric : "unsaved";
  }

  function hasSavedFrameworkProjectId() {
    const value = currentProjectId();
    if (value === null || value === undefined) return false;
    const text = String(value || "").trim().toLowerCase();
    if (!text || ["unsaved", "draft", "null", "undefined"].includes(text)) return false;
    return Number(value) > 0;
  }

  function currentProjectCacheName() {
    const configState = state && state.basic_config ? state.basic_config : {};
    const rawName = String(configState.project_title || configState.source_title || "未命名项目").trim() || "未命名项目";
    return safeProjectCacheName(rawName);
  }

  function safeProjectCacheName(value) {
    const text = String(value || "").trim()
      .replace(/[<>:"/\\|?*\x00-\x1f]+/g, "_")
      .replace(/\s+/g, "_")
      .replace(/^[._\s]+|[._\s]+$/g, "")
      .slice(0, 80);
    return text || "未命名项目";
  }

  function toStageError(data, fallbackStage, status) {
    const error = new Error(data && data.error ? data.error : `阶段 ${fallbackStage} 执行失败`);
    error.stage = (data && data.stage) || fallbackStage;
    error.status = status || 500;
    error.detail = (data && data.detail) || {};
    error.reason = error.detail && typeof error.detail.reason === "string"
      ? error.detail.reason.trim()
      : "";
    error.lastExceptionMessage = error.detail && typeof error.detail.last_exception_message === "string"
      ? error.detail.last_exception_message.trim()
      : "";
    return error;
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function extractBusinessField(value, fieldName) {
    if (value === null || value === undefined || value === "") return value;
    if (typeof value === "string") {
      const text = value.trim();
      if (!text) return value;
      try {
        return extractBusinessField(JSON.parse(text), fieldName);
      } catch (error) {
        return value;
      }
    }
    if (Array.isArray(value)) return value;
    if (typeof value !== "object") return value;
    if (value[fieldName] !== undefined && value[fieldName] !== null) return value[fieldName];
    if (value.data && typeof value.data === "object" && value.data[fieldName] !== undefined && value.data[fieldName] !== null) {
      return value.data[fieldName];
    }
    for (const containerName of ["newVariables", "variables"]) {
      const container = value[containerName];
      if (container && typeof container === "object" && !Array.isArray(container) && container[fieldName] !== undefined && container[fieldName] !== null) {
        return extractBusinessField(container[fieldName], fieldName);
      }
      if (Array.isArray(container)) {
        for (const item of container) {
          if (!item || typeof item !== "object") continue;
          const variable = Array.isArray(item.variable) ? item.variable[item.variable.length - 1] : (item.variable || item.key || item.name);
          if (String(variable || "").trim() === fieldName) {
            return extractBusinessField(item.value, fieldName);
          }
        }
      }
    }
    const responseData = Array.isArray(value.responseData)
      ? value.responseData
      : value.responseData && typeof value.responseData === "object"
        ? [value.responseData]
        : [];
    for (let index = responseData.length - 1; index >= 0; index -= 1) {
      const node = responseData[index];
      if (!node || typeof node !== "object") continue;
      for (const key of ["answerText", "responseText", "text", "content"]) {
        const raw = node[key] || (node.outputs && node.outputs[key]) || (node.answerNode && node.answerNode[key]);
        if (!raw || typeof raw !== "string") continue;
        try {
          const parsed = JSON.parse(raw);
          if (parsed && typeof parsed === "object" && parsed[fieldName] !== undefined && parsed[fieldName] !== null) {
            return parsed[fieldName];
          }
          if (parsed && parsed.data && typeof parsed.data === "object" && parsed.data[fieldName] !== undefined && parsed.data[fieldName] !== null) {
            return parsed.data[fieldName];
          }
        } catch (error) {
          // Ignore non-JSON answer text.
        }
      }
    }
    for (const key of ["answerText", "responseText", "text", "content"]) {
      if (!value[key] || typeof value[key] !== "string") continue;
      try {
        const parsed = JSON.parse(value[key]);
        if (parsed && typeof parsed === "object" && parsed[fieldName] !== undefined && parsed[fieldName] !== null) {
          return parsed[fieldName];
        }
      } catch (error) {
        // Ignore non-JSON text.
      }
    }
    return value;
  }

  function hasRawResponseKeys(value, depth = 0) {
    if (depth > 4 || value === null || value === undefined) return false;
    if (typeof value === "string") return RAW_RESPONSE_KEYS.some((key) => value.includes(key));
    if (Array.isArray(value)) return value.slice(0, 8).some((item) => hasRawResponseKeys(item, depth + 1));
    if (typeof value === "object") {
      return Object.keys(value).some((key) => RAW_RESPONSE_KEYS.includes(key) || hasRawResponseKeys(value[key], depth + 1));
    }
    return false;
  }

  function fieldSummary(value) {
    if (Array.isArray(value)) {
      return { type: "array", isArray: true, length: value.length, firstItemType: value.length ? typeof value[0] : "" };
    }
    if (value && typeof value === "object") {
      return { type: "object", keys: Object.keys(value).slice(0, 20), polluted: hasRawResponseKeys(value) };
    }
    if (typeof value === "string") {
      return { type: "string", length: value.length, polluted: hasRawResponseKeys(value) };
    }
    return { type: typeof value, polluted: false };
  }

  function debugCleanSummary(label, before, after) {
    if (!DEV_LOG_ENABLED || typeof console === "undefined" || !console.debug) return;
    console.debug(`[framework_planner] ${label}`, {
      before: before || {},
      after: after || {},
    });
  }

  function debugStageSummary(label, detail) {
    if (!DEV_LOG_ENABLED || typeof console === "undefined") return;
    const payload = detail || {};
    if (console.info) {
      console.info(`[framework_planner_debug] ${label}`, payload);
    } else if (console.debug) {
      console.debug(`[framework_planner_debug] ${label}`, payload);
    }
  }

  function debugFrontendEvent(event, payload, detail) {
    const safePayload = payload && typeof payload === "object" ? payload : {};
    const safeDetail = detail && typeof detail === "object" ? detail : {};
    debugStageSummary(event, {
      project_id: currentProjectId(),
      project_cache_name: currentProjectCacheName(),
      payload_keys: Object.keys(safePayload),
      payload_summary: payloadSummary(safePayload),
      detail: safeDetail,
    });
    fetch(`${API_BASE}/debug/frontend`, {
      method: "POST",
      headers: buildHeaders(),
      body: JSON.stringify({
        project_id: currentProjectId(),
        event,
        payload: safePayload,
        detail: safeDetail,
      }),
    }).catch((error) => {
      if (DEV_LOG_ENABLED && typeof console !== "undefined" && console.warn) {
        console.warn("[framework_planner_debug] frontend debug write failed", error);
      }
    });
  }

  function defaultBusinessValue(field) {
    return ARRAY_BUSINESS_FIELDS.has(field) ? [] : {};
  }

  function cleanBusinessFieldValue(value, field) {
    const extracted = extractBusinessField(value, field);
    if (!hasRawResponseKeys(extracted)) return extracted;
    return defaultBusinessValue(field);
  }

  function stripRawResponseKeys(value, depth = 0) {
    if (depth > 12 || value === null || value === undefined) return value;
    if (Array.isArray(value)) {
      return value.map((item) => stripRawResponseKeys(item, depth + 1));
    }
    if (typeof value !== "object") return value;
    const result = {};
    Object.keys(value).forEach((key) => {
      if (RAW_RESPONSE_KEYS.includes(key)) return;
      result[key] = stripRawResponseKeys(value[key], depth + 1);
    });
    return result;
  }

  function businessFieldSummary(source) {
    const summary = {};
    BUSINESS_FIELD_KEYS.forEach((field) => {
      summary[field] = fieldSummary(source ? source[field] : undefined);
    });
    return summary;
  }

  function cleanBusinessPayloadFields(payload, label, fields) {
    const beforeSummary = businessFieldSummary(payload);
    (fields || BUSINESS_FIELD_KEYS).forEach((field) => {
      if (!(field in payload)) return;
      payload[field] = cleanBusinessFieldValue(payload[field], field);
    });
    debugCleanSummary(`${label} business fields cleaned`, beforeSummary, businessFieldSummary(payload));
    return payload;
  }

  function cleanOutgoingPayload(payload, label) {
    const stripped = stripRawResponseKeys(payload || {});
    return cleanBusinessPayloadFields(stripped, label || "outgoing payload");
  }

  function cleanStage05Payload(payload) {
    debugCleanSummary("stage05 payload diagnostic", businessFieldSummary(payload), null);
    payload.basic_config = compactStage05BasicConfig(payload.basic_config);
    return cleanBusinessPayloadFields(payload, "stage05 payload", [
      "source_brief",
      "worldview_plan",
      "character_plan",
      "beat_checkpoint_timeline",
    ]);
  }

  function compactStage05BasicConfig(value) {
    const source = value && typeof value === "object" && !Array.isArray(value)
      ? value
      : {};
    const allowed = [
      "project_title",
      "source_title",
      "mode",
      "target_format",
      "season_count",
      "episodes_per_season",
      "minutes_per_episode",
      "adaptation_direction",
      "user_constraints",
      "user_requirements",
    ];
    const result = {};
    allowed.forEach((key) => {
      const item = source[key];
      if (item === undefined || item === null || item === "") return;
      result[key] = typeof item === "string" && ["adaptation_direction", "user_constraints", "user_requirements"].includes(key)
        ? item.slice(0, 1200)
        : item;
    });
    if (!result.source_title && result.project_title) result.source_title = result.project_title;
    if (!result.project_title && result.source_title) result.project_title = result.source_title;
    return result;
  }

  function cleanSavedBusinessFields(targetState) {
    const beforeSummary = businessFieldSummary(targetState);
    BUSINESS_FIELD_KEYS.forEach((field) => {
      const before = targetState[field];
      if (!hasRawResponseKeys(before)) return;
      targetState[field] = cleanBusinessFieldValue(before, field);
      if (hasRawResponseKeys(targetState[field])) {
        targetState[field] = defaultBusinessValue(field);
        const stageKey = stageKeyForBusinessField(field);
        if (targetState.stage_state && targetState.stage_state[stageKey]) {
          targetState.stage_state[stageKey].status = "error";
        }
      }
    });
    debugCleanSummary("localStorage business fields cleaned", beforeSummary, businessFieldSummary(targetState));
    return targetState;
  }

  function stageKeyForBusinessField(field) {
    return {
      source_brief: "basic",
      worldview_plan: "worldview",
      character_plan: "character",
      beat_checkpoint_timeline: "beat",
      checkpoint_explanation: "beat",
      character_storylines: "storylines",
    }[field] || "basic";
  }

  function loadState() {
    const params = new URLSearchParams(window.location.search || "");
    if (params.get("new") === "1" || params.get("new_framework") === "1") {
      storageRemove(STORAGE_KEY);
      storageRemove(LEGACY_STORAGE_KEY);
      const fresh = normalizeState(null);
      persistLoadedState(fresh);
      return fresh;
    }
    const saved = readStorage(STORAGE_KEY) || readStorage(LEGACY_STORAGE_KEY);
    const normalized = normalizeState(sanitizeLoadedState(saved));
    persistLoadedState(normalized);
    return normalized;
  }

  function readStorage(key) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function persistLoadedState(nextState) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextState));
      window.localStorage.removeItem(LEGACY_STORAGE_KEY);
    } catch (error) {
      // ignore storage write errors
    }
  }

  function storageRemove(key) {
    try {
      window.localStorage.removeItem(key);
    } catch (error) {
      // ignore storage write errors
    }
  }

  function sanitizeLoadedState(saved) {
    if (!saved || typeof saved !== "object") return saved;
    const sanitized = stripRawResponseKeys(saved);
    BUSINESS_FIELD_KEYS.forEach((field) => {
      if (saved[field] !== undefined) {
        sanitized[field] = cleanBusinessFieldValue(saved[field], field);
      }
    });
    sanitized.raw_stage_responses = {};
    debugCleanSummary("localStorage root sanitized", fieldSummary(saved), fieldSummary(sanitized));
    debugCleanSummary("localStorage retained business fields", businessFieldSummary(saved), businessFieldSummary(sanitized));
    return sanitized;
  }

  function normalizeState(saved) {
    const next = clone(initialState);
    const storedPreferences = loadPromptPreferences();
    if (!saved || typeof saved !== "object") {
      next.prompt_preferences = normalizePromptPreferences(storedPreferences);
      applyPromptPreferencesToBasicConfig(next, true);
      return syncStageFlow(next);
    }
    mergeInto(next, saved);
    next.basic_config = Object.assign(clone(initialState.basic_config), saved.basic_config || {});
    next.feedback = Object.assign(clone(initialState.feedback), saved.feedback || {});
    next.editors = Object.assign(
      clone(initialState.editors),
      saved.editors && typeof saved.editors === "object" && !Array.isArray(saved.editors) ? saved.editors : {}
    );
    next.stage_state = Object.assign(
      clone(initialState.stage_state),
      saved.stage_state && typeof saved.stage_state === "object" && !Array.isArray(saved.stage_state) ? saved.stage_state : {}
    );
    next.asset_state = Object.assign(
      clone(initialState.asset_state),
      saved.asset_state && typeof saved.asset_state === "object" && !Array.isArray(saved.asset_state) ? saved.asset_state : {}
    );
    const savedProjectId = Number(saved.project_id || next.asset_state.project_id || next.asset_state.asset_id || 0);
    next.project_id = savedProjectId > 0 ? savedProjectId : null;
    if (next.project_id) {
      next.asset_state.project_id = next.project_id;
      next.asset_state.asset_id = next.project_id;
    }
    next.prompt_preferences = normalizePromptPreferences(Object.assign({}, storedPreferences || {}, saved.prompt_preferences || {}));
    next.source_brief = next.source_brief && typeof next.source_brief === "object" && !Array.isArray(next.source_brief) ? next.source_brief : {};
    next.worldview_plan = next.worldview_plan && typeof next.worldview_plan === "object" && !Array.isArray(next.worldview_plan) ? next.worldview_plan : {};
    next.character_plan = next.character_plan && typeof next.character_plan === "object" && !Array.isArray(next.character_plan) ? next.character_plan : {};
    next.beat_checkpoint_timeline = Array.isArray(next.beat_checkpoint_timeline) ? next.beat_checkpoint_timeline : [];
    next.checkpoint_explanation = next.checkpoint_explanation && typeof next.checkpoint_explanation === "object" && !Array.isArray(next.checkpoint_explanation) ? next.checkpoint_explanation : {};
    next.character_storylines = Array.isArray(next.character_storylines) ? next.character_storylines : [];
    next.storyline_decisions = Array.isArray(next.storyline_decisions) ? next.storyline_decisions : [];
    STAGE_SEQUENCE.forEach((stageKey) => {
      next.stage_state[stageKey] = Object.assign(clone(initialState.stage_state[stageKey]), next.stage_state[stageKey] || {});
    });
    cleanSavedBusinessFields(next);
    return syncStageFlow(next);
  }

  function loadPromptPreferences() {
    return readStorage(PREFERENCE_STORAGE_KEY);
  }

  function normalizePromptPreferences(value) {
    const source = value && typeof value === "object" ? value : {};
    const defaults = clone(initialState.prompt_preferences);
    const next = Object.assign(defaults, source);
    next.stage_prompts = Object.assign(clone(initialState.prompt_preferences.stage_prompts), source.stage_prompts || {});
    next.basic_prompt_fields = Object.assign(clone(initialState.prompt_preferences.basic_prompt_fields), source.basic_prompt_fields || {});
    const customTemplates = Array.isArray(source.templates) ? source.templates : [];
    const templatesById = new Map();
    DEFAULT_PROMPT_TEMPLATES.concat(customTemplates).forEach((item) => {
      if (item && item.id) templatesById.set(String(item.id), {
        id: String(item.id),
        name: String(item.name || item.id),
        prompt: String(item.prompt || ""),
      });
    });
    next.templates = Array.from(templatesById.values());
    if (!next.templates.some((item) => item.id === next.active_template_id)) {
      next.active_template_id = "custom";
    }
    next.script_preference = String(next.script_preference || "");
    next.source_context = source.source_context && typeof source.source_context === "object" ? source.source_context : {};
    next.updated_at = String(next.updated_at || "");
    return next;
  }

  function applyPromptPreferencesToBasicConfig(targetState, fillExisting) {
    const fields = (targetState.prompt_preferences || {}).basic_prompt_fields || {};
    ["adaptation_direction", "user_constraints", "user_requirements"].forEach((key) => {
      const value = String(fields[key] || "").trim();
      if (!value) return;
      if (fillExisting || !String(targetState.basic_config[key] || "").trim()) {
        targetState.basic_config[key] = value;
      }
    });
  }

  function mergeInto(target, source) {
    Object.keys(source || {}).forEach((key) => {
      const sourceValue = source[key];
      if (Array.isArray(sourceValue)) {
        target[key] = clone(sourceValue);
        return;
      }
      if (sourceValue && typeof sourceValue === "object") {
        if (!target[key] || typeof target[key] !== "object" || Array.isArray(target[key])) {
          target[key] = {};
        }
        mergeInto(target[key], sourceValue);
        return;
      }
      target[key] = sourceValue;
    });
  }

  function saveState() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (error) {
      // ignore storage write errors
    }
  }

  function markDirty() {
    ui.dirty = true;
  }

  function clearDirty() {
    ui.dirty = false;
  }

  function hasUnsavedChanges() {
    return Boolean(ui.dirty);
  }

  function confirmDiscardUnsaved() {
    if (!hasUnsavedChanges()) return true;
    return window.confirm(UNSAVED_MESSAGE);
  }

  function promptUnsaved(label, handlers) {
    if (!hasUnsavedChanges()) {
      if (handlers && typeof handlers.discard === "function") handlers.discard();
      return false;
    }
    ui.unsavedPrompt = {
      label,
      save: handlers && handlers.save,
      discard: handlers && handlers.discard,
    };
    render();
    return true;
  }

  async function runUnsavedPrompt(choice) {
    const prompt = ui.unsavedPrompt;
    ui.unsavedPrompt = null;
    if (!prompt) {
      render();
      return;
    }
    if (choice === "cancel") {
      render();
      return;
    }
    if (choice === "discard") {
      clearDirty();
      if (typeof prompt.discard === "function") await prompt.discard();
      else render();
      return;
    }
    if (choice === "save") {
      try {
        await saveFrameworkAsset({ silent: true });
        clearDirty();
        if (typeof prompt.save === "function") await prompt.save();
        else if (typeof prompt.discard === "function") await prompt.discard();
        else render();
      } catch (error) {
        showToast((error && error.message) || "保存失败，已取消操作");
        render();
      }
    }
  }

  async function saveAndLeave(targetUrl) {
    try {
      await saveFrameworkAsset({ silent: true });
      clearDirty();
      ui.suppressBeforeUnload = true;
      window.location.href = targetUrl;
    } catch (error) {
      showToast((error && error.message) || "保存失败，已取消跳转");
    }
  }

  function selectorValue(value) {
    const text = String(value || "");
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(text);
    return text.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  }

  function focusSelectorFor(element) {
    if (!element || !element.matches) return "";
    const attributeSelectors = [
      "data-config-key",
      "data-script-preference",
      "data-stage-preference-key",
      "data-new-script-field",
      "data-asset-search",
      "data-feedback-key",
      "data-editor-key",
      "data-modal-field",
      "data-beat-index",
      "data-checkpoint-overview",
      "data-beat-note-index",
    ];
    for (const name of attributeSelectors) {
      if (element.hasAttribute(name)) {
        return `[${name}="${selectorValue(element.getAttribute(name))}"]`;
      }
    }
    if (element.hasAttribute("data-business-root") && element.hasAttribute("data-business-path")) {
      return `[data-business-root="${selectorValue(element.getAttribute("data-business-root"))}"][data-business-path="${selectorValue(element.getAttribute("data-business-path"))}"]`;
    }
    if (element.hasAttribute("data-beat-index") && element.hasAttribute("data-beat-field")) {
      return `[data-beat-index="${selectorValue(element.getAttribute("data-beat-index"))}"][data-beat-field="${selectorValue(element.getAttribute("data-beat-field"))}"]`;
    }
    return "";
  }

  function captureFocusedControl() {
    const active = document.activeElement;
    if (!active || !app.contains(active) || !active.matches || !active.matches("input, textarea, select")) return null;
    const selector = focusSelectorFor(active);
    if (!selector) return null;
    return {
      selector,
      value: "value" in active ? active.value : "",
      selectionStart: typeof active.selectionStart === "number" ? active.selectionStart : null,
      selectionEnd: typeof active.selectionEnd === "number" ? active.selectionEnd : null,
    };
  }

  function restoreFocusedControl(snapshot) {
    if (!snapshot || !snapshot.selector) return;
    const target = app.querySelector(snapshot.selector);
    if (!target || !target.focus) return;
    if ("value" in target && document.activeElement !== target && target.value !== snapshot.value) {
      target.value = snapshot.value;
    }
    target.focus({ preventScroll: true });
    if (
      snapshot.selectionStart !== null &&
      snapshot.selectionEnd !== null &&
      typeof target.setSelectionRange === "function"
    ) {
      try {
        target.setSelectionRange(snapshot.selectionStart, snapshot.selectionEnd);
      } catch (error) {
        // Some input types do not support selection ranges.
      }
    }
  }

  function savePromptPreferences(reason) {
    if (!state.prompt_preferences) return;
    state.prompt_preferences.updated_at = new Date().toISOString();
    state.prompt_preferences.basic_prompt_fields = {
      adaptation_direction: state.basic_config.adaptation_direction || "",
      user_constraints: state.basic_config.user_constraints || "",
      user_requirements: state.basic_config.user_requirements || "",
    };
    state.prompt_preferences.source_context = {
      project_title: state.basic_config.project_title || "",
      source_title: state.basic_config.source_title || "",
      target_format: state.basic_config.target_format || "",
      source_hash: simpleHash(state.basic_config.source_text || ""),
      reason: reason || "update",
    };
    try {
      window.localStorage.setItem(PREFERENCE_STORAGE_KEY, JSON.stringify(state.prompt_preferences));
    } catch (error) {
      // ignore storage write errors
    }
    syncPromptPreferencesRemote(reason);
  }

  let preferenceSyncTimer = null;

  function syncPromptPreferencesRemote(reason) {
    window.clearTimeout(preferenceSyncTimer);
    preferenceSyncTimer = window.setTimeout(() => {
      requestJson("/api/user-knowledge/preferences", {
        method: "PUT",
        body: JSON.stringify({
          user_preference_prompt: String((state.prompt_preferences || {}).script_preference || ""),
          selected_preference_tag_ids: (ui.knowledge.selectedIds || []).map(String),
          stage_prompts: normalizeStagePrompts((state.prompt_preferences || {}).stage_prompts || {}),
          reason: reason || "update",
        }),
      }).catch((error) => {
        if (DEV_LOG_ENABLED && typeof console !== "undefined" && console.warn) {
          console.warn("[framework_planner] preference sync failed", error);
        }
      });
    }, 400);
  }

  function simpleHash(value) {
    const text = String(value || "");
    let hash = 0;
    for (let index = 0; index < text.length; index += 1) {
      hash = ((hash << 5) - hash + text.charCodeAt(index)) | 0;
    }
    return String(hash);
  }

  function showToast(message) {
    ui.toast = message;
    render();
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
      ui.toast = "";
      render();
    }, 2400);
  }

  function recordHistory(action, detail) {
    state.user_edit_history.push({
      at: new Date().toISOString(),
      action,
      detail: detail || {},
    });
    if (state.user_edit_history.length > 200) {
      state.user_edit_history = state.user_edit_history.slice(-200);
    }
  }

  function viewDef(viewId) {
    return VIEW_DEFS.find((item) => item.id === viewId) || VIEW_DEFS[0];
  }

  function stageKeyForView(viewId) {
    return viewDef(viewId).stageKey;
  }

  function stageNoForKey(stageKey) {
    return {
      basic: "01",
      worldview: "02",
      character: "03",
      beat: "04",
      storylines: "05",
      guide: "06",
      package: "07",
    }[stageKey] || "";
  }

  function stageBlockedByUpstream(stage) {
    return Boolean(stage && stage.locked && !stage.confirmed);
  }

  function prerequisiteStageKey(stageKey) {
    const index = STAGE_SEQUENCE.indexOf(stageKey);
    return index > 0 ? STAGE_SEQUENCE[index - 1] : "";
  }

  function prerequisiteConfirmedFor(targetState, stageKey) {
    if (stageKey === "basic") return true;
    const prerequisite = prerequisiteStageKey(stageKey);
    if (!prerequisite) return true;
    const stageState = targetState && targetState.stage_state ? targetState.stage_state : {};
    return Boolean((stageState[prerequisite] || {}).confirmed);
  }

  function viewUnlockedFor(targetState, viewId) {
    const stageState = targetState && targetState.stage_state ? targetState.stage_state : {};
    const stageKey = stageKeyForView(viewId);
    if (stageKey === "basic") return true;
    if (!prerequisiteConfirmedFor(targetState, stageKey)) return false;
    if ((stageState[stageKey] || {}).confirmed) return true;
    return prerequisiteConfirmedFor(targetState, stageKey);
  }

  function viewUnlocked(viewId) {
    return viewUnlockedFor(state, viewId);
  }

  function setCurrentView(viewId) {
    if (!viewUnlocked(viewId)) {
      showToast("请先确认上游阶段");
      return;
    }
    state.current_view = viewId;
    render();
    loadStageHistory(stageKeyForView(viewId)).catch(() => {});
  }

  function setStageLoading(stageKey, loading) {
    ui.loading[stageKey] = Boolean(loading);
    if (loading) {
      ui.loadingStartedAt[stageKey] = Date.now();
      startLoadingTicker();
    } else {
      delete ui.loadingStartedAt[stageKey];
      stopLoadingTickerIfIdle();
    }
  }

  function isStageLoading(stageKey) {
    return Boolean(ui.loading[stageKey]);
  }

  function runningStageKey() {
    return STAGE_SEQUENCE.find((stageKey) => isStageLoading(stageKey) || (state.stage_state[stageKey] || {}).status === "running") || "";
  }

  function canStartFrameworkScript() {
    return !isEmptyValue(state.framework_plan_package)
      && !runningStageKey()
      && !ui.loading.framework_script;
  }

  function renderFrameworkScriptButton(sizeClass) {
    const className = sizeClass ? ` ${sizeClass}` : "";
    const disabled = canStartFrameworkScript() ? "" : "disabled";
    const label = ui.loading.framework_script ? "正在保存并进入剧本正文阶段..." : "保存框架并进入剧本正文阶段";
    return `<button class="fp-btn${className} primary" data-action="start-framework-script" ${disabled}>${label}</button>`;
  }

  function renderSaveFrameworkButton(sizeClass) {
    const className = sizeClass ? ` ${sizeClass}` : "";
    const disabled = runningStageKey() || ui.loading.framework_save || ui.loading.framework_script ? "disabled" : "";
    const label = ui.loading.framework_save ? "正在保存..." : "保存框架";
    return `<button class="fp-btn${className}" data-action="save-framework-asset" ${disabled}>${label}</button>`;
  }

  function processingElapsedLabel(stageKey) {
    const startedAt = ui.loadingStartedAt[stageKey];
    if (!startedAt) return "刚刚开始";
    const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    if (seconds < 60) return `${seconds} 秒`;
    return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
  }

  function waitForPaint() {
    return new Promise((resolve) => {
      window.requestAnimationFrame(() => window.setTimeout(resolve, 0));
    });
  }

  function startLoadingTicker() {
    if (ui.loadingTicker) return;
    ui.loadingTicker = window.setInterval(() => {
      if (runningStageKey()) {
        render();
      } else {
        stopLoadingTickerIfIdle();
      }
    }, 5000);
  }

  function stopLoadingTickerIfIdle() {
    if (runningStageKey() || !ui.loadingTicker) return;
    window.clearInterval(ui.loadingTicker);
    ui.loadingTicker = null;
  }

  function stageStatusTag(stageKey) {
    const stage = state.stage_state[stageKey];
    if (!stage) return `<span class="fp-tag">未知</span>`;
    if (isStageLoading(stageKey) || stage.status === "running") return `<span class="fp-tag blue fp-processing-dot">处理中</span>`;
    if (stage.confirmed) return `<span class="fp-tag ok">已确认并锁定</span>`;
    if (stage.locked) return `<span class="fp-tag lock">待上游确认</span>`;
    if (stage.status === "generated") return `<span class="fp-tag blue">已生成，待确认</span>`;
    if (stage.status === "updated") return `<span class="fp-tag warn">已更新，待确认</span>`;
    if (stage.status === "error") return `<span class="fp-tag red">执行异常</span>`;
    if (stageKey === "basic") return `<span class="fp-tag blue">可编辑</span>`;
    return `<span class="fp-tag">待生成</span>`;
  }

  function unlockStage(stageKey) {
    if (!state.stage_state[stageKey]) return;
    state.stage_state[stageKey].locked = false;
    if (state.stage_state[stageKey].status === "locked") {
      state.stage_state[stageKey].status = "idle";
    }
  }

  function clearStageData(stageKey) {
    if (stageKey === "worldview") state.worldview_plan = {};
    if (stageKey === "character") state.character_plan = {};
    if (stageKey === "beat") {
      state.beat_checkpoint_timeline = [];
      state.checkpoint_explanation = {};
      state.framework_score_report = "";
      state.beat_revision_round = 0;
      ui.expandedBeats = {};
    }
    if (stageKey === "storylines") {
      state.character_storylines = [];
      state.storyline_decisions = [];
      ui.modalStorylineId = null;
      ui.expandedStorylines = {};
    }
    if (stageKey === "guide") state.adaptation_guide = {};
    if (stageKey === "package") {
      state.framework_plan_package = {};
      state.validation_report = {};
    }
    if (stageKey === "basic") {
      state.source_brief = {};
    }
  }

  function hasStageDataFor(targetState, stageKey) {
    if (stageKey === "basic") return true;
    if (stageKey === "worldview") return !isEmptyValue(targetState.worldview_plan);
    if (stageKey === "character") return !isEmptyValue(targetState.character_plan);
    if (stageKey === "beat") {
      return Array.isArray(targetState.beat_checkpoint_timeline) && targetState.beat_checkpoint_timeline.length > 0;
    }
    if (stageKey === "storylines") {
      return Array.isArray(targetState.character_storylines) && targetState.character_storylines.length > 0;
    }
    if (stageKey === "guide") return !isEmptyValue(targetState.adaptation_guide);
    if (stageKey === "package") return !isEmptyValue(targetState.framework_plan_package);
    return false;
  }

  function hasStageData(stageKey) {
    return hasStageDataFor(state, stageKey);
  }

  function downstreamStages(stageKey) {
    const index = STAGE_SEQUENCE.indexOf(stageKey);
    return index === -1 ? [] : STAGE_SEQUENCE.slice(index + 1);
  }

  function firstViewForStage(stageKey) {
    const item = VIEW_DEFS.find((view) => view.stageKey === stageKey);
    return item ? item.id : "basic";
  }

  function realStageDisplayTitle(stageKey) {
    return {
      basic: "01 原文信息提取 / 基础配置",
      worldview: "02 世界观方案",
      character: "03 人设方案",
      beat: "04 三幕十五节拍阶段",
      storylines: "05 人物故事线阶段",
      guide: "06 整体改编指引",
      package: "07 最终策划包输出",
    }[stageKey] || stageDisplayTitle(stageKey);
  }

  function upstreamStageKey(stageKey) {
    const index = STAGE_SEQUENCE.indexOf(stageKey);
    return index > 0 ? STAGE_SEQUENCE[index - 1] : "";
  }

  function stageDisplayTitle(stageKey) {
    return viewDef(firstViewForStage(stageKey)).label.replace(/^\d+[a-z]?\.\s*/i, "");
  }

  function sharedStageHint(stageKey) {
    if (stageKey === "beat") {
      return "04 阶段包含“时间轴”和“卡点说明”两个子视图。";
    }
    if (stageKey === "storylines") {
      return "05 阶段包含“故事线总览”“故事线详情”“故事线处理”三个子视图。";
    }
    return "";
  }

  function renderUpstreamRollbackButton(stageKey) {
    const upstream = upstreamStageKey(stageKey);
    if (!upstream) return "";
    if (!hasStageData(upstream)) return "";
    return `<button class="fp-btn danger subtle" data-action="rollback-stage" data-stage-key="${upstream}">回退 ${escapeHtml(realStageDisplayTitle(upstream))}</button>`;
  }

  function firstAccessibleView(targetState) {
    return (VIEW_DEFS.find((item) => viewUnlockedFor(targetState, item.id)) || VIEW_DEFS[0]).id;
  }

  function reconcileStageState(targetState) {
    if (!targetState || typeof targetState !== "object") return targetState;
    targetState.stage_state = targetState.stage_state || clone(initialState.stage_state);

    STAGE_SEQUENCE.forEach((stageKey) => {
      targetState.stage_state[stageKey] = Object.assign(
        clone(initialState.stage_state[stageKey]),
        targetState.stage_state[stageKey] || {}
      );
    });

    STAGE_SEQUENCE.forEach((stageKey) => {
      const stage = targetState.stage_state[stageKey];
      const unlocked = viewUnlockedFor(targetState, firstViewForStage(stageKey));

      if (stageKey === "basic") {
        stage.locked = Boolean(stage.confirmed);
        if (stage.confirmed) {
          stage.status = "confirmed";
        } else if (stage.status !== "running" && stage.status !== "error") {
          stage.status = "editing";
        }
        return;
      }

      if (!prerequisiteConfirmedFor(targetState, stageKey)) {
        stage.confirmed = false;
        stage.locked = true;
        stage.status = "locked";
        return;
      }

      if (stage.confirmed) {
        stage.locked = true;
        stage.status = "confirmed";
        return;
      }

      if (!unlocked) {
        stage.confirmed = false;
        stage.locked = true;
        stage.status = "locked";
        return;
      }

      stage.locked = false;

      if (stage.status === "running" || stage.status === "error") {
        return;
      }

      stage.status = hasStageDataFor(targetState, stageKey)
        ? (stage.status === "updated" ? "updated" : "generated")
        : "idle";
    });

    if (!VIEW_DEFS.some((item) => item.id === targetState.current_view)) {
      targetState.current_view = "basic";
    }
    if (!viewUnlockedFor(targetState, targetState.current_view)) {
      targetState.current_view = firstAccessibleView(targetState);
    }

    return targetState;
  }

  function syncStageFlow(targetState) {
    syncStorylineDecisions(targetState);
    syncStorylineExpansionState(targetState);
    const reconciled = reconcileStageState(targetState);
    syncFrameworkAssetState(reconciled, "sync");
    return reconciled;
  }

  function syncStorylineExpansionState(targetState) {
    if (!targetState || !Array.isArray(targetState.character_storylines)) {
      ui.expandedStorylines = {};
      return;
    }
    const validIds = new Set(
      targetState.character_storylines
        .map((item) => String((item && (item.id || item.title)) || "").trim())
        .filter(Boolean)
    );
    Object.keys(ui.expandedStorylines).forEach((id) => {
      if (!validIds.has(id)) delete ui.expandedStorylines[id];
    });
  }

  function syncFrameworkAssetState(targetState, action) {
    if (!targetState || typeof targetState !== "object") return targetState;
    const stageState = targetState.stage_state || {};
    const currentStage = stageKeyForView(targetState.current_view || "basic");
    const confirmedStages = STAGE_SEQUENCE.filter((stageKey) => Boolean((stageState[stageKey] || {}).confirmed));
    const lockedStages = STAGE_SEQUENCE.filter((stageKey) => Boolean((stageState[stageKey] || {}).locked));
    const runningStage = STAGE_SEQUENCE.find((stageKey) => (stageState[stageKey] || {}).status === "running");
    const hasFinalPackage = !isEmptyValue(targetState.framework_plan_package);
    const status = runningStage
      ? "running"
      : hasFinalPackage && Boolean((stageState.package || {}).confirmed)
        ? "completed"
        : confirmedStages.length
          ? "in_progress"
          : "draft";
    targetState.asset_state = Object.assign(clone(initialState.asset_state), targetState.asset_state || {}, {
      asset_kind: "framework_planner",
      status,
      current_stage: runningStage || currentStage,
      confirmed_stages: confirmedStages,
      locked_stages: lockedStages,
      stage_outputs: {
        beat_checkpoint_timeline_count: Array.isArray(targetState.beat_checkpoint_timeline) ? targetState.beat_checkpoint_timeline.length : 0,
        checkpoint_explanation_count: checkpointExplanationCount(targetState.checkpoint_explanation),
        character_storylines_count: Array.isArray(targetState.character_storylines) ? targetState.character_storylines.length : 0,
      },
      last_action: action && action !== "sync" ? action : (targetState.asset_state || {}).last_action || "sync",
      updated_at: new Date().toISOString(),
    });
    return targetState;
  }

  function checkpointExplanationCount(explanation) {
    if (!explanation || typeof explanation !== "object" || Array.isArray(explanation)) return 0;
    return Array.isArray(explanation.beat_notes) ? explanation.beat_notes.length : 0;
  }

  function rollbackStage(stageKey) {
    const title = realStageDisplayTitle(stageKey);
    const hint = sharedStageHint(stageKey);
    const affected = downstreamStages(stageKey).map(realStageDisplayTitle).join("、") || "无后续阶段";
    const proceed = window.confirm(
      `确认回退 ${title} 吗？\n\n${hint ? `${hint}\n` : ""}这会清空整个当前真实阶段及后续阶段结果与确认状态，不只是当前子页。\n\n后续将清空：${affected}`
    );
    if (!proceed) return;

    if (stageKey === "basic") {
      state.stage_state.basic.confirmed = false;
      state.stage_state.basic.locked = false;
      state.stage_state.basic.status = "editing";
      state.source_brief = {};
    } else {
      state.stage_state[stageKey].confirmed = false;
      state.stage_state[stageKey].locked = false;
      state.stage_state[stageKey].status = hasStageData(stageKey) ? "updated" : "idle";
    }

    downstreamStages(stageKey).forEach((downstreamKey) => {
      clearStageData(downstreamKey);
      state.stage_state[downstreamKey].confirmed = false;
      state.stage_state[downstreamKey].locked = true;
      state.stage_state[downstreamKey].status = "locked";
    });

    if (stageKey !== "package") {
      state.stage_state.package.locked = true;
      state.stage_state.package.status = "locked";
      state.stage_state.package.confirmed = false;
      state.framework_plan_package = {};
      state.validation_report = {};
    }

    ui.editMode.worldview = false;
    ui.editMode.character = false;
    ui.editMode.beatTimeline = false;
    ui.editMode.beatExplanation = false;
    ui.editMode.guide = false;
    state.current_view = firstViewForStage(stageKey);
    syncStageFlow(state);
    syncFrameworkAssetState(state, `rollback:${stageKey}`);
    recordHistory("rollback", { stageKey });
    markDirty();
    showToast("已回退并清空下游确认状态");
    render();
  }

  function isEmptyValue(value) {
    if (value == null) return true;
    if (typeof value === "string") return !value.trim();
    if (Array.isArray(value)) return value.length === 0;
    if (typeof value === "object") return Object.keys(value).length === 0;
    return false;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatText(value) {
    return escapeHtml(value).replace(/\n/g, "<br>");
  }

  function prettyJson(value) {
    return JSON.stringify(value == null ? {} : value, null, 2);
  }

  function readKnowledgePanelOpen() {
    try {
      return window.localStorage.getItem(KNOWLEDGE_PANEL_STORAGE_KEY) === "1";
    } catch (error) {
      return false;
    }
  }

  function persistKnowledgePanelOpen(open) {
    try {
      window.localStorage.setItem(KNOWLEDGE_PANEL_STORAGE_KEY, open ? "1" : "0");
    } catch (error) {
      // ignore storage write errors
    }
  }

  function stagePromptLabel(stageKey) {
    return {
      basic: "01 基础信息",
      worldview: "02 世界观",
      character: "03 人设",
      beat: "04 十五节拍",
      storylines: "05 人物故事线",
      guide: "06 改编指引",
      package: "07 最终策划包",
    }[stageKey] || stageKey;
  }

  function emptyKnowledgeTagForm() {
    return {
      id: "",
      name: "",
      category: "自定义",
      description: "",
      prompt_text: "",
      stage_prompts: {
        basic: "",
        worldview: "",
        character: "",
        beat: "",
        storylines: "",
        guide: "",
        package: "",
      },
    };
  }

  function normalizeStagePrompts(value) {
    const source = value && typeof value === "object" && !Array.isArray(value) ? value : {};
    return {
      basic: String(source.basic || ""),
      worldview: String(source.worldview || ""),
      character: String(source.character || ""),
      beat: String(source.beat || ""),
      storylines: String(source.storylines || ""),
      guide: String(source.guide || ""),
      package: String(source.package || ""),
    };
  }

  function selectedKnowledgeTags() {
    const selected = new Set((ui.knowledge.selectedIds || []).map((item) => String(item)));
    return (ui.knowledge.tags || []).filter((tag) => selected.has(String(tag.id || "")));
  }

  function knowledgePayloadFields(stageKey) {
    const tags = selectedKnowledgeTags();
    const selectedIds = (ui.knowledge.selectedIds || []).map((item) => String(item || "").trim()).filter(Boolean);
    const stagePrompts = normalizeStagePrompts((state.prompt_preferences || {}).stage_prompts || {});
    return {
      selected_preference_tag_ids: selectedIds,
      selected_preference_tags: tags,
      user_preference_prompt: String((state.prompt_preferences || {}).script_preference || ""),
      user_knowledge_tag_prompt: String(ui.knowledge.tagPromptText || ""),
      user_knowledge_stage_prompts: stagePrompts,
      prompt_preferences: {
        script_preference: String((state.prompt_preferences || {}).script_preference || ""),
        stage_prompts: stagePrompts,
      },
      user_knowledge_stage_prompt: String(stagePrompts[stageKey] || ""),
      stage_preference_prompt: String(stagePrompts[stageKey] || ""),
      user_stage_preference_prompt: String(stagePrompts[stageKey] || ""),
    };
  }

  function attachKnowledgePayload(payload, stageKey) {
    return Object.assign({}, payload || {}, knowledgePayloadFields(stageKey || "basic"));
  }

  function truncateText(value, limit) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    const max = Number(limit || 80);
    return text.length > max ? `${text.slice(0, max)}...` : text;
  }

  const FIELD_LABELS = {
    source_brief: "原文信息提取",
    worldview_plan: "世界观方案",
    character_plan: "人物设定",
    beat_checkpoint_timeline: "三幕十五节拍时间轴",
    checkpoint_explanation: "节拍说明",
    character_storylines: "人物故事线",
    storyline_decisions: "故事线处理",
    character_relationships: "人物关系",
    main_characters: "主要角色",
    protagonist: "主角",
    antagonist: "反派",
    supporting_characters: "配角",
    goal: "目标",
    flaw: "缺陷",
    name: "姓名",
    title: "标题",
    role: "角色定位",
    summary: "摘要",
    overview: "整体说明",
    motivation: "动机",
    conflict: "冲突",
    relationship: "关系",
    personality: "性格",
    background: "背景",
    arc: "成长弧",
    act: "幕",
    beat_no: "节拍序号",
    beat_name: "节拍名称",
    episode_range: "集数范围",
    checkpoint_title: "卡点标题",
    narrative_function: "叙事功能",
    plot_content: "剧情内容",
    character_change: "人物变化",
    conflict_upgrade: "冲突升级",
    hook_or_reversal: "钩子 / 反转",
    linked_storylines: "关联故事线",
    beat_notes: "节拍说明",
    explanation: "说明",
    core_premise: "核心前提",
    theme: "主题",
    tone: "风格",
    setting: "设定",
    rules: "规则",
    timeline: "时间线",
    factions: "阵营",
    locations: "场景地点",
    detailed_storyline: "详细剧情",
    linked_beats: "关联节拍",
    episode_distribution: "分集安排",
    edit_notes: "编辑备注",
    framework_plan_package: "最终策划包",
    validation_report: "校验报告",
    user_requirements: "用户偏好",
    basic_config: "基础配置",
    project_title: "剧本名称",
    source_title: "原作名称",
    target_format: "类型 / 形式",
    season_count: "季数",
    episodes_per_season: "每季集数",
    minutes_per_episode: "每集分钟数",
    adaptation_direction: "改编方向",
    user_constraints: "限制条件",
    story_outline: "故事描述",
    status: "状态",
    issues: "问题",
    warnings: "提醒",
    passed: "是否通过",
    source_text: "原文材料",
    style: "风格",
    focus: "重点",
    display_text: "展示文本",
    display_texts: "展示文本",
    framework_score_report: "框架评分报告",
    validation_report: "校验报告",
    passed_checks: "通过检查",
    blocking_issues: "阻断问题",
    repair_notes: "修复说明",
    handoff_to_script_workflow: "下游交接说明",
    generation_priorities: "生成优先级",
    hard_constraints: "硬约束",
    do_not_change: "不可改动",
    risk_flags: "风险提醒",
    recommended_next_action: "推荐下一步",
    sceneDictionary: "场景字典",
    scriptWorldRulesDigest: "正文世界规则摘要",
    appearanceMapping: "人设服装 alias 映射",
    allEnrichedEpisodePlan: "丰富分集计划",
    allEnrichedEpisodePlanText: "丰富分集计划文本",
    worldviewPlan: "世界观方案",
    core_rules: "核心规则",
    coreRules: "核心规则",
    forbidden_rules: "禁忌与代价",
    taboos_and_costs: "禁忌与代价",
    narrative_risks: "叙事风险",
    characterPlan: "人物方案",
    character_arc: "人物成长线",
    characterArc: "人物成长线",
    character_goals: "人物目标",
    characterGoals: "人物目标",
    beatCheckpointTimeline: "节拍卡点规划",
    characterStorylines: "人物故事线",
    overallAdaptationGuide: "整体改编指引",
    frameworkPlanPackage: "框架策划包",
    adaptation_guide: "整体改编指引",
    adaptationGuide: "整体改编指引",
    world_setting: "世界设定",
    worldSetting: "世界设定",
    main_relationships: "人物关系",
    reversals: "反转与钩子",
    hooks: "钩子",
    three_act_structure: "三幕结构",
    key_nodes: "关键节点",
    integrity_check: "完整性检查",
  };

  function fieldLabel(key) {
    const normalized = String(key || "");
    if (FIELD_LABELS[normalized]) return FIELD_LABELS[normalized];
    return friendlyFallbackLabel(normalized);
  }

  function isHiddenTechnicalKey(key) {
    return TECHNICAL_FIELD_KEYS.has(String(key || ""));
  }

  function friendlyFallbackLabel(key) {
    const text = String(key || "")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/[_-]+/g, " ")
      .trim();
    if (!text) return "补充信息";
    const words = text.split(/\s+/).filter(Boolean);
    if (words.length > 1) {
      return words.map((word) => FIELD_LABELS[word] || fallbackWordLabel(word)).join(" / ");
    }
    return fallbackWordLabel(text);
  }

  function fallbackWordLabel(word) {
    const lower = String(word || "").toLowerCase();
    const map = {
      world: "世界", worldview: "世界观", plan: "方案", summary: "概述", core: "核心",
      rules: "规则", rule: "规则", taboo: "禁忌", taboos: "禁忌", cost: "代价",
      risk: "风险", risks: "风险", narrative: "叙事", character: "人物", characters: "人物",
      arc: "成长线", storylines: "故事线", storyline: "故事线", beat: "节拍",
      checkpoint: "卡点", timeline: "时间轴", guide: "指引", adaptation: "改编",
      overall: "整体", package: "策划包", validation: "校验", report: "报告",
      relation: "关系", relationships: "关系", goal: "目标", goals: "目标",
      change: "变化", changes: "变化", direction: "方向", style: "风格",
      warning: "提醒", warnings: "提醒", issue: "问题", issues: "问题",
    };
    return map[lower] || String(word || "补充信息");
  }

  function isRenderableValue(value) {
    if (value === null || value === undefined) return false;
    if (typeof value === "string") {
      const text = value.trim();
      return Boolean(text) && !["{}", "[]", "null", "undefined", "[object Object]"].includes(text);
    }
    if (Array.isArray(value)) return value.some(isRenderableValue);
    if (typeof value === "object") {
      return Object.keys(value).some((key) => !isHiddenTechnicalKey(key) && isRenderableValue(value[key]));
    }
    return true;
  }

  function editorValueFor(key) {
    if (state.editors[key]) return state.editors[key];
    if (key === "worldview_plan") return prettyJson(state.worldview_plan);
    if (key === "character_plan") return prettyJson(state.character_plan);
    if (key === "beat_checkpoint_timeline") return prettyJson(state.beat_checkpoint_timeline);
    if (key === "checkpoint_explanation") return prettyJson(state.checkpoint_explanation);
    if (key === "adaptation_guide") return prettyJson(state.adaptation_guide);
    return "";
  }

  function parseEditorValue(editorKey, rawText) {
    const text = String(rawText || "").trim();
    if (!text) {
      if (editorKey === "beat_checkpoint_timeline") return [];
      return {};
    }
    try {
      return JSON.parse(text);
    } catch (error) {
      if (editorKey === "adaptation_guide") {
        return {
          core_setting_adjustments: text,
          structure_and_rhythm: "",
          visualization_strategy: "",
          character_emotion_strategy: "",
        };
      }
      if (editorKey === "beat_checkpoint_timeline") {
        throw new Error("十五节拍时间轴必须是合法 JSON 数组");
      }
      if (editorKey === "checkpoint_explanation") {
        return {
          overview: text,
          beat_notes: [],
        };
      }
      return { content: text };
    }
  }

  function render() {
    const focusedControl = captureFocusedControl();
    syncStageFlow(state);
    saveState();
    app.innerHTML = `
      <div class="fp-shell">
        ${renderSidebar()}
        <main class="fp-main">
          ${renderTopbar()}
          ${renderCurrentView()}
        </main>
        ${renderFooter()}
        ${ui.toast ? `<div class="fp-toast">${escapeHtml(ui.toast)}</div>` : ""}
        ${ui.showNewScriptModal ? renderNewScriptModal() : ""}
        ${ui.modalStorylineId ? renderStorylineModal(ui.modalStorylineId) : ""}
        ${ui.unsavedPrompt ? renderUnsavedPrompt() : ""}
      </div>
    `;
    restoreFocusedControl(focusedControl);
  }

  function renderUnsavedPrompt() {
    const target = ui.unsavedPrompt || {};
    return `
      <div class="fp-modal-mask" data-action="cancel-unsaved-prompt">
        <div class="fp-modal fp-unsaved-modal" data-modal-content="unsaved">
          <div class="fp-modal-head">
            <div>
              <h2>当前框架尚未保存</h2>
              <p class="fp-modal-sub">${escapeHtml(UNSAVED_MESSAGE)}</p>
            </div>
          </div>
          <div class="fp-stage-note">
            <strong>即将执行</strong>
            <span>${escapeHtml(target.label || "离开当前框架")}</span>
          </div>
          <div class="fp-actions">
            <button class="fp-btn primary" data-action="save-unsaved-prompt">保存并退出</button>
            <button class="fp-btn danger subtle" data-action="discard-unsaved-prompt">不保存，直接退出</button>
            <button class="fp-btn" data-action="cancel-unsaved-prompt">取消，继续编辑</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderNewScriptModal() {
    const form = ui.newScriptForm;
    return `
      <div class="fp-modal-mask" data-action="close-new-script">
        <div class="fp-modal" data-modal-content="new-script">
          <div class="fp-card-title-row">
            <div>
            <h2 class="fp-card-title">新建框架项目</h2>
              <p class="fp-card-sub">创建全新的 01-07 框架策划上下文，不会带入旧项目历史版本。</p>
            </div>
            <button class="fp-btn small" data-action="close-new-script">关闭</button>
          </div>
          <div class="fp-grid two">
            <label class="fp-field"><span>框架项目名称</span><input data-new-script-field="title" value="${escapeHtml(form.title)}" /></label>
            <label class="fp-field"><span>类型 / 风格</span><input data-new-script-field="target_format" value="${escapeHtml(form.target_format)}" /></label>
          </div>
          <div class="fp-grid two" style="margin-top:12px">
            <label class="fp-field"><span>季数</span><input type="number" min="1" data-new-script-field="season_count" value="${escapeHtml(form.season_count)}" /></label>
            <label class="fp-field"><span>每季集数</span><input type="number" min="1" data-new-script-field="episodes_per_season" value="${escapeHtml(form.episodes_per_season)}" /></label>
          </div>
          <label class="fp-field" style="margin-top:12px"><span>细分风格</span><input data-new-script-field="style" value="${escapeHtml(form.style)}" placeholder="例如：短剧强反转、悬疑、都市情感" /></label>
          <label class="fp-field" style="margin-top:12px"><span>简短描述</span><textarea data-new-script-field="description" placeholder="一句话写清故事方向、主角或核心冲突。">${escapeHtml(form.description)}</textarea></label>
          <div class="fp-actions">
            <button class="fp-btn" data-action="close-new-script">取消</button>
            <button class="fp-btn primary" data-action="submit-new-script">创建并进入 01 阶段</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderSidebar() {
    const navItems = VIEW_DEFS.map((item, index) => {
      const unlocked = viewUnlocked(item.id);
      const active = state.current_view === item.id ? "active" : "";
      const done = state.stage_state[item.stageKey] && state.stage_state[item.stageKey].confirmed ? "done" : "";
      const locked = unlocked ? "" : "locked";
      const mark = done ? "✓" : String(index + 1);
      return `
        <button class="fp-nav-item ${active} ${done} ${locked}" data-action="go-view" data-view="${item.id}" ${unlocked ? "" : "disabled"}>
          <span>${escapeHtml(item.label)}</span>
          <span class="fp-nav-pill">${mark}</span>
        </button>
      `;
    }).join("");
    const modeLabel = config.backendReady ? "真实后端" : "Mock / 预留接口";
    const modeClass = config.backendReady ? "blue" : "warn";
    return `
      <aside class="fp-side">
        <div class="fp-logo">
          <div class="fp-logo-mark">FP</div>
          <div>
            剧本框架策划工作台
          </div>
        </div>
        <div class="fp-side-note">
          <div class="fp-side-line"><span class="fp-tag ${modeClass}">${escapeHtml(modeLabel)}</span></div>
          <div>上游阶段确认并锁定后，下游阶段内容不能直接修改。
如需更改上游内容，必须先点击“回退”按钮，这会自动清空下游阶段的确认状态，再进行修改。</div>
        </div>
        <div class="fp-side-note">
          <strong>本地保存：</strong>状态会自动保存
        </div>
        <nav class="fp-nav">${navItems}</nav>
      </aside>
    `;
  }

  function renderTopbar() {
    const projectId = currentProjectId();
    const stageTitle = realStageDisplayTitle(stageKeyForView(state.current_view || "basic"));
    const assetId = hasSavedFrameworkProjectId() ? projectId : "尚未保存";
    return `
      <div class="fp-top">
        <div>
          <div class="fp-kicker">01-07 框架策划阶段</div>
          <h1 class="fp-title">${escapeHtml(state.basic_config.project_title || "未命名框架策划")}</h1>
          <p class="fp-top-sub">目标：产出可保存的框架资产。当前阶段：${escapeHtml(stageTitle)} · 框架资产 ID：${escapeHtml(assetId)}</p>
        </div>
        <div class="fp-top-actions">
          <button class="fp-btn small primary" data-action="open-new-script">新建框架项目</button>
          ${renderSaveFrameworkButton("small")}
          ${renderFrameworkScriptButton("small")}
          <button class="fp-btn small" data-action="toggle-assets">${ui.assetsOpen ? "收起已有项目" : "继续上次项目"}</button>
          <a class="fp-btn small ghost" data-guard-nav="workspace" href="${escapeHtml(config.workspaceUrl || "/workspace")}">返回主工作台</a>
          <button class="fp-btn small danger" data-action="reset-state" ${canClearFrameworkInput() ? "" : "disabled"}>清空输入</button>
        </div>
      </div>
      ${ui.assetsOpen ? renderAssetManager() : ""}
      ${renderKnowledgePanel()}
      <div class="fp-card fp-steps">${renderStepRail()}</div>
      ${renderRunningStageStatus()}
    `;
  }

  function renderAssetManager() {
    const assets = filteredAssets();
    return `
      <section class="fp-card fp-asset-manager">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">继续编辑已有项目</h2>
            <p class="fp-card-sub">打开已保存的框架项目并恢复上次状态。新建框架项目不会自动带入这里的历史内容。</p>
          </div>
          <button class="fp-btn small" data-action="refresh-assets" ${ui.assetsLoading ? "disabled" : ""}>${ui.assetsLoading ? "刷新中..." : "刷新"}</button>
        </div>
        <div class="fp-asset-toolbar">
          <input data-asset-search placeholder="搜索标题或摘要" value="${escapeHtml(ui.assetSearch)}" />
          <select data-asset-status-filter>
            ${[
              ["all", "全部状态"],
              ["draft", "草稿"],
              ["running", "处理中"],
              ["completed", "完成"],
              ["failed", "失败"],
              ["terminated", "已停止"],
            ].map(([value, label]) => `<option value="${value}" ${ui.assetStatusFilter === value ? "selected" : ""}>${label}</option>`).join("")}
          </select>
          <select data-asset-sort>
            <option value="updated_desc" ${ui.assetSort === "updated_desc" ? "selected" : ""}>最近修改优先</option>
            <option value="created_desc" ${ui.assetSort === "created_desc" ? "selected" : ""}>最近创建优先</option>
            <option value="title_asc" ${ui.assetSort === "title_asc" ? "selected" : ""}>名称 A-Z</option>
          </select>
        </div>
        ${ui.assetsLoading ? renderProcessingBanner("正在刷新资产列表...") : ""}
        <div class="fp-asset-list">
          ${assets.length ? assets.map(renderAssetItem).join("") : `<div class="fp-empty">暂无匹配资产。可以点击“新建框架项目”开始一个新的 01-07 框架策划。</div>`}
        </div>
      </section>
    `;
  }

  function renderAssetItem(item) {
    const projectId = item.project_id;
    const taskId = String(item.task_id || "");
    const status = String(item.status || "draft");
    const canStop = taskId && ["pending", "running", "pausing", "paused"].includes(status);
    const canContinue = taskId && ["paused", "failed", "terminated"].includes(status);
    return `
      <article class="fp-asset-item">
        <div>
          <div class="fp-asset-title">${escapeHtml(item.title || "未命名剧本")}</div>
          <div class="fp-asset-meta">
            <span class="fp-tag ${assetStatusClass(status)}">${escapeHtml(assetStatusLabel(status))}</span>
            <span>上次修改：${escapeHtml(formatDateTime(item.updated_at || item.created_at || ""))}</span>
            <span>${escapeHtml(item.current_stage_label || "待开始")}</span>
          </div>
          <p>${escapeHtml(item.summary || "这个剧本还没有简短描述。")}</p>
        </div>
        <div class="fp-asset-actions">
          <button class="fp-btn small primary" data-action="open-asset" data-project-id="${escapeHtml(projectId)}">打开查看</button>
          <button class="fp-btn small" data-action="duplicate-asset" data-project-id="${escapeHtml(projectId)}">复制</button>
          ${canStop ? `<button class="fp-btn small danger" data-action="stop-asset-task" data-task-id="${escapeHtml(taskId)}">停止</button>` : ""}
          ${canContinue ? `<button class="fp-btn small" data-action="continue-asset-task" data-task-id="${escapeHtml(taskId)}">继续</button>` : ""}
          <button class="fp-btn small danger subtle" data-action="delete-asset" data-project-id="${escapeHtml(projectId)}">删除</button>
        </div>
      </article>
    `;
  }

  function renderKnowledgePanel() {
    const selectedTags = selectedKnowledgeTags();
    const missingIds = (ui.knowledge.selectedIds || []).filter((id) => !selectedTags.some((tag) => String(tag.id || "") === String(id)));
    const builtinTags = (ui.knowledge.tags || []).filter((tag) => tag.builtin);
    const customTags = (ui.knowledge.tags || []).filter((tag) => !tag.builtin);
    const selectedLabel = selectedTags.length || missingIds.length
      ? `${selectedTags.length + missingIds.length} 个已选`
      : "允许不选择";
    return `
      <section class="fp-card fp-knowledge-panel ${ui.knowledge.open ? "is-open" : ""}">
        <button class="fp-knowledge-toggle" type="button" data-action="toggle-knowledge-panel" aria-expanded="${ui.knowledge.open ? "true" : "false"}">
          <span>
          <strong>智慧库 / 阶段偏好</strong>
            <small>${escapeHtml(selectedLabel)} · ${ui.knowledge.status ? escapeHtml(ui.knowledge.status) : "可为每个策划阶段注入不同偏好"}</small>
          </span>
          <span class="fp-tag blue">${ui.knowledge.open ? "收起" : "展开"}</span>
        </button>
        ${ui.knowledge.open ? `
          <div class="fp-knowledge-body">
            <div class="fp-knowledge-actions">
              <button class="fp-btn small" data-action="refresh-knowledge-tags" ${ui.knowledge.loading ? "disabled" : ""}>${ui.knowledge.loading ? "加载中..." : "刷新标签"}</button>
              <button class="fp-btn small primary" data-action="apply-knowledge-tags">应用到 01-07 阶段偏好</button>
              <button class="fp-btn small" data-action="new-knowledge-tag">${ui.knowledge.formOpen && !ui.knowledge.editingId ? "收起新建" : "新建自定义标签"}</button>
            </div>
            ${ui.knowledge.status ? `<div class="fp-inline-warning compact">${escapeHtml(ui.knowledge.status)}</div>` : ""}
            ${renderKnowledgeSelected(selectedTags, missingIds)}
            <div class="fp-knowledge-grid">
              <div>
                <h3>默认标签</h3>
                ${renderKnowledgeTagGroup(builtinTags, "暂无系统预设标签。")}
              </div>
              <div>
                <h3>用户自定义标签</h3>
                ${renderKnowledgeTagGroup(customTags, "暂无自定义标签。")}
              </div>
            </div>
            ${renderKnowledgeStagePreview()}
            ${ui.knowledge.formOpen ? renderKnowledgeForm() : ""}
          </div>
        ` : ""}
      </section>
    `;
  }

  function renderKnowledgeSelected(tags, missingIds) {
    const items = tags.map((tag) => `<span class="fp-tag ${tag.builtin ? "blue" : "ok"}">${escapeHtml(tag.name || tag.id)}</span>`)
      .concat((missingIds || []).map((id) => `<span class="fp-tag red">${escapeHtml(id)}（标签已删除）</span>`));
    return `
      <div class="fp-knowledge-selected">
        <strong>当前已选择标签</strong>
        <div>${items.length ? items.join("") : `<span class="fp-tag lock">未选择标签</span>`}</div>
      </div>
    `;
  }

  function renderKnowledgeTagGroup(tags, emptyText) {
    if (ui.knowledge.loading && !(ui.knowledge.tags || []).length) {
      return `<div class="fp-empty small">正在加载智慧库标签...</div>`;
    }
    if (!tags.length) {
      return `<div class="fp-empty small">${escapeHtml(emptyText)}</div>`;
    }
    return `
      <div class="fp-knowledge-list">
        ${tags.map(renderKnowledgeTagItem).join("")}
      </div>
    `;
  }

  function renderKnowledgeTagItem(tag) {
    const id = String(tag.id || "");
    const selected = (ui.knowledge.selectedIds || []).includes(id);
    const prompts = normalizeStagePrompts(tag.stage_prompts || {});
    return `
      <label class="fp-knowledge-item">
        <input type="checkbox" data-knowledge-tag-id="${escapeHtml(id)}" ${selected ? "checked" : ""} />
        <span>
          <strong>${escapeHtml(tag.name || id)}</strong>
          <small>${escapeHtml(tag.category || (tag.builtin ? "默认标签" : "自定义"))} · ${tag.builtin ? "默认标签，可编辑" : "自定义标签"}</small>
          ${tag.description ? `<em>${escapeHtml(truncateText(tag.description, 90))}</em>` : ""}
          <details class="fp-knowledge-stage-details">
            <summary>查看 01-07 阶段提示词</summary>
            <div>
              ${STAGE_SEQUENCE.map((stageKey) => `
                <p><strong>${escapeHtml(stagePromptLabel(stageKey))}</strong><span>${escapeHtml(truncateText(prompts[stageKey] || "", 120) || "暂无")}</span></p>
              `).join("")}
            </div>
          </details>
        </span>
        <span class="fp-knowledge-item-actions">
          <button class="fp-btn small" type="button" data-action="edit-knowledge-tag" data-tag-id="${escapeHtml(id)}">编辑</button>
          <button class="fp-btn small danger subtle" type="button" data-action="delete-knowledge-tag" data-tag-id="${escapeHtml(id)}">${tag.builtin ? "隐藏" : "删除"}</button>
        </span>
      </label>
    `;
  }

  function renderKnowledgeStagePreview() {
    const prompts = normalizeStagePrompts((state.prompt_preferences || {}).stage_prompts || {});
    return `
      <div class="fp-knowledge-preview">
        <div class="fp-card-title-row">
          <div>
            <h3>每阶段提示词预览</h3>
            <p class="fp-card-sub">应用标签后仍可在当前阶段文本框继续微调。</p>
          </div>
        </div>
        <div class="fp-knowledge-stage-grid">
          ${STAGE_SEQUENCE.map((stageKey) => `
            <div class="fp-knowledge-stage">
              <strong>${escapeHtml(stagePromptLabel(stageKey))}</strong>
              <p>${escapeHtml(truncateText(prompts[stageKey] || "", 120) || "暂无阶段提示词")}</p>
            </div>
          `).join("")}
        </div>
      </div>
    `;
  }

  function renderKnowledgeForm() {
    const form = ui.knowledge.form || emptyKnowledgeTagForm();
    const editing = Boolean(ui.knowledge.editingId);
    return `
      <div class="fp-knowledge-form">
        <div class="fp-card-title-row">
          <div>
            <h3>${editing ? "编辑标签" : "新建自定义标签"}</h3>
            <p class="fp-card-sub">通用偏好用于主工作台，阶段提示词用于框架策划 01-07。</p>
          </div>
          <button class="fp-btn small" data-action="cancel-knowledge-edit">取消</button>
        </div>
        <div class="fp-grid three">
          <label class="fp-field"><span>名称</span><input data-knowledge-form-key="name" value="${escapeHtml(form.name)}" /></label>
          <label class="fp-field"><span>分类</span><input data-knowledge-form-key="category" value="${escapeHtml(form.category)}" /></label>
          <label class="fp-field"><span>描述</span><input data-knowledge-form-key="description" value="${escapeHtml(form.description)}" /></label>
        </div>
        <label class="fp-field" style="margin-top:12px"><span>通用偏好 prompt_text</span><textarea data-knowledge-form-key="prompt_text">${escapeHtml(form.prompt_text)}</textarea></label>
        <div class="fp-knowledge-stage-edit-grid">
          ${STAGE_SEQUENCE.map((stageKey) => `
            <label class="fp-field">
              <span>${escapeHtml(stagePromptLabel(stageKey))}</span>
              <textarea data-knowledge-stage-key="${escapeHtml(stageKey)}">${escapeHtml((form.stage_prompts || {})[stageKey] || "")}</textarea>
            </label>
          `).join("")}
        </div>
        <div class="fp-actions">
          <button class="fp-btn primary" data-action="save-knowledge-tag">${editing ? "保存编辑" : "创建标签"}</button>
        </div>
      </div>
    `;
  }

  function filteredAssets() {
    const query = ui.assetSearch.trim().toLowerCase();
    let items = ui.assets.slice();
    if (query) {
      items = items.filter((item) => `${item.title || ""} ${item.summary || ""}`.toLowerCase().includes(query));
    }
    if (ui.assetStatusFilter !== "all") {
      items = items.filter((item) => String(item.status || "draft") === ui.assetStatusFilter);
    }
    items.sort((a, b) => {
      if (ui.assetSort === "title_asc") return String(a.title || "").localeCompare(String(b.title || ""), "zh-Hans-CN");
      const key = ui.assetSort === "created_desc" ? "created_at" : "updated_at";
      return String(b[key] || "").localeCompare(String(a[key] || ""));
    });
    return items;
  }

  function assetStatusLabel(status) {
    return {
      draft: "草稿",
      pending: "等待中",
      running: "处理中",
      pausing: "暂停中",
      paused: "已暂停",
      completed: "完成",
      failed: "失败",
      terminated: "已停止",
    }[status] || "已生成";
  }

  function assetStatusClass(status) {
    if (["running", "pending", "pausing"].includes(status)) return "blue";
    if (status === "completed") return "ok";
    if (["failed", "terminated"].includes(status)) return "red";
    return "warn";
  }

  function renderRunningStageStatus() {
    const stageKey = runningStageKey();
    if (!stageKey) return "";
    const stageNo = stageNoForKey(stageKey);
    const title = stageDisplayTitle(stageKey);
    return `
      <div class="fp-running-card" role="status" aria-live="polite">
        <div class="fp-running-main">
          <span class="fp-running-spinner" aria-hidden="true"></span>
          <div>
            <strong>阶段 ${escapeHtml(stageNo)} 正在处理：${escapeHtml(title)}</strong>
            <p>已运行 ${escapeHtml(processingElapsedLabel(stageKey))}。</p>
          </div>
        </div>
        <span class="fp-running-badge">处理中</span>
      </div>
    `;
  }

  function renderStepRail() {
    return VIEW_DEFS.map((item, index) => {
      const active = state.current_view === item.id ? "active" : "";
      const done = state.stage_state[item.stageKey] && state.stage_state[item.stageKey].confirmed ? "done" : "";
      const line = index < VIEW_DEFS.length - 1 ? `<span class="fp-step-line"></span>` : "";
      const mark = done ? "✓" : String(index + 1);
      return `<div class="fp-step ${active} ${done}"><span class="fp-step-dot">${mark}</span><span>${escapeHtml(item.label.replace(/^\d+\.\s*/, ""))}</span></div>${line}`;
    }).join("");
  }

  function renderCurrentView() {
    switch (state.current_view) {
      case "basic":
        return renderBasicView();
      case "worldview":
        return renderPlanStageView({
          stageKey: "worldview",
          title: "世界观方案",
          subtitle: "生成、编辑、更新、确认都在这里完成。只有基础配置确认并锁定后，世界观方案才可生成。",
          dataKey: "worldview_plan",
          nextTitle: "人设方案",
        });
      case "character":
        return renderPlanStageView({
          stageKey: "character",
          title: "人设方案",
          subtitle: "人设必须服从已确认世界观。确认后才解锁 04 阶段的三幕十五节拍卡点规划。",
          dataKey: "character_plan",
          nextTitle: "三幕十五节拍卡点规划",
        });
      case "beat_timeline":
        return renderBeatTimelineView();
      case "beat_explanation":
        return renderBeatExplanationView();
      case "storylines":
        return renderStorylinesView();
      case "storyline_details":
        return renderStorylineDetailsView();
      case "storyline_decisions":
        return renderStorylineDecisionView();
      case "guide":
        return renderGuideView();
      case "package":
        return renderPackageView();
      default:
        return renderBasicView();
    }
  }

  function renderBasicView() {
    const stage = state.stage_state.basic;
    const locked = stage.confirmed;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">基础配置</h2>
          </div>
          ${stageStatusTag("basic")}
        </div>
        ${locked ? `<div class="fp-inline-warning">基础配置已确认并锁定。如需修改，请显式回退到该阶段，系统会清空下游确认状态。</div>` : ""}
        <div class="fp-grid two">
          <div class="fp-field">
            <label>项目标题</label>
            <input data-config-key="project_title" value="${escapeHtml(state.basic_config.project_title)}" ${locked ? "disabled" : ""} />
          </div>
          <div class="fp-field">
            <label>写作模式</label>
            <select data-config-key="mode" ${locked ? "disabled" : ""}>
              <option value="创作" ${state.basic_config.mode === "创作" ? "selected" : ""}>创作</option>
              <option value="改写" ${state.basic_config.mode === "改写" ? "selected" : ""}>改写</option>
            </select>
          </div>
        </div>
        <div class="fp-grid two" style="margin-top:14px">
          <div class="fp-field">
            <label>作品标题</label>
            <input data-config-key="source_title" placeholder="例如：机甲纪元，拳爆天星" value="${escapeHtml(state.basic_config.source_title)}" ${locked ? "disabled" : ""} />
          </div>
          <div class="fp-field">
            <label>目标形式</label>
            <input data-config-key="target_format" placeholder="例如：短剧、长剧、网文剧本" value="${escapeHtml(state.basic_config.target_format)}" ${locked ? "disabled" : ""} />
          </div>
        </div>
        <div class="fp-grid three" style="margin-top:14px">
          <div class="fp-field">
            <label>季数</label>
            <input type="number" min="1" data-config-key="season_count" value="${escapeHtml(state.basic_config.season_count)}" ${locked ? "disabled" : ""} />
          </div>
          <div class="fp-field">
            <label>每季集数</label>
            <input type="number" min="15" data-config-key="episodes_per_season" value="${escapeHtml(state.basic_config.episodes_per_season)}" ${locked ? "disabled" : ""} />
          </div>
          <div class="fp-field">
            <label>每集分钟数</label>
            <input type="number" min="1" data-config-key="minutes_per_episode" value="${escapeHtml(state.basic_config.minutes_per_episode)}" ${locked ? "disabled" : ""} />
          </div>
        </div>
        <div class="fp-field" style="margin-top:14px">
          <label>原文材料</label>
          <textarea data-config-key="source_text" placeholder="可直接粘贴原文、梗概、旧策划、分集等材料。" ${locked ? "disabled" : ""}>${escapeHtml(state.basic_config.source_text)}</textarea>
        </div>
        <div class="fp-grid two" style="margin-top:14px">
          <div class="fp-field">
            <label>改编方向</label>
            <textarea data-config-key="adaptation_direction" placeholder="例如：压缩支线，强化中点反转，偏短剧强情绪推进。" ${locked ? "disabled" : ""}>${escapeHtml(state.basic_config.adaptation_direction)}</textarea>
          </div>
          <div class="fp-field">
            <label>用户提示词</label>
            <textarea data-config-key="user_requirements" placeholder="补充平台风格、人物偏好、节奏要求等。" ${locked ? "disabled" : ""}>${escapeHtml(state.basic_config.user_requirements)}</textarea>
          </div>
        </div>
        <div class="fp-field" style="margin-top:14px">
          <label>限制条件</label>
          <textarea data-config-key="user_constraints" placeholder="例如：不能改世界观底层逻辑，不能删除某角色。" ${locked ? "disabled" : ""}>${escapeHtml(state.basic_config.user_constraints)}</textarea>
        </div>
        ${renderScriptPreferencePanel(locked)}
        ${!isEmptyValue(state.source_brief) ? `
          <div class="fp-stage-note">
            <strong>01 阶段：用户原始输入</strong>
            ${renderDataBlock(state.source_brief, { dataKey: "source_brief", stageKey: "basic", editable: false })}
          </div>
        ` : ""}
        ${renderStageHistoryPanel("basic")}
        ${isStageLoading("basic") ? renderProcessingBanner("正在提取原文信息，请稍候。") : ""}
        <div class="fp-actions">
          ${locked ? `<button class="fp-btn danger" data-action="rollback-stage" data-stage-key="basic">回退到此阶段并清空下游</button>` : ""}
          <button class="fp-btn primary" data-action="confirm-basic" ${isStageLoading("basic") ? "disabled" : ""}>
            ${isStageLoading("basic") ? "正在提取原文信息..." : "确认基础配置并提取原文信息"}
          </button>
        </div>
      </section>
    `;
  }

  function renderScriptPreferencePanel(disabled) {
    const preferences = state.prompt_preferences || initialState.prompt_preferences;
    const templates = Array.isArray(preferences.templates) ? preferences.templates : DEFAULT_PROMPT_TEMPLATES;
    return `
      <div class="fp-preference-panel">
        <div class="fp-preference-head">
          <div>
            <strong>用户偏好提示</strong>
            <p>这里会自动保存到本地，下次生成时自动带入；选择模板后仍可继续手动微调。</p>
          </div>
          <select data-preference-template ${disabled ? "disabled" : ""}>
            ${templates.map((item) => `<option value="${escapeHtml(item.id)}" ${preferences.active_template_id === item.id ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}
          </select>
        </div>
        <textarea data-script-preference placeholder="例如：强化短剧钩子、保留原作核心关系、减少支线、人物情绪必须可拍。" ${disabled ? "disabled" : ""}>${escapeHtml(preferences.script_preference || "")}</textarea>
        <div class="fp-preference-meta">
          ${preferences.updated_at ? `上次保存：${escapeHtml(formatDateTime(preferences.updated_at))}` : "尚未保存偏好提示"}
        </div>
      </div>
    `;
  }

  function renderStagePreferenceField(stageKey, disabled) {
    const preferences = state.prompt_preferences || initialState.prompt_preferences;
    const value = (preferences.stage_prompts || {})[stageKey] || "";
    const preview = ui.lastStagePayloadPreview[stageKey];
    return `
      <div class="fp-preference-panel compact">
        <div class="fp-preference-head">
          <div>
            <strong>本阶段偏好</strong>
            <p>只影响 ${escapeHtml(stagePromptLabel(stageKey))}，不会污染其他阶段</p>
          </div>
          <button class="fp-btn small" data-action="apply-stage-preference" data-stage-key="${escapeHtml(stageKey)}" ${disabled || !String(value).trim() ? "disabled" : ""}>应用偏好</button>
        </div>
        <textarea data-stage-preference-key="${escapeHtml(stageKey)}" placeholder="补充本阶段偏好，例如希望强化/避免/保留的内容。" ${disabled ? "disabled" : ""}>${escapeHtml(value)}</textarea>
        ${preview ? `
          <div class="fp-preference-meta">
            已生成本阶段入参：阶段 ${escapeHtml(preview.stageNo)} · 字段 ${escapeHtml((preview.keys || []).map(fieldLabel).join("、"))} · ${escapeHtml(preview.updated_at || "")}
          </div>
        ` : ""}
      </div>
    `;
  }

  function renderStageHistoryPanel(stageKey) {
    const stageNo = stageNoForKey(stageKey);
    if (!stageNo) return "";
    const entries = ui.stageHistory[stageKey] || [];
    const loading = ui.stageHistoryLoading[stageKey];
    return `
      <details class="fp-history-panel fp-advanced-panel">
        <summary>
          <span>高级 / 版本记录 / 回滚记录</span>
          <small>默认隐藏，避免与当前阶段结果混淆</small>
        </summary>
        <div class="fp-preference-head">
          <div>
            <strong>${escapeHtml(stageDisplayTitle(stageKey))}版本记录</strong>
            <p>这里仅用于排查和回滚。恢复旧版本会覆盖当前 ${escapeHtml(stageDisplayTitle(stageKey))} 结果，并可能要求重新运行后续阶段；不会删除已保存资产。</p>
          </div>
          <button class="fp-btn small" data-action="refresh-stage-history" data-stage-key="${escapeHtml(stageKey)}" ${loading ? "disabled" : ""}>${loading ? "刷新中..." : "查看历史版本"}</button>
        </div>
        <div class="fp-history-list">
          ${entries.length ? entries.map((entry) => `
            <div class="fp-history-item">
              <div>
                <strong>${escapeHtml(stageDisplayTitle(stageKey))}</strong>
                <span>${escapeHtml(formatHistoryTimestamp(entry.timestamp))}</span>
                <small>${escapeHtml((entry.payload_keys || []).map(fieldLabel).join("、") || "无入参摘要")}</small>
              </div>
              <div class="fp-history-actions">
                <span class="fp-tag ${entry.status === "success" ? "ok" : "red"}">${entry.status === "success" ? "成功" : "失败"}</span>
                <button class="fp-btn small" title="会覆盖当前${escapeHtml(stageDisplayTitle(stageKey))}结果；后续阶段可能需要重新运行；不会删除已保存资产。" data-action="load-stage-history" data-stage-key="${escapeHtml(stageKey)}" data-history-file="${escapeHtml(entry.filename)}" ${entry.status !== "success" ? "disabled" : ""}>恢复到此版本</button>
              </div>
            </div>
          `).join("") : `<div class="fp-empty small">暂无历史版本。生成本阶段后会自动保存。</div>`}
        </div>
      </details>
    `;
  }

  function formatHistoryTimestamp(value) {
    const text = String(value || "");
    const match = text.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/);
    if (!match) return text || "未知时间";
    return `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}:${match[6]}`;
  }

  function formatDateTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value || "");
    return date.toLocaleString();
  }

  function renderPlanStageView(options) {
    const stage = state.stage_state[options.stageKey];
    const data = state[options.dataKey];
    const blocked = stageBlockedByUpstream(stage);
    const confirmed = stage.confirmed;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">${escapeHtml(options.title)}</h2>
            <p class="fp-card-sub">${escapeHtml(options.subtitle)}</p>
          </div>
          ${stageStatusTag(options.stageKey)}
        </div>
        ${confirmed ? `<div class="fp-inline-warning">${escapeHtml(options.title)}已确认并锁定。下游内容已基于当前版本生成，如需改动请显式回退。</div>` : ""}
        ${isStageLoading(options.stageKey) ? renderProcessingBanner(`正在生成${options.title}，请稍候...`) : ""}
        ${blocked && isEmptyValue(data) ? `<div class="fp-empty">请先确认上游阶段。</div>` : renderDataBlock(data, { dataKey: options.dataKey, stageKey: options.stageKey, editable: !blocked && !confirmed })}
        ${renderStagePreferenceField(options.stageKey, blocked || confirmed || isStageLoading(options.stageKey))}
        ${renderStageHistoryPanel(options.stageKey)}
        ${renderStageError(options.stageKey)}
        <div class="fp-lock-note">本阶段由上游确认或底部“下一阶段”自动生成。人工操作只保留确认与显式回退。</div>
        <div class="fp-actions">
          ${renderUpstreamRollbackButton(options.stageKey)}
          ${confirmed ? `<button class="fp-btn danger" data-action="rollback-stage" data-stage-key="${options.stageKey}">回退 ${escapeHtml(realStageDisplayTitle(options.stageKey))}</button>` : ""}
          <button class="fp-btn primary" data-action="confirm-stage" data-stage-key="${options.stageKey}" ${blocked || confirmed || isEmptyValue(data) ? "disabled" : ""}>确认并进入${escapeHtml(options.nextTitle)}</button>
        </div>
      </section>
    `;
  }

  function renderBeatTimelineView() {
    const stage = state.stage_state.beat;
    const blocked = stageBlockedByUpstream(stage);
    const confirmed = stage.confirmed;
    const canConfirm = state.beat_checkpoint_timeline.length === 15 && !isEmptyValue(state.checkpoint_explanation);
    const hasTimeline = Array.isArray(state.beat_checkpoint_timeline) && state.beat_checkpoint_timeline.length > 0;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">三幕十五节拍卡点规划时间轴</h2>
            <p class="fp-card-sub">04 阶段子视图：时间轴。与“卡点说明”共用同一个后端阶段。</p>

          </div>
          ${stageStatusTag("beat")}
        </div>
        ${confirmed ? `<div class="fp-inline-warning">04 阶段已确认并锁定，05 人物故事线会严格基于这 15 个节拍继续拆解。</div>` : ""}
        ${isStageLoading("beat") ? renderProcessingBanner("正在生成三幕十五节拍时间轴，请稍候...") : ""}
        ${blocked && !hasTimeline ? `<div class="fp-empty">请先确认人设方案。</div>` : renderBeatTimeline(state.beat_checkpoint_timeline, { editable: !blocked && !confirmed })}
        ${renderStagePreferenceField("beat", blocked || confirmed || isStageLoading("beat"))}
        ${renderStageHistoryPanel("beat")}
        ${renderStageError("beat")}
        <div class="fp-lock-note">时间轴可直接编辑；修改节拍后会同步卡点说明，并清空已失效的 05 人物故事线。</div>
        <div class="fp-actions">
          ${renderUpstreamRollbackButton("beat")}
          ${confirmed ? `<button class="fp-btn danger" data-action="rollback-stage" data-stage-key="beat">回退 04 三幕十五节拍阶段</button>` : ""}
          <button class="fp-btn primary" data-action="confirm-stage" data-stage-key="beat" ${blocked || confirmed || !canConfirm ? "disabled" : ""}>确认并进入人物故事线</button>
        </div>
      </section>
    `;
  }

  function renderBeatTimeline(items, options) {
    if (!Array.isArray(items) || !items.length) {
      return `<div class="fp-empty">尚未生成 04 阶段时间轴。确认 03 后，才能生成 15 条固定顺序的 beat_checkpoint_timeline。</div>`;
    }
    const editable = Boolean(options && options.editable);
    const nodes = items.map((item) => {
      const explanation = beatExplanationFor(item.beat_no);
      return `
      <article class="fp-beat-node">
        <div class="fp-beat-act">${escapeHtml(item.act || "")}</div>
        <div class="fp-beat-title">${escapeHtml(`${item.beat_no}. ${item.beat_name}`)}</div>
        <div class="fp-beat-dot"></div>
        <div class="fp-beat-range">${escapeHtml(item.episode_range || "")}</div>
        ${explanation ? `<div class="fp-beat-node-summary">${escapeHtml(explanation)}</div>` : ""}
      </article>
    `}).join("");
    const cards = items.map((item, index) => {
      const explanation = beatExplanationFor(item.beat_no);
      const summary = beatSummaryText(item, explanation);
      const isOpen = Boolean(ui.expandedBeats[String(item.beat_no || index + 1)]);
      return `
      <details class="fp-beat-card fp-beat-detail" data-beat-detail="${escapeHtml(item.beat_no || index + 1)}" ${isOpen ? "open" : ""}>
        <summary>
          <span>
            <strong>${escapeHtml(`${item.beat_no}. ${item.beat_name}`)}</strong>
            <em>${escapeHtml(item.act || "")} · ${escapeHtml(item.episode_range || "")}</em>
          </span>
          <small>${escapeHtml(summary)}</small>
        </summary>
        <div class="fp-beat-detail-body">
          <div class="fp-beat-meta">${escapeHtml(item.checkpoint_title || "")}</div>
          ${explanation ? `<div class="fp-beat-explain"><strong>卡点说明：</strong>${escapeHtml(explanation)}</div>` : ""}
          ${renderBeatField(index, "episode_range", "集数范围", item.episode_range, editable)}
          ${renderBeatField(index, "checkpoint_title", "卡点标题", item.checkpoint_title, editable)}
          ${renderBeatField(index, "narrative_function", "叙事功能", item.narrative_function, editable)}
          ${renderBeatField(index, "plot_content", "剧情内容", item.plot_content, editable)}
          ${renderBeatField(index, "character_change", "人物变化", item.character_change, editable)}
          ${renderBeatField(index, "conflict_upgrade", "冲突升级", item.conflict_upgrade, editable)}
          ${renderBeatField(index, "hook_or_reversal", "钩子 / 反转", item.hook_or_reversal, editable)}
          ${renderBeatField(index, "linked_storylines", "关联故事线", (item.linked_storylines || []).join("、"), editable)}
        </div>
      </details>
    `}).join("");
    return `
      <div class="fp-timeline-wrap"><div class="fp-timeline">${nodes}</div></div>
      <div class="fp-json-meta">当前共 ${items.length} 条节拍，确认按钮要求固定为 15 条。</div>
      <div class="fp-beat-card-grid">${cards}</div>
    `;
  }

  function beatSummaryText(item, explanation) {
    const text = explanation || item.hook_or_reversal || item.plot_content || item.narrative_function || item.checkpoint_title || "";
    return truncateText(text, 72);
  }

  function renderBeatField(index, field, label, value, editable) {
    const text = value == null ? "" : String(value);
    if (!editable) {
      return `<p><strong>${escapeHtml(label)}：</strong>${formatText(text)}</p>`;
    }
    const isShort = ["episode_range", "checkpoint_title", "linked_storylines"].includes(field);
    if (isShort) {
      return `
        <label class="fp-beat-edit-field">
          <span>${escapeHtml(label)}</span>
          <input data-beat-index="${index}" data-beat-field="${escapeHtml(field)}" value="${escapeHtml(text)}" />
        </label>
      `;
    }
    return `
      <label class="fp-beat-edit-field">
        <span>${escapeHtml(label)}</span>
        <textarea data-beat-index="${index}" data-beat-field="${escapeHtml(field)}">${escapeHtml(text)}</textarea>
      </label>
    `;
  }

  function beatExplanationFor(beatNo) {
    const explanation = state.checkpoint_explanation;
    if (!explanation || typeof explanation !== "object" || Array.isArray(explanation)) return "";
    const notes = Array.isArray(explanation.beat_notes) ? explanation.beat_notes : [];
    const note = notes.find((item) => Number(item && item.beat_no) === Number(beatNo));
    if (!note || typeof note !== "object") return "";
    return note.explanation || note.summary || note.note || note.content || "";
  }

  function renderCheckpointExplanation(data, options) {
    if (isEmptyValue(data)) {
      return `<div class="fp-empty">尚未生成卡点说明。生成 04 阶段后，这里会展示每个节拍的解释摘要。</div>`;
    }
    const editable = Boolean(options && options.editable);
    const overview = data && typeof data === "object" && !Array.isArray(data) ? (data.overview || data.summary || "") : String(data || "");
    const notes = data && typeof data === "object" && Array.isArray(data.beat_notes) ? data.beat_notes : [];
    return `
      <div class="fp-stage-note">
        <strong>整体说明</strong>
        ${editable ? `<textarea class="fp-checkpoint-overview" data-checkpoint-overview>${escapeHtml(overview)}</textarea>` : `<div class="fp-text">${formatText(overview)}</div>`}
      </div>
      <div class="fp-beat-card-grid">
        ${notes.map((note, index) => `
          <article class="fp-beat-card">
            <h3>${escapeHtml(`${note.beat_no || index + 1}. ${BEAT_NAMES[(Number(note.beat_no) || index + 1) - 1] || "卡点说明"}`)}</h3>
            ${editable ? `
              <label class="fp-beat-edit-field">
                <span>说明摘要</span>
                <textarea data-beat-note-index="${index}">${escapeHtml(note.explanation || note.summary || note.note || note.content || "")}</textarea>
              </label>
            ` : `<p>${formatText(note.explanation || note.summary || note.note || note.content || "")}</p>`}
          </article>
        `).join("")}
      </div>
    `;
  }

  function renderProcessingBanner(message) {
    return `
      <div class="fp-processing-banner">
        <span class="fp-spinner" aria-hidden="true"></span>
        <span>${escapeHtml(message)}</span>
      </div>
    `;
  }

  function renderBeatExplanationView() {
    const stage = state.stage_state.beat;
    const blocked = stageBlockedByUpstream(stage);
    const confirmed = stage.confirmed;
    const hasExplanation = !isEmptyValue(state.checkpoint_explanation);
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">三幕十五节拍卡点说明</h2>
            <p class="fp-card-sub">04 阶段子视图：卡点说明。与“时间轴”共用同一个后端阶段。</p>
          </div>
          ${stageStatusTag("beat")}
        </div>
        ${isStageLoading("beat") ? renderProcessingBanner("正在生成卡点说明，请稍候...") : ""}
        ${blocked && !hasExplanation ? `<div class="fp-empty">请先确认人设方案。</div>` : renderCheckpointExplanation(state.checkpoint_explanation, { editable: !blocked && !confirmed })}
        ${renderStagePreferenceField("beat", blocked || confirmed || isStageLoading("beat"))}
        ${renderStageHistoryPanel("beat")}
        <div class="fp-actions">
          ${renderUpstreamRollbackButton("beat")}
          <button class="fp-btn primary" data-action="confirm-stage" data-stage-key="beat" ${blocked || confirmed || state.beat_checkpoint_timeline.length !== 15 || isEmptyValue(state.checkpoint_explanation) ? "disabled" : ""}>确认 04 并进入人物故事线</button>
        </div>
      </section>
    `;
  }

  function renderStorylinesView() {
    const stage = state.stage_state.storylines;
    const blocked = stageBlockedByUpstream(stage);
    const confirmed = stage.confirmed;
    const hasStorylines = Array.isArray(state.character_storylines) && state.character_storylines.length > 0;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">不同人物故事线</h2>
            <p class="fp-card-sub">05 阶段：人物故事线。故事线详情与处理决策分别放在后两个视图中查看和修改。</p>
          </div>
          ${stageStatusTag("storylines")}
        </div>
        ${confirmed ? `<div class="fp-inline-warning">人物故事线已确认并锁定。06 阶段的整体改编指引会以当前故事线取舍为准。</div>` : ""}
        ${isStageLoading("storylines") ? renderProcessingBanner("正在生成人物故事线，请稍候...") : ""}
        ${blocked && !hasStorylines ? `<div class="fp-empty">请先确认 04 阶段。</div>` : renderStorylineCards(state.character_storylines, { concise: true })}
        ${renderStagePreferenceField("storylines", blocked || confirmed || isStageLoading("storylines"))}
        ${renderStageHistoryPanel("storylines")}
        ${renderStageError("storylines")}
        <div class="fp-lock-note">05 阶段由 04 确认后自动生成；如回退 04，人物故事线会同步清空，避免旧故事线引用旧节拍。</div>
        <div class="fp-actions">
          ${renderUpstreamRollbackButton("storylines")}
          ${confirmed ? `<button class="fp-btn danger" data-action="rollback-stage" data-stage-key="storylines">回退 05 人物故事线阶段</button>` : ""}
          <button class="fp-btn" data-action="go-view" data-view="storyline_details" ${!state.character_storylines.length ? "disabled" : ""}>查看详细故事线</button>
          <button class="fp-btn primary" data-action="go-view" data-view="storyline_decisions" ${!state.character_storylines.length ? "disabled" : ""}>进入故事线处理</button>
        </div>
      </section>
    `;
  }

  function renderStorylineDetailsView() {
    const stage = state.stage_state.storylines;
    const blocked = stageBlockedByUpstream(stage);
    const hasStorylines = Array.isArray(state.character_storylines) && state.character_storylines.length > 0;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">查看详细不同人物故事线</h2>
            <p class="fp-card-sub">05 阶段子视图：详情查看。与“故事线总览”“故事线处理”共用同一个后端阶段。</p>
          </div>
          ${stageStatusTag("storylines")}
        </div>
        ${blocked && !hasStorylines ? `<div class="fp-empty">请先确认 04 阶段。</div>` : renderStorylineCards(state.character_storylines, { detailed: true })}
        ${renderStagePreferenceField("storylines", blocked || stage.confirmed || isStageLoading("storylines"))}
        ${renderStageHistoryPanel("storylines")}
        <div class="fp-actions">
          ${renderUpstreamRollbackButton("storylines")}
          <button class="fp-btn" data-action="go-view" data-view="storylines">返回故事线总览</button>
          <button class="fp-btn primary" data-action="go-view" data-view="storyline_decisions" ${!state.character_storylines.length ? "disabled" : ""}>去处理保留 / 精简 / 删除</button>
        </div>
      </section>
    `;
  }

  function renderStorylineDecisionView() {
    const stage = state.stage_state.storylines;
    const blocked = stageBlockedByUpstream(stage);
    const confirmed = stage.confirmed;
    const canConfirm = state.character_storylines.length > 0;
    const hasStorylines = Array.isArray(state.character_storylines) && state.character_storylines.length > 0;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">故事线处理：保留 / 精简 / 删除</h2>
            <p class="fp-card-sub">05 阶段子视图：处理决策。回退会清空整个 05 人物故事线阶段及后续阶段。</p>
          </div>
          ${stageStatusTag("storylines")}
        </div>
        ${blocked && !hasStorylines ? `<div class="fp-empty">请先确认 04 阶段。</div>` : renderStorylineDecisionGrid()}
        ${renderStagePreferenceField("storylines", blocked || confirmed || isStageLoading("storylines"))}
        ${renderStageHistoryPanel("storylines")}
        <div class="fp-actions">
          ${renderUpstreamRollbackButton("storylines")}
          ${confirmed ? `<button class="fp-btn danger" data-action="rollback-stage" data-stage-key="storylines">回退 05 人物故事线阶段</button>` : ""}
          <button class="fp-btn" data-action="go-view" data-view="storyline_details" ${!state.character_storylines.length ? "disabled" : ""}>返回详情查看</button>
          <button class="fp-btn primary" data-action="confirm-stage" data-stage-key="storylines" ${blocked || confirmed || !canConfirm ? "disabled" : ""}>确认并进入整体改编指引</button>
        </div>
      </section>
    `;
  }

  function renderGuideView() {
    const stage = state.stage_state.guide;
    const blocked = stageBlockedByUpstream(stage);
    const confirmed = stage.confirmed;
    const hasGuide = !isEmptyValue(state.adaptation_guide);
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">整体改编指引四项</h2>
          </div>
          ${stageStatusTag("guide")}
        </div>
        ${confirmed ? `<div class="fp-inline-warning">整体改编指引已确认并锁定。现在可以生成最终策划包。</div>` : ""}
        ${isStageLoading("guide") ? renderProcessingBanner("正在生成整体改编指引，请稍候...") : ""}
        ${blocked && !hasGuide ? `<div class="fp-empty">请先确认 05 阶段。</div>` : renderGuideCards(state.adaptation_guide)}
        ${renderStagePreferenceField("guide", blocked || confirmed || isStageLoading("guide"))}
        ${renderStageHistoryPanel("guide")}
        ${renderStageError("guide")}
        <div class="fp-actions">
          ${renderUpstreamRollbackButton("guide")}
          ${confirmed ? `<button class="fp-btn danger" data-action="rollback-stage" data-stage-key="guide">回退 ${escapeHtml(realStageDisplayTitle("guide"))}</button>` : ""}
          <button class="fp-btn primary" data-action="confirm-stage" data-stage-key="guide" ${blocked || confirmed || isEmptyValue(state.adaptation_guide) ? "disabled" : ""}>确认并进入最终输出</button>
        </div>
      </section>
    `;
  }

  function renderPackageView() {
    const locked = state.stage_state.package.locked;
    const hasOutput = !isEmptyValue(state.framework_plan_package);
    const completed = hasOutput && !locked;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">最终策划包输出</h2>
          </div>
          ${locked ? `<span class="fp-tag lock">待上游确认</span>` : hasOutput ? `<span class="fp-tag ok">07 输出已生成</span>` : `<span class="fp-tag blue">等待生成</span>`}
        </div>
        ${isStageLoading("package") ? renderProcessingBanner("正在生成最终策划包，请稍候...") : ""}
        ${completed ? `<div class="fp-complete-banner">框架已完成，可以进入剧本正文阶段。</div>` : ""}
        ${locked && !hasOutput ? `<div class="fp-empty">请先确认 06 阶段。</div>` : `
          ${renderPackageBlocks()}
        `}
        ${renderStagePreferenceField("package", locked || isStageLoading("package"))}
        ${renderStageHistoryPanel("package")}
        <div class="fp-actions">
          ${renderUpstreamRollbackButton("package")}
          ${renderSaveFrameworkButton("")}
          <button class="fp-btn primary" data-action="copy-final-package" ${locked || !hasOutput ? "disabled" : ""}>复制最终策划包</button>
          ${renderFrameworkScriptButton("")}
        </div>
      </section>
    `;
  }

  function renderPackageBlocks() {
    if (isEmptyValue(state.framework_plan_package)) {
      return `<div class="fp-empty">07 阶段尚未执行。确认 06 后，再生成最终策划包。</div>`;
    }
    return `
      <div class="fp-grid two">
        <div class="fp-panel-card">
          <h3 class="fp-panel-title">最终策划包</h3>
          ${renderDataBlock(state.framework_plan_package, { dataKey: "framework_plan_package", stageKey: "package", editable: false })}
        </div>
        <div class="fp-panel-card">
          <h3 class="fp-panel-title">校验报告</h3>
          ${renderDataBlock(state.validation_report, { dataKey: "validation_report", stageKey: "package", editable: false })}
        </div>
      </div>
      <div class="fp-stage-note">
        <strong>当前框架版本</strong>
        <div class="fp-asset-meta">
          <span>资产编号：${escapeHtml((state.asset_state || {}).asset_id || state.project_id || "尚未保存")}</span>
          <span>保存时间：${escapeHtml(formatDateTime((state.asset_state || {}).updated_at || "" ) || "尚未保存")}</span>
          <span>状态：${escapeHtml(assetStatusLabel((state.asset_state || {}).status || "draft"))}</span>
        </div>
      </div>
    `;
  }

  function renderDataBlock(data, options) {
    if (isEmptyValue(data)) {
      return `<div class="fp-empty">当前阶段还没有可展示结果。请先生成，或基于上一版执行更新。</div>`;
    }
    const overview = renderStructuredOutputOverview(data, options || {});
    const form = renderBusinessValue(data, {
      rootKey: options && options.dataKey,
      stageKey: options && options.stageKey,
      path: [],
      keyName: options && options.dataKey,
      depth: 0,
      editable: Boolean(options && options.editable),
      forceOpen: true,
    });
    const rawTree = renderRawDebugBlock(data, options || {});
    return `
      <div class="fp-business-form" data-business-form="${escapeHtml((options && options.dataKey) || "")}">
        ${overview}
        ${form}
        ${rawTree}
      </div>
    `;
  }

  function renderRawDebugBlock(data, options) {
    const dataKey = (options && options.dataKey) || "stage_output";
    return `
      <details class="fp-debug-raw">
        <summary>调试原始数据</summary>
        <div class="fp-tree-toolbar">
          <button class="fp-btn small" data-action="tree-expand-all">全部展开</button>
          <button class="fp-btn small" data-action="tree-collapse-all">全部收起</button>
        </div>
        ${renderTree(data, dataKey, 0, [dataKey])}
      </details>
    `;
  }

  function renderTree(value, keyName = "root", depth = 0, path = []) {
    const clean = stripRawResponseKeys(value);
    if (!isRenderableValue(clean)) return `<div class="fp-empty small">暂无内容</div>`;
    const treeId = encodeBusinessPath(path.length ? path : [keyName]);
    const forcedOpen = ui.rawTreeAllOpen || ui.expandedRawTree[treeId] === true || (depth === 0 && !ui.rawTreeAllCollapsed);
    if (Array.isArray(clean)) {
      const items = clean.filter(isRenderableValue);
      if (!items.length) return `<div class="fp-empty small">暂无条目</div>`;
      return `
        <details class="fp-tree-node" data-tree-node="${escapeHtml(treeId)}" ${forcedOpen ? "open" : ""}>
          <summary><span class="fp-tree-arrow"></span><strong>${escapeHtml(fieldLabel(keyName))}</strong><small>${items.length} 条</small></summary>
          <div class="fp-tree-body">
            ${items.map((item, index) => renderTree(item, `${fieldLabel(keyName)} ${index + 1}`, depth + 1, path.concat(index))).join("")}
            <button type="button" class="fp-btn small ghost fp-collapse-local" data-action="collapse-tree-node">收起本层</button>
          </div>
        </details>
      `;
    }
    if (clean && typeof clean === "object") {
      const entries = Object.keys(clean).filter((key) => !isHiddenTechnicalKey(key) && isRenderableValue(clean[key]));
      if (!entries.length) return `<div class="fp-empty small">暂无内容</div>`;
      return `
        <details class="fp-tree-node" data-tree-node="${escapeHtml(treeId)}" ${forcedOpen ? "open" : ""}>
          <summary><span class="fp-tree-arrow"></span><strong>${escapeHtml(fieldLabel(keyName))}</strong><small>${escapeHtml(summarizeBusinessValue(clean))}</small></summary>
          <div class="fp-tree-body">
            ${entries.map((key) => renderTree(clean[key], key, depth + 1, path.concat(key))).join("")}
            <button type="button" class="fp-btn small ghost fp-collapse-local" data-action="collapse-tree-node">收起本层</button>
          </div>
        </details>
      `;
    }
    const text = String(clean == null ? "" : clean);
    const long = text.length > 420;
    return `
      <div class="fp-tree-leaf">
        <strong>${escapeHtml(fieldLabel(keyName))}</strong>
        ${long ? `
          <details class="fp-tree-text-more">
            <summary>${escapeHtml(truncateText(text, 420))} <span>展开全文</span></summary>
            <div>${formatText(text)}</div>
          </details>
        ` : `<span>${formatText(text)}</span>`}
      </div>
    `;
  }

  function renderStructuredOutputOverview(data, options) {
    if (!data || typeof data !== "object") {
      return `<div class="fp-output-overview"><h3>${escapeHtml(fieldLabel(options.dataKey || "内容"))}</h3><p>${escapeHtml(String(data || ""))}</p></div>`;
    }
    const title = extractOutputTitle(data, options);
    const summary = extractOutputSummary(data);
    const bullets = extractOutputBullets(data);
    return `
      <div class="fp-output-overview">
        <h3>${escapeHtml(title)}</h3>
        ${summary ? `<p>${escapeHtml(summary)}</p>` : ""}
        ${bullets.length ? `<ul>${bullets.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
      </div>
    `;
  }

  function extractOutputTitle(data, options) {
    if (data.title) return data.title;
    if (data.project_title) return data.project_title;
    if (data.name) return data.name;
    return fieldLabel(options.dataKey || options.rootKey || "阶段输出");
  }

  function extractOutputSummary(data) {
    for (const key of ["summary", "overview", "display_text", "core_premise", "input_summary", "recommended_next_action"]) {
      if (typeof data[key] === "string" && data[key].trim()) return truncateText(data[key], 260);
    }
    if (data.handoff_to_script_workflow && typeof data.handoff_to_script_workflow === "object") {
      return truncateText(data.handoff_to_script_workflow.input_summary || data.handoff_to_script_workflow.recommended_next_action || "", 260);
    }
    return summarizeBusinessValue(data);
  }

  function extractOutputBullets(data) {
    const keys = ["passed_checks", "warnings", "blocking_issues", "generation_priorities", "hard_constraints", "do_not_change", "risk_flags"];
    const result = [];
    for (const key of keys) {
      const value = data[key] || (data.validation_report && data.validation_report[key]) || (data.handoff_to_script_workflow && data.handoff_to_script_workflow[key]);
      if (!Array.isArray(value)) continue;
      value.slice(0, 5).forEach((item) => {
        const text = typeof item === "string" ? item : summarizeBusinessValue(item);
        if (text) result.push(`${fieldLabel(key)}：${truncateText(text, 120)}`);
      });
      if (result.length >= 6) break;
    }
    return result.slice(0, 6);
  }

  function renderPayloadSummary(payload) {
    const cleaned = cleanOutgoingPayload(payload || {});
    const entries = Object.keys(cleaned).filter((key) => !isHiddenTechnicalKey(key) && isRenderableValue(cleaned[key]));
    if (!entries.length) return `<div class="fp-empty small">当前没有可发送的业务字段。</div>`;
    return `
      <div class="fp-business-form compact">
        ${entries.map((key) => `
          <div class="fp-detail-item">
            <strong>${escapeHtml(fieldLabel(key))}</strong>
            <span>${escapeHtml(summarizeBusinessValue(cleaned[key]))}</span>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderBusinessValue(value, context) {
    const path = Array.isArray(context.path) ? context.path : [];
    const depth = Number(context.depth || 0);
    if (Array.isArray(value)) {
      return renderBusinessArray(value, context, path, depth);
    }
    if (value && typeof value === "object") {
      return renderBusinessObject(value, context, path, depth);
    }
    return renderBusinessPrimitive(value, context, path);
  }

  function renderBusinessObject(value, context, path, depth) {
    const entries = Object.keys(value || {}).filter((key) => !isHiddenTechnicalKey(key) && isRenderableValue(value[key]));
    if (!entries.length) return `<div class="fp-empty small">暂无内容</div>`;
    const title = fieldLabel(context.keyName || path[path.length - 1] || "内容");
    const panelKey = businessPanelKey(context.rootKey, path);
    const open = context.forceOpen || depth === 0 || isCoreBusinessKey(context.keyName) || ui.expandedBusinessPanels[panelKey] === true;
    const content = entries.map((key) => {
      const nextValue = value[key];
      const nextPath = path.concat(key);
      return renderBusinessValue(nextValue, Object.assign({}, context, {
        path: nextPath,
        keyName: key,
        depth: depth + 1,
        forceOpen: false,
      }));
    }).join("");
    if (depth === 0) {
      return `<div class="fp-business-root">${content}</div>`;
    }
    return `
      <details class="fp-business-panel" data-business-panel="${escapeHtml(panelKey)}" ${open ? "open" : ""}>
        <summary>
          <strong>${escapeHtml(title)}</strong>
          <small>${escapeHtml(summarizeBusinessValue(value))}</small>
        </summary>
        <div class="fp-business-panel-body">${content}</div>
      </details>
    `;
  }

  function renderBusinessArray(value, context, path, depth) {
    const title = fieldLabel(context.keyName || path[path.length - 1] || "列表");
    const panelKey = businessPanelKey(context.rootKey, path);
    const open = context.forceOpen || isCoreBusinessKey(context.keyName) || ui.expandedBusinessPanels[panelKey] === true;
    const visibleItems = value.filter(isRenderableValue);
    if (!visibleItems.length) return `<div class="fp-empty small">暂无条目</div>`;
    const items = visibleItems.map((item, index) => {
      const itemPath = path.concat(index);
      const itemKey = businessPanelKey(context.rootKey, itemPath);
      const itemOpen = index === 0 || ui.expandedBusinessPanels[itemKey] === true;
      const itemTitle = businessItemTitle(item, index, title);
      if (item && typeof item === "object") {
        return `
          <details class="fp-business-panel fp-business-item" data-business-panel="${escapeHtml(itemKey)}" ${itemOpen ? "open" : ""}>
            <summary>
              <strong>${escapeHtml(itemTitle)}</strong>
              <small>${escapeHtml(summarizeBusinessValue(item))}</small>
            </summary>
            <div class="fp-business-panel-body">
              ${renderBusinessValue(item, Object.assign({}, context, {
                path: itemPath,
                keyName: `${title} ${index + 1}`,
                depth: depth + 1,
                forceOpen: true,
              }))}
            </div>
          </details>
        `;
      }
      return renderBusinessPrimitive(item, Object.assign({}, context, { keyName: `${title} ${index + 1}` }), itemPath);
    }).join("");
    return `
      <details class="fp-business-panel" data-business-panel="${escapeHtml(panelKey)}" ${open ? "open" : ""}>
        <summary>
          <strong>${escapeHtml(title)}</strong>
          <small>${escapeHtml(`${visibleItems.length} 条 · ${summarizeBusinessValue(visibleItems)}`)}</small>
        </summary>
        <div class="fp-business-panel-body">${items || `<div class="fp-empty small">暂无条目</div>`}</div>
      </details>
    `;
  }

  function renderBusinessPrimitive(value, context, path) {
    const label = fieldLabel(context.keyName || path[path.length - 1] || "内容");
    if (!isRenderableValue(value)) return "";
    const encodedPath = encodeBusinessPath(path);
    const disabled = context.editable ? "" : "disabled";
    const type = typeof value;
    const stringValue = value == null ? "" : String(value);
    if (type === "boolean") {
      return `
        <label class="fp-business-field">
          <span>${escapeHtml(label)}</span>
          <select data-business-root="${escapeHtml(context.rootKey)}" data-business-stage="${escapeHtml(context.stageKey)}" data-business-path="${escapeHtml(encodedPath)}" ${disabled}>
            <option value="true" ${value ? "selected" : ""}>是</option>
            <option value="false" ${!value ? "selected" : ""}>否</option>
          </select>
        </label>
      `;
    }
    const numeric = type === "number";
    const multiline = stringValue.length > 80 || /\n/.test(stringValue);
    return `
      <label class="fp-business-field">
        <span>${escapeHtml(label)}</span>
        ${multiline ? `
          <textarea data-business-root="${escapeHtml(context.rootKey)}" data-business-stage="${escapeHtml(context.stageKey)}" data-business-path="${escapeHtml(encodedPath)}" data-business-type="${numeric ? "number" : "string"}" ${disabled}>${escapeHtml(stringValue)}</textarea>
        ` : `
          <input type="${numeric ? "number" : "text"}" data-business-root="${escapeHtml(context.rootKey)}" data-business-stage="${escapeHtml(context.stageKey)}" data-business-path="${escapeHtml(encodedPath)}" data-business-type="${numeric ? "number" : "string"}" value="${escapeHtml(stringValue)}" ${disabled} />
        `}
      </label>
    `;
  }

  function businessPanelKey(rootKey, path) {
    return `${rootKey || "root"}:${(path || []).join(".")}`;
  }

  function isCoreBusinessKey(key) {
    return ["protagonist", "main_characters", "beat_checkpoint_timeline", "checkpoint_explanation"].includes(String(key || ""));
  }

  function encodeBusinessPath(path) {
    return encodeURIComponent(JSON.stringify(path || []));
  }

  function decodeBusinessPath(value) {
    try {
      const parsed = JSON.parse(decodeURIComponent(String(value || "%5B%5D")));
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function summarizeBusinessValue(value) {
    if (Array.isArray(value)) return value.slice(0, 3).map((item, index) => businessItemTitle(item, index, "条目")).join(" / ");
    if (value && typeof value === "object") {
      const preferred = ["summary", "overview", "goal", "motivation", "plot_content", "core_premise", "title", "name"];
      for (const key of preferred) {
        if (value[key]) return truncateText(value[key], 96);
      }
      return Object.keys(value).slice(0, 5).map(fieldLabel).join("、");
    }
    return truncateText(value, 96);
  }

  function businessItemTitle(item, index, fallback) {
    if (item && typeof item === "object") {
      return item.name || item.title || item.beat_name || item.role || `${fallback || "条目"} ${index + 1}`;
    }
    return `${fallback || "条目"} ${index + 1}`;
  }

  function formatEpisodeDistributionLines(value) {
    if (!Array.isArray(value) || !value.length) return "";
    return value.map((segment) => {
      if (segment && typeof segment === "object") {
        return `${segment.episode_range || ""} | ${segment.focus || segment.summary || segment.note || ""}`.trim();
      }
      return String(segment || "");
    }).filter(Boolean).join("\n");
  }

  function parseEpisodeDistributionLines(text) {
    return String(text || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const parts = line.split("|");
        if (parts.length > 1) {
          return {
            episode_range: parts.shift().trim(),
            focus: parts.join("|").trim(),
          };
        }
        return { episode_range: "", focus: line };
      });
  }

  function renderEditorBlock(editorKey, title) {
    return `
      <div class="fp-field fp-editor">
        <label>编辑${escapeHtml(title)}</label>
        <textarea data-editor-key="${editorKey}">${escapeHtml(editorValueFor(editorKey))}</textarea>
      </div>
    `;
  }

  function renderBeatNoteError(message) {
    return message ? `<div class="fp-inline-warning">${escapeHtml(message)}</div>` : "";
  }

  function renderStageError(stageKey) {
    const message = ui.stageErrors[stageKey];
    return renderBeatNoteError(message);
  }

  function renderStorylineCards(items, options) {
    if (!Array.isArray(items) || !items.length) {
      return `<div class="fp-empty">尚未生成人物故事线。</div>`;
    }
    return `<div class="fp-story-grid">${items.map((item) => {
      const distribution = (item.episode_distribution || []).map((segment) => `
        <div class="fp-detail-item">
          <strong>${escapeHtml(segment.episode_range || "未标注集数")}</strong>
          ${escapeHtml(segment.focus || "")}
        </div>
      `).join("");
      const linkedBeats = Array.isArray(item.linked_beats) ? item.linked_beats : [];
      const storylineId = String(item.id || item.title || "");
      const isOpen = Boolean(ui.expandedStorylines[storylineId]);
      const summary = storylineSummaryText(item);
      const meta = [
        item.character_name || item.title || "",
        item.line_type || "",
        item.importance ? `重要性：${item.importance}` : "",
      ].filter(Boolean).join(" · ");
      return `
        <details class="fp-story-card fp-story-detail" data-storyline-detail="${escapeHtml(storylineId)}" ${isOpen || (options && options.detailed) ? "open" : ""}>
          <summary>
            <div class="fp-story-head">
              <div>
                <h3>${escapeHtml(item.title || item.character_name || "未命名人物线")}</h3>
                ${meta ? `<em>${escapeHtml(meta)}</em>` : ""}
              </div>
              <span class="fp-tag ${decisionTagClass(item.decision)}">${escapeHtml(decisionLabel(item.decision))}</span>
            </div>
            <p><strong>摘要：</strong>${escapeHtml(summary)}</p>
            ${linkedBeats.length ? `<div class="fp-story-beats">${linkedBeats.map((beat) => `<span>Beat ${escapeHtml(beat)}</span>`).join("")}</div>` : `<div class="fp-story-beats muted"><span>未链接节拍</span></div>`}
          </summary>
          <div class="fp-story-detail-body">
            <div class="fp-detail-list">
              <div class="fp-detail-item"><strong>重要决策</strong>${escapeHtml(decisionLabel(item.decision))}</div>
              <div class="fp-detail-item"><strong>详细剧情</strong>${formatText(item.detailed_storyline || "尚未补充详细人物线。")}</div>
              <div class="fp-detail-item"><strong>关联节拍</strong>${escapeHtml(linkedBeats.length ? linkedBeats.join("、") : "尚未链接")}</div>
              <div class="fp-detail-item"><strong>编辑备注</strong>${escapeHtml(item.edit_notes || "暂无备注")}</div>
            </div>
            ${distribution ? `<div class="fp-detail-list" style="margin-top:12px">${distribution}</div>` : ""}
            <div class="fp-actions" style="margin-top:12px">
              <button class="fp-btn small" data-action="open-storyline-modal" data-storyline-id="${escapeHtml(item.id)}">编辑 / 补充</button>
              ${options && options.concise ? `<button class="fp-btn small" data-action="go-view" data-view="storyline_decisions">去做处理决策</button>` : ""}
            </div>
          </div>
        </details>
      `;
    }).join("")}</div>`;
  }

  function storylineSummaryText(item) {
    return item.summary || item.detailed_storyline || item.edit_notes || "尚未补充摘要。";
  }

  function renderStorylineDecisionGrid() {
    if (!Array.isArray(state.character_storylines) || !state.character_storylines.length) {
      return `<div class="fp-empty">尚未生成人物故事线。</div>`;
    }
    return `
      <div class="fp-story-grid">
        ${state.character_storylines.map((item) => `
          <details class="fp-story-card fp-story-detail" data-storyline-detail="${escapeHtml(item.id || item.title || "")}" ${ui.expandedStorylines[String(item.id || item.title || "")] ? "open" : ""}>
            <summary>
            <div class="fp-story-head">
              <div>
                <h3>${escapeHtml(item.title || item.character_name || "未命名人物线")}</h3>
                <em>${escapeHtml([item.line_type || "", item.importance ? `重要性：${item.importance}` : ""].filter(Boolean).join(" · "))}</em>
              </div>
              <span class="fp-tag ${decisionTagClass(item.decision)}">${escapeHtml(decisionLabel(item.decision))}</span>
            </div>
            <p><strong>摘要：</strong>${escapeHtml(storylineSummaryText(item))}</p>
            ${Array.isArray(item.linked_beats) && item.linked_beats.length ? `<div class="fp-story-beats">${item.linked_beats.map((beat) => `<span>Beat ${escapeHtml(beat)}</span>`).join("")}</div>` : ""}
            </summary>
            <div class="fp-story-detail-body">
            <div class="fp-radio-row">
              ${STORYLINE_DECISIONS.map(([value, label]) => `
                <label>
                  <input type="radio" name="storyline-${escapeHtml(item.id)}" data-action="change-storyline-decision" data-storyline-id="${escapeHtml(item.id)}" value="${value}" ${item.decision === value ? "checked" : ""} ${state.stage_state.storylines.confirmed ? "disabled" : ""} />
                  ${escapeHtml(label)}
                </label>
              `).join("")}
            </div>
            <div class="fp-actions" style="margin-top:0">
              <button class="fp-btn small" data-action="open-storyline-modal" data-storyline-id="${escapeHtml(item.id)}">查看并编辑细节</button>
            </div>
            </div>
          </details>
        `).join("")}
      </div>
    `;
  }

  function renderStorylineModal(storylineId) {
    const storyline = state.character_storylines.find((item) => item.id === storylineId);
    if (!storyline) return "";
    return `
      <div class="fp-modal-mask" data-action="close-storyline-modal">
        <div class="fp-modal" data-modal-content="storyline">
          <div class="fp-modal-head">
            <div>
              <h2>${escapeHtml(storyline.title || "")}</h2>
            </div>
            <button class="fp-btn small" data-action="close-storyline-modal">关闭</button>
          </div>
          <div class="fp-field">
            <label>标题</label>
            <input data-modal-field="title" value="${escapeHtml(storyline.title || "")}" />
          </div>
          <div class="fp-field">
            <label>摘要</label>
            <textarea data-modal-field="summary">${escapeHtml(storyline.summary || "")}</textarea>
          </div>
          <div class="fp-field" style="margin-top:12px">
            <label>详细剧情</label>
            <textarea data-modal-field="detailed_storyline">${escapeHtml(storyline.detailed_storyline || "")}</textarea>
          </div>
          <div class="fp-grid two" style="margin-top:12px">
            <div class="fp-field">
              <label>关联节拍（逗号分隔）</label>
              <input data-modal-field="linked_beats" value="${escapeHtml((storyline.linked_beats || []).join(", "))}" />
            </div>
            <div class="fp-field">
              <label>处理决策</label>
              <select data-modal-field="decision">
                ${STORYLINE_DECISIONS.map(([value, label]) => `<option value="${value}" ${storyline.decision === value ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}
              </select>
            </div>
          </div>
          <div class="fp-field" style="margin-top:12px">
            <label>分集安排（每行一条：集数 | 重点）</label>
            <textarea data-modal-field="episode_distribution">${escapeHtml(formatEpisodeDistributionLines(storyline.episode_distribution || []))}</textarea>
          </div>
          <div class="fp-field" style="margin-top:12px">
            <label>编辑备注</label>
            <textarea data-modal-field="edit_notes">${escapeHtml(storyline.edit_notes || "")}</textarea>
          </div>
          <div class="fp-actions">
            <button class="fp-btn" data-action="close-storyline-modal">关闭</button>
            <button class="fp-btn primary" data-action="save-storyline-modal" data-storyline-id="${escapeHtml(storyline.id)}">更新故事线</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderGuideCards(data) {
    if (isEmptyValue(data)) {
      return `<div class="fp-empty">尚未生成整体改编指引。</div>`;
    }
    const cards = [
      ["core_setting_adjustments", "1. 核心设定调整"],
      ["structure_and_rhythm", "2. 叙事节奏与结构"],
      ["visualization_strategy", "3. 视觉化呈现"],
      ["character_emotion_strategy", "4. 角色与情绪塑造"],
    ];
    return `
      <div class="fp-guide-grid">
        ${cards.map(([key, label]) => `
          <article class="fp-guide-card">
            <h3>${escapeHtml(label)}</h3>
            <p>${escapeHtml((data && data[key]) || "")}</p>
          </article>
        `).join("")}
      </div>
    `;
  }

  function renderFooter() {
    const currentIndex = VIEW_DEFS.findIndex((item) => item.id === state.current_view);
    const previous = VIEW_DEFS[currentIndex - 1];
    const next = VIEW_DEFS[currentIndex + 1];
    return `
      <div class="fp-footer">
        <div class="fp-footer-note">localStorage 自动保存已开启。上游确认后不能直接改；如需修改，请使用显式回退。</div>
        <div class="fp-top-actions">
          <button class="fp-btn" data-action="go-view" data-view="${previous ? previous.id : ""}" ${previous && viewUnlocked(previous.id) ? "" : "disabled"}>上一步</button>
          <button class="fp-btn primary" data-action="go-next-stage" data-view="${next ? next.id : ""}" ${next && viewUnlocked(next.id) ? "" : "disabled"}>下一步</button>
        </div>
      </div>
    `;
  }

  async function goNextStage(nextViewId) {
    const currentStageKey = stageKeyForView(state.current_view);
    const nextView = viewDef(nextViewId);
    if (!nextView || !viewUnlocked(nextView.id)) {
      showToast("请先确认上游阶段");
      return;
    }
    state.current_view = nextView.id;
    render();
    loadStageHistory(nextView.stageKey).catch(() => {});
    const nextStageKey = nextView.stageKey;
    if (nextStageKey !== currentStageKey) {
      await autoGenerateCurrentStage();
    }
  }

  async function autoGenerateCurrentStage() {
    const stageKey = stageKeyForView(state.current_view);
    const stage = state.stage_state[stageKey];
    if (!stage || stageKey === "basic" || stage.confirmed || stage.locked || hasStageData(stageKey) || isStageLoading(stageKey)) {
      return;
    }
    try {
      await runStage(stageKey, { revise: false });
      showToast("已进入下一阶段并开始生成");
    } catch (error) {
      showToast(formatStageError(error, stageNoForKey(stageKey)));
    }
  }

  function decisionLabel(value) {
    return {
      keep: "保留",
      simplify: "精简",
      delete: "删除",
    }[value] || "保留";
  }

  function decisionTagClass(value) {
    return {
      keep: "blue",
      simplify: "warn",
      delete: "red",
    }[value] || "blue";
  }

  function buildWorkingPayload() {
    return {
      basic_config: clone(state.basic_config),
      source_brief: clone(state.source_brief),
      worldview_plan: clone(state.worldview_plan),
      character_plan: clone(state.character_plan),
      beat_checkpoint_timeline: clone(state.beat_checkpoint_timeline),
      checkpoint_explanation: clone(state.checkpoint_explanation),
      character_storylines: clone(state.character_storylines),
      storyline_decisions: clone(state.storyline_decisions),
      adaptation_guide: clone(state.adaptation_guide),
      user_edit_history: clone(state.user_edit_history),
      framework_plan_package: clone(state.framework_plan_package),
      validation_report: clone(state.validation_report),
      _meta: {
        framework_score_report: state.framework_score_report,
        beat_revision_round: state.beat_revision_round,
        stage_state: clone(state.stage_state),
      },
    };
  }

  function positiveNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : fallback;
  }

  function frameworkToScriptPayload() {
    syncBasicConfigFromDom();
    const basic = state.basic_config || {};
    const seasonCount = positiveNumber(basic.season_count, 1);
    const episodesPerSeason = positiveNumber(basic.episodes_per_season, 60);
    const totalEpisodes = positiveNumber(basic.total_episodes, seasonCount * episodesPerSeason);
    const minutesPerEpisode = positiveNumber(basic.minutes_per_episode, 2);
    const title = String(basic.project_title || basic.source_title || "未命名框架剧本").trim();
    const knowledgeFields = knowledgePayloadFields("package");
    const payload = Object.assign({
      title,
      project_title: title,
      source_title: String(basic.source_title || title).trim(),
      target_format: String(basic.target_format || "短剧").trim(),
      season_count: seasonCount,
      episodes_per_season: episodesPerSeason,
      total_episodes: totalEpisodes,
      minutes_per_episode: minutesPerEpisode,
      episode_word_count: basic.episode_word_count ? positiveNumber(basic.episode_word_count, undefined) : undefined,
      source_framework_project_id: currentProjectId(),
      project_id: currentProjectId(),
      user_expectation: [
        String(basic.adaptation_direction || "").trim(),
        String(basic.user_constraints || "").trim(),
        payloadUserRequirements(),
      ].filter(Boolean).join("\n\n"),
      user_requirements: payloadUserRequirements(),
      adaptation_direction: String(basic.adaptation_direction || "").trim(),
      basic_config: clone(basic),
      framework_plan_package: clone(state.framework_plan_package),
      source_brief: clone(state.source_brief),
      worldview_plan: clone(state.worldview_plan),
      character_plan: clone(state.character_plan),
      beat_checkpoint_timeline: clone(state.beat_checkpoint_timeline),
      checkpoint_explanation: clone(state.checkpoint_explanation),
      character_storylines: clone(state.character_storylines),
      storyline_decisions: clone(state.storyline_decisions),
      adaptation_guide: clone(state.adaptation_guide),
      prompt_preferences: clone(state.prompt_preferences || {}),
      workflow_mode: "framework_to_script",
      generation_chain: "framework_to_script",
      framework_to_script: true,
      framework_planner_source: true,
    }, knowledgeFields);
    payload.prompt_preferences = clone(state.prompt_preferences || {});
    if (state.user_knowledge_step_prompts) {
      payload.user_knowledge_step_prompts = clone(state.user_knowledge_step_prompts);
    } else if ((state.prompt_preferences || {}).step_prompts) {
      payload.user_knowledge_step_prompts = clone(state.prompt_preferences.step_prompts);
    }
    return cleanOutgoingPayload(payload, "framework_to_script payload");
  }

  function frameworkAssetSavePayload() {
    syncBasicConfigFromDom();
    const knowledgeFields = knowledgePayloadFields("package");
    const assetState = clone(state.asset_state || {});
    const projectId = currentProjectId();
    if (Number(projectId) > 0) {
      assetState.asset_id = Number(projectId);
      assetState.project_id = Number(projectId);
    }
    const payload = Object.assign({
      project_id: Number(projectId) > 0 ? Number(projectId) : null,
      asset_kind: "framework_planner",
      project_title: state.basic_config.project_title || state.basic_config.source_title || "未命名框架策划",
      title: state.basic_config.project_title || state.basic_config.source_title || "未命名框架策划",
      basic_config: clone(state.basic_config),
      source_brief: clone(state.source_brief),
      worldview_plan: clone(state.worldview_plan),
      character_plan: clone(state.character_plan),
      beat_checkpoint_timeline: clone(state.beat_checkpoint_timeline),
      checkpoint_explanation: clone(state.checkpoint_explanation),
      character_storylines: clone(state.character_storylines),
      storyline_decisions: clone(state.storyline_decisions),
      adaptation_guide: clone(state.adaptation_guide),
      framework_plan_package: clone(state.framework_plan_package),
      validation_report: clone(state.validation_report),
      display_texts: clone(state.display_texts || {}),
      prompt_preferences: clone(state.prompt_preferences || {}),
      asset_state: assetState,
      stage_state: clone(state.stage_state || {}),
      current_view: state.current_view || "basic",
      created_at: assetState.created_at || "",
      updated_at: new Date().toISOString(),
    }, knowledgeFields);
    payload.prompt_preferences = clone(state.prompt_preferences || {});
    return cleanOutgoingPayload(payload, "framework_asset_save payload");
  }

  function payloadUserRequirements() {
    const parts = [];
    const base = String(state.basic_config.user_requirements || "").trim();
    const preference = String((state.prompt_preferences || {}).script_preference || "").trim();
    if (base) parts.push(base);
    if (preference && preference !== base) parts.push(`用户偏好提示：${preference}`);
    return parts.join("\n\n");
  }

  function syncBasicConfigFromDom() {
    if (!app || !state || !state.basic_config) return;
    app.querySelectorAll("[data-config-key]").forEach((field) => {
      const key = field.dataset.configKey;
      if (!key || field.disabled) return;
      state.basic_config[key] = field.type === "number" ? Number(field.value) : field.value;
    });
  }

  function collectNewScriptFormFromDom() {
    const next = Object.assign({}, ui.newScriptForm || {});
    app.querySelectorAll("[data-new-script-field]").forEach((field) => {
      const key = field.dataset.newScriptField;
      if (!key) return;
      next[key] = field.type === "number" ? Number(field.value) : field.value;
    });
    ui.newScriptForm = next;
    return next;
  }

  function stageFeedbackPayload(stageKey) {
    const parts = [];
    const explicit = String((state.feedback || {})[stageKey] || "").trim();
    const preference = String(((state.prompt_preferences || {}).stage_prompts || {})[stageKey] || "").trim();
    if (explicit) parts.push(explicit);
    if (preference && preference !== explicit) parts.push(`用户偏好提示：${preference}`);
    return parts.join("\n\n");
  }

  function buildStagePayload(stageKey, options) {
    syncBasicConfigFromDom();
    const revise = options && options.revise;
    if (stageKey === "basic") {
      return {
        project_title: state.basic_config.project_title,
        mode: state.basic_config.mode,
        source_text: state.basic_config.source_text,
        source_title: state.basic_config.source_title || state.basic_config.project_title,
        target_format: state.basic_config.target_format,
        season_count: state.basic_config.season_count,
        episodes_per_season: state.basic_config.episodes_per_season,
        minutes_per_episode: state.basic_config.minutes_per_episode,
        adaptation_direction: state.basic_config.adaptation_direction,
        user_constraints: state.basic_config.user_constraints,
        user_requirements: payloadUserRequirements(),
      };
    }
    if (stageKey === "worldview") {
      return {
        mode: revise ? "改写" : "创作",
        source_brief: state.source_brief,
        locked_basic_config: state.basic_config,
        basic_config: state.basic_config,
        previous_worldview_plan: revise ? state.worldview_plan : {},
        user_feedback: stageFeedbackPayload("worldview"),
        adaptation_direction: state.basic_config.adaptation_direction,
        user_requirements: payloadUserRequirements(),
      };
    }
    if (stageKey === "character") {
      return {
        mode: revise ? "改写" : "创作",
        source_brief: state.source_brief,
        locked_basic_config: state.basic_config,
        basic_config: state.basic_config,
        worldview_plan: state.worldview_plan,
        previous_character_plan: revise ? state.character_plan : {},
        user_feedback: stageFeedbackPayload("character"),
        adaptation_direction: state.basic_config.adaptation_direction,
        user_requirements: payloadUserRequirements(),
      };
    }
    if (stageKey === "beat") {
      return {
        mode: revise ? "改写" : "创作",
        source_brief: state.source_brief,
        basic_config: state.basic_config,
        worldview_plan: state.worldview_plan,
        character_plan: state.character_plan,
        previous_beat_checkpoint_timeline: revise ? state.beat_checkpoint_timeline : [],
        user_feedback: stageFeedbackPayload("beat"),
        framework_score_report: state.framework_score_report,
        adaptation_direction: state.basic_config.adaptation_direction,
        user_requirements: payloadUserRequirements(),
      };
    }
    if (stageKey === "storylines") {
      return cleanStage05Payload({
        mode: revise ? "改写" : "创作",
        source_brief: state.source_brief,
        basic_config: state.basic_config,
        worldview_plan: state.worldview_plan,
        character_plan: state.character_plan,
        beat_checkpoint_timeline: state.beat_checkpoint_timeline,
        previous_character_storylines: revise ? state.character_storylines : [],
        current_storyline_decisions: state.storyline_decisions,
        user_feedback: stageFeedbackPayload("storylines"),
        adaptation_direction: state.basic_config.adaptation_direction,
        user_requirements: payloadUserRequirements(),
      });
    }
    if (stageKey === "guide") {
      return {
        mode: revise ? "改写" : "创作",
        source_brief: state.source_brief,
        basic_config: state.basic_config,
        worldview_plan: state.worldview_plan,
        character_plan: state.character_plan,
        beat_checkpoint_timeline: state.beat_checkpoint_timeline,
        character_storylines: state.character_storylines,
        storyline_decisions: state.storyline_decisions,
        previous_adaptation_guide: revise ? state.adaptation_guide : {},
        user_feedback: stageFeedbackPayload("guide"),
        adaptation_direction: state.basic_config.adaptation_direction,
        user_requirements: payloadUserRequirements(),
      };
    }
    if (stageKey === "package") {
      return {
        mode: revise ? "改写" : "创作",
        basic_config: state.basic_config,
        source_brief: state.source_brief,
        worldview_plan: state.worldview_plan,
        character_plan: state.character_plan,
        beat_checkpoint_timeline: state.beat_checkpoint_timeline,
        checkpoint_explanation: state.checkpoint_explanation,
        character_storylines: state.character_storylines,
        storyline_decisions: state.storyline_decisions,
        adaptation_guide: state.adaptation_guide,
        user_edit_history: state.user_edit_history,
        previous_framework_plan_package: revise ? state.framework_plan_package : {},
        user_feedback: stageFeedbackPayload("package"),
        adaptation_direction: state.basic_config.adaptation_direction,
        user_requirements: payloadUserRequirements(),
      };
    }
    return {};
  }

  function attachProjectContext(payload) {
    const next = Object.assign({}, payload || {});
    next.project_id = currentProjectId();
    next.project_title = state.basic_config.project_title || state.basic_config.source_title || "";
    return next;
  }

  async function loadStageHistory(stageKey) {
    const stageNo = stageNoForKey(stageKey);
    if (!stageNo) return;
    ui.stageHistoryLoading[stageKey] = true;
    render();
    try {
      const params = new URLSearchParams({
        project_id: currentProjectCacheName(),
        stage: stageNo,
      });
      const data = await requestJson(`/api/framework-planner/history?${params.toString()}`);
      ui.stageHistory[stageKey] = Array.isArray(data.entries) ? data.entries : [];
    } catch (error) {
      showToast(error.message || "历史版本刷新失败");
    } finally {
      ui.stageHistoryLoading[stageKey] = false;
      render();
    }
  }

  async function loadHistoryVersion(stageKey, filename) {
    if (!filename) return;
    const proceed = window.confirm(`将恢复到“${stageDisplayTitle(stageKey)}”在该时间点的版本，不影响已保存的其他历史版本。`);
    if (!proceed) return;
    try {
      const projectId = encodeURIComponent(currentProjectCacheName());
      const data = await requestJson(`/api/framework-planner/history/${projectId}/${encodeURIComponent(filename)}`);
      const record = data.record || {};
      const output = record.output || {};
      if (record.status !== "success") {
        showToast("失败版本不能加载到当前界面");
        return;
      }
      applyStageResponse(stageNoForKey(stageKey), { data: output, display_text: "" });
      state.stage_state[stageKey].status = "loaded_history";
      state.stage_state[stageKey].confirmed = false;
      recordHistory("load_stage_history", { stageKey, filename });
      saveState();
      showToast("已恢复到此版本，请确认后再进入下游阶段");
      render();
    } catch (error) {
      showToast(error.message || "历史版本加载失败");
    }
  }

  function applyStageResponse(stageNo, response) {
    const safeResponse = response && typeof response === "object" ? response : {};
    const safeData = safeResponse.data && typeof safeResponse.data === "object" ? safeResponse.data : {};
    state.raw_stage_responses[stageNo] = safeResponse.raw || {};
    state.display_texts[stageNo] = safeResponse.display_text || "";
    if (stageNo === "01") {
      state.source_brief = safeData.source_brief && typeof safeData.source_brief === "object" && !Array.isArray(safeData.source_brief)
        ? safeData.source_brief
        : {};
    }
    if (stageNo === "02") {
      state.worldview_plan = safeData.worldview_plan && typeof safeData.worldview_plan === "object" && !Array.isArray(safeData.worldview_plan)
        ? safeData.worldview_plan
        : {};
    }
    if (stageNo === "03") {
      state.character_plan = safeData.character_plan && typeof safeData.character_plan === "object" && !Array.isArray(safeData.character_plan)
        ? safeData.character_plan
        : {};
    }
    if (stageNo === "04") {
      state.beat_checkpoint_timeline = Array.isArray(safeData.beat_checkpoint_timeline)
        ? safeData.beat_checkpoint_timeline
        : [];
      state.checkpoint_explanation = safeData.checkpoint_explanation && typeof safeData.checkpoint_explanation === "object" && !Array.isArray(safeData.checkpoint_explanation)
        ? safeData.checkpoint_explanation
        : {};
      syncBeatCheckpointData({ clearStorylines: true });
    }
    if (stageNo === "05") {
      state.character_storylines = Array.isArray(safeData.character_storylines)
        ? safeData.character_storylines
        : [];
      normalizeStorylinesForCurrentBeats();
    }
    if (stageNo === "06") {
      state.adaptation_guide = safeData.adaptation_guide && typeof safeData.adaptation_guide === "object" && !Array.isArray(safeData.adaptation_guide)
        ? safeData.adaptation_guide
        : {};
    }
    if (stageNo === "07") {
      state.framework_plan_package = safeData.framework_plan_package && typeof safeData.framework_plan_package === "object" && !Array.isArray(safeData.framework_plan_package)
        ? safeData.framework_plan_package
        : {};
      state.validation_report = safeData.validation_report && typeof safeData.validation_report === "object" && !Array.isArray(safeData.validation_report)
        ? safeData.validation_report
        : {};
    }
    syncStageFlow(state);
    markDirty();
  }

  function syncStorylineDecisions(targetState) {
    const storylines = Array.isArray(targetState.character_storylines) ? targetState.character_storylines : [];
    targetState.storyline_decisions = storylines.map((item) => ({
      storyline_id: item.id,
      title: item.title,
      linked_beats: Array.isArray(item.linked_beats) ? item.linked_beats : [],
      decision: item.decision || "keep",
    }));
  }

  async function runStage(stageKey, options) {
    const stageNo = stageNoForKey(stageKey);
    setStageLoading(stageKey, true);
    ui.stageErrors[stageKey] = "";
    state.stage_state[stageKey].status = "running";
    render();
    try {
      await waitForPaint();
      const payload = cleanOutgoingPayload(attachProjectContext(attachKnowledgePayload(buildStagePayload(stageKey, options || {}), stageKey)), `stage${stageNo} payload`);
      debugFrontendEvent(`stage${stageNo}_request`, payload, {
        stageKey,
        stageNo,
        revise: Boolean(options && options.revise),
        current_view: state.current_view,
      });
      const response = await planningApi.runStage(stageNo, payload);
      debugFrontendEvent(`stage${stageNo}_response`, payload, {
        stageKey,
        stageNo,
        ok: Boolean(response && response.ok),
        response_keys: response && typeof response === "object" ? Object.keys(response) : [],
        data_summary: payloadSummary((response && response.data) || {}),
        history: response && response.history ? response.history : {},
      });
      applyStageResponse(stageNo, response);
      if (response.history) {
        ui.stageHistory[stageKey] = [response.history].concat(ui.stageHistory[stageKey] || []).slice(0, 50);
      } else {
        loadStageHistory(stageKey).catch(() => {});
      }
      state.stage_state[stageKey].status = options && options.revise ? "updated" : "generated";
      state.stage_state[stageKey].confirmed = false;
      recordHistory(options && options.revise ? "revise_stage" : "generate_stage", { stageKey, stageNo });
      return response;
    } catch (error) {
      state.stage_state[stageKey].status = "error";
      ui.stageErrors[stageKey] = formatStageError(error, stageNo);
      debugFrontendEvent(`stage${stageNo}_error`, attachProjectContext(attachKnowledgePayload(buildStagePayload(stageKey, options || {}), stageKey)), {
        stageKey,
        stageNo,
        message: error && error.message ? error.message : String(error || ""),
        status: error && error.status ? error.status : 0,
        detail: error && error.detail ? error.detail : {},
      });
      throw error;
    } finally {
      setStageLoading(stageKey, false);
      render();
    }
  }

  function formatStageError(error, stageNo) {
    const label = `阶段 ${stageNo}`;
    if (!error) return `${label} 执行失败`;
    const message = error.message || `${label} 执行失败`;
    const reason = error.reason || (error.detail && typeof error.detail.reason === "string" ? error.detail.reason.trim() : "");
    const endpoint = error.detail && typeof error.detail.endpoint === "string"
      ? error.detail.endpoint.trim()
      : "";
    const suggestion = error.detail && typeof error.detail.suggestion === "string"
      ? error.detail.suggestion.trim()
      : "";
    const lastExceptionMessage = error.lastExceptionMessage
      || (error.detail && typeof error.detail.last_exception_message === "string" ? error.detail.last_exception_message.trim() : "");
    if (Number(error.status || 0) >= 500) {
      return `${label}：模型暂时不可用，请稍后重试。`;
    }
    if (/格式异常/.test(message)) return `${label} 返回格式异常，请重试或查看日志。`;
    if (/无法连接 FastGPT 服务/.test(message)) {
      const parts = [`${label} 无法连接 FastGPT 服务`];
      if (endpoint) parts.push(`当前 endpoint：${endpoint}`);
      parts.push(suggestion || "建议检查 IP、端口、防火墙、FastGPT 服务状态。");
      return parts.join("\n");
    }
    if (lastExceptionMessage && lastExceptionMessage !== message && lastExceptionMessage !== reason) {
      return `${label}：${message}（${lastExceptionMessage}）`;
    }
    if (reason && reason !== message) return `${label}：${message}（${reason}）`;
    return `${label}：${message}`;
  }

  async function confirmBasic() {
    syncBasicConfigFromDom();
    if (!state.basic_config.source_title && !state.basic_config.project_title) {
      showToast("请至少填写作品标题或项目标题");
      return;
    }
    if (!state.basic_config.target_format) {
      showToast("请填写目标形式");
      return;
    }
    try {
      const response = await runStage("basic");
      state.stage_state.basic.confirmed = true;
      state.stage_state.basic.locked = true;
      state.stage_state.basic.status = "confirmed";
      unlockStage("worldview");
      state.current_view = "worldview";
      syncStageFlow(state);
      syncFrameworkAssetState(state, "confirm:basic");
      recordHistory("confirm_stage", { stageKey: "basic", stageNo: "01", sourceBrief: !isEmptyValue(state.source_brief) });
      markDirty();
      showToast("基础配置已确认，并已生成 source_brief");
      render();
      await autoGenerateCurrentStage();
    } catch (error) {
      showToast(formatStageError(error, "01"));
    }
  }

  async function confirmStage(stageKey) {
    if (stageKey === "worldview" && isEmptyValue(state.worldview_plan)) return;
    if (stageKey === "character" && isEmptyValue(state.character_plan)) return;
    if (stageKey === "beat" && (state.beat_checkpoint_timeline.length !== 15 || isEmptyValue(state.checkpoint_explanation))) {
      showToast("04 阶段必须同时具备 15 条时间轴和卡点说明后才能确认");
      return;
    }
    if (stageKey === "storylines") {
      normalizeStorylinesForCurrentBeats();
    }
    if (stageKey === "storylines" && !state.character_storylines.length) return;
    if (stageKey === "guide" && isEmptyValue(state.adaptation_guide)) return;

    state.stage_state[stageKey].confirmed = true;
    state.stage_state[stageKey].locked = true;
    state.stage_state[stageKey].status = "confirmed";
    if (stageKey === "worldview") {
      unlockStage("character");
      state.current_view = "character";
    }
    if (stageKey === "character") {
      unlockStage("beat");
      state.current_view = "beat_timeline";
    }
    if (stageKey === "beat") {
      unlockStage("storylines");
      state.current_view = "storylines";
    }
    if (stageKey === "storylines") {
      unlockStage("guide");
      state.current_view = "guide";
    }
    if (stageKey === "guide") {
      unlockStage("package");
      state.current_view = "package";
    }
    syncStageFlow(state);
    syncFrameworkAssetState(state, `confirm:${stageKey}`);
    recordHistory("confirm_stage", { stageKey, stageNo: stageNoForKey(stageKey) });
    markDirty();
    showToast("已确认并锁定，已解锁下游阶段");
    render();
    await autoGenerateCurrentStage();
  }

  function openEditor(editorStage, editorKey) {
    if (editorStage === "worldview") ui.editMode.worldview = true;
    if (editorStage === "character") ui.editMode.character = true;
    if (editorStage === "beatTimeline") ui.editMode.beatTimeline = true;
    if (editorStage === "beatExplanation") ui.editMode.beatExplanation = true;
    if (editorStage === "guide") ui.editMode.guide = true;
    state.editors[editorKey] = editorValueFor(editorKey);
    render();
  }

  function cancelEditor(editorStage) {
    if (editorStage === "worldview") ui.editMode.worldview = false;
    if (editorStage === "character") ui.editMode.character = false;
    if (editorStage === "beatTimeline") ui.editMode.beatTimeline = false;
    if (editorStage === "beatExplanation") ui.editMode.beatExplanation = false;
    if (editorStage === "guide") ui.editMode.guide = false;
    render();
  }

  function saveEditor(editorKey, stageKey) {
    try {
      const nextValue = parseEditorValue(editorKey, state.editors[editorKey]);
      if (editorKey === "worldview_plan") state.worldview_plan = nextValue;
      if (editorKey === "character_plan") state.character_plan = nextValue;
      if (editorKey === "beat_checkpoint_timeline") state.beat_checkpoint_timeline = Array.isArray(nextValue) ? nextValue : [];
      if (editorKey === "checkpoint_explanation") state.checkpoint_explanation = nextValue;
      if (editorKey === "adaptation_guide") state.adaptation_guide = nextValue;
      state.stage_state[stageKey].status = "updated";
      state.stage_state[stageKey].confirmed = false;
      if (stageKey === "worldview") ui.editMode.worldview = false;
      if (stageKey === "character") ui.editMode.character = false;
      if (editorKey === "beat_checkpoint_timeline") ui.editMode.beatTimeline = false;
      if (editorKey === "checkpoint_explanation") ui.editMode.beatExplanation = false;
      if (stageKey === "guide") ui.editMode.guide = false;
      syncStageFlow(state);
      recordHistory("save_editor", { stageKey, editorKey });
      markDirty();
      showToast("已更新，确认后才会解锁下游");
      render();
    } catch (error) {
      showToast(error.message || "编辑内容格式不正确");
    }
  }

  function updateBusinessField(rootKey, stageKey, path, rawValue, rawType) {
    if (!rootKey || !Array.isArray(path)) return;
    if (!Object.prototype.hasOwnProperty.call(state, rootKey)) return;
    const stage = state.stage_state[stageKey];
    if (stage && stage.confirmed) return;
    let value = rawValue;
    if (rawType === "number") {
      value = rawValue === "" ? "" : Number(rawValue);
    }
    if (rawValue === "true" || rawValue === "false") {
      value = rawValue === "true";
    }
    setNestedValue(state[rootKey], path, value);
    if (stage) {
      stage.status = "updated";
      stage.confirmed = false;
    }
    if (stageKey === "beat") {
      syncBeatCheckpointData({ clearStorylines: true });
    }
    syncStageFlow(state);
    markDirty();
    saveState();
    debugStageSummary("business form updated", {
      rootKey,
      stageKey,
      path: path.join("."),
      value: fieldSummary(value),
    });
  }

  function setNestedValue(root, path, value) {
    if (!root || typeof root !== "object" || !path.length) return;
    let cursor = root;
    for (let index = 0; index < path.length - 1; index += 1) {
      const key = path[index];
      if (cursor[key] === null || typeof cursor[key] !== "object") {
        cursor[key] = typeof path[index + 1] === "number" ? [] : {};
      }
      cursor = cursor[key];
    }
    cursor[path[path.length - 1]] = value;
  }

  function applyStagePreference(stageKey) {
    const prompt = String((((state.prompt_preferences || {}).stage_prompts || {})[stageKey]) || "").trim();
    if (!prompt) {
      showToast("本阶段还没有可应用的偏好提示");
      return;
    }
    state.feedback[stageKey] = prompt;
    savePromptPreferences(`apply_stage_preference:${stageKey}`);
    const payload = cleanOutgoingPayload(attachProjectContext(attachKnowledgePayload(buildStagePayload(stageKey, { revise: hasStageData(stageKey) }), stageKey)), `stage${stageNoForKey(stageKey)} applied-preference payload`);
    ui.lastStagePayloadPreview[stageKey] = {
      stageNo: stageNoForKey(stageKey),
      keys: Object.keys(payload).filter((key) => !key.startsWith("_")).slice(0, 12),
      updated_at: formatDateTime(new Date().toISOString()),
      payload,
    };
    debugStageSummary("stage preference applied", {
      stageKey,
      payload: payloadSummary(payload),
    });
    saveState();
    showToast("已应用本阶段偏好，并生成干净阶段入参");
    render();
  }

  function payloadSummary(payload) {
    const summary = {};
    Object.keys(payload || {}).forEach((key) => {
      summary[key] = fieldSummary(payload[key]);
    });
    return summary;
  }

  function applyStorylineDecision(storylineId, decision) {
    const storyline = state.character_storylines.find((item) => item.id === storylineId);
    if (!storyline || state.stage_state.storylines.confirmed) return;
    storyline.decision = decision;
    syncStorylineDecisions(state);
    state.stage_state.storylines.status = "updated";
    state.stage_state.storylines.confirmed = false;
    syncStageFlow(state);
    recordHistory("storyline_decision", { storylineId, decision });
    markDirty();
    saveState();
    render();
  }

  function openStorylineModal(storylineId) {
    ui.modalStorylineId = storylineId;
    render();
  }

  function closeStorylineModal() {
    ui.modalStorylineId = null;
    render();
  }

  function saveStorylineModal(storylineId) {
    const storyline = state.character_storylines.find((item) => item.id === storylineId);
    if (!storyline) return;
    const title = document.querySelector('[data-modal-field="title"]');
    const summary = document.querySelector('[data-modal-field="summary"]');
    const detailed = document.querySelector('[data-modal-field="detailed_storyline"]');
    const linkedBeats = document.querySelector('[data-modal-field="linked_beats"]');
    const episodeDistribution = document.querySelector('[data-modal-field="episode_distribution"]');
    const editNotes = document.querySelector('[data-modal-field="edit_notes"]');
    const decision = document.querySelector('[data-modal-field="decision"]');

    storyline.title = title ? title.value.trim() || storyline.title : storyline.title;
    storyline.summary = summary ? summary.value.trim() : storyline.summary;
    storyline.detailed_storyline = detailed ? detailed.value.trim() : storyline.detailed_storyline;
    storyline.linked_beats = parseLinkedBeats(linkedBeats ? linkedBeats.value : "");
    storyline.edit_notes = editNotes ? editNotes.value.trim() : storyline.edit_notes;
    storyline.decision = decision ? decision.value : storyline.decision;
    if (episodeDistribution) {
      storyline.episode_distribution = parseEpisodeDistributionLines(episodeDistribution.value);
    }
    syncStorylineDecisions(state);
    state.stage_state.storylines.status = "updated";
    state.stage_state.storylines.confirmed = false;
    syncStageFlow(state);
    recordHistory("update_storyline_detail", { storylineId });
    ui.modalStorylineId = null;
    markDirty();
    showToast("故事线已更新，仍需确认");
    render();
  }

  function addManualStoryline() {
    if (state.stage_state.storylines.confirmed) return;
    const id = `manual_storyline_${Date.now()}`;
    state.character_storylines.push({
      id,
      title: "人工补充故事线",
      summary: "",
      detailed_storyline: "",
      linked_beats: [],
      episode_distribution: [],
      edit_notes: "人工补充",
      decision: "keep",
    });
    syncStorylineDecisions(state);
    state.stage_state.storylines.status = "updated";
    state.stage_state.storylines.confirmed = false;
    syncStageFlow(state);
    recordHistory("add_storyline", { storylineId: id });
    markDirty();
    ui.modalStorylineId = id;
    render();
  }

  function parseLinkedBeats(text) {
    return String(text || "")
      .split(/[,，、]/)
      .map((item) => Number(item.trim()))
      .filter((item) => Number.isFinite(item) && item > 0);
  }

  function updateBeatTimelineField(indexValue, field, rawValue) {
    if (state.stage_state.beat.confirmed) return;
    const index = Number(indexValue);
    if (!Number.isInteger(index) || index < 0 || index >= state.beat_checkpoint_timeline.length) return;
    const beat = state.beat_checkpoint_timeline[index];
    if (!beat || typeof beat !== "object") return;
    if (field === "linked_storylines") {
      beat[field] = String(rawValue || "")
        .split(/[,，、]/)
        .map((item) => item.trim())
        .filter(Boolean);
    } else {
      beat[field] = rawValue;
    }
    state.stage_state.beat.status = "updated";
    state.stage_state.beat.confirmed = false;
    syncBeatCheckpointData({ clearStorylines: true });
    syncStageFlow(state);
    markDirty();
    saveState();
  }

  function ensureCheckpointExplanationObject() {
    if (!state.checkpoint_explanation || typeof state.checkpoint_explanation !== "object" || Array.isArray(state.checkpoint_explanation)) {
      state.checkpoint_explanation = { overview: "", beat_notes: [] };
    }
    if (!Array.isArray(state.checkpoint_explanation.beat_notes)) {
      state.checkpoint_explanation.beat_notes = [];
    }
    return state.checkpoint_explanation;
  }

  function updateCheckpointOverview(value) {
    if (state.stage_state.beat.confirmed) return;
    const explanation = ensureCheckpointExplanationObject();
    explanation.overview = value;
    state.stage_state.beat.status = "updated";
    state.stage_state.beat.confirmed = false;
    syncBeatCheckpointData({ clearStorylines: false });
    syncStageFlow(state);
    markDirty();
    saveState();
  }

  function updateCheckpointBeatNote(indexValue, value) {
    if (state.stage_state.beat.confirmed) return;
    const index = Number(indexValue);
    const explanation = ensureCheckpointExplanationObject();
    if (!Number.isInteger(index) || index < 0) return;
    while (explanation.beat_notes.length <= index) {
      const beatNo = explanation.beat_notes.length + 1;
      explanation.beat_notes.push({ beat_no: beatNo, explanation: "" });
    }
    const note = explanation.beat_notes[index];
    note.explanation = value;
    state.stage_state.beat.status = "updated";
    state.stage_state.beat.confirmed = false;
    syncBeatCheckpointData({ clearStorylines: false });
    syncStageFlow(state);
    markDirty();
    saveState();
  }

  function syncBeatCheckpointData(options) {
    const clearStorylines = Boolean(options && options.clearStorylines);
    const beats = Array.isArray(state.beat_checkpoint_timeline) ? state.beat_checkpoint_timeline : [];
    const explanation = ensureCheckpointExplanationObject();
    const notesByBeat = new Map(
      (Array.isArray(explanation.beat_notes) ? explanation.beat_notes : [])
        .filter((note) => note && typeof note === "object")
        .map((note) => [Number(note.beat_no), note])
    );
    explanation.beat_notes = beats.map((beat, index) => {
      const beatNo = Number(beat && beat.beat_no) || index + 1;
      const existing = notesByBeat.get(beatNo) || {};
      return {
        beat_no: beatNo,
        explanation: existing.explanation || existing.summary || existing.note || beatSummaryText(beat || {}, ""),
      };
    });
    if (!explanation.overview) {
      explanation.overview = "该卡点说明与同一条十五节拍时间轴一一对应。";
    }
    if (clearStorylines && state.character_storylines.length) {
      state.character_storylines = [];
      state.storyline_decisions = [];
      state.stage_state.storylines.confirmed = false;
      state.stage_state.storylines.locked = true;
      state.stage_state.storylines.status = "locked";
      downstreamStages("storylines").forEach((stageKey) => {
        clearStageData(stageKey);
        state.stage_state[stageKey].confirmed = false;
        state.stage_state[stageKey].locked = true;
        state.stage_state[stageKey].status = "locked";
      });
    }
  }

  function normalizeStorylinesForCurrentBeats() {
    const validBeats = new Set((state.beat_checkpoint_timeline || []).map((beat, index) => Number(beat && beat.beat_no) || index + 1));
    state.character_storylines = (Array.isArray(state.character_storylines) ? state.character_storylines : []).map((item, index) => {
      const next = Object.assign({
        id: `storyline_${index + 1}`,
        title: `故事线 ${index + 1}`,
        summary: "",
        detailed_storyline: "",
        linked_beats: [],
        episode_distribution: [],
        edit_notes: "",
        decision: "keep",
      }, item || {});
      next.summary = String(next.summary || "");
      next.detailed_storyline = String(next.detailed_storyline || "");
      next.linked_beats = (Array.isArray(next.linked_beats) ? next.linked_beats : parseLinkedBeats(next.linked_beats))
        .filter((beatNo) => validBeats.has(Number(beatNo)));
      next.decision = next.decision || "keep";
      return next;
    });
    syncStorylineDecisions(state);
  }

  async function runBeatScoreLoop(maxRounds) {
    const rounds = Number(maxRounds || 3);
    let round = 1;
    let current = state.beat_checkpoint_timeline.length ? clone(state.beat_checkpoint_timeline) : null;
    let lastScoreReport = state.framework_score_report || "";

    setStageLoading("beat", true);
    ui.stageErrors.beat = "";
    state.stage_state.beat.status = "running";
    render();
    try {
      while (round <= rounds) {
        const payload = cleanOutgoingPayload(attachKnowledgePayload({
          mode: current ? "改写" : "创作",
          project_id: currentProjectId(),
          source_brief: state.source_brief,
          basic_config: state.basic_config,
          worldview_plan: state.worldview_plan,
          character_plan: state.character_plan,
          previous_beat_checkpoint_timeline: current || [],
          user_feedback: stageFeedbackPayload("beat"),
          framework_score_report: lastScoreReport,
          adaptation_direction: state.basic_config.adaptation_direction,
          user_requirements: payloadUserRequirements(),
        }, "beat"), "stage04 score-loop payload");
        const beatResponse = await planningApi.runStage("04", payload);
        applyStageResponse("04", beatResponse);
        state.beat_revision_round = round;
        state.stage_state.beat.status = "updated";
        state.stage_state.beat.confirmed = false;
        const scoreResponse = await planningApi.runBeatScore({
          project_id: currentProjectId(),
          beat_checkpoint_timeline: state.beat_checkpoint_timeline,
          checkpoint_explanation: state.checkpoint_explanation,
          basic_config: state.basic_config,
          source_brief: state.source_brief,
          worldview_plan: state.worldview_plan,
          character_plan: state.character_plan,
        });
        state.framework_score_report = ((scoreResponse.data || {}).framework_score_report) || "";
        state.raw_stage_responses["04_score"] = scoreResponse.raw || {};
        recordHistory("beat_score_round", { round, framework_score_report: state.framework_score_report });
        if (scoreLooksPassed(state.framework_score_report)) {
          showToast(`评分循环完成，第 ${round} 轮通过`);
          break;
        }
        current = clone(state.beat_checkpoint_timeline);
        lastScoreReport = state.framework_score_report;
        round += 1;
      }
      if (round > rounds && !scoreLooksPassed(state.framework_score_report)) {
        showToast(`评分循环已跑满 ${rounds} 轮，仍建议人工检查`);
      }
      render();
    } catch (error) {
      state.stage_state.beat.status = "error";
      ui.stageErrors.beat = formatStageError(error, "04");
      showToast(formatStageError(error, "04"));
      render();
    } finally {
      setStageLoading("beat", false);
      render();
    }
  }

  function scoreLooksPassed(report) {
    const text = String(report || "").toLowerCase();
    return /pass|通过|无需修改|可进入下一阶段/.test(text);
  }

  function resetTransientUi() {
    ui.toast = "";
    ui.loading = {};
    ui.loadingStartedAt = {};
    ui.stageErrors = {};
    ui.modalStorylineId = null;
    ui.expandedBeats = {};
    ui.expandedStorylines = {};
    ui.expandedBusinessPanels = {};
    ui.lastStagePayloadPreview = {};
    ui.stageHistory = {};
    ui.stageHistoryLoading = {};
    ui.assetsOpen = false;
    ui.showNewScriptModal = false;
    ui.assetsLoading = false;
    ui.assetSearch = "";
    ui.assetStatusFilter = "all";
    ui.assetSort = "updated_desc";
    ui.newScriptForm = {
      title: "",
      season_count: 1,
      episodes_per_season: 60,
      target_format: "短剧",
      style: "",
      description: "",
    };
    ui.editMode = {
      worldview: false,
      character: false,
      beatTimeline: false,
      beatExplanation: false,
      guide: false,
    };
    if (ui.loadingTicker) {
      window.clearInterval(ui.loadingTicker);
      ui.loadingTicker = null;
    }
  }

  function resetState() {
    if (!canClearFrameworkInput()) {
      showToast("当前策划已开始，不能清空输入；如需新建，请点击新建框架项目");
      return;
    }
    const proceed = window.confirm("确认清空当前输入吗？已保存的资产和历史版本会保留。");
    if (!proceed) return;
    const assetState = clone(state.asset_state || initialState.asset_state);
    state.basic_config = clone(initialState.basic_config);
    state.source_brief = {};
    state.prompt_preferences = normalizePromptPreferences({});
    state.asset_state = assetState;
    state.current_view = "basic";
    state.feedback = clone(initialState.feedback);
    state.editors = clone(initialState.editors);
    state.stage_state = clone(initialState.stage_state);
    ui.knowledge.selectedIds = [];
    ui.knowledge.tagPromptText = "";
    syncStageFlow(state);
    saveState();
    savePromptPreferences("clear_input");
    render();
  }

  function canClearFrameworkInput() {
    if (state.current_view !== "basic") return false;
    if (Object.values(ui.loading || {}).some(Boolean)) return false;
    const confirmed = STAGE_SEQUENCE.some((stageKey) => Boolean((state.stage_state[stageKey] || {}).confirmed));
    if (confirmed) return false;
    return STAGE_SEQUENCE.every((stageKey) => !hasStageData(stageKey));
  }

  async function startFrameworkScript() {
    if (!canStartFrameworkScript()) {
      showToast("请先完成并确认 07 最终策划包输出");
      return;
    }

    ui.loading.framework_script = true;
    render();

    try {
      if (!hasSavedFrameworkProjectId() || hasUnsavedChanges()) {
        try {
          await saveFrameworkAsset({ silent: true });
        } catch (error) {
          showToast(`当前框架保存失败，无法进入框架转剧本工作台：${(error && error.message) || "未知错误"}`);
          return;
        }
      }

      if (!hasSavedFrameworkProjectId()) {
        showToast("project_id 缺失，无法进入框架转剧本工作台。");
        return;
      }

      const sourceProjectId =
        state.project_id
        || (state.asset_state || {}).project_id
        || (state.asset_state || {}).asset_id;

      try {
        window.localStorage.setItem("frameworkToScriptSource", JSON.stringify({
          source_framework_project_id: sourceProjectId,
          project_id: sourceProjectId,
          framework_plan_package: state.framework_plan_package || {},
          worldview_plan: state.worldview_plan || (state.framework_plan_package || {}).worldview_plan || {},
          beat_checkpoint_timeline: state.beat_checkpoint_timeline || (state.framework_plan_package || {}).beat_checkpoint_timeline || [],
          character_storylines: state.character_storylines || (state.framework_plan_package || {}).character_storylines || [],
          character_plan: state.character_plan || (state.framework_plan_package || {}).character_plan || {},
          saved_at: new Date().toISOString()
        }));
      } catch (error) {
        console.warn("保存框架转剧本本地上下文失败", error);
      }

      const workspaceUrl = new URL("/framework-to-script", window.location.origin);
      workspaceUrl.searchParams.set("framework_asset_id", String(sourceProjectId));
      workspaceUrl.searchParams.set("source_framework_project_id", String(sourceProjectId));
      workspaceUrl.searchParams.set("project_id", String(sourceProjectId));
      const authToken = new URLSearchParams(window.location.search).get("auth_token") || config.authToken || "";
      if (authToken) {
        workspaceUrl.searchParams.set("auth_token", authToken);
      }

      clearDirty();
      window.location.href = workspaceUrl.pathname + workspaceUrl.search + workspaceUrl.hash;
    } catch (error) {
      showToast((error && error.message) || "进入框架转剧本工作台失败");
    } finally {
      ui.loading.framework_script = false;
      render();
    }
  }

  async function saveFrameworkAsset(options) {
    ui.loading.framework_save = true;
    render();
    try {
      const data = await planningApi.saveFrameworkAsset(frameworkAssetSavePayload());
      const asset = data.asset || data.project || {};
      const projectId = data.project_id || asset.project_id || asset.asset_id || asset.id || "";
      if (projectId === undefined || projectId === null || String(projectId).trim() === "") {
        throw new Error("project_id 缺失");
      }
      state.project_id = projectId;
      state.asset_state = Object.assign({}, state.asset_state || {}, asset.asset_state || {}, {
        asset_kind: "framework_planner",
        asset_id: projectId,
        project_id: projectId,
        status: asset.status || (state.asset_state || {}).status || "in_progress",
        updated_at: asset.updated_at || new Date().toISOString(),
      });
      syncStageFlow(state);
      saveState();
      clearDirty();
      if (!options || !options.silent) {
        showToast("当前框架已保存");
      }
      await loadAssets();
      return asset;
    } catch (error) {
      if (!options || !options.silent) {
        showToast((error && error.message) || "保存失败");
      }
      throw error;
    } finally {
      ui.loading.framework_save = false;
      render();
    }
  }

  async function loadKnowledgeTags() {
    ui.knowledge.loading = true;
    ui.knowledge.status = "";
    if (ui.knowledge.open) render();
    try {
      const data = await requestJson("/api/user-knowledge/tags");
      ui.knowledge.tags = Array.isArray(data.tags) ? data.tags : [];
      ui.knowledge.status = ui.knowledge.tags.length ? "" : "暂无可用标签";
    } catch (error) {
      ui.knowledge.tags = [];
      ui.knowledge.status = error.message || "智慧库标签加载失败，已显示空列表";
    } finally {
      ui.knowledge.loading = false;
      render();
    }
  }

  async function loadKnowledgePreferences() {
    try {
      const data = await requestJson("/api/user-knowledge/preferences");
      const preferences = data.preferences || {};
      const remoteStagePrompts = normalizeStagePrompts(preferences.stage_prompts || {});
      const hasRemoteStagePrompt = Object.values(remoteStagePrompts).some((value) => String(value || "").trim());
      if (Array.isArray(preferences.selected_preference_tag_ids)) {
        ui.knowledge.selectedIds = preferences.selected_preference_tag_ids.map(String);
      }
      state.prompt_preferences = normalizePromptPreferences(Object.assign({}, state.prompt_preferences || {}, {
        script_preference: preferences.user_preference_prompt || (state.prompt_preferences || {}).script_preference || "",
        stage_prompts: hasRemoteStagePrompt ? remoteStagePrompts : (state.prompt_preferences || {}).stage_prompts || {},
      }));
      saveState();
      render();
    } catch (error) {
      if (DEV_LOG_ENABLED && typeof console !== "undefined" && console.warn) {
        console.warn("[framework_planner] preference load failed", error);
      }
    }
  }

  function setKnowledgeSelection(tagId, selected) {
    const id = String(tagId || "").trim();
    if (!id) return;
    const ids = new Set(ui.knowledge.selectedIds || []);
    if (selected) ids.add(id);
    else ids.delete(id);
    ui.knowledge.selectedIds = Array.from(ids);
    saveState();
    render();
  }

  async function applyKnowledgeTags() {
    const selectedIds = (ui.knowledge.selectedIds || []).map((item) => String(item || "").trim()).filter(Boolean);
    try {
      const data = await requestJson("/api/user-knowledge/apply-tags", {
        method: "POST",
        body: JSON.stringify({
          selected_tag_ids: selectedIds,
          existing_user_preference: String((state.prompt_preferences || {}).script_preference || ""),
        }),
      });
      const stagePrompts = normalizeStagePrompts(data.stage_prompts || {});
      state.prompt_preferences = normalizePromptPreferences(Object.assign({}, state.prompt_preferences || {}, {
        script_preference: String(data.merged_preference_prompt || ""),
        stage_prompts: stagePrompts,
        active_template_id: "custom",
      }));
      ui.knowledge.selectedIds = Array.isArray(data.selected_tag_ids) ? data.selected_tag_ids.map(String) : selectedIds;
      ui.knowledge.tagPromptText = String(data.tag_prompt_text || "");
      savePromptPreferences("apply_knowledge_tags");
      saveState();
      showToast(selectedIds.length ? "智慧库标签已应用到每阶段提示词" : "已清空智慧库阶段提示词");
      render();
    } catch (error) {
      ui.knowledge.status = error.message || "智慧库标签应用失败";
      showToast(ui.knowledge.status);
      render();
    }
  }

  function collectKnowledgeFormFromDom() {
    const form = emptyKnowledgeTagForm();
    form.id = ui.knowledge.editingId || "";
    app.querySelectorAll("[data-knowledge-form-key]").forEach((field) => {
      const key = field.dataset.knowledgeFormKey;
      if (key) form[key] = field.value;
    });
    app.querySelectorAll("[data-knowledge-stage-key]").forEach((field) => {
      const key = field.dataset.knowledgeStageKey;
      if (key) form.stage_prompts[key] = field.value;
    });
    ui.knowledge.form = form;
    return form;
  }

  function openKnowledgeForm(tagId) {
    const id = String(tagId || "");
    const tag = id ? (ui.knowledge.tags || []).find((item) => String(item.id || "") === id) : null;
    if (tag && tag.builtin) return;
    ui.knowledge.editingId = tag ? id : "";
    ui.knowledge.formOpen = true;
    ui.knowledge.form = tag ? {
      id,
      name: String(tag.name || ""),
      category: String(tag.category || "自定义"),
      description: String(tag.description || ""),
      prompt_text: String(tag.prompt_text || ""),
      stage_prompts: normalizeStagePrompts(tag.stage_prompts || {}),
    } : emptyKnowledgeTagForm();
    render();
  }

  async function saveKnowledgeTag() {
    const form = collectKnowledgeFormFromDom();
    if (!String(form.name || "").trim()) {
      showToast("请填写标签名称");
      return;
    }
    const editingId = String(ui.knowledge.editingId || "");
    const url = editingId ? `/api/user-knowledge/tags/${encodeURIComponent(editingId)}` : "/api/user-knowledge/tags";
    const method = editingId ? "PATCH" : "POST";
    try {
      const data = await requestJson(url, {
        method,
        body: JSON.stringify(form),
      });
      const tag = data.tag;
      if (tag && tag.id) {
        const existingIndex = ui.knowledge.tags.findIndex((item) => String(item.id || "") === String(tag.id));
        if (existingIndex >= 0) ui.knowledge.tags.splice(existingIndex, 1, tag);
        else ui.knowledge.tags.push(tag);
        ui.knowledge.selectedIds = Array.from(new Set((ui.knowledge.selectedIds || []).concat(String(tag.id))));
      }
      ui.knowledge.formOpen = false;
      ui.knowledge.editingId = "";
      ui.knowledge.form = emptyKnowledgeTagForm();
      await loadKnowledgeTags();
      showToast(editingId ? "标签已保存" : "标签已创建");
    } catch (error) {
      showToast(error.message || "标签保存失败");
    }
  }

  async function deleteKnowledgeTag(tagId) {
    const id = String(tagId || "").trim();
    if (!id) return;
    if (!window.confirm("确认删除这个自定义标签吗？已生成项目会保留历史内容。")) return;
    try {
      await requestJson(`/api/user-knowledge/tags/${encodeURIComponent(id)}`, { method: "DELETE" });
      ui.knowledge.tags = ui.knowledge.tags.filter((tag) => String(tag.id || "") !== id);
      ui.knowledge.selectedIds = ui.knowledge.selectedIds.filter((item) => String(item) !== id);
      if (ui.knowledge.editingId === id) {
        ui.knowledge.formOpen = false;
        ui.knowledge.editingId = "";
      }
      await loadKnowledgeTags();
      showToast("标签已删除");
    } catch (error) {
      showToast(error.message || "标签删除失败");
    }
  }

  async function loadAssets() {
    ui.assetsLoading = true;
    if (ui.assetsOpen) render();
    try {
      const data = await requestJson("/api/assets");
      ui.assets = Array.isArray(data.assets) ? data.assets : [];
    } catch (error) {
      showToast(error.message || "资产列表加载失败");
    } finally {
      ui.assetsLoading = false;
      if (ui.assetsOpen) render();
    }
  }

  async function createNewScript() {
    const form = clone(collectNewScriptFormFromDom());
    debugStageSummary("new_script_submit_collected", {
      form,
      dom_field_count: app.querySelectorAll("[data-new-script-field]").length,
    });
    if (!String(form.title || "").trim()) {
      showToast("请填写剧本名称");
      return;
    }
    debugFrontendEvent("new_script_submit", {
      project_title: form.title || "",
      source_title: form.title || "",
      target_format: form.target_format || "",
      season_count: form.season_count,
      episodes_per_season: form.episodes_per_season,
      source_text: form.description || "",
      user_requirements: form.style || "",
    }, {
      form,
      note: "新建框架项目提交时从当前 DOM 重新收集的表单值",
    });
    const data = await requestJson("/api/framework-planner/assets", {
      method: "POST",
      body: JSON.stringify(form),
    });
    const asset = data.asset || {};
    resetTransientUi();
    state = clone(initialState);
    state.basic_config.project_title = asset.title || form.title || "未命名剧本";
    state.basic_config.source_title = asset.title || form.title || "";
    state.basic_config.target_format = form.target_format || "短剧";
    state.basic_config.season_count = Number(form.season_count || 1);
    state.basic_config.episodes_per_season = Number(form.episodes_per_season || 60);
    state.basic_config.user_requirements = form.style || "";
    state.basic_config.source_text = form.description || "";
    state.project_id = asset.project_id || null;
    state.asset_state.asset_id = asset.project_id || null;
    state.asset_state.project_id = asset.project_id || null;
    state.asset_state.status = "draft";
    state.current_view = "basic";
    ui.assetsOpen = true;
    syncStageFlow(state);
    saveState();
    clearDirty();
    debugFrontendEvent("new_script_created", {
      project_id: state.asset_state.asset_id,
      project_title: state.basic_config.project_title,
      source_title: state.basic_config.source_title,
      target_format: state.basic_config.target_format,
      season_count: state.basic_config.season_count,
      episodes_per_season: state.basic_config.episodes_per_season,
      source_text: state.basic_config.source_text,
      user_requirements: state.basic_config.user_requirements,
    }, {
      asset,
      history_hint: `版本历史：${currentProjectCacheName()}`,
    });
    await loadAssets();
    await loadStageHistory("basic");
    showToast("新框架项目已创建，已进入 01 阶段");
  }

  async function deleteAsset(projectId) {
    if (!projectId) return;
    if (!window.confirm("确认删除这个剧本资产吗？")) return;
    await requestJson(`/api/projects/${projectId}`, { method: "DELETE" });
    await loadAssets();
    showToast("资产已删除");
  }

  async function duplicateAsset(projectId) {
    const data = await requestJson(`/api/projects/${projectId}`);
    const project = data.project || {};
    const input = project.input_payload || {};
    ui.newScriptForm = {
      title: `${project.title || input.title || "未命名剧本"} 副本`,
      season_count: input.season_count || 1,
      episodes_per_season: input.episodes_per_season || project.total_episodes || 60,
      target_format: input.target_format || "短剧",
      style: input.style || "",
      description: input.story_outline || "",
    };
    await createNewScript();
  }

  function restoreFrameworkPlannerState(project) {
    const restored = project.framework_planner_state
      || ((project.input_payload || {}).framework_planner_state)
      || ((project.artifacts || {}).framework_planner_state)
      || {};
    if (!restored || typeof restored !== "object" || Array.isArray(restored)) {
      throw new Error("资产恢复失败：缺少 framework_planner_state");
    }
    resetTransientUi();
    state = clone(initialState);
    [
      "basic_config",
      "source_brief",
      "worldview_plan",
      "character_plan",
      "beat_checkpoint_timeline",
      "checkpoint_explanation",
      "character_storylines",
      "storyline_decisions",
      "adaptation_guide",
      "framework_plan_package",
      "validation_report",
      "display_texts",
      "prompt_preferences",
      "asset_state",
      "stage_state",
    ].forEach((key) => {
      if (restored[key] !== undefined && restored[key] !== null) {
        state[key] = clone(restored[key]);
      }
    });
    const projectId = Number(project.project_id || restored.project_id || 0);
    state.project_id = projectId > 0 ? projectId : null;
    state.asset_state = Object.assign(clone(initialState.asset_state), state.asset_state || {}, {
      asset_kind: "framework_planner",
      asset_id: state.project_id,
      project_id: state.project_id,
      status: project.status || (state.asset_state || {}).status || "in_progress",
    });
    if (!state.stage_state || typeof state.stage_state !== "object") {
      state.stage_state = clone(initialState.stage_state);
    }
    if (!isEmptyValue(state.framework_plan_package)) {
      STAGE_SEQUENCE.forEach((stageKey) => {
        state.stage_state[stageKey] = Object.assign(clone(initialState.stage_state[stageKey]), state.stage_state[stageKey] || {}, {
          confirmed: true,
          locked: true,
          status: "confirmed",
        });
      });
      state.current_view = restored.current_view || "package";
    } else {
      state.current_view = restored.current_view || "basic";
    }
    ui.knowledge.selectedIds = Array.isArray(restored.selected_preference_tag_ids)
      ? restored.selected_preference_tag_ids.map(String)
      : [];
    syncStageFlow(state);
    saveState();
  }

  async function openAsset(projectId) {
    if (promptUnsaved("切换到已有项目", {
      save: async () => openAsset(projectId),
      discard: async () => openAsset(projectId),
    })) return;
    const data = await requestJson(`/api/projects/${projectId}`);
    const project = data.project || {};
    if (String(project.asset_kind || "") === "framework_planner") {
      try {
        restoreFrameworkPlannerState(project);
      } catch (error) {
        showToast((error && error.message) || "资产恢复失败");
        return;
      }
      ui.stageHistory = {};
      ui.stageHistoryLoading = {};
      await loadStageHistory(stageKeyForView(state.current_view || "basic"));
      showToast("已恢复框架策划资产，可继续生成或进入下游剧本");
      render();
      clearDirty();
      return;
    }
    const input = project.input_payload || {};
    resetTransientUi();
    state = clone(initialState);
    state.basic_config.project_title = project.title || input.title || state.basic_config.project_title;
    state.basic_config.source_title = project.title || input.title || state.basic_config.source_title;
    state.basic_config.target_format = input.target_format || state.basic_config.target_format;
    state.basic_config.season_count = Number(input.season_count || state.basic_config.season_count || 1);
    state.basic_config.episodes_per_season = Number(input.episodes_per_season || state.basic_config.episodes_per_season || 60);
    state.basic_config.user_requirements = input.style || state.basic_config.user_requirements || "";
    state.basic_config.source_text = input.story_outline || state.basic_config.source_text || "";
    state.asset_state.asset_id = project.project_id || null;
    state.asset_state.status = project.status || "draft";
    state.current_view = "basic";
    ui.stageHistory = {};
    ui.stageHistoryLoading = {};
    syncStageFlow(state);
    saveState();
    clearDirty();
    await loadStageHistory("basic");
    showToast("已打开资产，可从第一阶段查看和继续策划");
    render();
  }

  async function controlAssetTask(taskId, action) {
    if (!taskId) return;
    const asset = ui.assets.find((item) => String(item.task_id || "") === String(taskId));
    const status = String(asset?.status || "");
    const endpoint = action === "stop" ? "terminate" : (["failed", "terminated"].includes(status) ? "retry" : "resume");
    await requestJson(`/api/tasks/${taskId}/${endpoint}`, { method: "POST" });
    await loadAssets();
    showToast(action === "stop" ? "任务已停止" : "任务已继续");
  }

  function copyText(text, successText) {
  const value = typeof text === "string" ? text : JSON.stringify(text ?? "", null, 2);

  const notifyCopied = () => {
    if (!successText) return true;

    if (typeof showToast === "function") {
      showToast(successText);
    } else if (typeof toast === "function") {
      toast(successText);
    } else if (typeof setStatus === "function") {
      setStatus(successText);
    } else {
      console.log(successText);
    }

    return true;
  };

  const fallbackCopy = () => {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "readonly");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    textarea.style.top = "0";
    textarea.style.opacity = "0";

    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();

    try {
      const ok = document.execCommand("copy");
      if (ok) {
        notifyCopied();
        return true;
      }
    } catch (error) {
      console.warn("[framework-planner] document.execCommand('copy') failed", error);
    } finally {
      document.body.removeChild(textarea);
    }

    window.prompt("浏览器禁止自动复制，请手动复制以下内容：", value);
    return false;
  };

  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    navigator.clipboard.writeText(value)
      .then(() => notifyCopied())
      .catch((error) => {
        console.warn("[framework-planner] navigator.clipboard.writeText failed, fallback to textarea copy", error);
        fallbackCopy();
      });
    return true;
  }

  return fallbackCopy();
}

  function buildMockStageResponse(stageNo, payload) {
    const response = {
      ok: true,
      stage: stageNo,
      data: {},
      raw: { mock: true, source: "frontend_fallback_mock" },
      display_text: "",
    };

    if (stageNo === "01") {
      response.data.source_brief = {
        source_title: payload.source_title || "未命名原作",
        target_format: payload.target_format || "短剧",
        core_premise: (payload.source_text || "").slice(0, 160) || "前端 mock 提取结果。",
        adaptation_direction: payload.adaptation_direction || "",
      };
      response.display_text = prettyJson(response.data.source_brief);
      return response;
    }
    if (stageNo === "02") {
      response.data.worldview_plan = {
        world_type: "前端 mock 世界观",
        main_conflict: "主角被迫进入高压规则体系并向上破局。",
      };
      response.display_text = prettyJson(response.data.worldview_plan);
      return response;
    }
    if (stageNo === "03") {
      response.data.character_plan = {
        protagonist: { name: "林渡", flaw: "过度逞强" },
        antagonist: { name: "周砺", role: "规则压迫者" },
      };
      response.display_text = prettyJson(response.data.character_plan);
      return response;
    }
    if (stageNo === "04") {
      const ranges = splitEpisodeRanges(Number((payload.basic_config || {}).episodes_per_season || 60));
      response.data.beat_checkpoint_timeline = BEAT_NAMES.map((name, index) => ({
        beat_no: index + 1,
        beat_name: name,
        act: index < 6 ? "第一幕" : index < 12 ? "第二幕" : "第三幕",
        episode_range: ranges[index],
        checkpoint_title: `${name}卡点`,
        narrative_function: `${name}叙事功能说明`,
        plot_content: `${name}剧情内容`,
        character_change: "主角状态发生递进变化",
        conflict_upgrade: "冲突继续升级",
        hook_or_reversal: `${name}结尾钩子`,
        linked_storylines: ["主角成长线"],
      }));
      response.data.checkpoint_explanation = {
        overview: "frontend mock checkpoint_explanation",
        beat_notes: response.data.beat_checkpoint_timeline.map((item) => ({
          beat_no: item.beat_no,
          explanation: item.plot_content,
        })),
      };
      response.display_text = prettyJson(response.data);
      return response;
    }
    if (stageNo === "05") {
      response.data.character_storylines = [
        {
          id: "protagonist_growth",
          title: "主角成长线",
          summary: "主角从被压制走向主动反攻。",
          detailed_storyline: "承担主线成长和策略升级。",
          linked_beats: [1, 4, 9, 12, 14, 15],
          episode_distribution: [{ episode_range: "前中后段", focus: "成长递进" }],
          edit_notes: "重点保留",
          decision: "keep",
        },
        {
          id: "b_story_relationship",
          title: "B故事情感线",
          summary: "承担关系变化和主题回流。",
          detailed_storyline: "帮助主角完成价值观转向。",
          linked_beats: [3, 7, 12, 15],
          episode_distribution: [{ episode_range: "中后段", focus: "关系升级" }],
          edit_notes: "建议精简",
          decision: "simplify",
        },
      ];
      response.display_text = prettyJson(response.data.character_storylines);
      return response;
    }
    if (stageNo === "06") {
      response.data.adaptation_guide = {
        core_setting_adjustments: "保留规则对抗骨架。",
        structure_and_rhythm: "保持强开局、中点反转、后段反攻。",
        visualization_strategy: "尽量用可拍摄冲突外化信息。",
        character_emotion_strategy: "强调主角由屈辱到反攻的情绪线。",
      };
      response.display_text = prettyJson(response.data.adaptation_guide);
      return response;
    }
    if (stageNo === "07") {
      response.data.framework_plan_package = buildWorkingPayload();
      response.data.validation_report = {
        passed: true,
        summary: "frontend mock 校验通过",
      };
      response.display_text = prettyJson(response.data);
      return response;
    }
    return response;
  }

  function buildMockScoreResponse(payload) {
    const beats = Array.isArray(payload.beat_checkpoint_timeline) ? payload.beat_checkpoint_timeline : [];
    const ok = beats.length === 15;
    const report = ok
      ? "PASS\n总评：frontend mock 认为 15 条节拍齐备，可进入下一阶段。"
      : `REVISE\n总评：当前仅有 ${beats.length} 条节拍，仍需补齐。`;
    return {
      ok: true,
      stage: "04",
      data: { framework_score_report: report },
      raw: { mock: true, source: "frontend_fallback_mock_score" },
      display_text: report,
    };
  }

  function splitEpisodeRanges(totalEpisodes) {
    const total = Math.max(15, Number(totalEpisodes) || 60);
    const weights = [3, 4, 4, 4, 4, 5, 5, 7, 5, 5, 4, 4, 3, 2, 1];
    const sum = weights.reduce((acc, item) => acc + item, 0);
    let start = 1;
    return weights.map((weight, index) => {
      const remaining = 15 - index;
      let length = index === weights.length - 1 ? total - start + 1 : Math.max(1, Math.round(total * weight / sum));
      if (start + length + remaining - 2 > total) {
        length = Math.max(1, total - start - remaining + 2);
      }
      const end = Math.min(total, start + length - 1);
      const text = start === end ? `第${start}集` : `第${start}-${end}集`;
      start = end + 1;
      return text;
    });
  }

  app.addEventListener("input", (event) => {
    const target = event.target;
    if (target.matches("[data-config-key]")) {
      const key = target.dataset.configKey;
      state.basic_config[key] = target.type === "number" ? Number(target.value) : target.value;
      markDirty();
      debugStageSummary("basic_config_input", {
        key,
        value_length: String(target.value || "").length,
        current_value: target.type === "number" ? Number(target.value) : target.value,
      });
      savePromptPreferences(`basic_config:${key}`);
      saveState();
      return;
    }
    if (target.matches("[data-script-preference]")) {
      state.prompt_preferences.script_preference = target.value;
      state.prompt_preferences.active_template_id = "custom";
      markDirty();
      savePromptPreferences("script_preference");
      saveState();
      return;
    }
    if (target.matches("[data-stage-preference-key]")) {
      const stageKey = target.dataset.stagePreferenceKey;
      state.prompt_preferences.stage_prompts[stageKey] = target.value;
      markDirty();
      savePromptPreferences(`stage_preference:${stageKey}`);
      saveState();
      return;
    }
    if (target.matches("[data-new-script-field]")) {
      const key = target.dataset.newScriptField;
      ui.newScriptForm[key] = target.type === "number" ? Number(target.value) : target.value;
      debugStageSummary("new_script_input", {
        key,
        value_length: String(target.value || "").length,
        current_value: target.type === "number" ? Number(target.value) : target.value,
      });
      return;
    }
    if (target.matches("[data-knowledge-form-key]")) {
      const key = target.dataset.knowledgeFormKey;
      if (key) ui.knowledge.form[key] = target.value;
      return;
    }
    if (target.matches("[data-knowledge-stage-key]")) {
      const key = target.dataset.knowledgeStageKey;
      if (key) ui.knowledge.form.stage_prompts[key] = target.value;
      return;
    }
    if (target.matches("[data-asset-search]")) {
      ui.assetSearch = target.value;
      render();
      return;
    }
    if (target.matches("[data-feedback-key]")) {
      state.feedback[target.dataset.feedbackKey] = target.value;
      markDirty();
      savePromptPreferences(`feedback:${target.dataset.feedbackKey}`);
      saveState();
      return;
    }
    if (target.matches("[data-editor-key]")) {
      state.editors[target.dataset.editorKey] = target.value;
      markDirty();
      savePromptPreferences(`editor:${target.dataset.editorKey}`);
      saveState();
      return;
    }
    if (target.matches("[data-business-root][data-business-path]")) {
      updateBusinessField(
        target.dataset.businessRoot,
        target.dataset.businessStage,
        decodeBusinessPath(target.dataset.businessPath),
        target.value,
        target.dataset.businessType
      );
      return;
    }
    if (target.matches("[data-beat-index][data-beat-field]")) {
      updateBeatTimelineField(target.dataset.beatIndex, target.dataset.beatField, target.value);
      return;
    }
    if (target.matches("[data-checkpoint-overview]")) {
      updateCheckpointOverview(target.value);
      return;
    }
    if (target.matches("[data-beat-note-index]")) {
      updateCheckpointBeatNote(target.dataset.beatNoteIndex, target.value);
      return;
    }
  });

  app.addEventListener("change", (event) => {
    const target = event.target;
    if (target.matches("[data-config-key]")) {
      const key = target.dataset.configKey;
      state.basic_config[key] = target.type === "number" ? Number(target.value) : target.value;
      markDirty();
      debugStageSummary("basic_config_change", {
        key,
        value_length: String(target.value || "").length,
        current_value: target.type === "number" ? Number(target.value) : target.value,
      });
      savePromptPreferences(`basic_config:${key}`);
      saveState();
      return;
    }
    if (target.matches("[data-new-script-field]")) {
      const key = target.dataset.newScriptField;
      ui.newScriptForm[key] = target.type === "number" ? Number(target.value) : target.value;
      debugStageSummary("new_script_change", {
        key,
        value_length: String(target.value || "").length,
        current_value: target.type === "number" ? Number(target.value) : target.value,
      });
      return;
    }
    if (target.matches("[data-business-root][data-business-path]")) {
      updateBusinessField(
        target.dataset.businessRoot,
        target.dataset.businessStage,
        decodeBusinessPath(target.dataset.businessPath),
        target.value,
        target.dataset.businessType
      );
      return;
    }
    if (target.matches("[data-asset-status-filter]")) {
      ui.assetStatusFilter = target.value || "all";
      render();
      return;
    }
    if (target.matches("[data-asset-sort]")) {
      ui.assetSort = target.value || "updated_desc";
      render();
      return;
    }
    if (target.matches("[data-knowledge-tag-id]")) {
      setKnowledgeSelection(target.dataset.knowledgeTagId, target.checked);
      return;
    }
    if (!target.matches("[data-preference-template]")) return;
    const templateId = target.value || "custom";
    const templates = ((state.prompt_preferences || {}).templates || DEFAULT_PROMPT_TEMPLATES);
    const template = templates.find((item) => item.id === templateId);
    state.prompt_preferences.active_template_id = templateId;
    if (template && templateId !== "custom") {
      state.prompt_preferences.script_preference = template.prompt || "";
    }
    savePromptPreferences(`template:${templateId}`);
    saveState();
    render();
  });

  app.addEventListener("toggle", (event) => {
    const detail = event.target;
    if (!detail || !detail.matches || !detail.matches("[data-beat-detail]")) return;
    ui.expandedBeats[String(detail.dataset.beatDetail || "")] = Boolean(detail.open);
  }, true);
  app.addEventListener("toggle", (event) => {
    const detail = event.target;
    if (!detail || !detail.matches || !detail.matches("[data-storyline-detail]")) return;
    ui.expandedStorylines[String(detail.dataset.storylineDetail || "")] = Boolean(detail.open);
  }, true);
  app.addEventListener("toggle", (event) => {
    const detail = event.target;
    if (!detail || !detail.matches || !detail.matches("[data-business-panel]")) return;
    ui.expandedBusinessPanels[String(detail.dataset.businessPanel || "")] = Boolean(detail.open);
  }, true);
  app.addEventListener("toggle", (event) => {
    const detail = event.target;
    if (!detail || !detail.matches || !detail.matches("[data-tree-node]")) return;
    ui.expandedRawTree[String(detail.dataset.treeNode || "")] = Boolean(detail.open);
  }, true);

  app.addEventListener("click", async (event) => {
    const guardedLink = event.target.closest && event.target.closest("a[data-guard-nav]");
    if (guardedLink && hasUnsavedChanges()) {
      event.preventDefault();
      const targetUrl = guardedLink.href;
      promptUnsaved("返回主工作台", {
        save: async () => saveAndLeave(targetUrl),
        discard: () => {
          ui.suppressBeforeUnload = true;
          window.location.href = targetUrl;
        },
      });
      return;
    }
    const actionElement = event.target.closest("[data-action]");
    if (!actionElement) return;
    const action = actionElement.dataset.action;

    if (action === "save-unsaved-prompt") {
      await runUnsavedPrompt("save");
      return;
    }
    if (action === "discard-unsaved-prompt") {
      await runUnsavedPrompt("discard");
      return;
    }
    if (action === "cancel-unsaved-prompt") {
      if (actionElement.matches(".fp-modal-mask") && event.target !== actionElement) return;
      await runUnsavedPrompt("cancel");
      return;
    }
    if (action === "go-view") {
      setCurrentView(actionElement.dataset.view);
      return;
    }
    if (action === "open-new-script") {
      if (promptUnsaved("新建框架项目", {
        save: () => {
          ui.showNewScriptModal = true;
          render();
        },
        discard: () => {
          ui.showNewScriptModal = true;
          render();
        },
      })) return;
      ui.showNewScriptModal = true;
      render();
      return;
    }
    if (action === "close-new-script") {
      if (actionElement.matches(".fp-modal-mask") && event.target !== actionElement) {
        return;
      }
      ui.showNewScriptModal = false;
      render();
      return;
    }
    if (action === "submit-new-script") {
      try {
        await createNewScript();
      } catch (error) {
        showToast(error.message || "新建框架项目失败");
      }
      return;
    }
    if (action === "toggle-assets") {
      ui.assetsOpen = !ui.assetsOpen;
      render();
      if (ui.assetsOpen && !ui.assets.length) await loadAssets();
      return;
    }
    if (action === "toggle-knowledge-panel") {
      ui.knowledge.open = !ui.knowledge.open;
      persistKnowledgePanelOpen(ui.knowledge.open);
      render();
      if (ui.knowledge.open && !ui.knowledge.tags.length) await loadKnowledgeTags();
      return;
    }
    if (action === "refresh-knowledge-tags") {
      await loadKnowledgeTags();
      return;
    }
    if (action === "apply-knowledge-tags") {
      await applyKnowledgeTags();
      return;
    }
    if (action === "new-knowledge-tag") {
      if (ui.knowledge.formOpen && !ui.knowledge.editingId) {
        ui.knowledge.formOpen = false;
        ui.knowledge.form = emptyKnowledgeTagForm();
        render();
      } else {
        openKnowledgeForm("");
      }
      return;
    }
    if (action === "edit-knowledge-tag") {
      openKnowledgeForm(actionElement.dataset.tagId);
      return;
    }
    if (action === "cancel-knowledge-edit") {
      ui.knowledge.formOpen = false;
      ui.knowledge.editingId = "";
      ui.knowledge.form = emptyKnowledgeTagForm();
      render();
      return;
    }
    if (action === "save-knowledge-tag") {
      await saveKnowledgeTag();
      return;
    }
    if (action === "delete-knowledge-tag") {
      await deleteKnowledgeTag(actionElement.dataset.tagId);
      return;
    }
    if (action === "refresh-assets") {
      await loadAssets();
      return;
    }
    if (action === "open-asset") {
      await openAsset(actionElement.dataset.projectId);
      return;
    }
    if (action === "delete-asset") {
      await deleteAsset(actionElement.dataset.projectId);
      return;
    }
    if (action === "duplicate-asset") {
      await duplicateAsset(actionElement.dataset.projectId);
      return;
    }
    if (action === "stop-asset-task") {
      await controlAssetTask(actionElement.dataset.taskId, "stop");
      return;
    }
    if (action === "continue-asset-task") {
      await controlAssetTask(actionElement.dataset.taskId, "continue");
      return;
    }
    if (action === "refresh-stage-history") {
      await loadStageHistory(actionElement.dataset.stageKey);
      return;
    }
    if (action === "load-stage-history") {
      await loadHistoryVersion(actionElement.dataset.stageKey, actionElement.dataset.historyFile);
      return;
    }
    if (action === "tree-expand-all") {
      ui.rawTreeAllOpen = true;
      ui.rawTreeAllCollapsed = false;
      render();
      return;
    }
    if (action === "tree-collapse-all") {
      ui.rawTreeAllOpen = false;
      ui.rawTreeAllCollapsed = true;
      ui.expandedRawTree = {};
      render();
      return;
    }
    if (action === "collapse-tree-node") {
      const detail = actionElement.closest("details[data-tree-node]");
      if (detail) {
        ui.expandedRawTree[String(detail.dataset.treeNode || "")] = false;
        detail.open = false;
      }
      return;
    }
    if (action === "go-next-stage") {
      await goNextStage(actionElement.dataset.view);
      return;
    }
    if (action === "reset-state") {
      resetState();
      return;
    }
    if (action === "copy-final-package") {
      copyText(prettyJson({
        framework_plan_package: state.framework_plan_package,
        validation_report: state.validation_report,
      }), "已复制最终策划包");
      return;
    }
    if (action === "save-framework-asset") {
      await saveFrameworkAsset();
      return;
    }
    if (action === "start-framework-script") {
      await startFrameworkScript();
      return;
    }
    if (action === "confirm-basic") {
      await confirmBasic();
      return;
    }
    if (action === "run-stage-generate") {
      const stageKey = actionElement.dataset.stageKey;
      try {
        await runStage(stageKey, { revise: false });
        if (stageKey === "package") {
          showToast("已生成最终策划包");
        } else {
          showToast("已生成，若有人工修改请先更新再确认");
        }
      } catch (error) {
        showToast(formatStageError(error, stageNoForKey(stageKey)));
      }
      return;
    }
    if (action === "run-stage-revise") {
      const stageKey = actionElement.dataset.stageKey;
      try {
        await runStage(stageKey, { revise: true });
        showToast("已按修改意见更新，确认后才会解锁下游");
      } catch (error) {
        showToast(formatStageError(error, stageNoForKey(stageKey)));
      }
      return;
    }
    if (action === "apply-stage-preference") {
      applyStagePreference(actionElement.dataset.stageKey);
      return;
    }
    if (action === "confirm-stage") {
      await confirmStage(actionElement.dataset.stageKey);
      return;
    }
    if (action === "rollback-stage") {
      rollbackStage(actionElement.dataset.stageKey);
      return;
    }
    if (action === "open-editor") {
      openEditor(actionElement.dataset.editorStage, actionElement.dataset.editorKey);
      return;
    }
    if (action === "cancel-editor") {
      cancelEditor(actionElement.dataset.editorStage);
      return;
    }
    if (action === "save-editor") {
      saveEditor(actionElement.dataset.editorKey, actionElement.dataset.stageKey);
      return;
    }
    if (action === "change-storyline-decision") {
      applyStorylineDecision(actionElement.dataset.storylineId, actionElement.value);
      return;
    }
    if (action === "open-storyline-modal") {
      openStorylineModal(actionElement.dataset.storylineId);
      return;
    }
    if (action === "close-storyline-modal") {
      if (!event.target.closest("[data-modal-content='storyline']") || event.target === actionElement) {
        closeStorylineModal();
      } else {
        closeStorylineModal();
      }
      return;
    }
    if (action === "save-storyline-modal") {
      saveStorylineModal(actionElement.dataset.storylineId);
      return;
    }
  });

  document.addEventListener("click", (event) => {
    if (event.target && event.target.matches(".fp-modal-mask[data-action='close-storyline-modal']")) {
      closeStorylineModal();
    }
    if (event.target && event.target.matches(".fp-modal-mask[data-action='close-new-script']")) {
      ui.showNewScriptModal = false;
      render();
    }
  });

  window.frameworkPlannerDebug = {
    getState: () => clone(state),
    buildWorkingPayload,
    buildStagePayload: (stageKey, options) => cleanOutgoingPayload(attachKnowledgePayload(buildStagePayload(stageKey, options || {}), stageKey), `debug stage ${stageKey} payload`),
    getLastStagePayloadPreview: () => clone(ui.lastStagePayloadPreview),
    runBeatScoreLoop,
  };

  window.addEventListener("beforeunload", (event) => {
    if (ui.suppressBeforeUnload || !hasUnsavedChanges()) return;
    event.preventDefault();
    event.returnValue = UNSAVED_MESSAGE;
  });

  render();
  loadKnowledgePreferences().catch(() => {});
  loadAssets().catch(() => {});
  loadStageHistory(stageKeyForView(state.current_view || "basic")).catch(() => {});
})();
