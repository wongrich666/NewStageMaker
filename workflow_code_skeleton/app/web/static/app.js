(() => {
  "use strict";

  const userKey = `user.${window.scriptMakerConfig.userId || "anon"}`;
  const draftStorage = window.localStorage;
  const pageStorage = window.sessionStorage;
  const STORAGE = {
    draft: `scriptmaker.web.${userKey}.draft`,
    selectedProjectId: `scriptmaker.web.${userKey}.selectedProjectId`,
    modelId: `scriptmaker.web.${userKey}.modelId`,
    sidebarCollapsed: `scriptmaker.web.${userKey}.sidebarCollapsed`,
    userKnowledge: `scriptmaker.web.${userKey}.userKnowledge`,
    hotReviewSession: `scriptmaker.web.${userKey}.hotReviewSession`
  };

  const POLL_INTERVAL = 1500;
  const MAX_EXPECTATION_LINES = 5;
  const RUNNING_STATUSES = new Set(["pending", "running", "pausing"]);
  const RESUMABLE_STATUSES = new Set(["paused", "pausing", "failed", "terminated"]);
  const TERMINATABLE_STATUSES = new Set(["pending", "running", "pausing", "paused", "failed"]);
  const HOT_REVIEW_RUN_TIMEOUT_MS = 75 * 60 * 1000;
  const HOT_REVIEW_RESULT_POLL_INTERVAL_MS = 10000;
  const HOT_REVIEW_RESULT_POLL_GRACE_MS = 10000;
  const CHARACTER_RESKIN_RUNNING_MESSAGES = [
    "正在运行：统计原剧本实际集数...",
    "正在运行：生成人设循环变量...",
    "正在运行：审核人设循环变量...",
    "正在运行：必要时修订人设循环变量...",
    "正在运行：整理人设...",
    "正在运行：按批次编写角色对话...",
    "正在运行：审核角色对话...",
    "正在运行：必要时修订角色对话...",
    "正在运行：按批次编写剧本正文...",
    "正在运行：审核剧本正文...",
    "正在运行：必要时修订剧本正文...",
    "正在运行：保存剧本记忆并拼接最终正文..."
  ];
  const $ = (id) => document.getElementById(id);
  const currentAuthToken = () => new URL(window.location.href).searchParams.get("auth_token") || "";

  const els = {
    workspaceShell: document.querySelector(".chat-workspace-shell"),
    workspaceSidebar: $("workspaceCard"),
    sidebarToggleBtn: $("sidebarToggleBtn"),
    assistantToolsFolder: $("assistantToolsFolder"),
    waibaoScriptBtn: $("waibaoScriptBtn"),
    toolList: $("toolList"),
    toolPanel: $("toolPanel"),
    toolPanelTitle: $("toolPanelTitle"),
    closeToolPanelBtn: $("closeToolPanelBtn"),
    openCommunityPanelLink: $("openCommunityPanelLink"),
    communityPanel: $("community"),
    closeCommunityPanelBtn: $("closeCommunityPanelBtn"),
    modelSelect: $("modelSelect"),
    expectationInput: $("expectationInput"),
    userKnowledgePanel: $("userKnowledgePanel"),
    knowledgeTagList: $("knowledgeTagList"),
    knowledgeTagStatus: $("knowledgeTagStatus"),
    selectedKnowledgeTags: $("selectedKnowledgeTags"),
    applyKnowledgeTagsBtn: $("applyKnowledgeTagsBtn"),
    userPreferenceInput: $("userPreferenceInput"),
    knowledgePreferencePreview: $("knowledgePreferencePreview"),
    knowledgeTagNameInput: $("knowledgeTagNameInput"),
    knowledgeTagCategoryInput: $("knowledgeTagCategoryInput"),
    knowledgeTagDescriptionInput: $("knowledgeTagDescriptionInput"),
    knowledgeTagPromptInput: $("knowledgeTagPromptInput"),
    createKnowledgeTagBtn: $("createKnowledgeTagBtn"),
    characterCountInput: $("characterCountInput"),
    episodeCountInput: $("episodeCountInput"),
    formHint: $("formHint"),

    startBtn: $("startBtn"),
    newGenerationWindowBtn: $("newGenerationWindowBtn"),
    multiOpenCountSelect: $("multiOpenCountSelect"),
    pauseBtn: $("pauseBtn"),
    resumeBtn: $("resumeBtn"),
    terminateBtn: $("terminateBtn"),
    clearBtn: $("clearBtn"),
    saveBtn: $("saveBtn"),
    completionPanel: $("completionPanel"),
    confirmCompletionBtn: $("confirmCompletionBtn"),
    rollbackRewriteBtn: $("rollbackRewriteBtn"),
    rollbackStageSelect: $("rollbackStageSelect"),
    rollbackScriptStartSelect: $("rollbackScriptStartSelect"),
    cacheNoticeText: $("cacheNoticeText"),
    refreshProjectsBtn: $("refreshProjectsBtn"),
    workspaceCard: $("workspaceCard"),
    activeWorkspaceFolder: $("activeWorkspaceFolder"),
    completedWorkspaceFolder: $("completedWorkspaceFolder"),
    activeProjectList: $("activeProjectList"),
    completedProjectList: $("completedProjectList"),
    assetSubnav: $("assetSubnav"),
    assetDetailPanel: $("assetDetailPanel"),
    newScriptProjectList: $("newScriptProjectList"),
    waibaoProjectList: $("waibaoProjectList"),
    characterReskinProjectList: $("characterReskinProjectList"),
    activeProjectCount: $("activeProjectCount"),
    completedProjectCount: $("completedProjectCount"),

    openProfileBtn: $("openProfileBtn"),
    closeProfileBtn: $("closeProfileBtn"),
    closeProfileBackdrop: $("closeProfileBackdrop"),
    profilePanel: $("profilePanel"),
    newAssetBtn: $("newAssetBtn"),
    newScriptBtn: $("newScriptBtn"),
    viewAssetsBtn: $("viewAssetsBtn"),
    refreshAssetsBtn: $("refreshAssetsBtn"),
    refreshCommunityBtn: $("refreshCommunityBtn"),
    assetsList: $("assetsList"),
    communityList: $("communityList"),
    assetEditor: $("assetEditor"),
    assetDeleteDialog: $("assetDeleteDialog"),
    assetDeleteBackdrop: $("assetDeleteBackdrop"),
    assetDeleteMessage: $("assetDeleteMessage"),
    confirmDeleteAssetBtn: $("confirmDeleteAssetBtn"),
    cancelDeleteAssetBtn: $("cancelDeleteAssetBtn"),
    editAssetTitle: $("editAssetTitle"),
    editAssetSummary: $("editAssetSummary"),
    editAssetPrivacy: $("editAssetPrivacy"),
    editAssetFinal: $("editAssetFinal"),
    saveAssetEditBtn: $("saveAssetEditBtn"),
    cancelAssetEditBtn: $("cancelAssetEditBtn"),
    usernameForm: $("usernameForm"),
    passwordForm: $("passwordForm"),
    profileUsernameInput: $("profileUsernameInput"),
    currentPasswordInput: $("currentPasswordInput"),
    newPasswordInput: $("newPasswordInput"),
    confirmPasswordInput: $("confirmPasswordInput"),
    profileMessage: $("profileMessage"),
    toolForms: $("toolForms"),
    runToolBtn: $("runToolBtn"),
    downloadToolBtn: $("downloadToolBtn"),
    toolHistory: $("toolHistory"),
    toolHistoryCount: $("toolHistoryCount"),
    toolHistoryList: $("toolHistoryList"),
    toolOutputBox: $("toolOutputBox"),

    statusText: $("statusText"),
    messageText: $("messageText"),
    stageText: $("stageText"),
    waitDurationText: $("waitDurationText"),
    progressFill: $("progressFill"),
    progressText: $("progressText"),
    projectText: $("projectText"),
    taskText: $("taskText"),
    scriptFormatText: $("scriptFormatText"),
    chatTranscript: $("chatTranscript"),
    outputTitle: $("outputTitle"),
    outputNaturalBox: $("outputNaturalBox"),
    finalOutputBox: $("finalOutputBox"),
    composerModeText: $("composerModeText"),
  };

  const state = {
    projectId: null,
    taskId: null,
    status: "idle",
    pollTimer: null,
    debugPollTimer: null,
    lastConsoleLogIndex: 0,
    lastDebugTaskId: "",
    lastDebugError: "",
    availableModels: [],
    latestSnapshot: null,
    projects: [],
    projectStatusMap: {},
    projectsInitialized: false,
    assets: [],
    communityAssets: [],
    editingProjectId: null,
    editingProjectStatus: null,
    editingAssetKind: "",
    editingAssetLocked: false,
    assetEditMode: "view",
    assetDirty: false,
    assetDeleteConfirmResolver: null,
    assetDeleteHideTimer: null,
    toolDefinitions: {},
    activeTool: "hot_review",
    toolDrafts: {},
    toolResults: {},
    toolProgressTimer: null,
    toolProgressIndex: 0,
    knowledgeTags: [],
    selectedKnowledgeTagIds: [],
    userKnowledgeTagPrompt: "",
    userKnowledgeError: "",
    loadingActions: {},
    assetsStatus: "idle",
    assetsError: "",
    assetsPage: 1,
    communityStatus: "idle",
    communityError: "",
    communityPage: 1,
    lastTranscriptSignature: "",
    elapsedTimer: null,
    workspaceCollapseTimer: null,
    expandedUserPrompts: {}
  };

  const DEFAULT_TOOL_DEFINITIONS = {
    hot_review: {
      key: "hot_review",
      label: "爆款文审核",
      help: "提交待审核剧本，让工具返回完整审核意见，并支持下载 TXT。",
      fields: [
        { name: "review_text", label: "待审核剧本", type: "textarea", placeholder: "粘贴待审核的剧本、大纲或片段。", required: true }
      ],
      configured: false,
      source: "fallback"
    },
    punchup: {
      key: "punchup",
      label: "增加爽感",
      help: "不改主干情节，重点增强爽点、节奏和表达力度。",
      fields: [
        { name: "title", label: "剧本名", type: "input", placeholder: "原剧本名。", required: true },
        { name: "story_outline", label: "故事梗概", type: "textarea", placeholder: "故事梗概。", required: true },
        { name: "characters", label: "人物小传", type: "textarea", placeholder: "人物设定。", required: true },
        { name: "core_scenes", label: "核心场景", type: "textarea", placeholder: "核心场景。", required: true },
        { name: "script", label: "剧本正文", type: "textarea", placeholder: "需要增爽的剧本正文。", required: true },
        { name: "total_episodes", label: "总集数", type: "number", placeholder: "总集数。", required: true }
      ],
      configured: false,
      source: "fallback"
    },
    character_reskin: {
      key: "character_reskin",
      label: "只换人设",
      help: "保留主剧情结构，重点替换人物小传和角色设定。",
      fields: [
        { name: "title", label: "剧本标题", type: "input", placeholder: "新剧本标题。", required: true },
        { name: "story_outline", label: "故事大纲", type: "textarea", placeholder: "故事大纲。", required: true },
        { name: "characters", label: "人物小传", type: "textarea", placeholder: "需要替换的人物小传。", required: true },
        { name: "core_scenes", label: "核心场景", type: "textarea", placeholder: "核心场景。", required: true },
        { name: "source_script", label: "原剧本正文", type: "textarea", placeholder: "原剧本正文。", required: true },
        { name: "total_episodes", label: "总集数", type: "number", placeholder: "总集数。", required: true },
        { name: "episode_word_count", label: "每集正文字数", type: "number", placeholder: "每集字数。", required: true }
      ],
      configured: false,
      source: "fallback"
    },
    sitcom_generator: {
      key: "sitcom_generator",
      label: "情景剧生成",
      help: "固定人物与关系，每集生成一个独立闭环故事，结果自动保存到新剧本资产。",
      fields: [
        { name: "project_title", label: "情景剧名称", type: "input", placeholder: "例如：合租屋奇遇记。", required: true },
        { name: "sitcom_requirement", label: "创作要求", type: "textarea", placeholder: "题材、受众、笑点或冲突方向。", required: true },
        { name: "total_episodes", label: "总集数", type: "number", placeholder: "例如：20。", required: true, defaultValue: 20 },
        { name: "episode_word_count", label: "每集字数", type: "number", placeholder: "例如：1200。", required: true, defaultValue: 1200 },
        { name: "batch_start_episode", label: "本次起始集", type: "number", placeholder: "首次填 1。", required: true, defaultValue: 1 },
        { name: "batch_end_episode", label: "本次结束集", type: "number", placeholder: "建议每批 3-5 集。", required: true, defaultValue: 3 },
        { name: "fixed_characters", label: "固定人物设定", type: "textarea", placeholder: "姓名、身份、性格、关系和不可改变项。", required: true },
        { name: "main_scenes", label: "主要场景", type: "textarea", placeholder: "常驻场景及可变化的临时场景。", required: true },
        { name: "style_requirements", label: "风格要求", type: "textarea", placeholder: "轻喜剧、强反转、单集闭环。", required: false, defaultValue: "轻喜剧、节奏明快、单集闭环、人物性格稳定" },
        { name: "continuity_level", label: "连续性强度", type: "input", placeholder: "弱 / 中 / 强。", required: false, defaultValue: "弱" }
      ],
      configured: false,
      source: "fallback"
    },
    new_framework: {
      key: "new_framework",
      label: "15节拍剧本框架",
      help: "单独生成 15 节拍剧本框架 / 剧本大纲，并支持下载 TXT。",
      runUrl: "/api/tools/new-framework",
      fields: [
        { name: "story", label: "用户想要的故事", type: "textarea", placeholder: "输入故事方向、题材、人设、世界观、核心设定或一句话梗概。", required: true, defaultValue: "" },
        { name: "character_count", label: "角色数量", type: "number", placeholder: "需要生成的核心角色数量。", required: true, defaultValue: "" },
        { name: "story_scale", label: "故事体量", type: "input", placeholder: "例如：电影、短剧、长篇连续剧、单集剧本。", required: false, defaultValue: "连载爆款短剧" },
        { name: "total_episodes", label: "总集数或章节数", type: "number", placeholder: "例如 60。", required: true, defaultValue: 60 },
        { name: "genre_tone", label: "题材风格", type: "input", placeholder: "例如：悬疑复仇、都市情感、古装权谋。", required: false, defaultValue: "" },
        { name: "target_audience", label: "目标受众或平台风格", type: "input", placeholder: "例如：短剧爽感、长剧强情节、女性向。", required: false, defaultValue: "" }
      ],
      configured: false,
      source: "fallback"
    }
  };

  function isAuthenticated() {
    return Boolean(window.scriptMakerConfig.isAuthenticated);
  }

  function requireLogin() {
    if (isAuthenticated()) return true;
    window.location.href = window.scriptMakerConfig.loginUrl || "/login";
    return false;
  }

  function normalizeNumber(value) {
    const parsed = Number(value || 0);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }

  function currentUrl() {
    return new URL(window.location.href);
  }

  function updateUrlParams(mutator) {
    const url = currentUrl();
    mutator(url.searchParams);
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

  function isFreshWorkspaceMode() {
    const url = currentUrl();
    return url.searchParams.get("mode") === "new" && !normalizeNumber(url.searchParams.get("project_id"));
  }

  function readSelectedProjectId() {
    const url = currentUrl();
    if (url.searchParams.get("mode") === "new" && !normalizeNumber(url.searchParams.get("project_id"))) {
      return null;
    }
    const fromUrl = normalizeNumber(url.searchParams.get("project_id"));
    if (fromUrl) return fromUrl;
    return normalizeNumber(pageStorage.getItem(STORAGE.selectedProjectId));
  }

  function persistSelectedProjectId(projectId) {
    const normalized = normalizeNumber(projectId);
    if (normalized) {
      pageStorage.setItem(STORAGE.selectedProjectId, String(normalized));
    } else {
      pageStorage.removeItem(STORAGE.selectedProjectId);
    }
    const url = currentUrl();
    if (normalized) {
      url.searchParams.set("project_id", String(normalized));
      url.searchParams.delete("mode");
      url.searchParams.delete("script_format_mode");
    } else {
      url.searchParams.delete("project_id");
      if (!isFreshWorkspaceMode()) {
        url.searchParams.delete("mode");
      }
    }
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

  function buildWorkspaceUrl({ projectId = null, fresh = false, scriptFormatMode = "", windowSeed = "" } = {}) {
    const url = currentUrl();
    const basePath = window.scriptMakerConfig.workspaceUrl || url.pathname;
    url.pathname = basePath;
    url.searchParams.delete("project_id");
    url.searchParams.delete("mode");
    url.searchParams.delete("section");
    url.searchParams.delete("panel");
    url.searchParams.delete("script_format_mode");
    url.searchParams.delete("multi_open");
    if (projectId) {
      url.searchParams.set("project_id", String(projectId));
    } else if (fresh) {
      url.searchParams.set("mode", "new");
      const normalizedSeed = String(windowSeed || "").trim();
      if (normalizedSeed) {
        url.searchParams.set("multi_open", normalizedSeed);
      }
      const normalizedFormat = String(scriptFormatMode || "").trim().toLowerCase();
      if (normalizedFormat) {
        url.searchParams.set("script_format_mode", normalizedFormat);
      }
    }
    return `${url.pathname}${url.search}${url.hash}`;
  }

  function switchToFreshWorkspace() {
    state.projectId = null;
    state.taskId = null;
    state.status = "idle";
    state.latestSnapshot = null;
    closeCommunityPanel();
    persistSelectedProjectId(null);
    pageStorage.removeItem(STORAGE.selectedProjectId);
    const freshUrl = buildWorkspaceUrl({ fresh: true });
    window.history.replaceState({}, "", freshUrl);
    renderSnapshot(null);
  }

  function openWorkspaceInNewPage({ projectId = null, fresh = false, scriptFormatMode = "", windowSeed = "" } = {}) {
    window.open(buildWorkspaceUrl({ projectId, fresh, scriptFormatMode, windowSeed }), "_blank", "noopener");
  }

  function openFreshGenerationWindows(count = 1) {
    const normalizedCount = Math.max(1, Math.min(4, Number(count) || 1));
    for (let index = 0; index < normalizedCount; index += 1) {
      openWorkspaceInNewPage({
        fresh: true,
        windowSeed: `${Date.now()}-${index + 1}`
      });
    }
  }

  function statusLabel(status) {
    const mapping = {
      idle: "待开始",
      pending: "准备中",
      running: "生成中",
      pausing: "暂停中",
      paused: "已暂停",
      completed: "已完成",
      failed: "执行失败",
      terminated: "已终止"
    };
    return mapping[status] || status || "待开始";
  }

  function formatDuration(ms) {
    const totalSeconds = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    const hh = String(hours).padStart(2, "0");
    const mm = String(minutes).padStart(2, "0");
    const ss = String(seconds).padStart(2, "0");
    if (days > 0) {
      return `${days}天 ${hh}:${mm}:${ss}`;
    }
    if (hours > 0) {
      return `${hh}:${mm}:${ss}`;
    }
    return `${String(minutes).padStart(2, "0")}:${ss}`;
  }

  function snapshotWaitMs(snapshot) {
    if (!snapshot) return 0;
    const base = Number(snapshot.wait_elapsed_ms || 0);
    const liveStart = Date.parse(snapshot.wait_started_at || "");
    if (RUNNING_STATUSES.has(snapshot.status) && Number.isFinite(liveStart)) {
      return Math.max(0, base + (Date.now() - liveStart));
    }
    return Math.max(0, base);
  }

  function renderWaitDuration(snapshot = state.latestSnapshot) {
    if (!els.waitDurationText) return;
    if (!snapshot) {
      els.waitDurationText.textContent = "00:00";
      return;
    }
    els.waitDurationText.textContent = formatDuration(snapshotWaitMs(snapshot));
  }

  function startElapsedTimer() {
    if (state.elapsedTimer) return;
    state.elapsedTimer = window.setInterval(() => {
      renderWaitDuration(state.latestSnapshot);
      const statusMessage = statusNoteFrom(state.latestSnapshot);
      if (els.messageText) {
        els.messageText.textContent = statusMessage;
        els.messageText.classList.toggle("hidden", !statusMessage);
      }
    }, 1000);
  }

  function stopElapsedTimer() {
    if (state.elapsedTimer) {
      window.clearInterval(state.elapsedTimer);
      state.elapsedTimer = null;
    }
  }

  function syncElapsedTimer(snapshot = state.latestSnapshot) {
    const hasLiveElapsed = Boolean(
      snapshot
      && RUNNING_STATUSES.has(snapshot.status)
      && snapshot.wait_started_at
    );
    if (hasLiveElapsed) {
      startElapsedTimer();
    } else {
      stopElapsedTimer();
    }
    renderWaitDuration(snapshot);
  }

  function promptToggleKey(snapshot) {
    const projectId = normalizeNumber(snapshot?.project_id);
    if (projectId) return `project:${projectId}`;
    const taskId = String(snapshot?.task_id || "").trim();
    return taskId ? `task:${taskId}` : "current";
  }

  function inputLineCount(text) {
    const normalized = String(text || "").replace(/\r\n/g, "\n");
    return normalized ? normalized.split("\n").length : 1;
  }

  function normalizeScriptFormatMode(value) {
    const normalized = String(value || "").trim().toLowerCase();
    return normalized === "waibao" ? "waibao" : "";
  }

  function selectedScriptFormatMode() {
    const urlMode = normalizeScriptFormatMode(currentUrl().searchParams.get("script_format_mode"));
    if (urlMode) return urlMode;
    return normalizeScriptFormatMode(state.latestSnapshot?.input_payload?.script_format_mode);
  }

  function scriptFormatModeLabel(value) {
    return normalizeScriptFormatMode(value) === "waibao" ? "外包专属格式" : "标准格式";
  }

  function syncScriptFormatModeUi(snapshot = null) {
    const mode = normalizeScriptFormatMode(snapshot?.input_payload?.script_format_mode)
      || selectedScriptFormatMode();
    const label = scriptFormatModeLabel(mode);
    if (els.scriptFormatText) {
      els.scriptFormatText.textContent = label;
      els.scriptFormatText.dataset.mode = mode || "default";
    }
    if (els.composerModeText) {
      els.composerModeText.textContent = label;
      els.composerModeText.dataset.mode = mode || "default";
    }
    if (els.workspaceShell) {
      els.workspaceShell.dataset.scriptFormatMode = mode || "default";
    }
  }

  function syncExpectationInputHeight() {
    const textarea = els.expectationInput;
    if (!textarea) return;
    const style = window.getComputedStyle(textarea);
    const lineHeight = Number.parseFloat(style.lineHeight) || 24;
    const paddingTop = Number.parseFloat(style.paddingTop) || 0;
    const paddingBottom = Number.parseFloat(style.paddingBottom) || 0;
    const minHeight = Number.parseFloat(style.minHeight) || 54;
    const maxHeight = Math.max(minHeight, Math.ceil((lineHeight * MAX_EXPECTATION_LINES) + paddingTop + paddingBottom));
    textarea.style.height = "auto";
    const nextHeight = Math.max(minHeight, Math.min(textarea.scrollHeight, maxHeight));
    textarea.style.height = `${nextHeight}px`;
    const collapsed = textarea.scrollHeight > (maxHeight + 1);
    textarea.classList.toggle("is-collapsed", collapsed);
    textarea.style.overflowY = collapsed ? "auto" : "hidden";
  }

  function isRestartingCurrentProject() {
    return Boolean(state.projectId && ["failed", "terminated"].includes(state.status));
  }

  function fallbackExpectationForRestart() {
    if (!isRestartingCurrentProject()) return "";
    return String(state.latestSnapshot?.input_payload?.user_expectation || "").trim();
  }

  function saveDraft() {
    const draft = {
      user_expectation: els.expectationInput.value.trim(),
      character_count: Number(els.characterCountInput.value || 0),
      total_episodes: Number(els.episodeCountInput.value || 0),
      selected_preference_tag_ids: [...state.selectedKnowledgeTagIds],
      user_preference_prompt: String(els.userPreferenceInput?.value || ""),
      user_knowledge_tag_prompt: String(state.userKnowledgeTagPrompt || "")
    };
    draftStorage.setItem(STORAGE.draft, JSON.stringify(draft));
    draftStorage.setItem(STORAGE.modelId, els.modelSelect.value || "");
    draftStorage.setItem(STORAGE.userKnowledge, JSON.stringify({
      selected_preference_tag_ids: draft.selected_preference_tag_ids,
      user_preference_prompt: draft.user_preference_prompt,
      user_knowledge_tag_prompt: draft.user_knowledge_tag_prompt
    }));
  }

  function restoreDraft() {
    try {
      const raw = draftStorage.getItem(STORAGE.draft);
      if (!raw) return;
      const draft = JSON.parse(raw);
      els.expectationInput.value = draft.user_expectation || "";
      els.characterCountInput.value = draft.character_count || 5;
      els.episodeCountInput.value = draft.total_episodes || 10;
      restoreKnowledgeDraft(draft);
      syncExpectationInputHeight();
    } catch (_) {}
  }

  function restoreKnowledgeDraft(draft = null) {
    let data = draft;
    if (!data) {
      try {
        data = JSON.parse(draftStorage.getItem(STORAGE.userKnowledge) || "{}");
      } catch (_) {
        data = {};
      }
    }
    state.selectedKnowledgeTagIds = Array.isArray(data?.selected_preference_tag_ids)
      ? data.selected_preference_tag_ids.map((item) => String(item || "").trim()).filter(Boolean)
      : [];
    state.userKnowledgeTagPrompt = String(data?.user_knowledge_tag_prompt || "");
    if (els.userPreferenceInput) {
      els.userPreferenceInput.value = String(data?.user_preference_prompt || "");
    }
  }

  function clearDraft() {
    draftStorage.removeItem(STORAGE.draft);
    draftStorage.removeItem(STORAGE.userKnowledge);
  }

  // 记住侧边栏折叠状态，让用户切页面回来后仍保持同一工作台布局。
  function applySidebarCollapsed(collapsed) {
    if (!els.workspaceSidebar) return;
    const isCollapsed = Boolean(collapsed);
    els.workspaceSidebar.classList.toggle("is-collapsed", isCollapsed);
    els.workspaceShell?.classList.toggle("sidebar-collapsed", isCollapsed);
    els.sidebarToggleBtn?.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
    els.sidebarToggleBtn?.setAttribute("aria-label", isCollapsed ? "展开导航栏" : "收起导航栏");
    if (els.sidebarToggleBtn) els.sidebarToggleBtn.title = isCollapsed ? "展开导航栏" : "收起导航栏";
    if (isCollapsed) {
      els.workspaceSidebar.querySelectorAll("details[open]").forEach((folder) => {
        folder.open = false;
      });
    }
    draftStorage.setItem(STORAGE.sidebarCollapsed, isCollapsed ? "1" : "0");
  }

  function restoreSidebarCollapsed() {
    applySidebarCollapsed(draftStorage.getItem(STORAGE.sidebarCollapsed) === "1");
  }

  function hotReviewSessionAssetKey(result) {
    return String(
      result?.savedAsset?.project_id
      || result?.saved_asset?.project_id
      || result?.savedAsset?.id
      || result?.project_id
      || ""
    ).trim();
  }

  function persistHotReviewSession(result = state.toolResults.hot_review) {
    if (!result) return;
    const normalized = normalizeScriptAuditEcgResult(result);
    const assetKey = hotReviewSessionAssetKey(normalized);
    const payload = {
      tool: "hot_review",
      assetKey,
      draft: state.toolDrafts.hot_review || {},
      result: normalized,
      updatedAt: new Date().toISOString(),
    };
    try {
      pageStorage.setItem(STORAGE.hotReviewSession, JSON.stringify(payload));
    } catch (_) {
      if (!assetKey) return;
      try {
        pageStorage.setItem(STORAGE.hotReviewSession, JSON.stringify({
          tool: "hot_review",
          assetKey,
          draft: state.toolDrafts.hot_review || {},
          updatedAt: payload.updatedAt,
        }));
      } catch (__) {}
    }
  }

  function readHotReviewSession() {
    try {
      const raw = pageStorage.getItem(STORAGE.hotReviewSession);
      if (!raw) return null;
      const payload = JSON.parse(raw);
      return payload && payload.tool === "hot_review" ? payload : null;
    } catch (_) {
      return null;
    }
  }

  function normalizeProjectText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function shortenProjectText(value, maxLength = 18) {
    const text = normalizeProjectText(value);
    if (!text) return "";
    if (text.length <= maxLength) return text;
    return `${text.slice(0, maxLength)}...`;
  }

  function projectDisplayTitle(projectLike) {
    if (!projectLike) return "未选中";
    const artifacts = projectLike.artifacts || {};
    const inputPayload = projectLike.input_payload || {};
    const directTitle = [
      projectLike.title,
      artifacts.script_title_content,
      projectLike.script_title_content,
      inputPayload.title
    ].map(normalizeProjectText).find(Boolean);
    if (directTitle) {
      return directTitle;
    }
    const expectationText = [
      inputPayload.user_expectation,
      projectLike.user_expectation
    ].map(normalizeProjectText).find(Boolean);
    if (expectationText) {
      return shortenProjectText(expectationText);
    }
    const projectId = normalizeNumber(projectLike.project_id);
    return projectId ? `项目 ${projectId}` : "未命名剧本";
  }

  function runtimeProjectDisplayTitle(projectLike) {
    if (!projectLike) return "未选中";
    const artifacts = projectLike.artifacts || {};
    const inputPayload = projectLike.input_payload || {};
    const generatedTitle = [
      artifacts.script_title_content,
      projectLike.script_title_content
    ].map(normalizeProjectText).find(Boolean);
    if (generatedTitle) {
      return generatedTitle;
    }
    const savedTitle = [
      projectLike.title,
      inputPayload.title
    ].map(normalizeProjectText).find(Boolean);
    if (savedTitle) {
      return savedTitle;
    }
    const expectationText = [
      inputPayload.user_expectation,
      projectLike.user_expectation
    ].map(normalizeProjectText).find(Boolean);
    if (expectationText) {
      return shortenProjectText(expectationText);
    }
    return projectDisplayTitle(projectLike);
  }

  function formHasUserInput() {
    return Boolean(
      els.expectationInput.value.trim()
      || Number(els.characterCountInput.value || 5) !== 5
      || Number(els.episodeCountInput.value || 10) !== 10
    );
  }

  function restoreInputPayload(inputPayload, { force = false } = {}) {
    if (!inputPayload || (!force && formHasUserInput())) return;
    els.expectationInput.value = "";
    els.characterCountInput.value = inputPayload.character_count || 5;
    els.episodeCountInput.value = inputPayload.total_episodes || 10;
    state.selectedKnowledgeTagIds = Array.isArray(inputPayload.selected_preference_tag_ids)
      ? inputPayload.selected_preference_tag_ids.map((item) => String(item || "").trim()).filter(Boolean)
      : [];
    state.userKnowledgeTagPrompt = String(inputPayload.user_knowledge_tag_prompt || "");
    if (els.userPreferenceInput) {
      els.userPreferenceInput.value = String(inputPayload.user_preference_prompt || "");
    }
    renderUserKnowledgePanel();
    syncExpectationInputHeight();
    saveDraft();
  }

  function currentModelLabel() {
    const selected = state.availableModels.find((item) => item.id === els.modelSelect.value);
    return selected?.label || "未选择";
  }

  function isTechnicalErrorText(text) {
    const value = String(text || "").trim();
    if (!value) return false;
    if (value.length > 120) return true;
    return [
      "fastgpt",
      "traceback",
      "http ",
      "response.text",
      "url:",
      "url：",
      "requests.",
      "exception",
      "typeerror",
      "bad gateway",
      "failed to fetch",
      "json",
      "校验失败",
      "无法转换",
      ".py"
    ].some((marker) => value.toLowerCase().includes(marker));
  }

  function friendlyErrorText(error, fallback = "操作失败，请稍后重试。", context = {}) {
    const text = String(error?.message || "").trim();
    const toolKey = String(context?.toolKey || "").trim();
    if (error?.name === "AbortError") {
      return toolKey === "hot_review"
        ? "爆款文审核等待时间过长，已停止等待。当前输入已保留，可以稍后重试，或减少提交文本长度后再运行。"
        : "请求等待时间过长，已停止等待。请稍后重试，或减少提交文本长度后再运行。";
    }
    if (/timeout|timed\s*out|超时/i.test(text)) {
      return toolKey === "hot_review"
        ? "爆款文审核请求超时了。它耗时较长，当前输入已保留，可以稍后重试，或减少提交文本长度后再运行。"
        : "请求超时了。请稍后重试，或减少提交文本长度后再运行。";
    }
    if (/failed\s*to\s*fetch|networkerror|network\s*error|load\s*failed|断开|网络/i.test(text)) {
      return "网络请求暂时中断，请稍后刷新或重新点击。";
    }
    if (!text || isTechnicalErrorText(text)) {
      return fallback;
    }
    return text;
  }

  function showStatusError(error, fallback = "操作失败，请稍后重试。") {
    els.messageText.textContent = friendlyErrorText(error, fallback);
    els.messageText.classList.toggle("hidden", !els.messageText.textContent);
  }

  function showProfileError(error, fallback = "保存失败，请稍后重试。") {
    if (!els.profileMessage) return;
    els.profileMessage.textContent = friendlyErrorText(error, fallback);
  }

  function showToolError(error, fallback = "工具执行失败，请稍后重试。", context = {}) {
    if (!els.toolOutputBox) return;
    els.toolOutputBox.innerHTML = renderToolErrorCard(error, fallback, {
      toolKey: context.toolKey || state.activeTool
    });
  }

  function renderToolErrorCard(error, fallback = "工具执行失败，请稍后重试。", context = {}) {
    const message = friendlyErrorText(error, fallback, context);
    const raw = String(error?.message || "").trim();
    const showRaw = raw && raw !== message && !isTechnicalErrorText(raw);
    return `
      <section class="tool-error-card" role="alert">
        <div class="tool-error-icon">!</div>
        <div>
          <h4>运行失败</h4>
          <p>${escapeHtml(message)}</p>
          ${showRaw ? `<small>${escapeHtml(raw)}</small>` : ""}
          <div class="tool-error-actions">
            <span>当前输入已保留，可以直接重新运行。</span>
          </div>
        </div>
      </section>
    `;
  }

  function runtimeDebugUrl(taskId) {
  const base = `/api/tasks/${encodeURIComponent(taskId)}/debug`;
  const token = currentAuthToken();
  if (!token) {
    return base;
  }
  return `${base}?auth_token=${encodeURIComponent(token)}`;
}

function ensureRuntimeDebugPanel() {
  if (window.scriptMakerConfig?.enableRuntimeDebugPanel !== true) {
    return null;
  }
  let panel = document.getElementById("runtime-version-panel") || document.getElementById("runtime-debug-panel");
  if (panel) {
    return panel;
  }

  panel = document.createElement("section");
  panel.id = "runtime-version-panel";
  panel.style.cssText = [
    "position:fixed",
    "right:16px",
    "bottom:16px",
    "z-index:9999",
    "width:min(520px, calc(100vw - 32px))",
    "max-height:70vh",
    "overflow:auto",
    "background:#111827",
    "color:#e5e7eb",
    "border:1px solid rgba(255,255,255,0.16)",
    "border-radius:12px",
    "box-shadow:0 18px 45px rgba(0,0,0,0.35)",
    "padding:12px",
    "font-size:12px",
    "line-height:1.5",
  ].join(";");

  panel.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;">
      <strong>运行状态 / 版本历史</strong>
      <button type="button" data-role="close-version-panel" style="border:0;border-radius:8px;padding:4px 8px;cursor:pointer;">隐藏</button>
    </div>
    <div data-role="summary" style="margin-bottom:8px;color:#cbd5e1;"></div>
    <details open style="margin-bottom:8px;">
      <summary style="cursor:pointer;color:#f9fafb;">当前版本</summary>
      <div data-role="version" style="display:flex;flex-direction:column;gap:6px;background:#020617;border-radius:8px;padding:8px;margin:8px 0 0;max-height:260px;overflow:auto;"></div>
    </details>
    <details open>
      <summary style="cursor:pointer;color:#f9fafb;">版本历史</summary>
      <div data-role="versions" style="display:flex;flex-direction:column;gap:6px;margin-top:8px;"></div>
    </details>
  `;

  const closeButton = panel.querySelector("[data-role='close-version-panel']");
  closeButton?.addEventListener("click", () => {
    panel.style.display = "none";
  });

  document.body.appendChild(panel);
  return panel;
}

function renderRuntimeDebug(debug) {
  if (window.scriptMakerConfig?.enableRuntimeDebugPanel !== true) {
    return;
  }
  if (!debug || typeof debug !== "object") {
    return;
  }
  const debugTaskId = String(debug.task_id || "").trim();
  if (debugTaskId && debugTaskId !== state.lastDebugTaskId) {
    state.lastDebugTaskId = debugTaskId;
    state.lastConsoleLogIndex = 0;
    state.lastDebugError = "";
  }

  const panel = ensureRuntimeDebugPanel();
  if (!panel) return;
  panel.style.display = "";

  const summary = panel.querySelector("[data-role='summary']");
  const versionBox = panel.querySelector("[data-role='version']");
  const versionsBox = panel.querySelector("[data-role='versions']");

  const logs = Array.isArray(debug.logs) ? debug.logs : [];
  const versionRows = [
    ["项目编号", debug.project_id],
    ["任务状态", debug.status],
    ["当前阶段", debug.current_stage_label || debug.current_stage],
    ["当前批次", debug.current_batch],
    ["完成进度", debug.progress_percent ? `${debug.progress_percent}%` : ""],
    ["已生成集数", debug.generated_episodes],
    ["等待确认", debug.awaiting_user_confirmation ? "是" : "否"],
  ].filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== "");

  if (summary) {
    summary.textContent = [
      `status=${debug.status || "-"}`,
      `stage=${debug.current_stage || "-"}`,
      `node=${debug.current_node_name || debug.current_node_id || "-"}`,
      `运行记录=${logs.length}`,
      `checkpoint=${debug.resume_checkpoint_exists ? "yes" : "no"}`,
    ].join(" | ");
  }

  if (versionBox) {
    versionBox.innerHTML = versionRows.map(([label, value]) => `
      <div style="display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid rgba(255,255,255,0.08);padding-bottom:4px;">
        <span style="color:#94a3b8;">${escapeHtml(label)}</span>
        <strong style="color:#e5e7eb;text-align:right;">${escapeHtml(String(value))}</strong>
      </div>
    `).join("");
  }

  if (versionsBox) {
    if (!logs.length) {
      versionsBox.innerHTML = `<div style="color:#94a3b8;">暂无版本历史。</div>`;
    } else {
      versionsBox.innerHTML = logs
        .slice(-80)
        .map((item) => {
          const level = escapeHtml(String(item.level || "info"));
          const time = escapeHtml(String(item.time || ""));
          const title = escapeHtml(String(item.title || ""));
          const message = escapeHtml(String(item.message || ""));
          const nodeId = item.node_id ? ` <span style="color:#94a3b8;">${escapeHtml(String(item.node_id))}</span>` : "";
          return `
            <div style="border:1px solid rgba(255,255,255,0.10);border-radius:8px;padding:6px;background:rgba(255,255,255,0.04);">
              <div style="color:#93c5fd;">[${level}] ${time}${nodeId}</div>
              <div style="font-weight:600;color:#f9fafb;">${title}</div>
              <div style="color:#d1d5db;">${message}</div>
            </div>
          `;
        })
        .join("");
    }
  }

  for (const item of logs) {
    const index = Number(item.index || 0);
    if (!index || index <= state.lastConsoleLogIndex) {
      continue;
    }

    const line = [
      "[runtime-log]",
      item.time || "",
      item.level || "info",
      item.title || "",
      item.message || "",
    ].join(" ");

    if (String(item.level || "").toLowerCase() === "error") {
      console.error(line, item);
    } else {
      console.log(line, item);
    }

    state.lastConsoleLogIndex = Math.max(state.lastConsoleLogIndex, index);
  }

  if (debug.error && debug.error !== state.lastDebugError) {
    console.error("[runtime-error]", debug.error);
    state.lastDebugError = debug.error;
  }
}

async function fetchRuntimeDebug() {
  const taskId = String(state.taskId || state.latestSnapshot?.task_id || "").trim();
  if (!taskId) {
    return;
  }

  state.taskId = taskId;

  const response = await fetch(runtimeDebugUrl(taskId), {
    headers: {
      Accept: "application/json",
    },
  });

  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload || payload.ok === false) {
    const message = payload?.error || payload?.message || `debug 请求失败：${response.status}`;
    throw new Error(message);
  }

  renderRuntimeDebug(payload.debug || {});
}

function startRuntimeDebugPolling() {
  if (window.scriptMakerConfig?.enableRuntimeDebugPanel !== true) {
    return;
  }
  if (state.debugPollTimer) {
    return;
  }

  state.debugPollTimer = window.setInterval(() => {
    fetchRuntimeDebug().catch((error) => {
      if (error?.message && error.message !== state.lastDebugError) {
        console.error("[runtime-debug-fetch-error]", error);
        state.lastDebugError = error.message;
      }
    });
  }, 2000);

  fetchRuntimeDebug().catch(() => {});
}

startRuntimeDebugPolling();

  function compactMessageText(value) {
    return String(value || "").trim();
  }

  async function copyTextToClipboard(text) {
    const content = compactMessageText(text);
    if (!content) return false;
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(content);
      return true;
    }
    const helper = document.createElement("textarea");
    helper.value = content;
    helper.setAttribute("readonly", "readonly");
    helper.style.position = "fixed";
    helper.style.opacity = "0";
    helper.style.pointerEvents = "none";
    document.body.appendChild(helper);
    helper.focus();
    helper.select();
    const copied = document.execCommand("copy");
    helper.remove();
    return copied;
  }

  // 只在确认有最终成品时，给下载和保存按钮提供最终剧本文本。
  function finalOutputFrom(snapshot) {
    if (!snapshot) return "";
    const artifacts = snapshot?.artifacts || {};
    return artifacts.final_output_text || artifacts.final_script || "";
  }

  // 只展示用户真正关心的正式阶段内容，避免把中间过程直接摊开。
  function stageDisplayPayload(snapshot) {
    if (!snapshot) {
      return {
        title: "当前阶段输出",
        output: "",
        natural: ""
      };
    }
    if (isFrameworkToScriptSnapshot(snapshot) && normalizeStageKey(snapshot.current_stage) === "final") {
      return {
        title: "基于框架生成的剧本正文",
        output: snapshot.display_stage_output || finalOutputFrom(snapshot) || "",
        natural: snapshot.display_stage_output_natural || ""
      };
    }
    return {
      title: snapshot.display_stage_title || "当前阶段输出",
      output: snapshot.display_stage_output || "",
      natural: snapshot.display_stage_output_natural || ""
    };
  }

  function runtimeLoadingSuffix(snapshot, nowMs = Date.now()) {
    if (!snapshot || !RUNNING_STATUSES.has(snapshot.status)) return "";
    const frame = Math.floor(nowMs / 500) % 3;
    return ".".repeat(frame + 1);
  }

  function defaultRuntimeMessage(snapshot) {
    if (!snapshot) return "";
    const stageKey = String(snapshot.current_stage || "").trim().toLowerCase();
    const stageLabel = String(snapshot.current_stage_label || "").trim();
    const batch = String(snapshot.current_batch || "").trim();
    const mapping = {
      framework: "正在生成剧本框架",
      framework_naturalize: "正在整理剧本框架自然语言说明",
      appearance_strategy: "正在生成服装前置策略",
      appearance_pre_strategy: "正在生成服装前置策略",
      validation: "正在执行集数检查",
      consistency: "正在执行集数一致性检查",
      episode_plan_normalize: "正在规范化分集计划",
      worldview: "正在生成世界观",
      worldview_naturalize: "正在整理世界观自然语言说明",
      character: "正在生成人物设定",
      characters: "正在生成人物设定",
      scene: "正在生成核心场景",
      scenes: "正在生成核心场景",
      appearance: "正在生成服装版本映射",
      appearance_alias_generation: "正在生成服装版本映射",
      appearance_alias_writing: "正在编写服装版本映射",
      appearance_alias_review: "正在审核服装版本映射",
      appearance_alias_rewrite: "正在修订服装版本映射",
      appearance_alias_unstructured: "正在整理服装版本映射自然语言说明",
      framework_scene_dictionary: "正在生成框架转剧本：提炼核心场景",
      framework_appearanceMapping: "正在生成框架转剧本：人设服装 alias 映射",
      framework_enriched_episode_plan: "正在生成框架转剧本：丰富分集计划",
      framework_causal_conflict: "正在生成框架转剧本因果冲突推进计划",
      framework_causal_conflict_write: "正在编写框架转剧本：因果冲突推进计划",
      framework_causal_conflict_review: "正在审核框架转剧本：因果冲突推进计划",
      framework_causal_conflict_rewrite: "正在修订框架转剧本：因果冲突推进计划",
      framework_causal_conflict_memory: "正在写入框架转剧本：因果冲突记忆",
      framework_script: "正在生成框架转剧本正文对白融合稿",
      framework_script_write: "正在编写框架转剧本：正文对白融合",
      framework_script_review: "正在审核框架转剧本：正文对白融合",
      framework_script_rewrite: "正在修订框架转剧本：正文对白融合",
      framework_script_memory: "正在写入框架转剧本：正文记忆",
      hooks: "正在生成开头冲突钩子",
      hooks_writing: "正在生成开头冲突钩子",
      hook: "正在生成开头冲突钩子",
      hook_write: "正在生成开头冲突钩子",
      hooks_review: "正在审核开头冲突钩子",
      hook_review: "正在审核开头冲突钩子",
      hooks_rewrite: "正在修订开头冲突钩子",
      hook_revise: "正在修订开头冲突钩子",
      hook_memory: "正在写入开头冲突钩子记忆",
      dialogues: "正在生成角色对白",
      dialogues_writing: "正在生成角色对白",
      dialogue: "正在生成角色对白",
      dialogue_write: "正在生成角色对白",
      dialogues_review: "正在审核角色对白",
      dialogue_review: "正在审核角色对白",
      dialogues_rewrite: "正在修订角色对白",
      dialogue_revise: "正在修订角色对白",
      dialogue_memory: "正在写入角色对白记忆",
      script: "正在生成剧本正文",
      script_writing: "正在生成剧本正文",
      script_write: "正在生成剧本正文",
      script_review: "正在审核剧本正文",
      script_rewrite: "正在修订剧本正文",
      script_revise: "正在修订剧本正文",
      script_memory: "正在写入剧本正文记忆",
      final: "正在整理最终剧本",
      finalize: "正在整理最终剧本"
    };
    const base = mapping[stageKey] || (stageLabel ? `正在处理${stageLabel}` : "正在处理中");
    return batch ? `${base}：第 ${batch} 集` : base;
  }

  // 当前状态下只保留必要提示，避免和“当前阶段”重复。
  function statusNoteFrom(snapshot, nowMs = Date.now()) {
    if (!snapshot) return "";
    if (snapshot.status === "failed") {
      return "当前步骤执行失败，可继续或重试。";
    }
    if (snapshot.status === "terminated") {
      return "已终止。";
    }
    if (snapshot.status === "paused") {
      return snapshot.message || "已暂停。";
    }
    if (snapshot.status === "pausing") {
      return `${snapshot.message || "正在暂停"}${runtimeLoadingSuffix(snapshot, nowMs)}`;
    }
    if (snapshot.status === "completed") {
      return snapshot.awaiting_user_confirmation
        ? "剧本已生成完成，等待你确认是否满意。"
        : "剧本已完成。";
    }
    const runtimeMessage = String(snapshot.message || "").trim();
    const base = runtimeMessage || defaultRuntimeMessage(snapshot);
    if (!base) return "";
    return `${base}${runtimeLoadingSuffix(snapshot, nowMs)}`;
  }

  function creationStatusLabel(snapshot) {
    if (!snapshot) return "待开始";
    if (snapshot.status === "completed") return "已完成";
    if (snapshot.status === "paused" || snapshot.status === "pausing") return "已暂停";
    if (snapshot.status === "failed") return "执行失败";
    if (snapshot.status === "terminated") return "已终止";
    return "创作中";
  }

  function isFrameworkToScriptSnapshot(snapshot) {
    const inputPayload = snapshot?.input_payload || {};
    return Boolean(
      inputPayload.framework_to_script === true
      || String(inputPayload.generation_chain || "").trim() === "framework_to_script"
      || String(inputPayload.workflow_mode || "").trim() === "framework_to_script"
      || inputPayload.framework_planner_source === true
    );
  }

  function frameworkStageLabel(stageKey) {
    const mapping = {
      framework_scene_dictionary: "框架转剧本：提炼核心场景",
      framework_appearancemapping: "框架转剧本：人设服装 alias 映射",
      framework_appearance_mapping: "框架转剧本：人设服装 alias 映射",
      framework_enriched_episode_plan: "框架转剧本：丰富分集计划",
      framework_causal_conflict: "框架转剧本：因果冲突推进计划",
      framework_causal_conflict_write: "框架转剧本：因果冲突推进计划",
      framework_causal_conflict_review: "框架转剧本：因果冲突推进计划",
      framework_causal_conflict_rewrite: "框架转剧本：因果冲突推进计划",
      framework_causal_conflict_memory: "框架转剧本：因果冲突推进计划",
      framework_script: "框架转剧本：正文对白融合",
      framework_script_write: "框架转剧本：正文对白融合",
      framework_script_review: "框架转剧本：正文对白融合",
      framework_script_rewrite: "框架转剧本：正文对白融合",
      framework_script_memory: "框架转剧本：正文对白融合",
      final: "基于框架生成的剧本正文",
      finalize: "基于框架生成的剧本正文",
      finished: "基于框架生成的剧本正文",
    };
    return mapping[String(stageKey || "").trim().toLowerCase()] || "";
  }

  function displayStageLabel(snapshot) {
    const backendLabel = String(snapshot?.current_stage_label || "").trim();
    if (backendLabel) return backendLabel;
    if (isFrameworkToScriptSnapshot(snapshot)) {
      return frameworkStageLabel(snapshot.current_stage) || "正在处理";
    }
    return snapshot?.display_stage_title || "正在处理";
  }

  function fallbackProgressPercent(snapshot) {
    const stageKey = String(snapshot?.current_stage || "").trim().toLowerCase();
    if (!isFrameworkToScriptSnapshot(snapshot)) return 0;
    if (stageKey === "framework_scene_dictionary") return 8;
    if (stageKey === "framework_appearancemapping" || stageKey === "framework_appearance_mapping") return 14;
    if (stageKey === "framework_enriched_episode_plan") return 22;
    if (stageKey.startsWith("framework_causal_conflict")) return 45;
    if (stageKey.startsWith("framework_script")) return 78;
    if (["final", "finalize", "finished"].includes(stageKey) || snapshot?.status === "completed") return 100;
    return 0;
  }

  function displayProgressPercent(snapshot) {
    const backendProgress = Number(snapshot?.progress_percent || 0);
    if (backendProgress > 0 || snapshot?.status === "completed") {
      return Math.max(0, Math.min(100, backendProgress || 100));
    }
    return fallbackProgressPercent(snapshot);
  }

  // 把后端阶段名统一折叠成前端可识别的正式阶段键。
  function normalizeStageKey(stageKey) {
    const mapping = {
      framework: "framework",
      framework_naturalize: "framework",
      appearance_strategy: "internal",
      appearance_pre_strategy: "internal",
      consistency: "internal",
      episode_plan_normalize: "internal",
      worldview: "worldview",
      worldview_naturalize: "worldview",
      character: "characters",
      characters: "characters",
      scene: "scenes",
      scenes: "scenes",
      appearance: "internal",
      appearance_alias_generation: "internal",
      appearance_alias_writing: "internal",
      appearance_alias_review: "internal",
      appearance_alias_rewrite: "internal",
      appearance_alias_unstructured: "internal",
      framework_scene_dictionary: "framework_to_script",
      framework_appearancemapping: "framework_to_script",
      framework_appearance_mapping: "framework_to_script",
      framework_enriched_episode_plan: "framework_to_script",
      framework_causal_conflict: "framework_to_script",
      framework_causal_conflict_write: "framework_to_script",
      framework_causal_conflict_review: "framework_to_script",
      framework_causal_conflict_rewrite: "framework_to_script",
      framework_causal_conflict_memory: "framework_to_script",
      framework_script: "framework_to_script",
      framework_script_write: "framework_to_script",
      framework_script_review: "framework_to_script",
      framework_script_rewrite: "framework_to_script",
      framework_script_memory: "framework_to_script",
      hook: "internal",
      hooks: "internal",
      hooks_writing: "internal",
      hook_write: "internal",
      hooks_review: "internal",
      hook_review: "internal",
      hooks_rewrite: "internal",
      hook_revise: "internal",
      hook_memory: "internal",
      dialogue: "internal",
      dialogues: "internal",
      dialogues_writing: "internal",
      dialogue_write: "internal",
      dialogues_review: "internal",
      dialogue_review: "internal",
      dialogues_rewrite: "internal",
      dialogue_revise: "internal",
      dialogue_memory: "internal",
      script: "internal",
      script_writing: "internal",
      script_write: "internal",
      script_review: "internal",
      script_rewrite: "internal",
      script_revise: "internal",
      script_memory: "internal",
      memory: "internal",
      final: "final",
      finalize: "final",
      finished: "final"
    };
    return mapping[String(stageKey || "").trim().toLowerCase()] || "";
  }

  function formatDisplayValue(value) {
    if (value === null || value === undefined || value === "") return "";
    if (typeof value === "string") {
      const text = value.trim();
      if (window.fieldLabelsCn && typeof window.fieldLabelsCn.readableText === "function" && /^[\[{]/.test(text)) {
        try {
          const parsed = JSON.parse(text);
          if (parsed && typeof parsed === "object") return window.fieldLabelsCn.readableText(parsed);
        } catch (_) {}
      }
      return text;
    }
    if (Array.isArray(value) || typeof value === "object") {
      if (window.fieldLabelsCn && typeof window.fieldLabelsCn.readableText === "function") {
        return window.fieldLabelsCn.readableText(value);
      }
      try {
        return JSON.stringify(value, null, 2).trim();
      } catch (_) {
        return String(value).trim();
      }
    }
    return String(value).trim();
  }

  function isMeaningfulStageOutput(value) {
    const text = formatDisplayValue(value);
    if (!text) return false;
    if (text === "{}" || text === "[]" || text === "[object Object]") return false;
    if (
      text === "剧本框架自然语言说明暂未生成。"
      || text === "世界观自然语言说明暂未生成。"
      || text === "人物设定自然语言说明暂未生成。"
      || text === "核心场景自然语言说明暂未生成。"
    ) {
      return false;
    }
    return true;
  }

  function formatToolOutput(value) {
    if (value === null || value === undefined || value === "") {
      return "工具没有返回可展示结果。";
    }
    if (typeof value === "string") {
      const text = value.trim();
      if (!text) return "工具没有返回可展示结果。";
      try {
        const parsed = JSON.parse(text);
        if (parsed && typeof parsed === "object") {
          return JSON.stringify(parsed, null, 2);
        }
      } catch (_) {}
      return text;
    }
    return formatDisplayValue(value) || "工具没有返回可展示结果。";
  }

  function partialScriptOutput(snapshot) {
    const artifacts = snapshot?.artifacts || {};
    const finalOutput = formatDisplayValue(artifacts.final_output_text || artifacts.final_script);
    if (finalOutput) return finalOutput;
    const partialScript = formatDisplayValue(artifacts.partial_script);
    if (partialScript) return partialScript;
    const batches = Array.isArray(artifacts.script_batches_display) ? artifacts.script_batches_display : [];
    if (!batches.length) return "";
    return batches.map((batch) => {
      const range = String(
        batch?.range
        || (
          batch?.start_episode && batch?.end_episode
            ? `${batch.start_episode}-${batch.end_episode}`
            : ""
        )
      ).trim();
      const content = formatDisplayValue(batch?.content);
      if (!content) return "";
      return range ? `第 ${range} 集\n${content}` : content;
    }).filter(Boolean).join("\n\n");
  }

  // 把框架阶段的多个正式产物拼成一个完整回复，方便在聊天流里整体展示。
  function frameworkStageOutput(snapshot) {
    const artifacts = snapshot?.artifacts || {};
    const natural = formatDisplayValue(artifacts.framework_natural_language);
    return isMeaningfulStageOutput(natural) ? natural : "";
  }

  function worldviewStageOutput(snapshot) {
    const artifacts = snapshot?.artifacts || {};
    const natural = formatDisplayValue(artifacts.worldview_natural_language);
    return isMeaningfulStageOutput(natural) ? natural : "";
  }

  // 只把平台真正对外公开的正式阶段产物整理成聊天消息。
  function visibleStageMessages(snapshot) {
    if (!snapshot) return [];
    const artifacts = snapshot?.artifacts || {};
    const currentDisplayKey = normalizeStageKey(snapshot.display_stage_key);
    const currentNatural = String(snapshot.display_stage_output_natural || "").trim();
    const messages = isFrameworkToScriptSnapshot(snapshot) ? [] : [
      {
        key: "framework",
        title: "剧本框架",
        output: frameworkStageOutput(snapshot)
      },
      {
        key: "worldview",
        title: "世界观",
        output: worldviewStageOutput(snapshot)
      },
      {
        key: "final",
        title: formatDisplayValue(artifacts.final_output_text || artifacts.final_script) ? "剧本正文" : "已生成正文",
        output: partialScriptOutput(snapshot)
      }
    ].filter((item) => isMeaningfulStageOutput(item.output));

    if (isFrameworkToScriptSnapshot(snapshot)) {
      const displayPayload = stageDisplayPayload(snapshot);
      const displayOutput = formatDisplayValue(displayPayload.output);
      const displayKey = String(snapshot.display_stage_key || snapshot.current_stage || "framework_to_script").trim();
      const normalizedDisplayKey = normalizeStageKey(displayKey);
      const isFinal = normalizeStageKey(snapshot.current_stage) === "final" || snapshot.status === "completed";
      if (isMeaningfulStageOutput(displayOutput)) {
        messages.push({
          key: isFinal ? "framework_to_script_final" : (normalizedDisplayKey || "framework_to_script"),
          title: isFinal ? "基于框架生成的剧本正文" : (displayPayload.title || displayStageLabel(snapshot)),
          output: displayOutput,
          natural: displayPayload.natural || "",
        });
      }
    }

    return messages.map((item) => ({
      ...item,
      natural: item.natural || (currentDisplayKey === item.key ? currentNatural : "")
    }));
  }

  // 内部阶段统一折叠成“思考分析”，避免把中间工作流细节直接暴露给用户。
  function thinkingStateFrom(snapshot) {
    if (!snapshot) return null;
    const normalizedCurrentStage = normalizeStageKey(snapshot.current_stage);
    const isRunning = RUNNING_STATUSES.has(snapshot.status) || snapshot.status === "pausing";
    if (!isRunning && !["internal", "framework_to_script"].includes(normalizedCurrentStage)) return null;
    const runtimeMessage = String(statusNoteFrom(snapshot) || "").trim();
    return {
      stageLabel: displayStageLabel(snapshot),
      stateLabel: creationStatusLabel(snapshot),
      content: runtimeMessage,
      note: isFrameworkToScriptSnapshot(snapshot) ? "来源：三幕十五节拍框架策划包" : "",
    };
  }

  function userPromptSummary(snapshot) {
    const inputPayload = snapshot?.input_payload || {};
    return {
      expectation: String(inputPayload.user_expectation || "").trim(),
      characterCount: Number(inputPayload.character_count || 0),
      totalEpisodes: Number(inputPayload.total_episodes || 0),
      frameworkToScript: isFrameworkToScriptSnapshot(snapshot),
      sourceFrameworkProjectId: String(inputPayload.source_framework_project_id || "").trim()
    };
  }

  function userPromptCopyText(snapshot) {
    return userPromptSummary(snapshot).expectation || "";
  }

  function stageMessageCopyText(snapshot, stageKey) {
    const message = visibleStageMessages(snapshot).find((item) => item.key === stageKey);
    if (!message) return "";
    const parts = [compactMessageText(message.output)];
    const natural = compactMessageText(message.natural);
    if (natural && natural !== parts[0]) {
      parts.push(natural);
    }
    return parts.filter(Boolean).join("\n\n");
  }

  function thinkingMessageCopyText(snapshot) {
    const thinkingState = thinkingStateFrom(snapshot);
    if (!thinkingState) return "";
    const parts = [compactMessageText(thinkingState.content)];
    const note = compactMessageText(thinkingState.note);
    if (note && note !== parts[0]) {
      parts.push(note);
    }
    return parts.filter(Boolean).join("\n\n");
  }

  function renderCopyButton(kind, key) {
    const attributes = [`data-chat-action="copy-message"`];
    if (kind) attributes.push(`data-copy-kind="${escapeHtml(kind)}"`);
    if (key) attributes.push(`data-copy-key="${escapeHtml(key)}"`);
    return `<button class="chat-copy-btn" type="button" ${attributes.join(" ")}>复制</button>`;
  }

  function renderUserPromptBubble(snapshot) {
    const prompt = userPromptSummary(snapshot);
    const expectation = prompt.expectation || "还没有填写创作需求。";
    const lineCount = inputLineCount(expectation);
    const toggleKey = promptToggleKey(snapshot);
    const collapsed = lineCount > MAX_EXPECTATION_LINES && !state.expandedUserPrompts[toggleKey];
    const chips = [
      prompt.frameworkToScript ? "来源：三幕十五节拍框架策划包" : "",
      prompt.sourceFrameworkProjectId ? `框架资产：${prompt.sourceFrameworkProjectId}` : "",
      prompt.characterCount > 0 ? `角色数量 ${prompt.characterCount}` : "",
      prompt.totalEpisodes > 0 ? `总集数 ${prompt.totalEpisodes}` : ""
    ].filter(Boolean);
    return `
      <article class="chat-message user">
        <div class="chat-bubble-row">
          <div class="chat-avatar">我</div>
          <div class="chat-bubble">
            <div class="chat-bubble-head">
              <span class="chat-bubble-title">创作指令</span>
            </div>
            <pre class="chat-bubble-content${collapsed ? " chat-bubble-content-collapsed" : ""}">${escapeHtml(expectation)}</pre>
            ${lineCount > MAX_EXPECTATION_LINES ? `
              <button
                class="chat-bubble-toggle"
                type="button"
                data-chat-action="toggle-user-prompt"
                data-prompt-key="${escapeHtml(toggleKey)}"
              >${collapsed ? `展开全文（${lineCount}行）` : "收起"}</button>
            ` : ""}
            <div class="chat-bubble-foot">
              <div class="chat-user-meta">${chips.map((item) => `<span class="chat-chip">${escapeHtml(item)}</span>`).join("")}</div>
              <div class="chat-bubble-foot-actions">
                ${renderCopyButton("user_prompt", "current")}
              </div>
            </div>
          </div>
        </div>
      </article>
    `;
  }

  function renderAssistantStageBubble(message) {
    return `
      <article class="chat-message assistant">
        <div class="chat-bubble-row">
          <div class="chat-avatar">AI</div>
          <div class="chat-bubble">
            <div class="chat-bubble-head">
              <span class="chat-bubble-title">${escapeHtml(message.title)}</span>
            </div>
            <pre class="chat-bubble-content">${escapeHtml(message.output)}</pre>
            ${message.natural ? `
              <div class="chat-bubble-preview">
                <span class="chat-bubble-preview-label">阶段说明</span>
                <p class="chat-bubble-preview-text">${escapeHtml(message.natural)}</p>
              </div>
            ` : ""}
            <div class="chat-bubble-foot">
              <div class="chat-bubble-foot-meta">
                <span class="chat-bubble-meta">阶段产出</span>
              </div>
              <div class="chat-bubble-foot-actions">
                ${renderCopyButton("stage_output", message.key)}
              </div>
            </div>
          </div>
        </div>
      </article>
    `;
  }

  function renderThinkingBubble(thinkingState) {
    const stageLabel = String(thinkingState.stageLabel || "处理中").trim();
    const stateLabel = String(thinkingState.stateLabel || "创作中").trim();
    const content = compactMessageText(thinkingState.content) || (
      stateLabel === "创作中"
        ? stageLabel
        : stateLabel
    );
    return `
      <article class="chat-message system">
        <div class="chat-bubble-row">
          <div class="chat-avatar">AI</div>
          <div class="chat-bubble">
            <div class="chat-bubble-head">
              <span class="chat-bubble-title">${escapeHtml(stateLabel)}</span>
            </div>
            <div class="chat-bubble-content"><span>${escapeHtml(content)}</span></div>
            ${thinkingState.note ? `
              <div class="chat-bubble-preview">
                <span class="chat-bubble-preview-label">状态说明</span>
                <p class="chat-bubble-preview-text">${escapeHtml(thinkingState.note)}</p>
              </div>
            ` : ""}
            <div class="chat-bubble-foot">
              <div class="chat-bubble-foot-meta">
                <span class="chat-bubble-meta">${escapeHtml(stageLabel)}</span>
              </div>
              <div class="chat-bubble-foot-actions">
                ${renderCopyButton("thinking_state", "current")}
              </div>
            </div>
          </div>
        </div>
      </article>
    `;
  }

  function transcriptSignature(snapshot) {
    if (!snapshot) return "__empty__";
    return JSON.stringify({
      projectId: snapshot.project_id || null,
      taskId: snapshot.task_id || null,
      status: snapshot.status || "",
      currentStage: snapshot.current_stage || "",
      currentBatch: snapshot.current_batch || "",
      currentStageLabel: snapshot.current_stage_label || "",
      runtimeMessage: String(snapshot.message || "").trim(),
      displayStageKey: snapshot.display_stage_key || "",
      displayStageOutputNatural: String(snapshot.display_stage_output_natural || "").trim(),
      displayStageTitle: snapshot.display_stage_title || "",
      finalOutputText: formatDisplayValue(snapshot?.artifacts?.final_output_text || snapshot?.artifacts?.final_script),
      partialScript: formatDisplayValue(snapshot?.artifacts?.partial_script),
      scriptBatchesDisplay: snapshot?.artifacts?.script_batches_display || [],
      visibleMessages: visibleStageMessages(snapshot),
      thinkingState: thinkingStateFrom(snapshot),
      prompt: userPromptSummary(snapshot),
    });
  }

  function scrollTranscriptToLatest() {
    if (!els.chatTranscript) return;
    const target = els.chatTranscript.querySelector(".chat-message:last-of-type")
      || els.chatTranscript.querySelector(".chat-empty-state:last-of-type");
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ block: "end" });
      return;
    }
    els.chatTranscript.scrollTop = els.chatTranscript.scrollHeight;
  }

  // 把当前项目压成对话流，只展示用户需要看的正式回复与一个统一的思考状态。
  function renderChatTranscript(snapshot) {
    if (!els.chatTranscript) return;
    const previousScrollTop = els.chatTranscript.scrollTop;
    const nextSignature = transcriptSignature(snapshot);
    if (!snapshot) {
      const suggestions = Object.values(toolDefinitions()).slice(0, 4).map((tool) => `
        <button class="chat-suggestion-btn" type="button" data-suggestion-tool="${escapeHtml(tool.key)}">
          ${escapeHtml(tool.label)}
        </button>
      `).join("");
      els.chatTranscript.innerHTML = `
        <section class="chat-empty-state">
          <strong>剧本创作工作台</strong>
          <p>直接输入你的创作需求，平台会把剧本框架和剧本正文按对话流展示，中间过程统一显示创作状态。</p>
          <div class="chat-empty-tools">${suggestions}</div>
        </section>
      `;
      state.lastTranscriptSignature = nextSignature;
      els.chatTranscript.scrollTop = 0;
      return;
    }

    const messages = [renderUserPromptBubble(snapshot)];
    const stageMessages = visibleStageMessages(snapshot);
    stageMessages.forEach((message) => {
      messages.push(renderAssistantStageBubble(message));
    });

    const thinkingState = thinkingStateFrom(snapshot);
    if (thinkingState) {
      messages.push(renderThinkingBubble(thinkingState));
    }

    els.chatTranscript.innerHTML = messages.join("");
    state.lastTranscriptSignature = nextSignature;
    els.chatTranscript.scrollTop = previousScrollTop;
  }

  // 只渲染后端允许回退到的阶段，不展示还没执行过的未来步骤。
  function renderRollbackOptions(options, selectedValue = "") {
    if (!els.rollbackStageSelect) return;
    const normalized = Array.isArray(options) ? options : [];
    els.rollbackStageSelect.innerHTML = [
      `<option value="">选择回退步骤</option>`,
      ...normalized.map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}</option>`)
    ].join("");
    if (selectedValue && normalized.some((item) => item.key === selectedValue)) {
      els.rollbackStageSelect.value = selectedValue;
    }
  }

  function rollbackRangeSelectPlaceholder(stageKey) {
    if (stageKey === "hooks") return "选择开头冲突钩子开始重写的集数范围";
    if (stageKey === "dialogues") return "选择角色对话开始重写的集数范围";
    if (stageKey === "script") return "选择剧本正文开始重写的集数范围";
    return "选择开始重写的集数范围";
  }

  function rollbackStageRangeOptions(snapshot, stageKey) {
    const optionsByStage = snapshot?.rollback_stage_start_options;
    if (optionsByStage && typeof optionsByStage === "object") {
      return Array.isArray(optionsByStage[stageKey]) ? optionsByStage[stageKey] : [];
    }
    if (stageKey === "script") {
      return Array.isArray(snapshot?.rollback_script_start_options) ? snapshot.rollback_script_start_options : [];
    }
    return [];
  }

  function rollbackStageDependencies(snapshot, stageKey) {
    const dependencies = snapshot?.rollback_stage_dependencies;
    if (dependencies && typeof dependencies === "object" && Array.isArray(dependencies[stageKey])) {
      return dependencies[stageKey];
    }
    if (stageKey === "hooks") return ["hooks", "dialogues", "script"];
    if (stageKey === "dialogues") return ["dialogues", "script"];
    if (stageKey === "script") return ["script"];
    return [stageKey].filter(Boolean);
  }

  function rollbackStageLabelMap(snapshot) {
    const entries = Array.isArray(snapshot?.rollback_stage_options) ? snapshot.rollback_stage_options : [];
    return entries.reduce((acc, item) => {
      if (item?.key) acc[item.key] = item.label || item.key;
      return acc;
    }, {});
  }

  // 当回退到 hooks/dialogues/script 阶段时，让用户按集数范围选择从哪一批开始重写。
  function renderRollbackScriptStartOptions(options, selectedValue = "") {
    if (!els.rollbackScriptStartSelect) return;
    const normalized = Array.isArray(options) ? options : [];
    const selectedStage = els.rollbackStageSelect?.value || "";
    const show = normalized.length > 0 && ["hooks", "dialogues", "script"].includes(selectedStage);
    els.rollbackScriptStartSelect.innerHTML = [
      `<option value="">${escapeHtml(rollbackRangeSelectPlaceholder(selectedStage))}</option>`,
      ...normalized.map((item) => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`)
    ].join("");
    if (selectedValue && normalized.some((item) => String(item.value) === String(selectedValue))) {
      els.rollbackScriptStartSelect.value = String(selectedValue);
    }
    els.rollbackScriptStartSelect.classList.toggle("hidden", !show);
    els.rollbackScriptStartSelect.disabled = !show || !Boolean(state.latestSnapshot?.can_stage_rollback);
  }

  // 承接后端项目快照，把运行状态、阶段输出和可操作按钮同步到页面。
  function renderSnapshot(snapshot) {
    const previousProjectId = state.projectId;
    const previousTaskId = state.taskId;
    state.latestSnapshot = snapshot || null;
    if (!snapshot) {
      state.projectId = null;
      state.taskId = null;
      state.status = "idle";
      els.statusText.textContent = isAuthenticated() ? "待开始" : "游客浏览";
      els.messageText.textContent = "";
      els.messageText.classList.add("hidden");
      els.stageText.textContent = "待开始";
      els.progressFill.style.width = "0%";
      els.progressText.textContent = "0%";
      els.projectText.textContent = "当前剧本：未选中";
      els.projectText.title = "当前剧本：未选中";
      els.taskText.textContent = "任务：未选中";
      if (els.outputTitle) els.outputTitle.textContent = "当前阶段输出";
      if (els.outputNaturalBox) {
        els.outputNaturalBox.textContent = "当前还没有阶段成品。";
      }
      els.finalOutputBox.textContent = "暂无内容";
      syncScriptFormatModeUi(null);
      renderChatTranscript(null);
      syncElapsedTimer(null);
      if (els.cacheNoticeText) {
        els.cacheNoticeText.textContent = "系统会保留必要缓存，方便暂停、继续、失败恢复和阶段回退。";
      }
      renderRollbackOptions([]);
      renderRollbackScriptStartOptions([]);
      renderProjectList(state.projects);
      syncButtons();
      return;
    }

    state.projectId = snapshot.project_id || null;
    state.taskId = snapshot.task_id || null;
    state.status = snapshot.status || "idle";

    if (window.scriptMakerConfig?.enableRuntimeDebugPanel === true && state.taskId && String(state.taskId) !== state.lastDebugTaskId) {
      state.lastConsoleLogIndex = 0;
      state.lastDebugError = "";
      fetchRuntimeDebug().catch((error) => {
        if (error?.message && error.message !== state.lastDebugError) {
          console.error("[runtime-debug-fetch-error]", error);
          state.lastDebugError = error.message;
        }
      });
    }

    const progress = displayProgressPercent(snapshot);
    const displayPayload = stageDisplayPayload(snapshot);
    const finalOutput = displayPayload.output || (RUNNING_STATUSES.has(snapshot.status) ? "" : "暂无内容");
    const projectTitle = runtimeProjectDisplayTitle(snapshot);
    const statusMessage = statusNoteFrom(snapshot);

    els.statusText.textContent = statusLabel(snapshot.status);
    els.messageText.textContent = statusMessage;
    els.messageText.classList.toggle("hidden", !statusMessage);
    els.stageText.textContent = displayStageLabel(snapshot);
    els.progressFill.style.width = `${progress}%`;
    els.progressText.textContent = `${progress}%`;
    els.projectText.textContent = `当前剧本：${projectTitle}`;
    els.projectText.title = `当前剧本：${projectTitle}`;
    els.taskText.textContent = `任务：${snapshot.task_id || "未创建"}`;
    syncScriptFormatModeUi(snapshot);
    if (els.outputTitle) {
      els.outputTitle.textContent = displayPayload.title || "当前阶段输出";
    }
    if (els.outputNaturalBox) {
      els.outputNaturalBox.textContent = displayPayload.natural || "";
    }
    els.finalOutputBox.textContent = finalOutput;
    renderChatTranscript(snapshot);
    syncElapsedTimer(snapshot);
    if (els.cacheNoticeText) {
      els.cacheNoticeText.textContent = snapshot.cache_notice || "系统会保留必要缓存，方便暂停、继续、失败恢复和阶段回退。";
    }
    const snapshotChanged = (
      Number(previousProjectId || 0) !== Number(state.projectId || 0)
      || String(previousTaskId || "") !== String(state.taskId || "")
    );
    const rollbackStageOptions = snapshot.rollback_stage_options || [];
    const defaultRollbackStage = snapshot.rollback_stage_default || "";
    const defaultRollbackStart = snapshot.rollback_start_episode_default
      ? String(snapshot.rollback_start_episode_default)
      : "";
    const currentRollbackStage = snapshotChanged ? "" : (els.rollbackStageSelect?.value || "");
    const desiredRollbackStage = (
      currentRollbackStage
      && rollbackStageOptions.some((item) => item.key === currentRollbackStage)
    )
      ? currentRollbackStage
      : defaultRollbackStage;
    renderRollbackOptions(rollbackStageOptions, desiredRollbackStage);
    const rollbackScriptStartOptions = rollbackStageRangeOptions(snapshot, desiredRollbackStage);
    const currentRollbackStart = snapshotChanged ? "" : (els.rollbackScriptStartSelect?.value || "");
    const desiredRollbackStart = (
      ["hooks", "dialogues", "script"].includes(desiredRollbackStage)
      && currentRollbackStart
      && rollbackScriptStartOptions.some((item) => String(item.value) === String(currentRollbackStart))
    )
      ? currentRollbackStart
      : ["hooks", "dialogues", "script"].includes(desiredRollbackStage)
        ? defaultRollbackStart
        : "";
    renderRollbackScriptStartOptions(rollbackScriptStartOptions, desiredRollbackStart);
    if (!["hooks", "dialogues", "script"].includes(desiredRollbackStage) && els.rollbackScriptStartSelect) {
      els.rollbackScriptStartSelect.value = "";
    }
    persistSelectedProjectId(snapshot.project_id);
    renderProjectList(state.projects);
    syncButtons();
  }

  // 根据当前项目状态统一收口按钮权限，避免用户点到不该点的操作。
  function syncButtons() {
    const hasProject = Boolean(state.projectId);
    const hasFinal = Boolean(state.latestSnapshot?.has_final || finalOutputFrom(state.latestSnapshot));
    const hasConfiguredModel = state.availableModels.some((item) => item.configured !== false);
    const canConfirmCompletion = Boolean(state.latestSnapshot?.can_confirm_completion);
    const canStageRollback = Boolean(state.latestSnapshot?.can_stage_rollback);
    const selectedRollbackStage = els.rollbackStageSelect?.value || "";
    const requiresScriptStart = ["hooks", "dialogues", "script"].includes(selectedRollbackStage);
    const hasRollbackSelection = Boolean(
      selectedRollbackStage && (!requiresScriptStart || (els.rollbackScriptStartSelect?.value || ""))
    );
    const formValidation = validateGenerationForm();
    const toolValidation = validateToolPayload();
    const assetValidation = validateAssetEditor();

    els.startBtn.disabled = isActionLoading("start");
    els.pauseBtn.disabled = isActionLoading("pause") || !(state.taskId && ["running", "pending"].includes(state.status));
    els.resumeBtn.disabled = isActionLoading("resume") || !(state.taskId && RESUMABLE_STATUSES.has(state.status));
    els.terminateBtn.disabled = isActionLoading("terminate") || !(state.taskId && TERMINATABLE_STATUSES.has(state.status));
    els.clearBtn.disabled = !isAuthenticated() || !canClearCurrentInput();
    els.saveBtn.disabled = isActionLoading("download") || !isAuthenticated() || !hasProject || !hasFinal;
    if (els.confirmCompletionBtn) {
      els.confirmCompletionBtn.disabled = isActionLoading("confirmCompletion") || !isAuthenticated() || !canConfirmCompletion;
    }
    if (els.rollbackStageSelect) {
      els.rollbackStageSelect.disabled = isActionLoading("rollback") || !isAuthenticated() || !canStageRollback;
    }
    if (els.rollbackScriptStartSelect) {
      const showScriptStart = canStageRollback && ["hooks", "dialogues", "script"].includes(selectedRollbackStage);
      els.rollbackScriptStartSelect.classList.toggle("hidden", !showScriptStart);
      els.rollbackScriptStartSelect.disabled = isActionLoading("rollback") || !showScriptStart;
    }
    if (els.rollbackRewriteBtn) {
      els.rollbackRewriteBtn.disabled = isActionLoading("rollback") || !isAuthenticated() || !canStageRollback || !hasRollbackSelection;
    }
    if (els.completionPanel) {
      const shouldShowCompletionPanel = Boolean(
        hasProject && (hasFinal || canConfirmCompletion || canStageRollback)
      );
      els.completionPanel.classList.toggle("hidden", !shouldShowCompletionPanel);
    }
    if (els.runToolBtn) {
      els.runToolBtn.disabled = isActionLoading("runTool") || !toolValidation.valid;
    }
    if (els.downloadToolBtn) {
      els.downloadToolBtn.disabled = isActionLoading("runTool") || !downloadToolButtonEnabled();
    }
    if (els.saveAssetEditBtn && state.editingProjectId) {
      const needsAppliedChange = state.assetEditMode === "edit" && !state.assetDirty;
      els.saveAssetEditBtn.disabled = isActionLoading("saveAsset") || !assetValidation.valid || needsAppliedChange;
    }
    if (!hasProject && !state.taskId && !hasConfiguredModel && els.formHint) {
      els.formHint.textContent = "当前没有可用模型。";
    } else if (!formValidation.valid && !hasProject && !RUNNING_STATUSES.has(state.status) && els.formHint) {
      els.formHint.textContent = formValidation.message || "当前流程：写剧本正文。请先填写故事期待、角色数量和总集数。";
    }
  }

  function hasConfiguredModel() {
    return state.availableModels.some((item) => item.configured !== false);
  }

  function selectedModelId() {
    const currentValue = String(els.modelSelect?.value || "").trim();
    if (currentValue) {
      return currentValue;
    }
    const fallbackModel = state.availableModels.find((item) => item.configured !== false) || state.availableModels[0];
    const fallbackId = String(fallbackModel?.id || "").trim();
    if (fallbackId && els.modelSelect) {
      els.modelSelect.value = fallbackId;
    }
    return fallbackId;
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // 优先使用后端返回的辅助工具定义，拿不到时退回本地默认配置，保证主页面不会被工具区拖垮。
  function toolDefinitions() {
    return Object.keys(state.toolDefinitions || {}).length
      ? state.toolDefinitions
      : DEFAULT_TOOL_DEFINITIONS;
  }

  function toolConfig(toolKey) {
    const definitions = toolDefinitions();
    return definitions[toolKey] || definitions.hot_review || Object.values(definitions)[0];
  }

  function isActionLoading(actionKey) {
    return Boolean(state.loadingActions?.[actionKey]);
  }

  function setActionLoading(actionKey, button, loading, loadingText = "处理中...") {
    if (!button) return;
    if (loading) {
      if (!button.dataset.originalText) {
        button.dataset.originalText = button.textContent;
      }
      state.loadingActions[actionKey] = true;
      button.textContent = loadingText;
      button.disabled = true;
    } else {
      delete state.loadingActions[actionKey];
      button.textContent = button.dataset.originalText || button.textContent;
    }
    syncButtons();
  }

  async function withActionLoading(actionKey, button, loadingText, runner) {
    setActionLoading(actionKey, button, true, loadingText);
    try {
      return await runner();
    } finally {
      setActionLoading(actionKey, button, false, loadingText);
    }
  }

  function validateGenerationForm() {
    if (!isAuthenticated()) {
      return { valid: false, message: "登录后即可开始创作。" };
    }
    if (!hasConfiguredModel()) {
      return { valid: false, message: "当前没有可用模型，请先完成 .env 配置。" };
    }
    const expectation = String(els.expectationInput?.value || "").trim() || fallbackExpectationForRestart();
    const characterCount = Number(els.characterCountInput?.value || 0);
    const totalEpisodes = Number(els.episodeCountInput?.value || 0);
    if (!expectation) {
      return { valid: false, message: "请填写想要的剧本。" };
    }
    if (expectation.length > 4000) {
      return { valid: false, message: "创作需求请控制在 4000 字以内。" };
    }
    if (!Number.isFinite(characterCount) || characterCount <= 0) {
      return { valid: false, message: "角色数量必须大于 0。" };
    }
    if (!Number.isFinite(totalEpisodes) || totalEpisodes <= 0) {
      return { valid: false, message: "总集数必须大于 0。" };
    }
    if (!selectedModelId()) {
      return { valid: false, message: "请选择可用模型。" };
    }
    return { valid: true, message: "" };
  }

  function validateToolPayload() {
    const tool = toolConfig(state.activeTool);
    if (!tool?.configured) {
      return { valid: false, message: "当前工具还未配置 API Key。" };
    }
    const payload = collectToolPayload(tool.key);
    for (const field of tool.fields || []) {
      const rawValue = payload[field.name];
      const value = field.type === "number" ? Number(rawValue || 0) : String(rawValue || "").trim();
      if (field.required && (field.type === "number" ? !(Number.isFinite(value) && value > 0) : !value)) {
        return { valid: false, message: `请先填写 ${field.label}。` };
      }
    }
    return { valid: true, message: "" };
  }

  function validateAssetEditor() {
    if (!state.editingProjectId) {
      return { valid: false, message: "请选择要编辑的资产。" };
    }
    const visibility = String(els.editAssetPrivacy?.value || "").trim();
    if (!["private", "public"].includes(visibility)) {
      return { valid: false, message: "请选择有效的公开状态。" };
    }
    if (state.editingAssetLocked) {
      return { valid: true, message: "" };
    }
    const title = String(els.editAssetTitle?.value || "").trim();
    const summary = String(els.editAssetSummary?.value || "").trim();
    if (!title) {
      return { valid: false, message: "资产标题不能为空。" };
    }
    if (title.length > 120) {
      return { valid: false, message: "资产标题请控制在 120 字以内。" };
    }
    if (summary.length > 20000) {
      return { valid: false, message: "摘要内容请控制在 20000 字以内。" };
    }
    return { valid: true, message: "" };
  }

  function renderListSkeleton(cardClass, count = 4) {
    return Array.from({ length: count }, (_, index) => `
      <article class="${cardClass} skeleton-card" aria-hidden="true">
        <div class="skeleton-line skeleton-line-short"></div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line skeleton-line-short"></div>
      </article>
    `).join("");
  }

  function errorCard(message, retryLabel = "重试") {
    return `
      <div class="empty-card error-card">
        <strong>${escapeHtml(message)}</strong>
        <div class="empty-card-actions">
          <button class="btn btn-secondary" type="button" data-action="retry-list">${escapeHtml(retryLabel)}</button>
        </div>
      </div>
    `;
  }

  function paginateItems(items, page, pageSize = 6) {
    const safePage = Math.max(1, Number(page || 1));
    const safeSize = Math.max(1, Number(pageSize || 6));
    return {
      visibleItems: items.slice(0, safePage * safeSize),
      hasMore: items.length > safePage * safeSize
    };
  }

  function normalizeToolDefinition(tool) {
    const key = tool?.key || tool?.tool_id || "";
    if (!key) return null;
    if (key === "reskin") return null;
    const fallback = DEFAULT_TOOL_DEFINITIONS[key] || {};
    return {
      key,
      label: tool.label || tool.title || fallback.label || key,
      help: tool.help || fallback.help || "",
      configured: tool.configured !== false,
      source: tool.source || fallback.source || "fallback",
      runUrl: tool.run_url || fallback.runUrl || "",
      jsonFile: tool.json_file || tool.workflow_json_file || null,
      fields: Array.isArray(tool.fields) && tool.fields.length
        ? tool.fields.map((field) => ({
          name: field.name,
          label: field.label || field.name,
          type: field.type || "input",
          placeholder: field.placeholder || "",
          required: Boolean(field.required),
          defaultValue: field.default_value ?? field.defaultValue ?? ""
        }))
        : (fallback.fields || []).map((field) => ({ ...field }))
    };
  }

  function currentToolRunUrl(toolKey = state.activeTool) {
    const tool = toolConfig(toolKey);
    return tool?.runUrl || `/api/tools/${toolKey}/run`;
  }

  function projectTitleCandidate() {
    const title = runtimeProjectDisplayTitle(state.latestSnapshot);
    if (!title || ["未选中", "未命名剧本"].includes(title) || /^项目\s+\d+$/.test(title)) {
      return "";
    }
    return title;
  }

  function currentExpectationCandidate() {
    return String(els.expectationInput?.value || "").trim()
      || String(state.latestSnapshot?.input_payload?.user_expectation || "").trim();
  }

  function currentCharacterCountCandidate() {
    const fromInput = Number(els.characterCountInput?.value || 0);
    if (Number.isFinite(fromInput) && fromInput > 0) return fromInput;
    const fromSnapshot = Number(state.latestSnapshot?.input_payload?.character_count || 0);
    return Number.isFinite(fromSnapshot) && fromSnapshot > 0 ? fromSnapshot : "";
  }

  function currentEpisodeCountCandidate() {
    const fromInput = Number(els.episodeCountInput?.value || 0);
    if (Number.isFinite(fromInput) && fromInput > 0) return fromInput;
    const fromSnapshot = Number(state.latestSnapshot?.input_payload?.total_episodes || 0);
    return Number.isFinite(fromSnapshot) && fromSnapshot > 0 ? fromSnapshot : "";
  }

  function buildNewFrameworkStoryPrefill() {
    const parts = [];
    const title = projectTitleCandidate();
    const expectation = currentExpectationCandidate();
    if (title) {
      parts.push(`剧本标题：${title}`);
    }
    if (expectation) {
      parts.push(expectation);
    }
    return parts.join("\n").trim();
  }

  function toolFieldInitialValue(toolKey, field) {
    if (toolKey === "new_framework") {
      if (field.name === "story") return buildNewFrameworkStoryPrefill();
      if (field.name === "character_count") return currentCharacterCountCandidate();
      if (field.name === "total_episodes") return currentEpisodeCountCandidate() || field.defaultValue || 60;
      if (field.name === "story_scale") return field.defaultValue || "连载爆款短剧";
      if (field.name === "genre_tone") return "";
      if (field.name === "target_audience") return "";
    }
    return field.defaultValue ?? "";
  }

  function normalizeToolFieldValue(field, value) {
    if (field.type === "number") {
      const parsed = Number(value);
      return Number.isFinite(parsed) && parsed > 0 ? String(parsed) : "";
    }
    return String(value ?? "").trim();
  }

  function ensureToolDraft(toolKey) {
    const tool = toolConfig(toolKey);
    const existing = state.toolDrafts[tool.key] || {};
    const nextDraft = {};
    for (const field of tool.fields || []) {
      const hasExistingValue = Object.prototype.hasOwnProperty.call(existing, field.name);
      nextDraft[field.name] = hasExistingValue
        ? normalizeToolFieldValue(field, existing[field.name])
        : normalizeToolFieldValue(field, toolFieldInitialValue(tool.key, field));
    }
    state.toolDrafts[tool.key] = nextDraft;
    return nextDraft;
  }

  function rememberCurrentToolDraft() {
    const tool = toolConfig(state.activeTool);
    const currentDraft = state.toolDrafts[tool.key] ? { ...state.toolDrafts[tool.key] } : {};
    const allowedFields = new Set((tool.fields || []).map((field) => String(field.name || "")));
    (els.toolForms || document).querySelectorAll("[data-tool-field]").forEach((field) => {
      const key = field.dataset.toolField;
      if (!allowedFields.has(key)) return;
      currentDraft[key] = field.type === "number" ? String(field.value || "").trim() : String(field.value || "");
    });
    state.toolDrafts[tool.key] = currentDraft;
  }

  function currentToolResult(toolKey = state.activeTool) {
    return normalizeScriptAuditEcgResult(state.toolResults[toolKey] || null);
  }

  function isToolAsset(assetLike) {
    return String(assetLike?.asset_kind || "").trim() === "tool_result";
  }

  /* HOT_REVIEW_ASSETS_V3_SAFE */
  function hotReviewJsonText(value) {
    try {
      return JSON.stringify(value || {});
    } catch (_) {
      return "";
    }
  }

  function hotReviewAssetKey(item) {
    const key = item?.project_id
      || item?.id
      || item?.asset_id
      || item?.assetId
      || item?.saved_asset_id
      || item?.savedAssetId
      || "";
    return String(key || "").trim();
  }

  function hotReviewResultObject(item) {
    const artifacts = item?.artifacts || {};
    return item?.result
      || item?.tool_result
      || artifacts.tool_result
      || artifacts.result
      || artifacts.output
      || {};
  }

  function hotReviewFirstText(item) {
    if (!item || typeof item !== "object") return String(item || "").trim();

    const artifacts = item.artifacts || {};
    const result = hotReviewResultObject(item);
    const candidates = [
      result.text,
      result.answer_text,
      result.answerText,
      result.content,
      result.output,
      item.text,
      item.answer_text,
      item.answerText,
      item.content,
      item.output,
      item.final_output_text,
      artifacts.text,
      artifacts.answer_text,
      artifacts.answerText,
      artifacts.content,
      artifacts.output,
      artifacts.final_output_text,
      artifacts.final_script
    ];

    return String(candidates.find((value) => String(value || "").trim()) || "").trim();
  }

  function hotReviewDeepText(item) {
    if (!item || typeof item !== "object") return String(item || "");
    const artifacts = item.artifacts || {};
    const result = hotReviewResultObject(item);

    return [
      item.tool_key,
      item.tool_id,
      item.tool_label,
      item.asset_type,
      item.asset_kind,
      item.category,
      item.type,
      item.result_type,
      item.resultType,
      item.title,
      item.name,
      item.summary,
      hotReviewFirstText(item),

      result.tool_key,
      result.tool_id,
      result.tool_label,
      result.asset_type,
      result.asset_kind,
      result.category,
      result.result_type,
      result.resultType,
      result.title,
      hotReviewFirstText(result),

      artifacts.asset_type,
      artifacts.asset_kind,
      artifacts.category,
      artifacts.result_type,
      artifacts.resultType,
      hotReviewFirstText(artifacts),

      hotReviewJsonText(item.audit),
      hotReviewJsonText(item.view),
      hotReviewJsonText(result.audit),
      hotReviewJsonText(result.view),
      hotReviewJsonText(artifacts.audit),
      hotReviewJsonText(artifacts.view),
      hotReviewJsonText(result),
      hotReviewJsonText(artifacts)
    ].filter(Boolean).join("\n");
  }

  function hotReviewLooksLikeAuditPayload(payload) {
    return looksLikeScriptAuditPayload(payload)
      || Boolean(
        payload
        && typeof payload === "object"
        && (
          String(payload.schema_version || "").includes("script_audit_ecg")
          || String(payload.result_type || payload.resultType || "").includes("script_audit_ecg")
          || Boolean(payload.audit && payload.view)
          || Boolean(payload.overall && (payload.dimension_scores || payload.ecg || payload.key_issues || payload.rewrite_plan))
        )
      );
  }

  function hotReviewParsedTextCandidates(text) {
    const parsed = parseScriptAuditJsonFromText(text);
    if (!parsed || typeof parsed !== "object") return [];
    return [
      parsed,
      parsed.audit,
      parsed.result,
      parsed.output,
      parsed.data
    ].filter(Boolean);
  }

  function hotReviewExtractAuditView(source) {
    if (!source || typeof source !== "object") {
      return { audit: null, view: null };
    }

    const artifacts = source.artifacts || {};
    const result = hotReviewResultObject(source);
    const saved = source.savedAsset || source.saved_asset || {};
    const savedArtifacts = saved.artifacts || {};
    const savedResult = hotReviewResultObject(saved);

    let view = source.view
      || result.view
      || artifacts.view
      || saved.view
      || savedResult.view
      || savedArtifacts.view
      || null;

    const textCandidates = [
      hotReviewFirstText(source),
      hotReviewFirstText(result),
      hotReviewFirstText(artifacts),
      hotReviewFirstText(saved),
      hotReviewFirstText(savedResult),
      source.text,
      source.answer_text,
      source.answerText,
      source.content,
      source.output,
      source.raw_text,
      source.final_output_text,
      result.text,
      result.answer_text,
      result.answerText,
      result.content,
      result.output,
      artifacts.text,
      artifacts.content,
      artifacts.output,
      artifacts.final_output_text
    ].filter(Boolean);

    const candidates = [
      source.audit,
      result.audit,
      artifacts.audit,
      saved.audit,
      savedResult.audit,
      savedArtifacts.audit,
      source,
      result,
      artifacts,
      saved,
      savedResult,
      ...textCandidates.flatMap((text) => hotReviewParsedTextCandidates(text))
    ].filter(Boolean);

    for (const candidate of candidates) {
      if (candidate?.audit && candidate?.view) {
        return { audit: candidate.audit, view: view || candidate.view };
      }
      if (hotReviewLooksLikeAuditPayload(candidate)) {
        return { audit: candidate.audit && candidate.view ? candidate.audit : candidate, view };
      }
    }

    return { audit: null, view };
  }

  function hotReviewAssetTitle(item) {
    const extracted = hotReviewExtractAuditView(item);
    const audit = extracted.audit || {};
    const view = extracted.view || {};
    const direct = audit?.meta?.script_title
      || view?.meta?.script_title
      || audit?.script_title
      || view?.script_title
      || "";

    if (String(direct || "").trim()) return String(direct).trim();

    const raw = hotReviewDeepText(item);
    const match = raw.match(/["']script_title["']\s*:\s*["']([^"']{1,120})["']/);
    if (match?.[1]) return match[1].trim();

    const fallback = projectDisplayTitle(item);
    return fallback && !["未选中", "未命名剧本"].includes(fallback) ? fallback : "未命名爆款文审核";
  }

  function hotReviewAssetScore(item) {
    const { audit } = hotReviewExtractAuditView(item);
    return audit?.overall?.total_score ?? audit?.overall?.score ?? "";
  }

  function hotReviewUniqueAssets(items) {
    const map = new Map();
    for (const item of Array.isArray(items) ? items : []) {
      if (!isHotReviewAsset(item)) continue;
      const key = hotReviewAssetKey(item) || hotReviewAssetTitle(item);
      if (!key) continue;
      map.set(key, { ...(map.get(key) || {}), ...item });
    }

    return [...map.values()].sort((a, b) =>
      String(b.updated_at || b.created_at || b.createdAt || "")
        .localeCompare(String(a.updated_at || a.created_at || a.createdAt || ""))
    );
  }

  function hotReviewFindAsset(key) {
    const target = String(key || "").trim();
    if (!target) return null;

    const pool = [
      ...(Array.isArray(state.assets) ? state.assets : []),
      ...(Array.isArray(state.projects) ? state.projects : []),
      state.latestSnapshot
    ].filter(Boolean);

    return pool.find((item) =>
      String(hotReviewAssetKey(item)) === target
      || String(item?.project_id || "") === target
      || String(item?.id || "") === target
      || String(item?.asset_id || item?.assetId || "") === target
      || String(hotReviewAssetTitle(item)) === target
    ) || null;
  }

  function hotReviewInputText(item) {
    const input = item?.input_payload || item?.request_payload || item?.tool_request || {};
    return String(input.review_text || input.text || input.input || "").trim();
  }

  /* HOT_REVIEW_ASSET_V4 */
  function hotReviewJsonTextV4(value) {
    try {
      return JSON.stringify(value || {});
    } catch (_) {
      return "";
    }
  }

  function hotReviewAssetKeyV4(item) {
    return String(
      item?.project_id
      || item?.id
      || item?.asset_id
      || item?.assetId
      || item?.saved_asset_id
      || item?.savedAssetId
      || ""
    ).trim();
  }

  function hotReviewResultObjectV4(item) {
    const artifacts = item?.artifacts || {};
    return item?.result
      || item?.tool_result
      || artifacts.tool_result
      || artifacts.result
      || artifacts.output
      || {};
  }

  function hotReviewFirstTextV4(item) {
    if (!item || typeof item !== "object") return String(item || "").trim();

    const artifacts = item.artifacts || {};
    const result = hotReviewResultObjectV4(item);
    const candidates = [
      result.text,
      result.answer_text,
      result.answerText,
      result.content,
      result.output,
      item.text,
      item.answer_text,
      item.answerText,
      item.content,
      item.output,
      item.final_output_text,
      item.tool_text,
      item.tool_output,
      item.raw_text,
      artifacts.text,
      artifacts.answer_text,
      artifacts.answerText,
      artifacts.content,
      artifacts.output,
      artifacts.final_output_text,
      artifacts.final_script,
      artifacts.raw_text
    ];

    return String(candidates.find((value) => String(value || "").trim()) || "").trim();
  }

  function hotReviewDeepTextV4(item) {
    if (!item || typeof item !== "object") return String(item || "");
    const artifacts = item.artifacts || {};
    const result = hotReviewResultObjectV4(item);

    return [
      item.tool_key,
      item.tool_id,
      item.tool_label,
      item.tool_filename,
      item.filename,
      item.asset_type,
      item.asset_kind,
      item.category,
      item.type,
      item.workflow_type,
      item.result_type,
      item.resultType,
      item.title,
      item.name,
      item.summary,
      hotReviewFirstTextV4(item),

      result.tool_key,
      result.tool_id,
      result.tool_label,
      result.tool_filename,
      result.filename,
      result.asset_type,
      result.asset_kind,
      result.category,
      result.type,
      result.result_type,
      result.resultType,
      result.title,
      result.name,
      result.summary,
      hotReviewFirstTextV4(result),

      artifacts.tool_key,
      artifacts.tool_id,
      artifacts.tool_label,
      artifacts.tool_filename,
      artifacts.filename,
      artifacts.asset_type,
      artifacts.asset_kind,
      artifacts.category,
      artifacts.type,
      artifacts.result_type,
      artifacts.resultType,
      hotReviewFirstTextV4(artifacts),

      hotReviewJsonTextV4(item.audit),
      hotReviewJsonTextV4(item.view),
      hotReviewJsonTextV4(result.audit),
      hotReviewJsonTextV4(result.view),
      hotReviewJsonTextV4(artifacts.audit),
      hotReviewJsonTextV4(artifacts.view),
      hotReviewJsonTextV4(result),
      hotReviewJsonTextV4(artifacts)
    ].filter(Boolean).join("\n");
  }

  function hotReviewLooksLikeAuditPayloadV4(payload) {
    return looksLikeScriptAuditPayload(payload)
      || Boolean(
        payload
        && typeof payload === "object"
        && (
          String(payload.schema_version || "").includes("script_audit_ecg")
          || String(payload.result_type || payload.resultType || "").includes("script_audit_ecg")
          || Boolean(payload.audit && payload.view)
          || Boolean(payload.overall && (payload.dimension_scores || payload.ecg || payload.key_issues || payload.rewrite_plan))
        )
      );
  }

  function hotReviewParsedTextCandidatesV4(text) {
    const parsed = parseScriptAuditJsonFromText(text);
    if (!parsed || typeof parsed !== "object") return [];
    return [
      parsed,
      parsed.audit,
      parsed.result,
      parsed.output,
      parsed.data
    ].filter(Boolean);
  }

  function hotReviewExtractAuditViewV4(source) {
    if (!source || typeof source !== "object") {
      return { audit: null, view: null };
    }

    const artifacts = source.artifacts || {};
    const result = hotReviewResultObjectV4(source);
    const saved = source.savedAsset || source.saved_asset || {};
    const savedArtifacts = saved.artifacts || {};
    const savedResult = hotReviewResultObjectV4(saved);

    let view = source.view
      || result.view
      || artifacts.view
      || saved.view
      || savedResult.view
      || savedArtifacts.view
      || null;

    const textCandidates = [
      hotReviewFirstTextV4(source),
      hotReviewFirstTextV4(result),
      hotReviewFirstTextV4(artifacts),
      hotReviewFirstTextV4(saved),
      hotReviewFirstTextV4(savedResult),
      source.text,
      source.answer_text,
      source.answerText,
      source.content,
      source.output,
      source.raw_text,
      source.final_output_text,
      result.text,
      result.answer_text,
      result.answerText,
      result.content,
      result.output,
      artifacts.text,
      artifacts.content,
      artifacts.output,
      artifacts.final_output_text
    ].filter(Boolean);

    const candidates = [
      source.audit,
      result.audit,
      artifacts.audit,
      saved.audit,
      savedResult.audit,
      savedArtifacts.audit,
      source,
      result,
      artifacts,
      saved,
      savedResult,
      ...textCandidates.flatMap((text) => hotReviewParsedTextCandidatesV4(text))
    ].filter(Boolean);

    for (const candidate of candidates) {
      if (candidate?.audit && candidate?.view) {
        return { audit: candidate.audit, view: view || candidate.view };
      }
      if (hotReviewLooksLikeAuditPayloadV4(candidate)) {
        return { audit: candidate.audit && candidate.view ? candidate.audit : candidate, view };
      }
    }

    return { audit: null, view };
  }

  function hotReviewAssetTitleV4(item) {
    const extracted = hotReviewExtractAuditViewV4(item);
    const audit = extracted.audit || {};
    const view = extracted.view || {};
    const direct = audit?.meta?.script_title
      || view?.meta?.script_title
      || audit?.script_title
      || view?.script_title
      || item?.script_title
      || item?.result?.script_title
      || item?.artifacts?.script_title
      || "";

    if (String(direct || "").trim()) return String(direct).trim();

    const raw = hotReviewDeepTextV4(item);
    const match = raw.match(/["']script_title["']\s*:\s*["']([^"']{1,120})["']/);
    if (match?.[1]) return match[1].trim();

    const fallback = projectDisplayTitle(item);
    return fallback && !["未选中", "未命名剧本", "爆款文审核", "辅助工具"].includes(fallback)
      ? fallback
      : "未命名爆款文审核";
  }

  function hotReviewAssetScoreV4(item) {
    const { audit } = hotReviewExtractAuditViewV4(item);
    return audit?.overall?.total_score ?? audit?.overall?.score ?? "";
  }

  function hotReviewUniqueAssetsV4(items) {
    const map = new Map();
    for (const item of Array.isArray(items) ? items : []) {
      if (!isHotReviewAsset(item)) continue;
      const key = hotReviewAssetKeyV4(item) || hotReviewAssetTitleV4(item);
      if (!key) continue;
      map.set(key, { ...(map.get(key) || {}), ...item });
    }

    return [...map.values()].sort((a, b) =>
      String(b.updated_at || b.created_at || b.createdAt || "")
        .localeCompare(String(a.updated_at || a.created_at || a.createdAt || ""))
    );
  }

  function hotReviewFindAssetV4(key) {
    const target = String(key || "").trim();
    if (!target) return null;

    const pool = [
      ...(Array.isArray(state.assets) ? state.assets : []),
      ...(Array.isArray(state.projects) ? state.projects : []),
      state.latestSnapshot
    ].filter(Boolean);

    return pool.find((item) =>
      String(hotReviewAssetKeyV4(item)) === target
      || String(item?.project_id || "") === target
      || String(item?.id || "") === target
      || String(item?.asset_id || item?.assetId || "") === target
      || String(hotReviewAssetTitleV4(item)) === target
    ) || null;
  }

  function hotReviewInputTextV4(item) {
    const input = item?.input_payload || item?.request_payload || item?.tool_request || {};
    return String(input.review_text || input.text || input.input || "").trim();
  }

  /* HOT_REVIEW_ASSET_OPEN_V5 */
  function hotReviewAssetKeyV5(item) {
    return String(item?.project_id || item?.id || item?.asset_id || item?.assetId || item?.saved_asset_id || "").trim();
  }

  function hotReviewResultObjectV5(item) {
    const artifacts = item?.artifacts || {};
    return item?.result || item?.tool_result || artifacts.tool_result || artifacts.result || artifacts.output || {};
  }

  function hotReviewFirstTextV5(item) {
    if (!item || typeof item !== "object") return String(item || "").trim();
    const artifacts = item.artifacts || {};
    const result = hotReviewResultObjectV5(item);
    const candidates = [
      result.raw_json,
      result.raw_model_json,
      result.answer_text,
      result.answerText,
      result.text,
      result.content,
      result.output,
      item.raw_json,
      item.raw_model_json,
      item.answer_text,
      item.answerText,
      item.text,
      item.content,
      item.output,
      item.final_output_text,
      item.final_preview,
      artifacts.raw_json,
      artifacts.raw_model_json,
      artifacts.final_output_text,
      artifacts.answer_text,
      artifacts.answerText,
      artifacts.text,
      artifacts.content,
      artifacts.output,
      artifacts.final_script
    ];
    return String(candidates.find((value) => String(value || "").trim()) || "").trim();
  }

  function hotReviewExtractAuditViewV5(item) {
    if (!item || typeof item !== "object") return { audit: null, view: null };
    const artifacts = item.artifacts || {};
    const result = hotReviewResultObjectV5(item);

    let audit = item.audit || result.audit || artifacts.audit || null;
    let view = item.view || result.view || artifacts.view || null;

    if (!audit) {
      const parsed = parseScriptAuditJsonFromText(hotReviewFirstTextV5(item));
      if (parsed?.audit && parsed?.view) {
        audit = parsed.audit;
        view = view || parsed.view;
      } else if (looksLikeScriptAuditPayload(parsed)) {
        audit = parsed;
      }
    }

    if (!view && audit) view = scriptAuditViewFromAudit(audit);
    return { audit, view };
  }

  function hotReviewAssetTitleV5(item) {
    const { audit, view } = hotReviewExtractAuditViewV5(item);
    const direct = audit?.meta?.script_title
      || view?.meta?.script_title
      || audit?.script_title
      || view?.script_title
      || item?.script_title
      || "";
    if (String(direct || "").trim()) return String(direct).trim();

    const label = String(item?.tool_label || item?.title || "").trim();
    const labelMatch = label.match(/爆款文审核[｜|]\s*(.+?)(?:[｜|]|$)/);
    if (labelMatch?.[1]) return labelMatch[1].trim();

    const raw = hotReviewFirstTextV5(item);
    const textMatch = raw.match(/《[^》]{1,80}》/);
    if (textMatch?.[0]) return textMatch[0];

    return projectDisplayTitle(item) || "未命名爆款文审核";
  }

  function hotReviewScoreV5(item) {
    const { audit } = hotReviewExtractAuditViewV5(item);
    return audit?.overall?.total_score ?? audit?.overall?.score ?? "";
  }

  function hotReviewUniqueAssetsV5(items) {
    const map = new Map();
    for (const item of Array.isArray(items) ? items : []) {
      if (!isHotReviewAsset(item)) continue;
      const key = hotReviewAssetKeyV5(item) || hotReviewAssetTitleV5(item);
      if (!key) continue;
      map.set(key, { ...(map.get(key) || {}), ...item });
    }
    return [...map.values()].sort((a, b) =>
      String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || ""))
    );
  }

  function isHotReviewAsset(assetLike) {
    if (!assetLike) return false;
    const artifacts = assetLike.artifacts || {};
    const result = hotReviewResultObjectV5(assetLike);
    const values = [
      assetLike.tool_key,
      assetLike.tool_id,
      assetLike.tool_label,
      assetLike.tool_filename,
      assetLike.asset_type,
      assetLike.asset_kind,
      assetLike.category,
      assetLike.workflow_type,
      assetLike.result_type,
      assetLike.resultType,
      result.tool_key,
      result.tool_id,
      result.result_type,
      result.resultType,
      artifacts.tool_key,
      artifacts.tool_id,
      artifacts.result_type,
      artifacts.tool_result?.result_type
    ].map((value) => String(value || "").trim());

    if (values.some((value) =>
      value === "hot_review"
      || value === "script_audit_ecg"
      || value.includes("hot_review")
      || value.includes("script_audit")
      || value.includes("爆款文审核")
    )) {
      return true;
    }

    if (hotReviewExtractAuditViewV5(assetLike).audit) return true;
    return /hot_review|script_audit|script_audit_ecg|爆款文审核|剧本心电图/i.test(
      [assetLike.title, assetLike.summary, hotReviewFirstTextV5(assetLike)].filter(Boolean).join("\\n")
    );
  }




  function toolResultFromAsset(assetLike) {
    const artifacts = assetLike?.artifacts || {};
    const result = hotReviewResultObjectV5(assetLike);
    const { audit, view } = hotReviewExtractAuditViewV5(assetLike);
    const fallbackText = hotReviewFirstTextV5(assetLike) || hotReviewFirstTextV5(result) || hotReviewFirstTextV5(artifacts);
    return normalizeScriptAuditEcgResult({
      ...assetLike,
      ...result,
      text: String(result.text || fallbackText || "").trim(),
      answer_text: String(result.answer_text || result.answerText || fallbackText || "").trim(),
      filename: result.filename || assetLike?.filename || assetLike?.tool_filename || "",
      result_type: result.result_type || assetLike?.result_type || artifacts.result_type || (audit || view ? "script_audit_ecg" : ""),
      resultType: result.resultType || result.result_type || assetLike?.resultType || assetLike?.result_type || (audit || view ? "script_audit_ecg" : ""),
      parsed: result.parsed ?? assetLike?.parsed ?? Boolean(audit || view),
      audit: audit || result.audit || assetLike?.audit || artifacts.audit || null,
      view: view || result.view || assetLike?.view || artifacts.view || null,
      parse_warnings: result.parse_warnings || assetLike?.parse_warnings || artifacts.parse_warnings || [],
      assetSaved: true,
      savedAsset: assetLike
    });
  }




  /* SCRIPT_AUDIT_ECG_SIDEBAR_V1 */
  function hotReviewSidebarAnchor() {
    return els.completedProjectList?.closest("details")
      || els.characterReskinProjectList?.closest("details")
      || els.waibaoProjectList?.closest("details")
      || els.newScriptProjectList?.closest("details")
      || null;
  }

  function ensureHotReviewProjectList() {
    const existing = document.getElementById("hotReviewProjectList");
    if (existing) return existing;

    const anchor = hotReviewSidebarAnchor();
    const parent = anchor?.parentElement;
    if (!parent) return null;

    const details = document.createElement("details");
    details.className = "workspace-folder hot-review-workspace-folder";
    details.open = true;
    details.innerHTML = `
      <summary>
        <span>爆款文审核资产</span>
        <small class="workspace-pick-state" id="hotReviewProjectCount">0</small>
      </summary>
      <div class="workspace-compact-list" id="hotReviewProjectList"></div>
    `;

    if (els.completedProjectList?.closest("details")) {
      els.completedProjectList.closest("details").insertAdjacentElement("afterend", details);
    } else {
      parent.appendChild(details);
    }

    return details.querySelector("#hotReviewProjectList");
  }

  function setHotReviewProjectCount(count) {
    const countEl = document.getElementById("hotReviewProjectCount");
    if (countEl) {
      countEl.textContent = String(Math.max(0, Number(count) || 0));
    }
  }

  function renderHotReviewCompactItems(items, emptyMessage) {
    const normalized = hotReviewUniqueAssetsV5(items);
    if (!normalized.length) {
      return `<div class="workspace-empty">${escapeHtml(emptyMessage)}</div>`;
    }

    return normalized.map((item) => {
      const key = hotReviewAssetKeyV5(item) || hotReviewAssetTitleV5(item);
      const updatedAt = String(item.updated_at || item.created_at || item.createdAt || "").trim();
      const score = hotReviewScoreV5(item);
      const hasScore = score !== "" && score !== null && score !== undefined;
      const scorePercent = hasScore ? Math.max(0, Math.min(100, Number(score) || 0)) : 0;
      const scoreText = hasScore ? `${score}/100` : statusLabel(item.status);
      return `
        <div class="workspace-pick-row hot-review-workspace-pick-row" style="--asset-progress: ${scorePercent}%;">
          <button
            class="workspace-pick hot-review-workspace-pick"
            type="button"
            data-action="open-hot-review-asset"
            data-project-id="${escapeHtml(key)}"
            data-hot-review-asset-key="${escapeHtml(key)}"
            title="${escapeHtml(hotReviewAssetTitleV5(item))}"
          >
            <span class="workspace-pick-main">
              <span class="workspace-pick-title">${escapeHtml(hotReviewAssetTitleV5(item))}</span>
              <span class="workspace-pick-meta">${escapeHtml(updatedAt || "爆款文审核资产")}</span>
            </span>
            <span class="workspace-pick-state">${escapeHtml(scoreText)}</span>
            <span class="workspace-pick-progress${hasScore ? "" : " is-empty"}" role="progressbar" aria-label="审核评分" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${scorePercent}">
              <span class="workspace-pick-progress-bar"></span>
            </span>
          </button>
          <button
            class="btn btn-danger workspace-pick-delete"
            type="button"
            data-action="delete-hot-review-asset"
            data-project-id="${escapeHtml(key)}"
            title="删除爆款文审核资产"
          >删除</button>
        </div>
      `;
    }).join("");
  }




  function assetTypeLabel(assetLike) {
    if (isHotReviewAsset(assetLike)) return "爆款文审核";
    return isToolAsset(assetLike) ? "辅助工具" : "剧本资产";
  }

  function assetWorkflowLabel(assetLike) {
    return String(assetLike?.tool_label || "").trim() || assetTypeLabel(assetLike);
  }

  function downloadToolButtonEnabled(toolKey = state.activeTool) {
    const result = currentToolResult(toolKey);
    return Boolean(result?.text && result?.filename);
  }

  /* SCRIPT_AUDIT_ECG_UI_V1 */

  function isScriptAuditEcgResult(result) {
    if (!result) {
      return false;
    }

    const resultType = String(
      result.result_type
      || result.resultType
      || ""
    ).trim();

    return Boolean(
      resultType === "script_audit_ecg"
      || (result.audit && (result.view || looksLikeScriptAuditPayload(result.audit)))
    );
  }


  function auditArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function auditText(value, fallback = "") {
    return String(value ?? fallback).trim();
  }

  function auditNumber(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function auditSeverityClass(value) {
    const text = auditText(value);
    if (text.includes("高") || text.includes("严重")) return "is-high";
    if (text.includes("中")) return "is-mid";
    if (text.includes("低")) return "is-low";
    return "";
  }

  function auditFirstText(...values) {
    for (const value of values) {
      const text = auditText(value);
      if (text) return text;
    }
    return "";
  }

  function auditScoreText(value) {
    const number = auditNumber(value, 0);
    return `${number > 0 ? "+" : ""}${Number.isInteger(number) ? number : number.toFixed(1)}`;
  }

  function auditListSummary(items, fields = []) {
    return auditArray(items).map((item, index) => {
      if (!item || typeof item !== "object") return auditText(item);
      return auditFirstText(
        ...fields.map((field) => item[field]),
        item.title,
        item.description,
        item.problem,
        item.content,
        item.fix_suggestion,
        `条目 ${index + 1}`
      );
    }).filter(Boolean);
  }


  /* SCRIPT_AUDIT_ECG_ASSET_PARSE_V1 */
  function parseScriptAuditJsonFromText(rawText) {
    let text = String(rawText || "").trim();
    if (!text) return null;

    const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
    if (fenced && fenced[1]) {
      text = fenced[1].trim();
    }

    const tryParse = (value) => {
      const variants = [
        value,
        String(value || "").replace(/[“”]/g, '"').replace(/[‘’]/g, "'"),
        String(value || "").replace(/,\s*([}\]])/g, "$1"),
        String(value || "").replace(/[“”]/g, '"').replace(/[‘’]/g, "'").replace(/,\s*([}\]])/g, "$1")
      ];
      for (const variant of variants) {
        try {
          return JSON.parse(variant);
        } catch (_) {
          // try the next repair variant
        }
      }
      return null;
    };

    let parsed = tryParse(text);
    if (!parsed) {
      const start = text.indexOf("{");
      const end = text.lastIndexOf("}");
      if (start >= 0 && end > start) {
        parsed = tryParse(text.slice(start, end + 1));
      }
    }

    if (typeof parsed === "string") {
      parsed = parseScriptAuditJsonFromText(parsed);
    }

    if (parsed && typeof parsed === "object") {
      const nestedText = parsed.answerText
        || parsed.answer_text
        || parsed.text
        || parsed.output
        || parsed.result
        || parsed.data
        || "";
      if (
        typeof nestedText === "string"
        && nestedText.trim()
        && (nestedText.includes("script_audit_ecg_v2") || nestedText.includes("script_audit_ecg_v3") || nestedText.includes("script_audit_compact_v1") || nestedText.includes('"overall"'))
      ) {
        const nested = parseScriptAuditJsonFromText(nestedText);
        if (nested && typeof nested === "object") return nested;
      }
      return parsed;
    }

    return null;
  }

  function looksLikeScriptAuditPayload(payload) {
    if (!payload || typeof payload !== "object") return false;
    const schema = String(payload.schema_version || "");
    return schema.includes("script_audit_ecg")
      || schema === "script_audit_compact_v1"
      || Boolean(payload.overall && (payload.dimension_scores || payload.global_dimensions || payload.ecg || payload.global_review || payload.episode_reviews || payload.episodes || payload.key_issues))
      || Boolean(payload.audit && (payload.view || payload.visualization));
  }

  function scriptAuditScoreValue(audit) {
    const score = audit?.overall?.total_score ?? audit?.overall?.score ?? audit?.total_score ?? "";
    const numeric = Number(score);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function preferScriptAuditCandidate(currentAudit, candidateAudit) {
    if (!candidateAudit || typeof candidateAudit !== "object") return currentAudit || null;
    if (!currentAudit || typeof currentAudit !== "object") return candidateAudit;
    const candidateScore = scriptAuditScoreValue(candidateAudit);
    const currentScore = scriptAuditScoreValue(currentAudit);
    const candidateHasContent = candidateScore !== null && candidateScore > 0;
    const currentHasContent = currentScore !== null && currentScore > 0;
    if (candidateHasContent && !currentHasContent) return candidateAudit;
    const candidateIssueCount = auditArray(candidateAudit.key_issues).length
      + auditArray(candidateAudit.rewrite_plan).length
      + auditArray(candidateAudit.episode_reviews).length
      + auditArray(candidateAudit.segments).length;
    const currentIssueCount = auditArray(currentAudit.key_issues).length
      + auditArray(currentAudit.rewrite_plan).length
      + auditArray(currentAudit.episode_reviews).length
      + auditArray(currentAudit.segments).length;
    return candidateIssueCount > currentIssueCount ? candidateAudit : currentAudit;
  }

  function scriptAuditViewFromAudit(audit, visualization = null) {
    const overall = audit?.overall || {};
    const dimensions = auditArray(visualization?.dimension_cards || audit?.dimension_scores || audit?.dimensions || audit?.dimension_cards);
    const globalReview = audit?.global_review || {};
    const compactGlobalReview = {
      main_genre: globalReview.main_genre,
      main_emotional_contract: globalReview.main_emotional_contract,
      main_conflict_chain: globalReview.main_conflict_chain,
      protagonist_arc: globalReview.protagonist_arc,
      payoff_chain: globalReview.payoff_chain,
      global_retention_problem: globalReview.global_retention_problem,
      global_revision_priority: globalReview.global_revision_priority,
      global_score_explanation: globalReview.global_score_explanation,
      global_strength_summary: globalReview.global_strength_summary,
      global_weakness_summary: globalReview.global_weakness_summary
    };
    const globalEcg = globalReview?.ecg || audit?.ecg || audit?.ecg_chart || {};
    const points = auditArray(
      visualization?.ecg_chart?.global?.points
      || globalReview?.global_ecg_points
      || globalEcg?.main_series?.points
      || globalEcg?.points
      || audit?.ecg_chart?.points
      || audit?.main_series?.points
    ).slice().sort((a, b) =>
      (auditNumber(a.episode_no) - auditNumber(b.episode_no))
      || (auditNumber(a.segment_index_global || a.segment_index) - auditNumber(b.segment_index_global || b.segment_index))
      || (auditNumber(a.start_offset) - auditNumber(b.start_offset))
    );

    const totalScore = overall.total_score ?? overall.score ?? audit?.total_score ?? "";
    const grade = overall.suitability_level || overall.grade || overall.level || "";
    const revisionCost = overall.revision_cost || overall.modify_cost || overall.cost || "";
    const episodeScoreMap = auditArray(visualization?.episode_score_map || globalReview.episode_score_map);
    const episodeCards = auditArray(audit?.episode_reviews || audit?.episode_summaries);
    const episodeNos = [...new Set([
      ...points.map((point) => auditNumber(point.episode_no, 0)).filter(Boolean),
      ...episodeCards.map((item) => auditNumber(item.episode_no, 0)).filter(Boolean),
      ...episodeScoreMap.map((item) => auditNumber(item.episode_no, 0)).filter(Boolean)
    ])].sort((a, b) => a - b);
    const scoreByEpisode = new Map(episodeScoreMap.map((item) => [auditNumber(item.episode_no, 0), item]));
    const episodeMarkers = episodeNos.map((episodeNo) => {
      const group = points.filter((point) => auditNumber(point.episode_no, 0) === episodeNo);
      const score = scoreByEpisode.get(episodeNo) || {};
      return {
        episode_no: episodeNo,
        episode_title: score.episode_title || `第${episodeNo}集`,
        point_count: group.length,
        episode_score: score.episode_score ?? "",
        retention_status: score.retention_status || "",
        main_problem: score.main_problem || "",
        next_priority_fix: score.next_priority_fix || ""
      };
    });
    const exportText = buildAuditExportText(audit, {
      points,
      dimensions,
      episodeCards,
      globalReview,
      totalScore,
      grade,
      revisionCost,
      structure: globalReview.global_structure_judgement || compactGlobalReview
    });

    return {
      summary_cards: [
        { key: "total_score", label: "总评分", value: totalScore, suffix: totalScore !== "" ? "/100" : "" },
        { key: "grade", label: "适配等级", value: grade || "-" },
        { key: "revision_cost", label: "修改成本", value: revisionCost || "-" },
        { key: "episodes", label: "总集数", value: audit?.meta?.total_episode_count || episodeNos.length || "-" },
        { key: "points", label: "心电点位", value: points.length || "-" }
      ],
      ecg_chart: {
        title: globalEcg?.title || audit?.ecg_chart?.title || "全剧总心电图",
        points,
        episode_markers: episodeMarkers,
        y_axis_range: globalEcg?.y_axis_range || [-5, 5],
        baseline: globalEcg?.baseline ?? 0,
        peak_points: auditArray(visualization?.ecg_chart?.global?.peak_points || globalEcg?.peak_points),
        valley_points: auditArray(visualization?.ecg_chart?.global?.valley_points || globalEcg?.valley_points)
      },
      dimension_cards: dimensions.map((item) => ({
        dimension_key: item.dimension_key || item.key || item.name || "",
        dimension_name: item.dimension_name || item.name || item.dimension_key || "评分维度",
        score: item.score ?? item.value ?? 0,
        max_score: item.max_score ?? item.full_score ?? 100,
        summary: item.summary || item.comment || item.reason || "",
        core_deductions: item.core_deductions || item.deductions || [],
        priority_fix: item.priority_fix || item.fix_suggestion || item.suggestion || ""
      })),
      global_review: {
        structure: globalReview.global_structure_judgement || compactGlobalReview || {},
        satisfying_points: auditArray(globalReview.global_satisfying_points || audit?.satisfying_points || audit?.selling_points),
        key_issues: auditArray(globalReview.global_key_issues || audit?.key_issues || audit?.issues),
        risk_scan: auditArray(globalReview.global_risk_scan || audit?.risk_scan || audit?.risks),
        rewrite_plan: auditArray(globalReview.global_rewrite_plan || audit?.rewrite_plan || audit?.fix_plan),
        episode_score_map: episodeScoreMap
      },
      issue_cards: auditArray(globalReview.global_key_issues || audit?.key_issues || audit?.issues || audit?.issue_cards),
      satisfying_point_cards: auditArray(globalReview.global_satisfying_points || audit?.satisfying_points || audit?.selling_points || audit?.satisfying_point_cards),
      risk_cards: auditArray(globalReview.global_risk_scan || audit?.risk_scan || audit?.risks || audit?.risk_cards),
      rewrite_tasks: auditArray(globalReview.global_rewrite_plan || audit?.rewrite_plan || audit?.rewrite_tasks || audit?.fix_plan),
      episode_cards: episodeCards,
      cross_episode_analysis: audit?.cross_episode_analysis || {},
      export_text: exportText,
      meta: {
        script_title: audit?.meta?.script_title || audit?.script_title || "",
        text_type: audit?.meta?.text_type || "",
        audit_scope: audit?.meta?.audit_scope || "",
        total_episode_count: audit?.meta?.total_episode_count || episodeNos.length || 0,
        total_segment_count: audit?.meta?.total_segment_count || points.length || 0
      }
    };
  }

  function buildAuditExportText(audit, context = {}) {
    const overall = audit?.overall || {};
    const meta = audit?.meta || {};
    const points = auditArray(context.points);
    const dimensions = auditArray(context.dimensions);
    const episodeCards = auditArray(context.episodeCards);
    const globalReview = context.globalReview || audit?.global_review || {};
    const structure = context.structure || globalReview.global_structure_judgement || {
      main_genre: globalReview.main_genre,
      main_emotional_contract: globalReview.main_emotional_contract,
      main_conflict_chain: globalReview.main_conflict_chain,
      protagonist_arc: globalReview.protagonist_arc,
      payoff_chain: globalReview.payoff_chain,
      global_retention_problem: globalReview.global_retention_problem,
      global_revision_priority: globalReview.global_revision_priority,
      global_score_explanation: globalReview.global_score_explanation,
      global_strength_summary: globalReview.global_strength_summary,
      global_weakness_summary: globalReview.global_weakness_summary
    };
    const lines = [
      `《${meta.script_title || "未命名剧本"}》爆款文审核报告`,
      "",
      "一、整体剧本评价",
      `总评分：${overall.total_score ?? overall.score ?? "-"} / 100`,
      `评级：${overall.level || "-"}`,
      `修改成本：${overall.modification_cost || "-"}`,
      `核心判断：${overall.core_judgement || "-"}`,
      `最大问题：${overall.largest_problem || overall.largest_hard_problem || "-"}`,
      `最佳保留：${overall.best_retained_part || "-"}`,
      `最终判断：${overall.final_judgement || "-"}`,
      "",
      "二、全局结构判断",
      `主类型：${structure.main_genre || "-"}`,
      `情绪契约：${structure.main_emotional_contract || "-"}`,
      `主冲突链：${structure.main_conflict_chain || "-"}`,
      `主角弧线：${structure.protagonist_arc || "-"}`,
      `留存问题：${structure.global_retention_problem || "-"}`,
      `修改优先级：${structure.global_revision_priority || "-"}`,
      `全剧得分解释：${structure.global_score_explanation || "-"}`,
      `全剧优势：${structure.global_strength_summary || "-"}`,
      `全剧短板：${structure.global_weakness_summary || "-"}`,
      "",
      "三、评分维度",
      ...dimensions.map((item) => `- ${item.dimension_name || item.dimension_key || "评分维度"}：${item.score ?? "-"} / ${item.max_score ?? "-"}。${item.summary || item.priority_fix || ""}`),
      "",
      "四、心电图节点摘要",
      ...points.map((point) => `- 第${point.episode_no || "?"}集 ${point.x_label || point.short_label || point.point_id || ""}：${auditScoreText(point.ecg_value)}。${point.audit_reason || point.commercial_effect || point.problem_if_any || ""}${point.fix_suggestion ? ` 建议：${point.fix_suggestion}` : ""}`),
      "",
      "五、单集重点评价",
      ...episodeCards.map((episode) => {
        const eo = episode.episode_overall || episode;
        return `- 第${episode.episode_no || "?"}集 ${episode.episode_title || ""}：${eo.episode_score ?? "-"} / 100。${eo.core_judgement || ""} 主钩子：${eo.main_hook || "-"}；主冲突：${eo.main_conflict || "-"}；优先修改：${eo.priority_fix || "-"}`;
      })
    ];
    return lines.filter((line) => line !== null && line !== undefined).join("\n").trim();
  }

  function normalizeScriptAuditEcgResult(result) {
    if (!result || typeof result !== "object") return result;

    let audit = result.audit || null;
    let view = result.view || null;
    let visualization = result.visualization || null;
    const resultType = String(result.result_type || result.resultType || "").trim();

    const candidates = [
      audit,
      result.output,
      result.result,
      result.data,
      result.tool_result,
      result.artifacts,
      result.savedAsset,
      result.saved_asset,
      parseScriptAuditJsonFromText(result.text),
      parseScriptAuditJsonFromText(result.answer_text),
      parseScriptAuditJsonFromText(result.answerText),
      parseScriptAuditJsonFromText(result.raw_text),
      parseScriptAuditJsonFromText(result.content),
      parseScriptAuditJsonFromText(result.final_output_text)
    ].filter(Boolean);

    for (const candidate of candidates) {
      if (candidate?.audit && candidate?.view) {
        const preferredAudit = preferScriptAuditCandidate(audit, candidate.audit);
        const replacedAudit = preferredAudit !== audit;
        audit = preferredAudit;
        view = replacedAudit ? candidate.view : (view || candidate.view);
        visualization = visualization || candidate.visualization || null;
        continue;
      }
      if (candidate?.audit && candidate?.visualization) {
        const preferredAudit = preferScriptAuditCandidate(audit, candidate.audit);
        const replacedAudit = preferredAudit !== audit;
        audit = preferredAudit;
        visualization = replacedAudit ? candidate.visualization : (visualization || candidate.visualization);
        view = replacedAudit ? (candidate.view || null) : (view || candidate.view || null);
        continue;
      }
      if (looksLikeScriptAuditPayload(candidate)) {
        const candidateAudit = candidate.audit && (candidate.view || candidate.visualization) ? candidate.audit : candidate;
        const preferredAudit = preferScriptAuditCandidate(audit, candidateAudit);
        const replacedAudit = preferredAudit !== audit;
        audit = preferredAudit;
        visualization = replacedAudit ? (candidate.visualization || null) : (visualization || candidate.visualization || null);
        view = replacedAudit ? (candidate.view || view || null) : view;
        continue;
      }
    }

    const rawText = result.text
      || result.answer_text
      || result.answerText
      || result.content
      || hotReviewFirstTextV4(result)
      || "";

    if (!audit && resultType === "script_audit_ecg") {
      audit = fallbackScriptAuditFromText(rawText, result.parse_warnings || result.parseWarnings || []);
    }

    if (!audit && !view) return result;
    if (!view && audit) view = scriptAuditViewFromAudit(audit, visualization);

    return {
      ...result,
      text: String(rawText || "").trim(),
      answer_text: String(result.answer_text || result.answerText || rawText || "").trim(),
      result_type: "script_audit_ecg",
      resultType: "script_audit_ecg",
      parsed: result.parsed === false ? false : true,
      audit: audit || {},
      visualization: visualization || {},
      view,
      warnings: result.warnings || result.parse_warnings || result.parseWarnings || [],
      parse_warnings: result.parse_warnings || result.parseWarnings || result.warnings || []
    };
  }

  function fallbackScriptAuditFromText(rawText, warnings = []) {
    const text = String(rawText || "").trim();
    const titleMatch = text.match(/《([^》]{1,80})》/) || text.match(/剧本(?:标题|名称)\s*[:：]\s*([^\n\r]{1,80})/);
    const scriptTitle = titleMatch?.[1]?.trim() || "未命名剧本";
    const excerpt = text.replace(/\s+/g, " ").slice(0, 1200);
    return {
      schema_version: "script_audit_ecg_v3_episode_global",
      meta: {
        script_title: scriptTitle,
        text_type: "未知",
        audit_scope: "解析容错",
        total_episode_count: 0,
        total_segment_count: 0
      },
      overall: {
        total_score: 0,
        level: "待重新解析",
        modification_cost: "未知",
        core_judgement: "模型输出暂时无法完整解析，已保留固定可视化面板。",
        largest_hard_problem: "缺少合法结构化 JSON。",
        final_judgement: "请重新运行审核，或检查模型是否严格返回指定 schema。"
      },
      dimension_scores: [],
      global_review: {
        global_structure_judgement: {
          global_retention_problem: "当前缺少可解析心电节点。",
          global_revision_priority: "优先修复模型输出格式。"
        },
        ecg: {
          title: "全剧总心电图",
          main_series: { points: [] },
          negative_zones: [],
          peak_points: [],
          valley_points: []
        },
        episode_score_map: [],
        global_satisfying_points: [],
        global_key_issues: [{
          title: "解析失败",
          risk_level: "高",
          description: "模型输出未能被解析为爆款文审核 v3 结构。",
          evidence: excerpt,
          fix_suggestion: "重新运行审核，要求模型只返回合法 JSON。"
        }],
        global_risk_scan: [],
        global_rewrite_plan: [{
          task_id: "parse_retry",
          priority: 1,
          target: "合规",
          problem: "返回内容不是可解析 JSON。",
          specific_action: "重新运行爆款文审核。",
          expected_result: "恢复完整心电图和单集评价。"
        }]
      },
      episode_reviews: [],
      cross_episode_analysis: {
        title: "跨集结构分析",
        retention_curve_summary: "解析失败，暂无法生成。"
      },
      parse_fallback: {
        enabled: true,
        warnings,
        raw_excerpt: excerpt
      }
    };
  }




  function renderAuditSummaryCards(cards) {
    const normalized = auditArray(cards);
    if (!normalized.length) return "";
    return `
      <section class="audit-card-grid audit-summary-grid">
        ${normalized.map((card) => `
          <article class="audit-summary-card">
            <small>${escapeHtml(card.label || card.key || "")}</small>
            <strong>${escapeHtml(auditText(card.value, "-"))}${escapeHtml(card.suffix || "")}</strong>
          </article>
        `).join("")}
      </section>
    `;
  }

  function renderAuditPopoverButton(title, bodyHtml, count = "") {
    if (!auditText(bodyHtml)) return "";
    return `
      <section class="audit-inline-section">
        <button class="audit-popover-trigger" type="button" data-action="toggle-audit-popover" aria-expanded="false">
          <span>${escapeHtml(title)}</span>
          ${count !== "" ? `<small>${escapeHtml(count)}</small>` : ""}
          <b aria-hidden="true">⌄</b>
        </button>
        <div class="audit-popover audit-inline-card" data-audit-popover hidden>
          <div class="audit-popover-card">
            ${bodyHtml}
          </div>
        </div>
      </section>
    `;
  }

  function renderAuditKeyValueList(items) {
    return `
      <div class="audit-kv-list">
        ${items.filter((item) => auditText(item.value)).map((item) => `
          <div>
            <small>${escapeHtml(item.label)}</small>
            <strong>${escapeHtml(item.value)}</strong>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderAuditEcgChart(chart) {
    const sourcePoints = auditArray(chart?.points);
    if (!sourcePoints.length) {
      return `<section class="audit-panel"><h4>剧本心电图</h4><p class="audit-empty">暂无心电点位。</p></section>`;
    }

    const points = sourcePoints.slice().sort((a, b) =>
      (auditNumber(a.episode_no, 0) - auditNumber(b.episode_no, 0))
      || (auditNumber(a.segment_index_global || a.segment_index, 0) - auditNumber(b.segment_index_global || b.segment_index, 0))
      || (auditNumber(a.segment_index_in_episode, 0) - auditNumber(b.segment_index_in_episode, 0))
      || (auditNumber(a.scene_no, 0) - auditNumber(b.scene_no, 0))
      || (auditNumber(a.start_offset, 0) - auditNumber(b.start_offset, 0))
      || (auditNumber(a.x, 0) - auditNumber(b.x, 0))
    );
    const markerEpisodes = auditArray(chart?.episode_markers)
      .map((item) => auditNumber(item.episode_no, 0))
      .filter(Boolean);
    const pointEpisodes = points.map((point) => auditNumber(point.episode_no, 0)).filter(Boolean);
    const orderedEpisodeNos = [...new Set([...markerEpisodes, ...pointEpisodes])].sort((a, b) => a - b);
    const unknownPoints = points.filter((point) => !auditNumber(point.episode_no, 0));
    const episodeGroups = orderedEpisodeNos.map((episodeNo) => ({
      episodeNo,
      label: `第${episodeNo}集`,
      points: points.filter((point) => auditNumber(point.episode_no, 0) === episodeNo)
    }));
    if (unknownPoints.length) {
      episodeGroups.push({
        episodeNo: 0,
        label: "未标集数",
        points: unknownPoints
      });
    }

    const sectionGap = 10;
    const minSectionW = 48;
    const pointGap = 36;
    const sectionPad = 14;
    const sectionWidths = episodeGroups.map((group) =>
      Math.max(minSectionW, sectionPad * 2 + Math.max(0, group.points.length - 1) * pointGap)
    );
    const width = Math.max(920, sectionWidths.reduce((sum, value) => sum + value, 0) + Math.max(0, episodeGroups.length - 1) * sectionGap + 108);
    const height = 300;
    const padX = 54;
    const padY = 34;
    const plotH = height - padY * 2;
    const maxAbs = 5;
    const yOf = (value) => padY + ((maxAbs - Math.max(-maxAbs, Math.min(maxAbs, value))) / (maxAbs * 2)) * plotH;
    const zeroY = yOf(0);
    const pointLayouts = [];
    const episodeLayouts = [];
    let cursorX = padX;
    episodeGroups.forEach((group, groupIndex) => {
      const sectionW = sectionWidths[groupIndex];
      const startX = cursorX;
      const centerX = startX + sectionW / 2;
      const groupPoints = group.points;
      episodeLayouts.push({
        ...group,
        startX,
        centerX,
        endX: startX + sectionW,
        width: sectionW
      });
      groupPoints.forEach((point, pointIndex) => {
        const x = groupPoints.length <= 1
          ? centerX
          : startX + sectionPad + pointIndex * ((sectionW - sectionPad * 2) / Math.max(1, groupPoints.length - 1));
        pointLayouts.push({ point, index: points.indexOf(point), x });
      });
      cursorX += sectionW + sectionGap;
    });
    pointLayouts.sort((a, b) => a.x - b.x);

    const episodeBands = episodeLayouts.map((group, index) => `
      <rect class="audit-episode-band ${index % 2 ? "is-alt" : ""}" x="${group.startX.toFixed(1)}" y="${padY}" width="${group.width.toFixed(1)}" height="${plotH}"></rect>
    `).join("");

    const segments = pointLayouts.slice(1).map((layout, index) => {
      const point = layout.point;
      const prevLayout = pointLayouts[index];
      const prev = prevLayout.point;
      const v1 = auditNumber(prev.ecg_value);
      const v2 = auditNumber(point.ecg_value);
      const klass = (v1 + v2) / 2 >= 0 ? "audit-ecg-line-pos" : "audit-ecg-line-neg";
      return `<line class="${klass}" x1="${prevLayout.x.toFixed(1)}" y1="${yOf(v1).toFixed(1)}" x2="${layout.x.toFixed(1)}" y2="${yOf(v2).toFixed(1)}"></line>`;
    }).join("");

    const episodeLines = episodeLayouts.map((group) => {
      const x = group.startX;
      const countLabel = group.points.length > 1 ? ` · ${group.points.length}点` : "";
      return `
        <line class="audit-episode-marker" x1="${x.toFixed(1)}" y1="${padY}" x2="${x.toFixed(1)}" y2="${height - padY}"></line>
        <text class="audit-episode-label" x="${group.centerX.toFixed(1)}" y="${height - 8}" text-anchor="middle">${escapeHtml(group.label + countLabel)}</text>
      `;
    }).join("");

    const circles = pointLayouts.map((layout) => {
      const point = layout.point;
      const index = layout.index;
      const value = auditNumber(point.ecg_value);
      const klass = value >= 0 ? "audit-ecg-dot-pos" : "audit-ecg-dot-neg";
      const title = auditText(point.hover_title || point?.hover_card?.title || point.short_label || point.event_type || point.point_id, `第${index + 1}点`);
      const reason = auditText(point.audit_reason || point.hover_body || point?.hover_card?.body || point.commercial_effect || "");
      const tooltip = `第${point.episode_no || "?"}集｜${auditScoreText(value)}｜${title}${reason ? "｜" + reason : ""}`;
      return `
        <g class="audit-ecg-node" data-action="show-audit-point" data-point-index="${index}" tabindex="0">
          <circle class="audit-ecg-dot ${klass}" cx="${layout.x.toFixed(1)}" cy="${yOf(value).toFixed(1)}" r="5.5"></circle>
          <title>${escapeHtml(tooltip)}</title>
        </g>
      `;
    }).join("");

    return `
      <section class="audit-panel audit-ecg-panel">
        <div class="audit-section-head">
          <div>
            <h4>${escapeHtml(chart?.title || "剧本心电图")}</h4>
            <p>按实际集数划分点位；悬停看摘要，点击节点看详细便签。</p>
          </div>
          <span class="audit-chip">点位 ${points.length}</span>
        </div>
        <div class="audit-ecg-wrap" data-audit-chart='${escapeHtml(JSON.stringify(points))}'>
          <svg class="audit-ecg-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="剧本心电图">
            ${episodeBands}
            <line class="audit-ecg-axis" x1="${padX}" y1="${zeroY.toFixed(1)}" x2="${width - padX}" y2="${zeroY.toFixed(1)}"></line>
            <text class="audit-ecg-label" x="8" y="${yOf(5).toFixed(1)}">+5</text>
            <text class="audit-ecg-label" x="8" y="${zeroY.toFixed(1)}">0</text>
            <text class="audit-ecg-label" x="8" y="${yOf(-5).toFixed(1)}">-5</text>
            ${episodeLines}
            ${segments}
            ${circles}
          </svg>
          <div class="audit-point-sticky" data-audit-point-card hidden></div>
        </div>
      </section>
    `;
  }

  function renderAuditPointSticky(point, index) {
    if (!point) return "";
    const impacts = auditArray(point.score_impacts);
    return `
      <article class="audit-point-card ${auditNumber(point.ecg_value) >= 0 ? "is-positive" : "is-negative"}">
        <button class="audit-popover-close" type="button" data-action="close-audit-point" aria-label="关闭">×</button>
        <div class="audit-point-score">${escapeHtml(auditScoreText(point.ecg_value))}</div>
        <div>
          <strong>${escapeHtml(point.hover_title || point?.hover_card?.title || point.short_label || point.event_type || `第${index + 1}点`)}</strong>
          <p>${escapeHtml(point.audit_reason || point.hover_body || point?.hover_card?.body || point.commercial_effect || "")}</p>
          ${point.segment_excerpt || point.original_text_excerpt || point?.hover_card?.evidence ? `<small>证据：${escapeHtml(point.segment_excerpt || point.original_text_excerpt || point.hover_card.evidence)}</small>` : ""}
          ${point.problem_if_any ? `<small>问题：${escapeHtml(point.problem_if_any)}</small>` : ""}
          ${point.fix_suggestion || point?.hover_card?.fix ? `<small class="audit-fix">建议：${escapeHtml(point.fix_suggestion || point.hover_card.fix)}</small>` : ""}
          ${impacts.length ? `<small>评分影响：${escapeHtml(impacts.map((item) => `${item.dimension_key || item.sub_key || "维度"} ${item.impact || ""} ${item.reason || ""}`).join("；"))}</small>` : ""}
        </div>
      </article>
    `;
  }

  function renderAuditDimensionCards(cards) {
    const normalized = auditArray(cards);
    if (!normalized.length) return "";
    return `
      <section class="audit-panel">
        <div class="audit-section-head"><h4>评分维度</h4></div>
        <div class="audit-dimension-grid">
          ${normalized.map((item) => {
            const score = auditNumber(item.score);
            const maxScore = auditNumber(item.max_score, 100) || 100;
            const pct = Math.max(0, Math.min(100, Math.round(score / maxScore * 100)));
            return `
              <article class="audit-dimension-card">
                <div>
                  <strong>${escapeHtml(item.dimension_name || item.dimension_key || "评分维度")}</strong>
                  <b>${escapeHtml(String(score))}/${escapeHtml(String(maxScore))}</b>
                </div>
                <div class="audit-progress"><i style="width:${pct}%"></i></div>
                <p>${escapeHtml(item.summary || item.priority_fix || "")}</p>
                ${auditArray(item.core_deductions).length ? `<small>扣分：${escapeHtml(auditArray(item.core_deductions).join("；"))}</small>` : ""}
                ${item.priority_fix ? `<small>优先修改：${escapeHtml(item.priority_fix)}</small>` : ""}
              </article>
            `;
          }).join("")}
        </div>
      </section>
    `;
  }

  function renderAuditList(title, items, options = {}) {
    const normalized = auditArray(items);
    if (!normalized.length) return "";
    const limit = options.limit || 8;
    return `
      <section class="audit-panel">
        <div class="audit-section-head">
          <h4>${escapeHtml(title)}</h4>
          <span class="audit-chip">${normalized.length}</span>
        </div>
        <div class="audit-list">
          ${normalized.slice(0, limit).map((item, index) => {
            const name = item.title || item.issue_title || item.risk_point || item.task_title || item.type || item.point_type || item.content || `条目 ${index + 1}`;
            const level = item.severity || item.risk_level || item.priority || item.strength || "";
            const body = item.summary || item.description || item.reason || item.problem || item.impact || item.content || item.fix_suggestion || item.rewrite_action || "";
            const evidence = item.evidence || item.text_evidence || item.original_text_excerpt || "";
            const fix = item.fix_suggestion || item.suggestion || item.rewrite_action || item.enhancement_suggestion || "";
            return `
              <article class="audit-list-card ${auditSeverityClass(level)}">
                <div>
                  <strong>${escapeHtml(name)}</strong>
                  ${level ? `<span class="audit-chip">${escapeHtml(level)}</span>` : ""}
                </div>
                ${body ? `<p>${escapeHtml(body)}</p>` : ""}
                ${evidence ? `<small>依据：${escapeHtml(evidence)}</small>` : ""}
                ${fix ? `<small class="audit-fix">建议：${escapeHtml(fix)}</small>` : ""}
              </article>
            `;
          }).join("")}
        </div>
      </section>
    `;
  }

  function renderGlobalReviewPopover(view, audit) {
    const globalReview = view.global_review || {};
    const structure = globalReview.structure || {};
    return renderAuditPopoverButton("全局评价", `
      <h4>全局评价</h4>
      ${renderAuditKeyValueList([
        { label: "主类型", value: structure.main_genre },
        { label: "情绪契约", value: structure.main_emotional_contract },
        { label: "主冲突链", value: structure.main_conflict_chain },
        { label: "主角弧线", value: structure.protagonist_arc },
        { label: "爽点兑现链", value: structure.payoff_chain },
        { label: "留存问题", value: structure.global_retention_problem },
        { label: "修改优先级", value: structure.global_revision_priority },
        { label: "得分解释", value: structure.global_score_explanation },
        { label: "全剧优势", value: structure.global_strength_summary },
        { label: "全剧短板", value: structure.global_weakness_summary },
      ])}
      ${renderAuditList("评分维度", view.dimension_cards || [], { limit: 12 })}
      ${renderAuditList("爽点与保留项", globalReview.satisfying_points || [], { limit: 8 })}
    `, "展开");
  }

  function renderEpisodeReviewsPopover(view) {
    const episodes = auditArray(view.episode_cards);
    return renderAuditPopoverButton("单集评价", `
      <h4>单集评价</h4>
      <div class="audit-episode-list">
        ${episodes.length ? episodes.map((episode) => {
          const overall = episode.episode_overall || episode;
          const scope = episode.episode_scope || {};
          const structure = episode.episode_structure || {};
          return `
            <article class="audit-list-card">
              <div>
                <strong>第${escapeHtml(episode.episode_no || "?")}集 ${escapeHtml(episode.episode_title || "")}</strong>
                <span class="audit-chip">${escapeHtml(auditText(overall.episode_score, "-"))}/100</span>
              </div>
              ${renderAuditKeyValueList([
                { label: "核心判断", value: overall.core_judgement },
                { label: "主钩子", value: overall.main_hook },
                { label: "主冲突", value: overall.main_conflict },
                { label: "主爽点", value: overall.main_payoff },
                { label: "最大流失点", value: overall.largest_retention_loss },
                { label: "最佳保留", value: overall.best_retained_part },
                { label: "得分解释", value: overall.episode_score_explanation },
                { label: "集尾拉力", value: overall.next_episode_pull },
                { label: "优先修改", value: overall.priority_fix },
                { label: "集尾钩子", value: episode.ending_hook?.content || episode.ending_hook?.strength },
                { label: "集目标", value: structure.episode_goal },
                { label: "主要阻力", value: structure.main_obstacle },
                { label: "被迫选择", value: structure.forced_choice },
                { label: "冲突结果", value: structure.conflict_result },
                { label: "局势变化", value: structure.situation_change },
                { label: "主角能动性", value: structure.protagonist_agency },
                { label: "留存引擎", value: structure.retention_engine },
                { label: "结构问题", value: structure.structure_problem },
                { label: "完整性证据", value: scope.integrity_evidence },
              ])}
              ${renderAuditList("关键问题", episode.key_issues || [], { limit: 4 })}
              ${renderAuditList("修改计划", episode.rewrite_plan || [], { limit: 4 })}
            </article>
          `;
        }).join("") : `<p class="audit-empty">暂无单集评价。</p>`}
      </div>
    `, episodes.length);
  }

  function renderCrossEpisodePopover(view) {
    const cross = view.cross_episode_analysis || {};
    return renderAuditPopoverButton("跨集结构分析", `
      <h4>跨集结构分析</h4>
      ${renderAuditKeyValueList([
        { label: "留存曲线", value: cross.retention_curve_summary },
        { label: "爽点分布", value: cross.payoff_distribution_problem || cross.payoff_distribution?.evidence || cross.payoff_distribution?.fix_suggestion },
        { label: "钩子连续性", value: cross.hook_continuity_problem || cross.hook_continuity?.evidence || cross.hook_continuity?.fix_suggestion },
        { label: "人物弧光连续性", value: cross.character_arc_problem || cross.character_arc_continuity?.problem || cross.character_arc_continuity?.fix_suggestion },
        { label: "修改建议", value: cross.fix_suggestion },
        { label: "单集分数趋势", value: cross.episode_score_trend },
        { label: "最佳集", value: cross.best_episode_no ? `第${cross.best_episode_no}集：${cross.best_episode_reason || ""}` : "" },
        { label: "最弱集", value: cross.weakest_episode_no ? `第${cross.weakest_episode_no}集：${cross.weakest_episode_reason || ""}` : "" },
        { label: "分差分析", value: cross.score_gap_analysis },
        { label: "全剧掉点模式", value: cross.global_dropoff_pattern },
      ])}
      ${renderAuditList("掉点风险", cross.episode_dropoff_risks || [], { limit: 10 })}
    `, "展开");
  }

  function renderScriptAuditEcgResult(result) {
    const view = result.view || {};
    const audit = result.audit || {};
    const overall = audit.overall || {};
    const meta = audit.meta || view.meta || {};
    const raw = result.answer_text || result.text || "";
    const warnings = auditArray(result.parse_warnings || result.parseWarnings);
    const score = scriptAuditScoreValue(audit);
    const hasStructuredContent = Boolean(
      (score && score > 0)
      || overall.core_judgement
      || overall.final_judgement
      || auditArray(view.issue_cards || audit.key_issues).length
      || auditArray(view.episode_cards || audit.episode_reviews).length
      || auditArray(view.dimension_cards || audit.dimension_scores).some((item) => Number(item?.score || 0) > 0)
    );
    const showRecoveredText = !hasStructuredContent && String(raw || "").trim();
    return `
      <div class="audit-result-shell">
        ${result.parsed === false || showRecoveredText ? `
          <section class="audit-parse-warning">
            <strong>${showRecoveredText ? "已恢复保存文本，结构化图表不完整。" : "解析未完全成功，已进入容错展示模式。"}</strong>
            <span>${escapeHtml(showRecoveredText ? "该资产保存了审核正文，但结构化 audit/view 字段不完整；下方展示原始审核内容。" : (warnings[0] || "模型输出格式不稳定，当前仅展示可恢复的固定审核面板。"))}</span>
          </section>
        ` : ""}
        <section class="audit-hero">
          <div>
            <div class="audit-kicker">爆款文审核 / ECG REPORT</div>
            <h3>${escapeHtml(meta.script_title || "剧本商业潜力审核")}</h3>
            <p>${escapeHtml(overall.core_judgement || overall.final_judgement || "已解析为结构化审核结果。")}</p>
          </div>
          <div class="audit-score-badge">
            <strong>${escapeHtml(String(overall.total_score ?? view?.summary_cards?.[0]?.value ?? "-"))}</strong>
            <span>/100</span>
          </div>
        </section>

        ${renderAuditSummaryCards(view.summary_cards)}
        ${renderAuditEcgChart(view.ecg_chart)}
        <section class="audit-popover-bar">
          ${renderGlobalReviewPopover(view, audit)}
          ${renderEpisodeReviewsPopover(view)}
          ${renderCrossEpisodePopover(view)}
          ${renderAuditPopoverButton("关键问题", renderAuditList("关键问题", view.issue_cards || audit.key_issues, { limit: 20 }), auditArray(view.issue_cards || audit.key_issues).length)}
          ${renderAuditPopoverButton("风险扫描", renderAuditList("风险扫描", view.risk_cards || audit.risk_scan, { limit: 20 }), auditArray(view.risk_cards || audit.risk_scan).length)}
          ${renderAuditPopoverButton("修改计划", renderAuditList("修改计划", view.rewrite_tasks || audit.rewrite_plan, { limit: 20 }), auditArray(view.rewrite_tasks || audit.rewrite_plan).length)}
          ${result.parsed === false || showRecoveredText ? renderAuditPopoverButton("原始输出摘要", `
            <h4>原始输出摘要</h4>
            <pre class="audit-raw-excerpt">${escapeHtml(raw.slice(0, 4000) || audit?.parse_fallback?.raw_excerpt || "暂无原始输出。")}</pre>
          `, "查看") : ""}
        </section>
        ${showRecoveredText ? `
          <section class="audit-panel">
            <div class="audit-section-head"><h4>已保存审核正文</h4></div>
            <pre class="audit-raw-excerpt">${escapeHtml(raw.slice(0, 12000))}</pre>
          </section>
        ` : ""}
        <section class="audit-export-actions">
          <button class="btn btn-primary" type="button" data-action="save-audit-asset">保存结果到资产</button>
          <button class="btn btn-secondary" type="button" data-action="download-audit-txt">导出 TXT</button>
          <button class="btn btn-secondary" type="button" data-action="download-audit-docx">导出 DOCX</button>
          <button class="btn btn-secondary" type="button" data-action="download-audit-image">导出长图</button>
        </section>
      </div>
    `;
  }



  function renderToolOutput(toolKey = state.activeTool, fallbackText = "") {
    const result = currentToolResult(toolKey);
    if (els.toolOutputBox) {
      if (isScriptAuditEcgResult(result)) {
        els.toolOutputBox.innerHTML = renderScriptAuditEcgResult(result);
      } else if (toolKey === "sitcom_generator" && sitcomResultPayload(result)) {
        els.toolOutputBox.innerHTML = renderSitcomResult(result);
      } else {
        els.toolOutputBox.textContent = result?.text
          || result?.answer_text
          || fallbackText
          || (isAuthenticated()
            ? "这里会显示辅助工具结果。"
            : "登录后可使用辅助工具。");
      }
    }
    if (els.downloadToolBtn) {
      const shouldShow = Boolean(result?.text && result?.filename) && !isScriptAuditEcgResult(result);
      els.downloadToolBtn.classList.toggle("hidden", !shouldShow);
      els.downloadToolBtn.disabled = !shouldShow || isActionLoading("runTool");
      if (shouldShow) {
        els.downloadToolBtn.textContent = toolKey === "character_reskin" && result?.savedAsset?.project_id
          ? "下载 DOCX"
          : "下载 TXT";
      }
    }
  }

  function parseJsonObject(value) {
    if (value && typeof value === "object") return value;
    if (typeof value !== "string") return null;
    const text = value.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
    if (!text || !/^[\[{]/.test(text)) return null;
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  function sitcomJsonStringField(text, fieldName) {
    const escapedName = String(fieldName).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = String(text || "").match(new RegExp(`"${escapedName}"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"`, "s"));
    if (!match) return "";
    try {
      return JSON.parse(`"${match[1]}"`);
    } catch (_) {
      return match[1].replace(/\\n/g, "\n").replace(/\\"/g, '"').trim();
    }
  }

  function sitcomBalancedField(text, fieldName) {
    const source = String(text || "");
    const fieldIndex = source.indexOf(`"${fieldName}"`);
    if (fieldIndex < 0) return null;
    const colonIndex = source.indexOf(":", fieldIndex + fieldName.length + 2);
    if (colonIndex < 0) return null;
    let start = colonIndex + 1;
    while (/\s/.test(source[start] || "")) start += 1;
    const opening = source[start];
    if (opening !== "[" && opening !== "{") return null;
    const closing = opening === "[" ? "]" : "}";
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let index = start; index < source.length; index += 1) {
      const char = source[index];
      if (inString) {
        if (escaped) escaped = false;
        else if (char === "\\") escaped = true;
        else if (char === '"') inString = false;
        continue;
      }
      if (char === '"') inString = true;
      else if (char === opening) depth += 1;
      else if (char === closing) {
        depth -= 1;
        if (depth === 0) {
          try {
            return JSON.parse(source.slice(start, index + 1));
          } catch (_) {
            return null;
          }
        }
      }
    }
    return null;
  }

  function recoverSitcomJsonishText(value) {
    if (typeof value !== "string") return null;
    const text = value.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
    if (!text || (!text.includes('"sitcom_bible"') && !text.includes('"episode_scripts"'))) return null;
    const recovered = {
      schema_version: sitcomJsonStringField(text, "schema_version") || "sitcom_generation_v1",
      generation_mode: sitcomJsonStringField(text, "generation_mode") || "sitcom",
      project_title: sitcomJsonStringField(text, "project_title"),
    };
    ["batch", "sitcom_bible", "season_topic_matrix", "episode_outlines", "episode_scripts", "quality_report", "updated_memory", "next_batch"]
      .forEach((fieldName) => {
        const fieldValue = sitcomBalancedField(text, fieldName);
        if (fieldValue !== null) recovered[fieldName] = fieldValue;
      });
    recovered.final_script_text = sitcomJsonStringField(text, "final_script_text");
    if (!recovered.final_script_text && Array.isArray(recovered.episode_scripts)) {
      recovered.final_script_text = recovered.episode_scripts
        .map((item) => sitcomEpisodeScript(item))
        .filter(Boolean)
        .join("\n\n");
    }
    if (!recovered.final_script_text && !Array.isArray(recovered.episode_scripts)) return null;
    recovered.ok = true;
    return recovered;
  }

  function sitcomResultPayload(result) {
    const candidates = [result?.output, result?.result, result?.text, result?.answer_text];
    for (const candidate of candidates) {
      const parsed = parseJsonObject(candidate) || recoverSitcomJsonishText(candidate);
      if (!parsed) continue;
      const payload = parsed.data && typeof parsed.data === "object" ? parsed.data : parsed;
      if (
        payload.generation_mode === "sitcom"
        || payload.schema_version === "sitcom_generation_v1"
        || Array.isArray(payload.episode_scripts)
        || payload.sitcom_bible
      ) return payload;
    }
    return null;
  }

  function sitcomPlainText(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/\\r\\n/g, "\n")
      .replace(/\\n/g, "\n")
      .replace(/\r\n/g, "\n")
      .trim();
  }

  function sitcomEpisodeNumber(item, index) {
    return item?.episode_number ?? item?.episode ?? item?.episode_no ?? item?.number ?? index + 1;
  }

  function sitcomEpisodeTitle(item, index) {
    return sitcomPlainText(item?.title || item?.episode_title || item?.name) || `第 ${sitcomEpisodeNumber(item, index)} 集`;
  }

  function sitcomEpisodeScript(item) {
    return sitcomPlainText(
      item?.script_text
      || item?.final_script
      || item?.script
      || item?.content
      || item?.text
      || ""
    );
  }

  function sitcomReadableText(value) {
    if (window.fieldLabelsCn && typeof window.fieldLabelsCn.readableText === "function") {
      return window.fieldLabelsCn.readableText(value);
    }
    return formatDisplayValue(value);
  }

  function renderSitcomInfoSection(title, value, { open = false } = {}) {
    if (value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length)) return "";
    return `
      <details class="sitcom-info-section" ${open ? "open" : ""}>
        <summary>${escapeHtml(title)}</summary>
        <pre>${escapeHtml(sitcomReadableText(value))}</pre>
      </details>
    `;
  }

  function renderSitcomResult(result) {
    const payload = sitcomResultPayload(result);
    if (!payload) return "";
    const episodes = Array.isArray(payload.episode_scripts) ? payload.episode_scripts : [];
    const batch = payload.batch && typeof payload.batch === "object" ? payload.batch : {};
    const firstEpisode = episodes.length ? sitcomEpisodeNumber(episodes[0], 0) : "";
    const startEpisode = batch.start_episode ?? batch.start ?? firstEpisode;
    const endEpisode = batch.end_episode ?? batch.end ?? (episodes.length ? sitcomEpisodeNumber(episodes[episodes.length - 1], episodes.length - 1) : "");
    const rangeText = startEpisode && endEpisode ? `第 ${startEpisode}-${endEpisode} 集` : `${episodes.length} 集`;
    const quality = payload.quality_report && typeof payload.quality_report === "object" ? payload.quality_report : {};
    const qualityPassed = quality.passed ?? quality.ok ?? payload.ok;

    const episodeHtml = episodes.map((item, index) => {
      const episode = item && typeof item === "object" ? item : { script_text: item };
      const number = sitcomEpisodeNumber(episode, index);
      const title = sitcomEpisodeTitle(episode, index);
      const script = sitcomEpisodeScript(episode);
      const supporting = Object.fromEntries(Object.entries(episode).filter(([key, value]) => (
        !["episode_number", "episode", "episode_no", "number", "title", "episode_title", "name", "script_text", "final_script", "script", "content", "text"].includes(key)
        && value !== null && value !== undefined && value !== ""
      )));
      return `
        <details class="sitcom-episode" ${index === 0 ? "open" : ""}>
          <summary>
            <span class="sitcom-episode-number">${escapeHtml(number)}</span>
            <span class="sitcom-episode-title">${escapeHtml(title)}</span>
            <span class="sitcom-episode-toggle">展开正文</span>
          </summary>
          <div class="sitcom-episode-body">
            ${script ? `<pre class="sitcom-script-text">${escapeHtml(script)}</pre>` : '<p class="sitcom-empty">本集未返回剧本正文。</p>'}
            ${Object.keys(supporting).length ? `
              <details class="sitcom-episode-notes">
                <summary>查看本集提纲与制作信息</summary>
                <pre>${escapeHtml(sitcomReadableText(supporting))}</pre>
              </details>
            ` : ""}
          </div>
        </details>
      `;
    }).join("");

    return `
      <div class="sitcom-result-shell">
        <header class="sitcom-result-head">
          <div>
            <span class="sitcom-kicker">情景剧生成完成</span>
            <h3>${escapeHtml(payload.project_title || result?.title || "未命名情景剧")}</h3>
          </div>
          <div class="sitcom-result-meta">
            <span>${escapeHtml(rangeText)}</span>
            <span>${episodes.length} 个完整剧本</span>
            <span class="${qualityPassed === false ? "is-warning" : "is-ready"}">${qualityPassed === false ? "需要复核" : "可以交付"}</span>
          </div>
        </header>
        <section class="sitcom-episodes-section">
          <div class="sitcom-section-heading">
            <h4>本批分集剧本</h4>
            <p>点击集标题展开或收起正文</p>
          </div>
          <div class="sitcom-episode-list">
            ${episodeHtml || '<p class="sitcom-empty">工作流没有返回 episode_scripts，请检查最终节点输出。</p>'}
          </div>
        </section>
        <section class="sitcom-supporting-section">
          <div class="sitcom-section-heading"><h4>策划与续写资料</h4></div>
          ${renderSitcomInfoSection("情景剧设定总表", payload.sitcom_bible, { open: true })}
          ${renderSitcomInfoSection("整季选题表", payload.season_topic_matrix)}
          ${renderSitcomInfoSection("分集大纲", payload.episode_outlines)}
          ${renderSitcomInfoSection("质量检查", payload.quality_report)}
          ${renderSitcomInfoSection("续写记忆", payload.updated_memory)}
          ${renderSitcomInfoSection("下一批建议", payload.next_batch)}
        </section>
      </div>
    `;
  }

  function isSitcomAsset(asset) {
    return String(asset?.tool_key || "").trim() === "sitcom_generator";
  }

  function sitcomAssetTimestamp(asset) {
    const timestamp = Date.parse(String(asset?.updated_at || asset?.created_at || ""));
    return Number.isFinite(timestamp) ? timestamp : 0;
  }

  function sitcomResultFromAsset(asset) {
    if (!asset || !isSitcomAsset(asset)) return null;
    const artifacts = asset.artifacts && typeof asset.artifacts === "object" ? asset.artifacts : {};
    const output = parseJsonObject(artifacts.tool_output)
      || parseJsonObject(asset.tool_output)
      || parseJsonObject(artifacts.final_output_text)
      || null;
    const text = sitcomPlainText(
      artifacts.final_output_text
      || artifacts.final_script
      || asset.final_output_text
      || ""
    );
    if (!output && !text) return null;
    const requestPayload = asset.tool_request_payload && typeof asset.tool_request_payload === "object"
      ? asset.tool_request_payload
      : {};
    const displayOutput = output || {
      schema_version: "sitcom_generation_v1",
      generation_mode: "sitcom",
      project_title: requestPayload.project_title || String(asset.title || "").replace(/^情景剧生成[｜|]?/, ""),
      batch: {
        start_episode: requestPayload.batch_start_episode || 1,
        end_episode: requestPayload.batch_end_episode || requestPayload.total_episodes || 1,
      },
      episode_scripts: [{
        episode_number: requestPayload.batch_start_episode || 1,
        title: "历史完整结果",
        script_text: text,
      }],
      final_script_text: text,
      ok: true,
    };
    return {
      title: asset.title || "情景剧生成",
      text,
      answer_text: text,
      output: displayOutput,
      outputType: "json",
      filename: artifacts.tool_filename || asset.tool_filename || "情景剧.txt",
      assetSaved: true,
      savedAsset: asset,
      restoredFromAsset: true,
    };
  }

  function applySitcomAssetResult(asset) {
    const result = sitcomResultFromAsset(asset);
    if (!result) return false;
    const payload = asset.tool_request_payload && typeof asset.tool_request_payload === "object"
      ? asset.tool_request_payload
      : {};
    state.toolDrafts.sitcom_generator = {
      ...ensureToolDraft("sitcom_generator"),
      ...payload,
    };
    state.toolResults.sitcom_generator = result;
    return true;
  }

  function restoreLatestSitcomResult() {
    if (state.toolResults.sitcom_generator) return true;
    const latest = [
      ...(Array.isArray(state.assets) ? state.assets : []),
      ...(Array.isArray(state.projects) ? state.projects : []),
    ]
      .filter((asset) => isSitcomAsset(asset))
      .sort((a, b) => sitcomAssetTimestamp(b) - sitcomAssetTimestamp(a))[0];
    return applySitcomAssetResult(latest);
  }

  async function openSitcomAsset(projectId) {
    let asset = [...(state.assets || []), ...(state.projects || [])]
      .find((item) => String(item.project_id) === String(projectId));
    try {
      const data = await requestJson(`/api/projects/${encodeURIComponent(projectId)}`);
      asset = data.project || asset;
    } catch (_) {
      // 详情失败时，列表快照仍可恢复旧记录的正文。
    }
    if (!applySitcomAssetResult(asset)) {
      throw new Error("该情景剧记录没有可恢复的正文。");
    }
    openToolPanel("sitcom_generator");
    renderToolForm("sitcom_generator");
    renderToolOutput("sitcom_generator");
    showToast("已打开情景剧记录", asset?.title || "历史结果已恢复。");
  }

  function characterReskinRunningMessage(index = 0) {
    const safeIndex = Math.max(0, Number(index) || 0) % CHARACTER_RESKIN_RUNNING_MESSAGES.length;
    return [
      CHARACTER_RESKIN_RUNNING_MESSAGES[safeIndex],
      "只换人设会串联多轮人设、对白、正文审核与修订，等待时间可能较长。",
      "当前页面没有卡住，请不要刷新；完成后会自动保存到只换人设资产。"
    ].join("\n");
  }

  function stopToolProgressTicker() {
    if (state.toolProgressTimer) {
      window.clearInterval(state.toolProgressTimer);
      state.toolProgressTimer = null;
    }
  }

  function startToolProgressTicker(toolKey) {
    stopToolProgressTicker();
    state.toolProgressIndex = 0;
    if (toolKey !== "character_reskin") return;
    renderToolOutput(toolKey, characterReskinRunningMessage(state.toolProgressIndex));
    state.toolProgressTimer = window.setInterval(() => {
      state.toolProgressIndex += 1;
      renderToolOutput(toolKey, characterReskinRunningMessage(state.toolProgressIndex));
    }, 9000);
  }


  function downloadTextFile(text, filename) {
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const objectUrl = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename || "tool_output.txt";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 0);
  }

  function activeAuditReportText() {
    const result = currentToolResult("hot_review") || currentToolResult();
    if (!isScriptAuditEcgResult(result)) return "";
    return String(result.view?.export_text || buildAuditExportText(result.audit || {}, {
      points: result.view?.ecg_chart?.points || [],
      dimensions: result.view?.dimension_cards || [],
      episodeCards: result.view?.episode_cards || [],
      globalReview: result.audit?.global_review || {}
    }) || "").trim();
  }

  function activeAuditReportTitle() {
    const result = currentToolResult("hot_review") || currentToolResult();
    const title = auditFirstText(
      result?.audit?.meta?.script_title,
      result?.view?.meta?.script_title,
      result?.script_title,
      result?.savedAsset?.script_title,
      "爆款文"
    );
    const safeTitle = title.replace(/[\\/:*?"<>|]+/g, "_").slice(0, 80) || "爆款文";
    return `${safeTitle}审核结果`;
  }

  async function downloadAuditDocx() {
    const text = activeAuditReportText();
    if (!text) {
      showToast("暂无可导出报告", "请先生成或打开爆款文审核结果。");
      return;
    }
    const authToken = currentAuthToken();
    const response = await fetch("/api/tools/hot_review/export/docx", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {})
      },
      body: JSON.stringify({ title: activeAuditReportTitle(), text })
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.message || data.error || "DOCX 导出失败。");
    }
    const blob = await response.blob();
    const objectUrl = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `${activeAuditReportTitle()}.docx`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 0);
  }

  function loadHtml2Canvas() {
    if (window.html2canvas) return Promise.resolve(window.html2canvas);
    return new Promise((resolve, reject) => {
      const existing = document.querySelector("script[data-html2canvas-loader]");
      if (existing) {
        existing.addEventListener("load", () => resolve(window.html2canvas));
        existing.addEventListener("error", reject);
        return;
      }
      const script = document.createElement("script");
      script.src = "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js";
      script.async = true;
      script.dataset.html2canvasLoader = "1";
      script.onload = () => window.html2canvas ? resolve(window.html2canvas) : reject(new Error("截图组件加载失败。"));
      script.onerror = () => reject(new Error("截图组件加载失败，请检查网络后重试。"));
      document.head.appendChild(script);
    });
  }

  async function saveActiveHotReviewResult(button = null) {
    const current = normalizeScriptAuditEcgResult(currentToolResult("hot_review"));
    if (!current || !isScriptAuditEcgResult(current)) {
      throw new Error("暂无可保存的爆款文审核结果。");
    }
    const savedAsset = current.savedAsset || current.saved_asset || {};
    const assetId = String(
      current.project_id
      || current.saved_asset_id
      || savedAsset.project_id
      || savedAsset.id
      || ""
    ).trim();
    const previousText = button?.textContent || "";
    if (button) {
      button.disabled = true;
      button.textContent = "保存中...";
    }
    try {
      const data = await requestJson("/api/tools/hot_review/save", {
        method: "POST",
        body: JSON.stringify({
          asset_id: assetId,
          saved_asset: savedAsset,
          request_payload: collectToolPayload("hot_review"),
          result: current,
        }),
      });
      const nextResult = normalizeScriptAuditEcgResult({
        ...current,
        ...data,
        ...(data.result || {}),
        assetSaved: true,
        asset_saved: true,
        savedAsset: data.saved_asset || data.result?.saved_asset || savedAsset,
        saved_asset: data.saved_asset || data.result?.saved_asset || savedAsset,
      });
      state.toolResults.hot_review = nextResult;
      persistHotReviewSession(nextResult);
      if (nextResult.savedAsset || nextResult.saved_asset) {
        mergeProjectListAsset(nextResult.savedAsset || nextResult.saved_asset);
      }
      renderToolOutput("hot_review");
      showToast("保存成功", "爆款文审核结果已保存到资产。");
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = previousText || "保存结果到资产";
      }
    }
  }

  async function downloadAuditImage() {
    const shell = document.querySelector(".audit-result-shell");
    if (!shell) {
      showToast("暂无可截图内容", "请先生成或打开爆款文审核结果。");
      return;
    }
    const popovers = [...shell.querySelectorAll("[data-audit-popover]")];
    const previousHidden = popovers.map((item) => item.hidden);
    const triggers = [...shell.querySelectorAll("[data-action='toggle-audit-popover']")];
    const previousExpanded = triggers.map((item) => item.getAttribute("aria-expanded") || "false");
    const previousIcons = triggers.map((item) => item.querySelector("b")?.textContent || "⌄");
    shell.classList.add("audit-exporting");
    popovers.forEach((item) => { item.hidden = false; });
    triggers.forEach((item) => {
      item.setAttribute("aria-expanded", "true");
      const icon = item.querySelector("b");
      if (icon) icon.textContent = "⌃";
    });
    try {
      const html2canvas = await loadHtml2Canvas();
      const canvas = await html2canvas(shell, {
        backgroundColor: "#fffaf1",
        scale: Math.min(2, window.devicePixelRatio || 1.5),
        useCORS: true,
      });
      const link = document.createElement("a");
      link.download = `${activeAuditReportTitle()}_爆款文审核长图.png`;
      link.href = canvas.toDataURL("image/png");
      document.body.appendChild(link);
      link.click();
      link.remove();
    } finally {
      popovers.forEach((item, index) => { item.hidden = previousHidden[index]; });
      triggers.forEach((item, index) => {
        item.setAttribute("aria-expanded", previousExpanded[index] || "false");
        const icon = item.querySelector("b");
        if (icon) icon.textContent = previousIcons[index] || "⌄";
      });
      shell.classList.remove("audit-exporting");
    }
  }

  function renderToolList() {
    if (!els.toolList) return;
    const definitions = Object.values(toolDefinitions()).filter((tool) => tool.key !== "new_framework");
    const toolNavigationMeta = {
      hot_review: { icon: "审", hint: "检查节奏、逻辑与爽点" },
      punchup: { icon: "爽", hint: "增强冲突、节奏与表达" },
      character_reskin: { icon: "人", hint: "保留剧情，只替换人物设定" },
      sitcom_generator: { icon: "剧", hint: "固定人物，每集一个独立故事" }
    };
    els.toolList.innerHTML = definitions.map((tool) => {
      const meta = toolNavigationMeta[tool.key] || {
        icon: "工",
        hint: String(tool.help || "打开并运行该辅助功能").replace(/。.*$/, "")
      };
      const availability = !isAuthenticated()
        ? "需登录"
        : (tool.configured ? "可运行" : "待配置");
      return `
        <button
          class="tool-shortcut${tool.key === state.activeTool ? " active" : ""}"
          type="button"
          data-tool-key="${escapeHtml(tool.key)}"
          aria-pressed="${tool.key === state.activeTool ? "true" : "false"}"
        >
          <span class="tool-shortcut-icon" aria-hidden="true">${escapeHtml(meta.icon)}</span>
          <span class="tool-shortcut-copy">
            <strong>${escapeHtml(tool.label)}</strong>
            <small>${escapeHtml(meta.hint)}</small>
          </span>
          <span class="tool-shortcut-tail">
            <small class="tool-shortcut-availability">${escapeHtml(availability)}</small>
            <b aria-hidden="true">›</b>
          </span>
        </button>
      `;
    }).join("");
  }

  function toolHistoryAssets(toolKey = state.activeTool) {
    const records = new Map();
    [...(state.projects || []), ...(state.assets || [])].forEach((item) => {
      if (String(item?.tool_key || "").trim() !== String(toolKey || "").trim()) return;
      const key = String(item.project_id || item.id || item.task_id || "").trim();
      if (!key) return;
      records.set(key, { ...(records.get(key) || {}), ...item });
    });
    return [...records.values()].sort((a, b) => (
      Date.parse(String(b.updated_at || b.created_at || ""))
      - Date.parse(String(a.updated_at || a.created_at || ""))
    ));
  }

  function toolHistoryTimeLabel(item) {
    const timestamp = Date.parse(String(item?.updated_at || item?.created_at || ""));
    if (!Number.isFinite(timestamp)) return "时间未知";
    return new Date(timestamp).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function renderToolHistory(toolKey = state.activeTool) {
    if (!els.toolHistory || !els.toolHistoryList) return;
    const records = isAuthenticated() ? toolHistoryAssets(toolKey) : [];
    els.toolHistory.classList.toggle("hidden", !isAuthenticated());
    if (els.toolHistoryCount) els.toolHistoryCount.textContent = `${records.length} 条`;
    if (!records.length) {
      els.toolHistoryList.innerHTML = '<p class="tool-history-empty">当前工具还没有生成记录。</p>';
      return;
    }
    els.toolHistoryList.innerHTML = records.slice(0, 12).map((item, index) => `
      <button
        class="tool-history-row"
        type="button"
        data-action="open-tool-history"
        data-tool-key="${escapeHtml(toolKey)}"
        data-project-id="${escapeHtml(item.project_id || item.id)}"
      >
        <span class="tool-history-index">${index + 1}</span>
        <span class="tool-history-copy">
          <strong>${escapeHtml(item.title || toolConfig(toolKey)?.label || "辅助工具结果")}</strong>
          <small>${escapeHtml(toolHistoryTimeLabel(item))}</small>
        </span>
        <span class="tool-history-open">查看</span>
      </button>
    `).join("");
  }

  function genericToolResultFromAsset(asset, toolKey) {
    if (!asset) return null;
    const artifacts = asset.artifacts && typeof asset.artifacts === "object" ? asset.artifacts : {};
    const output = artifacts.tool_output || asset.tool_output || null;
    const text = String(
      artifacts.final_output_text
      || artifacts.final_script
      || asset.final_output_text
      || asset.text
      || ""
    ).trim();
    if (!output && !text) return null;
    return {
      title: asset.title || toolConfig(toolKey)?.label || "辅助工具结果",
      text: text || formatToolOutput(output),
      answer_text: text || formatToolOutput(output),
      output: output || text,
      outputType: output ? "json" : "text",
      filename: artifacts.tool_filename || asset.tool_filename || `${toolConfig(toolKey)?.label || "辅助工具结果"}.txt`,
      assetSaved: true,
      savedAsset: asset,
      restoredFromAsset: true,
    };
  }

  async function openToolHistoryRecord(toolKey, projectId) {
    if (toolKey === "hot_review") {
      await openHotReviewAssetFromList(projectId);
      return;
    }
    if (toolKey === "sitcom_generator") {
      await openSitcomAsset(projectId);
      return;
    }
    let asset = [...(state.assets || []), ...(state.projects || [])]
      .find((item) => String(item.project_id || item.id) === String(projectId));
    try {
      const data = await requestJson(`/api/projects/${encodeURIComponent(projectId)}`);
      asset = data.project || asset;
    } catch (_) {
      // 列表快照包含正文时仍可打开。
    }
    const result = genericToolResultFromAsset(asset, toolKey);
    if (!result) throw new Error("该历史记录没有可展示的结果。");
    const requestPayload = asset?.tool_request_payload && typeof asset.tool_request_payload === "object"
      ? asset.tool_request_payload
      : {};
    state.toolDrafts[toolKey] = { ...ensureToolDraft(toolKey), ...requestPayload };
    state.toolResults[toolKey] = result;
    openToolPanel(toolKey);
    renderToolForm(toolKey);
    renderToolOutput(toolKey);
    showToast("已打开历史记录", asset?.title || "辅助工具结果已恢复。");
  }

  function openCommunityPanel() {
    if (!els.communityPanel) return;
    closeToolPanel();
    els.communityPanel.classList.remove("hidden");
    els.communityPanel.setAttribute("aria-hidden", "false");
    window.requestAnimationFrame(() => {
      els.communityPanel?.classList.add("panel-open");
    });
    updateUrlParams((params) => params.delete("section"));
    if (state.communityStatus === "idle" || (state.communityStatus === "error" && !state.communityAssets.length)) {
      loadCommunity({ resetPage: true }).catch((error) => {
        showToast("社区作品加载失败", friendlyErrorText(error, "请稍后重试。"));
        showStatusError(error, "社区作品加载失败，请稍后重试。");
      });
    }
  }

  function closeCommunityPanel() {
    if (!els.communityPanel || els.communityPanel.classList.contains("hidden")) return;
    els.communityPanel.classList.remove("panel-open");
    window.setTimeout(() => {
      els.communityPanel?.classList.add("hidden");
      els.communityPanel?.setAttribute("aria-hidden", "true");
    }, 180);
  }

  function openToolPanel(toolKey) {
    const tool = toolConfig(toolKey);
    state.activeTool = tool.key;
    if (tool.key === "sitcom_generator" && !state.toolResults.sitcom_generator) {
      restoreLatestSitcomResult();
    }
    closeCommunityPanel();
    if (els.assistantToolsFolder) {
      els.assistantToolsFolder.open = true;
    }
    renderToolList();
    renderToolForm(tool.key);
    els.toolPanel?.classList.remove("hidden");
    window.requestAnimationFrame(() => {
      els.toolPanel?.classList.add("panel-open");
    });
    updateUrlParams((params) => {
      params.set("section", "tools");
      params.set("tool", tool.key);
    });
  }

  function closeToolPanel() {
    if (!els.toolPanel || els.toolPanel.classList.contains("hidden")) return;
    els.toolPanel.classList.remove("panel-open");
    window.setTimeout(() => {
      els.toolPanel?.classList.add("hidden");
    }, 180);
  }

  async function loadTools() {
    state.toolDefinitions = { ...DEFAULT_TOOL_DEFINITIONS };
    if (!isAuthenticated()) {
      renderToolList();
      renderToolForm(state.activeTool);
      return;
    }
    try {
      const data = await requestJson(window.scriptMakerConfig.toolsUrl);
      const merged = { ...DEFAULT_TOOL_DEFINITIONS };
      for (const item of data.tools || []) {
        const normalized = normalizeToolDefinition(item);
        if (!normalized) continue;
        merged[normalized.key] = normalized;
      }
      state.toolDefinitions = merged;
    } catch (_) {
      state.toolDefinitions = { ...DEFAULT_TOOL_DEFINITIONS };
    }
    if (!toolConfig(state.activeTool)) {
      state.activeTool = Object.keys(toolDefinitions())[0] || "hot_review";
    }
    renderToolList();
    renderToolForm(state.activeTool);
  }

  
  /* HOT_REVIEW_FILE_UPLOAD_V1 */
  const HOT_REVIEW_UPLOAD_ALLOWED_EXTENSIONS = new Set([
    "txt",
    "md",
    "json",
    "docx",
    "pdf",
  ]);

  const HOT_REVIEW_UPLOAD_MAX_BYTES = 20 * 1024 * 1024;
  function hotReviewFileExtension(filename) {
    const parts = String(filename || "")
      .toLowerCase()
      .split(".");

    return parts.length > 1
      ? String(parts.pop() || "")
      : "";
  }

  function hotReviewUploadTextField() {
    if (!els.toolForms) return null;

    const preferredNames = [
      "review_text",
      "script_text",
      "script",
      "content",
      "text",
      "input",
    ];

    for (const fieldName of preferredNames) {
      const field = els.toolForms.querySelector(
        `[data-tool-field="${fieldName}"]`
      );

      if (
        field
        && (
          field.tagName === "TEXTAREA"
          || field.tagName === "INPUT"
        )
      ) {
        return field;
      }
    }

    return els.toolForms.querySelector(
      "textarea[data-tool-field]"
    );
  }

  function hotReviewUploadStatusElement() {
    return document.getElementById(
      "hotReviewUploadStatus"
    );
  }

  function setHotReviewUploadStatus(
    message,
    type = "",
  ) {
    const status = hotReviewUploadStatusElement();

    if (!status) return;

    status.textContent = String(message || "");

    if (type) {
      status.dataset.type = type;
    } else {
      delete status.dataset.type;
    }
  }

  function hotReviewUploadErrorMessage(
    error,
    fallback = "文件读取失败。",
  ) {
    const message = String(
      error?.message || ""
    ).trim();

    return message || fallback;
  }

  async function requestHotReviewFileExtraction(
    file,
  ) {
    const formData = new FormData();
    formData.append("file", file, file.name);

    const authToken = currentAuthToken();
    const headers = authToken
      ? {
          Authorization: `Bearer ${authToken}`,
        }
      : {};

    const response = await fetch(
      "/api/tools/hot_review/extract-file",
      {
        method: "POST",
        credentials: "same-origin",
        headers,
        body: formData,
      },
    );

    const raw = await response.text();

    let data = null;

    try {
      data = raw
        ? JSON.parse(raw)
        : null;
    } catch (_) {
      data = null;
    }

    if (response.status === 401) {
      window.location.href = "/login";
      throw new Error("请先登录。");
    }

    if (
      !response.ok
      || !data
      || data.success !== true
    ) {
      throw new Error(
        data?.message
        || `文件解析失败：${response.status}`
      );
    }

    return data;
  }

  function applyHotReviewUploadedText(
    text,
    filename,
  ) {
    const field = hotReviewUploadTextField();

    if (!field) {
      throw new Error(
        "没有找到爆款文审核文本输入框。"
      );
    }

    const normalizedText = String(text || "");
    const normalizedFilename = String(
      filename || ""
    ).trim();

    field.value = normalizedText;
    field.dataset.uploadedFilename =
      normalizedFilename;
    field.dataset.inputSource =
      "uploaded_file";

    const fieldName = String(
      field.dataset.toolField
      || "review_text"
    );

    state.toolDrafts.hot_review = {
      ...(state.toolDrafts.hot_review || {}),
      [fieldName]: normalizedText,
      uploaded_filename: normalizedFilename,
      input_source: "uploaded_file",
    };

    field.dispatchEvent(
      new Event("input", {
        bubbles: true,
      }),
    );

    field.dispatchEvent(
      new Event("change", {
        bubbles: true,
      }),
    );

    field.focus();
    field.setSelectionRange?.(
      0,
      0,
    );
  }

  async function handleHotReviewSelectedFile(
    file,
  ) {
    if (!file) return;

    if (!Number.isFinite(file.size) || file.size <= 0) {
      setHotReviewUploadStatus(
        "文件为空，无法读取。",
        "error",
      );
      return;
    }

    if (file.size > HOT_REVIEW_UPLOAD_MAX_BYTES) {
      setHotReviewUploadStatus(
        "文件超过 20 MB，无法上传。",
        "error",
      );
      return;
    }

    const extension = hotReviewFileExtension(
      file.name
    );

    if (
      !HOT_REVIEW_UPLOAD_ALLOWED_EXTENSIONS.has(
        extension
      )
    ) {
      setHotReviewUploadStatus(
        "暂不支持该格式，请上传 TXT、MD、JSON、DOCX 或 PDF。",
        "error",
      );
      return;
    }

    setHotReviewUploadStatus(
      `正在读取：${file.name}`,
      "loading",
    );

    const card = document.getElementById(
      "hotReviewUploadCard"
    );

    card?.classList.add("is-loading");

    try {
      const data =
        await requestHotReviewFileExtraction(
          file
        );

      const text = String(
        data.text || ""
      ).trim();

      if (!text) {
        throw new Error(
          "没有从文件中提取到可用文字。"
        );
      }

      applyHotReviewUploadedText(
        text,
        data.filename || file.name,
      );

      const characterCount = Number(
        data.char_count || text.length
      ).toLocaleString();

      setHotReviewUploadStatus(
        `已读取 ${data.filename || file.name}，共 ${characterCount} 个字符。可以继续编辑或直接运行审核。`,
        "success",
      );
    } catch (error) {
      console.error(
        "[hot-review-file-upload]",
        error,
      );

      setHotReviewUploadStatus(
        hotReviewUploadErrorMessage(
          error,
          "文件读取失败，请检查文件格式。",
        ),
        "error",
      );
    } finally {
      card?.classList.remove("is-loading");
    }
  }

  function mountHotReviewFileUploader(toolKey) {
    if (
      String(toolKey || "") !== "hot_review"
      || !els.toolForms
    ) {
      return;
    }

    if (
      document.getElementById(
        "hotReviewUploadCard"
      )
    ) {
      return;
    }

    const field = hotReviewUploadTextField();

    if (!field) return;

    const fieldWrapper =
      field.closest(".field")
      || field.parentElement;

    if (
      !fieldWrapper
      || !fieldWrapper.parentElement
    ) {
      return;
    }

    const card = document.createElement(
      "section"
    );

    card.id = "hotReviewUploadCard";
    card.className =
      "hot-review-upload-card";

    card.innerHTML = `
      <input
        id="hotReviewFileInput"
        class="hot-review-file-input"
        type="file"
        accept=".txt,.md,.json,.docx,.pdf,text/plain,text/markdown,application/json,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/pdf"
      />

      <div
        id="hotReviewDropzone"
        class="hot-review-dropzone"
        role="button"
        tabindex="0"
        aria-label="拖拽或选择剧本文件"
      >
        <div class="hot-review-dropzone-copy">
          <strong>拖拽剧本文件到这里</strong>
          <span>
            支持 TXT、MD、JSON、DOCX、PDF，最大 20 MB
          </span>
          <span>
            文件读取后会自动填入下方剧本文本框，仍可手动修改
          </span>
        </div>

        <button
          id="hotReviewChooseFileBtn"
          class="btn btn-secondary hot-review-choose-file-btn"
          type="button"
        >
          选择本地文件
        </button>
      </div>

      <div
        id="hotReviewUploadStatus"
        class="hot-review-upload-status"
        aria-live="polite"
      ></div>
    `;

    fieldWrapper.parentElement.insertBefore(
      card,
      fieldWrapper,
    );

    const fileInput = card.querySelector(
      "#hotReviewFileInput"
    );

    const dropzone = card.querySelector(
      "#hotReviewDropzone"
    );

    const chooseButton = card.querySelector(
      "#hotReviewChooseFileBtn"
    );

    const openFileDialog = () => {
      if (!fileInput) return;
      fileInput.value = "";
      fileInput.click();
    };

    chooseButton?.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopPropagation();
        openFileDialog();
      },
    );

    dropzone?.addEventListener(
      "click",
      (event) => {
        if (
          event.target.closest(
            "#hotReviewChooseFileBtn"
          )
        ) {
          return;
        }

        openFileDialog();
      },
    );

    dropzone?.addEventListener(
      "keydown",
      (event) => {
        if (
          event.key !== "Enter"
          && event.key !== " "
        ) {
          return;
        }

        event.preventDefault();
        openFileDialog();
      },
    );

    fileInput?.addEventListener(
      "change",
      async () => {
        const file = fileInput.files?.[0];

        await handleHotReviewSelectedFile(
          file,
        );

        fileInput.value = "";
      },
    );

    const preventDragDefaults = (event) => {
      event.preventDefault();
      event.stopPropagation();
    };

    for (const eventName of [
      "dragenter",
      "dragover",
    ]) {
      dropzone?.addEventListener(
        eventName,
        (event) => {
          preventDragDefaults(event);
          event.dataTransfer.dropEffect =
            "copy";
          dropzone.classList.add(
            "is-dragging"
          );
        },
      );
    }

    dropzone?.addEventListener(
      "dragleave",
      (event) => {
        preventDragDefaults(event);

        if (
          !dropzone.contains(
            event.relatedTarget
          )
        ) {
          dropzone.classList.remove(
            "is-dragging"
          );
        }
      },
    );

    dropzone?.addEventListener(
      "drop",
      async (event) => {
        preventDragDefaults(event);

        dropzone.classList.remove(
          "is-dragging"
        );

        const files = [
          ...(event.dataTransfer?.files || []),
        ];

        if (!files.length) return;

        if (files.length > 1) {
          setHotReviewUploadStatus(
            "一次只能上传一个剧本文件。",
            "error",
          );
          return;
        }

        await handleHotReviewSelectedFile(
          files[0]
        );
      },
    );
  }

