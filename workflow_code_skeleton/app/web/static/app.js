(() => {
  "use strict";

  const userKey = `user.${window.scriptMakerConfig.userId || "anon"}`;
  const STORAGE = {
    draft: `scriptmaker.web.${userKey}.draft`,
    projectId: `scriptmaker.web.${userKey}.projectId`,
    modelId: `scriptmaker.web.${userKey}.modelId`,
    snapshotPrefix: `scriptmaker.web.${userKey}.snapshot.`
  };

  const POLL_INTERVAL = 2000;
  const $ = (id) => document.getElementById(id);

  const els = {
    modelSelect: $("modelSelect"),
    titleInput: $("titleInput"),
    wordCountInput: $("wordCountInput"),
    episodeCountInput: $("episodeCountInput"),
    storyOutlineInput: $("storyOutlineInput"),
    coreSceneInput: $("coreSceneInput"),
    characterBiosInput: $("characterBiosInput"),
    episodePlanInput: $("episodePlanInput"),
    formHint: $("formHint"),

    startBtn: $("startBtn"),
    pauseBtn: $("pauseBtn"),
    resumeBtn: $("resumeBtn"),
    terminateBtn: $("terminateBtn"),
    clearBtn: $("clearBtn"),
    saveBtn: $("saveBtn"),
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
      title: els.titleInput.value.trim(),
      episode_word_count: Number(els.wordCountInput.value || 0),
      total_episodes: Number(els.episodeCountInput.value || 0),
      story_outline: els.storyOutlineInput.value,
      core_scene_input: els.coreSceneInput.value,
      character_bios: els.characterBiosInput.value,
      episode_plan: els.episodePlanInput.value
    };
    localStorage.setItem(STORAGE.draft, JSON.stringify(draft));
    localStorage.setItem(STORAGE.modelId, els.modelSelect.value || "");
  }

  function restoreDraft() {
    try {
      const raw = localStorage.getItem(STORAGE.draft);
      if (!raw) return;
      const draft = JSON.parse(raw);
      els.titleInput.value = draft.title || "";
      els.wordCountInput.value = draft.episode_word_count || 500;
      els.episodeCountInput.value = draft.total_episodes || 10;
      els.storyOutlineInput.value = draft.story_outline || "";
      els.coreSceneInput.value = draft.core_scene_input || "";
      els.characterBiosInput.value = draft.character_bios || "";
      els.episodePlanInput.value = draft.episode_plan || "";
    } catch (_) {}
  }

  function formHasUserInput() {
    return Boolean(
      els.titleInput.value.trim()
      || els.storyOutlineInput.value.trim()
      || els.coreSceneInput.value.trim()
      || els.characterBiosInput.value.trim()
      || els.episodePlanInput.value.trim()
    );
  }

  function restoreInputPayload(inputPayload) {
    if (!inputPayload || formHasUserInput()) return;
    els.titleInput.value = inputPayload.title || "";
    els.wordCountInput.value = inputPayload.episode_word_count || 500;
    els.episodeCountInput.value = inputPayload.total_episodes || 10;
    els.storyOutlineInput.value = inputPayload.story_outline || "";
    els.coreSceneInput.value = inputPayload.core_scene_input || "";
    els.characterBiosInput.value = inputPayload.character_bios || "";
    els.episodePlanInput.value = inputPayload.episode_plan || "";
    saveDraft();
  }

  function cacheSnapshot(snapshot) {
    if (!snapshot || !snapshot.project_id) return;
    localStorage.setItem(STORAGE.projectId, String(snapshot.project_id));
    localStorage.setItem(
      `${STORAGE.snapshotPrefix}${snapshot.project_id}`,
      JSON.stringify(snapshot)
    );
  }

  function readCachedSnapshot(projectId) {
    if (!projectId) return null;
    try {
      const raw = localStorage.getItem(`${STORAGE.snapshotPrefix}${projectId}`);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function clearCachedSnapshot(projectId) {
    if (projectId) {
      localStorage.removeItem(`${STORAGE.snapshotPrefix}${projectId}`);
    }
    localStorage.removeItem(STORAGE.projectId);
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
      els.statusText.textContent = "待开始";
      els.messageText.textContent = "填写创作输入后点击开始生成。";
      els.stageText.textContent = "尚未运行";
      els.batchText.textContent = "-";
      els.episodeProgressText.textContent = "0 / 0";
      els.modelText.textContent = currentModelLabel();
      els.progressFill.style.width = "0%";
      els.progressText.textContent = "0%";
      els.projectText.textContent = "项目：未创建";
      els.taskText.textContent = "任务：未创建";
      els.finalOutputBox.textContent = "暂无内容";
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

    cacheSnapshot(snapshot);
    syncButtons();
  }

  function syncButtons() {
    const status = state.status;
    const hasProject = Boolean(state.projectId);
    const hasFinal = Boolean(finalOutputFrom(state.latestSnapshot));
    const hasConfiguredModel = state.availableModels.some((item) => item.configured !== false);

    els.startBtn.disabled = !isAuthenticated() || !hasConfiguredModel || ["running", "pending", "pausing", "paused"].includes(status);
    els.pauseBtn.disabled = status !== "running" && status !== "pending";
    els.resumeBtn.disabled = !["paused", "pausing", "failed", "terminated"].includes(status);
    els.terminateBtn.disabled = !["pending", "running", "pausing", "paused", "failed"].includes(status);
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
    const response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
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
    const cachedModelId = localStorage.getItem(STORAGE.modelId) || "";
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
      title: els.titleInput.value.trim(),
      episode_word_count: Number(els.wordCountInput.value || 0),
      total_episodes: Number(els.episodeCountInput.value || 0),
      story_outline: els.storyOutlineInput.value.trim(),
      core_scene_input: els.coreSceneInput.value.trim(),
      character_bios: els.characterBiosInput.value.trim(),
      episode_plan: els.episodePlanInput.value.trim(),
      model_selection_id: els.modelSelect.value || ""
    };

    if (!payload.title) throw new Error("请填写剧本标题。");
    if (!payload.story_outline) throw new Error("请填写故事大纲。");
    if (!payload.character_bios) throw new Error("请填写人物小传。");
    if (!payload.episode_plan) throw new Error("请填写分集计划。");
    if (payload.episode_word_count <= 0) throw new Error("每集正文字数必须大于 0。");
    if (payload.total_episodes <= 0) throw new Error("总集数必须大于 0。");
    if (!payload.model_selection_id) throw new Error("当前没有可用模型，请先完成 .env 配置。");
    return payload;
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
    renderSnapshot(data.task);
    startPolling();
    els.formHint.textContent = "任务已启动，输入内容已缓存到当前账号。";
  }

  async function pauseTask() {
    if (!requireLogin()) return;
    if (!state.taskId) return;
    const data = await requestJson(`/api/tasks/${state.taskId}/pause`, { method: "POST" });
    renderSnapshot(data.task);
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
    startPolling();
  }

  async function terminateTask() {
    if (!requireLogin()) return;
    if (!state.taskId) return;
    const ok = window.confirm("确认终止当前任务吗？当前节点会在结束后停止。");
    if (!ok) return;
    const data = await requestJson(`/api/tasks/${state.taskId}/terminate`, { method: "POST" });
    renderSnapshot(data.task);
    startPolling();
  }

  async function clearAll() {
    if (!requireLogin()) return;
    if (["running", "pending", "pausing", "paused"].includes(state.status)) {
      throw new Error("请先终止当前任务，再执行清空全部。");
    }

    const projectId = state.projectId;
    if (projectId) {
      await requestJson(`/api/projects/${projectId}`, { method: "DELETE" });
    }

    clearCachedSnapshot(projectId);
    localStorage.removeItem(STORAGE.draft);
    state.projectId = null;
    state.taskId = null;
    state.status = "idle";
    state.latestSnapshot = null;
    stopPolling();
    els.titleInput.value = "";
    els.wordCountInput.value = 500;
    els.episodeCountInput.value = 10;
    els.storyOutlineInput.value = "";
    els.coreSceneInput.value = "";
    els.characterBiosInput.value = "";
    els.episodePlanInput.value = "";
    renderSnapshot(null);
    els.formHint.textContent = "已清空当前账号下的本地草稿和当前项目展示。";
  }

  function saveFinalScript() {
    if (!requireLogin()) return;
    if (!state.projectId) return;
    window.location.href = `/api/projects/${state.projectId}/download`;
  }

  function visibilityLabel(value) {
    return value === "public" ? "公开成品" : "不公开";
  }

  function statusBadge(status) {
    return statusLabel(status || "idle");
  }

  function emptyCard(message, actionText = "") {
    return `
      <div class="empty-card">
        <strong>${escapeHtml(message)}</strong>
        ${actionText ? `<p>${escapeHtml(actionText)}</p>` : ""}
      </div>
    `;
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
          <span>${escapeHtml(statusBadge(item.status))}</span>
          <span>${escapeHtml(visibilityLabel(item.visibility))}</span>
        </div>
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.summary)}</p>
        <div class="asset-meta">
          <span>项目 ${escapeHtml(item.project_id)}</span>
          <span>${item.has_final ? "已有成品" : "未完成"}</span>
        </div>
        <div class="asset-actions">
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
    els.editAssetSummary.value = input.story_outline || "";
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
    renderSnapshot(data.project);
    closeAssetEditor();
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
    await loadAssets();
    await loadCommunity();
  }

  async function deleteAsset(projectId) {
    if (!requireLogin()) return;
    const ok = window.confirm("确认删除这个剧本资产吗？删除后不可恢复。");
    if (!ok) return;
    await requestJson(`/api/projects/${projectId}`, { method: "DELETE" });
    if (Number(projectId) === Number(state.projectId)) {
      renderSnapshot(null);
    }
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

  async function pollTask() {
    if (!state.taskId) return;
    try {
      const data = await requestJson(`/api/tasks/${state.taskId}`);
      renderSnapshot(data.task);
      if (["running", "pending", "pausing"].includes(data.task.status)) {
        state.pollTimer = window.setTimeout(pollTask, POLL_INTERVAL);
      } else {
        stopPolling();
      }
    } catch (error) {
      els.messageText.textContent = error.message || String(error);
      state.pollTimer = window.setTimeout(pollTask, POLL_INTERVAL * 2);
    }
  }

  function startPolling() {
    stopPolling();
    state.pollTimer = window.setTimeout(pollTask, POLL_INTERVAL);
  }

  function stopPolling() {
    if (state.pollTimer) {
      window.clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
  }

  async function restoreProject() {
    if (!isAuthenticated()) {
      renderSnapshot(null);
      els.statusText.textContent = "游客浏览";
      els.messageText.textContent = "登录后可以开始生成、保存资产和管理公开状态。";
      return;
    }
    const cachedProjectId = Number(localStorage.getItem(STORAGE.projectId) || 0);
    if (cachedProjectId) {
      const cachedSnapshot = readCachedSnapshot(cachedProjectId);
      if (cachedSnapshot) {
        renderSnapshot(cachedSnapshot);
      }
    }

    const data = await requestJson(window.scriptMakerConfig.latestProjectUrl);
    if (data.project) {
      restoreInputPayload(data.project.input_payload);
      renderSnapshot(data.project);
      if (["running", "pending", "pausing"].includes(data.project.status)) {
        startPolling();
      }
    } else {
      renderSnapshot(null);
    }
  }

  function bindInputs() {
    [
      els.titleInput,
      els.wordCountInput,
      els.episodeCountInput,
      els.storyOutlineInput,
      els.coreSceneInput,
      els.characterBiosInput,
      els.episodePlanInput,
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
      document.getElementById("create")?.scrollIntoView({ behavior: "smooth" });
    });

    els.viewAssetsBtn?.addEventListener("click", () => {
      if (!requireLogin()) return;
      openProfilePanel();
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

    els.assetsList?.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button) return;
      const projectId = button.dataset.projectId;
      try {
        if (button.dataset.action === "edit-asset") {
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
        const ok = window.confirm("确认清空当前表单、本地缓存和当前项目记录吗？");
        if (!ok) return;
        await clearAll();
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
      await restoreProject();
      await loadAssets();
      await loadCommunity();
      if (hasConfiguredModel()) {
        els.formHint.textContent = `已登录 ${window.scriptMakerConfig.username}，草稿会按账号自动缓存。`;
      } else if (!isAuthenticated()) {
        els.formHint.textContent = "你可以先浏览说明和社区作品；登录后即可开始创作。";
      } else {
        els.formHint.textContent = "当前没有已配置模型，请先在 .env 中补齐模型服务配置。";
      }
    } catch (error) {
      els.messageText.textContent = error.message || String(error);
      els.formHint.textContent = "模型列表或历史项目恢复失败，请检查后端服务和工作流 JSON 路径。";
    }
  }

  window.addEventListener("DOMContentLoaded", init);
})();
