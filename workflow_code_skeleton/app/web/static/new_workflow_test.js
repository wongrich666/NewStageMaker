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
      source_last_episode: 0,
      continuation_target_episode: 10,
      continuation_policy: "strict",
      episode_word_count: 800,
      episode_duration_seconds: 90,
      scenes_per_episode: "1",
      source_text: "",
      continuation_bible: "",
      adaptation_direction: "",
      execution_mode: "step",
      distilled_skill_id: "",
      distilled_skill_version_id: "",
    },
    skillCatalog: [],
    skillCatalogLoading: false,
    skillPickerOpen: false,
    job: null,
    history: [],
    expandedProjects: [],
    taskFilter: "all",
    error: "",
    loading: false,
    selectedArtifact: "",
    activeView: "brief",
    editor: {
      open: false,
      artifactKey: "",
      stageId: "",
      mode: "manual",
      sectionId: "full",
      content: "",
      dirty: false,
      notice: "",
      feedback: "",
      continueAfter: false,
    },
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
        activeView: state.activeView,
        expandedProjects: Array.isArray(state.expandedProjects) ? state.expandedProjects : [],
        taskFilter: state.taskFilter || "all",
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

  function projectGroupKey(title) {
    return String(title || "未命名剧本")
      .trim()
      .replace(/^《\s*|\s*》$/g, "")
      .replace(/\s+/g, " ")
      .toLocaleLowerCase("zh-CN");
  }

  function groupHistory(items) {
    const groups = new Map();
    items.forEach((item) => {
      const key = projectGroupKey(item.project_title);
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          title: String(item.project_title || "未命名剧本").trim(),
          versions: [],
        });
      }
      groups.get(key).versions.push(item);
    });
    return Array.from(groups.values()).map((group) => {
      group.versions.sort((a, b) => {
        const aTime = Date.parse(a.updated_at || a.created_at || "") || 0;
        const bTime = Date.parse(b.updated_at || b.created_at || "") || 0;
        return bTime - aTime;
      });
      group.latest = group.versions[0] || {};
      group.running = group.versions.filter((item) => ACTIVE_JOB_STATUSES.has(String(item.status || "").toLowerCase())).length;
      group.completed = group.versions.filter((item) => Boolean(item.has_final_script)).length;
      group.failed = group.versions.filter((item) => String(item.status || "").toLowerCase() === "failed").length;
      return group;
    }).sort((a, b) => {
      const aTime = Date.parse(a.latest.updated_at || a.latest.created_at || "") || 0;
      const bTime = Date.parse(b.latest.updated_at || b.latest.created_at || "") || 0;
      return bTime - aTime;
    });
  }

  function formatHistoryTime(value) {
    const date = new Date(value || "");
    if (Number.isNaN(date.getTime())) return "时间未知";
    const now = new Date();
    const sameYear = date.getFullYear() === now.getFullYear();
    const datePart = `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    const timePart = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
    return `${sameYear ? datePart : `${date.getFullYear()}-${datePart}`} ${timePart}`;
  }

  function isProjectExpanded(group) {
    const expanded = new Set(Array.isArray(state.expandedProjects) ? state.expandedProjects : []);
    return expanded.has(group.key);
  }

  function expandProjectForJob(job) {
    const title = ((job || {}).request || {}).project_title || "";
    if (!title) return;
    const expanded = new Set(Array.isArray(state.expandedProjects) ? state.expandedProjects : []);
    expanded.add(projectGroupKey(title));
    state.expandedProjects = Array.from(expanded);
  }

  function toggleProjectGroup(key) {
    const expanded = new Set(Array.isArray(state.expandedProjects) ? state.expandedProjects : []);
    if (expanded.has(key)) expanded.delete(key);
    else expanded.add(key);
    state.expandedProjects = Array.from(expanded);
    saveState();
    render();
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

  function formatTargetDuration(seconds) {
    const safeSeconds = Math.max(0, Math.round(Number(seconds) || 0));
    const hours = Math.floor(safeSeconds / 3600);
    const minutes = Math.floor((safeSeconds % 3600) / 60);
    const remainder = safeSeconds % 60;
    if (hours) return `${hours}小时${minutes ? `${minutes}分` : ""}`;
    if (minutes) return `${minutes}分${remainder ? `${remainder}秒` : ""}`;
    return `${remainder}秒`;
  }

  function detectLastEpisode(text = state.form.source_text) {
    const value = String(text || "");
    const pattern = /(?:^|\n)\s*(?:#{1,6}\s*)?(?:第\s*(\d{1,3})\s*集|(?:EPISODE|EP)\s*(\d{1,3})\b)/gi;
    let lastEpisode = 0;
    let match;
    while ((match = pattern.exec(value)) !== null) {
      lastEpisode = Math.max(lastEpisode, Number(match[1] || match[2]) || 0);
    }
    return lastEpisode;
  }

  function continuationLastEpisode() {
    return detectLastEpisode() || Math.max(0, Number(state.form.source_last_episode) || 0);
  }

  function generationEpisodeCount() {
    if (state.form.mode !== "续写") {
      return Math.max(1, Number(state.form.episodes) || 1);
    }
    const lastEpisode = continuationLastEpisode();
    const targetEpisode = Math.max(0, Number(state.form.continuation_target_episode) || 0);
    if (!lastEpisode) return 0;
    return Math.max(0, targetEpisode - lastEpisode);
  }

  function deliveryRange() {
    if (state.form.mode !== "续写") {
      const count = Math.max(1, Number(state.form.episodes) || 1);
      return { start: 1, end: count, count };
    }
    const lastEpisode = continuationLastEpisode();
    const targetEpisode = Math.max(0, Number(state.form.continuation_target_episode) || 0);
    return {
      start: lastEpisode ? lastEpisode + 1 : 0,
      end: targetEpisode,
      count: Math.max(0, targetEpisode - lastEpisode),
    };
  }

  function updateDurationPreview() {
    const preview = app.querySelector("[data-duration-preview]");
    if (!preview) return;
    const total = generationEpisodeCount()
      * Math.max(15, Number(state.form.episode_duration_seconds) || 90);
    preview.textContent = formatTargetDuration(total);
    const hint = app.querySelector("[data-duration-hint]");
    if (hint) {
      hint.textContent = `${generationEpisodeCount()} 集 × ${Math.max(15, Number(state.form.episode_duration_seconds) || 90)} 秒`;
    }
  }

  function updateContinuationPreview() {
    if (state.form.mode !== "续写") return;
    const title = app.querySelector("[data-continuation-title]");
    const detail = app.querySelector("[data-continuation-detail]");
    const runRange = app.querySelector("[data-delivery-range]");
    const startButton = app.querySelector('[data-action="start"]');
    const status = app.querySelector(".nwt-continuation-status");
    if (!title || !detail || !status) return;
    const detected = detectLastEpisode();
    const lastEpisode = continuationLastEpisode();
    const range = deliveryRange();
    const ready = Boolean(lastEpisode && range.end > lastEpisode);
    status.classList.toggle("ready", ready);
    status.classList.toggle("needs-input", !ready);
    title.textContent = detected
      ? `已识别写至第${detected}集`
      : lastEpisode
        ? `当前按第${lastEpisode}集计算`
        : "未识别到集号";
    detail.textContent = ready
      ? `将只生成第${range.start}集至第${range.end}集，共${range.count}集；已有正文不会重写。`
      : "请上传带有“第N集”标题的已有剧本，或手动填写当前最后一集；目标集数必须更大。";
    if (runRange && !(state.job || {}).job_id) {
      runRange.textContent = ready
        ? `本次交付第${range.start}集至第${range.end}集，共${range.count}集`
        : "请先确认续写范围";
    }
    if (startButton && !state.loading && !isActive() && (state.configStatus || {}).ready) {
      startButton.disabled = !ready;
    }
  }

  function isActive(job = state.job) {
    return Boolean(job && ACTIVE_JOB_STATUSES.has(String(job.status || "").toLowerCase()));
  }

  function renderSignature(job) {
    const value = job && typeof job === "object" ? job : {};
    const files = value.recovered_files && typeof value.recovered_files === "object"
      ? value.recovered_files
      : {};
    const stages = Array.isArray(value.team_stages)
      ? value.team_stages.map((stage) => ({
        id: stage.id,
        name: stage.name,
        status: stage.status,
        error: stage.error,
        output_key: stage.output_key,
      }))
      : [];
    return JSON.stringify({
      status: value.status,
      status_text: value.status_text,
      progress: value.progress,
      active_stage: value.active_stage,
      execution_target: value.execution_target,
      stages,
      batch_progress: value.batch_progress,
      remote_checkpoint: value.remote_checkpoint,
      remote_retry_count: value.remote_retry_count,
      stage_resume_text_length: String(value.stage_resume_text || "").length,
      recovered_files: Object.fromEntries(
        Object.entries(files).map(([key, content]) => [key, String(content || "").length]),
      ),
      final_script_length: String(value.final_script || "").length,
      delivery_script_length: String(value.delivery_script || "").length,
      quality_gate: value.quality_gate,
      request_warnings: value.request_warnings,
      error: value.error,
      poll_warning: value.poll_warning,
      fallback_reason: value.fallback_reason,
      build_log_url: value.build && value.build.build_log_url,
      usage_metrics: value.usage_metrics,
    });
  }

  function historyRenderSignature(items) {
    return JSON.stringify((Array.isArray(items) ? items : []).map((item) => ({
      job_id: item.job_id,
      project_title: item.project_title,
      production_type: item.production_type,
      mode: item.mode,
      episodes: item.episodes,
      episode_start: item.episode_start,
      episode_end: item.episode_end,
      status: item.status,
      status_text: item.status_text,
      progress: item.progress,
      has_final_script: item.has_final_script,
    })));
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

  function memberHasOutput(member, job = state.job) {
    if (!member || !job) return false;
    if (member.key === "final_script") {
      return Boolean(String(job.final_script || job.delivery_script || "").trim());
    }
    const files = job.recovered_files && typeof job.recovered_files === "object"
      ? job.recovered_files
      : {};
    return Boolean(String(files[member.key] || "").trim());
  }

  function memberVisualStatus(member, job = state.job) {
    const explicit = stageStatusByName(member.name);
    if (["failed", "error", "failure", "cancel", "cancelled"].includes(String(explicit).toLowerCase())) {
      return "failed";
    }
    if (
      member.id === String((job || {}).active_stage || "")
      && isActive(job)
    ) {
      return "running";
    }
    if (["running", "start", "in_progress"].includes(String(explicit).toLowerCase())) {
      return "running";
    }
    if (memberHasOutput(member, job)) return "success";
    return explicit;
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

  function liveRuntimeText(job) {
    const activeDuration = formatDuration(job.active_stage_elapsed_ms);
    if (!isActive(job)) return "";
    return `CNB Runner 已连接 · 30秒心跳${activeDuration ? ` · 已运行 ${activeDuration}` : ""}`;
  }

  function patchLiveTelemetry(job) {
    const progress = Math.max(0, Math.min(100, Number(job.progress) || 0));
    const statusText = String(job.status_text || "填写任务后开始创作");
    app.querySelectorAll("[data-live-status-text]").forEach((node) => {
      node.textContent = statusText;
    });
    const runtime = app.querySelector("[data-live-runtime]");
    const runtimeText = liveRuntimeText(job);
    if (runtime) {
      runtime.hidden = !runtimeText;
      const textNode = runtime.querySelector("[data-live-runtime-text]");
      if (textNode) textNode.textContent = runtimeText;
    }
    const progressBar = app.querySelector("[data-live-progress]");
    if (progressBar) progressBar.style.width = `${progress}%`;
    const progressValue = app.querySelector("[data-live-progress-value]");
    if (progressValue) progressValue.textContent = `${progress}%`;
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

  function renderSkillCatalog(active) {
    const skills = Array.isArray(state.skillCatalog) ? state.skillCatalog : [];
    const selectedId = String(state.form.distilled_skill_id || "");
    const cards = skills.map((skill) => {
      const selected = selectedId === String(skill.skill_id || "");
      return `
        <button class="nwt-skill-card ${selected ? "selected" : ""}" type="button"
          data-skill-id="${escapeHtml(skill.skill_id)}"
          data-skill-version-id="${escapeHtml(skill.version_id)}"
          aria-pressed="${selected}" ${active ? "disabled" : ""}>
          <img src="${escapeHtml(skill.cover_url)}" alt="" loading="lazy" />
          <span class="nwt-skill-shade"></span>
          <span class="nwt-skill-check">${icon(selected ? "check" : "plus", 14)}</span>
          <span class="nwt-skill-card-copy">
            <small>${escapeHtml(skill.genre || "垂类剧本")} · ${escapeHtml(skill.market || "通用市场")}</small>
            <strong>${escapeHtml(skill.name)}</strong>
            <span><b>${escapeHtml(skill.version)}</b><i>${escapeHtml(skill.module_count)} 个专业模块</i><em>${escapeHtml(skill.score)} 分</em></span>
          </span>
        </button>`;
    }).join("");
    return `
      <div class="nwt-skill-picker">
        <button class="nwt-skill-none ${selectedId ? "" : "selected"}" type="button"
          data-skill-id="" data-skill-version-id="" aria-pressed="${!selectedId}" ${active ? "disabled" : ""}>
          <span>${icon("sparkles", 18)}</span>
          <strong>基础专业工作流</strong>
          <small>不套用垂类样本架构</small>
        </button>
        ${state.skillCatalogLoading ? `<div class="nwt-skill-loading">${icon("loader-circle", 18)} 正在读取已发布 Skill...</div>` : cards}
        ${!state.skillCatalogLoading && !skills.length ? `
          <a class="nwt-skill-empty" href="${escapeHtml(apiUrl('/distillation-lab'))}">
            <span>${icon("flask-conical", 19)}</span>
            <strong>还没有已发布 Skill</strong>
            <small>前往爆款蒸馏实验室创建并发布</small>
          </a>` : ""}
      </div>`;
  }

  function selectedCatalogSkill() {
    return (state.skillCatalog || []).find(
      (item) => String(item.skill_id || "") === String(state.form.distilled_skill_id || ""),
    ) || null;
  }

  function renderTeam() {
    const job = state.job || {};
    const files = job.recovered_files || {};
    const active = isActive();
    const remotelyControllable = Boolean(job.job_id);
    return TEAM.map((member, index) => {
      const status = memberVisualStatus(member, job);
      const [label, klass] = statusLabel(status);
      const hasOutput = memberHasOutput(member, job);
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
      const timing = job.stage_timings && typeof job.stage_timings === "object"
        ? job.stage_timings[member.id]
        : null;
      const durationMs = Number(
        (timing && (timing.elapsed_ms || timing.duration_ms))
        || (stageInfo && stageInfo.duration)
        || 0,
      );
      const duration = formatDuration(durationMs);
      const durationLabel = duration
        ? `${timing && timing.status === "running" ? "已运行" : "耗时"} ${duration}`
        : "";
      return `
        <article class="nwt-member ${klass} ${status === "running" ? "active" : ""}" data-stage-status="${escapeHtml(klass || "waiting")}">
          <div class="nwt-member-rail">
            <span class="nwt-member-index">${status === "running" ? '<i class="nwt-spinner"></i>' : klass === "done" ? icon("check", 15) : String(index + 1).padStart(2, "0")}</span>
            ${index < TEAM.length - 1 ? '<span class="nwt-rail-line"></span>' : ""}
          </div>
          <div class="nwt-member-copy">
            <div class="nwt-member-title">
              <strong>${escapeHtml(member.name)}</strong>
              <span class="nwt-member-status ${klass}">${klass === "done" ? icon("check", 11) : klass === "running" ? '<i class="nwt-mini-pulse"></i>' : ""}${escapeHtml(label)}</span>
            </div>
            <p>${escapeHtml(member.responsibility)}</p>
            <div class="nwt-member-meta">
              ${chars ? `<span>${formatNumber(chars)} 字</span>` : ""}
              ${durationLabel ? `<span>${escapeHtml(durationLabel)}</span>` : ""}
              ${status === "running" && job.batch_progress ? `<span>第${escapeHtml(job.batch_progress.current_start)}-${escapeHtml(job.batch_progress.current_end)}集</span>` : ""}
            </div>
          </div>
          <div class="nwt-member-actions">
            ${hasOutput ? `
              <button class="nwt-stage-edit" type="button" data-action="open-editor" data-artifact="${member.key}" data-stage="${member.id}">
                ${icon("file-pen-line", 14)}<span>查看与修改</span>
              </button>
            ` : `
              <button class="nwt-stage-run" type="button" data-action="run-stage" data-stage="${member.id}" ${canRun ? "" : "disabled"}>
                ${icon("play", 14)}<span>运行</span>
              </button>
            `}
          </div>
        </article>
      `;
    }).join("");
  }

  function renderTeamFlow() {
    const job = state.job || {};
    const activeStage = state.job && state.job.active_stage;
    const completedCount = TEAM.filter((member) => memberVisualStatus(member, job) === "success").length;
    return `
      <div class="nwt-team-flow-wrap">
        <div class="nwt-team-flow-head">
          <div>
            <span>${icon("route", 14)}创作链路</span>
            <small>每个节点完成后自动保存，可随时从当前进度继续</small>
          </div>
          <strong><b>${completedCount}</b> / ${TEAM.length} 节点完成</strong>
        </div>
        <div class="nwt-team-flow" aria-label="剧本团队工作流">
          ${TEAM.map((member, index) => {
            const status = memberVisualStatus(member, job);
            const [, klass] = statusLabel(status);
            const isRunning = member.id === activeStage && isActive();
            return `
              <div class="nwt-flow-step ${klass} ${isRunning ? "active" : ""}" data-stage-status="${escapeHtml(klass || "waiting")}">
                <span class="nwt-flow-node">
                  ${isRunning ? icon("loader-circle", 15) : klass === "done" ? icon("check", 15) : klass === "error" ? icon("x", 14) : String(index + 1)}
                </span>
                <strong>${escapeHtml(member.name)}</strong>
                <small>${klass === "done" ? "已完成" : isRunning ? "正在创作" : klass === "error" ? "需要处理" : "等待接力"}</small>
                ${index < TEAM.length - 1 ? '<i class="nwt-flow-connector"><b></b></i>' : ""}
              </div>
            `;
          }).join("")}
        </div>
      </div>
    `;
  }

  function renderRecoveredNotice(keys) {
    const labels = keys
      .map((key) => ARTIFACT_LABELS[key] || key)
      .filter(Boolean);
    return `
      <div class="nwt-recovered">
        <span class="nwt-recovered-icon">${icon("archive-restore", 16)}</span>
        <div>
          <strong>已恢复 ${labels.length} 项创作产物</strong>
          <small>${escapeHtml(labels.join(" · "))}</small>
        </div>
      </div>
    `;
  }

  function renderBatchProgress(job) {
    const total = Math.max(1, Number((job.request || {}).episodes || state.form.episodes) || 1);
    const episodeStart = Math.max(1, Number((job.request || {}).episode_start) || 1);
    const episodeEnd = Math.max(
      episodeStart,
      Number((job.request || {}).episode_end) || (episodeStart + total - 1),
    );
    const progress = job.batch_progress || {};
    const batchSize = Math.max(1, Number(progress.batch_size) || Math.min(5, total));
    const ranges = [];
    for (let start = episodeStart; start <= episodeEnd; start += batchSize) {
      ranges.push([start, Math.min(episodeEnd, start + batchSize - 1)]);
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
    const runtimeText = liveRuntimeText(job);
    return `
      <aside class="nwt-monitor">
        <div class="nwt-monitor-head">
          <div>
            <span class="nwt-eyebrow">CNB 远程运行</span>
            <h2>${escapeHtml(activeStage ? activeStage.name : (job.status_text || "等待任务"))}</h2>
          </div>
          <span class="nwt-live-state ${isActive(job) ? "active" : ""}">${isActive(job) ? "运行中" : progress === 100 ? "已完成" : "待命"}</span>
        </div>
        <p class="nwt-monitor-message" data-live-status-text>${escapeHtml(job.status_text || "填写任务后开始创作")}</p>
        <div class="nwt-runtime-live" data-live-runtime ${runtimeText ? "" : "hidden"}><i class="nwt-mini-pulse"></i><span data-live-runtime-text>${escapeHtml(runtimeText)}</span></div>
        <div class="nwt-monitor-progress"><span data-live-progress style="width:${progress}%"></span></div>
        <div class="nwt-monitor-progress-meta"><strong data-live-progress-value>${progress}%</strong><span>${escapeHtml(job.job_id || "尚未创建任务")}</span></div>
        ${job.job_id ? renderBatchProgress(job) : ""}
        ${renderUsage(job)}
        <div class="nwt-cost-note">
          <strong>动态成本控制</strong>
          <span>自动与分步模式均提交 CNB；云端失败时保留断点并等待重新提交。</span>
        </div>
      </aside>
    `;
  }

  function renderBuildLink() {
    const url = state.job && state.job.build && state.job.build.build_log_url;
    if (!url) return "";
    return `<a class="nwt-link" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">查看 CNB 执行记录</a>`;
  }

  function artifactContent(key) {
    const job = state.job || {};
    if (key === "final_script") return String(job.final_script || "");
    const files = job.recovered_files && typeof job.recovered_files === "object"
      ? job.recovered_files
      : {};
    return String(files[key] || "");
  }

  function artifactSections(content) {
    const text = String(content || "");
    const sections = [{ id: "full", title: "全文", start: 0, end: text.length }];
    if (!text.trim() || /^[\s]*[\[{]/.test(text)) return sections;
    const matches = [];
    const headingPattern = /^(#{1,4}\s+.+|第\s*[一二三四五六七八九十百零〇两\d]+\s*集(?:[：:·\s].*)?)\s*$/gm;
    let match;
    while ((match = headingPattern.exec(text)) !== null) {
      matches.push({
        start: match.index,
        title: String(match[1] || "").replace(/^#{1,4}\s*/, "").trim(),
      });
    }
    matches.forEach((item, index) => {
      sections.push({
        id: `section-${index}`,
        title: item.title || `片段 ${index + 1}`,
        start: item.start,
        end: index + 1 < matches.length ? matches[index + 1].start : text.length,
      });
    });
    return sections;
  }

  function currentEditorSection() {
    const editor = state.editor || initialState.editor;
    const sections = artifactSections(editor.content);
    return sections.find((item) => item.id === editor.sectionId) || sections[0];
  }

  function renderEditorWorkspace() {
    const editor = state.editor || {};
    if (!editor.open || !editor.artifactKey) return "";
    const member = TEAM.find((item) => item.id === editor.stageId || item.key === editor.artifactKey);
    if (!member) return "";
    const sections = artifactSections(editor.content);
    const selected = sections.find((item) => item.id === editor.sectionId) || sections[0];
    const selectedText = String(editor.content || "").slice(selected.start, selected.end);
    const active = isActive();
    const manual = editor.mode !== "rewrite";
    return `
      <div class="nwt-editor-backdrop" role="presentation" data-action="editor-backdrop">
        <section class="nwt-editor-workspace" role="dialog" aria-modal="true" aria-label="查看与修改 ${escapeHtml(member.name)}" data-editor-dialog>
          <header class="nwt-editor-head">
            <div>
              <span class="nwt-editor-kicker">${escapeHtml(member.name)}</span>
              <h2>${escapeHtml(ARTIFACT_LABELS[editor.artifactKey] || member.name)}</h2>
              <p>${formatNumber(String(editor.content || "").length)} 字 · 修改会保存到任务历史</p>
            </div>
            <div class="nwt-editor-head-actions">
              <button class="nwt-icon-btn" type="button" title="下载当前产物" data-action="download-artifact" data-artifact="${escapeHtml(editor.artifactKey)}">${icon("download", 17)}</button>
              <button class="nwt-icon-btn" type="button" title="关闭" data-action="close-editor">${icon("x", 18)}</button>
            </div>
          </header>
          <div class="nwt-editor-body">
            <aside class="nwt-editor-nav">
              <strong>内容定位</strong>
              <span>${sections.length > 1 ? `已识别 ${sections.length - 1} 个章节` : "当前产物按全文编辑"}</span>
              <nav>
                ${sections.map((item) => `
                  <button type="button" class="${item.id === selected.id ? "active" : ""}" data-action="select-editor-section" data-section-id="${item.id}">
                    ${icon(item.id === "full" ? "align-left" : "bookmark", 14)}
                    <span>${escapeHtml(item.title)}</span>
                  </button>
                `).join("")}
              </nav>
            </aside>
            <div class="nwt-editor-main">
              <div class="nwt-editor-mode" role="tablist" aria-label="修改方式">
                <button type="button" class="${manual ? "active" : ""}" data-action="editor-mode" data-mode="manual">
                  ${icon("text-cursor-input", 15)}<span>直接编辑</span>
                </button>
                <button type="button" class="${manual ? "" : "active"}" data-action="editor-mode" data-mode="rewrite">
                  ${icon("sparkles", 15)}<span>AI 按意见重写</span>
                </button>
              </div>
              ${editor.notice ? `<div class="nwt-editor-notice">${icon("circle-check", 15)}<span>${escapeHtml(editor.notice)}</span></div>` : ""}
              ${manual ? `
                <div class="nwt-editor-context">
                  <div><strong>${escapeHtml(selected.title)}</strong><span>${formatNumber(selectedText.length)} 字</span></div>
                  <p>直接保存会精确保留你的文字，并使依赖它的后续节点等待重新生成。</p>
                </div>
                <textarea class="nwt-editor-textarea" data-editor-section-text ${active ? "disabled" : ""}>${escapeHtml(selectedText)}</textarea>
                <footer class="nwt-editor-footer">
                  <span>${editor.dirty ? "有尚未保存的修改" : "当前内容已保存"}</span>
                  <button class="nwt-btn primary" type="button" data-action="save-editor" ${active ? "disabled" : ""}>${icon("save", 15)}<span>保存修改</span></button>
                </footer>
              ` : `
                <div class="nwt-editor-context">
                  <div><strong>让 ${escapeHtml(member.name)} 重写</strong><span>范围：${escapeHtml(selected.title)}</span></div>
                  <p>描述想达到的效果，系统会结合当前产物和上下文重新运行本节点。</p>
                </div>
                <div class="nwt-editor-suggestions">
                  ${["保留主线", "减少解释性对白", "加强开场钩子", "修复集间承接"].map((text) => `
                    <button type="button" data-action="append-feedback" data-feedback="${escapeHtml(text)}">${escapeHtml(text)}</button>
                  `).join("")}
                </div>
                <textarea class="nwt-editor-feedback" id="nwt-editor-feedback" placeholder="例如：保留现有主线，只重写第一集开场。用一句短促、有即时后果的话制造悬念，人物反应自然，不堆形容词。">${escapeHtml(editor.feedback || "")}</textarea>
                <footer class="nwt-editor-footer rewrite">
                  <label class="nwt-check"><input id="nwt-editor-continue" type="checkbox" ${editor.continueAfter ? "checked" : ""} /> 本节点完成后继续运行后续节点</label>
                  <button class="nwt-btn primary" type="button" data-action="rewrite-editor" ${active ? "disabled" : ""}>${icon("sparkles", 15)}<span>按意见重写本节点</span></button>
                </footer>
              `}
            </div>
          </div>
        </section>
      </div>
    `;
  }

  function renderTaskCenter() {
    const items = Array.isArray(state.history) ? state.history : [];
    const allGroups = groupHistory(items);
    const filter = ["all", "running", "delivered", "attention"].includes(state.taskFilter)
      ? state.taskFilter
      : "all";
    const groups = allGroups.filter((group) => {
      if (filter === "running") return group.running > 0;
      if (filter === "delivered") return group.completed > 0;
      if (filter === "attention") return group.failed > 0 || (!group.running && !group.completed);
      return true;
    });
    const running = items.filter((item) => ACTIVE_JOB_STATUSES.has(String(item.status || "").toLowerCase())).length;
    const delivered = items.filter((item) => Boolean(item.has_final_script)).length;
    const attention = allGroups.filter((group) => group.failed > 0 || (!group.running && !group.completed)).length;
    return `
      <aside class="nwt-task-center">
        <div class="nwt-task-head">
          <div>
            <span class="nwt-eyebrow">PROJECTS</span>
            <h2>剧本项目</h2>
            <p>按项目归档，展开查看每个生成版本</p>
          </div>
          <button class="nwt-icon-btn" type="button" title="刷新任务" data-action="refresh-history">${icon("refresh-cw")}</button>
        </div>
        <div class="nwt-task-summary">
          <div class="running"><strong>${running}</strong><span>运行中</span></div>
          <div class="project"><strong>${allGroups.length}</strong><span>项目</span></div>
          <div class="delivered"><strong>${delivered}</strong><span>已交付</span></div>
        </div>
        <button class="nwt-btn primary nwt-new-task" type="button" data-action="new-job">
          ${icon("plus", 17)}<span>新建剧本任务</span>
        </button>
        <div class="nwt-task-toolbar" role="tablist" aria-label="项目筛选">
          ${[
            ["all", "全部", allGroups.length],
            ["running", "运行中", running],
            ["delivered", "已交付", delivered],
            ["attention", "需处理", attention],
          ].map(([key, label, count]) => `
            <button type="button" class="${filter === key ? "active" : ""}" data-action="task-filter" data-task-filter="${key}" role="tab" aria-selected="${filter === key ? "true" : "false"}">
              <span>${label}</span><b>${count}</b>
            </button>
          `).join("")}
        </div>
        <div class="nwt-task-list-caption"><span>${filter === "all" ? "全部项目" : ["", "运行中的项目", "已交付的项目", "需要处理的项目"][ ["all", "running", "delivered", "attention"].indexOf(filter) ]}</span><small>${groups.length} 个</small></div>
        <div class="nwt-task-list">
          ${groups.length ? groups.map((group) => {
            const expanded = isProjectExpanded(group);
            const active = Boolean(state.job && group.versions.some((item) => item.job_id === state.job.job_id));
            const latest = group.latest || {};
            const groupState = group.running
              ? "running"
              : group.failed
                ? "failed"
                : group.completed
                  ? "done"
                  : "";
            const statusText = group.running
              ? `${group.running} 个版本运行中`
              : group.failed
                ? `${group.failed} 个版本需处理`
                : group.completed
                  ? `${group.completed} 个版本已交付`
                  : "待生成";
            const statusLabel = group.running ? "运行中" : group.failed ? "需处理" : group.completed ? "已交付" : "待生成";
            return `
              <section class="nwt-project-group ${expanded ? "expanded" : ""} ${active ? "active" : ""}">
                <button class="nwt-project-toggle" type="button" data-action="toggle-project" data-project-key="${escapeHtml(group.key)}" aria-expanded="${expanded ? "true" : "false"}">
                  <span class="nwt-project-icon">${icon("folder-kanban", 16)}</span>
                  <span class="nwt-project-copy">
                    <span class="nwt-task-title">
                      <strong>${escapeHtml(group.title || "未命名剧本")}</strong>
                      <span class="nwt-project-badge ${groupState}">${statusLabel}</span>
                    </span>
                    <span class="nwt-project-meta">
                      <span>${group.versions.length} 个版本</span>
                      <span>${escapeHtml(formatHistoryTime(latest.updated_at || latest.created_at))}</span>
                    </span>
                    <span class="nwt-task-status"><i class="nwt-task-state ${groupState}"></i>${escapeHtml(statusText)}</span>
                  </span>
                  <span class="nwt-project-chevron" aria-hidden="true">${icon("chevron-down", 15)}</span>
                </button>
                <div class="nwt-version-list" ${expanded ? "" : "hidden"}>
                  ${group.versions.map((item, index) => {
                    const itemActive = Boolean(state.job && state.job.job_id === item.job_id);
                    const itemRunning = ACTIVE_JOB_STATUSES.has(String(item.status || "").toLowerCase());
                    const versionNumber = group.versions.length - index;
                    return `
                      <article class="nwt-version-item ${itemActive ? "active" : ""}">
                        <button class="nwt-version-open" type="button" data-action="open-history" data-job-id="${escapeHtml(item.job_id)}">
                          <span class="nwt-version-line">
                            <strong>版本 ${versionNumber}</strong>
                            <time>${escapeHtml(formatHistoryTime(item.updated_at || item.created_at))}</time>
                          </span>
                          <span class="nwt-version-detail">${escapeHtml(item.production_type || "剧本")} · ${item.mode === "续写" ? `续写第${escapeHtml(item.episode_start || "?")}-${escapeHtml(item.episode_end || "?")}集` : `${escapeHtml(item.episodes || 0)}集`}</span>
                          <span class="nwt-version-status"><i class="nwt-task-state ${itemRunning ? "running" : item.has_final_script ? "done" : String(item.status || "").toLowerCase() === "failed" ? "failed" : ""}"></i>${escapeHtml(item.has_final_script ? "已交付" : item.status_text || item.status || "待生成")}</span>
                          <span class="nwt-task-progress"><i style="width:${Math.max(0, Math.min(100, Number(item.progress) || 0))}%"></i></span>
                        </button>
                        <button class="nwt-icon-btn danger nwt-version-delete" type="button" title="${itemRunning ? "运行中的版本不能删除" : "删除这个版本"}" data-action="delete-history" data-job-id="${escapeHtml(item.job_id)}" ${itemRunning ? "disabled" : ""}>${icon("trash-2", 14)}</button>
                      </article>
                    `;
                  }).join("")}
                </div>
              </section>
            `;
          }).join("") : `<div class="nwt-task-empty"><span>${filter === "all" ? "暂无项目" : "没有符合条件的项目"}</span><small>${filter === "all" ? "创建一个剧本任务后，会在这里持续显示版本进度" : "可以切换筛选条件查看其他项目"}</small></div>`}
        </div>
      </aside>
    `;
  }

  function render() {
    const job = state.job || {};
    const progress = Math.max(0, Math.min(100, Number(job.progress) || 0));
    const active = isActive();
    const finalScript = String(job.final_script || "");
    const deliveryScript = String(job.delivery_script || finalScript);
    const canRecover = Boolean(job.job_id && String(job.status || "").toLowerCase() === "failed" && !finalScript);
    const canLocalFallback = Boolean(
      job.job_id
      && String(job.status || "").toLowerCase() === "failed"
      && String(job.execution_target || "") === "remote_cnb"
      && Number(job.remote_retry_count || 0) >= Number(job.remote_retry_limit || 0)
    );
    const qualityGate = job.quality_gate && typeof job.quality_gate === "object" ? job.quality_gate : {};
    const gateErrors = Array.isArray(qualityGate.errors) ? qualityGate.errors : [];
    const gateWarnings = Array.isArray(qualityGate.warnings) ? qualityGate.warnings : [];
    const recoveredFiles = job.recovered_files && typeof job.recovered_files === "object"
      ? Object.keys(job.recovered_files)
      : [];
    const detectedLastEpisode = detectLastEpisode();
    const currentLastEpisode = continuationLastEpisode();
    const delivery = deliveryRange();
    const episodes = delivery.count;
    const continuationReady = state.form.mode !== "续写"
      || Boolean(currentLastEpisode && delivery.end > currentLastEpisode);
    const requestWarnings = Array.isArray(job.request_warnings) ? job.request_warnings : [];
    const activeView = ["brief", "team", "delivery"].includes(state.activeView)
      ? state.activeView
      : (finalScript ? "delivery" : job.job_id ? "team" : "brief");
    app.innerHTML = `
      <div class="nwt-shell nwt-view-${escapeHtml(activeView)}">
        <header class="nwt-header">
          <div class="nwt-brand">
            <span class="nwt-brand-mark">${icon("clapperboard", 22)}</span>
            <div>
              <h1>专业剧本制作台</h1>
              <p>项目制创作 · 专业编剧协作 · 全过程可追踪</p>
            </div>
          </div>
          <div class="nwt-actions">
            <a class="nwt-btn" href="${escapeHtml(config.workspaceUrl || "/workspace")}">${icon("arrow-left", 15)}<span>返回工作台</span></a>
          </div>
        </header>

        ${renderConfig()}

        <div class="nwt-studio-layout">
        ${renderTaskCenter()}
        <main class="nwt-main">
        <nav class="nwt-viewbar" aria-label="制作台工作区">
          <button type="button" class="${activeView === "brief" ? "active" : ""}" data-action="switch-view" data-view="brief" aria-pressed="${activeView === "brief"}">
            ${icon("sliders-horizontal", 16)}
            <span><strong>创作设置</strong><small>需求与生产规格</small></span>
          </button>
          <button type="button" class="${activeView === "team" ? "active" : ""}" data-action="switch-view" data-view="team" aria-pressed="${activeView === "team"}">
            ${icon("workflow", 16)}
            <span><strong>团队制作</strong><small>节点与中间产物</small></span>
            ${active ? '<i class="nwt-tab-live"></i>' : ""}
          </button>
          <button type="button" class="${activeView === "delivery" ? "active" : ""}" data-action="switch-view" data-view="delivery" aria-pressed="${activeView === "delivery"}">
            ${icon("file-check-2", 16)}
            <span><strong>成品交付</strong><small>终稿与文件下载</small></span>
            ${finalScript ? '<i class="nwt-tab-ready">已就绪</i>' : ""}
          </button>
        </nav>

        <div class="nwt-view-panel nwt-brief-view ${activeView === "brief" ? "active" : ""}">
        <section class="nwt-setup">
          <div class="nwt-section-head">
            <div class="nwt-section-title">
              <span class="nwt-section-icon">${icon("clapperboard", 18)}</span>
              <div>
              <h2>项目创作要求</h2>
              <p>先定义故事方向和交付规格，团队会据此建立统一创作合同。</p>
              </div>
            </div>
          </div>
          <div class="nwt-form-band">
            <div class="nwt-form-band-head">
              <span>01</span>
              <div><strong>项目定位</strong><small>确定作品身份、受众和题材方向</small></div>
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
                <button class="nwt-segment-option ${state.form.mode === "续写" ? "active" : ""}" type="button" data-choice-key="mode" data-choice-value="续写" aria-pressed="${state.form.mode === "续写"}" ${active ? "disabled" : ""}>
                  ${icon("forward", 14)}<span>续写</span>
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
          </div>
          </div>
          <div class="nwt-form-band nwt-skill-band ${state.skillPickerOpen ? "open" : ""}">
            <button class="nwt-skill-toggle" type="button" data-action="toggle-skill-picker" aria-expanded="${state.skillPickerOpen}">
              <span class="nwt-band-index">02</span>
              <span class="nwt-skill-toggle-copy"><strong>创作 Skill</strong><small>选择后，七个编剧节点按职责读取对应垂类架构</small></span>
              <span class="nwt-skill-current">
                ${selectedCatalogSkill() ? `<b>${escapeHtml(selectedCatalogSkill().name)}</b><small>${escapeHtml(selectedCatalogSkill().version)} · 已关联</small>` : `<b>基础专业工作流</b><small>未关联垂类 Skill</small>`}
              </span>
              <span class="nwt-skill-toggle-icon">${icon(state.skillPickerOpen ? "chevron-up" : "chevron-down", 17)}</span>
            </button>
            ${state.skillPickerOpen ? `
              <div class="nwt-skill-picker-panel">
                ${renderSkillCatalog(active)}
                <div class="nwt-skill-contract">
                  ${icon("lock-keyhole", 14)}
                  <span>${state.form.distilled_skill_id
                    ? "任务创建后锁定当前发布版本；后续迭代不会改变本次创作。"
                    : "未选择时使用平台基础专业 Skill，仍可正常生成高质量剧本。"}</span>
                </div>
              </div>` : ""}
          </div>
          <div class="nwt-form-band">
            <div class="nwt-form-band-head">
              <span>03</span>
              <div><strong>制作规格</strong><small>控制篇幅、场景密度和执行节奏</small></div>
            </div>
          <div class="nwt-form-grid nwt-form-grid-spec">
            ${state.form.mode === "续写" ? `
              <label class="nwt-field">
                <span>续写到第几集</span>
                <input type="number" min="2" max="999" data-form-key="continuation_target_episode" value="${escapeHtml(state.form.continuation_target_episode)}" ${active ? "disabled" : ""} />
                <small class="nwt-field-hint">填写最终希望写到的集号，系统自动计算新增集数</small>
              </label>
              ${detectedLastEpisode ? "" : `
                <label class="nwt-field">
                  <span>当前最后一集</span>
                  <input type="number" min="1" max="998" data-form-key="source_last_episode" value="${escapeHtml(state.form.source_last_episode || "")}" placeholder="未识别时手动填写" ${active ? "disabled" : ""} />
                  <small class="nwt-field-hint">上传或粘贴正文后通常会自动识别</small>
                </label>
              `}
            ` : `
              <label class="nwt-field">
                <span>总集数</span>
                <input type="number" min="1" max="120" data-form-key="episodes" value="${escapeHtml(state.form.episodes)}" ${active ? "disabled" : ""} />
              </label>
            `}
            <label class="nwt-field">
              <span>每集目标字数</span>
              <input type="number" min="100" max="5000" data-form-key="episode_word_count" value="${escapeHtml(state.form.episode_word_count)}" ${active ? "disabled" : ""} />
              <small class="nwt-field-hint">不少于目标值，最多上浮10%</small>
            </label>
            <label class="nwt-field">
              <span>每集视频时长（秒）</span>
              <input type="number" min="15" max="1800" step="5" data-form-key="episode_duration_seconds" value="${escapeHtml(state.form.episode_duration_seconds)}" ${active ? "disabled" : ""} />
              <small class="nwt-field-hint">对白、停顿、动作和镜头共同计时</small>
            </label>
            <div class="nwt-field nwt-duration-total" aria-live="polite">
              <span>全剧预计时长</span>
              <strong data-duration-preview>${escapeHtml(formatTargetDuration(generationEpisodeCount() * (Number(state.form.episode_duration_seconds) || 90)))}</strong>
              <small class="nwt-field-hint" data-duration-hint>${escapeHtml(generationEpisodeCount())} 集 × ${escapeHtml(state.form.episode_duration_seconds)} 秒</small>
            </div>
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
          </div>
          ${state.form.mode === "续写" ? `
            <div class="nwt-continuation-status ${continuationReady ? "ready" : "needs-input"}" aria-live="polite">
              <span class="nwt-continuation-icon">${icon(continuationReady ? "scan-search" : "circle-alert", 17)}</span>
              <div>
                <strong data-continuation-title>${detectedLastEpisode ? `已识别写至第${detectedLastEpisode}集` : currentLastEpisode ? `当前按第${currentLastEpisode}集计算` : "未识别到集号"}</strong>
                <small data-continuation-detail>${continuationReady
                  ? `将只生成第${delivery.start}集至第${delivery.end}集，共${delivery.count}集；已有正文不会重写。`
                  : "请上传带有“第N集”标题的已有剧本，或手动填写当前最后一集；目标集数必须更大。"}</small>
              </div>
            </div>
          ` : ""}
          </div>
          <div class="nwt-form-band nwt-form-band-material">
            <div class="nwt-form-band-head">
              <span>04</span>
              <div><strong>${state.form.mode === "续写" ? "已有剧本与续写方向" : "故事材料"}</strong><small>${state.form.mode === "续写" ? "已有正文作为正典，只创作新的集数" : "提供原始内容与本次创作必须遵守的方向"}</small></div>
            </div>
          <div class="nwt-form-grid nwt-material-grid">
            <label class="nwt-field wide">
              <span>${state.form.mode === "续写" ? "已有完整剧本" : "原始材料或创作要求"}</span>
              <textarea data-form-key="source_text" placeholder="${state.form.mode === "续写" ? "粘贴或上传已有剧本，系统会自动识别当前最后一集。" : "粘贴原文，或写清主角、目标、阻力、结局和必须保留的信息。"}" ${active ? "disabled" : ""}>${escapeHtml(state.form.source_text)}</textarea>
              <div class="nwt-upload-row">
                <label class="nwt-upload-button">
                  ${icon("paperclip", 14)}<span>上传材料</span>
                  <input type="file" data-upload-target="source_text" accept=".docx,.pdf,.txt,.md,.json" multiple ${active ? "disabled" : ""} />
                </label>
                <small>支持 Word、PDF、TXT、Markdown、JSON，可多选；单文件最大20MB</small>
              </div>
            </label>
            ${state.form.mode === "续写" ? `
              <label class="nwt-field wide nwt-continuation-bible">
                <span class="nwt-lock-label">${icon("lock-keyhole", 14)}续写创作圣经（锁定项）</span>
                <textarea data-form-key="continuation_bible" placeholder="填写或上传必须延续的人设、世界观、人物关系、主线与支线规划、未来剧情节点、语言风格和你喜欢的剧情方向。已有正文事实优先，不会反向改写旧集。" ${active ? "disabled" : ""}>${escapeHtml(state.form.continuation_bible)}</textarea>
                <div class="nwt-upload-row">
                  <label class="nwt-upload-button">
                    ${icon("file-lock-2", 14)}<span>上传故事大纲 / 人设文件</span>
                    <input type="file" data-upload-target="continuation_bible" accept=".docx,.pdf,.txt,.md,.json" multiple ${active ? "disabled" : ""} />
                  </label>
                  <small>作为后续集数的长期正典约束，可多文件追加；支持 Word、PDF、TXT、Markdown、JSON</small>
                </div>
              </label>
            ` : ""}
            <label class="nwt-field wide">
              <span>${state.form.mode === "续写" ? "续写方向" : "补充方向"}</span>
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
          </div>
          <div class="nwt-runbar">
            <div>
              <strong data-live-status-text>${escapeHtml(job.status_text || "尚未提交任务")}</strong>
              <small data-delivery-range>${job.job_id ? `任务 ${escapeHtml(job.job_id)}` : continuationReady ? `本次交付第${delivery.start}集至第${delivery.end}集，共${episodes}集` : "请先确认续写范围"}</small>
            </div>
            <div class="nwt-run-actions">
              ${canRecover ? '<button class="nwt-btn" type="button" data-action="recover">恢复中断产物</button>' : ""}
              ${active ? `<button class="nwt-btn danger" type="button" data-action="cancel">${icon("square", 15)}<span>停止任务</span></button>` : ""}
              ${canLocalFallback ? '<button class="nwt-btn danger" type="button" data-action="fallback">本地兜底</button>' : ""}
              <button class="nwt-btn primary" type="button" data-action="start" ${state.loading || active || !(state.configStatus || {}).ready || !continuationReady ? "disabled" : ""}>
                ${state.loading ? `${icon("loader-circle", 16)}<span>正在提交</span>` : active ? `${icon("activity", 16)}<span>团队创作中</span>` : finalScript ? `${icon("refresh-cw", 16)}<span>重新生成</span>` : `${icon("sparkles", 16)}<span>开始创作</span>`}
              </button>
            </div>
          </div>
        </section>
        </div>

        <div class="nwt-view-panel nwt-team-view ${activeView === "team" ? "active" : ""}">
        ${state.error ? `<div class="nwt-error">${escapeHtml(state.error)}</div>` : ""}
        ${job.poll_warning ? `<div class="nwt-warning">${escapeHtml(job.poll_warning)}</div>` : ""}
        ${job.fallback_reason ? `<div class="nwt-warning">远程 CNB 节点失败，已保留断点：${escapeHtml(job.fallback_reason)}</div>` : ""}
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
        ${recoveredFiles.length ? renderRecoveredNotice(recoveredFiles) : ""}

        <section class="nwt-team-section">
          <div class="nwt-section-head">
            <div class="nwt-section-title">
              <span class="nwt-section-icon">${icon("users", 18)}</span>
              <div>
              <h2>剧本团队</h2>
              <p>节点、运行状态和中间产物集中在同一条创作链路中。</p>
              </div>
            </div>
            ${(job.selected_skill || (job.request || {}).distilled_skill || {}).name ? `
              <div class="nwt-runtime-skill" title="本任务已冻结该 Skill 发布版本">
                ${icon("badge-check", 15)}
                <span><small>已关联 Skill</small><strong>${escapeHtml((job.selected_skill || job.request.distilled_skill).name)} · ${escapeHtml((job.selected_skill || job.request.distilled_skill).version || "")}</strong></span>
              </div>` : ""}
            ${renderBuildLink()}
          </div>
          ${renderTeamFlow()}
          <div class="nwt-team">${renderTeam()}</div>
        </section>
        </div>

        <section class="nwt-final nwt-view-panel nwt-delivery-view ${activeView === "delivery" ? "active" : ""}">
          <div class="nwt-final-head">
            <div>
              <h2>最终完整剧本</h2>
              <p>${finalScript ? (gateErrors.length ? "终审稿已恢复，可下载；门禁待修项保留在上方" : "已完成终审并通过严格门禁") : "NPC团队完成后，正文会直接显示在这里"}</p>
            </div>
            <div class="nwt-actions">
              <button class="nwt-btn" type="button" data-action="continue-script" ${finalScript ? "" : "disabled"}>${icon("forward", 15)}<span>续写本剧</span></button>
              <button class="nwt-btn" type="button" data-action="download-word" ${finalScript ? "" : "disabled"}>${icon("file-down", 15)}<span>Word</span></button>
              <button class="nwt-btn" type="button" data-action="download" ${finalScript ? "" : "disabled"}>${icon("download", 15)}<span>TXT</span></button>
            </div>
          </div>
          <div class="nwt-output">${deliveryScript ? escapeHtml(deliveryScript) : '<span class="nwt-empty">等待团队交付...</span>'}</div>
        </section>
        </main>
        <aside class="nwt-inspector">
          ${renderLiveMonitor(job)}
          <div class="nwt-inspector-note">
            <span>${icon("shield-check", 16)}</span>
            <div><strong>自动保存已开启</strong><small>每个节点完成后立即落盘，可从任务中心继续。</small></div>
          </div>
        </aside>
        </div>
        ${renderEditorWorkspace()}
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

  async function loadSkillCatalog() {
    state.skillCatalogLoading = true;
    render();
    try {
      const data = await request("/api/new-workflow-test/skills");
      state.skillCatalog = Array.isArray(data.skills) ? data.skills : [];
      const selected = state.skillCatalog.find((item) => item.skill_id === state.form.distilled_skill_id);
      if (state.form.distilled_skill_id && !selected) {
        state.form.distilled_skill_id = "";
        state.form.distilled_skill_version_id = "";
      }
    } catch (error) {
      state.error = `读取蒸馏 Skill 失败：${error.message || error}`;
    } finally {
      state.skillCatalogLoading = false;
      saveState();
      render();
    }
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
        expandProjectForJob(state.job);
        if (latest.request && typeof latest.request === "object") {
          const selectedSkill = latest.request.distilled_skill || latest.selected_skill || {};
          state.form = {
            ...state.form,
            ...latest.request,
            continuation_bible: String(latest.request.continuation_bible || ""),
            distilled_skill_id: String(selectedSkill.skill_id || ""),
            distilled_skill_version_id: String(selectedSkill.version_id || ""),
          };
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
    const previousSignature = historyRenderSignature(state.history);
    try {
      const data = await request("/api/new-workflow-test/npc/jobs");
      state.history = Array.isArray(data.jobs) ? data.jobs : [];
    } catch (error) {
      state.error = `读取历史记录失败：${error.message || error}`;
    }
    if (silent) {
      if (previousSignature !== historyRenderSignature(state.history)) {
        const current = app.querySelector(".nwt-task-center");
        if (current) current.outerHTML = renderTaskCenter();
        window.queueMicrotask(() => window.lucide && window.lucide.createIcons());
      }
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
      expandProjectForJob(state.job);
      state.activeView = state.job && state.job.final_script ? "delivery" : "team";
      if (state.job && state.job.request) {
        state.form = {
          ...state.form,
          ...state.job.request,
          continuation_bible: String(state.job.request.continuation_bible || ""),
        };
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
    state.activeView = "team";
    render();
    try {
      const data = await request("/api/new-workflow-test/npc/jobs", state.form);
      state.job = data.job || null;
      expandProjectForJob(state.job);
      if (state.job && state.job.request && typeof state.job.request === "object") {
        const selectedSkill = state.job.request.distilled_skill || state.job.selected_skill || {};
        state.form = {
          ...state.form,
          ...state.job.request,
          distilled_skill_id: String(selectedSkill.skill_id || state.form.distilled_skill_id || ""),
          distilled_skill_version_id: String(selectedSkill.version_id || state.form.distilled_skill_version_id || ""),
        };
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

  function continueCurrentScript() {
    const script = String((state.job || {}).final_script || "").trim();
    if (!script) return;
    const lastEpisode = detectLastEpisode(script);
    state.form = {
      ...state.form,
      mode: "续写",
      source_text: script,
      source_last_episode: lastEpisode,
      continuation_target_episode: Math.max(2, lastEpisode + 5),
      continuation_bible: String((((state.job || {}).request || {}).continuation_bible) || ""),
      adaptation_direction: "",
    };
    state.job = null;
    state.error = "";
    state.selectedArtifact = "";
    state.activeView = "brief";
    saveState();
    render();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function pollJob() {
    if (!state.job || !state.job.job_id || !isActive()) return;
    const previousSignature = renderSignature(state.job);
    try {
      const data = await request(`/api/new-workflow-test/npc/jobs/${encodeURIComponent(state.job.job_id)}`);
      state.job = data.job || state.job;
      state.error = state.job.status === "failed" ? (state.job.error || "NPC团队执行失败。") : "";
      saveState();
      if (previousSignature !== renderSignature(state.job)) {
        render();
      } else {
        patchLiveTelemetry(state.job);
      }
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
      if (targetKey === "source_text" && state.form.mode === "续写") {
        const detected = detectLastEpisode(state.form.source_text);
        if (detected && Number(state.form.continuation_target_episode) <= detected) {
          state.form.continuation_target_episode = detected + 5;
        }
      }
      saveState();
    } catch (error) {
      state.error = `上传失败：${error.message || error}`;
    } finally {
      state.loading = false;
      render();
    }
  }

  async function runStage(stage, options = {}) {
    if (!state.job || !state.job.job_id) return;
    const feedback = String(options.feedback || "");
    const continueAfter = Boolean(options.continueAfter);
    state.loading = true;
    state.error = "";
    render();
    try {
      const data = await request(
        `/api/new-workflow-test/npc/jobs/${encodeURIComponent(state.job.job_id)}/stages/${encodeURIComponent(stage)}/run`,
        { feedback, continue_after: continueAfter, local_fallback: Boolean(options.localFallback) },
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

  function openEditor(stageId, artifactKey) {
    const content = artifactContent(artifactKey);
    if (!content.trim()) return;
    state.editor = {
      open: true,
      artifactKey,
      stageId,
      mode: "manual",
      sectionId: "full",
      content,
      dirty: false,
      notice: "",
      feedback: "",
      continueAfter: false,
    };
    render();
  }

  function syncEditorBuffer() {
    const editor = state.editor || {};
    if (!editor.open) return;
    const textarea = app.querySelector("[data-editor-section-text]");
    if (!textarea) return;
    const selected = currentEditorSection();
    const replacement = String(textarea.value || "");
    const current = String(editor.content || "");
    const previous = current.slice(selected.start, selected.end);
    if (replacement === previous) return;
    editor.content = selected.id === "full"
      ? replacement
      : `${current.slice(0, selected.start)}${replacement}${current.slice(selected.end)}`;
    editor.dirty = true;
    editor.notice = "";
  }

  function closeEditor() {
    if (state.editor && state.editor.dirty && !window.confirm("当前修改还没有保存，确定关闭吗？")) return;
    state.editor = clone(initialState.editor);
    render();
  }

  function selectEditorSection(sectionId) {
    syncEditorBuffer();
    const sections = artifactSections((state.editor || {}).content);
    state.editor.sectionId = sections.some((item) => item.id === sectionId) ? sectionId : "full";
    render();
  }

  async function saveEditor() {
    if (!state.job || !state.job.job_id || !(state.editor || {}).artifactKey) return;
    syncEditorBuffer();
    const key = state.editor.artifactKey;
    const content = String(state.editor.content || "");
    state.loading = true;
    state.editor.notice = "";
    render();
    try {
      const data = await request(
        `/api/new-workflow-test/npc/jobs/${encodeURIComponent(state.job.job_id)}/artifacts/${encodeURIComponent(key)}`,
        { content },
        "PUT",
      );
      state.job = data.job || state.job;
      state.editor.content = content;
      state.editor.dirty = false;
      state.editor.notice = "修改已保存，依赖该内容的后续节点已标记为待重新生成。";
      saveState();
      loadHistory(true);
    } catch (error) {
      state.error = `保存修改失败：${error.message || error}`;
    } finally {
      state.loading = false;
      render();
    }
  }

  function rewriteEditor() {
    const editor = state.editor || {};
    if (!editor.open || !editor.stageId) return;
    const feedbackInput = document.getElementById("nwt-editor-feedback");
    const feedback = String((feedbackInput || {}).value || editor.feedback || "").trim();
    if (!feedback) {
      state.editor.notice = "请先写明希望编剧如何修改。";
      render();
      return;
    }
    const selected = currentEditorSection();
    const scopedFeedback = selected.id === "full"
      ? feedback
      : `${feedback}\n\n本次只修改“${selected.title}”，其余内容保持原有事实、顺序和结构。`;
    const continueAfter = Boolean((document.getElementById("nwt-editor-continue") || {}).checked || editor.continueAfter);
    const stageId = editor.stageId;
    state.editor = clone(initialState.editor);
    runStage(stageId, { feedback: scopedFeedback, continueAfter });
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
    if (!window.confirm("确认停止当前任务吗？云端或本地执行都会终止，并且不会自动重试；已保存的断点会保留。")) return;
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
    if (event.target.id === "nwt-editor-continue") {
      state.editor.continueAfter = Boolean(event.target.checked);
      return;
    }
    if (event.target.matches("[data-upload-target]")) {
      uploadFiles(event.target.files, String(event.target.dataset.uploadTarget || ""));
      return;
    }
    if (!event.target.matches("[data-form-key]")) return;
    syncForm();
    saveState();
    if (
      state.form.mode === "续写"
      && ["source_text", "source_last_episode", "continuation_target_episode"].includes(
        String(event.target.dataset.formKey || ""),
      )
    ) {
      render();
    }
  });

  app.addEventListener("input", (event) => {
    if (event.target.matches("[data-form-key]")) {
      syncForm();
      if (
        ["episodes", "source_last_episode", "continuation_target_episode", "episode_duration_seconds"].includes(
          String(event.target.dataset.formKey || ""),
        )
      ) {
        updateDurationPreview();
        updateContinuationPreview();
      }
      saveState();
    }
    if (event.target.matches("[data-editor-section-text]")) {
      state.editor.dirty = true;
      state.editor.notice = "";
      const status = app.querySelector(".nwt-editor-footer > span");
      if (status) status.textContent = "有尚未保存的修改";
    }
    if (event.target.id === "nwt-editor-feedback") {
      state.editor.feedback = String(event.target.value || "");
      state.editor.notice = "";
    }
  });

  app.addEventListener("click", (event) => {
    const skillCard = event.target.closest("[data-skill-id]");
    if (skillCard) {
      if (skillCard.disabled || isActive()) return;
      state.form.distilled_skill_id = String(skillCard.dataset.skillId || "");
      state.form.distilled_skill_version_id = String(skillCard.dataset.skillVersionId || "");
      state.skillPickerOpen = false;
      saveState();
      render();
      return;
    }
    const choice = event.target.closest("[data-choice-key]");
    if (choice) {
      if (choice.disabled) return;
      const key = String(choice.dataset.choiceKey || "");
      const value = String(choice.dataset.choiceValue || "");
      if (!key || state.form[key] === value) return;
      state.form[key] = value;
      if (key === "mode" && value === "续写") {
        const lastEpisode = continuationLastEpisode();
        if (lastEpisode && Number(state.form.continuation_target_episode) <= lastEpisode) {
          state.form.continuation_target_episode = lastEpisode + 5;
        }
      }
      saveState();
      render();
      return;
    }
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const action = button.dataset.action;
    if (action === "toggle-skill-picker") {
      state.skillPickerOpen = !state.skillPickerOpen;
      render();
      return;
    }
    if (action === "start") startJob();
    if (action === "recover") recoverJob();
    if (action === "cancel") cancelRun();
    if (action === "run-stage") runStage(String(button.dataset.stage || ""));
    if (action === "fallback") runStage(fallbackStage(), { localFallback: true });
    if (action === "open-editor") {
      openEditor(String(button.dataset.stage || ""), String(button.dataset.artifact || ""));
    }
    if (action === "editor-backdrop" && event.target === button) closeEditor();
    if (action === "close-editor") closeEditor();
    if (action === "select-editor-section") selectEditorSection(String(button.dataset.sectionId || "full"));
    if (action === "editor-mode") {
      if ((state.editor || {}).mode === "manual") syncEditorBuffer();
      state.editor.mode = String(button.dataset.mode || "manual");
      state.editor.notice = "";
      render();
    }
    if (action === "append-feedback") {
      const addition = String(button.dataset.feedback || "");
      const current = String((state.editor || {}).feedback || "").trim();
      state.editor.feedback = current ? `${current}；${addition}` : addition;
      render();
      const feedback = document.getElementById("nwt-editor-feedback");
      if (feedback) feedback.focus();
    }
    if (action === "save-editor") saveEditor();
    if (action === "rewrite-editor") rewriteEditor();
    if (action === "refresh-history") loadHistory();
    if (action === "task-filter") {
      state.taskFilter = ["all", "running", "delivered", "attention"].includes(button.dataset.taskFilter)
        ? button.dataset.taskFilter
        : "all";
      saveState();
      render();
    }
    if (action === "toggle-project") toggleProjectGroup(String(button.dataset.projectKey || ""));
    if (action === "open-history") openHistory(String(button.dataset.jobId || ""));
    if (action === "delete-history") deleteHistory(String(button.dataset.jobId || ""));
    if (action === "download-artifact") {
      const key = String(button.dataset.artifact || "");
      const files = (state.job || {}).recovered_files || {};
      const extension = key === "story_state" ? "json" : (key === "draft" ? "txt" : "md");
      downloadText(
        key === "final_script" ? String((state.job || {}).final_script || "") : String(files[key] || ""),
        `${state.form.project_title || "NPC剧本团队"}-${ARTIFACT_LABELS[key] || key}.${extension}`,
      );
    }
    if (action === "new-job") {
      window.localStorage.removeItem(STORAGE_KEY);
      const history = Array.isArray(state.history) ? state.history : [];
      const configStatus = state.configStatus;
      const skillCatalog = Array.isArray(state.skillCatalog) ? state.skillCatalog : [];
      state = clone(initialState);
      state.history = history;
      state.configStatus = configStatus;
      state.skillCatalog = skillCatalog;
      state.job = null;
      state.selectedArtifact = "";
      state.error = "";
      saveState();
      render();
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
    if (action === "switch-view") {
      const view = String(button.dataset.view || "");
      if (["brief", "team", "delivery"].includes(view)) {
        state.activeView = view;
        saveState();
        render();
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    }
    if (action === "download") {
      const text = String((state.job || {}).delivery_script || (state.job || {}).final_script || "");
      downloadText(text, `${state.form.project_title || "NPC剧本团队成品"}.txt`);
    }
    if (action === "download-word" && state.job && state.job.job_id) {
      window.location.href = apiUrl(
        `/api/new-workflow-test/npc/jobs/${encodeURIComponent(state.job.job_id)}/export/docx`,
      );
    }
    if (action === "continue-script") continueCurrentScript();
  });

  window.addEventListener("storage", (event) => {
    if (event.key === "distilledSkillCatalogChanged") loadSkillCatalog();
  });

  render();
  loadConfig();
  loadSkillCatalog();
  loadLatestJob();
  loadHistory();
})();
