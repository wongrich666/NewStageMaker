(() => {
  "use strict";

  const userKey = `user.${window.scriptMakerConfig.userId || "anon"}`;
  const storage = window.sessionStorage;
  const STORAGE = {
    draft: `scriptmaker.web.${userKey}.draft`,
    selectedProjectId: `scriptmaker.web.${userKey}.selectedProjectId`,
    modelId: `scriptmaker.web.${userKey}.modelId`
  };

  const POLL_INTERVAL = 2000;
  const RUNNING_STATUSES = new Set(["pending", "running", "pausing"]);
  const RESUMABLE_STATUSES = new Set(["paused", "pausing", "failed", "terminated"]);
  const TERMINATABLE_STATUSES = new Set(["pending", "running", "pausing", "paused", "failed"]);
  const $ = (id) => document.getElementById(id);
  const currentAuthToken = () => new URL(window.location.href).searchParams.get("auth_token") || "";

  const els = {
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
    refreshProjectsBtn: $("refreshProjectsBtn"),
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
    batchText: $("batchText"),
    episodeProgressText: $("episodeProgressText"),
    modelText: $("modelText"),
    progressFill: $("progressFill"),
    progressText: $("progressText"),
    projectText: $("projectText"),
    taskText: $("taskText"),
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
    activeTool: "hot_review"
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
    return normalizeNumber(storage.getItem(STORAGE.selectedProjectId));
  }

  function persistSelectedProjectId(projectId) {
    const normalized = normalizeNumber(projectId);
    if (normalized) {
      storage.setItem(STORAGE.selectedProjectId, String(normalized));
    } else {
      storage.removeItem(STORAGE.selectedProjectId);
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
    url.searchParams.delete("project_id");
    url.searchParams.delete("mode");
    if (projectId) {
      url.searchParams.set("project_id", String(projectId));
    } else if (fresh) {
      url.searchParams.set("mode", "new");
    }
    return `${url.pathname}${url.search}${url.hash}`;
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

  function saveDraft() {
    const draft = {
      user_expectation: els.expectationInput.value.trim(),
      character_count: Number(els.characterCountInput.value || 0),
      total_episodes: Number(els.episodeCountInput.value || 0),
    };
    storage.setItem(STORAGE.draft, JSON.stringify(draft));
    storage.setItem(STORAGE.modelId, els.modelSelect.value || "");
  }

  function restoreDraft() {
    try {
      const raw = storage.getItem(STORAGE.draft);
      if (!raw) return;
      const draft = JSON.parse(raw);
      els.expectationInput.value = draft.user_expectation || "";
      els.characterCountInput.value = draft.character_count || 5;
      els.episodeCountInput.value = draft.total_episodes || 10;
    } catch (_) {}
  }

  function clearDraft() {
    storage.removeItem(STORAGE.draft);
  }

  function formHasUserInput() {
    return Boolean(
      els.expectationInput.value.trim()
      || Number(els.characterCountInput.value || 5) !== 5
      || Number(els.episodeCountInput.value || 10) !== 10
    );
  }

  function restoreInputPayload(inputPayload) {
    if (!inputPayload || formHasUserInput()) return;
    els.expectationInput.value = inputPayload.user_expectation || "";
    els.characterCountInput.value = inputPayload.character_count || 5;
    els.episodeCountInput.value = inputPayload.total_episodes || 10;
    saveDraft();
  }

  function currentModelLabel() {
    const selected = state.availableModels.find((item) => item.id === els.modelSelect.value);
    return selected?.label || "未选择";
  }

  function finalOutputFrom(snapshot) {
    const artifacts = snapshot?.artifacts || {};
    return artifacts.final_output_text || artifacts.final_script || "";
  }

  function renderSnapshot(snapshot) {
    state.latestSnapshot = snapshot || null;
    if (!snapshot) {
      state.projectId = null;
      state.taskId = null;
      state.status = "idle";
      els.statusText.textContent = isAuthenticated() ? "待开始" : "游客浏览";
      els.messageText.textContent = isAuthenticated()
        ? "从下方任务列表选择一个项目，或直接填写新输入开始生成。"
        : "登录后可以开始生成、保存资产和管理公开状态。";
      els.stageText.textContent = "尚未运行";
      els.batchText.textContent = "-";
      els.episodeProgressText.textContent = "0 / 0";
      els.modelText.textContent = currentModelLabel();
      els.progressFill.style.width = "0%";
      els.progressText.textContent = "0%";
      els.projectText.textContent = "项目：未选中";
      els.taskText.textContent = "任务：未选中";
      els.finalOutputBox.textContent = "暂无内容";
      renderProjectList(state.projects);
      syncButtons();
      return;
    }

    state.projectId = snapshot.project_id || null;
    state.taskId = snapshot.task_id || null;
    state.status = snapshot.status || "idle";

    const progress = Number(snapshot.progress_percent || 0);
    const totalEpisodes = Number(snapshot.total_episodes || 0);
    const generatedEpisodes = Number(snapshot.generated_episodes || 0);
    const finalOutput = finalOutputFrom(snapshot);

    els.statusText.textContent = statusLabel(snapshot.status);
    els.messageText.textContent = snapshot.message || "后台正在处理。";
    els.stageText.textContent = snapshot.current_stage_label || "正在处理";
    els.batchText.textContent = snapshot.current_batch || "-";
    els.episodeProgressText.textContent = `${generatedEpisodes} / ${totalEpisodes}`;
    els.modelText.textContent = snapshot.model_option?.label || currentModelLabel();
    els.progressFill.style.width = `${progress}%`;
    els.progressText.textContent = `${progress}%`;
    els.projectText.textContent = `项目：${snapshot.project_id}`;
    els.taskText.textContent = `任务：${snapshot.task_id || "未创建"}`;
    els.finalOutputBox.textContent = finalOutput || "暂无内容";
    persistSelectedProjectId(snapshot.project_id);
    renderProjectList(state.projects);
    syncButtons();
  }

  function syncButtons() {
    const hasProject = Boolean(state.projectId);
    const hasFinal = Boolean(finalOutputFrom(state.latestSnapshot));
    const hasConfiguredModel = state.availableModels.some((item) => item.configured !== false);

    els.startBtn.disabled = !isAuthenticated() || !hasConfiguredModel;
    els.pauseBtn.disabled = !(state.taskId && ["running", "pending"].includes(state.status));
    els.resumeBtn.disabled = !(state.taskId && RESUMABLE_STATUSES.has(state.status));
    els.terminateBtn.disabled = !(state.taskId && TERMINATABLE_STATUSES.has(state.status));
    els.clearBtn.disabled = !isAuthenticated();
    els.saveBtn.disabled = !isAuthenticated() || !hasProject || !hasFinal;
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
    loadAssets().catch((error) => {
      els.messageText.textContent = error.message || String(error);
    });
  }

  function closeProfilePanel() {
    els.profilePanel?.classList.add("hidden");
    els.profilePanel?.setAttribute("aria-hidden", "true");
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
      els.modelText.textContent = "登录后可用";
      syncButtons();
      return;
    }
    const data = await requestJson(window.scriptMakerConfig.modelsUrl);
    state.availableModels = data.models || [];
    const availableModels = state.availableModels.filter((item) => item.configured !== false);
    const cachedModelId = storage.getItem(STORAGE.modelId) || "";
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
    els.modelText.textContent = currentModelLabel();
    syncButtons();
  }

  function buildPayload() {
    const payload = {
      user_expectation: els.expectationInput.value.trim(),
      character_count: Number(els.characterCountInput.value || 0),
      episode_word_count: 500,
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

  function renderProjectList(projects) {
    if (!els.activeProjectList || !els.completedProjectList) return;
    if (!isAuthenticated()) {
      const message = emptyCard("登录后才能创建和管理多任务", "登录后你可以同时开启多个项目，并在这里切换查看。");
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
              <span class="workspace-pick-title">${escapeHtml(item.title || "未命名剧本")}</span>
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

  async function loadProjectDetail(projectId, { restoreInputs = false, scroll = false } = {}) {
    const data = await requestJson(`/api/projects/${projectId}`);
    const project = data.project || null;
    if (!project) {
      persistSelectedProjectId(null);
      renderSnapshot(null);
      return null;
    }
    if (restoreInputs) {
      restoreInputPayload(project.input_payload);
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
      await loadProjectDetail(targetProjectId, { restoreInputs });
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

  async function startGeneration() {
    if (!requireLogin()) return;
    saveDraft();
    const payload = buildPayload();
    els.formHint.textContent = "正在创建任务，请稍候。";
    const data = await requestJson(window.scriptMakerConfig.startUrl, {
      method: "POST",
      body: JSON.stringify(payload)
    });
    await loadProjects({ restoreSelection: false, restoreInputs: false });
    await loadProjectDetail(data.task.project_id, { restoreInputs: false });
    startPolling();
    els.formHint.textContent = "新任务已启动。你可以继续填写新的输入，再开下一个任务。";
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

  function clearCurrentInput() {
    if (!requireLogin()) return;
    clearDraft();
    els.expectationInput.value = "";
    els.characterCountInput.value = 5;
    els.episodeCountInput.value = 10;
    els.formHint.textContent = "已清空当前编辑表单；后台任务和你的剧本资产都会保留。";
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
      `剧本：${item.title || "未命名剧本"}`,
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
          item.message || "这个后台任务在执行过程中失败了，你可以稍后打开项目继续生成。"
        );
      }
    }

    state.projectStatusMap = nextMap;
  }

  async function loadAssets() {
    if (!isAuthenticated()) {
      if (els.assetsList) {
        els.assetsList.innerHTML = emptyCard("登录后查看和处置你的剧本资产", "你可以修改、删除、设置公开或不公开。");
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
      els.assetsList.innerHTML = emptyCard("还没有剧本资产", "先新建一个剧本，生成结果会自动归档到这里。");
      return;
    }
    els.assetsList.innerHTML = assets.map((item) => `
      <article class="asset-tile">
        <div class="asset-topline">
          <span>${escapeHtml(statusLabel(item.status))}</span>
          <span>${escapeHtml(visibilityLabel(item.visibility))}</span>
        </div>
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.summary)}</p>
        <div class="asset-meta">
          <span>项目 ${escapeHtml(item.project_id)}</span>
          <span>${escapeHtml(item.current_stage_label || "待开始")}</span>
          <span>${escapeHtml(item.generated_episodes || 0)} / ${escapeHtml(item.total_episodes || 0)}</span>
        </div>
        <div class="asset-actions">
          <button class="btn btn-secondary" data-action="open-project" data-project-id="${escapeHtml(item.project_id)}">载入工作台</button>
          <button class="btn btn-ghost" data-action="open-project-page" data-project-id="${escapeHtml(item.project_id)}">新页面打开</button>
          <button class="btn btn-secondary" data-action="edit-asset" data-project-id="${escapeHtml(item.project_id)}">修改</button>
          <button class="btn btn-ghost" data-action="toggle-privacy" data-project-id="${escapeHtml(item.project_id)}" data-visibility="${escapeHtml(item.visibility)}">${item.visibility === "public" ? "设为不公开" : "公开成品"}</button>
          <button class="btn btn-danger" data-action="delete-asset" data-project-id="${escapeHtml(item.project_id)}">删除</button>
        </div>
      </article>
    `).join("");
  }

  function renderCommunity(assets) {
    if (!els.communityList) return;
    if (!assets.length) {
      els.communityList.innerHTML = emptyCard("社区里暂时还没有公开作品", "当用户把成品设置为公开后，会展示在这里。");
      return;
    }
    els.communityList.innerHTML = assets.map((item) => `
      <article class="community-tile">
        <span class="community-tag">公开成品</span>
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.summary)}</p>
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
    els.editAssetTitle.value = project.title || input.title || "";
    els.editAssetSummary.value = input.story_outline || artifacts.story_outline || "";
    els.editAssetPrivacy.value = project.visibility || "private";
    els.editAssetFinal.value = artifacts.final_output_text || artifacts.final_script || "";
    els.assetEditor.classList.remove("hidden");
    els.assetEditor.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function saveAssetEdit() {
    if (!requireLogin() || !state.editingProjectId) return;
    const payload = {
      title: els.editAssetTitle.value.trim(),
      story_outline: els.editAssetSummary.value.trim(),
      visibility: els.editAssetPrivacy.value,
      final_script: els.editAssetFinal.value
    };
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
    await requestJson(`/api/projects/${projectId}`, { method: "DELETE" });
    if (Number(projectId) === Number(state.projectId)) {
      persistSelectedProjectId(null);
      renderSnapshot(null);
    }
    await loadProjects({ restoreSelection: true, restoreInputs: false });
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
      els.profileMessage.textContent = error.message || String(error);
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
      els.profileMessage.textContent = error.message || String(error);
    }
  }

  async function pollWorkspace() {
    try {
      await loadProjects({ restoreSelection: true, restoreInputs: false });
    } catch (error) {
      els.messageText.textContent = error.message || String(error);
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
  }

  function bindInputs() {
    [
      els.expectationInput,
      els.characterCountInput,
      els.episodeCountInput,
      els.modelSelect
    ].forEach((el) => {
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

    els.refreshProjectsBtn?.addEventListener("click", async () => {
      try {
        await loadProjects({ restoreSelection: true, restoreInputs: false });
      } catch (error) {
        els.messageText.textContent = error.message || String(error);
      }
    });

    els.refreshAssetsBtn?.addEventListener("click", async () => {
      try {
        await loadAssets();
      } catch (error) {
        els.messageText.textContent = error.message || String(error);
      }
    });

    els.refreshCommunityBtn?.addEventListener("click", async () => {
      try {
        await loadCommunity();
      } catch (error) {
        els.messageText.textContent = error.message || String(error);
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
        els.messageText.textContent = error.message || String(error);
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
        els.messageText.textContent = error.message || String(error);
      }
    });

    els.saveAssetEditBtn?.addEventListener("click", async () => {
      try {
        await saveAssetEdit();
      } catch (error) {
        els.messageText.textContent = error.message || String(error);
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
        els.toolOutputBox.textContent = error.message || String(error);
      }
    });

    els.startBtn.addEventListener("click", async () => {
      try {
        await startGeneration();
      } catch (error) {
        els.messageText.textContent = error.message || String(error);
      }
    });

    els.pauseBtn.addEventListener("click", async () => {
      try {
        await pauseTask();
      } catch (error) {
        els.messageText.textContent = error.message || String(error);
      }
    });

    els.resumeBtn.addEventListener("click", async () => {
      try {
        await resumeTask();
      } catch (error) {
        els.messageText.textContent = error.message || String(error);
      }
    });

    els.terminateBtn.addEventListener("click", async () => {
      try {
        await terminateTask();
      } catch (error) {
        els.messageText.textContent = error.message || String(error);
      }
    });

    els.clearBtn.addEventListener("click", async () => {
      try {
        const ok = window.confirm("确认清空当前编辑表单吗？后台任务和剧本资产会保留。");
        if (!ok) return;
        clearCurrentInput();
      } catch (error) {
        els.messageText.textContent = error.message || String(error);
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
      els.messageText.textContent = error.message || String(error);
      els.formHint.textContent = "模型列表或历史项目恢复失败，请检查后端服务、.env 配置和工作流 JSON 路径。";
    }
  }

  window.addEventListener("DOMContentLoaded", init);
})();
