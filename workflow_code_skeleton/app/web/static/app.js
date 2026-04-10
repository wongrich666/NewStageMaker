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
    latestSnapshot: null
  };

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

    els.startBtn.disabled = !hasConfiguredModel || ["running", "pending", "pausing", "paused"].includes(status);
    els.pauseBtn.disabled = status !== "running" && status !== "pending";
    els.resumeBtn.disabled = !["paused", "pausing"].includes(status);
    els.terminateBtn.disabled = !["pending", "running", "pausing", "paused", "failed"].includes(status);
    els.saveBtn.disabled = !hasProject || !hasFinal;
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
    if (!state.taskId) return;
    const data = await requestJson(`/api/tasks/${state.taskId}/pause`, { method: "POST" });
    renderSnapshot(data.task);
    startPolling();
  }

  async function resumeTask() {
    if (!state.taskId) return;
    const data = await requestJson(`/api/tasks/${state.taskId}/resume`, { method: "POST" });
    renderSnapshot(data.task);
    startPolling();
  }

  async function terminateTask() {
    if (!state.taskId) return;
    const ok = window.confirm("确认终止当前任务吗？当前节点会在结束后停止。");
    if (!ok) return;
    const data = await requestJson(`/api/tasks/${state.taskId}/terminate`, { method: "POST" });
    renderSnapshot(data.task);
    startPolling();
  }

  async function clearAll() {
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
    if (!state.projectId) return;
    window.location.href = `/api/projects/${state.projectId}/download`;
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
    bindInputs();
    bindActions();
    renderSnapshot(null);

    try {
      await loadModels();
      await restoreProject();
      if (hasConfiguredModel()) {
        els.formHint.textContent = `已登录 ${window.scriptMakerConfig.username}，草稿会按账号自动缓存。`;
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
