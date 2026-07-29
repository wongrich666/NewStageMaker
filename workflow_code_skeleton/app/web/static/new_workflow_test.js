(() => {
  const app = document.getElementById("new-workflow-test-app");
  if (!app) return;

  const config = window.NEW_WORKFLOW_TEST_CONFIG || {};
  const params = new URLSearchParams(window.location.search);
  const authToken = params.get("auth_token") || config.authToken || "";
  const STORAGE_KEY = "codeBuddyNpcScriptTeam.v1";
  const POLL_MS = 5000;

  const TEAM = [
    { id: "showrunner", key: "contract", name: "总编剧", responsibility: "锁定创作承诺、题材方向与不可篡改事实" },
    { id: "story_architect", key: "story", name: "故事架构师", responsibility: "建立主线、支线、因果链与结局兑现" },
    { id: "character_emotion", key: "characters", name: "人物情感编剧", responsibility: "强化人物欲望、关系债与情绪共鸣" },
    { id: "episode_continuity", key: "episodes", name: "分集连续性编剧", responsibility: "锁定逐集场景、行动承接、冲突升级与尾钩" },
    { id: "script_writer", key: "draft", name: "正文对白编剧", responsibility: "按字数和场景格式完成可拍剧本初稿" },
    { id: "state_recorder", key: "story_state", name: "状态记录器", responsibility: "提取位置、知情范围、道具、关系和未完成动作" },
    { id: "final_editor", key: "final_script", name: "终审与钩子编辑", responsibility: "修好钩子、对白、连续性并交付带场景的最终剧本" },
  ];
  const STAGE_ALIASES = {
    "终审与钩子编辑": ["终审与钩子编辑", "钩子与戏剧编辑", "终审导演"],
  };
  const ACTIVE_JOB_STATUSES = new Set(["pending", "queued", "waiting", "start", "running", "in_progress", "result_pending", "stage_running"]);
  const ARTIFACT_LABELS = {
    contract: "01 创作合同",
    story: "02 故事架构",
    characters: "03 人物与声音",
    episodes: "04 分集连续性卡",
    draft: "05 剧本初稿",
    story_state: "故事状态 JSON",
    final_script: "最终完整剧本",
  };

  const initialState = {
    configStatus: null,
    form: {
      project_title: "",
      mode: "原创",
      production_type: "AI漫剧",
      target_market: "中国大陆",
      genre: "",
      episodes: 5,
      episode_word_count: 800,
      scenes_per_episode: "1",
      source_text: "",
      adaptation_direction: "",
      execution_mode: "step",
    },
    job: null,
    history: [],
    error: "",
    loading: false,
    selectedArtifact: "",
  };

  let state = loadState();
  let pollTimer = null;
  let taskTimer = null;

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function icon(name, size = 16) {
    return `<i data-lucide="${escapeHtml(name)}" style="width:${size}px;height:${size}px" aria-hidden="true"></i>`;
  }

  function loadState() {
    try {
      const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null");
      if (!saved || typeof saved !== "object") return clone(initialState);
      return {
        ...clone(initialState),
        ...saved,
        form: { ...clone(initialState.form), ...(saved.form || {}) },
        loading: false,
        error: "",
      };
    } catch (_) {
      return clone(initialState);
    }
  }

  function saveState() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
        form: state.form,
        job: state.job ? {
          job_id: state.job.job_id,
          status: state.job.status,
          status_text: state.job.status_text,
          updated_at: state.job.updated_at,
        } : null,
      }));
    } catch (_) {}
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function authHeaders(json = true) {
    const headers = {};
    if (json) headers["Content-Type"] = "application/json";
    if (authToken) headers.Authorization = `Bearer ${authToken}`;
    return headers;
  }

  function apiUrl(path) {
    if (!authToken) return path;
    const url = new URL(path, window.location.origin);
    url.searchParams.set("auth_token", authToken);
    return url.pathname + url.search;
  }

  async function request(path, payload, method) {
    const requestMethod = method || (payload === undefined ? "GET" : "POST");
    const response = await fetch(apiUrl(path), {
      method: requestMethod,
      headers: authHeaders(true),
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false || data.success === false) {
      const detail = data.detail && typeof data.detail === "object"
        ? Object.values(data.detail).filter((item) => typeof item === "string").join(" ")
        : "";
      throw new Error([data.error || data.message || `请求失败（HTTP ${response.status}）`, detail].filter(Boolean).join(" "));
    }
    return data;
  }

  function syncForm() {
    app.querySelectorAll("[data-form-key]").forEach((field) => {
      const key = field.dataset.formKey;
      state.form[key] = field.type === "number" ? Number(field.value) : field.value;
    });
  }

  function isActive(job = state.job) {
    return Boolean(job && ACTIVE_JOB_STATUSES.has(String(job.status || "").toLowerCase()));
  }

  function stageStatusByName(name) {
    if (!state.job) return "";
    const member = TEAM.find((item) => item.name === name);
    if (member && state.job.active_stage === member.id && isActive(state.job)) return "running";
    if (!Array.isArray(state.job.team_stages)) return "";
    if (
      name === "最终连续性门禁"
      && state.job.quality_gate
      && state.job.quality_gate.ok === true
    ) {
      return "success";
    }
    const names = STAGE_ALIASES[name] || [name];
    const statuses = state.job.team_stages
      .filter((stage) => {
        const candidate = String(stage.name || "").replaceAll(" ", "");
        return names.some((item) => {
          const normalized = String(item).replaceAll(" ", "");
          return candidate.includes(normalized) || normalized.includes(candidate);
        });
      })
      .map((stage) => String(stage.status || "").toLowerCase());
    if (statuses.some((status) => ["error", "failed", "failure", "cancel", "cancelled"].includes(status))) return "failed";
    if (statuses.some((status) => ["start", "running", "in_progress"].includes(status))) return "running";
    if (statuses.length && statuses.every((status) => ["success", "succeeded", "completed", "complete"].includes(status))) return "success";
    return statuses[statuses.length - 1] || "";
  }

  function statusLabel(status) {
    const value = String(status || "").toLowerCase();
    if (["success", "succeeded", "completed", "complete"].includes(value)) return ["已完成", "done"];
    if (["error", "failed", "failure", "cancel", "cancelled"].includes(value)) return ["失败", "error"];
    if (["start", "running", "in_progress"].includes(value)) return ["创作中", "running"];
    return ["等待", ""];
  }

  function formatNumber(value) {
    return new Intl.NumberFormat("zh-CN").format(Math.max(0, Number(value) || 0));
  }

  function formatDuration(value) {
    const milliseconds = Math.max(0, Number(value) || 0);
    if (!milliseconds) return "";
    const seconds = Math.round(milliseconds / 1000);
    if (seconds < 60) return `${seconds}秒`;
    return `${Math.floor(seconds / 60)}分${seconds % 60}秒`;
  }

  function artifactChars(member, files, job) {
    return member.key === "final_script"
      ? String(job.final_script || "").length
      : String(files[member.key] || "").length;
  }

  function renderConfig() {
    const value = state.configStatus || {};
    if (value.ready) {
      return `
        <div class="nwt-connection ready">
          <span class="nwt-connection-dot"></span>
          <div>
            <strong>CodeBuddy NPC 已就绪</strong>
            <small>${escapeHtml(value.repository)} · ${escapeHtml(value.model)} · ${escapeHtml(value.event)}</small>
          </div>
        </div>
      `;
    }
    const missing = Array.isArray(value.missing) ? value.missing.join("、") : "正在检查配置";
    return `
      <div class="nwt-connection">
        <span class="nwt-connection-dot"></span>
        <div>
          <strong>等待连接 CodeBuddy NPC</strong>
          <small>${escapeHtml(missing)}</small>
        </div>
      </div>
    `;
  }

  function renderTeam() {
    const job = state.job || {};
    const files = job.recovered_files || {};
    const active = isActive();
    const remotelyControllable = Boolean(job.job_id);
    return TEAM.map((member, index) => {
      const status = stageStatusByName(member.name);
      const [label, klass] = statusLabel(status);
      const hasOutput = member.key === "final_script"
        ? Boolean(String(job.final_script || "").trim())
        : Boolean(String(files[member.key] || "").trim());
      const previous = index ? TEAM[index - 1] : null;
      const previousReady = !previous || (
        previous.key === "final_script"
          ? Boolean(job.final_script)
          : Boolean(files[previous.key])
      );
      const canRun = Boolean(job.job_id && previousReady && !active && remotelyControllable);
      const chars = artifactChars(member, files, job);
      const stageInfo = (Array.isArray(job.team_stages) ? job.team_stages : [])
        .find((item) => String(item.name || "").includes(member.name));
      const duration = formatDuration(stageInfo && stageInfo.duration);
      const expanded = hasOutput && state.selectedArtifact === member.key;
      const artifactValue = member.key === "final_script"
        ? String(job.final_script || "")
        : String(files[member.key] || "");
      return `
        <article class="nwt-member ${klass} ${status === "running" ? "active" : ""} ${expanded ? "expanded" : ""}">
          <div class="nwt-member-rail">
            <span class="nwt-member-index">${status === "running" ? '<i class="nwt-spinner"></i>' : String(index + 1).padStart(2, "0")}</span>
            ${index < TEAM.length - 1 ? '<span class="nwt-rail-line"></span>' : ""}
          </div>
          <div class="nwt-member-copy">
            <div class="nwt-member-title">
              <strong>${escapeHtml(member.name)}</strong>
              <span class="nwt-member-status ${klass}">${escapeHtml(label)}</span>
            </div>
            <p>${escapeHtml(member.responsibility)}</p>
            <div class="nwt-member-meta">
              ${chars ? `<span>${formatNumber(chars)} 字</span>` : ""}
              ${duration ? `<span>${escapeHtml(duration)}</span>` : ""}
              ${status === "running" && job.batch_progress ? `<span>第${escapeHtml(job.batch_progress.current_start)}-${escapeHtml(job.batch_progress.current_end)}集</span>` : ""}
            </div>
          </div>
          <div class="nwt-member-actions">
            ${hasOutput ? `
              <button class="nwt-icon-btn ${expanded ? "active" : ""}" type="button" title="${expanded ? "收起产物" : "查看产物"}" data-action="artifact" data-artifact="${member.key}">
                ${icon(expanded ? "chevron-up" : "file-text")}
              </button>
            ` : ""}
            <button class="nwt-stage-run" type="button" data-action="run-stage" data-stage="${member.id}" ${canRun ? "" : "disabled"}>
              ${icon(hasOutput ? "refresh-cw" : "play", 14)}<span>${hasOutput ? "重新运行" : "运行"}</span>
            </button>
          </div>
          ${expanded ? `
            <div class="nwt-member-artifact">
              <div class="nwt-artifact-toolbar">
                <div>
                  <strong>${escapeHtml(ARTIFACT_LABELS[member.key] || member.name)}</strong>
                  <span>${formatNumber(artifactValue.length)} 字 · 已保存到任务历史</span>
                </div>
                <div class="nwt-actions">
                  <button class="nwt-btn compact" type="button" data-action="download-artifact" data-artifact="${member.key}">${icon("download", 14)}<span>下载</span></button>
                  <button class="nwt-btn compact primary-soft" type="button" data-action="save-artifact" data-artifact="${member.key}" ${active ? "disabled" : ""}>${icon("save", 14)}<span>保存修改</span></button>
                </div>
              </div>
              <textarea class="nwt-artifact-editor" data-artifact-editor="${member.key}" ${active ? "disabled" : ""}>${escapeHtml(artifactValue)}</textarea>
            </div>
          ` : ""}
        </article>
      `;
    }).join("");
  }

  function renderTeamFlow() {
    const activeStage = state.job && state.job.active_stage;
    return `
      <div class="nwt-team-flow" aria-label="剧本团队工作流">
        ${TEAM.map((member, index) => {
          const status = stageStatusByName(member.name);
          const [, klass] = statusLabel(status);
          const isRunning = member.id === activeStage && isActive();
          return `
            <div class="nwt-flow-step ${klass} ${isRunning ? "active" : ""}">
              <span class="nwt-flow-node">
                ${isRunning ? icon("loader-circle", 15) : klass === "done" ? icon("check", 15) : String(index + 1)}
              </span>
              <strong>${escapeHtml(member.name)}</strong>
              ${index < TEAM.length - 1 ? '<i class="nwt-flow-connector"></i>' : ""}
            </div>
          `;
        }).join("")}
      </div>
    `;
  }

  function renderBatchProgress(job) {
    const total = Math.max(1, Number((job.request || {}).episodes || state.form.episodes) || 1);
    const progress = job.batch_progress || {};
    const batchSize = Math.max(1, Number(progress.batch_size) || Math.min(5, total));
    const ranges = [];
    for (let start = 1; start <= total; start += batchSize) {
      ranges.push([start, Math.min(total, start + batchSize - 1)]);
    }
    const completed = Array.isArray(progress.completed_ranges) ? progress.completed_ranges : [];
    return `
      <div class="nwt-batch-track">
        ${ranges.map(([start, end]) => {
          const done = completed.some((item) => Number(item[0]) === start && Number(item[1]) === end);
          const current = Number(progress.current_start) === start && Number(progress.current_end) === end && isActive(job);
          return `<span class="${done ? "done" : current ? "active" : ""}" title="第${start}-${end}集">
            ${current ? '<i class="nwt-mini-pulse"></i>' : ""}${start === end ? `第${start}集` : `${start}-${end}`}
          </span>`;
        }).join("")}
      </div>
    `;
  }

  function renderUsage(job) {
    const usage = job.usage_metrics || {};
    const reported = Boolean(usage.provider_reported_tokens);
    const prompt = Number(usage.prompt_tokens) || 0;
    const completion = Number(usage.completion_tokens) || 0;
    const cached = Number(usage.cached_tokens) || 0;
    return `
      <div class="nwt-usage-grid">
        <div><span>模型调用</span><strong>${formatNumber(usage.calls || 0)}</strong></div>
        <div><span>输入 Token</span><strong>${reported ? formatNumber(prompt) : "待接口返回"}</strong></div>
        <div><span>输出 Token</span><strong>${reported ? formatNumber(completion) : "待接口返回"}</strong></div>
        <div><span>缓存命中</span><strong>${reported ? formatNumber(cached) : "—"}</strong></div>
      </div>
    `;
  }

  function renderLiveMonitor(job) {
    const activeStage = TEAM.find((member) => member.id === job.active_stage);
    const progress = Math.max(0, Math.min(100, Number(job.progress) || 0));
    return `
      <aside class="nwt-monitor">
        <div class="nwt-monitor-head">
          <div>
            <span class="nwt-eyebrow">${job.execution_target === "local_fallback" ? "本地兜底" : "CNB 远程运行"}</span>
            <h2>${escapeHtml(activeStage ? activeStage.name : (job.status_text || "等待任务"))}</h2>
          </div>
          <span class="nwt-live-state ${isActive(job) ? "active" : ""}">${isActive(job) ? "运行中" : progress === 100 ? "已完成" : "待命"}</span>
        </div>
        <p class="nwt-monitor-message">${escapeHtml(job.status_text || "填写任务后开始创作")}</p>
        <div class="nwt-monitor-progress"><span style="width:${progress}%"></span></div>
        <div class="nwt-monitor-progress-meta"><strong>${progress}%</strong><span>${escapeHtml(job.job_id || "尚未创建任务")}</span></div>
        ${job.job_id ? renderBatchProgress(job) : ""}
        ${renderUsage(job)}
        <div class="nwt-cost-note">
          <strong>动态成本控制</strong>
          <span>${job.execution_target === "local_fallback" ? "远程失败后由本地节点从已有产物继续。" : "自动与分步模式均提交 CNB；本机不消耗模型，失败时才启用兜底。"}</span>
        </div>
      </aside>
    `;
  }

  function renderBuildLink() {
    const url = state.job && state.job.build && state.job.build.build_log_url;
    if (!url) return "";
    return `<a class="nwt-link" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">查看 CNB 执行记录</a>`;
  }

  function renderArtifacts(job) {
    const files = job.recovered_files && typeof job.recovered_files === "object"
      ? { ...job.recovered_files }
      : {};
    if (job.final_script) files.final_script = job.final_script;
    const available = Object.keys(files).filter((key) => String(files[key] || "").trim());
    const keys = [
      ...Object.keys(ARTIFACT_LABELS).filter((key) => available.includes(key)),
      ...available.filter((key) => !Object.hasOwn(ARTIFACT_LABELS, key)).sort(),
    ];
    if (!keys.length) return "";
    const selected = keys.includes(state.selectedArtifact) ? state.selectedArtifact : keys[0];
    state.selectedArtifact = selected;
    return `
      <section class="nwt-artifacts">
        <div class="nwt-section-head">
          <div>
            <h2>中间产物</h2>
            <p>任务完成或中断后保存在 5002，可逐项查看和下载。</p>
          </div>
          <div class="nwt-actions">
            <button class="nwt-btn" type="button" data-action="save-artifact" data-artifact="${escapeHtml(selected)}" ${isActive(job) ? "disabled" : ""}>保存修改</button>
            <button class="nwt-btn" type="button" data-action="download-artifact" data-artifact="${escapeHtml(selected)}">下载当前文件</button>
          </div>
        </div>
        <div class="nwt-artifact-tabs">
          ${keys.map((key) => `
            <button class="${key === selected ? "active" : ""}" type="button" data-action="artifact" data-artifact="${escapeHtml(key)}">
              ${escapeHtml(ARTIFACT_LABELS[key] || key)}
            </button>
          `).join("")}
        </div>
        <textarea class="nwt-artifact-editor" data-artifact-editor="${escapeHtml(selected)}" ${isActive(job) ? "disabled" : ""}>${escapeHtml(files[selected])}</textarea>
      </section>
    `;
  }

  function renderTaskCenter() {
    const items = Array.isArray(state.history) ? state.history : [];
    const running = items.filter((item) => ACTIVE_JOB_STATUSES.has(String(item.status || "").toLowerCase())).length;
    const completed = items.filter((item) => Boolean(item.has_final_script)).length;
    return `
      <aside class="nwt-task-center">
        <div class="nwt-task-head">
          <div>
            <span class="nwt-eyebrow">TASK CENTER</span>
            <h2>任务中心</h2>
          </div>
          <button class="nwt-icon-btn" type="button" title="刷新任务" data-action="refresh-history">${icon("refresh-cw")}</button>
        </div>
        <div class="nwt-task-summary">
          <div><strong>${running}</strong><span>运行中</span></div>
          <div><strong>${completed}</strong><span>已交付</span></div>
          <div><strong>${items.length}</strong><span>全部</span></div>
        </div>
        <button class="nwt-btn primary nwt-new-task" type="button" data-action="new-job">
          ${icon("plus", 17)}<span>新建剧本任务</span>
        </button>
        <div class="nwt-task-list">
          ${items.length ? items.map((item) => `
            <article class="nwt-task-item ${state.job && state.job.job_id === item.job_id ? "active" : ""}">
              <button class="nwt-task-open" type="button" data-action="open-history" data-job-id="${escapeHtml(item.job_id)}">
                <span class="nwt-task-title"><strong>${escapeHtml(item.project_title || "未命名剧本")}</strong><i class="nwt-task-state ${ACTIVE_JOB_STATUSES.has(String(item.status || "").toLowerCase()) ? "running" : item.has_final_script ? "done" : String(item.status || "").toLowerCase() === "failed" ? "failed" : ""}"></i></span>
                <span class="nwt-task-meta">${escapeHtml(item.production_type || "")} · ${escapeHtml(item.episodes || 0)}集</span>
                <span class="nwt-task-status">${escapeHtml(item.status_text || item.status || "")}</span>
                <span class="nwt-task-progress"><i style="width:${Math.max(0, Math.min(100, Number(item.progress) || 0))}%"></i></span>
              </button>
              <button class="nwt-icon-btn danger" type="button" title="${ACTIVE_JOB_STATUSES.has(String(item.status || "").toLowerCase()) ? "运行中的任务不能删除" : "删除任务"}" data-action="delete-history" data-job-id="${escapeHtml(item.job_id)}" ${ACTIVE_JOB_STATUSES.has(String(item.status || "").toLowerCase()) ? "disabled" : ""}>${icon("trash-2", 15)}</button>
            </article>
          `).join("") : '<div class="nwt-task-empty"><span>暂无任务</span><small>创建后会在这里持续显示进度</small></div>'}
        </div>
      </aside>
    `;
  }

  function render() {
    const job = state.job || {};
    const progress = Math.max(0, Math.min(100, Number(job.progress) || 0));
    const active = isActive();
    const finalScript = String(job.final_script || "");
    const canRecover = Boolean(job.job_id && String(job.status || "").toLowerCase() === "failed" && !finalScript);
    const qualityGate = job.quality_gate && typeof job.quality_gate === "object" ? job.quality_gate : {};
    const gateErrors = Array.isArray(qualityGate.errors) ? qualityGate.errors : [];
    const gateWarnings = Array.isArray(qualityGate.warnings) ? qualityGate.warnings : [];
    const recoveredFiles = job.recovered_files && typeof job.recovered_files === "object"
      ? Object.keys(job.recovered_files)
      : [];
    const episodes = Math.max(1, Number(state.form.episodes) || 1);
    const requestWarnings = Array.isArray(job.request_warnings) ? job.request_warnings : [];
    app.innerHTML = `
      <div class="nwt-shell">
        <header class="nwt-header">
          <div class="nwt-brand">
            <span class="nwt-brand-mark">${icon("clapperboard", 22)}</span>
            <div>
              <p class="nwt-kicker">SCRIPT PRODUCTION WORKSPACE</p>
              <h1>专业剧本制作台</h1>
              <p>从故事架构到成品剧本，节点独立、过程可见、断点可续</p>
            </div>
          </div>
          <div class="nwt-actions">
            <a class="nwt-btn" href="${escapeHtml(config.workspaceUrl || "/workspace")}">${icon("arrow-left", 15)}<span>返回工作台</span></a>
          </div>
        </header>

        ${renderConfig()}

        <div class="nwt-layout">
        ${renderTaskCenter()}
        <main class="nwt-main">
        <div class="nwt-create-grid">
        <section class="nwt-setup">
          <div class="nwt-section-head">
            <div class="nwt-section-title">
              <span class="nwt-section-icon">${icon("clapperboard", 18)}</span>
              <div>
              <h2>创作任务</h2>
              <p>按你的题材、集数和成片要求组织专业编剧团队。</p>
              </div>
            </div>
          </div>
          <div class="nwt-form-grid">
            <label class="nwt-field project">
              <span>项目名称</span>
              <input data-form-key="project_title" value="${escapeHtml(state.form.project_title)}" placeholder="例如：狼人复仇记" ${active ? "disabled" : ""} />
            </label>
            <div class="nwt-field">
              <span>创作模式</span>
              <div class="nwt-segmented" role="group" aria-label="创作模式">
                <input type="hidden" data-form-key="mode" value="${escapeHtml(state.form.mode)}" />
                <button class="nwt-segment-option ${state.form.mode === "原创" ? "active" : ""}" type="button" data-choice-key="mode" data-choice-value="原创" aria-pressed="${state.form.mode === "原创"}" ${active ? "disabled" : ""}>
                  ${icon("pen-line", 14)}<span>原创</span>
                </button>
                <button class="nwt-segment-option ${state.form.mode === "改编" ? "active" : ""}" type="button" data-choice-key="mode" data-choice-value="改编" aria-pressed="${state.form.mode === "改编"}" ${active ? "disabled" : ""}>
                  ${icon("book-open", 14)}<span>改编</span>
                </button>
              </div>
            </div>
            <div class="nwt-field">
              <span>成片类型</span>
              <div class="nwt-segmented" role="group" aria-label="成片类型">
                <input type="hidden" data-form-key="production_type" value="${escapeHtml(state.form.production_type)}" />
                <button class="nwt-segment-option ${state.form.production_type === "AI漫剧" ? "active" : ""}" type="button" data-choice-key="production_type" data-choice-value="AI漫剧" aria-pressed="${state.form.production_type === "AI漫剧"}" ${active ? "disabled" : ""}>
                  ${icon("panels-top-left", 14)}<span>AI漫剧</span>
                </button>
                <button class="nwt-segment-option ${state.form.production_type === "AI真人剧" ? "active" : ""}" type="button" data-choice-key="production_type" data-choice-value="AI真人剧" aria-pressed="${state.form.production_type === "AI真人剧"}" ${active ? "disabled" : ""}>
                  ${icon("film", 14)}<span>AI真人剧</span>
                </button>
              </div>
            </div>
            <label class="nwt-field">
              <span>目标市场</span>
              <input data-form-key="target_market" value="${escapeHtml(state.form.target_market)}" placeholder="中国大陆、北美、东南亚..." ${active ? "disabled" : ""} />
            </label>
            <label class="nwt-field">
              <span>题材</span>
              <input data-form-key="genre" value="${escapeHtml(state.form.genre)}" placeholder="复仇、爱情、悬疑..." ${active ? "disabled" : ""} />
            </label>
            <label class="nwt-field">
              <span>总集数</span>
              <input type="number" min="1" max="120" data-form-key="episodes" value="${escapeHtml(state.form.episodes)}" ${active ? "disabled" : ""} />
            </label>
            <label class="nwt-field">
              <span>每集最低字数</span>
              <input type="number" min="100" max="5000" data-form-key="episode_word_count" value="${escapeHtml(state.form.episode_word_count)}" ${active ? "disabled" : ""} />
            </label>
            <label class="nwt-field control-wide">
              <span>每集场景</span>
              <div class="nwt-select-control">
                <span class="nwt-control-icon">${icon("panels-top-left", 16)}</span>
                <select data-form-key="scenes_per_episode" ${active ? "disabled" : ""}>
                  <option value="1" ${state.form.scenes_per_episode === "1" ? "selected" : ""}>每集 1 场（默认）</option>
                  <option value="1-2" ${state.form.scenes_per_episode === "1-2" ? "selected" : ""}>每集 1 至 2 场</option>
                  <option value="2" ${state.form.scenes_per_episode === "2" ? "selected" : ""}>每集 2 场</option>
                  <option value="2-3" ${state.form.scenes_per_episode === "2-3" ? "selected" : ""}>每集 2 至 3 场</option>
                  <option value="flexible" ${state.form.scenes_per_episode === "flexible" ? "selected" : ""}>按剧情灵活安排</option>
                </select>
                <span class="nwt-select-chevron">${icon("chevron-down", 15)}</span>
              </div>
              <small class="nwt-field-hint">换场会自动要求人物去向与行动承接</small>
            </label>
            <div class="nwt-field control-wide">
              <span>执行方式</span>
              <div class="nwt-segmented nwt-segmented-detail" role="group" aria-label="执行方式">
                <input type="hidden" data-form-key="execution_mode" value="${escapeHtml(state.form.execution_mode)}" />
                <button class="nwt-segment-option ${state.form.execution_mode === "step" ? "active" : ""}" type="button" data-choice-key="execution_mode" data-choice-value="step" aria-pressed="${state.form.execution_mode === "step"}" ${active ? "disabled" : ""}>
                  ${icon("list-checks", 14)}<span>逐节点确认</span>
                </button>
                <button class="nwt-segment-option ${state.form.execution_mode === "auto" ? "active" : ""}" type="button" data-choice-key="execution_mode" data-choice-value="auto" aria-pressed="${state.form.execution_mode === "auto"}" ${active ? "disabled" : ""}>
                  ${icon("fast-forward", 14)}<span>自动跑到底</span>
                </button>
              </div>
              <small class="nwt-field-hint">均由 CNB 远程执行，本地节点仅在失败时兜底</small>
            </div>
            <label class="nwt-field wide">
              <span>原始材料或创作要求</span>
              <textarea data-form-key="source_text" placeholder="粘贴原文，或写清主角、目标、阻力、结局和必须保留的信息。" ${active ? "disabled" : ""}>${escapeHtml(state.form.source_text)}</textarea>
              <div class="nwt-upload-row">
                <label class="nwt-upload-button">
                  ${icon("paperclip", 14)}<span>上传材料</span>
                  <input type="file" data-upload-target="source_text" accept=".docx,.pdf,.txt,.md,.json" multiple ${active ? "disabled" : ""} />
                </label>
                <small>支持 Word、PDF、TXT、Markdown、JSON，可多选；单文件最大20MB</small>
              </div>
            </label>
            <label class="nwt-field wide">
              <span>补充方向</span>
              <textarea data-form-key="adaptation_direction" placeholder="例如：前五秒一句话爆点；每集承接上一集动作；人物细腻但不堆形容词；所有道具和证据根据剧情需要自然出现。" ${active ? "disabled" : ""}>${escapeHtml(state.form.adaptation_direction)}</textarea>
              <div class="nwt-upload-row">
                <label class="nwt-upload-button">
                  ${icon("paperclip", 14)}<span>上传补充文件</span>
                  <input type="file" data-upload-target="adaptation_direction" accept=".docx,.pdf,.txt,.md,.json" multiple ${active ? "disabled" : ""} />
                </label>
                <small>解析后的内容会追加到补充方向，不覆盖已经填写的文字</small>
              </div>
            </label>
          </div>
          <div class="nwt-runbar">
            <div>
              <strong>${escapeHtml(job.status_text || "尚未提交任务")}</strong>
              <small>${job.job_id ? `任务 ${escapeHtml(job.job_id)}` : `本次交付第1集至第${episodes}集，共${episodes}集`}</small>
            </div>
            <div class="nwt-run-actions">
              ${canRecover ? '<button class="nwt-btn" type="button" data-action="recover">恢复中断产物</button>' : ""}
              ${active && job.execution_target === "local_fallback" ? '<button class="nwt-btn danger" type="button" data-action="cancel">停止本地兜底</button>' : ""}
              ${String(job.status || "").toLowerCase() === "failed" ? '<button class="nwt-btn danger" type="button" data-action="fallback">本地兜底继续</button>' : ""}
              <button class="nwt-btn primary" type="button" data-action="start" ${state.loading || active || !(state.configStatus || {}).ready ? "disabled" : ""}>
                ${state.loading ? `${icon("loader-circle", 16)}<span>正在提交</span>` : active ? `${icon("activity", 16)}<span>团队创作中</span>` : finalScript ? `${icon("refresh-cw", 16)}<span>重新生成</span>` : `${icon("sparkles", 16)}<span>开始创作</span>`}
              </button>
            </div>
          </div>
        </section>
        ${renderLiveMonitor(job)}
        </div>

        ${state.error ? `<div class="nwt-error">${escapeHtml(state.error)}</div>` : ""}
        ${job.poll_warning ? `<div class="nwt-warning">${escapeHtml(job.poll_warning)}</div>` : ""}
        ${job.fallback_reason ? `<div class="nwt-warning">远程 CNB 未能接管，本次已启用本地兜底：${escapeHtml(job.fallback_reason)}</div>` : ""}
        ${requestWarnings.map((item) => `<div class="nwt-warning">${escapeHtml(item)}</div>`).join("")}
        ${gateErrors.length ? `
          <div class="nwt-warning">
            <strong>最终稿已保留，严格门禁仍有 ${gateErrors.length} 项待修</strong>
            ${gateErrors.slice(0, 5).map((item) => `<span>${escapeHtml(item.message || item.code || "待修项")}</span>`).join("")}
          </div>
        ` : ""}
        ${!gateErrors.length && gateWarnings.length ? `
          <div class="nwt-warning">
            <strong>剧本已通过严格门禁，另有 ${gateWarnings.length} 项非阻断提示</strong>
            ${gateWarnings.slice(0, 5).map((item) => `<span>${escapeHtml(item.message || item.code || "优化提示")}</span>`).join("")}
          </div>
        ` : ""}
        ${recoveredFiles.length ? `<div class="nwt-recovered">已恢复中间产物：${escapeHtml(recoveredFiles.join("、"))}</div>` : ""}

        <section class="nwt-team-section">
          <div class="nwt-section-head">
            <div class="nwt-section-title">
              <span class="nwt-section-icon">${icon("users", 18)}</span>
              <div>
              <h2>剧本团队</h2>
              <p>节点、运行状态和中间产物集中在同一条创作链路中。</p>
              </div>
            </div>
            ${renderBuildLink()}
          </div>
          ${renderTeamFlow()}
          ${job.job_id && !active ? `
            <div class="nwt-stage-controls">
              <label>
                <span>给本次节点的修改意见</span>
                <textarea id="nwt-stage-feedback" placeholder="例如：保留主线，只重写第一集开场；钩子改成一句有危险后果的命令。"></textarea>
              </label>
              <label class="nwt-check"><input id="nwt-continue-after" type="checkbox" /> 本节点完成后自动继续到最终剧本</label>
            </div>
          ` : ""}
          <div class="nwt-team">${renderTeam()}</div>
        </section>

        <section class="nwt-final">
          <div class="nwt-final-head">
            <div>
              <h2>最终完整剧本</h2>
              <p>${finalScript ? (gateErrors.length ? "终审稿已恢复，可下载；门禁待修项保留在上方" : "已完成终审并通过严格门禁") : "NPC团队完成后，正文会直接显示在这里"}</p>
            </div>
            <div class="nwt-actions">
              <button class="nwt-btn" type="button" data-action="download-word" ${finalScript ? "" : "disabled"}>${icon("file-down", 15)}<span>Word</span></button>
              <button class="nwt-btn" type="button" data-action="download" ${finalScript ? "" : "disabled"}>${icon("download", 15)}<span>TXT</span></button>
            </div>
          </div>
          <div class="nwt-output">${finalScript ? escapeHtml(finalScript) : '<span class="nwt-empty">等待团队交付...</span>'}</div>
        </section>
        </main>
        </div>
      </div>
    `;
    window.queueMicrotask(() => window.lucide && window.lucide.createIcons());
  }

  async function loadConfig() {
    try {
      const data = await request("/api/new-workflow-test/npc/config");
      state.configStatus = data.config || {};
    } catch (error) {
      state.configStatus = { ready: false, missing: [error.message || String(error)] };
    }
    render();
  }

  async function loadLatestJob() {
    try {
      const data = await request("/api/new-workflow-test/npc/jobs/latest");
      const latest = data.job;
      if (!latest) return;
      const currentTime = Date.parse((state.job || {}).updated_at || "") || 0;
      const latestTime = Date.parse(latest.updated_at || "") || 0;
      if (!state.job || latestTime >= currentTime) {
        state.job = latest;
        if (latest.request && typeof latest.request === "object") {
          state.form = { ...state.form, ...latest.request };
        }
        saveState();
      }
    } catch (error) {
      state.error = `恢复最近任务失败：${error.message || error}`;
    }
    render();
    if (isActive()) schedulePoll(500);
  }

  async function loadHistory(silent = false) {
    try {
      const data = await request("/api/new-workflow-test/npc/jobs");
      state.history = Array.isArray(data.jobs) ? data.jobs : [];
    } catch (error) {
      state.error = `读取历史记录失败：${error.message || error}`;
    }
    if (silent) {
      const current = app.querySelector(".nwt-task-center");
      if (current) current.outerHTML = renderTaskCenter();
      window.queueMicrotask(() => window.lucide && window.lucide.createIcons());
    } else {
      render();
    }
    scheduleTaskCenter();
  }

  async function openHistory(jobId) {
    state.loading = true;
    render();
    try {
      const data = await request(`/api/new-workflow-test/npc/jobs/${encodeURIComponent(jobId)}`);
      state.job = data.job || null;
      if (state.job && state.job.request) {
        state.form = { ...state.form, ...state.job.request };
      }
      state.selectedArtifact = "";
      saveState();
      if (isActive()) schedulePoll(500);
    } catch (error) {
      state.error = `打开历史失败：${error.message || error}`;
    } finally {
      state.loading = false;
      render();
    }
  }

  async function deleteHistory(jobId) {
    if (!window.confirm("确定删除这次剧本及全部中间产物吗？")) return;
    try {
      await request(`/api/new-workflow-test/npc/jobs/${encodeURIComponent(jobId)}`, undefined, "DELETE");
      if (state.job && state.job.job_id === jobId) state.job = null;
      await loadHistory();
      saveState();
    } catch (error) {
      state.error = `删除历史失败：${error.message || error}`;
      render();
    }
  }

  async function startJob() {
    syncForm();
    state.loading = true;
    state.error = "";
    render();
    try {
      const data = await request("/api/new-workflow-test/npc/jobs", state.form);
      state.job = data.job || null;
      if (state.job && state.job.request && typeof state.job.request === "object") {
        state.form = { ...state.form, ...state.job.request };
      }
      saveState();
      loadHistory();
      schedulePoll(800);
    } catch (error) {
      state.error = error.message || String(error);
    } finally {
      state.loading = false;
      render();
    }
  }

  async function pollJob() {
    if (!state.job || !state.job.job_id || !isActive()) return;
    try {
      const data = await request(`/api/new-workflow-test/npc/jobs/${encodeURIComponent(state.job.job_id)}`);
      state.job = data.job || state.job;
      state.error = state.job.status === "failed" ? (state.job.error || "NPC团队执行失败。") : "";
      saveState();
      render();
      if (!isActive()) loadHistory();
      if (isActive()) schedulePoll(POLL_MS);
    } catch (error) {
      state.error = `读取团队进度失败：${error.message || error}`;
      render();
      schedulePoll(POLL_MS * 2);
    }
  }

  async function recoverJob() {
    if (!state.job || !state.job.job_id) return;
    state.loading = true;
    state.error = "";
    render();
    try {
      const data = await request(
        `/api/new-workflow-test/npc/jobs/${encodeURIComponent(state.job.job_id)}/recover`,
        {},
      );
      state.job = data.job || state.job;
      saveState();
    } catch (error) {
      state.error = `恢复中断产物失败：${error.message || error}`;
    } finally {
      state.loading = false;
      render();
    }
  }

  async function uploadFiles(files, targetKey) {
    if (!files || !files.length || !targetKey) return;
    syncForm();
    state.loading = true;
    state.error = "";
    render();
    try {
      const sections = [];
      for (const file of Array.from(files)) {
        const formData = new FormData();
        formData.append("file", file);
        const response = await fetch(apiUrl("/api/files/extract-text"), {
          method: "POST",
          headers: authHeaders(false),
          body: formData,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.ok === false || data.success === false) {
          throw new Error(`${file.name}：${data.error || data.message || "文件解析失败"}`);
        }
        sections.push(`【上传文件：${data.filename || file.name}】\n${String(data.text || "").trim()}`);
      }
      const current = String(state.form[targetKey] || "").trim();
      state.form[targetKey] = [current, ...sections].filter(Boolean).join("\n\n");
      saveState();
    } catch (error) {
      state.error = `上传失败：${error.message || error}`;
    } finally {
      state.loading = false;
      render();
    }
  }

  async function runStage(stage, localFallback = false) {
    if (!state.job || !state.job.job_id) return;
    const feedback = String((document.getElementById("nwt-stage-feedback") || {}).value || "");
    const continueAfter = Boolean((document.getElementById("nwt-continue-after") || {}).checked);
    state.loading = true;
    state.error = "";
    render();
    try {
      const data = await request(
        `/api/new-workflow-test/npc/jobs/${encodeURIComponent(state.job.job_id)}/stages/${encodeURIComponent(stage)}/run`,
        { feedback, continue_after: continueAfter, local_fallback: localFallback },
      );
      state.job = data.job || state.job;
      saveState();
      schedulePoll(500);
    } catch (error) {
      state.error = error.message || String(error);
    } finally {
      state.loading = false;
      render();
    }
  }

  function fallbackStage() {
    const job = state.job || {};
    if (job.remote_stage && TEAM.some((item) => item.id === job.remote_stage)) {
      return String(job.remote_stage);
    }
    const files = job.recovered_files || {};
    const missing = TEAM.find((item) => item.key === "final_script"
      ? !String(job.final_script || "").trim()
      : !String(files[item.key] || "").trim());
    return missing ? missing.id : "final_editor";
  }

  async function cancelRun() {
    if (!state.job || !state.job.job_id) return;
    try {
      const data = await request(
        `/api/new-workflow-test/npc/jobs/${encodeURIComponent(state.job.job_id)}/cancel`,
        {},
      );
      state.job = data.job || state.job;
      saveState();
      render();
    } catch (error) {
      state.error = error.message || String(error);
      render();
    }
  }

  async function saveArtifact(key) {
    if (!state.job || !state.job.job_id) return;
    const editor = app.querySelector(`[data-artifact-editor="${CSS.escape(key)}"]`);
    if (!editor) return;
    state.loading = true;
    render();
    try {
      const data = await request(
        `/api/new-workflow-test/npc/jobs/${encodeURIComponent(state.job.job_id)}/artifacts/${encodeURIComponent(key)}`,
        { content: editor.value },
        "PUT",
      );
      state.job = data.job || state.job;
      saveState();
      loadHistory();
    } catch (error) {
      state.error = `保存修改失败：${error.message || error}`;
    } finally {
      state.loading = false;
      render();
    }
  }

  function schedulePoll(delay = POLL_MS) {
    if (pollTimer) window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(pollJob, delay);
  }

  function scheduleTaskCenter(delay = POLL_MS) {
    if (taskTimer) window.clearTimeout(taskTimer);
    taskTimer = window.setTimeout(() => loadHistory(true), delay);
  }

  function downloadText(text, filename) {
    if (!text) return;
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  app.addEventListener("change", (event) => {
    if (event.target.matches("[data-upload-target]")) {
      uploadFiles(event.target.files, String(event.target.dataset.uploadTarget || ""));
      return;
    }
    if (!event.target.matches("[data-form-key]")) return;
    syncForm();
    saveState();
  });

  app.addEventListener("click", (event) => {
    const choice = event.target.closest("[data-choice-key]");
    if (choice) {
      if (choice.disabled) return;
      const key = String(choice.dataset.choiceKey || "");
      const value = String(choice.dataset.choiceValue || "");
      if (!key || state.form[key] === value) return;
      state.form[key] = value;
      saveState();
      render();
      return;
    }
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const action = button.dataset.action;
    if (action === "start") startJob();
    if (action === "recover") recoverJob();
    if (action === "cancel") cancelRun();
    if (action === "run-stage") runStage(String(button.dataset.stage || ""));
    if (action === "fallback") runStage(fallbackStage(), true);
    if (action === "save-artifact") saveArtifact(String(button.dataset.artifact || ""));
    if (action === "refresh-history") loadHistory();
    if (action === "open-history") openHistory(String(button.dataset.jobId || ""));
    if (action === "delete-history") deleteHistory(String(button.dataset.jobId || ""));
    if (action === "artifact") {
      const selected = String(button.dataset.artifact || "");
      state.selectedArtifact = state.selectedArtifact === selected ? "" : selected;
      render();
    }
    if (action === "download-artifact") {
      const key = String(button.dataset.artifact || "");
      const files = (state.job || {}).recovered_files || {};
      const extension = key === "story_state" ? "json" : (key === "draft" ? "txt" : "md");
      downloadText(
        String(files[key] || ""),
        `${state.form.project_title || "NPC剧本团队"}-${ARTIFACT_LABELS[key] || key}.${extension}`,
      );
    }
    if (action === "new-job") {
      window.localStorage.removeItem(STORAGE_KEY);
      const history = Array.isArray(state.history) ? state.history : [];
      const configStatus = state.configStatus;
      state = clone(initialState);
      state.history = history;
      state.configStatus = configStatus;
      state.job = null;
      state.selectedArtifact = "";
      state.error = "";
      saveState();
      render();
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
    if (action === "download") {
      const text = String((state.job || {}).final_script || "");
      downloadText(text, `${state.form.project_title || "NPC剧本团队成品"}.txt`);
    }
    if (action === "download-word" && state.job && state.job.job_id) {
      window.location.href = apiUrl(
        `/api/new-workflow-test/npc/jobs/${encodeURIComponent(state.job.job_id)}/export/docx`,
      );
    }
  });

  render();
  loadConfig();
  loadLatestJob();
  loadHistory();
})();
