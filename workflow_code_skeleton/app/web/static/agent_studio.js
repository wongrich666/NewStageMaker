(function () {
  const config = window.agentStudioConfig || {};
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const state = {
    conversations: [],
    currentConversationId: "",
    messages: [],
    context: {},
    sending: false,
    pollTimer: null,
    doctorSkills: [],
    selectedSkill: "",
    knowledgeTags: [],
    selectedKnowledgeTagIds: [],
    knowledgePreferences: {},
    knowledgeSaving: false,
    knowledgeView: "main",
    knowledgeActiveTagId: "",
    knowledgeFilmPage: 1,
    taskPanelOpen: null,
    taskPanelProjectId: "",
    selectedAttachment: null,
    uploadingAttachment: false,
  };

  const PIPELINE_STAGES = [
    ["01", "原文信息提取"],
    ["02", "世界观方案"],
    ["03", "人物设定"],
    ["04", "三幕十五节拍"],
    ["05", "人物故事线"],
    ["06", "整体改编指引"],
    ["07", "框架策划包校验"],
    ["08", "提炼核心场景"],
    ["09", "确定角色外观"],
    ["10", "优化分集计划"],
    ["11", "规划因果冲突"],
    ["12", "生成剧本正文"],
  ];

  function authHeaders() {
    return config.authToken ? { Authorization: `Bearer ${config.authToken}` } : {};
  }

  function withAuth(url) {
    if (!url || !config.authToken) return url || "#";
    const parsed = new URL(url, window.location.origin);
    if (!parsed.searchParams.has("auth_token")) parsed.searchParams.set("auth_token", config.authToken);
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function userFacingText(value) {
    return String(value || "")
      .replaceAll("01-12 人工模式流程已完成", "剧本创作流程完成")
      .replaceAll("人工模式 01-12 流程已完成", "剧本创作流程完成")
      .replaceAll("01-12 已完成", "剧本创作流程完成");
  }

  function formatMessageContent(value) {
    const safe = escapeHtml(value)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
    return safe.split(/\r?\n/).map((line) => {
      const heading = line.match(/^(#{1,3})\s+(.+)$/);
      if (heading) return `<div class="agent-copy-heading level-${heading[1].length}">${heading[2]}</div>`;
      if (/^\s*---+\s*$/.test(line)) return '<div class="agent-copy-divider"></div>';
      if (/^\s*&gt;\s?/.test(line)) return `<div class="agent-copy-quote">${line.replace(/^\s*&gt;\s?/, "")}</div>`;
      if (/^\s*[-*]\s+/.test(line)) return `<div class="agent-copy-list-item">${line.replace(/^\s*[-*]\s+/, "")}</div>`;
      if (/^\s*\|.*\|\s*$/.test(line)) return `<div class="agent-copy-table-row">${line.replace(/^\s*\|\s?|\s*\|\s*$/g, "")}</div>`;
      return `<div class="agent-copy-line">${line || "&nbsp;"}</div>`;
    }).join("");
  }

  async function fetchJson(url, options = {}) {
    const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
    const response = await fetch(url, {
      ...options,
      headers: {
        ...(options.body && !isFormData ? { "Content-Type": "application/json" } : {}),
        ...authHeaders(),
        ...(options.headers || {}),
      },
    });
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { message: text }; }
    if (!response.ok) throw new Error(data.message || data.error || `请求失败：HTTP ${response.status}`);
    return data;
  }

  function formatTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  function formatConversationTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "刚刚更新";
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const dayDiff = Math.round((today.getTime() - target.getTime()) / 86400000);
    const clock = date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
    if (dayDiff === 0) return `今天 ${clock}`;
    if (dayDiff === 1) return `昨天 ${clock}`;
    return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" }).replaceAll("/", ".");
  }

  function conversationStatus(item) {
    const conversationState = item && item.state && typeof item.state === "object" ? item.state : {};
    const phase = String(conversationState.pipeline_phase || "").toLowerCase();
    const stage = String(conversationState.pipeline_stage || "").padStart(2, "0");
    if (phase === "completed") return { label: "已完成", className: "is-done" };
    if (phase === "failed") return { label: "需处理", className: "is-error" };
    if (phase && !["terminated", "cancelled"].includes(phase)) return { label: stage && stage !== "00" ? `${stage} 阶段` : "创作中", className: "is-running" };
    if (item && item.project_id) return { label: "已关联", className: "is-linked" };
    return { label: "对话", className: "" };
  }

  function renderConversations() {
    const list = $("#conversationList");
    $("#conversationCount").textContent = String(state.conversations.length);
    if (!state.conversations.length) {
      list.innerHTML = '<div class="agent-side-empty"><strong>还没有创作对话</strong><span>点击上方按钮开始新的剧本创作</span></div>';
      return;
    }
    list.innerHTML = state.conversations.map((item) => {
      const status = conversationStatus(item);
      const title = item.title || "新的创作对话";
      return `
      <div class="agent-conversation-item ${item.id === state.currentConversationId ? "is-active" : ""}" data-conversation-id="${escapeHtml(item.id)}" data-conversation-title="${escapeHtml(title)}" role="button" tabindex="0" aria-current="${item.id === state.currentConversationId ? "true" : "false"}" title="${escapeHtml(title)}">
        <span class="agent-conversation-indicator ${status.className}"></span>
        <div class="agent-conversation-copy">
          <strong>${escapeHtml(title)}</strong>
          <small><span class="agent-conversation-status ${status.className}">${escapeHtml(status.label)}</span><time>${escapeHtml(formatConversationTime(item.updated_at))}</time></small>
        </div>
        <button class="agent-conversation-delete" type="button" data-delete-conversation="${escapeHtml(item.id)}" aria-label="删除《${escapeHtml(title)}》会话" title="删除会话">删除</button>
      </div>
    `;
    }).join("");
  }

  function eventCard(event) {
    const result = event && event.result && typeof event.result === "object" ? event.result : {};
    const ui = result.ui && typeof result.ui === "object" ? result.ui : {};
    if (ui.kind === "confirmation") {
      const summary = result.summary || {};
      const knowledgeNames = Array.isArray(summary.selected_preference_tags)
        ? summary.selected_preference_tags.map((item) => item && (item.name || item.id)).filter(Boolean)
        : [];
      return `
        <section class="agent-event-card is-confirmation">
          <h4>生成方案已准备</h4>
          <p>确认后将调用现有剧本平台创建后台任务，生成过程中可以继续对话查询或暂停。</p>
          <div class="agent-event-tags">
            <span>${escapeHtml(summary.title || "未命名剧本")}</span>
            <span>${escapeHtml(summary.total_episodes || 0)} 集</span>
            <span>${escapeHtml(summary.character_count || 0)} 个主要角色</span>
            <span>每集 ${escapeHtml(summary.episode_word_count || 600)} 字</span>
            ${knowledgeNames.length ? `<span>智慧库：${escapeHtml(knowledgeNames.join("、"))}</span>` : ""}
          </div>
          <div class="agent-event-actions">
            <button class="is-primary" type="button" data-agent-prompt="确认开始执行这个剧本生成任务">确认开始</button>
            <button type="button" data-agent-prompt="取消本次待执行的生成任务">取消</button>
          </div>
        </section>`;
    }
    if (["task_started", "progress", "project"].includes(ui.kind) && result.project) {
      const project = result.project;
      const progress = Math.max(0, Math.min(100, Number(project.progress_percent || 0)));
      return `
        <section class="agent-event-card">
          <h4>${escapeHtml(project.title || "剧本项目")}</h4>
          <p>${escapeHtml(userFacingText(project.message || project.current_stage_label || project.status || "已关联项目"))}</p>
          <div class="agent-mini-progress"><i style="width:${progress}%"></i></div>
          <div class="agent-event-tags">
            <span>${escapeHtml(userFacingText(project.current_stage_label || project.current_stage || "等待"))}</span>
            <span>${progress}%</span>
            ${project.total_episodes ? `<span>${escapeHtml(project.generated_episodes || 0)}/${escapeHtml(project.total_episodes)} 集</span>` : ""}
          </div>
          <div class="agent-event-actions"><a href="${escapeHtml(withAuth(`/workspace?project_id=${project.project_id || ""}`))}">进入原工作台</a></div>
        </section>`;
    }
    if (ui.kind === "download" && result.download_url) {
      return `
        <section class="agent-event-card">
          <h4>成品已经准备好</h4>
          <p>${escapeHtml(result.filename || "剧本成品")}</p>
          <div class="agent-event-actions"><a class="is-primary" href="${escapeHtml(withAuth(result.download_url))}">下载成品</a></div>
        </section>`;
    }
    if (ui.kind === "navigation" && result.url) {
      return `
        <section class="agent-event-card">
          <h4>原平台功能已保留</h4>
          <p>可以进入对应精细工作台继续人工调整。</p>
          <div class="agent-event-actions"><a href="${escapeHtml(withAuth(result.url))}">打开工作台</a></div>
        </section>`;
    }
    if (ui.kind === "doctor_report") {
      return `
        <section class="agent-event-card">
          <h4>${escapeHtml(result.skill || "剧本医生")}已完成</h4>
          <p>${escapeHtml(result.diagnosis || "报告已保存到AI剧本医生历史记录。")}</p>
          <div class="agent-event-tags">
            ${result.score != null ? `<span>评分 ${escapeHtml(result.score)}</span>` : ""}
            ${result.risk_level ? `<span>风险 ${escapeHtml(result.risk_level)}</span>` : ""}
          </div>
          <div class="agent-event-actions">
            <a href="${escapeHtml(withAuth(ui.url || "/workbuddy-studio"))}">查看完整报告</a>
            ${result.can_optimize && result.history_entry_id
              ? `<button class="is-primary" type="button" data-optimize-history-id="${escapeHtml(result.history_entry_id)}">一键优化并下载 Word</button>`
              : ""}
          </div>
        </section>`;
    }
    if (result.ok === false && result.error) {
      return `<section class="agent-event-card"><h4>操作未完成</h4><p>${escapeHtml(result.error)}</p></section>`;
    }
    return "";
  }

  function renderMessages({ scrollToBottom = true } = {}) {
    const list = $("#messageList");
    const viewport = $("#chatViewport");
    const previousScrollTop = viewport.scrollTop;
    const wasNearBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 120;
    const visible = state.messages.filter((item) => item.role === "user" || item.role === "assistant");
    $("#agentHero").hidden = visible.length > 1;
    list.innerHTML = visible.map((item) => {
      const isUser = item.role === "user";
      const metadata = item.metadata && typeof item.metadata === "object" ? item.metadata : {};
      const events = Array.isArray(metadata.events) ? metadata.events : [];
      const skillChip = metadata.selected_skill_name
        ? `<div class="agent-message-skill"><span>SKILL</span>${escapeHtml(metadata.selected_skill_name)}</div>`
        : "";
      const fileChip = metadata.attachment_name
        ? `<div class="agent-message-file"><span>FILE</span>${escapeHtml(metadata.attachment_name)}</div>`
        : "";
      const knowledgeNames = Array.isArray(metadata.selected_knowledge_tag_names) ? metadata.selected_knowledge_tag_names : [];
      const knowledgeChip = knowledgeNames.length
        ? `<div class="agent-message-knowledge"><span>智慧库</span>${escapeHtml(knowledgeNames.join("、"))}</div>`
        : "";
      return `
        <article class="agent-message ${isUser ? "is-user" : "is-assistant"}">
          <div class="agent-message-avatar">${isUser ? escapeHtml((config.username || "我").slice(0, 1)) : "AI"}</div>
          <div class="agent-message-body">
            ${fileChip}${skillChip}${knowledgeChip}
            <div class="agent-message-copy">${formatMessageContent(userFacingText(item.content || ""))}</div>
            ${events.length ? `<div class="agent-event-stack">${events.map(eventCard).join("")}</div>` : ""}
            <div class="agent-message-meta">${escapeHtml(formatTime(item.created_at))}</div>
          </div>
        </article>`;
    }).join("");
    requestAnimationFrame(() => {
      if (scrollToBottom || wasNearBottom) viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
      else viewport.scrollTop = previousScrollTop;
    });
  }

  function pipelineStageIndex(project) {
    const explicit = Number(project && project.pipeline_stage);
    const current = String(project && project.current_stage || "");
    if (explicit >= 1 && explicit <= 12) return explicit;
    const frameworkMap = { basic: 1, worldview: 2, character: 3, beat: 4, storylines: 5, guide: 6, package: 7 };
    if (frameworkMap[current]) return frameworkMap[current];
    if (current.includes("scene_dictionary")) return 8;
    if (current.includes("appearanceMapping")) return 9;
    if (current.includes("enriched_episode_plan")) return 10;
    if (current.includes("causal_conflict")) return 11;
    if (current.includes("framework_script") || ["final", "finalize", "finished"].includes(current)) return 12;
    return 0;
  }

  function isPipelineProject(project) {
    return Boolean(project && project.generation_chain === "agent_framework_01_12");
  }

  function isPipelineActive(project) {
    if (!isPipelineProject(project)) return false;
    const phase = String(project.pipeline_phase || "").toLowerCase();
    return !["completed", "failed", "terminated"].includes(phase);
  }

  function stageWorkspaceUrl(stageNumber, projectId) {
    const stage = String(stageNumber).padStart(2, "0");
    if (Number(stage) <= 7) {
      return withAuth(`/framework-planner?project_id=${encodeURIComponent(projectId)}&stage=${stage}`);
    }
    return withAuth(`/framework-to-script?framework_asset_id=${encodeURIComponent(projectId)}&project_id=${encodeURIComponent(projectId)}&stage=${stage}`);
  }

  function pipelineProgress(project) {
    const stage = pipelineStageIndex(project);
    if (!stage) return Math.max(0, Math.min(100, Number(project && project.progress_percent || 0)));
    if (stage <= 7) return Math.round((stage / 12) * 100);
    const nativeProgress = Math.max(0, Math.min(100, Number(project.progress_percent || 0)));
    const stageBase = Math.round(((stage - 1) / 12) * 100);
    const stageEnd = Math.round((stage / 12) * 100);
    return Math.min(stageEnd, Math.max(stageBase, Math.round(stageBase + ((stageEnd - stageBase) * nativeProgress / 100))));
  }

  function renderLiveExecution() {
    const container = $("#agentLiveExecution");
    if (!container) return;
    const project = state.context && state.context.current_project ? state.context.current_project : null;
    const status = String(project && project.status || "").toLowerCase();
    const active = project && ["pending", "running", "in_progress", "pausing", "paused", "retrying"].includes(status);
    if (!active && !state.sending) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }
    const stage = pipelineStageIndex(project);
    const progress = project ? pipelineProgress(project) : 2;
    const title = project
      ? (project.pipeline_message || project.message || project.current_stage_label || "正在执行剧本生成流程")
      : "正在理解需求并准备执行";
    const subtitle = project
      ? `${project.title || "剧本项目"} · 01-07 框架策划 → 08-12 框架转剧本`
      : "正在连接剧本创作平台";
    const chips = Array.from({ length: 12 }, (_, index) => {
      const number = index + 1;
      const className = number < stage ? "is-done" : number === stage ? "is-active" : "";
      return `<span class="${className}">${String(number).padStart(2, "0")}</span>`;
    }).join("");
    container.hidden = false;
    container.innerHTML = `
      <div class="agent-live-icon" aria-hidden="true"><i></i></div>
      <div class="agent-live-main">
        <strong>${escapeHtml(title)}</strong>
        <p>${escapeHtml(subtitle)}</p>
        <div class="agent-live-track"><i style="width:${progress}%"></i></div>
        <div class="agent-live-stages">${chips}</div>
      </div>
      <b>${progress}%</b>
    `;
  }

  function renderTaskRail(project) {
    const rail = $("#agentTaskRail");
    const idle = $("#agentTaskIdle");
    const waitingActions = $("#agentWaitingActions");
    if (!rail || !idle || !waitingActions) return;
    const visible = isPipelineProject(project);
    rail.hidden = !visible;
    idle.hidden = visible;
    waitingActions.hidden = !visible;
    if (!visible) return;

    const stage = pipelineStageIndex(project);
    const phase = String(project.pipeline_phase || "").toLowerCase();
    const completed = phase === "completed" || (stage === 12 && String(project.status || "").toLowerCase() === "completed");
    const failed = phase === "failed" || String(project.status || "").toLowerCase() === "failed";
    const projectId = project.project_id || project.framework_project_id || "";
    $("#taskStageList").innerHTML = PIPELINE_STAGES.map(([number, name]) => {
      const numeric = Number(number);
      const done = completed ? numeric <= 12 : numeric < stage;
      const active = !completed && numeric === stage;
      const stateText = done ? "已完成" : active ? (failed ? "失败" : "执行中") : "等待";
      const className = done ? "is-done" : active ? (failed ? "is-active is-failed" : "is-active") : "";
      const inner = `
        <span class="agent-stage-number">${number}</span>
        <span class="agent-stage-name">${escapeHtml(name)}</span>
        <span class="agent-stage-state">${stateText}</span>`;
      const canOpen = Boolean(projectId && (done || active || completed));
      return `<li class="agent-stage-item ${className}">${canOpen
        ? `<a class="agent-stage-link" href="${escapeHtml(stageWorkspaceUrl(number, projectId))}" title="在人工模式打开 ${number} ${escapeHtml(name)}">${inner}</a>`
        : `<div class="agent-stage-static">${inner}</div>`}</li>`;
    }).join("");
  }

  function syncTaskPanelVisibility(project) {
    const shell = $(".agent-shell");
    const toggle = $("#taskPanelToggle");
    if (!shell || !toggle) return;
    const projectId = String(project && (project.project_id || project.framework_project_id) || "");
    const active = isPipelineActive(project);
    if (active && projectId && state.taskPanelProjectId !== projectId) {
      state.taskPanelProjectId = projectId;
      state.taskPanelOpen = true;
    }
    const open = state.taskPanelOpen === null ? active : state.taskPanelOpen;
    shell.classList.toggle("is-task-panel-collapsed", !open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "收起任务" : "任务";
  }

  function renderContext() {
    const project = state.context && state.context.current_project ? state.context.current_project : null;
    syncTaskPanelVisibility(project);
    if (!project) {
      $("#contextProjectTitle").textContent = "尚未选择项目";
      $("#contextProjectMeta").textContent = "通过对话创建或选择项目";
      $("#contextStage").textContent = "等待指令";
      $("#contextProgress").textContent = "0%";
      $("#contextProgressBar").style.width = "0%";
      renderTaskRail(null);
      return;
    }
    const progress = project.generation_chain === "agent_framework_01_12"
      ? pipelineProgress(project)
      : Math.max(0, Math.min(100, Number(project.progress_percent || 0)));
    $("#contextProjectTitle").textContent = project.title || "未命名项目";
    $("#contextProjectMeta").textContent = project.message || `项目 #${project.project_id}`;
    $("#contextStage").textContent = userFacingText(project.pipeline_message || project.current_stage_label || project.current_stage || project.status || "等待");
    $("#contextProgress").textContent = `${progress}%`;
    $("#contextProgressBar").style.width = `${progress}%`;
    const currentStage = Math.max(1, pipelineStageIndex(project));
    $("#contextOpenProject").href = isPipelineProject(project)
      ? stageWorkspaceUrl(currentStage, project.project_id || "")
      : withAuth(`/workspace?project_id=${project.project_id || ""}`);
    renderTaskRail(project);
  }

  function setSending(value) {
    state.sending = Boolean(value);
    $("#agentSendBtn").disabled = state.sending;
    $("#agentInput").disabled = state.sending;
    $("#agentThinking").hidden = !state.sending;
  }

  function selectedSkillRecord() {
    return state.doctorSkills.find((item) => item.key === state.selectedSkill) || null;
  }

  const SKILL_VISUALS = {
    overall_dispatcher: { tone: "ocean", icon: "总检" },
    character_continuity: { tone: "mint", icon: "人物" },
    hook_rhythm: { tone: "sunset", icon: "节奏" },
    logic_holes: { tone: "indigo", icon: "逻辑" },
    character_humanity: { tone: "coral", icon: "人情" },
    character_resonance: { tone: "violet", icon: "共鸣" },
  };

  function skillVisual(skill) {
    return SKILL_VISUALS[String(skill && skill.key || "")] || {
      tone: "ocean",
      icon: String(skill && (skill.short_name || skill.name) || "技能").slice(0, 2),
    };
  }

  function knowledgeTagGroup(tag) {
    const group = String(tag && tag.group || "").trim();
    if (group) return group;
    if (String(tag && tag.id || "").startsWith("excellent_film_beat_")) return "excellent_film_beat";
    return tag && tag.builtin ? "default_style" : "user_custom";
  }

  function selectedKnowledgeTags() {
    const selected = new Set(state.selectedKnowledgeTagIds.map(String));
    return state.knowledgeTags.filter((tag) => selected.has(String(tag.id || "")));
  }

  const KNOWLEDGE_STAGE_FIELDS = [
    ["basic", "01 原文提取"], ["worldview", "02 世界观"], ["character", "03 人物设定"],
    ["beat", "04 三幕十五节拍"], ["storylines", "05 人物故事线"], ["guide", "06 改编指引"],
    ["package", "07 框架校验"], ["scene", "08 场景字典"], ["appearance", "09 角色外观"],
    ["episode", "10 分集细化"], ["conflict", "11 因果冲突"], ["script_text", "12 正文写作"],
  ];

  function knowledgeTagById(tagId) {
    return state.knowledgeTags.find((tag) => String(tag.id || "") === String(tagId || "")) || null;
  }

  function knowledgeOption(tag, { actions = false } = {}) {
    const id = String(tag.id || "");
    const checked = state.selectedKnowledgeTagIds.map(String).includes(id);
    return `
      <div class="agent-knowledge-option-row ${checked ? "is-selected" : ""}">
        <label class="agent-knowledge-option ${checked ? "is-selected" : ""}">
          <input type="checkbox" data-knowledge-tag-id="${escapeHtml(id)}" ${checked ? "checked" : ""}>
          <span class="agent-knowledge-check" aria-hidden="true">${checked ? "✓" : ""}</span>
          <span class="agent-knowledge-copy"><strong>${escapeHtml(tag.name || id)}</strong><small>${escapeHtml(tag.category || "创作偏好")}</small></span>
        </label>
        ${actions ? `<span class="agent-knowledge-row-actions">
          <button type="button" data-knowledge-action="edit" data-tag-id="${escapeHtml(id)}">编辑</button>
          <button type="button" data-knowledge-action="pin" data-tag-id="${escapeHtml(id)}">${tag.pinned ? "取消置顶" : "置顶"}</button>
          <button class="is-danger" type="button" data-knowledge-action="delete" data-tag-id="${escapeHtml(id)}">删除</button>
        </span>` : ""}
      </div>`;
  }

  function renderKnowledgeMain(query) {
    const defaults = state.knowledgeTags.filter((tag) => knowledgeTagGroup(tag) === "default_style" && (!query || [tag.name, tag.category].some((v) => String(v || "").toLowerCase().includes(query))));
    const custom = state.knowledgeTags.filter((tag) => knowledgeTagGroup(tag) === "user_custom" && (!query || [tag.name, tag.category, tag.description].some((v) => String(v || "").toLowerCase().includes(query))));
    const films = state.knowledgeTags.filter((tag) => knowledgeTagGroup(tag) === "excellent_film_beat");
    return `
      <section class="agent-knowledge-group">
        <h3>默认风格<span>${defaults.length}</span></h3>
        <div class="agent-knowledge-options">${defaults.map((tag) => knowledgeOption(tag)).join("") || `<p class="agent-knowledge-empty">暂无匹配标签</p>`}</div>
      </section>
      <button class="agent-knowledge-folder" type="button" data-knowledge-action="open-films">
        <span class="agent-knowledge-folder-mark">影</span><span><strong>优秀电影节拍</strong><small>选择电影后查看详情与 01–12 阶段提示词</small></span><b>${films.length} ›</b>
      </button>
      <section class="agent-knowledge-group">
        <div class="agent-knowledge-group-head"><h3>用户自定义<span>${custom.length}</span></h3><button type="button" data-knowledge-action="new">＋ 新建</button></div>
        <div class="agent-knowledge-custom-list">${custom.map((tag) => knowledgeOption(tag, { actions: true })).join("") || `<p class="agent-knowledge-empty">还没有自定义标签</p>`}</div>
      </section>`;
  }

  function renderKnowledgeFilms(query) {
    const films = state.knowledgeTags.filter((tag) => knowledgeTagGroup(tag) === "excellent_film_beat" && (!query || String(tag.name || "").toLowerCase().includes(query)));
    const pageSize = 16;
    const visible = films.slice(0, state.knowledgeFilmPage * pageSize);
    return `
      <section class="agent-knowledge-film-list">
        <div class="agent-knowledge-view-head"><button type="button" data-knowledge-action="back">‹ 返回</button><span>点击电影查看详情</span></div>
        ${visible.map((tag) => `<button type="button" class="agent-knowledge-film" data-knowledge-action="film-detail" data-tag-id="${escapeHtml(tag.id)}"><span>${escapeHtml(tag.name)}</span><small>${Object.values(tag.stage_prompts || {}).filter((value) => String(value || "").trim()).length}/12 阶段已设置</small><b>›</b></button>`).join("") || `<p class="agent-knowledge-empty is-search">没有找到电影</p>`}
        ${visible.length < films.length ? `<button class="agent-knowledge-more" type="button" data-knowledge-action="more-films">继续加载（${films.length - visible.length}）</button>` : ""}
      </section>`;
  }

  function renderKnowledgeDetail(tag) {
    if (!tag) return renderKnowledgeMain("");
    const checked = state.selectedKnowledgeTagIds.map(String).includes(String(tag.id || ""));
    return `
      <section class="agent-knowledge-detail">
        <div class="agent-knowledge-view-head"><button type="button" data-knowledge-action="back-films">‹ 返回电影</button><button type="button" data-knowledge-action="edit" data-tag-id="${escapeHtml(tag.id)}">编辑为我的版本</button></div>
        <div class="agent-knowledge-detail-title"><span class="agent-knowledge-folder-mark">影</span><span><h3>${escapeHtml(tag.name)}</h3><p>${escapeHtml(tag.description || "优秀电影节拍参考模板")}</p></span></div>
        <label class="agent-knowledge-detail-select"><input type="checkbox" data-knowledge-tag-id="${escapeHtml(tag.id)}" ${checked ? "checked" : ""}><span>${checked ? "已选择用于 Agent 创作" : "选择用于 Agent 创作"}</span></label>
        <div class="agent-knowledge-general"><strong>通用创作偏好</strong><p>${escapeHtml(tag.prompt_text || "暂无通用偏好，可编辑为个人版本。")}</p></div>
        <div class="agent-knowledge-stage-detail">${KNOWLEDGE_STAGE_FIELDS.map(([key, label]) => `<article><strong>${label}</strong><p>${escapeHtml(String((tag.stage_prompts || {})[key] || "暂无阶段提示词"))}</p></article>`).join("")}</div>
      </section>`;
  }

  function renderKnowledgeForm(tag) {
    const editing = Boolean(tag);
    const prompts = tag && tag.stage_prompts || {};
    return `
      <section class="agent-knowledge-form" data-editing-id="${escapeHtml(tag && tag.id || "")}">
        <div class="agent-knowledge-view-head"><button type="button" data-knowledge-action="back">‹ 返回</button><span>${editing ? "保存后生成个人副本" : "创建后自动选中"}</span></div>
        <h3>${editing ? `编辑：${escapeHtml(tag.name || "未命名")}` : "新建自定义标签"}</h3>
        <div class="agent-knowledge-form-grid">
          <label><span>名称</span><input data-knowledge-form="name" value="${escapeHtml(tag && tag.name || "")}"></label>
          <label><span>分类</span><input data-knowledge-form="category" value="${escapeHtml(tag && tag.category || "自定义")}"></label>
        </div>
        <label><span>描述</span><input data-knowledge-form="description" value="${escapeHtml(tag && tag.description || "")}"></label>
        <label><span>通用创作偏好</span><textarea data-knowledge-form="prompt_text">${escapeHtml(tag && tag.prompt_text || "")}</textarea></label>
        <h4>01–12 分阶段提示词</h4>
        <div class="agent-knowledge-form-stages">${KNOWLEDGE_STAGE_FIELDS.map(([key, label]) => `<label><span>${label}</span><textarea data-knowledge-stage="${key}">${escapeHtml(String(prompts[key] || ""))}</textarea></label>`).join("")}</div>
        <button class="agent-knowledge-form-save" type="button" data-knowledge-action="save-form">${editing ? "保存为我的标签" : "创建标签"}</button>
      </section>`;
  }

  function renderKnowledgeButton() {
    const tags = selectedKnowledgeTags();
    $("#knowledgeSelectionLabel").textContent = tags.length
      ? (tags.length <= 2 ? tags.map((tag) => tag.name).join("、") : `已选择 ${tags.length} 种风格`)
      : "选择创作风格";
    $("#knowledgePickerBtn").classList.toggle("has-selection", tags.length > 0);
    $("#knowledgeSelectedCount").textContent = `已选择 ${tags.length} 项`;
  }

  function renderKnowledgePicker() {
    const query = String($("#knowledgeSearchInput")?.value || "").trim().toLowerCase();
    $("#knowledgePickerStatus").textContent = state.knowledgeTags.length
      ? `共 ${state.knowledgeTags.length} 个可用标签，可多选。`
      : "暂无可用标签。";
    const activeTag = knowledgeTagById(state.knowledgeActiveTagId);
    $("#knowledgeTagGroups").innerHTML = state.knowledgeView === "films"
      ? renderKnowledgeFilms(query)
      : state.knowledgeView === "detail"
        ? renderKnowledgeDetail(activeTag)
        : state.knowledgeView === "form"
          ? renderKnowledgeForm(activeTag)
          : renderKnowledgeMain(query);
    $("#knowledgeSearchInput").closest("label").hidden = ["detail", "form"].includes(state.knowledgeView);
    renderKnowledgeButton();
  }

  async function saveKnowledgeTagForm() {
    const form = $("#knowledgeTagGroups .agent-knowledge-form");
    if (!form) return;
    const editingId = String(form.dataset.editingId || "");
    const payload = {
      name: String(form.querySelector('[data-knowledge-form="name"]')?.value || "").trim(),
      category: String(form.querySelector('[data-knowledge-form="category"]')?.value || "自定义").trim(),
      description: String(form.querySelector('[data-knowledge-form="description"]')?.value || "").trim(),
      prompt_text: String(form.querySelector('[data-knowledge-form="prompt_text"]')?.value || "").trim(),
      stage_prompts: {},
    };
    form.querySelectorAll("[data-knowledge-stage]").forEach((field) => {
      payload.stage_prompts[field.dataset.knowledgeStage] = field.value;
    });
    if (!payload.name) {
      $("#knowledgePickerStatus").textContent = "请填写标签名称。";
      return;
    }
    const data = await fetchJson(editingId ? `/api/user-knowledge/tags/${encodeURIComponent(editingId)}` : "/api/user-knowledge/tags", {
      method: editingId ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    const tag = data.tag;
    const savedTagId = String(tag && tag.id || "");
    await loadKnowledgeLibrary();
    if (savedTagId) {
      state.selectedKnowledgeTagIds = Array.from(new Set(state.selectedKnowledgeTagIds.concat(savedTagId)));
    }
    state.knowledgeView = "main";
    state.knowledgeActiveTagId = "";
    renderKnowledgePicker();
  }

  async function updateKnowledgeTag(tagId, changes) {
    await fetchJson(`/api/user-knowledge/tags/${encodeURIComponent(tagId)}`, {
      method: "PATCH",
      body: JSON.stringify(changes),
    });
    await loadKnowledgeLibrary();
  }

  async function deleteKnowledgeTag(tagId) {
    if (!window.confirm("确认删除这个自定义标签吗？已生成项目会保留历史内容。")) return;
    await fetchJson(`/api/user-knowledge/tags/${encodeURIComponent(tagId)}`, { method: "DELETE" });
    await loadKnowledgeLibrary();
    state.selectedKnowledgeTagIds = state.selectedKnowledgeTagIds.filter((id) => String(id) !== String(tagId));
  }

  async function loadKnowledgeLibrary() {
    try {
      const [tagsData, preferencesData] = await Promise.all([
        fetchJson("/api/user-knowledge/tags"),
        fetchJson("/api/user-knowledge/preferences"),
      ]);
      state.knowledgeTags = Array.isArray(tagsData.tags) ? tagsData.tags : [];
      state.knowledgePreferences = preferencesData.preferences || {};
      state.selectedKnowledgeTagIds = Array.isArray(state.knowledgePreferences.selected_preference_tag_ids)
        ? state.knowledgePreferences.selected_preference_tag_ids.map(String)
        : [];
    } catch (error) {
      state.knowledgeTags = [];
      $("#knowledgePickerStatus").textContent = error.message || "智慧库加载失败";
    }
    renderKnowledgePicker();
  }

  async function saveKnowledgeSelection() {
    if (state.knowledgeSaving) return;
    state.knowledgeSaving = true;
    const button = $("#knowledgeApplyBtn");
    button.disabled = true;
    button.textContent = "正在应用…";
    try {
      const applied = await fetchJson("/api/user-knowledge/apply-tags", {
        method: "POST",
        body: JSON.stringify({ selected_tag_ids: state.selectedKnowledgeTagIds }),
      });
      const saved = await fetchJson("/api/user-knowledge/preferences", {
        method: "PUT",
        body: JSON.stringify({
          selected_preference_tag_ids: applied.selected_preference_tag_ids || state.selectedKnowledgeTagIds,
          user_preference_prompt: state.knowledgePreferences.user_preference_prompt || "",
          stage_prompts: applied.stage_prompts || {},
        }),
      });
      state.knowledgePreferences = saved.preferences || state.knowledgePreferences;
      state.selectedKnowledgeTagIds = (applied.selected_preference_tag_ids || state.selectedKnowledgeTagIds).map(String);
      $("#knowledgePicker").hidden = true;
      $("#knowledgePickerBtn").setAttribute("aria-expanded", "false");
      renderKnowledgePicker();
    } catch (error) {
      $("#knowledgePickerStatus").textContent = error.message || "智慧库应用失败";
    } finally {
      state.knowledgeSaving = false;
      button.disabled = false;
      button.textContent = "应用到 Agent";
    }
  }

  function renderSkillAttachment() {
    const attachment = $("#skillAttachment");
    const skill = selectedSkillRecord();
    attachment.hidden = !skill;
    $("#skillAttachmentName").textContent = skill ? (skill.name || skill.short_name || skill.key) : "";
  }

  function renderSkillPicker() {
    const picker = $("#skillPicker");
    if (!picker) return;
    picker.innerHTML = state.doctorSkills.map((skill) => {
      const visual = skillVisual(skill);
      return `
      <button class="agent-skill-option is-${visual.tone} ${skill.key === state.selectedSkill ? "is-selected" : ""}" type="button" role="option" aria-selected="${skill.key === state.selectedSkill}" data-skill-key="${escapeHtml(skill.key)}">
        <span class="agent-skill-mark" aria-hidden="true">${escapeHtml(visual.icon)}</span>
        <span class="agent-skill-copy"><strong>${escapeHtml(skill.name || skill.key)}</strong><small>${escapeHtml(skill.description || "")}</small></span>
      </button>
    `;
    }).join("");
  }

  function selectSkill(skillKey) {
    state.selectedSkill = String(skillKey || "");
    renderSkillAttachment();
    renderSkillPicker();
    $("#skillPicker").hidden = true;
    $("#skillPickerBtn").setAttribute("aria-expanded", "false");
    $("#agentInput").focus();
  }

  function renderFileAttachment() {
    const attachment = state.selectedAttachment;
    $("#fileAttachment").hidden = !attachment;
    $("#fileAttachmentName").textContent = attachment ? attachment.filename : "";
    $("#fileAttachmentType").textContent = attachment ? String(attachment.extension || "FILE").replace(".", "").toUpperCase() : "FILE";
    $("#fileAttachmentMeta").textContent = attachment
      ? `${Number(attachment.char_count || 0).toLocaleString("zh-CN")} 字${attachment.converted_to_docx ? " · 将输出 Word" : ""}`
      : "";
  }

  async function uploadAttachment(file) {
    if (!file || !state.currentConversationId || state.uploadingAttachment) return;
    state.uploadingAttachment = true;
    const button = $("#filePickerBtn");
    const previousText = button.textContent;
    button.disabled = true;
    button.textContent = "上传中";
    try {
      const form = new FormData();
      form.append("file", file);
      const data = await fetchJson(
        `${config.conversationsUrl}/${encodeURIComponent(state.currentConversationId)}/attachments`,
        { method: "POST", body: form },
      );
      state.selectedAttachment = data.attachment || null;
      if (!state.selectedSkill) state.selectedSkill = "overall_dispatcher";
      renderFileAttachment();
      renderSkillAttachment();
      renderSkillPicker();
      $("#agentInput").focus();
    } catch (error) {
      window.alert(error.message || "文件上传失败");
    } finally {
      state.uploadingAttachment = false;
      button.disabled = false;
      button.textContent = previousText;
      $("#agentFileInput").value = "";
    }
  }

  async function downloadAuthenticated(url, filename) {
    const response = await fetch(withAuth(url), { headers: authHeaders() });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || data.message || "下载失败");
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename || "AI优化版剧本.docx";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  }

  async function optimizeAndDownload(historyId, button) {
    const previousText = button.textContent;
    button.disabled = true;
    button.textContent = "正在优化…";
    try {
      const data = await fetchJson(`/api/workbuddy/doctor/history/${encodeURIComponent(historyId)}/optimize`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      await downloadAuthenticated(data.download_url, data.download_name || "AI优化版剧本.docx");
      button.textContent = "优化版已下载";
    } catch (error) {
      button.disabled = false;
      button.textContent = previousText;
      window.alert(error.message || "一键优化失败");
    }
  }

  function autoSizeInput() {
    const input = $("#agentInput");
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  }

  async function loadStatus() {
    const pill = $("#agentStatusPill");
    try {
      const data = await fetchJson(config.statusUrl);
      const agent = data.agent || {};
      state.doctorSkills = Array.isArray(agent.doctor_skills) ? agent.doctor_skills : [];
      renderSkillPicker();
      if (pill) {
        pill.className = `agent-status-pill ${agent.configured ? "is-ready" : "is-error"}`;
        pill.innerHTML = `<i></i>${escapeHtml(agent.configured ? "服务已连接" : "服务未配置")}`;
      }
      const capabilities = Array.isArray(agent.capabilities) ? agent.capabilities : [];
      const capabilityList = $("#agentCapabilityList");
      if (capabilityList && capabilities.length) {
        capabilityList.innerHTML = capabilities.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
      }
    } catch (error) {
      if (pill) {
        pill.className = "agent-status-pill is-error";
        pill.innerHTML = `<i></i>${escapeHtml(error.message || "连接失败")}`;
      }
    }
  }

  async function loadConversations({ openFirst = true } = {}) {
    const data = await fetchJson(config.conversationsUrl);
    state.conversations = Array.isArray(data.conversations) ? data.conversations : [];
    renderConversations();
    if (openFirst && !state.currentConversationId) {
      if (state.conversations.length) await openConversation(state.conversations[0].id);
      else await createConversation();
    }
  }

  async function createConversation() {
    const data = await fetchJson(config.conversationsUrl, { method: "POST", body: JSON.stringify({}) });
    const conversation = data.conversation;
    state.conversations.unshift(conversation);
    state.currentConversationId = conversation.id;
    state.messages = Array.isArray(data.messages) ? data.messages : [];
    state.context = {};
    $("#conversationTitle").textContent = conversation.title || "新的创作对话";
    renderConversations();
    renderMessages();
    renderContext();
    $("#agentInput").focus();
  }

  async function openConversation(conversationId, { silent = false } = {}) {
    if (!conversationId) return;
    const data = await fetchJson(`${config.conversationsUrl}/${encodeURIComponent(conversationId)}`);
    state.currentConversationId = conversationId;
    state.messages = Array.isArray(data.messages) ? data.messages : [];
    state.context = data.context || {};
    const conversation = data.conversation || {};
    $("#conversationTitle").textContent = conversation.title || "新的创作对话";
    renderConversations();
    renderMessages({ scrollToBottom: !silent });
    renderContext();
    if (!silent) $("#agentInput").focus();
    schedulePoll();
  }

  async function deleteConversation(conversationId) {
    await fetchJson(`${config.conversationsUrl}/${encodeURIComponent(conversationId)}`, { method: "DELETE" });
    state.conversations = state.conversations.filter((item) => item.id !== conversationId);
    if (state.currentConversationId === conversationId) {
      state.currentConversationId = "";
      state.messages = [];
      state.context = {};
      if (state.conversations.length) await openConversation(state.conversations[0].id);
      else await createConversation();
    } else {
      renderConversations();
    }
  }

  async function sendMessage(text) {
    const content = String(text || "").trim();
    if (!content || state.sending) return;
    if (!state.currentConversationId) await createConversation();
    const attachedSkill = selectedSkillRecord();
    const attachedDocument = state.selectedAttachment;
    const attachedKnowledgeTags = selectedKnowledgeTags();
    const optimistic = {
      id: `local-${Date.now()}`,
      role: "user",
      content,
      metadata: {
        ...(attachedSkill ? { selected_skill: attachedSkill.key, selected_skill_name: attachedSkill.name } : {}),
        ...(attachedKnowledgeTags.length ? {
          selected_knowledge_tag_ids: attachedKnowledgeTags.map((tag) => String(tag.id || "")),
          selected_knowledge_tag_names: attachedKnowledgeTags.map((tag) => String(tag.name || tag.id || "")),
        } : {}),
        ...(attachedDocument ? {
          attachment_id: attachedDocument.id,
          attachment_name: attachedDocument.filename,
          attachment_extension: attachedDocument.extension,
        } : {}),
      },
      created_at: new Date().toISOString(),
    };
    state.messages.push(optimistic);
    renderMessages();
    $("#agentInput").value = "";
    autoSizeInput();
    setSending(true);
    try {
      const requestId = window.crypto && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
      const data = await fetchJson(
        `${config.conversationsUrl}/${encodeURIComponent(state.currentConversationId)}/messages`,
        { method: "POST", body: JSON.stringify({
          content,
          request_id: requestId,
          selected_skill: attachedSkill ? attachedSkill.key : "",
          selected_knowledge_tag_ids: attachedKnowledgeTags.map((tag) => String(tag.id || "")),
          attachment_id: attachedDocument ? attachedDocument.id : "",
        }) },
      );
      state.messages = state.messages.filter((item) => item.id !== optimistic.id);
      if (data.user_message) state.messages.push(data.user_message);
      if (data.assistant_message) state.messages.push(data.assistant_message);
      state.context = data.context || state.context;
      if (data.conversation) {
        const index = state.conversations.findIndex((item) => item.id === data.conversation.id);
        if (index >= 0) state.conversations[index] = data.conversation;
        else state.conversations.unshift(data.conversation);
        $("#conversationTitle").textContent = data.conversation.title || "创作对话";
      }
      renderConversations();
      renderMessages();
      renderContext();
      if (attachedSkill && state.selectedSkill === attachedSkill.key) selectSkill("");
      if (attachedDocument && state.selectedAttachment && state.selectedAttachment.id === attachedDocument.id) {
        state.selectedAttachment = null;
        renderFileAttachment();
      }
      schedulePoll();
    } catch (error) {
      state.messages.push({
        id: `error-${Date.now()}`,
        role: "assistant",
        content: `这次请求没有完成：${error.message || "请稍后重试"}`,
        metadata: {},
        created_at: new Date().toISOString(),
      });
      renderMessages();
    } finally {
      setSending(false);
      $("#agentInput").focus();
    }
  }

  function schedulePoll() {
    if (state.pollTimer) window.clearInterval(state.pollTimer);
    const project = state.context && state.context.current_project;
    const taskStatusActive = project && ["pending", "running", "in_progress", "pausing", "paused", "retrying"].includes(String(project.status || "").toLowerCase());
    if (!project || (!taskStatusActive && !isPipelineActive(project))) return;
    state.pollTimer = window.setInterval(() => {
      if (!state.sending && state.currentConversationId) openConversation(state.currentConversationId, { silent: true }).catch(() => {});
    }, 5000);
  }

  $("#agentComposer").addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage($("#agentInput").value);
  });
  $("#agentInput").addEventListener("input", autoSizeInput);
  $("#agentInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage(event.currentTarget.value);
    }
  });
  $("#skillPickerBtn").addEventListener("click", (event) => {
    event.stopPropagation();
    const picker = $("#skillPicker");
    picker.hidden = !picker.hidden;
    event.currentTarget.setAttribute("aria-expanded", String(!picker.hidden));
  });
  $("#skillPicker").addEventListener("click", (event) => {
    const option = event.target.closest("[data-skill-key]");
    if (option) selectSkill(option.dataset.skillKey);
  });
  $("#removeSkillBtn").addEventListener("click", () => selectSkill(""));
  $("#knowledgePickerBtn").addEventListener("click", (event) => {
    event.stopPropagation();
    const picker = $("#knowledgePicker");
    picker.hidden = !picker.hidden;
    event.currentTarget.setAttribute("aria-expanded", String(!picker.hidden));
    if (!picker.hidden) {
      picker.scrollTop = 0;
      $("#knowledgeSearchInput").focus({ preventScroll: true });
    }
  });
  $("#knowledgePickerClose").addEventListener("click", () => {
    $("#knowledgePicker").hidden = true;
    $("#knowledgePickerBtn").setAttribute("aria-expanded", "false");
  });
  $("#knowledgeSearchInput").addEventListener("input", renderKnowledgePicker);
  $("#knowledgeTagGroups").addEventListener("click", async (event) => {
    const action = event.target.closest("[data-knowledge-action]");
    if (!action) return;
    event.preventDefault();
    event.stopPropagation();
    const tagId = String(action.dataset.tagId || "");
    try {
      if (action.dataset.knowledgeAction === "open-films") {
        state.knowledgeView = "films";
        state.knowledgeFilmPage = 1;
      } else if (action.dataset.knowledgeAction === "film-detail") {
        state.knowledgeView = "detail";
        state.knowledgeActiveTagId = tagId;
      } else if (action.dataset.knowledgeAction === "more-films") {
        state.knowledgeFilmPage += 1;
      } else if (action.dataset.knowledgeAction === "back-films") {
        state.knowledgeView = "films";
        state.knowledgeActiveTagId = "";
      } else if (action.dataset.knowledgeAction === "back") {
        state.knowledgeView = "main";
        state.knowledgeActiveTagId = "";
      } else if (action.dataset.knowledgeAction === "new") {
        state.knowledgeView = "form";
        state.knowledgeActiveTagId = "";
      } else if (action.dataset.knowledgeAction === "edit") {
        state.knowledgeView = "form";
        state.knowledgeActiveTagId = tagId;
      } else if (action.dataset.knowledgeAction === "save-form") {
        await saveKnowledgeTagForm();
        return;
      } else if (action.dataset.knowledgeAction === "pin") {
        const tag = knowledgeTagById(tagId);
        await updateKnowledgeTag(tagId, { pinned: !(tag && tag.pinned) });
      } else if (action.dataset.knowledgeAction === "delete") {
        await deleteKnowledgeTag(tagId);
      }
      renderKnowledgePicker();
      $("#knowledgeTagGroups").scrollTop = 0;
    } catch (error) {
      $("#knowledgePickerStatus").textContent = error.message || "智慧库操作失败";
    }
  });
  $("#knowledgeTagGroups").addEventListener("change", (event) => {
    const checkbox = event.target.closest("input[data-knowledge-tag-id]");
    if (!checkbox) return;
    const id = String(checkbox.dataset.knowledgeTagId || "");
    const selected = new Set(state.selectedKnowledgeTagIds.map(String));
    if (checkbox.checked) selected.add(id);
    else selected.delete(id);
    state.selectedKnowledgeTagIds = Array.from(selected);
    renderKnowledgePicker();
  });
  $("#knowledgeClearBtn").addEventListener("click", () => {
    state.selectedKnowledgeTagIds = [];
    renderKnowledgePicker();
  });
  $("#knowledgeApplyBtn").addEventListener("click", saveKnowledgeSelection);
  $("#filePickerBtn").addEventListener("click", () => $("#agentFileInput").click());
  $("#agentFileInput").addEventListener("change", (event) => uploadAttachment(event.target.files && event.target.files[0]));
  $("#removeFileBtn").addEventListener("click", () => {
    state.selectedAttachment = null;
    renderFileAttachment();
  });
  $("#taskPanelToggle").addEventListener("click", () => {
    state.taskPanelOpen = $(".agent-shell").classList.contains("is-task-panel-collapsed");
    if (window.matchMedia("(max-width: 760px)").matches) {
      $("#agentContextPanel").classList.toggle("is-open", state.taskPanelOpen);
    }
    syncTaskPanelVisibility(state.context && state.context.current_project ? state.context.current_project : null);
  });
  $("#taskPanelClose").addEventListener("click", () => {
    state.taskPanelOpen = false;
    $("#agentContextPanel").classList.remove("is-open");
    syncTaskPanelVisibility(state.context && state.context.current_project ? state.context.current_project : null);
  });
  $("#newConversationBtn").addEventListener("click", () => createConversation().catch((error) => alert(error.message)));
  $("#conversationList").addEventListener("click", (event) => {
    const deleteButton = event.target.closest("[data-delete-conversation]");
    if (deleteButton) {
      event.stopPropagation();
      const row = deleteButton.closest("[data-conversation-id]");
      const title = row && row.dataset.conversationTitle || "这条创作对话";
      if (window.confirm(`删除《${title}》会话？\n已创建的剧本项目和资产不会删除。`)) {
        deleteConversation(deleteButton.dataset.deleteConversation).catch((error) => alert(error.message));
      }
      return;
    }
    const item = event.target.closest("[data-conversation-id]");
    if (item) openConversation(item.dataset.conversationId).catch((error) => alert(error.message));
  });
  $("#conversationList").addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key) || event.target.closest("button")) return;
    const item = event.target.closest("[data-conversation-id]");
    if (!item) return;
    event.preventDefault();
    openConversation(item.dataset.conversationId).catch((error) => alert(error.message));
  });
  document.addEventListener("click", async (event) => {
    if (!event.target.closest("#skillPicker, #skillPickerBtn")) {
      $("#skillPicker").hidden = true;
      $("#skillPickerBtn").setAttribute("aria-expanded", "false");
    }
    if (!event.target.closest("#knowledgePicker, #knowledgePickerBtn")) {
      $("#knowledgePicker").hidden = true;
      $("#knowledgePickerBtn").setAttribute("aria-expanded", "false");
    }
    const optimizeButton = event.target.closest("[data-optimize-history-id]");
    if (optimizeButton) {
      await optimizeAndDownload(optimizeButton.dataset.optimizeHistoryId, optimizeButton);
      return;
    }
    const fillButton = event.target.closest("[data-agent-fill]");
    if (fillButton) {
      const input = $("#agentInput");
      input.value = fillButton.dataset.agentFill || "";
      autoSizeInput();
      input.focus();
      return;
    }
    const promptButton = event.target.closest("[data-prompt], [data-agent-prompt]");
    if (!promptButton) return;
    const prompt = promptButton.dataset.prompt || promptButton.dataset.agentPrompt || "";
    if (prompt) sendMessage(prompt);
  });

  Promise.all([loadStatus(), loadKnowledgeLibrary(), loadConversations()]).catch((error) => {
    state.messages = [{ role: "assistant", content: `Agent工作台初始化失败：${error.message}`, metadata: {}, created_at: new Date().toISOString() }];
    renderMessages();
  });
})();