function renderToolForm(toolKey) {
    if (!els.toolForms) return;
    const tool = toolConfig(toolKey);
    state.activeTool = tool.key;
    const toolDraft = ensureToolDraft(tool.key);
    if (els.toolPanelTitle) {
      els.toolPanelTitle.textContent = tool.label;
    }
    els.toolForms.innerHTML = `
      <div class="tool-form-head">
        <p>${escapeHtml(tool.help)}</p>
        ${tool.jsonFile ? `<small class="tool-form-meta">工作流：${escapeHtml(tool.jsonFile)}</small>` : ""}
        ${tool.key === "character_reskin" ? `
          <div class="tool-linked-actions" aria-label="只换人设后续辅助工具">
            <button class="btn btn-secondary" type="button" disabled>爆款文审核（暂未接入）</button>
            <button class="btn btn-secondary" type="button" disabled>增加爽感（暂未接入）</button>
          </div>
        ` : ""}
      </div>
        <div class="tool-field-grid">
        ${tool.fields.map((field) => {
          const fieldValue = toolDraft[field.name] ?? "";
          if (field.type === "textarea") {
            return `
              <label class="field tool-field wide-field">
                <span>${escapeHtml(field.label)}${field.required ? " *" : ""}</span>
                <textarea data-tool-field="${escapeHtml(field.name)}" placeholder="${escapeHtml(field.placeholder)}">${escapeHtml(fieldValue)}</textarea>
              </label>
            `;
          }
          return `
            <label class="field tool-field">
              <span>${escapeHtml(field.label)}${field.required ? " *" : ""}</span>
              <input data-tool-field="${escapeHtml(field.name)}" type="${escapeHtml(field.type === "number" ? "number" : "text")}" placeholder="${escapeHtml(field.placeholder)}" value="${escapeHtml(fieldValue)}">
            </label>
          `;
        }).join("")}
      </div>
    `;
    mountHotReviewFileUploader(tool.key);
    if (els.runToolBtn) {
      els.runToolBtn.disabled = !isAuthenticated() || !tool.configured;
      els.runToolBtn.textContent = !isAuthenticated()
        ? "登录后可运行"
        : (tool.configured ? `运行${tool.label}` : `${tool.label} 待配置`);
    }
    renderToolOutput(
      tool.key,
      !isAuthenticated()
        ? "登录后可使用辅助工具。"
        : (tool.configured
          ? "这里会显示辅助工具结果。"
          : "当前工具还未配置 API Key，配置后即可运行。")
    );
    renderToolHistory(tool.key);
    syncButtons();
  }

  
  function collectToolPayload(toolKey = state.activeTool) {
    const tool = toolConfig(toolKey);
    const allowedFields = new Set((tool?.fields || []).map((field) => String(field.name || "")));
    const payload = {};

    (els.toolForms || document)
      .querySelectorAll("[data-tool-field]")
      .forEach((field) => {
        const key = field.dataset.toolField;
        if (!allowedFields.has(key)) return;

        payload[key] = field.type === "number"
          ? Number(field.value || 0)
          : String(field.value || "").trim();
      });

    if (toolKey === "hot_review") {
      const textField =
        hotReviewUploadTextField();

      const uploadedFilename = String(
        textField?.dataset.uploadedFilename
        || state.toolDrafts.hot_review
          ?.uploaded_filename
        || ""
      ).trim();

      if (uploadedFilename) {
        payload.uploaded_filename =
          uploadedFilename;
        payload.input_source =
          "uploaded_file";
      } else {
        payload.input_source =
          "manual_text";
      }
    }

    return payload;
  }


  function openProfilePanel() {
    if (!requireLogin()) return;
    els.profilePanel?.classList.remove("hidden");
    els.profilePanel?.setAttribute("aria-hidden", "false");
    window.requestAnimationFrame(() => {
      els.profilePanel?.classList.add("panel-open");
    });
    updateUrlParams((params) => params.set("panel", "profile"));
    loadAssets({ resetPage: true }).catch((error) => {
      showStatusError(error, "个人中心加载失败，请稍后重试。");
    });
  }

  function closeProfilePanel() {
    if (!els.profilePanel || els.profilePanel.classList.contains("hidden")) return;
    els.profilePanel.classList.remove("panel-open");
    window.setTimeout(() => {
      els.profilePanel?.classList.add("hidden");
      els.profilePanel?.setAttribute("aria-hidden", "true");
    }, 180);
    closeAssetEditor();
    updateUrlParams((params) => params.delete("panel"));
  }

  async function requestJson(url, options = {}) {
    const authToken = currentAuthToken();
    const timeoutMs = Number(options.timeoutMs || 0);
    const controller = timeoutMs > 0 ? new AbortController() : null;
    const timeoutId = controller
      ? window.setTimeout(() => controller.abort(), timeoutMs)
      : null;
    const { timeoutMs: _timeoutMs, signal: optionSignal, headers: optionHeaders, ...fetchOptions } = options;
    if (controller && optionSignal) {
      optionSignal.addEventListener?.("abort", () => controller.abort(), { once: true });
    }
    const response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        ...(optionHeaders || {})
      },
      ...fetchOptions,
      ...(controller ? { signal: controller.signal } : {})
    }).finally(() => {
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    });
    const data = await response.json().catch(() => null);
    if (response.status === 401) {
      window.location.href = "/login";
      throw new Error("请先登录。");
    }
    if (!response.ok || !data?.success) {
      const error = new Error(data?.message || `请求失败：${response.status}`);
      error.status = response.status;
      error.payload = data;
      throw error;
    }
    return data;
  }

  function selectedKnowledgeTags() {
    const selected = new Set(state.selectedKnowledgeTagIds);
    return state.knowledgeTags.filter((tag) => selected.has(String(tag.id || "")));
  }

  function userKnowledgePayload() {
    const tags = selectedKnowledgeTags().map((tag) => ({
      id: String(tag.id || ""),
      name: String(tag.name || ""),
      category: String(tag.category || ""),
      builtin: Boolean(tag.builtin),
      group: String(tag.group || ""),
      group_label: String(tag.group_label || ""),
      source: String(tag.source || ""),
      type: String(tag.type || ""),
      is_default: Boolean(tag.is_default),
      is_user_editable: tag.is_user_editable !== false,
      pinned: Boolean(tag.pinned),
      description: String(tag.description || ""),
      prompt_text: String(tag.prompt_text || ""),
      stage_prompts: normalizeKnowledgeStagePrompts(tag.stage_prompts || {})
    }));
    const stagePrompts = mergeSelectedKnowledgeStagePrompts(tags);
    return {
      selected_preference_tag_ids: [...state.selectedKnowledgeTagIds],
      selected_preference_tags: tags,
      user_preference_prompt: String(els.userPreferenceInput?.value || ""),
      user_knowledge_tag_prompt: String(state.userKnowledgeTagPrompt || ""),
      user_knowledge_stage_prompts: stagePrompts,
      prompt_preferences: {
        stage_prompts: stagePrompts
      }
    };
  }

  function normalizeKnowledgeStagePrompts(value) {
    const source = value && typeof value === "object" && !Array.isArray(value) ? value : {};
    return {
      basic: String(source.basic || ""),
      worldview: String(source.worldview || ""),
      character: String(source.character || ""),
      beat: String(source.beat || ""),
      storylines: String(source.storylines || ""),
      guide: String(source.guide || ""),
      package: String(source.package || ""),
      scene: String(source.scene || ""),
      appearance: String(source.appearance || ""),
      episode: String(source.episode || ""),
      conflict: String(source.conflict || ""),
      script_text: String(source.script_text || "")
    };
  }

  function mergeSelectedKnowledgeStagePrompts(tags) {
    const result = normalizeKnowledgeStagePrompts({});
    (tags || []).forEach((tag) => {
      const name = String(tag.name || tag.id || "").trim();
      const prompts = normalizeKnowledgeStagePrompts(tag.stage_prompts || {});
      Object.keys(result).forEach((stageKey) => {
        const text = String(prompts[stageKey] || "").trim();
        if (!text) return;
        const section = `【智慧库标签偏好：${name}】\n${text}`;
        result[stageKey] = result[stageKey] ? `${result[stageKey]}\n\n${section}` : section;
      });
    });
    return result;
  }

  function knowledgeTagGroup(tag) {
    const group = String((tag && tag.group) || "").trim();
    if (group) return group;
    if (String((tag && tag.id) || "").startsWith("excellent_film_beat_") || String((tag && tag.source) || "") === "save_the_cat_film_beat") return "excellent_film_beat";
    return tag && tag.builtin ? "default_style" : "user_custom";
  }

  function groupedKnowledgeTags(tags) {
    return [
      { id: "default_style", label: "默认风格分类" },
      { id: "user_custom", label: "用户自定义标签" },
      { id: "excellent_film_beat", label: "优秀电影节拍表标签" }
    ].map((group) => Object.assign({}, group, {
      tags: (tags || []).filter((tag) => knowledgeTagGroup(tag) === group.id)
    }));
  }

  function attachUserKnowledgePayload(payload) {
    Object.assign(payload, userKnowledgePayload());
    console.debug(`[user-knowledge] selected tags count=${state.selectedKnowledgeTagIds.length}`);
    return payload;
  }

  function renderUserKnowledgePanel() {
    if (!els.userKnowledgePanel) return;
    const selected = new Set(state.selectedKnowledgeTagIds);
    const tags = Array.isArray(state.knowledgeTags) ? state.knowledgeTags : [];
    if (els.knowledgeTagStatus) {
      els.knowledgeTagStatus.textContent = state.userKnowledgeError
        ? state.userKnowledgeError
        : (tags.length ? `已加载 ${tags.length} 个标签，可不选择。` : "暂无可用标签，可直接创作。");
    }
    if (els.knowledgeTagList) {
      const renderTag = (tag) => {
        const id = String(tag.id || "");
        const checked = selected.has(id);
        const customActions = tag.builtin ? "" : `
          <button class="knowledge-pin-btn" type="button" data-action="pin-knowledge-tag" data-tag-id="${escapeHtml(id)}" title="${tag.pinned ? "取消置顶" : "置顶自定义标签"}">${tag.pinned ? "已置顶" : "置顶"}</button>
          <button class="knowledge-delete-btn" type="button" data-action="delete-knowledge-tag" data-tag-id="${escapeHtml(id)}" title="删除自定义标签">×</button>
        `;
        return `
          <label class="knowledge-tag-pill${checked ? " is-selected" : ""}" title="${escapeHtml(tag.description || tag.prompt_text || "")}">
            <input type="checkbox" data-knowledge-tag-id="${escapeHtml(id)}" ${checked ? "checked" : ""}>
            <span>${escapeHtml(tag.name || id)}</span>
            <small>${escapeHtml(tag.category || "")}</small>
            ${customActions}
          </label>
        `;
      };
      els.knowledgeTagList.innerHTML = groupedKnowledgeTags(tags).map((group) => `
        <details class="knowledge-tag-group" open>
          <summary>${escapeHtml(group.label)}（${group.tags.length}）</summary>
          ${group.tags.length ? group.tags.map(renderTag).join("") : `<div class="empty-hint">暂无标签</div>`}
        </details>
      `).join("");
    }
    const selectedNames = selectedKnowledgeTags().map((tag) => tag.name || tag.id).filter(Boolean);
    if (els.selectedKnowledgeTags) {
      els.selectedKnowledgeTags.textContent = selectedNames.length
        ? `当前已选择：${selectedNames.join("、")}`
        : "当前未选择标签";
    }
    if (els.knowledgePreferencePreview) {
      const preview = String(els.userPreferenceInput?.value || "").trim();
      els.knowledgePreferencePreview.textContent = preview;
      els.knowledgePreferencePreview.classList.toggle("hidden", !preview);
    }
  }

  async function loadUserKnowledgeTags() {
    if (!isAuthenticated()) {
      state.knowledgeTags = [];
      renderUserKnowledgePanel();
      return;
    }
    try {
      const data = await requestJson("/api/user-knowledge/tags");
      state.knowledgeTags = Array.isArray(data.tags) ? data.tags : [];
      state.userKnowledgeError = "";
    } catch (error) {
      state.knowledgeTags = [];
      state.userKnowledgeError = "智慧库标签加载失败，不影响本次创作。";
      showStatusError(error, "智慧库标签加载失败，不影响本次创作。");
    }
    renderUserKnowledgePanel();
  }

  async function applyUserKnowledgeTags() {
    const existingPreference = String(els.userPreferenceInput?.value || "");
    try {
      const data = await requestJson("/api/user-knowledge/apply-tags", {
        method: "POST",
        body: JSON.stringify({
          selected_tag_ids: [...state.selectedKnowledgeTagIds],
          existing_user_preference: existingPreference
        })
      });
      if (els.userPreferenceInput) {
        els.userPreferenceInput.value = String(data.merged_preference_prompt || "");
      }
      state.userKnowledgeTagPrompt = String(data.tag_prompt_text || "");
      saveDraft();
      renderUserKnowledgePanel();
      showToast("智慧库标签已应用", "本次用户偏好已更新。");
    } catch (error) {
      if (els.userPreferenceInput) {
        els.userPreferenceInput.value = existingPreference;
      }
      showToast("智慧库标签应用失败", friendlyErrorText(error, "已保留原用户偏好。"));
      showStatusError(error, "智慧库标签应用失败，已保留原用户偏好。");
    }
  }

  async function createUserKnowledgeTag() {
    const payload = {
      name: els.knowledgeTagNameInput?.value || "",
      category: els.knowledgeTagCategoryInput?.value || "",
      description: els.knowledgeTagDescriptionInput?.value || "",
      prompt_text: els.knowledgeTagPromptInput?.value || ""
    };
    if (!String(payload.name || "").trim()) {
      showToast("无法新增标签", "请填写标签名称。");
      return;
    }
    try {
      const data = await requestJson("/api/user-knowledge/tags", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      const tag = data.tag;
      if (tag?.id) {
        state.knowledgeTags.push(tag);
        state.selectedKnowledgeTagIds = [...new Set([...state.selectedKnowledgeTagIds, String(tag.id)])];
      }
      [els.knowledgeTagNameInput, els.knowledgeTagCategoryInput, els.knowledgeTagDescriptionInput, els.knowledgeTagPromptInput]
        .filter(Boolean)
        .forEach((input) => {
          input.value = "";
        });
      saveDraft();
      renderUserKnowledgePanel();
      showToast("标签已新增", "自定义标签已保存。");
    } catch (error) {
      showToast("新增标签失败", friendlyErrorText(error, "请稍后重试。"));
      showStatusError(error, "新增标签失败，请稍后重试。");
    }
  }

  async function deleteUserKnowledgeTag(tagId) {
    if (!tagId) return;
    try {
      await requestJson(`/api/user-knowledge/tags/${encodeURIComponent(tagId)}`, { method: "DELETE" });
      state.knowledgeTags = state.knowledgeTags.filter((tag) => String(tag.id || "") !== String(tagId));
      state.selectedKnowledgeTagIds = state.selectedKnowledgeTagIds.filter((id) => id !== String(tagId));
      saveDraft();
      renderUserKnowledgePanel();
      showToast("标签已删除", "自定义标签已移除。");
    } catch (error) {
      showToast("删除标签失败", friendlyErrorText(error, "请稍后重试。"));
      showStatusError(error, "删除标签失败，请稍后重试。");
    }
  }

  async function toggleUserKnowledgeTagPinned(tagId) {
    if (!tagId) return;
    const tag = state.knowledgeTags.find((item) => String(item.id || "") === String(tagId));
    if (!tag || tag.builtin) return;
    try {
      const data = await requestJson(`/api/user-knowledge/tags/${encodeURIComponent(tagId)}`, {
        method: "PATCH",
        body: JSON.stringify({ pinned: !Boolean(tag.pinned) })
      });
      state.knowledgeTags = state.knowledgeTags
        .map((item) => String(item.id || "") === String(tagId) ? data.tag : item)
        .sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)));
      renderUserKnowledgePanel();
    } catch (error) {
      showToast("置顶标签失败", friendlyErrorText(error, "请稍后重试。"));
      showStatusError(error, "置顶标签失败，请稍后重试。");
    }
  }

  async function loadModels() {
    if (!isAuthenticated()) {
      state.availableModels = [];
      els.modelSelect.innerHTML = `<option value="">登录后选择模型</option>`;
      els.modelSelect.disabled = true;
      syncButtons();
      return;
    }
    const data = await requestJson(window.scriptMakerConfig.modelsUrl);
    state.availableModels = data.models || [];
    const availableModels = state.availableModels.filter((item) => item.configured !== false);
    const cachedModelId = draftStorage.getItem(STORAGE.modelId) || "";
    els.modelSelect.innerHTML = state.availableModels.map((item) => {
      const disabled = item.configured === false ? " disabled" : "";
      return `<option value="${escapeHtml(item.id)}"${disabled}>${escapeHtml(item.label)}</option>`;
    }).join("");

    const defaultModel = availableModels.find((item) => item.id === cachedModelId)
      || availableModels.find((item) => item.is_default)
      || availableModels[0]
      || state.availableModels[0];

    if (defaultModel) {
      els.modelSelect.value = defaultModel.id;
    }
    els.modelSelect.disabled = availableModels.length === 0;
    syncButtons();
  }

  // framework 起步只依赖网页上的 3 个用户输入；
  // story_outline / character_bios / core_scene_input / episode_plan
  // 都是 framework 的输出，不应该再伪装成“空输入”传给后端。
  function buildPayload() {
    const expectation = String(els.expectationInput.value || "").trim() || fallbackExpectationForRestart();
    const modelSelectionId = selectedModelId();
    const scriptFormatMode = selectedScriptFormatMode();
    const payload = {
      user_expectation: expectation,
      character_count: Number(els.characterCountInput.value || 0),
      episode_word_count: 600,
      total_episodes: Number(els.episodeCountInput.value || 0),
      title: "",
      model_selection_id: modelSelectionId
    };

    if (!payload.user_expectation) throw new Error("请填写想要的剧本。");
    if (payload.character_count <= 0) throw new Error("角色数量必须大于 0。");
    if (payload.total_episodes <= 0) throw new Error("总集数必须大于 0。");
    if (!payload.model_selection_id) throw new Error("当前没有可用模型，请先完成 .env 配置。");
    if (scriptFormatMode) {
      payload.script_format_mode = scriptFormatMode;
    }
    attachUserKnowledgePayload(payload);
    return payload;
  }

  // 把后台项目压成简洁任务列表，方便在同一账号下快速切换工作台。
  function renderProjectList(projects) {
    if (!els.completedProjectList) return;
    if (!isAuthenticated()) {
      const message = emptyCard("登录后查看任务");
      if (els.activeProjectList) els.activeProjectList.innerHTML = "";
      els.completedProjectList.innerHTML = message;
      if (els.newScriptProjectList) els.newScriptProjectList.innerHTML = message;
      if (els.waibaoProjectList) els.waibaoProjectList.innerHTML = message;
      if (els.characterReskinProjectList) els.characterReskinProjectList.innerHTML = message;
      const hotReviewProjectList = ensureHotReviewProjectList();
      if (hotReviewProjectList) hotReviewProjectList.innerHTML = message;
      setHotReviewProjectCount(0);
      if (els.activeProjectCount) els.activeProjectCount.textContent = "0";
      if (els.completedProjectCount) els.completedProjectCount.textContent = "0";
      return;
    }

    const hotReviewProjects = hotReviewUniqueAssets([...(Array.isArray(projects) ? projects : []), ...(Array.isArray(state.assets) ? state.assets : [])]);
    const frameworkProjects = projects.filter((item) => assetCategory(item) === "framework" && !isHotReviewAsset(item));
    const newScriptProjects = projects.filter((item) => assetCategory(item) === "new_script" && !isHotReviewAsset(item));
    const waibaoProjects = projects.filter((item) => assetCategory(item) === "waibao" && !isHotReviewAsset(item));
    const characterReskinProjects = projects.filter((item) => assetCategory(item) === "character_reskin" && !isHotReviewAsset(item));

    const renderCompactItems = (items, emptyMessage) => {
      if (!items.length) {
        return `<div class="workspace-empty">${escapeHtml(emptyMessage)}</div>`;
      }
      return items.map((item) => {
        const activeClass = Number(item.project_id) === Number(state.projectId) ? " active" : "";
        const statusClass = item.status === "failed"
          ? " failed"
          : item.status === "completed"
            ? " completed"
            : "";
        const progress = Math.max(0, Math.min(100, Number(item.progress_percent || 0)));
        const stageLabel = item.current_stage_label || statusLabel(item.status);
        return `
          <div class="workspace-pick-row" style="--asset-progress: ${progress}%;">
            <button
              class="workspace-pick${activeClass}${statusClass}"
              type="button"
              data-action="${isSitcomAsset(item) ? "open-sitcom-asset" : "select-project"}"
              data-project-id="${escapeHtml(item.project_id)}"
              title="${escapeHtml(projectTooltip(item))}"
            >
              <span class="workspace-pick-main">
                <span class="workspace-pick-title">${escapeHtml(projectDisplayTitle(item))}</span>
                <span class="workspace-pick-meta">${escapeHtml(`${progress}% · ${stageLabel}`)}</span>
              </span>
              <span class="workspace-pick-state">${escapeHtml(statusLabel(item.status))}</span>
              <span class="workspace-pick-progress" role="progressbar" aria-label="项目进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}">
                <span class="workspace-pick-progress-bar"></span>
              </span>
            </button>
            <button
              class="btn btn-danger workspace-pick-delete"
              type="button"
              data-action="delete-asset"
              data-project-id="${escapeHtml(item.project_id)}"
              aria-label="${escapeHtml(`删除 ${projectDisplayTitle(item)}`)}"
              title="${escapeHtml(`删除 ${projectDisplayTitle(item)}`)}"
            >删除</button>
          </div>
        `;
      }).join("");
    };

    if (els.activeWorkspaceFolder) els.activeWorkspaceFolder.remove();
    els.completedProjectList.innerHTML = renderCompactItems(frameworkProjects, "当前还没有框架资产。");
    if (els.newScriptProjectList) {
      els.newScriptProjectList.innerHTML = renderCompactItems(newScriptProjects, "当前还没有新剧本平台资产。");
    }
    if (els.waibaoProjectList) {
      els.waibaoProjectList.innerHTML = renderCompactItems(waibaoProjects, "当前还没有外包格式专属资产。");
    }
    if (els.characterReskinProjectList) {
      els.characterReskinProjectList.innerHTML = renderCompactItems(characterReskinProjects, "当前还没有只换人设资产。");
    }
    const hotReviewProjectList = ensureHotReviewProjectList();
    if (hotReviewProjectList) {
      hotReviewProjectList.innerHTML = renderHotReviewCompactItems(hotReviewProjects, "当前还没有爆款文审核资产。");
    }
    setHotReviewProjectCount(hotReviewProjects.length);
    if (els.activeProjectCount) {
      els.activeProjectCount.textContent = "0";
    }
    if (els.completedProjectCount) {
      els.completedProjectCount.textContent = String(frameworkProjects.length);
    }
  }

  function workspaceFolders() {
    return [
      els.completedWorkspaceFolder,
      document.getElementById("hotReviewProjectList")?.closest("details"),
      els.newScriptProjectList?.closest("details"),
      els.waibaoProjectList?.closest("details"),
      els.characterReskinProjectList?.closest("details")
    ].filter(Boolean);
  }

  function cancelWorkspaceAutoCollapse() {
    if (state.workspaceCollapseTimer) {
      window.clearTimeout(state.workspaceCollapseTimer);
      state.workspaceCollapseTimer = null;
    }
  }

  function collapseWorkspaceFolders() {
    workspaceFolders().forEach((folder) => {
      folder.open = false;
    });
  }

  function scheduleWorkspaceAutoCollapse() {
    cancelWorkspaceAutoCollapse();
    if (!workspaceFolders().some((folder) => folder.open)) {
      return;
    }
    state.workspaceCollapseTimer = window.setTimeout(() => {
      collapseWorkspaceFolders();
      state.workspaceCollapseTimer = null;
    }, 10000);
  }

  async function loadProjectDetail(projectId, { restoreInputs = false, scroll = false } = {}) {
    closeCommunityPanel();
    const data = await requestJson(`/api/projects/${projectId}`);
    const project = data.project || null;
    if (!project) {
      persistSelectedProjectId(null);
      renderSnapshot(null);
      return null;
    }
    if (restoreInputs) {
      restoreInputPayload(project.input_payload, { force: true });
    }
    persistSelectedProjectId(project.project_id);
    renderSnapshot(project);
    if (scroll) {
      document.querySelector(".workspace-runtime")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    return project;
  }

  async function loadProjects({ restoreSelection = true, restoreInputs = false } = {}) {
    if (!isAuthenticated()) {
      state.projects = [];
      renderProjectList([]);
      renderSnapshot(null);
      return [];
    }

    const data = await requestJson(window.scriptMakerConfig.projectsUrl);
    state.projects = data.projects || [];
    summarizeProjectStatusChanges(state.projects);
    renderProjectList(state.projects);

    const freshWorkspace = isFreshWorkspaceMode();
    let targetProjectId = restoreSelection
      ? (state.projectId || readSelectedProjectId() || null)
      : state.projectId;

    if (targetProjectId && !state.projects.some((item) => Number(item.project_id) === Number(targetProjectId))) {
      targetProjectId = null;
    }

    if (targetProjectId) {
      const shouldRestoreInputs = restoreInputs || Number(targetProjectId) !== Number(state.projectId);
      await loadProjectDetail(targetProjectId, { restoreInputs: shouldRestoreInputs });
    } else {
      if (!freshWorkspace) {
        persistSelectedProjectId(null);
      }
      renderSnapshot(null);
    }
    return state.projects;
  }

  function mergeProjectListAsset(asset) {
    if (!asset || typeof asset !== "object") return;
    const key = String(asset.project_id || asset.id || hotReviewAssetKeyV5(asset) || "").trim();
    if (!key) return;
    const projects = Array.isArray(state.projects) ? state.projects.slice() : [];
    const index = projects.findIndex((item) => String(item.project_id || item.id || hotReviewAssetKeyV5(item) || "") === key);
    if (index >= 0) {
      projects[index] = { ...projects[index], ...asset };
    } else {
      projects.unshift(asset);
    }
    state.projects = projects;
    renderProjectList(state.projects);
  }

  function hotReviewAssetTimestampMs(asset) {
    const raw = asset?.updated_at
      || asset?.updatedAt
      || asset?.created_at
      || asset?.createdAt
      || asset?.saved_at
      || asset?.savedAt
      || "";
    const timestamp = Date.parse(String(raw || ""));
    return Number.isFinite(timestamp) ? timestamp : 0;
  }

  function hotReviewKnownAssetKeys() {
    return new Set(
      (Array.isArray(state.assets) ? state.assets : [])
        .filter((item) => isHotReviewAsset(item))
        .map((item) => hotReviewAssetKey(item) || hotReviewAssetKeyV5(item) || hotReviewAssetTitle(item))
        .filter(Boolean)
        .map(String)
    );
  }

  function pickFreshHotReviewAsset(assets, { startedAtMs = 0, knownKeys = new Set() } = {}) {
    const cutoff = Math.max(0, Number(startedAtMs || 0) - HOT_REVIEW_RESULT_POLL_GRACE_MS);
    return hotReviewUniqueAssetsV5(assets)
      .filter((asset) => {
        const key = String(hotReviewAssetKey(asset) || hotReviewAssetKeyV5(asset) || hotReviewAssetTitle(asset) || "");
        const timestamp = hotReviewAssetTimestampMs(asset);
        if (timestamp && timestamp < cutoff) return false;
        if (!timestamp && key && knownKeys.has(key)) return false;
        const result = toolResultFromAsset(asset);
        return isScriptAuditEcgResult(result);
      })
      .sort((a, b) => hotReviewAssetTimestampMs(b) - hotReviewAssetTimestampMs(a))[0] || null;
  }

  function applyHotReviewAssetResult(asset, { toast = false } = {}) {
    if (!asset) return false;
    const result = toolResultFromAsset(asset);
    if (!isScriptAuditEcgResult(result)) return false;
    state.toolResults.hot_review = result;
    persistHotReviewSession(result);
    mergeProjectListAsset(asset);
    stopToolProgressTicker();
    renderToolOutput("hot_review");
    if (toast) {
      showToast("爆款文审核已完成", "已自动同步后端保存的可视化结果。");
    }
    return true;
  }

  function startHotReviewResultPolling({ startedAtMs = Date.now(), knownKeys = new Set() } = {}) {
    let stopped = false;
    let inFlight = false;
    let notified = false;
    const tick = async () => {
      if (stopped || inFlight || !isAuthenticated()) return;
      inFlight = true;
      try {
        const data = await requestJson(window.scriptMakerConfig.assetsUrl);
        const assets = Array.isArray(data.assets) ? data.assets : [];
        state.assets = assets;
        state.assetsStatus = assets.length ? "success" : "empty";
        renderAssets(state.assets);
        const asset = pickFreshHotReviewAsset(assets, { startedAtMs, knownKeys });
        if (asset && applyHotReviewAssetResult(asset, { toast: !notified })) {
          notified = true;
          stopped = true;
          window.clearInterval(timer);
        }
      } catch (error) {
        console.warn("[hot-review-poll]", error);
      } finally {
        inFlight = false;
      }
    };
    const timer = window.setInterval(tick, HOT_REVIEW_RESULT_POLL_INTERVAL_MS);
    window.setTimeout(tick, 3000);
    return {
      stop() {
        stopped = true;
        window.clearInterval(timer);
      }
    };
  }

  function shouldContinuePolling() {
    return state.projects.some((item) => RUNNING_STATUSES.has(item.status));
  }

  // 新建任务或在原资产 ID 上重新启动失败任务。
  async function startGeneration() {
    if (!requireLogin()) return;
    closeCommunityPanel();
    saveDraft();
    const payload = buildPayload();
    const restartingCurrentProject = Boolean(
      isRestartingCurrentProject()
    );
    els.formHint.textContent = restartingCurrentProject
      ? "正在基于当前资产重新开始生成。"
      : "当前流程：写剧本正文。正在创建任务，结果会保存到项目列表。";
    const endpoint = restartingCurrentProject
      ? `/api/projects/${state.projectId}/restart`
      : window.scriptMakerConfig.startUrl;
    const data = await requestJson(endpoint, {
      method: "POST",
      body: JSON.stringify(payload)
    });
    await loadProjects({ restoreSelection: false, restoreInputs: false });
    await loadProjectDetail(data.task.project_id, { restoreInputs: false });
    els.expectationInput.value = "";
    syncExpectationInputHeight();
    saveDraft();
    startPolling();
    els.formHint.textContent = restartingCurrentProject
      ? "当前资产已在原 ID 下重新开始生成。"
      : "新任务已启动。";
    showToast(
      restartingCurrentProject ? "已重新开始生成" : "任务已启动",
      restartingCurrentProject ? "当前资产正在原项目下继续生成。" : "主流程已经开始执行。"
    );
  }

  async function pauseTask() {
    if (!requireLogin()) return;
    if (!state.taskId) return;
    const data = await requestJson(`/api/tasks/${state.taskId}/pause`, { method: "POST" });
    renderSnapshot(data.task);
    await loadProjects({ restoreSelection: true, restoreInputs: false });
    startPolling();
    showToast("已发出暂停请求", "当前节点完成后会进入暂停状态。");
  }

  async function resumeTask() {
    if (!requireLogin()) return;
    if (!state.taskId) return;
    const endpoint = ["failed", "terminated"].includes(state.status)
      ? `/api/tasks/${state.taskId}/retry`
      : `/api/tasks/${state.taskId}/resume`;
    const data = await requestJson(endpoint, { method: "POST" });
    renderSnapshot(data.task);
    await loadProjects({ restoreSelection: true, restoreInputs: false });
    startPolling();
    showToast("已继续生成", "系统会从保留的进度继续推进。");
  }

  async function terminateTask() {
    if (!requireLogin()) return;
    if (!state.taskId) return;
    const ok = window.confirm("确认终止当前选中任务吗？当前节点会在结束后停止。");
    if (!ok) return;
    const data = await requestJson(`/api/tasks/${state.taskId}/terminate`, { method: "POST" });
    renderSnapshot(data.task);
    await loadProjects({ restoreSelection: true, restoreInputs: false });
    startPolling();
    showToast("已请求终止", "任务会在当前节点结束后停止。");
  }

  async function confirmCompletion() {
    if (!requireLogin()) return;
    if (!state.projectId || !state.latestSnapshot?.can_confirm_completion) return;
    const ok = window.confirm("确认当前剧本已经满意完成吗？确认后系统会清理执行缓存并锁定成品，之后不能再直接修改。");
    if (!ok) return;
    const data = await requestJson(`/api/projects/${state.projectId}/confirm-completion`, {
      method: "POST"
    });
    renderSnapshot(data.project);
    await loadProjects({ restoreSelection: true, restoreInputs: false });
    await loadAssets();
    await loadCommunity();
    showToast("已确认完成", "缓存已清理，当前成品已锁定。");
  }

  // 把项目回退到指定阶段或指定正文起始集，并保留前面已经确认的结果。
  async function rollbackRewrite() {
    if (!requireLogin()) return;
    if (!state.projectId || !state.latestSnapshot?.can_stage_rollback) return;
    const stageKey = els.rollbackStageSelect?.value || "";
    if (!stageKey) {
      throw new Error("请选择一个回退步骤。");
    }
    const selectedLabel = els.rollbackStageSelect?.selectedOptions?.[0]?.textContent?.trim() || "所选步骤";
    const rangeRequired = ["hooks", "dialogues", "script"].includes(stageKey);
    const startEpisodeValue = rangeRequired ? Number(els.rollbackScriptStartSelect?.value || 0) : 0;
    if (rangeRequired && startEpisodeValue <= 0) {
      throw new Error(`${rollbackRangeSelectPlaceholder(stageKey).replace("选择", "请选择")}`);
    }
      const options = rollbackStageRangeOptions(state.latestSnapshot, stageKey);
      const selectedRange = options.find((item) => String(item.value) === String(startEpisodeValue));
      const detailSuffix = selectedRange
        ? Number(selectedRange.end_episode || startEpisodeValue) < Number(state.latestSnapshot?.total_episodes || 0)
          ? `，从第 ${selectedRange.start_episode || startEpisodeValue} 集开始（将按批次重写第 ${selectedRange.start_episode || startEpisodeValue}-${selectedRange.end_episode || startEpisodeValue} 集，并继续重写后续批次）`
          : `，从第 ${selectedRange.start_episode || startEpisodeValue} 集开始（将重写第 ${selectedRange.start_episode || startEpisodeValue}-${selectedRange.end_episode || startEpisodeValue} 集）`
        : "";
    const stageLabelMap = rollbackStageLabelMap(state.latestSnapshot);
    const impactedLabels = rollbackStageDependencies(state.latestSnapshot, stageKey)
      .map((key) => stageLabelMap[key] || key)
      .filter(Boolean);
    const impactNotice = impactedLabels.length > 1
      ? `这会联动重写：${impactedLabels.join("、")}。`
      : "这会从该阶段继续重写后续内容。";
    const ok = window.confirm(`确认回退到“${selectedLabel}”${detailSuffix}吗？${impactNotice} 前面的结果会保留，后面的结果会被清空重做。`);
    if (!ok) return;
    const data = await requestJson(`/api/projects/${state.projectId}/rollback`, {
      method: "POST",
      body: JSON.stringify({
        stage_key: stageKey,
        start_episode: rangeRequired ? startEpisodeValue : null
      })
    });
    restoreInputPayload(data.task?.input_payload, { force: true });
    renderSnapshot(data.task);
    await loadProjects({ restoreSelection: true, restoreInputs: false });
    startPolling();
    showToast("已开始回退重写", `${selectedLabel}${detailSuffix || ""} 已重新进入生成流程。`);
  }

  function clearCurrentInput() {
    if (!requireLogin()) return;
    if (!canClearCurrentInput()) {
      showToast("不能清空输入", "当前策划已开始，不能清空输入；如需新建，请点击新建剧本。");
      return;
    }
    clearDraft();
    els.expectationInput.value = "";
    els.characterCountInput.value = 5;
    els.episodeCountInput.value = 10;
    state.selectedKnowledgeTagIds = [];
    state.userKnowledgeTagPrompt = "";
    if (els.userPreferenceInput) {
      els.userPreferenceInput.value = "";
    }
    renderUserKnowledgePanel();
    syncExpectationInputHeight();
    syncButtons();
    els.formHint.textContent = "输入已清空。";
  }

  function canClearCurrentInput() {
    const status = String(state.status || "idle");
    const hasProject = Boolean(state.projectId);
    const hasTask = Boolean(state.taskId);
    if (!hasProject && !hasTask) return true;
    const snapshot = state.latestSnapshot || {};
    const hasGenerated = Boolean(
      snapshot.has_final
      || snapshot.final_output
      || snapshot.output
      || snapshot.generated_episodes
      || snapshot.current_stage
      || snapshot.current_node_id
    );
    return ["idle", "draft"].includes(status) && !hasGenerated;
  }

  function saveFinalScript() {
    if (!requireLogin()) return;
    if (!state.projectId) return;
    const authToken = currentAuthToken();
    const suffix = authToken ? `?auth_token=${encodeURIComponent(authToken)}` : "";
    showToast("正在准备下载", "将为你导出包含框架与正文的 DOCX。");
    window.location.href = `/api/projects/${state.projectId}/download${suffix}`;
  }

  function visibilityLabel(value) {
    return value === "public" ? "公开成品" : "不公开";
  }

  function communityDetailUrl(projectId) {
    return `${window.scriptMakerConfig.communityDetailBaseUrl || "/community"}/${encodeURIComponent(projectId)}`;
  }

  function emptyCard(message, actionText = "") {
    return `
      <div class="empty-card">
        <strong>${escapeHtml(message)}</strong>
        ${actionText ? `<p>${escapeHtml(actionText)}</p>` : ""}
      </div>
    `;
  }

  function ensureToastStack() {
    let stack = document.getElementById("toastStack");
    if (stack) return stack;
    stack = document.createElement("div");
    stack.id = "toastStack";
    stack.className = "toast-stack";
    document.body.appendChild(stack);
    return stack;
  }

  function showToast(title, message) {
    const stack = ensureToastStack();
    const card = document.createElement("div");
    card.className = "toast-card";
    card.innerHTML = `<strong>${escapeHtml(title)}</strong><p>${escapeHtml(message)}</p>`;
    stack.appendChild(card);
    window.setTimeout(() => {
      card.remove();
      if (!stack.children.length) {
        stack.remove();
      }
    }, 5000);
  }

  function findOwnedAsset(projectId) {
    const targetId = Number(projectId);
    if (!Number.isFinite(targetId)) return null;
    return state.assets.find((item) => Number(item.project_id) === targetId)
      || state.projects.find((item) => Number(item.project_id) === targetId)
      || (Number(state.latestSnapshot?.project_id) === targetId ? state.latestSnapshot : null);
  }

  function assetDeletePromptMessage(projectId) {
    const item = findOwnedAsset(projectId);
    const title = projectDisplayTitle(item);
    if (title && title !== "未选中") {
      return `确定要删除“${title}”吗？此操作不可恢复。`;
    }
    return "确定要删除这个资产吗？此操作不可恢复。";
  }

  function closeAssetDeleteDialog() {
    if (!els.assetDeleteDialog || els.assetDeleteDialog.classList.contains("hidden")) return;
    els.assetDeleteDialog.classList.remove("panel-open");
    if (state.assetDeleteHideTimer) {
      window.clearTimeout(state.assetDeleteHideTimer);
    }
    state.assetDeleteHideTimer = window.setTimeout(() => {
      els.assetDeleteDialog?.classList.add("hidden");
      els.assetDeleteDialog?.setAttribute("aria-hidden", "true");
      state.assetDeleteHideTimer = null;
    }, 180);
  }

  function settleAssetDeleteDialog(confirmed) {
    const resolver = state.assetDeleteConfirmResolver;
    state.assetDeleteConfirmResolver = null;
    closeAssetDeleteDialog();
    if (resolver) {
      resolver(Boolean(confirmed));
    }
  }

  function confirmAssetDeletion(projectId) {
    const message = assetDeletePromptMessage(projectId);
    if (!els.assetDeleteDialog || !els.assetDeleteMessage || !els.confirmDeleteAssetBtn || !els.cancelDeleteAssetBtn) {
      return Promise.resolve(window.confirm(message));
    }
    if (state.assetDeleteConfirmResolver) {
      settleAssetDeleteDialog(false);
    }
    if (state.assetDeleteHideTimer) {
      window.clearTimeout(state.assetDeleteHideTimer);
      state.assetDeleteHideTimer = null;
    }
    els.assetDeleteMessage.textContent = message;
    els.assetDeleteDialog.classList.remove("hidden");
    els.assetDeleteDialog.setAttribute("aria-hidden", "false");
    window.requestAnimationFrame(() => {
      els.assetDeleteDialog?.classList.add("panel-open");
    });
    return new Promise((resolve) => {
      state.assetDeleteConfirmResolver = resolve;
    });
  }

  function showCopyToast() {
    const stack = ensureToastStack();
    const card = document.createElement("div");
    card.className = "toast-card toast-card-compact";
    card.innerHTML = `<strong>复制成功</strong>`;
    stack.appendChild(card);
    window.setTimeout(() => {
      card.remove();
      if (!stack.children.length) {
        stack.remove();
      }
    }, 1000);
  }

  function flashCopyButton(button, label) {
    if (!button) return;
    const original = button.dataset.originalLabel || button.textContent || "复制";
    button.dataset.originalLabel = original;
    button.textContent = label;
    button.disabled = true;
    window.setTimeout(() => {
      button.textContent = original;
      button.disabled = false;
    }, 1000);
  }

  function projectTooltip(item) {
      return [
      `剧本：${projectDisplayTitle(item)}`,
      `进度：${Number(item.progress_percent || 0)}%`,
      `当前阶段：${item.current_stage_label || statusLabel(item.status)}`,
      `当前状态：${statusLabel(item.status)}`
    ].join("\n");
  }

  function summarizeProjectStatusChanges(projects) {
    const nextMap = {};
    for (const item of projects) {
      nextMap[String(item.project_id)] = String(item.status || "");
    }

    if (!state.projectsInitialized) {
      state.projectStatusMap = nextMap;
      state.projectsInitialized = true;
      return;
    }

    for (const item of projects) {
      const projectId = String(item.project_id);
      const previousStatus = state.projectStatusMap[projectId];
      const currentStatus = String(item.status || "");
      if (
        previousStatus
        && previousStatus !== "failed"
        && currentStatus === "failed"
        && Number(item.project_id) !== Number(state.projectId)
      ) {
        showToast(
          `${item.title || "未命名剧本"} 失败了`,
          "后台任务已停在上一个成功步骤，你可以打开项目后手动继续生成。"
        );
      }
    }

    state.projectStatusMap = nextMap;
  }

  async function loadAssets({ resetPage = false } = {}) {
    if (!isAuthenticated()) {
      state.assetsStatus = "empty";
      state.assetsError = "";
      state.assets = [];
      state.assetsPage = 1;
      if (els.assetsList) {
        els.assetsList.innerHTML = emptyCard("登录后查看剧本资产");
      }
      return;
    }
    if (resetPage) {
      state.assetsPage = 1;
    }
    state.assetsStatus = "loading";
    state.assetsError = "";
    renderAssets(state.assets);
    try {
      const data = await requestJson(window.scriptMakerConfig.assetsUrl);
      state.assets = data.assets || [];
      state.assetsStatus = state.assets.length ? "success" : "empty";
      renderAssets(state.assets);
      renderToolHistory(state.activeTool);
      if (state.activeTool === "sitcom_generator" && !state.toolResults.sitcom_generator) {
        if (restoreLatestSitcomResult()) renderToolOutput("sitcom_generator");
      }
    } catch (error) {
      state.assetsStatus = "error";
      state.assetsError = friendlyErrorText(error, "资产列表加载失败，请稍后重试。");
      renderAssets(state.assets);
      throw error;
    }
  }

  async function loadCommunity({ resetPage = false } = {}) {
    if (!els.communityList) return;
    if (resetPage) {
      state.communityPage = 1;
    }
    state.communityStatus = "loading";
    state.communityError = "";
    renderCommunity([]);
    try {
      const data = await requestJson(window.scriptMakerConfig.communityUrl);
      state.communityAssets = data.assets || [];
      state.communityStatus = state.communityAssets.length ? "success" : "empty";
      renderCommunity(state.communityAssets);
    } catch (error) {
      state.communityStatus = "error";
      state.communityError = friendlyErrorText(error, "社区作品加载失败，请稍后重试。");
      renderCommunity(state.communityAssets);
      throw error;
    }
  }

  function renderAssets(assets) {
    if (!els.assetsList) return;
    if (state.assetsStatus === "loading") {
      els.assetsList.innerHTML = renderListSkeleton("asset-tile");
      return;
    }
    if (state.assetsStatus === "error") {
      els.assetsList.innerHTML = errorCard(state.assetsError || "资产列表加载失败，请稍后重试。");
      return;
    }
    if (!assets.length) {
      els.assetsList.innerHTML = emptyCard("还没有用户资产");
      return;
    }
    const categories = [
      ["爆款文审核资产", assets.filter((item) => isHotReviewAsset(item))],
      ["框架资产", assets.filter((item) => assetCategory(item) === "framework" && !isHotReviewAsset(item))],
      ["新剧本资产", assets.filter((item) => assetCategory(item) === "new_script" && !isHotReviewAsset(item))],
      ["其他辅助工具资产", assets.filter((item) => isToolAsset(item) && !isHotReviewAsset(item))],
    ];
    els.assetsList.innerHTML = categories.map(([title, items]) => `
      <section class="asset-category">
        <div class="asset-category-head">${escapeHtml(title)}</div>
        ${items.length ? items.map((item) => `
      <article class="asset-tile">
        <div class="asset-topline">
          <span class="status-pill ${item.status === "completed" ? "status-pill-completed" : ""}">${escapeHtml(statusLabel(item.status))}</span>
          ${isToolAsset(item)
            ? `<span class="status-pill status-pill-pending">${escapeHtml(assetTypeLabel(item))}</span>`
            : (item.completion_confirmed ? '<span class="status-pill status-pill-locked">已锁定</span>' : item.awaiting_user_confirmation ? '<span class="status-pill status-pill-pending">待确认</span>' : "")}
          <span class="status-pill ${item.visibility === "public" ? "status-pill-public" : "status-pill-private"}">${escapeHtml(visibilityLabel(item.visibility))}</span>
        </div>
        <h3>${escapeHtml(isHotReviewAsset(item) ? hotReviewAssetTitle(item) : projectDisplayTitle(item))}</h3>
        ${isHotReviewAsset(item) ? `<button class="btn btn-secondary" type="button" data-action="open-hot-review-asset" data-project-id="${escapeHtml(hotReviewAssetKey(item) || hotReviewAssetTitle(item))}" data-hot-review-asset-key="${escapeHtml(hotReviewAssetKey(item) || hotReviewAssetTitle(item))}">打开爆款文审核</button>` : ""}
        <p>${escapeHtml(item.summary)}</p>
        <div class="asset-meta">
          <span>项目 ${escapeHtml(item.project_id)}</span>
          <span>${escapeHtml(isToolAsset(item) ? assetWorkflowLabel(item) : (item.current_stage_label || "待开始"))}</span>
          <span>${escapeHtml(isToolAsset(item)
            ? (item.tool_filename || "已保存结果")
            : `${item.generated_episodes || 0} / ${item.total_episodes || 0}`)}</span>
        </div>
        <div class="asset-actions">
          <div class="asset-action-group">
            <span class="asset-action-label">资产操作</span>
            ${isToolAsset(item) ? "" : isFrameworkPlannerAsset(item)
              ? `<button class="btn btn-secondary" data-action="open-framework-asset" data-project-id="${escapeHtml(item.project_id)}">打开框架</button>`
              : `<button class="btn btn-secondary" data-action="open-project" data-project-id="${escapeHtml(item.project_id)}">载入工作台</button>`}
            ${isSitcomAsset(item)
              ? `<button class="btn btn-edit" data-action="open-sitcom-asset" data-project-id="${escapeHtml(item.project_id)}">打开情景剧</button>`
              : `<button class="btn btn-edit" data-action="edit-asset" data-project-id="${escapeHtml(item.project_id)}">打开查看</button>`}
            ${isFrameworkPlannerAsset(item) ? `<a class="btn btn-secondary" href="/framework-to-script?framework_asset_id=${encodeURIComponent(item.project_id)}${currentAuthToken() ? `&auth_token=${encodeURIComponent(currentAuthToken())}` : ""}">进入框架到剧本</a>` : ""}
            <button class="btn ${item.visibility === "public" ? "btn-public" : "btn-ghost"}" data-action="toggle-privacy" data-project-id="${escapeHtml(item.project_id)}" data-visibility="${escapeHtml(item.visibility)}">${item.visibility === "public" ? "设为不公开" : (isToolAsset(item) ? "公开结果" : "公开成品")}</button>
            <button class="btn btn-danger" data-action="delete-asset" data-project-id="${escapeHtml(item.project_id)}">删除资产</button>
          </div>
          ${renderAssetTaskActions(item)}
        </div>
      </article>
    `).join("") : emptyCard(`暂无${title}`)}
      </section>
    `).join("");
  }

  function assetCategory(item) {
    const explicit = String(item.asset_type || item.type || "").trim();
    if (["old_script", "legacy_script"].includes(explicit)) return "framework";
    if (["framework", "new_script", "character_reskin", "waibao"].includes(explicit)) return explicit;
    const assetKind = String(item.asset_kind || "").trim();
    const input = item.input_payload && typeof item.input_payload === "object" ? item.input_payload : {};
    const artifacts = item.artifacts && typeof item.artifacts === "object" ? item.artifacts : {};
    const frameworkToScriptState = artifacts.framework_to_script_state || item.framework_to_script_state;
    const hasFrameworkScriptState = frameworkToScriptState && typeof frameworkToScriptState === "object"
      && (
        Object.keys(frameworkToScriptState.scriptStages || {}).length > 0
        || Object.keys(frameworkToScriptState.stageOutputs || {}).length > 0
        || Boolean(frameworkToScriptState.runningStage)
      );
    const scriptMode = String(item.script_format_mode || input.script_format_mode || "").trim();
    const toolKey = String(item.tool_key || "").trim();
    if (assetKind === "tool_result" && toolKey === "character_reskin") return "character_reskin";
    if (scriptMode === "waibao") return "waibao";
    if (assetKind === "framework_to_script" || scriptMode === "framework_to_script" || input.framework_to_script === true || hasFrameworkScriptState) return "new_script";
    if (assetKind === "framework_planner") return "framework";
    return "old_script";
  }

  function isFrameworkPlannerAsset(item) {
    return String((item && item.asset_kind) || "").trim() === "framework_planner";
  }

  function renderAssetTaskActions(item) {
    if (isToolAsset(item)) return "";
    const taskId = String(item.task_id || "").trim();
    if (!taskId) return "";
    const status = String(item.status || "");
    const canContinue = RESUMABLE_STATUSES.has(status);
    const canStop = TERMINATABLE_STATUSES.has(status);
    return `
      <div class="asset-action-group task-action-group">
        <span class="asset-action-label">任务操作</span>
        ${canContinue ? `<button class="btn btn-secondary" data-action="continue-task" data-task-id="${escapeHtml(taskId)}" data-project-id="${escapeHtml(item.project_id)}">继续任务</button>` : ""}
        ${canStop ? `<button class="btn btn-danger" data-action="stop-task" data-task-id="${escapeHtml(taskId)}" data-project-id="${escapeHtml(item.project_id)}">停止任务</button>` : ""}
        <button class="btn btn-ghost" data-action="delete-task" data-task-id="${escapeHtml(taskId)}" data-project-id="${escapeHtml(item.project_id)}">删除任务</button>
      </div>
    `;
  }

  function frameworkPlannerAssetUrl(projectId) {
    const token = currentAuthToken();
    return `/framework-planner?auth_token=${encodeURIComponent(token)}&project_id=${encodeURIComponent(projectId)}`;
  }

  function renderCommunity(assets) {
    if (!els.communityList) return;
    if (state.communityStatus === "loading") {
      els.communityList.innerHTML = renderListSkeleton("community-tile");
      return;
    }
    if (state.communityStatus === "error") {
      els.communityList.innerHTML = errorCard(state.communityError || "社区作品加载失败，请稍后重试。");
      return;
    }
    if (!assets.length) {
      els.communityList.innerHTML = emptyCard("社区里暂时还没有公开作品");
      return;
    }
    const { visibleItems, hasMore } = paginateItems(assets, state.communityPage, 6);
    els.communityList.innerHTML = visibleItems.map((item) => `
      <article class="community-tile">
        <span class="community-tag status-pill-public">公开成品</span>
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.summary)}</p>
        <div class="community-actions">
          <a class="btn btn-secondary" href="${escapeHtml(communityDetailUrl(item.project_id))}" target="_blank" rel="noopener">查看全文</a>
        </div>
      </article>
    `).join("") + (hasMore ? `
      <div class="list-more-row">
        <button class="btn btn-secondary" type="button" data-action="load-more-community">加载更多作品</button>
      </div>
    ` : "");
  }

  async function openAssetEditor(projectId) {
    if (!requireLogin()) return;
    const data = await requestJson(`/api/projects/${projectId}`);
    const project = data.project || {};
    const input = project.input_payload || {};
    const artifacts = project.artifacts || {};
    const toolRequest = project.tool_request_payload && typeof project.tool_request_payload === "object"
      ? project.tool_request_payload
      : null;
    state.editingProjectId = Number(projectId);
    state.editingProjectStatus = String(project.status || "");
    state.editingAssetKind = String(project.asset_kind || "").trim();
    state.editingAssetLocked = Boolean(project.completion_confirmed && state.editingAssetKind !== "tool_result");
    state.assetEditMode = "view";
    state.assetDirty = false;
    const viewModeLocked = true;
    els.editAssetTitle.value = project.title || input.title || "";
    els.editAssetSummary.value = formatDisplayValue(
      toolRequest
        ? JSON.stringify(toolRequest, null, 2)
        : (input.story_outline || artifacts.story_outline || "")
    );
    els.editAssetPrivacy.value = project.visibility || "private";
    els.editAssetFinal.value = state.editingProjectStatus === "completed"
      ? formatDisplayValue(artifacts.final_output_text || artifacts.final_script || "")
      : "";
    if (els.editAssetTitle) els.editAssetTitle.disabled = viewModeLocked;
    if (els.editAssetSummary) els.editAssetSummary.disabled = viewModeLocked;
    if (els.editAssetFinal) els.editAssetFinal.disabled = viewModeLocked;
    if (els.editAssetPrivacy) els.editAssetPrivacy.disabled = true;
    if (els.saveAssetEditBtn) {
      els.saveAssetEditBtn.disabled = false;
      els.saveAssetEditBtn.textContent = "修改";
    }
    if (els.cancelAssetEditBtn) els.cancelAssetEditBtn.textContent = "取消";
    els.assetEditor.classList.remove("hidden");
    els.assetEditor.scrollIntoView({ behavior: "smooth", block: "center" });
    syncButtons();
  }

  async function saveAssetEdit() {
    if (!requireLogin() || !state.editingProjectId) return;
    if (state.assetEditMode !== "edit") {
      state.assetEditMode = "edit";
      state.assetDirty = false;
      if (els.editAssetTitle) els.editAssetTitle.disabled = state.editingAssetLocked;
      if (els.editAssetSummary) els.editAssetSummary.disabled = state.editingAssetLocked;
      if (els.editAssetFinal) els.editAssetFinal.disabled = state.editingAssetLocked;
      if (els.editAssetPrivacy) els.editAssetPrivacy.disabled = false;
      if (els.saveAssetEditBtn) els.saveAssetEditBtn.textContent = "应用修改";
      if (els.cancelAssetEditBtn) els.cancelAssetEditBtn.textContent = "取消修改";
      syncButtons();
      return;
    }
    const payload = {
      visibility: els.editAssetPrivacy.value
    };
    if (!state.editingAssetLocked) {
      payload.title = els.editAssetTitle.value.trim();
      payload.story_outline = els.editAssetSummary.value.trim();
      const finalScriptText = els.editAssetFinal.value.trim();
      if (state.editingProjectStatus === "completed" || finalScriptText) {
        payload.final_script = finalScriptText;
      }
    }
    const data = await requestJson(`/api/projects/${state.editingProjectId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    });
    if (Number(data.project?.project_id) === Number(state.projectId)) {
      renderSnapshot(data.project);
    }
    closeAssetEditor();
    await loadProjects({ restoreSelection: true, restoreInputs: false });
    await loadAssets();
    await loadCommunity();
    showToast("资产已保存", "修改内容已经同步更新。");
  }

  function closeAssetEditor() {
    if (state.assetEditMode === "edit" && state.assetDirty) {
      const action = window.prompt("当前资产有未应用修改。请输入：保存 / 不保存 / 取消", "取消");
      const normalized = String(action || "取消").trim();
      if (normalized === "保存") {
        saveAssetEdit().catch((error) => showToast("资产保存失败", friendlyErrorText(error, "请稍后重试。")));
        return;
      }
      if (normalized !== "不保存") return;
    }
    state.editingProjectId = null;
    state.editingProjectStatus = null;
    state.editingAssetKind = "";
    state.editingAssetLocked = false;
    state.assetEditMode = "view";
    state.assetDirty = false;
    [els.editAssetTitle, els.editAssetSummary, els.editAssetPrivacy, els.editAssetFinal].forEach((field) => {
      if (field) field.disabled = false;
    });
    if (els.editAssetTitle) els.editAssetTitle.value = "";
    if (els.editAssetSummary) els.editAssetSummary.value = "";
    if (els.editAssetPrivacy) els.editAssetPrivacy.value = "private";
    if (els.editAssetFinal) els.editAssetFinal.value = "";
    if (els.saveAssetEditBtn) {
      els.saveAssetEditBtn.disabled = false;
      els.saveAssetEditBtn.textContent = "修改";
    }
    if (els.cancelAssetEditBtn) els.cancelAssetEditBtn.textContent = "取消";
    els.assetEditor.classList.add("hidden");
    syncButtons();
  }

  async function toggleAssetPrivacy(projectId, currentVisibility) {
    if (!requireLogin()) return;
    const nextVisibility = currentVisibility === "public" ? "private" : "public";
    await requestJson(`/api/projects/${projectId}`, {
      method: "PATCH",
      body: JSON.stringify({ visibility: nextVisibility })
    });
    await loadProjects({ restoreSelection: true, restoreInputs: false });
    await loadAssets();
    await loadCommunity();
    showToast(nextVisibility === "public" ? "已设为公开" : "已设为不公开", "资产可见性已经更新。");
  }

  async function deleteAsset(projectId, button = null) {
    if (!requireLogin()) return;
    const ok = await confirmAssetDeletion(projectId);
    if (!ok) return;
    await withActionLoading(`deleteAsset:${projectId}`, button, "删除中...", async () => {
      const wasCurrentProject = Number(projectId) === Number(state.projectId);
      const wasEditingAsset = Number(projectId) === Number(state.editingProjectId);
      await requestJson(`/api/projects/${projectId}`, { method: "DELETE" });
      if (wasEditingAsset) {
        closeAssetEditor();
      }
      if (wasCurrentProject) {
        switchToFreshWorkspace();
      }
      await loadProjects({
        restoreSelection: !wasCurrentProject,
        restoreInputs: false
      });
      await loadAssets();
      await loadCommunity();
      showToast("资产已删除", "该用户资产已从当前账号移除。");
    });
  }

  async function continueAssetTask(taskId, projectId, button = null) {
    if (!requireLogin() || !taskId) return;
    await withActionLoading(`continueTask:${taskId}`, button, "继续中...", async () => {
      const item = state.assets.find((asset) => String(asset.task_id || "") === String(taskId));
      const endpoint = item && ["failed", "terminated"].includes(String(item.status || ""))
        ? `/api/tasks/${taskId}/retry`
        : `/api/tasks/${taskId}/resume`;
      const data = await requestJson(endpoint, { method: "POST" });
      if (Number(projectId) === Number(state.projectId) || Number(data.task?.project_id) === Number(state.projectId)) {
        renderSnapshot(data.task);
        startPolling();
      }
      await loadProjects({ restoreSelection: true, restoreInputs: false });
      await loadAssets();
      showToast("任务已继续", "已从保留进度继续推进。");
    });
  }

  async function stopAssetTask(taskId, projectId, button = null) {
    if (!requireLogin() || !taskId) return;
    const ok = window.confirm("确认停止这个任务吗？已生成的阶段和资产内容会保留。");
    if (!ok) return;
    await withActionLoading(`stopTask:${taskId}`, button, "停止中...", async () => {
      const data = await requestJson(`/api/tasks/${taskId}/terminate`, { method: "POST" });
      if (Number(projectId) === Number(state.projectId) || Number(data.task?.project_id) === Number(state.projectId)) {
        renderSnapshot(data.task);
      }
      await loadProjects({ restoreSelection: true, restoreInputs: false });
      await loadAssets();
      showToast("任务已停止", "当前任务已停止，资产内容已保留。");
    });
  }

  async function deleteTask(taskId, projectId, button = null) {
    if (!requireLogin() || !taskId) return;
    const ok = window.confirm("确认删除这个任务及其资产记录吗？此操作不可恢复。");
    if (!ok) return;
    await withActionLoading(`deleteTask:${taskId}`, button, "删除中...", async () => {
      await requestJson(`/api/tasks/${taskId}`, { method: "DELETE" });
      if (Number(projectId) === Number(state.projectId)) {
        switchToFreshWorkspace();
      }
      await loadProjects({ restoreSelection: Number(projectId) !== Number(state.projectId), restoreInputs: false });
      await loadAssets();
      await loadCommunity();
      showToast("任务已删除", "任务和对应资产记录已移除。");
    });
  }

  async function runActiveTool() {
    if (!requireLogin()) return;
    const activeToolKey = state.activeTool;
    const payload = collectToolPayload(activeToolKey);
    const hotReviewStartedAt = Date.now();
    const hotReviewKnownKeys = activeToolKey === "hot_review" ? hotReviewKnownAssetKeys() : new Set();
    let hotReviewResultPoller = null;
    if (activeToolKey === "new_framework") {
      const projectTitle = projectTitleCandidate();
      if (projectTitle) {
        payload.project_title = projectTitle;
      }
    }
    state.toolResults[activeToolKey] = null;
    renderToolOutput(activeToolKey, activeToolKey === "hot_review"
      ? "爆款文审核通常需要较长时间。你可以切换页面继续操作，完成后会自动保存到爆款文审核资产；如果本页请求中断，这里会显示失败原因，也可以稍后从资产查看或重新运行。"
      : (activeToolKey === "character_reskin"
        ? characterReskinRunningMessage(0)
        : "生成时间约十五分钟，请不要刷新，马上就好~"));
    startToolProgressTicker(activeToolKey);
    if (activeToolKey === "hot_review") {
      hotReviewResultPoller = startHotReviewResultPolling({
        startedAtMs: hotReviewStartedAt,
        knownKeys: hotReviewKnownKeys
      });
    }
    try {
      const data = await requestJson(currentToolRunUrl(activeToolKey), {
        method: "POST",
        body: JSON.stringify(payload),
        timeoutMs: activeToolKey === "hot_review" ? HOT_REVIEW_RUN_TIMEOUT_MS : 0
      });
      hotReviewResultPoller?.stop();
      stopToolProgressTicker();
      const result = data.result || data;
      const output = result.output ?? data.output ?? result.result ?? "";
      const text = String(result.text || data.text || formatToolOutput(output) || "").trim();
      const filename = String(result.filename || data.filename || "").trim();
      const assetSaved = Boolean(result.asset_saved || data.asset_saved);
      const assetSaveError = String(result.asset_save_error || data.asset_save_error || "").trim();
      state.toolResults[activeToolKey] = {
        ...data,
        ...result,
        text,
        answer_text: result.answer_text || data.answer_text || text,
        filename,
        output,
        result_type: result.result_type || data.result_type || "",
        resultType: result.result_type || data.result_type || "",
        parsed: result.parsed ?? data.parsed ?? false,
        audit: result.audit || data.audit || null,
        view: result.view || data.view || null,
        parse_warnings: result.parse_warnings || data.parse_warnings || [],
        parseWarnings: result.parse_warnings || data.parse_warnings || [],
        outputType: result.output_type || data.output_type || "text",
        assetSaved,
        savedAsset: result.saved_asset || data.saved_asset || null
      };
      state.toolResults[activeToolKey] = normalizeScriptAuditEcgResult(state.toolResults[activeToolKey]);
      if (activeToolKey === "hot_review") {
        persistHotReviewSession(state.toolResults.hot_review);
      }
      renderToolOutput(activeToolKey);
      if (assetSaved) {
        if (state.toolResults[activeToolKey]?.savedAsset) {
          mergeProjectListAsset(state.toolResults[activeToolKey].savedAsset);
        }
        try {
          await loadAssets();
          await loadProjects({ restoreSelection: true, restoreInputs: false });
        } catch (_) {
          // 结果已经生成并写入后端，不阻断当前工具面板的成功态展示。
        }
      }
      showToast(
        "辅助工具运行完成",
        assetSaveError
          ? `${result.title || toolConfig(activeToolKey)?.label || "当前工具"} 已返回结果，但写入用户资产失败了。`
          : (assetSaved
            ? `${result.title || toolConfig(activeToolKey)?.label || "当前工具"} 已返回结果，并已保存到用户资产。`
            : `${result.title || toolConfig(activeToolKey)?.label || "当前工具"} 已返回结果。`),
      );
    } catch (error) {
      hotReviewResultPoller?.stop();
      stopToolProgressTicker();
      if (activeToolKey === "hot_review" && isScriptAuditEcgResult(currentToolResult("hot_review"))) {
        renderToolOutput("hot_review");
        showToast("爆款文审核已完成", "请求链路已结束，当前页已展示自动同步到的结果。");
        return;
      }
      console.error("[tool-run]", error);
      const fallback = activeToolKey === "hot_review"
        ? "爆款文审核运行失败，可能是请求超时、后端中断或网络抖动。当前输入已保留，请稍后重试。"
        : "辅助工具运行失败，请稍后重试。";
      showToolError(error, fallback, { toolKey: activeToolKey });
      showToast("辅助工具运行失败", friendlyErrorText(error, fallback, { toolKey: activeToolKey }));
    }
  }

  function downloadActiveToolResult() {
    const result = currentToolResult();
    const tool = toolConfig(state.activeTool);
    const toolLabel = tool?.label || "辅助工具结果";
    if (!result?.text || !result?.filename) {
      showToast("暂无可下载内容", `请先成功生成${toolLabel}。`);
      return;
    }
    if (state.activeTool === "character_reskin" && result.savedAsset?.project_id) {
      const authToken = currentAuthToken();
      const suffix = authToken ? `?auth_token=${encodeURIComponent(authToken)}` : "";
      window.location.href = `/api/projects/${encodeURIComponent(result.savedAsset.project_id)}/download${suffix}`;
      showToast("DOCX 已开始下载", `${projectDisplayTitle(result.savedAsset)}.docx`);
      return;
    }
    downloadTextFile(result.text, result.filename);
    showToast("TXT 已开始下载", result.filename);
  }

  async function updateUsername(event) {
    event.preventDefault();
    if (!requireLogin()) return;
    const username = els.profileUsernameInput.value.trim();
    try {
      const data = await requestJson("/api/me/username", {
        method: "PATCH",
        body: JSON.stringify({ username })
      });
      window.scriptMakerConfig.username = data.user?.username || username;
      els.profileMessage.textContent = "用户名已修改。";
    } catch (error) {
      showProfileError(error, "用户名修改失败，请稍后重试。");
    }
  }

  async function updatePassword(event) {
    event.preventDefault();
    if (!requireLogin()) return;
    try {
      await requestJson("/api/me/password", {
        method: "PATCH",
        body: JSON.stringify({
          current_password: els.currentPasswordInput.value,
          new_password: els.newPasswordInput.value,
          confirm_password: els.confirmPasswordInput.value
        })
      });
      els.currentPasswordInput.value = "";
      els.newPasswordInput.value = "";
      els.confirmPasswordInput.value = "";
      els.profileMessage.textContent = "密码已修改。";
    } catch (error) {
      showProfileError(error, "密码修改失败，请稍后重试。");
    }
  }

  async function pollWorkspace() {
    try {
      await loadProjects({ restoreSelection: true, restoreInputs: false });
    } catch (error) {
      showStatusError(error, "后台状态同步失败，正在稍后重试。");
    }
    if (shouldContinuePolling()) {
      state.pollTimer = window.setTimeout(pollWorkspace, POLL_INTERVAL);
    } else {
      stopPolling();
    }
  }

  function startPolling() {
    stopPolling();
    state.pollTimer = window.setTimeout(pollWorkspace, POLL_INTERVAL);
  }

  function stopPolling() {
    if (state.pollTimer) {
      window.clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
  }

  async function restoreWorkspace() {
    if (!isAuthenticated()) {
      state.projects = [];
      renderProjectList([]);
      renderSnapshot(null);
      return;
    }
    await loadProjects({ restoreSelection: true, restoreInputs: true });
    if (shouldContinuePolling()) {
      startPolling();
    }
    const params = currentUrl().searchParams;
    const panel = params.get("panel");
    const section = params.get("section");
    if (panel === "profile" && isAuthenticated()) {
      openProfilePanel();
    }
    if (section === "tools") {
      window.setTimeout(() => {
        (async () => {
          if (els.assistantToolsFolder) {
            els.assistantToolsFolder.open = true;
          }
          const toolKey = params.get("tool") || state.activeTool || "hot_review";
          state.activeTool = toolConfig(toolKey)?.key || state.activeTool;
          const projectId = params.get("project_id");
          if ((toolKey === "hot_review" || projectId) && await restoreHotReviewPanelFromSession(projectId || "")) {
            return;
          }
          openToolPanel(state.activeTool);
        })().catch((error) => {
          showToast("爆款文审核恢复失败", friendlyErrorText(error, "请刷新资产列表后重试。"));
          openToolPanel(state.activeTool);
        });
      }, 80);
      return;
    }
    if (section === "community") {
      window.setTimeout(() => {
        openCommunityPanel();
      }, 80);
      return;
    }
    if (section) {
      window.setTimeout(() => {
        document.getElementById(section)?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    }
  }

  function bindInputs() {
    [
      els.expectationInput,
      els.characterCountInput,
      els.episodeCountInput,
      els.modelSelect
    ].filter(Boolean).forEach((el) => {
      el.addEventListener("input", () => {
        if (el === els.expectationInput) {
          syncExpectationInputHeight();
        }
        saveDraft();
        syncButtons();
      });
      el.addEventListener("change", () => {
        if (el === els.expectationInput) {
          syncExpectationInputHeight();
        }
        saveDraft();
        syncButtons();
      });
    });
    els.userPreferenceInput?.addEventListener("input", () => {
      saveDraft();
      renderUserKnowledgePanel();
    });
    els.userPreferenceInput?.addEventListener("change", () => {
      saveDraft();
      renderUserKnowledgePanel();
    });
    els.toolForms?.addEventListener("input", () => {
      rememberCurrentToolDraft();
      syncButtons();
    });
    els.toolForms?.addEventListener("change", () => {
      rememberCurrentToolDraft();
      syncButtons();
    });
    [els.editAssetTitle, els.editAssetSummary, els.editAssetPrivacy, els.editAssetFinal].filter(Boolean).forEach((el) => {
      el.addEventListener("input", () => {
        if (state.assetEditMode === "edit") state.assetDirty = true;
        syncButtons();
      });
      el.addEventListener("change", () => {
        if (state.assetEditMode === "edit") state.assetDirty = true;
        syncButtons();
      });
    });
  }

  function bindActions() {
    els.openProfileBtn?.addEventListener("click", openProfilePanel);
    els.closeProfileBtn?.addEventListener("click", closeProfilePanel);
    els.closeProfileBackdrop?.addEventListener("click", closeProfilePanel);
    els.usernameForm?.addEventListener("submit", updateUsername);
    els.passwordForm?.addEventListener("submit", updatePassword);
    els.sidebarToggleBtn?.addEventListener("click", () => {
      const nextCollapsed = !els.workspaceSidebar?.classList.contains("is-collapsed");
      applySidebarCollapsed(nextCollapsed);
    });

    els.newScriptBtn?.addEventListener("click", () => {
      if (!requireLogin()) return;
      openWorkspaceInNewPage({ fresh: true });
    });

    els.newGenerationWindowBtn?.addEventListener("click", () => {
      if (!requireLogin()) return;
      openFreshGenerationWindows(els.multiOpenCountSelect?.value || 1);
    });

    document.querySelectorAll("[data-multi-open-count]").forEach((button) => {
      button.addEventListener("click", () => {
        if (!requireLogin()) return;
        openFreshGenerationWindows(button.dataset.multiOpenCount);
      });
    });

    els.waibaoScriptBtn?.addEventListener("click", () => {
      if (!requireLogin()) return;
      openWorkspaceInNewPage({ fresh: true, scriptFormatMode: "waibao" });
    });

    els.openCommunityPanelLink?.addEventListener("click", (event) => {
      event.preventDefault();
      openCommunityPanel();
    });

    els.viewAssetsBtn?.addEventListener("click", () => {
      if (!requireLogin()) return;
      openProfilePanel();
    });

    els.newAssetBtn?.addEventListener("click", () => {
      if (!requireLogin()) return;
      closeProfilePanel();
      openWorkspaceInNewPage({ fresh: true });
    });

    els.workspaceCard?.addEventListener("mouseenter", cancelWorkspaceAutoCollapse);
    els.workspaceCard?.addEventListener("mouseleave", scheduleWorkspaceAutoCollapse);
    els.workspaceCard?.addEventListener("focusin", cancelWorkspaceAutoCollapse);
    els.workspaceCard?.addEventListener("focusout", () => {
      window.setTimeout(() => {
        if (!els.workspaceCard?.matches(":focus-within")) {
          scheduleWorkspaceAutoCollapse();
        }
      }, 0);
    });
    workspaceFolders().forEach((folder) => {
      folder.addEventListener("toggle", () => {
        if (folder.open) {
          cancelWorkspaceAutoCollapse();
        } else {
          scheduleWorkspaceAutoCollapse();
        }
      });
    });

    els.refreshProjectsBtn?.addEventListener("click", async () => {
      try {
        await loadProjects({ restoreSelection: true, restoreInputs: false });
      } catch (error) {
        showStatusError(error, "任务列表刷新失败，请稍后重试。");
      }
    });

    els.knowledgeTagList?.addEventListener("change", (event) => {
      const checkbox = event.target.closest("input[data-knowledge-tag-id]");
      if (!checkbox) return;
      const tagId = String(checkbox.dataset.knowledgeTagId || "").trim();
      if (!tagId) return;
      if (checkbox.checked) {
        state.selectedKnowledgeTagIds = [...new Set([...state.selectedKnowledgeTagIds, tagId])];
      } else {
        state.selectedKnowledgeTagIds = state.selectedKnowledgeTagIds.filter((id) => id !== tagId);
      }
      saveDraft();
      renderUserKnowledgePanel();
    });

    els.knowledgeTagList?.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-action]");
      if (!button) return;
      if (button.dataset.action === "delete-knowledge-tag") {
        event.preventDefault();
        event.stopPropagation();
        await deleteUserKnowledgeTag(button.dataset.tagId || "");
      } else if (button.dataset.action === "pin-knowledge-tag") {
        event.preventDefault();
        event.stopPropagation();
        await toggleUserKnowledgeTagPinned(button.dataset.tagId || "");
      }
    });

    els.applyKnowledgeTagsBtn?.addEventListener("click", applyUserKnowledgeTags);
    els.createKnowledgeTagBtn?.addEventListener("click", createUserKnowledgeTag);

    els.refreshAssetsBtn?.addEventListener("click", async () => {
      try {
        await loadAssets({ resetPage: true });
        showToast("资产列表已刷新", "已获取最新资产状态。");
      } catch (error) {
        showToast("资产列表刷新失败", friendlyErrorText(error, "请稍后重试。"));
        showStatusError(error, "资产列表刷新失败，请稍后重试。");
      }
    });

    els.refreshCommunityBtn?.addEventListener("click", async () => {
      try {
        await loadCommunity({ resetPage: true });
        showToast("社区列表已刷新", "已获取最新公开作品。");
      } catch (error) {
        showToast("社区作品刷新失败", friendlyErrorText(error, "请稍后重试。"));
        showStatusError(error, "社区作品刷新失败，请稍后重试。");
      }
    });

    [els.activeProjectList, els.completedProjectList, els.newScriptProjectList].forEach((container) => container?.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button) return;
      const projectId = button.dataset.projectId;
      try {
        if (button.dataset.action === "select-project") {
          // 框架项目直接跳转到框架策划器，不在工作台打开
          const existing = (state.projects || []).find((p) => String(p.project_id) === String(projectId));
          if (existing && isFrameworkPlannerAsset(existing)) {
            window.location.href = frameworkPlannerAssetUrl(projectId);
            return;
          }
          await loadProjectDetail(projectId, { restoreInputs: true, scroll: false });
        } else if (button.dataset.action === "open-sitcom-asset") {
          await openSitcomAsset(projectId);
        } else if (button.dataset.action === "delete-asset") {
          await deleteAsset(projectId, button);
        }
      } catch (error) {
        const fallback = button.dataset.action === "delete-asset"
          ? "资产操作失败，请稍后重试。"
          : "项目加载失败，请稍后重试。";
        showStatusError(error, fallback);
        showToast(button.dataset.action === "delete-asset" ? "资产操作失败" : "项目加载失败", friendlyErrorText(error, "请稍后重试。"));
      }
    }));

    els.assetsList?.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button) return;
      const projectId = button.dataset.projectId;
      try {
        if (button.dataset.action === "retry-list") {
          await loadAssets({ resetPage: true });
        } else if (button.dataset.action === "load-more-assets") {
          state.assetsPage += 1;
          renderAssets(state.assets);
        } else if (button.dataset.action === "open-framework-asset") {
          window.location.href = frameworkPlannerAssetUrl(projectId);
          return;
        } else if (button.dataset.action === "open-project") {
          const existing = (state.assets || []).find((item) => String(item.project_id) === String(projectId))
            || (state.projects || []).find((item) => String(item.project_id) === String(projectId));
          if (existing && isFrameworkPlannerAsset(existing)) {
            window.location.href = frameworkPlannerAssetUrl(projectId);
            return;
          }
          closeProfilePanel();
          await loadProjectDetail(projectId, { restoreInputs: true, scroll: false });
        } else if (button.dataset.action === "open-sitcom-asset") {
          await openSitcomAsset(projectId);
        } else if (button.dataset.action === "edit-asset") {
          await openAssetEditor(projectId);
        } else if (button.dataset.action === "toggle-privacy") {
          await toggleAssetPrivacy(projectId, button.dataset.visibility);
        } else if (button.dataset.action === "continue-task") {
          await continueAssetTask(button.dataset.taskId, projectId, button);
        } else if (button.dataset.action === "stop-task") {
          await stopAssetTask(button.dataset.taskId, projectId, button);
        } else if (button.dataset.action === "delete-task") {
          await deleteTask(button.dataset.taskId, projectId, button);
        } else if (button.dataset.action === "delete-asset") {
          await deleteAsset(projectId, button);
        }
      } catch (error) {
        showToast("资产操作失败", friendlyErrorText(error, "请稍后重试。"));
        showStatusError(error, "资产操作失败，请稍后重试。");
      }
    });

    els.assetDeleteBackdrop?.addEventListener("click", () => {
      settleAssetDeleteDialog(false);
    });
    els.cancelDeleteAssetBtn?.addEventListener("click", () => {
      settleAssetDeleteDialog(false);
    });
    els.confirmDeleteAssetBtn?.addEventListener("click", () => {
      settleAssetDeleteDialog(true);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && state.assetDeleteConfirmResolver) {
        settleAssetDeleteDialog(false);
      }
    });

    els.communityList?.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button) return;
      try {
        if (button.dataset.action === "retry-list") {
          await loadCommunity({ resetPage: true });
        } else if (button.dataset.action === "load-more-community") {
          state.communityPage += 1;
          renderCommunity(state.communityAssets);
        }
      } catch (error) {
        showToast("社区列表操作失败", friendlyErrorText(error, "请稍后重试。"));
        showStatusError(error, "社区作品刷新失败，请稍后重试。");
      }
    });

    els.saveAssetEditBtn?.addEventListener("click", async () => {
      try {
        await withActionLoading("saveAsset", els.saveAssetEditBtn, "保存中...", async () => {
          await saveAssetEdit();
        });
      } catch (error) {
        showToast("资产保存失败", friendlyErrorText(error, "请稍后重试。"));
        showStatusError(error, "资产保存失败，请稍后重试。");
      }
    });

    els.cancelAssetEditBtn?.addEventListener("click", closeAssetEditor);

    els.toolList?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-tool-key]");
      if (!button) return;
      openToolPanel(button.dataset.toolKey || state.activeTool);
    });

    els.toolHistoryList?.addEventListener("click", async (event) => {
      const button = event.target.closest('[data-action="open-tool-history"]');
      if (!button) return;
      try {
        await openToolHistoryRecord(
          button.dataset.toolKey || state.activeTool,
          button.dataset.projectId || "",
        );
      } catch (error) {
        showToast("历史记录打开失败", friendlyErrorText(error, "请稍后重试。"));
      }
    });

    els.chatTranscript?.addEventListener("click", (event) => {
      const toggleButton = event.target.closest("[data-chat-action='toggle-user-prompt']");
      if (toggleButton) {
        const promptKey = toggleButton.dataset.promptKey || "";
        if (promptKey) {
          state.expandedUserPrompts[promptKey] = !state.expandedUserPrompts[promptKey];
          renderChatTranscript(state.latestSnapshot);
        }
        return;
      }
      const copyButton = event.target.closest("[data-chat-action='copy-message']");
      if (copyButton) {
        const kind = copyButton.dataset.copyKind || "";
        const key = copyButton.dataset.copyKey || "";
        let text = "";
        if (kind === "user_prompt") {
          text = userPromptCopyText(state.latestSnapshot);
        } else if (kind === "stage_output") {
          text = stageMessageCopyText(state.latestSnapshot, key);
        } else if (kind === "thinking_state") {
          text = thinkingMessageCopyText(state.latestSnapshot);
        }
        copyTextToClipboard(text)
          .then((copied) => {
            if (copied) {
              flashCopyButton(copyButton, "已复制");
              showCopyToast();
            } else {
              flashCopyButton(copyButton, "复制失败");
              showToast("复制失败", "当前消息暂时没有可复制的文本。");
            }
          })
          .catch((error) => {
            flashCopyButton(copyButton, "复制失败");
            showToast("复制失败", friendlyErrorText(error, "请稍后重试。"));
          });
        return;
      }
      const button = event.target.closest("[data-suggestion-tool]");
      if (!button) return;
      openToolPanel(button.dataset.suggestionTool || state.activeTool);
    });

    els.closeToolPanelBtn?.addEventListener("click", closeToolPanel);
    els.closeCommunityPanelBtn?.addEventListener("click", closeCommunityPanel);
    els.downloadToolBtn?.addEventListener("click", downloadActiveToolResult);
    els.toolOutputBox?.addEventListener("click", async (event) => {
      const pointNode = event.target.closest("[data-action='show-audit-point']");
      if (pointNode) {
        const wrap = pointNode.closest("[data-audit-chart]");
        const card = wrap?.querySelector("[data-audit-point-card]");
        if (!wrap || !card) return;
        const points = JSON.parse(wrap.dataset.auditChart || "[]");
        const index = Number(pointNode.dataset.pointIndex || 0);
        card.innerHTML = renderAuditPointSticky(points[index], index);
        card.hidden = false;
        return;
      }
      const actionButton = event.target.closest("[data-action]");
      const action = actionButton?.dataset.action || "";
      if (action === "close-audit-point") {
        const card = actionButton.closest("[data-audit-point-card]");
        if (card) card.hidden = true;
        return;
      }
      if (action === "toggle-audit-popover") {
        const popover = actionButton.nextElementSibling;
        if (popover?.matches("[data-audit-popover]")) {
          const shouldOpen = popover.hidden;
          popover.hidden = !shouldOpen;
          actionButton.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
          const icon = actionButton.querySelector("b");
          if (icon) icon.textContent = shouldOpen ? "⌃" : "⌄";
        }
        return;
      }
      if (action === "close-audit-popover") {
        const popover = actionButton.closest("[data-audit-popover]");
        if (popover) popover.hidden = true;
        return;
      }
      try {
        if (action === "save-audit-asset") {
          await saveActiveHotReviewResult(actionButton);
        } else if (action === "download-audit-txt") {
          const text = activeAuditReportText();
          if (!text) throw new Error("暂无可导出的报告正文。");
          downloadTextFile(text, `${activeAuditReportTitle()}.txt`);
          showToast("TXT 已开始下载", `${activeAuditReportTitle()}.txt`);
        } else if (action === "download-audit-docx") {
          await downloadAuditDocx();
          showToast("DOCX 已开始下载", `${activeAuditReportTitle()}.docx`);
        } else if (action === "download-audit-image") {
          await downloadAuditImage();
          showToast("长图已开始下载", `${activeAuditReportTitle()}_爆款文审核长图.png`);
        }
      } catch (error) {
        showToast(action === "save-audit-asset" ? "保存失败" : "导出失败", friendlyErrorText(error, "请稍后重试。"));
      }
    });
    document.addEventListener("click", (event) => {
      if (event.target.closest(".audit-ecg-node, .audit-point-sticky")) return;
      document.querySelectorAll("[data-audit-point-card]").forEach((item) => { item.hidden = true; });
    });

    els.runToolBtn?.addEventListener("click", async () => {
      try {
        await withActionLoading("runTool", els.runToolBtn, "运行中...", async () => {
          await runActiveTool();
        });
      } catch (error) {
        showToast("工具执行失败", friendlyErrorText(error, "请查看后台日志。"));
        showToolError(error, "工具执行失败，请查看后台日志。");
      }
    });

    els.startBtn.addEventListener("click", async () => {
      try {
        await withActionLoading("start", els.startBtn, "启动中...", async () => {
          await startGeneration();
        });
      } catch (error) {
        showToast("启动任务失败", friendlyErrorText(error, "请稍后重试。"));
        showStatusError(error, "启动任务失败，请稍后重试。");
      }
    });

    els.pauseBtn.addEventListener("click", async () => {
      try {
        await withActionLoading("pause", els.pauseBtn, "暂停中...", async () => {
          await pauseTask();
        });
      } catch (error) {
        showToast("暂停失败", friendlyErrorText(error, "请稍后重试。"));
        showStatusError(error, "暂停失败，请稍后重试。");
      }
    });

    els.resumeBtn.addEventListener("click", async () => {
      try {
        await withActionLoading("resume", els.resumeBtn, "继续中...", async () => {
          await resumeTask();
        });
      } catch (error) {
        showToast("继续失败", friendlyErrorText(error, "请稍后重试。"));
        showStatusError(error, "继续失败，请稍后重试。");
      }
    });

    els.terminateBtn.addEventListener("click", async () => {
      try {
        await withActionLoading("terminate", els.terminateBtn, "终止中...", async () => {
          await terminateTask();
        });
      } catch (error) {
        showToast("终止失败", friendlyErrorText(error, "请稍后重试。"));
        showStatusError(error, "终止失败，请稍后重试。");
      }
    });

    els.confirmCompletionBtn?.addEventListener("click", async () => {
      try {
        await withActionLoading("confirmCompletion", els.confirmCompletionBtn, "确认中...", async () => {
          await confirmCompletion();
        });
      } catch (error) {
        showToast("确认完成失败", friendlyErrorText(error, "请稍后重试。"));
        showStatusError(error, "确认完成失败，请稍后重试。");
      }
    });

    els.rollbackStageSelect?.addEventListener("change", () => {
      const selectedStage = els.rollbackStageSelect?.value || "";
      if (!["hooks", "dialogues", "script"].includes(selectedStage) && els.rollbackScriptStartSelect) {
        els.rollbackScriptStartSelect.value = "";
      }
      const defaultScriptStart = ["hooks", "dialogues", "script"].includes(selectedStage)
        ? String(state.latestSnapshot?.rollback_start_episode_default || "")
        : "";
      renderRollbackScriptStartOptions(
        rollbackStageRangeOptions(state.latestSnapshot, selectedStage),
        els.rollbackScriptStartSelect?.value || defaultScriptStart
      );
      syncButtons();
    });
    els.rollbackScriptStartSelect?.addEventListener("change", syncButtons);

    els.rollbackRewriteBtn?.addEventListener("click", async () => {
      try {
        await withActionLoading("rollback", els.rollbackRewriteBtn, "回退中...", async () => {
          await rollbackRewrite();
        });
      } catch (error) {
        showToast("阶段回退失败", friendlyErrorText(error, "请稍后重试。"));
        showStatusError(error, "阶段回退失败，请稍后重试。");
      }
    });

    els.clearBtn.addEventListener("click", async () => {
      try {
        const ok = window.confirm("确认清空当前编辑表单吗？后台任务和剧本资产会保留。");
        if (!ok) return;
        clearCurrentInput();
      } catch (error) {
        showStatusError(error, "清空输入失败，请稍后重试。");
      }
    });

    els.saveBtn.addEventListener("click", async () => {
      await withActionLoading("download", els.saveBtn, "准备中...", async () => {
        saveFinalScript();
      });
    });
  }

  function bindAssetSubnav() {
    if (!els.assetSubnav || !els.assetDetailPanel) return;
    const buttons = [...els.assetSubnav.querySelectorAll("[data-asset-panel]")];
    const views = [...els.assetDetailPanel.querySelectorAll(".asset-detail-view")];

    const activate = (button) => {
      const panelId = button?.dataset?.assetPanel;
      const target = panelId ? document.getElementById(panelId) : null;
      if (!target) return;
      const alreadyActive = button.getAttribute("aria-selected") === "true" && !els.assetDetailPanel.hidden;

      buttons.forEach((item) => {
        const active = item === button && !alreadyActive;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-selected", active ? "true" : "false");
      });
      views.forEach((view) => {
        view.hidden = alreadyActive || view !== target;
        view.classList.toggle("is-active", !alreadyActive && view === target);
      });
      els.assetDetailPanel.hidden = alreadyActive;
      if (!alreadyActive) target.scrollTop = 0;
    };

    buttons.forEach((button) => button.addEventListener("click", () => activate(button)));
  }
  async function init() {
    restoreDraft();
    restoreKnowledgeDraft();
    syncExpectationInputHeight();
    restoreSidebarCollapsed();
    bindAssetSubnav();
    state.toolDefinitions = { ...DEFAULT_TOOL_DEFINITIONS };
    renderToolList();
    renderToolForm(state.activeTool);
    bindInputs();
    bindActions();
    renderSnapshot(null);

    try {
      await loadModels();
      await loadTools();
      await loadUserKnowledgeTags();
      await restoreWorkspace();
      await loadAssets();
      await loadCommunity();
      if (hasConfiguredModel()) {
        els.formHint.textContent = `当前流程：写剧本正文。已登录 ${window.scriptMakerConfig.username}，请先填写故事期待、角色数量和总集数。`;
      } else if (!isAuthenticated()) {
        els.formHint.textContent = "登录后即可开始创作。";
      } else {
        els.formHint.textContent = "当前没有可用模型。";
      }
    } catch (error) {
      showStatusError(error, "页面初始化失败，请稍后刷新重试。");
      els.formHint.textContent = "初始化失败，请检查服务配置。";
    }
  }


  async function openHotReviewAssetFromList(assetKey) {
    if (!assetKey) return false;
    let asset = findOwnedAsset(assetKey)
      || state.assets.find((item) => String(hotReviewAssetKeyV5(item) || item.project_id || item.id || "") === String(assetKey))
      || state.projects.find((item) => String(hotReviewAssetKeyV5(item) || item.project_id || item.id || "") === String(assetKey))
      || null;

    const projectId = Number(asset?.project_id || assetKey);
    if (Number.isFinite(projectId) && projectId > 0) {
      try {
        const detail = await requestJson(`/api/projects/${encodeURIComponent(projectId)}`);
        const detailAsset = detail.project || detail.asset || null;
        if (detailAsset) {
          asset = { ...(asset || {}), ...detailAsset };
          mergeProjectListAsset(asset);
        }
      } catch (_) {
        // 详情失败时保留列表快照。
      }
    }

    if (!asset) {
      showToast("资产未找到", "请刷新资产列表后重试。");
      return false;
    }

    const payload = asset.input_payload || asset.request_payload || asset.tool_request || asset.tool_request_payload || {};
    const reviewText = String(payload.review_text || payload.text || payload.input || "").trim();
    state.toolDrafts.hot_review = {
      ...ensureToolDraft("hot_review"),
      review_text: reviewText,
      text: reviewText
    };

    state.toolResults.hot_review = normalizeScriptAuditEcgResult(toolResultFromAsset(asset));
    persistHotReviewSession(state.toolResults.hot_review);
    openToolPanel("hot_review");
    renderToolForm("hot_review");
    renderToolOutput("hot_review");
    return true;
  }

  async function restoreHotReviewPanelFromSession(assetKey = "") {
    const session = readHotReviewSession();
    const targetKey = String(assetKey || session?.assetKey || "").trim();
    if (targetKey && await openHotReviewAssetFromList(targetKey)) {
      return true;
    }
    if (session?.result) {
      state.toolDrafts.hot_review = {
        ...ensureToolDraft("hot_review"),
        ...(session.draft || {}),
      };
      state.toolResults.hot_review = normalizeScriptAuditEcgResult(session.result);
      openToolPanel("hot_review");
      renderToolForm("hot_review");
      renderToolOutput("hot_review");
      return true;
    }
    return false;
  }





  document.addEventListener("click", (event) => {
    const deleteButton = event.target?.closest?.('[data-action="delete-hot-review-asset"]');
    if (deleteButton) {
      event.preventDefault();
      deleteAsset(deleteButton.dataset.projectId || "", deleteButton).catch((error) => {
        showToast("删除失败", friendlyErrorText(error, "请稍后重试。"));
      });
      return;
    }
    const button = event.target?.closest?.('[data-action="open-hot-review-asset"]');
    if (!button) return;
    event.preventDefault();
    openHotReviewAssetFromList(button.dataset.hotReviewAssetKey || button.dataset.assetKey || button.dataset.projectId || "");
  });

  window.addEventListener("DOMContentLoaded", init);
})();
