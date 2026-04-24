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
  const RUNNING_STATUSES = new Set(["pending", "running", "pausing"]);
  const RESUMABLE_STATUSES = new Set(["paused", "pausing", "failed", "terminated"]);
  const TERMINATABLE_STATUSES = new Set(["pending", "running", "pausing", "paused", "failed"]);
  const $ = (id) => document.getElementById(id);
  const currentAuthToken = () => new URL(window.location.href).searchParams.get("auth_token") || "";

  const els = {
    workspaceSidebar: $("workspaceCard"),
    sidebarToggleBtn: $("sidebarToggleBtn"),
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
    editingProjectId: null,
    editingProjectStatus: null,
    editingAssetLocked: false,
    activeTool: "hot_review",
    elapsedTimer: null,
    workspaceCollapseTimer: null
  };

  const TOOL_DEFINITIONS = {
    hot_review: {
      title: "爆款文审核",
      help: "提交剧本正文、故事大纲、分集计划或局部片段，系统会评估爆款元素、风险和修改建议。",
      fields: [
        ["text", "待检测文本", "textarea", "粘贴需要审核的剧本正文 / 小说原著 / 大纲 / 分集计划。"]
      ]
    },
    reskin: {
      title: "换皮",
      help: "输入源剧本材料和目标风格，调用换皮工作流生成新版本结果。",
      fields: [
        ["title", "剧本标题", "input", "新剧本标题。"],
        ["source_outline", "源剧本梗概", "textarea", "源故事梗概。"],
        ["core_scenes", "源剧本核心场景", "textarea", "可选，源剧本核心场景。"],
        ["source_characters", "源剧本人物小传", "textarea", "源人物小传。"],
        ["source_script", "源剧本正文", "textarea", "源剧本正文，可为空但效果会受影响。"],
        ["target_style", "目标风格", "textarea", "希望换成的题材、风格、爽点方向。"],
        ["total_episodes", "总集数", "number", "例如 60。"],
        ["episode_word_count", "每集字数", "number", "例如 500。"]
      ]
    },
    punchup: {
      title: "增加爽感",
      help: "在不改情节事实的前提下，强化台词网感、黄金 7 秒和爽点表达。",
      fields: [
        ["title", "剧本名", "input", "原剧本名。"],
        ["story_outline", "故事梗概", "textarea", "故事梗概。"],
        ["characters", "人物小传", "textarea", "人物设定。"],
        ["core_scenes", "核心场景", "textarea", "核心场景。"],
        ["script", "剧本正文", "textarea", "需要增爽的剧本正文。"],
        ["total_episodes", "总集数", "number", "总集数。"]
      ]
    },
    character_reskin: {
      title: "换皮只换人设",
      help: "保留主剧情结构，重点替换人物小传和角色设定。",
      fields: [
        ["title", "剧本标题", "input", "新剧本标题。"],
        ["story_outline", "故事大纲", "textarea", "故事大纲。"],
        ["characters", "人物小传", "textarea", "需要换皮的人物小传。"],
        ["core_scenes", "核心场景", "textarea", "核心场景。"],
        ["source_script", "原剧本正文", "textarea", "原剧本正文。"],
        ["total_episodes", "总集数", "number", "总集数。"],
        ["episode_word_count", "每集正文字数", "number", "每集字数。"]
      ]
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
    } catch (_) {}
  }

  function clearDraft() {
    draftStorage.removeItem(STORAGE.draft);
  }

  // 记住侧边栏折叠状态，让用户切页面回来后仍保持同一工作台布局。
  function applySidebarCollapsed(collapsed) {
    if (!els.workspaceSidebar) return;
    els.workspaceSidebar.classList.toggle("is-collapsed", Boolean(collapsed));
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
      artifacts.script_title,
      projectLike.script_title,
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
      artifacts.script_title,
      projectLike.script_title
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
    els.expectationInput.value = inputPayload.user_expectation || "";
    els.characterCountInput.value = inputPayload.character_count || 5;
    els.episodeCountInput.value = inputPayload.total_episodes || 10;
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

  // 当前状态下只保留必要提示，避免和“当前阶段”重复。
  function statusNoteFrom(snapshot) {
    if (!snapshot) return "";
    if (snapshot.status === "failed") {
      return "当前步骤执行失败，任务已停在上一个成功步骤。";
    }
    if (snapshot.status === "terminated") {
      return "任务已终止，已保留当前进度。";
    }
    if (snapshot.status === "paused" || snapshot.status === "pausing") {
      return snapshot.message || "已暂停，等待继续。";
    }
    if (snapshot.status === "completed") {
      return snapshot.awaiting_user_confirmation
        ? "剧本已生成完成，等待你确认是否满意。"
        : "剧本已完成。";
    }
    const runtimeMessage = String(snapshot.message || "").trim();
    if (!runtimeMessage) return "";
    const markers = ["自动重试", "已继续执行", "网络波动", "模型连接波动"];
    return markers.some((marker) => runtimeMessage.includes(marker)) ? runtimeMessage : "";
  }

  // 把后端阶段名统一折叠成前端可识别的正式阶段键。
  function normalizeStageKey(stageKey) {
    const mapping = {
      framework: "framework",
      appearance_strategy: "framework",
      consistency: "framework",
      episode_plan_normalize: "framework",
      worldview: "worldview",
      character: "characters",
      characters: "characters",
      scene: "scenes",
      scenes: "scenes",
      appearance: "scenes",
      hook: "internal",
      hooks: "internal",
      dialogue: "internal",
      dialogues: "internal",
      script: "internal",
      memory: "internal",
      final: "final",
      finalize: "final",
      finished: "final"
    };
    return mapping[String(stageKey || "").trim().toLowerCase()] || "";
  }

  // 把框架阶段的多个正式产物拼成一个完整回复，方便在聊天流里整体展示。
  function frameworkStageOutput(snapshot) {
    const artifacts = snapshot?.artifacts || {};
    const parts = [];
    const title = String(artifacts.script_title || "").trim();
    const storyOutline = String(artifacts.story_outline || "").trim();
    const characterBios = String(artifacts.character_bios || "").trim();
    const coreSceneInput = String(artifacts.core_scene_input || "").trim();
    const episodePlan = String(artifacts.episode_plan || "").trim();

    if (title) parts.push(`剧本标题\n${title}`);
    if (storyOutline) parts.push(`故事大纲\n${storyOutline}`);
    if (characterBios) parts.push(`人物小传\n${characterBios}`);
    if (coreSceneInput) parts.push(`核心场景\n${coreSceneInput}`);
    if (episodePlan) parts.push(`分集计划\n${episodePlan}`);
    return parts.join("\n\n").trim();
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
        output: String(artifacts.worldview || "").trim()
      },
      {
        key: "characters",
        title: "人物设定",
        output: String(artifacts.character_summary || "").trim()
      },
      {
        key: "scenes",
        title: "核心场景",
        output: String(artifacts.core_scene_summary || "").trim()
      },
      {
        key: "final",
        title: "最终剧本",
        output: String(artifacts.final_output_text || artifacts.final_script || "").trim()
      }
    ].filter((item) => item.output);

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
    const shouldFoldToThinking = normalizedCurrentStage === "internal" || (isRunning && !hasVisibleCurrentOutput);
    if (!shouldFoldToThinking) return null;
    return {
      loading: isRunning,
      stageLabel: snapshot.current_stage_label || "处理中",
      note: statusNoteFrom(snapshot) || ""
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
            <pre class="chat-bubble-content">${escapeHtml(expectation)}</pre>
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
                <span class="chat-bubble-preview-label">自然语言速览</span>
                <p class="chat-bubble-preview-text">${escapeHtml(message.natural)}</p>
              </div>
            ` : ""}
          </div>
        </div>
      </article>
    `;
  }

  function renderThinkingBubble(thinkingState) {
    const body = thinkingState.loading
      ? `
        <div class="chat-thinking">
          <span>思考分析</span>
          <span class="chat-thinking-dots"><span></span><span></span><span></span></span>
        </div>
      `
      : `<span>${escapeHtml(thinkingState.note || "当前步骤已暂停，等待你的下一步操作。")}</span>`;
    return `
      <article class="chat-message system">
        <div class="chat-bubble-row">
          <div class="chat-avatar">AI</div>
          <div class="chat-bubble">
            <div class="chat-bubble-head">
              <span class="chat-bubble-title">思考分析</span>
              <span class="chat-bubble-meta">${escapeHtml(thinkingState.stageLabel || "处理中")}</span>
            </div>
            <div class="chat-bubble-content">${body}</div>
            ${thinkingState.loading ? "" : thinkingState.note ? `
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
      els.chatTranscript.innerHTML = `
        <section class="chat-empty-state">
          <strong>框架到剧本，让 AI 实现你的想法</strong>
          <p>从左侧切换已有剧本，或者直接在下方输入你的创作需求。平台会把正式阶段产物按对话方式展示，中间过程统一折叠为思考分析。</p>
        </section>
      `;
      return;
    }

    const messages = [renderUserPromptBubble(snapshot)];
    visibleStageMessages(snapshot).forEach((item) => {
      messages.push(renderAssistantStageBubble(item));
    });

    const thinkingState = thinkingStateFrom(snapshot);
    if (thinkingState) {
      messages.push(renderThinkingBubble(thinkingState));
    }

    els.chatTranscript.innerHTML = messages.join("");
    els.chatTranscript.scrollTop = els.chatTranscript.scrollHeight;
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

  // 当回退到正文阶段时，让用户按集数选择从哪一批开始重写。
  function renderRollbackScriptStartOptions(options, selectedValue = "") {
    if (!els.rollbackScriptStartSelect) return;
    const normalized = Array.isArray(options) ? options : [];
    const show = normalized.length > 0 && (els.rollbackStageSelect?.value || "") === "script";
    els.rollbackScriptStartSelect.innerHTML = [
      `<option value="">选择正文开始重写的集数</option>`,
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
    const finalOutput = displayPayload.output || "暂无内容";
    const projectTitle = runtimeProjectDisplayTitle(snapshot);
    const statusMessage = statusNoteFrom(snapshot);

    els.statusText.textContent = statusLabel(snapshot.status);
    els.messageText.textContent = statusMessage;
    els.messageText.classList.toggle("hidden", !statusMessage);
    els.stageText.textContent = snapshot.current_stage_label || "正在处理";
    els.progressFill.style.width = `${progress}%`;
    els.progressText.textContent = `${progress}%`;
    els.projectText.textContent = `当前剧本：${projectTitle}`;
    els.projectText.title = `当前剧本：${projectTitle}`;
    els.taskText.textContent = `任务：${snapshot.task_id || "未创建"}`;
    if (els.outputTitle) {
      els.outputTitle.textContent = displayPayload.title || "当前阶段输出";
    }
    if (els.outputNaturalBox) {
      els.outputNaturalBox.textContent = displayPayload.natural || "当前阶段产出生成后，会在这里显示更容易阅读的自然语言速览。";
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
    const rollbackScriptStartOptions = snapshot.rollback_script_start_options || [];
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
    const currentRollbackStart = snapshotChanged ? "" : (els.rollbackScriptStartSelect?.value || "");
    const desiredRollbackStart = (
      desiredRollbackStage === "script"
      && currentRollbackStart
      && rollbackScriptStartOptions.some((item) => String(item.value) === String(currentRollbackStart))
    )
      ? currentRollbackStart
      : desiredRollbackStage === "script"
        ? defaultRollbackStart
        : "";
    renderRollbackScriptStartOptions(rollbackScriptStartOptions, desiredRollbackStart);
    if (desiredRollbackStage !== "script" && els.rollbackScriptStartSelect) {
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
    const requiresScriptStart = selectedRollbackStage === "script";
    const hasRollbackSelection = Boolean(
      selectedRollbackStage && (!requiresScriptStart || (els.rollbackScriptStartSelect?.value || ""))
    );

    els.startBtn.disabled = !isAuthenticated() || !hasConfiguredModel;
    els.pauseBtn.disabled = !(state.taskId && ["running", "pending"].includes(state.status));
    els.resumeBtn.disabled = !(state.taskId && RESUMABLE_STATUSES.has(state.status));
    els.terminateBtn.disabled = !(state.taskId && TERMINATABLE_STATUSES.has(state.status));
    els.clearBtn.disabled = !isAuthenticated();
    els.saveBtn.disabled = !isAuthenticated() || !hasProject || !hasFinal;
    if (els.confirmCompletionBtn) {
      els.confirmCompletionBtn.disabled = !isAuthenticated() || !canConfirmCompletion;
    }
    if (els.rollbackStageSelect) {
      els.rollbackStageSelect.disabled = !isAuthenticated() || !canStageRollback;
    }
    if (els.rollbackScriptStartSelect) {
      const showScriptStart = canStageRollback && selectedRollbackStage === "script";
      els.rollbackScriptStartSelect.classList.toggle("hidden", !showScriptStart);
      els.rollbackScriptStartSelect.disabled = !showScriptStart;
    }
    if (els.rollbackRewriteBtn) {
      els.rollbackRewriteBtn.disabled = !isAuthenticated() || !canStageRollback || !hasRollbackSelection;
    }
    if (els.completionPanel) {
      const shouldShowCompletionPanel = Boolean(
        hasProject && (hasFinal || canConfirmCompletion || canStageRollback)
      );
      els.completionPanel.classList.toggle("hidden", !shouldShowCompletionPanel);
    }
  }

  function hasConfiguredModel() {
    return state.availableModels.some((item) => item.configured !== false);
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderToolForm(toolKey) {
    if (!els.toolForms) return;
    const tool = TOOL_DEFINITIONS[toolKey] || TOOL_DEFINITIONS.hot_review;
    state.activeTool = toolKey;
    document.querySelectorAll(".tool-tab").forEach((button) => {
      button.classList.toggle("active", button.dataset.tool === toolKey);
    });
    els.toolForms.innerHTML = `
      <div class="tool-form-head">
        <h3>${escapeHtml(tool.title)}</h3>
        <p>${escapeHtml(tool.help)}</p>
      </div>
      <div class="tool-field-grid">
        ${tool.fields.map(([name, label, type, placeholder]) => {
          if (type === "textarea") {
            return `
              <label class="field tool-field wide-field">
                <span>${escapeHtml(label)}</span>
                <textarea data-tool-field="${escapeHtml(name)}" placeholder="${escapeHtml(placeholder)}"></textarea>
              </label>
            `;
          }
          return `
            <label class="field tool-field">
              <span>${escapeHtml(label)}</span>
              <input data-tool-field="${escapeHtml(name)}" type="${escapeHtml(type)}" placeholder="${escapeHtml(placeholder)}">
            </label>
          `;
        }).join("")}
      </div>
    `;
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
    updateUrlParams((params) => params.set("panel", "profile"));
    loadAssets().catch((error) => {
      showStatusError(error, "个人中心加载失败，请稍后重试。");
    });
  }

  function closeProfilePanel() {
    els.profilePanel?.classList.add("hidden");
    els.profilePanel?.setAttribute("aria-hidden", "true");
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

  // 只把当前表单里真正需要的最小输入打包给后端启动主流程。
  function buildPayload() {
    const payload = {
      user_expectation: els.expectationInput.value.trim(),
      character_count: Number(els.characterCountInput.value || 0),
      episode_word_count: 600,
      total_episodes: Number(els.episodeCountInput.value || 0),
      title: "",
      story_outline: "",
      core_scene_input: "",
      character_bios: "",
      episode_plan: "",
      model_selection_id: els.modelSelect.value || ""
    };

    if (!payload.user_expectation) throw new Error("请填写用户期待。");
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
    renderSnapshot(project);
    if (scroll) {
      document.querySelector(".runtime")?.scrollIntoView({ behavior: "smooth", block: "start" });
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
      state.projectId && ["failed", "terminated"].includes(state.status)
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
    startPolling();
    els.formHint.textContent = restartingCurrentProject
      ? "当前资产已在原 ID 下重新开始生成。"
      : "新任务已启动。";
  }

  async function pauseTask() {
    if (!requireLogin()) return;
    if (!state.taskId) return;
    const data = await requestJson(`/api/tasks/${state.taskId}/pause`, { method: "POST" });
    renderSnapshot(data.task);
    await loadProjects({ restoreSelection: true, restoreInputs: false });
    startPolling();
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
    const startEpisodeValue = stageKey === "script" ? Number(els.rollbackScriptStartSelect?.value || 0) : 0;
    if (stageKey === "script" && startEpisodeValue <= 0) {
      throw new Error("请选择正文开始重写的集数。");
    }
    const detailSuffix = stageKey === "script" ? `，从第 ${startEpisodeValue} 集开始重写后续正文` : "";
    const ok = window.confirm(`确认回退到“${selectedLabel}”${detailSuffix}吗？前面的结果会保留，后面的结果会被清空重做。`);
    if (!ok) return;
    const data = await requestJson(`/api/projects/${state.projectId}/rollback`, {
      method: "POST",
      body: JSON.stringify({
        stage_key: stageKey,
        start_episode: stageKey === "script" ? startEpisodeValue : null
      })
    });
    restoreInputPayload(data.task?.input_payload, { force: true });
    renderSnapshot(data.task);
    await loadProjects({ restoreSelection: true, restoreInputs: false });
    startPolling();
  }

  function clearCurrentInput() {
    if (!requireLogin()) return;
    clearDraft();
    els.expectationInput.value = "";
    els.characterCountInput.value = 5;
    els.episodeCountInput.value = 10;
    els.formHint.textContent = "输入已清空。";
  }

  function saveFinalScript() {
    if (!requireLogin()) return;
    if (!state.projectId) return;
    const authToken = currentAuthToken();
    const suffix = authToken ? `?auth_token=${encodeURIComponent(authToken)}` : "";
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

  async function loadAssets() {
    if (!isAuthenticated()) {
      if (els.assetsList) {
        els.assetsList.innerHTML = emptyCard("登录后查看剧本资产");
      }
      return;
    }
    const data = await requestJson(window.scriptMakerConfig.assetsUrl);
    state.assets = data.assets || [];
    renderAssets(state.assets);
  }

  async function loadCommunity() {
    const data = await requestJson(window.scriptMakerConfig.communityUrl);
    renderCommunity(data.assets || []);
  }

  function renderAssets(assets) {
    if (!els.assetsList) return;
    if (!assets.length) {
      els.assetsList.innerHTML = emptyCard("还没有剧本资产");
      return;
    }
    els.assetsList.innerHTML = assets.map((item) => `
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
    `).join("");
  }

  function renderCommunity(assets) {
    if (!els.communityList) return;
    if (!assets.length) {
      els.communityList.innerHTML = emptyCard("社区里暂时还没有公开作品");
      return;
    }
    els.communityList.innerHTML = assets.map((item) => `
      <article class="community-tile">
        <span class="community-tag status-pill-public">公开成品</span>
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.summary)}</p>
        <div class="community-actions">
          <a class="btn btn-secondary" href="${escapeHtml(communityDetailUrl(item.project_id))}" target="_blank" rel="noopener">查看全文</a>
        </div>
      </article>
    `).join("");
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
  }

  function closeAssetEditor() {
    state.editingProjectId = null;
    state.editingProjectStatus = null;
    state.editingAssetLocked = false;
    [els.editAssetTitle, els.editAssetSummary, els.editAssetPrivacy, els.editAssetFinal].forEach((field) => {
      if (field) field.disabled = false;
    });
    if (els.saveAssetEditBtn) {
      els.saveAssetEditBtn.disabled = false;
      els.saveAssetEditBtn.textContent = "保存修改";
    }
    els.assetEditor.classList.add("hidden");
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
  }

  async function runActiveTool() {
    if (!requireLogin()) return;
    const payload = collectToolPayload();
    els.toolOutputBox.textContent = "正在调用 FastGPT 工具，请稍候。";
    const data = await requestJson(`/api/tools/${state.activeTool}/run`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
    els.toolOutputBox.textContent = data.result?.result || "工具没有返回文本结果。";
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
      el.addEventListener("input", saveDraft);
      el.addEventListener("change", saveDraft);
    });
  }

  function bindActions() {
    els.openProfileBtn?.addEventListener("click", openProfilePanel);
    els.closeProfileBtn?.addEventListener("click", closeProfilePanel);
    els.closeProfileBackdrop?.addEventListener("click", closeProfilePanel);
    els.usernameForm?.addEventListener("submit", updateUsername);
    els.passwordForm?.addEventListener("submit", updatePassword);

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
        await loadAssets();
      } catch (error) {
        showStatusError(error, "资产列表刷新失败，请稍后重试。");
      }
    });

    els.refreshCommunityBtn?.addEventListener("click", async () => {
      try {
        await loadCommunity();
      } catch (error) {
        showStatusError(error, "社区作品刷新失败，请稍后重试。");
      }
    });

    [els.activeProjectList, els.completedProjectList].forEach((container) => container?.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button) return;
      const projectId = button.dataset.projectId;
      try {
        if (button.dataset.action === "select-project") {
          await loadProjectDetail(projectId, { restoreInputs: true, scroll: true });
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
        if (button.dataset.action === "open-project") {
          closeProfilePanel();
          await loadProjectDetail(projectId, { restoreInputs: true, scroll: true });
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
        showStatusError(error, "资产操作失败，请稍后重试。");
      }
    });

    els.saveAssetEditBtn?.addEventListener("click", async () => {
      try {
        await saveAssetEdit();
      } catch (error) {
        showStatusError(error, "资产保存失败，请稍后重试。");
      }
    });

    els.cancelAssetEditBtn?.addEventListener("click", closeAssetEditor);

    document.querySelectorAll(".tool-tab").forEach((button) => {
      button.addEventListener("click", () => renderToolForm(button.dataset.tool));
    });

    els.runToolBtn?.addEventListener("click", async () => {
      try {
        await runActiveTool();
      } catch (error) {
        showToolError(error, "工具执行失败，请查看后台日志。");
      }
    });

    els.startBtn.addEventListener("click", async () => {
      try {
        await startGeneration();
      } catch (error) {
        showStatusError(error, "启动任务失败，请稍后重试。");
      }
    });

    els.pauseBtn.addEventListener("click", async () => {
      try {
        await pauseTask();
      } catch (error) {
        showStatusError(error, "暂停失败，请稍后重试。");
      }
    });

    els.resumeBtn.addEventListener("click", async () => {
      try {
        await resumeTask();
      } catch (error) {
        showStatusError(error, "继续失败，请稍后重试。");
      }
    });

    els.terminateBtn.addEventListener("click", async () => {
      try {
        await terminateTask();
      } catch (error) {
        showStatusError(error, "终止失败，请稍后重试。");
      }
    });

    els.confirmCompletionBtn?.addEventListener("click", async () => {
      try {
        await confirmCompletion();
      } catch (error) {
        showStatusError(error, "确认完成失败，请稍后重试。");
      }
    });

    els.rollbackStageSelect?.addEventListener("change", () => {
      if ((els.rollbackStageSelect?.value || "") !== "script" && els.rollbackScriptStartSelect) {
        els.rollbackScriptStartSelect.value = "";
      }
      const defaultScriptStart = (els.rollbackStageSelect?.value || "") === "script"
        ? String(state.latestSnapshot?.rollback_start_episode_default || "")
        : "";
      renderRollbackScriptStartOptions(
        state.latestSnapshot?.rollback_script_start_options || [],
        els.rollbackScriptStartSelect?.value || defaultScriptStart
      );
      syncButtons();
    });
    els.rollbackScriptStartSelect?.addEventListener("change", syncButtons);

    els.rollbackRewriteBtn?.addEventListener("click", async () => {
      try {
        await rollbackRewrite();
      } catch (error) {
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

    els.saveBtn.addEventListener("click", saveFinalScript);
  }

  async function init() {
    restoreDraft();
    renderToolForm(state.activeTool);
    bindInputs();
    bindActions();
    renderSnapshot(null);

    try {
      await loadModels();
      await restoreWorkspace();
      await loadAssets();
      await loadCommunity();
      if (hasConfiguredModel()) {
        els.formHint.textContent = `已登录 ${window.scriptMakerConfig.username}。这个页面可以同时管理多个任务，离开后回来也能恢复。`;
      } else if (!isAuthenticated()) {
        els.formHint.textContent = "你可以先浏览说明和社区作品；登录后即可开始创作。";
      } else {
        els.formHint.textContent = "当前没有已配置模型，请先在 .env 中补齐模型服务配置。";
      }
    } catch (error) {
      showStatusError(error, "页面初始化失败，请稍后刷新重试。");
      els.formHint.textContent = "模型列表或历史项目恢复失败，请检查后端服务、.env 配置和工作流 JSON 路径。";
    }
  }

  window.addEventListener("DOMContentLoaded", init);
})();
