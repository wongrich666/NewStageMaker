(() => {
  "use strict";

  const userKey = `user.${window.scriptMakerConfig.userId || "anon"}`;
  const draftStorage = window.localStorage;
  const pageStorage = window.sessionStorage;
  const STORAGE = {
    draft: `scriptmaker.web.${userKey}.draft`,
    selectedProjectId: `scriptmaker.web.${userKey}.selectedProjectId`,
    modelId: `scriptmaker.web.${userKey}.modelId`,
    sidebarCollapsed: `scriptmaker.web.${userKey}.sidebarCollapsed`
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
    toolList: $("toolList"),
    toolPanel: $("toolPanel"),
    toolPanelTitle: $("toolPanelTitle"),
    closeToolPanelBtn: $("closeToolPanelBtn"),
    modelSelect: $("modelSelect"),
    expectationInput: $("expectationInput"),
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
    newScriptBtn: $("newScriptBtn"),
    viewAssetsBtn: $("viewAssetsBtn"),
    refreshAssetsBtn: $("refreshAssetsBtn"),
    refreshCommunityBtn: $("refreshCommunityBtn"),
    assetsList: $("assetsList"),
    communityList: $("communityList"),
    assetEditor: $("assetEditor"),
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
    toolOutputBox: $("toolOutputBox"),

    statusText: $("statusText"),
    messageText: $("messageText"),
    stageText: $("stageText"),
    waitDurationText: $("waitDurationText"),
    progressFill: $("progressFill"),
    progressText: $("progressText"),
    projectText: $("projectText"),
    taskText: $("taskText"),
    chatTranscript: $("chatTranscript"),
    outputTitle: $("outputTitle"),
    outputNaturalBox: $("outputNaturalBox"),
    finalOutputBox: $("finalOutputBox")
  };

  const state = {
    projectId: null,
    taskId: null,
    status: "idle",
    pollTimer: null,
    availableModels: [],
    latestSnapshot: null,
    projects: [],
    projectStatusMap: {},
    projectsInitialized: false,
    assets: [],
    communityAssets: [],
    editingProjectId: null,
    editingProjectStatus: null,
    editingAssetLocked: false,
    toolDefinitions: {},
    activeTool: "character_reskin",
    loadingActions: {},
    assetsStatus: "idle",
    assetsError: "",
    assetsPage: 1,
    communityStatus: "idle",
    communityError: "",
    communityPage: 1,
    elapsedTimer: null,
    workspaceCollapseTimer: null,
    expandedUserPrompts: {}
  };

  const DEFAULT_TOOL_DEFINITIONS = {
    hot_review: {
      key: "hot_review",
      label: "爆款文审核",
      help: "提交一段文本，让工具返回审核意见。",
      fields: [
        { name: "text", label: "待检测文本", type: "textarea", placeholder: "粘贴要审核的正文、大纲或片段。", required: true }
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
    } else {
      url.searchParams.delete("project_id");
      if (!isFreshWorkspaceMode()) {
        url.searchParams.delete("mode");
      }
    }
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

  function buildWorkspaceUrl({ projectId = null, fresh = false } = {}) {
    const url = currentUrl();
    const basePath = window.scriptMakerConfig.workspaceUrl || url.pathname;
    url.pathname = basePath;
    url.searchParams.delete("project_id");
    url.searchParams.delete("mode");
    url.searchParams.delete("section");
    url.searchParams.delete("panel");
    if (projectId) {
      url.searchParams.set("project_id", String(projectId));
    } else if (fresh) {
      url.searchParams.set("mode", "new");
    }
    return `${url.pathname}${url.search}${url.hash}`;
  }

  function switchToFreshWorkspace() {
    state.projectId = null;
    state.taskId = null;
    state.status = "idle";
    state.latestSnapshot = null;
    persistSelectedProjectId(null);
    pageStorage.removeItem(STORAGE.selectedProjectId);
    const freshUrl = buildWorkspaceUrl({ fresh: true });
    window.history.replaceState({}, "", freshUrl);
    renderSnapshot(null);
  }

  function openWorkspaceInNewPage({ projectId = null, fresh = false } = {}) {
    window.open(buildWorkspaceUrl({ projectId, fresh }), "_blank", "noopener");
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
    };
    draftStorage.setItem(STORAGE.draft, JSON.stringify(draft));
    draftStorage.setItem(STORAGE.modelId, els.modelSelect.value || "");
  }

  function restoreDraft() {
    try {
      const raw = draftStorage.getItem(STORAGE.draft);
      if (!raw) return;
      const draft = JSON.parse(raw);
      els.expectationInput.value = draft.user_expectation || "";
      els.characterCountInput.value = draft.character_count || 5;
      els.episodeCountInput.value = draft.total_episodes || 10;
      syncExpectationInputHeight();
    } catch (_) {}
  }

  function clearDraft() {
    draftStorage.removeItem(STORAGE.draft);
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
    if (typeof value === "string") return value.trim();
    if (Array.isArray(value) || typeof value === "object") {
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
    const messages = [
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

    return messages.map((item) => ({
      ...item,
      natural: currentDisplayKey === item.key ? currentNatural : ""
    }));
  }

  // 内部阶段统一折叠成“思考分析”，避免把中间工作流细节直接暴露给用户。
  function thinkingStateFrom(snapshot) {
    if (!snapshot) return null;
    const normalizedCurrentStage = normalizeStageKey(snapshot.current_stage);
    const visibleMessages = visibleStageMessages(snapshot);
    const hasVisibleCurrentOutput = Boolean(
      visibleMessages.find((item) => item.key === normalizeStageKey(snapshot.display_stage_key))
    );
    const isRunning = RUNNING_STATUSES.has(snapshot.status);
    const shouldFoldToThinking = (
      normalizedCurrentStage === "internal"
      || (isRunning && !hasVisibleCurrentOutput)
    );
    if (!shouldFoldToThinking) return null;
    return {
      stageLabel: snapshot.current_stage_label || snapshot.display_stage_title || "正在处理",
      stateLabel: creationStatusLabel(snapshot),
      note: isRunning || snapshot.status === "completed" ? "" : (statusNoteFrom(snapshot) || "")
    };
  }

  function userPromptSummary(snapshot) {
    const inputPayload = snapshot?.input_payload || {};
    return {
      expectation: String(inputPayload.user_expectation || "").trim(),
      characterCount: Number(inputPayload.character_count || 0),
      totalEpisodes: Number(inputPayload.total_episodes || 0)
    };
  }

  function renderUserPromptBubble(snapshot) {
    const prompt = userPromptSummary(snapshot);
    const expectation = prompt.expectation || "还没有填写创作需求。";
    const lineCount = inputLineCount(expectation);
    const toggleKey = promptToggleKey(snapshot);
    const collapsed = lineCount > MAX_EXPECTATION_LINES && !state.expandedUserPrompts[toggleKey];
    const chips = [
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
              <span class="chat-bubble-meta">输入</span>
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
            ${chips.length ? `<div class="chat-user-meta">${chips.map((item) => `<span class="chat-chip">${escapeHtml(item)}</span>`).join("")}</div>` : ""}
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
              <span class="chat-bubble-meta">阶段产出</span>
            </div>
            <pre class="chat-bubble-content">${escapeHtml(message.output)}</pre>
            ${message.natural ? `
              <div class="chat-bubble-preview">
                <span class="chat-bubble-preview-label">阶段说明</span>
                <p class="chat-bubble-preview-text">${escapeHtml(message.natural)}</p>
              </div>
            ` : ""}
          </div>
        </div>
      </article>
    `;
  }

  function renderThinkingBubble(thinkingState) {
    const stageLabel = String(thinkingState.stageLabel || "处理中").trim();
    const stateLabel = String(thinkingState.stateLabel || "创作中").trim();
    const content = stateLabel === "创作中"
      ? stageLabel
      : stateLabel;
    return `
      <article class="chat-message system">
        <div class="chat-bubble-row">
          <div class="chat-avatar">AI</div>
          <div class="chat-bubble">
            <div class="chat-bubble-head">
              <span class="chat-bubble-title">${escapeHtml(stateLabel)}</span>
              <span class="chat-bubble-meta">${escapeHtml(stageLabel)}</span>
            </div>
            <div class="chat-bubble-content"><span>${escapeHtml(content)}</span></div>
            ${thinkingState.note ? `
              <div class="chat-bubble-preview">
                <span class="chat-bubble-preview-label">状态说明</span>
                <p class="chat-bubble-preview-text">${escapeHtml(thinkingState.note)}</p>
              </div>
            ` : ""}
          </div>
        </div>
      </article>
    `;
  }

  // 把当前项目压成对话流，只展示用户需要看的正式回复与一个统一的思考状态。
  function renderChatTranscript(snapshot) {
    if (!els.chatTranscript) return;
    if (!snapshot) {
      const suggestions = Object.values(toolDefinitions()).slice(0, 4).map((tool) => `
        <button class="chat-suggestion-btn" type="button" data-suggestion-tool="${escapeHtml(tool.key)}">
          ${escapeHtml(tool.label)}
        </button>
      `).join("");
      els.chatTranscript.innerHTML = `
        <section class="chat-empty-state">
          <strong>剧本创作需求请写在这里~</strong>
          <p>直接输入你的创作需求，平台会把剧本框架和剧本正文按对话流展示，中间过程统一显示创作状态。</p>
          <div class="chat-empty-tools">${suggestions}</div>
        </section>
      `;
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
    if (stageKey === "dialogues") return "选择角色对白开始重写的集数范围";
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

    const progress = Number(snapshot.progress_percent || 0);
    const displayPayload = stageDisplayPayload(snapshot);
    const finalOutput = displayPayload.output || (RUNNING_STATUSES.has(snapshot.status) ? "" : "暂无内容");
    const projectTitle = runtimeProjectDisplayTitle(snapshot);
    const statusMessage = statusNoteFrom(snapshot);

    els.statusText.textContent = statusLabel(snapshot.status);
    els.messageText.textContent = statusMessage;
    els.messageText.classList.toggle("hidden", !statusMessage);
    els.stageText.textContent = snapshot.current_stage_label || snapshot.display_stage_title || "正在处理";
    els.progressFill.style.width = `${progress}%`;
    els.progressText.textContent = `${progress}%`;
    els.projectText.textContent = `当前剧本：${projectTitle}`;
    els.projectText.title = `当前剧本：${projectTitle}`;
    els.taskText.textContent = `任务：${snapshot.task_id || "未创建"}`;
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
    els.clearBtn.disabled = !isAuthenticated();
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
    if (els.saveAssetEditBtn && state.editingProjectId) {
      els.saveAssetEditBtn.disabled = isActionLoading("saveAsset") || !assetValidation.valid;
    }
    if (!hasProject && !state.taskId && !hasConfiguredModel && els.formHint) {
      els.formHint.textContent = "当前没有可用模型。";
    } else if (!formValidation.valid && !hasProject && !RUNNING_STATUSES.has(state.status) && els.formHint) {
      els.formHint.textContent = formValidation.message || "请先完善输入。";
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
      return { valid: false, message: "剧本标题不能为空。" };
    }
    if (title.length > 120) {
      return { valid: false, message: "剧本标题请控制在 120 字以内。" };
    }
    if (summary.length > 20000) {
      return { valid: false, message: "故事梗概请控制在 20000 字以内。" };
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
      jsonFile: tool.json_file || tool.workflow_json_file || null,
      fields: Array.isArray(tool.fields) && tool.fields.length
        ? tool.fields.map((field) => ({
          name: field.name,
          label: field.label || field.name,
          type: field.type || "input",
          placeholder: field.placeholder || "",
          required: Boolean(field.required)
        }))
        : (fallback.fields || []).map((field) => ({ ...field }))
    };
  }

  function renderToolList() {
    if (!els.toolList) return;
    const definitions = Object.values(toolDefinitions());
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

  function openToolPanel(toolKey) {
    const tool = toolConfig(toolKey);
    state.activeTool = tool.key;
    if (els.assistantToolsFolder) {
      els.assistantToolsFolder.open = true;
    }
    renderToolList();
    renderToolForm(tool.key);
    els.toolPanel?.classList.remove("hidden");
    window.requestAnimationFrame(() => {
      els.toolPanel?.classList.add("panel-open");
      els.toolPanel?.scrollIntoView({ behavior: "smooth", block: "start" });
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
    if (els.toolPanelTitle) {
      els.toolPanelTitle.textContent = tool.label;
    }
    els.toolForms.innerHTML = `
      <div class="tool-form-head">
        <h3>${escapeHtml(tool.label)}</h3>
        <p>${escapeHtml(tool.help)}</p>
        ${tool.jsonFile ? `<small class="tool-form-meta">工作流：${escapeHtml(tool.jsonFile)}</small>` : ""}
      </div>
      <div class="tool-field-grid">
        ${tool.fields.map((field) => {
          if (field.type === "textarea") {
            return `
              <label class="field tool-field wide-field">
                <span>${escapeHtml(field.label)}${field.required ? " *" : ""}</span>
                <textarea data-tool-field="${escapeHtml(field.name)}" placeholder="${escapeHtml(field.placeholder)}"></textarea>
              </label>
            `;
          }
          return `
            <label class="field tool-field">
              <span>${escapeHtml(field.label)}${field.required ? " *" : ""}</span>
              <input data-tool-field="${escapeHtml(field.name)}" type="${escapeHtml(field.type === "number" ? "number" : "text")}" placeholder="${escapeHtml(field.placeholder)}">
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
    if (els.toolOutputBox) {
      els.toolOutputBox.textContent = !isAuthenticated()
        ? "登录后可使用辅助工具。"
        : (tool.configured
          ? "这里会显示辅助工具结果。"
          : "当前工具还未配置 API Key，配置后即可运行。");
    }
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
    saveDraft();
    const payload = buildPayload();
    const restartingCurrentProject = Boolean(
      isRestartingCurrentProject()
    );
    els.formHint.textContent = restartingCurrentProject
      ? "正在基于当前资产重新开始生成。"
      : "正在创建任务。";
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
      ? `，从第 ${selectedRange.start_episode || startEpisodeValue}-${selectedRange.end_episode || startEpisodeValue} 集开始`
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
    clearDraft();
    els.expectationInput.value = "";
    els.characterCountInput.value = 5;
    els.episodeCountInput.value = 10;
    syncExpectationInputHeight();
    syncButtons();
    els.formHint.textContent = "输入已清空。";
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
      els.assetsList.innerHTML = emptyCard("还没有剧本资产");
      return;
    }
    const { visibleItems, hasMore } = paginateItems(assets, state.assetsPage, 6);
    els.assetsList.innerHTML = visibleItems.map((item) => `
      <article class="asset-tile">
        <div class="asset-topline">
          <span class="status-pill ${item.status === "completed" ? "status-pill-completed" : ""}">${escapeHtml(statusLabel(item.status))}</span>
          ${item.completion_confirmed ? '<span class="status-pill status-pill-locked">已锁定</span>' : item.awaiting_user_confirmation ? '<span class="status-pill status-pill-pending">待确认</span>' : ""}
          <span class="status-pill ${item.visibility === "public" ? "status-pill-public" : "status-pill-private"}">${escapeHtml(visibilityLabel(item.visibility))}</span>
        </div>
        <h3>${escapeHtml(projectDisplayTitle(item))}</h3>
        <p>${escapeHtml(item.summary)}</p>
        <div class="asset-meta">
          <span>项目 ${escapeHtml(item.project_id)}</span>
          <span>${escapeHtml(item.current_stage_label || "待开始")}</span>
          <span>${escapeHtml(item.generated_episodes || 0)} / ${escapeHtml(item.total_episodes || 0)}</span>
        </div>
        <div class="asset-actions">
          <button class="btn btn-secondary" data-action="open-project" data-project-id="${escapeHtml(item.project_id)}">载入工作台</button>
          <button class="btn btn-neutral" data-action="open-project-page" data-project-id="${escapeHtml(item.project_id)}">新页面打开</button>
          ${item.completion_confirmed ? "" : `<button class="btn btn-edit" data-action="edit-asset" data-project-id="${escapeHtml(item.project_id)}">修改</button>`}
          <button class="btn ${item.visibility === "public" ? "btn-public" : "btn-ghost"}" data-action="toggle-privacy" data-project-id="${escapeHtml(item.project_id)}" data-visibility="${escapeHtml(item.visibility)}">${item.visibility === "public" ? "设为不公开" : "公开成品"}</button>
          <button class="btn btn-danger" data-action="delete-asset" data-project-id="${escapeHtml(item.project_id)}">删除</button>
        </div>
      </article>
    `).join("") + (hasMore ? `
      <div class="list-more-row">
        <button class="btn btn-secondary" type="button" data-action="load-more-assets">加载更多资产</button>
      </div>
    ` : "");
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
    state.editingAssetLocked = Boolean(project.completion_confirmed);
    const locked = state.editingAssetLocked;
    els.editAssetTitle.value = project.title || input.title || "";
    els.editAssetSummary.value = input.story_outline || artifacts.story_outline || "";
    els.editAssetPrivacy.value = project.visibility || "private";
    els.editAssetFinal.value = state.editingProjectStatus === "completed"
      ? (artifacts.final_output_text || artifacts.final_script || "")
      : "";
    if (els.editAssetTitle) els.editAssetTitle.disabled = locked;
    if (els.editAssetSummary) els.editAssetSummary.disabled = locked;
    if (els.editAssetFinal) els.editAssetFinal.disabled = locked;
    if (els.editAssetPrivacy) els.editAssetPrivacy.disabled = false;
    if (els.saveAssetEditBtn) {
      els.saveAssetEditBtn.disabled = false;
      els.saveAssetEditBtn.textContent = locked ? "仅保存公开设置" : "保存修改";
    }
    els.assetEditor.classList.remove("hidden");
    els.assetEditor.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function saveAssetEdit() {
    if (!requireLogin() || !state.editingProjectId) return;
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
    state.editingProjectId = null;
    state.editingProjectStatus = null;
    state.editingAssetLocked = false;
    [els.editAssetTitle, els.editAssetSummary, els.editAssetPrivacy, els.editAssetFinal].forEach((field) => {
      if (field) field.disabled = false;
    });
    if (els.editAssetTitle) els.editAssetTitle.value = "";
    if (els.editAssetSummary) els.editAssetSummary.value = "";
    if (els.editAssetPrivacy) els.editAssetPrivacy.value = "private";
    if (els.editAssetFinal) els.editAssetFinal.value = "";
    if (els.saveAssetEditBtn) {
      els.saveAssetEditBtn.disabled = false;
      els.saveAssetEditBtn.textContent = "保存修改";
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
    showToast(nextVisibility === "public" ? "已公开成品" : "已设为不公开", "资产可见性已经更新。");
  }

  async function deleteAsset(projectId) {
    if (!requireLogin()) return;
    const ok = window.confirm("确认删除这个剧本资产吗？删除后不可恢复。");
    if (!ok) return;
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
    showToast("资产已删除", "该剧本资产已从当前账号移除。");
  }

  async function runActiveTool() {
    if (!requireLogin()) return;
    const payload = collectToolPayload();
    els.toolOutputBox.textContent = "正在调用 FastGPT 工具，请稍候。";
    const data = await requestJson(`/api/tools/${state.activeTool}/run`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
    const result = data.result || data;
    const output = result.output ?? data.output ?? result.result ?? "";
    els.toolOutputBox.textContent = formatToolOutput(output);
    showToast(
      "辅助工具运行完成",
      `${result.title || toolConfig(state.activeTool)?.label || "当前工具"} 已返回结果。`,
    );
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
    els.toolForms?.addEventListener("input", syncButtons);
    els.toolForms?.addEventListener("change", syncButtons);
    [els.editAssetTitle, els.editAssetSummary, els.editAssetPrivacy, els.editAssetFinal].filter(Boolean).forEach((el) => {
      el.addEventListener("input", syncButtons);
      el.addEventListener("change", syncButtons);
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

    els.viewAssetsBtn?.addEventListener("click", () => {
      if (!requireLogin()) return;
      openProfilePanel();
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
        }
      } catch (error) {
        showStatusError(error, "项目加载失败，请稍后重试。");
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
        } else if (button.dataset.action === "delete-asset") {
          await deleteAsset(projectId);
        }
      } catch (error) {
        showToast("资产操作失败", friendlyErrorText(error, "请稍后重试。"));
        showStatusError(error, "资产操作失败，请稍后重试。");
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
      const button = event.target.closest("[data-suggestion-tool]");
      if (!button) return;
      openToolPanel(button.dataset.suggestionTool || state.activeTool);
    });

    els.closeToolPanelBtn?.addEventListener("click", closeToolPanel);

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
      await restoreWorkspace();
      await loadAssets();
      await loadCommunity();
      if (hasConfiguredModel()) {
        els.formHint.textContent = `已登录 ${window.scriptMakerConfig.username}。`;
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
