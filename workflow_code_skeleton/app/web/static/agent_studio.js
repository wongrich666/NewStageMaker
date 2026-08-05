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
    distilledSkillLocked: false,
    taskPanelOpen: null,
    taskPanelProjectId: "",
    selectedTaskIdentity: "",
    selectedAttachment: null,
    uploadingAttachment: false,
  };

  const SCRIPT_TEAM_STAGES = [
    ["01", "总编剧"],
    ["02", "故事架构师"],
    ["03", "人物情感编剧"],
    ["04", "分集连续性编剧"],
    ["05", "正文对白编剧"],
    ["06", "状态记录器"],
    ["07", "终审与钩子编辑"],
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
    return String(value || "");
  }

  function formatInlineContent(value) {
    return escapeHtml(value)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function markdownTable(lines) {
    const rows = lines.map((line) => line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()));
    if (rows.length < 2 || rows[0].length < 2) return "";
    const separatorIndex = rows[1].every((cell) => /^:?-{3,}:?$/.test(cell)) ? 1 : -1;
    const header = rows[0];
    const body = rows.slice(separatorIndex === 1 ? 2 : 1);
    return `
      <div class="agent-copy-table-wrap">
        <table class="agent-copy-table">
          <thead><tr>${header.map((cell) => `<th>${formatInlineContent(cell)}</th>`).join("")}</tr></thead>
          ${body.length ? `<tbody>${body.map((row) => `<tr>${header.map((_, index) => `<td>${formatInlineContent(row[index] || "")}</td>`).join("")}</tr>`).join("")}</tbody>` : ""}
        </table>
      </div>`;
  }

  function formatMessageContent(value) {
    const lines = String(value || "").split(/\r?\n/);
    const formatted = [];
    for (let index = 0; index < lines.length; index += 1) {
      const rawLine = lines[index];
      if (/^\s*\|.*\|\s*$/.test(rawLine)) {
        const tableLines = [];
        while (index < lines.length && /^\s*\|.*\|\s*$/.test(lines[index])) {
          tableLines.push(lines[index]);
          index += 1;
        }
        index -= 1;
        const table = markdownTable(tableLines);
        if (table) {
          formatted.push(table);
          continue;
        }
      }
      const line = formatInlineContent(rawLine);
      const heading = line.match(/^(#{1,3})\s+(.+)$/);
      if (heading) formatted.push(`<div class="agent-copy-heading level-${heading[1].length}">${heading[2]}</div>`);
      else if (/^\s*---+\s*$/.test(line)) formatted.push('<div class="agent-copy-divider"></div>');
      else if (/^\s*&gt;\s?/.test(line)) formatted.push(`<div class="agent-copy-quote">${line.replace(/^\s*&gt;\s?/, "")}</div>`);
      else if (/^\s*[-*]\s+/.test(line)) formatted.push(`<div class="agent-copy-list-item">${line.replace(/^\s*[-*]\s+/, "")}</div>`);
      else formatted.push(`<div class="agent-copy-line">${line || "&nbsp;"}</div>`);
    }
    return formatted.join("");
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
    if (conversationState.script_team_job_id || (item && String(item.task_id || "").startsWith("npc-"))) {
      return { label: "已关联", className: "is-linked" };
    }
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

  function eventCard(event, { answered = false } = {}) {
    const result = event && event.result && typeof event.result === "object" ? event.result : {};
    const ui = result.ui && typeof result.ui === "object" ? result.ui : {};
    if (ui.kind === "choice") {
      const options = Array.isArray(result.options) ? result.options : [];
      const step = Math.max(1, Number(result.step || 1));
      const total = Math.max(step, Number(result.total || step));
      return `
        <section class="agent-choice-card ${answered ? "is-answered" : ""}">
          <header>
            <div><span>补齐关键信息</span><h4>${escapeHtml(result.question || "请选择一个选项")}</h4></div>
            <b>${step}/${total}</b>
          </header>
          <div class="agent-choice-options">
            ${options.map((option, index) => `
              <button type="button" data-agent-choice="${escapeHtml(option.prompt || option.label || "")}" ${answered ? "disabled" : ""}>
                <span>${index + 1}</span>
                <strong>${escapeHtml(option.label || `选项 ${index + 1}`)}</strong>
                ${option.description ? `<small>${escapeHtml(option.description)}</small>` : ""}
                <b aria-hidden="true">›</b>
              </button>`).join("")}
          </div>
          <footer>
            ${answered
              ? '<span class="agent-choice-done">已回答，选择结果已进入对话</span>'
              : `<button type="button" data-agent-fill="${escapeHtml(result.custom_prefix || "我的选择：")}">自己输入</button>
                 <button type="button" data-agent-choice="这个选项由你根据故事目标决定，采用平台推荐的默认值。">由 Agent 决定</button>`}
          </footer>
        </section>`;
    }
    if (ui.kind === "confirmation") {
      const summary = result.summary || {};
      const costEstimate = summary.cost_estimate || {};
      const knowledgeNames = Array.isArray(summary.selected_preference_tags)
        ? summary.selected_preference_tags.map((item) => item && (item.name || item.id)).filter(Boolean)
        : [];
      return `
        <section class="agent-event-card is-confirmation">
          <h4>生成方案已准备</h4>
          <p>${summary.execution_scope === "framework_only"
            ? "确认后由专业剧本团队执行前四个策划节点，不生成剧本正文。"
            : "确认后由专业剧本团队执行全部七个节点，过程中可以继续查询或暂停。"}</p>
          <div class="agent-event-tags">
            <span>${escapeHtml(summary.title || "未命名剧本")}</span>
            <span>${escapeHtml(summary.total_episodes || 0)} 集</span>
            <span>${escapeHtml(summary.character_count || 0)} 个主要角色</span>
            <span>每集 ${escapeHtml(summary.episode_word_count || 600)} 字</span>
            ${summary.source_filename ? `<span>源文件：${escapeHtml(summary.source_filename)}</span>` : ""}
            <span>${summary.execution_scope === "framework_only" ? "剧本团队前四个策划节点" : "剧本团队七节点完整生成"}</span>
            ${costEstimate.paid_call_range ? `<span>预计付费调用 ${escapeHtml(costEstimate.paid_call_range)}</span>` : ""}
            ${costEstimate.estimated_output_chars ? `<span>预计正文 ${Number(costEstimate.estimated_output_chars).toLocaleString()} 字</span>` : ""}
            ${summary.distilled_skill_name ? `<span>蒸馏架构：${escapeHtml(summary.distilled_skill_name)} · ${escapeHtml(summary.distilled_skill_version || "")}</span>` : ""}
            ${knowledgeNames.length ? `<span>历史创作偏好：${escapeHtml(knowledgeNames.join("、"))}</span>` : ""}
          </div>
          ${costEstimate.notice ? `<p class="agent-cost-notice">${escapeHtml(costEstimate.notice)}</p>` : ""}
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
            ${(project.selected_skill || {}).name ? `<span>Skill：${escapeHtml(project.selected_skill.name)} · ${escapeHtml(project.selected_skill.version || "")}</span>` : ""}
          </div>
          <div class="agent-event-actions"><a href="${escapeHtml(withAuth(project.workspace_url || "/new-workflow-test"))}">打开专业剧本团队</a></div>
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
          <h4>功能入口</h4>
          <p>可以进入对应模块继续操作。</p>
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
    const heroVisible = visible.length <= 1;
    $("#agentHero").hidden = !heroVisible;
    list.innerHTML = visible.map((item, messageIndex) => {
      const isUser = item.role === "user";
      const metadata = item.metadata && typeof item.metadata === "object" ? item.metadata : {};
      const events = Array.isArray(metadata.events) ? metadata.events : [];
      const hasTable = /^\s*\|.*\|\s*$/m.test(String(item.content || ""));
      const skillChip = metadata.selected_skill_name
        ? `<div class="agent-message-skill"><span>SKILL</span>${escapeHtml(metadata.selected_skill_name)}</div>`
        : "";
      const fileChip = metadata.attachment_name
        ? `<div class="agent-message-file"><span>FILE</span>${escapeHtml(metadata.attachment_name)}</div>`
        : "";
      const knowledgeNames = Array.isArray(metadata.selected_knowledge_tag_names) ? metadata.selected_knowledge_tag_names : [];
      const knowledgeChip = knowledgeNames.length
        ? `<div class="agent-message-knowledge"><span>创作偏好</span>${escapeHtml(knowledgeNames.join("、"))}</div>`
        : "";
      const distilledSkillChip = metadata.distilled_skill_name
        ? `<div class="agent-message-skill is-distilled"><span>蒸馏架构</span>${escapeHtml(metadata.distilled_skill_name)} · ${escapeHtml(metadata.distilled_skill_version || "")}</div>`
        : "";
      return `
        <article class="agent-message ${isUser ? "is-user" : "is-assistant"} ${hasTable ? "has-table" : ""}">
          <div class="agent-message-avatar">${isUser ? escapeHtml((config.username || "我").slice(0, 1)) : "AI"}</div>
          <div class="agent-message-body">
            ${fileChip}${skillChip}${distilledSkillChip}${knowledgeChip}
            <div class="agent-message-copy">${formatMessageContent(userFacingText(item.content || ""))}</div>
            ${events.length ? `<div class="agent-event-stack">${events.map((event) => eventCard(event, {
              answered: !isUser && visible.slice(messageIndex + 1).some((later) => later.role === "user"),
            })).join("")}</div>` : ""}
            <div class="agent-message-meta">${escapeHtml(formatTime(item.created_at))}</div>
          </div>
        </article>`;
    }).join("");
    requestAnimationFrame(() => {
      if (heroVisible && scrollToBottom) viewport.scrollTo({ top: 0, behavior: "auto" });
      else if (scrollToBottom || wasNearBottom) viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
      else viewport.scrollTop = previousScrollTop;
    });
  }

  function pipelineStageIndex(project) {
    const explicit = Number(project && project.pipeline_stage);
    return explicit >= 1 && explicit <= 7 ? explicit : 1;
  }

  function isPipelineProject(project) {
    return Boolean(project && project.generation_chain === "script_team_v2");
  }

  function isScriptTeamProject(project) {
    return Boolean(project && project.generation_chain === "script_team_v2");
  }

  function isPipelineActive(project) {
    if (!isPipelineProject(project)) return false;
    const phase = String(project.pipeline_phase || "").toLowerCase();
    return !["completed", "failed", "terminated"].includes(phase);
  }

  function pipelineProgress(project) {
    return Math.max(0, Math.min(100, Number(project && project.progress_percent || 0)));
  }

  function currentBackgroundOperation() {
    const context = state.context && typeof state.context === "object" ? state.context : {};
    if (context.active_operation) return context.active_operation;
    const project = context.current_project || null;
    const projectStatus = String(project && project.status || "").toLowerCase();
    const activeProject = project && (["pending", "running", "in_progress", "pausing", "paused", "retrying"].includes(projectStatus) || isPipelineActive(project));
    return activeProject ? null : (context.last_operation || null);
  }

  function operationIsActive(operation) {
    return Boolean(operation && operation.status === "running");
  }

  function operationElapsed(operation) {
    const startedAt = new Date(operation && operation.started_at || "");
    if (Number.isNaN(startedAt.getTime())) return "正在运行";
    const seconds = Math.max(0, Math.floor((Date.now() - startedAt.getTime()) / 1000));
    if (seconds < 60) return `已运行 ${seconds} 秒`;
    return `已运行 ${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
  }

  function taskHistoryRecords() {
    const context = state.context && typeof state.context === "object" ? state.context : {};
    return Array.isArray(context.task_history) ? context.task_history.filter((item) => item && item.identity) : [];
  }

  function renderTaskHistory(records, selectedIdentity) {
    const container = $("#agentTaskHistory");
    const list = $("#agentTaskHistoryList");
    const count = $("#agentTaskHistoryCount");
    if (!container || !list || !count) return;
    container.hidden = records.length < 2;
    count.textContent = String(records.length);
    list.innerHTML = records.slice().reverse().map((record) => {
      const project = record.kind === "script_team" && record.project ? record.project : null;
      const operation = record.kind === "operation" && record.operation ? record.operation : null;
      const title = project
        ? (project.title || "剧本团队任务")
        : (operation && (operation.filename || operation.skill_name)) || "剧本任务";
      const status = String((project && (project.pipeline_phase || project.status)) || (operation && operation.status) || "").toLowerCase();
      const active = operationIsActive(operation) || (project && (isPipelineActive(project) || ["pending", "running", "in_progress", "retrying"].includes(String(project.status || "").toLowerCase())));
      const statusLabel = active ? "执行中" : ["failed", "error"].includes(status) ? "失败" : ["paused", "pausing"].includes(status) ? "已暂停" : "已完成";
      const typeLabel = project
        ? "专业剧本团队"
        : operation && operation.type === "word_optimization" ? "Word 优化" : "剧本医生";
      return `
        <button type="button" class="${record.identity === selectedIdentity ? "is-active" : ""}" data-task-history-id="${escapeHtml(record.identity)}" title="查看 ${escapeHtml(title)} 的任务轨道">
          <i class="${active ? "is-running" : statusLabel === "失败" ? "is-failed" : "is-done"}"></i>
          <span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(typeLabel)} · ${escapeHtml(statusLabel)}</small></span>
        </button>`;
    }).join("");
  }

  function renderLiveExecution() {
    const container = $("#agentLiveExecution");
    if (!container) return;
    const project = state.context && state.context.current_project ? state.context.current_project : null;
    const operation = currentBackgroundOperation();
    const activeOperation = operationIsActive(operation) ? operation : null;
    if (activeOperation && ["script_doctor", "word_optimization"].includes(activeOperation.type)) {
      const optimizingWord = activeOperation.type === "word_optimization";
      const stageOrder = optimizingWord
        ? ["preparing", "ai_optimize", "saving", "completed"]
        : ["preparing", "ai_review", "saving", "completed"];
      const activeIndex = Math.max(0, stageOrder.indexOf(String(activeOperation.stage || "preparing")));
      const labels = optimizingWord
        ? ["读取原文", "AI优化", "生成Word", "完成"]
        : ["读取Word", "AI审查", "保存报告", "完成"];
      container.hidden = false;
      container.innerHTML = `
        <div class="agent-live-icon" aria-hidden="true"><i></i></div>
        <div class="agent-live-main">
          <strong>${escapeHtml(activeOperation.message || "AI剧本医生正在审查")}</strong>
          <p>${escapeHtml(activeOperation.filename || "上传剧本")} · ${escapeHtml(optimizingWord ? "一键优化 Word" : (activeOperation.skill_name || "剧本医生"))} · 刷新页面不会中止</p>
          <div class="agent-live-track"><i style="width:${Math.max(12, Number(activeOperation.progress_percent || 20))}%"></i></div>
          <div class="agent-live-stages is-doctor">${labels.map((label, index) => `<span class="${index < activeIndex ? "is-done" : index === activeIndex ? "is-active" : ""}">${escapeHtml(label)}</span>`).join("")}</div>
        </div>
        <b>${escapeHtml(operationElapsed(activeOperation))}</b>`;
      return;
    }
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
      ? `${project.title || "剧本项目"} · ${project.execution_scope === "framework_only"
        ? "专业剧本团队 · 策划四节点"
        : "专业剧本团队 · 七节点"}`
      : "正在连接剧本创作平台";
    const stageCount = 7;
    const chips = Array.from({ length: stageCount }, (_, index) => {
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

  function renderTaskRail(project, operation = null) {
    const rail = $("#agentTaskRail");
    const idle = $("#agentTaskIdle");
    const waitingActions = $("#agentWaitingActions");
    if (!rail || !idle || !waitingActions) return;
    const doctorOperation = operation && ["script_doctor", "word_optimization"].includes(operation.type) ? operation : null;
    rail.classList.toggle("is-doctor-task", Boolean(doctorOperation));
    const visible = Boolean(doctorOperation) || isPipelineProject(project);
    rail.hidden = !visible;
    idle.hidden = visible;
    waitingActions.hidden = !visible;
    if (!visible) return;

    if (doctorOperation) {
      const running = operationIsActive(doctorOperation);
      const completed = doctorOperation.status === "completed";
      const failed = doctorOperation.status === "failed";
      const optimizingWord = doctorOperation.type === "word_optimization";
      const stageIndex = running
        ? (["ai_review", "ai_optimize"].includes(doctorOperation.stage) ? 3 : doctorOperation.stage === "saving" ? 4 : 1)
        : 4;
      const stages = optimizingWord
        ? ["读取原始 Word", "加载剧本医生报告", "剧本 Agent 生成修改方案", "校验修改并生成 Word"]
        : ["读取 Word 剧本", `加载 ${doctorOperation.skill_name || "剧本医生 Skill"}`, "剧本 Agent 深度审查", "保存审查报告"];
      $("#taskStageList").innerHTML = stages.map((name, index) => {
        const number = index + 1;
        const done = completed || number < stageIndex;
        const active = running && number === stageIndex;
        const className = done ? "is-done" : active ? "is-active" : failed && number === stageIndex ? "is-active is-failed" : "";
        const stateText = done ? "已完成" : active ? "执行中" : failed && number === stageIndex ? "失败" : "等待";
        return `<li class="agent-stage-item ${className}"><div class="agent-stage-static"><span class="agent-stage-number">${String(number).padStart(2, "0")}</span><span class="agent-stage-name">${escapeHtml(name)}</span><span class="agent-stage-state">${stateText}</span></div></li>`;
      }).join("");
      $("#contextOpenProject").href = optimizingWord && completed && doctorOperation.download_url
        ? withAuth(doctorOperation.download_url)
        : withAuth("/workbuddy-studio");
      $("#contextOpenProject").textContent = optimizingWord
        ? (completed ? "查看并下载优化版 Word" : "打开剧本医生工作台")
        : (completed ? "打开剧本医生报告" : "打开剧本医生工作台");
      waitingActions.hidden = true;
      return;
    }

    const stage = pipelineStageIndex(project);
    const phase = String(project.pipeline_phase || "").toLowerCase();
    const completed = phase === "completed" || String(project.status || "").toLowerCase() === "completed";
    const failed = phase === "failed" || String(project.status || "").toLowerCase() === "failed";
    const jobId = project.job_id || project.task_id || "";
    $("#taskStageList").innerHTML = SCRIPT_TEAM_STAGES.map(([number, name]) => {
      const numeric = Number(number);
      const done = completed ? numeric <= 7 : numeric < stage;
      const active = !completed && numeric === stage;
      const stateText = done ? "已完成" : active ? (failed ? "失败" : "执行中") : "等待";
      const className = done ? "is-done" : active ? (failed ? "is-active is-failed" : "is-active") : "";
      const inner = `
        <span class="agent-stage-number">${number}</span>
        <span class="agent-stage-name">${escapeHtml(name)}</span>
        <span class="agent-stage-state">${stateText}</span>`;
      return `<li class="agent-stage-item ${className}"><a class="agent-stage-link" href="${escapeHtml(withAuth("/new-workflow-test"))}" title="打开专业剧本团队任务 ${escapeHtml(jobId)}">${inner}</a></li>`;
    }).join("");
    $("#contextOpenProject").href = withAuth(project.workspace_url || "/new-workflow-test");
    $("#contextOpenProject").textContent = completed ? "查看并下载最终剧本" : "打开专业剧本团队";
  }

  function syncTaskPanelVisibility(project, operation = null) {
    const shell = $(".agent-shell");
    const toggle = $("#taskPanelToggle");
    if (!shell || !toggle) return;
    const projectId = String(project && (project.job_id || project.task_id) || "");
    const active = isPipelineActive(project) || operationIsActive(operation);
    const taskIdentity = operationIsActive(operation) ? String(operation.request_id || "doctor") : projectId;
    if (active && taskIdentity && state.taskPanelProjectId !== taskIdentity) {
      state.taskPanelProjectId = taskIdentity;
      state.selectedTaskIdentity = operationIsActive(operation)
        ? `operation:${taskIdentity}`
        : `script_team:${taskIdentity}`;
      state.taskPanelOpen = true;
    }
    const open = state.taskPanelOpen === null ? active : state.taskPanelOpen;
    shell.classList.toggle("is-task-panel-collapsed", !open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "收起任务" : "任务";
  }

  function renderContext() {
    const currentProject = state.context && state.context.current_project ? state.context.current_project : null;
    const currentOperation = currentBackgroundOperation();
    syncTaskPanelVisibility(currentProject, currentOperation);
    const records = taskHistoryRecords();
    if (!records.some((record) => record.identity === state.selectedTaskIdentity)) {
      const preferredIdentity = operationIsActive(currentOperation)
        ? `operation:${currentOperation.request_id || ""}`
        : currentProject
          ? `script_team:${currentProject.job_id || currentProject.task_id || ""}`
          : records.length ? records[records.length - 1].identity : "";
      state.selectedTaskIdentity = preferredIdentity;
    }
    const selectedRecord = records.find((record) => record.identity === state.selectedTaskIdentity) || null;
    const project = selectedRecord && selectedRecord.kind === "script_team" ? selectedRecord.project : (!selectedRecord ? currentProject : null);
    const operation = selectedRecord && selectedRecord.kind === "operation" ? selectedRecord.operation : (!selectedRecord ? currentOperation : null);
    renderTaskHistory(records, state.selectedTaskIdentity);
    if (operation && ["script_doctor", "word_optimization"].includes(operation.type)) {
      const progress = Math.max(0, Math.min(100, Number(operation.progress_percent || 0)));
      $("#contextProjectTitle").textContent = operation.filename || "上传剧本";
      $("#contextProjectMeta").textContent = `${operation.type === "word_optimization" ? "一键优化 Word" : (operation.skill_name || "剧本医生")} · ${Number(operation.char_count || 0).toLocaleString("zh-CN")} 字`;
      $("#contextStage").textContent = operation.message || (operation.status === "completed" ? "审查完成" : "正在审查");
      $("#contextProgress").textContent = operation.status === "running" ? operationElapsed(operation) : operation.status === "completed" ? "完成" : "失败";
      $("#contextProgressBar").style.width = `${progress}%`;
      renderTaskRail(project, operation);
      renderLiveExecution();
      return;
    }
    if (!project) {
      $("#contextProjectTitle").textContent = "尚未选择项目";
      $("#contextProjectMeta").textContent = "通过对话创建或选择项目";
      $("#contextStage").textContent = "等待指令";
      $("#contextProgress").textContent = "0%";
      $("#contextProgressBar").style.width = "0%";
      renderTaskRail(null, null);
      renderLiveExecution();
      return;
    }
    const progress = pipelineProgress(project);
    $("#contextProjectTitle").textContent = project.title || "未命名项目";
    $("#contextProjectMeta").textContent = project.message || `任务 ${project.job_id || project.task_id || ""}`;
    $("#contextStage").textContent = userFacingText(project.pipeline_message || project.current_stage_label || project.current_stage || project.status || "等待");
    $("#contextProgress").textContent = `${progress}%`;
    $("#contextProgressBar").style.width = `${progress}%`;
    $("#contextOpenProject").href = withAuth(project.workspace_url || "/new-workflow-test");
    $("#contextOpenProject").textContent = "打开专业剧本团队";
    renderTaskRail(project, null);
    renderLiveExecution();
  }

  function setSending(value) {
    state.sending = Boolean(value);
    $("#agentSendBtn").disabled = state.sending;
    $("#agentInput").disabled = state.sending;
    $("#agentThinking").hidden = !state.sending;
    renderLiveExecution();
  }

  function selectedSkillRecord() {
    return state.doctorSkills.find((item) => item.key === state.selectedSkill) || null;
  }

  const SKILL_VISUALS = {
    overall_dispatcher: { tone: "ocean", icon: "总检" },
    character_continuity: { tone: "mint", icon: "人物" },
    hook_rhythm: { tone: "sunset", icon: "节奏" },
    logic_holes: { tone: "indigo", icon: "逻辑" },
    character_humanity: { tone: "coral", icon: "共鸣" },
  };

  function skillVisual(skill) {
    return SKILL_VISUALS[String(skill && skill.key || "")] || {
      tone: "ocean",
      icon: String(skill && (skill.short_name || skill.name) || "技能").slice(0, 2),
    };
  }

  function selectedKnowledgeTags() {
    const selected = new Set(state.selectedKnowledgeTagIds.map(String));
    return state.knowledgeTags.filter((tag) => selected.has(String(tag.skill_id || "")));
  }

  function knowledgeTagById(tagId) {
    return state.knowledgeTags.find((tag) => String(tag.skill_id || "") === String(tagId || "")) || null;
  }

  function knowledgeOption(tag) {
    const id = String(tag.skill_id || "");
    const checked = state.selectedKnowledgeTagIds.map(String).includes(id);
    return `
      <label class="agent-distilled-card ${checked ? "is-selected" : ""}">
        <input type="checkbox" data-knowledge-tag-id="${escapeHtml(id)}" ${checked ? "checked" : ""}>
        <img src="${escapeHtml(withAuth(tag.cover_url || ""))}" alt="" loading="lazy">
        <span class="agent-distilled-card-shade"></span>
        <span class="agent-distilled-check" aria-hidden="true">${checked ? "✓" : "+"}</span>
        <span class="agent-distilled-copy">
          <small>${escapeHtml(tag.genre || "垂类剧本")} · ${escapeHtml(tag.market || "通用市场")}</small>
          <strong>${escapeHtml(tag.name || id)}</strong>
          <span><b>${escapeHtml(tag.version || "")}</b><i>${escapeHtml(tag.module_count || 0)} 个创作模块</i><em>${escapeHtml(tag.score || 0)} 分</em></span>
        </span>
      </label>`;
  }

  function renderKnowledgeMain(query) {
    const skills = state.knowledgeTags.filter((tag) => !query || [tag.name, tag.genre, tag.market, tag.description].some((v) => String(v || "").toLowerCase().includes(query)));
    return `
      <div class="agent-distilled-grid">
        <label class="agent-distilled-card is-base ${state.selectedKnowledgeTagIds.length ? "" : "is-selected"}">
          <input type="checkbox" data-knowledge-tag-id="" ${state.selectedKnowledgeTagIds.length ? "" : "checked"}>
          <span class="agent-distilled-base-art">ITS</span>
          <span class="agent-distilled-check" aria-hidden="true">${state.selectedKnowledgeTagIds.length ? "+" : "✓"}</span>
          <span class="agent-distilled-copy"><small>通用 · 七节点团队</small><strong>基础专业工作流</strong><span><b>稳定版</b><i>不套用垂类样本架构</i></span></span>
        </label>
        ${skills.map((tag) => knowledgeOption(tag)).join("")}
        ${!skills.length ? `<a class="agent-distilled-empty" href="${escapeHtml(withAuth('/distillation-lab'))}"><strong>还没有匹配的已发布 Skill</strong><small>前往爆款蒸馏实验室创建并发布</small></a>` : ""}
      </div>`;
  }

  function renderKnowledgeButton() {
    const tags = selectedKnowledgeTags();
    $("#knowledgeSelectionLabel").textContent = tags.length
      ? `${tags[0].name} · ${tags[0].version || "已发布"}`
      : "使用基础专业工作流";
    $("#knowledgePickerBtn").classList.toggle("has-selection", tags.length > 0);
    $("#knowledgeSelectedCount").textContent = tags.length ? `已锁定 ${tags[0].name} · ${tags[0].version}` : "未选择垂类 Skill";
  }

  function renderKnowledgePicker() {
    const query = String($("#knowledgeSearchInput")?.value || "").trim().toLowerCase();
    $("#knowledgePickerStatus").textContent = state.knowledgeTags.length
      ? `${state.knowledgeTags.length} 个已发布 Skill；每次创作只能锁定一个版本。`
      : "暂无已发布 Skill，可继续使用基础专业工作流。";
    $("#knowledgeTagGroups").innerHTML = renderKnowledgeMain(query);
    renderKnowledgeButton();
  }

  async function loadKnowledgeLibrary() {
    try {
      const data = await fetchJson("/api/new-workflow-test/skills");
      state.knowledgeTags = Array.isArray(data.skills) ? data.skills : [];
      const savedId = String(window.localStorage.getItem("agentDistilledSkillId") || "");
      const savedVersionId = String(window.localStorage.getItem("agentDistilledSkillVersionId") || "");
      const saved = state.knowledgeTags.find((item) => String(item.skill_id || "") === savedId && String(item.version_id || "") === savedVersionId);
      state.selectedKnowledgeTagIds = saved ? [savedId] : [];
    } catch (error) {
      state.knowledgeTags = [];
      $("#knowledgePickerStatus").textContent = error.message || "爆款蒸馏库加载失败";
    }
    renderKnowledgePicker();
  }

  async function saveKnowledgeSelection() {
    if (state.knowledgeSaving) return;
    state.knowledgeSaving = true;
    const button = $("#knowledgeApplyBtn");
    button.disabled = true;
    button.textContent = "正在锁定…";
    try {
      const skill = selectedKnowledgeTags()[0] || null;
      if (skill) {
        window.localStorage.setItem("agentDistilledSkillId", String(skill.skill_id || ""));
        window.localStorage.setItem("agentDistilledSkillVersionId", String(skill.version_id || ""));
      } else {
        window.localStorage.removeItem("agentDistilledSkillId");
        window.localStorage.removeItem("agentDistilledSkillVersionId");
      }
      state.distilledSkillLocked = true;
      renderKnowledgePicker();
    } catch (error) {
      $("#knowledgePickerStatus").textContent = error.message || "Skill 锁定失败";
    } finally {
      state.knowledgeSaving = false;
      button.disabled = false;
      button.textContent = "锁定到本次创作";
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
      ? `${Number(attachment.char_count || 0).toLocaleString("zh-CN")} 字 · 已保存，尚未分析`
      : "";
    $("#agentInput").placeholder = attachment
      ? "文件已上传。请明确用途：分析框架、生成完整剧本、续写，或运行剧本医生…"
      : "描述你想生成的剧本，或说：继续、暂停、重试第10阶段、运行人物共鸣审查…";
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
        body: JSON.stringify({
          background: true,
          conversation_id: state.currentConversationId,
        }),
      });
      if (data.accepted) {
        button.textContent = data.already_running ? "优化任务运行中" : "后台优化已开始";
        state.context = data.context || state.context;
        renderContext();
        schedulePoll();
        return;
      }
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
    state.selectedTaskIdentity = "";
    state.taskPanelProjectId = "";
    $("#conversationTitle").textContent = conversation.title || "新的创作对话";
    renderConversations();
    renderMessages();
    renderContext();
    $("#agentInput").focus();
  }

  async function openConversation(conversationId, { silent = false } = {}) {
    if (!conversationId) return;
    const changedConversation = state.currentConversationId !== conversationId;
    const data = await fetchJson(`${config.conversationsUrl}/${encodeURIComponent(conversationId)}`);
    state.currentConversationId = conversationId;
    if (changedConversation) {
      state.selectedTaskIdentity = "";
      state.taskPanelProjectId = "";
    }
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
    const distilledSkill = attachedKnowledgeTags[0] || null;
    const optimistic = {
      id: `local-${Date.now()}`,
      role: "user",
      content,
      metadata: {
        ...(attachedSkill ? { selected_skill: attachedSkill.key, selected_skill_name: attachedSkill.name } : {}),
        ...(distilledSkill ? {
          distilled_skill_id: String(distilledSkill.skill_id || ""),
          distilled_skill_version_id: String(distilledSkill.version_id || ""),
          distilled_skill_name: String(distilledSkill.name || ""),
          distilled_skill_version: String(distilledSkill.version || ""),
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
          distilled_skill_id: distilledSkill ? String(distilledSkill.skill_id || "") : "",
          distilled_skill_version_id: distilledSkill ? String(distilledSkill.version_id || "") : "",
          selected_knowledge_tag_ids: [],
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
      const assistantEvents = data.assistant_message && data.assistant_message.metadata
        && Array.isArray(data.assistant_message.metadata.events)
        ? data.assistant_message.metadata.events
        : [];
      const isClarificationTurn = assistantEvents.some((event) => {
        const result = event && event.result && typeof event.result === "object" ? event.result : {};
        const ui = result.ui && typeof result.ui === "object" ? result.ui : {};
        return ui.kind === "choice";
      });
      if (attachedSkill && state.selectedSkill === attachedSkill.key && !isClarificationTurn) selectSkill("");
      // Keep the uploaded document selected during clarification turns. The user
      // can remove it explicitly after choosing framework analysis, generation,
      // continuation or doctor review.
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
    const operation = currentBackgroundOperation();
    const operationActive = operationIsActive(operation);
    const taskStatusActive = project && ["pending", "running", "in_progress", "pausing", "paused", "retrying"].includes(String(project.status || "").toLowerCase());
    if (!operationActive && (!project || (!taskStatusActive && !isPipelineActive(project)))) return;
    state.pollTimer = window.setInterval(() => {
      if (!state.sending && state.currentConversationId) openConversation(state.currentConversationId, { silent: true }).catch(() => {});
    }, 3000);
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
  $("#knowledgeTagGroups").addEventListener("change", (event) => {
    const checkbox = event.target.closest("input[data-knowledge-tag-id]");
    if (!checkbox) return;
    const id = String(checkbox.dataset.knowledgeTagId || "");
    state.selectedKnowledgeTagIds = checkbox.checked && id ? [id] : [];
    state.distilledSkillLocked = false;
    renderKnowledgePicker();
  });
  $("#knowledgeClearBtn").addEventListener("click", () => {
    state.selectedKnowledgeTagIds = [];
    state.distilledSkillLocked = false;
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
  $("#agentTaskHistoryList").addEventListener("click", (event) => {
    const button = event.target.closest("[data-task-history-id]");
    if (!button) return;
    state.selectedTaskIdentity = button.dataset.taskHistoryId || "";
    renderContext();
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
    const choiceButton = event.target.closest("[data-agent-choice]");
    if (choiceButton && !choiceButton.disabled) {
      const choiceCard = choiceButton.closest(".agent-choice-card");
      if (choiceCard) $$('button', choiceCard).forEach((button) => { button.disabled = true; });
      const prompt = choiceButton.dataset.agentChoice || "";
      if (prompt) sendMessage(prompt);
      return;
    }
    const promptButton = event.target.closest("[data-prompt], [data-agent-prompt]");
    if (!promptButton) return;
    const prompt = promptButton.dataset.prompt || promptButton.dataset.agentPrompt || "";
    if (prompt) sendMessage(prompt);
  });

  window.addEventListener("storage", (event) => {
    if (event.key === "distilledSkillCatalogChanged") loadKnowledgeLibrary();
  });

  Promise.all([loadStatus(), loadKnowledgeLibrary(), loadConversations()]).catch((error) => {
    state.messages = [{ role: "assistant", content: `Agent工作台初始化失败：${error.message}`, metadata: {}, created_at: new Date().toISOString() }];
    renderMessages();
  });
})();
