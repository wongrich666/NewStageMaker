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
    userKnowledge: `scriptmaker.web.${userKey}.userKnowledge`
  };

  const POLL_INTERVAL = 1500;
  const MAX_EXPECTATION_LINES = 5;
  const RUNNING_STATUSES = new Set(["pending", "running", "pausing"]);
  const RESUMABLE_STATUSES = new Set(["paused", "pausing", "failed", "terminated"]);
  const TERMINATABLE_STATUSES = new Set(["pending", "running", "pausing", "paused", "failed"]);
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
    activeTool: "character_reskin",
    toolDrafts: {},
    toolResults: {},
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
    reskin: {
      key: "reskin",
      label: "换皮",
      help: "保留原剧本骨架，按目标风格做整套换皮。",
      fields: [
        { name: "title", label: "剧本标题", type: "input", placeholder: "新剧本标题。", required: true },
        { name: "source_outline", label: "源剧本梗概", type: "textarea", placeholder: "源故事梗概。", required: true },
        { name: "core_scenes", label: "源剧本核心场景", type: "textarea", placeholder: "可选，源剧本核心场景。", required: false },
        { name: "source_characters", label: "源剧本人设", type: "textarea", placeholder: "源人物小传。", required: true },
        { name: "source_script", label: "源剧本正文", type: "textarea", placeholder: "源剧本正文。", required: true },
        { name: "target_style", label: "目标风格", type: "textarea", placeholder: "希望换成的题材、风格、爽点方向。", required: true },
        { name: "total_episodes", label: "总集数", type: "number", placeholder: "例如 60。", required: true },
        { name: "episode_word_count", label: "每集字数", type: "number", placeholder: "例如 500。", required: true }
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
        { name: "characters", label: "人物小传", type: "textarea", placeholder: "需要换皮的人物小传。", required: true },
        { name: "core_scenes", label: "核心场景", type: "textarea", placeholder: "核心场景。", required: true },
        { name: "source_script", label: "原剧本正文", type: "textarea", placeholder: "原剧本正文。", required: true },
        { name: "total_episodes", label: "总集数", type: "number", placeholder: "总集数。", required: true },
        { name: "episode_word_count", label: "每集正文字数", type: "number", placeholder: "每集字数。", required: true }
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

  function buildWorkspaceUrl({ projectId = null, fresh = false, scriptFormatMode = "" } = {}) {
    const url = currentUrl();
    const basePath = window.scriptMakerConfig.workspaceUrl || url.pathname;
    url.pathname = basePath;
    url.searchParams.delete("project_id");
    url.searchParams.delete("mode");
    url.searchParams.delete("section");
    url.searchParams.delete("panel");
    url.searchParams.delete("script_format_mode");
    if (projectId) {
      url.searchParams.set("project_id", String(projectId));
    } else if (fresh) {
      url.searchParams.set("mode", "new");
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

  function openWorkspaceInNewPage({ projectId = null, fresh = false, scriptFormatMode = "" } = {}) {
    window.open(buildWorkspaceUrl({ projectId, fresh, scriptFormatMode }), "_blank", "noopener");
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
    els.workspaceSidebar.classList.toggle("is-collapsed", Boolean(collapsed));
    els.workspaceShell?.classList.toggle("sidebar-collapsed", Boolean(collapsed));
    draftStorage.setItem(STORAGE.sidebarCollapsed, collapsed ? "1" : "0");
  }

  function restoreSidebarCollapsed() {
    applySidebarCollapsed(draftStorage.getItem(STORAGE.sidebarCollapsed) === "1");
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

  function friendlyErrorText(error, fallback = "操作失败，请稍后重试。") {
    const text = String(error?.message || "").trim();
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

  function showToolError(error, fallback = "工具执行失败，请稍后重试。") {
    if (!els.toolOutputBox) return;
    els.toolOutputBox.textContent = friendlyErrorText(error, fallback);
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
      framework_scene_dictionary: "正在生成框架转剧本：场景字典提炼",
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
      framework_scene_dictionary: "框架转剧本：场景字典提炼",
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
      els.saveAssetEditBtn.disabled = isActionLoading("saveAsset") || !assetValidation.valid;
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
    return definitions[toolKey] || definitions.character_reskin || Object.values(definitions)[0];
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
    const payload = collectToolPayload();
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
    document.querySelectorAll("[data-tool-field]").forEach((field) => {
      const key = field.dataset.toolField;
      currentDraft[key] = field.type === "number" ? String(field.value || "").trim() : String(field.value || "");
    });
    state.toolDrafts[tool.key] = currentDraft;
  }

  function currentToolResult(toolKey = state.activeTool) {
    return state.toolResults[toolKey] || null;
  }

  function isToolAsset(assetLike) {
    return String(assetLike?.asset_kind || "").trim() === "tool_result";
  }

  function assetTypeLabel(assetLike) {
    return isToolAsset(assetLike) ? "辅助工具" : "剧本资产";
  }

  function assetWorkflowLabel(assetLike) {
    return String(assetLike?.tool_label || "").trim() || assetTypeLabel(assetLike);
  }

  function downloadToolButtonEnabled(toolKey = state.activeTool) {
    const result = currentToolResult(toolKey);
    return Boolean(result?.text && result?.filename);
  }

  function renderToolOutput(toolKey = state.activeTool, fallbackText = "") {
    const result = currentToolResult(toolKey);
    if (els.toolOutputBox) {
      els.toolOutputBox.textContent = result?.text
        || fallbackText
        || (isAuthenticated()
          ? "这里会显示辅助工具结果。"
          : "登录后可使用辅助工具。");
    }
    if (els.downloadToolBtn) {
      const shouldShow = Boolean(result?.text && result?.filename);
      els.downloadToolBtn.classList.toggle("hidden", !shouldShow);
      els.downloadToolBtn.disabled = !shouldShow || isActionLoading("runTool");
      if (shouldShow) {
        els.downloadToolBtn.textContent = "下载 TXT";
      }
    }
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

  function renderToolList() {
    if (!els.toolList) return;
    const definitions = Object.values(toolDefinitions()).filter((tool) => tool.key !== "new_framework");
    els.toolList.innerHTML = definitions.map((tool) => `
      <button
        class="tool-shortcut${tool.key === state.activeTool ? " active" : ""}"
        type="button"
        data-tool-key="${escapeHtml(tool.key)}"
      >
        <span>${escapeHtml(tool.label)}</span>
        <small>${escapeHtml(
          !isAuthenticated()
            ? "登录后可运行"
            : (tool.configured ? "可直接运行" : "待配置 API Key")
        )}</small>
      </button>
    `).join("");
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
    updateUrlParams((params) => params.set("section", "tools"));
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
      state.activeTool = Object.keys(toolDefinitions())[0] || "character_reskin";
    }
    renderToolList();
    renderToolForm(state.activeTool);
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
    syncButtons();
  }

  function collectToolPayload() {
    const payload = {};
    document.querySelectorAll("[data-tool-field]").forEach((field) => {
      const key = field.dataset.toolField;
      payload[key] = field.type === "number" ? Number(field.value || 0) : field.value.trim();
    });
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
    const response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        ...(options.headers || {})
      },
      ...options
    });
    const data = await response.json().catch(() => null);
    if (response.status === 401) {
      window.location.href = "/login";
      throw new Error("请先登录。");
    }
    if (!response.ok || !data?.success) {
      throw new Error(data?.message || `请求失败：${response.status}`);
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
      els.knowledgeTagList.innerHTML = tags.map((tag) => {
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
      }).join("");
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

  function pickPreferredProjectId(projects) {
    if (!projects.length) return null;
    const running = projects.find((item) => RUNNING_STATUSES.has(item.status));
    const paused = projects.find((item) => item.status === "paused");
    return Number((running || paused || projects[0]).project_id || 0) || null;
  }

  // 把后台项目压成简洁任务列表，方便在同一账号下快速切换工作台。
  function renderProjectList(projects) {
    if (!els.activeProjectList || !els.completedProjectList) return;
    if (!isAuthenticated()) {
      const message = emptyCard("登录后查看任务");
      els.activeProjectList.innerHTML = message;
      els.completedProjectList.innerHTML = message;
      if (els.activeProjectCount) els.activeProjectCount.textContent = "0";
      if (els.completedProjectCount) els.completedProjectCount.textContent = "0";
      return;
    }

    const completedProjects = projects.filter((item) => item.status === "completed");
    const activeProjects = projects.filter((item) => item.status !== "completed");

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
        return `
          <div class="workspace-pick-row">
            <button
              class="workspace-pick${activeClass}${statusClass}"
              type="button"
              data-action="select-project"
              data-project-id="${escapeHtml(item.project_id)}"
              title="${escapeHtml(projectTooltip(item))}"
            >
              <span class="workspace-pick-main">
                <span class="workspace-pick-title">${escapeHtml(projectDisplayTitle(item))}</span>
                <span class="workspace-pick-meta">${escapeHtml(`${Number(item.progress_percent || 0)}% · ${item.current_stage_label || statusLabel(item.status)}`)}</span>
              </span>
              <span class="workspace-pick-state">${escapeHtml(statusLabel(item.status))}</span>
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

    els.activeProjectList.innerHTML = renderCompactItems(activeProjects, "当前没有未完成剧本。");
    els.completedProjectList.innerHTML = renderCompactItems(completedProjects, "当前还没有自然完成的剧本。");
    if (els.activeProjectCount) {
      els.activeProjectCount.textContent = String(activeProjects.length);
    }
    if (els.completedProjectCount) {
      els.completedProjectCount.textContent = String(completedProjects.length);
    }
  }

  function workspaceFolders() {
    return [els.activeWorkspaceFolder, els.completedWorkspaceFolder].filter(Boolean);
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
      ? (state.projectId || readSelectedProjectId() || (freshWorkspace ? null : pickPreferredProjectId(state.projects)))
      : state.projectId;

    if (targetProjectId && !state.projects.some((item) => Number(item.project_id) === Number(targetProjectId))) {
      targetProjectId = pickPreferredProjectId(state.projects);
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
      ["老剧本平台资产", assets.filter((item) => assetCategory(item) === "old_script")],
      ["框架资产", assets.filter((item) => assetCategory(item) === "framework")],
      ["新剧本资产", assets.filter((item) => assetCategory(item) === "new_script")],
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
        <h3>${escapeHtml(projectDisplayTitle(item))}</h3>
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
            ${isToolAsset(item) ? "" : `<button class="btn btn-secondary" data-action="open-project" data-project-id="${escapeHtml(item.project_id)}">载入工作台</button>`}
            ${isToolAsset(item) ? "" : `<button class="btn btn-neutral" data-action="open-project-page" data-project-id="${escapeHtml(item.project_id)}">打开查看</button>`}
            <button class="btn btn-edit" data-action="edit-asset" data-project-id="${escapeHtml(item.project_id)}">打开查看</button>
            ${assetCategory(item) === "framework" ? `<a class="btn btn-secondary" href="/framework-to-script?framework_asset_id=${encodeURIComponent(item.project_id)}${currentAuthToken() ? `&auth_token=${encodeURIComponent(currentAuthToken())}` : ""}">进入框架到剧本</a>` : ""}
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
    if (explicit === "legacy_script") return "old_script";
    if (["old_script", "framework", "new_script"].includes(explicit)) return explicit;
    const assetKind = String(item.asset_kind || "").trim();
    const input = item.input_payload && typeof item.input_payload === "object" ? item.input_payload : {};
    const scriptMode = String(item.script_format_mode || input.script_format_mode || "").trim();
    if (assetKind === "framework_planner") return "framework";
    if (assetKind === "framework_to_script" || scriptMode === "framework_to_script" || input.framework_to_script === true) return "new_script";
    return "old_script";
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
    state.editingProjectId = Number(projectId);
    state.editingProjectStatus = String(project.status || "");
    state.editingAssetKind = String(project.asset_kind || "").trim();
    state.editingAssetLocked = Boolean(project.completion_confirmed && state.editingAssetKind !== "tool_result");
    state.assetEditMode = "view";
    state.assetDirty = false;
    const locked = true;
    els.editAssetTitle.value = project.title || input.title || "";
    els.editAssetSummary.value = formatDisplayValue(input.story_outline || artifacts.story_outline || "");
    els.editAssetPrivacy.value = project.visibility || "private";
    els.editAssetFinal.value = state.editingProjectStatus === "completed"
      ? formatDisplayValue(artifacts.final_output_text || artifacts.final_script || "")
      : "";
    if (els.editAssetTitle) els.editAssetTitle.disabled = locked;
    if (els.editAssetSummary) els.editAssetSummary.disabled = locked;
    if (els.editAssetFinal) els.editAssetFinal.disabled = locked;
    if (els.editAssetPrivacy) els.editAssetPrivacy.disabled = true;
    if (els.saveAssetEditBtn) {
      els.saveAssetEditBtn.disabled = false;
      els.saveAssetEditBtn.textContent = "修改";
    }
    els.assetEditor.classList.remove("hidden");
    els.assetEditor.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function saveAssetEdit() {
    if (!requireLogin() || !state.editingProjectId) return;
    if (state.assetEditMode !== "edit") {
      state.assetEditMode = "edit";
      state.assetDirty = false;
      [els.editAssetTitle, els.editAssetSummary, els.editAssetPrivacy, els.editAssetFinal].forEach((field) => {
        if (field) field.disabled = false;
      });
      if (els.saveAssetEditBtn) els.saveAssetEditBtn.textContent = "应用修改";
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
    const payload = collectToolPayload();
    if (state.activeTool === "new_framework") {
      const projectTitle = projectTitleCandidate();
      if (projectTitle) {
        payload.project_title = projectTitle;
      }
    }
    state.toolResults[state.activeTool] = null;
    renderToolOutput(state.activeTool, "生成中，请稍候~");
    const data = await requestJson(currentToolRunUrl(state.activeTool), {
      method: "POST",
      body: JSON.stringify(payload)
    });
    const result = data.result || data;
    const output = result.output ?? data.output ?? result.result ?? "";
    const text = String(result.text || data.text || formatToolOutput(output) || "").trim();
    const filename = String(result.filename || data.filename || "").trim();
    const assetSaved = Boolean(result.asset_saved || data.asset_saved);
    const assetSaveError = String(result.asset_save_error || data.asset_save_error || "").trim();
    state.toolResults[state.activeTool] = {
      text,
      filename,
      outputType: result.output_type || data.output_type || "text",
      assetSaved,
      savedAsset: result.saved_asset || data.saved_asset || null
    };
    renderToolOutput(state.activeTool);
    if (assetSaved) {
      try {
        await loadAssets();
      } catch (_) {
        // 结果已经生成并写入后端，不阻断当前工具面板的成功态展示。
      }
    }
    showToast(
      "辅助工具运行完成",
      assetSaveError
        ? `${result.title || toolConfig(state.activeTool)?.label || "当前工具"} 已返回结果，但写入用户资产失败了。`
        : (assetSaved
          ? `${result.title || toolConfig(state.activeTool)?.label || "当前工具"} 已返回结果，并已保存到用户资产。`
          : `${result.title || toolConfig(state.activeTool)?.label || "当前工具"} 已返回结果。`),
    );
  }

  function downloadActiveToolResult() {
    const result = currentToolResult();
    const tool = toolConfig(state.activeTool);
    const toolLabel = tool?.label || "辅助工具结果";
    if (!result?.text || !result?.filename) {
      showToast("暂无可下载内容", `请先成功生成${toolLabel}。`);
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
        if (els.assistantToolsFolder) {
          els.assistantToolsFolder.open = true;
        }
        openToolPanel(state.activeTool);
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

    [els.activeProjectList, els.completedProjectList].forEach((container) => container?.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button) return;
      const projectId = button.dataset.projectId;
      try {
        if (button.dataset.action === "select-project") {
          await loadProjectDetail(projectId, { restoreInputs: true, scroll: false });
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
        } else if (button.dataset.action === "open-project") {
          closeProfilePanel();
          await loadProjectDetail(projectId, { restoreInputs: true, scroll: false });
        } else if (button.dataset.action === "open-project-page") {
          openWorkspaceInNewPage({ projectId });
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

  async function init() {
    restoreDraft();
    restoreKnowledgeDraft();
    syncExpectationInputHeight();
    restoreSidebarCollapsed();
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

  window.addEventListener("DOMContentLoaded", init);
})();
